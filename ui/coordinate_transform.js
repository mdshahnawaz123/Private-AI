// ============================================================================
// OpenCompany Model Transform -- coordinate / placement module.
// ----------------------------------------------------------------------------
// Shared, framework-agnostic ES module used by BOTH the isolated Fragments PoC
// and (after validation there) the production viewer. It implements ONLY the
// layer between "model geometry as loaded" and "where it sits in the federated
// scene":
//
//   IFC/Revit Coordinates -> [engine geometry, untouched] -> OpenCompany Model
//   Transform (THIS FILE) -> Federated Scene -> Three.js
//
// Hard rules this file enforces by construction:
//  - Never reads or writes a vertex buffer. Every function here returns a
//    {position, quaternion} pair meant to be applied to a per-model WRAPPER
//    Object3D (a THREE.Group that already sits above the model's own root
//    object/group) -- never to the model's own geometry.
//  - Bounding-box math is used ONLY by the "centerToCenter" mode. Every other
//    mode is physically unable to read a bounding box (see
//    computePlacementTransform below) -- bbox-center must never be used to
//    guess a BIM coordinate.
//  - Nothing here is fabricated. When a value (a Survey Point / Project Base
//    Point marker, an IfcMapConversion, a CRS) isn't actually present in the
//    IFC, the corresponding field is null and the caller is expected to show
//    that plainly rather than inventing a number.
// ============================================================================

import * as THREE from "three";

function _dr(v) { return (v && v.value !== undefined) ? v.value : v; }

// Raw IFC attribute values (IfcCartesianPoint.Coordinates etc, as returned by
// GetLine()) are in the IFC file's OWN native convention: Z is up. web-ifc's
// flatTransformation (what geometry is actually baked with) already converts
// to this app's Y-up convention. The mapping below -- three(x,y,z) =
// ifc(x, z, -y) -- was verified empirically for this project's file by
// comparing a raw placement-chain composition against the SAME element's
// verified flatTransformation translation (both landed within the element's
// own few-metre local geometric offset of each other); it is applied ONLY to
// the explicit fallback paths below (no marker/site geometry to cross-check
// against directly), and is never substituted for a flatTransformation-based
// value when one is available.
function ifcVecToThree(arr, metres) {
  return new THREE.Vector3(arr[0] * metres, arr[2] * metres, -arr[1] * metres);
}

// Geometry is loaded with COORDINATE_TO_ORIGIN:false throughout this app --
// web-ifc applies no implicit, stream-order-dependent shift (see
// OPENCOMPANY_FRAGMENTS_TRANSFORM_INVESTIGATION.md for why that shift was
// unsafe to build on). That means whatever a model's engine hands back
// ("Internal Origin") already IS the literal, un-shifted IFC coordinate
// value ("IFC Local Origin") and already IS each model's own local-frame
// origin ("Origin to Origin"). The three are kept as separate, named modes
// for BIM vocabulary clarity and for multi-model federation (a future model
// loaded with a DIFFERENT engine/setting could make them diverge again), but
// under this importer's convention all three compute to the same identity
// transform -- documented here rather than left as an unexplained coincidence.
export const PLACEMENT_MODES = [
  {
    id: "sharedCoordinates",
    label: "Shared Coordinates",
    authoritative: true,
    hint: "IFC/Revit Shared Coordinates -- IfcMapConversion (Eastings/Northings/OrthogonalHeight) when present, otherwise the raw IfcSite/placement origin this file was exported with. Treated as the BIM source of truth.",
  },
  {
    id: "surveyPoint",
    label: "Survey Point",
    hint: "Places the detected Survey Point marker at the world origin. Falls back to the Shared-Coordinates origin, clearly flagged, when this export does not carry a distinct Survey Point entity.",
  },
  {
    id: "projectBasePoint",
    label: "Project Base Point",
    hint: "Places the detected Project Base Point marker at the world origin. Falls back to the Shared-Coordinates origin, clearly flagged, when this export does not carry a distinct Project Base Point entity.",
  },
  {
    id: "internalOrigin",
    label: "Internal Origin",
    hint: "The importing engine's own working frame. With this importer's COORDINATE_TO_ORIGIN:false setting this is the same as IFC Local Origin -- a technical artifact of this software stack, not a BIM concept.",
  },
  {
    id: "centerToCenter",
    label: "Center to Center",
    hint: "Placement convenience only: centers this model's own bounding box at the origin. This is NOT a BIM coordinate system and is never used to infer one.",
  },
  {
    id: "originToOrigin",
    label: "Origin to Origin",
    hint: "Placement convenience only: shows this model at its own local placement origin, unmoved. Useful for federating several IFCs by their own local origins when they do not share real survey coordinates. Not a BIM coordinate system.",
  },
  {
    id: "ifcLocalOrigin",
    label: "IFC Local Origin",
    hint: "The literal, un-shifted coordinates as written in the IFC file. For a survey-scale export this can sit far from (0,0,0) -- that is expected, not an error.",
  },
];

