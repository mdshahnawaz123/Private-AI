// ============================================================================
// views_2d.js — 2D Views Module (Floor Plans, Elevations, Sections)
// ============================================================================
// Standalone ES module that integrates with the existing viewer.js.
// Uses the same THREE.js scene, camera, renderer and storey data.
// Does NOT change the viewer UI layout — only adds programmatic view-switching
// capability callable from the existing toolbar buttons.
//
// Usage in viewer.js:
//   import { Views2D } from "/ui/views_2d.js";
//   const views2d = new Views2D({ scene, camera, renderer, controls, storeys, bboxAll, models, fit });
//   views2d.showFloorPlan(storeyIndex);
//   views2d.showElevation("north");
//   views2d.showSection(point, normal);
//   views2d.exitView(); // back to 3D
// ============================================================================

import * as THREE from "three";

export class Views2D {
  constructor({ scene, getCamera, setCamera, renderer, controls, getStoreys, bboxAll, fit, applyClip, clearSection }) {
    this.scene = scene;
    this.getCamera = getCamera;      // () => current camera
    this.setCamera = setCamera;      // (cam) => swap active camera
    this.renderer = renderer;
    this.controls = controls;
    this.getStoreys = getStoreys;    // () => storeys array
    this.bboxAll = bboxAll;          // () => THREE.Box3
    this.fit = fit;                  // () => fit camera to model
    this.applyClip = applyClip;     // (plane) => apply clipping plane
    this.clearSection = clearSection; // () => remove clipping

    this._savedPerspective = null;   // saved 3D camera state
    this._orthoCamera = null;        // reusable ortho camera
    this._activeView = null;         // current 2D view descriptor
    this._viewList = new Map();      // id -> { name, type, plane, cameraSetup }

    this._clippingPlanes = [];
  }

  // ---- Floor Plans (from IFC storeys) ----
  generateFloorPlans() {
    const storeys = this.getStoreys();
    if (!storeys || !storeys.length) return [];

    const box = this.bboxAll();
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    const plans = [];
    const elevs = storeys.map(s => s.elev);
    const emin = Math.min(...elevs);
    const emax = Math.max(...elevs);

    storeys.forEach((s, i) => {
      // Map storey elevation to world Y coordinate
      const yW = (emax > emin)
        ? (box.min.y + (s.elev - emin) / (emax - emin) * (box.max.y - box.min.y))
        : (box.min.y + size.y * 0.5);
      const cutY = yW + Math.max(1.2, size.y * 0.06);

      const id = `plan-${i}`;
      const viewDef = {
        id,
        name: `Plan: ${s.name}`,
        type: "plan",
        storeyIndex: i,
        cutY,
        plane: new THREE.Plane(new THREE.Vector3(0, -1, 0), cutY),
        cameraSetup: () => {
          const cam = this._getOrCreateOrtho();
          const h = Math.max(size.x, size.z) * 0.6;
          const aspect = this.renderer.domElement.clientWidth / this.renderer.domElement.clientHeight;
          cam.left = -h * aspect;
          cam.right = h * aspect;
          cam.top = h;
          cam.bottom = -h;
          cam.near = -size.y * 2;
          cam.far = size.y * 2;
          cam.position.set(center.x, cutY + size.y, center.z);
          cam.up.set(0, 0, -1); // North = up on screen
          cam.lookAt(center.x, cutY, center.z);
          cam.updateProjectionMatrix();
          return cam;
        },
      };
      this._viewList.set(id, viewDef);
      plans.push(viewDef);
    });
    return plans;
  }

  // ---- Elevation Views (N/S/E/W from bounding box) ----
  generateElevations() {
    const box = this.bboxAll();
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    const dirs = [
      { id: "elev-north", name: "Elevation: North", normal: new THREE.Vector3(0, 0, -1), camDir: new THREE.Vector3(0, 0, 1) },
      { id: "elev-south", name: "Elevation: South", normal: new THREE.Vector3(0, 0, 1), camDir: new THREE.Vector3(0, 0, -1) },
      { id: "elev-east",  name: "Elevation: East",  normal: new THREE.Vector3(1, 0, 0), camDir: new THREE.Vector3(-1, 0, 0) },
      { id: "elev-west",  name: "Elevation: West",  normal: new THREE.Vector3(-1, 0, 0), camDir: new THREE.Vector3(1, 0, 0) },
    ];

    const elevations = [];
    const maxDim = Math.max(size.x, size.y, size.z);

    dirs.forEach(d => {
      const viewDef = {
        id: d.id,
        name: d.name,
        type: "elevation",
        plane: null, // Elevations typically don't clip
        cameraSetup: () => {
          const cam = this._getOrCreateOrtho();
          const h = Math.max(size.y, (d.camDir.x !== 0 ? size.z : size.x)) * 0.6;
          const aspect = this.renderer.domElement.clientWidth / this.renderer.domElement.clientHeight;
          cam.left = -h * aspect;
          cam.right = h * aspect;
          cam.top = h;
          cam.bottom = -h;
          cam.near = -maxDim * 2;
          cam.far = maxDim * 2;
          cam.position.copy(center).addScaledVector(d.camDir, -maxDim);
          cam.up.set(0, 1, 0);
          cam.lookAt(center);
          cam.updateProjectionMatrix();
          return cam;
        },
      };
      this._viewList.set(d.id, viewDef);
      elevations.push(viewDef);
    });
    return elevations;
  }

