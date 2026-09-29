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
const EXPO_EMBED = q.get("embed")==="1";
if(EXPO_EMBED){ const s=document.createElement("style");
  s.textContent="#right{display:none!important}#aiFab{display:none!important}#wrap{grid-template-columns:220px 1fr 0!important}";
  (document.head||document.documentElement).appendChild(s); }
function fileURL(rel){ return `${location.origin}/projects/${encodeURIComponent(project)}/file?rel=${encodeURIComponent(rel)}&token=${encodeURIComponent(token)}`; }

// ---- three scene (Y-up, matching web-ifc geometry output) ----
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e14);
const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100000);
camera.up.set(0,1,0);
const renderer = new THREE.WebGLRenderer({ antialias:true });
renderer.localClippingEnabled = true;
viewEl.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
scene.add(new THREE.HemisphereLight(0xffffff, 0x30363f, 1.05));
const dir = new THREE.DirectionalLight(0xffffff, 0.8); dir.position.set(1,1,2); scene.add(dir);
const dir2 = new THREE.DirectionalLight(0xffffff, 0.4); dir2.position.set(-1,-1,1); scene.add(dir2);
const grid = new THREE.GridHelper(200, 40, 0x2a3a50, 0x18222f); scene.add(grid); // Y-up: default GridHelper lies in the horizontal X-Z plane
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
  // Frames the real building: excludes far outlier "stray" geometry (survey-coordinate
  // slivers) so Fit does not zoom out. Never moves geometry — outliers still exist,
  // they are only left out of framing (and hidden by classifyStrays unless shown).
  const box = new THREE.Box3();
  allMeshes.forEach(m => { if(m.userData && m.userData.outlier) return; m.geometry.computeBoundingBox(); box.union(m.geometry.boundingBox); });
  if(box.isEmpty()){ allMeshes.forEach(m => { m.geometry.computeBoundingBox(); box.union(m.geometry.boundingBox); }); }
  return box;
}
let showOutliers=false, outlierCount=0;
function _pct(arr,p){ const s=arr.slice().sort((a,b)=>a-b); return s[Math.min(s.length-1, Math.max(0, Math.round(p*(s.length-1))))]; }
function classifyStrays(){
  // Flag geometry that sits far outside the building cluster or spans absurd distances.
  // Threshold is tied to the building's own size (robust 5..95 percentile core), so only
  // km-scale / scene-spanning strays are caught — never real, tightly-clustered elements.
  outlierCount=0; if(allMeshes.length<10){ return 0; }
  const cx=[],cy=[],cz=[],dg=[];
  allMeshes.forEach(m=>{ m.geometry.computeBoundingBox(); const bb=m.geometry.boundingBox; const c=bb.getCenter(new THREE.Vector3()); const d=bb.getSize(new THREE.Vector3()).length(); m.userData._c=c; m.userData._d=d; cx.push(c.x);cy.push(c.y);cz.push(c.z);dg.push(d); });
  const coreMin=new THREE.Vector3(_pct(cx,0.05),_pct(cy,0.05),_pct(cz,0.05));
  const coreMax=new THREE.Vector3(_pct(cx,0.95),_pct(cy,0.95),_pct(cz,0.95));
  const coreSize=Math.max(coreMax.x-coreMin.x, coreMax.y-coreMin.y, coreMax.z-coreMin.z, 1);
  const pad=coreSize*3;             // generous margin around the building core
  const maxDiag=coreSize*3;         // an element bigger than 3x the whole building is a sliver
  allMeshes.forEach(m=>{ const c=m.userData._c;
    const out = c.x<coreMin.x-pad || c.x>coreMax.x+pad || c.y<coreMin.y-pad || c.y>coreMax.y+pad || c.z<coreMin.z-pad || c.z>coreMax.z+pad || m.userData._d>maxDiag;
    m.userData.outlier=out; if(out){ m.visible=false; outlierCount++; }
  });
  window._outlierCount=outlierCount;
  return outlierCount;
}
function setStrays(show){ showOutliers=!!show; allMeshes.forEach(m=>{ if(m.userData.outlier) m.visible=showOutliers; });
  const b=$("btnStray"); if(b){ b.textContent = "Strays: "+(showOutliers?"on":"off"); b.classList.toggle("on",showOutliers); } fit(); }
