import unittest
import numpy as np
from identity_memory import IdentityMemory

def feature(index):
    a=np.zeros(20);a[index]=1
    return [a,a,a]

class IdentityTests(unittest.TestCase):
    def test_new_id_requires_six_confirmations(self):
        m=IdentityMemory();m.select(1,feature(0),0)
        m.update([],{},.1)
        for t in (2,2.1,2.2,2.3,2.4):self.assertIsNone(m.update([{'id':5}],{5:feature(0)},t))
        self.assertEqual(m.update([{'id':5}],{5:feature(0)},2.5),5)
        self.assertEqual(m.serial,1)
    def test_ambiguous_people_never_reacquired(self):
        m=IdentityMemory();m.select(1,feature(0),0)
        for t in (2,3,4,5,6):self.assertIsNone(m.update([{'id':5},{'id':6}],{5:feature(0),6:feature(0)},t))
        self.assertEqual(m.state,'ambiguous')
    def test_reused_id_wrong_appearance_rejected(self):
        m=IdentityMemory();m.select(1,feature(0),0)
        self.assertIsNone(m.update([{'id':1}],{1:feature(1)},.1))
    def test_expiration_and_release(self):
        m=IdentityMemory();m.select(1,feature(0),0)
        self.assertIsNone(m.update([{'id':1}],{1:feature(0)},61));self.assertEqual(m.state,'reselect')
        m.clear();self.assertIsNone(m.update([{'id':1}],{1:feature(0)},62))

    def test_known_other_person_vetoes_match(self):
        m=IdentityMemory();m.select(1,feature(0),0,negatives=[feature(0)])
        for t in (2,3,4,5,6,7):
            self.assertIsNone(m.update([{'id':5}],{5:feature(0)},t))
