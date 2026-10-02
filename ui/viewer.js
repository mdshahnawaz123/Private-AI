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
let camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100000);  // `let` so the Ortho toggle can swap the active camera
camera.up.set(0,1,0);
const perspCamera = camera;   // keep a handle to the original perspective camera
const renderer = new THREE.WebGLRenderer({ antialias:true });
renderer.localClippingEnabled = true;
viewEl.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x30363f, 1.15));
scene.add(new THREE.AmbientLight(0xffffff, 0.35));
const dir = new THREE.DirectionalLight(0xfff6e8, 0.95); dir.position.set(1,1.4,2); scene.add(dir);
const dir2 = new THREE.DirectionalLight(0xdbe6ff, 0.35); dir2.position.set(-1,-0.6,-1); scene.add(dir2);
const grid = new THREE.GridHelper(200, 40, 0x2a3a50, 0x18222f); scene.add(grid); // Y-up: default GridHelper lies in the horizontal X-Z plane
const root = new THREE.Group(); scene.add(root); // holds all models; rotated for True/Project North

function resize(){ const w=viewEl.clientWidth, h=viewEl.clientHeight; renderer.setSize(w,h,false);
  if(camera.isOrthographicCamera){ const asp=w/h, halfH=(camera.top-camera.bottom)/2, halfW=halfH*asp; camera.left=-halfW; camera.right=halfW; }
  else { camera.aspect=w/h; }
  camera.updateProjectionMatrix(); }
window.addEventListener("resize", resize);
(function loop(){ requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); updateNavGizmo(); })();

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

