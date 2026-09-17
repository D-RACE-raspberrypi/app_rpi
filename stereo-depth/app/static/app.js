const $=s=>document.querySelector(s);
let state=null,page='live',busy=false,initial=true,thumbCount=-1,toastTimer;
const titles={following:'Une personne. Une direction.',live:'La profondeur, en direct.',calibration:'Calibrer. Aligner. Mesurer.',settings:'Votre scène, vos réglages.'};
const fmt=(v,n=1)=>v==null?'—':Number(v).toLocaleString('fr-FR',{minimumFractionDigits:n,maximumFractionDigits:n});
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6500)}
function streams(){document.querySelectorAll('[data-stream]').forEach(img=>{const visible=!img.closest('.page').hidden;if(visible&&!img.getAttribute('src'))img.src='/stream/'+img.dataset.stream;else if(!visible)img.removeAttribute('src')})}
function navigate(p){page=p;document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!=='page-'+p);document.querySelectorAll('.nav').forEach(el=>el.classList.toggle('active',el.dataset.page===p));$('#page-title').textContent=titles[p];streams()}
document.querySelectorAll('[data-page],[data-go]').forEach(el=>el.onclick=()=>navigate(el.dataset.page||el.dataset.go));
async function api(path,data){const response=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let value;try{value=await response.json()}catch{throw Error('Réponse du serveur invalide.')}if(!response.ok)throw Error(value.error||'La demande a échoué.');return value}
async function action(button,fn){if(busy)return;busy=true;button.disabled=true;try{await fn();await poll()}catch(e){toast(e.message)}finally{busy=false;button.disabled=false;if(state)render(state)}}
function render(s,allowSliders=true){if(state?.trial!==s.trial)$('#measurement').hidden=true;state=s;$('#fps').innerHTML=fmt(s.fps)+'<small> img/s</small>';$('#sync').innerHTML=fmt(s.sync_ms,2)+'<small> ms</small>';$('#valid').innerHTML=fmt(s.valid_percent)+'<small> %</small>';$('#temp').innerHTML=fmt(s.temperature)+'<small> °C</small>';$('#connection').textContent=s.connected?'Deux caméras connectées':'Caméras indisponibles';$('#mode').textContent=s.demo?'SIMULATION':s.trial?'ESSAI · distances approximatives':s.calibrated?'Calibration active':'Calibration requise';$('#cal-dot').style.background=s.calibrated?'#68975b':'#d4a047';$('#uncalibrated').hidden=s.depth_enabled;$('#snapshot').disabled=!s.depth_enabled||!s.connected;$('#trial-toggle').textContent=s.trial?'Quitter le mode essai':'Activer le mode essai';$('#trial-toggle').disabled=busy||s.job.state==='running';$('#near-label').textContent=fmt(s.settings.near,2)+' m';$('#far-label').textContent=fmt(s.settings.far,2)+' m';
const alerts=[];if(s.trial)alerts.push('Mode essai : géométrie supposée, distances approximatives. Si la carte reste sombre, vérifiez l’ordre gauche / droite et visez une scène avec des détails.');if(s.demo)alerts.push('Mode simulation : ces images sont synthétiques.');if(!s.connected)alerts.push(s.error||'En attente des deux caméras…');else if(s.sync_ms>8)alerts.push('Décalage temporel élevé : immobilisez la scène. Les captures de calibration sont suspendues au-delà de 8 ms.');if(s.temperature>=80)alerts.push('Température élevée : vérifiez le refroidissement du Pi.');$('#alert').textContent=alerts.join(' ');$('#alert').hidden=!alerts.length;
$('#sample-count').textContent=s.sample_count+' / 20 vues conseillées';$('#capture-progress').style.width=Math.min(100,s.sample_count/20*100)+'%';$('#capture').disabled=busy||!s.connected||s.demo||s.job.state==='running';$('#solve').disabled=busy||s.sample_count<12||s.job.state==='running';$('#clear').disabled=busy||s.job.state==='running';$('#square').disabled=s.sample_count>0;$('#job').textContent=s.job.message||'12 vues minimum · 20 à 30 recommandées';if(s.sample_count)$('#square').value=s.square_mm;
if(thumbCount!==s.sample_count){$('#samples').replaceChildren(...s.samples.map(v=>{const img=document.createElement('img');img.src='/api/calibration/thumb/'+v.index+'?t='+Date.now();img.alt='Capture '+v.index;img.title='Vue '+v.index+' · couverture '+v.area_percent+' %';return img}));thumbCount=s.sample_count}
$('#cal-export').hidden=!s.calibrated;const r=s.calibration;if(r){$('#cal-report').innerHTML='<div class="report-stats"><div><span>BASE MESURÉE</span><strong>'+fmt(r.baseline_mm)+'<small> mm</small></strong></div><div><span>ERREUR RMS</span><strong>'+fmt(r.rms,2)+'<small> px</small></strong></div><div><span>ÉCART VERTICAL</span><strong>'+fmt(r.epipolar_px,2)+'<small> px</small></strong></div></div>';const p=document.createElement('p');p.textContent=r.samples+' vues · T = ['+r.translation_mm.map(v=>fmt(v,2)).join(' ; ')+'] mm · R = ['+r.rotation_deg.map(v=>fmt(v,2)).join(' ; ')+']°';$('#cal-report').append(p);r.warnings.forEach(w=>{const p=document.createElement('p');p.className='warning';p.textContent=w;$('#cal-report').append(p)})}else $('#cal-report').textContent='La calibration estimera les optiques, la translation et la rotation entre les caméras.';
const diagnostics=[['Capteurs',s.cameras.join(' / ')||'—'],['Orientation',String(s.display_rotation_deg||0)+'°'],['Synchronisation',s.sync_software?'Logicielle active':'Horodatages uniquement'],['Traitement',fmt(s.processing_ms)+' ms'],['Résolution profondeur',s.size.join(' × ')],['Filtre WLS',s.wls_available?'Disponible':'Indisponible'],['Dernière image',fmt(s.frame_age_s,2)+' s']];$('#diagnostics').replaceChildren(...diagnostics.flatMap(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;return[dt,dd]}));
syncSliders(s,allowSliders);if(initial){Object.entries(s.settings).forEach(([k,v])=>{if($('#depth-form').elements[k])$('#depth-form').elements[k].value=v});$('#camera-form').elements.focus.value=s.camera.focus;$('#camera-form').elements.swap.checked=s.camera.swap;initial=false}}
async function poll(){const revision=sliderRevision;try{render(await api('status'),revision===sliderRevision)}catch(e){$('#connection').textContent='Serveur injoignable';$('#alert').hidden=false;$('#alert').textContent='Connexion au Pi interrompue. Nouvelle tentative automatique…';['capture','solve','snapshot'].forEach(id=>$('#'+id).disabled=true);$('#slider-status').textContent='Serveur injoignable : les réglages ne peuvent pas être enregistrés.'}}
$('#capture').onclick=e=>action(e.currentTarget,async()=>{await api('calibration/capture',{square_mm:Number($('#square').value)});toast('Paire capturée. Déplacez ou inclinez maintenant le damier.')});
$('#solve').onclick=e=>action(e.currentTarget,()=>api('calibration/solve',{}));
$('#clear').onclick=e=>action(e.currentTarget,()=>api('calibration/clear',{}));
$('#trial-toggle').onclick=e=>action(e.currentTarget,()=>api('trial',{enabled:!state.trial}));
$('#snapshot').onclick=()=>location.href='/api/snapshot';
$('#depth-form').onsubmit=e=>{e.preventDefault();const values=Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,k==='preset'?v:Number(v)]));action(e.submitter,async()=>{await api('settings',values);toast('Réglages enregistrés.')})};
$('#camera-form').onsubmit=e=>{e.preventDefault();const form=e.target;action(e.submitter,async()=>{await api('camera',{focus:Number(form.elements.focus.value),swap:form.elements.swap.checked});toast('Caméras en cours de redémarrage.')})};
$('#depth-image').onclick=async e=>{if(!state?.depth_enabled)return;const box=e.target.getBoundingClientRect();try{const result=await api('measure?x='+((e.clientX-box.left)/box.width)+'&y='+((e.clientY-box.top)/box.height));$('#measurement').textContent=result.distance_m==null?'Aucune mesure fiable ici':(result.approximate?'≈ ':'')+fmt(result.distance_m,3)+' m · '+(result.approximate?'estimation sans calibration':'profondeur Z');$('#measurement').hidden=false}catch(err){toast(err.message)}};

