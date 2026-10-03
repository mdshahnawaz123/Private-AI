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
// three.js is Y-up (Y = height); survey/BIM is Z-up (Z = height). Map a three.js
// point to survey convention so coordinate readouts read as Easting/Northing/
// Elevation rather than the engine's X/Y/Z. Reused by the spot-coordinate tool.
const toSurvey = (x, y, z) => ({ E: x, N: z, Z: y });
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
const camera = new THREE.PerspectiveCamera(60, 1, 0.01, 1e7);       // 3D (perspective)
const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e6, 1e6); // 2D (Plan/Section/Elevation)
let activeCam = camera;
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
  if (activeCam === ortho) orthoFrustum();
}
// Size the orthographic frustum to the current view extent and aspect.
let orthoHalf = 50;
function orthoFrustum() {
  const aspect = (viewEl.clientWidth || 1) / Math.max(1, viewEl.clientHeight || 1);
  ortho.left = -orthoHalf * aspect; ortho.right = orthoHalf * aspect;
  ortho.top = orthoHalf; ortho.bottom = -orthoHalf;
  ortho.updateProjectionMatrix();
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
  // Recenter geometry near origin, and disable Fragments' 100 km distance cull
  // (these IFCs use absolute survey coordinates; the cull would otherwise drop
  // ALL geometry). Matches tools/fragments/convert_ifc_to_frag.mjs.
  importer.webIfcSettings = { COORDINATE_TO_ORIGIN: true };
  importer.distanceThreshold = null;
  return await importer.process({ bytes: ifcBytes });
}

async function loadModel(rel) {
  setLoading("Loading " + rel.split("/").pop() + " …");
  const bytes = await getFragBytes(rel);
  dlog("fragments-load", { bytes: bytes && bytes.length });
  const model = await fragments.load(bytes, { modelId: rel, camera });
  dlog("fragments-loaded");
  // Each model gets its own wrapper group. Federation sets the group's matrix;
  // Fragments never touches the group, only model.object inside it.
  const group = new THREE.Group(); group.name = "model:" + rel;
  group.add(model.object);
  scene.add(group);
  // Reveal the real model API so we stop guessing method names across versions.
  try {
    const proto = Object.getPrototypeOf(model) || {};
    const methods = Object.getOwnPropertyNames(proto).filter((n) => { try { return typeof model[n] === "function"; } catch (e) { return false; } });
    dlog("model-api", methods.join(","));
    dlog("model-props", { box: typeof model.box, getBox: typeof model.getBox, boundingBox: typeof model.boundingBox, useCamera: typeof model.useCamera, object: !!model.object, children: (model.object && model.object.children && model.object.children.length) || 0 });
  } catch (e) { derr("api-dump", e); }
  // Tell the model which camera to stream geometry for, if that API exists.
  try { if (typeof model.useCamera === "function") { model.useCamera(camera); dlog("use-camera-ok"); } else { dlog("use-camera-absent"); } } catch (e) { derr("useCamera", e); }
  model.getClippingPlanesEvent = () => renderer.clippingPlanes;
  const entry = { rel, model, group };
  loaded.push(entry);
  return entry;
}