function fit(){
  if(!allMeshes.length) return;
  const box = bboxAll(); const c = box.getCenter(new THREE.Vector3()); const s = box.getSize(new THREE.Vector3());
  const r = Math.max(s.x,s.y,s.z) || 10;
  controls.target.copy(c);
  camera.up.set(0,1,0);
  // 3/4 view (Y-up). When Plan North is on, yaw the VIEWPOINT about the vertical Y axis
  // by the IFC north angle so the building reads square to the plan. View only.
  const off = new THREE.Vector3(r*1.2, r*1.1, r*1.4);
  if(planNorth && Math.abs(northAngle)>1e-4) off.applyAxisAngle(new THREE.Vector3(0,1,0), northAngle);
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
    row.onclick = () => { selection = catMap.get(t).slice(); renderSel(); showProps(null, t); emitSel(null, t); };
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
  if(ev.button===0 && secTryDrag(ev)) return;
  if(hit){ selection = [hit.object]; renderSel(); showProps(hit.object); emitSel(hit.object); window._lastDiag=elementDiag(hit.object); if($("dbgPanel")&&$("dbgPanel").classList.contains("open")) buildDebug(); }
  else { selection = []; renderSel(); showProps(null); emitSel(null); window._lastDiag=null; }
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
function showAll(){ allMeshes.forEach(m=>{ if(!m.userData.outlier || showOutliers) m.visible=true; }); }
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
// ================= Interactive Section (Three.js clipping plane) =================
// Render-only. Never modifies IFC geometry. Owns renderer.clippingPlanes while active;
// hands control back to the storey-plan `clip` when off.
const SEC={ on:false, axis:'z', sign:1, pos:0, lo:0, hi:1, group:null, quad:null, edge:null, arrow:null, dragging:false, _box:null, _plane:new THREE.Plane() };
function _axisVec(a){ return new THREE.Vector3(a==='x'?1:0, a==='y'?1:0, a==='z'?1:0); }
function secBuildVisual(){
  if(SEC.group) return;
  SEC.group=new THREE.Group();
  const g=new THREE.PlaneGeometry(1,1);
  SEC.quad=new THREE.Mesh(g, new THREE.MeshBasicMaterial({color:0x4d7cfe,transparent:true,opacity:0.14,side:THREE.DoubleSide,depthWrite:false}));
  SEC.quad.userData.sectionHandle=true;
  SEC.edge=new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({color:0x8ab4ff}));
  SEC.arrow=new THREE.ArrowHelper(new THREE.Vector3(0,0,1), new THREE.Vector3(0,0,0), 1, 0x31d0a5, 0.4, 0.25);
  SEC.group.add(SEC.quad); SEC.group.add(SEC.edge); SEC.group.add(SEC.arrow);
  SEC.group.visible=false; scene.add(SEC.group);
}
function secClamp(){ if(SEC.pos<SEC.lo)SEC.pos=SEC.lo; if(SEC.pos>SEC.hi)SEC.pos=SEC.hi; }
function secStart(axis){
  clip.plane=null;                 // stop any storey-plan cut
  const b=bboxAll(); SEC._box=b; SEC.on=true; if(axis) SEC.axis=axis;
  const a=SEC.axis;
  SEC.lo=a==='x'?b.min.x:a==='y'?b.min.y:b.min.z;
  SEC.hi=a==='x'?b.max.x:a==='y'?b.max.y:b.max.z;
  if(!(SEC.pos>SEC.lo && SEC.pos<SEC.hi)) SEC.pos=(SEC.lo+SEC.hi)/2;
  secBuildVisual(); secUpdate(); secSyncUI(); showSecPanel(true);
}
function secCenter(){ const c=(SEC._box||bboxAll()).getCenter(new THREE.Vector3()); if(SEC.axis==='x')c.x=SEC.pos; else if(SEC.axis==='y')c.y=SEC.pos; else c.z=SEC.pos; return c; }
function secUpdate(){
  if(!SEC.on){ renderer.clippingPlanes = clip.plane?[clip.plane]:[]; if(SEC.group)SEC.group.visible=false; return; }
  const n=_axisVec(SEC.axis).multiplyScalar(SEC.sign);
  SEC._plane.normal.copy(n); SEC._plane.constant=-SEC.sign*SEC.pos;
  renderer.clippingPlanes=[SEC._plane];
  secPlaceVisual();
}
function secPlaceVisual(){
  if(!SEC.group) return; SEC.group.visible=true;
  const b=SEC._box||bboxAll(), sz=b.getSize(new THREE.Vector3()), a=SEC.axis, m=Math.max(sz.x,sz.y,sz.z)||10;
  let w,h;
  if(a==='z'){ w=sz.x*1.06; h=sz.y*1.06; SEC.group.quaternion.set(0,0,0,1); }
  else if(a==='x'){ w=sz.y*1.06; h=sz.z*1.06; SEC.group.quaternion.setFromEuler(new THREE.Euler(0,Math.PI/2,0)); }
  else { w=sz.x*1.06; h=sz.z*1.06; SEC.group.quaternion.setFromEuler(new THREE.Euler(-Math.PI/2,0,0)); }
  SEC.quad.scale.set(w,h,1); SEC.edge.scale.set(w,h,1);
  SEC.group.position.copy(secCenter());
  const nrm=_axisVec(a).multiplyScalar(SEC.sign).normalize();
  SEC.arrow.setDirection(nrm); SEC.arrow.setLength(m*0.14, m*0.05, m*0.03); SEC.arrow.position.set(0,0,0);
}
function secPct(){ return SEC.hi>SEC.lo ? ((SEC.pos-SEC.lo)/(SEC.hi-SEC.lo))*100 : 50; }
function secSyncUI(){ const s=$("secSlide"); if(s) s.value=secPct(); const nu=$("secNum"); if(nu && document.activeElement!==nu) nu.value=SEC.pos.toFixed(3);
  document.querySelectorAll("[data-ax]").forEach(b=>b.classList.toggle("on", SEC.on && b.dataset.ax===SEC.axis));
  const bs=$("btnSection"); if(bs) bs.classList.toggle("on", SEC.on); }
