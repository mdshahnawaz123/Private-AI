/* ==========================================================================
   CADCraft Studio - Computer-Aided Design & Drafting for Expo Design AI
   Clean-room AutoCAD-style 2D drafting engine inspired by storytold/cadcraft
   (pure Rust AutoCAD reimplementation).
   ========================================================================== */

// Safe accessors for global environment
var $ = (typeof window !== 'undefined' && typeof window.$ === 'function') ? window.$ : (id => document.getElementById(id));
var API = (typeof window !== 'undefined' && window.API) ? window.API : (typeof location !== 'undefined' ? location.origin : '');
var toast = (msg) => (typeof window !== 'undefined' && typeof window.toast === 'function' ? window.toast(msg) : console.log('[Toast]', msg));

var cadEntities = [];
var cadLayers = [
  { name: '0', color: '#808080', visible: true, locked: false, linetype: 'CONTINUOUS' },
  { name: 'WALLS', color: '#e2e8f0', visible: true, locked: false, linetype: 'CONTINUOUS' },
  { name: 'DOORS', color: '#2ecc71', visible: true, locked: false, linetype: 'CONTINUOUS' },
  { name: 'WINDOWS', color: '#3498db', visible: true, locked: false, linetype: 'CONTINUOUS' },
  { name: 'FURNITURE', color: '#f39c12', visible: true, locked: false, linetype: 'CONTINUOUS' },
  { name: 'ROOM_NAMES', color: '#e67e22', visible: true, locked: false, linetype: 'CONTINUOUS' },
  { name: 'DIMS', color: '#00e5ff', visible: true, locked: false, linetype: 'CONTINUOUS' }
];
var activeLayer = 'WALLS';
var cadUndoStack = [];
var cadRedoStack = [];
var selectedEntityIds = new Set();

// Viewport transform
var panX = 0, panY = 0;
var zoom = 0.05; // world units to screen pixels
var isPanning = false;
var panStartX = 0, panStartY = 0;

// Drafting modes: 'select', 'line', 'polyline', 'circle', 'arc', 'rectangle', 'text', 'dimension', 'erase', 'move', 'copy', 'offset'
var activeTool = 'select';
var draftPoints = [];
var mouseWorld = { x: 0, y: 0 };
var snappedPoint = null;
var snapType = null;

// Settings & toggles
var snapEnabled = true;
var gridEnabled = true;
var orthoEnabled = false;
var polarEnabled = false;

// Selection box
var isSelectingBox = false;
var selectBoxStart = { x: 0, y: 0 };
var currentDrawingTitle = 'Untitled Drawing';

// Command Line
const CAD_COMMANDS = {
  'L': 'line', 'LINE': 'line',
  'PL': 'polyline', 'PLINE': 'polyline',
  'C': 'circle', 'CIRCLE': 'circle',
  'REC': 'rectangle', 'RECTANG': 'rectangle', 'RECTANGLE': 'rectangle',
  'A': 'arc', 'ARC': 'arc',
  'T': 'text', 'TEXT': 'text', 'MTEXT': 'text',
  'DIM': 'dimension', 'DIMALIGNED': 'dimension', 'DIMLIN': 'dimension',
  'E': 'erase', 'ERASE': 'erase', 'DEL': 'erase',
  'M': 'move', 'MOVE': 'move',
  'CO': 'copy', 'CP': 'copy', 'COPY': 'copy',
  'O': 'offset', 'OFFSET': 'offset',
  'Z': 'zoom', 'ZOOM': 'zoom',
  'U': 'undo', 'UNDO': 'undo',
  'REDO': 'redo',
  'LA': 'layers', 'LAYER': 'layers',
  'RE': 'regen', 'REGEN': 'regen',
  'GRID': 'grid', 'ORTHO': 'ortho', 'OSNAP': 'osnap'
};

/* ==========================================================================
   RENDER CADCRAFT WORKSPACE UI
   ========================================================================== */
