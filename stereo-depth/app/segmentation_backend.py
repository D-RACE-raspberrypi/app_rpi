"""YOLOv5n instance masks through installed Hailo GStreamer postprocessing."""
import uuid
import cv2
import numpy as np
from hailo_backend import letterbox, create_tracker, iou

class SegmentationBackend:
    def __init__(self):
        import gi
        gi.require_version('Gst','1.0')
        from gi.repository import Gst
        import hailo
        self.Gst=Gst;self.hailo=hailo;self.pipeline=None;self.tracker=None
        Gst.init(None)
        self.name='seg-'+uuid.uuid4().hex
        try:
            self.pipeline=Gst.parse_launch('appsrc name=input is-live=true do-timestamp=true format=time block=true caps=video/x-raw,format=RGB,width=640,height=640,framerate=30/1 ! queue max-size-buffers=1 ! hailonet hef-path=/usr/share/hailo-models/yolov5n_seg_h8l_mz.hef batch-size=1 ! hailofilter so-path=/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/libyolov5seg_post.so config-path=/usr/share/hailo-models/yolov5seg.json function-name=yolov5seg qos=false ! appsink name=output sync=false async=false enable-last-sample=false max-buffers=1 drop=false')
            self.source=self.pipeline.get_by_name('input');self.sink=self.pipeline.get_by_name('output')
            self.pipeline.set_state(Gst.State.PLAYING)
            self.tracker=create_tracker(hailo,self.name);self.sequence=0
        except Exception:
            self.close();raise

    def infer(self,frame,threshold):
        Gst=self.Gst;h=self.hailo
        image,padding=letterbox(frame,(640,640));px,py,rw,rh=padding
        buffer=Gst.Buffer.new_wrapped(image.tobytes());buffer.duration=Gst.SECOND//30
        self.sequence+=1
        if self.source.emit('push-buffer',buffer)!=Gst.FlowReturn.OK:raise RuntimeError('Segmentation : entrée interrompue')
        sample=self.sink.emit('try-pull-sample',3*Gst.SECOND)
        if sample is None:
            msg=self.pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
            raise RuntimeError(str(msg.parse_error()) if msg else 'Segmentation : délai dépassé')
        roi=h.get_roi_from_buffer(sample.get_buffer());detections=[]
        height,width=frame.shape[:2]
        for d in roi.get_objects_typed(h.HAILO_DETECTION):
            if d.get_label()!='person' or d.get_confidence()<threshold:continue
            b=d.get_bbox();raw=np.array([b.xmin(),b.ymin(),b.xmax(),b.ymax()])
            box=np.clip([(raw[0]*640-px)/rw,(raw[1]*640-py)/rh,(raw[2]*640-px)/rw,(raw[3]*640-py)/rh],0,1)
            if box[2]<=box[0] or box[3]<=box[1]:continue
            masks=d.get_objects_typed(h.HAILO_CONF_CLASS_MASK)
            mask=np.zeros((height,width),np.uint8)
            if masks:
                m=masks[0];values=np.asarray(m.get_data(),dtype=np.float32).reshape(m.get_height(),m.get_width())
                # Mask is cropped to the detection box in the 640x640 letterbox.
                x1,y1,x2,y2=np.clip(np.rint(raw*640).astype(int),0,640)
                if x2>x1 and y2>y1 and values.size:
                    network=np.zeros((640,640),np.float32)
                    network[y1:y2,x1:x2]=cv2.resize(values,(x2-x1,y2-y1))
                    mask=(cv2.resize(network[py:py+rh,px:px+rw],(width,height))>.5).astype(np.uint8)
            detections.append(dict(box=box.tolist(),confidence=float(d.get_confidence()),mask=mask))
        inputs=[h.HailoDetection(h.HailoBBox(d['box'][0],d['box'][1],d['box'][2]-d['box'][0],d['box'][3]-d['box'][1]),0,'person',d['confidence']) for d in detections]
        tracks=self.tracker.update(self.name,inputs);people=[];used=set()
        for t in tracks:
            ids=[v for v in t.get_objects_typed(h.HAILO_UNIQUE_ID) if v.get_mode()==h.TRACKING_ID]
            if not ids:continue
            b=t.get_bbox();box=[b.xmin(),b.ymin(),b.xmax(),b.ymax()]
            matches=sorted([(iou(box,d['box']),i) for i,d in enumerate(detections) if i not in used],reverse=True)
            if not matches or matches[0][0]<.5 or (len(matches)>1 and matches[0][0]-matches[1][0]<.1):continue
            _,i=matches[0];used.add(i);people.append(dict(id=int(ids[0].get_id()),**detections[i]))
        return people

    def close(self):
        if self.pipeline is not None:self.pipeline.set_state(self.Gst.State.NULL);self.pipeline=None
        if self.tracker is not None:self.tracker.remove_jde_tracker(self.name);self.tracker=None