function secSetPct(p){ SEC.pos=SEC.lo+(SEC.hi-SEC.lo)*(p/100); secClamp(); secUpdate(); secSyncUI(); }
function secSetNum(v){ const x=parseFloat(v); if(!isNaN(x)){ SEC.pos=x; secClamp(); secUpdate(); secSyncUI(); } }
function secReverse(){ SEC.sign*=-1; secUpdate(); }
function secReset(){ SEC.pos=(SEC.lo+SEC.hi)/2; SEC.sign=1; secUpdate(); secSyncUI(); }
function secOff(){ SEC.on=false; if(SEC.group)SEC.group.visible=false; renderer.clippingPlanes = clip.plane?[clip.plane]:[];
  document.querySelectorAll("[data-ax]").forEach(b=>b.classList.remove("on")); const bs=$("btnSection"); if(bs) bs.classList.remove("on"); showSecPanel(false); }
function showSecPanel(v){ const p=$("secPanel"); if(!p) return; p.classList.toggle("open", v===undefined?!p.classList.contains("open"):v); }
// drag the section plane along its axis (camera + geometry untouched)
function secTryDrag(ev){
  if(!SEC.on || !SEC.group || !SEC.group.visible) return false;
  const r=renderer.domElement.getBoundingClientRect();
  mouse.x=((ev.clientX-r.left)/r.width)*2-1; mouse.y=-((ev.clientY-r.top)/r.height)*2+1;
  ray.setFromCamera(mouse,camera);
  if(ray.intersectObject(SEC.quad,false).length){ SEC.dragging=true; controls.enabled=false; return true; }
  return false;
}
function secDragMove(ev){
  if(!SEC.dragging) return;
  const r=renderer.domElement.getBoundingClientRect();
  const ndc=new THREE.Vector2(((ev.clientX-r.left)/r.width)*2-1, -((ev.clientY-r.top)/r.height)*2+1);
  ray.setFromCamera(ndc,camera);
  const axisV=_axisVec(SEC.axis), viewDir=new THREE.Vector3(); camera.getWorldDirection(viewDir);
  let pn=new THREE.Vector3().crossVectors(axisV,viewDir).cross(axisV);
  if(pn.lengthSq()<1e-8) pn.copy(viewDir);
  pn.normalize();
  const dp=new THREE.Plane().setFromNormalAndCoplanarPoint(pn, secCenter()), hit=new THREE.Vector3();
  if(ray.ray.intersectPlane(dp,hit)){ SEC.pos = SEC.axis==='x'?hit.x:SEC.axis==='y'?hit.y:hit.z; secClamp(); secUpdate(); secSyncUI(); }
}
function secDragEnd(){ if(SEC.dragging){ SEC.dragging=false; controls.enabled=true; } }
renderer.domElement.addEventListener("pointermove", secDragMove);
window.addEventListener("pointerup", secDragEnd);

