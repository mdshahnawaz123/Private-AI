// ============================================================================
// views_2d.js — That Open Company "Views" Component (Floor Plans, Elevations, Sections)
// ============================================================================
// Implements the That Open Company 2D Views specification:
// - Programmatic & interactive 2D views (Floor Plans from IFC storeys, Elevations, Sections)
// - Double-click on any 3D surface/wall creates an instant 2D section cut
// - "Close Active 2D View" restores original 3D perspective camera & clipping
// - Interactive 2D Views UI panel matching ThatOpen official design
// ============================================================================

(function init2DViews() {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // Wait for 3D engine context to be ready
  let ctx = window._viewer2DContext;
  let attempts = 0;
  if (!ctx) {
    const t = setInterval(() => {
      ctx = window._viewer2DContext;
      attempts++;
      if (ctx || attempts > 50) {
        clearInterval(t);
        if (ctx) bootstrap(ctx);
      }
    }, 200);
    return;
  }
  bootstrap(ctx);

  function bootstrap(ctx) {
    const THREE = ctx.THREE || window.THREE;
    let saved3D = null;
    let activeView = null;
    let sec2DLines = null;
    let customSections = [];

    // 1. Inject Styles
    const css = document.createElement('style');
    css.textContent = `
    #views2DPanel{position:absolute;right:136px;top:12px;width:340px;max-height:calc(100% - 80px);display:none;flex-direction:column;background:var(--panel,#131b26);border:1px solid var(--border,#2a3a50);border-radius:12px;box-shadow:0 14px 44px rgba(0,0,0,.65);z-index:15;color:var(--text,#dce6f5);font-size:12px;overflow:hidden;font-family:inherit}
    #views2DPanel.open{display:flex}
    #views2DPanel .vhd{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--border,#2a3a50);font-weight:700;font-size:13px;background:rgba(255,255,255,.02)}
    #views2DPanel .vhd span.x{cursor:pointer;color:var(--muted,#8aa0bd);font-size:18px;line-height:1}
    #views2DPanel .vhd span.x:hover{color:#fff}
    
    .v2d-card{border-bottom:1px solid var(--border,#2a3a50);padding:10px 14px}
    .v2d-card-hd{display:flex;align-items:center;justify-content:space-between;cursor:pointer;font-weight:600;font-size:12px;color:var(--text,#dce6f5);user-select:none}
    .v2d-card-hd .caret{font-size:10px;transition:transform .2s}
    .v2d-card.collapsed .v2d-card-body{display:none}
    .v2d-card.collapsed .v2d-card-hd .caret{transform:rotate(-90deg)}
    
    .v2d-info-box{background:rgba(77,124,254,.08);border:1px solid rgba(77,124,254,.25);border-radius:8px;padding:9px 11px;font-size:11.5px;color:#bcd0ff;line-height:1.45;margin-top:8px}
    .v2d-info-box b{color:#fff}
    
    .v2d-close-btn{width:100%;background:var(--panel2,#1b2533);border:1px solid var(--border,#2a3a50);color:var(--muted,#8aa0bd);border-radius:7px;padding:8px 12px;font-size:12px;font-weight:600;cursor:pointer;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:6px}
    .v2d-close-btn.active{background:var(--accent,#4d7cfe);border-color:var(--accent,#4d7cfe);color:#fff;box-shadow:0 0 14px rgba(77,124,254,.4)}
    .v2d-close-btn:disabled{opacity:.45;cursor:not-allowed;background:var(--panel2,#1b2533);color:var(--muted,#8aa0bd);border-color:var(--border,#2a3a50);box-shadow:none}
    
    #v2dListWrap{overflow-y:auto;max-height:360px;display:flex;flex-direction:column;gap:4px;margin-top:8px}
    .v2d-sec-title{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted,#8aa0bd);margin:8px 0 4px;font-weight:700}
    .v2d-item{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;background:var(--panel2,#1b2533);border:1px solid var(--border,#2a3a50);border-radius:7px;cursor:pointer;font-size:12px;transition:all .15s}
    .v2d-item:hover{border-color:var(--accent,#4d7cfe);background:rgba(77,124,254,.12)}
    .v2d-item.active{border-color:var(--accent,#4d7cfe);background:rgba(77,124,254,.2);color:#fff;font-weight:600}
    .v2d-item-title{display:flex;align-items:center;gap:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
    .v2d-item-meta{font-size:11px;color:var(--muted,#8aa0bd);margin-left:6px}
    .v2d-item-acts{display:flex;align-items:center;gap:4px}
    .v2d-act-btn{background:none;border:none;color:var(--muted,#8aa0bd);padding:3px 5px;border-radius:4px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}
    .v2d-act-btn:hover{color:#fff;background:rgba(255,255,255,.1)}
    .v2d-act-btn.del:hover{color:var(--red,#f2585f)}
    
    .v2d-status-bar{padding:8px 14px;background:var(--panel,#131b26);border-top:1px solid var(--border,#2a3a50);font-size:11px;color:var(--muted,#8aa0bd);display:flex;align-items:center;justify-content:space-between}
    .v2d-badge{display:inline-block;padding:2px 6px;border-radius:4px;background:rgba(49,208,165,.15);color:var(--mint,#31d0a5);font-size:10.5px;font-weight:600}
    `;
    document.head.appendChild(css);

    // 2. Inject Panel HTML
    const panel = document.createElement('div');
    panel.id = 'views2DPanel';
    panel.innerHTML = `
      <div class="vhd">
        <span style="display:flex;align-items:center;gap:6px">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
          2D Views
        </span>
        <span class="x" id="v2dClose">&times;</span>
      </div>
      
      <!-- Info Accordion -->
      <div class="v2d-card" id="v2dCardInfo">
        <div class="v2d-card-hd" onclick="this.parentElement.classList.toggle('collapsed')">
          <span>Info</span>
          <span class="caret">&#9662;</span>
        </div>
        <div class="v2d-card-body">
          <div class="v2d-info-box">
            &#128161; <b>Tip:</b> Go inside the building and double-click any wall or surface to create a 2D section.
          </div>
        </div>
      </div>
      
      <!-- Views Accordion -->
      <div class="v2d-card" id="v2dCardViews" style="flex:1;overflow:hidden;display:flex;flex-direction:column;border-bottom:none">
        <div class="v2d-card-hd" onclick="this.parentElement.classList.toggle('collapsed')">
          <span>Views</span>
          <span class="caret">&#9662;</span>
        </div>
        <div class="v2d-card-body" style="display:flex;flex-direction:column;flex:1;overflow:hidden;margin-top:10px">
          <button id="v2dCloseActive" class="v2d-close-btn" disabled>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            Close Active 2D View
          </button>
          
          <div id="v2dListWrap">
            <div id="v2dPlansSection">
              <div class="v2d-sec-title">Floor Plans</div>
              <div id="v2dPlansList">Loading storeys&hellip;</div>
            </div>
            
            <div id="v2dElevSection">
              <div class="v2d-sec-title">Elevations</div>
              <div id="v2dElevList"></div>
            </div>
            
            <div id="v2dCustomSection">
              <div class="v2d-sec-title">Custom Sections</div>
              <div id="v2dCustomList"><div style="color:var(--muted);font-size:11px;padding:4px 6px">Double-click any 3D element to add a cut.</div></div>
            </div>
          </div>
        </div>
      </div>
      
      <div class="v2d-status-bar">
        <span id="v2dStatusText">3D Perspective View</span>
        <span id="v2dStatusBadge" class="v2d-badge" style="display:none">2D Active</span>
      </div>
    `;
    (document.getElementById('view') || document.body).appendChild(panel);

    // 3. Connect Toolbar Button
    const btnViews2D = $('btnViews2D');
    if (btnViews2D) {
      btnViews2D.onclick = () => {
        panel.classList.toggle('open');
        btnViews2D.classList.toggle('on', panel.classList.contains('open'));
        if (panel.classList.contains('open')) refreshStoreys();
      };
    }
    $('v2dClose').onclick = () => {
      panel.classList.remove('open');
      if (btnViews2D) btnViews2D.classList.remove('on');
    };

    $('v2dCloseActive').onclick = () => exit2DView();

    // 4. Default Elevation Views
    const ELEVATIONS = [
      { id: 'elev-s', name: 'South Elevation (Front)', dir: new THREE.Vector3(0, 0, 1), up: new THREE.Vector3(0, 1, 0) },
      { id: 'elev-n', name: 'North Elevation (Back)', dir: new THREE.Vector3(0, 0, -1), up: new THREE.Vector3(0, 1, 0) },
      { id: 'elev-e', name: 'East Elevation (Right)', dir: new THREE.Vector3(1, 0, 0), up: new THREE.Vector3(0, 1, 0) },
      { id: 'elev-w', name: 'West Elevation (Left)', dir: new THREE.Vector3(-1, 0, 0), up: new THREE.Vector3(0, 1, 0) }
    ];

    function renderElevations() {
      const el = $('v2dElevList');
      if (!el) return;
      el.innerHTML = ELEVATIONS.map(ev => `
        <div class="v2d-item" data-id="${ev.id}">
          <div class="v2d-item-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16"/></svg>
            <span>${esc(ev.name)}</span>
          </div>
          <div class="v2d-item-acts">
            <span class="v2d-act-btn" title="Open Elevation">&#10530;</span>
          </div>
        </div>
      `).join('');

      el.querySelectorAll('.v2d-item').forEach((item, idx) => {
        item.onclick = () => openElevationView(ELEVATIONS[idx]);
      });
    }
    renderElevations();

    // 5. Populate Floor Plans from Storeys
    async function refreshStoreys() {
      const el = $('v2dPlansList');
      if (!el) return;

      let list = [];
      // Try from active spatial structure
      if (ctx.storeys && ctx.storeys.length) {
        list = ctx.storeys.map((st, i) => ({
          name: st.name || ("Storey " + (st.localId || i)),
          elevation: Number(st.elevation || st.Elevation || 0),
          localId: st.localId
        }));
      }

      // If empty, query project storeys API
      if (!list.length) {
        try {
          const params = new URLSearchParams(location.search);
          const project = params.get('project') || '';
          if (project) {
            const token = params.get('token') || (window.parent && window.parent.authToken) || '';
            const r = await fetch('/api/ifc/storeys?project=' + encodeURIComponent(project), {
              credentials: 'include',
              headers: token ? { 'Authorization': 'Bearer ' + token } : {}
            });
            if (r.ok) {
              const data = await r.json();
              if (data && data.storeys) {
                list = data.storeys.map(s => ({
                  name: s.storey,
                  elevation: Number(s.elevation || s.elev || 0),
                  count: s.count
                }));
              }
            }
          }
        } catch(e) {
          console.warn('[views2D] storeys query error:', e);
        }
      }

      if (!list.length) {
        el.innerHTML = '<div style="color:var(--muted);font-size:11px;padding:4px 6px">No IFC storeys detected in model.</div>';
        return;
      }

      // Sort lowest elevation first
      list.sort((a, b) => a.elevation - b.elevation);

      el.innerHTML = list.map((st, idx) => `
        <div class="v2d-item" data-idx="${idx}">
          <div class="v2d-item-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
            <span>${esc(st.name)}</span>
            <span class="v2d-item-meta">(${st.elevation >= 0 ? '+' : ''}${st.elevation.toFixed(1)}m)</span>
          </div>
          <div class="v2d-item-acts">
            <span class="v2d-act-btn" title="Open Floor Plan">&#10530;</span>
          </div>
        </div>
      `).join('');

      el.querySelectorAll('.v2d-item').forEach((item, idx) => {
        item.onclick = () => openFloorPlanView(list[idx]);
      });
    }

    // 6. Floor Plan View Activator
    async function openFloorPlanView(storey) {
      if (!ctx.modelBox && !ctx.activeModel) return;
      const box = ctx.modelBox || (ctx.activeModel && ctx.activeModel.boundingBox);
      if (!box) return;

      save3DState();

      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const radius = Math.max(size.x, size.z, size.y) * 0.5 || 25;

      // Determine cut elevation:
      // If storey.elevation is within model Y bounds, use it; otherwise interpolate
      let cutY = center.y;
      if (storey.elevation != null && storey.elevation >= box.min.y && storey.elevation <= box.max.y) {
        cutY = storey.elevation + 1.2; // 1.2m cut plane
      } else {
        // Fallback: if elevations are large numbers (mm), scale
        const scaled = storey.elevation * 0.001;
        if (scaled >= box.min.y && scaled <= box.max.y) {
          cutY = scaled + 1.2;
        } else {
          cutY = center.y;
        }
      }

      // Create horizontal clipping plane looking downward (-Y)
      const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), cutY);
      ctx.renderer.clippingPlanes = [plane];
      ctx.renderer.localClippingEnabled = true;

      // Generate 2D section lines if getSection is supported
      await generateSectionLines(plane);

      // Setup Orthographic Camera looking straight down
      const aspect = (ctx.viewEl.clientWidth || 800) / (ctx.viewEl.clientHeight || 600);
      const r = Math.max(size.x, size.z) * 0.55 || 20;

      const ortho = ctx.orthoCamera;
      ortho.left = -r * aspect;
      ortho.right = r * aspect;
      ortho.top = r;
      ortho.bottom = -r;
      ortho.near = 0.1;
      ortho.far = radius * 8;
      ortho.position.set(center.x, cutY + radius * 2, center.z);
      ortho.up.set(0, 0, -1); // North is UP
      ortho.lookAt(center.x, cutY, center.z);
      ortho.updateProjectionMatrix();

      ctx.camera = ortho;
      ctx.controls.object = ortho;
      ctx.controls.target.set(center.x, cutY, center.z);
      ctx.controls.update();

      activeView = { type: 'plan', name: storey.name, plane };
      updateActiveState(storey.name + ' (Floor Plan)');
    }

    // 7. Elevation View Activator
    async function openElevationView(elev) {
      if (!ctx.modelBox && !ctx.activeModel) return;
      const box = ctx.modelBox || (ctx.activeModel && ctx.activeModel.boundingBox);
      if (!box) return;

      save3DState();

      // Clear any horizontal clipping
      ctx.renderer.clippingPlanes = [];
      clearSectionLines();

      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      const radius = maxDim * 0.55 || 25;

      const aspect = (ctx.viewEl.clientWidth || 800) / (ctx.viewEl.clientHeight || 600);
      const ortho = ctx.orthoCamera;
      ortho.left = -radius * aspect;
      ortho.right = radius * aspect;
      ortho.top = radius;
      ortho.bottom = -radius;
      ortho.near = 0.1;
      ortho.far = maxDim * 6;

      const camPos = center.clone().addScaledVector(elev.dir, maxDim * 2.5);
      ortho.position.copy(camPos);
      ortho.up.copy(elev.up);
      ortho.lookAt(center);
      ortho.updateProjectionMatrix();

      ctx.camera = ortho;
      ctx.controls.object = ortho;
      ctx.controls.target.copy(center);
      ctx.controls.update();

      activeView = { type: 'elevation', name: elev.name };
      updateActiveState(elev.name);
    }

    // 8. Custom Section View Activator (Double-click or custom plane)
    async function openCustomSection(point, normal, name) {
      save3DState();

      const plane = new THREE.Plane();
      plane.setFromNormalAndCoplanarPoint(normal.clone().normalize(), point);

      ctx.renderer.clippingPlanes = [plane];
      ctx.renderer.localClippingEnabled = true;

      await generateSectionLines(plane);

      const box = ctx.modelBox || (ctx.activeModel && ctx.activeModel.boundingBox);
      const radius = box ? Math.max(...box.getSize(new THREE.Vector3()).toArray()) * 0.5 : 30;

      const aspect = (ctx.viewEl.clientWidth || 800) / (ctx.viewEl.clientHeight || 600);
      const ortho = ctx.orthoCamera;
      ortho.left = -radius * aspect;
      ortho.right = radius * aspect;
      ortho.top = radius;
      ortho.bottom = -radius;
      ortho.near = 0.1;
      ortho.far = radius * 8;

      const up = Math.abs(normal.y) > 0.9 ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(0, 1, 0);
      ortho.position.copy(point).addScaledVector(normal, radius * 2.5);
      ortho.up.copy(up);
      ortho.lookAt(point);
      ortho.updateProjectionMatrix();

      ctx.camera = ortho;
      ctx.controls.object = ortho;
      ctx.controls.target.copy(point);
      ctx.controls.update();

      activeView = { type: 'section', name, plane, point, normal };
      updateActiveState(name);
    }

    // 9. Native ThatOpen Section Lines Generator
    async function generateSectionLines(plane) {
      clearSectionLines();
      try {
        const models = ctx.secAllLoadedModels ? ctx.secAllLoadedModels() : [ctx.activeModel];
        let totalVerts = 0;
        const perModel = [];

        for (const m of models) {
          if (!m || !m.getSection) continue;
          try {
            const modelMatrix = ctx.secModelMatrixWorld ? ctx.secModelMatrixWorld(m) : m.object.matrixWorld;
            const inv = modelMatrix.clone().invert();
            const localPlane = plane.clone().applyMatrix4(inv);
            const res = await m.getSection(localPlane);
            const vertCount = res && typeof res.index === 'number' ? res.index : 0;
            if (res && vertCount >= 2) {
              perModel.push({ res, vertCount, modelMatrix });
              totalVerts += vertCount;
            }
          } catch(e) {}
        }

        if (totalVerts >= 2) {
          const positions = new Float32Array(totalVerts * 3);
          const v = new THREE.Vector3();
          let offset = 0;
          for (const { res, vertCount, modelMatrix } of perModel) {
            const src = res.buffer;
            for (let i = 0; i < vertCount; i++) {
              v.set(src[i*3], src[i*3+1], src[i*3+2]);
              v.applyMatrix4(modelMatrix);
              positions[(offset + i) * 3] = v.x;
              positions[(offset + i) * 3 + 1] = v.y;
              positions[(offset + i) * 3 + 2] = v.z;
            }
            offset += vertCount;
          }
          const geo = new THREE.BufferGeometry();
          geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
          const mat = new THREE.LineBasicMaterial({
            color: 0x31d0a5,
            depthTest: false,
            depthWrite: false,
            linewidth: 2
          });
          sec2DLines = new THREE.LineSegments(geo, mat);
          sec2DLines.renderOrder = 1000;
          ctx.scene.add(sec2DLines);
        }
      } catch(e) {
        console.warn('[views2D] getSection error:', e);
      }
      if (ctx.fragments && ctx.fragments.update) await ctx.fragments.update(true);
      if (ctx.renderer && ctx.scene && ctx.camera) ctx.renderer.render(ctx.scene, ctx.camera);
    }

    function clearSectionLines() {
      if (sec2DLines) {
        ctx.scene.remove(sec2DLines);
        if (sec2DLines.geometry) sec2DLines.geometry.dispose();
        if (sec2DLines.material) sec2DLines.material.dispose();
        sec2DLines = null;
      }
    }

    // 10. Exit 2D View (Back to 3D)
    function exit2DView() {
      if (!saved3D) return;

      // Clear clipping & 2D lines
      ctx.renderer.clippingPlanes = [];
      clearSectionLines();

      // Restore 3D Perspective camera
      const cam = saved3D.camera || ctx.perspCamera;
      cam.position.copy(saved3D.position);
      ctx.camera = cam;
      ctx.controls.object = cam;
      ctx.controls.target.copy(saved3D.target);
      ctx.controls.enabled = saved3D.controlsEnabled !== false;
      ctx.controls.update();

      saved3D = null;
      activeView = null;

      // Update UI
      const btnClose = $('v2dCloseActive');
      if (btnClose) {
        btnClose.disabled = true;
        btnClose.classList.remove('active');
      }
      const badge = $('v2dStatusBadge');
      if (badge) badge.style.display = 'none';
      const statusText = $('v2dStatusText');
      if (statusText) statusText.textContent = '3D Perspective View';

      // Unhighlight all view rows
      document.querySelectorAll('#views2DPanel .v2d-item').forEach(it => it.classList.remove('active'));

      if (ctx.fragments && ctx.fragments.update) ctx.fragments.update(true);
      if (ctx.renderer && ctx.scene && ctx.camera) ctx.renderer.render(ctx.scene, ctx.camera);
    }

    function save3DState() {
      if (!saved3D) {
        saved3D = {
          position: ctx.camera.position.clone(),
          target: ctx.controls.target.clone(),
          camera: ctx.camera,
          controlsEnabled: ctx.controls.enabled
        };
      }
    }

    function updateActiveState(title) {
      const btnClose = $('v2dCloseActive');
      if (btnClose) {
        btnClose.disabled = false;
        btnClose.classList.add('active');
      }
      const badge = $('v2dStatusBadge');
      if (badge) badge.style.display = 'inline-block';
      const statusText = $('v2dStatusText');
      if (statusText) statusText.textContent = title || '2D Active';

      // Highlight active row in UI
      document.querySelectorAll('#views2DPanel .v2d-item').forEach(it => {
        const span = it.querySelector('.v2d-item-title span');
        if (span && title && title.includes(span.textContent)) {
          it.classList.add('active');
        } else {
          it.classList.remove('active');
        }
      });
    }

    // 11. Double-Click on 3D Element to Create Section (when 2D Views panel is open or 2D view active)
    ctx.viewEl.addEventListener('dblclick', async (event) => {
      // Don't intercept if measuring mode is active
      const measToolBtn = $('btnMeasureTool');
      if (measToolBtn && measToolBtn.classList.contains('on')) return;

      // Only handle 2D custom sections when 2D Views panel is open or a 2D view is active
      const v2dPanel = $('views2DPanel');
      const is2DPanelOpen = v2dPanel && v2dPanel.classList.contains('open');
      if (!activeView && !is2DPanelOpen) return;

      const rect = ctx.viewEl.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      );

      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(ndc, ctx.camera);

      const meshes = [];
      if (ctx.secAllMeshes) {
        ctx.secAllMeshes(m => { if (m.visible) meshes.push(m); });
      }
      const intersects = ctx.secSafeRaycast ? ctx.secSafeRaycast(raycaster, meshes) : raycaster.intersectObjects(meshes);

      if (intersects && intersects.length > 0) {
        const hit = intersects[0];
        const pt = hit.point.clone();
        let normal = new THREE.Vector3(0, 0, 1);
        if (hit.face && hit.face.normal) {
          normal = hit.face.normal.clone().applyMatrix3(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)).normalize();
        }

        const secId = 'sec-' + Date.now();
        const secName = `Section ${customSections.length + 1}`;
        const secDef = { id: secId, name: secName, point: pt, normal };
        customSections.push(secDef);

        renderCustomSections();

        // Automatically open the new 2D section view
        if (!panel.classList.contains('open')) {
          panel.classList.add('open');
          if (btnViews2D) btnViews2D.classList.add('on');
        }
        await openCustomSection(pt, normal, secName);
      }
    });

    function renderCustomSections() {
      const el = $('v2dCustomList');
      if (!el) return;
      if (!customSections.length) {
        el.innerHTML = '<div style="color:var(--muted);font-size:11px;padding:4px 6px">Double-click any 3D element to add a cut.</div>';
        return;
      }
      el.innerHTML = customSections.map((sec, idx) => `
        <div class="v2d-item" data-id="${sec.id}">
          <div class="v2d-item-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/></svg>
            <span>${esc(sec.name)}</span>
          </div>
          <div class="v2d-item-acts">
            <span class="v2d-act-btn" title="Open Section">&#10530;</span>
            <span class="v2d-act-btn del" title="Delete Section" data-del="${idx}">&times;</span>
          </div>
        </div>
      `).join('');

      el.querySelectorAll('.v2d-item').forEach((item, idx) => {
        item.onclick = (e) => {
          if (e.target.classList.contains('del')) {
            e.stopPropagation();
            if (activeView && activeView.name === customSections[idx].name) exit2DView();
            customSections.splice(idx, 1);
            renderCustomSections();
            return;
          }
          const s = customSections[idx];
          openCustomSection(s.point, s.normal, s.name);
        };
      });
    }

    // Expose global API
    window.views2D = {
      openFloorPlan: openFloorPlanView,
      openElevation: openElevationView,
      openSection: openCustomSection,
      closeActive: exit2DView,
      refresh: refreshStoreys
    };

    console.log('[views2D] That Open Company 2D Views initialized.');
  }
})();
