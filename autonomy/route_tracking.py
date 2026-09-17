"""Persistent path in odometry frame, collision revalidation and pure pursuit."""
import copy,math
from odometry import world,local
from route_search import Field,integrate


def pursuit(path,c,lookahead=.28):
    # Rear axle origin matches the bicycle model used by route_search.
    point=path[-1]
    for p in path:
        if math.hypot(p[0],p[1]+c.wheelbase_m/2)>=lookahead:point=p;break
    x,y=point[0],point[1]+c.wheelbase_m/2
    steer=math.degrees(math.atan2(2*c.wheelbase_m*x,max(.001,x*x+y*y)))
    return max(-c.max_steering_deg,min(c.max_steering_deg,steer)),point


class RouteMemory:
    def __init__(self):self.clear()
    def clear(self):self.saved=None;self.epoch=None;self.target=None
    def choose(self,new,ranges,c,goal,pose,epoch):
        field=Field(ranges,c,goal);retained=False
        if self.saved is not None and epoch==self.epoch:
            old=copy.deepcopy(self.saved)
            path=[local(p,pose) for p in old['world_path']]
            nearest=min(range(len(path)),key=lambda i:math.hypot(*path[i]))
            if math.hypot(*path[nearest])<.18:
                path=path[nearest:]
                while path and path[0][1]<.015:path.pop(0)
                endpoint=math.hypot(path[-1][0]-goal[0],path[-1][1]-goal[1]) if path else 999
                if endpoint<.14 and len(path)>3 and all(field.at(*p) is not None for p in path):
                    # Re-evaluate BOTH proposals against today's observations and identical costs.
                    def cost(points):
                        total=0.;prev=(0.,0.)
                        for p in points:
                            risk=field.at(*p)
                            if risk is None:return float('inf')
                            d=math.dist(prev,p);prev=p
                            angle=abs(math.degrees(math.atan2(p[0],p[1])-math.atan2(goal[0],goal[1])))
                            total+=d*(1+risk[0]/50+c.unknown_cost*risk[1]/50+c.alignment_slope*angle/180)
                        return total
                    oldcost=cost(path);newcost=cost(new['path']) if new.get('path') else float('inf')
                    if oldcost<=newcost*1.15+.05:
                        old['path']=[list(p) for p in path];old['clearance_m']=sum(math.dist(a,b) for a,b in zip([(0,0)]+path,path))
                        old['reached']=endpoint<.045;old['search_cost']=oldcost;old['score']=50-10*oldcost
                        old['unknown_fraction']=max(field.at(*p)[1] for p in path)
                        old['unknown_penalty']=c.unknown_cost*old['unknown_fraction']
                        old['obstacle_penalty']=max(field.at(*p)[0] for p in path)
                        # These segments belong to the old origin; avoid publishing stale indices.
                        old['segments']=[];new=old;retained=True
        new['retained']=retained
        if new.get('path'):
            self.saved=copy.deepcopy(new);self.saved['world_path']=[world(p,pose) for p in new['path']];self.epoch=epoch
        else:self.clear()
        return new


def control(route,ranges,c,speed):
    if not route.get('path'):return None
    field=Field(ranges,c,route['path'][-1])
    # Shorten lookahead near bends; every resulting command is checked for collision.
    for lookahead in (.28,.22,.16):
        steering,point=pursuit(route['path'],c,lookahead)
        limited=min(speed,.25/(1+abs(math.tan(math.radians(steering)))*2))
        travel=limited*c.reaction_s+limited*limited/(2*c.deceleration_m_s2)
        steps=max(2,math.ceil(travel/.02))
        if all(field.at(*integrate((0,0,0),steering,travel*j/steps,c.wheelbase_m)[:2]) is not None for j in range(1,steps+1)):
            return steering,limited,point
    return None



class TargetFilter:
    def __init__(self):self.key=None;self.point=None;self.stamp=None;self.velocity=(0.,0.)
    def update(self,point,key,stamp):
        if self.key!=key or self.point is None or stamp-self.stamp>1 or stamp<self.stamp:
            self.key=key;self.point=point;self.velocity=(0.,0.)
        elif stamp>self.stamp:
            dt=stamp-self.stamp;alpha=1-math.exp(-dt/.20)
            # Large displacement resets instead of dragging the target across the scene.
            if math.dist(point,self.point)>.8:self.point=point;self.velocity=(0.,0.)
            else:
                old=self.point;self.point=tuple(a+alpha*(b-a) for a,b in zip(old,point))
                self.velocity=tuple(.7*v+.3*(b-a)/dt for v,a,b in zip(self.velocity,old,self.point))
        self.stamp=stamp;return self.point