// ================= Camera navigation modes (camera only) =================
function setNavMode(m){
  if(!controls) return;
  controls.mouseButtons.LEFT = m==='pan'?THREE.MOUSE.PAN : m==='zoom'?THREE.MOUSE.DOLLY : THREE.MOUSE.ROTATE;
  [['btnOrbit','orbit'],['btnPan','pan'],['btnZoom','zoom']].forEach(([id,k])=>{const b=$(id); if(b) b.classList.toggle("on", k===m);});
}

// ================= Per-element coordinate diagnostic =================
function _nearStorey(z){ if(!storeys.length) return "—"; let best=storeys[0], d=1e18; storeys.forEach(s=>{ const dd=Math.abs(s.elev-z); if(dd<d){d=dd;best=s;} }); return best.name+" (elev "+best.elev.toFixed(2)+")"; }
function elementDiag(mesh){
  if(!mesh) return null;
  const {modelID, expressID, typeName}=mesh.userData;
  mesh.geometry.computeBoundingBox();
  const wc=mesh.geometry.boundingBox.getCenter(new THREE.Vector3());   // FINAL world center (baked)
  let orig=wc.clone();
  if(coordMatrix){ const M=new THREE.Matrix4().fromArray(Array.from(coordMatrix)); orig=wc.clone().applyMatrix4(new THREE.Matrix4().copy(M).invert()); }
  let gid="", place=null;
  try{ const line=ifcAPI.GetLine(modelID, expressID, true); gid=attr(line,"GlobalId")||"";
    const rp=line.ObjectPlacement && line.ObjectPlacement.RelativePlacement, loc=rp&&rp.Location&&rp.Location.Coordinates;
    place=loc?loc.map(x=>(x&&x.value!==undefined?x.value:x)):null;
  }catch(e){}
  return { modelID, expressID, typeName, gid, world:wc, orig, place };
}

function applyClip(){
  renderer.clippingPlanes = clip.plane ? [clip.plane] : [];
}
function setSection(axis){ secStart(axis); }
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
function clearSection(){ secOff(); clip.plane=null; renderer.clippingPlanes=[]; document.querySelectorAll("[data-ax]").forEach(b=>b.classList.remove("on")); }
document.querySelectorAll("[data-ax]").forEach(b=> b.onclick = ()=> setSection(b.dataset.ax));
$("secOff").onclick = clearSection;
$("secInvert").onclick = ()=> secReverse();
$("secSlide").oninput = (e)=> secSetPct(+e.target.value);
if($("secNum")) $("secNum").oninput = (e)=> secSetNum(e.target.value);
if($("btnSection")) $("btnSection").onclick = ()=>{ if(SEC.on) secOff(); else secStart(SEC.axis); };
if($("secReset")) $("secReset").onclick = ()=> secReset();
if($("secClose")) $("secClose").onclick = ()=> showSecPanel(false);
if($("btnOrbit")) $("btnOrbit").onclick = ()=> setNavMode("orbit");
if($("btnPan")) $("btnPan").onclick = ()=> setNavMode("pan");
if($("btnZoom")) $("btnZoom").onclick = ()=> setNavMode("zoom");

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
  SEC.on=false; if(SEC.group) SEC.group.visible=false; showSecPanel(false);
  const s = storeys[+v]; const box = bboxAll();
  const c = box.getCenter(new THREE.Vector3()); const sz = box.getSize(new THREE.Vector3());
  // Y-up world: vertical = Y. Map the storey's IFC elevation onto the model's world-Y
  // range (robust to units and to upper storeys without geometry). Cut horizontally along Y.
  const elevs = storeys.map(z=>z.elev); const emin=Math.min.apply(null,elevs), emax=Math.max.apply(null,elevs);
  const yW = (emax>emin) ? (box.min.y + (s.elev-emin)/(emax-emin)*(box.max.y-box.min.y)) : (box.min.y + sz.y*0.5);
  const cut = yW + Math.max(1.2, sz.y*0.06);
  clip.box = box; clip.axis="y"; clip.sign=-1;
  clip.plane = new THREE.Plane(new THREE.Vector3(0,-1,0), cut);
  applyClip();
  const r = Math.max(sz.x, sz.z);
  controls.target.set(c.x, yW, c.z);
  // Plan North: screen-up = Project North (rotate world north about the vertical Y axis).
  camera.up.copy(planNorth && Math.abs(northAngle)>1e-4
    ? new THREE.Vector3(0,0,-1).applyAxisAngle(new THREE.Vector3(0,1,0), northAngle)
    : new THREE.Vector3(0,0,-1));
  camera.position.set(c.x, yW + r*1.6, c.z);
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
  if(window._lastDiag){ const d=window._lastDiag;
    const sr=[["SELECTED — IFC class", d.typeName],["SELECTED — GUID", d.gid||"—"],
      ["SELECTED — nearest storey", _nearStorey(d.world.z)],
      ["SELECTED — local placement", f(d.place,1)],
      ["SELECTED — original IFC (x,y,z)", f([d.orig.x,d.orig.y,d.orig.z],1)],
      ["SELECTED — final world (x,y,z)", f([d.world.x,d.world.y,d.world.z],3)],
      ["— model —",""]];
    rows.unshift.apply(rows, sr);
  }
  rows.push(["Stray elements hidden", (window._outlierCount||0) + (showOutliers?" (shown)":"") ]);
  rows.push(["Storeys (name : elev)", storeys.map(s=>s.name+":"+s.elev.toFixed(2)).join("  |  ") || "—"]);
  if(models.length>1){ const pm=models.map(m=>{ const bb=new THREE.Box3(); m.meshes.forEach(me=>{me.geometry.computeBoundingBox(); bb.union(me.geometry.boundingBox);}); const s=bb.getSize(new THREE.Vector3()); return m.name.split("/").pop()+"  Z["+bb.min.z.toFixed(1)+".."+bb.max.z.toFixed(1)+"] size("+s.x.toFixed(1)+","+s.y.toFixed(1)+","+s.z.toFixed(1)+")"; });
    rows.push(["Per-model world bbox (multi)", pm.join("  ||  ")]); }
  try{ console.log("[Expo3D] IFC transform audit:", Object.fromEntries(rows.filter(r=>r[0]&&r[1]!==""))); }catch(e){}
  const body = $("dbgBody");
  if(body){ body.innerHTML = rows.map(([k,v])=>`<div class="drow"><span>${k}</span><b>${v}</b></div>`).join(""); }
}
if($("btnDebug")) $("btnDebug").onclick = ()=>{ const p=$("dbgPanel"); if(p){ const open=!p.classList.contains("open"); p.classList.toggle("open",open); if(open) buildDebug(); } };
if($("dbgClose")) $("dbgClose").onclick = ()=>{ const p=$("dbgPanel"); if(p) p.classList.remove("open"); };