function renderCadCraftWorkspace(container) {
  container.innerHTML = `
    <div class="cad-workspace-root">
      <!-- TOP RIBBON TOOLBAR -->
      <div class="cad-ribbon">
        <div class="cad-ribbon-group">
          <div class="cad-group-title">FILE & CADCRAFT</div>
          <div class="cad-group-btns">
            <button class="cad-btn primary" id="cadOpenBtn" title="Open DXF or DWG file">
              <svg class="ico" viewBox="0 0 24 24"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>
              <span>Open CAD</span>
            </button>
            <input type="file" id="cadFileInput" accept=".dxf,.dwg" style="display:none">

            <button class="cad-btn" id="cadSaveBtn" title="Save DXF into project Drawings folder">
              <svg class="ico" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              <span>Save DXF</span>
            </button>

            <div class="cad-dropdown-wrap">
              <button class="cad-btn" id="cadSamplesBtn" title="Load architectural & engineering sample drawings">
                <svg class="ico" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span>Samples ▼</span>
              </button>
              <div class="cad-dropdown-menu" id="cadSamplesMenu" style="display:none">
                <a href="javascript:void(0)" data-sample="sample_apartment_plan">🏠 Apartment Floor Plan (CADCraft)</a>
                <a href="javascript:void(0)" data-sample="sample_structural_core">🏗️ Structural Column Grid & Core</a>
                <a href="javascript:void(0)" data-sample="sample_mechanical_bracket">⚙️ Mechanical Mounting Bracket</a>
              </div>
            </div>

            <button class="cad-btn" id="cadExportDxfBtn" title="Export as AutoCAD DXF file">
              <svg class="ico" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              <span>Export DXF</span>
            </button>
          </div>
        </div>

        <div class="cad-ribbon-sep"></div>

        <div class="cad-ribbon-group">
          <div class="cad-group-title">DRAW TOOLS</div>
          <div class="cad-group-btns">
            <button class="cad-tool-btn on" data-tool="select" title="Selection Tool (Space/Esc)"><svg class="ico" viewBox="0 0 24 24"><path d="M3 3l7 18 3-7 7-3L3 3z"/></svg><span>Select</span></button>
            <button class="cad-tool-btn" data-tool="line" title="Line (L)"><svg class="ico" viewBox="0 0 24 24"><line x1="4" y1="20" x2="20" y2="4"/></svg><span>Line</span></button>
            <button class="cad-tool-btn" data-tool="polyline" title="Polyline (PL)"><svg class="ico" viewBox="0 0 24 24"><polyline points="4 18 10 6 16 14 20 4"/></svg><span>Polyline</span></button>
            <button class="cad-tool-btn" data-tool="circle" title="Circle (C)"><svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/></svg><span>Circle</span></button>
            <button class="cad-tool-btn" data-tool="arc" title="3-Point Arc (A)"><svg class="ico" viewBox="0 0 24 24"><path d="M4 18a9 9 0 0 1 16 0"/></svg><span>Arc</span></button>
            <button class="cad-tool-btn" data-tool="rectangle" title="Rectangle (REC)"><svg class="ico" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="1"/></svg><span>Rect</span></button>
            <button class="cad-tool-btn" data-tool="text" title="Text Note (T)"><svg class="ico" viewBox="0 0 24 24"><polyline points="4 7 4 4 20 4 20 7"/><line x1="12" y1="4" x2="12" y2="20"/></svg><span>Text</span></button>
            <button class="cad-tool-btn" data-tool="dimension" title="Linear Dimension (DIM)"><svg class="ico" viewBox="0 0 24 24"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="3" y2="18"/><line x1="21" y1="6" x2="21" y2="18"/></svg><span>Dim</span></button>
          </div>
        </div>

        <div class="cad-ribbon-sep"></div>

        <div class="cad-ribbon-group">
          <div class="cad-group-title">MODIFY & VIEW</div>
          <div class="cad-group-btns">
            <button class="cad-tool-btn" data-tool="erase" title="Erase selected (E / Del)"><svg class="ico" viewBox="0 0 24 24"><path d="M19 6L6 19M6 6l13 13"/></svg><span>Erase</span></button>
            <button class="cad-tool-btn" data-tool="move" title="Move (M)"><svg class="ico" viewBox="0 0 24 24"><polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg><span>Move</span></button>
            <button class="cad-tool-btn" data-tool="copy" title="Copy (CO)"><svg class="ico" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg><span>Copy</span></button>
            <button class="cad-tool-btn" data-tool="offset" title="Offset (O)"><svg class="ico" viewBox="0 0 24 24"><path d="M4 14l8-8 8 8M4 20l8-8 8 8"/></svg><span>Offset</span></button>
            <button class="cad-btn" id="cadZoomExtentsBtn" title="Zoom to Extents (Z E)"><svg class="ico" viewBox="0 0 24 24"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg><span>Extents</span></button>
            <button class="cad-btn" id="cadUndoBtn" title="Undo (Ctrl+Z)"><svg class="ico" viewBox="0 0 24 24"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>
            <button class="cad-btn" id="cadRedoBtn" title="Redo (Ctrl+Y)"><svg class="ico" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>
          </div>
        </div>

        <div class="cad-ribbon-sep"></div>

        <!-- GENERATIVE AI & CADCRAFT RUST BRIDGE -->
        <div class="cad-ribbon-group" style="margin-left:auto">
          <div class="cad-group-title">AI & CADCRAFT ENGINE</div>
          <div class="cad-group-btns">
            <button class="cad-btn ai" id="cadRenderInAiStudioBtn" title="Render CAD model into AI Design Studio for 3D photorealistic concept generation">
              <svg class="ico" viewBox="0 0 24 24"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><circle cx="12" cy="12" r="9"/></svg>
              <span>🎨 Render in AI Studio</span>
            </button>
            <button class="cad-btn ghost" id="cadEngineInfoBtn" title="View CADCraft Pure Rust Architecture & CLI Info">
              <svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
              <span>CADCraft Engine</span>
            </button>
          </div>
        </div>
      </div>

      <!-- MAIN CANVAS & PALETTES CONTAINER -->
      <div class="cad-center-area">
        <!-- CANVAS WORKSPACE -->
        <div class="cad-canvas-wrap" id="cadCanvasWrap">
          <canvas id="cadCanvas"></canvas>

          <!-- LOADING OVERLAY -->
          <div class="cad-loading-overlay" id="cadLoadingOverlay" style="display:none">
            <div class="cad-spinner"></div>
            <div id="cadLoadingText" style="font-weight:600;font-size:13px;color:#fff">Loading CAD drawing...</div>
            <div id="cadLoadingSubtext" style="font-size:11px;color:var(--muted)">Converting vector geometry & layers</div>
          </div>

          <!-- UCS ICON OVERLAY -->
          <div class="cad-ucs-icon">
            <svg viewBox="0 0 40 40" width="40" height="40">
              <line x1="8" y1="32" x2="36" y2="32" stroke="#ff4757" stroke-width="2"/>
              <line x1="8" y1="32" x2="8" y2="4" stroke="#2ed573" stroke-width="2"/>
              <text x="32" y="28" fill="#ff4757" font-size="9" font-family="monospace" font-weight="bold">X</text>
              <text x="12" y="12" fill="#2ed573" font-size="9" font-family="monospace" font-weight="bold">Y</text>
              <rect x="6" y="30" width="4" height="4" fill="#ffffff"/>
            </svg>
          </div>

          <!-- PROMPT BANNER OVERLAY -->
          <div class="cad-prompt-banner" id="cadPromptBanner" style="display:none"></div>
        </div>

        <!-- RIGHT COLLAPSIBLE SIDEBAR: LAYERS & PROPERTIES -->
        <aside class="cad-side-palette" id="cadSidePalette">
          <!-- LAYERS SECTION -->
          <div class="cad-palette-box">
            <div class="cad-palette-head">
              <span>LAYERS</span>
              <button class="cad-mini-btn" id="cadAddLayerBtn" title="Create new layer">+ New</button>
            </div>
            <div class="cad-layer-table-wrap">
              <table class="cad-layer-table">
                <thead><tr><th>St</th><th>Color</th><th>Name</th><th>Lock</th></tr></thead>
                <tbody id="cadLayerList"></tbody>
              </table>
            </div>
            <div style="display:flex;align-items:center;gap:6px;margin-top:6px;font-size:11px">
              <span style="color:var(--muted)">Active:</span>
              <select id="cadActiveLayerSel" style="flex:1;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:3px"></select>
            </div>
          </div>

          <!-- PROPERTIES SECTION -->
          <div class="cad-palette-box" style="flex:1;display:flex;flex-direction:column">
            <div class="cad-palette-head">
              <span>PROPERTIES</span>
            </div>
            <div id="cadPropsContent" class="cad-props-body">
              <div style="color:var(--muted);font-size:11px;padding:8px 4px">No entity selected.<br>Click an entity to inspect or edit.</div>
            </div>
          </div>
        </aside>
      </div>

      <!-- COMMAND LINE AREA -->
      <div class="cad-cmd-area">
        <div class="cad-cmd-history" id="cadCmdHistory">
          <div class="cad-log-line">CADCraft Engine v0.4.2 [AutoCAD Clean-Room Pure Rust Environment]</div>
          <div class="cad-log-line">Model Space initialized. Type L (LINE), C (CIRCLE), REC (RECTANGLE), DIM, or Z E (Zoom Extents).</div>
        </div>
        <div class="cad-cmd-input-row">
          <span class="cad-cmd-label">Command:</span>
          <input type="text" class="cad-cmd-input" id="cadCmdInput" placeholder="Type a command or select a tool above..." autocomplete="off" spellcheck="false">
          <div class="cad-cmd-suggest" id="cadCmdSuggest" style="display:none"></div>
        </div>
      </div>

      <!-- STATUS BAR -->
      <div class="cad-status-bar">
        <div class="cad-coords" id="cadCoordsReadout">X: 0.000  Y: 0.000  Z: 0.000</div>
        <div class="cad-status-sep"></div>
        <div class="cad-status-toggles">
          <span class="cad-toggle on" id="cadTogModel">MODEL</span>
          <span class="cad-toggle on" id="cadTogGrid" title="Toggle Grid (F7)">GRID</span>
          <span class="cad-toggle on" id="cadTogSnap" title="Toggle Object Snaps (F3)">OSNAP</span>
          <span class="cad-toggle" id="cadTogOrtho" title="Toggle Ortho Mode (F8)">ORTHO</span>
          <span class="cad-toggle" id="cadTogPolar" title="Toggle Polar Tracking (F10)">POLAR</span>
        </div>
        <div style="margin-left:auto;display:flex;align-items:center;gap:12px;font-size:10.5px;color:var(--muted)">
          <span id="cadEntityCountReadout">Entities: 0</span>
          <span>Scale: 1:1 (Metric mm)</span>
          <span style="color:var(--accent2);font-weight:600">CADCraft Pure Rust</span>
        </div>
      </div>
    </div>
  `;

  _initCadCraftEngine();
}

/* ==========================================================================
   CAD ENGINE INITIALIZATION & EVENT BINDINGS
   ========================================================================== */
