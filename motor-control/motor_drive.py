#!/usr/bin/env python3
"""Exclusive PWM owner. HTTP retrieval never blocks the 50 Hz stop watchdog."""
import json,math,os,signal,threading,time,subprocess,fcntl,uuid,sys
from pathlib import Path
from urllib.request import urlopen
STATUS=Path('/run/rc-motor-drive.json')
NEUTRAL=1500000
CENTER=1566666  # servo_control(0) du dépôt : (59 + 145) / 2 = 102 degrés.
STEERING_MIN=1327777
STEERING_MAX=1805555

def steering_pulse(value):
    if not finite(value) or not -1<=value<=1:raise ValueError("Direction invalide")
    return 1000000+int(102+43*value)*1000000//180

def finite(x):return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)

def command(packet,now):
    if not isinstance(packet,dict):return None,'Navigation indisponible'
    if not packet.get('armed'):return None,'Moteurs désarmés'
    if packet.get('demo'):return None,'Simulation interdite aux moteurs'
    for field in ('lease_until','plan_until'):
        value=packet.get(field)
        if not finite(value) or not now<value<=now+3:return None,'Consigne ou liaison périmée'
    if packet.get('steering_sign') not in (-1,1) or not packet.get('direction_verified'):return None,'Sens de direction à confirmer'
    if packet.get('mode')=='manual' and packet.get('source')=='gamepad':
        manual=packet.get('manual',{});effort=manual.get('effort');steer=manual.get('steering')
        if not finite(effort) or not finite(steer) or abs(effort)>1 or abs(steer)>1:return None,'Commande manuelle invalide'
        return (effort,steer*packet['steering_sign']),packet.get('reason','Commande manuelle')
    if not packet.get('odometry_valid'):return None,'Localisation lidar incertaine'
    if packet.get('mode')!='autonomous':return None,'Mode manuel'
    intent=packet.get('intent',{});motion=intent.get('motion');speed=intent.get('speed_m_s');steer=intent.get('steering_normalized')
    if motion=='stop':return (0.,0.),packet.get('reason','Arrêt demandé')
    if motion not in ('forward','reverse') or not finite(speed) or not finite(steer) or abs(steer)>1:return None,'Consigne invalide'
    if (motion=='forward' and speed<=0) or (motion=='reverse' and speed>=0):return None,'Sens incohérent'
    limit=packet.get('speed_limit')
    if not finite(limit) or limit<=0 or abs(speed)>limit+.001:return None,'Vitesse invalide'
    # No minimum jump: an arbitrarily small intent must never trigger gear-2 full power.
    effort=min(1.,abs(speed)/limit)*(1 if motion=='forward' else -1)
    return (effort,steer*packet['steering_sign']),'Commande active'

class Esc:
    """Nonblocking brake/neutral/reverse sequence, cancelled immediately by stop."""
    def __init__(self):self.last=1;self.phase=None;self.until=0
    def step(self,effort,now):
        if effort==0:self.phase=None;return NEUTRAL
        side=1 if effort>0 else -1
        if self.phase and side!=-1:self.phase=None
        if side==-1 and self.last==1 and self.phase is None:self.phase='neutral';self.until=now+.4
        pulse=NEUTRAL+round(75000*effort)
        if self.phase=='neutral':
            if now<self.until:return NEUTRAL
            self.phase='brake';self.until=now+.5
        if self.phase=='brake':
            if now<self.until:return pulse
            self.phase='pause';self.until=now+.3
        if self.phase=='pause':
            if now<self.until:return NEUTRAL
            self.phase=None;self.last=-1
        self.last=side
        return pulse

