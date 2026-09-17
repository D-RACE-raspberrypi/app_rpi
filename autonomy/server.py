#!/usr/bin/env python3
"""Fusion dashboard and advisory intent API. No connection to motor drivers."""
import argparse
import math
from imu import Imu
from pilot_session import PilotSession
from odometry import Odometry,world,local
from route_tracking import TargetFilter
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlparse
from urllib.request import urlopen,Request
from planner import Config,Planner,finite

ROOT=Path(__file__).resolve().parent


def json_request(url,data=None):
    req=Request(url,data=json.dumps(data).encode() if data is not None else None,
                headers={'Content-Type':'application/json'} if data is not None else {})
    with urlopen(req,timeout=.7) as response:
        raw=response.read(4_000_001)
        if len(raw)>4_000_000:raise ValueError('Réponse capteur trop volumineuse.')
        return json.loads(raw)


def demo_sensors(scenario):
    points=[]
    for angle in range(360):
        a=(angle+180)%360-180
        if scenario=='unknown_rear' and abs(a)>90:continue
        d=3000
        if scenario in ('blocked','unknown_rear','trapped') and abs(a)<75:d=470
        if scenario=='trapped' and abs(a)>100:d=470
        if scenario=='obstacle_right' and 5<a<65:d=650
        if scenario=='close_obstacle' and abs(a)<10:d=150
        points.append(dict(angle_deg=angle,distance_mm=d,quality=30))
    target=dict(id=1,bearing_deg=25.,distance_m=2.5,confidence=.95,box=[.4,.1,.65,.9])
    if scenario=='near':target['distance_m']=1.
    vision=dict(state='ready',fresh=True,age_s=.02,approximate=False,generation=1,
        selection_state='visible',selected_id=1,target=target,people=[target],image=None)
    scan=dict(timestamp=time.time(),duration_s=.2,points=points)
    if scenario=='lost':vision.update(target=None,selection_state='lost')
    if scenario=='stale':scan['timestamp']-=5
    return vision,scan


class ScanWindow:
    """Three distinct revolutions, bounded by source time; no invented returns."""
    def __init__(self,config=None):
        self.scans=[];self.config=config

    def add(self,scan):
        if (not isinstance(scan,dict) or not finite(scan.get('timestamp'))
                or not isinstance(scan.get('points'),list) or len(scan['points'])>20000):
            self.scans=[]
            return
        timestamp=scan['timestamp']
        if self.scans and timestamp<self.scans[-1]['timestamp']:
            self.scans=[]
        if not self.scans or timestamp!=self.scans[-1]['timestamp']:
            self.scans.append(copy.deepcopy(scan))
            self.scans=self.scans[-3:]

    def snapshot(self,now,max_age):
        self.scans=[s for s in self.scans if 0<=now-s['timestamp']<=min(.6,max_age)]
        if not self.scans:return None
        if self.config is not None and '_pose' in self.scans[-1]:
            c=self.config;last=self.scans[-1];points=[]
            self.scans=[s for s in self.scans if s.get('_pose_epoch')==last['_pose_epoch']]
            for scan in self.scans:
                for p in scan['points']:
                    if p.get('distance_mm',0)<=0 or p.get('quality',0)<=0:continue
                    a=math.radians((p['angle_deg']-c.lidar_front_deg)*c.lidar_sign);d=p['distance_mm']/1000
                    q=local(world((c.lidar_x_m+d*math.sin(a),c.lidar_y_m+d*math.cos(a)),scan['_pose']),last['_pose'])
                    x,y=q[0]-c.lidar_x_m,q[1]-c.lidar_y_m
                    points.append(dict(angle_deg=(math.degrees(math.atan2(x,y))/c.lidar_sign+c.lidar_front_deg)%360,distance_mm=1000*math.hypot(x,y),quality=p['quality']))
        else:points=[p for scan in self.scans for p in scan['points']]
        # Planner takes the nearest valid return per sector in the CURRENT car frame.
        return dict(timestamp=self.scans[0]['timestamp'],
            latest_timestamp=self.scans[-1]['timestamp'],turns=len(self.scans),
            window_s=round(self.scans[-1]['timestamp']-self.scans[0]['timestamp'],3),
            points=points)


