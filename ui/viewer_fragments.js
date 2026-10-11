import * as THREE from "three";
import { OrbitControls } from "./vendor_fragments/OrbitControls.js?b=5";
import * as FRAGS from "./vendor_fragments/fragments/index.mjs?b=5";
import * as OBC from "@thatopen/components";

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

const renderer = new THREE.WebGLRenderer({ antialias:true, logarithmicDepthBuffer: true, powerPreference: "high-performance" });
renderer.localClippingEnabled = true;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
viewEl.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;

// Track pointer down vs drag distance so rotation does not trigger accidental selection
let _pointerDownPos = null;
let _isDraggingPointer = false;
renderer.domElement.addEventListener("pointerdown", (ev) => {
  if (ev.button === 0) {
    _pointerDownPos = { x: ev.clientX, y: ev.clientY };
    _isDraggingPointer = false;
  }
});
window.addEventListener("pointermove", (ev) => {
  if (_pointerDownPos) {
    const dist = Math.hypot(ev.clientX - _pointerDownPos.x, ev.clientY - _pointerDownPos.y);
    if (dist > 5) {
      _isDraggingPointer = true;
    }
  }
});
window.addEventListener("pointerup", () => {
  setTimeout(() => {
    _pointerDownPos = null;
    _isDraggingPointer = false;
  }, 100);
});

// Architectural Lighting Suite (Sun, Sky dome, Soft ground bounce)
scene.add(new THREE.HemisphereLight(0xe8f0ff, 0x242d38, 1.25));
scene.add(new THREE.AmbientLight(0xffffff, 0.45));
const dir = new THREE.DirectionalLight(0xfff8ee, 1.1); 
dir.position.set(1.5, 2.2, 1.8); 
scene.add(dir);
const fillLight = new THREE.DirectionalLight(0xd4e2f8, 0.4);
fillLight.position.set(-1.5, 1.0, -1.5);
scene.add(fillLight);
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

// ---- Left & Right Panel Resizers ----
(function wireResizers(){
  const leftH = $("leftResizer");
  const rightH = $("rightResizer");
  
  if (leftH) {
    let drag = false;
    leftH.addEventListener("pointerdown", e => {
      drag = true;
      leftH.classList.add("drag");
      try { leftH.setPointerCapture(e.pointerId); } catch(_) {}
    });
    window.addEventListener("pointermove", e => {
      if (!drag) return;
      const w = Math.min(600, Math.max(160, e.clientX));
      document.documentElement.style.setProperty("--leftw", w + "px");
      resize();
    });
    window.addEventListener("pointerup", () => {
      if (drag) {
        drag = false;
        leftH.classList.remove("drag");
        resize();
      }
    });
  }

  if (rightH) {
    let drag = false;
    rightH.addEventListener("pointerdown", e => {
      drag = true;
      rightH.classList.add("drag");
      try { rightH.setPointerCapture(e.pointerId); } catch(_) {}
    });
    window.addEventListener("pointermove", e => {
      if (!drag) return;
      const w = Math.min(650, Math.max(180, window.innerWidth - e.clientX));
      document.documentElement.style.setProperty("--rightw", w + "px");
      resize();
    });
    window.addEventListener("pointerup", () => {
      if (drag) {
        drag = false;
        rightH.classList.remove("drag");
        resize();
      }
    });
  }
})();

// ---- FastModelPicker (GPU-readback picking via @thatopen/components) ----
// Duck-typed "world" object with exactly what FastModelPicker/FastModelPickers
// touch at runtime (confirmed by reading the un-minified @thatopen/components
// source): FastModelPickers.get() only needs world.uuid + world.onDisposed.add();
// the picker itself only ever reads world.renderer (truthy check),
// world.scene.three, world.camera.three, world.renderer.three and
// world.renderer.clippingPlanes. camera and renderer.clippingPlanes are exposed
// via getters -- never snapshotted -- because this app swaps `camera` between
// perspective/ortho and mutates renderer.clippingPlanes elsewhere after this
// object is built.
const components = new OBC.Components();
const fragmentsManagerOBC = components.get(OBC.FragmentsManager);
const pickers = components.get(OBC.FastModelPickers);
const pickerWorld = {
  uuid: "expo-design-ai-picker-world",
  scene: { three: scene },
  get camera() { return { three: camera }; },
  get renderer() {
    return {
      three: renderer,
      get clippingPlanes() { return renderer.clippingPlanes; },
    };
  },
  onDisposed: { add() {} },
};
const picker = pickers.get(pickerWorld);

// ---- Engine: Fragments ----
let fragments, activeModel, modelBox;
let loadedModels = []; // [{ rel, model, name }]
const root = new THREE.Group(); scene.add(root);

const MODEL_COLORS = ["#4d7cfe", "#31d0a5", "#f5b73d", "#8a6cff", "#f2585f", "#4dd2ff", "#ff79c6", "#50fa7b"];
function renderModelList() {
  const host = $("modelList");
  if (!host) return;
  host.innerHTML = "";
  if (!loadedModels.length) {
    host.innerHTML = '<div class="hint" style="padding:4px 0">No models loaded.</div>';
    return;
  }
  loadedModels.forEach((mItem, idx) => {
    const row = document.createElement("div");
    row.className = "mrow";
    const col = MODEL_COLORS[idx % MODEL_COLORS.length];
    
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = (mItem.model && mItem.model.object) ? mItem.model.object.visible : true;
    cb.title = "Hide / unhide this model";
    cb.onchange = () => {
      if (mItem.model && mItem.model.object) {
        mItem.model.object.visible = cb.checked;
      }
    };

    const dot = document.createElement("span");
    dot.className = "mdot";
    dot.style.background = col;

    const nm = document.createElement("span");
    nm.className = "mname";
    nm.textContent = mItem.name;
    nm.title = mItem.rel;

    const btnDel = document.createElement("button");
    btnDel.innerHTML = "&times;";
    btnDel.title = "Remove model from scene";
    btnDel.style.cssText = "background:none;border:none;color:var(--muted);cursor:pointer;font-size:15px;line-height:1;padding:0 4px";
    btnDel.onmouseover = () => { btnDel.style.color = "var(--red)"; };
    btnDel.onmouseout = () => { btnDel.style.color = "var(--muted)"; };
    btnDel.onclick = (e) => {
      e.stopPropagation();
      if (mItem.model && mItem.model.object) {
        root.remove(mItem.model.object);
      }
      loadedModels = loadedModels.filter(m => m.rel !== mItem.rel);
      if (activeModel === mItem.model) {
        activeModel = loadedModels.length ? loadedModels[0].model : null;
      }
      renderModelList();
      buildSpatialTree();
      renderCatList();
    };

    row.appendChild(cb);
    row.appendChild(dot);
    row.appendChild(nm);
    row.appendChild(btnDel);
    host.appendChild(row);
  });
}

function wireAddModel() {
  const btnAdd = $("btnAddModel");
  const modal = $("addModelModal");
  const closeBtn = $("closeAddModel");
  const listEl = $("projectModelsList");
  const localInput = $("localIfcInput");

  if (!btnAdd || !modal) return;

  if (closeBtn) closeBtn.onclick = () => { modal.style.display = "none"; };

  btnAdd.onclick = async () => {
    const isShowing = modal.style.display === "flex";
    if (isShowing) { modal.style.display = "none"; return; }
    modal.style.display = "flex";
    listEl.innerHTML = '<div class="hint">Scanning project models...</div>';
    try {
      const res = await fetch(`/projects/${encodeURIComponent(project)}/documents`);
      if (!res.ok) throw new Error("Could not fetch documents");
      const docs = await res.json();
      const modelDocs = docs.filter(d => {
        const fn = (d.filename || '').toLowerCase();
        return d.category === "3D Models" || fn.endsWith(".ifc") || fn.endsWith(".frag");
      });
      if (!modelDocs.length) {
        listEl.innerHTML = '<div class="hint">No other 3D models found in this project.</div>';
        return;
      }
      listEl.innerHTML = "";
      modelDocs.forEach(doc => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;justify-content:space-between;align-items:center;padding:5px 7px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;font-size:11.5px;cursor:pointer";
        const isLoaded = loadedModels.some(m => m.rel === doc.rel || m.name === doc.filename);
        row.innerHTML = `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1" title="${doc.rel}">${doc.filename}</span>` +
          `<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:${isLoaded ? 'rgba(49,208,165,.2)' : 'var(--accent)'};color:${isLoaded ? '#31d0a5' : '#fff'}">${isLoaded ? 'Loaded' : '+ Add'}</span>`;
        if (!isLoaded) {
          row.onclick = async () => {
            modal.style.display = "none";
            await loadModel(doc.rel);
          };
        }
        listEl.appendChild(row);
      });
    } catch(e) {
      listEl.innerHTML = `<div class="hint">Error: ${e.message}</div>`;
    }
  };

  if (localInput) {
    localInput.onchange = async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      modal.style.display = "none";
      try {
        setLoading(`Loading ${file.name}...`);
        const buffer = new Uint8Array(await file.arrayBuffer());
        const localModel = await fragments.load(buffer, { modelId: file.name });
        root.add(localModel.object);
        loadedModels.push({ rel: file.name, model: localModel, name: file.name });
        activeModel = localModel;
        renderModelList();
        buildSpatialTree();
        fit();
      } catch(err) {
        alert("Failed to load local model: " + err.message);
      } finally {
        setLoading(null);
      }
    };
  }
}

async function initEngine() {
  logDiag("Initializing Fragments Engine...");
  try {
    const workerUrl = new URL("./vendor_fragments/fragments/Worker/worker.mjs", location.href).toString();
    fragments = new FRAGS.FragmentsModels(workerUrl);
    // Point the components-side FragmentsManager at the SAME FragmentsModels
    // core this app drives directly, so FastModelPicker (which reads models
    // through OBC.FragmentsManager.list -> core.models.list) sees every model
    // this app loads, without a second worker/core being created. There is no
    // public API for adopting an externally-created core -- FragmentsManager's
    // own init() always does `new FragmentsModels(...)` itself -- so this
    // relies on `_core` being a TS-private field with no runtime enforcement,
    // whose name is preserved unmangled in this build (confirmed by reading
    // components.min.mjs directly). fragments.models.list is populated by the
    // core itself as models load, so no separate per-model registration step
    // is needed here.
    fragmentsManagerOBC._core = fragments;
  } catch (e) {
    logDiag("Error initializing FragmentsModels: " + e.message, true);
  }
}

