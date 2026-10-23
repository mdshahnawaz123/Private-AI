const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {randomUUID}=require('node:crypto');
const listeners=new Set(),sent=[];
let current=true;
const win={addEventListener:(name,fn)=>listeners.add(fn),removeEventListener:(name,fn)=>listeners.delete(fn)};
const source={postMessage(message,origin){
  sent.push(message);assert.equal(origin,'http://expo.local');
  queueMicrotask(()=>{
    const base={origin,source,data:{type:'expo:bim:response',project:'QA',requestId:message.requestId,result:{ready:true,categories:['IFCDOOR'],message:'REAL RECEIPT'}}};
    for(const fn of [...listeners])fn({...base,origin:'https://untrusted.invalid',data:{...base.data,result:{message:'SPOOF'}}});
    for(const fn of [...listeners])fn({...base,source:{},data:{...base.data,result:{message:'WRONG FRAME'}}});
    for(const fn of [...listeners])fn({...base,data:{...base.data,project:'OTHER',result:{message:'WRONG PROJECT'}}});
    for(const fn of [...listeners])fn(base);
  });
}};
const frame={contentWindow:source};
const env={window:win,crypto:{randomUUID},location:{origin:'http://expo.local'},document:{getElementById:()=>frame},setTimeout,clearTimeout,
  fetch:async()=>({ok:true,json:async()=>({handled:true,actions:[{tool:'hide',category:'IFCDOOR'}]})})};
vm.runInNewContext(fs.readFileSync('ui/bim_ai_bridge.js','utf8'),env);
(async()=>{
  const api=win.ExpoBimChat;
  let result=await api.request(frame,'QA','context');
  assert.equal(result.message,'REAL RECEIPT');assert.equal(listeners.size,0);
  result=await api.run({question:'hide doors',project:'QA',frame,isCurrent:()=>current});
  assert.equal(result.message,'REAL RECEIPT');assert.equal(sent.at(-1).operation,'execute');
  const count=sent.filter(s=>s.operation==='execute').length;
  current=false;
  result=await api.run({question:'hide doors',project:'QA',frame,isCurrent:()=>current});
  assert.match(result.message,/changed/);assert.equal(sent.filter(s=>s.operation==='execute').length,count);
  assert.equal(api.candidate('summarise this document'),false);
  assert.equal(api.candidate('colour doors red'),true);
  console.log('PASS: actual viewer receipts, strict origin/frame/project checks, listener cleanup and project-switch protection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