class Fusion:
    def __init__(self,vision_url,lidar_url,config_path,demo=False):
        self.vision_url=vision_url.rstrip('/');self.lidar_url=lidar_url.rstrip('/')
        self.path=Path(config_path);self.demo=demo;self.scenario='clear'
        c=Config()
        if self.path.exists():c=Config.validated(json.loads(self.path.read_text()))
        self.planner=Planner(c);self.lock=threading.RLock();self.running=False
        self.vision=None;self.scan=None;self.vision_at=0;self.scan_at=0
        self.errors={};self.output={};self.updated=0;self.sequence=0
        self.epoch=0;self.scan_window=ScanWindow(c)
        self.odometry=Odometry();self.imu=Imu(ROOT/'imu-calibration.json');self.target_filter=TargetFilter()
        self.drive_until=0.;self.drive_driver=None;self.drive_owner=None;self.pilot=None
        self.drive_config_path=self.path.with_name('drive-config.json')
        self.drive_config=dict(steering_sign=1,direction_verified=False)
        if self.drive_config_path.exists():self.drive_config.update(json.loads(self.drive_config_path.read_text()))

    def start(self):
        self.running=True
        if not self.demo:self.imu.start()
        threading.Thread(target=self.run,daemon=True,name='fusion-planner').start()

    def motor_status(self):
        try:
            status=json.loads(Path('/run/rc-motor-drive.json').read_text())
            if time.monotonic()-status['updated_monotonic']>.5:raise ValueError()
            return status
        except Exception:return dict(connected=False,armed=False,reason='Service moteur indisponible')

    def drive_action(self,data):
        with self.lock:return self._drive_action(data)

    def _drive_action(self,data):
        action=data.get('action');owner=data.get('owner')
        if action=='stop':
            self.drive_until=0.;self.drive_owner=None
            self.set_mode('manual');return
        if self.demo:raise ValueError('Moteurs interdits en simulation.')
        if action=='direction':
            if time.monotonic()<self.drive_until:raise ValueError('Arrêter les moteurs avant ce réglage.')
            sign=data.get('sign')
            if type(sign) is not int or sign not in (-1,1):raise ValueError('Choisir le sens de direction.')
            self.drive_config=dict(steering_sign=sign,direction_verified=True)
            tmp=self.drive_config_path.with_suffix('.tmp');tmp.write_text(json.dumps(self.drive_config));tmp.replace(self.drive_config_path);return
        if not isinstance(owner,str) or not 8<=len(owner)<=100:raise ValueError('Session de conduite invalide.')
        if action=='start':
            status=self.motor_status()
            if not status.get('boot_id'):raise ValueError('Service moteur indisponible.')
            if not self.drive_config.get('direction_verified'):raise ValueError('Confirmer le sens de direction avant de démarrer.')
            if self.planner.config.target_m is None:raise ValueError('Choisir la distance à maintenir.')
            if self.drive_owner not in (None,owner) and time.monotonic()<self.drive_until:raise ValueError('Suivi déjà activé dans un autre onglet.')
            self.pilot=None;self.set_mode('autonomous');self.drive_driver=status['boot_id'];self.drive_owner=owner;self.drive_until=time.monotonic()+1.5;return
        if action=='heartbeat' and owner==self.drive_owner and time.monotonic()<self.drive_until:
            self.drive_until=time.monotonic()+1.5;return
        raise ValueError('Suivi désarmé : appuyer sur Démarrer.')

    def pilot_action(self,data):
        with self.lock:
            action=data.get('action');owner=data.get('owner');now=time.monotonic()
            if action=='stop':return self.drive_action(dict(action='stop'))
            if action=='preview':
                if now<self.drive_until:raise ValueError('Une session de conduite est active.')
                self.set_mode('autonomous');return
            if action=='start':
                session=PilotSession(data.get('mode','manual'))
                self.drive_action(dict(action='start',owner=owner));self.pilot=session
                return
            if not self.pilot or owner!=self.drive_owner or now>=self.drive_until:
                raise ValueError('Session désarmée : activer les commandes.')
            if action=='mode':self.pilot.switch(data.get('mode'),now)
            elif action=='input':
                try:self.pilot.update(data,now)
                except ValueError:
                    self.drive_action(dict(action='stop'));raise
                self.drive_until=now+.5
            else:raise ValueError('Action inconnue.')

    def drive_snapshot(self):
        with self.lock:
            p=copy.deepcopy(self.output);now=time.monotonic();motion=p.get('intent',{}).get('motion')
            packet=dict(armed=now<self.drive_until,lease_until=self.drive_until,plan_until=self.updated+.3,
                demo=self.demo,driver_id=self.drive_driver,**self.drive_config,
                intent=p.get('intent',{}),mode=p.get('mode'),reason=p.get('reason'),
                odometry_valid=self.odometry.status(time.time())['valid'],
                speed_limit=self.planner.config.max_reverse_m_s if motion=='reverse' else self.planner.config.max_forward_m_s)
            if self.pilot:
                state=self.pilot.status(now)
                if not state['connected'] or not state['ready']:
                    packet.update(plan_until=now+.1,mode='manual',source='gamepad',manual=dict(effort=0.,steering=0.),
                        reason='Relâcher les gâchettes / attendre la manette')
                elif self.pilot.mode=='manual':
                    packet.update(plan_until=self.pilot.stamp+.35,mode='manual',source='gamepad',
                        manual=dict(effort=self.pilot.effort,steering=self.pilot.steer,gear=self.pilot.gear),reason=f'Commande manuelle · niveau {self.pilot.gear}')
            return packet

    def configure(self,values):
        with self.lock:
            c=Config.validated({**asdict(self.planner.config),**values})
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(asdict(c),indent=2));tmp.replace(self.path)
            self.planner.config=c;self.planner.reset();self.epoch+=1
            self.scan_window=ScanWindow(c);self.odometry=Odometry();self.target_filter=TargetFilter()
            self.output={};self.updated=0

    def set_mode(self,mode):
        with self.lock:
            if mode=='autonomous' and self.planner.config.target_m is None:
                raise ValueError('Choisissez d’abord la distance à maintenir.')
            self.planner.set_mode(mode);self.epoch+=1;self.output={};self.updated=0
            if mode=='manual':self.drive_until=0.;self.drive_owner=None;self.pilot=None

    def snapshot(self):
        with self.lock:
            output=copy.deepcopy(self.output)
            age=time.monotonic()-self.updated
            if age>.3:
                output=dict(mode=self.planner.mode,state='stop',reason='Calcul indisponible ou périmé.',
                    intent=dict(motion='stop',speed_m_s=0,steering_deg=0,steering_normalized=0,ttl_ms=0),
                    motor_control=False,advisory_only=True)
            # TTL expires at production, not at the time of this HTTP request.
            output['intent']['ttl_ms']=max(0,int(300-age*1000)) if age<=.3 else 0
            output.update(motor_control=time.monotonic()<self.drive_until,advisory_only=not time.monotonic()<self.drive_until)
            output.update(sequence=self.sequence,generated_at_unix=time.time()-max(0,age),demo=self.demo)
            vision=copy.deepcopy(self.vision)
            if isinstance(vision,dict):
                original_age=vision.get('age_s')
                age_v=original_age+time.monotonic()-self.vision_at if isinstance(original_age,(int,float)) else None
                vision['age_s']=age_v
                if age_v is None or not 0<=age_v<=self.planner.config.max_age_s:
                    vision.update(fresh=False,target=None,people=[])
            return dict(plan=output,config=asdict(self.planner.config),errors=dict(self.errors),
                drive=dict(active=time.monotonic()<self.drive_until,config=dict(self.drive_config),status=self.motor_status(),
                    owner=self.drive_owner,pilot=self.pilot.status(time.monotonic()) if self.pilot else None),
                vision=vision,scan=copy.deepcopy(self.scan),
                odometry=self.odometry.status(time.time()),imu=self.imu.status(),
                sources=dict(vision=self.vision_url,lidar=self.lidar_url),demo=self.demo,scenario=self.scenario)

    def run(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures={};requested={}
            while self.running:
                now=time.monotonic()
                if self.demo:
                    with self.lock:
                        self.vision,self.scan=demo_sensors(self.scenario)
                        self.vision_at=self.scan_at=now
                else:
                    urls={'vision':self.vision_url+'/api/following','lidar':self.lidar_url+'/api/latest'}
                    for name,url in urls.items():
                        if name in futures and futures[name].done():
                            try:
                                value=futures.pop(name).result()
                                with self.lock:
                                    if name=='vision':self.vision=value;self.vision_at=requested[name]
                                    else:
                                        self.odometry.update(value,self.planner.config,self.imu)
                                        self.scan_window.add(value);self.scan_at=requested[name]
                                    self.errors.pop(name,None)
                            except Exception as exc:
                                with self.lock:
                                    self.errors[name]=str(exc)
                                    if name=='vision':self.vision=None
                                    else:self.scan=None;self.scan_window.scans=[]
                        if name not in futures:
                            requested[name]=now
                            futures[name]=pool.submit(json_request,url)
                with self.lock:
                    if not self.demo:self.scan=self.scan_window.snapshot(time.time(),self.planner.config.max_age_s)
                    v=copy.deepcopy(self.vision)
                    if isinstance(v,dict):
                        source_age=v.get('age_s')
                        v['age_s']=source_age+(now-self.vision_at) if isinstance(source_age,(int,float)) else None
                    if self.scan is not None and not self.demo:
                        self.scan['odometry']=self.odometry.status(time.time())
                    if isinstance(v,dict) and isinstance(v.get('target'),dict) and self.odometry.valid:
                        t=v['target'];age=v.get('age_s');d=t.get('distance_m');angle=t.get('bearing_deg')
                        # Bound-only depths are never smoothed into an invented metric distance.
                        if finite(age) and finite(d) and finite(angle) and t.get('distance_status')!='beyond_range':
                            stamp=time.time()-age;capture_pose=self.odometry.pose_at(stamp)
                            if capture_pose is not None:
                                c=self.planner.config;a=math.radians(angle)
                                key=(v.get('generation'),v.get('identity_id',v.get('selected_id')),self.odometry.epoch)
                                q=world((d*math.sin(a)+c.camera_x_m,d*math.cos(a)+c.camera_y_m),capture_pose)
                                q=self.target_filter.update(q,key,stamp)
                                x,y=local(q,self.odometry.pose);x-=c.camera_x_m;y-=c.camera_y_m
                                t['distance_m']=math.hypot(x,y);t['bearing_deg']=math.degrees(math.atan2(x,y));t['filtered']=True
                    try:
                        if now<self.drive_until:
                            motor=self.motor_status()
                            if motor.get('arming'):
                                self.planner.phase='idle';self.planner.blocked_since=None
                            elif self.planner.phase=='reverse' and motor.get('esc_phase'):
                                # Recovery duration starts AFTER the ESC brake/neutral sequence.
                                self.planner.until=now+self.planner.config.reverse_duration_s
                        self.output=self.planner.step(v,self.scan,now,time.time())
                        self.errors.pop('planner',None)
                    except Exception as exc:
                        self.errors['planner']=str(exc)
                        self.output=dict(mode=self.planner.mode,state='stop',reason='Données invalides : calcul arrêté.',
                            intent=dict(motion='stop',speed_m_s=0,steering_deg=0,steering_normalized=0,ttl_ms=300),
                            motor_control=False,advisory_only=True)
                        self.planner.reset()
                    self.updated=time.monotonic();self.sequence+=1
                time.sleep(max(.01,.1-(time.monotonic()-now)))


def make_handler(fusion):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self,data,status=200):
            payload=json.dumps(data,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)))
            self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            route=urlparse(self.path).path
            try:
                if route=='/api/drive-intent':return self.send_json(fusion.drive_snapshot())
                if route=='/api/state':return self.send_json(fusion.snapshot())
                if route=='/api/intent':return self.send_json(fusion.snapshot()['plan'])
                if route in ('/stream/left','/stream/right','/stream/depth'):
                    # Stream proxy: browsers need only reach the fusion host.
                    with urlopen(fusion.vision_url+route,timeout=3) as stream:
                        self.send_response(200);self.send_header('Content-Type',stream.headers['Content-Type'])
                        self.send_header('Cache-Control','no-store');self.end_headers()
                        while True:
                            chunk=stream.read(8192)
                            if not chunk:break
                            self.wfile.write(chunk)
                    return
                paths={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
                if route not in paths:return self.send_error(404)
                p=ROOT/'static'/paths[route];data=p.read_bytes()
                types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css'}
                self.send_response(200);self.send_header('Content-Type',types[p.suffix]);self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
            except Exception as exc:self.send_error(502,str(exc))
        def do_POST(self):
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.send_json({'error':'Origine refusée.'},403)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384:raise ValueError('Corps JSON requis (16 Ko maximum).')
                if 'application/json' not in self.headers.get('Content-Type',''):raise ValueError('JSON requis.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('Objet JSON requis.')
                if self.path=='/api/pilot':fusion.pilot_action(data)
                elif self.path=='/api/drive':fusion.drive_action(data)
                elif self.path=='/api/config':fusion.configure(data)
                elif self.path=='/api/mode' and set(data)=={'mode'}:fusion.set_mode(data['mode'])
                elif self.path=='/api/similarity' and set(data)=={'similarity_threshold'}:
                    if fusion.demo:raise ValueError('Réglage indisponible en simulation.')
                    json_request(fusion.vision_url+'/api/following/settings',data)
                elif self.path=='/api/select' and set(data)=={'id','generation'}:
                    if fusion.demo:raise ValueError('La cible de démonstration est synthétique.')
                    json_request(fusion.vision_url+'/api/following/select',data)
                    with fusion.lock:fusion.planner.reset();fusion.output={};fusion.updated=0
                elif self.path=='/api/demo' and fusion.demo and data.get('scenario') in ('clear','near','obstacle_right','blocked','unknown_rear','trapped','lost','stale','close_obstacle'):
                    with fusion.lock:
                        fusion.scenario=data['scenario'];fusion.planner.reset();fusion.output={};fusion.updated=0
                else:return self.send_error(404)
                return self.send_json({'ok':True})
            except Exception as exc:return self.send_json({'error':str(exc)},400)
        def log_message(self,*args):pass
    return Handler


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vision-url',default='http://127.0.0.1:8080')
    p.add_argument('--lidar-url',default='http://127.0.0.1:8765')
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8081)
    p.add_argument('--config',type=Path);p.add_argument('--demo',action='store_true');a=p.parse_args()
    for url in (a.vision_url,a.lidar_url):
        parsed=urlparse(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username:p.error('URL HTTP(S) sans identifiants requise.')
    f=Fusion(a.vision_url,a.lidar_url,a.config or ROOT/('config-demo.json' if a.demo else 'config.json'),a.demo)
    server=ThreadingHTTPServer((a.host,a.port),make_handler(f));f.start()
    print(f'Fusion sur http://{a.host}:{a.port} — propositions uniquement, aucun moteur',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:f.running=False;server.server_close()
