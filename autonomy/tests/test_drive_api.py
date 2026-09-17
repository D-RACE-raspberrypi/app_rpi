import unittest,tempfile,time
from pathlib import Path
from server import Fusion

class DriveTests(unittest.TestCase):
    def make(self,demo=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        f=Fusion('http://localhost:8080','http://localhost:8765',Path(tmp.name)/'config.json',demo)
        f.motor_status=lambda:dict(boot_id='fake',connected=True)
        f.planner.config.target_m=1.;return f
    def test_never_armed_at_boot(self):
        f=self.make();self.assertFalse(f.drive_snapshot()['armed'])
    def test_unknown_direction_and_demo_rejected(self):
        for f in (self.make(),self.make(True)):
            with self.assertRaises(ValueError):f.drive_action(dict(action='start',owner='abcdefgh'))
    def test_lease_ownership_expiry_and_stop(self):
        f=self.make();f.drive_action(dict(action='direction',sign=-1));f.drive_action(dict(action='start',owner='abcdefgh'))
        self.assertTrue(f.drive_snapshot()['armed']);self.assertEqual(f.planner.mode,'autonomous')
        with self.assertRaises(ValueError):f.drive_action(dict(action='heartbeat',owner='other-user'))
        f.drive_until=time.monotonic()-1
        with self.assertRaises(ValueError):f.drive_action(dict(action='heartbeat',owner='abcdefgh'))
        f.drive_action(dict(action='stop'));self.assertEqual(f.planner.mode,'manual')
        self.assertFalse(f.drive_snapshot()['armed'])
    def test_setting_direction_during_motion_rejected(self):
        f=self.make();f.drive_action(dict(action='direction',sign=1));f.drive_action(dict(action='start',owner='abcdefgh'))
        with self.assertRaises(ValueError):f.drive_action(dict(action='direction',sign=-1))