// Multi-model federation: place model 0 at identity (its own 0,0,0) and every
// other model by M0^-1 * Mi, where Mi is the model's coordination matrix (its
// real-world placement). Shared-coordinate models then line up correctly while
// the scene stays near the origin.
async function federate() {
  if (loaded.length < 2) return;
  const mats = [];
  for (const L of loaded) {
    let m = null;
    try { if (typeof L.model.getCoordinationMatrix === "function") m = await L.model.getCoordinationMatrix(); } catch (e) { derr("coordMatrix", e); }
    mats.push(m);
    // Report in survey convention: three.js is Y-up (Y = height), survey is
    // Z-up. So three.js translation (x=Easting, y=Elevation, z=Northing) maps to
    // Easting=elements[12], Northing=elements[14], Elevation=elements[13].
    dlog("coord", m ? { m: L.rel.split("/").pop(), E: +m.elements[12].toFixed(1), N: +m.elements[14].toFixed(1), Elev: +m.elements[13].toFixed(1) } : { m: L.rel.split("/").pop(), t: null });
  }
  const ref = mats[0];
  if (!ref) { dlog("federate-skip", "no reference coordination matrix"); return; }
  const refInv = ref.clone().invert();
  for (let i = 0; i < loaded.length; i++) {
    const m = mats[i]; if (!m) continue;
    const relMat = refInv.clone().multiply(m);
    loaded[i].group.matrixAutoUpdate = false;
    loaded[i].group.matrix.copy(relMat);
    loaded[i].group.updateMatrixWorld(true);
  }
  dlog("federated", { models: loaded.length });
}

