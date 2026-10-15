/**
 * MPD — Masterplan AI Interface (Masterplan Processing Division)
 * Integrates offline agentic Qwen 3.5 9B reasoning, spatial reasoning engine,
 * CAD/PDF vector graphics engine, plot registers, and review meeting audit logs.
 */

const _mpdEl = (t, c, h) => { const d = document.createElement(t); if (c) d.className = c; if (h != null) d.innerHTML = h; return d; };
const _mpdEsc = s => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const _mpd$ = id => (typeof $ === 'function' ? $(id) : document.getElementById(id));
function _getMpdProject(proj) {
  if (proj) return proj;
  if (typeof currentProject !== 'undefined' && currentProject) return currentProject;
  if (typeof window !== 'undefined' && window.currentProject) return window.currentProject;
  const pSel = document.getElementById('projSel');
  if (pSel && pSel.value) return pSel.value;
  return 'C3085 - 3EH -Expo Hills';
}

let _mpdPlots = [];
let _mpdSummary = null;
let _mpdSelectedPlotId = null;
let _mpdHighlightPlots = [];
let _mpdActiveTab = 'chat'; // 'chat' | 'register'
let _mpdFilterSector = 'All';
let _mpdFilterLandUse = 'All';
let _mpdFilterStatus = 'All';
let _mpdSearchQuery = '';
let _mpdShowSetbacks = true;
let _mpdShowViolationsOnly = false;
let _mpdTransform = { panX: 0, panY: 0, zoom: 1.0 };
let _mpdCanvas = null;
let _mpdCtx = null;
let _mpdHoverPlot = null;
let _mpdChatHist = [];

const LAND_USE_COLORS = {
  'Residential': { fill: 'rgba(245, 183, 61, 0.35)', stroke: '#f5b73d', text: '#ffe699' },
  'Commercial': { fill: 'rgba(47, 107, 255, 0.35)', stroke: '#2f6bff', text: '#b3cbff' },
  'Mixed Use': { fill: 'rgba(168, 85, 247, 0.35)', stroke: '#a855f7', text: '#e9d5ff' },
  'Open Space / Park': { fill: 'rgba(53, 208, 127, 0.35)', stroke: '#35d07f', text: '#bbf7d0' },
  'Civic': { fill: 'rgba(49, 208, 197, 0.35)', stroke: '#31d0c5', text: '#99f6e4' },
  'Utilities': { fill: 'rgba(100, 116, 139, 0.35)', stroke: '#64748b', text: '#cbd5e1' },
  'Default': { fill: 'rgba(148, 163, 184, 0.3)', stroke: '#94a3b8', text: '#f1f5f9' }
};

function getPlotColor(plot) {
  if (plot.status === 'violation') {
    return { fill: 'rgba(242, 88, 95, 0.45)', stroke: '#f2585f', text: '#fca5a5' };
  }
  return LAND_USE_COLORS[plot.land_use] || LAND_USE_COLORS['Default'];
}

async function renderMPDWorkspace(container) {
  const proj = _getMpdProject();
  container.innerHTML = `
    <div class="mpd-root" id="mpdRoot">
      <!-- Unified Masterplan CAD Toolbar -->
      <div class="mpd-canvas-toolbar">
        <div class="mpd-canvas-toolbar-group">
          <button class="cad-btn" id="mpdImportBtn" onclick="window._openImportModal && window._openImportModal()" title="Import DXF, DWG, Excel or PDF">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
            Import File
          </button>
          <button class="cad-btn" id="mpdFilesBtn" onclick="window._openFilesModal && window._openFilesModal()" title="View masterplan source files and cross-reconciliation status">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            Files (<span id="mpdFileCount">0</span>)
          </button>
          <button class="cad-btn" id="mpdReconcileBtn" onclick="window._triggerReconciliation && window._triggerReconciliation()" title="Reconcile and stabilize CAD vs Excel relation">
            <svg class="ico" style="width:13px;height:13px;color:var(--accent2)" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
            Reconcile &amp; Link
          </button>
          <button class="cad-btn" id="mpdAuditBtn" title="Run spatial rule and zoning audit">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            Run Spatial Audit
          </button>
          <button class="cad-btn" id="mpdExportCadBtn" title="Export highlighted CAD DXF">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
            Export CAD (.dxf)
          </button>
          <button class="cad-btn" id="mpdAuditLogBtn" title="View audit history & undo changes">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>
            Audit Log &amp; Undo
          </button>
          <button class="cad-btn" id="mpdResetBtn" title="Reset sample masterplan">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
          </button>

          <div style="width:1px;height:18px;background:var(--border);margin:0 4px"></div>

          <button class="mpd-canvas-ctrl active" id="btnToggleSetbacks" title="Toggle Setback Envelopes">
            <svg class="ico" style="width:12px;height:12px" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="7" y="7" width="10" height="10" stroke-dasharray="2 2"/></svg>
            Setbacks
          </button>
          <button class="mpd-canvas-ctrl" id="btnToggleViolations" title="Show Violations Only">
            <svg class="ico" style="width:12px;height:12px;color:var(--red)" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            Violations Only
          </button>
        </div>

        <div class="mpd-canvas-toolbar-group">
          <button class="mpd-canvas-ctrl" id="btnZoomIn" title="Zoom In">+</button>
          <button class="mpd-canvas-ctrl" id="btnZoomOut" title="Zoom Out">-</button>
          <button class="mpd-canvas-ctrl" id="btnZoomFit" title="Fit Entire Masterplan">Fit</button>
        </div>
      </div>

      <!-- Full-screen Canvas Container -->
      <div class="mpd-canvas-container" id="mpdCanvasContainer">
        <canvas id="mpdCanvas"></canvas>
        <div class="mpd-canvas-tooltip" id="mpdTooltip"></div>
      </div>

      <!-- Canvas Footer Status Bar -->
      <div class="mpd-canvas-footer">
        <div id="mpdStatusCoords">Cursor: (0.0, 0.0) m · Scale: 100%</div>
        <div style="display:flex;align-items:center;gap:12px">
          <div id="mpdSelectedInfo">No Plot Selected</div>
          <button class="cad-btn" id="mpdConfirmBtn" style="padding:3px 10px;font-size:11px;background:rgba(53,208,127,.15);border-color:rgba(53,208,127,.4);color:var(--green)">
            Confirm Selection
          </button>
        </div>
      </div>
    </div>
  `;

  // Wire global event handlers immediately so buttons are responsive without waiting for network
  _wireMpdEvents(proj);

  // Initialize Canvas
  _initCanvas();
  // Fetch data
  await _loadMasterplanData(proj);
  await _loadFilesCount(proj);
}

function _switchMpdTab(tab) {
  _mpdActiveTab = tab;
  $('tabChat').classList.toggle('active', tab === 'chat');
  $('tabRegister').classList.toggle('active', tab === 'register');
  $('paneChat').style.display = tab === 'chat' ? 'flex' : 'none';
  $('paneRegister').style.display = tab === 'register' ? 'flex' : 'none';
}

async function _loadMasterplanData(proj) {
  try {
    const [summaryRes, plotsRes] = await Promise.all([
      fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}`),
      fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/plots`)
    ]);

    if (summaryRes.ok) {
      _mpdSummary = await summaryRes.json();
      _renderMpdSummary(_mpdSummary);
    }
    if (plotsRes.ok) {
      _mpdPlots = await plotsRes.json();
      _renderPlotTable(_mpdPlots);
      _drawCanvas();
      _fitCanvasToPlots();
    }
  } catch (err) {
    console.error('Error loading masterplan data:', err);
    toast('Error loading masterplan data');
  }
}

