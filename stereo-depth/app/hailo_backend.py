"""Hailo-8L YOLOv8 (COCO, integrated NMS) + TAPPAS JDE tracker.
Imports are lazy: the stereo application also runs without the AI Kit.
"""
from contextlib import ExitStack
from pathlib import Path
import os
import uuid
import cv2
import numpy as np


def letterbox(frame, size):
    h, w = frame.shape[:2]
    out_h, out_w = size
    scale = min(out_w/w, out_h/h)
    rw, rh = round(w*scale), round(h*scale)
    x, y = (out_w-rw)//2, (out_h-rh)//2
    canvas = np.full((out_h, out_w, 3), 114, np.uint8)
    canvas[y:y+rh, x:x+rw] = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (rw, rh))
    return canvas, (x, y, rw, rh)


def decode_people(nms, size, padding, threshold):
    """Native Hailo NMS: class -> detections[ymin,xmin,ymax,xmax,score]."""
    if len(nms) != 80:
        raise ValueError("HEF incompatible : modèle COCO à 80 classes et sortie NMS requis.")
    rows = np.asarray(nms[0], dtype=float)  # COCO person = class 0
    if rows.size == 0: return []
    if rows.ndim != 2 or rows.shape[1] != 5:
        raise ValueError("Format NMS Hailo inattendu (N × 5 requis).")
    oh, ow = size
    px, py, rw, rh = padding
    people = []
    for y1, x1, y2, x2, score in rows:
        if not np.isfinite([y1,x1,y2,x2,score]).all() or score < threshold: continue
        box = np.clip([(x1*ow-px)/rw, (y1*oh-py)/rh, (x2*ow-px)/rw, (y2*oh-py)/rh], 0, 1)
        if box[2]-box[0] > .01 and box[3]-box[1] > .02:
            people.append(dict(box=box.tolist(), confidence=float(score)))
    return people


def iou(a, b):
    x1,y1 = max(a[0],b[0]), max(a[1],b[1])
    x2,y2 = min(a[2],b[2]), min(a[3],b[3])
    overlap = max(0,x2-x1)*max(0,y2-y1)
    return overlap / max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap)


def create_tracker(hailo, name):
    tracker = hailo.HailoTracker.get_instance()
    # Python HailoTrackerParams() is zero-initialized, including Kalman noise.
    # Start from C++ defaults to keep association and prediction well-defined.
    tracker.add_jde_tracker(name)
    tracker.set_keep_tracked_frames(name, 3)
    tracker.set_keep_lost_frames(name, 15)
    tracker.set_keep_new_frames(name, 2)
    return tracker


class HailoBackend:
    def __init__(self):
        self.stack = ExitStack()
        self.tracker = None
        try:
            import hailo
            from hailo_platform import (HEF, VDevice, ConfigureParams, HailoStreamInterface,
                InputVStreamParams, OutputVStreamParams, FormatType, InferVStreams)
            self.hailo = hailo
            if not hasattr(hailo, 'HailoTracker'):
                raise RuntimeError("Bindings Python Hailo Tracker absents : installer une version TAPPAS compatible.")
            paths = [Path(os.environ['STEREO_HAILO_HEF'])] if os.environ.get('STEREO_HAILO_HEF') else [
                Path(__file__).parent/'models/yolov8s_h8l.hef',
                Path('/usr/share/hailo-models/yolov8s_h8l.hef')]
            path = next((p for p in paths if p.is_file()), None)
            if path is None:
                raise RuntimeError("Modèle absent : installer yolov8s_h8l.hef (COCO avec NMS) dans models/ ou définir STEREO_HAILO_HEF.")
            hef = HEF(str(path))
            inputs, outputs = hef.get_input_vstream_infos(), hef.get_output_vstream_infos()
            if len(inputs) != 1 or len(outputs) != 1 or 'nms' not in outputs[0].name.lower():
                raise RuntimeError("HEF requis : une entrée RGB et une sortie Hailo NMS intégrée.")
            self.input_name, self.output_name = inputs[0].name, outputs[0].name
            self.size = tuple(inputs[0].shape[:2])
            device = self.stack.enter_context(VDevice())
            groups = device.configure(hef, ConfigureParams.create_from_hef(hef, interface=HailoStreamInterface.PCIe))
            group = groups[0]
            ip = InputVStreamParams.make_from_network_group(group, quantized=True, format_type=FormatType.UINT8)
            op = OutputVStreamParams.make_from_network_group(group, quantized=False, format_type=FormatType.FLOAT32)
            self.pipeline = self.stack.enter_context(InferVStreams(group, ip, op))
            self.stack.enter_context(group.activate(group.create_params()))
            self.name = 'stereo-' + uuid.uuid4().hex
            self.tracker = create_tracker(hailo, self.name)
            self.model = path.name
        except Exception:
            self.close()
            raise

    def infer(self, frame, threshold):
        image, padding = letterbox(frame, self.size)
        result = self.pipeline.infer({self.input_name: image[None]})
        detections = decode_people(result[self.output_name][0], self.size, padding, threshold)
        h = self.hailo
        inputs = [h.HailoDetection(h.HailoBBox(d['box'][0], d['box'][1], d['box'][2]-d['box'][0], d['box'][3]-d['box'][1]),
                                  0, 'person', d['confidence']) for d in detections]
        tracks = self.tracker.update(self.name, inputs)
        people, used = [], set()
        for track in tracks:
            ids = track.get_objects_typed(h.HAILO_UNIQUE_ID)
            ids = [i for i in ids if i.get_mode() == h.TRACKING_ID]
            if not ids: continue
            b = track.get_bbox()
            box = [b.xmin(),b.ymin(),b.xmax(),b.ymax()]
            candidates = sorted([(iou(box,d['box']), i) for i,d in enumerate(detections) if i not in used], reverse=True)
            # Never publish distances on a purely predicted box or an ambiguous match.
            if not candidates or candidates[0][0] < .5: continue
            if len(candidates)>1 and candidates[0][0]-candidates[1][0] < .1: continue
            _, i = candidates[0]
            used.add(i)
            people.append(dict(id=int(ids[0].get_id()), **detections[i]))
        return people

    def close(self):
        if self.tracker is not None and hasattr(self, 'name'):
            try: self.tracker.remove_jde_tracker(self.name)
            except Exception: pass
            self.tracker = None
        self.stack.close()
