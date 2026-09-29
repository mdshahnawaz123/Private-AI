import * as THREE from "three";
import { OrbitControls } from "/ui/vendor/OrbitControls.js";
import * as WebIFC from "/ui/vendor/web-ifc-api.js";

const $ = (id) => document.getElementById(id);
const viewEl = $("view"), loadingEl = $("loading"), errEl = $("err");
function showErr(msg){ errEl.style.display="block"; errEl.innerHTML = msg; }
function setLoading(t){ if(t===null){ loadingEl.style.display="none"; } else { loadingEl.style.display="grid"; loadingEl.textContent=t; } }

// ---- query params ----
const q = new URLSearchParams(location.search);
const project = q.get("project") || "";
const token = q.get("token") || "";
const rels = q.getAll("rel");
function fileURL(rel){ return `${location.origin}/projects/${encodeURIComponent(project)}/file?rel=${encodeURIComponent(rel)}&token=${encodeURIComponent(token)}`; }

// ---- three scene (Z-up for BIM) ----
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e14);
const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100000);
camera.up.set(0,0,1);
const renderer = new THREE.WebGLRenderer({ antialias:true });
renderer.localClippingEnabled = true;
viewEl.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
scene.add(new THREE.HemisphereLight(0xffffff, 0x30363f, 1.05));
const dir = new THREE.DirectionalLight(0xffffff, 0.8); dir.position.set(1,1,2); scene.add(dir);
const dir2 = new THREE.DirectionalLight(0xffffff, 0.4); dir2.position.set(-1,-1,1); scene.add(dir2);
const grid = new THREE.GridHelper(200, 40, 0x2a3a50, 0x18222f); grid.rotation.x = Math.PI/2; scene.add(grid);
const root = new THREE.Group(); scene.add(root); // holds all models; rotated for True/Project North

