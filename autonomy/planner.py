"""Local advisory planner. Metres, seconds, 0° forward, positive right.
No hardware imports, PWM, joystick or motor output. Re-evaluate every 100 ms.
"""
from dataclasses import dataclass, asdict, replace
from route_search import search as search_route
import math
from route_tracking import RouteMemory, control


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def wrap(angle): return (angle+180)%360-180


@dataclass
class Config:
    alignment_slope: float = 1.
    obstacle_cost: float = 1.
    obstacle_x: float = 30.
    obstacle_y: float = 0.
    unknown_cost: float = 15.
    target_m: float | None = None
    tolerance_m: float = .15
    width_m: float = .20
    length_m: float = .30
    wheelbase_m: float = .20
    margin_m: float = .10
    max_steering_deg: float = 25.
    lidar_x_m: float = 0.
    lidar_y_m: float = 0.
    camera_x_m: float = 0.
    camera_y_m: float = 0.
    lidar_front_deg: float = 0.
    lidar_sign: int = 1
    max_forward_m_s: float = .25
    max_reverse_m_s: float = .12
    deceleration_m_s2: float = .5
    reaction_s: float = .4
    horizon_m: float = 1.
    max_age_s: float = .8
    blocked_delay_s: float = 1.
    reverse_duration_s: float = 1.
    shift_pause_s: float = .5
    reverse_attempts: int = 2
    geometry_confirmed: bool = False

    @classmethod
    def validated(cls, values):
        if not isinstance(values,dict) or set(values)-set(asdict(cls())):raise ValueError('Réglages inconnus.')
        c=cls(**values)
        limits={'obstacle_x':(0,200),'obstacle_y':(0,200),'alignment_slope':(0,5),'obstacle_cost':(0,5),'unknown_cost':(0,100),'target_m':(.3,10),'tolerance_m':(.05,.5),'width_m':(.1,1),
            'length_m':(.15,2),'wheelbase_m':(.1,1.5),'margin_m':(0,.5),
            'max_steering_deg':(5,40),'lidar_x_m':(-.5,.5),'lidar_y_m':(-1,1),
            'camera_x_m':(-.5,.5),'camera_y_m':(-1,1),'lidar_front_deg':(-180,180),
            'max_forward_m_s':(.05,.6),'max_reverse_m_s':(.03,.25),
            'deceleration_m_s2':(.1,2),'reaction_s':(.2,1),'horizon_m':(.3,2),
            'max_age_s':(.1,1),'blocked_delay_s':(.5,5),'reverse_duration_s':(.3,2),
            'shift_pause_s':(.3,2),'reverse_attempts':(1,3)}
        for key,(lo,hi) in limits.items():
            v=getattr(c,key)
            if key=='target_m' and v is None:continue
            if not finite(v) or not lo<=v<=hi:raise ValueError(f'{key} doit être entre {lo} et {hi}.')
        if type(c.lidar_sign) is not int or c.lidar_sign not in (-1,1):raise ValueError('Sens lidar : -1 ou +1.')
        if type(c.reverse_attempts) is not int:raise ValueError('Nombre de tentatives entier requis.')
        if type(c.geometry_confirmed) is not bool:raise ValueError('Confirmation de géométrie booléenne requise.')
        if c.wheelbase_m>c.length_m:raise ValueError('Empattement supérieur à la longueur.')
        if abs(c.lidar_x_m)>c.width_m/2 or abs(c.lidar_y_m)>c.length_m/2:
            raise ValueError('Ce modèle suppose le lidar à l’intérieur du gabarit de la voiture.')
        return c

    @property
    def radius(self):return math.hypot(self.width_m/2,self.length_m/2)+self.margin_m