function _renderMpdSummary(s) {
  if (!s) return;
  if ($('kpiArea')) $('kpiArea').innerHTML = `${(s.total_area_sqm || 0).toLocaleString()} <span class="mpd-kpi-sub">m² (${((s.total_area_sqm || 0)/10000).toFixed(1)} Ha)</span>`;
  if ($('kpiPlots')) $('kpiPlots').innerHTML = `${s.total_plots || 0} <span class="mpd-kpi-sub">plots</span>`;
  if ($('kpiGfa')) $('kpiGfa').innerHTML = `${(s.total_gfa_sqm || 0).toLocaleString()} <span class="mpd-kpi-sub">m²</span>`;
  if ($('kpiFar')) $('kpiFar').innerHTML = `${s.average_far ? s.average_far.toFixed(2) : '0.00'}`;

  const c = s.compliant_plots || 0;
  const w = s.warning_plots || 0;
  const v = s.violation_plots || 0;

  if ($('kpiCompliance')) {
    $('kpiCompliance').innerHTML = `
      <span class="mpd-badge green" style="padding:2px 7px;font-size:11px">${c} OK</span>
      ${w ? `<span class="mpd-badge warn" style="padding:2px 7px;font-size:11px">${w} Warn</span>` : ''}
      ${v ? `<span class="mpd-badge red" style="padding:2px 7px;font-size:11px">${v} Clashes</span>` : ''}
    `;
  }
}

function _renderPlotTable(plots) {
  const tbody = $('mpdPlotTableBody');
  if (!tbody) return;

  const filtered = plots.filter(p => {
    if (_mpdFilterLandUse !== 'All' && p.land_use !== _mpdFilterLandUse) return false;
    if (_mpdFilterSector !== 'All' && p.sector !== _mpdFilterSector) return false;
    if (_mpdFilterStatus !== 'All' && p.status !== _mpdFilterStatus) return false;
    if (_mpdSearchQuery) {
      const q = _mpdSearchQuery.toLowerCase();
      return p.plot_id.toLowerCase().includes(q) || p.sector.toLowerCase().includes(q) || p.land_use.toLowerCase().includes(q);
    }
    return true;
  });

  const countBadge = $('mpdPlotCountBadge');
  if (countBadge) {
    countBadge.textContent = `${filtered.length} plot${filtered.length === 1 ? '' : 's'}`;
  }

  tbody.innerHTML = filtered.map(p => {
    const isSel = p.plot_id === _mpdSelectedPlotId;
    const badge = p.status === 'compliant'
      ? '<span class="mpd-badge green" style="padding:1px 6px;font-size:9.5px">Compliant</span>'
      : (p.status === 'warning'
        ? '<span class="mpd-badge warn" style="padding:1px 6px;font-size:9.5px">Warning</span>'
        : '<span class="mpd-badge red" style="padding:1px 6px;font-size:9.5px">Violation</span>');

    return `
      <tr class="${isSel ? 'selected' : ''}" onclick="_selectPlot('${_mpdEsc(p.plot_id)}')">
        <td><b>${_mpdEsc(p.plot_id)}</b></td>
        <td>${_mpdEsc(p.land_use)}</td>
        <td>${Math.round(p.area_sqm).toLocaleString()}</td>
        <td>${Math.round(p.achieved_gfa).toLocaleString()}</td>
        <td>${p.far.toFixed(2)}</td>
        <td>${badge}</td>
      </tr>
    `;
  }).join('');
}

function _filterPlots() {
  _mpdSearchQuery = $('tblSearch').value.trim();
  _mpdFilterLandUse = $('tblLandUse').value;
  _renderPlotTable(_mpdPlots);
}

function _selectPlot(plotId, zoomTo = false) {
  _mpdSelectedPlotId = plotId;
  const plot = _mpdPlots.find(p => p.plot_id === plotId);
  if (!plot) return;

  // Update selection banner
  const selInfo = $('mpdSelectedInfo');
  if (selInfo) {
    const statusTag = plot.status === 'violation' ? ' <span style="color:var(--red);font-weight:700">⚠️ Violation</span>' : (plot.status === 'warning' ? ' <span style="color:var(--amber);font-weight:700">⚠️ Warning</span>' : ' <span style="color:var(--green)">✓ Compliant</span>');
    selInfo.innerHTML = `Selected: <b>${_mpdEsc(plot.plot_id)}</b> (${_mpdEsc(plot.land_use)} · Area: ${Math.round(plot.area_sqm).toLocaleString()} m² · FAR: ${plot.far.toFixed(2)} / Max: ${plot.max_far.toFixed(2)})${statusTag}`;
  }

  // Update Inspector Card if present in DOM
  if ($('inspPlotTitle')) $('inspPlotTitle').textContent = `Plot ${plot.plot_id} Inspector`;
  if ($('inspStatusBadge')) {
    $('inspStatusBadge').className = `mpd-badge ${plot.status === 'compliant' ? 'green' : (plot.status === 'warning' ? 'warn' : 'red')}`;
    $('inspStatusBadge').textContent = plot.status.toUpperCase();
  }
  if ($('inspSector')) $('inspSector').value = plot.sector;
  if ($('inspLandUse')) $('inspLandUse').value = plot.land_use;
  if ($('inspArea')) $('inspArea').value = Math.round(plot.area_sqm);
  if ($('inspAchGfa')) $('inspAchGfa').value = Math.round(plot.achieved_gfa);
  if ($('inspFar')) $('inspFar').value = `${plot.far.toFixed(2)} / Max: ${plot.max_far.toFixed(2)}`;
  if ($('inspFrontSb')) $('inspFrontSb').value = plot.front_setback_m;

  const violBox = $('inspViolationsBox');
  if (violBox) {
    if (plot.violations && plot.violations.length > 0) {
      violBox.style.display = 'block';
      violBox.innerHTML = `⚠️ <b>Regulatory Issues</b>:<br>` + plot.violations.map(v => `• ${_mpdEsc(v)}`).join('<br>');
    } else {
      violBox.style.display = 'none';
    }
  }

  // Highlight row in table if table exists
  document.querySelectorAll('#mpdPlotTableBody tr').forEach(tr => tr.classList.remove('selected'));
  _renderPlotTable(_mpdPlots);

  if (zoomTo && plot.geometry && plot.geometry.centroid) {
    _centerPlotOnCanvas(plot);
  }

  _drawCanvas();
  if (typeof updateCtxActions === 'function') updateCtxActions();
}

function _calcInspFar() {
  const area = parseFloat($('inspArea').value) || 1;
  const ach = parseFloat($('inspAchGfa').value) || 0;
  const far = ach / area;
  const plot = _mpdPlots.find(p => p.plot_id === _mpdSelectedPlotId);
  const maxFar = plot ? plot.max_far : 2.5;
  $('inspFar').value = `${far.toFixed(2)} / Max: ${maxFar.toFixed(2)}`;
}

async function _savePlotInspection() {
  if (!_mpdSelectedPlotId) return;
  const proj = currentProject || 'C3085 - 3EH -Expo Hills';
  const plot = _mpdPlots.find(p => p.plot_id === _mpdSelectedPlotId);
  if (!plot) return;

  plot.land_use = $('inspLandUse').value;
  plot.achieved_gfa = parseFloat($('inspAchGfa').value) || plot.achieved_gfa;
  plot.front_setback_m = parseFloat($('inspFrontSb').value) || plot.front_setback_m;
  plot.far = Math.round((plot.achieved_gfa / plot.area_sqm) * 100) / 100;

  try {
    const r = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/plots/${encodeURIComponent(plot.plot_id)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(plot)
    });
    if (r.ok) {
      const updated = await r.json();
      toast(`✅ Plot ${plot.plot_id} updated and re-audited!`);
      await _loadMasterplanData(proj);
      _selectPlot(updated.plot_id);
    }
  } catch (e) {
    toast(`Failed to update plot: ${e.message}`);
  }
}

/* ============================================================
   CANVAS GRAPHICS ENGINE IMPLEMENTATION
   ============================================================ */

