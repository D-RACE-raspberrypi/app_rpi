import unittest
from test_moteurs import Sorties,NEUTRE,CENTRE

class Fake(Sorties):
    def __init__(self):super().__init__(True);self.ready=True;self.events=[];self.interrupt=False
    def ecrire(self,c,n,v):self.events.append((c,n,v))
    def attendre(self,d):
        if self.interrupt:raise KeyboardInterrupt
        return True

class Tests(unittest.TestCase):
    def test_each_action_finishes_neutral(self):
        for action in ('0','1','2','3','4','5'):
            s=Fake();s.action(action,1)
            self.assertEqual(s.events[-2:],[(0,'duty_cycle',NEUTRE),(1,'duty_cycle',CENTRE)])
    def test_interrupt_finishes_neutral(self):
        for action in ('1','2','3','4'):
            s=Fake();s.interrupt=True
            with self.assertRaises(KeyboardInterrupt):s.action(action,1)
            self.assertEqual(s.events[-2:],[(0,'duty_cycle',NEUTRE),(1,'duty_cycle',CENTRE)])
    def test_duration_cannot_be_unbounded(self):
        for d in (0,4,float('nan'),float('inf')):
            s=Fake()
            with self.assertRaises(ValueError):s.action('1',d)
            self.assertEqual(s.events,[])

if __name__=='__main__':unittest.main()
