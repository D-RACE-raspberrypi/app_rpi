import copy,unittest
from motor_drive import command,Esc,NEUTRAL,Hardware,steering_pulse,CENTER,STEERING_MIN,STEERING_MAX

def packet():return dict(armed=True,demo=False,lease_until=11,plan_until=10.2,direction_verified=True,steering_sign=1,odometry_valid=True,mode='autonomous',speed_limit=.25,intent=dict(motion='forward',speed_m_s=.25,steering_normalized=.4))

class Tests(unittest.TestCase):
    def test_physical_steering_center_and_limits(self):
        self.assertEqual(steering_pulse(0),1566666)
        self.assertEqual(steering_pulse(-1),STEERING_MIN)
        self.assertEqual(steering_pulse(1),STEERING_MAX)
        self.assertLess(steering_pulse(-.2),CENTER)
        self.assertGreater(steering_pulse(.2),CENTER)
        h=Hardware();writes=[];h.write=lambda *args:writes.append(args)
        h.apply(NEUTRAL,0)
        self.assertEqual(writes,[(0,"duty_cycle",NEUTRAL),(1,"duty_cycle",1566666)])

    def test_forward_and_reverse_with_sign(self):
        p=packet();self.assertEqual(command(p,10)[0],(1.,.4))
        p['steering_sign']=-1;p['intent'].update(motion='reverse',speed_m_s=-.125)
        self.assertEqual(command(p,10)[0],(-.5,-.4))
    def test_guards_stop(self):
        for changes in ({'armed':False},{'demo':True},{'lease_until':9},{'plan_until':9},{'plan_until':float('nan')},{'direction_verified':False},{'steering_sign':0},{'odometry_valid':False},{'mode':'manual'}):
            p=packet();p.update(changes);self.assertIsNone(command(p,10)[0],changes)
    def test_invalid_commands_stop(self):
        for changes in ({'speed_m_s':float('nan')},{'speed_m_s':-.1},{'speed_m_s':.4},{'steering_normalized':2},{'motion':'wat'}):
            p=packet();p['intent'].update(changes);self.assertIsNone(command(p,10)[0],changes)
    def test_low_speed_not_forced_to_high_throttle(self):
        p=packet();p['intent']['speed_m_s']=.025
        self.assertAlmostEqual(command(p,10)[0][0],.1)
    def test_stop_interrupts_every_reverse_phase(self):
        for t in (.1,.6,1.):
            e=Esc();e.step(1,0);e.step(-1,.01);e.step(-1,t)
            self.assertEqual(e.step(0,t+.01),NEUTRAL)
            self.assertIsNone(e.phase)
    def test_reverse_timing(self):
        e=Esc();self.assertEqual(e.step(1,0),1575000)
        self.assertEqual(e.step(-1,1),NEUTRAL)
        self.assertEqual(e.step(-1,1.41),1425000)
        self.assertEqual(e.step(-1,1.92),NEUTRAL)
        self.assertEqual(e.step(-1,2.23),1425000)
        self.assertEqual(e.step(0,2.24),NEUTRAL)
    def test_manual_without_sensors_but_with_lease(self):
        p=packet();p.update(mode='manual',source='gamepad',odometry_valid=False,manual=dict(effort=.5,steering=-.4))
        self.assertEqual(command(p,10)[0],(.5,-.4))
        self.assertIsNone(command(p,11)[0])
        p['manual']['effort']=2;self.assertIsNone(command(p,10)[0])
    def test_four_manual_gears_match_group_formula(self):
        for gear in (1,2,3,4):
            for throttle in (-1.,-.4,0.,.4,1.):
                p=packet();p.update(mode='manual',source='gamepad',manual=dict(effort=throttle,steering=0.,gear=gear))
                effort,_=command(p,10)[0]
                esc=Esc();esc.last=-1
                self.assertEqual(esc.step(effort,10),1500000+round(throttle*37500*gear))
        for gear in (0,5,True,2.5):
            p['manual']['gear']=gear;self.assertIsNone(command(p,10)[0])
        auto=packet();auto['manual']={'gear':4}
        self.assertEqual(Esc().step(command(auto,10)[0][0],10),1575000)

    def test_frozen_packet_expires(self):
        p=packet();self.assertIsNotNone(command(p,10)[0]);self.assertIsNone(command(p,10.21)[0])

if __name__=='__main__':unittest.main()