function _initCanvas() {
  const container = $('mpdCanvasContainer');
  _mpdCanvas = $('mpdCanvas');
  if (!_mpdCanvas || !container) return;
  _mpdCtx = _mpdCanvas.getContext('2d');

  function resize() {
    const rect = container.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    _mpdCanvas.width = rect.width * dpr;
    _mpdCanvas.height = rect.height * dpr;
    _mpdCanvas.style.width = `${rect.width}px`;
    _mpdCanvas.style.height = `${rect.height}px`;
    _drawCanvas();
  }
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => { resize(); });
    ro.observe(container);
  }
  window.addEventListener('resize', resize);
  setTimeout(() => { resize(); _fitCanvasToPlots(); }, 80);

  // Pan & Zoom controls
  let isDragging = false;
  let startX = 0, startY = 0;

  container.addEventListener('mousedown', e => {
    isDragging = true;
    startX = e.clientX - _mpdTransform.panX;
    startY = e.clientY - _mpdTransform.panY;
  });

  window.addEventListener('mouseup', () => { isDragging = false; });

  container.addEventListener('mousemove', e => {
    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    if (isDragging) {
      _mpdTransform.panX = e.clientX - startX;
      _mpdTransform.panY = e.clientY - startY;
      _drawCanvas();
      return;
    }

    // Hit testing
    const worldX = (mouseX - _mpdTransform.panX) / _mpdTransform.zoom;
    const worldY = (mouseY - _mpdTransform.panY) / _mpdTransform.zoom;

    $('mpdStatusCoords').textContent = `Cursor: (${Math.round(worldX)}, ${Math.round(worldY)}) m · Scale: ${Math.round(_mpdTransform.zoom * 100)}%`;

    const hit = _hitTestPlots(worldX, worldY);
    const tooltip = $('mpdTooltip');

    if (hit) {
      _mpdHoverPlot = hit;
      tooltip.style.display = 'block';
      tooltip.style.left = `${mouseX + 14}px`;
      tooltip.style.top = `${mouseY + 14}px`;
      tooltip.innerHTML = `
        <div style="font-weight:700;color:var(--text);font-size:12px">${_mpdEsc(hit.plot_id)} · ${_mpdEsc(hit.land_use)}</div>
        <div style="font-size:10.5px;color:var(--muted)">Area: ${Math.round(hit.area_sqm).toLocaleString()} m² | FAR: ${hit.far.toFixed(2)}</div>
        <div style="font-size:10.5px;color:${hit.status==='violation'?'var(--red)':'var(--green)'}">Status: ${hit.status.toUpperCase()}</div>
      `;
    } else {
      _mpdHoverPlot = null;
      tooltip.style.display = 'none';
    }
    _drawCanvas();
  });

  container.addEventListener('wheel', e => {
    e.preventDefault();
    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
    const newZoom = Math.max(0.2, Math.min(6.0, _mpdTransform.zoom * zoomFactor));

    _mpdTransform.panX = mouseX - (mouseX - _mpdTransform.panX) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.panY = mouseY - (mouseY - _mpdTransform.panY) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.zoom = newZoom;
    _drawCanvas();
  });

  container.addEventListener('click', e => {
    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const worldX = (mouseX - _mpdTransform.panX) / _mpdTransform.zoom;
    const worldY = (mouseY - _mpdTransform.panY) / _mpdTransform.zoom;

    const hit = _hitTestPlots(worldX, worldY);
    if (hit) {
      _selectPlot(hit.plot_id);
    }
  });

  // Toolbar buttons
  $('btnToggleSetbacks').onclick = function() {
    _mpdShowSetbacks = !_mpdShowSetbacks;
    this.classList.toggle('active', _mpdShowSetbacks);
    _drawCanvas();
  };

  $('btnToggleViolations').onclick = function() {
    _mpdShowViolationsOnly = !_mpdShowViolationsOnly;
    this.classList.toggle('active', _mpdShowViolationsOnly);
    _drawCanvas();
  };

  $('btnZoomIn').onclick = () => { _mpdTransform.zoom = Math.min(6.0, _mpdTransform.zoom * 1.25); _drawCanvas(); };
  $('btnZoomOut').onclick = () => { _mpdTransform.zoom = Math.max(0.2, _mpdTransform.zoom * 0.8); _drawCanvas(); };
  $('btnZoomFit').onclick = () => { _fitCanvasToPlots(); };
}

function _hitTestPlots(wx, wy) {
  for (const plot of _mpdPlots) {
    if (_mpdShowViolationsOnly && plot.status !== 'violation') continue;
    if (plot.geometry && plot.geometry.bbox) {
      const [minX, minY, maxX, maxY] = plot.geometry.bbox;
      // Invert Y coordinate since Canvas 0,0 is top-left
      if (wx >= minX && wx <= maxX && wy >= minY && wy <= maxY) {
        return plot;
      }
    }
  }
  return null;
}

function _centerPlotOnCanvas(plot) {
  if (!_mpdCanvas || !plot.geometry || !plot.geometry.centroid) return;
  const dpr = window.devicePixelRatio || 1;
  const w = _mpdCanvas.width / dpr;
  const h = _mpdCanvas.height / dpr;
  const cx = plot.geometry.centroid[0];
  const cy = plot.geometry.centroid[1];

  _mpdTransform.zoom = 1.6;
  _mpdTransform.panX = w / 2 - cx * _mpdTransform.zoom;
  _mpdTransform.panY = h / 2 - cy * _mpdTransform.zoom;
}

function _fitCanvasToPlots() {
  if (!_mpdCanvas || !_mpdPlots.length) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  for (const p of _mpdPlots) {
    if (p.geometry && p.geometry.bbox) {
      minX = Math.min(minX, p.geometry.bbox[0]);
      minY = Math.min(minY, p.geometry.bbox[1]);
      maxX = Math.max(maxX, p.geometry.bbox[2]);
      maxY = Math.max(maxY, p.geometry.bbox[3]);
    }
  }

  if (minX === Infinity) return;

  const dpr = window.devicePixelRatio || 1;
  const cw = _mpdCanvas.width / dpr;
  const ch = _mpdCanvas.height / dpr;
  const pw = maxX - minX + 100;
  const ph = maxY - minY + 100;

  const scale = Math.min(cw / pw, ch / ph) * 0.85;
  _mpdTransform.zoom = Math.max(0.15, Math.min(2.5, scale));
  _mpdTransform.panX = (cw - (minX + maxX) * _mpdTransform.zoom) / 2;
  _mpdTransform.panY = (ch - (minY + maxY) * _mpdTransform.zoom) / 2;
  _drawCanvas();
}

function _drawCanvas() {
  if (!_mpdCtx || !_mpdCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const ctx = _mpdCtx;

  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, _mpdCanvas.width, _mpdCanvas.height);

  // Apply camera transform
  ctx.scale(dpr, dpr);
  ctx.translate(_mpdTransform.panX, _mpdTransform.panY);
  ctx.scale(_mpdTransform.zoom, _mpdTransform.zoom);

  // Draw CAD Coordinate Grid
  _drawGrid(ctx);

  // Draw Plots
  for (const plot of _mpdPlots) {
    if (_mpdShowViolationsOnly && plot.status !== 'violation') continue;
    _drawPlot(ctx, plot);
  }

  ctx.restore();
}

function _drawGrid(ctx) {
  ctx.save();
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
  ctx.lineWidth = 1 / _mpdTransform.zoom;

  const step = 100;
  for (let x = -200; x <= 1400; x += step) {
    ctx.beginPath();
    ctx.moveTo(x, -200);
    ctx.lineTo(x, 1000);
    ctx.stroke();
  }
  for (let y = -200; y <= 1000; y += step) {
    ctx.beginPath();
    ctx.moveTo(-200, y);
    ctx.lineTo(1400, y);
    ctx.stroke();
  }

  // Masterplan Boundary outline
  ctx.strokeStyle = 'rgba(47, 107, 255, 0.2)';
  ctx.lineWidth = 2 / _mpdTransform.zoom;
  ctx.strokeRect(50, -50, 1000, 650);

  ctx.restore();
}

