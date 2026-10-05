import * as THREE from "three";
import { OrbitControls } from "./vendor_fragments/OrbitControls.js?b=5";
import * as FRAGS from "./vendor_fragments/fragments/index.mjs?b=5";

// ---- Diagnostic Logger (Loaded First) ----
const diagOverlay = document.createElement('div');
diagOverlay.style.cssText = 'position:absolute; top:50px; left:260px; right:260px; background:rgba(10,14,20,0.9); border:1px solid #f2585f; color:#eaf0f7; padding:15px; font-family:monospace; z-index:9999; max-height:80vh; overflow-y:auto; display:none; pointer-events:none;';
// document.body.appendChild(diagOverlay);

window._diagLogs = [];
function logDiag(msg, isError = false) {
  const time = new Date().toLocaleTimeString();
  const line = `[${time}] ${msg}`;
  console[isError ? 'error' : 'log'](line);
  window._diagLogs.push(line);
  
  if (isError) {
    // diagOverlay.style.display = 'block';
    diagOverlay.innerHTML += `<div style="color:#f2585f; font-weight:bold;">${line}</div>`;
    const errEl = document.getElementById("err");
    if (errEl) {
      errEl.style.display="block"; 
      errEl.innerHTML = msg;
    }
  } else {
    diagOverlay.innerHTML += `<div style="color:#31d0a5;">${line}</div>`;
  }
}

// Global Error Handler
window.onerror = function(msg, url, lineNo, columnNo, error) {
    logDiag(`ERROR: ${msg} at ${lineNo}:${columnNo}`, true);
    setLoading(null);
    return false;
};

// ---- UI Bindings ----
const $ = (id) => document.getElementById(id);
const viewEl = $("view"), loadingEl = $("loading");
function setLoading(t){ if(t===null){ loadingEl.style.display="none"; } else { loadingEl.style.display="grid"; const l=$("ldtxt"); if(l) l.innerHTML=t; } }

// ---- query params ----
const q = new URLSearchParams(location.search);
const project = q.get("project") || "";
const token = q.get("token") || "";
const rels = q.getAll("rel");

function fileURL(rel){ 
  return `${location.origin}/projects/${encodeURIComponent(project)}/file?rel=${encodeURIComponent(rel)}&token=${encodeURIComponent(token)}`; 
}

// ---- Scene Setup ----
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e14);
const perspCamera = new THREE.PerspectiveCamera(60, 1, 0.1, 100000); 
perspCamera.up.set(0,1,0);
const orthoCamera = new THREE.OrthographicCamera();
orthoCamera.up.set(0,1,0);

let camera = perspCamera;

const renderer = new THREE.WebGLRenderer({ antialias:true, logarithmicDepthBuffer: true });
renderer.localClippingEnabled = true;
viewEl.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;

scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x30363f, 1.15));
scene.add(new THREE.AmbientLight(0xffffff, 0.35));
const dir = new THREE.DirectionalLight(0xfff6e8, 0.95); dir.position.set(1,1.4,2); scene.add(dir);
const grid = new THREE.GridHelper(200, 40, 0x2a3a50, 0x18222f); scene.add(grid);

function resize(){ 
  const w=viewEl.clientWidth, h=viewEl.clientHeight; 
  renderer.setSize(w,h,false);
  if(camera.isOrthographicCamera){ 
    const asp=w/h, halfH=(camera.top-camera.bottom)/2, halfW=halfH*asp; 
    camera.left=-halfW; camera.right=halfW; 
  } else { 
    camera.aspect=w/h; 
  }
  camera.updateProjectionMatrix(); 
}
window.addEventListener("resize", resize);

// ---- Engine: Fragments ----
let fragments, activeModel, modelBox;
const root = new THREE.Group(); scene.add(root);

async function initEngine() {
  logDiag("Initializing Fragments Engine...");
  try {
    const workerUrl = new URL("./vendor_fragments/fragments/Worker/worker.mjs", location.href).toString();
    fragments = new FRAGS.FragmentsModels(workerUrl);
  } catch (e) {
    logDiag("Error initializing FragmentsModels: " + e.message, true);
  }
}

