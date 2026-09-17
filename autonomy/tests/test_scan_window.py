import unittest
from server import ScanWindow
from planner import Config, ranges_from_scan

class ScanWindowTests(unittest.TestCase):
    def scan(self,t,angle=0,d=2000):
        return dict(timestamp=t,points=[dict(angle_deg=angle,distance_mm=d,quality=15)])

    def test_three_distinct_turns_fill_holes_keep_nearest(self):
        w=ScanWindow()
        for s in [self.scan(10,0,500),self.scan(10.2,2),self.scan(10.4,0,2500)]:w.add(s)
        w.add(self.scan(10.4,0,2500))
        merged=w.snapshot(10.45,.8)
        self.assertEqual(merged['turns'],3)
        r=ranges_from_scan(merged,Config())
        self.assertEqual(r[:3],[.5,2,None])
        w.add(self.scan(10.6,4))
        self.assertEqual(w.snapshot(10.61,.8)['turns'],3)
        self.assertEqual(ranges_from_scan(w.snapshot(10.61,.8),Config())[0],2.5)

    def test_each_turn_expires_without_refreshing_old_measurements(self):
        w=ScanWindow();w.add(self.scan(10));w.add(self.scan(10.4,2))
        self.assertEqual(w.snapshot(10.61,.8)['turns'],1)
        self.assertIsNone(w.snapshot(11.01,.8))

    def test_age_limit_future_invalid_and_source_restart(self):
        w=ScanWindow();w.add(self.scan(10))
        self.assertIsNone(w.snapshot(10.3,.2))
        w.add(self.scan(20));self.assertIsNone(w.snapshot(19,.8))
        w.add(self.scan(20));w.add(self.scan(19))
        self.assertEqual(w.snapshot(19.1,.8)['turns'],1)
        w.add(None);self.assertIsNone(w.snapshot(19.1,.8))