// ---- Category appearance palette (fallback "realistic" styling) ----
// Real IFC material colours (IfcStyledItem/IfcSurfaceStyle, pulled from
// web-ifc's StreamAllMeshes) are still honoured when the source file
// actually defines them -- see styleFor() below.
const CATEGORY_STYLE = {
  WALL:         { color:0xd8d2c4, roughness:0.85, metalness:0.0  },
  WINDOW:       { color:0x6fa9d8, roughness:0.08, metalness:0.15, opacity:0.38 },
  DOOR:         { color:0x8a5a35, roughness:0.65, metalness:0.0  },
  SLAB:         { color:0x9b9a92, roughness:0.9,  metalness:0.0  },
  ROOF:         { color:0x53565d, roughness:0.75, metalness:0.05 },
  RAILING:      { color:0x383d46, roughness:0.35, metalness:0.65 },
  STAIRFLIGHT:  { color:0xb7b6ad, roughness:0.8,  metalness:0.0  },
  MEMBER:       { color:0x8d8d85, roughness:0.6,  metalness:0.2  },
  PLATE:        { color:0x7b808a, roughness:0.45, metalness:0.45 },
  FLOWTERMINAL: { color:0xb23b3b, roughness:0.4,  metalness:0.3  },
  BUILDINGELEMENTPROXY: { color:0xc9c2d6, roughness:0.75, metalness:0.0 },
  CURTAINWALL:  { color:0x6fa9d8, roughness:0.08, metalness:0.15, opacity:0.38 },
  DEFAULT:      { color:0xaba99f, roughness:0.8,  metalness:0.0  },
};
const REALISTIC_PALETTE = { on: true };  // toggled by the "Realistic" / "IFC colors" button
function styleFor(tName){
  const up = (tName||"").toUpperCase();
  for (const key in CATEGORY_STYLE){ if (up.indexOf(key) !== -1) return CATEGORY_STYLE[key]; }
  return CATEGORY_STYLE.DEFAULT;
}
// A source colour counts as "real" (keep it) only if it isn't the flat
// IFC default grey (~0.6,0.6,0.6, fully opaque) that untextured exports fall back to.
function looksLikeRealMaterial(c){
  const near06 = (v)=> Math.abs(v-0.6) < 0.03;
  if (c.w >= 0.999 && near06(c.x) && near06(c.y) && near06(c.z)) return false;
  return true;
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
      const rawCol = new THREE.Color(c.x, c.y, c.z), rawOpacity = c.w, rawIsReal = looksLikeRealMaterial(c);
      const st = styleFor(tName);
      const styledCol = new THREE.Color(st.color), styledOpacity = (st.opacity!==undefined ? st.opacity : 1);
      const useRealColor = !REALISTIC_PALETTE.on || rawIsReal;
      const baseCol = useRealColor ? rawCol : styledCol;
      const baseOpacity = useRealColor ? rawOpacity : styledOpacity;
      const rough = useRealColor ? 0.85 : st.roughness, metal = useRealColor ? 0.0 : st.metalness;
      const mat = new THREE.MeshStandardMaterial({ color: baseCol, roughness: rough, metalness: metal,
        side: THREE.DoubleSide, transparent: baseOpacity<0.999, opacity: baseOpacity });
      const mesh = new THREE.Mesh(bg, mat);
      mesh.userData = { modelID, expressID: eid, typeName: tName, origColor: baseCol.clone(), origOpacity: baseOpacity, origRough: rough, origMetal: metal,
        rawColor: rawCol, rawOpacity: rawOpacity, rawIsReal: rawIsReal, styledColor: styledCol, styledOpacity: styledOpacity, styledRough: st.roughness, styledMetal: st.metalness };
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
  // Categories are ALWAYS derived from the loaded model (catMap), never hard-coded.
  [...catMap.keys()].sort().forEach(t => {
    const meshes = catMap.get(t);
    const row = document.createElement("div"); row.className="catrow"; row.dataset.cat = t.toLowerCase();
    const eye = document.createElement("span"); eye.className="cvis"; eye.textContent = "◉"; eye.title = "Toggle visibility";
    const lbl = document.createElement("span"); lbl.textContent = t.replace(/^IFC/,""); lbl.style.flex = "1";
    const cnt = document.createElement("span"); cnt.className="tcount"; cnt.textContent = meshes.length;
    row.appendChild(eye); row.appendChild(lbl); row.appendChild(cnt);
    // Click label = select category (additive with Ctrl/Shift for multi-select).
    lbl.onclick = (ev) => {
      const add = ev.ctrlKey || ev.shiftKey || ev.metaKey;
      const set = add ? new Set(selection) : new Set();
      meshes.forEach(m=>set.add(m));
      selection = [...set];
      box.querySelectorAll(".catrow").forEach(r=>r.classList.remove("on"));
      if(!add) row.classList.add("on"); else row.classList.add("on");
      renderSel(); showProps(selection.length===1?selection[0]:null, selection.length===1?null:t); emitSel(null, t);
    };
    // Eye = toggle this category's visibility (does not touch selection).
    eye.onclick = (ev) => {
      ev.stopPropagation();
      const anyVisible = meshes.some(m=>m.visible);
      meshes.forEach(m=>{ if(!m.userData.outlier || showOutliers) m.visible = !anyVisible; });
      eye.style.opacity = anyVisible ? ".35" : ".8";
    };
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
  if(ev.button===0 && typeof SBX!=="undefined" && SBX.on && sbxTryDrag(ev)) return;  // section-box face drag preempts selection
  const hit = pick(ev);
  if(ev.button===0 && secTryDrag(ev)) return;
  if(hit){ selection = [hit.object]; renderSel(); showProps(hit.object); emitSel(hit.object); window._lastDiag=elementDiag(hit.object); if($("dbgPanel")&&$("dbgPanel").classList.contains("open")) buildDebug(); }
  else { selection = []; renderSel(); showProps(null); emitSel(null); window._lastDiag=null; }
});

function attr(line, k){ try{ return line[k] && (line[k].value!==undefined? line[k].value : line[k]); }catch(e){ return undefined; } }
function showProps(mesh, catName){
  const box = $("propBox");
  if(catName && !mesh){ const arr=catMap.get(catName); const n=arr?arr.length:selection.length; box.innerHTML = `<div class="prop"><b>Selected group</b>${_esc(catName)} — ${n} element(s)</div>`; return; }
  if(!mesh){ box.innerHTML = `<div class="hint">Click an element in the model to see its properties.</div>`; return; }
  const { modelID, expressID, typeName } = mesh.userData;
  let name="", gid="", objType="";
  try { const line = ifcAPI.GetLine(modelID, expressID, true); name = attr(line,"Name")||""; gid = attr(line,"GlobalId")||""; objType = attr(line,"ObjectType")||""; } catch(e){}
  // Dimensions from the element's world bounding box (what the geometry actually spans).
  let dimHtml = "";
  try {
    mesh.geometry.computeBoundingBox();
    const s = mesh.geometry.boundingBox.getSize(new THREE.Vector3());
    dimHtml = `<div class="sec" style="margin-top:12px">Geometry</div>` +
      `<div class="prop"><b>Size (x,y,z)</b>${s.x.toFixed(3)} × ${s.y.toFixed(3)} × ${s.z.toFixed(3)} m</div>`;
    const wc = mesh.geometry.boundingBox.getCenter(new THREE.Vector3());
    const st = _nearStorey(wc.y);
    if (st && st !== "—") dimHtml += `<div class="prop"><b>Nearest storey</b>${st}</div>`;
  } catch(e){}
  // Property sets + quantities (dynamic — only what the IFC actually carries).
  let psHtml = "";
  try {
    const pmap = buildPsetMap();
    const sets = pmap.get(modelID + ":" + expressID) || [];
    if (sets.length){
      psHtml = `<div class="sec" style="margin-top:12px">Property sets &amp; quantities</div>`;
      sets.forEach(ps=>{
        if(!ps.props.length) return;
        psHtml += `<div class="prop" style="margin-bottom:4px"><b>${_esc(ps.name||"(unnamed)")}</b></div>`;
        ps.props.forEach(p=>{ psHtml += `<div class="pr" style="display:flex;justify-content:space-between;gap:10px;font-size:11.5px;padding:2px 0;color:var(--text)"><span style="color:var(--muted)">${_esc(p.k)}</span><span style="text-align:right">${_esc(p.v!==undefined&&p.v!==null?p.v:"")}</span></div>`; });
      });
    }
  } catch(e){}
  box.innerHTML =
    `<div class="sec">Identity</div>` +
    `<div class="prop"><b>IFC class</b>${_esc(typeName)}</div>` +
    (name?`<div class="prop"><b>Name</b>${_esc(name)}</div>`:"") +
    (objType?`<div class="prop"><b>Object type</b>${_esc(objType)}</div>`:"") +
    (gid?`<div class="prop"><b>Global ID</b>${_esc(gid)}</div>`:"") +
    `<div class="prop"><b>Express ID</b>${expressID}</div>` +
    dimHtml + psHtml;
}
function _esc(s){ return (s==null?"":String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

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

// ---- Realistic-palette toggle: styled type colors vs. the model's own raw IFC colors ----
function applyRealisticToggle(){
  allMeshes.forEach(m=>{
    const ud = m.userData;
    const useReal = !REALISTIC_PALETTE.on || ud.rawIsReal;
    ud.origColor = (useReal ? ud.rawColor : ud.styledColor).clone();
    ud.origOpacity = useReal ? ud.rawOpacity : ud.styledOpacity;
    ud.origRough = useReal ? 0.85 : ud.styledRough;
    ud.origMetal = useReal ? 0.0 : ud.styledMetal;
    if (m.material.roughness!==undefined) m.material.roughness = ud.origRough;
    if (m.material.metalness!==undefined) m.material.metalness = ud.origMetal;
  });
  setDisplayMode(displayMode);  // reapplies origColor/origOpacity under the current display mode (shaded/wire/trans/xray)
}
if($("btnRealistic")) $("btnRealistic").onclick = () => {
  REALISTIC_PALETTE.on = !REALISTIC_PALETTE.on;
  $("btnRealistic").classList.toggle("on", REALISTIC_PALETTE.on);
  $("btnRealistic").textContent = REALISTIC_PALETTE.on ? "Realistic" : "IFC colors";
  applyRealisticToggle();
};

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
  if(typeof sbxOff==="function" && SBX && SBX.on) sbxOff();   // box and plane are mutually exclusive
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
function showSecPanel(v){ stShow(v, "plane"); }
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
function clearSection(){ secOff(); if(typeof sbxOff==="function") sbxOff(); clip.plane=null; renderer.clippingPlanes=[];
  if(typeof setDisplayMode==="function" && displayMode!=="shaded") setDisplayMode("shaded");
  document.querySelectorAll("[data-ax]").forEach(b=>b.classList.remove("on")); }
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
  if(typeof sbxOff==="function" && SBX && SBX.on) sbxOff();
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
  try{
    if(typeof SBX!=="undefined" && SBX.on && SBX.box){ const b=SBX.box;
      L.push(""); L.push("ACTIVE SECTION BOX (view clip, " + (SBX.outside?"keeping OUTSIDE":"keeping INSIDE") + "): "
        + "X[" + b.min.x.toFixed(2) + ".." + b.max.x.toFixed(2) + "] "
        + "Y[" + b.min.y.toFixed(2) + ".." + b.max.y.toFixed(2) + "] "
        + "Z[" + b.min.z.toFixed(2) + ".." + b.max.z.toFixed(2) + "]");
    } else if(SEC.on){ L.push(""); L.push("ACTIVE SECTION PLANE: axis " + SEC.axis.toUpperCase() + " at " + SEC.pos.toFixed(2) + " (view clip)"); }
    if(typeof displayMode!=="undefined" && displayMode!=="shaded") L.push("DISPLAY MODE: " + displayMode);
  }catch(e){}
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
  if(document.getElementById("navDock")) return;
  const dock = document.createElement("div"); dock.id = "navDock";
  dock.innerHTML =
    '<button id="navHome" title="Fit the whole model">&#8962;</button>' +
    '<div id="navCubeWrap">' +
      '<div id="navCompass">' +
        '<span style="left:50%;top:1px;transform:translateX(-50%)">N</span>' +
        '<span style="left:50%;bottom:1px;transform:translateX(-50%)">S</span>' +
        '<span style="right:1px;top:50%;transform:translateY(-50%)">E</span>' +
        '<span style="left:1px;top:50%;transform:translateY(-50%)">W</span>' +
      '</div>' +
      '<div id="navScene"><div id="navCube">' +
        '<div class="face f-front" data-v="front">FRONT</div>' +
        '<div class="face f-back" data-v="back">BACK</div>' +
        '<div class="face f-right" data-v="right">RIGHT</div>' +
        '<div class="face f-left" data-v="left">LEFT</div>' +
        '<div class="face f-top" data-v="top">TOP</div>' +
        '<div class="face f-bottom" data-v="bottom">BOTTOM</div>' +
      '</div></div>' +
    '</div>';
  document.getElementById("view").appendChild(dock);
  dock.querySelectorAll(".face").forEach(f => f.onclick = (ev)=>{ ev.stopPropagation(); setView(f.dataset.v); });
  const home = dock.querySelector("#navHome"); if(home) home.onclick = ()=> fit();
}
// Rotates the CSS 3D cube + compass ring to mirror the camera's current
// orientation each frame (view-only -- the IFC geometry/world frame never moves).
function updateNavGizmo(){
  const cube = document.getElementById("navCube"); if(!cube) return;
  const dir = new THREE.Vector3(); camera.getWorldDirection(dir);
  const yaw = Math.atan2(dir.x, dir.z) * 180/Math.PI;
  const pitch = Math.asin(Math.max(-1,Math.min(1,dir.y))) * 180/Math.PI;
  cube.style.transform = "rotateX(" + pitch + "deg) rotateY(" + (-yaw) + "deg)";
  const compass = document.getElementById("navCompass");
  if(compass) compass.style.transform = "rotate(" + yaw + "deg)";
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
      else if(c==="secBox"){ if(SBX.on) sbxOff(); else sbxStart(); }
      else if(c==="secBoxOff"){ sbxOff(); }
      else if(c==="resize"){ resize(); }
      else if(c.indexOf("display:")===0) setDisplayMode(c.slice(8));
      else if(c.indexOf("proj:")===0) setProjection(c.slice(5));
      else if(c.indexOf("view:")===0) setView(c.slice(5));
    }catch(e){}
  }
});