function _drawPlot(ctx, plot) {
  if (!plot.geometry || !plot.geometry.coordinates || plot.geometry.coordinates.length < 3) return;

  const isSel = plot.plot_id === _mpdSelectedPlotId;
  const isHl = _mpdHighlightPlots.includes(plot.plot_id);
  const isHov = _mpdHoverPlot && _mpdHoverPlot.plot_id === plot.plot_id;
  const color = getPlotColor(plot);

  ctx.save();

  // Draw Parcel Boundary Polygon
  ctx.beginPath();
  const coords = plot.geometry.coordinates;
  ctx.moveTo(coords[0][0], coords[0][1]);
  for (let i = 1; i < coords.length; i++) {
    ctx.lineTo(coords[i][0], coords[i][1]);
  }
  ctx.closePath();

  // Fill
  ctx.fillStyle = isSel ? 'rgba(47, 107, 255, 0.55)' : (isHl ? 'rgba(245, 183, 61, 0.55)' : (isHov ? 'rgba(255, 255, 255, 0.2)' : color.fill));
  ctx.fill();

  // Stroke
  ctx.lineWidth = (isSel ? 4 : (isHl || isHov ? 3 : 1.5)) / _mpdTransform.zoom;
  ctx.strokeStyle = isSel ? '#00f2fe' : (isHl ? '#f5b73d' : (plot.status === 'violation' ? '#f2585f' : color.stroke));
  ctx.stroke();

  // Draw Setback Envelope if active
  if (_mpdShowSetbacks && plot.geometry.setback_envelope && plot.geometry.setback_envelope.length >= 3) {
    ctx.beginPath();
    const sb = plot.geometry.setback_envelope;
    ctx.moveTo(sb[0][0], sb[0][1]);
    for (let i = 1; i < sb.length; i++) {
      ctx.lineTo(sb[i][0], sb[i][1]);
    }
    ctx.closePath();
    ctx.setLineDash([4 / _mpdTransform.zoom, 4 / _mpdTransform.zoom]);
    ctx.lineWidth = 1 / _mpdTransform.zoom;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Centroid Text Annotation
  const bbox = plot.geometry.bbox || [coords[0][0], coords[0][1], coords[1][0], coords[1][1]];
  const plotW = Math.max(20, bbox[2] - bbox[0]);
  const plotH = Math.max(20, bbox[3] - bbox[1]);
  const cx = plot.geometry.centroid ? plot.geometry.centroid[0] : (bbox[0] + bbox[2]) / 2;
  const cy = plot.geometry.centroid ? plot.geometry.centroid[1] : (bbox[1] + bbox[3]) / 2;

  // Bounded Plot ID (never exceeds plot width)
  const maxTitleFont = Math.min(plotW * 0.18, 14 / _mpdTransform.zoom);
  const titleFont = Math.max(7, maxTitleFont);
  ctx.fillStyle = isSel ? '#ffffff' : color.text;
  ctx.font = `bold ${titleFont}px Inter, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(plot.plot_id, cx, cy - titleFont * 0.55);

  // Bounded FAR text
  const maxSubFont = Math.min(plotW * 0.12, 11 / _mpdTransform.zoom);
  const subFont = Math.max(6, maxSubFont);
  ctx.font = `${subFont}px Inter, sans-serif`;
  ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
  ctx.fillText(`FAR ${plot.far.toFixed(2)}`, cx, cy + subFont * 0.75);

  // Elegant top-right alert badge for violations (instead of stamping giant text)
  if (plot.status === 'violation') {
    const badgeR = Math.min(9, Math.max(5, plotW * 0.05));
    const bx = bbox[2] - badgeR - 4;
    const by = bbox[1] + badgeR + 4;
    ctx.fillStyle = '#f2585f';
    ctx.beginPath();
    ctx.arc(bx, by, badgeR, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = `bold ${badgeR * 1.3}px Inter, sans-serif`;
    ctx.fillText('!', bx, by);
  }

  ctx.restore();
}

/* ============================================================
   AI COPILOT & TOOL RUNNER (Qwen 3.5 9B)
   ============================================================ */

function _sendMpdChip(chipEl) {
  $('mpdChatInput').value = chipEl.textContent.trim();
  _handleMpdChatSubmit();
}

async function _handleMpdChatSubmit() {
  const input = $('mpdChatInput');
  const query = input.value.trim();
  if (!query) return;
  input.value = '';

  const hist = $('mpdChatHistory');
  const userMsg = document.createElement('div');
  userMsg.className = 'mpd-msg user';
  userMsg.textContent = query;
  hist.appendChild(userMsg);
  hist.scrollTop = hist.scrollHeight;

  // Add Thinking Placeholder
  const agentMsg = document.createElement('div');
  agentMsg.className = 'mpd-msg agent';
  agentMsg.innerHTML = `
    <div style="font-weight:700;display:flex;align-items:center;gap:6px;color:var(--accent2)">
      <svg class="ico" style="width:14px;height:14px;animation:spin 1s linear infinite" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
      Qwen 3.5 9B Reasoning &amp; Spatial Planning...
    </div>
  `;
  hist.appendChild(agentMsg);
  hist.scrollTop = hist.scrollHeight;

  const proj = currentProject || 'C3085 - 3EH -Expo Hills';

  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/ai-query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        project_id: proj,
        selected_plot_id: _mpdSelectedPlotId
      })
    });

    if (!res.ok) throw new Error('AI query service error');
    const data = await res.json();

    _mpdHighlightPlots = data.highlight_plots || [];
    _drawCanvas();

    let toolBadges = '';
    if (data.tools_called && data.tools_called.length) {
      toolBadges = data.tools_called.map(t => `<span class="mpd-badge" style="font-size:9.5px;padding:2px 6px">Tool: ${_mpdEsc(t)}</span>`).join(' ');
    }

    agentMsg.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <div style="font-weight:700;color:var(--accent2);font-size:11.5px">Qwen 3.5 9B Copilot · Intent: ${_mpdEsc(data.intent || 'QUERY')}</div>
        <div>${toolBadges}</div>
      </div>
      <div style="line-height:1.5;font-size:12px">${mdLite(data.answer)}</div>
    `;

    // If highlights exist, select first one
    if (_mpdHighlightPlots.length > 0) {
      _selectPlot(_mpdHighlightPlots[0], true);
    }
  } catch (err) {
    agentMsg.innerHTML = `<span style="color:var(--red)">Failed to reach reasoning model: ${_mpdEsc(err.message)}</span>`;
  }
  hist.scrollTop = hist.scrollHeight;
}

/* ============================================================
   GLOBAL MODALS & ACTIONS
   ============================================================ */

