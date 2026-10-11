
// ================= Sectioning Tools (ported from ui/viewer.js) =================
// Adapted for the Fragments engine: no flat `allMeshes` array exists here, so
// mesh-material loops traverse `activeModel.object` instead, and bbox centering
// reuses the already-computed `modelBox` (a THREE.Box3) rather than a custom
// bboxAll() union.

function secAllMeshes(cb){
  if(activeModel && activeModel.object){
    activeModel.object.traverse(c=>{ if(c.isMesh && c.material){ cb(c); } });
  }
}

function secModelCenter(){
  if(modelBox) return modelBox.getCenter(new THREE.Vector3());
  return new THREE.Vector3(0,0,0);
}
function secModelRadius(){
  if(modelBox){ const s = modelBox.getSize(new THREE.Vector3()); return Math.max(s.x,s.y,s.z)/2 || 10; }
  return 10;
}

const clip = { plane:null };

function applyClippingPlanes(){
  const planes = [];
  if(SEC.on && SEC._plane) planes.push(SEC._plane);
  if(SBX.on && SBX.planes) planes.push(...SBX.planes);
  renderer.clippingPlanes = planes;
}

// ---------------- SEC: free-orientation Section Plane ----------------
const SEC = {
  on:false, editing:false, placing:false,
  group:null, quad:null, edge:null, arrow:null,
  gizmoMode:"translate", // 'translate' | 'rotate'
  freeNormal:null, freePoint:null,
  _plane:null,
  drag:null
};

function secBuildVisual(){
  secClearVisual();
  const size = secModelRadius()*1.6 || 20;
  const quadGeo = new THREE.PlaneGeometry(size, size);
  const quadMat = new THREE.MeshBasicMaterial({ color:0x4aa3ff, transparent:true, opacity:0.12, side:THREE.DoubleSide, depthWrite:false });
  SEC.quad = new THREE.Mesh(quadGeo, quadMat);
  const edgeGeo = new THREE.EdgesGeometry(quadGeo);
  SEC.edge = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color:0x4aa3ff }));
  SEC.group = new THREE.Group();
  SEC.group.add(SEC.quad);
  SEC.group.add(SEC.edge);
  scene.add(SEC.group);
  secBuildGizmo();
  secSetGizmoVisible(false);
}

function secClearVisual(){
  if(SEC.group){ scene.remove(SEC.group); SEC.group=null; SEC.quad=null; SEC.edge=null; }
  if(SEC.arrow){ scene.remove(SEC.arrow); SEC.arrow=null; }
}

function secMakeArrow(axis, color){
  const len = secModelRadius()*0.35 || 6;
  const g = new THREE.Group();
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(len*0.02, len*0.02, len*0.82, 8), new THREE.MeshBasicMaterial({color, depthTest:false}));
  shaft.position.y = len*0.41;
  const head = new THREE.Mesh(new THREE.ConeGeometry(len*0.06, len*0.18, 10), new THREE.MeshBasicMaterial({color, depthTest:false}));
  head.position.y = len*0.82+len*0.09;
  const pickShaft = new THREE.Mesh(new THREE.CylinderGeometry(len*0.09, len*0.09, len, 8), new THREE.MeshBasicMaterial({visible:false}));
  pickShaft.position.y = len*0.5;
  pickShaft.userData.secAxis = axis; pickShaft.userData.secHandle = "translate";
  g.add(shaft); g.add(head); g.add(pickShaft);
  g.renderOrder = 999;
  if(axis==="x") g.rotation.z = -Math.PI/2;
  if(axis==="z") g.rotation.x = Math.PI/2;
  g.userData.secAxis = axis;
  return g;
}

function secMakeRing(axis, color){
  const r = secModelRadius()*0.5 || 8;
  const torus = new THREE.Mesh(new THREE.TorusGeometry(r, r*0.015, 8, 48), new THREE.MeshBasicMaterial({color, depthTest:false}));
  const pick = new THREE.Mesh(new THREE.TorusGeometry(r, r*0.06, 8, 48), new THREE.MeshBasicMaterial({visible:false}));
  pick.userData.secAxis = axis; pick.userData.secHandle = "rotate";
  const g = new THREE.Group(); g.add(torus); g.add(pick);
  if(axis==="x") g.rotation.y = Math.PI/2;
  if(axis==="y") g.rotation.x = Math.PI/2;
  g.userData.secAxis = axis; g.userData.secRing = true;
  g.renderOrder = 999;
  return g;
}