// ============================================================
// UPGRADE MODULE (additive) — section box, display modes, ortho,
// spatial tree, left search + resizer. All view-only; never edits
// IFC geometry; preserves the existing plane-section + storey logic.
// ============================================================

// ---- ACC-style interactive SECTION BOX (6 clipping planes) ----
const SBX = { on:false, box:null, full:null, planes:[], helper:null, faces:[], group:null, dragging:null, outside:false };
function applyClipRestore(){
  allMeshes.forEach(m=>{ if(m.material) m.material.clipIntersection=false; });
  renderer.clippingPlanes = SEC.on ? [SEC._plane] : (clip.plane ? [clip.plane] : []);
}
function sbxBuildVisual(){
  if(SBX.group) return;
  SBX.group = new THREE.Group(); scene.add(SBX.group);
  SBX.helper = new THREE.Box3Helper(SBX.box, new THREE.Color(0x4d7cfe));
  try{ SBX.helper.material.depthTest=false; }catch(e){}
  SBX.group.add(SBX.helper);
  const mk=(axis,side)=>{ const q=new THREE.Mesh(new THREE.PlaneGeometry(1,1),
      new THREE.MeshBasicMaterial({color:0x4d7cfe,transparent:true,opacity:0.10,side:THREE.DoubleSide,depthWrite:false,depthTest:false}));
    q.userData.sbxFace={axis,side}; q.renderOrder=999; SBX.faces.push(q); SBX.group.add(q); };
  ["x","y","z"].forEach(a=>{ mk(a,"min"); mk(a,"max"); });
}
function sbxPlaceVisual(){
  if(!SBX.group) return; SBX.group.visible=true;
  const b=SBX.box, c=b.getCenter(new THREE.Vector3()), s=b.getSize(new THREE.Vector3());
  SBX.faces.forEach(q=>{ const {axis,side}=q.userData.sbxFace; const pos=c.clone(); let w,h,euler;
    if(axis==="x"){ pos.x=side==="min"?b.min.x:b.max.x; w=s.y; h=s.z; euler=new THREE.Euler(0,Math.PI/2,0); }
    else if(axis==="y"){ pos.y=side==="min"?b.min.y:b.max.y; w=s.x; h=s.z; euler=new THREE.Euler(-Math.PI/2,0,0); }
    else { pos.z=side==="min"?b.min.z:b.max.z; w=s.x; h=s.y; euler=new THREE.Euler(0,0,0); }
    q.position.copy(pos); q.scale.set(Math.max(w,0.01),Math.max(h,0.01),1); q.setRotationFromEuler(euler);
  });
}
function sbxApply(){
  if(!SBX.on){ applyClipRestore(); if(SBX.group)SBX.group.visible=false; return; }
  const b=SBX.box, P=SBX.planes;
  P[0].set(new THREE.Vector3(-1,0,0),  b.max.x);  // keep x <= max
  P[1].set(new THREE.Vector3( 1,0,0), -b.min.x);  // keep x >= min
  P[2].set(new THREE.Vector3(0,-1,0),  b.max.y);
  P[3].set(new THREE.Vector3(0, 1,0), -b.min.y);
  P[4].set(new THREE.Vector3(0,0,-1),  b.max.z);
  P[5].set(new THREE.Vector3(0,0, 1), -b.min.z);
  if(SBX.outside){ P.forEach(p=>{ p.normal.multiplyScalar(-1); p.constant*=-1; });
    allMeshes.forEach(m=>{ if(m.material) m.material.clipIntersection=true; }); }
  else { allMeshes.forEach(m=>{ if(m.material) m.material.clipIntersection=false; }); }
  renderer.clippingPlanes = P.slice();
  sbxPlaceVisual();
}
function sbxStart(){
  secOff();                         // turn single-plane section off first (no conflict)
  const f=bboxAll(); SBX.full=f.clone(); SBX.box=f.clone(); SBX.outside=false;
  if(!SBX.planes.length){ for(let i=0;i<6;i++) SBX.planes.push(new THREE.Plane()); }
  SBX.on=true; sbxBuildVisual(); SBX.helper.box=SBX.box; sbxApply(); sbxSyncSliders(); showBoxPanel(true); sbxSyncBtn();
}
function sbxOff(){ SBX.on=false; if(SBX.group)SBX.group.visible=false; applyClipRestore(); showBoxPanel(false); sbxSyncBtn(); }
function sbxReset(){ if(!SBX.full)return; SBX.box.copy(SBX.full); SBX.outside=false; sbxApply(); sbxSyncSliders(); }
function sbxReverse(){ SBX.outside=!SBX.outside; sbxApply(); }
function sbxSyncBtn(){ const b=$("btnSecBox"); if(b) b.classList.toggle("on", SBX.on); }
function showBoxPanel(v){ stShow(v, "box"); }
function sbxPct(axis,side){ const f=SBX.full,b=SBX.box; const lo=f.min[axis],hi=f.max[axis]; return hi>lo?((b[side][axis]-lo)/(hi-lo))*100:(side==="min"?0:100); }
function sbxSyncSliders(){ if(!SBX.full)return; const set=(id,val)=>{const e=$(id); if(e&&document.activeElement!==e)e.value=val;};
  set("bxXmin",sbxPct("x","min")); set("bxXmax",sbxPct("x","max"));
  set("bxYmin",sbxPct("y","min")); set("bxYmax",sbxPct("y","max"));
  set("bxZmin",sbxPct("z","min")); set("bxZmax",sbxPct("z","max")); }