function _wireMpdEvents(proj) {
  const activeProj = _getMpdProject(proj);

  // Import Dialog
  const impBtn = _mpd$('mpdImportBtn');
  if (impBtn) impBtn.onclick = () => _openImportModal(activeProj);

  // Files List & Status Dialog
  const filesBtn = _mpd$('mpdFilesBtn');
  if (filesBtn) filesBtn.onclick = () => _openFilesModal(activeProj);

  // Reconcile & Link Action
  const recBtn = _mpd$('mpdReconcileBtn');
  if (recBtn) recBtn.onclick = () => _triggerReconciliation(activeProj);

  // Spatial Audit Action
  const auditBtn = _mpd$('mpdAuditBtn');
  if (auditBtn) auditBtn.onclick = async () => {
    toast('Running end-to-end spatial and zoning audit...');
    try {
      const r = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/audit`, { method: 'POST' });
      if (r.ok) {
        const res = await r.json();
        toast(`✅ Spatial audit complete: ${res.violations} violations, ${res.warnings} warnings detected.`);
        await _loadMasterplanData(activeProj);
      }
    } catch (e) {
      toast('Spatial audit failed');
    }
  };

  // Export CAD (.dxf)
  const expBtn = _mpd$('mpdExportCadBtn');
  if (expBtn) expBtn.onclick = () => {
    const highlights = _mpdHighlightPlots.join(',');
    const url = `${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/export-cad${highlights ? `?highlights=${encodeURIComponent(highlights)}` : ''}`;
    window.open(url, '_blank');
    toast('📥 Downloading highlighted CAD copy (DXF)...');
  };

  // Audit Log & Undo Dialog
  const logBtn = _mpd$('mpdAuditLogBtn');
  if (logBtn) logBtn.onclick = () => _openAuditLogModal(activeProj);

  // Reset Sample
  const rstBtn = _mpd$('mpdResetBtn');
  if (rstBtn) rstBtn.onclick = async () => {
    if (!confirm('Reset masterplan back to standard Expo Hills sample layout?')) return;
    try {
      await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/reset-sample`, { method: 'POST' });
      toast('Masterplan reset successfully!');
      await _loadMasterplanData(activeProj);
      await _loadFilesCount(activeProj);
    } catch (e) {}
  };

  // Confirm Selection Action
  const confBtn = _mpd$('mpdConfirmBtn');
  if (confBtn) confBtn.onclick = async () => {
    if (!_mpdSelectedPlotId) {
      toast('Please select a plot first.');
      return;
    }
    toast(`✅ Confirmed review action for Plot ${_mpdSelectedPlotId}`);
  };
}

async function _loadFilesCount(proj) {
  const activeProj = _getMpdProject(proj);
  try {
    const r = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/files`);
    if (r.ok) {
      const data = await r.json();
      const countEl = _mpd$('mpdFileCount');
      if (countEl) {
        countEl.textContent = String(data.total_files || (data.files ? data.files.length : 0));
      }
    }
  } catch (e) {
    console.warn('Failed to load files count:', e);
  }
}

async function _openFilesModal(proj) {
  const activeProj = _getMpdProject(proj);
  document.querySelectorAll('.mpd-modal-wrapper').forEach(m => m.remove());

  const modal = _mpdEl('div', 'mpd-modal-wrapper modal-overlay cad-modal-overlay', `
    <div class="modal" style="width:780px;max-width:94vw;max-height:85vh;background:#0d1424;border:1px solid var(--border);border-radius:var(--r-lg);padding:24px;box-shadow:0 14px 40px rgba(0,0,0,.7);display:flex;flex-direction:column;gap:14px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
          <svg class="ico" style="width:20px;height:20px;color:var(--accent2)" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          Masterplan Source Files &amp; AI Model Ground Truth
        </div>
        <button id="closeFilesModal" style="background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1">&times;</button>
      </div>

      <div style="font-size:12px;color:var(--muted);line-height:1.5">
        Multi-source files uploaded for <b>${_mpdEsc(activeProj)}</b>. Link CAD vector geometry (.dxf/.dwg) with Excel development registers (.xlsx) to form certified ground truth for Agentic AI spatial reasoning.
      </div>

      <!-- Relation Link Status Banner -->
      <div id="mpdRelationStatusCard" style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--r-md);padding:12px 14px">
        <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)">
          <div class="spinner" style="width:16px;height:16px;border-width:2px"></div>
          Checking source file correlation status...
        </div>
      </div>

      <!-- Files List Table -->
      <div style="flex:1;overflow-y:auto;max-height:360px;border:1px solid var(--border);border-radius:var(--r-sm);background:#070b15">
        <table style="width:100%;border-collapse:collapse;font-size:12px;text-align:left">
          <thead>
            <tr style="background:#0f172a;color:var(--muted);border-bottom:1px solid var(--border)">
              <th style="padding:10px 12px;font-weight:600">File Name</th>
              <th style="padding:10px 12px;font-weight:600">Type</th>
              <th style="padding:10px 12px;font-weight:600">Size</th>
              <th style="padding:10px 12px;font-weight:600">Plots</th>
              <th style="padding:10px 12px;font-weight:600">Uploaded</th>
              <th style="padding:10px 12px;font-weight:600">Status</th>
            </tr>
          </thead>
          <tbody id="mpdFilesTableBody">
            <tr>
              <td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">Loading uploaded files...</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Bottom Actions -->
      <div style="display:flex;justify-content:space-between;align-items:center;padding-top:6px;border-top:1px solid rgba(255,255,255,.05)">
        <button class="cad-btn" id="uploadMoreFromFilesBtn" style="display:flex;align-items:center;gap:6px">
          <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
          Upload New File
        </button>
        <div style="display:flex;gap:10px">
          <button class="primary" id="reconcileFromFilesBtn" style="display:flex;align-items:center;gap:6px;background:var(--accent2);border-color:var(--accent2)">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
            Reconcile &amp; Link CAD ⟷ Excel
          </button>
          <button class="cad-btn" id="closeFilesBtn">Close</button>
        </div>
      </div>
    </div>
  `);
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:99999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(5px)";
  document.body.appendChild(modal);

  const closeBtn = modal.querySelector('#closeFilesModal');
  const closeBtn2 = modal.querySelector('#closeFilesBtn');
  const uploadMoreBtn = modal.querySelector('#uploadMoreFromFilesBtn');
  const reconcileBtn = modal.querySelector('#reconcileFromFilesBtn');

  if (closeBtn) closeBtn.onclick = () => modal.remove();
  if (closeBtn2) closeBtn2.onclick = () => modal.remove();
  if (uploadMoreBtn) uploadMoreBtn.onclick = () => {
    modal.remove();
    _openImportModal(activeProj);
  };
  if (reconcileBtn) reconcileBtn.onclick = () => {
    modal.remove();
    _triggerReconciliation(activeProj);
  };
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/files`);
    if (res.ok) {
      const data = await res.json();
      const files = data.files || [];
      const rel = data.relation;

      const countEl = _mpd$('mpdFileCount');
      if (countEl) countEl.textContent = String(files.length);

      const relCard = modal.querySelector('#mpdRelationStatusCard');
      if (rel && rel.status === 'stabilized_linked') {
        relCard.style.borderColor = 'rgba(53,208,127,.4)';
        relCard.style.background = 'rgba(53,208,127,.07)';
        relCard.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-weight:700;color:var(--green);font-size:12.5px;display:flex;align-items:center;gap:6px;margin-bottom:3px">
                <svg class="ico" style="width:15px;height:15px" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                Active Ground Truth Link: CAD Vector ⟷ Excel Schedule
              </div>
              <div style="font-size:11.5px;color:var(--text)">
                <b>${_mpdEsc(rel.cad_file)}</b> linked with <b>${_mpdEsc(rel.excel_file)}</b> (${rel.matched_plots} parcels stabilized)
              </div>
            </div>
            <span class="mpd-badge green" style="font-size:10.5px;padding:3px 8px">Verified Ground Truth</span>
          </div>
        `;
      } else {
        const cadFiles = files.filter(f => f.file_type === 'cad');
        const excelFiles = files.filter(f => f.file_type === 'excel');
        const canReconcile = cadFiles.length > 0 && excelFiles.length > 0;
        relCard.style.borderColor = canReconcile ? 'rgba(47,107,255,.4)' : 'rgba(245,183,61,.3)';
        relCard.style.background = canReconcile ? 'rgba(47,107,255,.07)' : 'rgba(245,183,61,.07)';
        relCard.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-weight:700;color:${canReconcile ? 'var(--accent2)' : 'var(--amber)'};font-size:12.5px;margin-bottom:3px">
                ${canReconcile ? '⚡ Ready for Cross-Reconciliation' : '⚠️ Pending Cross-Source Uploads'}
              </div>
              <div style="font-size:11.5px;color:var(--text)">
                ${canReconcile ? 'Both CAD drawing and Excel register detected. Click Reconcile & Link to establish ground truth.' : 'Upload both a CAD drawing (.dxf/.dwg) and an Excel schedule (.xlsx) to correlate geometry with zoning.'}
              </div>
            </div>
            ${canReconcile ? `<span class="mpd-badge" style="font-size:10.5px;padding:3px 8px;background:rgba(47,107,255,.2);color:var(--accent2)">Ready to Link</span>` : `<span class="mpd-badge warn" style="font-size:10.5px;padding:3px 8px">Incomplete</span>`}
          </div>
        `;
      }

      const tbody = modal.querySelector('#mpdFilesTableBody');
      if (!files.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--muted)">No masterplan files uploaded yet for this project.</td></tr>`;
        return;
      }
      tbody.innerHTML = files.map(f => {
        let typeBadge = '';
        if (f.file_type === 'cad') typeBadge = `<span class="mpd-badge" style="background:rgba(47,107,255,.15);color:var(--accent2)">CAD Drawing</span>`;
        else if (f.file_type === 'excel') typeBadge = `<span class="mpd-badge" style="background:rgba(53,208,127,.15);color:var(--green)">Excel Register</span>`;
        else if (f.file_type === 'pdf') typeBadge = `<span class="mpd-badge" style="background:rgba(245,183,61,.15);color:var(--amber)">PDF Zoning</span>`;
        else typeBadge = `<span class="mpd-badge">${_mpdEsc(f.file_type)}</span>`;

        const sizeKb = f.file_size ? `${(f.file_size / 1024).toFixed(0)} KB` : '—';
        const dateStr = f.uploaded_at ? new Date(f.uploaded_at).toLocaleString() : '—';
        const statusBadge = f.status === 'linked'
          ? `<span class="mpd-badge green" style="font-size:10px">Linked</span>`
          : `<span class="mpd-badge" style="font-size:10px">${_mpdEsc(f.status || 'Indexed')}</span>`;

        return `
          <tr style="border-bottom:1px solid rgba(255,255,255,.05)">
            <td style="padding:9px 12px;font-weight:600;color:var(--text);display:flex;align-items:center;gap:7px">
              <svg class="ico" style="width:13px;height:13px;color:var(--muted)" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              ${_mpdEsc(f.filename)}
            </td>
            <td style="padding:9px 12px">${typeBadge}</td>
            <td style="padding:9px 12px;color:var(--muted)">${sizeKb}</td>
            <td style="padding:9px 12px;font-weight:700">${f.plots_count || 0}</td>
            <td style="padding:9px 12px;color:var(--muted);font-size:11px">${dateStr}</td>
            <td style="padding:9px 12px">${statusBadge}</td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    console.error('Failed to load files:', err);
  }
}

async function _triggerReconciliation(proj) {
  const activeProj = _getMpdProject(proj);
  toast('🔄 Correlating CAD drawings with Excel development schedule...');
  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/reconcile`, {
      method: 'POST'
    });
    const data = await res.json();
    if (data.status === 'warning') {
      toast(`⚠️ ${data.message}`);
      if (typeof setAiTab === 'function') setAiTab('chat');
      _mpdAddChatMsg('a', `
        <div style="border-left:3px solid var(--amber);padding-left:10px">
          <div style="font-weight:700;color:var(--amber);margin-bottom:4px">⚠️ Masterplan Multi-Source Linking Advisory</div>
          <div style="font-size:12.5px;color:var(--text);margin-bottom:8px">${_mpdEsc(data.message)}</div>
          <div style="font-size:11.5px;color:var(--muted)">To establish a verified Agentic AI Ground Truth relation, please upload both:
            <ul style="margin:4px 0 6px 18px">
              <li><b>CAD Vector Drawing</b> (.dxf or .dwg) — defines physical parcel geometry</li>
              <li><b>Excel Development Register</b> (.xlsx) — defines official BUA and allowable FAR</li>
            </ul>
          </div>
          <button class="cad-btn" onclick="document.getElementById('mpdImportBtn')?.click()" style="margin-top:6px;padding:4px 12px;font-size:11px">
            📁 Upload Masterplan File
          </button>
        </div>
      `);
      return;
    }
    _handleReconciliationResult(activeProj, data);
  } catch (err) {
    toast(`Reconciliation failed: ${err.message}`);
  }
}

