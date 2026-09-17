#!/usr/bin/env python3
"""Local direction suggestions only: no steering or throttle output.
Coordinates: 0 forward, positive right. Lidar must be at footprint centre.
Unknown 2-degree sectors are forbidden; zero ranges never mean free space.
"""
import argparse
import json
import math
import time
from pathlib import Path

BIN = 2
STEP = .025

def wrap(a):
    return (a+180)%360-180

def build_ranges(points, front, sign, max_range):
    ranges = [None]*(360//BIN)
    for p in points:
        a, d, q = p['angle_deg'], p['distance_mm']/1000, p['quality']
        if not all(math.isfinite(v) for v in (a,d,q)) or d <= 0 or q <= 0:
            continue
        index = int((sign*(a-front)%360)//BIN)
        # A measured return beyond the planning range still establishes a ray.
        d = min(d, max_range)
        ranges[index] = d if ranges[index] is None else min(ranges[index], d)
    return ranges

def corridor_clearance(ranges, heading, radius, horizon):
    # Conservative circular footprint, including margin. Samples of its swept
    # disk must lie inside observed sectors. Initial footprint is exempt from
    # unknown-space checks; any measured obstacle inside it still forces STOP.
    if any(d is not None and d <= radius for d in ranges):
        return 0., 'obstacle_proche'
    rays=[]
    for i,d in enumerate(ranges):
        for offset in (0., 1., 2.):
            angle=math.radians(wrap(i*BIN+offset-heading))
            rays.append((math.cos(angle), math.sin(angle), d))
    clearance=0.
    for step in range(1, int(horizon/STEP)+1):
        travel=step*STEP
        for c,s,d in rays:
            disc=radius*radius-(travel*s)**2
            if disc < 0:
                continue
            far=travel*c+math.sqrt(disc)
            if far <= radius+1e-9:
                continue
            if d is None:
                return clearance, 'zone_inconnue'
            if far+STEP >= d:
                return clearance, 'obstacle'
        clearance=travel
    return clearance, 'horizon_atteint'

def plan(scan, target=30, front=0, sign=1, width=.20, length=.30,
         margin=.10, horizon=1.5, minimum=.35, max_age=1., now=None):
    now=time.time() if now is None else now
    age=now-scan['timestamp']
    ranges=build_ranges(scan['points'], front, sign, 6.)
    radius=math.hypot(width/2,length/2)+margin
    candidates=[]
    angles=sorted(set(list(range(-90,91,5))+([target] if -90<=target<=90 else [])))
    for heading in angles:
        clearance, reason=corridor_clearance(ranges,heading,radius,horizon)
        allowed=clearance >= minimum
        alignment=math.cos(math.radians(wrap(heading-target)))
        bonus=2*alignment
        space_bonus=clearance/horizon
        penalty=.8*math.exp(-clearance/.4)
        score=bonus+space_bonus-penalty if allowed else None
        candidates.append(dict(angle_deg=heading,clearance_m=round(clearance,3),
            allowed=allowed,reason=reason,score=round(score,4) if score is not None else None,
            target_bonus=round(bonus,4),space_bonus=round(space_bonus,4),
            proximity_penalty=round(penalty,4)))
    ranked=sorted((c for c in candidates if c['allowed']),key=lambda c:c['score'],reverse=True)
    stale=not 0 <= age <= max_age
    best=ranked[0] if ranked else None
    status='STOP_SCAN_PERIME' if stale else ('DIRECTION_PROPOSEE' if best else 'STOP_AUCUN_PASSAGE')
    return dict(status=status,vehicle_control_enabled=False,target_deg=target,
        scan_age_s=round(age,3),known_sectors=sum(d is not None for d in ranges),
        total_sectors=len(ranges),footprint_radius_m=round(radius,3),
        proposed_direction=None if stale else best,geometric_best=best,
        candidates=candidates,sectors=[dict(start_deg=wrap(i*BIN),range_m=d) for i,d in enumerate(ranges)],
        assumptions=['Lidar au centre du gabarit','Angle avant et sens a calibrer',
                     'Couloirs droits uniquement: virage non valide',
                     'Controle propulsion et direction absent'])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',type=float,default=30)
    p.add_argument('--front-angle',type=float,default=0)
    p.add_argument('--angle-sign',type=int,choices=(-1,1),default=1)
    p.add_argument('--width',type=float,default=.20)
    p.add_argument('--length',type=float,default=.30)
    p.add_argument('--margin',type=float,default=.10)
    p.add_argument('--horizon',type=float,default=1.5)
    p.add_argument('--min-clearance',type=float,default=.35)
    p.add_argument('--scan',default=str(Path(__file__).with_name('scans.jsonl')))
    p.add_argument('--replay',action='store_true',help='Analyse historique; aucune instruction de mouvement')
    p.add_argument('--output',default=str(Path(__file__).with_name('direction.json')))
    a=p.parse_args()
    if not all(math.isfinite(v) for v in (a.target,a.front_angle,a.width,a.length,a.margin,a.horizon,a.min_clearance)):
        p.error('Valeurs finies requises')
    if not (0<a.width<=2 and 0<a.length<=3 and 0<=a.margin<=1 and .05<=a.min_clearance<=a.horizon<=4):
        p.error('Dimensions/horizon invalides (metres)')
    last=None
    with open(a.scan) as f:
        for line in f:
            if line.strip(): last=line
    if last is None: p.error('Aucun scan complet')
    scan=json.loads(last)
    result=plan(scan,wrap(a.target),a.front_angle,a.angle_sign,a.width,a.length,a.margin,a.horizon,a.min_clearance)
    if a.replay:
        result['status']='SIMULATION_HISTORIQUE'
        result['proposed_direction']=None
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print('Mode:',result['status'],'(aucune commande voiture)')
    print(f'Cible: {wrap(a.target):+.0f} deg; secteurs mesures: {result["known_sectors"]}/180; rayon gabarit+marge: {result["footprint_radius_m"]:.2f} m')
    best=result['geometric_best']
    if best and (a.replay or result['proposed_direction']):
        print(f'Meilleure direction geometrique: {best["angle_deg"]:+.0f} deg, couloir observe sur {best["clearance_m"]:.2f} m')
    else:
        print('STOP: aucun passage suffisamment observe, obstacle proche, ou scan perime.')
    print(' angle | libre (m) | score | limite')
    for c in result['candidates']:
        score='INTERDIT' if c['score'] is None else f'{c["score"]:.2f}'
        print(f'{c["angle_deg"]:+6.0f} | {c["clearance_m"]:9.2f} | {score:8s} | {c["reason"]}')
    print('Details:',a.output)

if __name__=='__main__':
    main()