// Union of all loaded models' world bounding boxes (null if empty). Shared by
// fit and sectioning.
async function unionBox() {
  const union = new THREE.Box3();
  for (const L of loaded) {
    let local = null;
    try {
      if (typeof L.model.getItemsIdsWithGeometry === "function" && typeof L.model.getMergedBox === "function") {
        const ids = await L.model.getItemsIdsWithGeometry();
        if (ids && ids.length) local = asBox3(await L.model.getMergedBox(ids));
      }
    } catch (e) {}
    L.group.updateMatrixWorld(true);
    if (local && !local.isEmpty()) { union.union(local.clone().applyMatrix4(L.group.matrixWorld)); }
    else { try { const b = new THREE.Box3().setFromObject(L.group); if (!b.isEmpty()) union.union(b); } catch (e) {} }
  }
  return union.isEmpty() ? null : union;
}
// Frame the camera to the union of all loaded models' world bounding boxes.
async function fitAll() {
  const union = await unionBox();
  if (!union) { dlog("fitall-no-box"); return false; }
  const size = union.getSize(new THREE.Vector3());
  const center = union.getCenter(new THREE.Vector3());
  dlog("union-box", { size_WxDxH: [+size.x.toFixed(1), +size.z.toFixed(1), +size.y.toFixed(1)], center_ENZ: [+center.x.toFixed(1), +center.z.toFixed(1), +center.y.toFixed(1)] });
  const r = Math.max(size.x, size.y, size.z) || 10;
  if (activeCam === ortho) { orthoHalf = r * 0.62; orthoFrustum(); }
  else { activeCam.near = Math.max(0.01, r / 1000); activeCam.far = r * 100; activeCam.updateProjectionMatrix(); }
  activeCam.position.set(center.x + r, center.y + r * 0.7, center.z + r);
  controls.target.copy(center); controls.update();
  return true;
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
  // Preferred: ask the worker for the merged bounding box of all geometry items
  // (works even before anything has streamed into the visible scene).
  try {
    if (typeof model.getItemsIdsWithGeometry === "function" && typeof model.getMergedBox === "function") {
      const ids = await model.getItemsIdsWithGeometry();
      if (ids && ids.length) {
        const b = asBox3(await model.getMergedBox(ids));
        if (b && !b.isEmpty()) { dlog("box-src", "getMergedBox(" + ids.length + " ids)"); return b; }
      } else { dlog("geom-ids", { count: (ids && ids.length) || 0 }); }
    }
  } catch (e) { derr("getMergedBox", e); }
  try { if (model.box) { const b = asBox3(model.box); if (b && !b.isEmpty()) { dlog("box-src", "model.box"); return b; } } } catch (e) {}
  try { const b = new THREE.Box3().setFromObject(model.object); if (!b.isEmpty()) { dlog("box-src", "setFromObject"); return b; } } catch (e) {}
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
    try { res = await model.raycast({ camera: activeCam, mouse, dom }); } catch (e) { res = null; }
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

renderer.domElement.addEventListener("pointerdown", (ev) => { if (ev.button !== 0) return; if (measureMode) measureClick(ev); else pickAt(ev); });

// ---- Display mode ----
function setWire(on) {
  loaded.forEach(({ model }) => model.object.traverse((o) => {
    if (o.material) { const mats = Array.isArray(o.material) ? o.material : [o.material]; mats.forEach((m) => { if ("wireframe" in m) m.wireframe = on; }); }
  }));
  $("btnShaded").classList.toggle("on", !on);
  $("btnWire").classList.toggle("on", on);
}
$("btnFit").onclick = () => { if (loaded.length) fitAll(); };  // fire-and-forget
$("btnShaded").onclick = () => setWire(false);
$("btnWire").onclick = () => setWire(true);

// ---- Models + Categories panel ----
const MODEL_COLORS = [0x4d7cfe, 0x31d0a5, 0xf5b73d, 0xb07cff, 0xff6b6b, 0x4dd2ff, 0xffd24d, 0x7cffb0];
function renderModelsPanel() {
  const el = $("mdlList"); if (!el) return;
  const cnt = $("mdlCount"); if (cnt) cnt.textContent = "(" + loaded.length + ")";
  el.innerHTML = "";
  loaded.forEach((L, i) => {
    const row = document.createElement("div"); row.className = "item";
    const col = "#" + new THREE.Color(MODEL_COLORS[i % MODEL_COLORS.length]).getHexString();
    row.innerHTML = '<input type="checkbox" checked><span class="dot" style="background:' + col + '"></span><span class="nm"></span><button class="iso">isolate</button>';
    row.querySelector(".nm").textContent = L.rel.split("/").pop();
    row.querySelector(".nm").title = L.rel;
    const cb = row.querySelector("input");
    cb.onchange = () => { L.group.visible = cb.checked; };
    row.querySelector(".iso").onclick = () => {
      loaded.forEach((o, j) => { o.group.visible = (j === i); const c = el.children[j] && el.children[j].querySelector("input"); if (c) c.checked = (j === i); });
    };
    el.appendChild(row);
  });
}
function flattenIds(res) {
  if (!res) return [];
  if (Array.isArray(res)) return res;
  if (typeof res === "object") { let out = []; for (const k in res) { if (Array.isArray(res[k])) out = out.concat(res[k]); } return out; }
  return [];
}
async function setCategoryVisible(cat, vis) {
  for (const L of loaded) {
    try {
      if (typeof L.model.getItemsOfCategories === "function" && typeof L.model.setVisible === "function") {
        const ids = flattenIds(await L.model.getItemsOfCategories([new RegExp("^" + cat + "$")]));
        if (ids.length) await L.model.setVisible(ids, vis);
      }
    } catch (e) { derr("setCategoryVisible:" + cat, e); }
  }
  try { await fragments.update(true); } catch (e) {}
}
async function renderCategoriesPanel() {
  const el = $("catList"); if (!el) return;
  const set = new Set();
  for (const L of loaded) {
    try { if (typeof L.model.getCategories === "function") { (await L.model.getCategories() || []).forEach((c) => set.add(c)); } } catch (e) { derr("getCategories", e); }
  }
  const cats = [...set].sort();
  dlog("categories", { count: cats.length });
  el.innerHTML = "";
  cats.forEach((cat) => {
    const row = document.createElement("div"); row.className = "item";
    row.innerHTML = '<input type="checkbox" checked><span class="nm"></span>';
    row.querySelector(".nm").textContent = cat.replace(/^IFC/, "");
    row.querySelector(".nm").title = cat;
    const cb = row.querySelector("input");
    cb.onchange = () => setCategoryVisible(cat, cb.checked);
    el.appendChild(row);
  });
}
async function showAll() {
  loaded.forEach((L) => { L.group.visible = true; });
  for (const L of loaded) {
    try { if (typeof L.model.getItemsIdsWithGeometry === "function" && typeof L.model.setVisible === "function") { const ids = await L.model.getItemsIdsWithGeometry(); if (ids && ids.length) await L.model.setVisible(ids, true); } } catch (e) {}
  }
  try { await fragments.update(true); } catch (e) {}
  renderModelsPanel(); renderCategoriesPanel();
}
if ($("btnPanel")) $("btnPanel").onclick = () => { const s = $("side"); if (s) s.classList.toggle("open"); };
if ($("btnShowAll")) $("btnShowAll").onclick = () => showAll();

// Reference coordination matrix (model 0, local->absolute), for true survey
// coordinates in the point tool. Set in boot.
let REF = null;

// ---- Section plane (global clipping) ----
const SEC = { plane: null, axis: null, sign: 1, box: null };
function setSecBtns(axis) { [["btnSecX", "x"], ["btnSecY", "y"], ["btnSecZ", "z"]].forEach(([id, a]) => { const b = $(id); if (b) b.classList.toggle("on", axis === a); }); }
async function setSection(axis) {
  const box = await unionBox();
  if (!box) { dlog("section-no-box"); return; }
  SEC.box = box; SEC.axis = axis;
  const c = box.getCenter(new THREE.Vector3());
  const n = axis === "x" ? new THREE.Vector3(1, 0, 0) : axis === "y" ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(0, 0, 1);
  n.multiplyScalar(SEC.sign);
  SEC.plane = new THREE.Plane(n.clone(), -n.dot(c));
  renderer.clippingPlanes = [SEC.plane];
  const lo = axis === "x" ? box.min.x : axis === "y" ? box.min.y : box.min.z;
  const hi = axis === "x" ? box.max.x : axis === "y" ? box.max.y : box.max.z;
  const mid = axis === "x" ? c.x : axis === "y" ? c.y : c.z;
  const sl = $("secSlider");
  if (sl) { sl.min = lo; sl.max = hi; sl.step = Math.max(0.01, (hi - lo) / 500); sl.value = mid; sl.style.display = "block"; }
  setSecBtns(axis);
  dlog("section", { axis, sign: SEC.sign });
}
function moveSection(val) { if (SEC.plane) SEC.plane.constant = -SEC.sign * parseFloat(val); }
function flipSection() { SEC.sign *= -1; if (SEC.axis) setSection(SEC.axis); }
function clearSection() { SEC.plane = null; SEC.axis = null; renderer.clippingPlanes = []; const sl = $("secSlider"); if (sl) sl.style.display = "none"; setSecBtns(null); }
if ($("btnSecX")) $("btnSecX").onclick = () => setSection("x");
if ($("btnSecY")) $("btnSecY").onclick = () => setSection("y");
if ($("btnSecZ")) $("btnSecZ").onclick = () => setSection("z");
if ($("btnSecOff")) $("btnSecOff").onclick = () => clearSection();
if ($("btnSecFlip")) $("btnSecFlip").onclick = () => flipSection();
if ($("secSlider")) $("secSlider").oninput = (e) => moveSection(e.target.value);

// ---- Measurement + annotations ----
let measureMode = null; // 'len' | 'point'
let mPts = [];
const mObjs = [];
let mLabels = []; // {el, pt}
function markerR() { const b = SEC.box; if (b) { const s = b.getSize(new THREE.Vector3()); return Math.max(0.15, Math.max(s.x, s.y, s.z) / 400); } return 0.3; }
function clearMeasure() { mObjs.forEach((o) => scene.remove(o)); mObjs.length = 0; mPts = []; mLabels.forEach((l) => l.el.remove()); mLabels = []; const o = $("measureOut"); if (o) o.textContent = "—"; }
function setMeasure(mode) {
  measureMode = (measureMode === mode) ? null : mode;
  [["btnMeasure", "len"], ["btnPoint", "point"]].forEach(([id, m]) => { const b = $(id); if (b) b.classList.toggle("on", measureMode === m); });
  mPts = [];
  const o = $("measureOut"); if (o) { o.textContent = measureMode === "len" ? "Click two points…" : measureMode === "point" ? "Click a point…" : "—"; o.style.display = measureMode ? "block" : "none"; }
}
function addMarker(p) { const s = new THREE.Mesh(new THREE.SphereGeometry(markerR(), 12, 12), new THREE.MeshBasicMaterial({ color: 0xf5b73d, depthTest: false })); s.position.copy(p); s.renderOrder = 999; scene.add(s); mObjs.push(s); }
function addLine(a, b) { const g = new THREE.BufferGeometry().setFromPoints([a, b]); const l = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xf5b73d, depthTest: false })); l.renderOrder = 999; scene.add(l); mObjs.push(l); }
function addLabel(p, text) { const el = document.createElement("div"); el.className = "mlabel"; el.textContent = text; viewEl.appendChild(el); mLabels.push({ el, pt: p.clone() }); }
function updateLabels() {
  if (!mLabels.length) return;
  const w = viewEl.clientWidth, h = viewEl.clientHeight;
  for (const L of mLabels) { const v = L.pt.clone().project(activeCam); const vis = v.z < 1; L.el.style.display = vis ? "block" : "none"; if (vis) { L.el.style.left = ((v.x * 0.5 + 0.5) * w) + "px"; L.el.style.top = ((-v.y * 0.5 + 0.5) * h) + "px"; } }
}
async function measureClick(ev) {
  const dom = renderer.domElement; const rect = dom.getBoundingClientRect();
  const mouse = new THREE.Vector2(ev.clientX - rect.left, ev.clientY - rect.top);
  let hit = null;
  for (const L of loaded) { if (!L.group.visible) continue; let r = null; try { r = await L.model.raycast({ camera: activeCam, mouse, dom }); } catch (e) {} if (r && r.point) { hit = r; break; } }
  if (!hit || !hit.point) { dlog("measure-miss"); return; }
  const p = new THREE.Vector3(hit.point.x, hit.point.y, hit.point.z);
  addMarker(p); mPts.push(p);
  if (measureMode === "len") {
    if (mPts.length >= 2) {
      const a = mPts[mPts.length - 2], b = mPts[mPts.length - 1];
      addLine(a, b); const d = a.distanceTo(b);
      addLabel(a.clone().lerp(b, 0.5), d.toFixed(2) + " m");
      const o = $("measureOut"); if (o) o.textContent = "Length: " + d.toFixed(3) + " m";
      mPts = [];
    }
  } else if (measureMode === "point") {
    const w = REF ? p.clone().applyMatrix4(REF) : p;  // true survey coords when REF known
    const s = toSurvey(w.x, w.y, w.z);
    const txt = "E " + s.E.toFixed(2) + "  N " + s.N.toFixed(2) + "  Z " + s.Z.toFixed(2);
    addLabel(p, txt);
    const o = $("measureOut"); if (o) o.textContent = txt;
    mPts = [];
  }
}
if ($("btnMeasure")) $("btnMeasure").onclick = () => setMeasure("len");
if ($("btnPoint")) $("btnPoint").onclick = () => setMeasure("point");
if ($("btnMclr")) $("btnMclr").onclick = () => clearMeasure();