function resize(){ const w=viewEl.clientWidth, h=viewEl.clientHeight; renderer.setSize(w,h,false); camera.aspect=w/h; camera.updateProjectionMatrix(); }
window.addEventListener("resize", resize);
(function loop(){ requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

// ---- state ----
const HL = new THREE.Color(0x4d7cfe);
let allMeshes = [];                 // every mesh
const models = [];                  // {name, modelID, group, meshes}
const catMap = new Map();           // typeName -> [meshes]
let selection = [];                 // current selection set (meshes)
const clip = { plane:null, axis:null, sign:1, box:null };

// ---- IFC engine ----
const ifcAPI = new WebIFC.IfcAPI();
ifcAPI.SetWasmPath("/ui/vendor/");

function typeName(code){
  try { if (ifcAPI.GetNameFromTypeCode) return ifcAPI.GetNameFromTypeCode(code); } catch(e){}
  return "Type " + code;
}

let coordMatrix = null;   // shared origin-shift from the FIRST model (common world frame)
async function loadModel(rel, isFirst){
  setLoading("Reading " + rel.split("/").pop() + " …");
  const res = await fetch(fileURL(rel));
  if(!res.ok) throw new Error("Could not fetch " + rel + " (" + res.status + ")");
  const data = new Uint8Array(await res.arrayBuffer());
  // Items 6 & 8: normalise large survey coordinates for float precision AND keep every
  // model in ONE common world frame. The first model defines the origin shift (its
  // coordination matrix); later models reuse the SAME shift so they stay aligned to it.
  let modelID;
  if(isFirst){
    modelID = ifcAPI.OpenModel(data, { COORDINATE_TO_ORIGIN:true });
    try { coordMatrix = ifcAPI.GetCoordinationMatrix(modelID); } catch(e){ coordMatrix = null; }
  } else if(coordMatrix){
    modelID = ifcAPI.OpenModel(data, { COORDINATE_TO_ORIGIN:false });
    try { ifcAPI.SetGeometryTransformation(modelID, coordMatrix); } catch(e){}
  } else {
    modelID = ifcAPI.OpenModel(data, { COORDINATE_TO_ORIGIN:true });
  }
  const group = new THREE.Group(); group.name = rel;
  const meshes = [];
  ifcAPI.StreamAllMeshes(modelID, (flatMesh) => {
    const eid = flatMesh.expressID;
    let tName = "Element";
    try { tName = typeName(ifcAPI.GetLineType(modelID, eid)); } catch(e){}
    const geoms = flatMesh.geometries;
    for (let i=0;i<geoms.size();i++){
      const pg = geoms.get(i);
      const g = ifcAPI.GetGeometry(modelID, pg.geometryExpressID);
      const vArr = ifcAPI.GetVertexArray(g.GetVertexData(), g.GetVertexDataSize());
      const iArr = ifcAPI.GetIndexArray(g.GetIndexData(), g.GetIndexDataSize());
      const n = vArr.length/6;
      const pos = new Float32Array(n*3), nor = new Float32Array(n*3);
      for (let v=0,j=0; j<n; v+=6, j++){ pos[j*3]=vArr[v];pos[j*3+1]=vArr[v+1];pos[j*3+2]=vArr[v+2];nor[j*3]=vArr[v+3];nor[j*3+1]=vArr[v+4];nor[j*3+2]=vArr[v+5]; }
      const bg = new THREE.BufferGeometry();
      bg.setAttribute("position", new THREE.BufferAttribute(pos,3));
      bg.setAttribute("normal", new THREE.BufferAttribute(nor,3));
      bg.setIndex(new THREE.BufferAttribute(new Uint32Array(iArr),1));
      bg.applyMatrix4(new THREE.Matrix4().fromArray(pg.flatTransformation));
      const c = pg.color;
      const baseCol = new THREE.Color(c.x, c.y, c.z);
      const mat = new THREE.MeshLambertMaterial({ color: baseCol, side: THREE.DoubleSide, transparent: c.w<0.999, opacity: c.w });
      const mesh = new THREE.Mesh(bg, mat);
      mesh.userData = { modelID, expressID: eid, typeName: tName, origColor: baseCol.clone(), origOpacity: c.w };
      group.add(mesh); meshes.push(mesh); allMeshes.push(mesh);
      if(!catMap.has(tName)) catMap.set(tName, []);
      catMap.get(tName).push(mesh);
    }
  });
  root.add(group);
  models.push({ name: rel, modelID, group, meshes });
  return { modelID, meshes };
}

function bboxAll(){
  const box = new THREE.Box3();
  allMeshes.forEach(m => { m.geometry.computeBoundingBox(); box.union(m.geometry.boundingBox); });
  return box;
}
function fit(){
  if(!allMeshes.length) return;
  const box = bboxAll(); const c = box.getCenter(new THREE.Vector3()); const s = box.getSize(new THREE.Vector3());
  const r = Math.max(s.x,s.y,s.z) || 10;
  controls.target.copy(c);
  camera.up.set(0,0,1);
  // 3/4 view; when Plan North is on, yaw the VIEWPOINT by the IFC north angle so the
  // building reads square to the plan. View only — geometry keeps true IFC coordinates.
  const off = new THREE.Vector3(r*1.2, -r*1.4, r*1.1);
  if(planNorth && Math.abs(northAngle)>1e-4) off.applyAxisAngle(new THREE.Vector3(0,0,1), northAngle);
  camera.position.copy(c).add(off);
  camera.near = r/1000; camera.far = r*50; camera.updateProjectionMatrix();
  controls.update();
}
$("btnFit").onclick = fit;
$("btnReset").onclick = () => { clearSection(); showAll(); clearMeasure(); resetColors(); selection=[]; renderSel(); $("storeySel").value=""; fit(); };

// ---- model + category lists ----
function renderModelList(){
  const box = $("modelList"); box.innerHTML = "";
  models.forEach((m,i) => {
    const row = document.createElement("div"); row.className="mrow";
    const cb = document.createElement("input"); cb.type="checkbox"; cb.checked=true;
    cb.onchange = () => { m.group.visible = cb.checked; };
    const dot = document.createElement("span"); dot.className="mdot"; dot.style.background = ["#4d7cfe","#31d0a5","#f5b73d","#8a6cff","#f2585f"][i%5];
    const nm = document.createElement("span"); nm.className="mname"; nm.textContent = m.name.split("/").pop(); nm.title=m.name;
    row.appendChild(cb); row.appendChild(dot); row.appendChild(nm); box.appendChild(row);
  });
}
function renderCatList(){
  const box = $("catList"); box.innerHTML = "";
  [...catMap.keys()].sort().forEach(t => {
    const row = document.createElement("div"); row.className="catrow";
    row.textContent = t.replace(/^IFC/,"") + "  (" + catMap.get(t).length + ")";
    row.onclick = () => { selection = catMap.get(t).slice(); renderSel(); showProps(null, t); };
    box.appendChild(row);
  });
}

// ---- selection + highlight ----
function renderSel(){
  allMeshes.forEach(m => { if(m.material.emissive){ m.material.emissive.setRGB(0,0,0); } });
  selection.forEach(m => { if(m.material.emissive){ m.material.emissive.copy(HL).multiplyScalar(0.5); } });
}
const ray = new THREE.Raycaster(); const mouse = new THREE.Vector2();
function pick(ev){
  const r = renderer.domElement.getBoundingClientRect();
  mouse.x = ((ev.clientX-r.left)/r.width)*2-1; mouse.y = -((ev.clientY-r.top)/r.height)*2+1;
  ray.setFromCamera(mouse, camera);
  const hits = ray.intersectObjects(allMeshes.filter(m=>m.visible), false);
  return hits.length ? hits[0] : null;
}
renderer.domElement.addEventListener("pointerdown", (ev) => {
  if(ev.button!==0) return;
  if(measureMode){ handleMeasureClick(ev); return; }
  const hit = pick(ev);
  if(hit){ selection = [hit.object]; renderSel(); showProps(hit.object); }
  else { selection = []; renderSel(); showProps(null); }
});

function attr(line, k){ try{ return line[k] && (line[k].value!==undefined? line[k].value : line[k]); }catch(e){ return undefined; } }
function showProps(mesh, catName){
  const box = $("propBox");
  if(catName && !mesh){ box.innerHTML = `<div class="prop"><b>Category selected</b>${catName} — ${catMap.get(catName).length} elements</div>`; return; }
  if(!mesh){ box.innerHTML = `<div class="hint">Click an element in the model to see its properties.</div>`; return; }
  const { modelID, expressID, typeName } = mesh.userData;
  let name="", gid="", objType="";
  try { const line = ifcAPI.GetLine(modelID, expressID, true); name = attr(line,"Name")||""; gid = attr(line,"GlobalId")||""; objType = attr(line,"ObjectType")||""; } catch(e){}
  box.innerHTML =
    `<div class="prop"><b>Type</b>${typeName}</div>` +
    (name?`<div class="prop"><b>Name</b>${name}</div>`:"") +
    (objType?`<div class="prop"><b>Object type</b>${objType}</div>`:"") +
    (gid?`<div class="prop"><b>Global ID</b>${gid}</div>`:"") +
    `<div class="prop"><b>Express ID</b>${expressID}</div>`;
}

// ---- visibility ----
function showAll(){ allMeshes.forEach(m=>m.visible=true); }
$("btnShowAll").onclick = showAll;
$("btnHide").onclick = () => { if(!selection.length){ hint("Select an element or category first"); return; } selection.forEach(m=>m.visible=false); };
$("btnIso").onclick = () => { if(!selection.length){ hint("Select an element or category first"); return; } const set=new Set(selection); allMeshes.forEach(m=>m.visible=set.has(m)); };

// ---- color override ----
$("btnColSel").onclick = () => {
  if(!selection.length){ hint("Select an element or category first"); return; }
  const c = new THREE.Color($("colPick").value);
  selection.forEach(m=>{ m.material.color.copy(c); m.material.needsUpdate=true; });
};
function resetColors(){ allMeshes.forEach(m=>{ m.material.color.copy(m.userData.origColor); m.material.opacity=m.userData.origOpacity; m.material.transparent=m.userData.origOpacity<0.999; m.material.needsUpdate=true; }); }
$("btnColReset").onclick = resetColors;

// ---- section / clipping ----
function applyClip(){
  renderer.clippingPlanes = clip.plane ? [clip.plane] : [];
}
function setSection(axis){
  const box = bboxAll(); clip.box = box; clip.axis = axis; clip.sign = 1;
  const min = box.min, max = box.max;
  const normal = new THREE.Vector3(axis==="x"?1:0, axis==="y"?1:0, axis==="z"?1:0);
  clip.plane = new THREE.Plane(normal.clone(), 0);
  moveSection(50);
  document.querySelectorAll("[data-ax]").forEach(b=>b.classList.toggle("on", b.dataset.ax===axis));
  applyClip();
}
function moveSection(pct){
  if(!clip.plane) return;
  const b = clip.box; const a = clip.axis;
  const lo = a==="x"?b.min.x:a==="y"?b.min.y:b.min.z;
  const hi = a==="x"?b.max.x:a==="y"?b.max.y:b.max.z;
  const at = lo + (hi-lo)*(pct/100);
  const n = new THREE.Vector3(a==="x"?1:0, a==="y"?1:0, a==="z"?1:0).multiplyScalar(clip.sign);
  clip.plane.normal.copy(n);
  clip.plane.constant = -clip.sign*at;
}
function clearSection(){ clip.plane=null; clip.axis=null; applyClip(); document.querySelectorAll("[data-ax]").forEach(b=>b.classList.remove("on")); }
document.querySelectorAll("[data-ax]").forEach(b=> b.onclick = ()=> setSection(b.dataset.ax));
$("secOff").onclick = clearSection;
$("secInvert").onclick = ()=>{ if(!clip.plane) return; clip.sign*=-1; moveSection(+$("secSlide").value); };
$("secSlide").oninput = (e)=> moveSection(+e.target.value);

// ---- floor plans (via storey + top view) ----
let storeys = [];
function loadStoreys(){
  const sel = $("storeySel");
  models.forEach(m=>{
    let ids; try{ ids = ifcAPI.GetLineIDsWithType(m.modelID, WebIFC.IFCBUILDINGSTOREY); }catch(e){ return; }
    for(let i=0;i<ids.size();i++){
      let line; try{ line = ifcAPI.GetLine(m.modelID, ids.get(i)); }catch(e){ continue; }
      const nm = (line.Name&&line.Name.value)||("Level "+i);
      const el = (line.Elevation&&line.Elevation.value)||0;
      storeys.push({ name:nm, elev:el });
    }
  });
  storeys.sort((a,b)=>a.elev-b.elev);
  storeys.forEach((s,i)=>{ const o=document.createElement("option"); o.value=i; o.textContent = s.name + "  (" + s.elev.toFixed(2) + ")"; sel.appendChild(o); });
}
$("storeySel").onchange = (e)=>{
  const v = e.target.value;
  if(v===""){ clearSection(); fit(); return; }
  const s = storeys[+v]; const box = bboxAll();
  // horizontal cut ~1.4 above storey, looking down = plan
  clip.box = box; clip.axis="z"; clip.sign=-1;
  clip.plane = new THREE.Plane(new THREE.Vector3(0,0,-1), (s.elev+1.4));
  applyClip();
  const c = box.getCenter(new THREE.Vector3()); const sz = box.getSize(new THREE.Vector3());
  const r = Math.max(sz.x,sz.y);
  controls.target.set(c.x,c.y,s.elev);
  // Plan North: screen-up follows the building's local +Y (project north); else world +Y.
  camera.up.copy(planNorth && Math.abs(northAngle)>1e-4
    ? new THREE.Vector3(-Math.sin(northAngle), Math.cos(northAngle), 0)
    : new THREE.Vector3(0,1,0));
  camera.position.set(c.x, c.y, s.elev + r*1.6);
  controls.update();
};

// ---- measurement ----
let measureMode = null; // 'len' | 'area'
let mPts = []; let mObjs = [];
function hint(t){ $("modeHint").textContent = t; }
function clearMeasure(){ mObjs.forEach(o=>scene.remove(o)); mObjs=[]; mPts=[]; $("measureOut").textContent="—"; }
$("btnMclr").onclick = ()=>{ clearMeasure(); };
$("btnLen").onclick = ()=>{ measureMode = measureMode==="len"?null:"len"; mPts=[]; toggleMeasureBtns(); hint(measureMode?"Click two points to measure length":""); };
$("btnArea").onclick = ()=>{ measureMode = measureMode==="area"?null:"area"; mPts=[]; toggleMeasureBtns(); hint(measureMode?"Click points, then click Area again to finish":""); };
function toggleMeasureBtns(){ $("btnLen").classList.toggle("on", measureMode==="len"); $("btnArea").classList.toggle("on", measureMode==="area"); }
function dot(p, col){ const s=new THREE.Mesh(new THREE.SphereGeometry(0.06,10,10), new THREE.MeshBasicMaterial({color:col})); s.position.copy(p); s.scale.setScalar(sceneScale()); scene.add(s); mObjs.push(s); return s; }
function sceneScale(){ const b=bboxAll(); const sz=b.getSize(new THREE.Vector3()); return Math.max(0.3, Math.max(sz.x,sz.y,sz.z)/120); }
function line(a,b,col){ const g=new THREE.BufferGeometry().setFromPoints([a,b]); const l=new THREE.Line(g,new THREE.LineBasicMaterial({color:col})); scene.add(l); mObjs.push(l); }
function handleMeasureClick(ev){
  const hit = pick(ev); if(!hit) return;
  const p = hit.point.clone(); mPts.push(p); dot(p, 0xf5b73d);
  if(measureMode==="len"){
    if(mPts.length>=2){ const a=mPts[mPts.length-2], b=mPts[mPts.length-1]; line(a,b,0xf5b73d); const d=a.distanceTo(b); $("measureOut").textContent = "Length: " + d.toFixed(3) + " m"; }
  } else if(measureMode==="area"){
    if(mPts.length>=2){ line(mPts[mPts.length-2], mPts[mPts.length-1], 0x31d0a5); }
    if(mPts.length>=3){ $("measureOut").textContent = "Area: " + polyArea(mPts).toFixed(3) + " m²  (" + mPts.length + " pts)"; }
  }
}
function polyArea(pts){ // Newell's method (planar polygon area in 3D)
  const n = new THREE.Vector3();
  for(let i=0;i<pts.length;i++){ const a=pts[i], b=pts[(i+1)%pts.length]; n.x += (a.y-b.y)*(a.z+b.z); n.y += (a.z-b.z)*(a.x+b.x); n.z += (a.x-b.x)*(a.y+b.y); }
  return n.length()/2;
}

// ---- AI: model-context builder + property extraction ----
let _psetMap = null;
function buildPsetMap(){
  if(_psetMap) return _psetMap;
  _psetMap = new Map(); // "modelID:expressID" -> [{name, props:[{k,v}]}]
  models.forEach(m=>{
    let rels; try{ rels = ifcAPI.GetLineIDsWithType(m.modelID, WebIFC.IFCRELDEFINESBYPROPERTIES); }catch(e){ return; }
    for(let i=0;i<rels.size();i++){
      let rel; try{ rel = ifcAPI.GetLine(m.modelID, rels.get(i), true); }catch(e){ continue; }
      const def = rel.RelatingPropertyDefinition; if(!def) continue;
      const psetName = (def.Name && def.Name.value) || "";
      const list = def.HasProperties || def.Quantities || [];
      const entries = [];
      (Array.isArray(list)?list:[]).forEach(p=>{
        if(!p) return;
        const k = (p.Name && p.Name.value) || "";
        let v;
        if(p.NominalValue && p.NominalValue.value!==undefined) v = p.NominalValue.value;
        else { ["AreaValue","LengthValue","VolumeValue","CountValue","WeightValue"].forEach(q=>{ if(p[q] && p[q].value!==undefined) v = p[q].value; }); }
        if(k) entries.push({k, v});
      });
      const objs = rel.RelatedObjects || [];
      (Array.isArray(objs)?objs:[]).forEach(o=>{
        const eid = o && (o.value!==undefined ? o.value : o.expressID);
        if(eid===undefined || eid===null) return;
        const key = m.modelID + ":" + eid;
        if(!_psetMap.has(key)) _psetMap.set(key, []);
        _psetMap.get(key).push({name:psetName, props:entries});
      });
    }
  });
  return _psetMap;
}
function collectSpaces(){
  const out = []; const pmap = buildPsetMap();
  models.forEach(m=>{
    let ids; try{ ids = ifcAPI.GetLineIDsWithType(m.modelID, WebIFC.IFCSPACE); }catch(e){ return; }
    for(let i=0;i<ids.size();i++){
      const eid = ids.get(i);
      let line; try{ line = ifcAPI.GetLine(m.modelID, eid); }catch(e){ continue; }
      const name = (line.LongName && line.LongName.value) || (line.Name && line.Name.value) || ("Space " + eid);
      let area = 0;
      (pmap.get(m.modelID + ":" + eid) || []).forEach(ps=> ps.props.forEach(p=>{
        if(/area/i.test(p.k) && typeof p.v === "number"){ if(/gross/i.test(p.k) || !area) area = p.v; }
      }));
      out.push({name, area});
    }
  });
  return out;
}
function buildModelContext(){
  const L = [];
  L.push("PROJECT: " + project);
  L.push("MODELS LOADED: " + (models.map(m=>m.name.split("/").pop()).join(", ") || "(none)"));
  if(storeys.length){
    L.push("");
    L.push("BUILDING STOREYS / LEVELS (" + storeys.length + "), low to high:");
    storeys.forEach(s=> L.push("  - " + s.name + "  (elevation " + s.elev.toFixed(2) + ")"));
  }
  const cats = [...catMap.keys()].sort((a,b)=> catMap.get(b).length - catMap.get(a).length);
  let total = 0; cats.forEach(t=> total += catMap.get(t).length);
  L.push("");
  L.push("ELEMENT COUNTS BY IFC TYPE (total geometric elements: " + total + "):");
  cats.forEach(t=> L.push("  - " + t + ": " + catMap.get(t).length));
  let spaces = []; try{ spaces = collectSpaces(); }catch(e){}
  if(spaces.length){
    L.push("");
    L.push("SPACES / ROOMS (" + spaces.length + "):");
    let ta = 0;
    spaces.slice(0,300).forEach(s=>{ if(s.area) ta += s.area; L.push("  - " + s.name + (s.area ? ("  area " + s.area.toFixed(2) + " m2") : "")); });
    if(spaces.length>300) L.push("  ...(" + (spaces.length-300) + " more spaces not listed)");
    if(ta) L.push("  TOTAL LISTED SPACE AREA: " + ta.toFixed(2) + " m2");
  }
  return L.join("\n");
}
function selectedElementContext(){
  if(selection.length !== 1) return "";
  const mesh = selection[0];
  const { modelID, expressID, typeName } = mesh.userData;
  let name="", gid="", objType="";
  try{ const line = ifcAPI.GetLine(modelID, expressID, true); name=attr(line,"Name")||""; gid=attr(line,"GlobalId")||""; objType=attr(line,"ObjectType")||""; }catch(e){}
  const L = [];
  L.push("IFC type: " + typeName);
  if(name) L.push("Name: " + name);
  if(objType) L.push("ObjectType: " + objType);
  if(gid) L.push("GlobalId: " + gid);
  L.push("ExpressID: " + expressID);
  let pmap; try{ pmap = buildPsetMap(); }catch(e){ pmap = new Map(); }
  (pmap.get(modelID + ":" + expressID) || []).forEach(ps=>{
    if(!ps.props.length) return;
    L.push("Property set '" + (ps.name || "(unnamed)") + "':");
    ps.props.forEach(p=> L.push("  - " + p.k + ": " + (p.v!==undefined && p.v!==null ? p.v : "")));
  });
  return L.join("\n");
}

// ---- AI: chat UI + streaming ----
const aiHistory = [];
function aiOpen(v){ const p=$("aiPanel"); const open = v!==undefined?v:!p.classList.contains("open"); p.classList.toggle("open", open); const fab=$("aiFab"); if(fab) fab.classList.toggle("hidden", open); if(open) $("aiInput").focus(); }
function scrollAI(){ const b=$("aiMsgs"); b.scrollTop = b.scrollHeight; }
function appendMsg(role, text){ const d=document.createElement("div"); d.className="aimsg "+role; d.textContent=text; $("aiMsgs").appendChild(d); scrollAI(); return d; }
async function askAI(){
  const inp = $("aiInput"); const q = (inp.value||"").trim(); if(!q) return;
  inp.value="";
  appendMsg("user", q);
  const prior = aiHistory.slice(-8);
  aiHistory.push({role:"user", content:q});
  const ctx = buildModelContext();
  const sel = $("aiInclSel").checked ? selectedElementContext() : "";
  const bubble = appendMsg("ai", "…");
  let answer = "";
  try{
    const res = await fetch(location.origin + "/ask_model", {
      method:"POST",
      headers:{ "Content-Type":"application/json", "Authorization":"Bearer " + token },
      body: JSON.stringify({ project, query:q, context:ctx, selection:sel, messages:prior })
    });
    if(!res.ok){ bubble.textContent = "Error " + res.status + ": " + (await res.text()).slice(0,200); return; }
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf="";
    while(true){
      const {value, done} = await reader.read(); if(done) break;
      buf += dec.decode(value, {stream:true});
      let idx;
      while((idx = buf.indexOf("\n\n")) >= 0){
        const line = buf.slice(0, idx); buf = buf.slice(idx+2);
        const dl = line.split("\n").find(l=>l.startsWith("data:")); if(!dl) continue;
        let d; try{ d = JSON.parse(dl.slice(5).trim()); }catch(e){ continue; }
        if(d.type==="token"){ answer += d.text; bubble.textContent = answer; scrollAI(); }
        else if(d.type==="error"){ answer += "\n[error] " + d.message; bubble.textContent = answer; }
      }
    }
    if(!answer) bubble.textContent = "(no answer)";
    aiHistory.push({role:"assistant", content:answer});
  }catch(e){ bubble.textContent = "Request failed: " + (e && e.message ? e.message : e); }
}
if($("btnAI")) $("btnAI").onclick = ()=> aiOpen();
if($("aiFab")) $("aiFab").onclick = ()=> aiOpen(true);
if($("aiClose")) $("aiClose").onclick = ()=> aiOpen(false);
if($("aiSend")) $("aiSend").onclick = askAI;
if($("aiInput")) $("aiInput").addEventListener("keydown", (e)=>{ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); askAI(); } });