// ---------------------------------------------------------------------------
// Matrix-world-aware bounding box helpers.
// ---------------------------------------------------------------------------
// Production's existing bbox helpers (bboxAll, classifyStrays, element
// diagnostics) read `mesh.geometry.boundingBox` directly, which is LOCAL
// geometry space. That was safe only because every model previously sat at
// identity in its parent group. Once a model's wrapper group can carry a
// real placement transform, those call sites must go through matrixWorld.
export function worldBox(mesh) {
  if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
  mesh.updateMatrixWorld();
  return mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld);
}

export function worldBoxForMeshes(meshes) {
  const box = new THREE.Box3();
  meshes.forEach((m) => box.union(worldBox(m)));
  return box;
}

// ---------------------------------------------------------------------------
// Synchronous, raw-attribute extraction (cheap -- reads already-parsed IFC
// line data, does not stream geometry). Works against any already-open
// web-ifc model regardless of what COORDINATE_TO_ORIGIN setting it was
// opened with, because GetLine() returns raw STEP attribute values, which
// COORDINATE_TO_ORIGIN never touches (only StreamMeshes' flatTransformation
// is affected by that setting).
// ---------------------------------------------------------------------------
export function extractIfcInfo(ifcAPI, WebIFC, modelID) {
  const info = {
    lengthUnit: { label: "?", metres: 1 },
    trueNorthDeg: null,
    site: { origin: null, refDir: null, expressID: null },
    mapConversion: null,
    projectedCRS: null,
    markerCandidates: { surveyPoint: null, projectBasePoint: null }, // expressIDs, if named markers are found
  };

  try {
    const proj = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCPROJECT);
    if (proj.size()) {
      const pr = ifcAPI.GetLine(modelID, proj.get(0), true);
      const units = (pr.UnitsInContext && pr.UnitsInContext.Units) || [];
      for (const u of Array.isArray(units) ? units : []) {
        const ut = u && u.UnitType && String(_dr(u.UnitType));
        if (ut && ut.indexOf("LENGTHUNIT") >= 0) {
          const name = String(_dr(u.Name) || ""), prefix = String(_dr(u.Prefix) || "").replace(/[.]/g, "");
          const pmap = { MEGA: 1e6, KILO: 1e3, HECTO: 1e2, DECA: 1e1, "": 1, DECI: 1e-1, CENTI: 1e-2, MILLI: 1e-3, MICRO: 1e-6 };
          const metres = pmap[prefix] !== undefined ? pmap[prefix] : 1;
          info.lengthUnit = { label: (prefix ? prefix + "." : "") + name.replace("IFC", "").replace(/[.]/g, ""), metres };
          break;
        }
      }
    }
  } catch (e) {}

  try {
    const ctxs = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCGEOMETRICREPRESENTATIONCONTEXT);
    for (let i = 0; i < ctxs.size(); i++) {
      const c = ifcAPI.GetLine(modelID, ctxs.get(i), true);
      const tn = c.TrueNorth && c.TrueNorth.DirectionRatios;
      if (tn && tn.length >= 2) { info.trueNorthDeg = Math.atan2(_dr(tn[0]), _dr(tn[1])) * 180 / Math.PI; break; }
    }
  } catch (e) {}

  try {
    const ids = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCSITE);
    if (ids.size()) {
      const eid = ids.get(0);
      const el = ifcAPI.GetLine(modelID, eid, true);
      const rp = el.ObjectPlacement && el.ObjectPlacement.RelativePlacement;
      const loc = rp && rp.Location && rp.Location.Coordinates;
      const rd = rp && rp.RefDirection && rp.RefDirection.DirectionRatios;
      info.site = { origin: loc ? loc.map(_dr) : null, refDir: rd ? rd.map(_dr) : null, expressID: eid };
    }
  } catch (e) {}

  try {
    if (WebIFC.IFCMAPCONVERSION) {
      const ids = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCMAPCONVERSION);
      if (ids.size()) {
        const mc = ifcAPI.GetLine(modelID, ids.get(0), true);
        info.mapConversion = {
          eastings: _dr(mc.Eastings), northings: _dr(mc.Northings), orthogonalHeight: _dr(mc.OrthogonalHeight),
          xAxisAbscissa: _dr(mc.XAxisAbscissa), xAxisOrdinate: _dr(mc.XAxisOrdinate), scale: _dr(mc.Scale),
        };
      }
    }
  } catch (e) {}

  try {
    if (WebIFC.IFCPROJECTEDCRS) {
      const ids = ifcAPI.GetLineIDsWithType(modelID, WebIFC.IFCPROJECTEDCRS);
      if (ids.size()) {
        const crs = ifcAPI.GetLine(modelID, ids.get(0), true);
        info.projectedCRS = { name: _dr(crs.Name) || null, description: _dr(crs.Description) || null };
      }
    }
  } catch (e) {}

  // Survey Point / Project Base Point: Revit does not always export these as
  // distinct IFC entities. Only record one when a clearly-named marker is
  // actually present in this file -- never invent a value.
  try {
    const markerTypes = [WebIFC.IFCBUILDINGELEMENTPROXY, WebIFC.IFCANNOTATION].filter((t) => t !== undefined);
    for (const t of markerTypes) {
      let ids; try { ids = ifcAPI.GetLineIDsWithType(modelID, t); } catch (e) { continue; }
      for (let i = 0; i < ids.size(); i++) {
        let el; try { el = ifcAPI.GetLine(modelID, ids.get(i), true); } catch (e) { continue; }
        const tag = (String(_dr(el.Name) || "") + " " + String(_dr(el.ObjectType) || "")).toLowerCase();
        if (!info.markerCandidates.surveyPoint && tag.indexOf("survey point") >= 0) info.markerCandidates.surveyPoint = ids.get(i);
        if (!info.markerCandidates.projectBasePoint && tag.indexOf("project base point") >= 0) info.markerCandidates.projectBasePoint = ids.get(i);
      }
    }
  } catch (e) {}

  return info;
}

