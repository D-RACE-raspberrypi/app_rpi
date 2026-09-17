"""Same local-server tests on all desktop OSes, no Pi or motors required."""
import json,threading,unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from launch import handler

class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler('http://192.0.2.1:8081'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def test_interface_and_assets(self):
        for path in ('/','/pilot.js','/pilot.css','/map.js'):
            with urlopen(self.url+path) as r:self.assertEqual(r.status,200);self.assertGreater(len(r.read()),100)
    def test_fixed_pi(self):
        with urlopen(self.url+'/api/connection') as r:self.assertEqual(json.load(r),{'url':'http://192.0.2.1:8081'})
    def test_foreign_origin_and_host_rejected(self):
        for headers in ({'Origin':'http://other.invalid'},{'Host':'other.invalid'}):
            with self.assertRaises(HTTPError) as cm:urlopen(Request(self.url+'/api/connection',headers=headers))
            self.assertEqual(cm.exception.code,403);cm.exception.close()
    def test_arbitrary_paths_rejected(self):
        with self.assertRaises(HTTPError) as cm:urlopen(self.url+'/not-a-proxy')
        self.assertEqual(cm.exception.code,404);cm.exception.close()
if __name__=='__main__':unittest.main()
