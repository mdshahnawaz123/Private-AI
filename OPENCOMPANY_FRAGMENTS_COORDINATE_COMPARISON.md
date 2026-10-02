# OPENCOMPANY — Fragments PoC vs Production Coordinate Comparison

**Status: READ-ONLY.** No change was made to `viewer.js`, production UI, sectioning, camera, selection, model tree, engine, or dependencies. Production was only read via its own existing, pre-existing read-only diagnostic (`btnDebug` → `buildDebug()`, already in `viewer.js`) and by clicking one element to select it.

Model: `C3085-MDL-3EH6117-AR-0000001.ifc` (same file in both systems — confirmed via the iframe's own `src` query string in production, and the same file fetched by the PoC).

**web-ifc version note (per your instruction):** the PoC remains pinned to `web-ifc@0.0.77`. Reason, for the record: `web-ifc@0.0.78` (the newest release satisfying Fragments' own `>=0.0.77` peer dependency) is internally broken — its JS wrapper calls the WASM binary's `StreamMeshes` with 4 arguments, but the WASM build shipped in that same 0.0.78 tarball only exports a 3-argument binding (confirmed by diffing the official npm tarballs directly). `web-ifc@0.0.77` has matching JS/WASM. No further web-ifc version change was made or attempted this task.

---

## 1. How each system currently computes the transform

**Production (`viewer.js`, read directly, not changed):**
- Uses `ifcAPI.GetFlatMesh`-style geometry (web-ifc's own flattened mesh pipeline), which already bakes the *entire* `IfcLocalPlacement` hierarchy (Project → Site → Building → Storey → Element) into each mesh's vertices. Production does **not** apply any additional rotation or translation to the geometry itself.
- `coordMatrix` (`ifcAPI.GetCoordinationMatrix`) is only used to align a *second* model onto the *first* model's origin when multiple IFCs are loaded together (`rels.length>1`). For this single-model test it is identity — confirmed in the panel: `Origin shift (coord. matrix t): [0.00, 0.00, 0.00]`.
- `bboxAll()` unions the bounding boxes of all loaded meshes, **explicitly skipping any mesh flagged `userData.outlier`** (there's a dedicated "Hide stray geometry (survey-coordinate slivers)" toggle, `btnStray`, in the toolbar — this is a known, named feature, not incidental).
- North handling is **view-only**: `detectNorthAngle()` reads the `IfcSite`/`IfcBuilding` placement's `RefDirection` and rotates only the **camera**, never the geometry (this is explicit in the code's own comments: "We DO NOT rotate or move the geometry. We only detect the site rotation and rotate the CAMERA").
- Storey `elev` as shown in the debug panel is the storey's own (I didn't verify whether raw/local or accumulated — see §4, this is now a flagged open question, not an assumption).

**Fragments PoC (`@thatopen/fragments@3.4.7`, `IfcImporter`):**
- Converts IFC → its own `.frag` binary via `IfcGeometryProcessor`, which also walks the full placement hierarchy and bakes world transforms into geometry (confirmed earlier: items came out in plausible small human-scale local coordinates, not raw survey coordinates).
- Has its own `distanceThreshold` (default `1e5`) for filtering far-away "outlier" geometry during import, and its own `replaceStoreyElevation`/`replaceSiteElevation` options (on by default) which explicitly compute an **absolute, accumulated** elevation per storey rather than using the raw local `IfcBuildingStorey.Elevation` attribute (per Fragments' own inline doc comment, read directly from the installed package).
- `model.box` / `model.getCoordinates()` / `model.getPositions()` give geometry already baked the same way.

Both systems bake the full placement hierarchy into geometry and don't apply any further transform at read time. The difference is in *what they do with far-away "stray" geometry* and *how storey elevation is reported* — not in whether they honor `IfcLocalPlacement`.

---

## 2. Comparison table

| Parameter | Production | Fragments | Difference | Status |
|---|---:|---:|---:|---|
| Min X | -19.95 | -22.98 | -3.03 | see §5 |
| Min Y | -38.10 | -6.20 | **+31.90** | **FLAG** |
| Min Z | -66.69 | -81.29 | -14.60 | see §5 |
| Max X | 53.93 | 52.90 | -1.03 | see §5 |
| Max Y | 11.55 | 43.45 | **+31.90** | **FLAG** |
| Max Z | 25.00 | 25.59 | +0.59 | close |
| Center X | 16.99 | 14.96 | -2.03 | see §5 |
| Center Y | -13.28 | 18.63 | **+31.90** | **FLAG** |
| Center Z | -20.85 | -27.85 | -7.01 | see §5 |
| Dimension X | 73.88 | 75.88 | +2.00 | see §5 |
| Dimension Y | 49.65 | 49.65 | **0.00** | **exact match** |
| Dimension Z | 91.69 | 106.88 | +15.19 | see §5 |
| Rotation X/Y/Z | not independently isolated | not independently isolated | — | **UNVERIFIED** (see §6) |

All values in metres, both systems' own native reporting units.

**Single-element cross-check (GUID-matched, not just bbox-level):** selected an `IfcRoof` in the live production viewer by clicking it — GUID `2Hi7Pz7ZT9N8tns68uI_Ng`. Looked up the *exact same GUID* in the Fragments PoC via `getLocalIdsByGuids`/`getPositions`:

| | Production (`SELECTED — final world`) | Fragments (`getPositions`) | Diff |
|---|---:|---:|---:|
| X | 17.045 | 15.720 | -1.325 |
| Y | 7.600 | 39.503 | **+31.903** |
| Z | -21.799 | -31.221 | -9.422 |

The **Y offset reproduces to within 0.003 m of the whole-model bbox-level offset** (31.90 vs 31.903). This is not noise — it's a real, consistent, system-wide vertical translation between the two pipelines' output for identical input geometry.

---

## 3. What's responsible for the Y offset (recommendation, not a fix)

I did not trace this to one line of code with certainty — that would require instrumenting both pipelines' placement-accumulation step directly, which I didn't do (would mean modifying code to add logging, which this task's constraints don't permit). What the evidence supports:

- It's a **pure translation along one axis**, not a rotation or scale error — the offset is the same sign and nearly the same magnitude at both the single-element level and the whole-bbox level, and X/Z differences don't show the axis-mixing a rotation would produce.
- Production explicitly does **not** re-center or re-origin the model (`coordMatrix` is identity here; no translation is applied beyond what web-ifc's own flattened mesh already encodes).
- Fragments' `IfcImporter` has its own `replaceSiteElevation`/`replaceStoreyElevation` logic (on by default) that recomputes **absolute site elevation** by walking placement offsets itself, rather than trusting the raw attribute chain the way web-ifc's flat mesh does. A ~31.9 m vertical reinterpretation is consistent with Fragments computing (or mis-accumulating) an elevation reference differently than web-ifc's baked-in placement chain for this particular file's `IfcSite`/`IfcBuilding` nesting.

**My recommendation (for your approval, not yet implemented):** before any production migration, test loading this same model through Fragments with `replaceStoreyElevation` and `replaceSiteElevation` both set to `false` on the `IfcImporter`, and re-run this same single-GUID cross-check. If the Y offset disappears, that confirms the elevation-replacement logic as the cause and gives a one-line, well-understood fix (a config flag, not a coordinate hack). I have not made this change — it needs your sign-off per your instruction.

---

## 4. Storey comparison — a second, independent finding

I compared storeys **by name**, not by list position (list order/dedup differs between the two systems, so index-based comparison would be misleading).

**First storey (basement):** `TOWER 7 -Basement-FFL` — production -5,500 mm (-5.5 m), Fragments -5.5 m. **Exact match.**

**Highest storey:** Production's `TOWER 7 - Building Top` sits at 46,400 mm (46.4 m). **This name does not appear anywhere in Fragments' 87 storeys at all.** Neither does `TOWER 7 - RF-FFL` (44.9 m) or `TOWER 7 - GF-FFL` (1.5 m).

**Middle storeys — the real finding:** Production lists 13 distinctly-named Tower 7 storeys (`GF-FFL` 1.5 m, `1st-FFL` 4.5 m, `2nd-FFL` 8.9 m, `3rd-FFL` 12.5 m, ... `11th-FFL` 41.3 m, `RF-FFL` 44.9 m, `Building Top` 46.4 m). Of these, **only the basement name survived into Fragments' output.** The other 11 elevation values (4.5, 8.9, 12.5, 16.1, 19.7, 23.3, 26.9, 30.5, 34.1, 37.7, 41.3) *are* present in Fragments' storey list — but attached to the wrong name: Fragments reports them as generic `Level 01` / `Level 01-Partial Plans` / `Level 01 TYPE A` / `Level 01 TYPE H` / `Level 01 TYPE J`, names that in *production's* list sit at elevation **0.00 mm**, not these values.

So: the numeric elevation values for 11 of 13 Tower-7 storeys **do** show up in Fragments' data, matched almost certainly by correct underlying placement math — but the **Name attribute Fragments reports for those local IDs is wrong** (it's picking up a different, generically-named storey's `Name`, not the Tower-7-specific one). I did not dig further into *why* — that requires inspecting the IFC's own `IfcBuildingStorey` entity list and relationship graph directly, which is a real investigation task in itself, not something to guess at. Flagging this as a second, independent, and separately concerning finding — this is a **data-integrity** issue (wrong storey names, which the storey dropdown/model tree UI depends on), distinct from the Y-offset **geometry** issue in §3.

---

## 5. Likely explanation for the remaining X/Z/dimension differences

Production has an explicit, named feature: a "Hide stray geometry (survey-coordinate slivers)" toggle (`btnStray`), and `bboxAll()` explicitly excludes meshes flagged `userData.outlier` from the bounding box. The Fragments PoC's bbox was read directly off `model.box` with no equivalent outlier exclusion applied. The remaining X (~1–3 m) and Z (~7–15 m) differences are the right order of magnitude for a handful of stray/far geometry slivers being included in one bbox and excluded from the other — but I have **not confirmed this directly** (would require identifying the specific stray elements and checking their presence/absence on each side). Flagging as the most likely explanation, not a confirmed one.

---

## 6. Rotation — UNVERIFIED, explicitly

I did not isolate a true rotation comparison. What I can say: the differences found (§2, §3) are consistent with pure translation, not rotation — if there were a rotation mismatch between the two pipelines, X and Z would show position-dependent (not constant) divergence, and they don't show that pattern in the one sample tested. But one GUID is not enough points to rule out a small rotation confidently (a true test needs 3+ non-collinear matched points, enough to fit/compare a full transform). Both systems report `True North (context): 0.000° from +Y` identically. Production's "Site rotation applied to view: 180.000°" is explicitly camera-only per the code comments in §1 and should have no geometry analog to check in Fragments at all. I'm marking Rotation **UNVERIFIED** rather than guessing PASS.

---

## 7. Visual comparison

Attempted but not completed to a useful standard: the production viewer's embedded panel in this session's layout is narrow and the model's "fit view" (after including stray geometry) renders the building as a thin sliver far from camera, making reliable screen-coordinate clicking difficult. I got one successful element selection (the GUID used in §2/§3) but a second attempted click missed geometry twice. I did not pursue a full side-by-side screenshot comparison — the numeric, GUID-matched comparison in §2/§3 is more conclusive than a visual check would be for this specific question (coordinate/rotation correctness), so I prioritized that instead of spending more time on imprecise clicking.

---

## 8. Final output

```
COORDINATES: FAIL (systematic +31.9 m vertical offset found, reproducible at both bbox and single-element/GUID level; root cause hypothesis given in §3, not yet confirmed or fixed)

ROTATION: UNVERIFIED (no rotation mismatch detected in available data, but only one matched point was tested — insufficient to confirm)

STOREYS: FAIL (11 of 13 Tower-7 storeys have correct elevation but WRONG Name in Fragments' output; 2 of 13 — GF-FFL, and either RF-FFL or Building Top — not found at all)

NORTH: PASS (True North context angle matches exactly: 0.000° in both; production's north handling is camera-only by design, nothing in Fragments' geometry should need to replicate it)

OVERALL: NOT READY FOR PRODUCTION MIGRATION
```

Two concrete, scoped issues block migration: (1) the ~31.9 m vertical offset (§3) and (2) the storey-name mismatch (§4). Both have a specific, testable next step (§3's `replaceStoreyElevation`/`replaceSiteElevation: false` experiment; §4's need to inspect the IFC's storey entity/relationship graph directly) — neither has been attempted yet, pending your approval, per your instruction not to auto-correct.
