# Importer Transformation Test — replaceStoreyElevation / replaceSiteElevation / COORDINATE_TO_ORIGIN

**Status: READ-ONLY / isolated PoC only.** No permanent code change was made anywhere — production `viewer.js` untouched, and the isolated PoC's own files (`_fragments_poc.html`, `vendor_fragments/`) were also left unmodified; every test below ran as a transient, in-browser experiment via the browser console against the already-loaded PoC page, then discarded.

Per your instruction, nothing here has been "fixed." This documents exactly what was tested and what the data shows, including two **negative** results — hypotheses that did NOT explain the +31.90 m discrepancy, so they are ruled out rather than left ambiguous.

## Baseline (unchanged from the first comparison report)

GUID `2Hi7Pz7ZT9N8tns68uI_Ng` (`IfcRoof`, "Basic Roof:AR-Roof-Generic_300mm:957646"), local ID 46002 in the Fragments model.

- Production (`viewer.js`'s own "SELECTED — final world"): **(17.045, 7.600, -21.799)**
- Fragments (baseline PoC, `web-ifc@0.0.77`, defaults): **(15.720, 39.503, -31.221)**
- ΔY = +31.903 m

## Test 1 — `replaceStoreyElevation = false`, `replaceSiteElevation = false`

Set directly on a fresh `IfcImporter` instance before calling `.process()` on the same IFC bytes, loaded as a second, independent model alongside the baseline (both models live in the same page simultaneously, so this is a true apples-to-apples re-run, not a different session):

```js
importer.replaceStoreyElevation = false;
importer.replaceSiteElevation = false;
```

**Result: byte-for-byte identical output.** Bounding box matched the baseline to the last printed decimal digit, and GUID `2Hi7Pz7ZT9N8tns68uI_Ng`'s position came back **exactly (15.71977, 39.50305, -31.22084)** — the same as baseline, same ΔY = +31.903 m.

**Conclusion: ruled out.** These two flags have zero effect on this model's output. My hypothesis in the first comparison report (`OPENCOMPANY_FRAGMENTS_COORDINATE_COMPARISON.md`, §3) — that `replaceStoreyElevation`/`replaceSiteElevation` were responsible — is **incorrect** and is withdrawn.

## Test 2 — `web-ifc`'s own `OpenModel` settings (`COORDINATE_TO_ORIGIN`)

While investigating further, I found that `web-ifc`'s `OpenModel(bytes, settings)` has a `COORDINATE_TO_ORIGIN` setting production explicitly passes (`viewer.js` line ~109: `ifcAPI.OpenModel(data, { COORDINATE_TO_ORIGIN:true })`, with a comment explaining it normalizes large survey coordinates for float precision). I checked whether Fragments' `IfcImporter` sets this the same way.

**Direct `web-ifc` test** (bypassing Fragments entirely, calling `OpenModel` myself with each setting and reading the raw `flatTransformation` for element 46002):

| Setting | `flatTransformation` translation (x, y, z) |
|---|---|
| `{COORDINATE_TO_ORIGIN: true}` | (-22.72, -0.15, 20.41) — human-scale |
| `{COORDINATE_TO_ORIGIN: false}` | (481567.95, 44.95, -2761772.35) — raw survey-scale |
| `{}` (default) | (481567.95, 44.95, -2761772.35) — same as `false` |

This confirmed the flag has a large, real effect on raw web-ifc output, as expected.

**Then I checked what `IfcImporter` actually uses.** Reading `@thatopen/fragments@3.4.7`'s installed source directly (not assuming): `IfcImporter`'s `webIfcSettings` field **already defaults to `{ COORDINATE_TO_ORIGIN: true }`** — the same setting production uses. I set `importer.webIfcSettings = { COORDINATE_TO_ORIGIN: true }` explicitly anyway and re-ran the full import.

**Result: again, byte-for-byte identical to baseline** — because the default was already what I was setting. GUID `2Hi7Pz7ZT9N8tns68uI_Ng` still came back at (15.71977, 39.50305, -31.22084).

**Conclusion: ruled out.** Fragments already requests the same `COORDINATE_TO_ORIGIN:true` web-ifc normalization production uses. This is not where the two pipelines diverge.

## Test 3 — is `getPositions()` even measuring the same thing as production's "final world"?

Production's own "final world" value is explicitly a **mesh bounding-box center** (`viewer.js`: `mesh.geometry.computeBoundingBox(); const wc = mesh.geometry.boundingBox.getCenter(...)`). I checked whether Fragments' `getPositions()` is measuring the same thing, using `model.getBoxes([46002])` (Fragments' own per-item bounding-box API) and computing the center myself the same way production does:

```
getBoxes([46002]) → min (-19.226, 39.353, -73.770), max (50.665, 39.653, 11.329)
bbox center = (15.720, 39.503, -31.221)
getPositions([46002]) = (15.720, 39.503, -31.221)
```

**Identical.** `getPositions()` is a bounding-box center, exactly like production's metric — ruled out as a measurement-definition mismatch. (Side note, independently confirmed by this: the roof's own Y-extent is only 39.353–39.653, a 0.3 m span — matching its real ~300 mm thickness. It is genuinely sitting flat at Y≈39.5 in Fragments' output. This is real geometry positioning, not a bbox artifact.)

## Test 4 — does web-ifc's own per-element placement already show the gap, or does it appear later?

I compared the **raw `flatTransformation` translation web-ifc reports for element 46002 directly** (captured in Test 2's standalone script, with `COORDINATE_TO_ORIGIN:true`, matching both production's and Fragments' setting) against Fragments' **final** reported position for the same element:

| | X | Y | Z |
|---|---:|---:|---:|
| Raw web-ifc `flatTransformation` for element 46002 | -22.72 | -0.15 | 20.41 |
| Fragments' final `getPositions()`/`getBoxes()` center | 15.72 | 39.50 | -31.22 |
| Difference | +38.44 | +39.65 | -51.63 |

This is a **large, three-axis difference** — not the clean single-axis ~31.9 m vertical shift seen when comparing Fragments to *production*. That tells me something important: **web-ifc's own raw per-element placement output (with the correct, shared `COORDINATE_TO_ORIGIN:true` setting) does not by itself match Fragments' final geometry position either.** Something inside Fragments' own pipeline — after it reads `flatTransformation` from web-ifc, during its own mesh/fragment-building step (`IfcGeometryProcessor` → `Builder`/`Meshes`, the code that bakes per-item geometry into the `.frag` binary) — applies **additional** repositioning that I have not traced to a specific line. This is one level more specific than "the +31.9 m gap is unexplained": the gap is not coming from web-ifc's settings or from web-ifc's output at all. It is introduced somewhere inside Fragments' own geometry-baking step, downstream of `flatTransformation`.

## Where this leaves the investigation

Four things tested, four hypotheses addressed, with real data, not assumption:

1. `replaceStoreyElevation`/`replaceSiteElevation` — **ruled out** (no effect at all).
2. `COORDINATE_TO_ORIGIN` web-ifc setting mismatch — **ruled out** (Fragments already defaults to the same value production uses).
3. bbox-center vs. placement-origin measurement mismatch — **ruled out** (both production and Fragments measure bbox center; confirmed identical by direct computation).
4. Whether the gap originates in web-ifc's own output — **ruled out as the sole cause** (web-ifc's raw per-element placement, under the shared setting, differs from Fragments' final position by a different, three-axis amount than the clean vertical-only gap seen vs. production — meaning Fragments' own internal geometry-baking step is where the additional, still-unidentified transformation is introduced).

**Recommended next step (not yet attempted, needs your go-ahead):** this now points specifically at Fragments' `Builder`/`Meshes` geometry-baking code (inside `IfcGeometryProcessor.process`, after the `onElementLoaded` callback fires with `position:[px,py,pz]`) as the place to trace next — comparing that raw `px,py,pz` value directly against what ends up in the `.frag` binary and ultimately in `getPositions()`. That requires either temporary instrumentation of Fragments' own (vendored, isolated-PoC-only) code to log intermediate values, or very careful manual tracing of the `Builder`/flatbuffer serialization path. I have not done either yet — flagging it as the precise next step rather than guessing further.

## Bottom line

```
Test 1 (replaceStoreyElevation / replaceSiteElevation = false): NO CHANGE — hypothesis ruled out
Test 2 (COORDINATE_TO_ORIGIN mismatch): NO CHANGE — hypothesis ruled out (Fragments already uses the same setting)
Test 3 (bbox-center vs. placement-origin measurement difference): RULED OUT — both measure bbox center, confirmed identical methodology
Test 4 (does web-ifc's own raw output already explain it): RULED OUT AS SOLE CAUSE — the gap changes shape (3-axis, not clean 1-axis) between web-ifc's raw output and Fragments' final position, meaning Fragments' own geometry-baking step introduces an additional, still-unidentified transform
+31.90 m discrepancy (Fragments vs. production): STILL PRESENT, root cause narrowed to Fragments' internal Builder/Meshes geometry-baking step, not yet pinpointed to a specific line
```

No permanent change was made. No translation, hard-coded correction, or workaround was applied anywhere — per your instruction, the discrepancy remains open and is reported, not patched.
