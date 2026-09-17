#!/usr/bin/env python3
"""Read-only lidar viewer; never controls hardware or serves directory listings."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route=self.path.split('?',1)[0]
        if route in ('/','/viewer.html'):
            data=(ROOT/'viewer.html').read_bytes();kind='text/html; charset=utf-8'
        elif route=='/scores.js':
            data=(ROOT/'scores.js').read_bytes();kind='text/javascript; charset=utf-8'
        elif route=='/api/latest':
            try:
                data=(ROOT/'latest.json').read_bytes()
            except FileNotFoundError:
                data=b'null'
            kind='application/json'
        elif route=='/api/scans':
            scans=[]
            try:
                with (ROOT/'scans.jsonl').open() as f:
                    for line in deque(f,maxlen=120):
                        try:
                            scan=json.loads(line)
                            if isinstance(scan,dict) and 'points' in scan and 'timestamp' in scan:
                                scans.append(scan)
                        except json.JSONDecodeError:
                            pass # Writer may be partway through the last line.
            except FileNotFoundError:
                pass
            data=json.dumps({'scans':scans},allow_nan=False).encode();kind='application/json'
        else:
            self.send_error(404);return
        self.send_response(200)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*args):pass
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--bind',default='0.0.0.0');a=p.parse_args()
    server=ThreadingHTTPServer((a.bind,a.port),Handler)
    print(f'Vue lidar sur le port {a.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