function sbxSetSlider(axis,side,pct){ if(!SBX.full)return; const f=SBX.full,lo=f.min[axis],hi=f.max[axis];
  const EPS=(hi-lo)*0.02||0.01; let v=lo+(hi-lo)*(pct/100);
  if(side==="min") SBX.box.min[axis]=Math.min(v, SBX.box.max[axis]-EPS);
  else SBX.box.max[axis]=Math.max(v, SBX.box.min[axis]+EPS);
  sbxApply(); }
function sbxTryDrag(ev){ if(!SBX.on||!SBX.group) return false;
  const r=renderer.domElement.getBoundingClientRect();
  mouse.x=((ev.clientX-r.left)/r.width)*2-1; mouse.y=-((ev.clientY-r.top)/r.height)*2+1;
  ray.setFromCamera(mouse,camera);
  const hit=ray.intersectObjects(SBX.faces,false);
  if(hit.length){ SBX.dragging=hit[0].object.userData.sbxFace; controls.enabled=false; return true; }
  return false; }
function sbxDragMove(ev){ if(!SBX.dragging) return;
  const {axis,side}=SBX.dragging;
  const r=renderer.domElement.getBoundingClientRect();
  const ndc=new THREE.Vector2(((ev.clientX-r.left)/r.width)*2-1, -((ev.clientY-r.top)/r.height)*2+1);
  ray.setFromCamera(ndc,camera);
  const axisV=_axisVec(axis), viewDir=new THREE.Vector3(); camera.getWorldDirection(viewDir);
  let pn=new THREE.Vector3().crossVectors(axisV,viewDir).cross(axisV); if(pn.lengthSq()<1e-8)pn.copy(viewDir); pn.normalize();
  const dp=new THREE.Plane().setFromNormalAndCoplanarPoint(pn, SBX.box.getCenter(new THREE.Vector3())), hit=new THREE.Vector3();
  if(ray.ray.intersectPlane(dp,hit)){ const f=SBX.full, EPS=(f.max[axis]-f.min[axis])*0.02||0.01;
    let v=Math.max(f.min[axis], Math.min(f.max[axis], hit[axis]));
    if(side==="min") SBX.box.min[axis]=Math.min(v, SBX.box.max[axis]-EPS);
    else SBX.box.max[axis]=Math.max(v, SBX.box.min[axis]+EPS);
    sbxApply(); sbxSyncSliders(); } }