function secBuildGizmo(){
  if(SEC.arrow){ scene.remove(SEC.arrow); }
  SEC.arrow = new THREE.Group();
  SEC.arrow.add(secMakeArrow("x", 0xff4d4d));
  SEC.arrow.add(secMakeArrow("y", 0x4dff6a));
  SEC.arrow.add(secMakeArrow("z", 0x4d9dff));
  SEC.arrow.add(secMakeRing("x", 0xff4d4d));
  SEC.arrow.add(secMakeRing("y", 0x4dff6a));
  SEC.arrow.add(secMakeRing("z", 0x4d9dff));
  scene.add(SEC.arrow);
  secSetGizmoMode(SEC.gizmoMode);
}

function secSetGizmoMode(mode){
  SEC.gizmoMode = mode;
  if(!SEC.arrow) return;
  SEC.arrow.children.forEach(c=>{
    const isRing = !!c.userData.secRing;
    c.visible = (mode==="rotate") ? isRing : !isRing;
  });
  const bMove=$('secModeMove'), bRot=$('secModeRotate');
  if(bMove) bMove.classList.toggle("on", mode==="translate");
  if(bRot) bRot.classList.toggle("on", mode==="rotate");
}

function secSetGizmoVisible(v){
  if(SEC.arrow) SEC.arrow.visible = v && (($('secShowGizmo') ? $('secShowGizmo').checked : true));
  if(SEC.group) SEC.group.visible = ($('secShowFrame') ? $('secShowFrame').checked : true);
}

function secPositionGizmo(){
  if(!SEC._plane) return;
  const n = SEC._plane.normal.clone();
  const pt = n.clone().multiplyScalar(-SEC._plane.constant);
  if(SEC.group){ SEC.group.position.copy(pt); SEC.group.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1), n); }
  if(SEC.arrow){ SEC.arrow.position.copy(pt); SEC.arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1), n); }
}

function secUpdate(){
  if(!SEC.group) return;
  const n = new THREE.Vector3(0,0,1).applyQuaternion(SEC.group.quaternion).normalize();
  const pt = SEC.group.position;
  SEC._plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, pt);
  SEC.freeNormal = n.clone();
  SEC.freePoint = pt.clone();
  applyClippingPlanes();
  secSyncFreePanel();
}

function secSyncFreePanel(){
  const n = SEC.freeNormal || new THREE.Vector3(0,0,1);
  const pt = SEC.freePoint || new THREE.Vector3();
  const eul = new THREE.Euler().setFromQuaternion(SEC.group ? SEC.group.quaternion : new THREE.Quaternion(), "XYZ");
  const set = (id, val)=>{ const e=$(id); if(e && document.activeElement!==e) e.value = (Math.round(val*100)/100); };
  set("secPosX", pt.x); set("secPosY", pt.y); set("secPosZ", pt.z);
  set("secRotX", eul.x*180/Math.PI); set("secRotY", eul.y*180/Math.PI); set("secRotZ", eul.z*180/Math.PI);
}

function secNumPosInput(){
  if(!SEC.group) return;
  const v = (id)=> { const e=$(id); return e? (parseFloat(e.value)||0) : 0; };
  SEC.group.position.set(v("secPosX"), v("secPosY"), v("secPosZ"));
  secUpdate(); secPositionGizmoSync();
}
function secNumRotInput(){
  if(!SEC.group) return;
  const v = (id)=> { const e=$(id); return e? (parseFloat(e.value)||0) : 0; };
  SEC.group.quaternion.setFromEuler(new THREE.Euler(v("secRotX")*Math.PI/180, v("secRotY")*Math.PI/180, v("secRotZ")*Math.PI/180, "XYZ"));
  secUpdate(); secPositionGizmoSync();
}
function secPositionGizmoSync(){
  if(SEC.arrow){ SEC.arrow.position.copy(SEC.group.position); SEC.arrow.quaternion.copy(SEC.group.quaternion); }
}

