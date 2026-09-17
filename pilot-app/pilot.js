'use strict';
const $=s=>document.querySelector(s),fmt=(v,n=2)=>Number.isFinite(v)?v.toFixed(n).replace('.',','):'—';
let state=null,displayed=null,mode='manual',active=false,owner='',seq=0,busy=false,touchWas=false,padKey=null,latestPad=null,initialized=false,epoch=0;
const touchField=$('#touch-index');touchField.value=localStorage.getItem('rc-touch-index')||17;
touchField.onchange=()=>{if(active){touchField.value=localStorage.getItem('rc-touch-index')||17;return}localStorage.setItem('rc-touch-index',touchField.value)};
async function api(path,data){const r=await fetch('/api/'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined,signal:AbortSignal.timeout(1800)});const d=await r.json();if(!r.ok)throw Error(d.error||'Connexion interrompue');return d}
function note(message){$('#notice').textContent=message}
function showMode(value){mode=value;$('#manual').classList.toggle('selected',value==='manual');$('#auto').classList.toggle('selected',value==='autonomous');$('#mode-label').textContent=value==='manual'?'Manuel':'Automatique'}
async function stop(){epoch++;active=false;owner='';try{await api('pilot',{action:'stop'})}catch(e){note('Liaison perdue : arrêt automatique à expiration des commandes.')}$('#arm').textContent='Activer les commandes'}
$('#stop').onclick=stop;
async function changeMode(value){if(active){try{await api('pilot',{action:'mode',mode:value,owner});note('Changement de mode : relâche les gâchettes.')}catch(e){await stop();note(e.message)}}else showMode(value)}
$('#manual').onclick=()=>changeMode('manual');$('#auto').onclick=()=>changeMode('autonomous');
$('#arm').onclick=async()=>{if(active)return;const pad=latestPad;if(!pad||pad.accel>.05||pad.brake>.05||pad.touch){note('Connecte la manette et relâche les gâchettes et le pavé tactile.');return}const version=++epoch;owner=crypto.randomUUID();seq=0;$('#arm').disabled=true;try{await api('pilot',{action:'start',mode,owner});if(version!==epoch){await api('pilot',{action:'stop'});return}active=true;padKey=pad.key;note('Armement au neutre pendant 3 secondes.');}catch(e){active=false;note(e.message)}};
$('#distance-form').onsubmit=async e=>{e.preventDefault();try{await api('config',{target_m:Number($('#target').value)});note('Distance enregistrée.')}catch(e){note(e.message)}};
$('#release').onclick=async()=>{if(state?.vision)try{await api('select',{id:null,generation:state.vision.generation})}catch(e){note(e.message)}};
function readPad(){const pads=navigator.getGamepads?.();const p=pads&&Array.from(pads).find(p=>p?.connected&&p.mapping==='standard');if(!p)return null;const touch=Number(touchField.value);return {key:p.index+':'+p.id,id:p.id,steer:Math.max(-1,Math.min(1,p.axes[0]||0)),accel:p.buttons[7]?.value||0,brake:p.buttons[6]?.value||0,touch:!!p.buttons[touch]?.pressed,connected:true,pressed:p.buttons.flatMap((b,i)=>b.pressed?[i]:[]),hasTouch:!!p.buttons[touch]}}
async function inputLoop(){latestPad=readPad();const p=latestPad;$('#gamepad').textContent=p?p.id:'Appuie sur un bouton de la manette';$('#buttons').textContent='Boutons pressés : '+(p?.pressed.join(', ')||'aucun');$('#padwarning').textContent=p&&!p.hasTouch?'Ce navigateur n’expose pas le bouton configuré du pavé tactile. Le changement de mode reste disponible à l’écran.':'';
 if(active&&(!p||p.key!==padKey||document.hidden)){await stop();note('Commandes arrêtées : manette déconnectée ou onglet masqué.');}
 if(p){if(!active&&p.touch&&!touchWas)showMode(mode==='manual'?'autonomous':'manual');touchWas=p.touch}else touchWas=false;
 if(active&&p&&!busy){busy=true;try{await api('pilot',{action:'input',owner,seq:seq++,...p})}catch(e){await stop();note(e.message)}finally{busy=false}}
 setTimeout(inputLoop,80);
}
function leave(){epoch++;active=false;navigator.sendBeacon('/api/pilot',new Blob([JSON.stringify({action:'stop'})],{type:'application/json'}))}
document.addEventListener('visibilitychange',()=>{if(document.hidden&&active)leave()});window.addEventListener('pagehide',()=>{if(active)leave()});
async function render(s){state=s;const d=s.drive,p=s.plan,m=d.status||{};$('#connection').textContent=s.demo?'SIMULATION':'Pi connecté · '+(s.vision?.fresh?'caméra en direct':'caméra en attente');
 if(active&&(!d.active||d.owner!==owner)){active=false;epoch++;note('Commandes désarmées.');}
 if(active&&d.pilot)showMode(d.pilot.mode);
 $('#arm').disabled=active||!latestPad||!m.boot_id||!!s.demo||d.active;$('#arm').textContent=active?'Commandes activées':'Activer les commandes';touchField.disabled=active;
 if(active)note((d.pilot?.ready?'':'Relâche les gâchettes. ')+(m.reason||''));
 $('#effort').textContent=m.pulse_us==null?'Désarmé':m.pulse_us>1501?'Avancer':m.pulse_us<1499?'Frein / recul':'Au neutre';$('#steering').textContent=Math.abs(m.steering||0)<.02?'Centre':(m.steering<0?'Gauche ':'Droite ')+Math.round(Math.abs(m.steering)*100)+' %';$('#distance').textContent=fmt(s.vision?.target?.distance_m)+' m';
 $('#route-info').textContent=p.chosen?'Trajectoire calculée':p.reason;$('#scan-age').textContent=s.scan?'Scan '+fmt(Math.max(0,Date.now()/1000-s.scan.timestamp),1)+' s':'Lidar en attente';drawMap(s);
 const v=s.vision;$('#selection').textContent=v?.selected_id!=null?'Personne '+v.selected_id+' · '+({visible:'visible',lost:'hors champ',confirming:'vérification',reselect:'à sélectionner',ambiguous:'ambiguë'}[v.selection_state]||'en attente'):'Aucune personne sélectionnée';$('#target-info').textContent=v?.target?'Distance '+fmt(v.target.distance_m)+' m · angle '+fmt(v.target.bearing_deg,1)+'°':'Clique dans un cadre pour sélectionner une personne.';
 if(!initialized){if(s.config.target_m!=null)$('#target').value=s.config.target_m;initialized=true;if(!d.active&&p.mode==='manual')api('pilot',{action:'preview'}).catch(e=>note(e.message))}
 const c=$('#person'),ctx=c.getContext('2d');displayed=null;
 if(v?.image){const im=new Image();im.src='data:image/jpeg;base64,'+v.image;await im.decode();c.width=im.width;c.height=im.height;ctx.drawImage(im,0,0);if(v.fresh){displayed=v;ctx.lineWidth=2;ctx.font='15px system-ui';for(const person of v.people||[]){const [x,y,x2,y2]=person.box;ctx.strokeStyle=ctx.fillStyle=person.id===v.selected_id?'#c6ef9f':'white';ctx.strokeRect(x*c.width,y*c.height,(x2-x)*c.width,(y2-y)*c.height);ctx.fillText('#'+person.id,x*c.width+3,Math.max(17,y*c.height-5))}}}else{ctx.clearRect(0,0,c.width,c.height);ctx.fillStyle='#bac9b6';ctx.font='18px system-ui';ctx.fillText('En attente de la caméra…',30,50)}
}
$('#person').onclick=async e=>{if(!displayed)return;const r=e.target.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;const hits=displayed.people.filter(p=>x>=p.box[0]&&x<=p.box[2]&&y>=p.box[1]&&y<=p.box[3]);if(hits.length!==1){note('Choisis une personne dont le cadre ne se superpose pas.');return}try{await api('select',{id:hits[0].id,generation:displayed.generation})}catch(e){note(e.message)}};
async function poll(){try{await render(await api('state'))}catch(e){$('#connection').textContent='Pi indisponible';displayed=null;if(active)await stop();note(e.message)}setTimeout(poll,200)}
api('connection').then(c=>{$('#advanced').href=c.url}).catch(()=>{});inputLoop();poll();