// ---- North alignment (Project North vs True North) — VIEW ONLY ----
// The IFC (Revit "Shared Coordinates") georeferences the building through the IfcSite
// placement, which carries the True-North rotation and the survey translation.
// web-ifc's flatTransformation already applies the FULL IfcLocalPlacement hierarchy
// (Project -> Site -> Building -> Storey -> Element), so the geometry is already in
// correct IFC world coordinates. We DO NOT rotate or move the geometry. We only detect
// the site rotation and rotate the CAMERA so the model reads square to the 2D plans.
let northAngle = 0;     // radians: angle of the building's local +X in world (from IfcSite)
let planNorth = true;   // true = view rotated to Project North (matches the plans)
function _dr(v){ return (v && v.value!==undefined) ? v.value : v; }
function detectNorthAngle(){
  for(const m of models){
    for(const tcode of [WebIFC.IFCSITE, WebIFC.IFCBUILDING]){
      let ids; try{ ids = ifcAPI.GetLineIDsWithType(m.modelID, tcode); }catch(e){ continue; }
      for(let i=0;i<ids.size();i++){
        let el; try{ el = ifcAPI.GetLine(m.modelID, ids.get(i), true); }catch(e){ continue; }
        let node = el.ObjectPlacement, guard=0;
        while(node && guard++<8){
          const rp = node.RelativePlacement;
          const rd = rp && rp.RefDirection && rp.RefDirection.DirectionRatios;
          if(rd && rd.length>=2){
            const x=_dr(rd[0]), y=_dr(rd[1]);
            if(typeof x==="number" && typeof y==="number" && (Math.abs(x-1)>1e-6 || Math.abs(y)>1e-6)){
              return Math.atan2(y, x);
            }
          }
          node = node.PlacementRelTo || null;
        }
      }
    }
  }
  return 0;
}
function applyNorthBtn(){
  const b = $("btnAlign"); if(!b) return;
  if(Math.abs(northAngle) < 1e-4){ b.style.display = "none"; return; }
  b.textContent = planNorth ? "Plan North" : "True North";
  b.classList.toggle("on", planNorth);
  b.title = "IFC True North is " + (northAngle*180/Math.PI).toFixed(2) + "° from Project North (IfcSite placement). "
          + "This rotates the VIEW only — the model keeps its true IFC coordinates.";
}
function reapplyView(){ const sv=$("storeySel"); if(sv && sv.value!==""){ sv.onchange({target:sv}); } else { fit(); } }
if($("btnAlign")) $("btnAlign").onclick = ()=>{ planNorth = !planNorth; applyNorthBtn(); reapplyView(); };