function _mpdAddChatMsg(who, html) {
  if (typeof addMsg === 'function') {
    return addMsg(who, html);
  }
  const aiMsgs = document.getElementById('aiMsgs');
  if (!aiMsgs) return null;
  const label = who === 'u' ? 'You' : 'Design AI';
  const d = _mpdEl('div', 'm ' + who, `
    <div class="av" aria-hidden="true">${who==='u'?'U':'AI'}</div>
    <div class="message-content">
      <div class="message-label">${label}</div>
      <div class="bub">${html}</div>
    </div>
  `);
  aiMsgs.appendChild(d);
  aiMsgs.scrollTop = aiMsgs.scrollHeight;
  return d.querySelector('.bub');
}

function _handleReconciliationResult(proj, rec) {
  if (!rec) return;

  if (typeof setAiTab === 'function') {
    setAiTab('chat');
  }

  if (rec.discrepancies && rec.discrepancies.length > 0) {
    const cadName = rec.cad_file || rec.cad_filename || 'CAD Drawing';
    const excelName = rec.excel_file || rec.excel_filename || 'Excel Schedule';

    const discHtml = rec.discrepancies.map(d => `
      <div id="reconcileCard_${_mpdEsc(d.plot_id)}" style="background:#090f1d;border:1px solid rgba(245,183,61,.35);border-radius:8px;padding:12px;margin:8px 0">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <div style="font-weight:700;color:var(--amber);font-size:12.5px">${_mpdEsc(d.title || ('Plot ' + d.plot_id))}</div>
          ${d.diff_pct ? `<span class="mpd-badge warn" style="font-size:10px">Δ ${d.diff_pct}%</span>` : ''}
        </div>
        <div style="font-size:12px;color:var(--text);line-height:1.5;margin-bottom:10px">${_mpdEsc(d.question)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
          <div style="background:rgba(47,107,255,.1);border:1px solid rgba(47,107,255,.3);border-radius:6px;padding:6px 10px">
            <span style="font-size:10px;color:var(--muted);display:block">CAD DRAWING</span>
            <b style="color:var(--accent2);font-size:12px">${_mpdEsc(String(d.cad_val))}</b>
          </div>
          <div style="background:rgba(53,208,127,.1);border:1px solid rgba(53,208,127,.3);border-radius:6px;padding:6px 10px">
            <span style="font-size:10px;color:var(--muted);display:block">EXCEL REGISTER</span>
            <b style="color:var(--green);font-size:12px">${_mpdEsc(String(d.excel_val))}</b>
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="primary" style="padding:6px 12px;font-size:11px" onclick="window._resolveMpdRelation('${_mpdEsc(proj)}', '${_mpdEsc(d.plot_id)}', 'cad', ${Number(d.cad_val) || 0}, ${Number(d.excel_val) || 0})">
            Adopt CAD Geometry (${_mpdEsc(String(d.cad_val))} m²)
          </button>
          <button class="cad-btn" style="padding:6px 12px;font-size:11px;color:var(--green);border-color:rgba(53,208,127,.4)" onclick="window._resolveMpdRelation('${_mpdEsc(proj)}', '${_mpdEsc(d.plot_id)}', 'excel', ${Number(d.cad_val) || 0}, ${Number(d.excel_val) || 0})">
            Adopt Excel Schedule (${_mpdEsc(String(d.excel_val))} m²)
          </button>
        </div>
      </div>
    `).join('');

    _mpdAddChatMsg('a', `
      <div style="border-left:3px solid var(--amber);padding-left:10px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span class="mpd-badge warn" style="font-size:10.5px;font-weight:700">⚠️ Masterplan Multi-Source Discrepancy</span>
          <span style="font-size:11px;color:var(--muted)">${_mpdEsc(cadName)} ⟷ ${_mpdEsc(excelName)}</span>
        </div>
        <div style="font-size:12.5px;color:var(--text);line-height:1.5;margin-bottom:8px">
          Cross-correlation analyzed <b>${rec.total_plots || rec.matched_plots}</b> plots. Found <b>${rec.discrepancies.length}</b> parameter conflict between CAD parcel geometry and Excel schedule. Please confirm which source to stabilize:
        </div>
        ${discHtml}
      </div>
    `);

    const discIds = rec.discrepancies.map(d => d.plot_id);
    if (typeof window._highlightMpdPlots === 'function') {
      window._highlightMpdPlots(discIds);
    }
  } else if (rec.matched_plots && rec.matched_plots > 0) {
    _mpdAddChatMsg('a', `
      <div style="border-left:3px solid var(--green);padding-left:10px">
        <div style="font-weight:700;color:var(--green);font-size:12.5px;margin-bottom:4px">✅ 100% Geometric Parity Correlated</div>
        <div style="font-size:12.5px;color:var(--text);line-height:1.5;margin-bottom:8px">
          All <b>${rec.matched_plots}</b> plots matched identically between CAD drawing <code>${_mpdEsc(rec.cad_file || rec.cad_filename || 'CAD')}</code> and Excel schedule <code>${_mpdEsc(rec.excel_file || rec.excel_filename || 'Excel')}</code> with zero area or FAR discrepancies.
        </div>
        <button class="primary" style="padding:6px 16px;font-size:11.5px" onclick="window._confirmMpdFullLink('${_mpdEsc(proj)}')">
          🔗 Confirm &amp; Link into AI Ground Truth
        </button>
      </div>
    `);
  }
}