function secStart(){
  SEC.on = true;
  secBuildVisual();
  const c = secModelCenter();
  SEC.group.position.copy(c);
  SEC.group.quaternion.identity();
  secPositionGizmoSync();
  secUpdate();
  stRenderPlaneList();
}

function secOff(){
  SEC.on = false; SEC.editing = false; SEC.placing = false;
  secClearVisual();
  SEC._plane = null; SEC.freeNormal = null; SEC.freePoint = null;
  applyClippingPlanes();
  stRenderPlaneList();
  secSyncPanelVisibility();
}

function secReverse(){
  if(!SEC.group) return;
  SEC.group.rotateY(Math.PI);
  secUpdate(); secPositionGizmoSync();
}
function secReset(){
  if(!SEC.on) return;
  const c = secModelCenter();
  SEC.group.position.copy(c);
  SEC.group.quaternion.identity();
  secPositionGizmoSync();
  secUpdate();
}
function secDelete(){ secOff(); }
function secApply(){ SEC.editing=false; secSetGizmoVisible(false); secSyncPanelVisibility(); }
function secCancelEditing(){ SEC.editing=false; secSetGizmoVisible(false); secSyncPanelVisibility(); }

function secSyncPanelVisibility(){
  const editBlock = $('secEditBlock');
  if(editBlock) editBlock.style.display = (SEC.on) ? "" : "none";
  stRenderPlaneList();
}

// ---- SEC drag handling (gizmo pick via raycast on pointerdown/pointermove) ----
const secRaycaster = new THREE.Raycaster();
function secPointerToNDC(ev){
  const rect = viewEl.getBoundingClientRect();
  return new THREE.Vector2(((ev.clientX-rect.left)/rect.width)*2-1, -((ev.clientY-rect.top)/rect.height)*2+1);
}

function secTryDrag(ev){
  if(!SEC.on || !SEC.editing || !SEC.arrow || !SEC.arrow.visible) return false;
  const ndc = secPointerToNDC(ev);
  secRaycaster.setFromCamera(ndc, camera);
  const pickable = [];
  SEC.arrow.traverse(c=>{ if(c.isMesh && c.userData && c.userData.secHandle) pickable.push(c); });
  const hits = secRaycaster.intersectObjects(pickable, true);
  if(!hits.length) return false;
  const h = hits[0].object;
  SEC.drag = { handle:h.userData.secHandle, axis:h.userData.secAxis, startPoint:hits[0].point.clone(),
    startPos:SEC.group.position.clone(), startQuat:SEC.group.quaternion.clone(), ev0:{x:ev.clientX,y:ev.clientY} };
  controls.enabled = false;
  return true;
}

function secLocalAxis(axis){
  const v = axis==="x" ? new THREE.Vector3(1,0,0) : axis==="y" ? new THREE.Vector3(0,1,0) : new THREE.Vector3(0,0,1);
  return v.applyQuaternion(SEC.group.quaternion).normalize();
}

function secDragMove(ev){
  if(!SEC.drag) return;
  const dx = ev.clientX - SEC.drag.ev0.x, dy = ev.clientY - SEC.drag.ev0.y;
  if(SEC.drag.handle === "translate"){
    const axisVec = secLocalAxis(SEC.drag.axis);
    const rect = viewEl.getBoundingClientRect();
    const scale = secModelRadius()*0.01 || 0.05;
    const screenDelta = (dx - dy); // simple combined drag amount
    const amt = screenDelta * scale;
    SEC.group.position.copy(SEC.drag.startPos).addScaledVector(axisVec, amt);
  } else if(SEC.drag.handle === "rotate"){
    const amt = (dx+dy) * 0.005;
    const axisVec = SEC.drag.axis==="x"?new THREE.Vector3(1,0,0):SEC.drag.axis==="y"?new THREE.Vector3(0,1,0):new THREE.Vector3(0,0,1);
    const q = new THREE.Quaternion().setFromAxisAngle(axisVec, amt);
    SEC.group.quaternion.copy(SEC.drag.startQuat).multiply(q);
  }
  secPositionGizmoSync();
  secUpdate();
}
function secDragEnd(){
  if(SEC.drag){ SEC.drag = null; controls.enabled = true; }
}