  // ---- Arbitrary Section View ----
  createSectionView(name, point, normal) {
    const id = `section-${Date.now()}`;
    const box = this.bboxAll();
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);

    // Create clipping plane
    const plane = new THREE.Plane();
    plane.setFromNormalAndCoplanarPoint(normal.clone().normalize(), point);

    // Camera looks along the plane normal
    const camDir = normal.clone().normalize();

    const viewDef = {
      id,
      name: name || `Section ${this._viewList.size + 1}`,
      type: "section",
      plane,
      point: point.clone(),
      normal: normal.clone(),
      cameraSetup: () => {
        const cam = this._getOrCreateOrtho();
        const h = maxDim * 0.6;
        const aspect = this.renderer.domElement.clientWidth / this.renderer.domElement.clientHeight;
        cam.left = -h * aspect;
        cam.right = h * aspect;
        cam.top = h;
        cam.bottom = -h;
        cam.near = -maxDim * 2;
        cam.far = maxDim * 2;
        cam.position.copy(point).addScaledVector(camDir, maxDim);
        cam.up.set(0, 1, 0);
        cam.lookAt(point);
        cam.updateProjectionMatrix();
        return cam;
      },
    };
    this._viewList.set(id, viewDef);
    return viewDef;
  }

  // ---- View Activation ----
  openView(viewId) {
    const viewDef = this._viewList.get(viewId);
    if (!viewDef) { console.warn("[Views2D] Unknown view:", viewId); return; }

    // Save 3D camera state if not already saved
    if (!this._savedPerspective) {
      const cam = this.getCamera();
      this._savedPerspective = {
        position: cam.position.clone(),
        target: this.controls.target.clone(),
        zoom: cam.zoom || 1,
        isPerspective: cam.isPerspectiveCamera,
      };
    }

    // Setup ortho camera for this view
    const orthoCam = viewDef.cameraSetup();

    // Apply clipping plane if present
    if (viewDef.plane) {
      this.renderer.clippingPlanes = [viewDef.plane];
      this.renderer.localClippingEnabled = true;
    } else {
      this.renderer.clippingPlanes = [];
    }

    // Switch to ortho camera
    this.setCamera(orthoCam);
    if (this.controls.object) {
      this.controls.object = orthoCam;
    }

    this._activeView = viewDef;
    console.log("[Views2D] Opened:", viewDef.name);
  }

  // ---- Floor Plan shortcut ----
  showFloorPlan(storeyIndex) {
    const id = `plan-${storeyIndex}`;
    if (!this._viewList.has(id)) this.generateFloorPlans();
    this.openView(id);
  }

  // ---- Elevation shortcut ----
  showElevation(direction) {
    const id = `elev-${direction}`;
    if (!this._viewList.has(id)) this.generateElevations();
    this.openView(id);
  }

  // ---- Exit 2D View (back to 3D) ----
  exitView() {
    if (!this._savedPerspective) return;

    // Restore clipping
    this.renderer.clippingPlanes = [];
    this.clearSection();

    // Restore 3D camera
    const cam = this.getCamera();
    if (this._savedPerspective.isPerspective && cam.isOrthographicCamera) {
      // Need to swap back to perspective
      // The setCamera callback handles this
    }

    // Restore position/target from saved state
    const newCam = this.getCamera();
    newCam.position.copy(this._savedPerspective.position);
    if (this.controls.target) {
      this.controls.target.copy(this._savedPerspective.target);
    }
    this.controls.update();

    this._savedPerspective = null;
    this._activeView = null;
    this.fit();
    console.log("[Views2D] Exited to 3D");
  }

  // ---- Query ----
  get activeView() { return this._activeView; }
  get isIn2D() { return this._activeView !== null; }
  get viewList() { return [...this._viewList.values()]; }
  getFloorPlans() { return this.viewList.filter(v => v.type === "plan"); }
  getElevations() { return this.viewList.filter(v => v.type === "elevation"); }
  getSections() { return this.viewList.filter(v => v.type === "section"); }

  // ---- Internals ----
  _getOrCreateOrtho() {
    if (!this._orthoCamera) {
      const w = this.renderer.domElement.clientWidth;
      const h = this.renderer.domElement.clientHeight;
      this._orthoCamera = new THREE.OrthographicCamera(-w / 2, w / 2, h / 2, -h / 2, -10000, 10000);
    }
    return this._orthoCamera;
  }
}