window._resolveMpdRelation = async function(proj, plotId, choice, cadVal, excelVal) {
  const card = document.getElementById(`reconcileCard_${plotId}`);
  if (card) {
    card.style.opacity = '0.6';
    card.querySelectorAll('button').forEach(b => b.disabled = true);
  }
  toast(`Stabilizing ground truth for Plot ${plotId}...`);
  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/stabilize-relation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resolutions: { [plotId]: choice },
        excel_area: excelVal,
        author: 'Design AI Copilot'
      })
    });
    if (res.ok) {
      toast(`✅ Stabilized Plot ${plotId} (${choice.toUpperCase()})`);
      if (card) {
        card.innerHTML = `
          <div style="color:var(--green);font-weight:700;font-size:12px;display:flex;align-items:center;gap:6px">
            <svg class="ico" style="width:14px;height:14px" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
            Resolved: Plot ${_mpdEsc(plotId)} Ground Truth Stabilized with ${choice.toUpperCase()} (${choice === 'cad' ? cadVal : excelVal} m²)
          </div>
        `;
      }
      _mpdAddChatMsg('a', `
        <div style="border-left:3px solid var(--green);padding-left:10px">
          <div style="font-weight:700;color:var(--green);font-size:12.5px;margin-bottom:3px">✅ Ground Truth Relation Stabilized: Plot ${_mpdEsc(plotId)}</div>
          <div style="font-size:12px;color:var(--text);line-height:1.5">
            Confirmed and linked <b>${choice.toUpperCase()}</b> value (<b>${choice === 'cad' ? cadVal : excelVal} m²</b>) as certified ground truth for Plot ${_mpdEsc(plotId)}.
          </div>
          <div style="font-size:11px;color:var(--muted);margin-top:6px">
            Spatial calculations, FAR limits, and subsequent AI chat interactions are now updated and aligned.
          </div>
        </div>
      `);
      await _loadMasterplanData(proj);
      await _loadFilesCount(proj);
      if (typeof window._highlightMpdPlots === 'function') {
        window._highlightMpdPlots([plotId]);
      }
    } else {
      const err = await res.json().catch(() => ({ detail: 'Failed' }));
      toast(`Stabilization failed: ${err.detail || 'Error'}`);
      if (card) {
        card.style.opacity = '1';
        card.querySelectorAll('button').forEach(b => b.disabled = false);
      }
    }
  } catch (e) {
    toast(`Error: ${e.message}`);
    if (card) {
      card.style.opacity = '1';
      card.querySelectorAll('button').forEach(b => b.disabled = false);
    }
  }
};

window._confirmMpdFullLink = async function(proj) {
  toast('Stabilizing all parcels into Agentic AI Ground Truth...');
  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/stabilize-relation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resolutions: {},
        author: 'Design AI Copilot'
      })
    });
    if (res.ok) {
      toast('✅ Successfully stabilized and linked all parcels!');
      _mpdAddChatMsg('a', `
        <div style="border-left:3px solid var(--green);padding-left:10px">
          <div style="font-weight:700;color:var(--green);font-size:13px;margin-bottom:4px">🎉 Masterplan Sources Linked to Agentic AI Model</div>
          <div style="font-size:12px;color:var(--text);line-height:1.5">
            All CAD drawing vector geometry and Excel development registers have been unified into the permanent AI reasoning model. You can now chat directly with the Agentic AI regarding any plot, FAR constraint, or zoning regulation.
          </div>
        </div>
      `);
      await _loadMasterplanData(proj);
      await _loadFilesCount(proj);
    }
  } catch (e) {
    toast(`Failed to link: ${e.message}`);
  }
};