function _initCadCraftEngine() {
  const canvas = $('cadCanvas');
  const wrap = $('cadCanvasWrap');
  if (!canvas || !wrap) return;

  // Resize canvas
  function resizeCanvas() {
    const rect = wrap.getBoundingClientRect();
    canvas.width = rect.width * (window.devicePixelRatio || 1);
    canvas.height = rect.height * (window.devicePixelRatio || 1);
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    _drawCadCanvas();
  }
  window.addEventListener('resize', resizeCanvas);
  setTimeout(resizeCanvas, 50);

  // Set initial pan/zoom
  panX = wrap.clientWidth / 2;
  panY = wrap.clientHeight / 2;

  // Tool buttons
  document.querySelectorAll('.cad-tool-btn').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.cad-tool-btn').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      setCadTool(btn.getAttribute('data-tool'));
    };
  });

  // Toggles
  const togGrid = $('cadTogGrid');
  if (togGrid) togGrid.onclick = () => { gridEnabled = !gridEnabled; togGrid.classList.toggle('on', gridEnabled); _drawCadCanvas(); };

  const togSnap = $('cadTogSnap');
  if (togSnap) togSnap.onclick = () => { snapEnabled = !snapEnabled; togSnap.classList.toggle('on', snapEnabled); };

  const togOrtho = $('cadTogOrtho');
  if (togOrtho) togOrtho.onclick = () => { orthoEnabled = !orthoEnabled; togOrtho.classList.toggle('on', orthoEnabled); };

  // Zoom extents button
  const zExtBtn = $('cadZoomExtentsBtn');
  if (zExtBtn) zExtBtn.onclick = zoomExtents;

  // Undo / Redo
  const uBtn = $('cadUndoBtn');
  if (uBtn) uBtn.onclick = cadUndo;
  const rBtn = $('cadRedoBtn');
  if (rBtn) rBtn.onclick = cadRedo;

  // Open file
  const openBtn = $('cadOpenBtn');
  const fileInp = $('cadFileInput');
  if (openBtn && fileInp) {
    openBtn.onclick = () => fileInp.click();
    fileInp.onchange = async () => {
      if (fileInp.files && fileInp.files[0]) {
        await _loadCadFromFile(fileInp.files[0]);
      }
    };
  }

  // Save DXF
  const saveBtn = $('cadSaveBtn');
  if (saveBtn) saveBtn.onclick = _saveCadDrawingToProject;

  // Export DXF
  const expBtn = $('cadExportDxfBtn');
  if (expBtn) expBtn.onclick = _exportCadDrawingDxf;

  // Samples dropdown
  const samplesBtn = $('cadSamplesBtn');
  const samplesMenu = $('cadSamplesMenu');
  if (samplesBtn && samplesMenu) {
    samplesBtn.onclick = (e) => {
      e.stopPropagation();
      samplesMenu.style.display = samplesMenu.style.display === 'none' ? 'block' : 'none';
    };
    document.addEventListener('click', () => { if (samplesMenu) samplesMenu.style.display = 'none'; });
    samplesMenu.querySelectorAll('a[data-sample]').forEach(a => {
      a.onclick = async () => {
        const sampleId = a.getAttribute('data-sample');
        await _loadCadSample(sampleId);
      };
    });
  }

  // AI Studio Render conditioning
  const aiBtn = $('cadRenderInAiStudioBtn');
  if (aiBtn) aiBtn.onclick = _renderCadForAiStudio;

  // Engine info modal
  const infoBtn = $('cadEngineInfoBtn');
  if (infoBtn) infoBtn.onclick = _showCadCraftInfoModal;

  // Canvas Mouse Interactions
  canvas.onmousedown = _onCanvasMouseDown;
  window.addEventListener('mousemove', _onCanvasMouseMove);
  window.addEventListener('mouseup', _onCanvasMouseUp);
  canvas.onwheel = _onCanvasWheel;
  canvas.oncontextmenu = (e) => { e.preventDefault(); _onCanvasContextMenu(e); };

  // Command Input
  const cmdInp = $('cadCmdInput');
  if (cmdInp) {
    cmdInp.onkeydown = (e) => {
      if (e.key === 'Enter') {
        const val = cmdInp.value.trim();
        cmdInp.value = '';
        if (val) _executeCadCommand(val);
      } else if (e.key === 'Escape') {
        cancelCurrentCommand();
        cmdInp.blur();
      }
    };
  }

  // Keyboard hotkeys
  window.addEventListener('keydown', (e) => {
    if (currentDest !== 'cadcraft') return;
    if (document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA')) {
      if (document.activeElement.id !== 'cadCmdInput') return;
    }
    if (e.key === 'Escape') { cancelCurrentCommand(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') {
      if (document.activeElement.id !== 'cadCmdInput') { eraseSelectedEntities(); }
    }
    else if (e.ctrlKey && e.key.toLowerCase() === 'z') { e.preventDefault(); cadUndo(); }
    else if (e.ctrlKey && e.key.toLowerCase() === 'y') { e.preventDefault(); cadRedo(); }
    else if (e.key === 'F7') { e.preventDefault(); gridEnabled = !gridEnabled; $('cadTogGrid').classList.toggle('on', gridEnabled); _drawCadCanvas(); }
    else if (e.key === 'F8') { e.preventDefault(); orthoEnabled = !orthoEnabled; $('cadTogOrtho').classList.toggle('on', orthoEnabled); }
    else if (e.key === 'F3') { e.preventDefault(); snapEnabled = !snapEnabled; $('cadTogSnap').classList.toggle('on', snapEnabled); }
  });

  // Layer list rendering
  _refreshCadLayersUI();

  // Load sample apartment plan by default if empty
  if (cadEntities.length === 0 && !window._cadSkipDefaultSample) {
    _loadCadSample('sample_apartment_plan');
  } else {
    _drawCadCanvas();
  }
}

/* ==========================================================================
   COORDINATE TRANSFORMS: WORLD <-> SCREEN
   ========================================================================== */
function worldToScreen(wx, wy) {
  const dpr = window.devicePixelRatio || 1;
  const sx = panX + wx * zoom;
  const sy = panY - wy * zoom; // Invert CAD Y
  return { x: sx * dpr, y: sy * dpr };
}

function screenToWorld(sx, sy) {
  const wx = (sx - panX) / zoom;
  const wy = (panY - sy) / zoom;
  return { x: wx, y: wy };
}

/* ==========================================================================
   CANVAS DRAWING PIPELINE
   ========================================================================== */
function _drawCadCanvas() {
  const canvas = $('cadCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width;
  const h = canvas.height;

  // Clear Model Space Background (#181a20)
  ctx.fillStyle = '#181a20';
  ctx.fillRect(0, 0, w, h);

  // 1. Grid
  if (gridEnabled) {
    _drawGrid(ctx, w, h, dpr);
  }

  // 2. World Axes
  _drawWorldAxes(ctx);

  // 3. Render CAD Entities
  cadEntities.forEach(ent => {
    // Check layer visibility
    const layerObj = cadLayers.find(l => l.name === ent.layer);
    if (layerObj && !layerObj.visible) return;

    const isSelected = selectedEntityIds.has(ent.id);
    _renderCadEntity(ctx, ent, isSelected);
  });

  // 4. In-progress drafting rubber-band
  _renderDraftingPreview(ctx);

  // 5. Selection Window
  if (isSelectingBox) {
    _renderSelectionBox(ctx);
  }

  // 6. Object Snap marker
  if (snappedPoint) {
    _renderSnapMarker(ctx, snappedPoint, snapType);
  }

  // Update entity count readout
  const countEl = $('cadEntityCountReadout');
  if (countEl) countEl.textContent = `Entities: ${cadEntities.length}`;
}

function _drawGrid(ctx, w, h, dpr) {
  // Determine adaptive grid step
  const minPixels = 20 * dpr;
  let gridStep = 100; // 100mm
  while (gridStep * zoom * dpr < minPixels) { gridStep *= 5; }
  while (gridStep * zoom * dpr > minPixels * 5) { gridStep /= 2; }

  const minW = screenToWorld(0, h / dpr);
  const maxW = screenToWorld(w / dpr, 0);

  const startX = Math.floor(minW.x / gridStep) * gridStep;
  const endX = Math.ceil(maxW.x / gridStep) * gridStep;
  const startY = Math.floor(minW.y / gridStep) * gridStep;
  const endY = Math.ceil(maxW.y / gridStep) * gridStep;

  ctx.lineWidth = 1;
  for (let x = startX; x <= endX; x += gridStep) {
    const isMajor = Math.abs(x % (gridStep * 5)) < 1e-4;
    ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.03)';
    const p1 = worldToScreen(x, minW.y);
    const p2 = worldToScreen(x, maxW.y);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }

  for (let y = startY; y <= endY; y += gridStep) {
    const isMajor = Math.abs(y % (gridStep * 5)) < 1e-4;
    ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.03)';
    const p1 = worldToScreen(minW.x, y);
    const p2 = worldToScreen(maxW.x, y);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }
}

function _drawWorldAxes(ctx) {
  const orig = worldToScreen(0, 0);
  const dpr = window.devicePixelRatio || 1;

  ctx.lineWidth = 1.5 * dpr;
  // X axis (Red)
  ctx.strokeStyle = 'rgba(255, 71, 87, 0.45)';
  ctx.beginPath();
  ctx.moveTo(orig.x, orig.y);
  ctx.lineTo(orig.x + 80 * dpr, orig.y);
  ctx.stroke();

  // Y axis (Green)
  ctx.strokeStyle = 'rgba(46, 213, 115, 0.45)';
  ctx.beginPath();
  ctx.moveTo(orig.x, orig.y);
  ctx.lineTo(orig.x, orig.y - 80 * dpr);
  ctx.stroke();
}

function _renderCadEntity(ctx, ent, isSelected) {
  const dpr = window.devicePixelRatio || 1;
  ctx.save();

  if (isSelected) {
    ctx.strokeStyle = '#00ffff';
    ctx.fillStyle = '#00ffff';
    ctx.lineWidth = 2.5 * dpr;
    ctx.setLineDash([4 * dpr, 2 * dpr]);
  } else {
    ctx.strokeStyle = ent.color || '#ffffff';
    ctx.fillStyle = ent.color || '#ffffff';
    ctx.lineWidth = (ent.layer === 'WALLS' ? 2 : 1.2) * dpr;
    ctx.setLineDash([]);
  }

  const type = ent.type;

  if (type === 'LINE') {
    const p1 = worldToScreen(ent.x1, ent.y1);
    const p2 = worldToScreen(ent.x2, ent.y2);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  } else if (type === 'POLYLINE' && ent.points && ent.points.length >= 2) {
    ctx.beginPath();
    const p0 = worldToScreen(ent.points[0][0], ent.points[0][1]);
    ctx.moveTo(p0.x, p0.y);
    for (let i = 1; i < ent.points.length; i++) {
      const p = worldToScreen(ent.points[i][0], ent.points[i][1]);
      ctx.lineTo(p.x, p.y);
    }
    if (ent.closed) ctx.closePath();
    ctx.stroke();
  } else if (type === 'CIRCLE') {
    const c = worldToScreen(ent.cx, ent.cy);
    const r = ent.radius * zoom * dpr;
    ctx.beginPath();
    ctx.arc(c.x, c.y, Math.max(r, 1), 0, Math.PI * 2);
    ctx.stroke();
  } else if (type === 'ARC') {
    const c = worldToScreen(ent.cx, ent.cy);
    const r = ent.radius * zoom * dpr;
    // Invert angles for CAD coordinate system (CCW in world -> CW in canvas)
    const sa = -ent.start_angle * (Math.PI / 180);
    const ea = -ent.end_angle * (Math.PI / 180);
    ctx.beginPath();
    ctx.arc(c.x, c.y, Math.max(r, 1), ea, sa, false);
    ctx.stroke();
  } else if (type === 'TEXT') {
    const p = worldToScreen(ent.x, ent.y);
    const h = (ent.height || 250) * zoom * dpr;
    ctx.font = `${Math.max(10 * dpr, h)}px sans-serif`;
    ctx.fillText(ent.text, p.x, p.y);
  } else if (type === 'DIMENSION') {
    _renderDimension(ctx, ent, isSelected, dpr);
  }

  ctx.restore();
}