function sbxDragEnd(){ if(SBX.dragging){ SBX.dragging=null; controls.enabled=true; } }
// face-drag start is handled inside the existing pointerdown handler (deterministic);
// here we only need move + end listeners (they no-op unless a face drag is active).
renderer.domElement.addEventListener("pointermove", sbxDragMove);
window.addEventListener("pointerup", sbxDragEnd);
if($("btnSecBox")) $("btnSecBox").onclick = ()=>{ if(SBX.on) sbxOff(); else sbxStart(); };
if($("secBoxClose")) $("secBoxClose").onclick = ()=> showBoxPanel(false);
if($("bxReset")) $("bxReset").onclick = sbxReset;
if($("bxOff")) $("bxOff").onclick = sbxOff;
if($("bxReverse")) $("bxReverse").onclick = sbxReverse;
[["bxXmin","x","min"],["bxXmax","x","max"],["bxYmin","y","min"],["bxYmax","y","max"],["bxZmin","z","min"],["bxZmax","z","max"]]
  .forEach(([id,a,s])=>{ const e=$(id); if(e) e.oninput=()=> sbxSetSlider(a,s,+e.value); });

// ---- Display modes (material-level, reversible) ----
let displayMode="shaded";
function setDisplayMode(mode){
  displayMode=mode;
  allMeshes.forEach(m=>{ const md=m.material; if(!md) return;
    md.wireframe=false; md.color.copy(m.userData.origColor); md.opacity=m.userData.origOpacity; md.transparent=m.userData.origOpacity<0.999; md.depthWrite=true;
    if(mode==="wire"){ md.wireframe=true; }
    else if(mode==="trans"){ md.transparent=true; md.opacity=0.35; }
    else if(mode==="xray"){ md.transparent=true; md.opacity=0.12; md.depthWrite=false; }
    md.needsUpdate=true;
  });
  [["dmShaded","shaded"],["dmWire","wire"],["dmTrans","trans"],["dmXray","xray"]].forEach(([id,k])=>{ const b=$(id); if(b) b.classList.toggle("on", k===mode); });
}

