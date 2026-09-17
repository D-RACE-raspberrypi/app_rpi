"""MPU6500 gyro sampling. Calibration explicit; no position from double integration."""
import os,fcntl,struct,time,threading,json,math
from pathlib import Path

class Imu:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.Lock();self.history=[];self.error=None;self.calibration=None
        try:self.calibration=json.loads(self.path.read_text())
        except (OSError,ValueError):pass
    def open(self):
        f=os.open('/dev/i2c-1',os.O_RDWR);fcntl.ioctl(f,0x0703,0x68)
        os.write(f,b'\x75');identity=os.read(f,1)[0]
        if identity not in (0x68,0x70):os.close(f);raise ValueError('IMU non reconnue')
        for reg,value in ((0x6b,1),(0x1b,0),(0x1c,0),(0x1a,3),(0x19,9)):os.write(f,bytes((reg,value)))
        time.sleep(.1);return f
    @staticmethod
    def sample(f):
        os.write(f,b'\x3b');v=struct.unpack('>7h',os.read(f,14))
        return [x/16384 for x in v[:3]],[x/131 for x in v[4:]]
    def calibrate(self):
        import statistics
        f=self.open();samples=[]
        try:
            for _ in range(300):samples.append(self.sample(f));time.sleep(.01)
        finally:os.close(f)
        acc=[statistics.mean(s[0][i] for s in samples) for i in range(3)]
        bias=[statistics.mean(s[1][i] for s in samples) for i in range(3)]
        jitter=max(statistics.pstdev(s[1][i] for s in samples) for i in range(3))
        acc_jitter=max(statistics.pstdev(s[0][i] for s in samples) for i in range(3))
        axis=max(range(3),key=lambda i:abs(acc[i]));norm=math.sqrt(sum(a*a for a in acc))
        if jitter>1. or acc_jitter>.06 or not .8<norm<1.25 or abs(acc[axis])/norm<.95:
            raise ValueError('Calibration refusée : mouvement ou axe vertical trop incliné')
        self.calibration=dict(bias=bias,axis=axis,sign=-1 if acc[axis]>0 else 1,accel_g=acc,gyro_std=jitter,created=time.time())
        self.path.write_text(json.dumps(self.calibration,indent=2));return self.calibration
    def start(self):threading.Thread(target=self.run,daemon=True,name='imu').start()
    def run(self):
        while True:
            f=None
            try:
                if not self.calibration:raise ValueError('Gyroscope à calibrer au repos')
                f=self.open();yaw=0.;previous=time.time()
                while True:
                    _,gyro=self.sample(f);now=time.time();dt=now-previous;previous=now;c=self.calibration
                    if not 0<dt<.1:raise ValueError('Interruption du flux gyroscope')
                    rate=c['sign']*(gyro[c['axis']]-c['bias'][c['axis']]);yaw+=math.radians(rate)*dt
                    with self.lock:
                        self.history.append((now,yaw));self.history=self.history[-250:];self.error=None
                    time.sleep(.01)
            except Exception as e:
                with self.lock:self.history=[];self.error=str(e)
                time.sleep(1)
            finally:
                if f is not None:os.close(f)
    def delta(self,start,end):
        with self.lock:h=list(self.history)
        if not h or start<h[0][0] or end>h[-1][0]+.06:return None
        def at(t):
            for a,b in zip(h,h[1:]):
                if a[0]<=t<=b[0]:return a[1]+(b[1]-a[1])*(t-a[0])/(b[0]-a[0])
            return h[-1][1]
        return at(end)-at(start)
    def status(self):
        with self.lock:return dict(calibrated=bool(self.calibration),fresh=bool(self.history and time.time()-self.history[-1][0]<.1),error=self.error)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--calibrate',action='store_true');a=p.parse_args()
    imu=Imu(Path(__file__).with_name('imu-calibration.json'))
    if a.calibrate:print(json.dumps(imu.calibrate()))