class Hardware:
    def __init__(self):self.chip=None;self.lock=None
    def write(self,channel,field,value):
        (self.chip/f'pwm{channel}'/field).write_text(str(value))
    def open(self):
        candidates=[p for p in Path('/sys/class/pwm').glob('pwmchip*') if '1f00098000.pwm' in str(p.resolve())]
        if len(candidates)!=1:raise RuntimeError('PWM0 1f00098000.pwm absent : overlay PWM requis')
        self.chip=candidates[0]
        self.lock=open('/run/rc-motor-test.lock','w')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:self.lock.close();self.lock=None;raise
        try:
            for p in Path('/proc').glob('[0-9]*/comm'):
                try:name=p.read_text().strip()
                except OSError:continue
                if name=='serveur_pi':raise RuntimeError('Le contrôleur manuel est déjà actif')
            for ch,gpio,neutral in ((0,12,NEUTRAL),(1,13,CENTER)):
                if not (self.chip/f'pwm{ch}').exists():(self.chip/'export').write_text(str(ch));time.sleep(.1)
                self.write(ch,'enable',0);self.write(ch,'duty_cycle',0);self.write(ch,'period',20000000)
                self.write(ch,'duty_cycle',neutral)
                subprocess.run(['pinctrl','set',str(gpio),'a0'],check=True,capture_output=True)
                self.write(ch,'enable',1)
        except BaseException:self.close();raise
    def apply(self,pulse,steer):
        # Motor stop first; steering errors cannot delay a requested stop.
        self.write(0,'duty_cycle',pulse)
        self.write(1,'duty_cycle',steering_pulse(steer))
    def close(self):
        if self.chip and self.lock:
            for ch,value in ((0,NEUTRAL),(1,CENTER)):
                try:self.write(ch,'duty_cycle',value)
                except OSError:pass
        if self.lock:self.lock.close()
        self.lock=None

class Receiver:
    def __init__(self):self.packet=None;self.running=True
    def run(self):
        while self.running:
            try:
                with urlopen('http://127.0.0.1:8081/api/drive-intent',timeout=.5) as r:
                    data=r.read(16001)
                    if len(data)>16000:raise ValueError('Réponse trop grande')
                    self.packet=json.loads(data)
            except Exception:self.packet=None
            time.sleep(.04)

def main():
    boot_id=uuid.uuid4().hex
    receiver=Receiver();threading.Thread(target=receiver.run,daemon=True).start()
    running=True;hardware=None;esc=Esc();ready=0.;report_at=0.;retry_at=0.;hardware_error=None
    def end(*_):
        nonlocal running
        running=False
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,end)
    try:
        while running:
            now=time.monotonic();packet=receiver.packet;desired,reason=command(packet,now);pulse=NEUTRAL;steer=0.
            if packet and packet.get('driver_id')!=boot_id:desired=None;reason='Démarrer le suivi pour armer les moteurs'
            try:
                armed=bool(packet and packet.get('armed') and finite(packet.get('lease_until')) and now<packet['lease_until'])
                if not armed:
                    if hardware:hardware.close();hardware=None
                    esc=Esc();hardware_error=None
                elif hardware is None and now>=retry_at:
                    h=Hardware();h.open();hardware=h;ready=time.monotonic()+3;esc=Esc();hardware_error=None
                if hardware:
                    if desired is not None and now>=ready:
                        effort,steer=desired;pulse=esc.step(effort,now)
                    else:
                        esc.step(0,now)
                        if now<ready:reason='Armement ESC au neutre (3 s)'
                    hardware.apply(pulse,steer)
            except Exception as e:
                hardware_error=('Moteurs occupés : fermer le programme de test ou le contrôleur manuel.' if isinstance(e,BlockingIOError) else 'Erreur moteur : '+str(e));retry_at=now+2
                if hardware:hardware.close();hardware=None
            if hardware_error and hardware is None:reason=hardware_error
            if now>=report_at:
                report_at=now+.1
                payload=dict(boot_id=boot_id,updated_monotonic=now,esc_phase=esc.phase,arming=hardware is not None and now<ready,armed=armed,connected=hardware is not None,pulse_us=pulse/1000,steering=steer,reason=reason)
                tmp=STATUS.with_suffix('.tmp');tmp.write_text(json.dumps(payload));tmp.chmod(0o644);tmp.replace(STATUS)
            time.sleep(.02)
    finally:
        receiver.running=False
        if hardware:hardware.close()
        STATUS.unlink(missing_ok=True)

def force_neutral():
    h=Hardware()
    try:
        candidates=[p for p in Path('/sys/class/pwm').glob('pwmchip*') if '1f00098000.pwm' in str(p.resolve())]
        if not candidates:return
        h.chip=candidates[0];h.lock=open('/run/rc-motor-test.lock','w')
        try:fcntl.flock(h.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:h.lock.close();h.lock=None;return
    finally:h.close()

if __name__=='__main__':
    if '--stop' in sys.argv:force_neutral()
    else:main()