function _renderDimension(ctx, ent, isSelected, dpr) {
  const p1 = worldToScreen(ent.x1, ent.y1);
  const p2 = worldToScreen(ent.x2, ent.y2);

  ctx.beginPath();
  ctx.moveTo(p1.x, p1.y);
  ctx.lineTo(p2.x, p2.y);
  ctx.stroke();

  // Architectural ticks (45-degree slashes)
  const tickLen = 6 * dpr;
  ctx.beginPath();
  ctx.moveTo(p1.x - tickLen, p1.y + tickLen);
  ctx.lineTo(p1.x + tickLen, p1.y - tickLen);
  ctx.moveTo(p2.x - tickLen, p2.y + tickLen);
  ctx.lineTo(p2.x + tickLen, p2.y - tickLen);
  ctx.stroke();

  // Dimension text at midpoint
  const midX = (p1.x + p2.x) / 2;
  const midY = (p1.y + p2.y) / 2 - 8 * dpr;
  ctx.font = `bold ${10 * dpr}px monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(ent.text || '', midX, midY);
}

function _renderDraftingPreview(ctx) {
  if (draftPoints.length === 0) return;
  const dpr = window.devicePixelRatio || 1;
  const p1 = worldToScreen(draftPoints[0].x, draftPoints[0].y);
  const p2 = worldToScreen(mouseWorld.x, mouseWorld.y);

  ctx.save();
  ctx.strokeStyle = '#2ecc71';
  ctx.lineWidth = 1.5 * dpr;
  ctx.setLineDash([4 * dpr, 3 * dpr]);

  if (activeTool === 'line' || activeTool === 'dimension') {
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  } else if (activeTool === 'rectangle') {
    const rx = Math.min(p1.x, p2.x);
    const ry = Math.min(p1.y, p2.y);
    const rw = Math.abs(p2.x - p1.x);
    const rh = Math.abs(p2.y - p1.y);
    ctx.strokeRect(rx, ry, rw, rh);
  } else if (activeTool === 'circle') {
    const r = Math.hypot(mouseWorld.x - draftPoints[0].x, mouseWorld.y - draftPoints[0].y) * zoom * dpr;
    ctx.beginPath();
    ctx.arc(p1.x, p1.y, r, 0, Math.PI * 2);
    ctx.stroke();
  } else if (activeTool === 'polyline') {
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    for (let i = 1; i < draftPoints.length; i++) {
      const pt = worldToScreen(draftPoints[i].x, draftPoints[i].y);
      ctx.lineTo(pt.x, pt.y);
    }
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }

  ctx.restore();
}

function _renderSelectionBox(ctx) {
  const dpr = window.devicePixelRatio || 1;
  const p1 = worldToScreen(selectBoxStart.x, selectBoxStart.y);
  const p2 = worldToScreen(mouseWorld.x, mouseWorld.y);

  const rx = Math.min(p1.x, p2.x);
  const ry = Math.min(p1.y, p2.y);
  const rw = Math.abs(p2.x - p1.x);
  const rh = Math.abs(p2.y - p1.y);

  const isCrossing = mouseWorld.x < selectBoxStart.x; // Dragging left = green crossing

  ctx.save();
  if (isCrossing) {
    ctx.fillStyle = 'rgba(46, 204, 113, 0.15)';
    ctx.strokeStyle = '#2ecc71';
    ctx.setLineDash([4 * dpr, 2 * dpr]);
  } else {
    ctx.fillStyle = 'rgba(52, 152, 219, 0.15)';
    ctx.strokeStyle = '#3498db';
    ctx.setLineDash([]);
  }
  ctx.fillRect(rx, ry, rw, rh);
  ctx.strokeRect(rx, ry, rw, rh);
  ctx.restore();
}

function _renderSnapMarker(ctx, pt, type) {
  const dpr = window.devicePixelRatio || 1;
  const p = worldToScreen(pt.x, pt.y);
  const sz = 7 * dpr;

  ctx.save();
  ctx.strokeStyle = '#2ecc71';
  ctx.lineWidth = 2 * dpr;
  ctx.setLineDash([]);

  if (type === 'Endpoint') {
    ctx.strokeRect(p.x - sz, p.y - sz, sz * 2, sz * 2);
  } else if (type === 'Midpoint') {
    ctx.beginPath();
    ctx.moveTo(p.x, p.y - sz);
    ctx.lineTo(p.x + sz, p.y + sz);
    ctx.lineTo(p.x - sz, p.y + sz);
    ctx.closePath();
    ctx.stroke();
  } else if (type === 'Center') {
    ctx.beginPath();
    ctx.arc(p.x, p.y, sz, 0, Math.PI * 2);
    ctx.stroke();
  } else {
    ctx.strokeRect(p.x - sz, p.y - sz, sz * 2, sz * 2);
  }

  // Tooltip
  ctx.font = `${9 * dpr}px sans-serif`;
  ctx.fillStyle = '#2ecc71';
  ctx.fillText(type || 'Snap', p.x + 10 * dpr, p.y - 8 * dpr);
  ctx.restore();
}

/* ==========================================================================
   OBJECT SNAPPING & ORTHO ENGINE
   ========================================================================== */
function _computeSnapPoint(rawWx, rawWy) {
  if (!snapEnabled) return { point: { x: rawWx, y: rawWy }, type: null };

  const snapToleranceWorld = 14 / zoom;
  let closestDist = snapToleranceWorld;
  let bestPt = null;
  let bestType = null;

  cadEntities.forEach(ent => {
    // Endpoints
    if (ent.type === 'LINE') {
      const d1 = Math.hypot(ent.x1 - rawWx, ent.y1 - rawWy);
      if (d1 < closestDist) { closestDist = d1; bestPt = { x: ent.x1, y: ent.y1 }; bestType = 'Endpoint'; }
      const d2 = Math.hypot(ent.x2 - rawWx, ent.y2 - rawWy);
      if (d2 < closestDist) { closestDist = d2; bestPt = { x: ent.x2, y: ent.y2 }; bestType = 'Endpoint'; }

      // Midpoint
      const mx = (ent.x1 + ent.x2) / 2, my = (ent.y1 + ent.y2) / 2;
      const dm = Math.hypot(mx - rawWx, my - rawWy);
      if (dm < closestDist) { closestDist = dm; bestPt = { x: mx, y: my }; bestType = 'Midpoint'; }
    } else if (ent.type === 'CIRCLE' || ent.type === 'ARC') {
      // Center
      const dc = Math.hypot(ent.cx - rawWx, ent.cy - rawWy);
      if (dc < closestDist) { closestDist = dc; bestPt = { x: ent.cx, y: ent.cy }; bestType = 'Center'; }
    }
  });

  if (bestPt) {
    return { point: bestPt, type: bestType };
  }

  // Ortho lock if active and drafting from a point
  if (orthoEnabled && draftPoints.length > 0) {
    const origin = draftPoints[draftPoints.length - 1];
    const dx = Math.abs(rawWx - origin.x);
    const dy = Math.abs(rawWy - origin.y);
    if (dx > dy) {
      return { point: { x: rawWx, y: origin.y }, type: null };
    } else {
      return { point: { x: origin.x, y: rawWy }, type: null };
    }
  }

  return { point: { x: rawWx, y: rawWy }, type: null };
}

/* ==========================================================================
   CANVAS MOUSE & EVENT HANDLERS
   ========================================================================== */
function _onCanvasMouseDown(e) {
  const canvas = $('cadCanvas');
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;

  // Middle-mouse or Space+Left: Pan
  if (e.button === 1 || (e.button === 0 && e.spaceKey)) {
    isPanning = true;
    panStartX = e.clientX - panX;
    panStartY = e.clientY - panY;
    canvas.style.cursor = 'grab';
    return;
  }

  if (e.button === 0) {
    const w = screenToWorld(sx, sy);
    const snap = _computeSnapPoint(w.x, w.y);
    const clickPoint = snap.point;

    if (activeTool === 'select') {
      // Try picking an entity directly
      const picked = _pickEntityAt(w.x, w.y);
      if (picked) {
        if (!e.shiftKey) selectedEntityIds.clear();
        selectedEntityIds.add(picked.id);
        _renderPropertiesPanel();
      } else {
        // Start selection rectangle
        isSelectingBox = true;
        selectBoxStart = { x: w.x, y: w.y };
        if (!e.shiftKey) selectedEntityIds.clear();
      }
      _drawCadCanvas();
    } else {
      // Drafting mode point collection
      _handleDraftClick(clickPoint);
    }
  }
}

function _onCanvasMouseMove(e) {
  const canvas = $('cadCanvas');
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;

  if (isPanning) {
    panX = e.clientX - panStartX;
    panY = e.clientY - panStartY;
    _drawCadCanvas();
    return;
  }

  const rawW = screenToWorld(sx, sy);
  const snapRes = _computeSnapPoint(rawW.x, rawW.y);
  mouseWorld = snapRes.point;
  snappedPoint = snapRes.type ? snapRes.point : null;
  snapType = snapRes.type;

  // Status bar coordinates
  const coordEl = $('cadCoordsReadout');
  if (coordEl) coordEl.textContent = `X: ${mouseWorld.x.toFixed(3)}  Y: ${mouseWorld.y.toFixed(3)}  Z: 0.000`;

  _drawCadCanvas();
}

function _onCanvasMouseUp(e) {
  if (isPanning) {
    isPanning = false;
    const canvas = $('cadCanvas');
    if (canvas) canvas.style.cursor = 'crosshair';
  }

  if (isSelectingBox) {
    isSelectingBox = false;
    _finishSelectionBox();
    _drawCadCanvas();
    _renderPropertiesPanel();
  }
}

function _onCanvasWheel(e) {
  e.preventDefault();
  const canvas = $('cadCanvas');
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;

  const worldBefore = screenToWorld(sx, sy);
  const factor = e.deltaY < 0 ? 1.15 : 0.87;
  zoom = Math.max(0.0005, Math.min(zoom * factor, 50.0));

  panX = sx - worldBefore.x * zoom;
  panY = sy + worldBefore.y * zoom;

  _drawCadCanvas();
}

function _onCanvasContextMenu(e) {
  // Right-click commits drafting or cancels
  if (draftPoints.length > 0) {
    _commitDrafting();
  } else {
    cancelCurrentCommand();
  }
}

/* ==========================================================================
   DRAFTING STATE MACHINE
   ========================================================================== */
function setCadTool(tool) {
  cancelCurrentCommand();
  activeTool = tool;
  const banner = $('cadPromptBanner');

  if (tool === 'select') {
    if (banner) banner.style.display = 'none';
    logCmd('Select mode: Click entity or drag selection window.');
  } else if (tool === 'line') {
    showPrompt('LINE: Specify first point:');
  } else if (tool === 'polyline') {
    showPrompt('PLINE: Specify start point:');
  } else if (tool === 'circle') {
    showPrompt('CIRCLE: Specify center point:');
  } else if (tool === 'rectangle') {
    showPrompt('RECTANGLE: Specify first corner:');
  } else if (tool === 'arc') {
    showPrompt('ARC: Specify start point:');
  } else if (tool === 'text') {
    showPrompt('TEXT: Specify text placement point:');
  } else if (tool === 'dimension') {
    showPrompt('DIMENSION: Specify first extension point:');
  }
  _drawCadCanvas();
}

function showPrompt(text) {
  const banner = $('cadPromptBanner');
  if (banner) {
    banner.textContent = text;
    banner.style.display = 'block';
  }
  logCmd(text);
}

function _handleDraftClick(pt) {
  draftPoints.push({ x: pt.x, y: pt.y });

  if (activeTool === 'line') {
    if (draftPoints.length === 1) {
      showPrompt('LINE: Specify next point or [Enter to finish]:');
    } else {
      _saveHistory();
      cadEntities.push({
        id: `ent_${Date.now()}_${Math.floor(Math.random()*1000)}`,
        type: 'LINE',
        layer: activeLayer,
        color: _getActiveLayerColor(),
        x1: Math.round(draftPoints[0].x),
        y1: Math.round(draftPoints[0].y),
        x2: Math.round(pt.x),
        y2: Math.round(pt.y)
      });
      draftPoints = [{ x: pt.x, y: pt.y }]; // Continue line chain
      _drawCadCanvas();
    }
  } else if (activeTool === 'circle') {
    if (draftPoints.length === 1) {
      showPrompt('CIRCLE: Specify radius:');
    } else {
      const r = Math.hypot(pt.x - draftPoints[0].x, pt.y - draftPoints[0].y);
      if (r > 1) {
        _saveHistory();
        cadEntities.push({
          id: `ent_${Date.now()}_${Math.floor(Math.random()*1000)}`,
          type: 'CIRCLE',
          layer: activeLayer,
          color: _getActiveLayerColor(),
          cx: Math.round(draftPoints[0].x),
          cy: Math.round(draftPoints[0].y),
          radius: Math.round(r)
        });
      }
      cancelCurrentCommand();
    }
  } else if (activeTool === 'rectangle') {
    if (draftPoints.length === 1) {
      showPrompt('RECTANGLE: Specify other corner:');
    } else {
      const p1 = draftPoints[0];
      const p2 = pt;
      _saveHistory();
      cadEntities.push({
        id: `ent_${Date.now()}_${Math.floor(Math.random()*1000)}`,
        type: 'POLYLINE',
        layer: activeLayer,
        color: _getActiveLayerColor(),
        points: [
          [Math.round(p1.x), Math.round(p1.y)],
          [Math.round(p2.x), Math.round(p1.y)],
          [Math.round(p2.x), Math.round(p2.y)],
          [Math.round(p1.x), Math.round(p2.y)]
        ],
        closed: true
      });
      cancelCurrentCommand();
    }
  } else if (activeTool === 'dimension') {
    if (draftPoints.length === 1) {
      showPrompt('DIMENSION: Specify second point:');
    } else {
      const p1 = draftPoints[0];
      const dist = Math.hypot(pt.x - p1.x, pt.y - p1.y);
      _saveHistory();
      cadEntities.push({
        id: `ent_${Date.now()}_${Math.floor(Math.random()*1000)}`,
        type: 'DIMENSION',
        layer: 'DIMS',
        color: '#00e5ff',
        x1: Math.round(p1.x),
        y1: Math.round(p1.y),
        x2: Math.round(pt.x),
        y2: Math.round(pt.y),
        text: `${dist.toFixed(0)} mm`
      });
      cancelCurrentCommand();
    }
  } else if (activeTool === 'text') {
    const textVal = prompt('Enter text note / annotation:', 'ROOM LABEL');
    if (textVal) {
      _saveHistory();
      cadEntities.push({
        id: `ent_${Date.now()}_${Math.floor(Math.random()*1000)}`,
        type: 'TEXT',
        layer: activeLayer,
        color: _getActiveLayerColor(),
        x: Math.round(pt.x),
        y: Math.round(pt.y),
        text: textVal,
        height: 250
      });
    }
    cancelCurrentCommand();
  }
}

function _commitDrafting() {
  if (activeTool === 'polyline' && draftPoints.length >= 2) {
    _saveHistory();
    cadEntities.push({
      id: `ent_${Date.now()}_${Math.floor(Math.random()*1000)}`,
      type: 'POLYLINE',
      layer: activeLayer,
      color: _getActiveLayerColor(),
      points: draftPoints.map(p => [Math.round(p.x), Math.round(p.y)]),
      closed: false
    });
  }
  cancelCurrentCommand();
}

function cancelCurrentCommand() {
  draftPoints = [];
  const banner = $('cadPromptBanner');
  if (banner) banner.style.display = 'none';
  _drawCadCanvas();
}

/* ==========================================================================
   SELECTION ENGINE
   ========================================================================== */
function _pickEntityAt(wx, wy) {
  const tol = 8 / zoom;
  for (let i = cadEntities.length - 1; i >= 0; i--) {
    const ent = cadEntities[i];
    if (ent.type === 'LINE') {
      const dist = _pointToSegmentDist(wx, wy, ent.x1, ent.y1, ent.x2, ent.y2);
      if (dist < tol) return ent;
    } else if (ent.type === 'CIRCLE') {
      const d = Math.abs(Math.hypot(wx - ent.cx, wy - ent.cy) - ent.radius);
      if (d < tol) return ent;
    } else if (ent.type === 'POLYLINE' && ent.points) {
      for (let j = 0; j < ent.points.length - 1; j++) {
        const d = _pointToSegmentDist(wx, wy, ent.points[j][0], ent.points[j][1], ent.points[j+1][0], ent.points[j+1][1]);
        if (d < tol) return ent;
      }
    }
  }
  return null;
}

function _pointToSegmentDist(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const l2 = dx * dx + dy * dy;
  if (l2 === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / l2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function _finishSelectionBox() {
  const minX = Math.min(selectBoxStart.x, mouseWorld.x);
  const maxX = Math.max(selectBoxStart.x, mouseWorld.x);
  const minY = Math.min(selectBoxStart.y, mouseWorld.y);
  const maxY = Math.max(selectBoxStart.y, mouseWorld.y);

  cadEntities.forEach(ent => {
    let inside = false;
    if (ent.type === 'LINE') {
      inside = (ent.x1 >= minX && ent.x1 <= maxX && ent.y1 >= minY && ent.y1 <= maxY) ||
               (ent.x2 >= minX && ent.x2 <= maxX && ent.y2 >= minY && ent.y2 <= maxY);
    } else if (ent.type === 'CIRCLE') {
      inside = (ent.cx >= minX && ent.cx <= maxX && ent.cy >= minY && ent.cy <= maxY);
    } else if (ent.type === 'POLYLINE' && ent.points) {
      inside = ent.points.some(p => p[0] >= minX && p[0] <= maxX && p[1] >= minY && p[1] <= maxY);
    }
    if (inside) selectedEntityIds.add(ent.id);
  });
}

function eraseSelectedEntities() {
  if (selectedEntityIds.size === 0) return;
  _saveHistory();
  cadEntities = cadEntities.filter(e => !selectedEntityIds.has(e.id));
  const count = selectedEntityIds.size;
  selectedEntityIds.clear();
  logCmd(`ERASE: ${count} entities deleted.`);
  _drawCadCanvas();
  _renderPropertiesPanel();
}

/* ==========================================================================
   UNDO / REDO
   ========================================================================== */
function _saveHistory() {
  cadUndoStack.push(JSON.parse(JSON.stringify(cadEntities)));
  if (cadUndoStack.length > 50) cadUndoStack.shift();
  cadRedoStack = [];
}

function cadUndo() {
  if (cadUndoStack.length === 0) return;
  cadRedoStack.push(JSON.parse(JSON.stringify(cadEntities)));
  cadEntities = cadUndoStack.pop();
  selectedEntityIds.clear();
  logCmd('UNDO performed.');
  _drawCadCanvas();
  _renderPropertiesPanel();
}

function cadRedo() {
  if (cadRedoStack.length === 0) return;
  cadUndoStack.push(JSON.parse(JSON.stringify(cadEntities)));
  cadEntities = cadRedoStack.pop();
  selectedEntityIds.clear();
  logCmd('REDO performed.');
  _drawCadCanvas();
  _renderPropertiesPanel();
}

/* ==========================================================================
   ZOOM EXTENTS
   ========================================================================== */
function zoomExtents() {
  const wrap = $('cadCanvasWrap');
  const w = wrap ? wrap.clientWidth : 800;
  const h = wrap ? wrap.clientHeight : 600;

  if (cadEntities.length === 0) {
    panX = w / 2;
    panY = h / 2;
    zoom = 0.05;
    _drawCadCanvas();
    return;
  }

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const updateBBox = (x, y) => {
    if (typeof x === 'number' && isFinite(x) && typeof y === 'number' && isFinite(y)) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
  };

  cadEntities.forEach(ent => {
    if (ent.x1 != null && ent.y1 != null) { updateBBox(ent.x1, ent.y1); }
    if (ent.x2 != null && ent.y2 != null) { updateBBox(ent.x2, ent.y2); }
    if (ent.x != null && ent.y != null) { updateBBox(ent.x, ent.y); }
    if (ent.cx != null && ent.cy != null && ent.radius != null) {
      updateBBox(ent.cx - ent.radius, ent.cy - ent.radius);
      updateBBox(ent.cx + ent.radius, ent.cy + ent.radius);
    }
    if (ent.points && Array.isArray(ent.points)) {
      ent.points.forEach(p => { if (Array.isArray(p) && p.length >= 2) updateBBox(p[0], p[1]); });
    }
  });

  if (!isFinite(minX) || !isFinite(maxX) || !isFinite(minY) || !isFinite(maxY)) {
    minX = 0; maxX = 1000; minY = 0; maxY = 1000;
  }

  const dx = Math.max(maxX - minX, 10);
  const dy = Math.max(maxY - minY, 10);

  zoom = Math.min((w * 0.85) / dx, (h * 0.85) / dy);
  if (!isFinite(zoom) || isNaN(zoom) || zoom <= 0) zoom = 0.05;

  const midX = (minX + maxX) / 2;
  const midY = (minY + maxY) / 2;

  panX = w / 2 - midX * zoom;
  panY = h / 2 + midY * zoom;

  logCmd('ZOOM Extents executed.');
  _drawCadCanvas();
}

/* ==========================================================================
   LAYERS & PROPERTIES PALETTES
   ========================================================================== */
function _getActiveLayerColor() {
  const l = cadLayers.find(x => x.name === activeLayer);
  return l ? l.color : '#ffffff';
}

function _refreshCadLayersUI() {
  const listEl = $('cadLayerList');
  const selEl = $('cadActiveLayerSel');
  if (!listEl) return;

  listEl.innerHTML = cadLayers.map(l => `
    <tr class="${l.name === activeLayer ? 'active-row' : ''}">
      <td>
        <span class="cad-eye-btn ${l.visible ? 'on' : ''}" data-layer="${l.name}" title="Toggle Visibility">👁️</span>
      </td>
      <td>
        <span class="cad-layer-color-pill" style="background:${l.color}"></span>
      </td>
      <td class="cad-layer-name-cell" data-layer="${l.name}">${l.name}</td>
      <td>
        <span class="cad-lock-btn ${l.locked ? 'on' : ''}" data-layer="${l.name}" title="Lock Layer">${l.locked ? '🔒' : '🔓'}</span>
      </td>
    </tr>
  `).join('');

  if (selEl) {
    selEl.innerHTML = cadLayers.map(l => `
      <option value="${l.name}" ${l.name === activeLayer ? 'selected' : ''}>${l.name}</option>
    `).join('');
    selEl.onchange = () => { activeLayer = selEl.value; _refreshCadLayersUI(); };
  }

  // Bind visibility toggles
  listEl.querySelectorAll('.cad-eye-btn').forEach(btn => {
    btn.onclick = () => {
      const lname = btn.getAttribute('data-layer');
      const lay = cadLayers.find(l => l.name === lname);
      if (lay) { lay.visible = !lay.visible; _refreshCadLayersUI(); _drawCadCanvas(); }
    };
  });

  // Bind click layer to set active
  listEl.querySelectorAll('.cad-layer-name-cell').forEach(cell => {
    cell.onclick = () => {
      activeLayer = cell.getAttribute('data-layer');
      _refreshCadLayersUI();
    };
  });
}

function _renderPropertiesPanel() {
  const propBox = $('cadPropsContent');
  if (!propBox) return;

  if (selectedEntityIds.size === 0) {
    propBox.innerHTML = '<div style="color:var(--muted);font-size:11px;padding:8px 4px">No entity selected.<br>Click an entity to inspect or edit.</div>';
    return;
  }

  if (selectedEntityIds.size > 1) {
    propBox.innerHTML = `
      <div class="cad-prop-group">
        <div class="cad-prop-title">MULTIPLE SELECTION</div>
        <div class="cad-prop-row"><span>Selected Count:</span><b>${selectedEntityIds.size} entities</b></div>
        <button class="cad-btn" style="margin-top:8px;width:100%" onclick="eraseSelectedEntities()">Erase All Selected</button>
      </div>
    `;
    return;
  }

  const selectedId = [...selectedEntityIds][0];
  const ent = cadEntities.find(e => e.id === selectedId);
  if (!ent) return;

  let detailsHTML = '';
  if (ent.type === 'LINE') {
    const len = Math.hypot(ent.x2 - ent.x1, ent.y2 - ent.y1);
    detailsHTML = `
      <div class="cad-prop-row"><span>Length:</span><b>${len.toFixed(2)} mm</b></div>
      <div class="cad-prop-row"><span>Start (X,Y):</span><b>${ent.x1}, ${ent.y1}</b></div>
      <div class="cad-prop-row"><span>End (X,Y):</span><b>${ent.x2}, ${ent.y2}</b></div>
    `;
  } else if (ent.type === 'CIRCLE') {
    detailsHTML = `
      <div class="cad-prop-row"><span>Radius:</span><b>${ent.radius} mm</b></div>
      <div class="cad-prop-row"><span>Diameter:</span><b>${(ent.radius * 2)} mm</b></div>
      <div class="cad-prop-row"><span>Center:</span><b>(${ent.cx}, ${ent.cy})</b></div>
    `;
  } else if (ent.type === 'TEXT') {
    detailsHTML = `
      <div class="cad-prop-row"><span>Contents:</span><b>${ent.text}</b></div>
      <div class="cad-prop-row"><span>Height:</span><b>${ent.height} mm</b></div>
    `;
  }

  propBox.innerHTML = `
    <div class="cad-prop-group">
      <div class="cad-prop-title">ENTITY DATA</div>
      <div class="cad-prop-row"><span>Type:</span><b>${ent.type}</b></div>
      <div class="cad-prop-row"><span>Layer:</span>
        <select id="cadChangeLayerSel" style="background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:2px 6px">
          ${cadLayers.map(l => `<option value="${l.name}" ${l.name === ent.layer ? 'selected' : ''}>${l.name}</option>`).join('')}
        </select>
      </div>
      <div class="cad-prop-row"><span>Color:</span><span style="display:inline-block;width:14px;height:14px;background:${ent.color||'#fff'};border-radius:2px"></span></div>
      ${detailsHTML}
      <button class="cad-btn" style="margin-top:8px;width:100%" onclick="eraseSelectedEntities()">Erase Entity</button>
    </div>
  `;

  const changeLayerSel = $('cadChangeLayerSel');
  if (changeLayerSel) {
    changeLayerSel.onchange = () => {
      _saveHistory();
      ent.layer = changeLayerSel.value;
      const matchedLayer = cadLayers.find(l => l.name === ent.layer);
      ent.color = matchedLayer ? matchedLayer.color : '#ffffff';
      _drawCadCanvas();
      _renderPropertiesPanel();
    };
  }
}

/* ==========================================================================
   COMMAND LINE DISPATCHER
   ========================================================================== */
function _executeCadCommand(rawInput) {
  const parts = rawInput.trim().split(/\s+/);
  const cmd = parts[0].toUpperCase();
  logCmd(`> ${rawInput}`);

  const toolName = CAD_COMMANDS[cmd];
  if (toolName) {
    if (toolName === 'zoom') {
      const arg = (parts[1] || '').toUpperCase();
      if (arg === 'E' || arg === 'EXTENTS' || !arg) zoomExtents();
    } else if (toolName === 'erase') {
      eraseSelectedEntities();
    } else if (toolName === 'undo') {
      cadUndo();
    } else if (toolName === 'redo') {
      cadRedo();
    } else if (toolName === 'layers') {
      const p = $('cadSidePalette');
      if (p) p.style.display = p.style.display === 'none' ? 'flex' : 'none';
    } else {
      document.querySelectorAll('.cad-tool-btn').forEach(b => {
        b.classList.toggle('on', b.getAttribute('data-tool') === toolName);
      });
      setCadTool(toolName);
    }
  } else {
    // Relative coordinates syntax e.g. @5000,0
    if (rawInput.startsWith('@') && draftPoints.length > 0) {
      const coords = rawInput.substring(1).split(',');
      if (coords.length === 2) {
        const dx = parseFloat(coords[0]) || 0;
        const dy = parseFloat(coords[1]) || 0;
        const origin = draftPoints[draftPoints.length - 1];
        _handleDraftClick({ x: origin.x + dx, y: origin.y + dy });
        return;
      }
    }
    logCmd(`Unknown command: "${rawInput}". Type L, C, REC, DIM, or Z E.`);
  }
}

function logCmd(msg) {
  const hist = $('cadCmdHistory');
  if (!hist) return;
  const line = document.createElement('div');
  line.className = 'cad-log-line';
  line.textContent = msg;
  hist.appendChild(line);
  hist.scrollTop = hist.scrollHeight;
}

/* ==========================================================================
   FILE OPERATIONS & SAMPLES
   ========================================================================== */
function _getCadAuthHeaders(extraHeaders = {}) {
  const t = (typeof authToken !== 'undefined' && authToken) ? authToken : (localStorage.getItem('expo_token') || '');
  const headers = Object.assign({}, extraHeaders);
  if (t) headers['Authorization'] = `Bearer ${t}`;
  return headers;
}

async function _loadCadSample(sampleId) {
  try {
    toast('Loading architectural CAD sample...');
    const res = await fetch(`${API}/api/v1/cad/sample/${sampleId}`, {
      headers: _getCadAuthHeaders()
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.success && data.entities) {
      cadEntities = data.entities;
      if (data.layers && data.layers.length > 0) {
        cadLayers = data.layers;
        activeLayer = cadLayers[1] ? cadLayers[1].name : cadLayers[0].name;
      }
      currentDrawingTitle = data.title || 'Sample Drawing';
      _refreshCadLayersUI();
      zoomExtents();
      logCmd(`Loaded: ${currentDrawingTitle} (${cadEntities.length} entities)`);
      toast(`Loaded ${currentDrawingTitle}`);
    }
  } catch (err) {
    toast(`Failed to load sample: ${err.message}`);
  }
}

function showCadLoading(title, sub) {
  const ov = $('cadLoadingOverlay');
  const txt = $('cadLoadingText');
  const subEl = $('cadLoadingSubtext');
  if (ov) ov.style.display = 'flex';
  if (txt && title) txt.textContent = title;
  if (subEl && sub) subEl.textContent = sub;
}

function hideCadLoading() {
  const ov = $('cadLoadingOverlay');
  if (ov) ov.style.display = 'none';
}

function _showDwgFallbackModal(filename, meta) {
  const old = $('cadDwgModal');
  if (old) old.remove();

  const ov = document.createElement('div');
  ov.id = 'cadDwgModal';
  ov.className = 'cad-modal-overlay';
  const fileSizeMb = meta && meta.file_size ? (meta.file_size / (1024 * 1024)).toFixed(2) + ' MB' : 'N/A';
  ov.innerHTML = `
    <div class="cad-modal-box" style="width:560px">
      <div class="cad-modal-head">
        <div style="display:flex;align-items:center;gap:8px">
          <svg class="ico" style="color:var(--amber)" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <strong style="font-size:14px">AutoCAD DWG Drawing Detected</strong>
        </div>
        <button class="cad-modal-close" onclick="$('cadDwgModal').remove()">&times;</button>
      </div>
      <div class="cad-modal-body">
        <p style="margin-top:0">The drawing <b>${filename}</b> is an AutoCAD proprietary binary DWG file.</p>
        <div style="background:#16233b;padding:12px 14px;border-radius:8px;border:1px solid var(--border);margin:12px 0;font-size:12px;line-height:1.7">
          <div><span style="color:var(--muted)">AutoCAD Version:</span> <b>${meta.dwg_version || 'AutoCAD 2018/2021/2024 (AC1032)'}</b></div>
          <div><span style="color:var(--muted)">Drawing Sheet No:</span> <b>${meta.drawing_number || 'Detected in titleblock'}</b></div>
          <div><span style="color:var(--muted)">Binary File Size:</span> <b>${fileSizeMb}</b></div>
        </div>
        <p style="color:var(--muted);font-size:12px;line-height:1.55">
          AutoCAD DWG vector geometry is converted via the free <b>Open Design Alliance (ODA) File Converter</b>.
          If conversion takes a moment on large multi-megabyte files, you can also export directly as standard <b>DXF</b> format from AutoCAD or Revit for instant loading.
        </p>
        <div style="display:flex;gap:10px;margin-top:18px;justify-content:flex-end">
          <button class="cad-btn" onclick="$('cadDwgModal').remove()">Close</button>
          <button class="cad-btn primary" onclick="$('cadDwgModal').remove(); _loadCadSample('sample_apartment_plan');">Load Architectural Sample</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(ov);
}

