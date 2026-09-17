"""OSNet Market1501 512-D descriptors. CPU/OpenCV, Hailo remains dedicated to masks."""
from pathlib import Path
import cv2
import numpy as np

class ReIdentifier:
    def __init__(self):
        path=Path(__file__).parent/'models/osnet_x1_0.onnx'
        if not path.is_file():raise RuntimeError('Modèle OSNet de ré-identification absent')
        self.net=cv2.dnn.readNetFromONNX(str(path))
        self.mean=np.array([.485,.456,.406],np.float32)[:,None,None]
        self.std=np.array([.229,.224,.225],np.float32)[:,None,None]
    def describe(self,image,box):
        h,w=image.shape[:2];x1,y1,x2,y2=box
        x1,x2=max(0,int(x1*w)),min(w,int(x2*w));y1,y2=max(0,int(y1*h)),min(h,int(y2*h))
        if x2-x1<20 or y2-y1<48:return None
        crop=cv2.resize(image[y1:y2,x1:x2],(128,256))
        crop=cv2.cvtColor(crop,cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2,0,1)/255
        self.net.setInput(((crop-self.mean)/self.std)[None])
        vector=self.net.forward().reshape(-1)
        norm=float(np.linalg.norm(vector))
        if vector.size!=512 or not np.isfinite(vector).all() or norm<1e-8:return None
        return vector/norm
