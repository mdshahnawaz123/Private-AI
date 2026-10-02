--------------------------------------------------
DETERMINISTIC IFC ANCHOR / OFFSET — INVESTIGATION
--------------------------------------------------

**Scope: investigation only.** No production file was changed. The only live
experiment was a temporary `importer.distanceThreshold = 5e6` bump in the
isolated PoC (`_fragments_poc.html`), run once to empirically confirm the
root cause below, then reverted immediately — it is not in the file anymore
(verified: `grep distanceThreshold _fragments_poc.html` now returns nothing).

## 1. Root cause, confirmed with live data

Fragments' own `IfcGeometryProcessor` (installed `@thatopen/fragments@3.4.7`,
`fragments/index.mjs`) has a **hardcoded safety guard**, not a bug:

```
index.mjs:40035   __publicField(this, "distanceThreshold", 1e5);   // on IfcImporter
index.mjs:38400   const distanceThreshold = this._serializer.distanceThreshold;
index.mjs:38401   if (distanceThreshold !== null) {
index.mjs:38404     if (tempPosition.x > distanceThreshold || tempPosition.y > distanceThreshold || tempPosition.z > distanceThreshold) {
index.mjs:38406       console.log(`Fragments: Object ${element.id} is more than ${distanceThreshold} meters away from the origin and will be skipped.`);
index.mjs:38407       return;
                     }
                   }
```

The field's own doc comment (`index.mjs:40028-40034`) says, verbatim: *"If
it's too high, it's either because your file uses absolute coordinates
(which is a very bad idea, and usually due to a poor IFC export) or because
there are objects that are very, very far away."* Fragments' authors built
this specifically to catch exactly our scenario — a file whose raw
coordinates (Easting ≈ 481,559 m, Northing ≈ 2,761,729 m) sit ~28x past the
100 km default. With `COORDINATE_TO_ORIGIN:false`, **every one of the
6,936 geometric items was silently skipped** (488+ matching console lines
captured). Raising `distanceThreshold` to 5,000,000 as a one-off diagnostic
made all 6,936 items load, with a bbox matching every other independent
measurement of this file (min ≈ [481529.25, -0.75, -2761822.42], max ≈
[481605.13, 48.90, -2761715.54]) — this *proves* the raw-coordinate import
path is otherwise correct, and that the threshold was the sole blocker. The
diagnostic change has been reverted; it is not a fix.

## 2. Where a deterministic offset could be applied — and why it can't, inside Fragments

web-ifc's own `OpenModel(data, settings)` only accepts `COORDINATE_TO_ORIGIN`
as a **boolean** (`web-ifc-api.js:71501`, `CreateSettings()`) — there is no
settings field to pass an explicit offset vector. The only API that imposes
an *explicit, caller-chosen* coordination transform is:

```
web-ifc-api.js:72206   SetGeometryTransformation(modelID, transformationMatrix)  // flat 4x4, array[16]
```

This is exactly the deterministic mechanism we need — but it must be called
**after** `OpenModel` and **before** the model is streamed, on that specific
`modelID`. Tracing Fragments' own `IfcFileReader.load()`
(`index.mjs:38348-38366`):

```js
this._ifcAPI = new WEBIFC.IfcAPI();
await this._ifcAPI.Init();
modelID = await this._ifcAPI.OpenModel(data.bytes, this.webIfcSettings);
...
// streaming begins immediately after, inside the same function
```

`this._ifcAPI` and `modelID` are **local to `IfcFileReader.load()`**, which
is itself only ever constructed and called from inside
`IfcGeometryProcessor.process()` (`index.mjs:38395` area:
`const reader = new IfcFileReader(this._serializer); ... await reader.load(data);`).
Neither the `ifcAPI` instance nor the `modelID` is ever exposed to
`IfcGeometryProcessor`, to the top-level `IfcImporter`, or to our host code —
`IfcImporter`/`IfcGeometryProcessor` communicate with `IfcFileReader`
*exclusively* through one-way callbacks (`onElementLoaded`,
`onGeometryLoaded`, `onCoordinatesLoaded`, etc.), never a handle back to the
live model.

