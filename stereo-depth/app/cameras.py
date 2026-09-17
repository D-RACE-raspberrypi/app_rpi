"""Two independent acquisition threads, bounded queues, timestamp pairing."""
from collections import deque
import threading
import time
import cv2
import numpy as np
from stereo import SIZE


class StereoCamera:
    def __init__(self, focus=1.0, swap=False):
        from picamera2 import Picamera2
        from libcamera import controls
        info = Picamera2.global_camera_info()
        if len(info) < 2:
            raise RuntimeError(f"{len(info)} caméra détectée. Deux caméras CSI sont nécessaires.")
        self.ids = [info[i]["Id"] for i in ([1, 0] if swap else [0, 1])]
        self.names = [info[i]["Model"] for i in ([1, 0] if swap else [0, 1])]
        self.condition = threading.Condition()
        self.queues = [deque(maxlen=5), deque(maxlen=5)]
        self.running = True
        self.error = None
        self.cameras = []
        self.threads = []
        self.sync = False
        try:
            for index in ([1, 0] if swap else [0, 1]):
                cam = Picamera2(index)
                self.cameras.append(cam)
                cfg = cam.create_video_configuration(main={"size": SIZE, "format": "RGB888"},
                                                       buffer_count=6, controls={"FrameRate": 30.0})
                cam.configure(cfg)
                if "AfMode" in cam.camera_controls:
                    cam.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": focus})
            self.sync = all("SyncMode" in cam.camera_controls for cam in self.cameras) and hasattr(controls, "rpi")
            if self.sync:
                self.cameras[0].set_controls({"SyncMode": controls.rpi.SyncModeEnum.Server})
                self.cameras[1].set_controls({"SyncMode": controls.rpi.SyncModeEnum.Client})
            self.cameras[1].start()
            self.cameras[0].start()
            for i in range(2):
                thread = threading.Thread(target=self._capture, args=(i,), daemon=True)
                thread.start(); self.threads.append(thread)
        except Exception:
            self.close()
            raise

    def _capture(self, i):
        try:
            while self.running:
                request = self.cameras[i].capture_request()
                try:
                    # Picamera2 RGB888 has B,G,R byte order, matching OpenCV.
                    frame = request.make_array("main").copy()
                    meta = request.get_metadata()
                finally:
                    request.release()
                timestamp = meta.get("SensorTimestamp")
                if timestamp is None:
                    raise RuntimeError("SensorTimestamp absent : appairage des images impossible.")
                with self.condition:
                    self.queues[i].append((timestamp, frame, meta))
                    self.condition.notify_all()
        except Exception as exc:
            if self.running:
                self.error = str(exc)
                with self.condition:
                    self.condition.notify_all()

    def read(self, timeout=3):
        deadline = time.monotonic() + timeout
        with self.condition:
            while time.monotonic() < deadline:
                if self.error:
                    raise RuntimeError(self.error)
                if all(self.queues):
                    # Match a recent frame against the nearest timestamp; discard stale frames.
                    pairs = [(abs(l[0]-r[0]), i, j) for i, l in enumerate(self.queues[0]) for j, r in enumerate(self.queues[1])]
                    delta, i, j = min(pairs, key=lambda p: (p[0], -(p[1]+p[2])))
                    if delta <= 20_000_000:
                        left, right = self.queues[0][i], self.queues[1][j]
                        for _ in range(i+1): self.queues[0].popleft()
                        for _ in range(j+1): self.queues[1].popleft()
                        return left[1], right[1], delta/1e6, [left[2], right[2]]
                    older = 0 if self.queues[0][0][0] < self.queues[1][0][0] else 1
                    self.queues[older].popleft()
                self.condition.wait(0.025)
        raise RuntimeError("Pas de paire d'images depuis 3 s. Vérifier les nappes et les autres applications caméra.")

    def set_focus(self, value):
        for cam in self.cameras:
            cam.set_controls({"LensPosition": value})

    def close(self):
        self.running = False
        for cam in self.cameras:
            try: cam.stop()
            except Exception: pass
        for thread in self.threads:
            thread.join(timeout=2)
        for cam in self.cameras:
            try: cam.close()
            except Exception: pass


class DemoCamera:
    """Explicitly labelled synthetic source for UI development only."""
    ids = ["demo-left", "demo-right"]
    names = ["Simulation", "Simulation"]
    sync = False

    def __init__(self, **kwargs):
        rng = np.random.default_rng(42)
        self.texture = cv2.GaussianBlur(rng.integers(30, 210, (480, 640, 3), dtype=np.uint8), (3, 3), 0)
        self.start = time.monotonic()

    def read(self, timeout=3):
        time.sleep(1/30)
        left = self.texture.copy()
        cv2.rectangle(left, (180, 100), (420, 360), (90, 145, 180), 4)
        cv2.putText(left, "SIMULATION", (190, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 245, 245), 2)
        right = np.roll(left, -16, axis=1)
        return left, right, 0.0, [{}, {}]

    def set_focus(self, value): pass
    def close(self): pass