// ---------------- SBX: axis-aligned Section Box ----------------
const SBX = { on:false, box:null, helper:null, faces:[], planes:null, drag:null };

function sbxBuildVisual(){
  sbxClearVisual();
  const c = secModelCenter();
  const r = secModelRadius() || 10;
  SBX.box = new THREE.Box3(new THREE.Vector3(c.x-r,c.y-r,c.z-r), new THREE.Vector3(c.x+r,c.y+r,c.z+r));
  SBX.helper = new THREE.Box3Helper(SBX.box, 0xffa94d);
  scene.add(SBX.helper);
  sbxBuildFaces();
  sbxApply();
}

function sbxClearVisual(){
  if(SBX.helper){ scene.remove(SBX.helper); SBX.helper=null; }
  (SBX.faces||[]).forEach(f=>scene.remove(f));
  SBX.faces = [];
}

function sbxBuildFaces(){
  (SBX.faces||[]).forEach(f=>scene.remove(f));
  SBX.faces = [];
  if(!SBX.box) return;
  const defs = [
    ["x","min"],["x","max"],["y","min"],["y","max"],["z","min"],["z","max"]
  ];
  defs.forEach(([axis,side])=>{
    const size = SBX.box.getSize(new THREE.Vector3());
    const w = axis==="x"? size.y : size.x;
    const h = axis==="z"? size.y : size.z;
    const geo = new THREE.PlaneGeometry(Math.max(w,0.01), Math.max(h,0.01));
    const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({color:0xffa94d, transparent:true, opacity:0.001, side:THREE.DoubleSide, depthWrite:false}));
    mesh.userData.sbxAxis = axis; mesh.userData.sbxSide = side;
    SBX.faces.push(mesh); scene.add(mesh);
  });
  sbxSyncFacePositions();
}

function sbxSyncFacePositions(){
  if(!SBX.box) return;
  const c = SBX.box.getCenter(new THREE.Vector3());
  SBX.faces.forEach(f=>{
    const axis = f.userData.sbxAxis, side = f.userData.sbxSide;
    const val = side==="min" ? SBX.box.min[axis] : SBX.box.max[axis];
    f.position.copy(c);
    f.position[axis] = val;
    if(axis==="x") f.rotation.set(0, Math.PI/2, 0);
    else if(axis==="y") f.rotation.set(Math.PI/2, 0, 0);
    else f.rotation.set(0,0,0);
  });
}

function sbxPlanesFromBox(){
  if(!SBX.box) return [];
  return [
    new THREE.Plane(new THREE.Vector3(1,0,0), -SBX.box.min.x),
    new THREE.Plane(new THREE.Vector3(-1,0,0), SBX.box.max.x),
    new THREE.Plane(new THREE.Vector3(0,1,0), -SBX.box.min.y),
    new THREE.Plane(new THREE.Vector3(0,-1,0), SBX.box.max.y),
    new THREE.Plane(new THREE.Vector3(0,0,1), -SBX.box.min.z),
    new THREE.Plane(new THREE.Vector3(0,0,-1), SBX.box.max.z),
  ];
}

function sbxApply(){
  SBX.planes = sbxPlanesFromBox();
  applyClippingPlanes();
  sbxSyncSliders();
}

function sbxStart(){
  secOff();
  SBX.on = true;
  sbxBuildVisual();
  stRenderBoxList();
}
function sbxOff(){
  SBX.on = false;
  sbxClearVisual();
  SBX.box = null; SBX.planes = null;
  applyClippingPlanes();
  stRenderBoxList();
}
function sbxReset(){
  if(!SBX.on) return;
  const c = secModelCenter(); const r = secModelRadius() || 10;
  SBX.box.min.set(c.x-r,c.y-r,c.z-r); SBX.box.max.set(c.x+r,c.y+r,c.z+r);
  sbxBuildFaces(); sbxApply();
}
function sbxReverse(){
  if(!SBX.on || !SBX.planes) return;
  SBX.planes = SBX.planes.map(p=> new THREE.Plane(p.normal.clone().negate(), -p.constant));
  renderer.clippingPlanes = (SEC.on && SEC._plane ? [SEC._plane] : []).concat(SBX.planes);
}

