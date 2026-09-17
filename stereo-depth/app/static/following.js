/* Each response contains its own image and detections: no MJPEG/JSON drift. */
let followState=null,followFrame=null,followBusy=false,followInitial=true;
const fc=document.querySelector('#follow-canvas'),ctx=fc.getContext('2d');
const followLabels={starting:'Initialisation du suivi…',waiting_hailo:'En attente du kit Hailo',disabled:'Suivi en pause',ready:'Détection et suivi actifs'};
async function followAction(path,data){if(followBusy)return;followBusy=true;try{await api('following/'+path,data)}catch(e){toast(e.message)}finally{followBusy=false}}
function paintFollow(s){
 const b=$('#follow-badge');b.textContent=followLabels[s.state]||s.state;
 $('#follow-error').textContent=s.state==='waiting_hailo'?'Montez le kit, installez HailoRT / TAPPAS et le modèle YOLOv8 Hailo‑8L. '+(s.error||''):s.error||'';
 $('#follow-toggle').textContent=s.config.enabled?'Mettre en pause':'Activer le suivi';
 $('#follow-toggle').disabled=followBusy;
 $('#follow-unlock').disabled=s.selected_id==null;
 $('#follow-quality').textContent=(s.approximate?'ESSAI · distances et angles approximatifs. ':'')+'Angle positif : droite · négatif : gauche. Référence : axe des caméras + correction de montage.';
 $('#follow-performance').textContent=s.fresh?fmt(s.inference_ms,0)+' ms · image âgée de '+fmt(s.age_s,2)+' s':s.state==='ready'?'Image périmée : mesures suspendues':'YOLOv8 sur Hailo · suivi JDE';
 const target=s.target;
 $('#follow-target').textContent=s.selection_state==='none'?'Cliquez sur une personne':s.selection_state==='reselect'?'Cible perdue · sélectionnez de nouveau':s.selection_state==='ambiguous'?'Apparence ambiguë · arrêt':s.selection_state==='confirming'?'Vérification du retour…':s.selection_state==='lost'?'Cible invisible · identité mémorisée':'Personne n° '+s.selected_id;
 $('#follow-distance').textContent=target?.distance_m!=null?(target.distance_status==='beyond_range'?'> ':s.approximate?'≈ ':'')+fmt(target.distance_m,2)+' m':'—';
 $('#follow-bearing').textContent=target?((target.bearing_deg>0?'+':'')+fmt(target.bearing_deg,1)+'°'):'—';
 $('#follow-delta').textContent=target?.distance_error_m!=null?(target.distance_error_m>0?'+':'')+fmt(target.distance_error_m,2)+' m':'—';
 $('#follow-reason').textContent=target?(target.depth_reason||'Distance horizontale estimée sur le torse · '+fmt(target.valid_percent,0)+' % de profondeur valide'):'Aucune distance n’est extrapolée pendant une perte de cible.';
 $('#follow-arrow').style.transform='rotate('+(target?.bearing_deg||0)+'deg)';
 $('#follow-arrow').style.opacity=target?'1':'.2';
 $('#follow-direction').textContent=!target?'Direction indisponible':Math.abs(target.bearing_deg)<3?'Dans l’axe':target.bearing_deg>0?'Personne à droite':'Personne à gauche';
 const list=$('#follow-people');list.replaceChildren(...s.people.map(p=>{const button=document.createElement('button');button.className='button small';button.textContent='Personne '+p.id+' · '+fmt(p.confidence*100,0)+' %';button.onclick=()=>followAction('select',{id:p.id,generation:s.generation});return button}));
 if(followInitial){for(const [k,v] of Object.entries(s.config)){const el=$('#follow-form').elements[k];if(el)el.value=v}followInitial=false;updateFollowOutputs()}
}
async function showFollow(s){
 if(s.image){const img=new Image();img.src='data:image/jpeg;base64,'+s.image;await img.decode();fc.width=img.width;fc.height=img.height;ctx.drawImage(img,0,0);followFrame=s;
  ctx.font=Math.max(13,fc.width/32)+'px sans-serif';ctx.lineWidth=2;
  for(const p of s.people){const [x1,y1,x2,y2]=p.box;ctx.strokeStyle=p.id===s.selected_id?'#b9ff57':'#ffffff';ctx.fillStyle=ctx.strokeStyle;ctx.strokeRect(x1*fc.width,y1*fc.height,(x2-x1)*fc.width,(y2-y1)*fc.height);ctx.fillText('#'+p.id,x1*fc.width+4,Math.max(18,y1*fc.height-5))}
  ctx.strokeStyle='#ffffff66';ctx.beginPath();ctx.moveTo(fc.width/2,0);ctx.lineTo(fc.width/2,fc.height);ctx.stroke();
 }
 paintFollow(s);followState=s;
}
fc.onclick=e=>{if(!followFrame?.fresh)return;const rect=fc.getBoundingClientRect(),x=(e.clientX-rect.left)/rect.width,y=(e.clientY-rect.top)/rect.height;const candidates=followFrame.people.filter(p=>x>=p.box[0]&&x<=p.box[2]&&y>=p.box[1]&&y<=p.box[3]);if(candidates.length===1)followAction('select',{id:candidates[0].id,generation:followFrame.generation});else toast(candidates.length?'Cadres superposés : utilisez les boutons de personne.':'Cliquez dans le cadre d’une personne détectée.')};
$('#follow-toggle').onclick=()=>followState&&followAction('settings',{enabled:!followState.config.enabled});
$('#follow-unlock').onclick=()=>followAction('select',{id:null,generation:followState.generation});
function updateFollowOutputs(){for(const name of ['confidence','target_m','camera_yaw_deg']){$('#out-'+name).textContent=fmt(Number($('#follow-form').elements[name].value),name==='confidence'?2:1)}}
$('#follow-form').oninput=updateFollowOutputs;
$('#follow-form').onsubmit=e=>{e.preventDefault();followAction('settings',Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,Number(v)])))};
(async function refreshFollow(){if(page==='following'){try{await showFollow(await api('following'))}catch(e){followFrame=null;$('#follow-badge').textContent='Connexion au Pi interrompue';$('#follow-distance').textContent=$('#follow-bearing').textContent=$('#follow-delta').textContent='—';$('#follow-arrow').style.opacity='.2';$('#follow-people').replaceChildren();$('#follow-error').textContent=e.message}}setTimeout(refreshFollow,250)})();