async function loadModel(rel) {
  setLoading("Reading " + rel.split("/").pop() + " ...");
  logDiag("Starting to load model: " + rel);
  // diagOverlay.style.display = 'block'; 
  
  try {
    let fragBytes;
    const fragUrl = fileURL(rel + ".frag");
    const fragRes = await fetch(fragUrl);
    
    if (fragRes.ok) {
        logDiag("Found pre-converted .frag file! Downloading...");
        fragBytes = new Uint8Array(await fragRes.arrayBuffer());
    } else {
        logDiag("No .frag found. Falling back to fetching raw IFC file...");
        const url = fileURL(rel);
        const res = await fetch(url);
        if (!res.ok) throw new Error("Could not fetch " + rel + " (Status: " + res.status + ")");
        const bytes = new Uint8Array(await res.arrayBuffer());

        logDiag("Setting up browser IfcImporter...");
        const importer = new FRAGS.IfcImporter();
        importer.wasm.path = "/ui/vendor_fragments/";
        importer.wasm.absolute = true;
        importer.webIfcSettings = { COORDINATE_TO_ORIGIN: true };
        await importer.setup();
        
        logDiag("Parsing IFC in browser...");
        fragBytes = await importer.convert(bytes);
        logDiag("Converted to .frag bytes.");
    }

    logDiag("Loading .frag into FragmentsModels...");
    activeModel = await fragments.load(fragBytes, { modelId: rel });
    if(activeModel.getClippingPlanesEvent) activeModel.getClippingPlanesEvent = () => renderer.clippingPlanes;
    await fragments.update(true);
    
    root.add(activeModel.object);
    
    modelBox = new THREE.Box3().setFromObject(activeModel.object);
    const center = modelBox.getCenter(new THREE.Vector3());
    if (center.length() > 5000) {
      logDiag("Model is extremely far from origin. Auto-centering...");
      activeModel.object.position.copy(center).negate();
      activeModel.object.updateMatrixWorld(true);
      modelBox = new THREE.Box3().setFromObject(activeModel.object);
    }
    
    try { await buildSpatialTree(); } catch(e){}
    try { await renderCatList(); } catch(e){}
    
    fit();
    setLoading(null);
  } catch (err) {
    logDiag("Failed to load model: " + err, true);
    setLoading(null);
  }
}

function fit() {
    if(!modelBox) return;
    const size = modelBox.getSize(new THREE.Vector3());
    const center = modelBox.getCenter(new THREE.Vector3());
    const r = Math.max(size.x, size.y, size.z) || 10;
    
    camera.position.set(center.x + r, center.y + r*0.6, center.z + r);
    camera.near = Math.max(0.01, r / 1000);
    camera.far = Math.max(10000, r * 100); 
    camera.updateProjectionMatrix();
    
    controls.target.copy(center);
    controls.update();
}

let storeys = [];
window._highlightNode = (localId) => {
    if(!localId || !activeModel || !activeModel.setColor) return;
    try { activeModel.resetColor(); } catch(e){}
    activeModel.setColor([localId], new THREE.Color(0x4d7cfe));
    window._lastSelId = localId;
};

async function buildSpatialTree() {
  const treeEl = $("spatialTree");
  if(!treeEl || !activeModel) return;
  try {
    const spatial = await activeModel.getSpatialStructure();
    const sel = $("storeySel");
    if(sel) sel.innerHTML = '<option value="">3D view</option>';
    storeys = [];

    function traverse(node, depth=0) {
      if(!node) return "";
      if (node.category === 'IFCBUILDINGSTOREY') {
         storeys.push(node);
         if(sel) {
            const opt = document.createElement('option');
            opt.value = node.localId;
            opt.textContent = "Storey " + (node.localId || "");
            sel.appendChild(opt);
         }
      }
      let html = `<div style="padding-left:${depth*12}px; margin:3px 0;">`;
      html += `<div class="trow" onclick="window._highlightNode(${node.localId})">`;
      html += `<b>${node.category || 'Node'}</b> ${node.localId ? '(ID: '+node.localId+')' : ''}`;
      html += `</div>`;
      if(node.children) {
        for(const child of node.children) { html += traverse(child, depth+1); }
      }
      html += `</div>`;
      return html;
    }

    treeEl.innerHTML = traverse(spatial);

    if(sel) {
       sel.onchange = async () => {
         const val = sel.value;
         if(!val) {
           if($("btnPersp")) $("btnPersp").click();
           return;
         }
         if($("btnOrtho")) $("btnOrtho").click();
         try {
           const pos = await activeModel.getPositions([parseInt(val)]);
           if (pos && pos[0]) {
              const vec = new THREE.Vector3().fromArray(pos[0]);
              camera.position.set(vec.x, vec.y + 50, vec.z);
              camera.lookAt(vec.x, vec.y, vec.z);
              controls.target.copy(new THREE.Vector3(vec.x, vec.y, vec.z));
              controls.update();
           }
         } catch(e) { }
       };
    }
  } catch (e) {
    console.warn("Spatial tree err", e);
  }
}