function sbxSyncSliders(){
  if(!SBX.box) return;
  const set=(id,val)=>{ const e=$(id); if(e && document.activeElement!==e) e.value = Math.round(val*100)/100; };
  set("bxXmin", SBX.box.min.x); set("bxXmax", SBX.box.max.x);
  set("bxYmin", SBX.box.min.y); set("bxYmax", SBX.box.max.y);
  set("bxZmin", SBX.box.min.z); set("bxZmax", SBX.box.max.z);
}
function sbxSetSlider(axis, side, val){
  if(!SBX.box) return;
  SBX.box[side][axis] = val;
  sbxBuildFaces(); sbxApply();
}

function sbxPointerToNDC(ev){ return secPointerToNDC(ev); }

function sbxTryDrag(ev){
  if(!SBX.on || !SBX.faces.length) return false;
  if(!($('bxShowGizmo') ? $('bxShowGizmo').checked : true)) return false;
  const ndc = sbxPointerToNDC(ev);
  secRaycaster.setFromCamera(ndc, camera);
  const hits = secRaycaster.intersectObjects(SBX.faces, false);
  if(!hits.length) return false;
  const f = hits[0].object;
  SBX.drag = { axis:f.userData.sbxAxis, side:f.userData.sbxSide, start:hits[0].point.clone(),
    startVal: f.userData.sbxSide==="min" ? SBX.box.min[f.userData.sbxAxis] : SBX.box.max[f.userData.sbxAxis],
    ev0:{x:ev.clientX,y:ev.clientY} };
  controls.enabled = false;
  return true;
}
function sbxDragMove(ev){
  if(!SBX.drag) return;
  const dy = ev.clientY - SBX.drag.ev0.y;
  const scale = secModelRadius()*0.01 || 0.05;
  const val = SBX.drag.startVal - dy*scale;
  SBX.box[SBX.drag.side][SBX.drag.axis] = val;
  sbxBuildFaces(); sbxApply();
}
function sbxDragEnd(){
  if(SBX.drag){ SBX.drag=null; controls.enabled = true; }
}

// ---------------- Panel: tabs / lists ----------------
function stRenderPlaneList(){
  const host = $('stPlaneList'); if(!host) return;
  if(SEC.on){
    const label = "Plane · custom orientation";
    host.innerHTML = '<div class="stRow"><span>'+label+'</span><button class="stDel" title="Remove">×</button></div>';
    const del = host.querySelector(".stDel"); if(del) del.onclick = ()=> secDelete();
  } else {
    host.innerHTML = '<div class="stEmpty">Nothing to display. Add a plane.</div>';
  }
  secSyncPanelVisibilityOnly();
}
function secSyncPanelVisibilityOnly(){
  const editBlock = $('secEditBlock');
  if(editBlock) editBlock.style.display = (SEC.on) ? "" : "none";
}
function stRenderBoxList(){
  const host = $('stBoxList'); if(!host) return;
  if(SBX.on){
    host.innerHTML = '<div class="stRow"><span>Section Box</span><button class="stDel" title="Remove">×</button></div>';
    const del = host.querySelector(".stDel"); if(del) del.onclick = ()=> sbxOff();
  } else {
    host.innerHTML = '<div class="stEmpty">Nothing to display. Add a box.</div>';
  }
}
function stSetTab(tab){
  const pTab=$('stTabPlane'), bTab=$('stTabBox'), pPane=$('stPanePlane')||$('stPlaneList'), bPane=$('stPaneBox');
  if(pTab) pTab.classList.toggle("on", tab==="plane");
  if(bTab) bTab.classList.toggle("on", tab==="box");
  const planeBlock = $('secEditBlock'); // part of plane pane
  const planePane = document.querySelector('[data-pane="plane"]') || null;
  if($('stPaneBox')) $('stPaneBox').style.display = (tab==="box") ? "" : "none";
  document.querySelectorAll('.stPanePlane,[data-pane="plane"]').forEach(e=> e.style.display = (tab==="plane") ? "" : "none");
}