// ---- 2D / 3D views (Plan / Section / Elevation) ----
// Iso = perspective 3D. Top = plan, Front/Back/Left/Right = elevations, all in
// an orthographic 2D camera (rotation locked). Combine Top + the section slider
// for a storey plan cut.
function setProjection(is2d) {
  activeCam = is2d ? ortho : camera;
  controls.object = activeCam;
  controls.enableRotate = !is2d;
  for (const L of loaded) { try { if (typeof L.model.useCamera === "function") L.model.useCamera(activeCam); } catch (e) {} }
}
function setViewBtns(view) { [["btnIso", "iso"], ["btnTop", "top"], ["btnFront", "front"], ["btnBack", "back"], ["btnLeft", "left"], ["btnRight", "right"]].forEach(([id, v]) => { const b = $(id); if (b) b.classList.toggle("on", view === v); }); }
async function frameView(view) {
  const box = await unionBox(); if (!box) { dlog("view-no-box"); return; }
  const c = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const r = Math.max(size.x, size.y, size.z) || 10;
  let dir, up = new THREE.Vector3(0, 1, 0);
  switch (view) {
    case "top": dir = new THREE.Vector3(0, -1, 0); up = new THREE.Vector3(0, 0, -1); break;  // plan
    case "front": dir = new THREE.Vector3(0, 0, -1); break;
    case "back": dir = new THREE.Vector3(0, 0, 1); break;
    case "left": dir = new THREE.Vector3(1, 0, 0); break;
    case "right": dir = new THREE.Vector3(-1, 0, 0); break;
    default: dir = new THREE.Vector3(1, 0.7, 1).normalize();  // iso
  }
  const dist = r * 2.2;
  activeCam.up.copy(up);
  activeCam.position.copy(c).sub(dir.clone().multiplyScalar(dist));
  controls.target.copy(c);
  if (activeCam === ortho) { orthoHalf = r * 0.6; orthoFrustum(); ortho.near = -r * 20; ortho.far = r * 20; ortho.updateProjectionMatrix(); }
  else { activeCam.near = Math.max(0.01, r / 1000); activeCam.far = r * 100; activeCam.updateProjectionMatrix(); }
  controls.update();
  dlog("view", view);
}
async function setView(view) { setProjection(view !== "iso"); await frameView(view); setViewBtns(view); }
[["btnIso", "iso"], ["btnTop", "top"], ["btnFront", "front"], ["btnBack", "back"], ["btnLeft", "left"], ["btnRight", "right"]].forEach(([id, v]) => { const b = $(id); if (b) b.onclick = () => setView(v); });

