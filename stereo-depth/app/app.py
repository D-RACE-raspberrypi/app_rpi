#!/usr/bin/env python3
"""Stereo Studio — local Raspberry Pi stereo camera application."""
import argparse
import atexit
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import threading
import time
import zipfile
from urllib.parse import urlparse

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request, send_file
from cameras import StereoCamera, DemoCamera
from stereo import SIZE, BOARD, DepthSettings, DepthProcessor, detect_board, align_corners, calibrate, ideal_geometry
from following import Follower

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("stereo")


def atomic_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))
    tmp.replace(path)


def placeholder(title, subtitle=""): 
    frame = np.full((480, 640, 3), (25, 21, 18), np.uint8)
    for x in range(0, 640, 40): cv2.line(frame, (x, 0), (x, 480), (36, 31, 27), 1)
    for y in range(0, 480, 40): cv2.line(frame, (0, y), (640, y), (36, 31, 27), 1)
    cv2.putText(frame, title, (40, 225), cv2.FONT_HERSHEY_SIMPLEX, .8, (212, 225, 225), 1, cv2.LINE_AA)
    cv2.putText(frame, subtitle, (40, 265), cv2.FONT_HERSHEY_SIMPLEX, .45, (133, 155, 155), 1, cv2.LINE_AA)
    return frame