const sliderSpecs=[
 ['trial_x','X · déplacement horizontal','px',160,.5],['trial_y','Y · déplacement vertical','px',120,.5],
 ['trial_zoom','Z · zoom','%',60,.5],['trial_pitch','RX · inclinaison verticale','°',10,.1],
 ['trial_yaw','RY · inclinaison horizontale','°',10,.1],['trial_roll','RZ · rotation dans l’image','°',10,.1],
 ['texture_sensitivity','Sensibilité aux faibles détails','%',100,1,0]
];
const sliderControls={};
let sliderPending={},sliderSaving=false,sliderTimer=null,sliderRevision=0;
function sliderDirection(name){return state?.display_rotation_deg===180&&['trial_x','trial_y','trial_pitch','trial_yaw'].includes(name)?-1:1}
function setSliderValue(name,value){value*=sliderDirection(name);const c=sliderControls[name];c.range.value=value;c.number.value=value;c.range.setAttribute('aria-valuetext',fmt(value,1)+' '+c.unit)}
function queueSlider(name,value){const stored=value*sliderDirection(name);setSliderValue(name,stored);sliderPending[name]=stored;sliderRevision++;$('#measurement').hidden=true;$('#slider-status').textContent='Modification en attente…';if(name==='texture_sensitivity')$('#sensitivity-status').textContent='Modification en attente…';if(!sliderTimer)sliderTimer=setTimeout(()=>{sliderTimer=null;flushSliders()},180)}
async function flushSliders(){
  if(sliderSaving||!Object.keys(sliderPending).length)return;
  const values=sliderPending;sliderPending={};sliderSaving=true;$('#slider-status').textContent='Application en cours…';if('texture_sensitivity' in values)$('#sensitivity-status').textContent='Application en cours…';
  try{await api('settings',values);if(state)Object.assign(state.settings,values);$('#slider-status').textContent='Appliqué en direct · sauvegardé sur le Pi';if('texture_sensitivity' in values)$('#sensitivity-status').textContent='Sensibilité appliquée · sauvegardée sur le Pi';}
  catch(e){Object.keys(values).forEach(name=>{if(!(name in sliderPending)&&state)setSliderValue(name,state.settings[name]||0)});$('#slider-status').textContent='Non appliqué : '+e.message;if('texture_sensitivity' in values)$('#sensitivity-status').textContent='Non appliqué : '+e.message;toast(e.message);}
  finally{sliderSaving=false;if(Object.keys(sliderPending).length){clearTimeout(sliderTimer);sliderTimer=null;flushSliders()}else await poll()}
}
function syncSliders(s,allow){
 const ready=s.trial&&s.depth_enabled&&s.job.state!=='running';
 Object.entries(sliderControls).forEach(([name,c])=>{c.range.disabled=c.number.disabled=name==='texture_sensitivity'?(!s.depth_enabled||s.job.state==='running'):!ready});
 $('#reset-pose').disabled=!ready;
 if(!ready)$('#slider-status').textContent=s.job.state==='running'?'Calibration en cours : attendre la fin du calcul.':'Activez le mode essai pour aligner manuellement la caméra droite. La calibration au damier est conservée.';
 else if(initial)$('#slider-status').textContent='Prêt · application et sauvegarde automatiques';
 if(allow&&!sliderSaving&&!Object.keys(sliderPending).length){Object.entries(sliderControls).forEach(([name,c])=>{if(document.activeElement!==c.range&&document.activeElement!==c.number)setSliderValue(name,s.settings[name]||0)})}
}
for(const [name,label,unit,limit,step,minimum=-limit] of sliderSpecs){
 const row=document.createElement('div');row.className='slider-row';
 const title=document.createElement('label');title.htmlFor='slider-'+name;title.textContent=label;
 const range=document.createElement('input');Object.assign(range,{type:'range',id:'slider-'+name,min:minimum,max:limit,step,value:0,disabled:true});
 const number=document.createElement('input');Object.assign(number,{type:'number',min:minimum,max:limit,step,value:0,disabled:true});number.setAttribute('aria-label',label+' · valeur en '+unit);
 const valueBox=document.createElement('div');valueBox.className='slider-value';const suffix=document.createElement('span');suffix.textContent=unit;valueBox.append(number,suffix);
 const track=document.createElement('div');track.className='slider-track';track.append(range,valueBox);
 const limits=document.createElement('div');limits.className='slider-limits';const low=document.createElement('span'),high=document.createElement('span');low.textContent=name==='texture_sensitivity'?'0 · strict':minimum+' '+unit;high.textContent=name==='texture_sensitivity'?'100 · tolérant':'+'+limit+' '+unit;limits.append(low,high);
 row.append(title,track,limits);$(name==='texture_sensitivity'?'#sensitivity-sliders':'#pose-sliders').append(row);
 sliderControls[name]={range,number,unit};
 range.oninput=()=>queueSlider(name,Number(range.value));
 number.oninput=()=>{if(number.value!==''&&number.validity.valid)queueSlider(name,Number(number.value))};
 number.onblur=()=>{if(number.value===''||!number.validity.valid)number.value=range.value};
 range.onchange=number.onchange=()=>{clearTimeout(sliderTimer);sliderTimer=null;flushSliders()};
}
$('#reset-pose').onclick=()=>{sliderSpecs.slice(0,6).forEach(([name])=>queueSlider(name,0));clearTimeout(sliderTimer);sliderTimer=null;flushSliders()};


$('#alignment-view').onclick=()=>{const img=$('#alignment-image'),blend=img.dataset.stream!=='alignment';img.dataset.stream=blend?'alignment':'rectified';img.src='/stream/'+img.dataset.stream;img.style.aspectRatio=blend?'4/3':'8/3';$('#alignment-view').textContent=blend?'Afficher côte à côte':'Superposer les images';$('#alignment-caption').textContent=blend?'Gauche en vert · droite en magenta':'Gauche fixe / droite corrigée';img.alt=$('#alignment-caption').textContent};
streams();(async function refresh(){await poll();setTimeout(refresh,1200)})();
