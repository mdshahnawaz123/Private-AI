const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/mpd.js','utf8');
const predicates = {};
vm.createContext(predicates);
vm.runInContext(source.slice(source.indexOf('function _compilePredicate'), source.indexOf('let _mpdPlots')), predicates);
const compile=predicates._compilePredicate;
assert.equal(compile("far > 2 and land_use.lower() == 'mixed use'")({}, {far:3, land_use:'Mixed Use'}),true);
assert.equal(compile("far > 2 and land_use.lower() == 'mixed use'")({}, {far:1, land_use:'Mixed Use'}),false);
assert.equal(compile("layer.startswith('PLOT') and text not in ['Road', 'Note']")({layer:'plot-boundary',text:'Office'},{}),true);
assert.equal(compile("status == 'violation' or area >= 100")({}, {area_sqm:101}),true);
for(const payload of ['globalThis.fetch("/admin/users")', 'text.constructor.constructor("return window")()', '(function(){return true})()', 'true; fetch("/admin/users")']){
  const rejected=compile(payload);
  assert.ok(rejected.error,payload);
  assert.equal(rejected({},{}),false);
}
const start = source.indexOf('window._executeMpdChatActions =');
const end = source.indexOf('window._applyMpdViewActions =', start);
const calls=[];
const context = {currentDest:'mpd', _getMpdProject:()=> 'Test', window:{
  _performMpdCadAction:async(action, project)=>{calls.push([action.type,project]);return 'Created verified revision';},
  _applyMpdViewActions:(actions, project)=>{calls.push([actions[0].type,project]);return 'View receipt';}
}};
vm.createContext(context);
vm.runInContext(source.slice(start,end), context);
(async()=>{
  const execute = context.window._executeMpdChatActions;
  assert.match(await execute([{type:'edit_hatches'}],'Other'),/not applied/);
  assert.equal(calls.length,0);
  context.currentDest='documents';
  assert.match(await execute([{type:'edit_hatches'}],'Test'),/not applied/);
  assert.equal(calls.length,0);
  context.currentDest='mpd';
  assert.equal(await execute([{type:'edit_hatches'},{type:'set_text_mode'}],'Test'), 'Created verified revision\nView receipt');
  assert.equal(calls.length,2);
  context.window._performMpdCadAction=async()=>{throw new Error('No matching hatches');};
  assert.match(await execute([{type:'edit_hatches'}],'Test'),/Action failed: No matching hatches/);
  const app=fs.readFileSync('ui/app.js','utf8');
  const branch=app.slice(app.indexOf("else if(d.type==='viewer_action')"),app.indexOf('// Handle 3D Viewer AI Commands'));
  assert.match(branch,/await window\._executeMpdChatActions/);
  assert.match(branch,/ans \+= receipt/);
  console.log('PASS: real action receipts, project/view scope, failure reporting, and multi-action execution');
})().catch(error=>{console.error(error);process.exitCode=1;});