// A dense/unusual model (e.g. a tessellated-mesh-heavy IFC with millions of
// raw faces, rather than parametric solids) can make the Fragments worker
// stall indefinitely on fragments.load()/importer.convert() with no error
// and no progress -- confirmed live 2026-10-09 against a 592MB .ifc whose
// 23.5MB .frag never finished loading after 8+ minutes, silently, with the
// existing try/catch never firing because the underlying promise simply
// never settled (a crashed/stuck worker doesn't always reject). Wrapping
// the two long-running steps in a timeout turns that silent, indefinite
// hang into a visible error the user can act on instead of waiting forever
// with no feedback.
const MODEL_LOAD_TIMEOUT_MS = 180000; // 3 minutes
function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(
      `${label} timed out after ${Math.round(ms / 1000)}s. This usually means the model's ` +
      `geometry is unusually dense (millions of raw mesh faces instead of parametric solids) ` +
      `and overwhelmed the in-browser geometry processor. Try re-exporting this model with ` +
      `simplified/parametric geometry, or splitting it into smaller files.`
    )), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function loadModel(rel) {
  setLoading("Reading " + rel.split("/").pop() + " ...");
  logDiag("Starting to load model: " + rel);
  // diagOverlay.style.display = 'block'; 
  
  try {
    let fragBytes;
    const fragUrl = fileURL(rel + ".frag");
    let fragRes = await fetch(fragUrl);

    if (!fragRes.ok) {
      // Every uploaded IFC should get a .frag sibling generated server-side at upload time;
      // a missing one here means that never ran (or failed silently) for this file. Ask the
      // server to convert it now, with its full Node toolchain, rather than falling back to
      // parsing the raw IFC in-browser -- the vendored @thatopen/fragments build's
      // IfcImporter has no setup()/convert() methods (confirmed 2026-10-09), so that fallback
      // always threw "importer.setup is not a function" instead of loading anything.
      logDiag("No pre-converted .frag found. Asking the server to convert this model now (this can take a while for large files)...");
      setLoading("Converting " + rel.split("/").pop() + " for 3D viewing (first time only)…");
      const ensureUrl = `${location.origin}/projects/${encodeURIComponent(project)}/ensure-frag?rel=${encodeURIComponent(rel)}&token=${encodeURIComponent(token)}`;
      let ensureOk = false;
      try {
        const ensureRes = await withTimeout(fetch(ensureUrl), MODEL_LOAD_TIMEOUT_MS, "Server-side .frag conversion");
        ensureOk = ensureRes.ok;
        if (!ensureOk) {
          let detail = "";
          try { detail = (await ensureRes.json()).detail || ""; } catch(e) {}
          logDiag(`Server-side conversion failed (${ensureRes.status}): ${detail}`, true);
        }
      } catch (e) {
        logDiag("Server-side conversion request failed: " + e, true);
      }
      if (ensureOk) {
        fragRes = await fetch(fragUrl);
      }
      if (!ensureOk || !fragRes.ok) {
        throw new Error(
          "This model hasn't been converted for 3D viewing yet, and automatic conversion " +
          "did not produce a usable file. Ask an administrator to check the server's IFC " +
          "diagnostics for " + rel + ", or re-upload the file."
        );
      }
    }

    logDiag("Found pre-converted .frag file! Downloading...");
    fragBytes = new Uint8Array(await fragRes.arrayBuffer());

    logDiag("Loading .frag into FragmentsModels...");
    activeModel = await withTimeout(fragments.load(fragBytes, { modelId: rel }), MODEL_LOAD_TIMEOUT_MS, "Loading .frag into the viewer");
    if(activeModel.getClippingPlanesEvent) activeModel.getClippingPlanesEvent = () => renderer.clippingPlanes;
    await fragments.update(true);
    
    root.add(activeModel.object);

    // modelBox tracks the UNION of every loaded model so bounds/camera/clipping
    // span all of them, not just whichever model was loaded most recently.
    // Auto-centering only ever runs for the FIRST model loaded: it translates
    // the shared `root` group itself (not this model's own object), which
    // establishes one coordinate frame that every model added to `root`
    // afterwards automatically inherits. Centering each model's own object
    // independently (the old behavior) would move every far-from-origin model
    // to its OWN center at (0,0,0), stacking separately-positioned models on
    // top of one another instead of preserving their real-world relative
    // offsets (most multi-building/multi-discipline IFC exports already share
    // one real-world coordinate system from the authoring tool).
    if (!modelBox) {
      const firstBox = new THREE.Box3().setFromObject(activeModel.object);
      const firstCenter = firstBox.getCenter(new THREE.Vector3());
      if (firstCenter.length() > 5000) {
        logDiag("Model is extremely far from origin. Auto-centering the shared scene...");
        root.position.copy(firstCenter).negate();
        root.updateMatrixWorld(true);
      }
      modelBox = new THREE.Box3().setFromObject(activeModel.object);
    } else {
      modelBox.union(new THREE.Box3().setFromObject(activeModel.object));
    }

    const mName = rel.split("/").pop();
    const existingIdx = loadedModels.findIndex(m => m.rel === rel);
    if (existingIdx >= 0) {
      loadedModels[existingIdx] = { rel, model: activeModel, name: mName };
    } else {
      loadedModels.push({ rel, model: activeModel, name: mName });
    }
    try { renderModelList(); } catch(e){}

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

    const badgeClass = (cat) => {
      const c = (cat || '').toUpperCase();
      if(c.includes('PROJECT')) return 'tb-proj';
      if(c.includes('SITE')) return 'tb-site';
      if(c.includes('BUILDING') && !c.includes('STOREY')) return 'tb-bldg';
      if(c.includes('STOREY')) return 'tb-storey';
      return 'tb-node';
    };

    function traverse(node, depth=0) {
      if(!node) return "";
      const cat = (node.category || 'Node').toUpperCase();
      const hasChildren = node.children && node.children.length > 0;
      
      if (cat === 'IFCBUILDINGSTOREY') {
         storeys.push(node);
         if(sel) {
            const opt = document.createElement('option');
            opt.value = node.localId;
            opt.textContent = "Storey " + (node.localId || "");
            sel.appendChild(opt);
         }
      }

      const indent = depth * 10;
      const bClass = badgeClass(cat);
      const shortCat = cat.replace(/^IFC/, '');
      const labelText = node.name || (node.localId ? `Element #${node.localId}` : shortCat);
      const isHighLevel = depth <= 3 || cat.includes('PROJECT') || cat.includes('SITE') || (cat.includes('BUILDING') && !cat.includes('STOREY')) || cat.includes('STOREY');
      const shouldCollapse = !isHighLevel;

      let html = `<div class="tree-node" style="margin-left:${indent}px" data-node-id="${node.localId || ''}" data-depth="${depth}">`;
      html += `<div class="trow" data-local-id="${node.localId || ''}">`;
      
      if (hasChildren) {
        html += `<span class="tcaret ${shouldCollapse ? 'closed' : ''}" onclick="window._toggleTreeNode(this, event)">▼</span>`;
      } else {
        html += `<span style="width:14px;display:inline-block"></span>`;
      }

      html += `<span class="tbadge ${bClass}">${shortCat}</span>`;
      html += `<span class="tlabel" title="${cat}${node.localId ? ' (ID: ' + node.localId + ')' : ''}">${labelText}</span>`;
      if(node.localId) {
        html += `<span class="tcount">#${node.localId}</span>`;
      }
      html += `</div>`;

      if(hasChildren) {
        html += `<div class="tree-children" style="display:${shouldCollapse ? 'none' : 'block'}">`;
        for(const child of node.children) { html += traverse(child, depth+1); }
        html += `</div>`;
      }
      html += `</div>`;
      return html;
    }

    treeEl.innerHTML = traverse(spatial);

    // Click handler for selection + properties panel synchronization
    treeEl.querySelectorAll('.trow').forEach(row => {
      row.addEventListener('click', async (e) => {
        if(e.target.classList.contains('tcaret')) return;
        treeEl.querySelectorAll('.trow').forEach(r => r.classList.remove('on'));
        row.classList.add('on');
        const lid = row.dataset.localId;
        if(lid && activeModel) {
          const numId = parseInt(lid);
          window._highlightNode(numId);
          window._lastSelId = numId;
          await displayElementProperties(activeModel, numId);
        }
      });
    });

    // Expand / Collapse all controls
    const btnExp = $('btnTreeExpandAll');
    if (btnExp) {
      btnExp.onclick = () => {
        treeEl.querySelectorAll('.tree-children').forEach(c => c.style.display = 'block');
        treeEl.querySelectorAll('.tcaret').forEach(c => c.classList.remove('closed'));
      };
    }
    const btnCol = $('btnTreeCollapseAll');
    if (btnCol) {
      btnCol.onclick = () => {
        treeEl.querySelectorAll('.tree-node').forEach(node => {
          const depth = parseInt(node.dataset.depth || '0');
          if (depth >= 2) {
            const children = node.querySelector(':scope > .tree-children');
            const caret = node.querySelector(':scope > .trow > .tcaret');
            if (children) children.style.display = 'none';
            if (caret) caret.classList.add('closed');
          }
        });
      };
    }

    // Search filter across spatial tree, categories, and models
    const treeSearchInput = $('treeSearch');
    if (treeSearchInput && !treeSearchInput._wired) {
      treeSearchInput._wired = true;
      treeSearchInput.addEventListener('input', () => {
        const q = (treeSearchInput.value || '').trim().toLowerCase();
        if (!q) {
          treeEl.querySelectorAll('.tree-node').forEach(node => {
            node.style.display = '';
            const depth = parseInt(node.dataset.depth || '0');
            const isHighLevel = depth <= 3;
            const children = node.querySelector(':scope > .tree-children');
            const caret = node.querySelector(':scope > .trow > .tcaret');
            if (children) children.style.display = isHighLevel ? 'block' : 'none';
            if (caret) caret.classList.toggle('closed', !isHighLevel);
          });
        } else {
          treeEl.querySelectorAll('.tree-node').forEach(node => {
            const row = node.querySelector(':scope > .trow');
            const text = (row ? row.textContent : '').toLowerCase();
            const match = text.includes(q);
            if (match) {
              node.style.display = '';
              let p = node.parentElement;
              while (p && p !== treeEl) {
                if (p.classList.contains('tree-children')) {
                  p.style.display = 'block';
                  const parentNode = p.closest('.tree-node');
                  if (parentNode) {
                    parentNode.style.display = '';
                    const caret = parentNode.querySelector(':scope > .trow > .tcaret');
                    if (caret) caret.classList.remove('closed');
                  }
                }
                p = p.parentElement;
              }
            } else {
              const hasMatchingDescendant = !!node.querySelector('.tree-node');
              if (!hasMatchingDescendant) {
                node.style.display = 'none';
              }
            }
          });
        }

        const catEl = $('catList');
        if (catEl) {
          catEl.querySelectorAll('.trow, .catrow').forEach(r => {
            r.style.display = (!q || r.textContent.toLowerCase().includes(q)) ? '' : 'none';
          });
        }
        const modelList = $('modelList');
        if (modelList) {
          modelList.querySelectorAll('.mrow').forEach(r => {
            r.style.display = (!q || r.textContent.toLowerCase().includes(q)) ? '' : 'none';
          });
        }
      });
    }

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

window._toggleTreeNode = (caret, event) => {
  event.stopPropagation();
  const parentNode = caret.closest('.tree-node');
  if(!parentNode) return;
  const children = parentNode.querySelector('.tree-children');
  if(!children) return;
  const isClosed = caret.classList.toggle('closed');
  children.style.display = isClosed ? 'none' : 'block';
};

async function renderCatList() {
  const catEl = $("catList");
  if(!catEl || !activeModel) return;
  try {
    const cats = await activeModel.getCategories();
    catEl.innerHTML = cats.map(c => `<div class="trow"><span>${c}</span></div>`).join("");
  } catch(e) {}
}

// ---- Property Extraction & Inspector ----
function extractVal(v) {
  if (v == null) return null;
  if (typeof v === "object") {
    if ("value" in v) return extractVal(v.value);
    if (Array.isArray(v)) {
      const arr = v.map(extractVal).filter(x => x !== null && x !== undefined && x !== "");
      return arr.length ? arr.join(", ") : null;
    }
    const entries = Object.entries(v)
      .filter(([subK]) => !subK.startsWith("_"))
      .map(([subK, subV]) => `${subK}: ${extractVal(subV)}`)
      .filter(s => !s.endsWith("null") && !s.endsWith("undefined") && !s.endsWith(": "));
    return entries.length ? entries.join("; ") : null;
  }
  return String(v);
}

async function displayElementProperties(pickedModel, localId) {
  const propBox = $('propBox');
  if (!propBox || !pickedModel) return;
  propBox.innerHTML = '<div class="hint">Loading properties...</div>';
  try {
    const dataArr = await pickedModel.getItemsData([localId], {
      attributesDefault: true,
      relations: {
        IsDefinedBy: { attributes: true, relations: true },
        DefinesOccurrence: { attributes: true, relations: false }
      }
    });
    if (!dataArr || !dataArr.length) {
      propBox.innerHTML = `<div class="sec">Element #${localId}</div><div class="hint">No attributes available.</div>`;
      return;
    }
    const data = dataArr[0];
    const cat = extractVal(data._category || data.category || data.ObjectType) || "Element";
    const name = extractVal(data.Name || data.name) || "";
    const gid = extractVal(data._guid || data.GlobalId || data.guid) || "";
    const objType = extractVal(data.ObjectType || data.objectType) || "";

    let html = `<div class="sec">Selected Element</div>`;
    html += `<div class="prop"><b>Category</b><span>${cat}</span></div>`;
    if (name) html += `<div class="prop"><b>Name</b><span>${name}</span></div>`;
    if (objType && objType !== name) html += `<div class="prop"><b>Type</b><span>${objType}</span></div>`;
    if (gid) html += `<div class="prop"><b>GlobalId</b><span style="font-family:monospace;font-size:10.5px;word-break:break-all">${gid}</span></div>`;
    html += `<div class="prop"><b>Local ID</b><span>#${localId}</span></div>`;

    // Built-in Attributes
    const skipKeys = new Set(["_category", "_localId", "_guid", "category", "Name", "name", "GlobalId", "guid", "ObjectType", "objectType", "IsDefinedBy", "DefinesOccurrence"]);
    let attrHtml = "";
    for (const [k, v] of Object.entries(data)) {
      if (skipKeys.has(k) || Array.isArray(v)) continue;
      const val = extractVal(v);
      if (val !== null && val !== undefined && val !== "" && val !== "null") {
        const label = k.replace(/^_+/, '');
        attrHtml += `<div class="prop"><b>${label}</b><span>${val}</span></div>`;
      }
    }
    if (attrHtml) {
      html += `<div class="sec" style="margin-top:12px">Attributes</div>` + attrHtml;
    }

    // Property Sets from IsDefinedBy
    if (data.IsDefinedBy && Array.isArray(data.IsDefinedBy)) {
      let psetsHtml = "";
      for (const pset of data.IsDefinedBy) {
        if (!pset || typeof pset !== "object") continue;
        const psetName = extractVal(pset.Name || pset.name || pset._category) || "Property Set";
        let rowsHtml = "";
        for (const [pk, pv] of Object.entries(pset)) {
          if (pk.startsWith("_") || pk === "Name" || pk === "name" || pk === "HasProperties") continue;
          const pval = extractVal(pv);
          if (pval !== null && pval !== undefined && pval !== "") {
            rowsHtml += `<div class="pr" style="display:flex;justify-content:space-between;gap:8px;font-size:11.5px;padding:2px 0"><span style="color:var(--muted)">${pk}</span><span style="text-align:right">${pval}</span></div>`;
          }
        }
        if (rowsHtml) {
          psetsHtml += `<div class="prop" style="margin-top:8px;margin-bottom:2px"><b>${psetName}</b></div>` + rowsHtml;
        }
      }
      if (psetsHtml) {
        html += `<div class="sec" style="margin-top:12px">Property Sets &amp; Quantities</div>` + psetsHtml;
      }
    }

    propBox.innerHTML = html;
  } catch(err) {
    propBox.innerHTML = `<div class="sec">Element #${localId}</div><div class="hint">Attributes unavailable: ${err.message || err}</div>`;
  }
}

// ---- Full Measurement Suite (Length, Area, Spot Elevation / Point, Angle) ----
const measSettings = { unit: "m", unit2: "none", precision: 3, free: false }; // free: false means Snap is ON by default
const UNIT_DEFS = {
  mm: { factor: 1000, suffix: "mm" },
  cm: { factor: 100, suffix: "cm" },
  m: { factor: 1, suffix: "m" },
  in: { factor: 39.3701, suffix: "in" },
  ft: { factor: 3.28084, suffix: "ft" },
  ftdec: { factor: 3.28084, suffix: "ft" }
};

function sceneScale() {
  if (modelBox) {
    const sz = modelBox.getSize(new THREE.Vector3());
    return Math.max(0.08, Math.max(sz.x, sz.y, sz.z) / 450);
  }
  return 0.08;
}

function fmtLen(meters) {
  const u = UNIT_DEFS[measSettings.unit] || UNIT_DEFS.m;
  let out = (meters * u.factor).toFixed(measSettings.precision) + " " + u.suffix;
  if (measSettings.unit2 !== "none" && measSettings.unit2 !== measSettings.unit) {
    const u2 = UNIT_DEFS[measSettings.unit2] || UNIT_DEFS.mm;
    out += " (" + (meters * u2.factor).toFixed(measSettings.precision) + " " + u2.suffix + ")";
  }
  return out;
}

function fmtArea(sqMeters) {
  const u = UNIT_DEFS[measSettings.unit] || UNIT_DEFS.m;
  const f = u.factor * u.factor;
  let out = (sqMeters * f).toFixed(measSettings.precision) + " " + u.suffix + "²";
  if (measSettings.unit2 !== "none" && measSettings.unit2 !== measSettings.unit) {
    const u2 = UNIT_DEFS[measSettings.unit2] || UNIT_DEFS.mm;
    out += " (" + (sqMeters * u2.factor * u2.factor).toFixed(measSettings.precision) + " " + u2.suffix + "²)";
  }
  return out;
}

function fmtCoord(val) {
  const u = UNIT_DEFS[measSettings.unit] || UNIT_DEFS.m;
  return (val * u.factor).toFixed(measSettings.precision) + " " + u.suffix;
}

function polyArea(pts) {
  const n = new THREE.Vector3();
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    n.x += (a.y - b.y) * (a.z + b.z);
    n.y += (a.z - b.z) * (a.x + b.x);
    n.z += (a.x - b.x) * (a.y + b.y);
  }
  return n.length() / 2;
}

// Snap a clicked point to the nearest geometry vertex or edge across loaded meshes
function snapToNearestVertex(p, maxDistWorld) {
  // Use a tight, precise snap radius around the clicked point
  const tol = maxDistWorld || Math.min(1.5, Math.max(0.25, sceneScale() * 1.5));
  let best = null, bestD = tol;
  const v = new THREE.Vector3();
  const instM = new THREE.Matrix4();
  
  try {
    secAllMeshes(mesh => {
      if (!mesh || !mesh.visible || !mesh.geometry) return;
      const posAttr = mesh.geometry.attributes && mesh.geometry.attributes.position;
      if (!posAttr || !posAttr.array || posAttr.count === 0) return;
      
      const count = posAttr.count;
      const isInstanced = mesh.isInstancedMesh && mesh.count > 0;
      const instancesToCheck = isInstanced ? Math.min(mesh.count, 64) : 1;
      
      for (let inst = 0; inst < instancesToCheck; inst++) {
        let mWorld = mesh.matrixWorld;
        if (isInstanced) {
          mesh.getMatrixAt(inst, instM);
          mWorld = instM.clone().premultiply(mesh.matrixWorld);
        }
        
        const step = count > 5000 ? Math.ceil(count / 5000) : 1;
        for (let i = 0; i < count; i += step) {
          if (i * posAttr.itemSize + 2 >= posAttr.array.length) break;
          v.fromBufferAttribute(posAttr, i).applyMatrix4(mWorld);
          const d = v.distanceTo(p);
          if (d < bestD) {
            bestD = d;
            best = v.clone();
          }
        }
      }
    });
  } catch(e) {
    console.warn("Snap calculation notice:", e);
  }
  
  return best || p;
}

let measMode = null;
let measPts = [];
let measObjs = [];
let measLabels = [];

function clearMeasure() {
  measObjs.forEach(o => scene.remove(o));
  measObjs = [];
  measPts = [];
  measLabels.forEach(l => l.remove());
  measLabels = [];
  const out = $('measureOut');
  if (out) out.textContent = "—";
}

function measDot(pt, col = 0xf5b73d) {
  const r = Math.max(0.012, sceneScale() * 0.45);
  const geom = new THREE.SphereGeometry(r, 16, 16);
  const mat = new THREE.MeshBasicMaterial({ color: col, depthTest: false });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.renderOrder = 2000;
  mesh.position.copy(pt);
  scene.add(mesh);
  measObjs.push(mesh);
  return mesh;
}

function measLine(a, b, col = 0xf5b73d) {
  const geom = new THREE.BufferGeometry().setFromPoints([a, b]);
  const mat = new THREE.LineBasicMaterial({ color: col, depthTest: false, linewidth: 2 });
  const l = new THREE.Line(geom, mat);
  l.renderOrder = 2000;
  scene.add(l);
  measObjs.push(l);
  return l;
}

function addDimensionTag(a, b, text) {
  const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
  const div = document.createElement("div");
  div.className = "mDimTag";
  div.textContent = text;
  const view = $('view');
  if (view) view.appendChild(div);
  measLabels.push(div);

  function updatePos() {
    if (!div.parentNode) return;
    const v = mid.clone().project(camera);
    if (v.z > 1) {
      div.style.display = "none";
    } else {
      div.style.display = "block";
      const w = view.clientWidth, h = view.clientHeight;
      div.style.left = ((v.x * 0.5 + 0.5) * w) + "px";
      div.style.top = ((-(v.y * 0.5 - 0.5) * h)) + "px";
    }
  }
  updatePos();
  div._updatePos = updatePos;
  return div;
}

function addSpotElevationLabel(pt) {
  const div = document.createElement("div");
  div.className = "mLabel";
  div.innerHTML = `<b>Spot Elevation:</b> ${fmtCoord(pt.y)}<br><span style="color:var(--muted)">X: ${fmtCoord(pt.x)} | Z: ${fmtCoord(pt.z)}</span>`;
  const view = $('view');
  if (view) view.appendChild(div);
  measLabels.push(div);
  
  function updatePos() {
    if (!div.parentNode) return;
    const v = pt.clone().project(camera);
    if (v.z > 1) {
      div.style.display = "none";
    } else {
      div.style.display = "block";
      const w = view.clientWidth, h = view.clientHeight;
      div.style.left = ((v.x * 0.5 + 0.5) * w + 10) + "px";
      div.style.top = ((-(v.y * 0.5 - 0.5) * h) - 10) + "px";
    }
  }
  updatePos();
  div._updatePos = updatePos;
}

function updateMeasureLabels() {
  measLabels.forEach(l => { if (l._updatePos) l._updatePos(); });
}

function handleMeasureClick(rawPt) {
  let pt = rawPt.clone();
  if (!measSettings.free) {
    pt = snapToNearestVertex(pt);
  }
  measPts.push(pt.clone());
  measDot(pt, measMode === "point" ? 0x4d7cfe : 0xf5b73d);

  if (measMode === "len") {
    if (measPts.length >= 2) {
      const a = measPts[0], b = measPts[1];
      measLine(a, b, 0xf5b73d);
      const d = a.distanceTo(b);
      const formatted = fmtLen(d);
      addDimensionTag(a, b, formatted);
      const out = $('measureOut');
      if (out) out.textContent = "Length: " + formatted;
      measPts = []; // Ready for next pair of points
    }
  } else if (measMode === "area") {
    if (measPts.length >= 2) {
      measLine(measPts[measPts.length - 2], measPts[measPts.length - 1], 0x31d0a5);
    }
    if (measPts.length >= 3) {
      const area = polyArea(measPts);
      const out = $('measureOut');
      if (out) out.textContent = "Area: " + fmtArea(area) + " (" + measPts.length + " pts)";
    }
  } else if (measMode === "point") {
    addSpotElevationLabel(pt);
    const out = $('measureOut');
    if (out) out.textContent = `Spot Elevation: ${fmtCoord(pt.y)} | X: ${fmtCoord(pt.x)} · Z: ${fmtCoord(pt.z)}`;
  } else if (measMode === "angle") {
    if (measPts.length >= 2) {
      measLine(measPts[measPts.length - 2], measPts[measPts.length - 1], 0x31d0a5);
    }
    if (measPts.length >= 3) {
      const a = measPts[0], vtx = measPts[1], b = measPts[2];
      const v1 = new THREE.Vector3().subVectors(a, vtx), v2 = new THREE.Vector3().subVectors(b, vtx);
      const deg = (v1.angleTo(v2) * 180 / Math.PI).toFixed(measSettings.precision);
      addDimensionTag(a, b, `${deg}°`);
      const out = $('measureOut');
      if (out) out.textContent = `Angle: ${deg}°`;
      measPts = [];
    }
  }
}

function syncSnapButtons() {
  const isSnap = !measSettings.free;
  if ($('btnSnapToggle')) $('btnSnapToggle').classList.toggle('on', isSnap);
  if ($('measFree')) $('measFree').checked = measSettings.free;
}

function setMeasureMode(mode) {
  measMode = measMode === mode ? null : mode;
  measPts = [];
  [['btnLen', 'len'], ['btnArea', 'area'], ['btnPoint', 'point'], ['btnAngle', 'angle']].forEach(([id, m]) => {
    const b = $(id);
    if (b) b.classList.toggle('on', measMode === m);
  });
  const hints = {
    len: "Click two points to measure distance (shows live 3D tag)",
    area: "Click 3 or more points to measure surface area",
    point: "Click a point to read spot elevation and coordinates",
    angle: "Click 3 points (start, vertex, end) to measure angle"
  };
  const reticle = $('snapReticle');
  if (reticle && !measMode) reticle.style.display = 'none';
}

// Feature 1: Real-Time Magnetic Hover Snapping Reticle
let _snapHoverThrottle = 0;
viewEl.addEventListener('pointermove', (e) => {
  const reticle = $('snapReticle');
  if (!reticle) return;
  if (!measMode || measSettings.free || !activeModel) {
    reticle.style.display = 'none';
    return;
  }
  const now = performance.now();
  if (now - _snapHoverThrottle < 25) return; // 40fps smooth throttle
  _snapHoverThrottle = now;

  const ndc = secPointerToNDC(e);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(ndc, camera);
  const meshes = [];
  secAllMeshes(m => { if (m.visible) meshes.push(m); });
  const hits = ray.intersectObjects(meshes, true);

  if (hits.length > 0 && hits[0].face) {
    const hitPt = hits[0].point;
    const face = hits[0].face;
    const geom = hits[0].object.geometry;
    const matWorld = hits[0].object.matrixWorld;
    if (geom && geom.attributes && geom.attributes.position) {
      const pos = geom.attributes.position;
      const vA = new THREE.Vector3().fromBufferAttribute(pos, face.a).applyMatrix4(matWorld);
      const vB = new THREE.Vector3().fromBufferAttribute(pos, face.b).applyMatrix4(matWorld);
      const vC = new THREE.Vector3().fromBufferAttribute(pos, face.c).applyMatrix4(matWorld);

      let target = vA;
      let minD = hitPt.distanceTo(vA);
      const dB = hitPt.distanceTo(vB);
      if (dB < minD) { target = vB; minD = dB; }
      const dC = hitPt.distanceTo(vC);
      if (dC < minD) { target = vC; minD = dC; }

      // Project vertex to 2D screen space
      const screenV = target.clone().project(camera);
      if (screenV.z <= 1) {
        const w = viewEl.clientWidth, h = viewEl.clientHeight;
        const x = (screenV.x * 0.5 + 0.5) * w;
        const y = (-(screenV.y * 0.5 - 0.5) * h);
        reticle.style.left = x + 'px';
        reticle.style.top = y + 'px';
        reticle.style.display = 'block';
        return;
      }
    }
  }
  reticle.style.display = 'none';
});

if ($('btnLen')) $('btnLen').onclick = (e) => { e.stopPropagation(); setMeasureMode('len'); };
if ($('btnArea')) $('btnArea').onclick = (e) => { e.stopPropagation(); setMeasureMode('area'); };
if ($('btnPoint')) $('btnPoint').onclick = (e) => { e.stopPropagation(); setMeasureMode('point'); };
if ($('btnAngle')) $('btnAngle').onclick = (e) => { e.stopPropagation(); setMeasureMode('angle'); };
if ($('btnSnapToggle')) $('btnSnapToggle').onclick = (e) => {
  e.stopPropagation();
  measSettings.free = !measSettings.free;
  syncSnapButtons();
  logDiag(measSettings.free ? "Snap disabled (free measurement)" : "Snap enabled (snapping to vertices)");
};
if ($('btnMclr')) $('btnMclr').onclick = (e) => { e.stopPropagation(); clearMeasure(); };
if ($('btnMeasureDone')) $('btnMeasureDone').onclick = (e) => {
  e.stopPropagation();
  setMeasureMode(null);
  const dock = $('measureDock'); if (dock) dock.classList.remove('open');
  const btn = $('btnMeasureTool'); if (btn) btn.classList.remove('on');
};
if ($('btnMeasureTool')) $('btnMeasureTool').onclick = (e) => {
  e.stopPropagation();
  const dock = $('measureDock'); if (!dock) return;
  const open = !dock.classList.contains('open');
  dock.classList.toggle('open', open);
  $('btnMeasureTool').classList.toggle('on', open);
  if (!open) setMeasureMode(null);
  else syncSnapButtons();
};
const mDockEl = $('measureDock');
if (mDockEl) mDockEl.addEventListener('click', (e) => e.stopPropagation());
if ($('btnMeasureSettings')) $('btnMeasureSettings').onclick = (e) => {
  e.stopPropagation();
  const p = $('measureSettingsPanel'); if (p) p.classList.toggle('open');
};
if ($('measSetClose')) $('measSetClose').onclick = (e) => {
  e.stopPropagation();
  const p = $('measureSettingsPanel'); if (p) p.classList.remove('open');
};
if ($('measFree')) $('measFree').onchange = (e) => {
  measSettings.free = e.target.checked;
  syncSnapButtons();
};
if ($('measUnit')) $('measUnit').onchange = (e) => { measSettings.unit = e.target.value; };
if ($('measUnit2')) $('measUnit2').onchange = (e) => { measSettings.unit2 = e.target.value; };
if ($('measPrecision')) $('measPrecision').onchange = (e) => { measSettings.precision = parseInt(e.target.value, 10); };

viewEl.addEventListener('click', async (event) => {
    if (!activeModel) return;
    if (_isDraggingPointer) return;
    if (_pointerDownPos) {
        const dist = Math.hypot(event.clientX - _pointerDownPos.x, event.clientY - _pointerDownPos.y);
        if (dist > 5) return;
    }

    const ndc = secPointerToNDC(event);
    let pick = null;
    try { pick = await picker.getFullPick(ndc); } catch(e) { pick = null; }

    // Accurate raycast for picking and measurement
    let hitPoint = pick && pick.point ? pick.point.clone() : null;
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(ndc, camera);
    const meshes = [];
    secAllMeshes(m => { if (m.visible) meshes.push(m); });
    const intersects = raycaster.intersectObjects(meshes, true);
    if (intersects.length > 0) {
      hitPoint = intersects[0].point.clone();
      // If snapping is enabled, snap directly to the exact triangle vertices of the clicked face
      if (measMode && !measSettings.free && intersects[0].face) {
        const face = intersects[0].face;
        const geom = intersects[0].object.geometry;
        const matWorld = intersects[0].object.matrixWorld;
        if (geom && geom.attributes && geom.attributes.position) {
          const pos = geom.attributes.position;
          const vA = new THREE.Vector3().fromBufferAttribute(pos, face.a).applyMatrix4(matWorld);
          const vB = new THREE.Vector3().fromBufferAttribute(pos, face.b).applyMatrix4(matWorld);
          const vC = new THREE.Vector3().fromBufferAttribute(pos, face.c).applyMatrix4(matWorld);
          
          let closest = vA;
          let minD = hitPoint.distanceTo(vA);
          const dB = hitPoint.distanceTo(vB);
          if (dB < minD) { closest = vB; minD = dB; }
          const dC = hitPoint.distanceTo(vC);
          if (dC < minD) { closest = vC; minD = dC; }
          
          // Snap if within reasonable distance to face corner
          if (minD < 2.0) hitPoint = closest;
        }
      }
    }

    // Measurement intercept
    if (measMode && hitPoint) {
        handleMeasureClick(hitPoint);
        return;
    }

    let localId = pick ? pick.localId : null;
    let pickedModel = (pick && fragments && fragments.models && fragments.models.list.get(pick.modelId)) || activeModel;

    if (!hitPoint && localId === null) {
        window._lastSelId = null;
        if (activeModel && activeModel.resetColor) {
            try { activeModel.resetColor(); } catch(e){}
        }
        const propBox = $('propBox');
        if (propBox) propBox.innerHTML = '<div class="hint">Select an element to see properties.</div>';
        return;
    }

    if (localId !== null && localId !== undefined) {
      window._lastSelId = localId;
      if (pickedModel.setColor) {
          try { pickedModel.resetColor(); } catch(e){}
          try { pickedModel.setColor([localId], new THREE.Color(0x4d7cfe)); } catch(e) {}
      }
      await displayElementProperties(pickedModel, localId);
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

const btnToggleGrid = $('btnToggleGrid');
if (btnToggleGrid) {
  btnToggleGrid.onclick = () => {
    grid.visible = !grid.visible;
    btnToggleGrid.classList.toggle('on', grid.visible);
  };
}

const viewModeSel = $('viewModeSel');
if (viewModeSel) {
  viewModeSel.onchange = async () => {
    const val = viewModeSel.value;
    if (val === "3d") {
      if (sec2DActive) sec2DExit();
      if ($('btnPersp')) $('btnPersp').click();
      fit();
    } else if (val === "plan") {
      if (sec2DActive) sec2DExit();
      if ($('btnOrtho')) $('btnOrtho').click();
      setView("top");
    } else if (val === "elev-s") {
      if (sec2DActive) sec2DExit();
      if ($('btnOrtho')) $('btnOrtho').click();
      setView("front");
    } else if (val === "elev-n") {
      if (sec2DActive) sec2DExit();
      if ($('btnOrtho')) $('btnOrtho').click();
      setView("back");
    } else if (val === "elev-e") {
      if (sec2DActive) sec2DExit();
      if ($('btnOrtho')) $('btnOrtho').click();
      setView("right");
    } else if (val === "elev-w") {
      if (sec2DActive) sec2DExit();
      if ($('btnOrtho')) $('btnOrtho').click();
      setView("left");
    } else if (val === "section") {
      if (!SEC.on) secStart("z");
      await secGenerate2DView();
    }
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
  
  // Display mode is a view-wide setting, so it applies to every loaded model's
  // meshes, not just activeModel's -- otherwise switching to Wireframe/X-ray
  // with several models loaded would leave all-but-one of them shaded.
  const dmModels = secAllLoadedModels();
  if (!dmModels.length) return;
  dmModels.forEach(model => {
    if (!model || !model.object) return;
    model.object.children.forEach(mesh => {
        if(!mesh || !mesh.material) return;
        // Three.js's wireframe renderer (updateWireframeAttribute) needs an
        // indexed BufferGeometry; some Fragments-built meshes are non-indexed
        // and crash the render loop every frame if `wireframe = true` is set
        // on them (confirmed live: TypeError reading 'length' inside
        // three.module.js's getWireframeAttribute). Skip wireframe specifically
        // for those meshes rather than crashing -- they stay shaded instead.
        const canWireframe = !!(mesh.geometry && mesh.geometry.index);

        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        mats.forEach(mat => {
          if (mode === 'shaded') {
            mat.wireframe = false;
            mat.transparent = false;
            mat.opacity = 1.0;
            mat.depthTest = true;
          } else if (mode === 'wire') {
            mat.wireframe = canWireframe;
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
  if (!controls) return;
  // In both select and orbit modes, left-drag orbits smoothly.
  // Click-vs-drag threshold in the click handler distinguishes stationary element picking from rotation drag.
  controls.mouseButtons.LEFT = m==='pan'?THREE.MOUSE.PAN : m==='zoom'?THREE.MOUSE.DOLLY : THREE.MOUSE.ROTATE;
  controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
  controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
  [['btnSelect','select'],['btnOrbit','orbit'],['btnPan','pan'],['btnZoom','zoom']].forEach(pair=>{
    const b = $(pair[0]); if(b) b.classList.toggle("on", pair[1]===m);
  });
}
if($('btnSelect')) $('btnSelect').onclick = ()=> setNavMode("select");
if($('btnOrbit')) $('btnOrbit').onclick = ()=> setNavMode("orbit");
if($('btnPan')) $('btnPan').onclick = ()=> setNavMode("pan");
if($('btnZoom')) $('btnZoom').onclick = ()=> setNavMode("zoom");
// Select is the default tool on load, matching the toolbar's default "on"
// button (btnSelect) and most CAD/BIM viewers' convention of a plain
// pointer-select default rather than orbit-on-left-click.
setNavMode("select");

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

// Feature 3: Ghost Context Mode (Translucent surrounding context)
let isGhostMode = false;
if($('btnGhost')) $('btnGhost').onclick = async () => {
    if (!activeModel || !window._lastSelId) return;
    isGhostMode = !isGhostMode;
    $('btnGhost').classList.toggle('on', isGhostMode);
    
    secAllMeshes(mesh => {
        if (!mesh.material) return;
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        mats.forEach(m => {
            if (isGhostMode) {
                m.transparent = true;
                m.opacity = 0.18;
                m.depthWrite = false;
            } else {
                m.transparent = false;
                m.opacity = 1.0;
                m.depthWrite = true;
            }
        });
    });
    
    // Highlight selected item firmly
    try {
        activeModel.setColor([window._lastSelId], new THREE.Color(isGhostMode ? 0x4d7cfe : 0x4d7cfe));
    } catch(e) {}
};

if($('btnShowAll')) $('btnShowAll').onclick = () => {
    isGhostMode = false;
    if ($('btnGhost')) $('btnGhost').classList.remove('on');
    secAllMeshes(mesh => {
        if (!mesh.material) return;
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        mats.forEach(m => {
            m.transparent = false;
            m.opacity = 1.0;
            m.depthWrite = true;
        });
    });
    if (activeModel) {
        if(activeModel.resetVisible) { try { activeModel.resetVisible(); } catch(e){} }
        if(activeModel.object && activeModel.object.children) {
            activeModel.object.children.forEach(c => c.visible = true);
        }
    }
};

// Feature 4: First-Person Walkthrough Navigation (WASD + Mouse Look)
let isWalkMode = false;
const walkKeys = { forward: false, backward: false, left: false, right: false, up: false, down: false };
const walkSpeed = 0.35;

function toggleWalkMode(enable) {
    isWalkMode = enable !== undefined ? enable : !isWalkMode;
    const btn = $('btnWalk');
    if (btn) btn.classList.toggle('on', isWalkMode);
    const prompt = $('walkNavPrompt');
    if (prompt) prompt.style.display = isWalkMode ? 'flex' : 'none';
    
    if (isWalkMode) {
        // Position camera to comfortable eye-level if floating high
        if (modelBox) {
            const center = modelBox.getCenter(new THREE.Vector3());
            camera.position.y = Math.max(camera.position.y, center.y + 1.7);
        }
    }
}

if ($('btnWalk')) $('btnWalk').onclick = () => toggleWalkMode();
if ($('btnExitWalk')) $('btnExitWalk').onclick = () => toggleWalkMode(false);

window.addEventListener('keydown', (e) => {
    if (!isWalkMode) return;
    if (['input', 'textarea'].includes(document.activeElement.tagName.toLowerCase())) return;
    if (e.key === 'w' || e.key === 'W' || e.key === 'ArrowUp') walkKeys.forward = true;
    if (e.key === 's' || e.key === 'S' || e.key === 'ArrowDown') walkKeys.backward = true;
    if (e.key === 'a' || e.key === 'A' || e.key === 'ArrowLeft') walkKeys.left = true;
    if (e.key === 'd' || e.key === 'D' || e.key === 'ArrowRight') walkKeys.right = true;
    if (e.key === ' ' || e.key === 'e' || e.key === 'E') walkKeys.up = true;
    if (e.key === 'Shift' || e.key === 'q' || e.key === 'Q') walkKeys.down = true;
});

window.addEventListener('keyup', (e) => {
    if (!isWalkMode) return;
    if (e.key === 'w' || e.key === 'W' || e.key === 'ArrowUp') walkKeys.forward = false;
    if (e.key === 's' || e.key === 'S' || e.key === 'ArrowDown') walkKeys.backward = false;
    if (e.key === 'a' || e.key === 'A' || e.key === 'ArrowLeft') walkKeys.left = false;
    if (e.key === 'd' || e.key === 'D' || e.key === 'ArrowRight') walkKeys.right = false;
    if (e.key === ' ' || e.key === 'e' || e.key === 'E') walkKeys.up = false;
    if (e.key === 'Shift' || e.key === 'q' || e.key === 'Q') walkKeys.down = false;
});

function updateWalkPhysics() {
    if (!isWalkMode || !camera) return;
    const forward = new THREE.Vector3();
    camera.getWorldDirection(forward);
    forward.y = 0;
    forward.normalize();
    
    const side = new THREE.Vector3().crossVectors(camera.up, forward).normalize();
    const move = new THREE.Vector3();
    
    if (walkKeys.forward) move.add(forward);
    if (walkKeys.backward) move.sub(forward);
    if (walkKeys.left) move.add(side);
    if (walkKeys.right) move.sub(side);
    if (walkKeys.up) move.y += 1;
    if (walkKeys.down) move.y -= 1;
    
    if (move.lengthSq() > 0) {
        move.normalize().multiplyScalar(walkSpeed);
        camera.position.add(move);
        if (controls && controls.target) {
            controls.target.add(move);
        }
    }
}

if($('btnSectionTool')) $('btnSectionTool').onclick = ()=>{
    const p = $('secToolsPanel'); if(!p) return;
    const open = !p.classList.contains("open");
    p.classList.toggle("open", open);
    const b = $('btnSectionTool'); if(b) b.classList.toggle("on", open);
};
if($('stClose')) $('stClose').onclick = ()=> {
    const p = $('secToolsPanel'); if(p) p.classList.remove("open");
    const b = $('btnSectionTool'); if(b) b.classList.remove("on");
};


// ================= Sectioning Tools (ported from ui/viewer.js) =================
// Adapted for the Fragments engine: no flat `allMeshes` array exists here, so
// mesh-material loops traverse `activeModel.object` instead, and bbox centering
// reuses the already-computed `modelBox` (a THREE.Box3) rather than a custom
// bboxAll() union.

// Every loaded model (not just activeModel), via the same fragments.models.list
// Map that the click-to-select handler already resolves pickedModel from.
// Falls back to [activeModel] if fragments/models isn't available for some reason.
function secAllLoadedModels(){
  return (fragments && fragments.models && fragments.models.list)
    ? Array.from(fragments.models.list.values())
    : (activeModel ? [activeModel] : []);
}

function secAllMeshes(cb){
  secAllLoadedModels().forEach(model => {
    if(model && model.object){
      model.object.traverse(c=>{ if(c.isMesh && c.material){ cb(c); } });
    }
  });
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

// ---------------- Click-to-place workflow ----------------
// Lets the user draw their own section by clicking directly on the model, instead of only
// starting from a model-centered plane and dragging it. Mirrors ui/viewer.js's placement flow.
function secCameraNormal(){
  const d = new THREE.Vector3(); camera.getWorldDirection(d);
  const ax = Math.abs(d.x), ay = Math.abs(d.y), az = Math.abs(d.z);
  if(ay >= ax && ay >= az) return new THREE.Vector3(0, d.y >= 0 ? 1 : -1, 0);
  if(ax >= az) return new THREE.Vector3(d.x >= 0 ? 1 : -1, 0, 0);
  return new THREE.Vector3(0, 0, d.z >= 0 ? 1 : -1);
}

function secPlacePickableMeshes(){
  const list = [];
  secAllLoadedModels().forEach(model => {
    if(model && model.object){
      model.object.traverse(c=>{
        if(c.isMesh && c.visible && c.geometry && c.geometry.attributes && c.geometry.attributes.position){
          const pos = c.geometry.attributes.position;
          if(pos.array && pos.array.length > 0 && pos.count > 0){
            if(c.geometry.index && (!c.geometry.index.array || c.geometry.index.array.length === 0)) return;
            list.push(c);
          }
        }
      });
    }
  });
  return list;
}

function secPlaceApplyPreview(){
  if(!SEC.group) return;
  SEC.group.position.copy(SEC.freePoint);
  SEC.group.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1), SEC.freeNormal);
  SEC.group.visible = true;
  if(SEC.arrow) SEC.arrow.visible = false; // gizmo stays hidden until placement is confirmed
}

function secPlaceBegin(){
  if(!activeModel){ logDiag("Load a model before placing a section plane.", true); return; }
  if(sec2DActive) sec2DExit();
  if(SBX.on) sbxOff();
  secBuildVisual();
  SEC.on = false;
  SEC.placing = true;
  SEC.editing = false;
  SEC.freeNormal = secCameraNormal();
  SEC.freePoint = secModelCenter();
  secPlaceApplyPreview();
  const hint = $('secPlaceHint'); if(hint) hint.style.display = "block";
  const addBtn = $('secAddBtn'); if(addBtn) addBtn.style.display = "none";
}

let _secPlaceMoveBusy = false;
async function secPlaceMove(ev){
  if(!SEC.placing || !activeModel) return;
  // GPU-readback pick via FastModelPicker (components.get(OBC.FastModelPickers)),
  // model-agnostic and reusing the same render the click-to-select handler uses.
  // Replaces the old activeModel.raycaster.raycast()/activeModel.raycast() cascade.
  if(_secPlaceMoveBusy) return; // the async pick can outlive a fast mouse, so drop
  _secPlaceMoveBusy = true;     // overlapping calls instead of racing stale results in.
  try {
    let res = null;
    try {
      const ndc = secPointerToNDC(ev);
      res = await picker.getFullPick(ndc);
    } catch(e) { res = null; }
    if(!SEC.placing) return; // placement may have been cancelled while the pick was in flight
    if(res && res.point && res.normal){
      SEC.freeNormal.copy(res.normal).normalize();
      SEC.freePoint.copy(res.point);
    } else {
      SEC.freeNormal.copy(secCameraNormal());
      SEC.freePoint.copy(secModelCenter());
    }
    secPlaceApplyPreview();
  } finally {
    _secPlaceMoveBusy = false;
  }
}

function secPlaceConfirm(){
  SEC.placing = false;
  SEC.on = true;
  SEC.editing = true;
  secUpdate();
  secPositionGizmoSync();
  secSetGizmoVisible(true);
  const hint = $('secPlaceHint'); if(hint) hint.style.display = "none";
  const addBtn = $('secAddBtn'); if(addBtn) addBtn.style.display = "";
  secSyncPanelVisibility();
  stRenderPlaneList();
}

function secPlaceCancel(){
  SEC.placing = false;
  if(SEC.group) SEC.group.visible = false;
  const hint = $('secPlaceHint'); if(hint) hint.style.display = "none";
  const addBtn = $('secAddBtn'); if(addBtn) addBtn.style.display = "";
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

// ---- SEC drag handling (gizmo pick + ray/plane projection on pointerdown/pointermove) ----
// Uses the same "intersect a drag plane, project onto axis/rotation" approach as
// THREE.TransformControls, so the handle tracks 1:1 under the mouse cursor instead
// of an approximate screen-delta mapping.
const secRaycaster = new THREE.Raycaster();
function secPointerToNDC(ev){
  const rect = viewEl.getBoundingClientRect();
  return new THREE.Vector2(((ev.clientX-rect.left)/rect.width)*2-1, -((ev.clientY-rect.top)/rect.height)*2+1);
}

// Build a plane that contains the given axis line (through `origin`) and faces the
// camera as squarely as possible -- the standard gizmo drag-plane construction.
function secDragPlaneForAxis(axisVec, origin){
  const eye = new THREE.Vector3().subVectors(camera.position, origin);
  if(eye.lengthSq() < 1e-9) eye.set(0,0,1);
  eye.normalize();
  let normal = new THREE.Vector3().crossVectors(axisVec, eye);
  if(normal.lengthSq() < 1e-8){
    // axis nearly points straight at the camera -- fall back to any perpendicular
    normal = new THREE.Vector3(1,0,0).cross(axisVec);
    if(normal.lengthSq() < 1e-8) normal = new THREE.Vector3(0,1,0).cross(axisVec);
  }
  normal.cross(axisVec).normalize();
  return new THREE.Plane().setFromNormalAndCoplanarPoint(normal, origin);
}

function secRayPlanePoint(ev, plane){
  const ndc = secPointerToNDC(ev);
  secRaycaster.setFromCamera(ndc, camera);
  const out = new THREE.Vector3();
  return secRaycaster.ray.intersectPlane(plane, out) ? out : null;
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
  const axis = h.userData.secAxis;
  const origin = SEC.group.position.clone();
  const axisVec = secLocalAxis(axis);

  if(h.userData.secHandle === "translate"){
    const plane = secDragPlaneForAxis(axisVec, origin);
    const p0 = secRayPlanePoint(ev, plane) || origin.clone();
    SEC.drag = { handle:"translate", axis, plane, axisVec, origin,
      startOffset: new THREE.Vector3().subVectors(p0, origin).dot(axisVec),
      startPos: origin.clone() };
  } else {
    // rotate: drag plane is perpendicular to the (world) rotation axis itself
    const worldAxis = axis==="x"?new THREE.Vector3(1,0,0):axis==="y"?new THREE.Vector3(0,1,0):new THREE.Vector3(0,0,1);
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(worldAxis, origin);
    const p0 = secRayPlanePoint(ev, plane);
    const v0 = p0 ? new THREE.Vector3().subVectors(p0, origin) : null;
    if(!v0 || v0.lengthSq() < 1e-6) return false; // camera looking down the axis -- no usable angle
    v0.normalize();
    SEC.drag = { handle:"rotate", axis, plane, worldAxis, origin, v0, startQuat:SEC.group.quaternion.clone() };
  }
  controls.enabled = false;
  return true;
}

function secLocalAxis(axis){
  const v = axis==="x" ? new THREE.Vector3(1,0,0) : axis==="y" ? new THREE.Vector3(0,1,0) : new THREE.Vector3(0,0,1);
  return v.applyQuaternion(SEC.group.quaternion).normalize();
}

function secDragMove(ev){
  if(!SEC.drag) return;
  if(SEC.drag.handle === "translate"){
    const p = secRayPlanePoint(ev, SEC.drag.plane);
    if(!p) return;
    const offset = new THREE.Vector3().subVectors(p, SEC.drag.origin).dot(SEC.drag.axisVec);
    const amt = offset - SEC.drag.startOffset;
    SEC.group.position.copy(SEC.drag.startPos).addScaledVector(SEC.drag.axisVec, amt);
  } else if(SEC.drag.handle === "rotate"){
    const p = secRayPlanePoint(ev, SEC.drag.plane);
    if(!p) return;
    const v1 = new THREE.Vector3().subVectors(p, SEC.drag.origin);
    if(v1.lengthSq() < 1e-6) return;
    v1.normalize();
    const cross = new THREE.Vector3().crossVectors(SEC.drag.v0, v1);
    const sin = cross.dot(SEC.drag.worldAxis);
    const cos = SEC.drag.v0.dot(v1);
    const angle = Math.atan2(sin, cos);
    const q = new THREE.Quaternion().setFromAxisAngle(SEC.drag.worldAxis, angle);
    SEC.group.quaternion.copy(SEC.drag.startQuat).premultiply(q);
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
  const axis = f.userData.sbxAxis, side = f.userData.sbxSide;
  const axisVec = axis==="x"?new THREE.Vector3(1,0,0):axis==="y"?new THREE.Vector3(0,1,0):new THREE.Vector3(0,0,1);
  const origin = hits[0].point.clone();
  // Drag plane: contains the face's own axis line, faces the camera -- same
  // ray/plane projection technique as the section-plane gizmo, so the face
  // tracks 1:1 under the cursor instead of a fixed screen-pixel-to-world scale.
  const plane = secDragPlaneForAxis(axisVec, origin);
  const p0 = secRayPlanePoint(ev, plane) || origin;
  SBX.drag = { axis, side, plane, axisVec, origin,
    startOffset: new THREE.Vector3().subVectors(p0, origin).dot(axisVec),
    startVal: side==="min" ? SBX.box.min[axis] : SBX.box.max[axis] };
  controls.enabled = false;
  return true;
}
function sbxDragMove(ev){
  if(!SBX.drag) return;
  const p = secRayPlanePoint(ev, SBX.drag.plane);
  if(!p) return;
  const offset = new THREE.Vector3().subVectors(p, SBX.drag.origin).dot(SBX.drag.axisVec);
  const amt = offset - SBX.drag.startOffset;
  SBX.box[SBX.drag.side][SBX.drag.axis] = SBX.drag.startVal + amt;
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
  const pTab=$('stTabPlane'), bTab=$('stTabBox'), pPane=$('stPanePlane'), bPane=$('stPaneBox');
  if(pTab) pTab.classList.toggle("on", tab==="plane");
  if(bTab) bTab.classList.toggle("on", tab==="box");
  if(pPane) pPane.style.display = (tab==="plane") ? "" : "none";
  if(bPane) bPane.style.display = (tab==="box") ? "" : "none";
}

// ---------------- Global pointer priority chain (placement -> box drag -> plane drag -> pick) ----------------
renderer.domElement.addEventListener("pointerdown", (ev)=>{
  if(ev.button !== 0) return;
  if(SEC.placing) { secPlaceConfirm(); ev.preventDefault(); ev.stopPropagation(); return; }
  if(SBX.on && sbxTryDrag(ev)) { ev.preventDefault(); ev.stopPropagation(); return; }
  if(SEC.on && secTryDrag(ev)) { ev.preventDefault(); ev.stopPropagation(); return; }
  // otherwise fall through to the existing click-based element picking
});
renderer.domElement.addEventListener("pointermove", (ev)=>{
  if(SEC.placing) { secPlaceMove(ev); return; }
  if(SEC.drag) { secDragMove(ev); return; }
  if(SBX.drag) { sbxDragMove(ev); return; }
});
window.addEventListener("pointerup", ()=>{
  if(SEC.drag) secDragEnd();
  if(SBX.drag) sbxDragEnd();
});
window.addEventListener("keydown", (ev)=>{
  if(ev.key !== "Escape") return;
  if(SEC.placing) secPlaceCancel();
});

// ---------------- UI wiring ----------------
if($('stTabPlane')) $('stTabPlane').onclick = ()=> stSetTab("plane");
if($('stTabBox')) $('stTabBox').onclick = ()=> stSetTab("box");
if($('stMin')) $('stMin').onclick = ()=>{ const p=$('secToolsPanel'); if(p) p.classList.toggle("min"); };

if($('secAddBtn')) $('secAddBtn').onclick = ()=>{
  if(SEC.on){ SEC.editing = true; secSetGizmoVisible(true); secSyncPanelVisibility(); return; }
  if(SEC.placing) return;
  secPlaceBegin();
};
if($('secPlaceCancelBtn')) $('secPlaceCancelBtn').onclick = (ev)=>{ ev.stopPropagation(); secPlaceCancel(); };
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

// ---------------- 2D Section View (Plan / Elevation) ----------------
// Uses Fragments' own native `model.getSection(plane, localIds?)` API (SectionManager/
// SectionGenerator inside @thatopen/fragments) to cut the loaded model along the active
// SEC plane and get back true cut-edge line geometry, then reframes an orthographic
// camera to look straight along the plane's normal -- a horizontal SEC plane gives a
// flat "Plan" view, a vertical one gives an "Elevation"/section view.
let sec2DLines = null;
let sec2DActive = false;
let sec2DSaved = null; // { camera, position, quaternion, top, bottom, left, right, target, navMode, controlsEnabled }

function secModelMatrixWorld(model){
  const m = model || activeModel;
  if(m && m.object){ m.object.updateMatrixWorld(true); return m.object.matrixWorld; }
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
    // Cut every loaded model, not just activeModel, so a federated multi-model
    // scene gets one continuous section line across all of them. The shared
    // SEC._plane (scene/world space) is transformed into EACH model's own
    // local space before calling that model's own getSection(), and the
    // returned edge vertices (in that model's local space) are transformed
    // back to scene space via that SAME model's own matrixWorld -- never
    // activeModel's -- before all models' buffers are merged into one.
    const models = secAllLoadedModels();
    let totalVerts = 0;
    const perModel = [];
    for(const model of models){
      if(!model || !model.getSection) continue;
      try {
        const modelMatrix = secModelMatrixWorld(model);
        const invMatrix = modelMatrix.clone().invert();
        const localPlane = SEC._plane.clone().applyMatrix4(invMatrix);
        const result = await model.getSection(localPlane);
        const vertCount = result && typeof result.index === "number" ? result.index : 0;
        if(result && vertCount >= 2){
          perModel.push({ result, vertCount, modelMatrix });
          totalVerts += vertCount;
        }
      } catch(e) {
        logDiag("2D view: section cut failed for model " + (model.modelId || model.uuid || "?") + ": " + e, true);
      }
    }

    if(totalVerts < 2){
      logDiag("2D view: no geometry intersects this plane -- move it so it actually cuts through the model.", true);
      return;
    }

    const positions = new Float32Array(totalVerts * 3);
    const v = new THREE.Vector3();
    let vOffset = 0;
    for(const { result, vertCount, modelMatrix } of perModel){
      const src = result.buffer;
      for(let i = 0; i < vertCount; i++){
        v.set(src[i*3], src[i*3+1], src[i*3+2]);
        v.applyMatrix4(modelMatrix); // worker returns points in that model's own local space
        positions[(vOffset+i)*3] = v.x; positions[(vOffset+i)*3+1] = v.y; positions[(vOffset+i)*3+2] = v.z;
      }
      vOffset += vertCount;
    }

    if(sec2DLines){ scene.remove(sec2DLines); sec2DLines.geometry.dispose(); sec2DLines.material.dispose(); sec2DLines = null; }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const mat = new THREE.LineBasicMaterial({ color: 0x1a1d24, depthTest: false, depthWrite: false });
    sec2DLines = new THREE.LineSegments(geo, mat);
    sec2DLines.renderOrder = 1000;
    scene.add(sec2DLines);

    // Save current camera/nav state so "Back to 3D" restores exactly where the user was.
    if(!sec2DActive){
      sec2DSaved = {
        camera, position: camera.position.clone(), quaternion: camera.quaternion.clone(),
        top: camera.top, bottom: camera.bottom, left: camera.left, right: camera.right,
        target: controls.target.clone(), controlsEnabled: controls.enabled,
        background: scene.background ? scene.background.clone() : null,
        gridVisible: grid.visible,
      };
    }

    const normal = SEC.freeNormal ? SEC.freeNormal.clone() : new THREE.Vector3(0,0,1);
    const center = SEC.freePoint ? SEC.freePoint.clone() : secModelCenter();
    // For a horizontal section plane (Plan view), camera points down and up vector must point towards North (-Z)
    const up = Math.abs(normal.y) > 0.9 ? new THREE.Vector3(0,0,-1) : new THREE.Vector3(0,1,0);
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

    secAllLoadedModels().forEach(model => { if(model && model.object) model.object.visible = false; });
    if(SEC.group) SEC.group.visible = false;
    if(SEC.arrow) SEC.arrow.visible = false;
    if(SBX.helper) SBX.helper.visible = false;
    (SBX.faces||[]).forEach(f=> f.visible = false);
    sec2DLines.visible = true;
    // A plan/elevation reads as a CAD drawing, not a 3D scene -- white page, dark lines,
    // no floor grid, no lighting-driven shading to compete with the cut edges.
    scene.background = new THREE.Color(0xffffff);
    grid.visible = false;

    sec2DActive = true;
    const genBtn = $('sec2DGenBtn'); if(genBtn) genBtn.classList.add("on");
    const exitRow = $('sec2DExitRow'); if(exitRow) exitRow.style.display = "";
    const hint = $('sec2DHint'); if(hint) hint.style.display = "";
    logDiag(`2D view generated: ${totalVerts/2} cut-edge segments across ${perModel.length} model(s).`);
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
  secAllLoadedModels().forEach(model => { if(model && model.object) model.object.visible = true; });
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
    scene.background = sec2DSaved.background || new THREE.Color(0x0a0e14);
    grid.visible = sec2DSaved.gridVisible;
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

window._secDebug = { SEC, SBX, renderer, scene, get camera(){ return camera; }, THREE, viewEl, applyClippingPlanes, secTryDrag, secDragMove, secDragEnd, sbxTryDrag, sbxDragMove, sbxDragEnd, secGenerate2DView, sec2DExit, get sec2DActive(){ return sec2DActive; }, secPlaceBegin, secPlaceMove, secPlaceConfirm, secPlaceCancel, get activeModel(){ return activeModel; } };
// ================= End Sectioning Tools =================

// ---- 3D Navigation Gizmo (ViewCube + Compass) ----
function setView(dir){
  const box = modelBox || (activeModel && activeModel.boundingBox);
  if(!box) return;
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  const r = Math.max(s.x, s.y, s.z) || 10;
  const d = r * 1.9;
  controls.target.copy(c);
  // World axes standard in AEC/IFC: +Y is Up, +Z is South, -Z is North, +X is East, -X is West.
  const V = { top:[0,1,0], bottom:[0,-1,0], front:[0,0,1], back:[0,0,-1], right:[1,0,0], left:[-1,0,0] };
  const v = V[dir] || V.front;
  camera.up.set(0,1,0);
  if(dir === "top") camera.up.set(0,0,-1); // In Top view, looking down (+Y), camera up points towards -Z (North/up on screen)
  else if(dir === "bottom") camera.up.set(0,0,1);
  camera.position.set(c.x + v[0]*d, c.y + v[1]*d, c.z + v[2]*d);
  if(camera.isOrthographicCamera){
    const aspect = viewEl.clientWidth / viewEl.clientHeight || 1;
    const halfH = r * 1.15;
    const halfW = halfH * aspect;
    camera.left = -halfW; camera.right = halfW;
    camera.top = halfH; camera.bottom = -halfH;
    camera.near = 0.05; camera.far = d * 5;
  } else {
    camera.near = Math.max(0.01, r / 1000);
    camera.far = Math.max(10000, r * 100);
  }
  camera.updateProjectionMatrix();
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
  const targetParent = document.getElementById("view") || document.body;
  targetParent.appendChild(dock);
  dock.querySelectorAll(".face").forEach(f => f.onclick = (ev)=>{ ev.stopPropagation(); setView(f.dataset.v); });
  const home = dock.querySelector("#navHome"); if(home) home.onclick = (ev)=> { ev.stopPropagation(); fit(); };
}

function updateNavGizmo(){
  const cube = document.getElementById("navCube"); if(!cube) return;
  if(!camera) return;
  const dir = new THREE.Vector3(); camera.getWorldDirection(dir);
  // In our coordinate space: facing South (+Z) has yaw = 0, facing North (-Z) has yaw = 180.
  // The compass ring's N label is at the top (0deg offset relative to North).
  // When looking towards North (-Z, e.g. in Top view with camera.up = -Z), North is UP on screen.
  const yaw = Math.atan2(dir.x, -dir.z) * 180 / Math.PI;
  const pitch = Math.asin(Math.max(-1, Math.min(1, dir.y))) * 180 / Math.PI;
  cube.style.transform = "rotateX(" + pitch + "deg) rotateY(" + (-yaw) + "deg)";
  const compass = document.getElementById("navCompass");
  if(compass) compass.style.transform = "rotate(" + yaw + "deg)";
}

function animate() {
  requestAnimationFrame(animate);
  if(controls) controls.update();
  try { updateWalkPhysics(); } catch(e){}
  updateNavGizmo();
  try { updateMeasureLabels(); } catch(e){}
  if(renderer && scene && camera) renderer.render(scene, camera);
}

async function boot() {
  logDiag("Booting viewer...");
  resize();
  injectGizmo();
  try { wireAddModel(); } catch(e){ console.error("wireAddModel error", e); }
  try { renderModelList(); } catch(e){ console.error("renderModelList error", e); }
  await initEngine();
  animate();
  if (rels.length > 0) {
    // Load every requested model, sequentially rather than in parallel --
    // loadModel() already races each network/worker step against
    // MODEL_LOAD_TIMEOUT_MS for exactly the dense-model hang case documented
    // above, and loading several such models at once would multiply worker
    // contention risk instead of just taking longer. loadModel() already
    // catches and logDiag's its own failures without rethrowing, so one bad
    // model (404, conversion failure, timeout) does not stop the rest from
    // loading; the try/catch here is defense-in-depth in case that contract
    // ever changes.
    for (const rel of rels) {
      try {
        await loadModel(rel);
      } catch (e) {
        logDiag("Unexpected error loading model " + rel + ": " + e, true);
      }
    }
    setLoading(null);
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
    } else if (cmd.command === 'render') {
        logDiag(`AI Command received: Render 3D view`);
        if ($('btnAiRender')) $('btnAiRender').click();
    }
});

// ---- 3D AI Render (Qwen Image Turbo) Wiring ----
(function wireAiRender() {
    const btnAiRender = $('btnAiRender');
    const modal = $('renderModal');
    const closeBtn = $('renderClose');
    const doBtn = $('btnDoRender');
    const dlBtn = $('btnDownloadRender');
    const snapImg = $('renderSnapshotImg');
    const ph = $('renderPlaceholder');
    const ld = $('renderLoading');
    const resInfo = $('renderResultInfo');

    if (!btnAiRender || !modal) return;

    function openModal() {
        modal.style.display = 'flex';
        btnAiRender.classList.add('on');
        captureCurrentView();
    }

    function closeModal() {
        modal.style.display = 'none';
        btnAiRender.classList.remove('on');
    }

    btnAiRender.onclick = openModal;
    if (closeBtn) closeBtn.onclick = closeModal;

    function captureCurrentView() {
        if (!renderer || !renderer.domElement) return "";
        try {
            // Render one frame clean
            renderer.render(scene, camera);
            const dataUrl = renderer.domElement.toDataURL("image/png");
            if (snapImg) {
                snapImg.src = dataUrl;
                snapImg.style.display = 'block';
            }
            if (ph) ph.style.display = 'none';
            return dataUrl;
        } catch(e) {
            console.error("Snapshot capture error", e);
            return "";
        }
    }

    if (doBtn) {
        doBtn.onclick = async () => {
            const dataUrl = captureCurrentView();
            const promptVal = $('renderPrompt') ? $('renderPrompt').value : "";
            const styleVal = $('renderStyle') ? $('renderStyle').value : "photorealistic modern architecture";
            const modelVal = $('renderModelSelect') ? $('renderModelSelect').value : "FLUX.2-klein-4B";
            
            if (ld) {
                ld.style.display = 'flex';
                const ldTxt = $('renderLoadingTxt');
                if (ldTxt) ldTxt.textContent = `Rendering with ${modelVal}…`;
            }
            if (resInfo) resInfo.style.display = 'none';
            if (dlBtn) dlBtn.style.display = 'none';
            doBtn.disabled = true;

            try {
                const headers = { "Content-Type": "application/json" };
                if (token) headers["Authorization"] = `Bearer ${token}`;
                const resp = await fetch(`/api/ai/render?token=${encodeURIComponent(token || "")}`, {
                    method: "POST",
                    headers,
                    body: JSON.stringify({
                        image: dataUrl,
                        model: modelVal,
                        prompt: promptVal || "Photorealistic modern architectural render, natural lighting, highly detailed materials, 8k resolution, cinematic atmosphere",
                        style: styleVal
                    })
                });
                const res = await resp.json();
                
                if (res.image_url) {
                    snapImg.src = res.image_url;
                    snapImg.style.display = 'block';
                    if (dlBtn) {
                        dlBtn.style.display = 'inline-block';
                        dlBtn.onclick = () => {
                            const a = document.createElement('a');
                            a.href = res.image_url;
                            a.download = `render_${(res.model || modelVal).replace(/[^a-zA-Z0-9]/g, '_')}_${Date.now()}.png`;
                            a.click();
                        };
                    }
                    if (resInfo) {
                        resInfo.style.display = 'block';
                        let infoHtml = `<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px"><span style="color:#22c55e;font-weight:700">● Render Ready</span> <b>${res.model || modelVal}</b> <span style="opacity:0.7">(${res.provider || 'local'})</span></div>`;
                        if (res.analysis) {
                            infoHtml += `<div style="font-size:11px;opacity:0.9;max-height:100px;overflow-y:auto;border-top:1px solid rgba(255,255,255,0.1);padding-top:4px">${res.analysis.replace(/\n/g, '<br>')}</div>`;
                        }
                        resInfo.innerHTML = infoHtml;
                    }
                } else if (res.analysis) {
                    if (resInfo) {
                        resInfo.style.display = 'block';
                        resInfo.innerHTML = `<b>${res.model || modelVal} Architectural &amp; Lighting Synthesis:</b><br>${res.analysis.replace(/\n/g, '<br>')}`;
                    }
                } else if (res.error) {
                    if (resInfo) {
                        resInfo.style.display = 'block';
                        resInfo.innerHTML = `<span style="color:#ff6b6b">Render error: ${res.error}</span>`;
                    }
                }
            } catch(err) {
                if (resInfo) {
                    resInfo.style.display = 'block';
                    resInfo.innerHTML = `<span style="color:#ff6b6b">Connection error: ${err}</span>`;
                }
            } finally {
                if (ld) ld.style.display = 'none';
                doBtn.disabled = false;
            }
        };
    }
})();
