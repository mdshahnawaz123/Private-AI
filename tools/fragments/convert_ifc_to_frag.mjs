// IFC -> Fragments (.frag) converter (server-side, Node).
//
// Turns a raw .ifc into The Open Company "Fragments" binary (.frag), which is
// ~9x smaller and loads in a fraction of the time (see
// OPENCOMPANY_FRAGMENTS_POC_RESULTS.md: 80 MB IFC -> 8.66 MB .frag, 587 ms load
// vs multi-second raw web-ifc parsing).
//
// This mirrors the proven browser PoC (ui/_fragments_poc.html) exactly:
//   const importer = new FRAGS.IfcImporter();
//   importer.wasm.path = <dir with web-ifc wasm>; importer.wasm.absolute = true;
//   importer.webIfcSettings = { COORDINATE_TO_ORIGIN: false };
//   const fragBytes = await importer.process({ bytes });
// COORDINATE_TO_ORIGIN:false keeps raw IFC geometry (no stream-order-dependent
// auto-shift) so the viewer's own placement layer stays authoritative -- the
// same setting the web-ifc load path uses today.
//
// Usage:   node convert_ifc_to_frag.mjs <input.ifc> <output.frag>
// Output:  writes <output.frag>; prints a one-line JSON status to STDOUT.
// Exit:    0 ok, 2 bad args, 1 conversion error. All diagnostics go to STDERR
//          so STDOUT carries only the JSON result the caller parses.

import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import process from "node:process";

function fail(code, msg, extra) {
  try { console.error(JSON.stringify(Object.assign({ ok: false, error: msg }, extra || {}))); } catch (_) {}
  process.exit(code);
}

const inPath = process.argv[2];
const outPath = process.argv[3];
if (!inPath || !outPath) {
  console.error("usage: node convert_ifc_to_frag.mjs <input.ifc> <output.frag>");
  process.exit(2);
}

const t0 = Date.now();

let FRAGS;
try {
  FRAGS = await import("@thatopen/fragments");
} catch (e) {
  // Dependencies not installed -- the caller treats this as "skip, keep the IFC".
  fail(1, "fragments-module-not-found: run `npm install` in tools/fragments/ (" + (e && e.message ? e.message : e) + ")");
}

// Locate the web-ifc package directory (which contains web-ifc.wasm) so the
// importer points at the same pinned web-ifc (0.0.77) the viewer bundle uses.
// NOTE: web-ifc's package.json "exports" does NOT expose "./package.json", so
// require.resolve("web-ifc/package.json") throws ERR_PACKAGE_PATH_NOT_EXPORTED.
// Resolve the package's main entry instead (always exported) and take its dir;
// fall back to this script's own node_modules. Verify web-ifc.wasm is there.
const dirHasWasm = (d) => !!d && existsSync(path.join(d, "web-ifc.wasm"));
let webIfcDir = null;
try {
  const require = createRequire(import.meta.url);
  const cand = path.dirname(require.resolve("web-ifc"));
  if (dirHasWasm(cand)) webIfcDir = cand;
} catch (e) { /* fall through to the filesystem guess */ }
if (!webIfcDir) {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const cand = path.join(here, "node_modules", "web-ifc");
  if (dirHasWasm(cand)) webIfcDir = cand;
}
if (!webIfcDir) {
  fail(1, "web-ifc-wasm-not-found: run `npm install` in tools/fragments/ (could not locate web-ifc.wasm)");
}

let bytes;
try {
  bytes = new Uint8Array(await readFile(inPath));
} catch (e) {
  fail(1, "read-failed: " + (e && e.message ? e.message : e));
}

try {
  const importer = new FRAGS.IfcImporter();
  importer.wasm.path = webIfcDir.endsWith(path.sep) ? webIfcDir : webIfcDir + path.sep;
  importer.wasm.absolute = true;
  // COORDINATE_TO_ORIGIN:true recenters geometry near (0,0,0) at parse time.
  // These models are georeferenced at survey scale (~2,700 km from origin);
  // Fragments skips any object more than 100 km from origin, so WITHOUT this
  // the .frag comes out nearly empty ("... is more than 100000 meters away ...
  // will be skipped"). Recentering keeps all geometry and renders precisely.
  // (Multi-model federation alignment is handled in the viewer at Phase 2b.)
  importer.webIfcSettings = { COORDINATE_TO_ORIGIN: true };

  const fragBytes = await importer.process({ bytes });
  await writeFile(outPath, Buffer.from(fragBytes));

  const result = {
    ok: true,
    in: inPath,
    out: outPath,
    inBytes: bytes.length,
    outBytes: fragBytes.length,
    ratio: +(bytes.length / Math.max(1, fragBytes.length)).toFixed(2),
    ms: Date.now() - t0,
  };
  process.stdout.write(JSON.stringify(result) + "\n");
  process.exit(0);
} catch (e) {
  fail(1, "convert-failed: " + (e && e.message ? e.message : e), { stack: e && e.stack ? String(e.stack).split("\n").slice(0, 4).join(" | ") : null });
}