async function renderCatList() {
  const catEl = $("catList");
  if(!catEl || !activeModel) return;
  try {
    const cats = await activeModel.getCategories();
    catEl.innerHTML = cats.map(c => `<div class="trow"><span>${c}</span></div>`).join("");
  } catch(e) {}
}

// ---- Measurement State ----
window._measureMode = null; 
let measurePoints = [];
const measureGroup = new THREE.Group();
measureGroup.name = 'measureGroup';
root.add(measureGroup);

function createMeasureLabel(text, pos) {
    const div = document.createElement('div');
    div.className = 'mLabel';
    div.innerText = text;
    div.style.position = 'absolute';
    div.style.color = '#fff';
    div.style.background = '#131b26';
    div.style.border = '1px solid #4d7cfe';
    div.style.padding = '4px 8px';
    div.style.borderRadius = '4px';
    div.style.pointerEvents = 'none';
    div.style.transform = 'translate(-50%, -100%)';
    div.style.zIndex = '10';
    document.body.appendChild(div);
    
    const update = () => {
        if (!div.parentNode) return;
        const temp = pos.clone().project(camera);
        const x = (temp.x * .5 + .5) * window.innerWidth;
        const y = (temp.y * -.5 + .5) * window.innerHeight;
        div.style.left = x + 'px';
        div.style.top = y + 'px';
        requestAnimationFrame(update);
    };
    update();
    return div;
}

const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

