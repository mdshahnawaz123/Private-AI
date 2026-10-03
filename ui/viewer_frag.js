// Fragments viewer (Phase 2a, beta) -- additive, opt-in. The production web-ifc
// viewer (viewer.js) is untouched and remains the default.
//
// Loads a model from its lightweight Fragments (.frag) binary when present;
// if no .frag exists yet (not converted), it falls back to fetching the raw
// .ifc and converting in-browser (the proven PoC path), so it always works.
//
// Scope 2a: single model, orbit/zoom/fit, click-select -> highlight + property
// panel + selection bridge to the parent shell, shaded/wire. Multi-model
// federation, categories/tree, section, measurement, 2D plans and sheets are
// later increments (2b-2e).

import * as THREE from "three";
import { OrbitControls } from "/ui/vendor_fragments/OrbitControls.js?v=1";
import * as FRAGS from "/ui/vendor_fragments/fragments/index.mjs?v=1";
import * as WebIFC from "web-ifc";

const $ = (id) => document.getElementById(id);
const q = new URLSearchParams(location.search);
const project = q.get("project") || "default";
const token = q.get("token") || "";
const rels = q.getAll("rel");

// Diagnostics bridge to the inline capture in viewer_frag.html (also mirrors to
// /diagnostics/viewer). Safe no-ops if the inline script didn't load.
const dlog = (s, e) => { try { if (window.__dlog) window.__dlog(s, e); } catch (x) {} };
const derr = (w, e) => { try { if (window.__derr) window.__derr(w, e); } catch (x) {} };
dlog("module-loaded", { three: (typeof THREE !== "undefined" && THREE.REVISION) || "?", rels: rels.length });

function fileURL(rel) {
  return `${location.origin}/projects/${encodeURIComponent(project)}/file?rel=${encodeURIComponent(rel)}&token=${encodeURIComponent(token)}`;
}
function setLoading(msg) { const l = $("loading"); if (!l) return; if (msg == null) { l.style.display = "none"; } else { l.style.display = "flex"; const m = $("loadMsg"); if (m) m.textContent = msg; } }
function showErr(msg) { setLoading(null); const e = $("err"); if (e) { e.style.display = "flex"; const m = $("errMsg"); if (m) m.textContent = msg; } }

// ---- three.js scene ----
const viewEl = $("view");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0e1116);
const camera = new THREE.PerspectiveCamera(60, 1, 0.01, 1e7);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.localClippingEnabled = true;
viewEl.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.AmbientLight(0xffffff, 0.65));
const dir = new THREE.DirectionalLight(0xffffff, 1.0); dir.position.set(1, 2, 1); scene.add(dir);
const dir2 = new THREE.DirectionalLight(0xffffff, 0.4); dir2.position.set(-1, 1, -2); scene.add(dir2);
const grid = new THREE.GridHelper(500, 50, 0x30363d, 0x20262e); scene.add(grid);

function resize() {
  const w = viewEl.clientWidth || window.innerWidth, h = viewEl.clientHeight || window.innerHeight;
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);

// ---- Fragments engine ----
const workerUrl = new URL("/ui/vendor_fragments/fragments/Worker/worker.mjs?v=2", location.href).toString();
dlog("fragments-worker", workerUrl);
const fragments = new FRAGS.FragmentsModels(workerUrl);
dlog("fragments-engine-created");

const loaded = []; // { rel, model }

async function getFragBytes(rel) {
  // Prefer the pre-built .frag; fall back to converting the raw .ifc in-browser.
  try {
    dlog("frag-fetch", rel + ".frag");
    const r = await fetch(fileURL(rel + ".frag"));
    if (r.ok) {
      const buf = new Uint8Array(await r.arrayBuffer());
      if (buf.length > 0) { dlog("frag-fetched", { bytes: buf.length }); return buf; }
      dlog("frag-empty", "0 bytes — will convert from IFC");
    } else {
      dlog("frag-miss", { status: r.status });
    }
  } catch (e) { derr("frag-fetch", e); }

  setLoading("No .frag yet — converting IFC (one-time)…");
  dlog("ifc-convert-start", rel);
  const ri = await fetch(fileURL(rel));
  if (!ri.ok) throw new Error("Could not fetch model (" + ri.status + ")");
  const ifcBytes = new Uint8Array(await ri.arrayBuffer());
  const importer = new FRAGS.IfcImporter();
  importer.wasm.path = "/ui/vendor_fragments/";
  importer.wasm.absolute = true;
  // Recenter geometry near origin so survey-scale models aren't skipped by
  // Fragments' 100 km cull (matches tools/fragments/convert_ifc_to_frag.mjs).
  importer.webIfcSettings = { COORDINATE_TO_ORIGIN: true };
  return await importer.process({ bytes: ifcBytes });
}

