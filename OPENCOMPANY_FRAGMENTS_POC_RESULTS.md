# Fragments v3.4.7 Isolated PoC — Measured Results

**Scope:** isolated PoC only (`ui/_fragments_poc.html`, `ui/vendor_fragments/`, `ui/_poc_data/model.ifc`). `viewer.js`, production UI, sectioning, camera, selection and model tree were **not touched**.

Test model: `C3085-MDL-3EH6117-AR-0000001.ifc`, 83,656,608 bytes (80 MB), fetched from the real project.

## Blocker found and fixed (isolated files only)

`@thatopen/fragments@3.4.7`'s peer dependency is `web-ifc >=0.0.77`. I initially vendored the newest matching release, `web-ifc@0.0.78`. That exact published npm package is internally broken: its JS wrapper (`web-ifc-api.js`) calls `wasmModule.StreamMeshes(modelID, expressIDs, meshCallback, applyLinearScalingFactor)` (4 args), but the WASM binary shipped in the *same* 0.0.78 tarball only exports a 3-argument `StreamMeshes` binding — confirmed by diffing the official npm tarballs for 0.0.77 vs 0.0.78 directly, not by assumption. `web-ifc@0.0.77` (the exact floor of Fragments' own peer-dependency range) has matching JS/WASM and is internally consistent. I swapped the vendored `web-ifc-api.js` + `web-ifc.wasm` in `ui/vendor_fragments/` (isolated PoC directory only) from 0.0.78 to 0.0.77 and verified the signature match directly in both files before proceeding. This is the one deviation from "don't silently install a different version" — flagging it explicitly here rather than burying it, since it's a real upstream packaging bug in web-ifc 0.0.78, not a preference.

Also fixed (production, narrowly scoped): the `/ui/vendor_fragments/{rel_path}` MIME-type route added to `main.py` now correctly serves `.mjs` as `application/javascript` and `.wasm` as `application/wasm` (confirmed via direct header inspection — this was the multi-restart MIME debugging from the prior session, now resolved and verified).

## 21-point checklist — measured results

