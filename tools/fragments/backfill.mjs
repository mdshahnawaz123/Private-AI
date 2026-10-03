// Backfill: convert every .ifc under a directory that doesn't already have a
// .frag sibling, using the same converter the backend calls per upload.
//
// Usage:
//   node backfill.mjs [rootDir]
// Default rootDir = ../../data/docs (relative to this file), i.e. all project
// models. Run from anywhere; paths are resolved against this script's location.

import { readdir, access } from "node:fs/promises";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import process from "node:process";

const here = path.dirname(fileURLToPath(import.meta.url));
const converter = path.join(here, "convert_ifc_to_frag.mjs");
const args = process.argv.slice(2);
const force = args.includes("--force");           // re-convert even if a .frag already exists
const posArg = args.find((a) => !a.startsWith("--"));
const root = posArg ? path.resolve(posArg) : path.join(here, "..", "..", "data", "docs");

async function exists(p) { try { await access(p); return true; } catch (e) { return false; } }
async function* walk(dir) {
  let entries = [];
  try { entries = await readdir(dir, { withFileTypes: true }); } catch (e) { return; }
  for (const e of entries) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) yield* walk(p);
    else yield p;
  }
}
const run = (ifc) => new Promise((res) => {
  const c = spawn(process.execPath, [converter, ifc, ifc + ".frag"], { stdio: ["ignore", "inherit", "inherit"] });
  c.on("close", (code) => res(code));
});

console.error("Backfill root: " + root);
let done = 0, skip = 0, fail = 0, total = 0;
for await (const f of walk(root)) {
  if (!f.toLowerCase().endsWith(".ifc")) continue;
  total++;
  if (!force && await exists(f + ".frag")) { skip++; continue; }
  console.error("\n[" + (done + fail + 1) + "] Converting: " + path.basename(f));
  const code = await run(f);
  if (code === 0) done++; else { fail++; console.error("  -> FAILED (see error above)"); }
}
console.error(`\nBackfill complete over ${total} IFC file(s): ${done} converted, ${skip} already had .frag, ${fail} failed.`);
process.exit(fail > 0 ? 1 : 0);