// ---- Navigation gizmo (CAMERA ONLY — never rotates IFC geometry) ----
function setView(dir){
  if(!allMeshes.length) return;
  const box = bboxAll(); const c = box.getCenter(new THREE.Vector3()); const s = box.getSize(new THREE.Vector3());
  const r = Math.max(s.x,s.y,s.z) || 10; const d = r*1.9;
  controls.target.copy(c);
  const V = { top:[0,1,0], bottom:[0,-1,0], front:[0,0,1], back:[0,0,-1], right:[1,0,0], left:[-1,0,0] };
  const v = V[dir] || V.front;
  // Camera only (Y-up). Geometry, world transform and Plan/True-North are untouched.
  camera.up.set(0,1,0);
  if(dir==="top") camera.up.set(0,0,-1);
  else if(dir==="bottom") camera.up.set(0,0,1);
  camera.position.set(c.x + v[0]*d, c.y + v[1]*d, c.z + v[2]*d);
  camera.near = r/1000; camera.far = r*50; camera.updateProjectionMatrix();
  controls.update();
}
function injectGizmo(){
  if(document.getElementById("navGizmo")) return;
  const g = document.createElement("div"); g.id = "navGizmo";
  const faces = [["Top","top"],["Front","front"],["Right","right"],["Bottom","bottom"],["Back","back"],["Left","left"]];
  g.innerHTML = '<div class="gzt">CAMERA VIEW</div>' + faces.map(f=>`<button data-v="${f[1]}">${f[0]}</button>`).join("") + '<button class="gzfit" data-v="fit">Fit</button>';
  document.getElementById("view").appendChild(g);
  g.querySelectorAll("button").forEach(b => b.onclick = () => { const v=b.dataset.v; if(v==="fit") fit(); else setView(v); });
  const st = document.createElement("style");
  st.textContent = "#navGizmo{position:absolute;left:16px;top:16px;z-index:7;display:grid;grid-template-columns:repeat(3,1fr);gap:4px;background:rgba(19,27,38,.92);border:1px solid #213042;border-radius:10px;padding:8px;width:198px;box-shadow:0 8px 24px rgba(0,0,0,.42)}"
    + "#navGizmo .gzt{grid-column:1/4;font-size:9px;letter-spacing:1.4px;color:#8797ac;font-weight:700;margin-bottom:2px}"
    + "#navGizmo button{background:#1b2533;border:1px solid #213042;color:#eaf0f7;border-radius:6px;padding:7px 4px;font-size:11px;font-family:inherit;cursor:pointer}"
    + "#navGizmo button:hover{border-color:#4d7cfe;color:#bcd0ff}"
    + "#navGizmo .gzfit{grid-column:1/4;background:#4d7cfe;border-color:#4d7cfe;color:#fff;font-weight:600}";
  document.head.appendChild(st);
}