// ---- render loop ----
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  try { fragments.update(); } catch (e) {}
  renderer.render(scene, activeCam);
  updateLabels();
}

// ---- boot ----
(async () => {
  try {
    dlog("boot-start");
    resize();
    // Default framing so the grid is always visible even before/without a fit.
    camera.position.set(30, 22, 30); controls.target.set(0, 0, 0); controls.update();
    if (!rels.length) { showErr("No model selected."); dlog("boot-no-model"); return; }
    // Phase 2b: load ALL selected models, then federate them.
    for (const rel of rels) {
      setLoading("Loading " + rel.split("/").pop() + " …");
      try { await loadModel(rel); } catch (e) { derr("load:" + rel.split("/").pop(), e); }
    }
    dlog("all-loaded", { models: loaded.length });
    await fragments.update(true);
    try { if (loaded[0] && typeof loaded[0].model.getCoordinationMatrix === "function") REF = await loaded[0].model.getCoordinationMatrix(); } catch (e) { derr("ref-matrix", e); }
    await federate();
    await fragments.update(true);
    const framed = await fitAll();
    dlog("fit-done", { framed, models: loaded.length });
    if (!framed) {
      let tries = 0;
      const retry = async () => {
        tries++;
        try { await fragments.update(true); } catch (e) {}
        if (await fitAll()) { dlog("fit-retry-ok", { tries }); }
        else if (tries < 6) { setTimeout(retry, 600); }
        else { dlog("fit-gave-up", "box still empty after retries — paste this log"); }
      };
      setTimeout(retry, 500);
    }
    $("title").textContent = loaded.length === 1 ? loaded[0].rel.split("/").pop() : (loaded.length + " models federated");
    try { renderModelsPanel(); } catch (e) { derr("modelsPanel", e); }
    try { renderCategoriesPanel(); } catch (e) { derr("categoriesPanel", e); }
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
