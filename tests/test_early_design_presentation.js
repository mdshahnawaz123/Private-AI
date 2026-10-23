const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const directory = process.env.EARLY_DESIGN_QA_DIR || fs.mkdtempSync(path.join(require('node:os').tmpdir(),'early-design-'));
fs.mkdirSync(directory,{recursive:true});
const fixture = JSON.parse(require('node:child_process').execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json; from services.early_design import generate, floor_plan; p={"plot":[[0,0],[80,0],[100,90],[20,130],[-15,60]],"max_height":48.8,"max_floors":13,"target_gfa":35000}; r=generate(p); print(json.dumps({"result":r,"plans":{str(i):floor_plan(r,i,p) for i in range(len(r["options"]))}}))'],{encoding:'utf8'}));
const fields = {edPrompt:{value:'Light limestone and bronze shading fins'}, edRenderView:{value:'primary'}};
let submissions = [], references = [], messages = [], available = true, changed = false;
const context = {window:{}, console, Blob, FormData, URL, crypto:require('node:crypto').webcrypto,
  setTimeout:fn=>fn(), currentProject:'Early Design QA',
  document:{getElementById:id=>fields[id], querySelector:()=>null}, toast:message=>messages.push(message),
  fetch:async (url, options={}) => {
    let data;
    if (url.endsWith('/workflows')) {
      data = [{id:'text-only',available:true,category:'concept'}, {id:'sketch_to_render',available,category:'sketch',parameters:[{name:'input_image_path',type:'image',required:true}]}];
      if (changed) context.window.edState.result = structuredClone(fixture.result);
    } else if (url.endsWith('/jobs')) {
      assert.equal(options.method,'POST'); assert.ok(options.body instanceof FormData);
      const form = options.body;
      assert.equal(form.get('workflow_id'),'sketch_to_render');
      assert.equal(form.get('input_image').type,'image/png');
      assert.equal(form.get('project'),'Early Design QA');
      assert.equal(form.get('steps'),null,'Use workflow sampling defaults');
      assert.match(form.get('prompt'),/Use the supplied axonometric/);
      submissions.push(form); data={job_id:'job-'+submissions.length};
    } else if (url.endsWith('/outputs')) data=[{output_id:'render-'+submissions.length}];
    else data={status:'completed'};
    return {ok:true,json:async()=>data};
  }};
context.window.location={origin:'http://localhost:8090'};
vm.createContext(context);
vm.runInContext(fs.readFileSync('ui/early_design_presentation.js','utf8'),context);
const presentation=context.window.EarlyDesignPresentation;
const source=fs.readFileSync('ui/early_design.js','utf8');
vm.runInContext(source,context);
const state=context.window.edState;
state.result=fixture.result; state.source='manual'; state.refine=false; state.inputs.site_name='QA <script>alert(1)</script>';
for (const [i,plan] of Object.entries(fixture.plans)) state.plans[`${i}:typical`]=plan;
const scenes=fixture.result.options.map(option=>presentation.massingSvg(fixture.result,option));
scenes.forEach(svg=>{assert.doesNotMatch(svg,/NaN|Infinity|var\(/);assert.match(svg,/fill-rule="evenodd"/);});
assert.notEqual(scenes[0],presentation.massingSvg(fixture.result,fixture.result.options[0],true));
assert.equal(presentation.selectWorkflow([{id:'text',available:true,category:'concept'}]),undefined);
assert.equal(presentation.selectWorkflow([{available:false,parameters:[{name:'input_image_path',type:'image'}]}]),undefined);
assert.equal(presentation.selectWorkflow([{available:true,parameters:[{name:'input_image_path',type:'image'}, {name:'other',type:'image',required:true}]}]),undefined);
const page=fs.readFileSync('ui/app.html','utf8');
assert.ok(page.indexOf('early_design_presentation.js')<page.indexOf('early_design.js'));
// Inject only rasterization; execute the real render handler and real selection/prompt code.
presentation.png=async svg=>{references.push(svg);return new Blob(['PNG reference test'],{type:'image/png'});};
(async()=>{
  await context.window.edRender();
  assert.equal(submissions.length,1);assert.ok(state.render[0].views.primary);
  fields.edRenderView.value='reverse'; await context.window.edRender();
  assert.equal(submissions.length,2);assert.ok(state.render[0].views.primary);assert.ok(state.render[0].views.reverse);
  assert.notEqual(references[0],references[1]);
  assert.equal(submissions[0].get('seed'),submissions[1].get('seed'),'Reuse the design seed between viewpoints');
  assert.match(submissions[0].get('prompt'),/Do not remove or add floors/);
  available=false; await context.window.edRender();
  assert.equal(submissions.length,2);assert.match(messages.at(-1),/No available image-reference workflow/);
  available=true; changed=true; await context.window.edRender();
  assert.equal(submissions.length,2);assert.match(messages.at(-1),/design changed/);
  changed=false;state.result=fixture.result;state.current=0;state.view='board';
  const root={scrollTop:0};
  const container={innerHTML:'',querySelector:()=>root,querySelectorAll:()=>[]};
  context.document.body={contains:()=>true};
  context.document.getElementById=id=>fields[id];
  context.window.renderEarlyDesignWorkspace(container);
  assert.match(container.innerHTML,/Floor zoning — calculated geometry/);
  assert.match(container.innerHTML,/Reverse view — AI visual concept/);
  assert.doesNotMatch(container.innerHTML,/<script>alert/);
  assert.ok(container.innerHTML.includes(`GFA ${fixture.result.options[0].metrics.gfa} m²`));
  const siteBox=container.innerHTML.match(/Site plan — calculated geometry<\/figcaption>[\s\S]*?viewBox="([^"]+)"/)[1].split(/[ ,]+/).map(Number);
  const floorBox=container.innerHTML.match(/Floor zoning — calculated geometry<\/figcaption>[\s\S]*?viewBox="([^"]+)"/)[1].split(/[ ,]+/).map(Number);
  assert.ok(floorBox[2]<siteBox[2], 'Board floor plan must zoom to the floorplate rather than the entire plot');
  // Export a portable geometry-only QA board. No generated image is invented for this preview.
  const article=container.innerHTML.match(/<article class="ed-board">[\s\S]*?<\/article>/)[0]
    .replace(/<figure><figcaption>[^<]*AI visual concept<\/figcaption>[\s\S]*?<\/figure>/g,'');
  fs.writeFileSync(path.join(directory,'concept-board-preview.html'),`<!doctype html><meta charset="utf-8"><style>${presentation.css}</style>${article}`);
  fs.writeFileSync(path.join(directory,'reference.svg'),references[0]);
  fs.writeFileSync(path.join(directory,'reference-reverse.svg'),references[1]);
  console.log('PASS: four typologies, geometry references, two render submissions, unavailable-workflow handling, stale-design guard, board composition and escaped labels.');
})().catch(e=>{console.error(e);process.exitCode=1;});