// ---------------------------------------------------------------------------
// Async marker resolution.
// ---------------------------------------------------------------------------
// With this importer's COORDINATE_TO_ORIGIN:false convention, whatever the
// host's own already-loaded model hands back for an element IS the true,
// un-shifted IFC position already -- there is no separate "internal shift"
// to measure or undo (see the PLACEMENT_MODES comment above). So resolving a
// Survey Point / Project Base Point marker's true position is just asking
// the host to look up that ONE element's position through whatever
// mechanism it already has -- no throwaway second model, no cross-check.
//
// `getTruePosition(expressID)` is supplied by the caller: production passes
// a function that runs a single-element StreamMeshes against its own
// already-open (COORDINATE_TO_ORIGIN:false) model; Fragments-based callers
// pass `model.getPositions([id]).then(r => r[0])`. Returning null/undefined
// means "could not resolve" (e.g. the entity has no geometry) -- the caller
// then falls back to the raw placement attribute, explicitly flagged.

/**
 * Full orchestration: combines the sync raw-attribute extraction with
 * resolving Survey Point / Project Base Point markers (when present) to
 * their true positions, so computePlacementTransform() can stay pure and
 * synchronous.
 *
 * @param {object} args
 * @param {WebIFC.IfcAPI} args.ifcAPI   - the host's already-open ifcAPI (for the sync raw reads)
 * @param {object}        args.WebIFC   - the WebIFC module namespace (for type constants)
 * @param {number}        args.modelID  - the host's already-open model (must be COORDINATE_TO_ORIGIN:false)
 * @param {(expressID:number)=>Promise<THREE.Vector3|null>} args.getTruePosition
 */
