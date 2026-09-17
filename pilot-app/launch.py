#!/usr/bin/env python3
"""Local cockpit: localhost permits browser Gamepad API; fixed upstream Pi proxy."""
import argparse,json,webbrowser,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parent

def handler(upstream):
 class Handler(BaseHTTPRequestHandler):
  def reply(self,code,data,kind='application/json'):
   self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
  def request(self):
   if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
    return self.reply(403,b'{"error":"Host refuse"}')
   origin=self.headers.get('Origin')
   if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.reply(403,b'{"error":"Origine refusee"}')
   try:
    if self.command=='GET' and self.path=='/api/connection':return self.reply(200,json.dumps({'url':upstream}).encode())
    if self.command=='GET' and self.path in ('/','/pilot.js','/pilot.css','/map.js'):
     path=ROOT/('index.html' if self.path=='/' else self.path[1:]);return self.reply(200,path.read_bytes(),{'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css'}[path.suffix])
    allowed=('/api/state','/api/vision') if self.command=='GET' else ('/api/pilot','/api/config','/api/select','/api/mode')
    if self.path not in allowed:return self.reply(404,b'{}')
    data=None
    if self.command=='POST':
     n=int(self.headers.get('Content-Length','0'))
     if not 0<n<=16384:raise ValueError('Requete invalide')
     if 'application/json' not in self.headers.get('Content-Type',''):raise ValueError('JSON requis')
     data=self.rfile.read(n)
    req=Request(upstream+self.path,data=data,headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=2) as r:self.reply(r.status,r.read())
   except HTTPError as e:self.reply(e.code,e.read())
   except (BrokenPipeError,ConnectionResetError):pass
   except Exception as e:self.reply(502,json.dumps({'error':str(e)}).encode())
  do_GET=request;do_POST=request
  def log_message(self,*a):pass
 return Handler
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--pi',default='10.215.13.38');p.add_argument('--port',type=int,default=8090);p.add_argument('--no-browser',action='store_true');p.add_argument('--ask-ip',action='store_true',help='Demander l’adresse du Pi au lancement');a=p.parse_args()
 if a.ask_ip:a.pi=input(f'Adresse du Pi [{a.pi}] : ').strip() or a.pi
 if not a.pi or any(c not in '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-' for c in a.pi):p.error('Adresse du Pi invalide')
 url=f'http://localhost:{a.port}/'
 try:server=ThreadingHTTPServer(('127.0.0.1',a.port),handler('http://'+a.pi+':8081'))
 except OSError:
  try:
   with urlopen(url+'api/connection',timeout=1) as response:existing=json.load(response)
   if existing.get('url')!='http://'+a.pi+':8081':raise ValueError()
  except Exception:p.error('Port occupé : fermer l’autre application ou choisir --port 8091.')
  if not a.no_browser:webbrowser.open(url)
  print('Application déjà ouverte : '+url);sys.exit(0)
 print('D-RACE : '+url,flush=True)
 if not a.no_browser:webbrowser.open(url)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
