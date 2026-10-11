
// ---------------- 2D Section View (Plan / Elevation) ----------------
// Uses Fragments' own native `model.getSection(plane, localIds?)` API (SectionManager/
// SectionGenerator inside @thatopen/fragments) to cut the loaded model along the active
// SEC plane and get back true cut-edge line geometry, then reframes an orthographic
// camera to look straight along the plane's normal -- a horizontal SEC plane gives a
// flat "Plan" view, a vertical one gives an "Elevation"/section view.
let sec2DLines = null;
let sec2DActive = false;
let sec2DSaved = null; // { camera, position, quaternion, top, bottom, left, right, target, navMode, controlsEnabled }

function secModelMatrixWorld(){
  if(activeModel && activeModel.object){ activeModel.object.updateMatrixWorld(true); return activeModel.object.matrixWorld; }
  return new THREE.Matrix4();
}

async function secGenerate2DView(){
  if(!activeModel || !SEC.on || !SEC._plane){
    logDiag("2D view: add and position a section plane first.", true);
    return;
  }
  const btn = $('sec2DGenBtn'); if(btn) btn.disabled = true;
  setLoading("Generating 2D section view…");
  try {
    const modelMatrix = secModelMatrixWorld();
    const invMatrix = modelMatrix.clone().invert();
    const localPlane = SEC._plane.clone().applyMatrix4(invMatrix);

    const result = await activeModel.getSection(localPlane);
    const vertCount = result && typeof result.index === "number" ? result.index : 0;
    if(!result || vertCount < 2){
      logDiag("2D view: no geometry intersects this plane -- move it so it actually cuts through the model.", true);
      return;
    }

    const src = result.buffer;
    const positions = new Float32Array(vertCount * 3);
    const v = new THREE.Vector3();
    for(let i = 0; i < vertCount; i++){
      v.set(src[i*3], src[i*3+1], src[i*3+2]);
      v.applyMatrix4(modelMatrix); // worker returns points in the model's own local space
      positions[i*3] = v.x; positions[i*3+1] = v.y; positions[i*3+2] = v.z;
    }

    if(sec2DLines){ scene.remove(sec2DLines); sec2DLines.geometry.dispose(); sec2DLines.material.dispose(); sec2DLines = null; }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const mat = new THREE.LineBasicMaterial({ color: 0x0b0d10, depthTest: false, depthWrite: false });
    sec2DLines = new THREE.LineSegments(geo, mat);
    sec2DLines.renderOrder = 1000;
    scene.add(sec2DLines);

    // Save current camera/nav state so "Back to 3D" restores exactly where the user was.
    if(!sec2DActive){
      sec2DSaved = {
        camera, position: camera.position.clone(), quaternion: camera.quaternion.clone(),
        top: camera.top, bottom: camera.bottom, left: camera.left, right: camera.right,
        target: controls.target.clone(), controlsEnabled: controls.enabled,
      };
    }

    const normal = SEC.freeNormal ? SEC.freeNormal.clone() : new THREE.Vector3(0,0,1);
    const center = SEC.freePoint ? SEC.freePoint.clone() : secModelCenter();
    const up = Math.abs(normal.y) > 0.9 ? new THREE.Vector3(0,0,1) : new THREE.Vector3(0,1,0);
    const r = secModelRadius() * 1.4 || 20;

    camera = orthoCamera;
    camera.position.copy(center).addScaledVector(normal, r*3);
    camera.up.copy(up);
    camera.lookAt(center);
    const aspect = viewEl.clientWidth / viewEl.clientHeight || 1;
    camera.left = -r*aspect; camera.right = r*aspect; camera.top = r; camera.bottom = -r;
    camera.near = 0.1; camera.far = r*8;
    camera.updateProjectionMatrix();

    controls.object = camera;
    controls.target.copy(center);
    controls.enabled = false; // lock navigation -- this is a flat drawing, not a 3D view
    controls.update();

    if(activeModel.object) activeModel.object.visible = false;
    if(SEC.group) SEC.group.visible = false;
    if(SEC.arrow) SEC.arrow.visible = false;
    if(SBX.helper) SBX.helper.visible = false;
    (SBX.faces||[]).forEach(f=> f.visible = false);
    sec2DLines.visible = true;

    sec2DActive = true;
    const genBtn = $('sec2DGenBtn'); if(genBtn) genBtn.classList.add("on");
    const exitRow = $('sec2DExitRow'); if(exitRow) exitRow.style.display = "";
    const hint = $('sec2DHint'); if(hint) hint.style.display = "";
    logDiag(`2D view generated: ${vertCount/2} cut-edge segments.`);
  } catch(e) {
    logDiag("2D view generation failed: " + e, true);
  } finally {
    setLoading(null);
    if(btn) btn.disabled = false;
  }
}

function sec2DExit(){
  if(!sec2DActive) return;
  if(sec2DLines) sec2DLines.visible = false;
  if(activeModel && activeModel.object) activeModel.object.visible = true;
  if(SEC.group) SEC.group.visible = ($('secShowFrame') ? $('secShowFrame').checked : true);
  if(SEC.arrow) SEC.arrow.visible = SEC.editing && ($('secShowGizmo') ? $('secShowGizmo').checked : true);
  if(SBX.on && SBX.helper) SBX.helper.visible = ($('bxShowFrame') ? $('bxShowFrame').checked : true);
  if(SBX.on) (SBX.faces||[]).forEach(f=> f.visible = ($('bxShowGizmo') ? $('bxShowGizmo').checked : true));

  if(sec2DSaved){
    camera = sec2DSaved.camera;
    camera.position.copy(sec2DSaved.position);
    camera.quaternion.copy(sec2DSaved.quaternion);
    if(camera.isOrthographicCamera){
      camera.top = sec2DSaved.top; camera.bottom = sec2DSaved.bottom;
      camera.left = sec2DSaved.left; camera.right = sec2DSaved.right;
      camera.updateProjectionMatrix();
    }
    controls.object = camera;
    controls.target.copy(sec2DSaved.target);
    controls.enabled = sec2DSaved.controlsEnabled;
    controls.update();
  }
  resize();

  sec2DActive = false;
  const genBtn = $('sec2DGenBtn'); if(genBtn) genBtn.classList.remove("on");
  const exitRow = $('sec2DExitRow'); if(exitRow) exitRow.style.display = "none";
  const hint = $('sec2DHint'); if(hint) hint.style.display = "none";
}

if($('sec2DGenBtn')) $('sec2DGenBtn').onclick = ()=> secGenerate2DView();
if($('sec2DExitBtn')) $('sec2DExitBtn').onclick = ()=> sec2DExit();
// Deleting/turning off the active plane while in 2D view should drop back to 3D rather
// than leave a stale flat drawing with nothing driving it.
const _secDeleteOrig = secDelete;
secDelete = function(){ if(sec2DActive) sec2DExit(); _secDeleteOrig(); };
