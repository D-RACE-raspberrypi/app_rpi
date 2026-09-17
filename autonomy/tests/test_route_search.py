import math
import unittest
from planner import Config,Planner
from route_search import search,Field,integrate


def scan_points(points):
    ranges=[6.]*180
    for x,y in points:
        index=int(math.degrees(math.atan2(x,y))%360//2)
        ranges[index]=min(ranges[index],math.hypot(x,y))
    return ranges

class RouteTests(unittest.TestCase):
    def test_detour_turns_then_countersteers_and_stops_at_goal(self):
        c=Config(margin_m=0,horizon_m=2)
        ranges=scan_points([(-.1,.85),(.1,.85)])
        goal=(0,1.7);r=search(ranges,c,goal,max_seconds=1)
        self.assertTrue(r['reached'])
        controls=[s['steering_deg'] for s in r['segments']]
        self.assertTrue(any(v<0 for v in controls) and any(v>0 for v in controls))
        self.assertLess(math.dist(r['path'][-1],goal),.045)
        field=Field(ranges,c,goal)
        pose=(0.,0.,0.);idx=0
        for segment in r['segments']:
            start=pose
            count=segment['end_index']-idx+1
            for n in range(1,count+1):
                exact=integrate(start,segment['steering_deg'],segment['length_m']*n/count,c.wheelbase_m)
                self.assertLess(math.dist(exact[:2],r['path'][idx+n-1]),.003)
                self.assertIsNotNone(field.at(*exact[:2]))
                self.assertGreaterEqual(math.dist(exact[:2],(0,2.)),.3-1e-8)
            idx+=count;pose=exact
        self.assertGreater(r['clearance_m'],1.7) # Detour length can exceed direct distance.

    def test_person_and_obstacles_beyond_stop_do_not_change_route(self):
        c=Config(margin_m=0,horizon_m=2,obstacle_cost=5,obstacle_x=200,obstacle_y=200)
        free=search(scan_points([]),c,(0,1.7),max_seconds=1)
        behind=search(scan_points([(0,2.),(-.5,2.3),(.6,2.1)]),c,(0,1.7),max_seconds=1)
        self.assertTrue(behind['reached'])
        self.assertEqual(free['path'],behind['path'])
        self.assertEqual(behind['obstacle_penalty'],0)

    def test_beyond_goal_cannot_overlap_vehicle_at_destination(self):
        c=Config(margin_m=0,horizon_m=2)
        field=Field(scan_points([(0,1.75)]),c,(0,1.7))
        self.assertIsNone(field.at(0,1.7))

    def test_closed_front_does_not_produce_route(self):
        c=Config(margin_m=0,horizon_m=2)
        ranges=scan_points([(x*.05,.27) for x in range(-20,21)])
        r=search(ranges,c,(0,1.7),max_seconds=1)
        self.assertFalse(r['reached']);self.assertFalse(r['path'])

    def test_budget_is_reported_and_no_goal_claimed(self):
        r=search(scan_points([(0,.9)]),Config(margin_m=0),(0,1.7),max_nodes=1,max_seconds=1)
        self.assertFalse(r['reached']);self.assertTrue(r['search_limited'])

    def test_planner_standoff_independent_of_detour_budget(self):
        v=dict(state='ready',fresh=True,age_s=0,selection_state='visible',selected_id=1,generation=1,
            target=dict(distance_m=2,bearing_deg=0),approximate=False)
        ranges=scan_points([(0,2.)]);scan=dict(timestamp=1000,points=[dict(angle_deg=i*2+1,distance_mm=d*1000,quality=20) for i,d in enumerate(ranges)])
        p=Planner(Config(target_m=.3,margin_m=0,horizon_m=2));p.set_mode('autonomous')
        r=p.step(v,scan,0,1000)
        self.assertTrue(r['goal']['reached_by_plan'])
        self.assertAlmostEqual(r['chosen']['path'][-1][1],1.7,places=2)
        p.config.horizon_m=1
        r=p.step(v,scan,1,1000)
        self.assertTrue(r['goal']['reached_by_plan'])
        self.assertAlmostEqual(r['goal']['y_m'],1.7)
        self.assertAlmostEqual(r['chosen']['path'][-1][1],1.7,places=2)
