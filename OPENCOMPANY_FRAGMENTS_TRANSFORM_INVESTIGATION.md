--------------------------------------------------
FRAGMENTS TRANSFORM INVESTIGATION
--------------------------------------------------

**Scope: isolated PoC / debug environment only.** No production file was modified. No IFC export setting, Revit coordinate, or production viewer was touched. The only files changed were a throwaway instrumented copy of the vendored Fragments bundle (`ui/vendor_fragments/fragments/index.debug.mjs` — a copy with `console`/`window.__fragDebug` logging added, never referenced by `_fragments_poc.html` or any production page) and this report. No permanent fix was applied anywhere.

Element:
GUID: `2Hi7Pz7ZT9N8tns68uI_Ng`
LocalId (web-ifc express ID): `46002`
Type: `IfcRoof` ("Basic Roof:AR-Roof-Generic_300mm:957646")

Raw web-ifc position (reproducing production's exact method — `ifcAPI.StreamAllMeshes(modelID, cb)`, `OpenModel(bytes, {COORDINATE_TO_ORIGIN:true})`, same settings production uses):
X: 17.045407
Y: 7.600000
Z: -21.799405

(This matches production's own live-reported "SELECTED — final world" value of (17.045, 7.600, -21.799) to the 3rd decimal place — confirms this standalone replication is measuring exactly what production measures, by the same method.)

Fragments position (`model.getPositions([46002])` / `model.getBoxes([46002])` on the real, unmodified `@thatopen/fragments@3.4.7` `IfcImporter` → `FragmentsModels.load()` pipeline):
X: 15.719771
Y: 39.503054
Z: -31.220835

Delta (Fragments − raw/production):
DX: -1.325636
DY: +31.903054
DZ: -9.421430

Raw matrix (M_raw — web-ifc `flatTransformation` for element 46002, captured via `StreamAllMeshes`, THREE.Matrix4 column-major 16-element array, scale baked in at 0.001 since the IFC's length unit is millimetres):
```
[-0.001, 0,      0,     0,
  0,     0,      0.001, 0,
  0,     0.001,  0,     0,
  17.045407, 7.6, -21.799405, 1]
```

Fragments matrix (M_fragments — the exact same field, `geometryRef.flatTransformation`, captured live inside Fragments' own `IfcGeometryProcessor` callback during a real `importer.process()` run, instrumented in place, not reconstructed):
```
[-0.001, 0,      0,     0,
  0,     0,      0.001, 0,
  0,     0.001,  0,     0,
  15.719771, 39.503054, -31.220835, 1]
```

Delta matrix (M_delta = inverse(M_raw) · M_fragments):
The rotation/scale block (the first 12 of the 16 elements) is **byte-identical** between M_raw and M_fragments — confirmed directly, not inferred. Because of that, M_delta reduces exactly to a pure translation with an identity rotation block:
```
[1, 0, 0, 0,
 0, 1, 0, 0,
 0, 0, 1, 0,
 -1.325636, 31.903054, -9.421430, 1]
```
No rotation, no scale, no axis swap. This is a clean rigid-body translation difference and nothing else.

Vertex trace for this element, raw → stored → returned (all captured directly, same instrumented run):
```
raw vertex (web-ifc, pre-scale, this element's own local geometry, first vertex): (-22723.29, -20406.99, 150) [mm, local/untransformed]
local geometry bbox (pre-scale):  min (-34945.41, -42549.41, -150)   max (34945.41, 42549.41, 150)
local geometry bbox (post-scale, metres): min (-34.945, -42.549, -0.150)  max (34.945, 42.549, 0.150)
  → this bbox is exactly symmetric about (0,0,0) in local space, so after any rigid transform its
    world-space center equals the transform's own translation component exactly — confirmed: Fragments'
    final getPositions()/getBoxes() center, (15.719771, 39.503054, -31.220835), equals M_fragments'
    translation to 5 decimal places. There is no separate "measurement definition" gap (already ruled
    out in the prior report) and this run re-confirms it with the actual raw vertex data, not just the
    final API output.
vertex stored in Fragments (via getBoxes() bbox center): (15.719770, 39.503054, -31.220840)
vertex returned by getPositions(): (15.719770, 39.503054, -31.220840)
```
Stored and returned values match each other exactly — the gap exists **before** the fragment-building step even starts, right at the point web-ifc's own `flatTransformation` is read. It is not introduced later by `Builder`/`Meshes` serialization.

Transformation introduced at:
**`web-ifc`'s own native `COORDINATE_TO_ORIGIN` auto-origin logic, inside `ifcAPI.OpenModel`/`StreamMeshes`/`StreamAllMeshes` (the WASM module itself — not in any Fragments or production JavaScript).** Specifically, the divergence is a direct consequence of **which element each pipeline streams first**:
- Production (`viewer.js`, `ifcAPI.StreamAllMeshes(modelID, cb)` — natural, file-native element order): first element streamed is express ID **21064**, whose own post-shift translation comes out at (-2.0, 0.125, -0.75) — i.e. very close to the new origin.
- Fragments (`@thatopen/fragments@3.4.7`'s `IfcGeometryProcessor.process`, which does **not** use `StreamAllMeshes` — it calls `ifcAPI.GetAllTypesOfModel()`, filters to a specific category list, explicitly moves `IFCANNOTATION` to the end, then calls `ifcAPI.StreamMeshes(modelID, idsForThatCategory, cb)` once per category): first element streamed is express ID **1138** (a door), whose own post-shift translation comes out at (-0.015, 0.049, -0.023) — also very close to the new origin.

Both pipelines' first-streamed element ends up near-zero after the shift — confirming `COORDINATE_TO_ORIGIN` anchors its shift to roughly wherever the *first geometry processed in that particular streaming call* sits. Since production and Fragments hand web-ifc two different element orderings (different first elements, 21064 vs 1138, which sit at two different real-world positions), web-ifc computes two different origin shifts, and every subsequent element — including our test roof, element 46002 — comes out translated by the difference between those two shifts. That difference is exactly the (-1.325636, +31.903054, -9.421430) delta measured above.

Likely cause:
`web-ifc`'s `COORDINATE_TO_ORIGIN` is a **stream-order-dependent, not file-absolute**, normalization. It isn't a fixed, file-wide value retrievable once via `GetCoordinationMatrix()` (that call returns identity `[0,0,0]` translation in both pipelines — already checked and ruled out as the mechanism in the prior test). It's established implicitly, the first time geometry is actually streamed in a given call, from whatever element happens to come first in that call's own ordering. Production's `StreamAllMeshes` and Fragments' per-category `StreamMeshes` calls simply don't agree on which element is "first," so they don't agree on where "the origin" is, even though both correctly honor the full `IfcLocalPlacement` hierarchy (rotation/orientation is identical between them, confirmed above) and both use the identical `COORDINATE_TO_ORIGIN: true` setting.

This is not a bug in how either pipeline reads `IfcLocalPlacement`, not a double-transform, not a rotation error, not an inverted matrix, and not anything specific to `IfcGeometryProcessor`/`Builder`/`Meshes` — those were all directly inspected and instrumented and shown to faithfully pass through whatever `flatTransformation` web-ifc itself hands them. The divergence is fully formed before Fragments' own code does anything with it.

Evidence (exact instrumentation results, all captured this session, all reproducible):
- `replaceStoreyElevation=false` / `replaceSiteElevation=false` (prior report, Test 1): no change — ruled out.
- Fragments' `webIfcSettings` default already is `{COORDINATE_TO_ORIGIN:true}` (prior report, Test 2): ruled out as a settings mismatch.
- `getBoxes()` bbox-center identical to `getPositions()` (prior report, Test 3; re-confirmed above from raw, symmetric local-space vertex data): ruled out as a measurement-definition mismatch.
- Instrumented `IfcGeometryProcessor.process`'s internal element-processing loop (the `Transform.createTransform`/`localIds.unshift(currentItem.element.id)` global-transform-building code): correctly pairs each item's ID with its own position — the index arithmetic (`items[items.length-1-i]` read together with `localIds.unshift(...)` and `gtLocalIds.unshift(...)`) is internally self-consistent; a separate, differently-named array (`localIDs`, capital, forward-pushed) exists in the same function for an unrelated purpose and is **not** what pairs with the rendered transform — flagged and ruled out as a false lead after verifying against the direct `items[]` scan (`trueIndexInItemsArray`/`trueItemPosition`), which matched Fragments' actual final output exactly.
- Direct `StreamAllMeshes` replication of production's method, run standalone against the same IFC bytes, same `COORDINATE_TO_ORIGIN:true` setting: reproduces production's own reported value for element 46002 to 3 decimal places.
- Direct comparison of M_raw vs M_fragments 4×4 matrices: rotation/scale blocks byte-identical; only the translation component differs, by exactly the measured delta.
- First-streamed-element identification in both pipelines (21064 for production's order, 1138 for Fragments' order), both landing near-zero post-shift in their own run — the direct mechanism behind the differing origins.

Production impact:
This explains the entire whole-model +31.9 m-style offset reported earlier (that was the bbox/whole-model manifestation of this same, single, per-model constant shift — every element in a model shares one `COORDINATE_TO_ORIGIN` shift per streaming call, so the whole model moves together as one rigid body, which is exactly what was observed: identical Y-dimension size, pure translation, no distortion). For OpenCompany, this means: **the discrepancy is not a Fragments integrity bug, not a Revit/IFC export problem, and not something that can be fixed by touching coordinate math in either pipeline's placement-handling code.** It is purely a byproduct of the two pipelines not streaming web-ifc's geometry in the same order. Any future Fragments integration needs to either (a) make Fragments stream in the same order production does, (b) make production stream in Fragments' order, or (c) stop relying on `COORDINATE_TO_ORIGIN`'s implicit, order-dependent shift entirely and apply an explicit, independently-computed, reproducible origin (e.g. derived once from `IfcSite`'s own placement, the same value already read and recorded in the first comparison report) on top of `COORDINATE_TO_ORIGIN:false` raw output, in both pipelines, so neither depends on stream order at all.

Recommended next step (smallest possible controlled test — not yet attempted, needs your approval before any code changes):
In the isolated PoC only, set `importer.webIfcSettings = {COORDINATE_TO_ORIGIN:false}` (now that we know this flag's shift is unreliable/order-dependent, forcing it off everywhere is the honest, controlled first step), then apply a **single, explicit, manually-computed translation** equal to the raw `IfcSite` placement origin already recorded in `OPENCOMPANY_FRAGMENTS_COORDINATE_COMPARISON.md` (Easting 481559.608 m, Northing 2761729.448 m, Elevation 0.0 m) to Fragments' output only, and re-run the exact same GUID check. If element 46002 then lands within centimetres of production's (17.045, 7.600, -21.799), that confirms an explicit, file-anchored origin (not a stream-order-dependent one) is the correct fix, and the same explicit origin could in principle also be applied to production for full future consistency — a decision for you, not something to apply unilaterally. I have not run this test yet; flagging it as the next concrete, controlled step per your "no fix without approval" instruction.

No production files changed.
No permanent fix applied.
--------------------------------------------------
