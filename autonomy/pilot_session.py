"""Browser controller session. Inputs expire and transitions require neutral triggers."""
import math,time

def axis(value,lo,hi):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
        raise ValueError('Commande manette invalide.')
    return value

class PilotSession:
    def __init__(self,mode='manual'):
        if mode not in ('manual','autonomous'):raise ValueError('Mode inconnu.')
        self.mode=mode;self.seq=-1;self.touch=False;self.until=0.;self.ready=False
        self.steer=0.;self.effort=0.;self.stamp=0.;self.connected=False;self.gear=2
    def switch(self,mode,now):
        if mode not in ('manual','autonomous'):raise ValueError('Mode inconnu.')
        self.mode=mode;self.until=now+.4;self.ready=False;self.effort=0.;self.steer=0.
    def update(self,data,now):
        seq=data.get('seq')
        if type(seq) is not int or seq<=self.seq:raise ValueError('Trame manette ancienne.')
        steer=axis(data.get('steer'),-1,1);accel=axis(data.get('accel'),0,1);brake=axis(data.get('brake'),0,1)
        gear=data.get('gear',2)
        if type(gear) is not int or gear not in (1,2,3,4):raise ValueError('Niveau manuel invalide.')
        touch=data.get('touch');connected=data.get('connected')
        if type(touch) is not bool or type(connected) is not bool:raise ValueError('État manette invalide.')
        if not connected:raise ValueError('Manette déconnectée.')
        # First held touch at arming is not an edge; wait for release first.
        if self.seq>=0 and touch and not self.touch:self.switch('manual' if self.mode=='autonomous' else 'autonomous',now)
        self.seq=seq;self.touch=touch;self.stamp=now;self.connected=True;self.gear=gear
        if now>=self.until and accel<.05 and brake<.05:self.ready=True
        self.steer=0. if abs(steer)<.06 else steer
        self.effort=accel-brake if self.ready and now>=self.until else 0.
    def status(self,now):
        return dict(mode=self.mode,connected=self.connected and now-self.stamp<.35,ready=self.ready and now>=self.until,seq=self.seq,gear=self.gear)