// ---- Debug: IFC coordinate / transform audit ----
function _lenUnit(modelID){
  try{
    const proj = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCPROJECT);
    if(proj.size()){
      const pr = ifcAPI.GetLine(modelID, proj.get(0), true);
      const units = (pr.UnitsInContext && pr.UnitsInContext.Units) || [];
      for(const u of (Array.isArray(units)?units:[])){
        const ut = u && u.UnitType && String(_dr(u.UnitType));
        if(ut && ut.indexOf("LENGTHUNIT")>=0){
          const name = String(_dr(u.Name)||""), prefix = String(_dr(u.Prefix)||"").replace(/[.]/g,"");
          const pmap = {MEGA:1e6,KILO:1e3,HECTO:1e2,DECA:1e1,"":1,DECI:1e-1,CENTI:1e-2,MILLI:1e-3,MICRO:1e-6};
          const metres = (pmap[prefix]!==undefined?pmap[prefix]:1);
          return { label:(prefix?prefix+".":"")+name.replace("IFC","").replace(/[.]/g,""), metres };
        }
      }
    }
  }catch(e){}
  return { label:"?", metres:1 };
}
function _trueNorthDeg(modelID){
  try{
    const ctxs = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCGEOMETRICREPRESENTATIONCONTEXT);
    for(let i=0;i<ctxs.size();i++){
      const c = ifcAPI.GetLine(modelID, ctxs.get(i), true);
      const tn = c.TrueNorth && c.TrueNorth.DirectionRatios;
      if(tn && tn.length>=2){ return Math.atan2(_dr(tn[0]), _dr(tn[1]))*180/Math.PI; }
    }
  }catch(e){}
  return null;
}
function _siteInfo(modelID){
  try{
    const ids = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCSITE);
    if(ids.size()){
      const el = ifcAPI.GetLine(modelID, ids.get(0), true);
      const rp = el.ObjectPlacement && el.ObjectPlacement.RelativePlacement;
      const loc = rp && rp.Location && rp.Location.Coordinates;
      const rd = rp && rp.RefDirection && rp.RefDirection.DirectionRatios;
      return { origin: loc?loc.map(_dr):null, refDir: rd?rd.map(_dr):null };
    }
  }catch(e){}
  return {};
}
function buildDebug(){
  if(!models.length) return;
  const m0 = models[0].modelID;
  const box = bboxAll(); const sz=box.getSize(new THREE.Vector3()), mn=box.min, mx=box.max;
  const unit = _lenUnit(m0), tn = _trueNorthDeg(m0), sp = _siteInfo(m0);
  let hasMap = 0; try{ if(WebIFC.IFCMAPCONVERSION) hasMap = ifcAPI.GetLineIDsWithType(m0, WebIFC.IFCMAPCONVERSION).size(); }catch(e){}
  const cm = coordMatrix ? Array.from(coordMatrix) : null;
  const f = (a,n=2)=> a ? "["+a.map(v=>(+v).toFixed(n)).join(", ")+"]" : "—";
  const big = Math.max(sz.x,sz.y,sz.z) > 400;
  const rows = [
    ["Models in world frame", rels.length + (coordMatrix?"  (shared origin)":"")],
    ["IFC length unit", unit.label + "  →  " + unit.metres + " m/unit"],
    ["World geometry scale", big ? "file units ≈ mm (large)" : "metres (web-ifc scaled)"],
    ["True North (context)", tn===null ? "identity 0°" : tn.toFixed(3)+"° from +Y"],
    ["IfcSite origin", f(sp.origin,1)],
    ["IfcSite RefDirection", f(sp.refDir,4)],
    ["Site rotation applied to view", (northAngle*180/Math.PI).toFixed(3)+"°"],
    ["IfcMapConversion / CRS", hasMap ? (hasMap+" present") : "none (IFC2x3)"],
    ["Origin shift (coord. matrix t)", cm ? f([cm[12],cm[13],cm[14]],2) : "per-model"],
    ["World bbox min", f([mn.x,mn.y,mn.z],2)],
    ["World bbox max", f([mx.x,mx.y,mx.z],2)],
    ["World size (x,y,z)", f([sz.x,sz.y,sz.z],2)],
    ["View mode", planNorth ? "Plan North (view yawed)" : "True North (raw)"],
  ];
  try{ console.log("[Expo3D] IFC transform audit:", Object.fromEntries(rows)); }catch(e){}
  const body = $("dbgBody");
  if(body){ body.innerHTML = rows.map(([k,v])=>`<div class="drow"><span>${k}</span><b>${v}</b></div>`).join(""); }
}
if($("btnDebug")) $("btnDebug").onclick = ()=>{ const p=$("dbgPanel"); if(p){ const open=!p.classList.contains("open"); p.classList.toggle("open",open); if(open) buildDebug(); } };
if($("dbgClose")) $("dbgClose").onclick = ()=>{ const p=$("dbgPanel"); if(p) p.classList.remove("open"); };

// ---- boot ----
(async () => {
  try {
    await ifcAPI.Init();
    if(!rels.length){ setLoading(null); showErr("No model selected. Pick an IFC from the 3D Review tab."); return; }
    for(let i=0;i<rels.length;i++){ await loadModel(rels[i], i===0); }
    northAngle = detectNorthAngle();
    applyNorthBtn();
    renderModelList(); renderCatList(); loadStoreys();
    buildDebug();
    resize(); fit(); setLoading(null);
  } catch(e){
    setLoading(null);
    showErr("<b>Viewer failed to start.</b><br>" + (e && e.message ? e.message : e) +
      "<br><br>If this is the first run, make sure you ran <b>setup_3d_viewer.bat</b> once (it downloads the 3D engine into ui\\vendor).");
    console.error(e);
  }
})();
