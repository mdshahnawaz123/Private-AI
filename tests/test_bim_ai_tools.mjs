import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../ui/bim_ai_tools.js',import.meta.url),'utf8');
const {createBimTools,readableIfc}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const cyclic={_localId:{value:12},Name:{value:'Wall'}};cyclic.IsDefinedBy=[cyclic];
assert.doesNotThrow(()=>JSON.stringify(readableIfc(cyclic)));
assert.equal(readableIfc(cyclic).IsDefinedBy[0].reference,12);
function model(modelId,groups){
  const all=Object.values(groups).flat(),visible=new Map(all.map(id=>[id,true])),colors=new Map();
  return {modelId,visible,colors,object:{visible:true},
    getCategories:async()=>Object.keys(groups),getItemsIdsWithGeometry:async()=>all,
    getVisible:async ids=>ids.map(id=>visible.get(id)),
    getItemsOfCategories:async patterns=>Object.fromEntries(Object.entries(groups).filter(([c])=>patterns.some(p=>p.test(c)))),
    setVisible:async(ids,value)=>ids.forEach(id=>visible.set(id,value)),
    resetVisible:async()=>all.forEach(id=>visible.set(id,true)),
    setColor:async(ids,color)=>ids.forEach(id=>colors.set(id,color)),
    resetColor:async ids=>(ids||all).forEach(id=>colors.delete(id)),
    getItemsData:async ids=>ids.map(id=>({_localId:{value:id},Name:{value:id===0?'Fire Door FD-01':'Ordinary door'},FireRating:{value:0}})),
  };
}
const a=model('model-a',{IFCDOOR:[0,1],IFCWALLSTANDARDCASE:[2]});
const b=model('model-b',{IFCCOLUMN:[0,3]});
let selected={modelId:'model-b',localId:0},updates=0;
const engine=createBimTools({getModels:()=>[{model:a,name:'A'},{model:b,name:'B'}],getSelected:()=>selected,makeColor:x=>x,update:async()=>{updates++;},fit:()=>{}});
const factualContext=await engine.context();
assert.equal(factualContext.counts_complete,true);
assert.equal(factualContext.counts.IFCDOOR,2);
assert.equal(factualContext.counts.IFCCOLUMN,2);
assert.equal(factualContext.models[0].counts.IFCDOOR,2);
let r=await engine.execute([{tool:'isolate',category:'IFCDOOR'}]);
assert.equal(r.ok,true);assert.match(r.message,/Isolated 2/);
assert.equal(a.visible.get(2),false);assert.equal(b.visible.get(0),false);
r=await engine.execute([{tool:'undo'}]);assert.equal(r.ok,true);assert.equal(b.visible.get(0),true);
r=await engine.execute([{tool:'hide',category:'IFCWALL'}]);assert.equal(r.ok,true);assert.equal(a.visible.get(2),false);
r=await engine.execute([{tool:'color',selected:true,color:'#ffff00'}]);assert.equal(r.ok,true);
assert.equal(b.colors.get(0),'#ffff00');assert.equal(a.colors.size,0);
r=await engine.execute([{tool:'undo'}]);assert.equal(r.ok,true);assert.equal(b.colors.size,0);assert.equal(a.visible.get(2),false);
r=await engine.execute([{tool:'isolate',category:'IFCROOF'}]);assert.equal(r.ok,false);assert.equal(a.visible.get(0),true);
r=await engine.execute([{tool:'color',category:'IFCDOOR',color:'javascript:alert(1)'}]);assert.equal(r.ok,false);
r=await engine.execute([{tool:'color',category:'IFCDOOR',color:'#ff4444',text_match:'fire door'}]);
assert.equal(r.ok,true);assert.equal(a.colors.get(0),'#ff4444');assert.equal(a.colors.has(1),false);
r=await engine.execute([{tool:'hide',category:'IFCDOOR',text_match:'FireRating'}]);assert.equal(r.ok,false,'Do not match a property key whose value is false/zero');
r=await engine.execute([{tool:'properties',selected:true}]);assert.equal(r.ok,true);assert.equal(r.sources[0].model,'model-b');assert.deepEqual(r.sources[0].ids,[0]);
selected=null;r=await engine.execute([{tool:'properties',selected:true}]);assert.equal(r.ok,false);
r=await engine.execute([{tool:'reset'}]);assert.equal(r.ok,true);assert.equal(a.visible.get(2),true);assert.equal(a.colors.size,0);
// Validate the entire compound command before the first mutation.
r=await engine.execute([{tool:'hide',category:'IFCDOOR'},{tool:'isolate',category:'IFCROOF'}]);
assert.equal(r.ok,false);assert.equal(a.visible.get(0),true);
const original=a.setColor;a.setColor=async()=>{throw new Error('Worker failed');};
r=await engine.execute([{tool:'hide',category:'IFCDOOR'},{tool:'color',category:'IFCDOOR',color:'#ff4444'}]);
assert.equal(r.ok,false);assert.equal(a.visible.get(0),true);a.setColor=original;
assert.ok(updates>0);
let camera=1;
const cameraEngine=createBimTools({getModels:()=>[{model:a}],getSelected:()=>null,makeColor:x=>x,
  update:async()=>{},getCameraState:()=>({value:camera}),restoreCameraState:s=>{camera=s.value;},fit:()=>{camera=42;}});
assert.equal((await cameraEngine.execute([{tool:'fit'}])).ok,true);assert.equal(camera,42);
assert.equal((await cameraEngine.execute([{tool:'undo'}])).ok,true);assert.equal(camera,1);
a.object.visible=false;
assert.equal((await engine.execute([{tool:'show',category:'IFCDOOR'}])).ok,true);assert.equal(a.object.visible,true);
assert.equal((await engine.execute([{tool:'undo'}])).ok,true);assert.equal(a.object.visible,false);
console.log('PASS: category and selected tools, multi-model identity, wall family, literal property values, no-match safety, rollback, undo, reset, actual receipts.');