// ---- Perspective / Orthographic toggle (camera only) ----
let projMode="persp";
function setProjection(kind){
  if(kind===projMode) return;
  const w=viewEl.clientWidth||1, h=viewEl.clientHeight||1, asp=w/h;
  const pos=camera.position.clone(), tgt=controls.target.clone(), up=camera.up.clone();
  const box=bboxAll(), r=Math.max(...box.getSize(new THREE.Vector3()).toArray())||10;
  if(kind==="ortho"){
    const dist=pos.distanceTo(tgt)||r*2, halfH=dist*0.6, halfW=halfH*asp;
    const oc=new THREE.OrthographicCamera(-halfW,halfW,halfH,-halfH, r/1000, r*50);
    oc.position.copy(pos); oc.up.copy(up); oc.lookAt(tgt); camera=oc;
  } else {
    perspCamera.position.copy(pos); perspCamera.up.copy(up); perspCamera.aspect=asp;
    perspCamera.near=r/1000; perspCamera.far=r*50; perspCamera.lookAt(tgt); perspCamera.updateProjectionMatrix(); camera=perspCamera;
  }
  projMode=kind; controls.object=camera; controls.target.copy(tgt); camera.updateProjectionMatrix(); controls.update();
  const bp=$("btnPersp"), bo=$("btnOrtho"); if(bp)bp.classList.toggle("on",kind==="persp"); if(bo)bo.classList.toggle("on",kind==="ortho");
}
if($("btnPersp")) $("btnPersp").onclick=()=> setProjection("persp");
if($("btnOrtho")) $("btnOrtho").onclick=()=> setProjection("ortho");
[["dmShaded","shaded"],["dmWire","wire"],["dmTrans","trans"],["dmXray","xray"]].forEach(([id,k])=>{ const b=$(id); if(b) b.onclick=()=> setDisplayMode(k); });