async function loadModel(rel) {
  setLoading("Loading " + rel.split("/").pop() + " …");
  const bytes = await getFragBytes(rel);
  dlog("fragments-load", { bytes: bytes && bytes.length });
  const model = await fragments.load(bytes, { modelId: rel, camera });
  dlog("fragments-loaded");
  scene.add(model.object);
  // Critical: tell the model which camera to stream geometry for. Without this,
  // Fragments never materializes geometry (empty box, blank view).
  try { model.useCamera(camera); dlog("use-camera-ok"); } catch (e) { derr("useCamera", e); }
  model.getClippingPlanesEvent = () => renderer.clippingPlanes;
  loaded.push({ rel, model });
  return model;
}

function asBox3(b) {
  if (!b) return null;
  if (b.isBox3) return b;
  if (b.min && b.max) {
    const g = (p, a, i) => (p[a] != null ? p[a] : (Array.isArray(p) ? p[i] : undefined));
    const mn = new THREE.Vector3(g(b.min, "x", 0), g(b.min, "y", 1), g(b.min, "z", 2));
    const mx = new THREE.Vector3(g(b.max, "x", 0), g(b.max, "y", 1), g(b.max, "z", 2));
    if ([mn.x, mn.y, mn.z, mx.x, mx.y, mx.z].every((n) => typeof n === "number" && isFinite(n))) return new THREE.Box3(mn, mx);
  }
  return null;
}
async function computeBox(model) {
  // The authoritative source in Fragments v3 is the async model.getBox().
  try { const b = asBox3(await model.getBox()); if (b && !b.isEmpty()) return b; } catch (e) { derr("getBox", e); }
  try { if (model.box && !model.box.isEmpty()) return model.box; } catch (e) {}
  try { const b = new THREE.Box3().setFromObject(model.object); if (!b.isEmpty()) return b; } catch (e) {}
  return null;
}
async function fitTo(model) {
  const box = await computeBox(model);
  if (!box) { dlog("fit-no-box", "bounding box empty / geometry not ready yet"); return false; }
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  dlog("box", { min: box.min.toArray().map((n) => +n.toFixed(1)), max: box.max.toArray().map((n) => +n.toFixed(1)), size: size.toArray().map((n) => +n.toFixed(1)) });
  const r = Math.max(size.x, size.y, size.z) || 10;
  camera.near = Math.max(0.01, r / 1000); camera.far = r * 100; camera.updateProjectionMatrix();
  camera.position.set(center.x + r, center.y + r * 0.7, center.z + r);
  controls.target.copy(center); controls.update();
  return true;
}

// ---- Selection: click -> raycast -> highlight + properties + parent bridge ----
let lastHighlight = null; // { model, id }
const HL_COLOR = new THREE.Color(0x4d7cfe);

function flatAttr(v) {
  if (v == null) return "";
  if (typeof v === "object") { if ("value" in v) return v.value; return JSON.stringify(v); }
  return v;
}

async function pickAt(ev) {
  if (!loaded.length) return;
  const dom = renderer.domElement;
  const rect = dom.getBoundingClientRect();
  const mouse = new THREE.Vector2(ev.clientX - rect.left, ev.clientY - rect.top);
  let hit = null, hitModel = null;
  for (const { model } of loaded) {
    let res = null;
    try { res = await model.raycast({ camera, mouse, dom }); } catch (e) { res = null; }
    if (res && (res.localId != null || res.itemId != null)) { hit = res; hitModel = model; break; }
  }
  // clear previous highlight
  if (lastHighlight) { try { await lastHighlight.model.resetHighlight([lastHighlight.id]); } catch (e) {} lastHighlight = null; }
  if (!hit || !hitModel) { $("props").style.display = "none"; emitSel(null); return; }
  const id = hit.localId != null ? hit.localId : hit.itemId;
  try { await hitModel.highlight([id], { color: HL_COLOR, opacity: 1, transparent: false }); lastHighlight = { model: hitModel, id }; } catch (e) {}
  await showProps(hitModel, id);
}