class Engine:
    def __init__(self, data_dir, demo=False):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        self.demo = demo
        self.follower = Follower(self.data)
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.capture_lock = threading.Lock()
        self.config = dict(focus=1.0, swap=False)
        self.settings = DepthSettings()
        self.trial = False
        self.rotate_display = True
        try:
            saved = json.loads((self.data / "settings.json").read_text())
            self.settings = DepthSettings.validated(saved["depth"])
            self.config.update(saved["camera"])
            self.trial = saved.get("trial") is True
            self.rotate_display = saved.get("rotate_display", True) is True
        except FileNotFoundError: pass
        except Exception: log.exception("Réglages ignorés")
        self.cal = self.report = self.processor = None
        self.version = 0
        self.samples = []
        self.sample_info = []
        self.square_mm = 25.0
        self.job = dict(state="idle", message="")
        self.camera = None
        self.running = False
        self.restart = False
        self.raw = None
        self.depth = None
        self.disparity = None
        self.images = {}
        self.sequence = 0
        self.last_frame = 0
        self.last_depth = 0
        self.status = dict(connected=False, error=None, fps=0, processing_ms=0, sync_ms=None,
                           sync_software=False, valid_percent=0, cameras=[], temperature=None)
        self.publish({"depth": placeholder("Calibration requise", "Ouvrir l'assistant pour commencer."),
                      "left": placeholder("Connexion camera..."), "right": placeholder("Connexion camera..."),
                      "rectified": placeholder("Calibration requise"), "alignment": placeholder("Calibration requise")})

    def save_settings(self):
        atomic_json(self.data / "settings.json", dict(depth=asdict(self.settings), camera=self.config,
                                                      trial=self.trial, rotate_display=self.rotate_display))

    def orient(self, image):
        """Orient display images AND matching pixel arrays; capture geometry stays unchanged."""
        return cv2.rotate(image, cv2.ROTATE_180) if self.rotate_display else image

    def effective_geometry(self):
        return ideal_geometry() if self.trial else self.cal

    def rebuild_processor(self):
        cal = self.effective_geometry()
        self.processor = DepthProcessor(cal, self.settings, trial=self.trial) if cal is not None else None
        self.depth = self.disparity = None
        self.last_depth = 0
        self.version += 1
        self.follower.invalidate()

    def load_calibration(self):
        with self.lock:
            self.cal = self.report = self.processor = None
            self.version += 1
            self.follower.invalidate()
        path = self.data / "calibration.npz"
        try:
            if not path.exists(): return
            with np.load(path, allow_pickle=False) as saved:
                report = json.loads(str(saved["report"]))
                if report["camera_ids"] != self.camera.ids or report["focus"] != self.config["focus"]:
                    self.job = dict(state="idle", message="Calibration sauvegardée incompatible avec l'ordre des caméras ou la mise au point.")
                    return
                cal = {k: saved[k] for k in ("K1", "K2", "D1", "D2", "R", "T")}
            processor = DepthProcessor(cal, self.settings)
            with self.lock:
                self.cal, self.report, self.processor = cal, report, processor
                self.version += 1
                self.follower.invalidate()
        except Exception: log.exception("Calibration sauvegardée ignorée")
        finally:
            with self.lock:
                self.rebuild_processor()

    def start(self):
        self.running = True
        self.follower.start()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.follower.stop()
        if hasattr(self, "thread"): self.thread.join(timeout=5)

    def publish(self, frames):
        encoded = {}
        for key, frame in frames.items():
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if ok: encoded[key] = jpeg.tobytes()
        with self.condition:
            self.images.update(encoded)
            self.sequence += 1
            self.condition.notify_all()

    def run(self):
        cv2.setNumThreads(3)
        previous = time.monotonic()
        try:
            while self.running:
                try:
                    if self.camera is None or self.restart:
                        if self.camera: self.camera.close()
                        self.camera = None
                        with self.lock:
                            config = self.config.copy()
                            self.restart = False
                        self.camera = (DemoCamera if self.demo else StereoCamera)(**config)
                        self.load_calibration()
                        with self.lock:
                            self.status.update(cameras=self.camera.names, sync_software=self.camera.sync)
                    left, right, delta, metadata = self.camera.read()
                    started = time.monotonic()
                    with self.lock:
                        self.raw = (left, right, delta)
                        self.last_frame = started
                        processor, version, trial = self.processor, self.version, self.trial
                    frames = dict(left=self.orient(left), right=self.orient(right))
                    tracking_image = frames['left']
                    projection = ideal_geometry()['K1']
                    rotation = np.eye(3)
                    depth = disparity = None
                    range_depth = None
                    valid = 0.0
                    if processor:
                        l, r, color, depth, disparity, valid = processor.process(left, right)
                        l, r, color, depth, disparity = [self.orient(v) for v in (l,r,color,depth,disparity)]
                        range_depth = self.orient(processor.range_depth)
                        tracking_image = l
                        projection = getattr(processor, 'left_projection', projection)
                        rotation = getattr(processor, 'left_rotation', rotation)
                        if trial:
                            cv2.rectangle(color, (0, 0), (color.shape[1], 27), (25, 21, 18), -1)
                            cv2.putText(color, "ESSAI - DISTANCES APPROXIMATIVES", (8, 19),
                                        cv2.FONT_HERSHEY_SIMPLEX, .43, (120, 210, 245), 1, cv2.LINE_AA)
                        frames["depth"] = color
                        rect = np.hstack((l, r))
                        for y in range(24, rect.shape[0], 40):
                            cv2.line(rect, (0, y), (rect.shape[1], y), (143, 229, 75), 1)
                        frames["rectified"] = rect
                        # Fixed reference in green; corrected right in magenta.
                        lg, rg = [cv2.cvtColor(v, cv2.COLOR_BGR2GRAY) for v in (l,r)]
                        frames["alignment"] = cv2.merge((rg,lg,rg))
                    else:
                        frames["depth"] = placeholder("Calibration requise", "La profondeur metrique sera disponible apres calibration.")
                        frames["rectified"] = frames["alignment"] = placeholder("Calibration requise")
                    now = time.monotonic()
                    fps = 1 / max(now-previous, 0.001)
                    previous = now
                    with self.lock:
                        if version != self.version or self.restart: continue
                        self.depth, self.disparity = depth, disparity
                        self.last_depth = started if depth is not None else 0
                        self.status.update(connected=True, error=None, fps=round(.85*self.status["fps"]+.15*fps, 1),
                                           processing_ms=round((now-started)*1000, 1), sync_ms=round(delta, 2),
                                           valid_percent=round(valid, 1),
                                           exposure_us=metadata[0].get("ExposureTime"))
                        self.publish(frames)
                        self.images['tracking'] = cv2.imencode('.jpg', tracking_image)[1].tobytes()
                        self.follower.submit(tracking_image, range_depth, projection, rotation, self.rotate_display,
                                             trial or processor is None, started, version, far=processor.settings.far if processor else 4.)
                except Exception as exc:
                    log.exception("Acquisition")
                    self.follower.invalidate()
                    with self.lock:
                        self.status.update(connected=False, error=str(exc), fps=0, valid_percent=0)
                        self.raw = self.depth = self.disparity = None
                        self.last_frame = 0
                    self.publish({k: placeholder("Camera indisponible", "Reconnexion automatique en cours...") for k in ("left", "right", "depth", "rectified", "alignment")})
                    if self.camera: self.camera.close()
                    self.camera = None
                    for _ in range(30):
                        if not self.running: break
                        time.sleep(.1)
        finally:
            if self.camera: self.camera.close()

    def snapshot(self):
        with self.lock:
            status = dict(self.status)
            age = time.monotonic()-self.last_frame if self.last_frame else None
            status["frame_age_s"] = round(age, 2) if age is not None else None
            if age is None or age > 3:
                status["connected"] = False
            try:
                status["temperature"] = round(float(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
            except (OSError, ValueError): pass
            return dict(**status, demo=self.demo, calibrated=self.cal is not None and not self.trial,
                        trial=self.trial, display_rotation_deg=180 if self.rotate_display else 0,
                        depth_enabled=self.processor is not None, calibration=self.report,
                        settings=asdict(self.settings), camera=self.config, samples=list(self.sample_info),
                        sample_count=len(self.samples), square_mm=self.square_mm, job=dict(self.job),
                        size=list(self.processor.size if self.processor else SIZE),
                        wls_available=hasattr(cv2, "ximgproc"))

    def capture_sample(self, square_mm):
        if not self.capture_lock.acquire(blocking=False):
            raise ValueError("Une capture est déjà en cours.")
        try:
            with self.lock:
                if self.job["state"] == "running": raise ValueError("Calibration en cours.")
                if self.demo: raise ValueError("La simulation ne permet pas de calibrer des caméras réelles.")
                if not np.isfinite(square_mm) or not 5 <= square_mm <= 100: raise ValueError("Taille de case : 5 à 100 mm.")
                if self.samples and square_mm != self.square_mm: raise ValueError("Vider les captures avant de changer la taille des cases.")
                if len(self.samples) >= 40: raise ValueError("40 captures maximum. Calculer la calibration ou vider la série.")
                if self.raw is None or time.monotonic()-self.last_frame > 1: raise ValueError("Attendre les images des deux caméras.")
                left, right, delta = self.raw
                version = self.version
                if delta > 8: raise ValueError("Décalage temporel > 8 ms : attendre la synchronisation des caméras.")
            a, b = detect_board(left), detect_board(right)
            if a is None or b is None:
                missing = "gauche et droite" if a is None and b is None else ("gauche" if a is None else "droite")
                raise ValueError(f"Damier 9 × 6 coins non détecté côté {missing}. Montrer les 10 × 7 cases entières, sans flou ni reflet.")
            a, b = align_corners(a, b)
            hull_area = cv2.contourArea(cv2.convexHull(a)) / (SIZE[0]*SIZE[1])
            if hull_area < .025: raise ValueError("Damier trop petit dans l'image. Le rapprocher.")
            with self.lock:
                if version != self.version: raise ValueError("La configuration a changé pendant la capture. Recommencer.")
                if self.job["state"] == "running": raise ValueError("Calibration en cours.")
                if any(float(np.linalg.norm(a-prev[0], axis=2).mean()) < 12 for prev in self.samples):
                    raise ValueError("Vue trop proche d'une capture existante. Déplacer ou incliner le damier.")
                self.square_mm = square_mm
                self.samples.append((a, b))
                index = len(self.samples)
                folder = self.data / "captures"
                folder.mkdir(exist_ok=True)
                cv2.imwrite(str(folder / f"{index:02d}-left.png"), left)
                cv2.imwrite(str(folder / f"{index:02d}-right.png"), right)
                thumb = left.copy()
                cv2.drawChessboardCorners(thumb, BOARD, a, True)
                cv2.imwrite(str(folder / f"{index:02d}-thumb.jpg"), cv2.resize(thumb, (240, 180)))
                info = dict(index=index, center=(a.mean(axis=0).ravel()/np.array(SIZE)).tolist(),
                            area_percent=round(hull_area*100, 1), sync_ms=round(delta, 2))
                self.sample_info.append(info)
                np.savez_compressed(self.data / "capture-points.npz", left=np.array([s[0] for s in self.samples]),
                                    right=np.array([s[1] for s in self.samples]), square_mm=square_mm)
            return info
        finally:
            self.capture_lock.release()

    def solve(self):
        with self.lock:
            if self.job["state"] == "running": raise ValueError("Calibration déjà en cours.")
            if len(self.samples) < 12: raise ValueError("Il faut au moins 12 captures différentes.")
            if self.camera is None or not self.status["connected"]:
                raise ValueError("Attendre la reconnexion des caméras avant le calcul.")
            samples, square, version = list(self.samples), self.square_mm, self.version
            ids, focus = list(self.camera.ids), self.config["focus"]
            self.job = dict(state="running", message="Calcul des optiques, de la pose et de la rectification…")
        def task():
            try:
                cal, report = calibrate(samples, square)
                report.update(created_at=datetime.now(timezone.utc).isoformat(), camera_ids=ids, focus=focus,
                              image_size=list(SIZE), model="pinhole + distorsion radiale/tangentielle", demo=self.demo)
                with self.lock:
                    if version != self.version: raise ValueError("Configuration modifiée pendant la calibration.")
                    clean = DepthSettings(**{**asdict(self.settings), **{k: 0.0 for k in ("tx", "ty", "tz", "rx", "ry", "rz")}})
                    processor = DepthProcessor(cal, clean)
                    path = self.data / "calibration.npz"
                    if path.exists():
                        archive = self.data / "history"
                        archive.mkdir(exist_ok=True)
                        (archive / f"calibration-{time.time_ns()}.npz").write_bytes(path.read_bytes())
                    with open(self.data / "calibration.tmp", "wb") as out:
                        np.savez_compressed(out, **cal, report=json.dumps(report))
                    (self.data / "calibration.tmp").replace(path)
                    self.cal, self.report, self.processor, self.settings = cal, report, processor, clean
                    self.trial = False
                    self.depth = self.disparity = None
                    self.version += 1
                    self.follower.invalidate()
                    self.save_settings()
                    self.job = dict(state="done", message="Calibration sauvegardée. La profondeur est active.")
            except Exception as exc:
                log.exception("Calibration")
                with self.lock: self.job = dict(state="error", message=str(exc))
        threading.Thread(target=task, daemon=True).start()


def create_app(engine):
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    @app.before_request
    def same_origin():
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc != request.host:
                return jsonify(error="Origine non autorisée."), 403
            if not request.is_json: return jsonify(error="Corps JSON requis."), 415

    @app.errorhandler(ValueError)
    def invalid(exc): return jsonify(error=str(exc)), 400

    @app.get("/")
    def index(): return app.send_static_file("index.html")

    @app.get("/api/status")
    def status(): return jsonify(engine.snapshot())

    @app.get('/api/following')
    def following():
        result = engine.follower.snapshot()
        if result['image'] is None:
            with engine.lock:
                jpeg = engine.images.get('tracking', engine.images.get('left'))
                result['image'] = base64.b64encode(jpeg).decode() if jpeg else None
        return jsonify(result)

    @app.post('/api/following/settings')
    def following_settings():
        values = request.get_json()
        if not isinstance(values, dict): raise ValueError('Objet JSON requis.')
        engine.follower.configure(values)
        return jsonify(ok=True)

    @app.post('/api/following/select')
    def following_select():
        values = request.get_json()
        if not isinstance(values, dict) or set(values) != {'id', 'generation'}: raise ValueError('id et generation requis.')
        engine.follower.select(values['id'], values['generation'])
        return jsonify(ok=True)

    @app.get("/stream/<view>")
    def stream(view):
        if view not in ("left", "right", "depth", "rectified", "alignment"): return "Not found", 404
        def frames():
            seq = -1
            while True:
                with engine.condition:
                    engine.condition.wait_for(lambda: engine.sequence != seq, timeout=3)
                    seq = engine.sequence
                    frame = engine.images[view]
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
                time.sleep(0.025)
        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame",
                        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/settings")
    def settings():
        values = request.get_json()
        if not isinstance(values, dict): raise ValueError("Objet JSON requis.")
        with engine.lock:
            if engine.job["state"] == "running": raise ValueError("Attendre la fin de la calibration.")
            updated = DepthSettings.validated({**asdict(engine.settings), **values})
            cal = engine.effective_geometry()
            processor = DepthProcessor(cal, updated, trial=engine.trial) if cal is not None else None
            engine.settings, engine.processor = updated, processor
            engine.version += 1
            engine.follower.invalidate()
            engine.depth = engine.disparity = None
            engine.save_settings()
        return jsonify(ok=True)

    @app.post("/api/trial")
    def trial_mode():
        values = request.get_json()
        if not isinstance(values, dict) or set(values) != {"enabled"} or not isinstance(values["enabled"], bool):
            raise ValueError("Le champ enabled doit être un booléen.")
        with engine.lock:
            if engine.job["state"] == "running": raise ValueError("Attendre la fin de la calibration.")
            enabled = values["enabled"]
            cal = ideal_geometry() if enabled else engine.cal
            processor = DepthProcessor(cal, engine.settings, trial=enabled) if cal is not None else None
            engine.trial, engine.processor = enabled, processor
            engine.depth = engine.disparity = None
            engine.last_depth = 0
            engine.version += 1
            engine.follower.invalidate()
            engine.status["valid_percent"] = 0
            engine.publish({"depth": placeholder("Essai sans calibration" if enabled else "Changement de mode..."),
                            "rectified": placeholder("Changement de mode..."), "alignment": placeholder("Changement de mode...")})
            engine.save_settings()
        return jsonify(ok=True)

    @app.post("/api/camera")
    def camera():
        values = request.get_json()
        if not isinstance(values, dict) or set(values) != {"focus", "swap"}: raise ValueError("Réglages caméra invalides.")
        focus, swap = values["focus"], values["swap"]
        if isinstance(focus, bool) or not isinstance(focus, (int, float)) or not np.isfinite(focus) or not 0 <= focus <= 10 or not isinstance(swap, bool):
            raise ValueError("Mise au point de 0 à 10 dioptries et ordre G/D booléen requis.")
        with engine.capture_lock, engine.lock:
            if engine.job["state"] == "running": raise ValueError("Attendre la fin du calcul.")
            if engine.samples: raise ValueError("Vider la série de captures avant de modifier les caméras.")
            engine.config = dict(focus=float(focus), swap=swap)
            engine.cal = engine.report = engine.processor = None
            engine.raw = engine.depth = engine.disparity = None
            engine.version += 1
            engine.follower.invalidate()
            engine.restart = True
            engine.status["connected"] = False
            engine.save_settings()
        return jsonify(ok=True)

    @app.post("/api/calibration/capture")
    def capture():
        values = request.get_json()
        if not isinstance(values, dict): raise ValueError("Objet JSON requis.")
        try: square = float(values.get("square_mm", 25))
        except (TypeError, ValueError): raise ValueError("Taille de case invalide.")
        return jsonify(ok=True, sample=engine.capture_sample(square))

    @app.post("/api/calibration/clear")
    def clear():
        with engine.capture_lock, engine.lock:
            if engine.job["state"] == "running": raise ValueError("Attendre la fin du calcul.")
            engine.samples.clear(); engine.sample_info.clear()
            engine.job = dict(state="idle", message="Nouvelle série prête. La calibration active est conservée.")
            engine.version += 1
            engine.follower.invalidate()
        return jsonify(ok=True)

    @app.post("/api/calibration/solve")
    def solve():
        engine.solve()
        return jsonify(ok=True), 202

    @app.get("/api/calibration/thumb/<int:index>")
    def thumb(index):
        if index < 1 or index > len(engine.samples): return "Not found", 404
        path = engine.data / "captures" / f"{index:02d}-thumb.jpg"
        if not engine.rotate_display: return send_file(path, max_age=0)
        thumbnail = engine.orient(cv2.imread(str(path)))
        _, jpeg = cv2.imencode(".jpg", thumbnail)
        return Response(jpeg.tobytes(), mimetype="image/jpeg", headers={"Cache-Control":"no-store"})

    @app.get("/api/calibration/export")
    def export_calibration():
        with engine.lock:
            if engine.cal is None: raise ValueError("Aucune calibration active.")
            data = dict(report=engine.report, matrices={k: v.tolist() for k, v in engine.cal.items()},
                        corrections=asdict(engine.settings), translation_unit="metre",
                        calibration_image_orientation="unrotated capture",
                        display_rotation_deg=180 if engine.rotate_display else 0)
        return Response(json.dumps(data, indent=2, ensure_ascii=False), mimetype="application/json",
                        headers={"Content-Disposition": 'attachment; filename="stereo-calibration.json"'})

    @app.get("/api/measure")
    def measure():
        try: x, y = float(request.args["x"]), float(request.args["y"])
        except (KeyError, ValueError): raise ValueError("Coordonnées invalides.")
        if not np.isfinite([x, y]).all() or not 0 <= x <= 1 or not 0 <= y <= 1: raise ValueError("Coordonnées hors image.")
        with engine.lock:
            if engine.depth is None or time.monotonic()-engine.last_depth > 1: raise ValueError("Aucune profondeur récente disponible.")
            h, w = engine.depth.shape
            ix, iy = min(w-1, int(x*w)), min(h-1, int(y*h))
            region = engine.depth[max(0, iy-3):min(h, iy+4), max(0, ix-3):min(w, ix+4)]
            values = region[np.isfinite(region)]
            approximate = engine.trial
        return jsonify(distance_m=round(float(np.median(values)), 3) if len(values) >= 5 else None,
                       approximate=approximate,
                       valid_pixels=len(values), method="Médiane locale 7 × 7 ; profondeur Z dans le repère rectifié gauche")

    @app.get("/api/snapshot")
    def snapshot():
        with engine.lock:
            if engine.depth is None or time.monotonic()-engine.last_depth > 1: raise ValueError("Calibrer et attendre une carte de profondeur récente.")
            depth, disparity = engine.depth.copy(), engine.disparity.copy()
            images = dict(engine.images)
            report = dict(engine.report) if engine.report and not engine.trial else None
            approximate = engine.trial
            assumptions = dict(baseline_mm=65, focal_px=500, image_size=list(SIZE),
                               parallel_axes=True, distortion="assumed zero",
                               manual_reference="unwarped left", right_image_homography=engine.processor.trial_transform.tolist(),
                               metric_scale_valid=False) if approximate else None
            settings = asdict(engine.settings)
            display_rotation_deg = 180 if engine.rotate_display else 0
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            array = io.BytesIO(); np.save(array, depth); archive.writestr("depth-metres.npy", array.getvalue())
            array = io.BytesIO(); np.save(array, disparity); archive.writestr("disparity-pixels.npy", array.getvalue())
            millimetres = np.clip(np.nan_to_num(depth, nan=0)*1000, 0, 65535).astype(np.uint16)
            _, png = cv2.imencode(".png", millimetres)
            archive.writestr("depth-millimetres.png", png.tobytes())
            archive.writestr("depth-preview.jpg", images["depth"])
            archive.writestr("left-raw.jpg", images["left"])
            archive.writestr("right-raw.jpg", images["right"])
            archive.writestr("metadata.json", json.dumps(dict(calibration=report, settings=settings,
                              approximate=approximate, mode="trial" if approximate else "calibrated", assumptions=assumptions,
                              image_rotation_deg=display_rotation_deg,
                              geometry_coordinates="unrotated capture; pixel arrays and JPEGs rotated for display",
                              disparity_definition="unrotated left x minus unrotated right x; array rotated for display",
                              captured_at=datetime.now(timezone.utc).isoformat(), depth_size=list(depth.shape[::-1]),
                              invalid_npy="NaN", invalid_png=0, depth_unit="metre", depth_axis="rectified left Z"), indent=2))
        output.seek(0)
        return send_file(output, mimetype="application/zip", as_attachment=True,
                         download_name="stereo-depth-ESSAI.zip" if approximate else "stereo-depth.zip")

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = Engine(args.data_dir or ROOT / ("data-demo" if args.demo else "data"), demo=args.demo)
    engine.start()
    atexit.register(engine.stop)
    create_app(engine).run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)
