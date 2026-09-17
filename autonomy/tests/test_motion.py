import unittest,math,copy
import numpy as np
from odometry import register,world,local
from route_tracking import RouteMemory,TargetFilter,control
from route_search import search
from planner import Config
from server import ScanWindow

class MotionTests(unittest.TestCase):
    def test_rigid_motion_registration(self):
        rng=np.random.default_rng(4);previous=rng.uniform(-2,2,(170,2));pose=(.035,.07,.04)
        current=np.array([local(p,pose) for p in previous])
        fitted=register(current,previous,.04)
        self.assertIsNotNone(fitted)
        for actual,expected in zip(fitted[0],pose):self.assertAlmostEqual(actual,expected,places=2)
    def test_single_wall_rejected(self):
        cloud=np.array([(i*.02,1) for i in range(100)])
        self.assertIsNone(register(cloud,cloud,0))
    def test_transforms_roundtrip(self):
        p=(.3,2);pose=(2,3,.7)
        np.testing.assert_allclose(local(world(p,pose),pose),p)
    def test_scan_compensation(self):
        c=Config();window=ScanWindow(c)
        window.add(dict(timestamp=10,points=[dict(angle_deg=0,distance_mm=2000,quality=10)],_pose=(0,0,0),_pose_epoch=1))
        window.add(dict(timestamp=10.2,points=[dict(angle_deg=0,distance_mm=1900,quality=10)],_pose=(0,.1,0),_pose_epoch=1))
        result=window.snapshot(10.25,.8)
        self.assertEqual(len(result['points']),2)
        for p in result['points']:self.assertAlmostEqual(p['distance_mm'],1900)
        window.add(dict(timestamp=10.4,points=[],_pose=(0,0,0),_pose_epoch=2))
        self.assertEqual(window.snapshot(10.45,.8)['points'],[])
    def test_retained_route_and_new_obstacle(self):
        c=Config(target_m=.3,margin_m=0);ranges=[4.]*180;goal=(0,1.5)
        route=search(ranges,c,goal);memory=RouteMemory()
        memory.choose(route,ranges,c,goal,(0,0,0),1)
        chosen=memory.choose(search(ranges,c,(.01,1.5)),ranges,c,(.01,1.5),(0,0,0),1)
        self.assertTrue(chosen['retained'])
        blocked=list(ranges);blocked[0]=.5
        chosen=memory.choose(dict(path=[]),blocked,c,goal,(0,0,0),1)
        self.assertFalse(chosen['retained']);self.assertEqual(chosen['path'],[])
    def test_pursuit_validates_actual_arc(self):
        c=Config(margin_m=0)
        route=dict(path=[[0,.04*i] for i in range(1,31)])
        self.assertIsNotNone(control(route,[4.]*180,c,.2))
        ranges=[4.]*180;ranges[0]=.3
        self.assertIsNone(control(route,ranges,c,.25))
    def test_filter_resets_on_identity_or_epoch(self):
        f=TargetFilter();f.update((0,2),1,10);p=f.update((.1,2),1,10.1)
        self.assertGreater(p[0],0);self.assertLess(p[0],.1)
        self.assertEqual(f.update((1,2),2,10.2),(1,2))
