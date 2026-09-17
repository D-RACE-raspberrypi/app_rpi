"""Bounded hybrid A*: continuous bicycle motions, discretized search states.
Coordinates refer to the axle midpoint, x right, y forward. No actuator access.
"""
import heapq
import math
import time


def integrate(pose,steering,travel,wheelbase):
    x,y,yaw=pose;k=math.tan(math.radians(steering))/wheelbase;turn=k*travel
    if abs(k)<1e-9:dx,dy=0.,travel
    else:dx=(1-math.cos(turn))/k+wheelbase/2*math.sin(turn);dy=math.sin(turn)/k+wheelbase/2*(math.cos(turn)-1)
    return x+math.cos(yaw)*dx+math.sin(yaw)*dy,y-math.sin(yaw)*dx+math.cos(yaw)*dy,yaw+turn


class Field:
    def __init__(self,ranges,c,goal):
        self.c=c;self.ranges=ranges;self.goal=goal;self.distance=math.hypot(*goal)
        self.axis=(goal[0]/max(self.distance,1e-9),goal[1]/max(self.distance,1e-9))
        self.cells={};self.points=[]
        # Existing footprint plus discretization margin; independent of horizon.
        self.radius=c.radius+.04
        self.max_radius=self.radius
        for i,d in enumerate(ranges):
            if d is None:continue
            a=math.radians(i*2+1);x=c.lidar_x_m+d*math.sin(a);y=c.lidar_y_m+d*math.cos(a)
            radius=self.radius+d*math.sin(math.radians(1))
            self.max_radius=max(self.max_radius,radius)
            point=(x,y,radius)
            self.points.append(point);self.cells.setdefault((math.floor(x/.3),math.floor(y/.3)),[]).append(point)

    def at(self,x,y):
        # Keep the centre on the approach side of the stopping plane.
        if x*self.axis[0]+y*self.axis[1]>self.distance+1e-8:return None
        reach=self.max_radius+.2;ix,iy=math.floor(x/.3),math.floor(y/.3);n=math.ceil(reach/.3)
        cost=0.
        for gx in range(ix-n,ix+n+1):
            for gy in range(iy-n,iy+n+1):
                for px,py,r in self.cells.get((gx,gy),()):
                    d=math.hypot(x-px,y-py)
                    if d<=r:return None
                    # Obstacles beyond the stopping plane never contribute to score.
                    if px*self.axis[0]+py*self.axis[1]>self.distance:continue
                    gap=d-r
                    if gap<=.2:
                        cost=max(cost,self.c.obstacle_cost*(self.c.obstacle_x+(self.c.obstacle_y-self.c.obstacle_x)*gap/.2))
        # Missing or occluded returns affect cost only (forward requests).
        unknown=0
        for dx,dy in [(0,0),(-self.radius,0),(self.radius,0),(0,self.radius),(0,-self.radius)]:
            rx,ry=x+dx-self.c.lidar_x_m,y+dy-self.c.lidar_y_m
            angle=math.degrees(math.atan2(rx,ry))%360
            d=self.ranges[int(angle//2)]
            unknown+=d is None or math.hypot(rx,ry)>d
        return cost,unknown/5


def search(ranges,c,goal,last_steering=0.,max_nodes=1800,max_seconds=.16):
    start_time=time.monotonic();field=Field(ranges,c,goal);distance=field.distance
    if distance<.001:return dict(path=[],segments=[],reached=True,expanded=0)
    # Nodes: pose, cost, length, parent index, samples, steering, risk totals.
    nodes=[((0.,0.,0.),0.,0.,-1,[],last_steering,0.,0.)]
    queue=[(distance,0)];seen={};expanded=0;found=None;best=0;best_distance=distance
    primitive=.16;budget=distance+c.horizon_m
    def key(p):return round(p[0]/.06),round(p[1]/.06),round(math.degrees(p[2])/10)%36
    seen[key(nodes[0][0])]=0.
    while queue and expanded<max_nodes and time.monotonic()-start_time<max_seconds:
        _,index=heapq.heappop(queue);pose,g,length,parent,samples,previous,obs_total,unknown_total=nodes[index]
        if g>seen.get(key(pose),float('inf'))+1e-8:continue
        x,y,yaw=pose;remaining=math.hypot(goal[0]-x,goal[1]-y)
        if remaining<.045 and index:
            found=index;break
        if remaining<best_distance:best=index;best_distance=remaining
        expanded+=1
        local_x=math.cos(yaw)*(goal[0]-x)-math.sin(yaw)*(goal[1]-y)
        desired=max(-c.max_steering_deg,min(c.max_steering_deg,math.degrees(math.atan2(2*c.wheelbase_m*local_x,max(.01,remaining**2)))))
        controls=sorted(set([c.max_steering_deg*i/3 for i in range(-3,4)]+[desired]))
        for steer in controls:
            travel=min(primitive,remaining)
            if length+travel>budget:continue
            steps=max(1,math.ceil(travel/.04));points=[];obs=unknown=0.;end=None
            for j in range(1,steps+1):
                end=integrate(pose,steer,travel*j/steps,c.wheelbase_m)
                risk=field.at(end[0],end[1])
                if risk is None:break
                points.append(end);obs+=risk[0]/steps;unknown+=risk[1]/steps
            if len(points)!=steps:continue
            delta_angle=abs(math.degrees(math.atan2(end[0],end[1]))-math.degrees(math.atan2(goal[0],goal[1])))
            # Length is a path-search cost, not a bonus rewarding clearance.
            cost=g+travel*(1+obs/50+c.unknown_cost*unknown/50+c.alignment_slope*delta_angle/180)+.002*abs(steer-previous)/c.max_steering_deg
            k=key(end)
            if cost>=seen.get(k,float('inf')):continue
            seen[k]=cost;node=len(nodes);nodes.append((end,cost,length+travel,index,points,steer,obs_total+obs*travel,unknown_total+unknown*travel))
            heuristic=math.hypot(goal[0]-end[0],goal[1]-end[1])
            heapq.heappush(queue,(cost+1.4*heuristic,node))
    reached=found is not None;index=found if reached else best
    # No usable progress: let the caller stop/recover instead of issuing a dead path.
    if index==0 or (not reached and best_distance>distance-.2):
        return dict(path=[],segments=[],reached=False,expanded=expanded,search_limited=bool(queue),elapsed_ms=round((time.monotonic()-start_time)*1000,1))
    chain=[]
    while index:
        chain.append(nodes[index]);index=nodes[index][3]
    chain.reverse();path=[];segments=[];travel=0.
    for pose,g,length,parent,points,steer,obs,unknown in chain:
        path.extend([[round(p[0],4),round(p[1],4)] for p in points])
        segments.append(dict(steering_deg=round(steer,3),length_m=round(length-travel,4),end_index=len(path)-1))
        travel=length
    last=chain[-1];steer=chain[0][5]
    return dict(path=path,segments=segments,reached=reached,expanded=expanded,search_limited=not reached and bool(queue),
        elapsed_ms=round((time.monotonic()-start_time)*1000,1),steering_deg=round(steer,3),steering_normalized=steer/c.max_steering_deg,
        clearance_m=round(travel,4),unknown_fraction=last[7]/travel,unknown_penalty=c.unknown_cost*last[7]/travel,
        obstacle_penalty=last[6]/travel,score=round(50-last[1]*10,2),alignment_bonus=50.,
        direction_deg=round(math.degrees(math.atan2(path[-1][0],path[-1][1])),2),reverse=False,allowed=True,
        reason='goal' if reached else 'partial',search_cost=round(last[1],3))
