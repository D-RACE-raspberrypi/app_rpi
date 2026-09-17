/* Same conservative straight-corridor model as direction.py; no vehicle control. */
function scoreDirections(points,target,front=0,sign=1,obstacleWeight=1){
 const wrap=a=>(a%360+540)%360-180,R=Math.hypot(.1,.15)+.1,step=.025,horizon=1.5;
 const ranges=Array(180).fill(null);
 for(const p of points){if(!(p.distance_mm>0&&p.quality>0))continue;const i=Math.floor(((sign*(p.angle_deg-front)%360+360)%360)/2),d=Math.min(p.distance_mm/1000,6);ranges[i]=ranges[i]===null?d:Math.min(ranges[i],d);}
 const close=ranges.some(d=>d!==null&&d<=R),angles=Array.from({length:37},(_,i)=>i*5-90);
 target=wrap(target);if(target>=-90&&target<=90&&!angles.includes(target))angles.push(target);angles.sort((a,b)=>a-b);
 return angles.map(angle=>{
 let clearance=0,reason=close?'obstacle_proche':'horizon_atteint';
 if(!close){const rays=[];for(let i=0;i<180;i++)for(const offset of [0,1,2]){const rad=wrap(i*2+offset-angle)*Math.PI/180;rays.push([Math.cos(rad),Math.sin(rad),ranges[i]]);}
 outer:for(let n=1;n<=60;n++){const t=n*step;for(const [c,s,d] of rays){const disc=R*R-(t*s)**2;if(disc<0)continue;const far=t*c+Math.sqrt(disc);if(far<=R+1e-9)continue;if(d===null){reason='zone_inconnue';break outer;}if(far+step>=d){reason='obstacle';break outer;}}clearance=t;}}
 // Preference remains numeric even when the independent corridor test fails.
 // Bin-based density avoids changing the score just because scan rate changes.
 const targetBonus=50+50*Math.cos(wrap(angle-target)*Math.PI/180);
 let peakRisk=0,densityRisk=0,unknownWeight=0,totalWeight=0;
 for(let i=0;i<180;i++){
   const delta=Math.abs(wrap(i*2+1-angle)),d=ranges[i];
   if(delta<=30){const w=Math.exp(-.5*(delta/15)**2);totalWeight+=w;
     if(d===null)unknownWeight+=w;
     else densityRisk+=w*Math.exp(-Math.max(0,d-R)/.8);
   }
   if(d!==null){const spread=10+Math.atan2(R,d)*180/Math.PI;
     const risk=Math.exp(-Math.max(0,d-R)/.8)*Math.exp(-.5*(delta/spread)**2);
     peakRisk=Math.max(peakRisk,risk);
   }
 }
 const obstaclePenalty=obstacleWeight*(45*peakRisk+25*densityRisk/totalWeight);
 const unknownPenalty=20*unknownWeight/totalWeight;
 const score=Math.max(0,Math.min(100,targetBonus-obstaclePenalty-unknownPenalty));
 const allowed=clearance>=.35;
 return {angle,clearance,allowed,score,reason,targetBonus,obstaclePenalty,unknownPenalty};
 });
}
if(typeof module!=='undefined')module.exports={scoreDirections};