viewEl.addEventListener('click', async (event) => {
    if (!activeModel) return;

    const rect = viewEl.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    
    raycaster.setFromCamera(mouse, camera);

    let hit = null;
    let localId = null;

    if (activeModel.raycast) {
        // Try VirtualFragmentsModel API directly on its raycaster to bypass model.view missing
        try {
            if (activeModel.raycaster && activeModel.raycaster.raycast) {
                const res = activeModel.raycaster.raycast(raycaster.ray, raycaster.ray, null, false);
                if (res) {
                    hit = res;
                    localId = res.localId !== undefined ? res.localId : (res.hit && res.hit.localId !== undefined ? res.hit.localId : null);
                }
            } else {
                const res = await activeModel.raycast(raycaster.ray, raycaster.ray, false);
                if (res) {
                    hit = res;
                    localId = res.localId !== undefined ? res.localId : (res.hit && res.hit.localId !== undefined ? res.hit.localId : null);
                }
            }
        } catch(e) {}

        // Try _FragmentsModel API if that didn't work
        if (!hit) {
            try {
                const rayData = {
                    mouse: { x: event.clientX, y: event.clientY },
                    dom: viewEl,
                    camera: camera
                };
                const res = await activeModel.raycast(rayData);
                if (res) {
                    hit = res;
                    localId = res.localId !== undefined ? res.localId : (res.hit && res.hit.localId !== undefined ? res.hit.localId : null);
                }
            } catch(e) {}
        }
    }

    // If activeModel raycast failed, try the raw raycaster but protect against crashing
    if (!hit) {
        try {
            const validChildren = [];
            scene.traverse(c => {
                if (c.isMesh && c.geometry && c.geometry.attributes && c.geometry.attributes.position) {
                    const pos = c.geometry.attributes.position;
                    if (pos.array && pos.array.length > 0 && pos.count > 0) {
                        // Check index array if index exists
                        if (c.geometry.index && (!c.geometry.index.array || c.geometry.index.array.length === 0)) {
                            return; // Invalid index array
                        }
                        validChildren.push(c);
                    }
                }
            });
            const intersects = raycaster.intersectObjects(validChildren, false);
            if (intersects.length > 0) {
                hit = intersects[0];
            }
        } catch (e) {
            console.warn("Raw raycaster crashed:", e);
        }
    }

    if (!hit) {
        window._lastSelId = null;
        if (activeModel && activeModel.resetColor) {
            try { activeModel.resetColor(); } catch(e){}
        }
        const propBox = $('propBox');
        if (propBox) propBox.innerHTML = '<div class="hint">Select an element to see properties.</div>';
        return;
    }
    
    if (window._measureMode === 'length') {
        const pt = hit.point;
        const sphereMat = new THREE.MeshBasicMaterial({ color: 0xff0000, depthTest: false });
        const sphere = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 8), sphereMat);
        sphere.position.copy(pt);
        scene.add(sphere);
        window._measurePoints.push(pt);
        
        if (window._measurePoints.length === 2) {
            const p1 = window._measurePoints[0];
            const p2 = window._measurePoints[1];
            const dist = p1.distanceTo(p2);
            
            const mat = new THREE.LineBasicMaterial({ color: 0xff0000, linewidth: 2 });
            const geom = new THREE.BufferGeometry().setFromPoints([p1, p2]);
            const line = new THREE.Line(geom, mat);
            scene.add(line);
            
            alert(`Distance: ${dist.toFixed(3)}m`);
            
            window._measureMode = null;
            window._measurePoints = [];
            
            if ($('btnMeasure')) $('btnMeasure').classList.remove('active');
        }
        return; 
    }

    // FlatBuffer Fallback
    if (localId === null) {
       try {
           const index = hit.batchId !== undefined ? hit.batchId : hit.instanceId;
           if (activeModel.data && typeof activeModel.data.meshes === 'function') {
               const meshes = activeModel.data.meshes();
               if (meshes && typeof meshes.meshesItems === 'function' && typeof activeModel.data.localIds === 'function') {
                   const localIdIndex = meshes.meshesItems(index);
                   localId = activeModel.data.localIds(localIdIndex);
               }
           }
       } catch(e) {}
    }

    if (localId === null && hit.object && hit.object.getItemID) {
      localId = hit.object.getItemID(hit.instanceId);
    }

    if (localId !== null && localId !== undefined) {
      console.log("Selected localId:", localId);
      window._lastSelId = localId;
      
      if (activeModel.setColor) {
          try { activeModel.resetColor(); } catch(e){}
          try { activeModel.setColor([localId], new THREE.Color(0x4d7cfe)); } catch(e) {}
      }

      const propBox = $('propBox');
      if (propBox) {
        propBox.innerHTML = '<div class="hint">Loading properties...</div>';
        try {
          const data = await activeModel.getItemsData([localId], { attributesDefault: true });
          if (data && data.length > 0) {
            const props = data[0];
            let html = '<div class="sec">Selected Element</div>';
            for (const [k, v] of Object.entries(props)) {
              if (typeof v === 'object') continue;
              html += `<div class="prop"><b>${k}</b>${v}</div>`;
            }
            propBox.innerHTML = html;
          }
        } catch(err) {
          propBox.innerHTML = '<div class="hint">No properties found.</div>';
        }
      }
    }
});

// ---- Toolbar Bindings ----

const btnPersp = $('btnPersp');
const btnOrtho = $('btnOrtho');

if (btnPersp && btnOrtho) {
  btnPersp.onclick = () => {
    btnPersp.classList.add('on');
    btnOrtho.classList.remove('on');
    camera = perspCamera;
    controls.object = camera;
    if(activeModel && activeModel.useCamera) activeModel.useCamera(camera);
    resize();
  };
  btnOrtho.onclick = () => {
    btnOrtho.classList.add('on');
    btnPersp.classList.remove('on');
    camera = orthoCamera;
    
    if(modelBox) {
      const center = modelBox.getCenter(new THREE.Vector3());
      const size = modelBox.getSize(new THREE.Vector3());
      const r = Math.max(size.x, size.y, size.z) || 10;
      camera.position.set(center.x + r, center.y + r*0.6, center.z + r);
      camera.lookAt(center);
    }
    
    controls.object = camera;
    if(activeModel && activeModel.useCamera) activeModel.useCamera(camera);
    resize();
  };
}

