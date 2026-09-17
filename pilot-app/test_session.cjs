// Offline regression: display failures must not stop a healthy control channel.
const {readFileSync}=require('node:fs');
const vm=require('node:vm');const assert=require('node:assert/strict');
const source=readFileSync(__dirname+'/pilot.js','utf8').split("api('connection').then")[0];
const elements=new Map();const element=()=>({value:'17',classList:{toggle(){}},getContext(){return {}}});
const context=vm.createContext({console,performance,localStorage:{getItem:()=>null},document:{hidden:false,querySelector(s){if(!elements.has(s))elements.set(s,element());return elements.get(s)},addEventListener(){}},window:{addEventListener(){}},navigator:{},setTimeout(){},AbortSignal,crypto:require('node:crypto').webcrypto});
vm.runInContext(source,context);
(async()=>{
 await vm.runInContext("active=true;api=async()=>{throw Error('Timeout carte')};poll()",context);
 assert.equal(vm.runInContext('active',context),true,'telemetry failure must not disarm');
 await vm.runInContext("readPad=()=>({key:'pad',id:'pad',accel:0,brake:0,steer:0,touch:false,connected:true,pressed:[],hasTouch:true});padKey='pad';owner='test';inputLoop()",context);
 assert.equal(vm.runInContext('active',context),false,'control failure must disarm');
 await vm.runInContext("active=true;api=async()=>({ok:true});readPad=()=>null;inputLoop()",context);
 assert.equal(vm.runInContext('active',context),false,'controller loss must disarm');
 console.log('3 session regression checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
