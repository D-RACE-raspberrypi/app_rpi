import unittest,time
from pilot_session import PilotSession
from test_drive_api import DriveTests

def frame(seq,**kw):return dict(seq=seq,steer=.2,accel=0.,brake=0.,touch=False,connected=True,**kw)
class SessionTests(unittest.TestCase):
 def test_neutral_before_acceleration(self):
  s=PilotSession();p=frame(0);p['accel']=1;s.update(p,10);self.assertFalse(s.ready);self.assertEqual(s.effort,0)
  s.update(frame(1),10.1);p['seq']=2;s.update(p,10.2);self.assertEqual(s.effort,1)
 def test_one_toggle_per_press_and_transition_neutral(self):
  s=PilotSession();s.update(frame(0),10)
  p=frame(1);p['touch']=True;s.update(p,10.1);self.assertEqual(s.mode,'autonomous');self.assertFalse(s.ready)
  p['seq']=2;s.update(p,10.2);self.assertEqual(s.mode,'autonomous')
  s.update(frame(3),10.6);self.assertTrue(s.ready)
  p['seq']=4;s.update(p,10.7);self.assertEqual(s.mode,'manual');self.assertEqual(s.effort,0)
 def test_initial_held_touch_does_not_toggle(self):
  s=PilotSession();p=frame(0);p['touch']=True;s.update(p,10);self.assertEqual(s.mode,'manual')
 def test_expiry_invalid_and_duplicate(self):
  s=PilotSession();s.update(frame(0),10);self.assertFalse(s.status(10.4)['connected'])
  for p in (frame(0),dict(frame(1),steer=float('nan')),dict(frame(2),connected=False)):
   with self.assertRaises(ValueError):s.update(p,10.1)
class IntegrationTests(DriveTests):
 def pilot(self):
  f=self.make();f.drive_action(dict(action='direction',sign=1));f.pilot_action(dict(action='start',owner='abcdefgh',mode='manual'));return f
 def test_manual_does_not_need_vision_or_odometry(self):
  f=self.pilot();f.pilot_action(dict(frame(0),action='input',owner='abcdefgh'))
  f.pilot_action(dict(frame(1),action='input',owner='abcdefgh',accel=.5))
  p=f.drive_snapshot();self.assertEqual(p['mode'],'manual');self.assertEqual(p['manual']['effort'],.5);self.assertFalse(p['odometry_valid'])
 def test_old_or_foreign_inputs_cannot_drive(self):
  f=self.pilot()
  with self.assertRaises(ValueError):f.pilot_action(dict(frame(0),action='input',owner='stranger'))
  f.pilot_action(dict(frame(0),action='input',owner='abcdefgh'))
  with self.assertRaises(ValueError):f.pilot_action(dict(frame(0),action='input',owner='abcdefgh'))
  self.assertFalse(f.drive_snapshot()['armed'])
 def test_switch_suppresses_old_inputs(self):
  f=self.pilot();f.pilot_action(dict(frame(0),action='input',owner='abcdefgh'))
  f.pilot_action(dict(action='mode',owner='abcdefgh',mode='autonomous'))
  self.assertEqual(f.drive_snapshot()['manual']['effort'],0)
 def test_stop_clears_session(self):
  f=self.pilot();f.pilot_action(dict(action='stop'));self.assertIsNone(f.pilot);self.assertFalse(f.drive_snapshot()['armed'])