const btnShaded = $('dmShaded');
const btnWire = $('dmWire');
const btnTrans = $('dmTrans');
const btnXray = $('dmXray');
const dmBtns = [btnShaded, btnWire, btnTrans, btnXray];

function setDisplayMode(mode, activeBtn) {
  dmBtns.forEach(b => { if(b) b.classList.remove('on'); });
  if(activeBtn) activeBtn.classList.add('on');
  
  if (!activeModel || !activeModel.object) return;
  activeModel.object.children.forEach(mesh => {
      if(!mesh || !mesh.material) return;
      
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      mats.forEach(mat => {
        if (mode === 'shaded') {
          mat.wireframe = false;
          mat.transparent = false;
          mat.opacity = 1.0;
          mat.depthTest = true;
        } else if (mode === 'wire') {
          mat.wireframe = true;
          mat.transparent = false;
          mat.opacity = 1.0;
          mat.depthTest = true;
        } else if (mode === 'trans') {
          mat.wireframe = false;
          mat.transparent = true;
          mat.opacity = 0.5;
          mat.depthTest = true;
        } else if (mode === 'xray') {
          mat.wireframe = false;
          mat.transparent = true;
          mat.opacity = 0.15;
          mat.depthTest = false;
        }
        mat.needsUpdate = true;
      });
  });
}

if (btnShaded) btnShaded.onclick = () => setDisplayMode('shaded', btnShaded);
if (btnWire) btnWire.onclick = () => setDisplayMode('wire', btnWire);
if (btnTrans) btnTrans.onclick = () => setDisplayMode('trans', btnTrans);
if (btnXray) btnXray.onclick = () => setDisplayMode('xray', btnXray);

if($('btnRealistic')) $('btnRealistic').onclick = () => {
    const btn = $('btnRealistic');
    if(!btn) return;
    const isOn = btn.classList.contains("on");
    btn.classList.toggle("on", !isOn);
    if (activeModel && activeModel.resetColor) {
        try { activeModel.resetColor(); } catch(e){}
    }
};

function setNavMode(m) {
  controls.mouseButtons.LEFT = m==='pan'?THREE.MOUSE.PAN : m==='zoom'?THREE.MOUSE.DOLLY : THREE.MOUSE.ROTATE;
  [['btnOrbit','orbit'],['btnPan','pan'],['btnZoom','zoom']].forEach(pair=>{
    const b = $(pair[0]); if(b) b.classList.toggle("on", pair[1]===m);
  });
}
if($('btnOrbit')) $('btnOrbit').onclick = ()=> setNavMode("orbit");
if($('btnPan')) $('btnPan').onclick = ()=> setNavMode("pan");
if($('btnZoom')) $('btnZoom').onclick = ()=> setNavMode("zoom");

if($('btnFit')) $('btnFit').onclick = () => fit();
if($('btnReset')) $('btnReset').onclick = () => { 
    fit(); 
    if($('dmShaded')) { setDisplayMode('shaded', $('dmShaded')); }
    if(activeModel && activeModel.resetVisible) activeModel.resetVisible(); 
    if(activeModel && activeModel.object && activeModel.object.children) {
        activeModel.object.children.forEach(c => c.visible = true);
    }
    window._lastSelId = null;
    if (activeModel && activeModel.resetColor) { try { activeModel.resetColor(); } catch(e){} }
};

if($('btnHide')) $('btnHide').onclick = () => {
    if (activeModel && activeModel.setVisible && window._lastSelId) {
        activeModel.setVisible([window._lastSelId], false);
    }
};
if($('btnIso')) $('btnIso').onclick = async () => {
    if (activeModel && activeModel.setVisible && window._lastSelId) {
        try {
            const allIds = await activeModel.getItemsIdsWithGeometry();
            activeModel.setVisible(allIds, false);
            activeModel.setVisible([window._lastSelId], true);
        } catch(e) {
            activeModel.object.children.forEach(c => c.visible = false);
            activeModel.setVisible([window._lastSelId], true);
        }
    }
};
if($('btnShowAll')) $('btnShowAll').onclick = () => {
    if (activeModel) {
        if(activeModel.resetVisible) { try { activeModel.resetVisible(); } catch(e){} }
        if(activeModel.object && activeModel.object.children) {
            activeModel.object.children.forEach(c => c.visible = true);
        }
    }
};

