// ============================================================================
// clipper.js — That Open Company "Clipper" Component (Cutting Models)
// ============================================================================
// Implements the That Open Company Clipper specification:
// - Component Enabled: Double-click on any 3D surface to create clipping plane
// - Clipper Visible: Toggles visibility of visual plane helpers in scene
// - Planes Color: Customizes plane mesh & outline colors
// - Planes Opacity: Customizes plane mesh transparency (0.0 - 1.0)
// - Planes Size: Customizes plane physical dimensions
// - Auto Scale Planes: Adapts plane size to model bounding radius
// - Toggle Clippings: Pauses / resumes clipping cuts across model
// - Delete All: Clears all clipping planes
// - Plane list with Flip / Reverse (⇄) and Delete (×) controls
// - Real-time plane dragging along normal
// ============================================================================

(function initThatOpenClipper() {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // Wait for 3D viewer context
  let ctx = window._viewer2DContext;
  let attempts = 0;
  if (!ctx) {
    const t = setInterval(() => {
      ctx = window._viewer2DContext;
      attempts++;
      if (ctx || attempts > 60) {
        clearInterval(t);
        if (ctx) bootstrap(ctx);
      }
    }, 200);
    return;
  }
  bootstrap(ctx);

  function bootstrap(ctx) {
    const THREE = ctx.THREE || window.THREE;
    if (!THREE) return;

    // Clipper state
    const clipper = {
      enabled: true,
      visible: true,
      color: '#202932',
      opacity: 0.2,
      size: 5.2,
      autoScale: true,
      clippingsActive: true,
      planes: [],
      counter: 1,

      // Drag state
      drag: null
    };

    window.clipper = clipper;

    // Helpers
    function getEffectiveSize() {
      if (clipper.autoScale && ctx.secModelRadius) {
        const rad = ctx.secModelRadius();
        return Math.max(clipper.size, rad * 1.8);
      }
      return clipper.size;
    }

    function createPlaneVisual(point, normal, colorHex, opacityVal, sizeVal) {
      const group = new THREE.Group();
      group.position.copy(point);
      group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);

      // 1. Semi-transparent cutting quad
      const quadGeo = new THREE.PlaneGeometry(sizeVal, sizeVal);
      const quadMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(colorHex),
        transparent: true,
        opacity: opacityVal,
        side: THREE.DoubleSide,
        depthWrite: false
      });
      const quad = new THREE.Mesh(quadGeo, quadMat);
      quad.renderOrder = 998;
      group.add(quad);

      // 2. Outlines
      const edgeGeo = new THREE.EdgesGeometry(quadGeo);
      const edgeMat = new THREE.LineBasicMaterial({
        color: new THREE.Color(colorHex),
        linewidth: 2,
        depthTest: false
      });
      const edge = new THREE.LineSegments(edgeGeo, edgeMat);
      edge.renderOrder = 999;
      group.add(edge);

      // 3. Normal direction arrow
      const arrowLen = Math.max(sizeVal * 0.15, 1.0);
      const arrowGroup = new THREE.Group();

      const shaftMat = new THREE.MeshBasicMaterial({ color: 0x4aa3ff, depthTest: false });
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(arrowLen * 0.03, arrowLen * 0.03, arrowLen * 0.8, 12), shaftMat);
      shaft.position.z = arrowLen * 0.4;
      shaft.rotation.x = Math.PI / 2;
      arrowGroup.add(shaft);

      const coneMat = new THREE.MeshBasicMaterial({ color: 0x4aa3ff, depthTest: false });
      const cone = new THREE.Mesh(new THREE.ConeGeometry(arrowLen * 0.08, arrowLen * 0.25, 12), coneMat);
      cone.position.z = arrowLen * 0.8 + arrowLen * 0.125;
      cone.rotation.x = Math.PI / 2;
      arrowGroup.add(cone);

      arrowGroup.renderOrder = 1000;
      group.add(arrowGroup);

      // 4. Invisible pick mesh for easy mouse hit testing & dragging
      const pickGeo = new THREE.PlaneGeometry(sizeVal * 1.05, sizeVal * 1.05);
      const pickMat = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide });
      const pickMesh = new THREE.Mesh(pickGeo, pickMat);
      pickMesh.userData.isClipperPlane = true;
      group.add(pickMesh);

      group.visible = clipper.visible;
      ctx.scene.add(group);

      return { group, quad, edge, arrowGroup, pickMesh };
    }

    // Sync clipping planes to renderer
    function syncClippingPlanes() {
      if (!ctx.renderer) return;

      const planes = [];
      if (clipper.clippingsActive) {
        clipper.planes.forEach(p => {
          if (p.plane) planes.push(p.plane);
        });
      }

      // Preserve SBX planes if section box is active
      const sbx = window._secDebug && window._secDebug.SBX;
      if (sbx && sbx.on && sbx.planes) {
        planes.push(...sbx.planes);
      }

      ctx.renderer.clippingPlanes = planes;
      ctx.renderer.localClippingEnabled = planes.length > 0;

      if (ctx.activeModel && ctx.activeModel.getClippingPlanesEvent) {
        ctx.activeModel.getClippingPlanesEvent = () => ctx.renderer.clippingPlanes;
      }
      if (ctx.fragments && ctx.fragments.update) {
        try { ctx.fragments.update(true); } catch (e) {}
      }
    }

    // Create a new clipping plane
    clipper.createPlane = function(point, normal, customName) {
      const norm = normal.clone().normalize();
      const pt = point.clone();

      const threePlane = new THREE.Plane().setFromNormalAndCoplanarPoint(norm, pt);
      const name = customName || `Plane ${clipper.counter++}`;
      const id = 'clip-' + Date.now() + '-' + Math.random().toString(36).substr(2, 4);

      const sizeVal = getEffectiveSize();
      const visual = createPlaneVisual(pt, norm, clipper.color, clipper.opacity, sizeVal);
      visual.pickMesh.userData.planeId = id;

      const planeItem = {
        id,
        name,
        point: pt,
        normal: norm,
        plane: threePlane,
        visual
      };

      clipper.planes.push(planeItem);
      syncClippingPlanes();
      renderPlaneList();
      return planeItem;
    };

    // Reverse plane normal
    clipper.reversePlane = function(id) {
      const item = clipper.planes.find(p => p.id === id);
      if (!item) return;

      item.normal.negate();
      item.plane.setFromNormalAndCoplanarPoint(item.normal, item.point);
      item.visual.group.rotateY(Math.PI);

      syncClippingPlanes();
      renderPlaneList();
    };

    // Delete plane
    clipper.deletePlane = function(id) {
      const idx = clipper.planes.findIndex(p => p.id === id);
      if (idx === -1) return;

      const item = clipper.planes[idx];
      if (item.visual && item.visual.group) {
        ctx.scene.remove(item.visual.group);
        if (item.visual.quad && item.visual.quad.geometry) item.visual.quad.geometry.dispose();
        if (item.visual.quad && item.visual.quad.material) item.visual.quad.material.dispose();
      }

      clipper.planes.splice(idx, 1);
      syncClippingPlanes();
      renderPlaneList();
    };

    // Delete All
    clipper.deleteAll = function() {
      clipper.planes.forEach(item => {
        if (item.visual && item.visual.group) {
          ctx.scene.remove(item.visual.group);
          if (item.visual.quad && item.visual.quad.geometry) item.visual.quad.geometry.dispose();
          if (item.visual.quad && item.visual.quad.material) item.visual.quad.material.dispose();
        }
      });
      clipper.planes = [];
      syncClippingPlanes();
      renderPlaneList();
    };

    // Toggle clippings
    clipper.toggleClippings = function() {
      clipper.clippingsActive = !clipper.clippingsActive;
      syncClippingPlanes();

      const btn = $('clipToggleClippings');
      if (btn) {
        btn.classList.toggle('on', clipper.clippingsActive);
        btn.style.color = clipper.clippingsActive ? 'var(--text)' : 'var(--muted)';
        btn.title = clipper.clippingsActive ? 'Clippings active' : 'Clippings paused';
      }
    };

    // Update color
    clipper.updateColor = function(colorHex) {
      clipper.color = colorHex;
      const col = new THREE.Color(colorHex);
      clipper.planes.forEach(p => {
        if (p.visual) {
          if (p.visual.quad) p.visual.quad.material.color = col;
          if (p.visual.edge) p.visual.edge.material.color = col;
        }
      });
      renderPlaneList();
    };

    // Update opacity
    clipper.updateOpacity = function(val) {
      clipper.opacity = Math.max(0, Math.min(1, parseFloat(val) || 0.2));
      clipper.planes.forEach(p => {
        if (p.visual && p.visual.quad) {
          p.visual.quad.material.opacity = clipper.opacity;
        }
      });
    };

    // Update size
    clipper.updateSize = function(val) {
      clipper.size = Math.max(0.5, parseFloat(val) || 5.2);
      clipper.refreshSizes();
    };

    // Refresh size of all planes
    clipper.refreshSizes = function() {
      const sizeVal = getEffectiveSize();
      clipper.planes.forEach(p => {
        if (p.visual && p.visual.quad) {
          p.visual.quad.geometry.dispose();
          p.visual.quad.geometry = new THREE.PlaneGeometry(sizeVal, sizeVal);
          if (p.visual.edge) {
            p.visual.edge.geometry.dispose();
            p.visual.edge.geometry = new THREE.EdgesGeometry(p.visual.quad.geometry);
          }
          if (p.visual.pickMesh) {
            p.visual.pickMesh.geometry.dispose();
            p.visual.pickMesh.geometry = new THREE.PlaneGeometry(sizeVal * 1.05, sizeVal * 1.05);
          }
        }
      });
    };

    // Update visibility
    clipper.updateVisible = function(vis) {
      clipper.visible = !!vis;
      clipper.planes.forEach(p => {
        if (p.visual && p.visual.group) {
          p.visual.group.visible = clipper.visible;
        }
      });
    };

    // Render Planes list UI
    function renderPlaneList() {
      const listEl = $('clipPlaneList');
      if (!listEl) return;

      if (!clipper.planes.length) {
        listEl.innerHTML = '<div class="stEmpty">Nothing to display. Double-click model or click "+ Create Plane".</div>';
        return;
      }

      listEl.innerHTML = clipper.planes.map(p => {
        const nx = p.normal.x.toFixed(2);
        const ny = p.normal.y.toFixed(2);
        const nz = p.normal.z.toFixed(2);
        let axisHint = '';
        if (Math.abs(p.normal.y) > 0.9) axisHint = p.normal.y > 0 ? '+Y (Top)' : '-Y (Bottom)';
        else if (Math.abs(p.normal.x) > 0.9) axisHint = p.normal.x > 0 ? '+X (East)' : '-X (West)';
        else if (Math.abs(p.normal.z) > 0.9) axisHint = p.normal.z > 0 ? '+Z (South)' : '-Z (North)';
        else axisHint = `[${nx}, ${ny}, ${nz}]`;

        return `
          <div class="stRow" data-plane-id="${p.id}" style="cursor:pointer">
            <div class="stRowIco" style="background:${clipper.color}"></div>
            <div class="stRowLbl" style="font-weight:600;display:flex;flex-direction:column">
              <span>${esc(p.name)}</span>
              <span style="font-weight:400;color:var(--muted);font-size:10px">${axisHint}</span>
            </div>
            <button class="tb stFlip" data-flip="${p.id}" title="Reverse Normal (⇄)" style="padding:3px 7px;font-size:12px;background:none;border:none;cursor:pointer;color:var(--text)">&#8644;</button>
            <button class="tb stDel" data-del="${p.id}" title="Delete Plane" style="padding:3px 7px;font-size:14px;background:none;border:none;cursor:pointer;color:#ff6b6b">&times;</button>
          </div>
        `;
      }).join('');

      // Wire item actions
      listEl.querySelectorAll('.stFlip').forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          clipper.reversePlane(btn.getAttribute('data-flip'));
        };
      });

      listEl.querySelectorAll('.stDel').forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          clipper.deletePlane(btn.getAttribute('data-del'));
        };
      });
    }

    // ---------------- Mouse Interaction & Real-Time Plane Dragging ----------------
    function getPointerNDC(event) {
      const rect = ctx.viewEl.getBoundingClientRect();
      return new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      );
    }

    function getRaycaster(event) {
      const ray = new THREE.Raycaster();
      ray.setFromCamera(getPointerNDC(event), ctx.camera);
      return ray;
    }

    // Check if pointer is over any plane pickMesh or arrow
    function tryStartPlaneDrag(event) {
      if (!clipper.visible || !clipper.planes.length) return false;

      const ray = getRaycaster(event);
      const pickMeshes = [];
      clipper.planes.forEach(p => {
        if (p.visual && p.visual.pickMesh) pickMeshes.push(p.visual.pickMesh);
      });

      const hits = ray.intersectObjects(pickMeshes, true);
      if (!hits.length) return false;

      const hitMesh = hits[0].object;
      const planeId = hitMesh.userData.planeId;
      const targetPlane = clipper.planes.find(p => p.id === planeId);
      if (!targetPlane) return false;

      // Setup drag plane containing the normal and facing the camera
      const norm = targetPlane.normal.clone();
      const origin = targetPlane.point.clone();
      const eye = new THREE.Vector3().subVectors(ctx.camera.position, origin).normalize();
      let cross = new THREE.Vector3().crossVectors(norm, eye);
      if (cross.lengthSq() < 1e-4) cross = new THREE.Vector3(0, 1, 0).cross(norm);
      const dragPlaneNormal = cross.cross(norm).normalize();
      const dragPlane = new THREE.Plane().setFromNormalAndCoplanarPoint(dragPlaneNormal, origin);

      const p0 = new THREE.Vector3();
      ray.ray.intersectPlane(dragPlane, p0);
      const startOffset = p0.clone().sub(origin).dot(norm);

      clipper.drag = {
        targetPlane,
        norm,
        origin,
        dragPlane,
        startOffset
      };

      if (ctx.controls) ctx.controls.enabled = false;
      return true;
    }

    function onPointerMove(event) {
      if (!clipper.drag) return;

      const ray = getRaycaster(event);
      const pCurrent = new THREE.Vector3();
      if (!ray.ray.intersectPlane(clipper.drag.dragPlane, pCurrent)) return;

      const currentOffset = pCurrent.clone().sub(clipper.drag.origin).dot(clipper.drag.norm);
      const delta = currentOffset - clipper.drag.startOffset;

      const newPoint = clipper.drag.origin.clone().addScaledVector(clipper.drag.norm, delta);
      const tp = clipper.drag.targetPlane;

      tp.point.copy(newPoint);
      tp.plane.setFromNormalAndCoplanarPoint(tp.normal, newPoint);
      tp.visual.group.position.copy(newPoint);

      syncClippingPlanes();
    }

    function onPointerUp() {
      if (clipper.drag) {
        clipper.drag = null;
        if (ctx.controls) ctx.controls.enabled = true;
      }
    }

    ctx.renderer.domElement.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      if (tryStartPlaneDrag(e)) {
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);

    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerup', onPointerUp, { passive: true });

    // ---------------- Double-Click to Create Clipping Plane on 3D Model ----------------
    let _lastDblClick = 0;
    async function onCanvasDblClick(event) {
      const now = performance.now();
      if (now - _lastDblClick < 300) return;
      _lastDblClick = now;

      if (!clipper.enabled) return;

      // Guard: If measure tool is active, don't clip
      const measToolBtn = $('btnMeasureTool');
      if (measToolBtn && measToolBtn.classList.contains('on')) return;

      // Guard: If 2D Views panel is open or active, views_2d handles it
      const v2dPanel = $('views2DPanel');
      if (v2dPanel && v2dPanel.classList.contains('open')) return;

      const ndc = getPointerNDC(event);
      let hitPoint = null;
      let hitNormal = null;

      // 1. Try ThatOpen GPU FastModelPicker
      if (ctx.picker && ctx.picker.getFullPick) {
        try {
          const res = await ctx.picker.getFullPick(ndc);
          if (res && res.point) {
            hitPoint = new THREE.Vector3(res.point.x, res.point.y, res.point.z);
            if (res.normal && (res.normal.x || res.normal.y || res.normal.z)) {
              hitNormal = new THREE.Vector3(res.normal.x, res.normal.y, res.normal.z).normalize();
            } else {
              hitNormal = new THREE.Vector3(0, 1, 0);
            }
          }
        } catch (e) {
          console.warn('[clipper] FastModelPicker err:', e);
        }
      }

      // 2. Fallback to raycast if picker did not return a hit
      if (!hitPoint) {
        const ray = getRaycaster(event);
        const meshes = [];
        ctx.scene.traverse(c => {
          if (c.isMesh && c.visible && !c.userData.isClipperPlane) {
            meshes.push(c);
          }
        });
        const intersects = ray.intersectObjects(meshes, true);
        if (intersects && intersects.length > 0) {
          const hit = intersects[0];
          hitPoint = hit.point.clone();
          if (hit.face && hit.face.normal) {
            hitNormal = hit.face.normal.clone().applyMatrix3(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)).normalize();
          } else {
            hitNormal = new THREE.Vector3(0, 1, 0);
          }
        }
      }

      // 3. Fallback: Place plane along ray intersecting model center depth plane
      if (!hitPoint) {
        const ray = getRaycaster(event);
        const center = ctx.secModelCenter ? ctx.secModelCenter() : new THREE.Vector3(0, 0, 0);
        const camDir = ctx.camera.getWorldDirection(new THREE.Vector3()).negate();
        const centerPlane = new THREE.Plane().setFromNormalAndCoplanarPoint(camDir, center);
        const outPt = new THREE.Vector3();
        if (ray.ray.intersectPlane(centerPlane, outPt)) {
          hitPoint = outPt;
          hitNormal = camDir;
        }
      }

      if (hitPoint) {
        if (!hitNormal || hitNormal.lengthSq() < 1e-4) hitNormal = new THREE.Vector3(0, 1, 0);
        clipper.createPlane(hitPoint, hitNormal);

        // Ensure Clipper panel is open
        const panel = $('secToolsPanel');
        if (panel && !panel.classList.contains('open')) {
          panel.classList.add('open');
          const btn = $('btnSectionTool');
          if (btn) btn.classList.add('on');
        }
      }
    }

    if (ctx.renderer && ctx.renderer.domElement) {
      ctx.renderer.domElement.addEventListener('dblclick', onCanvasDblClick);
    }
    if (ctx.viewEl) {
      ctx.viewEl.addEventListener('dblclick', onCanvasDblClick);
    }

    // ---------------- UI Wireup ----------------
    // 1. Controls
    const clipEnabledEl = $('clipEnabled');
    if (clipEnabledEl) {
      clipEnabledEl.onchange = (e) => { clipper.enabled = e.target.checked; };
    }

    const clipVisibleEl = $('clipVisible');
    if (clipVisibleEl) {
      clipVisibleEl.onchange = (e) => { clipper.updateVisible(e.target.checked); };
    }

    const clipColorEl = $('clipColor');
    if (clipColorEl) {
      clipColorEl.oninput = (e) => { clipper.updateColor(e.target.value); };
    }

    const clipOpacityEl = $('clipOpacity');
    if (clipOpacityEl) {
      clipOpacityEl.oninput = (e) => { clipper.updateOpacity(e.target.value); };
    }

    const clipSizeEl = $('clipSize');
    if (clipSizeEl) {
      clipSizeEl.oninput = (e) => { clipper.updateSize(e.target.value); };
    }

    const clipAutoScaleEl = $('clipAutoScale');
    if (clipAutoScaleEl) {
      clipAutoScaleEl.onchange = (e) => {
        clipper.autoScale = e.target.checked;
        clipper.refreshSizes();
      };
    }

    const clipToggleBtn = $('clipToggleClippings');
    if (clipToggleBtn) {
      clipToggleBtn.onclick = () => { clipper.toggleClippings(); };
    }

    const clipDeleteAllBtn = $('clipDeleteAll');
    if (clipDeleteAllBtn) {
      clipDeleteAllBtn.onclick = () => { clipper.deleteAll(); };
    }

    // 2. Preset Planes
    const clipAddBtn = $('clipAddBtn');
    if (clipAddBtn) {
      clipAddBtn.onclick = () => {
        const c = ctx.secModelCenter ? ctx.secModelCenter() : new THREE.Vector3(0, 0, 0);
        clipper.createPlane(c, new THREE.Vector3(0, 1, 0));
      };
    }

    const clipAddX = $('clipAddX');
    if (clipAddX) {
      clipAddX.onclick = () => {
        const c = ctx.secModelCenter ? ctx.secModelCenter() : new THREE.Vector3(0, 0, 0);
        clipper.createPlane(c, new THREE.Vector3(1, 0, 0), `Plane X`);
      };
    }

    const clipAddY = $('clipAddY');
    if (clipAddY) {
      clipAddY.onclick = () => {
        const c = ctx.secModelCenter ? ctx.secModelCenter() : new THREE.Vector3(0, 0, 0);
        clipper.createPlane(c, new THREE.Vector3(0, 1, 0), `Plane Y`);
      };
    }

    const clipAddZ = $('clipAddZ');
    if (clipAddZ) {
      clipAddZ.onclick = () => {
        const c = ctx.secModelCenter ? ctx.secModelCenter() : new THREE.Vector3(0, 0, 0);
        clipper.createPlane(c, new THREE.Vector3(0, 0, 1), `Plane Z`);
      };
    }

    // Initial render
    renderPlaneList();
  }
})();