// ---- Left panel: search filter + resizable splitter ----
function filterTree(){ const q=(($("treeSearch")||{}).value||"").toLowerCase().trim();
  document.querySelectorAll("#catList .catrow, #spatialTree .trow").forEach(r=>{ r.style.display=(!q||(r.dataset.cat||"").includes(q)||r.textContent.toLowerCase().includes(q))?"":"none"; });
  document.querySelectorAll("#modelList .mrow").forEach(r=>{ r.style.display=(!q||r.textContent.toLowerCase().includes(q))?"":"none"; }); }
if($("treeSearch")) $("treeSearch").oninput=filterTree;
(function wireResizer(){ const h=$("leftResizer"); if(!h) return; let drag=false;
  h.addEventListener("pointerdown",e=>{ drag=true; h.classList.add("drag"); try{h.setPointerCapture(e.pointerId);}catch(_){} });
  window.addEventListener("pointermove",e=>{ if(!drag)return; const w=Math.min(460,Math.max(170,e.clientX)); document.documentElement.style.setProperty("--leftw",w+"px"); resize(); });
  window.addEventListener("pointerup",()=>{ if(drag){ drag=false; h.classList.remove("drag"); resize(); } });
})();

// ---- Spatial tree (Project / Site / Building / Storey) — dynamic ----
function buildSpatialTree(){
  const host=$("spatialTree"); if(!host) return; host.innerHTML="";
  const idx=new Map(); allMeshes.forEach(m=>{ const k=m.userData.modelID+":"+m.userData.expressID; if(!idx.has(k))idx.set(k,[]); idx.get(k).push(m); });
  const nodes=[];
  models.forEach(m=>{
    const byStorey=new Map();
    try{ const rels=ifcAPI.GetLineIDsWithType(m.modelID, WebIFC.IFCRELCONTAINEDINSPATIALSTRUCTURE);
      for(let i=0;i<rels.size();i++){ let rel; try{rel=ifcAPI.GetLine(m.modelID,rels.get(i),true);}catch(e){continue;}
        const st=rel.RelatingStructure, stEid=st&&(st.value!==undefined?st.value:st.expressID);
        const arr=byStorey.get(stEid)||[]; const els=rel.RelatedElements||[];
        (Array.isArray(els)?els:[]).forEach(o=>{ const eid=o&&(o.value!==undefined?o.value:o.expressID); if(eid!=null)(idx.get(m.modelID+":"+eid)||[]).forEach(me=>arr.push(me)); });
        byStorey.set(stEid,arr); }
    }catch(e){}
    [["IfcProject",WebIFC.IFCPROJECT],["IfcSite",WebIFC.IFCSITE],["IfcBuilding",WebIFC.IFCBUILDING],["IfcBuildingStorey",WebIFC.IFCBUILDINGSTOREY]].forEach(([tn,code],depth)=>{
      let ids; try{ids=ifcAPI.GetLineIDsWithType(m.modelID,code);}catch(e){return;}
      for(let i=0;i<ids.size();i++){ const eid=ids.get(i); let line; try{line=ifcAPI.GetLine(m.modelID,eid);}catch(e){continue;}
        const nm=(line.LongName&&line.LongName.value)||(line.Name&&line.Name.value)||tn;
        nodes.push({label:nm, type:tn, depth, meshes: byStorey.get(eid)||null}); }
    });
  });
  if(!nodes.length){ host.innerHTML='<div class="hint">No spatial hierarchy found in this model.</div>'; return; }
  nodes.forEach(n=>{ const row=document.createElement("div"); row.className="trow"; row.dataset.cat=n.label.toLowerCase();
    row.style.paddingLeft=(6+n.depth*12)+"px";
    const lbl=document.createElement("span"); lbl.textContent=n.label; lbl.style.flex="1"; lbl.title=n.type; row.appendChild(lbl);
    if(n.meshes&&n.meshes.length){ const c=document.createElement("span"); c.className="tcount"; c.textContent=n.meshes.length; row.appendChild(c);
      row.onclick=()=>{ selection=n.meshes.slice(); renderSel(); showProps(null,n.label); emitSel(null,n.label);
        host.querySelectorAll(".trow").forEach(r=>r.classList.remove("on")); row.classList.add("on"); }; }
    host.appendChild(row); });
}