function _openImportModal(proj) {
  const activeProj = _getMpdProject(proj);
  document.querySelectorAll('.mpd-modal-wrapper').forEach(m => m.remove());

  const modal = _mpdEl('div', 'mpd-modal-wrapper modal-overlay cad-modal-overlay', `
    <div class="modal" style="width:540px;max-width:94vw;background:#0d1424;border:1px solid var(--border);border-radius:var(--r-lg);padding:24px;box-shadow:0 14px 40px rgba(0,0,0,.7);display:flex;flex-direction:column;gap:16px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
          <svg class="ico" style="width:20px;height:20px;color:var(--accent2)" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
          Import Masterplan File
        </div>
        <button id="closeImpModal" style="background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1">&times;</button>
      </div>

      <div style="font-size:12px;color:var(--muted);line-height:1.5">
        Upload masterplan documents or drawings for <b>${_mpdEsc(activeProj)}</b>. The system automatically routes the file to the corresponding engine parser:
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:11px">
        <div style="background:var(--surface2);padding:10px;border-radius:6px;border:1px solid var(--border);text-align:center">
          <b style="color:var(--accent2)">DWG / DXF Parser</b><br><span style="color:var(--muted)">Vector parcels, setbacks &amp; layers</span>
        </div>
        <div style="background:var(--surface2);padding:10px;border-radius:6px;border:1px solid var(--border);text-align:center">
          <b style="color:var(--green)">Excel Parser</b><br><span style="color:var(--muted)">Plot registers, BUA, FAR &amp; setbacks</span>
        </div>
        <div style="background:var(--surface2);padding:10px;border-radius:6px;border:1px solid var(--border);text-align:center">
          <b style="color:var(--amber)">PDF Parser</b><br><span style="color:var(--muted)">Zoning datasheets &amp; FAR schedules</span>
        </div>
      </div>

      <div style="border:2px dashed var(--border);border-radius:var(--r-md);padding:28px;text-align:center;background:#080e1b;cursor:pointer;transition:all .2s ease" id="mpdDropZone">
        <input type="file" id="mpdFileInput" accept=".dxf,.dwg,.xlsx,.xls,.pdf" style="display:none">
        <svg class="ico" style="width:36px;height:36px;color:var(--muted);margin-bottom:10px" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
        <div style="font-weight:700;font-size:13px;margin-bottom:4px">Click or Drag &amp; Drop Masterplan File</div>
        <div style="font-size:11px;color:var(--muted)">Supports .dxf, .dwg, .xlsx, .pdf (up to 200MB)</div>
        <div id="mpdSelectedFileName" style="margin-top:10px;font-weight:700;color:var(--accent2)"></div>
      </div>

      <div style="display:flex;justify-content:flex-end;gap:10px">
        <button class="cad-btn" id="cancelImpBtn">Cancel</button>
        <button class="primary" id="startImpBtn" disabled style="padding:7px 18px;background:var(--accent2);border-color:var(--accent2)">Process &amp; Ingest</button>
      </div>
    </div>
  `);
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:99999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(5px)";
  document.body.appendChild(modal);

  let selectedFile = null;
  const fileInput = modal.querySelector('#mpdFileInput');
  const dropZone = modal.querySelector('#mpdDropZone');
  const startBtn = modal.querySelector('#startImpBtn');
  const selectedNameEl = modal.querySelector('#mpdSelectedFileName');
  const closeBtn = modal.querySelector('#closeImpModal');
  const cancelBtn = modal.querySelector('#cancelImpBtn');

  if (closeBtn) closeBtn.onclick = () => modal.remove();
  if (cancelBtn) cancelBtn.onclick = () => modal.remove();
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  if (dropZone && fileInput) {
    dropZone.onclick = () => fileInput.click();
    dropZone.ondragover = (e) => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--accent2)';
      dropZone.style.background = '#0d1933';
    };
    dropZone.ondragleave = (e) => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border)';
      dropZone.style.background = '#080e1b';
    };
    dropZone.ondrop = (e) => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border)';
      dropZone.style.background = '#080e1b';
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        selectedFile = e.dataTransfer.files[0];
        selectedNameEl.textContent = `Selected: ${selectedFile.name} (${(selectedFile.size/1024).toFixed(0)} KB)`;
        startBtn.disabled = false;
      }
    };
    fileInput.onchange = () => {
      if (fileInput.files && fileInput.files.length) {
        selectedFile = fileInput.files[0];
        selectedNameEl.textContent = `Selected: ${selectedFile.name} (${(selectedFile.size/1024).toFixed(0)} KB)`;
        startBtn.disabled = false;
      }
    };
  }

  if (startBtn) {
    startBtn.onclick = async () => {
      if (!selectedFile) return;
      startBtn.disabled = true;
      startBtn.textContent = 'Ingesting & Registering...';

      const form = new FormData();
      form.append('file', selectedFile);

      try {
        const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/import-file`, {
          method: 'POST',
          body: form
        });
        const data = await res.json();
        if (res.ok) {
          toast(`✅ ${data.message}`);
          modal.remove();
          await _loadMasterplanData(activeProj);
          await _loadFilesCount(activeProj);
          _mpdAddChatMsg('a', `
            <div style="border-left:3px solid var(--accent2);padding-left:10px">
              <div style="font-weight:700;color:var(--accent2);font-size:12.5px;margin-bottom:3px">📁 Masterplan File Registered: ${_mpdEsc(data.filename)}</div>
              <div style="font-size:12px;color:var(--text);line-height:1.5">
                Successfully processed and recorded <b>${data.count}</b> plots under MPD. When ready, mention in this AI chat to <b>check file and stabilize the relation</b>, or click <b>Reconcile &amp; Link</b> in the toolbar.
              </div>
            </div>
          `);
        } else {
          toast(`Upload failed: ${data.detail || 'Error'}`);
          startBtn.disabled = false;
          startBtn.textContent = 'Process & Ingest';
        }
      } catch (err) {
        toast(`Error uploading: ${err.message}`);
        startBtn.disabled = false;
        startBtn.textContent = 'Process & Ingest';
      }
    };
  }
}

async function _openAuditLogModal(proj) {
  const activeProj = _getMpdProject(proj);
  document.querySelectorAll('.mpd-modal-wrapper').forEach(m => m.remove());

  const modal = _mpdEl('div', 'mpd-modal-wrapper modal-overlay cad-modal-overlay', `
    <div class="modal" style="width:680px;max-width:94vw;max-height:85vh;background:#0d1424;border:1px solid var(--border);border-radius:var(--r-lg);padding:24px;box-shadow:0 14px 40px rgba(0,0,0,.7);display:flex;flex-direction:column;gap:14px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
          <svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>
          Design Review Audit Log &amp; Undo
        </div>
        <button id="closeAuditModal" style="background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1">&times;</button>
      </div>

      <div style="font-size:12px;color:var(--muted)">
        Chronological audit trail of all parameters adjusted, rules validated, and actions taken during masterplan review meetings:
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:11px;color:var(--faint)">Logged actions with reversible states</span>
        <button class="primary" id="undoActionBtn" style="padding:6px 14px;background:#f5b73d;border-color:#f5b73d;color:#000;font-weight:700">
          ↩ Undo Last Action
        </button>
      </div>

      <div style="flex:1;overflow-y:auto;max-height:450px;border:1px solid var(--border);border-radius:var(--r-sm);background:#070b15;padding:8px" id="auditList">
        <div style="text-align:center;padding:20px;color:var(--muted)">Loading audit records...</div>
      </div>
    </div>
  `);
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:99999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(5px)";
  document.body.appendChild(modal);

  const closeBtn = modal.querySelector('#closeAuditModal');
  const undoBtn = modal.querySelector('#undoActionBtn');
  const listEl = modal.querySelector('#auditList');

  if (closeBtn) closeBtn.onclick = () => modal.remove();
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  async function loadLogs() {
    try {
      const r = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/audit-log`);
      if (r.ok) {
        const logs = await r.json();
        if (!logs.length) {
          listEl.innerHTML = '<div style="text-align:center;padding:30px;color:var(--muted)">No audit actions recorded yet.</div>';
          return;
        }
        listEl.innerHTML = logs.map(l => `
          <div style="padding:10px;border-bottom:1px solid rgba(255,255,255,.05);display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
            <div>
              <div style="font-weight:700;font-size:12px;color:var(--text);margin-bottom:3px">${_mpdEsc(l.description)}</div>
              <div style="font-size:10.5px;color:var(--muted)">Action: <b style="color:var(--accent2)">${_mpdEsc(l.action_type)}</b> · Author: <b>${_mpdEsc(l.author)}</b></div>
            </div>
            <div style="font-size:10px;color:var(--faint);white-space:nowrap">${new Date(l.timestamp).toLocaleTimeString()}</div>
          </div>
        `).join('');
      }
    } catch (e) {}
  }

  if (undoBtn) {
    undoBtn.onclick = async () => {
      try {
        const r = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(activeProj)}/undo`, { method: 'POST' });
        if (r.ok) {
          const data = await r.json();
          toast(`↩ ${data.message}`);
          await loadLogs();
          await _loadMasterplanData(activeProj);
        } else {
          toast('No actions left to undo.');
        }
      } catch (e) {
        toast('Undo failed');
      }
    };
  }

  await loadLogs();
}

window.renderMPDWorkspace = renderMPDWorkspace;
window._switchMpdTab = _switchMpdTab;
window._filterPlots = _filterPlots;
window._selectPlot = _selectPlot;
window._calcInspFar = _calcInspFar;
window._savePlotInspection = _savePlotInspection;
window._sendMpdChip = _sendMpdChip;
window._handleMpdChatSubmit = _handleMpdChatSubmit;
window._highlightMpdPlots = (plots) => {
  _mpdHighlightPlots = Array.isArray(plots) ? plots : [];
  _drawCanvas();
  if (_mpdHighlightPlots.length > 0) {
    _selectPlot(_mpdHighlightPlots[0], true);
  }
};
window._getMpdSelectedPlotId = () => _mpdSelectedPlotId;
window._getMpdPlots = () => _mpdPlots;
window._openImportModal = _openImportModal;
window._openFilesModal = _openFilesModal;
window._triggerReconciliation = _triggerReconciliation;
window._openAuditLogModal = _openAuditLogModal;
window._resolveMpdRelation = _resolveMpdRelation;
window._confirmMpdFullLink = _confirmMpdFullLink;
window._getMpdProject = _getMpdProject;