**Conclusion: Fragments 3.4.7 does not natively support supplying a
pre-computed/deterministic coordination transform.** `webIfcSettings.COORDINATE_TO_ORIGIN`
(web-ifc's own stream-order-dependent auto-shift) is the only coordinate-shift
knob Fragments exposes, and we have already proven that mechanism unsafe
(`OPENCOMPANY_FRAGMENTS_TRANSFORM_INVESTIGATION.md`). There is no supported
subclassing or option object that reaches `SetGeometryTransformation` on
Fragments' internal model.

## 3. Smallest safe architecture that still achieves it

Since Fragments' *internal* model is unreachable, the offset has to be
applied **before the bytes ever reach Fragments** — i.e. a pre-processing
step on the raw IFC bytes themselves, entirely outside and independent of
Fragments' code:

1. **Read the deterministic anchor from the raw bytes directly** (cheap, text-level,
   no WASM needed): locate the `IFCSITE` entity, follow its
   `ObjectPlacement -> IfcLocalPlacement -> RelativePlacement(IfcAxis2Placement3D) -> Location`
   chain to the one `IFCCARTESIANPOINT` entity that anchors the whole file
   (in this project's files: express ID 104 → #103 → #102 → #101 →
   `IFCCARTESIANPOINT((481559607.99999988,2761729448.0,0.0))`, exactly the
   chain already hand-traced in the coordinate-comparison report). When
   `IFCMAPCONVERSION`/`IFCPROJECTEDCRS` is present, prefer that instead, per
   requirement #5. This read never touches a bounding box.
2. **Rewrite that one entity's coordinates** to `(0.0, 0.0, 0.0)` (or any
   small, deterministic value) in the raw byte buffer, producing a new,
   patched `Uint8Array`. Because every other placement in an IFC file is
   defined *relative to* its parent in the placement tree, shifting this
   **single** top-of-hierarchy point shifts every element's absolute
   position by exactly the same constant — deterministically, independent of
   element order, independent of web-ifc's internal streaming, independent
   of Fragments entirely. IFC SPF (STEP Physical File) is plain, re-serializable
   ASCII text, so this is a text rewrite, not a binary patch.
3. **Store the anchor as model metadata** (requirement #6) — the exact
   subtracted value (Easting/Northing/Elevation, plus which source it came
   from: `IfcMapConversion` or raw `IfcSite` placement) is recorded on the
   model record *before* the bytes are patched, so it is never lost.
4. **Hand the patched bytes to `importer.process({ bytes: patchedBytes })`**
   with `webIfcSettings.COORDINATE_TO_ORIGIN: false` (requirement #3 — no
   reliance on the auto-shift at all). Fragments now sees a file whose own
   embedded coordinates already sit near the origin, clears the
   `distanceThreshold` guard on its own, and needs **zero code changes** —
   it is processing a completely ordinary, well-behaved IFC file as far as
   it can tell.

This is the smallest change that satisfies every constraint: it needs no
Fragments source modification, no raised `distanceThreshold`, no dependency
on stream order, and the anchor itself is computed once, from IFC Site /
Map Conversion data, before any geometry streaming happens at all.

## 4. Inverse transform — recovering real Easting / Northing / Elevation

Because the pre-shift is a pure, known, constant translation (`anchor`,
already converted to this app's Y-up, metres convention via the
already-verified `ifcVecToThree` mapping — see `coordinate_transform.js`),
reconstruction is a single vector add, not a re-derivation:

```
real_E/N/Elev (Y-up, metres) = local_Fragments_point + anchor
```

and converting back to labeled Easting/Northing/Elevation for display uses
the same inverse relationship already established for `ifcVecToThree`
(three.x → Easting, -three.z → Northing, three.y → Elevation). Concretely,
for a point the user selects or measures in Fragments' (now near-origin)
local frame, the UI's real-world readout is just that point's world
position (after the OpenCompany Model Transform group's own placement is
also accounted for, same as today) plus the stored anchor — no new math
category, just one more constant to add alongside what `applyPlacementMode`
already does.

## 5. Selection, measurement, sectioning — do they need adjustment?

No structural change. The OpenCompany Model Transform design already in
place (wrapper `THREE.Group` per model; `applyPlacementMode`'s
delta-translation re-anchoring of `clip.plane`/`clip.box`, `SEC._plane`,
`SBX.box`/`planes`/`full`, `mPts`/`mObjs`/`mLabels`) operates purely in terms
of *"how much did this model's placement just change"* — it has no
dependency on which specific mode is numerically identity. Today, with no
pre-shift, `internalOrigin`/`ifcLocalOrigin`/`originToOrigin` all happen to
be identity and `sharedCoordinates` needs an offset only when
`IfcMapConversion` is present. Under the new architecture that flips:
`internalOrigin` (Fragments' own near-origin frame) becomes identity, and
`sharedCoordinates`/`ifcLocalOrigin` need `+anchor` instead. That is a
one-branch change inside `computePlacementTransform` — the group-transform
layer, the delta-reattachment mechanism, and every UI hook (selection,
properties, visibility, measurement labels, section planes) stay exactly as
already built and tested.

## 6. What still needs building (not started — awaiting approval)

- A small, dedicated raw-STEP anchor patcher: locate the anchor entity,
  parse its 3 numbers, rewrite the line, return a new `Uint8Array`. Needs a
  real (if narrow) STEP-text parser — robust enough for Revit's one-entity-
  per-line export style, with an explicit, loud failure (not a silent
  guess) if a file's layout doesn't match that assumption.
- `extractIfcInfo`'s raw-attribute reads already locate this exact entity
  chain today (`info.site.expressID`, `info.mapConversion`) — the patcher
  reuses that, not a second lookup.
- `computePlacementTransform`'s `internalOrigin`/`ifcLocalOrigin`/
  `originToOrigin`/`sharedCoordinates` branches need the sign/identity swap
  described in §5.
- Verification per requirements #16-18 (round-trip on ≥3 elements, spot
  elevation/E/N check, selection/measurement/sectioning smoke test) — to be
  run once this is implemented, in the isolated PoC, before any production
  change.

No production file has been modified. No workaround has been kept in place.
--------------------------------------------------
