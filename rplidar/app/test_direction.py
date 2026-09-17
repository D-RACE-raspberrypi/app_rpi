import unittest
from direction import plan

def scene(obstacle=None, unknown=False):
    points=[]
    for a in range(360):
        d=4000
        if obstacle and abs((a-obstacle[0]+180)%360-180)<8:
            d=obstacle[1]
        if unknown: d=0
        points.append(dict(angle_deg=a,distance_mm=d,quality=15))
    return dict(timestamp=100,points=points)

class DirectionTests(unittest.TestCase):
    def test_open_space_follows_target(self):
        for target in (-45,0,30,70):
            r=plan(scene(),target=target,now=100)
            self.assertEqual(r['proposed_direction']['angle_deg'],target)
    def test_obstacle_selects_another_direction(self):
        r=plan(scene((30,800)),target=30,now=100)
        self.assertIsNotNone(r['proposed_direction'])
        self.assertNotEqual(r['proposed_direction']['angle_deg'],30)
    def test_close_obstacle_stops(self):
        r=plan(scene((30,150)),now=100)
        self.assertEqual(r['status'],'STOP_AUCUN_PASSAGE')
    def test_unknown_stops(self):
        r=plan(scene(unknown=True),now=100)
        self.assertEqual(r['status'],'STOP_AUCUN_PASSAGE')
    def test_stale_scan_stops(self):
        r=plan(scene(),now=103)
        self.assertEqual(r['status'],'STOP_SCAN_PERIME')
        self.assertIsNone(r['proposed_direction'])
    def test_orientation(self):
        r=plan(scene((90,800)),target=0,front=90,now=100)
        self.assertNotEqual(r['proposed_direction']['angle_deg'],0)

if __name__=='__main__':
    unittest.main()