export async function buildPlacementInfo({ ifcAPI, WebIFC, modelID, getTruePosition }) {
  const info = extractIfcInfo(ifcAPI, WebIFC, modelID);
  const metres = info.lengthUnit.metres;

  async function resolveMarker(expressID) {
    if (expressID != null && typeof getTruePosition === "function") {
      try {
        const p = await getTruePosition(expressID);
        if (p) return { offset: p.clone().multiplyScalar(-1), found: true, isApprox: false };
      } catch (e) {}
    }
    // No distinct marker geometry to resolve -- fall back to the raw
    // IfcSite placement attribute, converted to this app's Y-up convention
    // and to metres, clearly flagged as approximate.
    if (info.site.origin) {
      const trueXYZ = ifcVecToThree(info.site.origin, metres);
      return { offset: trueXYZ.multiplyScalar(-1), found: false, isApprox: true };
    }
    return { offset: null, found: false, isApprox: false };
  }

  info.markers = {
    surveyPoint: await resolveMarker(info.markerCandidates.surveyPoint),
    projectBasePoint: await resolveMarker(info.markerCandidates.projectBasePoint),
  };

  return info;
}

// ---------------------------------------------------------------------------
// Pure placement-transform computation. No IFC access, no network, no
// bounding-box read EXCEPT in the one branch that is explicitly allowed to
// use one (centerToCenter).
// ---------------------------------------------------------------------------
export function computePlacementTransform(mode, info, localBox) {
  const identity = { position: new THREE.Vector3(0, 0, 0), quaternion: new THREE.Quaternion() };

  // Calculate the deterministic anchor translation: the true survey origin of
  // THIS model, in metres, three.js Y-up convention.
  let anchorPos = new THREE.Vector3(0, 0, 0);
  if (info && info.deterministicAnchor) {
    const metres = info.lengthUnit ? info.lengthUnit.metres : 1.0;
    const arr = info.deterministicAnchor;
    // Apply Y-up three.js mapping: (X, Y, Z) -> (X, Z, -Y)
    anchorPos = new THREE.Vector3(arr[0] * metres, arr[2] * metres, -arr[1] * metres);
  }

  // Multi-model federation: every model is rebased by ONE common scene origin
  // (SCENE_ANCHOR -- the first georeferenced model's survey anchor, set in
  // viewer.js and passed in as info.sceneAnchor). Because models that share a
  // coordinate system differ only by small offsets, subtracting the SAME anchor
  // from all of them keeps them mutually aligned yet places every model near
  // the three.js origin, where float32 keeps full precision. SCENE_ANCHOR is
  // already in metres, three.js convention. Absolute survey coordinates are
  // reconstructed for readouts by adding it back (see trueCoord() in viewer.js).
  const sceneAnchor = (info && info.sceneAnchor) ? info.sceneAnchor : new THREE.Vector3(0, 0, 0);
  const rebased = () => anchorPos.clone().sub(sceneAnchor);

  switch (mode) {
    case "internalOrigin":
    case "originToOrigin":
      return identity;

    case "ifcLocalOrigin":
    case "sharedCoordinates": {
      return { position: rebased(), quaternion: new THREE.Quaternion() };
    }

    case "surveyPoint": {
      const m = info.markers.surveyPoint;
      // Fallback (no distinct marker) behaves like Shared Coordinates, so it
      // must rebase too; the marker-found branch deliberately pins this model's
      // own survey point to the world origin (a single-model alignment mode).
      if (!m || !m.offset) return { position: rebased(), quaternion: new THREE.Quaternion() };
      return { position: m.offset.clone(), quaternion: new THREE.Quaternion() };
    }

    case "projectBasePoint": {
      const m = info.markers.projectBasePoint;
      if (!m || !m.offset) return { position: rebased(), quaternion: new THREE.Quaternion() };
      return { position: m.offset.clone(), quaternion: new THREE.Quaternion() };
    }

    case "centerToCenter": {
      if (!localBox || localBox.isEmpty()) return identity;
      const c = localBox.getCenter(new THREE.Vector3());
      return { position: c.multiplyScalar(-1), quaternion: new THREE.Quaternion() };
    }

    default:
      return identity;
  }
}

