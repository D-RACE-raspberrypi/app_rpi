const assert=require('node:assert/strict');const {scoreDirections}=require('./scores.js');
function scene(obstacle,unknown=false){return Array.from({length:360},(_,a)=>({angle_deg:a,distance_mm:unknown?0:obstacle&&Math.abs((a-obstacle[0]+540)%360-180)<8?obstacle[1]:4000,quality:15}));}
const best=s=>s.filter(c=>c.allowed).sort((a,b)=>b.score-a.score)[0];
for(const target of [-45,0,30,70])assert.equal(best(scoreDirections(scene(),target)).angle,target);
assert.notEqual(best(scoreDirections(scene([30,800]),30)).angle,30);
assert.equal(best(scoreDirections(scene([30,150]),30)),undefined);
assert.equal(best(scoreDirections(scene(null,true),30)),undefined);
assert.notEqual(best(scoreDirections(scene([90,800]),0,90)).angle,0);
const fs=require('node:fs'),vm=require('node:vm');const html=fs.readFileSync(__dirname+'/viewer.html','utf8');new vm.Script(html.split('<script>')[1].split('</script>')[0]);
console.log('Scores: 8 assertions OK; syntaxe visualisation OK');
