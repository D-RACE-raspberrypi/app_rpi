"""Robust local scan registration with optional gyro yaw prior. x right/y forward."""
import math
import numpy as np


def world(point,pose):
    x,y=point;c,s=math.cos(pose[2]),math.sin(pose[2])
    return (pose[0]+c*x+s*y,pose[1]-s*x+c*y)


def local(point,pose):
    x,y=point[0]-pose[0],point[1]-pose[1];c,s=math.cos(pose[2]),math.sin(pose[2])
    return (c*x-s*y,s*x+c*y)


def register(current,previous,dyaw=None):
    if len(current)<40 or len(previous)<40:return None
    source=np.asarray(current);target=np.asarray(previous)
    yaw=dyaw or 0.;t=np.zeros(2);residual=None;ratio=0.
    for _ in range(12):
        c,s=math.cos(yaw),math.sin(yaw);r=np.array([[c,s],[-s,c]])
        transformed=source@r.T+t
        distances=((transformed[:,None,:]-target[None,:,:])**2).sum(axis=2)
        idx=distances.argmin(axis=1);err=distances[np.arange(len(source)),idx]
        keep=err<min(.30**2,float(np.quantile(err,.75)))
        if keep.sum()<30:return None
        a=source[keep];b=target[idx[keep]]
        # Reject essentially collinear scenery: sliding along a wall is unobservable.
        eig=np.linalg.eigvalsh(np.cov(b.T))
        if eig[0]<.015 or eig[0]/max(eig[1],1e-9)<.015:return None
        ac=a-a.mean(axis=0);bc=b-b.mean(axis=0)
        u,_,vt=np.linalg.svd(ac.T@bc);rotation=vt.T@u.T
        if np.linalg.det(rotation)<0:return None
        fitted=math.atan2(rotation[0,1],rotation[0,0])
        if dyaw is not None:
            if abs((fitted-dyaw+math.pi)%(2*math.pi)-math.pi)>.20:return None
            yaw=.8*dyaw+.2*fitted
        else:yaw=fitted
        c,s=math.cos(yaw),math.sin(yaw);r=np.array([[c,s],[-s,c]])
        t=b.mean(axis=0)-r@a.mean(axis=0)
        residual=float(np.sqrt(np.mean(np.sum((a@r.T+t-b)**2,axis=1))))
        ratio=float(keep.mean())
    if residual>.07 or ratio<.45:return None
    return (float(t[0]),float(t[1]),yaw),dict(residual_m=round(residual,4),inlier_fraction=round(ratio,3))


class Odometry:
    def __init__(self):self.pose=(0.,0.,0.);self.previous=None;self.stamp=None;self.epoch=0;self.valid=False;self.quality={};self.history=[]
    def update(self,scan,c,imu=None):
        stamp=scan.get('timestamp')
        if stamp==self.stamp:return
        cloud=[]
        for p in scan.get('points',[]):
            d=p.get('distance_mm',0)/1000
            if p.get('quality',0)<=0 or not .15<d<6:continue
            a=math.radians((p['angle_deg']-c.lidar_front_deg)*c.lidar_sign)
            cloud.append((c.lidar_x_m+d*math.sin(a),c.lidar_y_m+d*math.cos(a)))
        cloud=cloud[::max(1,len(cloud)//180)]
        dt=stamp-self.stamp if self.stamp is not None else None
        fit=register(cloud,self.previous,imu.delta(self.stamp,stamp) if imu else None) if self.previous is not None and dt is not None and 0<dt<.65 else None
        self.valid=False
        if fit:
            delta,quality=fit
            if math.hypot(*delta[:2])<=.6*dt+.035 and abs(delta[2])<=1.5*dt+.04:
                x,y=world(delta[:2],self.pose);self.pose=(x,y,self.pose[2]+delta[2]);self.valid=True;self.quality=quality
        if not self.valid:
            self.epoch+=1;self.pose=(0.,0.,0.);self.history=[];self.quality={}
        self.previous=cloud;self.stamp=stamp
        self.history.append((stamp,self.pose));self.history=self.history[-20:]
        scan['_pose']=self.pose;scan['_pose_epoch']=self.epoch
    def pose_at(self,stamp):
        if not self.valid or not self.history or stamp<self.history[0][0] or stamp>self.history[-1][0]+.15:return None
        for (ta,a),(tb,b) in zip(self.history,self.history[1:]):
            if ta<=stamp<=tb:
                f=(stamp-ta)/(tb-ta);return tuple(x+(y-x)*f for x,y in zip(a,b))
        return self.pose
    def status(self,now):
        return dict(valid=self.valid and self.stamp is not None and 0<=now-self.stamp<.5,pose=list(self.pose),epoch=self.epoch,**self.quality)