// ---------------------------------------------------------------------------
// Deterministic IFC Anchor / Offset Pre-processor
// ---------------------------------------------------------------------------
export function applyDeterministicAnchor(arrayBuffer) {
  const text = new TextDecoder('utf-8').decode(arrayBuffer);
  const lines = text.split('\n');
  const linesById = new Map();
  let mapConvAnchor = null;
  let sitePlacementId = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('#')) {
      const eqIdx = line.indexOf('=');
      if (eqIdx !== -1) {
        const id = parseInt(line.substring(1, eqIdx), 10);
        linesById.set(id, { index: i, line });
        
        if (line.includes('IFCMAPCONVERSION(')) {
          const m = line.match(/IFCMAPCONVERSION\([^,]+,[^,]+,([^,]+),([^,]+),([^,]+)/);
          if (m) mapConvAnchor = [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])];
        } else if (line.includes('IFCSITE(')) {
          const m = line.match(/IFCSITE\([^,]+,[^,]+,[^,]+,[^,]+,[^,]+,\s*#(\d+)/);
          if (m) sitePlacementId = parseInt(m[1], 10);
        }
      }
    }
  }

  let locationId = null;
  let currentPlacementId = sitePlacementId;
  while (currentPlacementId) {
    const pInfo = linesById.get(currentPlacementId);
    if (!pInfo) break;
    const pLine = pInfo.line;
    
    const m = pLine.match(/IFCLOCALPLACEMENT\([^,]*,?\s*#(\d+)\s*\)/);
    if (!m) break;
    
    const relTo = pLine.match(/IFCLOCALPLACEMENT\((#\d+)/);
    const relToId = relTo ? parseInt(relTo[1].substring(1), 10) : null;
    
    const relPlacementId = parseInt(m[1], 10);
    const rInfo = linesById.get(relPlacementId);
    if (rInfo) {
      const m2 = rInfo.line.match(/IFCAXIS2PLACEMENT3D\(\s*#(\d+)/);
      if (m2) {
        locationId = parseInt(m2[1], 10);
        break;
      }
    }
    currentPlacementId = relToId;
  }

  let anchor = null;
  let patchedText = text;

  if (locationId) {
    const lInfo = linesById.get(locationId);
    if (lInfo) {
      const m3 = lInfo.line.match(/IFCCARTESIANPOINT\(\(([^)]+)\)\)/);
      if (m3) {
        const coords = m3[1].split(',').map(parseFloat);
        anchor = mapConvAnchor ? mapConvAnchor : coords;
        
        const patchedLine = `#${locationId}=IFCCARTESIANPOINT((0.0,0.0,0.0));\r`;
        lines[lInfo.index] = patchedLine;
        patchedText = lines.join('\n');
      }
    }
  }

  return {
    patchedBuffer: new TextEncoder().encode(patchedText).buffer,
    anchor: anchor
  };
}

