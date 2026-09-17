"""Read-only person following: synchronized image, stereo depth and camera bearing.
No motor interface. Hailo owns a dedicated worker and a one-frame mailbox.
"""
import base64
import copy
import json
import logging
from pathlib import Path
import threading
import time
import math
import cv2
import numpy as np
from hailo_backend import HailoBackend, iou
from segmentation_backend import SegmentationBackend
from identity_memory import IdentityMemory
from reid_backend import ReIdentifier

DEFAULTS = dict(enabled=True, confidence=.45, target_m=1.5, camera_yaw_deg=0., similarity_threshold=.92)


def validate(values):
    if not isinstance(values, dict) or set(values)-set(DEFAULTS): raise ValueError('Réglages de suivi inconnus.')
    out = {**DEFAULTS, **values}
    if not isinstance(out['enabled'], bool): raise ValueError('enabled doit être un booléen.')
    for k, low, high in [('confidence',.1,.95),('target_m',.3,10),('camera_yaw_deg',-90,90),('similarity_threshold',.5,.99)]:
        v = out[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{k} : valeur de {low} à {high} requise.')
    return out


def measure_person(box, depth, projection, rect_rotation, size, rotated, yaw, mask=None, far=4.):
    """Central torso ROI; reject sparse or mixed depths. Bearing is camera-relative.
    Recover the capture ray from oriented rectified pixels, then undo rectification.
    The 180° physical camera mounting inverts capture X/Y.
    """
    w,h = size
    x1,y1,x2,y2 = box
    u,v = (x1+x2)*.5*w, (y1+y2)*.5*h
    if rotated: u,v = w-1-u,h-1-v
    p = projection
    ray = np.array([(u-p[0,2])/p[0,0],(v-p[1,2])/p[1,1],1.])
    ray = rect_rotation.T @ ray
    if rotated: ray[:2] *= -1
    bearing = math.degrees(math.atan2(ray[0],ray[2])) + yaw
    bearing = (bearing+180)%360-180
    result = dict(bearing_deg=round(bearing,1), distance_m=None, depth_z_m=None,
                  lateral_m=None, forward_m=None, valid_percent=0., depth_reason='Profondeur indisponible')
    if depth is None: return result
    # Narrow middle of upper body, excluding silhouette edges and most background.
    xa,xb = int((x1+.3*(x2-x1))*w), int((x1+.7*(x2-x1))*w)
    ya,yb = int((y1+.2*(y2-y1))*h), int((y1+.6*(y2-y1))*h)
    selection=np.zeros((h,w),np.uint8)
    selection[max(0,ya):min(h,yb),max(0,xa):min(w,xb)]=1
    if mask is not None:
        if mask.shape!=(h,w):return result
        interior=cv2.erode(mask.astype(np.uint8),np.ones((7,7),np.uint8))
        selection &= interior
        result['depth_method']='masque érodé + groupe dominant'
    else:result['depth_method']='torse réduit + groupe dominant'
    roi = depth[selection.astype(bool)]
    values = roi[np.isfinite(roi)&(roi>0)]
    fraction = len(values)/max(1,roi.size)
    result['valid_percent'] = round(fraction*100,1)
    if len(values)<20 or fraction<.2:
        result['depth_reason']='Trop peu de profondeur valide sur le torse'
        return result
    # Separate genuinely different surfaces; average only within a dominant group.
    ordered=np.sort(values)
    cuts=np.flatnonzero(np.diff(ordered)>np.maximum(.3,.15*ordered[:-1]))+1
    groups=sorted(np.split(ordered,cuts),key=len,reverse=True)
    chosen=groups[0]
    if len(chosen)<20 or len(chosen)<.65*len(values):
        result['depth_reason']='Plusieurs surfaces sans profondeur dominante'
        return result
    # A continuous tail can bridge two surfaces. Find a compact dominant interval.
    median=float(np.median(chosen));width=max(.6,median*.35)
    ends=np.searchsorted(chosen,chosen+width,side='right')
    start=int(np.argmax(ends-np.arange(len(chosen))))
    compact=chosen[start:ends[start]]
    if len(compact)<20 or len(compact)<.65*len(values):
        result['depth_reason']='Profondeur trop dispersée même après filtrage'
        return result
    chosen=compact
    q10,q90=np.percentile(chosen,[10,90]);z=float(np.median(chosen))
    lo,hi=np.percentile(chosen,[15,85])
    trimmed=chosen[(chosen>=lo)&(chosen<=hi)]
    z=float(np.mean(trimmed)) if len(trimmed) else z
    result['depth_support_percent']=round(100*len(chosen)/len(values),1)
    result['distance_status']='measured'
    if q10>far:
        result['distance_status']='beyond_range'
        result['distance_lower_bound_m']=round(far*math.hypot(ray[0],ray[2]),3)
        result['range_limit_m']=far
        z=far
    distance = z*math.hypot(ray[0],ray[2])
    angle = math.radians(bearing)
    result.update(distance_m=round(distance,3),depth_z_m=round(z,3),
                  lateral_m=round(distance*math.sin(angle),3),forward_m=round(distance*math.cos(angle),3),depth_reason=None)
    return result


class Follower:
    def __init__(self, data, backend_factory=SegmentationBackend):
        self.path = Path(data)/'tracking.json'
        self.config = dict(DEFAULTS)
        try: self.config=validate(json.loads(self.path.read_text()))
        except FileNotFoundError: pass
        except Exception: logging.exception('Réglages de suivi ignorés')
        self.factory=backend_factory
        self.condition=threading.Condition(threading.RLock())
        self.pending=None
        self.version=None
        self.generation=0
        self.selected=None
        self.selected_seen=0.
        self.expired=False
        self.result=None
        self.state='starting'
        self.error=None
        self.running=False
        self.sequence=0
        self.identity=IdentityMemory();self.features={};self.visible_identity=None

    def configure(self, values):
        with self.condition:
            updated=validate({**self.config,**values})
            temp=self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(updated,indent=2))
            temp.replace(self.path)
            self.config=updated
            if set(values)!={'similarity_threshold'}:self.invalidate_locked()
            self.condition.notify_all()

    def invalidate_locked(self):
        self.identity.clear();self.features={};self.visible_identity=None
        self.generation+=1
        self.selected=None
        self.expired=False
        self.result=None
        self.pending=None

    def invalidate(self):
        with self.condition: self.invalidate_locked()

    def submit(self, image, depth, projection, rotation, rotated, approximate, timestamp, version, far=4.):
        with self.condition:
            if version!=self.version:
                self.invalidate_locked()
                self.version=version
            if not self.config['enabled']: return
            # Producer never blocks on inference; newer frames replace pending frames.
            self.pending=(image,depth,projection,rotation,rotated,approximate,timestamp,self.generation,far)
            self.condition.notify_all()

    def start(self):
        self.running=True
        self.thread=threading.Thread(target=self.run,daemon=True,name='hailo-following')
        self.thread.start()

    def stop(self):
        self.running=False
        with self.condition: self.condition.notify_all()
        if hasattr(self,'thread'): self.thread.join(timeout=5)

    def select(self, track_id, generation):
        with self.condition:
            if track_id is None:
                self.selected=None; self.expired=False;self.identity.clear();self.visible_identity=None
                return
            if isinstance(track_id,bool) or not isinstance(track_id,int): raise ValueError('Identifiant de personne invalide.')
            if generation != self.generation: raise ValueError('Image périmée : sélectionner sur la nouvelle image.')
            if not self.result or time.monotonic()-self.result['captured_at']>1:
                raise ValueError('Attendre une détection récente.')
            if not any(p['id']==track_id for p in self.result['people']): raise ValueError('Personne non visible : sélectionner de nouveau.')
            self.selected=track_id
            self.selected_seen=self.result['captured_at']
            self.identity.select(track_id,self.features.get(track_id),self.selected_seen,
                                 [v for k,v in self.features.items() if k!=track_id])
            self.visible_identity=track_id
            self.expired=False

    def snapshot(self):
        with self.condition:
            now=time.monotonic()
            result=copy.deepcopy(self.result) if self.result else dict(people=[],image=None)
            age=now-result['captured_at'] if 'captured_at' in result else None
            fresh=age is not None and age<=1 and self.config['enabled'] and self.state=='ready'
            if not fresh: result['people']=[]
            target=next((p for p in result['people'] if p['id']==self.selected),None) if not self.expired and self.visible_identity==self.selected else None
            selected_state='none' if self.selected is None else ('visible' if target else 'lost')
            if self.selected is not None and not target:
                selected_state=self.identity.state if self.identity.state!='visible' else 'lost'
            if self.selected is not None and now-self.selected_seen>60:
                target=None; selected_state='reselect'
            if target:
                target=dict(target)
                target['distance_error_m']=round(target['distance_m']-self.config['target_m'],3) if target['distance_m'] is not None else None
            result.update(state='disabled' if not self.config['enabled'] else self.state,
                          error=self.error, config=dict(self.config), generation=self.generation,
                          age_s=round(age,2) if age is not None else None, fresh=fresh,
                          selected_id=self.selected, selection_state=selected_state,target=target,
                          identity_id=self.identity.serial,identity_score=self.identity.score,
                          identity_method='OSNet 512D + ancre fixe + confirmation multi-images',
                          backend='Hailo · YOLOv5n segmentation + JDE', motor_control=False)
            return result

    def run(self):
        backend=None
        backend_generation=None
        reidentifier=None
        try:
            while self.running:
                with self.condition:
                    self.condition.wait_for(lambda:not self.running or (self.pending is not None and self.config['enabled']),timeout=1)
                    if not self.running: break
                    if not self.config['enabled']:
                        if backend: backend.close(); backend=None
                        continue
                    if self.pending is None: continue
                    packet=self.pending; self.pending=None
                    config=dict(self.config)
                image,depth,projection,rotation,rotated,approximate,captured,generation,far=packet
                try:
                    if backend is None or backend_generation!=generation:
                        if backend: backend.close()
                        backend=None
                        backend=self.factory()
                        backend_generation=generation
                    if time.monotonic()-captured>1: continue
                    start=time.monotonic()
                    people=backend.infer(image,config['confidence'])
                    overlay=image.copy();features={}
                    if reidentifier is None:reidentifier=ReIdentifier()
                    for person_index,person in enumerate(people):
                        mask=person.pop('mask',None)
                        features[person['id']]=reidentifier.describe(image,person['box']) if person_index<4 else None
                        if mask is not None:
                            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                            cv2.drawContours(overlay,contours,-1,(130,235,140),1)
                        person.update(measure_person(person['box'],depth,projection,rotation,
                                      image.shape[1::-1],rotated,config['camera_yaw_deg'],mask=mask,far=far))
                        # Overlapping people contaminate a torso ROI; don't guess its owner.
                        if mask is None and any(other['id']!=person['id'] and iou(person['box'],other['box'])>.25 for other in people):
                            person.update(distance_m=None,depth_z_m=None,lateral_m=None,forward_m=None,
                                          depth_reason='Personnes superposées : distance incertaine')
                    ok,jpeg=cv2.imencode('.jpg',overlay,[cv2.IMWRITE_JPEG_QUALITY,82])
                    with self.condition:
                        if generation!=self.generation: continue
                        self.state='ready'; self.error=None
                        self.sequence+=1
                        self.result=dict(sequence=self.sequence,captured_at=captured,people=people,
                            image=base64.b64encode(jpeg).decode() if ok else None,
                            approximate=approximate,inference_ms=round((time.monotonic()-start)*1000,1))
                        self.features=features
                        self.visible_identity=self.identity.update(people,features,captured,self.config['similarity_threshold'])
                        if self.visible_identity is not None:
                            self.selected=self.visible_identity;self.selected_seen=captured;self.expired=False
                except Exception as exc:
                    if backend:
                        try: backend.close()
                        except Exception: logging.exception('Fermeture Hailo')
                    backend=None
                    with self.condition:
                        self.state='waiting_hailo'; self.error=str(exc)
                        self.invalidate_locked()
                    # Retry without busy looping; shutdown remains interruptible.
                    for _ in range(100):
                        if not self.running: break
                        time.sleep(.1)
        finally:
            if backend: backend.close()