if($('btnSectionTool')) $('btnSectionTool').onclick = ()=>{
    const p = $('secToolsPanel'); if(!p) return;
    const open = !p.classList.contains("open");
    p.classList.toggle("open", open);
    const b = $('btnSectionTool'); if(b) b.classList.toggle("on", open);
};
if($('btnMeasureTool')) $('btnMeasureTool').onclick = ()=>{
    const d=$('measureDock'); if(!d) return; 
    const open=!d.classList.contains("open");
    d.classList.toggle("open", open); 
    const t=$('btnMeasureTool'); if(t) t.classList.toggle("on", open);
};
if($('btnMeasureDone')) $('btnMeasureDone').onclick = ()=>{
    const d=$('measureDock'); if(d) d.classList.remove("open");
    const t=$('btnMeasureTool'); if(t) t.classList.remove("on");
    window._measureMode = null;
    if ($('btnLen')) $('btnLen').classList.remove("on");
};
if($('btnLen')) $('btnLen').onclick = () => {
    window._measureMode = window._measureMode === 'length' ? null : 'length';
    $('btnLen').classList.toggle('on', window._measureMode === 'length');
};
if($('btnMclr')) $('btnMclr').onclick = () => {
    if (typeof measureGroup !== 'undefined') measureGroup.clear();
    measurePoints = [];
    document.querySelectorAll('.mLabel').forEach(e => e.remove());
};

if($('stClose')) $('stClose').onclick = ()=> {
    const p = $('secToolsPanel'); if(p) p.classList.remove("open");
    const b = $('btnSectionTool'); if(b) b.classList.remove("on");
};

function animate() {
  requestAnimationFrame(animate);
  if(controls) controls.update();
  if(renderer && scene && camera) renderer.render(scene, camera);
}

async function boot() {
  logDiag("Booting viewer...");
  resize();
  await initEngine();
  animate();
  if (rels.length > 0) {
    await loadModel(rels[0]);
  } else {
    setLoading(null);
  }
}

// Start
boot();



// ---- External AI Commands ----
window.addEventListener('message', async (event) => {
    if (!event.data || event.data.type !== 'viewer_command') return;
    const cmd = event.data;
    
    if (cmd.command === 'isolate' && activeModel) {
        logDiag(`AI Command received: Isolate category ${cmd.category}`);
        try {
            // Find all localIds for this category
            const targetCat = cmd.category.toUpperCase();
            const spatial = await activeModel.getSpatialStructure();
            let ids = [];
            
            function searchNode(node) {
                if(!node) return;
                // If it's the exact category, or it's a category we want
                if (node.category && node.category.toUpperCase().includes(targetCat)) {
                    if (node.localId) ids.push(node.localId);
                    // Also gather all children localIds
                    function gatherChildren(n) {
                        if (n.localId) ids.push(n.localId);
                        if (n.children) n.children.forEach(gatherChildren);
                    }
                    if (node.children) node.children.forEach(gatherChildren);
                } else if (node.children) {
                    node.children.forEach(searchNode);
                }
            }
            searchNode(spatial);
            
            if (ids.length > 0) {
                // Hide all, show targeted
                const allIds = await activeModel.getItemsIdsWithGeometry();
                activeModel.setVisible(allIds, false);
                activeModel.setVisible(ids, true);
                
                // Color highlight
                try { activeModel.resetColor(); } catch(e){}
                activeModel.setColor(ids, new THREE.Color(0x4d7cfe));
                
                logDiag(`Isolated ${ids.length} elements for ${targetCat}`);
            } else {
                logDiag(`No elements found for category: ${targetCat}`, true);
            }
        } catch(e) {
            console.error("AI Command error", e);
        }
    }
});