// ---------------- Global pointer priority chain (gizmo/box drag) ----------------
renderer.domElement.addEventListener("pointerdown", (ev)=>{
  if(ev.button !== 0) return;
  if(SBX.on && sbxTryDrag(ev)) { ev.preventDefault(); ev.stopPropagation(); return; }
  if(SEC.on && secTryDrag(ev)) { ev.preventDefault(); ev.stopPropagation(); return; }
  // otherwise fall through to the existing click-based element picking
});
renderer.domElement.addEventListener("pointermove", (ev)=>{
  if(SEC.drag) { secDragMove(ev); return; }
  if(SBX.drag) { sbxDragMove(ev); return; }
});
window.addEventListener("pointerup", ()=>{
  if(SEC.drag) secDragEnd();
  if(SBX.drag) sbxDragEnd();
});

// ---------------- UI wiring ----------------
if($('stTabPlane')) $('stTabPlane').onclick = ()=> stSetTab("plane");
if($('stTabBox')) $('stTabBox').onclick = ()=> stSetTab("box");
if($('stMin')) $('stMin').onclick = ()=>{ const p=$('secToolsPanel'); if(p) p.classList.toggle("min"); };

if($('secAddBtn')) $('secAddBtn').onclick = ()=>{
  if(SEC.on){ SEC.editing = true; secSetGizmoVisible(true); secSyncPanelVisibility(); return; }
  secStart();
  SEC.editing = true; secSetGizmoVisible(true); secSyncPanelVisibility();
};
if($('secInvert2')) $('secInvert2').onclick = ()=> secReverse();
if($('secResetBtn2')) $('secResetBtn2').onclick = ()=> secReset();
if($('secDeleteBtn')) $('secDeleteBtn').onclick = ()=> secDelete();
if($('secCancelBtn')) $('secCancelBtn').onclick = ()=> secCancelEditing();
if($('secApplyBtn')) $('secApplyBtn').onclick = ()=> secApply();
if($('secModeMove')) $('secModeMove').onclick = ()=> secSetGizmoMode("translate");
if($('secModeRotate')) $('secModeRotate').onclick = ()=> secSetGizmoMode("rotate");
["secPosX","secPosY","secPosZ"].forEach(id=>{ if($(id)) $(id).oninput = secNumPosInput; });
["secRotX","secRotY","secRotZ"].forEach(id=>{ if($(id)) $(id).oninput = secNumRotInput; });
if($('secShowFrame')) $('secShowFrame').onchange = (e)=>{ if(SEC.group) SEC.group.visible = e.target.checked; };
if($('secShowGizmo')) $('secShowGizmo').onchange = (e)=>{ secSetGizmoVisible(SEC.editing); };

if($('bxAddBtn')) $('bxAddBtn').onclick = ()=>{ if(!SBX.on) sbxStart(); else stRenderBoxList(); };
if($('bxReset')) $('bxReset').onclick = sbxReset;
if($('bxOff')) $('bxOff').onclick = sbxOff;
if($('bxReverse')) $('bxReverse').onclick = sbxReverse;
if($('bxShowFrame')) $('bxShowFrame').onchange = (e)=>{ if(SBX.helper) SBX.helper.visible = e.target.checked; };
if($('bxShowGizmo')) $('bxShowGizmo').onchange = (e)=>{ (SBX.faces||[]).forEach(f=> f.visible = e.target.checked); };
[["bxXmin","x","min"],["bxXmax","x","max"],["bxYmin","y","min"],["bxYmax","y","max"],["bxZmin","z","min"],["bxZmax","z","max"]]
  .forEach(([id,a,s])=>{ const e=$(id); if(e) e.oninput = ()=> sbxSetSlider(a,s,+e.value); });

// init lists in empty state
stRenderPlaneList();
stRenderBoxList();
// ================= End Sectioning Tools =================