async function _loadCadFromFile(file) {
  try {
    const isDwg = file.name.toLowerCase().endsWith('.dwg');
    showCadLoading(`Parsing ${file.name}...`, isDwg ? 'Converting AutoCAD DWG vector geometry via ODA engine...' : 'Extracting layers, lines, dimensions & text...');
    toast(`Parsing ${file.name}...`);
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${API}/api/v1/cad/parse`, {
      method: 'POST',
      headers: _getCadAuthHeaders(),
      body: fd
    });
    const data = await res.json();
    hideCadLoading();
    if (data.success && data.entities && data.entities.length > 0) {
      cadEntities = data.entities;
      if (data.layers && data.layers.length) cadLayers = data.layers;
      currentDrawingTitle = file.name;
      _refreshCadLayersUI();
      zoomExtents();
      logCmd(`Opened CAD file: ${file.name} (${cadEntities.length} entities, ${cadLayers.length} layers)`);
      toast(`Successfully opened ${file.name} (${cadEntities.length} entities)`);
    } else if (data.dwg_fallback) {
      _showDwgFallbackModal(file.name, data.metadata || {});
    } else if (data.success && data.entities) {
      cadEntities = [];
      _refreshCadLayersUI();
      _drawCadCanvas();
      toast(`Opened ${file.name} (0 vector entities in model space)`);
    } else {
      toast(data.error || 'Could not parse CAD file.');
    }
  } catch (err) {
    hideCadLoading();
    toast(`CAD open error: ${err.message}`);
  }
}

async function openCadProjectDrawing(filename, projectName) {
  if (filename && filename.startsWith('sample_')) {
    await _loadCadSample(filename);
    return;
  }
  projectName = projectName || (typeof currentProject !== 'undefined' ? currentProject : '');
  try {
    const isDwg = filename.toLowerCase().endsWith('.dwg');
    showCadLoading(`Loading ${filename} in CADCraft...`, isDwg ? 'Converting AutoCAD DWG vector geometry via ODA engine...' : 'Extracting layers, lines, dimensions & text...');
    toast(`Loading ${filename} in CADCraft...`);
    const fd = new FormData();
    fd.append('project', projectName);
    fd.append('filename', filename);
    const res = await fetch(`${API}/api/v1/cad/parse`, {
      method: 'POST',
      headers: _getCadAuthHeaders(),
      body: fd
    });
    const data = await res.json();
    hideCadLoading();
    if (data.success && data.entities && data.entities.length > 0) {
      cadEntities = data.entities;
      if (data.layers && data.layers.length) cadLayers = data.layers;
      currentDrawingTitle = filename;
      _refreshCadLayersUI();
      zoomExtents();
      logCmd(`Opened project drawing: ${filename} (${cadEntities.length} entities, ${cadLayers.length} layers)`);
      toast(`Successfully opened ${filename} (${cadEntities.length} entities)`);
    } else if (data.dwg_fallback) {
      _showDwgFallbackModal(filename, data.metadata || {});
    } else if (data.success && data.entities) {
      cadEntities = [];
      _refreshCadLayersUI();
      _drawCadCanvas();
      toast(`Opened ${filename} (0 vector entities in model space)`);
    } else {
      toast(data.error || 'Could not parse CAD file.');
    }
  } catch (err) {
    hideCadLoading();
    toast(`CAD load error: ${err.message}`);
  }
}
window.openCadProjectDrawing = openCadProjectDrawing;

async function _saveCadDrawingToProject() {
  if (cadEntities.length === 0) {
    toast('Drawing is empty. Draw elements before saving.');
    return;
  }
  const filename = prompt('Enter drawing filename to save in project:', currentDrawingTitle.endsWith('.dxf') ? currentDrawingTitle : `${currentDrawingTitle}.dxf`);
  if (!filename) return;

  try {
    toast('Saving CAD drawing to project...');
    const res = await fetch(`${API}/api/v1/cad/save`, {
      method: 'POST',
      headers: _getCadAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        project: typeof currentProject !== 'undefined' ? currentProject : '',
        filename: filename,
        entities: cadEntities,
        layers: cadLayers,
        folder: 'Drawings'
      })
    });
    const data = await res.json();
    if (data.success) {
      toast(`Saved to Drawings/${data.filename}`);
      logCmd(`Saved: Drawings/${data.filename} (${data.file_size} bytes). Available in project drawings.`);
      if (typeof loadDocuments === 'function') await loadDocuments(); // Refresh project documents
    } else {
      toast('Save failed: ' + (data.detail || 'Unknown error'));
    }
  } catch (err) {
    toast(`Save error: ${err.message}`);
  }
}

async function _exportCadDrawingDxf() {
  if (cadEntities.length === 0) {
    toast('Drawing is empty.');
    return;
  }
  try {
    const res = await fetch(`${API}/api/v1/cad/export-dxf`, {
      method: 'POST',
      headers: _getCadAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        filename: currentDrawingTitle.endsWith('.dxf') ? currentDrawingTitle : `${currentDrawingTitle}.dxf`,
        entities: cadEntities,
        layers: cadLayers
      })
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = currentDrawingTitle.endsWith('.dxf') ? currentDrawingTitle : `${currentDrawingTitle}.dxf`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('DXF exported successfully');
  } catch (err) {
    toast(`Export error: ${err.message}`);
  }
}

async function _renderCadForAiStudio() {
  if (cadEntities.length === 0) {
    toast('Draw walls or architectural elements first.');
    return;
  }

  try {
    toast('Rendering CAD vector linework for AI Studio...');
    const res = await fetch(`${API}/api/v1/cad/render-for-ai`, {
      method: 'POST',
      headers: _getCadAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        project: typeof currentProject !== 'undefined' ? currentProject : '',
        entities: cadEntities,
        width: 1024,
        height: 1024,
        invert_colors: true
      })
    });
    const data = await res.json();
    if (data.success && data.input_image_path) {
      toast('Linework conditioned! Opening AI Design Studio...');
      // Switch workspace to AI Studio
      if (typeof navigate === 'function') navigate('studio');
      setTimeout(() => {
        // Set sketch-to-render workflow
        const wfCards = document.querySelectorAll('.studio-wf-card');
        wfCards.forEach(c => {
          if (c.getAttribute('data-wf') === 'sketch_to_render') c.click();
        });
        // Prompt suggestion
        const promptEl = $('studioPrompt');
        if (promptEl) {
          promptEl.value = 'Photorealistic architectural visualization based on 2D CAD architectural plan, fair-faced concrete walls, floor-to-ceiling glass, warm interior 3000K illumination, natural daylighting.';
        }
        // Preview conditioning image
        const previewWrap = $('studioPreviewWrap');
        const previewImg = $('studioPreviewImg');
        if (previewWrap && previewImg && data.input_image_url) {
          previewImg.src = data.input_image_url;
          previewWrap.style.display = 'block';
        }
      }, 300);
    } else {
      toast('Render failed: ' + (data.detail || 'Error'));
    }
  } catch (err) {
    toast(`AI conditioning error: ${err.message}`);
  }
}

function _showCadCraftInfoModal() {
  const modalHTML = `
    <div class="cad-modal-overlay" id="cadModalOverlay" onclick="this.remove()">
      <div class="cad-modal-box" onclick="event.stopPropagation()">
        <div class="cad-modal-head">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:18px">📐</span>
            <b style="font-size:14px;color:var(--text)">CADCraft Engine & Open-Source AutoCAD Integration</b>
          </div>
          <button class="cad-modal-close" onclick="$('cadModalOverlay').remove()">×</button>
        </div>
        <div class="cad-modal-body">
          <p style="margin-top:0">
            <b>CADCraft</b> is an open-source, clean-room computer-aided design and drafting application built in <b>pure Rust</b>.
            It provides AutoCAD-grade command line workflows, object snaps, layers, dimensions, and native DXF compatibility.
          </p>

          <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:10px;margin:12px 0;font-size:11.5px">
            <div style="font-weight:700;color:var(--accent2);margin-bottom:6px">🚀 Run CADCraft Native Desktop App</div>
            <code style="display:block;background:rgba(0,0,0,0.4);padding:8px;border-radius:4px;font-family:monospace;color:#2ecc71;user-select:all">
              git clone https://github.com/storytold/cadcraft.git<br>
              cd cadcraft<br>
              cargo run --release -p cadcraft -- --sample
            </code>
          </div>

          <div style="font-size:11.5px;color:var(--muted);line-height:1.6">
            <b>Features in Expo Design AI:</b>
            <ul style="margin:4px 0 0 16px;padding:0">
              <li>Open, view, and edit any <code>.dxf</code> or <code>.dwg</code> drawings right in the browser.</li>
              <li>AutoCAD shortcuts: <code>L</code> (Line), <code>C</code> (Circle), <code>REC</code> (Rectangle), <code>DIM</code> (Dimensions), <code>Z E</code> (Zoom Extents).</li>
              <li>Save edited drawings directly to the project's <b>Drawings/</b> folder.</li>
              <li><b>1-Click AI Concept Generation</b>: Render CAD floor plans directly into the AI Design Studio!</li>
            </ul>
          </div>

          <div style="margin-top:16px;display:flex;justify-content:flex-end;gap:8px">
            <a href="https://github.com/storytold/cadcraft" target="_blank" class="cad-btn primary" style="text-decoration:none">
              View CADCraft on GitHub ↗
            </a>
            <button class="cad-btn ghost" onclick="$('cadModalOverlay').remove()">Close</button>
          </div>
        </div>
      </div>
    </div>
  `;
  const div = document.createElement('div');
  div.innerHTML = modalHTML;
  document.body.appendChild(div.firstElementChild);
}

// Global exports for workspace integration
window.renderCadCraftWorkspace = renderCadCraftWorkspace;
window.openCadProjectDrawing = openCadProjectDrawing;