// ---- Workspace bridge: report selection + serve model context to the parent shell ----
function emitSel(mesh, catName){
  let payload;
  if(catName && !mesh){ payload = { kind:"category", name:catName, count:(catMap.get(catName)||[]).length }; }
  else if(mesh){
    const { modelID, expressID, typeName } = mesh.userData;
    let name="", gid="", objType="";
    try{ const line = ifcAPI.GetLine(modelID, expressID, true); name=attr(line,"Name")||""; gid=attr(line,"GlobalId")||""; objType=attr(line,"ObjectType")||""; }catch(e){}
    let text=""; try{ text = selectedElementContext(); }catch(e){}
    payload = { kind:"element", typeName, name, objType, gid, expressID, text };
  } else { payload = { kind:"none" }; }
  try{ parent.postMessage({ source:"expo-viewer", type:"selection", payload }, "*"); }catch(e){}
}
window.addEventListener("message", (ev)=>{
  const d = ev.data || {};
  if(d.type === "expo:getContext"){
    let context="", selText="";
    try{ context = buildModelContext(); }catch(e){}
    try{ selText = selectedElementContext(); }catch(e){}
    try{ (ev.source || parent).postMessage({ source:"expo-viewer", type:"context", context, selection:selText }, "*"); }catch(e){}
  } else if(d.type === "expo:setView"){ try{ setView(d.view); }catch(e){} }
  else if(d.type === "expo:cmd"){
    const c = d.cmd || "";
    try{
      if(c==="fit") fit();
      else if(c==="reset"){ const b=$("btnReset"); if(b) b.click(); }
      else if(c==="planN"){ if(typeof planNorth!=="undefined" && !planNorth){ planNorth=true; applyNorthBtn(); reapplyView(); } }
      else if(c==="trueN"){ if(typeof planNorth!=="undefined" && planNorth){ planNorth=false; applyNorthBtn(); reapplyView(); } }
      else if(c==="secX") setSection("x");
      else if(c==="secY") setSection("y");
      else if(c==="secZ") setSection("z");
      else if(c==="secOff") clearSection();
      else if(c==="hide"){ const b=$("btnHide"); if(b) b.click(); }
      else if(c==="iso"){ const b=$("btnIso"); if(b) b.click(); }
      else if(c==="showall") showAll();
      else if(c==="measure"){ const b=$("btnLen"); if(b) b.click(); }
      else if(c==="resize"){ resize(); }
      else if(c.indexOf("view:")===0) setView(c.slice(5));
    }catch(e){}
  }
});

// ---- boot ----
(async () => {
  try {
    await ifcAPI.Init();
    if(!rels.length){ setLoading(null); showErr("No model selected. Pick an IFC from the 3D Review tab."); return; }
    for(let i=0;i<rels.length;i++){ await loadModel(rels[i], i===0); }
    northAngle = detectNorthAngle();
    applyNorthBtn();
    renderModelList(); renderCatList(); loadStoreys();
    classifyStrays();
    buildDebug();
    resize(); fit(); injectGizmo(); setLoading(null);
    if($("btnStray")) $("btnStray").onclick = ()=> setStrays(!showOutliers);
    try{ parent.postMessage({ source:"expo-viewer", type:"ready", project }, "*"); }catch(e){}
  } catch(e){
    setLoading(null);
    showErr("<b>Viewer failed to start.</b><br>" + (e && e.message ? e.message : e) +
      "<br><br>If this is the first run, make sure you ran <b>setup_3d_viewer.bat</b> once (it downloads the 3D engine into ui\\vendor).");
    console.error(e);
  }
})();