async function showProps(model, id) {
  let data = {};
  try { const arr = await model.getItemsData([id], { attributesDefault: true }); data = (arr && arr[0]) || {}; } catch (e) {}
  let gid = "";
  try { const g = await model.getGuidsByLocalIds([id]); gid = (g && g[0]) || ""; } catch (e) {}
  const name = flatAttr(data.Name) || "";
  const category = flatAttr(data._category || data.category) || flatAttr(data.ObjectType) || "Element";
  const objType = flatAttr(data.ObjectType) || "";
  const rowsOrder = ["Name", "ObjectType", "Tag", "PredefinedType", "OverallHeight", "OverallWidth"];
  const rows = [];
  rows.push(["Category", category]);
  if (gid) rows.push(["GlobalId", gid]);
  rows.push(["localId", String(id)]);
  for (const k of rowsOrder) { if (data[k] != null) rows.push([k, flatAttr(data[k])]); }
  $("propTitle").textContent = name || category || "Element";
  $("propBody").innerHTML = rows.map(([k, v]) => `<div class="row"><b>${k}</b><span>${String(v).slice(0, 120)}</span></div>`).join("");
  $("props").style.display = "block";
  const text = rows.map(([k, v]) => k + ": " + v).join("\n");
  emitSel({ kind: "element", typeName: category, name, objType, gid, expressID: id, text });
}

function emitSel(payload) {
  try { parent.postMessage({ source: "expo-viewer", type: "selection", payload: payload || { kind: "none" } }, "*"); } catch (e) {}
}

renderer.domElement.addEventListener("pointerdown", (ev) => { if (ev.button === 0) pickAt(ev); });

// ---- Display mode ----
function setWire(on) {
  loaded.forEach(({ model }) => model.object.traverse((o) => {
    if (o.material) { const mats = Array.isArray(o.material) ? o.material : [o.material]; mats.forEach((m) => { if ("wireframe" in m) m.wireframe = on; }); }
  }));
  $("btnShaded").classList.toggle("on", !on);
  $("btnWire").classList.toggle("on", on);
}
$("btnFit").onclick = () => { if (loaded[0]) fitTo(loaded[0].model); };  // fire-and-forget
$("btnShaded").onclick = () => setWire(false);
$("btnWire").onclick = () => setWire(true);

// ---- render loop ----
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  try { fragments.update(); } catch (e) {}
  renderer.render(scene, camera);
}

// ---- boot ----
(async () => {
  try {
    dlog("boot-start");
    resize();
    // Default framing so the grid is always visible even before/without a fit.
    camera.position.set(30, 22, 30); controls.target.set(0, 0, 0); controls.update();
    if (!rels.length) { showErr("No model selected."); dlog("boot-no-model"); return; }
    // 2a: single model. Multi-model federation is Phase 2b.
    const first = rels[0];
    const model = await loadModel(first);
    dlog("fragments-update");
    await fragments.update(true);
    const framed = await fitTo(model);
    dlog("fit-done", { framed });
    if (!framed) {
      // Fragments may still be streaming geometry; retry a couple of times.
      let tries = 0;
      const retry = async () => {
        tries++;
        try { await fragments.update(true); } catch (e) {}
        if (await fitTo(model)) { dlog("fit-retry-ok", { tries }); }
        else if (tries < 6) { setTimeout(retry, 600); }
        else { dlog("fit-gave-up", "box still empty after retries — paste this log"); }
      };
      setTimeout(retry, 500);
    }
    $("title").textContent = first.split("/").pop() + (rels.length > 1 ? "  (1 of " + rels.length + " — multi-model is next)" : "");
    setLoading(null);
    animate();
    try { window.__ready = true; } catch (e) {}
    dlog("READY");
    try { parent.postMessage({ source: "expo-viewer", type: "ready", project, engine: "fragments" }, "*"); } catch (e) {}
    try { parent.postMessage({ source: "expo-viewer", type: "loaded", rels: loaded.map((l) => l.rel) }, "*"); } catch (e) {}
  } catch (e) {
    console.error(e);
    derr("boot", e);
    showErr((e && e.message ? e.message : String(e)) + "  — see the diagnostics panel (bottom-left) for the step that failed.");
  }
})();