// ---- Unified Sectioning Tools panel (Plane / Box tabs) ----
function stRenderPlaneList(){
  const host = $("stPlaneList"); if(!host) return;
  if(SEC.on){
    host.innerHTML = '<div class="stRow"><span class="stRowIco"></span><span class="stRowLbl">Plane \u00b7 ' + SEC.axis.toUpperCase() + ' axis</span><button class="stDel" title="Remove">\u00d7</button></div>';
    const del = host.querySelector(".stDel"); if(del) del.onclick = ()=>{ const b=$("secOff"); if(b) b.click(); };
  } else { host.innerHTML = '<div class="stEmpty">Nothing to display. Add a plane.</div>'; }
}
function stRenderBoxList(){
  const host = $("stBoxList"); if(!host) return;
  if(SBX.on){
    host.innerHTML = '<div class="stRow"><span class="stRowIco"></span><span class="stRowLbl">Section box</span><button class="stDel" title="Remove">\u00d7</button></div>';
    const del = host.querySelector(".stDel"); if(del) del.onclick = ()=>{ const b=$("bxOff"); if(b) b.click(); };
  } else { host.innerHTML = '<div class="stEmpty">Nothing to display. Add a box.</div>'; }
}
function stSetTab(tab){
  const isPlane = tab==="plane";
  const tp=$("stTabPlane"), tb=$("stTabBox"), pp=$("stPanePlane"), pb=$("stPaneBox");
  if(tp) tp.classList.toggle("on", isPlane);
  if(tb) tb.classList.toggle("on", !isPlane);
  if(pp) pp.classList.toggle("on", isPlane);
  if(pb) pb.classList.toggle("on", !isPlane);
}
function stShow(v, tab){
  const p = $("secToolsPanel"); if(!p) return;
  const open = v===undefined ? !p.classList.contains("open") : v;
  p.classList.toggle("open", open);
  if(open){ p.classList.remove("min"); if(tab) stSetTab(tab); }
  stRenderPlaneList(); stRenderBoxList();
}
if($("stTabPlane")) $("stTabPlane").onclick = ()=> stSetTab("plane");
if($("stTabBox")) $("stTabBox").onclick = ()=> stSetTab("box");
if($("stClose")) $("stClose").onclick = ()=> stShow(false);
if($("stMin")) $("stMin").onclick = ()=>{ const p=$("secToolsPanel"); if(p) p.classList.toggle("min"); };
if($("stPlaneAdvToggle")) $("stPlaneAdvToggle").onclick = ()=>{ const e=$("stPlaneAdv"); if(!e) return; const open=e.style.display==="none"; e.style.display=open?"flex":"none"; $("stPlaneAdvToggle").innerHTML = "Fine controls " + (open?"&#9652;":"&#9662;"); };
if($("stBoxAdvToggle")) $("stBoxAdvToggle").onclick = ()=>{ const e=$("stBoxAdv"); if(!e) return; const open=e.style.display==="none"; e.style.display=open?"flex":"none"; $("stBoxAdvToggle").innerHTML = "Fine controls " + (open?"&#9652;":"&#9662;"); };
if($("secAddBtn")) $("secAddBtn").onclick = ()=>{ if(!SEC.on) secStart(SEC.axis); stRenderPlaneList(); };
if($("bxAddBtn")) $("bxAddBtn").onclick = ()=>{ if(!SBX.on) sbxStart(); stRenderBoxList(); };
if($("secShowFrame")) $("secShowFrame").onchange = (e)=>{ if(SEC.quad) SEC.quad.visible = e.target.checked; if(SEC.edge) SEC.edge.visible = e.target.checked; };
if($("secShowGizmo")) $("secShowGizmo").onchange = (e)=>{ if(SEC.arrow) SEC.arrow.visible = e.target.checked; };
if($("bxShowFrame")) $("bxShowFrame").onchange = (e)=>{ if(SBX.helper) SBX.helper.visible = e.target.checked; };
if($("bxShowGizmo")) $("bxShowGizmo").onchange = (e)=>{ (SBX.faces||[]).forEach(f=> f.visible = e.target.checked); };

// ---- Measurement dock (floating bottom-center pill) ----
if($("btnMeasureTool")) $("btnMeasureTool").onclick = ()=>{
  const d=$("measureDock"); if(!d) return; const open=!d.classList.contains("open");
  d.classList.toggle("open", open); $("btnMeasureTool").classList.toggle("on", open);
};
if($("btnMeasureDone")) $("btnMeasureDone").onclick = ()=>{
  measureMode = null; toggleMeasureBtns();
  const d=$("measureDock"); if(d) d.classList.remove("open");
  const t=$("btnMeasureTool"); if(t) t.classList.remove("on");
};

// ---- boot ----
(async () => {
  try {
    await ifcAPI.Init();
    if(!rels.length){ setLoading(null); showErr("No model selected. Pick an IFC from the 3D Review tab."); return; }
    for(let i=0;i<rels.length;i++){ await loadModel(rels[i], i===0); }
    northAngle = detectNorthAngle();
    applyNorthBtn();
    renderModelList(); renderCatList(); loadStoreys();
    try{ buildSpatialTree(); }catch(e){ console.warn("spatial tree:", e); }
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
