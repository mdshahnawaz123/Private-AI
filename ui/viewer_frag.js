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
const workerUrl = new URL("/ui/vendor_fragments/fragments/Worker/worker.mjs?v=1", location.href).toString();
const fragments = new FRAGS.FragmentsModels(workerUrl);

const loaded = []; // { rel, model }

async function getFragBytes(rel) {
  // Prefer the pre-built .frag; fall back to converting the raw .ifc in-browser.
  try {
    const r = await fetch(fileURL(rel + ".frag"));
    if (r.ok) {
      const buf = new Uint8Array(await r.arrayBuffer());
      if (buf.length > 0) return buf;
    }
  } catch (e) { /* fall through to IFC conversion */ }

  setLoading("No .frag yet — converting IFC (one-time)…");
  const ri = await fetch(fileURL(rel));
  if (!ri.ok) throw new Error("Could not fetch model (" + ri.status + ")");
  const ifcBytes = new Uint8Array(await ri.arrayBuffer());
  const importer = new FRAGS.IfcImporter();
  importer.wasm.path = "/ui/vendor_fragments/";
  importer.wasm.absolute = true;
  importer.webIfcSettings = { COORDINATE_TO_ORIGIN: false };
  return await importer.process({ bytes: ifcBytes });
}

async function loadModel(rel) {
  setLoading("Loading " + rel.split("/").pop() + " …");
  const bytes = await getFragBytes(rel);
  const model = await fragments.load(bytes, { modelId: rel, camera });
  scene.add(model.object);
  model.getClippingPlanesEvent = () => renderer.clippingPlanes;
  loaded.push({ rel, model });
  return model;
}

function fitTo(model) {
  const box = model.box || new THREE.Box3().setFromObject(model.object);
  if (!box || box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const r = Math.max(size.x, size.y, size.z) || 10;
  camera.near = Math.max(0.01, r / 1000); camera.far = r * 100; camera.updateProjectionMatrix();
  camera.position.set(center.x + r, center.y + r * 0.7, center.z + r);
  controls.target.copy(center); controls.update();
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
$("btnFit").onclick = () => { if (loaded[0]) fitTo(loaded[0].model); };
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
    resize();
    if (!rels.length) { showErr("No model selected."); return; }
    // 2a: single model. Multi-model federation is Phase 2b.
    const first = rels[0];
    const model = await loadModel(first);
    await fragments.update(true);
    fitTo(model);
    $("title").textContent = first.split("/").pop() + (rels.length > 1 ? "  (1 of " + rels.length + " — multi-model is next)" : "");
    setLoading(null);
    animate();
    try { parent.postMessage({ source: "expo-viewer", type: "ready", project, engine: "fragments" }, "*"); } catch (e) {}
    try { parent.postMessage({ source: "expo-viewer", type: "loaded", rels: loaded.map((l) => l.rel) }, "*"); } catch (e) {}
  } catch (e) {
    console.error(e);
    showErr((e && e.message ? e.message : String(e)) + "  — if this mentions web-ifc/worker, the vendor bundle may be incomplete.");
  }
})();