def ranges_from_scan(scan,c):
    if not isinstance(scan,dict) or not isinstance(scan.get('points'),list):raise ValueError('Scan lidar absent ou invalide.')
    if not finite(scan.get('timestamp')):raise ValueError('Date lidar invalide.')
    if len(scan['points'])>20000:raise ValueError('Scan lidar trop volumineux.')
    ranges=[None]*180
    for p in scan['points']:
        if not isinstance(p,dict):continue
        a,d,q=p.get('angle_deg'),p.get('distance_mm'),p.get('quality')
        if not all(finite(v) for v in (a,d,q)) or d<=0 or q<=0:continue
        idx=int((c.lidar_sign*(a-c.lidar_front_deg)%360)//2)
        d=min(d/1000,6.)
        ranges[idx]=d if ranges[idx] is None else min(d,ranges[idx])
    return ranges


def obstacle_direction_penalty(ranges,c,heading):
    """Lateral distance to the candidate ray, in metres, not a fixed angle."""
    a=math.radians(heading);sx,sy=math.sin(a),math.cos(a)
    penalty=0.
    for i,d in enumerate(ranges):
        if d is None:continue
        angle=math.radians(i*2+1)
        x=c.lidar_x_m+d*math.sin(angle);y=c.lidar_y_m+d*math.cos(angle)
        if not 0<x*sx+y*sy<=c.horizon_m+c.radius:continue
        lateral=abs(x*sy-y*sx)
        if lateral>.2+1e-9:continue
        fraction=min(1.,lateral/.2)
        penalty=max(penalty,c.obstacle_x+(c.obstacle_y-c.obstacle_x)*fraction)
    return round(c.obstacle_cost*penalty,3)


def arc(steering_deg, travel_m, wheelbase):
    """Centre of axle midpoint; rear axle bicycle model; signed travel."""
    k=math.tan(math.radians(steering_deg))/wheelbase
    yaw=k*travel_m
    if abs(k)<1e-9:return 0.,travel_m,0.
    x=(1-math.cos(yaw))/k+wheelbase/2*math.sin(yaw)
    y=math.sin(yaw)/k+wheelbase/2*(math.cos(yaw)-1)
    return x,y,math.degrees(yaw)


def footprint_intersection(cx,cy,radius,angle):
    # Farthest intersection of the footprint disk with a ray from the lidar.
    dot=cx*math.sin(angle)+cy*math.cos(angle)
    disc=radius*radius-cx*cx-cy*cy+dot*dot
    return None if disc<0 else dot+math.sqrt(max(0,disc))


def close_obstacle(ranges,c):
    for i,d in enumerate(ranges):
        if d is None:continue
        # Every return is conservatively treated as occupying its whole 2° bin.
        for offset in (0,1,2):
            angle=math.radians(i*2+offset)
            x=c.lidar_x_m+d*math.sin(angle);y=c.lidar_y_m+d*math.cos(angle)
            if math.hypot(x,y)<=c.radius:return True
    return False


def corridor(ranges,c,steering,reverse=False):
    step=.04
    path=[];clearance=0.;reason='horizon';unknown_fraction=0.
    # Inflate for sampling in distance and angle, so gaps do not imply free space.
    r=c.radius+step+(c.horizon_m+c.radius+math.hypot(c.lidar_x_m,c.lidar_y_m))*math.sin(math.radians(1))
    rays=[]
    for i,d in enumerate(ranges):
        a=math.radians(i*2+1)
        initial=footprint_intersection(-c.lidar_x_m,-c.lidar_y_m,r,a)
        rays.append((a,d,initial))
    for n in range(1,math.ceil(c.horizon_m/step)+1):
        travel=min(n*step,c.horizon_m)
        x,y,yaw=arc(steering,-travel if reverse else travel,c.wheelbase_m)
        blocked=None;unknown=0;observed=0
        for a,d,initial in rays:
            far=footprint_intersection(x-c.lidar_x_m,y-c.lidar_y_m,r,a)
            if far is None or far<=0:continue
            # Initial footprint is assumed occupied by the vehicle; don't demand
            # visibility beneath it. Measured intrusions are checked separately.
            if initial is not None and far<=initial+1e-8:continue
            if d is None:
                unknown+=1
                if reverse:blocked='unknown';break
                continue
            observed+=1
            if far>=d:blocked='obstacle';break
        fraction=unknown/max(1,unknown+observed)
        # Unknown sectors affect forward scoring only; reverse stays strict.
        if blocked:reason=blocked;break
        unknown_fraction=max(unknown_fraction,fraction)
        path.append([round(x,3),round(y,3)]);clearance=travel
    return dict(steering_deg=round(steering,2),steering_normalized=round(steering/c.max_steering_deg,3),
                reverse=reverse,clearance_m=round(clearance,3),reason=reason,path=path,
                unknown_fraction=round(unknown_fraction,3),unknown_penalty=round(c.unknown_cost*unknown_fraction,3))


class Planner:
    def __init__(self,config=None):
        self.config=config or Config()
        self.mode='manual';self.reset()

    def reset(self):
        self.phase='idle';self.blocked_since=None;self.until=0.;self.attempts=0
        self.last_steering=0.;self.reverse_steering=0.;self.target_key=None
        self.holding=False
        self.route_memory=RouteMemory()

    def set_mode(self,mode):
        if mode not in ('manual','autonomous'):raise ValueError('Mode inconnu.')
        self.mode=mode;self.reset()

    def step(self,vision,scan,now,wall_now):
        c=self.config
        result=dict(mode=self.mode,state='stop',reason='',motor_control=False,advisory_only=True,
            intent=dict(motion='stop',speed_m_s=0.,steering_deg=0.,steering_normalized=0.,ttl_ms=300),
            target=None,candidates=[],chosen=None,recovery_attempts=self.attempts,
            footprint_radius_m=round(c.radius,3),readiness=[],sectors=[])
        def stop(reason,state='stop'):
            if state in ('target_lost','no_depth','lidar_unavailable','lidar_stale','obstacle_close'):
                self.phase='idle';self.blocked_since=None;self.route_memory.clear()
            result.update(reason=reason,state=state,recovery_attempts=self.attempts)
            return result
        # Measurements remain visible independently of navigation activation.
        if (isinstance(vision,dict) and vision.get('fresh') and vision.get('state')=='ready'
                and finite(vision.get('age_s')) and 0<=vision['age_s']<=c.max_age_s
                and vision.get('selection_state')=='visible'):
            measured=vision.get('target')
            if (isinstance(measured,dict) and finite(measured.get('distance_m'))
                    and measured['distance_m']>0 and finite(measured.get('bearing_deg'))):
                a=math.radians(measured['bearing_deg'])
                x=measured['distance_m']*math.sin(a)+c.camera_x_m
                y=measured['distance_m']*math.cos(a)+c.camera_y_m
                d=math.hypot(x,y)
                result['target']=dict(distance_m=round(d,3),bearing_deg=round(math.degrees(math.atan2(x,y)),2),
                    error_m=round(d-c.target_m,3) if c.target_m is not None else None)
                if measured.get('distance_status')=='beyond_range':result['target']['distance_status']='beyond_range'
                if vision.get('approximate',True):
                    result['readiness'].append('Profondeur en mode essai : mesures approximatives.')
        if self.mode!='autonomous':return stop('Mode manuel : aucune consigne autonome.','manual')
        if c.target_m is None:return stop('Choisissez la distance à maintenir.','setup')
        if not isinstance(vision,dict) or not vision.get('fresh') or vision.get('state')!='ready':
            self.phase='idle';self.blocked_since=None
            return stop('Suivi indisponible ou image périmée.','target_lost')
        age=vision.get('age_s')
        if not finite(age) or not 0<=age<=c.max_age_s:return stop('Image trop ancienne.','target_lost')
        target=vision.get('target')
        if not isinstance(target,dict) or vision.get('selection_state')!='visible':
            self.phase='idle';self.blocked_since=None
            return stop('Sélectionnez une personne visible.','target_lost')
        if not finite(target.get('distance_m')) or target['distance_m']<=0 or not finite(target.get('bearing_deg')):
            return stop('Distance de la personne indisponible.','no_depth')
        key=(vision.get('generation'),vision.get('identity_id',vision.get('selected_id')))
        if key!=self.target_key:self.reset();self.target_key=key
        angle=math.radians(target['bearing_deg'])
        tx=target['distance_m']*math.sin(angle)+c.camera_x_m
        ty=target['distance_m']*math.cos(angle)+c.camera_y_m
        distance=math.hypot(tx,ty);bearing=math.degrees(math.atan2(tx,ty));error=distance-c.target_m
        result['target']=dict(distance_m=round(distance,3),bearing_deg=round(bearing,2),error_m=round(error,3))
        if target.get('distance_status')=='beyond_range':
            result['target']['distance_status']='beyond_range'
            result['readiness'].append('Personne au-delà de la plage stéréo : distance minimale seulement.')
            if error<=c.tolerance_m:return stop('Distance hors plage : impossible de vérifier la consigne choisie.','no_depth')
        if not c.geometry_confirmed:result['readiness'].append('Gabarit, empattement, braquage et repères provisoires.')
        try:ranges=ranges_from_scan(scan,c)
        except ValueError as exc:return stop(str(exc),'lidar_unavailable')
        lidar_age=wall_now-scan['timestamp'];result['scan_age_s']=round(lidar_age,3)
        if not 0<=lidar_age<=c.max_age_s:return stop('Scan lidar périmé ou horloges désynchronisées.','lidar_stale')
        result['sectors']=[dict(angle_deg=wrap(i*2+1),distance_m=d) for i,d in enumerate(ranges)]
        if all(d is None for d in ranges):return stop('Aucune mesure lidar valide.','lidar_unavailable')
        if close_obstacle(ranges,c):
            self.phase='idle';self.blocked_since=None
            return stop('Obstacle dans le gabarit et sa marge : arrêt.','obstacle_close')
        if error<=c.tolerance_m+(.1 if self.holding else 0):
            self.holding=True
            self.phase='idle';self.blocked_since=None
            return stop('Distance souhaitée atteinte ; arrêt.' if error>=-c.tolerance_m else 'Personne trop proche ; arrêt.','hold_distance')
        self.holding=False
        goal_distance=max(0,distance-c.target_m)
        goal=(tx*goal_distance/distance,ty*goal_distance/distance)
        local_distance=goal_distance
        local_goal=(tx*local_distance/distance,ty*local_distance/distance)
        result['goal']=dict(x_m=round(goal[0],3),y_m=round(goal[1],3),distance_to_person_m=c.target_m,
            local_x_m=round(local_goal[0],3),local_y_m=round(local_goal[1],3),within_horizon=True)
        route=search_route(ranges,c,local_goal,self.last_steering)
        odom=scan.get('odometry',{})
        if odom.get('valid'):
            route=self.route_memory.choose(route,ranges,c,local_goal,odom['pose'],odom['epoch'])
        else:
            self.route_memory.clear()
            result['readiness'].append('Position lidar incertaine : nouvelle trajectoire locale, sans mémoire de déplacement.')
        result['search']=dict(expanded=route['expanded'],elapsed_ms=route.get('elapsed_ms',0),limited=route.get('search_limited',False))
        forward_config=replace(c,horizon_m=max(.04,min(c.horizon_m,local_distance)))
        steering=[c.max_steering_deg*i/16 for i in range(-16,17)]
        # Include the exact arc aimed at the target at the displayed horizon.
        lo,hi=-c.max_steering_deg,c.max_steering_deg
        for _ in range(24):
            mid=(lo+hi)/2
            x,y,_=arc(mid,c.horizon_m,c.wheelbase_m)
            if math.degrees(math.atan2(x,y))<bearing:lo=mid
            else:hi=mid
        steering=sorted(set(steering+[(lo+hi)/2]))
        forward=[]
        for s in steering:
            p=corridor(ranges,forward_config,s)
            endpoint=arc(s,max(.04,p['clearance_m']),c.wheelbase_m)
            heading=math.degrees(math.atan2(endpoint[0],endpoint[1]))
            p['direction_deg']=round(heading,2)
            p['alignment_bonus']=round(50-c.alignment_slope*abs(wrap(heading-bearing)),3)
            p['obstacle_penalty']=obstacle_direction_penalty(ranges,forward_config,heading)
            p['score']=round(p['alignment_bonus']-p['obstacle_penalty']
                -.5*abs(s-self.last_steering)/c.max_steering_deg-p['unknown_penalty'],2)
            p['allowed']=p['clearance_m']>=.20 and abs(wrap(heading-bearing))<85
            forward.append(p)
        result['candidates']=forward
        ranked=[route] if route.get('path') else []
        if ranked:result['candidates'].append(route)
        def motion(p,reverse=False):
            cap=c.max_reverse_m_s if reverse else c.max_forward_m_s
            free=max(0,p['clearance_m']-.08)
            # v*reaction + v²/(2a) <= observed clearance minus stopping reserve.
            speed=min(cap,-c.deceleration_m_s2*c.reaction_s+math.sqrt((c.deceleration_m_s2*c.reaction_s)**2+2*c.deceleration_m_s2*free))
            if not reverse:speed=min(speed,max(0,error-c.tolerance_m)*.5)
            if not reverse and p.get('path'):
                command=control(p,ranges,c,speed)
                if command is None:
                    self.route_memory.clear()
                    return stop('Arc de commande non libre : recalcul de trajectoire.','controller_blocked')
                steer,speed,point=command
                p['steering_deg']=round(steer,3);p['steering_normalized']=steer/c.max_steering_deg
                result['controller']=dict(method='pure_pursuit',lookahead_point=list(point),retained=p.get('retained',False))
            self.last_steering=p['steering_deg']
            result.update(state='reversing' if reverse else 'following',reason='Recul de dégagement limité.' if reverse else 'Suivre la cible par le passage observé.',chosen=p,recovery_attempts=self.attempts)
            if p['unknown_fraction']>0:
                result['reason']='Trajectoire proposée avec zones sans mesure ('+str(round(100*p['unknown_fraction']))+' % maximum du passage). '
                result['readiness'].append('Passage partiellement observé : proposition expérimentale, sans commande moteur.')
            if not reverse and p.get('path'):
                result['reason']='Trajectoire à plusieurs braquages vers le point d’arrêt.' if p['reached'] and result['goal']['within_horizon'] else 'Trajectoire partielle : recalcul nécessaire pour rejoindre le point d’arrêt.'
                result['goal']['reached_by_plan']=bool(p['reached'] and result['goal']['within_horizon'])
            result['intent']=dict(motion='reverse' if reverse else 'forward',speed_m_s=round(-speed if reverse else speed,3),steering_deg=p['steering_deg'],steering_normalized=p['steering_normalized'],ttl_ms=300)
            return result
        if self.phase=='reverse':
            if now>=self.until:
                self.phase='pause';self.until=now+c.shift_pause_s
                return stop('Fin du recul ; pause avant changement de sens.','shift_pause')
            p=corridor(ranges,c,self.reverse_steering,True)
            result['candidates'].append(p)
            if p['clearance_m']<.20:
                self.phase='pause';self.until=now+c.shift_pause_s
                return stop('Recul interrompu : arrière non libre.','reverse_blocked')
            return motion(p,True)
        if self.phase=='pause':
            if now<self.until:return stop('Pause avant changement de sens.','shift_pause')
            self.phase='idle';self.blocked_since=None
        if ranked:
            self.phase='idle';self.blocked_since=None
            return motion(ranked[0])
        if route.get('search_limited'):return stop('Recherche de détour incomplète : arrêt en attendant un plan.','planning_limited')
        if self.blocked_since is None:self.blocked_since=now
        if self.attempts>=c.reverse_attempts:return stop('Tentatives de dégagement épuisées : intervention manuelle.','blocked')
        if not any(p['reason']=='obstacle' for p in forward):return stop('Avant insuffisamment observé : pas de recul automatique.','unknown')
        if now-self.blocked_since<c.blocked_delay_s:return stop('Passage avant bloqué ; arrêt avant dégagement.','blocked_wait')
        reverse=[]
        for s in steering:
            p=corridor(ranges,c,s,True)
            _,_,yaw=arc(s,-c.max_reverse_m_s*c.reverse_duration_s,c.wheelbase_m)
            p['alignment_bonus']=round(50-c.alignment_slope*abs(wrap(yaw-bearing)),3)
            rx,ry,_=arc(s,-max(.04,p['clearance_m']),c.wheelbase_m)
            p['obstacle_penalty']=obstacle_direction_penalty(ranges,c,math.degrees(math.atan2(rx,ry)))
            p['score']=round(p['alignment_bonus']-p['obstacle_penalty'],2)
            p['allowed']=p['clearance_m']>=max(.20,c.max_reverse_m_s*c.reverse_duration_s+.08)
            reverse.append(p)
        result['candidates']+=reverse
        choices=sorted((p for p in reverse if p['allowed']),key=lambda p:p['score'],reverse=True)
        if not choices:return stop('Avant bloqué et aucun recul observé libre.','blocked')
        self.attempts+=1;self.phase='reverse';self.until=now+c.reverse_duration_s
        self.reverse_steering=choices[0]['steering_deg']
        return motion(choices[0],True)
