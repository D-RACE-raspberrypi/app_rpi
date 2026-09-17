import json
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planner import Config,Planner,arc,ranges_from_scan,corridor,obstacle_direction_penalty
from server import demo_sensors,Fusion
from route_search import Field,integrate


class PlanningTests(unittest.TestCase):
    def setup_scene(self,scenario='clear',**kwargs):
        p=Planner(Config(target_m=1.5,**kwargs));p.set_mode('autonomous')
        v,s=demo_sensors(scenario);s['timestamp']=1000
        return p,v,s
    def test_manual_and_distance_required(self):
        p=Planner();v,s=demo_sensors('clear')
        self.assertEqual(p.step(v,s,0,time.time())['state'],'manual')
        p.set_mode('autonomous')
        self.assertEqual(p.step(v,s,0,time.time())['state'],'setup')
    def test_manual_displays_fresh_measurements_without_motion(self):
        p=Planner();v,s=demo_sensors('clear')
        r=p.step(v,s,0,time.time())
        self.assertIsNotNone(r['target'])
        self.assertEqual(r['target']['distance_m'],round(v['target']['distance_m'],3))
        self.assertEqual(r['target']['bearing_deg'],round(v['target']['bearing_deg'],2))
        self.assertIsNone(r['target']['error_m'])
        self.assertEqual(r['intent']['motion'],'stop')
        v['age_s']=10
        self.assertIsNone(p.step(v,s,1,time.time())['target'])
        v['age_s']=0;v['selection_state']='lost'
        self.assertIsNone(p.step(v,s,2,time.time())['target'])

    def test_small_target_angle_matches_displayed_endpoint(self):
        p,v,s=self.setup_scene()
        v['target']['bearing_deg']=-5
        p.last_steering=-6.25
        result=p.step(v,s,0,1000)
        chosen=result['chosen']
        self.assertIsNotNone(chosen)
        x,y=chosen['path'][-1]
        self.assertAlmostEqual(math.degrees(math.atan2(x,y)),-5,delta=.2)
        self.assertAlmostEqual(chosen['direction_deg'],-5,delta=.2)

    def test_clear_space_follows_bearing(self):
        p,v,s=self.setup_scene();r=p.step(v,s,0,1000)
        self.assertEqual(r['intent']['motion'],'forward')
        self.assertGreater(r['intent']['steering_deg'],0)
        self.assertFalse(r['motor_control']);self.assertTrue(r['advisory_only'])
    def test_obstacle_limits_path_and_speed(self):
        p,v,s=self.setup_scene('obstacle_right');r=p.step(v,s,0,1000)
        self.assertEqual(r['state'],'following')
        chosen=r['chosen']
        self.assertTrue(chosen['allowed'])
        self.assertGreaterEqual(chosen['clearance_m'],.2)
        field=Field(ranges_from_scan(s,p.config),p.config,(r['goal']['local_x_m'],r['goal']['local_y_m']))
        for x,y in chosen['path']:
            self.assertIsNotNone(field.at(x,y))
        speed=r['intent']['speed_m_s']
        self.assertLessEqual(speed*p.config.reaction_s+speed**2/(2*p.config.deceleration_m_s2),chosen['clearance_m']-.08+.002)
        for candidate in r['candidates']:
            if candidate.get('segments'):continue
            expected=round(candidate['alignment_bonus']-candidate['obstacle_penalty']-candidate['unknown_penalty']-.5*abs(candidate['steering_deg'])/p.config.max_steering_deg,2)
            self.assertAlmostEqual(candidate['score'],expected,delta=.01)
    def test_hold_distance_hysteresis(self):
        p,v,s=self.setup_scene('near');self.assertEqual(p.step(v,s,0,1000)['state'],'hold_distance')
        v['target']['distance_m']=1.7
        self.assertEqual(p.step(v,s,.1,1000)['state'],'hold_distance')
        v['target']['distance_m']=1.9
        self.assertEqual(p.step(v,s,.2,1000)['state'],'following')
    def test_lost_unknown_stale_invalid_are_stops(self):
        for scenario in ('lost','stale','close_obstacle'):
            p,v,s=self.setup_scene(scenario)
            if scenario=='stale':s['timestamp']=990
            with self.subTest(scenario=scenario):self.assertEqual(p.step(v,s,0,1000)['intent']['motion'],'stop')
        for key,val in [('distance_m',None),('distance_m',float('nan')),('bearing_deg',float('inf'))]:
            p,v,s=self.setup_scene();v['target'][key]=val
            self.assertEqual(p.step(v,s,0,1000)['state'],'no_depth')
        p,v,s=self.setup_scene();s['timestamp']=1001
        self.assertEqual(p.step(v,s,0,1000)['state'],'lidar_stale')
        s['timestamp']=1000;v['age_s']=2
        self.assertEqual(p.step(v,s,0,1000)['state'],'target_lost')
    def test_reverse_requires_observed_rear(self):
        for scenario in ('unknown_rear','trapped'):
            p,v,s=self.setup_scene(scenario);p.step(v,s,0,1000)
            self.assertEqual(p.step(v,s,1.1,1000)['intent']['motion'],'stop')
        p,v,s=self.setup_scene('blocked');p.step(v,s,0,1000)
        r=p.step(v,s,1.1,1000)
        self.assertEqual(r['intent']['motion'],'reverse')
        self.assertLess(r['intent']['speed_m_s'],0)
        self.assertLess(r['intent']['steering_deg'],0) # reversing left turns body right
    def test_reverse_duration_pause_and_attempt_limit(self):
        p,v,s=self.setup_scene('blocked')
        for t,want in [(0,'blocked_wait'),(1.1,'reversing'),(2.2,'shift_pause'),(2.4,'shift_pause'),(2.8,'blocked_wait'),(4,'reversing'),(5.1,'shift_pause'),(5.7,'blocked')]:
            self.assertEqual(p.step(v,s,t,1000)['state'],want)
        self.assertEqual(p.attempts,2)
    def test_reverse_stops_immediately_when_rear_becomes_blocked(self):
        p,v,s=self.setup_scene('blocked');p.step(v,s,0,1000);p.step(v,s,1.1,1000)
        _,blocked=demo_sensors('trapped');blocked['timestamp']=1000
        self.assertEqual(p.step(v,blocked,1.2,1000)['intent']['motion'],'stop')
    def test_sensor_loss_cancels_recovery(self):
        p,v,s=self.setup_scene('blocked');p.step(v,s,0,1000);p.step(v,s,1.1,1000)
        s['timestamp']=990
        self.assertEqual(p.step(v,s,1.2,1000)['intent']['motion'],'stop')
        self.assertEqual(p.phase,'idle')
    def test_narrow_unknown_gaps_penalized_and_obstacles_still_block(self):
        c=Config();ranges=[3.]*180
        clear=corridor(ranges,c,0)
        ranges[5]=None;ranges[9]=None
        gaps=corridor(ranges,c,0)
        self.assertEqual(gaps['clearance_m'],clear['clearance_m'])
        self.assertGreater(gaps['unknown_penalty'],0)
        ranges[0]=.4
        self.assertEqual(corridor(ranges,c,0)['reason'],'obstacle')
        ranges=[3.]*180;ranges[90]=None
        self.assertEqual(corridor(ranges,c,0,True)['reason'],'unknown')

    def test_unknown_cost_changes_penalty_and_validates(self):
        ranges=[3.]*180;ranges[5]=None
        low=corridor(ranges,Config(unknown_cost=0),0)
        high=corridor(ranges,Config(unknown_cost=100),0)
        self.assertEqual(low['unknown_penalty'],0)
        self.assertGreater(high['unknown_penalty'],0)
        self.assertEqual(low['clearance_m'],high['clearance_m'])
        for value in (-1,101,float('nan')):
            with self.assertRaises(ValueError):Config.validated({'unknown_cost':value})

    def test_score_controls_and_collision_guard(self):
        p,v,s=self.setup_scene(alignment_slope=0,obstacle_cost=0)
        r=p.step(v,s,0,1000)
        self.assertTrue(all(x['alignment_bonus']==50 and x['obstacle_penalty']==0 for x in r['candidates']))
        p.config.alignment_slope=5;p.config.obstacle_cost=5
        r=p.step(v,s,.1,1000)
        straight=next(x for x in r['candidates'] if x['steering_deg']==0)
        self.assertAlmostEqual(straight['alignment_bonus'],50-5*25)
        self.assertGreaterEqual(straight['obstacle_penalty'],0)
        p,v,s=self.setup_scene('close_obstacle',obstacle_cost=0)
        self.assertEqual(p.step(v,s,0,1000)['intent']['motion'],'stop')
        for key in ('alignment_slope','obstacle_cost'):
            for value in (-1,6,float('nan')):
                with self.assertRaises(ValueError):Config.validated({key:value})

    def test_obstacle_profile_in_metres(self):
        c=Config(obstacle_x=80,obstacle_y=20)
        ranges=[None]*180;ranges[0]=1.
        self.assertAlmostEqual(obstacle_direction_penalty(ranges,c,1),80)
        self.assertAlmostEqual(obstacle_direction_penalty(ranges,c,1+math.degrees(math.asin(.1))),50,places=2)
        self.assertAlmostEqual(obstacle_direction_penalty(ranges,c,1+math.degrees(math.asin(.2))),20,places=2)
        self.assertEqual(obstacle_direction_penalty(ranges,c,1+math.degrees(math.asin(.21))),0)
        self.assertEqual(obstacle_direction_penalty(ranges,c,181),0)
        ranges[0]=3
        self.assertEqual(obstacle_direction_penalty(ranges,c,1),0)
        for name in ('obstacle_x','obstacle_y'):
            with self.assertRaises(ValueError):Config.validated({name:-1})

    def test_unknown_majority_does_not_reject_forward(self):
        ranges=[None]*180;ranges[90]=3.
        path=corridor(ranges,Config(unknown_cost=0),0)
        self.assertEqual(path['clearance_m'],1.)
        self.assertEqual(path['unknown_fraction'],1.)
        self.assertEqual(path['unknown_penalty'],0)
        ranges[0]=.4
        self.assertEqual(corridor(ranges,Config(),0)['reason'],'obstacle')

    def test_beyond_range_target_can_be_followed_as_lower_bound(self):
        p,v,s=self.setup_scene()
        v['target'].update(distance_m=4.,distance_status='beyond_range')
        r=p.step(v,s,0,1000)
        self.assertEqual(r['target']['distance_status'],'beyond_range')
        self.assertEqual(r['intent']['motion'],'forward')
        p.config.target_m=5
        self.assertEqual(p.step(v,s,1,1000)['intent']['motion'],'stop')

    def test_unknown_is_not_free(self):
        p,v,s=self.setup_scene();s['points']=[]
        r=p.step(v,s,0,1000);self.assertEqual(r['intent']['motion'],'stop')
        s['points']=[dict(angle_deg=i,distance_mm=0,quality=10) for i in range(360)]
        self.assertTrue(all(d is None for d in ranges_from_scan(s,p.config)))
    def test_no_lidar_keeps_target_but_proposes_stop(self):
        p,v,_=self.setup_scene()
        r=p.step(v,None,0,1000)
        self.assertEqual(r['state'],'lidar_unavailable')
        self.assertIsNotNone(r['target'])
        self.assertEqual(r['intent']['motion'],'stop')
    def test_speed_has_stopping_room(self):
        for scenario in ('clear','obstacle_right'):
            p,v,s=self.setup_scene(scenario);r=p.step(v,s,0,1000);speed=r['intent']['speed_m_s']
            stopping=speed*p.config.reaction_s+speed*speed/(2*p.config.deceleration_m_s2)
            self.assertLessEqual(stopping,r['chosen']['clearance_m']-.075)
    def test_camera_offset_transforms_target(self):
        p,v,s=self.setup_scene(camera_x_m=.2,camera_y_m=.1);v['target'].update(distance_m=2,bearing_deg=0)
        r=p.step(v,s,0,1000)
        self.assertAlmostEqual(r['target']['distance_m'],math.hypot(.2,2.1),places=3)
        self.assertGreater(r['target']['bearing_deg'],0)
    def test_kinematics_and_mirror(self):
        x,y,yaw=arc(20,.3,.2);mx,my,myaw=arc(-20,.3,.2)
        self.assertAlmostEqual(x,-mx);self.assertAlmostEqual(y,my);self.assertAlmostEqual(yaw,-myaw)
        self.assertLess(arc(20,-.3,.2)[2],0)
    def test_invalid_config(self):
        for config in [{'target_m':float('nan')},{'wheelbase_m':2},{'lidar_sign':0},{'reverse_attempts':1.5},{'geometry_confirmed':1},{'unknown':2}]:
            with self.subTest(config=config),self.assertRaises(ValueError):Config.validated(config)
    def test_intent_expires_and_mode_change_invalidates_output(self):
        with tempfile.TemporaryDirectory() as folder:
            f=Fusion('http://localhost:8080','http://localhost:8765',Path(folder)/'config.json')
            f.configure({'target_m':1.5});f.set_mode('autonomous')
            self.assertEqual(f.snapshot()['plan']['intent']['motion'],'stop')
            p,v,s=self.setup_scene();f.output=p.step(v,s,0,1000);f.updated=time.monotonic()-.4
            self.assertEqual(f.snapshot()['plan']['intent']['ttl_ms'],0)
            self.assertEqual(f.snapshot()['plan']['intent']['motion'],'stop')
            f.set_mode('manual');self.assertEqual(f.snapshot()['plan']['mode'],'manual')
            self.assertEqual(Fusion('x','y',f.path).planner.mode,'manual')

if __name__=='__main__':unittest.main()