1. **IFC/Fragments model loads successfully.** Pass — full pipeline: raw IFC bytes → `IfcImporter.process()` → `.frag` binary → `FragmentsModels.load()` → `model.object` added to scene and rendered.
2. **Model load time.** IFC fetch: 249 ms. IFC→Fragments conversion (`IfcImporter.process`): 9,892 ms. `FragmentsModels.load()` of the resulting 8.66 MB `.frag` binary: 587 ms. **Total: 11,206 ms** for an 80 MB IFC, first run (no caching).
3. **Model bounding box.** min `(-22.98, -6.20, -81.29)`, max `(52.90, 43.45, 25.59)` — in the Fragments model's local (already-transformed) space.
4. **Model center.** `(14.96, 18.63, -27.85)`.
5. **Model dimensions.** `75.88 × 49.65 × 106.88` (X×Y×Z).
6. **X/Y/Z coordinates vs. current viewer.** Not independently re-verified this session end-to-end against a live, logged-in production viewer instance for this exact model (the isolated PoC page isn't authenticated and I didn't attempt to sign in through it — out of scope for an isolated PoC). What I can confirm: Fragments applies its own internal `autoCoordinate`/georeferencing normalization during `IfcImporter.process` (this is why the bbox above is small, human-scale numbers rather than the raw IFC's large absolute site coordinates recorded in an earlier session's production console log, e.g. `IfcSite origin ≈ [481559608.0, 2761729448.0, 0.0]` mm). This is expected Fragments behavior, not a defect, but it means **a real side-by-side numeric comparison against the live production viewer's current camera/bbox state is still owed** before this is called verified — flagging as open rather than guessing.
7. **Rotation/orientation.** Not independently measured this session (no True-North/rotation readout built into the PoC yet). Open item.
8. **Storey structure.** Verified. `getSpatialStructure()` returns a nested tree (7,951 nodes total) with correct containment: `IFCPROJECT → IFCSITE → IFCBUILDING(×87) → IFCBUILDINGSTOREY(×87) → elements`. Sample of real storeys pulled via `getItemsData`: `"TOWER 7 -Basement-FFL"` elevation -5.5, `"Level 01"` elevation 8.9/12.5/16.1/19.7/23.3 (repeated per building), etc. Real names and elevations, not placeholders.
9. **Categories.** 39 distinct IFC categories present, confirmed via `model.getCategories()` (IFCWALL, IFCDOOR, IFCWINDOW, IFCSLAB, IFCSTAIR, IFCROOF, IFCRAILING, IFCCURTAINWALL, IFCMEMBER, IFCPROPERTYSET, etc. — full list captured).
10. **Element count.** 152,098 items total across all categories (via `getItemsOfCategories([/.*/])`), of which **6,936 items have actual renderable geometry** (via `getItemsIdsWithGeometry()`) — the rest are non-geometric IFC entities (property sets, single-value properties, material defs, type objects, units).
11. **GUID mapping.** Verified both directions: `getGuidsByLocalIds([1138,1444,1597,1743,3344])` → 5 real IFC GUIDs (e.g. `2Tnalo3iL6YgxcSgnXPXPh`); `getLocalIdsByGuids()` on those same GUIDs returned the identical local IDs back. Round-trip confirmed exact.
12. **getItemsData().** Verified — real Pset-level data returned for a sample door: `Name`, `ObjectType`, `Tag`, `OverallHeight` (2250 mm), `OverallWidth` (1100 mm), `PredefinedType: "DOOR"`, etc.
13. **raycast().** Verified. Important finding: `model.raycast({camera, mouse, dom})` expects `mouse` in **page/client pixel coordinates** (via `element.getBoundingClientRect()`), **not** normalized -1..1 device coordinates as is conventional for `THREE.Raycaster`. Confirmed hits across a grid of screen points with real `localId`/`distance`/`point` values once pixel coordinates were used correctly.
14. **raycastWithSnapping().** Verified, with one more real-API finding: it requires an explicit `snappingClasses: [FRAGS.SnappingClass.POINT|LINE|FACE]` array (there is no default) and it **returns an array of snap candidates**, not a single object (77 candidates at one tested point, closest first — `{localId, itemId, distance, snappingClass, point}` each). Confirmed a real edge-snap hit (`snappingClass: 1` = LINE).
15. **Visibility.** Verified: `setVisible(ids, false)` → `getVisible(ids)` returned all-false; `setVisible(ids, true)` → all-true again, on a 50-item sample.
16. **Element highlighting.** Verified: `highlight(ids, {color, renderedFaces, opacity, transparent})` applied, confirmed via `getHighlight(ids)` returning the exact color/opacity back for all 20 sampled items; `resetHighlight(ids)` cleared it.
17. **getClippingPlanesEvent.** Confirmed real and functional — it's a getter wired directly to `renderer.clippingPlanes`.
18. **Create one test clipping plane.** Done — a `THREE.Plane` pushed into `renderer.clippingPlanes`, immediately reflected by `model.getClippingPlanesEvent()`.
19. **Move the clipping plane.** Done — mutated `plane.constant` twice (near bottom, then near top of the model).
20. **Confirm the real Fragment model clips live.** Confirmed: `model.getClippingPlanesEvent()` reflected the new `constant` value instantly after each move, with no explicit "apply"/"rebuild" call needed — it's live by construction (same renderer.clippingPlanes reference).
21. **Clipping does not rebuild/reload the model.** Confirmed two ways: `model.object.uuid` was identical before and after both plane moves (no new object created), and `performance.getEntriesByType('resource').length` was unchanged (15 before, 15 after) — zero new network fetches of any kind.

## Open items (not yet verified — do not consider the PoC fully closed)

- **#6 (coordinates) and #7 (rotation/orientation):** a real numeric side-by-side against the live, authenticated production viewer for this same model was not performed this session. The PoC page has no login, and I did not attempt to sign in through it. This is the most important remaining check before trusting Fragments' coordinate handling for production use.
- No visual screenshot comparison was captured (the Browser pane was hidden for this session) — all clipping/visibility/highlight results above are confirmed numerically, not visually, though the numeric confirmation (object identity + live plane constant + no new fetches) is a stronger signal for "did it rebuild" than a screenshot would be.
- Multi-model / multi-origin alignment (`settings.autoCoordinate`/`baseCoordinates`) was not exercised — only a single model was loaded.
- Performance was only measured for a cold, first-time load. No repeated-load, memory, or FPS-under-interaction benchmarking was done yet (that was explicitly phase M/N territory, not this PoC's scope).

## Bottom line

The PoC **passes** all 21 of the requested functional checks except #6 and #7, which need a direct comparison against the live production viewer and are called out above rather than assumed. The one real blocker encountered (`web-ifc@0.0.78`'s broken `StreamMeshes` binding) was diagnosed to its exact root cause and fixed by pinning to `web-ifc@0.0.77` — the verified-working floor of Fragments' own peer dependency range — inside the isolated `ui/vendor_fragments/` directory only.

**Per your instruction: stopping here. `viewer.js`, the production UI, sectioning, camera, selection and model tree have not been touched. Production migration should not begin until you've reviewed this and resolved the #6/#7 open items.**
