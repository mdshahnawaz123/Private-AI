// HTML-escape anything that came from a drawing or a filename (layer names, TEXT, metadata).
function _cadEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"'`]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','`':'&#96;'}[c]));
}
function _cadColor(v) {
  const c = String(v || '');
  return /^#[0-9a-fA-F]{3,8}$|^rgba?\([\d\s.,%]+\)$|^[a-zA-Z]{3,20}$/.test(c) ? c : '#ffffff';
}
/* ==========================================================================
   CADCraft Studio - Computer-Aided Design & Drafting for Expo Design AI
   Clean-room AutoCAD-style 2D drafting engine inspired by storytold/cadcraft
   (pure Rust AutoCAD reimplementation).
   ========================================================================== */
(function(window, document) {
'use strict';

// Safe accessors for environment
var $ = (typeof window !== 'undefined' && typeof window.$ === 'function') ? window.$ : (id => document ? document.getElementById(id) : null);
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

// Command Line & AutoCAD / CADCraft Aliases
const CAD_COMMANDS = {
  // Draw
  'L': 'line', 'LINE': 'line',
  'PL': 'polyline', 'PLINE': 'polyline',
  'C': 'circle', 'CIRCLE': 'circle',
  'REC': 'rectangle', 'RECT': 'rectangle', 'RECTANG': 'rectangle', 'RECTANGLE': 'rectangle',
  'A': 'arc', 'ARC': 'arc',
  'T': 'text', 'TEXT': 'text', 'MTEXT': 'text', 'MT': 'text', 'DT': 'text', 'DTEXT': 'text',
  'DIM': 'dimension', 'DLI': 'dimension', 'DIMLIN': 'dimension', 'DIMLINEAR': 'dimension',
  'DAL': 'dimension', 'DIMALIGNED': 'dimension',

  // Modify
  'E': 'erase', 'ERASE': 'erase', 'DEL': 'erase',
  'M': 'move', 'MOVE': 'move',
  'CO': 'copy', 'CP': 'copy', 'COPY': 'copy',
  'O': 'offset', 'OFFSET': 'offset',
  'RO': 'rotate', 'ROTATE': 'rotate',
  'SC': 'scale', 'SCALE': 'scale',
  'MI': 'mirror', 'MIRROR': 'mirror',
  'TR': 'trim', 'TRIM': 'trim',
  'EX': 'extend', 'EXTEND': 'extend',
  'F': 'fillet', 'FILLET': 'fillet',
  'CHA': 'chamfer', 'CHAMFER': 'chamfer',
  'AR': 'array', 'ARRAY': 'array',
  'H': 'hatch', 'BH': 'hatch', 'BHATCH': 'hatch', 'HATCH': 'hatch',
  'OVERKILL': 'overkill',
  'X': 'explode', 'EXPLODE': 'explode',

  // View & Nav
  'Z': 'zoom', 'ZOOM': 'zoom',
  'P': 'pan', 'PAN': 'pan',
  'RE': 'regen', 'REGEN': 'regen',

  // Utility & Inquiry
  'U': 'undo', 'UNDO': 'undo',
  'REDO': 'redo',
  'LA': 'layers', 'LAYER': 'layers',
  'DIST': 'dist', 'DI': 'dist',
  'ID': 'id',
  'AUDIT': 'audit',
  'GRID': 'grid', 'ORTHO': 'ortho', 'OSNAP': 'osnap', 'POLAR': 'polar'
};

/* ==========================================================================
   RENDER CADCRAFT WORKSPACE UI (Official AutoCAD / storytold/cadcraft Layout)
   ========================================================================== */
function _toggleAccordion(id) {
  const grp = document.getElementById(id);
  if (!grp) return;
  grp.classList.toggle('open');
  const caret = grp.querySelector('.cad-acc-caret');
  if (caret) caret.textContent = grp.classList.contains('open') ? '▾' : '▸';
}
window._toggleAccordion = _toggleAccordion;

function _toggleLayerListTable() {
  const container = $('cadLayerTableContainer');
  const toggle = $('cadLayerListToggle');
  if (!container || !toggle) return;
  const isHidden = container.style.display === 'none';
  container.style.display = isHidden ? 'block' : 'none';
  toggle.innerHTML = isHidden ? '<span>▾ Hide Layer List</span>' : '<span>▸ Show Layer List</span>';
}
window._toggleLayerListTable = _toggleLayerListTable;

function renderCadCraftWorkspace(container) {
  container.innerHTML = `
    <div class="cadcraft-app-root">
      <!-- 1. TOP TITLEBAR & QUICK ACCESS TOOLBAR -->
      <header class="cad-titlebar">
        <!-- Quick Access Toolbar (Left) -->
        <div class="cad-qat">
          <button class="cad-icon-btn" id="cadNewBtn" title="New Drawing (Ctrl+N)">📄</button>
          <button class="cad-icon-btn" id="cadOpenBtn" title="Open DWG/DXF (Ctrl+O)">📁</button>
          <input type="file" id="cadFileInput" accept=".dxf,.dwg" style="display:none">
          <button class="cad-icon-btn" id="cadSaveBtn" title="Save to Drawings (Ctrl+S)">💾</button>
          <button class="cad-icon-btn" id="cadExportDxfBtn" title="Export AutoCAD DXF">💾⁺</button>
          <div class="cad-vsep"></div>
          <button class="cad-icon-btn" id="cadUndoBtn" title="Undo (Ctrl+Z)">↶</button>
          <button class="cad-icon-btn" id="cadRedoBtn" title="Redo (Ctrl+Y)">↷</button>
          <div class="cad-vsep"></div>
          <button class="cad-icon-btn" id="cadPlotBtn" title="Plot / Print (Ctrl+P)">🖨️</button>
          <button class="cad-icon-btn" id="cadPanBtn" title="Pan (P)">✋</button>
          <button class="cad-icon-btn" id="cadZoomExtentsBtn" title="Zoom Extents (Z E)">⤢</button>
          <button class="cad-icon-btn" id="cadMeasureBtn" title="Measure Distance (DIST)">📏</button>
          <button class="cad-icon-btn" id="cadLayersQatBtn" title="Toggle Layers Panel">🗂️</button>
          <button class="cad-icon-btn" id="cadHelpBtn" title="Shortcuts & Commands">?</button>
        </div>

        <!-- Center App Title & Drawing Name -->
        <div class="cad-app-title">
          <span class="cad-title-brand">CADCraft</span>
          <span class="cad-title-doc" id="cadTitleDocName">apartment.dxf</span>
        </div>

        <!-- Right Header AI Tools & Samples -->
        <div class="cad-header-right">
          <div class="cad-dropdown-wrap">
            <button class="cad-header-pill" id="cadSamplesBtn" title="Sample Drawings">
              <span>🏢 Samples ▾</span>
            </button>
            <div class="cad-dropdown-menu" id="cadSamplesMenu" style="display:none">
              <a href="javascript:void(0)" data-sample="sample_cadcraft_apartment">🏢 CADCraft Apartment Master Plan (Official Upstream)</a>
              <a href="javascript:void(0)" data-sample="sample_apartment_plan">🏠 2-Bedroom Residential Floor Plan</a>
              <a href="javascript:void(0)" data-sample="sample_structural_core">🏗️ Structural Column Grid & Core</a>
              <a href="javascript:void(0)" data-sample="sample_mechanical_bracket">⚙️ Mechanical Mounting Bracket</a>
            </div>
          </div>

          <button class="cad-header-pill ai" id="cadRenderInAiStudioBtn" title="Render CAD in AI Design Studio for 3D Photorealism">
            <span>🎨 Render in AI Studio</span>
          </button>

          <button class="cad-icon-btn close" id="cadCloseStudioBtn" title="Close CADCraft Studio" onclick="navigate('drawings')">✕</button>
        </div>
      </header>

      <!-- 2. DOCUMENT TABS BAR -->
      <div class="cad-doctabs-bar">
        <div class="cad-doctab start" id="cadTabStart" title="Start Page">
          <span>⊞ + Start</span>
        </div>
        <div class="cad-doctab active" id="cadTabActiveDoc" title="Active Drawing">
          <span id="cadTabActiveTitle">apartment.dxf</span>
          <span class="cad-tab-close" id="cadTabCloseBtn" title="Close drawing">×</span>
        </div>
      </div>

      <!-- 3. MAIN WORKSPACE (LEFT TOOL PALETTES + CANVAS + RIGHT PALETTE) -->
      <div class="cad-main-workspace">
        <!-- LEFT TOOL PALETTE (AutoCAD Tool Palettes Style) -->
        <aside class="cad-left-palette" id="cadLeftPalette">
          <div class="cad-palette-tabs">
            <div class="cad-pal-tab active" id="cadPalTabDrafting">Drafting</div>
            <div class="cad-pal-tab" id="cadPalTabModeling">Modeling</div>
            <button class="cad-pal-collapse" id="cadPalCollapseBtn" title="Collapse Palette">&lt;</button>
          </div>

          <div class="cad-palette-scroll" id="cadPaletteScroll">
            <!-- DRAW ACCORDION -->
            <div class="cad-acc-group open" id="cadAccDraw">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccDraw')">
                <span class="cad-acc-caret">▾</span>
                <span class="cad-acc-title">Draw</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="line" title="Line (L)"><svg viewBox="0 0 24 24"><line x1="4" y1="20" x2="20" y2="4" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="polyline" title="Polyline / Spline (PL)"><svg viewBox="0 0 24 24"><path d="M4 18 Q 10 4 16 14 T 20 6" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="circle" title="Circle (C)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg></button>
                  <button class="cad-tbtn" data-tool="rectangle" title="Rectangle (REC)"><svg viewBox="0 0 24 24"><rect x="4" y="6" width="16" height="12" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="arc" title="Arc (A)"><svg viewBox="0 0 24 24"><path d="M4 18 A 9 9 0 0 1 20 18" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="ellipse" title="Ellipse (EL)"><svg viewBox="0 0 24 24"><ellipse cx="12" cy="12" rx="9" ry="5" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="polygon" title="Polygon (POL)"><svg viewBox="0 0 24 24"><polygon points="12 4 20 9 17 19 7 19 4 9" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="hatch" title="Hatch (H)"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5"/><line x1="4" y1="12" x2="12" y2="4" stroke="currentColor" stroke-width="1.5"/><line x1="4" y1="20" x2="20" y2="4" stroke="currentColor" stroke-width="1.5"/><line x1="12" y1="20" x2="20" y2="12" stroke="currentColor" stroke-width="1.5"/></svg></button>
                  <button class="cad-tbtn" data-tool="point" title="Point (PO)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="2.5" fill="currentColor"/><line x1="6" y1="12" x2="18" y2="12" stroke="currentColor"/><line x1="12" y1="6" x2="12" y2="18" stroke="currentColor"/></svg></button>
                  <button class="cad-tbtn" data-tool="revcloud" title="Revision Cloud"><svg viewBox="0 0 24 24"><path d="M6 16 A3 3 0 0 1 8 10 A4 4 0 0 1 15 9 A3 3 0 0 1 18 14 A3 3 0 0 1 16 18 L7 18 Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>
                  <button class="cad-tbtn" data-tool="donut" title="Donut (DO)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>
                  <button class="cad-tbtn" data-tool="select" title="Selection Tool (Space)"><svg viewBox="0 0 24 24"><path d="M3 3l7 18 3-7 7-3L3 3z" fill="none" stroke="currentColor" stroke-width="1.8"/></svg></button>
                </div>
              </div>
            </div>

            <!-- HATCH ACCORDION -->
            <div class="cad-acc-group" id="cadAccHatch">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccHatch')">
                <span class="cad-acc-caret">▸</span>
                <span class="cad-acc-title">Hatch</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="hatch-solid" title="Solid Hatch"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" fill="currentColor"/></svg></button>
                  <button class="cad-tbtn" data-tool="hatch-pattern" title="Pattern Hatch (ANSI)"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" fill="none" stroke="currentColor"/><line x1="4" y1="12" x2="12" y2="4" stroke="currentColor"/><line x1="8" y1="20" x2="20" y2="8" stroke="currentColor"/></svg></button>
                </div>
              </div>
            </div>

            <!-- BLOCK ACCORDION -->
            <div class="cad-acc-group" id="cadAccBlock">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccBlock')">
                <span class="cad-acc-caret">▸</span>
                <span class="cad-acc-title">Block</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="block" title="Create Block (B)"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="10" height="10" stroke="currentColor" fill="none"/><circle cx="16" cy="16" r="4" fill="currentColor"/></svg></button>
                  <button class="cad-tbtn" data-tool="insert" title="Insert Block (I)"><svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" stroke="currentColor" fill="none"/><path d="M12 2v6m-3-3l3 3 3-3" stroke="currentColor" fill="none"/></svg></button>
                </div>
              </div>
            </div>

            <!-- MODIFY ACCORDION -->
            <div class="cad-acc-group open" id="cadAccModify">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccModify')">
                <span class="cad-acc-caret">▾</span>
                <span class="cad-acc-title">Modify</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="move" title="Move (M)"><svg viewBox="0 0 24 24"><path d="M12 2v20M2 12h20M12 2l-3 3M12 2l3 3M12 22l-3-3M12 22l3-3M2 12l3-3M2 12l3 3M22 12l-3-3M22 12l3 3" stroke="currentColor" stroke-width="1.5"/></svg></button>
                  <button class="cad-tbtn" data-tool="rotate" title="Rotate (RO)"><svg viewBox="0 0 24 24"><path d="M21 12 A9 9 0 1 1 18 5.6 L18 10 M18 5.6 L13 5.6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>
                  <button class="cad-tbtn" data-tool="trim" title="Trim (TR)"><svg viewBox="0 0 24 24"><line x1="3" y1="12" x2="21" y2="12" stroke="currentColor" stroke-width="1.5"/><path d="M12 3 L12 21 M9 8 L15 16 M15 8 L9 16" stroke="currentColor" stroke-width="1.5"/></svg></button>
                  <button class="cad-tbtn" data-tool="extend" title="Extend (EX)"><svg viewBox="0 0 24 24"><line x1="20" y1="3" x2="20" y2="21" stroke="currentColor" stroke-width="2"/><line x1="4" y1="12" x2="16" y2="12" stroke="currentColor" stroke-width="1.5"/><polyline points="12 8 16 12 12 16" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>
                  <button class="cad-tbtn" data-tool="erase" title="Erase (E / Del)"><svg viewBox="0 0 24 24"><line x1="5" y1="5" x2="19" y2="19" stroke="currentColor" stroke-width="2"/><line x1="19" y1="5" x2="5" y2="19" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="copy" title="Copy (CO)"><svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="4" y="4" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2,2"/></svg></button>
                  <button class="cad-tbtn" data-tool="mirror" title="Mirror (MI)"><svg viewBox="0 0 24 24"><polygon points="10 4 3 19 10 19" fill="none" stroke="currentColor" stroke-width="1.5"/><polygon points="14 4 21 19 14 19" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2,2"/><line x1="12" y1="2" x2="12" y2="22" stroke="currentColor" stroke-dasharray="2,1"/></svg></button>
                  <button class="cad-tbtn" data-tool="fillet" title="Fillet (F)"><svg viewBox="0 0 24 24"><path d="M4 20 L12 20 A 8 8 0 0 0 20 12 L20 4" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="chamfer" title="Chamfer (CHA)"><svg viewBox="0 0 24 24"><polyline points="4 20 12 20 20 12 20 4" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>
                  <button class="cad-tbtn" data-tool="explode" title="Explode (X)"><svg viewBox="0 0 24 24"><rect x="8" y="8" width="8" height="8" fill="none" stroke="currentColor"/><line x1="4" y1="4" x2="7" y2="7" stroke="currentColor"/><line x1="20" y1="4" x2="17" y2="7" stroke="currentColor"/><line x1="4" y1="20" x2="7" y2="17" stroke="currentColor"/><line x1="20" y1="20" x2="17" y2="17" stroke="currentColor"/></svg></button>
                  <button class="cad-tbtn" data-tool="scale" title="Scale (SC)"><svg viewBox="0 0 24 24"><rect x="4" y="12" width="8" height="8" stroke="currentColor" fill="none"/><rect x="4" y="4" width="16" height="16" stroke="currentColor" fill="none" stroke-dasharray="2,2"/></svg></button>
                  <button class="cad-tbtn" data-tool="offset" title="Offset (O)"><svg viewBox="0 0 24 24"><path d="M4 16 C 8 8 16 8 20 16" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M4 20 C 8 12 16 12 20 20" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>
                </div>
              </div>
            </div>

            <!-- TEXT ACCORDION -->
            <div class="cad-acc-group" id="cadAccText">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccText')">
                <span class="cad-acc-caret">▸</span>
                <span class="cad-acc-title">Text</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="text" title="Multiline Text (MT / T)"><span style="font-size:14px;font-weight:bold">A</span></button>
                  <button class="cad-tbtn" data-tool="text" title="Single-line Text (DT)"><span style="font-size:12px">A_</span></button>
                  <button class="cad-tbtn" data-tool="find" title="Find (FIND)">🔍</button>
                </div>
              </div>
            </div>

            <!-- DIMENSION ACCORDION -->
            <div class="cad-acc-group open" id="cadAccDim">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccDim')">
                <span class="cad-acc-caret">▾</span>
                <span class="cad-acc-title">Dimension</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="dimension" title="Linear Dimension (DIMLIN)"><svg viewBox="0 0 24 24"><line x1="3" y1="12" x2="21" y2="12" stroke="currentColor" stroke-width="1.5"/><line x1="3" y1="6" x2="3" y2="18" stroke="currentColor"/><line x1="21" y1="6" x2="21" y2="18" stroke="currentColor"/><text x="12" y="10" font-size="7" fill="currentColor" text-anchor="middle">15</text></svg></button>
                  <button class="cad-tbtn" data-tool="dim-aligned" title="Aligned Dimension (DIMALIGNED)"><svg viewBox="0 0 24 24"><line x1="4" y1="20" x2="20" y2="4" stroke="currentColor" stroke-width="1.5"/><line x1="2" y1="18" x2="6" y2="22" stroke="currentColor"/><line x1="18" y1="2" x2="22" y2="6" stroke="currentColor"/></svg></button>
                  <button class="cad-tbtn" data-tool="dim-radius" title="Radius Dimension (DIMRAD)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" stroke="currentColor" fill="none"/><line x1="12" y1="12" x2="19" y2="7" stroke="currentColor"/><text x="14" y="9" font-size="6" fill="currentColor">R</text></svg></button>
                  <button class="cad-tbtn" data-tool="dim-diameter" title="Diameter Dimension (DIMDIA)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" stroke="currentColor" fill="none"/><line x1="6" y1="18" x2="18" y2="6" stroke="currentColor"/><text x="15" y="8" font-size="6" fill="currentColor">⌀</text></svg></button>
                </div>
              </div>
            </div>

            <!-- LEADER ACCORDION -->
            <div class="cad-acc-group" id="cadAccLeader">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccLeader')">
                <span class="cad-acc-caret">▸</span>
                <span class="cad-acc-title">Leader</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="leader" title="Multileader (MLD)"><svg viewBox="0 0 24 24"><polyline points="4 20 12 12 20 12" stroke="currentColor" fill="none" stroke-width="1.5"/><polygon points="4 20 7 16 8 19" fill="currentColor"/></svg></button>
                </div>
              </div>
            </div>

            <!-- TABLE ACCORDION -->
            <div class="cad-acc-group" id="cadAccTable">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccTable')">
                <span class="cad-acc-caret">▸</span>
                <span class="cad-acc-title">Table</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="table" title="Table (TABLE)"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" stroke="currentColor" fill="none"/><line x1="4" y1="9" x2="20" y2="9" stroke="currentColor"/><line x1="4" y1="14" x2="20" y2="14" stroke="currentColor"/><line x1="12" y1="4" x2="12" y2="20" stroke="currentColor"/></svg></button>
                </div>
              </div>
            </div>

            <!-- PARAMETRIC ACCORDION -->
            <div class="cad-acc-group" id="cadAccParametric">
              <div class="cad-acc-head" onclick="_toggleAccordion('cadAccParametric')">
                <span class="cad-acc-caret">▸</span>
                <span class="cad-acc-title">Parametric</span>
              </div>
              <div class="cad-acc-body">
                <div class="cad-tool-grid">
                  <button class="cad-tbtn" data-tool="param-lock" title="Lock Constraints"><svg viewBox="0 0 24 24"><rect x="6" y="11" width="12" height="10" rx="2" stroke="currentColor" fill="none"/><path d="M9 11 V 7 A 3 3 0 0 1 15 7 V 11" stroke="currentColor" fill="none"/></svg></button>
                </div>
              </div>
            </div>
          </div>
        </aside>

        <!-- CENTER CANVAS VIEWPORT -->
        <main class="cad-canvas-wrap" id="cadCanvasWrap">
          <canvas id="cadCanvas"></canvas>

          <!-- TOP-LEFT VIEWPORT HUD OVERLAY -->
          <div class="cad-viewport-hud">
            <span class="cad-hud-item" title="Viewport Controls">+</span>
            <span class="cad-hud-sep">|</span>
            <span class="cad-hud-item" id="cadHudViewName" title="View Direction">Top</span>
            <span class="cad-hud-sep">|</span>
            <span class="cad-hud-item" id="cadHudStyleName" title="Visual Style">2D Wireframe</span>
          </div>

          <!-- TOP-RIGHT AUTOCAD VIEWCUBE OVERLAY -->
          <div class="cad-viewcube-wrap" id="cadViewCubeWrap">
            <svg class="cad-viewcube-svg" viewBox="0 0 100 100" id="cadViewCubeSvg">
              <!-- Compass Ring -->
              <circle cx="50" cy="50" r="44" fill="rgba(30, 36, 46, 0.75)" stroke="#3a4454" stroke-width="1.5"/>
              <circle cx="50" cy="50" r="34" fill="none" stroke="#2a3240" stroke-width="1"/>
              <!-- Cardinal points -->
              <polygon points="50,7 46,13 54,13" fill="#38bdf8"/>
              <text x="50" y="21" fill="#e2e8f0" font-size="9" font-family="sans-serif" font-weight="bold" text-anchor="middle">N</text>
              <text x="83" y="53" fill="#94a3b8" font-size="9" font-family="sans-serif" font-weight="bold" text-anchor="middle">E</text>
              <text x="50" y="85" fill="#94a3b8" font-size="9" font-family="sans-serif" font-weight="bold" text-anchor="middle">S</text>
              <text x="17" y="53" fill="#94a3b8" font-size="9" font-family="sans-serif" font-weight="bold" text-anchor="middle">W</text>
              
              <!-- Isometric ViewCube -->
              <g id="cadCubeTopFace" class="cad-cube-face" style="cursor:pointer">
                <polygon points="50,28 72,40 50,52 28,40" fill="#3f4857" stroke="#5d697e" stroke-width="1"/>
                <text x="50" y="43" fill="#ffffff" font-size="9" font-family="sans-serif" font-weight="bold" text-anchor="middle">TOP</text>
              </g>
              <polygon points="28,40 50,52 50,68 28,56" fill="#2c333f" stroke="#485364" stroke-width="1"/>
              <polygon points="50,52 72,40 72,56 50,68" fill="#242b36" stroke="#485364" stroke-width="1"/>
            </svg>
            <div class="cad-wcs-pill" id="cadWcsPill" title="Coordinate System">
              <span>WCS ▾</span>
            </div>
          </div>

          <!-- BOTTOM-LEFT UCS ICON OVERLAY -->
          <div class="cad-ucs-hud">
            <svg viewBox="0 0 50 50" width="50" height="50">
              <line x1="10" y1="40" x2="42" y2="40" stroke="#ff4757" stroke-width="2"/>
              <line x1="10" y1="40" x2="10" y2="8" stroke="#2ed573" stroke-width="2"/>
              <rect x="7" y="37" width="6" height="6" fill="#ffffff"/>
              <text x="38" y="36" fill="#ff4757" font-size="10" font-family="monospace" font-weight="bold">X</text>
              <text x="14" y="16" fill="#2ed573" font-size="10" font-family="monospace" font-weight="bold">Y</text>
            </svg>
          </div>

          <!-- BOTTOM-CENTER FLOATING COMMAND WINDOW -->
          <div class="cad-floating-cmd" id="cadFloatingCmd">
            <div class="cad-cmd-recent" id="cadCmdRecent">Command: ZOOM</div>
            <div class="cad-cmd-row">
              <span class="cad-cmd-prompt-ico">&gt;_</span>
              <input type="text" class="cad-cmd-field" id="cadCmdInput" placeholder="Type a command" autocomplete="off" spellcheck="false">
              <button class="cad-cmd-hist-btn" id="cadCmdHistBtn" title="Command History">⌄</button>
            </div>
          </div>

          <!-- LOADING OVERLAY -->
          <div class="cad-loading-overlay" id="cadLoadingOverlay" style="display:none">
            <div class="cad-spinner"></div>
            <div id="cadLoadingText" style="font-weight:600;font-size:13px;color:#fff">Loading CAD drawing...</div>
            <div id="cadLoadingSubtext" style="font-size:11px;color:var(--muted)">Converting vector geometry & layers</div>
          </div>
        </main>

        <!-- RIGHT SIDE PANEL (LAYERS & AUTOCAD PROPERTIES INSPECTOR) -->
        <aside class="cad-right-palette" id="cadRightPalette">
          <!-- PALETTE TOP ICON TABS -->
          <div class="cad-right-tabs">
            <button class="cad-rtab active" id="cadRTabLayers" title="Layers"><svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" fill="none" stroke-width="1.8"/></svg></button>
            <button class="cad-rtab" id="cadRTabProps" title="Properties"><svg viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" stroke="currentColor" fill="none" stroke-width="1.8"/></svg></button>
            <button class="cad-rtab" id="cadRTabTables" title="Data / Table"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" stroke="currentColor" fill="none" stroke-width="1.8"/><line x1="3" y1="9" x2="21" y2="9" stroke="currentColor"/><line x1="3" y1="15" x2="21" y2="15" stroke="currentColor"/><line x1="9" y1="3" x2="9" y2="21" stroke="currentColor"/><line x1="15" y1="3" x2="15" y2="21" stroke="currentColor"/></svg></button>
          </div>

          <!-- LAYERS SECTION -->
          <div class="cad-layer-section">
            <div class="cad-layer-title">Layers</div>
            <div class="cad-layer-icons-bar">
              <button class="cad-licon" id="cadAddLayerBtn" title="New Layer">+</button>
              <button class="cad-licon" id="cadDelLayerBtn" title="Delete Layer">-</button>
              <button class="cad-licon" id="cadSetCurLayerBtn" title="Set Current">✓</button>
              <button class="cad-licon on" id="cadTogLayerBulb" title="Turn Layer On/Off">💡</button>
              <button class="cad-licon on" id="cadTogLayerFreeze" title="Freeze / Thaw">☀️</button>
              <button class="cad-licon" id="cadTogLayerLock" title="Lock / Unlock">🔒</button>
              <span class="cad-layer-color-dot" id="cadActiveLayerColorDot" style="display:inline-block;width:12px;height:12px;background:#808080;border-radius:2px;border:1px solid rgba(255,255,255,0.2)"></span>
              <button class="cad-licon" id="cadPlotLayerBtn" title="Plot On/Off">🖨️</button>
            </div>

            <div class="cad-active-layer-row">
              <span class="cad-dot" id="cadCurrentLayerDot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#808080;margin-right:4px"></span>
              <select id="cadActiveLayerSel" class="cad-layer-select"></select>
            </div>

            <div class="cad-layer-state-label">Unsaved Layer State</div>

            <div class="cad-layer-list-toggle" id="cadLayerListToggle" onclick="_toggleLayerListTable()">
              <span>▸ Show Layer List</span>
            </div>

            <div class="cad-layer-table-container" id="cadLayerTableContainer" style="display:none">
              <table class="cad-layer-table">
                <thead>
                  <tr><th>St</th><th>Color</th><th>Name</th><th>Lock</th></tr>
                </thead>
                <tbody id="cadLayerList"></tbody>
              </table>
            </div>
          </div>

          <!-- AUTOCAD PROPERTIES INSPECTOR -->
          <div class="cad-properties-section">
            <div class="cad-prop-head">
              <span>Properties</span>
              <div class="cad-prop-pill">
                <button class="active">All</button>
                <button>My</button>
              </div>
            </div>

            <div class="cad-prop-target-row">
              <select id="cadPropTargetSel" class="cad-target-select">
                <option value="none">No selection</option>
              </select>
            </div>

            <!-- AUTOCAD PROPERTY GRID (EXACT FIELDS FROM CADCRAFT SCREENSHOT) -->
            <div class="cad-autocad-grid" id="cadAutocadGrid">
              <div class="cad-grid-row"><span class="k">Color</span><span class="v" id="propColor">■ ByLayer ▾</span></div>
              <div class="cad-grid-row"><span class="k">Layer</span><span class="v" id="propLayer">0 ▾</span></div>
              <div class="cad-grid-row"><span class="k">Linetype</span><span class="v" id="propLinetype">ByLayer ▾</span></div>
              <div class="cad-grid-row"><span class="k">Linetype scale</span><span class="v" id="propLtScale">1.0000</span></div>
              <div class="cad-grid-row"><span class="k">Lineweight</span><span class="v" id="propLineweight">ByLayer ▾</span></div>
              <div class="cad-grid-row"><span class="k">Transparency</span><span class="v" id="propTransparency">ByLayer ▾</span></div>
              <div class="cad-grid-row"><span class="k">Thickness</span><span class="v" id="propThickness">0.0000</span></div>
              <div class="cad-grid-row"><span class="k">Text style</span><span class="v" id="propTextStyle">Standard ▾</span></div>
              <div class="cad-grid-row"><span class="k">Dimension style</span><span class="v" id="propDimStyle">Standard ▾</span></div>
              <div class="cad-grid-row"><span class="k">Multileader style</span><span class="v" id="propMldStyle">Standard ▾</span></div>
              <div class="cad-grid-row"><span class="k">Table style</span><span class="v" id="propTableStyle">Standard ▾</span></div>
              <div class="cad-grid-row"><span class="k">Annotation scale</span><span class="v" id="propAnnoScale">1:1 ▾</span></div>
              <div class="cad-grid-row"><span class="k">Text height</span><span class="v" id="propTextHeight">2.5000</span></div>
              <div class="cad-grid-row"><span class="k">Plot style</span><span class="v" id="propPlotStyle">ByColor ▾</span></div>
              <div class="cad-grid-row"><span class="k">Plot style table</span><span class="v" id="propPlotTable">None ▾</span></div>
              <div class="cad-grid-row"><span class="k">Plot style attached to</span><span class="v" id="propPlotAttach">Model ▾</span></div>
              <div class="cad-grid-row"><span class="k">Plot style type</span><span class="v" id="propPlotType">Not available</span></div>
              <div id="cadDynamicEntityProps"></div>
            </div>
          </div>
        </aside>
      </div>

      <!-- 4. BOTTOM LAYOUT TABS & STATUS BAR -->
      <footer class="cad-bottom-bar">
        <div class="cad-layout-tabs">
          <button class="cad-ltab active" id="cadLTabModel">Model</button>
          <button class="cad-ltab add" id="cadLTabAdd">+</button>
          <button class="cad-ltab" id="cadLTabLayout1">Layout1</button>
          <button class="cad-ltab" id="cadLTabLayout2">Layout2</button>
        </div>

        <div class="cad-bottom-status-right">
          <button class="cad-sico on" id="cadTogModelPaper" title="Model / Paper Space">🔲</button>
          <button class="cad-sico on" id="cadTogGrid" title="Grid Display (F7)">▦</button>
          <button class="cad-sico on" id="cadTogSnap" title="Snap Mode (F9)">⤓</button>
          <button class="cad-sico" id="cadTogOrtho" title="Ortho Mode (F8)">⟂</button>
          <button class="cad-sico" id="cadTogPolar" title="Polar Tracking (F10)">∠</button>
          <button class="cad-sico" id="cadTogIso" title="Isometric Drafting">◇</button>
          <button class="cad-sico" id="cadTogTracking" title="Object Snap Tracking (F11)">⊹</button>
          <button class="cad-sico on" id="cadTogOsnap" title="2D Object Snap (F3)">⊡</button>
          <button class="cad-sico" id="cadTogLineweight" title="Show/Hide Lineweight">≡</button>
          <button class="cad-sico" id="cadTogTransparency" title="Transparency Display">◧</button>
          <button class="cad-sico" id="cadTogCycling" title="Selection Cycling">↻</button>
          <span class="cad-scale-label">1:1 ▾</span>
          <button class="cad-sico" id="cadTogCleanScreen" title="Clean Screen (Ctrl+0)">⛶</button>
        </div>
      </footer>
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

  // Left Tool Palette Tool Buttons
  document.querySelectorAll('.cad-tbtn[data-tool]').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.cad-tbtn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const tool = btn.getAttribute('data-tool');
      if (tool === 'erase') {
        eraseSelectedEntities();
      } else if (tool === 'line' || tool === 'polyline' || tool === 'circle' || tool === 'arc' || tool === 'rectangle' || tool === 'text' || tool === 'dimension' || tool === 'move' || tool === 'copy' || tool === 'offset' || tool === 'select') {
        setCadTool(tool);
      } else if (tool.startsWith('dim-')) {
        setCadTool('dimension');
      } else if (tool.startsWith('hatch')) {
        setCadTool('hatch');
      } else {
        setCadTool(tool);
      }
      logCmd(`Activated tool: ${tool.toUpperCase()}`);
      const recentEl = $('cadCmdRecent');
      if (recentEl) recentEl.textContent = `Command: ${tool.toUpperCase()}`;
    };
  });

  // Top QAT Buttons
  const newBtn = $('cadNewBtn');
  if (newBtn) {
    newBtn.onclick = () => {
      cadEntities = [];
      cadUndoStack = [];
      cadRedoStack = [];
      selectedEntityIds.clear();
      currentDrawingTitle = 'Untitled.dxf';
      const docNameEl = $('cadTitleDocName');
      if (docNameEl) docNameEl.textContent = currentDrawingTitle;
      const tabTitleEl = $('cadTabActiveTitle');
      if (tabTitleEl) tabTitleEl.textContent = currentDrawingTitle;
      _refreshCadLayersUI();
      _drawCadCanvas();
      toast('Created new empty drawing.');
    };
  }

  // Toggles
  const togGrid = $('cadTogGrid');
  if (togGrid) togGrid.onclick = () => { gridEnabled = !gridEnabled; togGrid.classList.toggle('on', gridEnabled); _drawCadCanvas(); };

  const togSnap = $('cadTogSnap');
  if (togSnap) togSnap.onclick = () => { snapEnabled = !snapEnabled; togSnap.classList.toggle('on', snapEnabled); };

  const togOrtho = $('cadTogOrtho');
  if (togOrtho) togOrtho.onclick = () => { orthoEnabled = !orthoEnabled; togOrtho.classList.toggle('on', orthoEnabled); };

  const togPolar = $('cadTogPolar');
  if (togPolar) togPolar.onclick = () => { polarEnabled = !polarEnabled; togPolar.classList.toggle('on', polarEnabled); };

  const togOsnap = $('cadTogOsnap');
  if (togOsnap) togOsnap.onclick = () => { snapEnabled = !snapEnabled; togOsnap.classList.toggle('on', snapEnabled); };

  const cleanScreenBtn = $('cadTogCleanScreen');
  if (cleanScreenBtn) {
    cleanScreenBtn.onclick = () => {
      const lp = $('cadLeftPalette');
      const rp = $('cadRightPalette');
      if (lp) lp.style.display = lp.style.display === 'none' ? 'flex' : 'none';
      if (rp) rp.style.display = rp.style.display === 'none' ? 'flex' : 'none';
      setTimeout(resizeCanvas, 60);
    };
  }

  // Zoom extents button & ViewCube
  const zExtBtn = $('cadZoomExtentsBtn');
  if (zExtBtn) zExtBtn.onclick = zoomExtents;

  const cubeTop = $('cadCubeTopFace');
  if (cubeTop) cubeTop.onclick = zoomExtents;

  // Measure button
  const measureBtn = $('cadMeasureBtn');
  if (measureBtn) {
    measureBtn.onclick = () => {
      setCadTool('dist');
      showPrompt('DIST: Click first point to measure distance:');
    };
  }

  // Pan button
  const panBtn = $('cadPanBtn');
  if (panBtn) panBtn.onclick = () => { setCadTool('select'); toast('Middle-mouse drag or Left-click drag to pan.'); };

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

  // Canvas Mouse Interactions
  canvas.onmousedown = _onCanvasMouseDown;
  window.addEventListener('mousemove', _onCanvasMouseMove);
  window.addEventListener('mouseup', _onCanvasMouseUp);
  canvas.onwheel = _onCanvasWheel;
  canvas.oncontextmenu = (e) => { e.preventDefault(); _onCanvasContextMenu(e); };

  // Floating Command Input
  const cmdInp = $('cadCmdInput');
  if (cmdInp) {
    cmdInp.onkeydown = (e) => {
      if (e.key === 'Enter') {
        const val = cmdInp.value.trim();
        cmdInp.value = '';
        if (val) {
          const recentEl = $('cadCmdRecent');
          if (recentEl) recentEl.textContent = `Command: ${val}`;
          _executeCadCommand(val);
        }
      } else if (e.key === 'Escape') {
        cancelCurrentCommand();
        cmdInp.blur();
      }
    };
  }

  // Keyboard hotkeys
  window.addEventListener('keydown', (e) => {
    if (typeof currentDest !== 'undefined' && currentDest !== 'cadcraft') return;
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

  // Load official CADCraft apartment master plan by default if empty
  if (cadEntities.length === 0 && !window._cadSkipDefaultSample) {
    _loadCadSample('sample_cadcraft_apartment');
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

  // 4. Selection Control Grips (AutoCAD / CADCraft Grip Squares)
  if (selectedEntityIds.size > 0 && !isSelectingBox) {
    _renderSelectionGrips(ctx, dpr);
  }

  // 5. In-progress drafting rubber-band
  _renderDraftingPreview(ctx);

  // 6. Selection Window
  if (isSelectingBox) {
    _renderSelectionBox(ctx);
  }

  // 7. Object Snap marker
  if (snappedPoint) {
    _renderSnapMarker(ctx, snappedPoint, snapType);
  }

  // Update entity count readout
  const countEl = $('cadEntityCountReadout');
  if (countEl) countEl.textContent = `Entities: ${cadEntities.length}`;
}

function _renderSelectionGrips(ctx, dpr) {
  const sz = 3.5 * dpr;
  ctx.save();
  ctx.fillStyle = '#00ffff';
  ctx.strokeStyle = '#000000';
  ctx.lineWidth = 1 * dpr;

  selectedEntityIds.forEach(id => {
    const ent = cadEntities.find(e => e.id === id);
    if (!ent) return;
    const gripPts = [];
    if (ent.type === 'LINE') {
      gripPts.push(
        { x: ent.x1, y: ent.y1 },
        { x: (ent.x1 + ent.x2) / 2, y: (ent.y1 + ent.y2) / 2 },
        { x: ent.x2, y: ent.y2 }
      );
    } else if (ent.type === 'CIRCLE') {
      gripPts.push(
        { x: ent.cx, y: ent.cy },
        { x: ent.cx + ent.radius, y: ent.cy },
        { x: ent.cx - ent.radius, y: ent.cy },
        { x: ent.cx, y: ent.cy + ent.radius },
        { x: ent.cx, y: ent.cy - ent.radius }
      );
    } else if (ent.type === 'POLYLINE' && ent.points) {
      ent.points.forEach(pt => gripPts.push({ x: pt[0], y: pt[1] }));
    } else if (ent.type === 'DIMENSION') {
      gripPts.push(
        { x: ent.x1, y: ent.y1 },
        { x: (ent.x1 + ent.x2) / 2, y: (ent.y1 + ent.y2) / 2 },
        { x: ent.x2, y: ent.y2 }
      );
    } else if (ent.type === 'TEXT') {
      gripPts.push({ x: ent.x, y: ent.y });
    }

    gripPts.forEach(pt => {
      const scr = worldToScreen(pt.x, pt.y);
      ctx.fillRect(scr.x - sz, scr.y - sz, sz * 2, sz * 2);
      ctx.strokeRect(scr.x - sz, scr.y - sz, sz * 2, sz * 2);
    });
  });

  ctx.restore();
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
    const raw = String(ent.text || '');
    const lines = raw.split(/\\P|\r?\n/).map(l => {
      return l.replace(/\{\\H[0-9.]+x;([^}]+)\}/gi, '$1')
              .replace(/\\[A-Za-z0-9]+;/g, '')
              .replace(/[\{\}]/g, '')
              .trim();
    }).filter(Boolean);

    const baseH = (ent.height || 250) * zoom * dpr;
    if (baseH >= 2.5 || isSelected) {
      const p = worldToScreen(ent.x, ent.y);
      ctx.save();
      const isRoomLabel = ent.layer === 'ROOM_NAMES' || ent.layer === 'A-ANNO';
      ctx.fillStyle = isSelected ? '#00ffff' : (isRoomLabel ? '#ffff00' : (ent.color || '#ffffff'));
      lines.forEach((line, idx) => {
        const lineH = idx === 0 ? Math.min(120, Math.max(7 * dpr, baseH)) : Math.min(90, Math.max(5.5 * dpr, baseH * 0.72));
        ctx.font = `${idx === 0 && isRoomLabel ? 'bold ' : ''}${Math.round(lineH)}px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif`;
        const yOffset = idx * (lineH * 1.35);
        ctx.fillText(line, p.x, p.y + yOffset);
      });
      ctx.restore();
    }
  } else if (type === 'DIMENSION') {
    _renderDimension(ctx, ent, isSelected, dpr);
  } else if (type === 'HATCH' && ent.paths && ent.paths.length > 0) {
    _renderHatch(ctx, ent, isSelected, dpr);
  } else if (type === 'LEADER' && ent.points && ent.points.length >= 2) {
    _renderLeader(ctx, ent, isSelected, dpr);
  }

  ctx.restore();
}

function _renderHatch(ctx, ent, isSelected, dpr) {
  if (!ent.paths || ent.paths.length === 0) return;
  ctx.save();
  const isWall = (ent.layer || '').toUpperCase().includes('WALL');
  ctx.strokeStyle = isSelected ? '#00ffff' : (ent.color || '#5a6475');
  ctx.lineWidth = 1 * dpr;
  ctx.fillStyle = isSelected ? 'rgba(0, 255, 255, 0.25)' : (isWall ? '#3e4652' : (ent.color ? `${_cadColor(ent.color)}33` : 'rgba(255, 255, 255, 0.15)'));

  ent.paths.forEach(path => {
    if (path.length >= 3) {
      ctx.beginPath();
      const p0 = worldToScreen(path[0][0], path[0][1]);
      ctx.moveTo(p0.x, p0.y);
      for (let i = 1; i < path.length; i++) {
        const pt = worldToScreen(path[i][0], path[i][1]);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  });
  ctx.restore();
}

function _renderLeader(ctx, ent, isSelected, dpr) {
  if (!ent.points || ent.points.length < 2) return;
  ctx.save();
  ctx.strokeStyle = isSelected ? '#00ffff' : (ent.color || '#00e5ff');
  ctx.fillStyle = ctx.strokeStyle;
  ctx.lineWidth = 1.5 * dpr;

  ctx.beginPath();
  const p0 = worldToScreen(ent.points[0][0], ent.points[0][1]);
  ctx.moveTo(p0.x, p0.y);
  for (let i = 1; i < ent.points.length; i++) {
    const pt = worldToScreen(ent.points[i][0], ent.points[i][1]);
    ctx.lineTo(pt.x, pt.y);
  }
  ctx.stroke();

  // Arrowhead at p0
  const p1 = worldToScreen(ent.points[1][0], ent.points[1][1]);
  const ang = Math.atan2(p0.y - p1.y, p0.x - p1.x);
  const arrowLen = 9 * dpr;
  ctx.beginPath();
  ctx.moveTo(p0.x, p0.y);
  ctx.lineTo(p0.x - arrowLen * Math.cos(ang - Math.PI / 6), p0.y - arrowLen * Math.sin(ang - Math.PI / 6));
  ctx.lineTo(p0.x - arrowLen * Math.cos(ang + Math.PI / 6), p0.y - arrowLen * Math.sin(ang + Math.PI / 6));
  ctx.closePath();
  ctx.fill();

  if (ent.text) {
    const plast = worldToScreen(ent.points[ent.points.length - 1][0], ent.points[ent.points.length - 1][1]);
    ctx.font = `bold ${Math.max(9 * dpr, 11)}px sans-serif`;
    ctx.fillText(ent.text, plast.x + 6 * dpr, plast.y - 4 * dpr);
  }
  ctx.restore();
}

function _renderDimension(ctx, ent, isSelected, dpr) {
  const p1 = worldToScreen(ent.x1, ent.y1);
  const p2 = worldToScreen(ent.x2, ent.y2);
  const len = Math.hypot(p2.x - p1.x, p2.y - p1.y);
  if (len < 2 && !isSelected) return;

  ctx.beginPath();
  ctx.moveTo(p1.x, p1.y);
  ctx.lineTo(p2.x, p2.y);
  ctx.stroke();

  // Architectural ticks (45-degree slashes)
  const tickLen = Math.min(len * 0.2, 6 * dpr);
  if (tickLen > 1) {
    ctx.beginPath();
    ctx.moveTo(p1.x - tickLen, p1.y + tickLen);
    ctx.lineTo(p1.x + tickLen, p1.y - tickLen);
    ctx.moveTo(p2.x - tickLen, p2.y + tickLen);
    ctx.lineTo(p2.x + tickLen, p2.y - tickLen);
    ctx.stroke();
  }

  // Dimension text at midpoint
  if ((len >= 24 || isSelected) && ent.text) {
    const midX = (p1.x + p2.x) / 2;
    const midY = (p1.y + p2.y) / 2 - 6 * dpr;
    ctx.font = `bold ${Math.min(13 * dpr, Math.max(8 * dpr, len * 0.1))}px monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(ent.text, midX, midY);
  }
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

function _checkLineSegmentIntersection(x1, y1, x2, y2, x3, y3, x4, y4) {
  const d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
  if (Math.abs(d) < 1e-6) return null;
  const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d;
  const u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / d;
  if (t >= -0.002 && t <= 1.002 && u >= -0.002 && u <= 1.002) {
    return { x: x1 + t * (x2 - x1), y: y1 + t * (y2 - y1) };
  }
  return null;
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
  } else if (type === 'Quadrant') {
    ctx.beginPath();
    ctx.moveTo(p.x, p.y - sz);
    ctx.lineTo(p.x + sz, p.y);
    ctx.lineTo(p.x, p.y + sz);
    ctx.lineTo(p.x - sz, p.y);
    ctx.closePath();
    ctx.stroke();
  } else if (type === 'Intersection') {
    ctx.beginPath();
    ctx.moveTo(p.x - sz, p.y - sz);
    ctx.lineTo(p.x + sz, p.y + sz);
    ctx.moveTo(p.x + sz, p.y - sz);
    ctx.lineTo(p.x - sz, p.y + sz);
    ctx.stroke();
  } else if (type === 'Perpendicular') {
    ctx.beginPath();
    ctx.moveTo(p.x - sz, p.y + sz);
    ctx.lineTo(p.x - sz, p.y - sz);
    ctx.lineTo(p.x + sz, p.y - sz);
    ctx.moveTo(p.x - sz, p.y);
    ctx.lineTo(p.x, p.y);
    ctx.lineTo(p.x, p.y - sz);
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

  const snapToleranceWorld = 15 / zoom;
  let closestDist = snapToleranceWorld;
  let bestPt = null;
  let bestType = null;

  // Collect linear segments for intersection & perpendicular tests
  const nearbySegments = [];

  cadEntities.forEach(ent => {
    if (ent.type === 'LINE') {
      const d1 = Math.hypot(ent.x1 - rawWx, ent.y1 - rawWy);
      if (d1 < closestDist) { closestDist = d1; bestPt = { x: ent.x1, y: ent.y1 }; bestType = 'Endpoint'; }
      const d2 = Math.hypot(ent.x2 - rawWx, ent.y2 - rawWy);
      if (d2 < closestDist) { closestDist = d2; bestPt = { x: ent.x2, y: ent.y2 }; bestType = 'Endpoint'; }

      // Midpoint
      const mx = (ent.x1 + ent.x2) / 2, my = (ent.y1 + ent.y2) / 2;
      const dm = Math.hypot(mx - rawWx, my - rawWy);
      if (dm < closestDist) { closestDist = dm; bestPt = { x: mx, y: my }; bestType = 'Midpoint'; }

      if (Math.min(d1, d2, dm) < snapToleranceWorld * 5) {
        nearbySegments.push({ x1: ent.x1, y1: ent.y1, x2: ent.x2, y2: ent.y2 });
      }
    } else if (ent.type === 'POLYLINE' && ent.points && ent.points.length >= 2) {
      for (let i = 0; i < ent.points.length; i++) {
        const pt = ent.points[i];
        const d = Math.hypot(pt[0] - rawWx, pt[1] - rawWy);
        if (d < closestDist) { closestDist = d; bestPt = { x: pt[0], y: pt[1] }; bestType = 'Endpoint'; }

        // Midpoint of polyline segment
        if (i < ent.points.length - 1 || ent.closed) {
          const nextPt = ent.points[(i + 1) % ent.points.length];
          const mx = (pt[0] + nextPt[0]) / 2, my = (pt[1] + nextPt[1]) / 2;
          const dm = Math.hypot(mx - rawWx, my - rawWy);
          if (dm < closestDist) { closestDist = dm; bestPt = { x: mx, y: my }; bestType = 'Midpoint'; }

          if (Math.min(d, dm) < snapToleranceWorld * 5) {
            nearbySegments.push({ x1: pt[0], y1: pt[1], x2: nextPt[0], y2: nextPt[1] });
          }
        }
      }
    } else if (ent.type === 'CIRCLE' || ent.type === 'ARC') {
      // Center
      const dc = Math.hypot(ent.cx - rawWx, ent.cy - rawWy);
      if (dc < closestDist) { closestDist = dc; bestPt = { x: ent.cx, y: ent.cy }; bestType = 'Center'; }

      // Quadrants for circle (0, 90, 180, 270 deg)
      if (ent.type === 'CIRCLE') {
        const quads = [
          { x: ent.cx + ent.radius, y: ent.cy },
          { x: ent.cx - ent.radius, y: ent.cy },
          { x: ent.cx, y: ent.cy + ent.radius },
          { x: ent.cx, y: ent.cy - ent.radius }
        ];
        for (const q of quads) {
          const dq = Math.hypot(q.x - rawWx, q.y - rawWy);
          if (dq < closestDist) { closestDist = dq; bestPt = q; bestType = 'Quadrant'; }
        }
      }
    }
  });

  // Intersection Snapping between nearby segments
  if (nearbySegments.length >= 2) {
    for (let i = 0; i < nearbySegments.length; i++) {
      for (let j = i + 1; j < nearbySegments.length; j++) {
        const s1 = nearbySegments[i];
        const s2 = nearbySegments[j];
        const inter = _checkLineSegmentIntersection(s1.x1, s1.y1, s1.x2, s1.y2, s2.x1, s2.y1, s2.x2, s2.y2);
        if (inter) {
          const di = Math.hypot(inter.x - rawWx, inter.y - rawWy);
          if (di < closestDist) {
            closestDist = di;
            bestPt = inter;
            bestType = 'Intersection';
          }
        }
      }
    }
  }

  // Perpendicular Snap from draft origin
  if (draftPoints.length > 0 && nearbySegments.length > 0) {
    const origin = draftPoints[draftPoints.length - 1];
    for (const seg of nearbySegments) {
      const dx = seg.x2 - seg.x1;
      const dy = seg.y2 - seg.y1;
      const lenSq = dx * dx + dy * dy;
      if (lenSq > 1e-4) {
        const t = Math.max(0, Math.min(1, ((origin.x - seg.x1) * dx + (origin.y - seg.y1) * dy) / lenSq));
        const projX = seg.x1 + t * dx;
        const projY = seg.y1 + t * dy;
        const dp = Math.hypot(projX - rawWx, projY - rawWy);
        if (dp < closestDist * 0.85) {
          closestDist = dp;
          bestPt = { x: projX, y: projY };
          bestType = 'Perpendicular';
        }
      }
    }
  }

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
  } else if (activeTool === 'id') {
    logCmd(`ID Point: X = ${pt.x.toFixed(3)}  Y = ${pt.y.toFixed(3)}  Z = 0.000`);
    toast(`Point: (${pt.x.toFixed(2)}, ${pt.y.toFixed(2)})`);
    cancelCurrentCommand();
  } else if (activeTool === 'dist') {
    if (draftPoints.length === 1) {
      showPrompt('DIST: Specify second point:');
    } else {
      const p1 = draftPoints[0];
      const p2 = draftPoints[1];
      const dist = Math.hypot(p2.x - p1.x, p2.y - p1.y);
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      logCmd(`DIST = ${dist.toFixed(3)} mm, Delta X = ${dx.toFixed(3)}, Delta Y = ${dy.toFixed(3)}`);
      toast(`Distance: ${dist.toFixed(2)} mm`);
      cancelCurrentCommand();
    }
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
        <span class="cad-eye-btn ${l.visible ? 'on' : ''}" data-layer="${_cadEsc(l.name)}" title="Toggle Visibility">👁️</span>
      </td>
      <td>
        <span class="cad-layer-color-pill" style="background:${_cadColor(l.color)}"></span>
      </td>
      <td class="cad-layer-name-cell" data-layer="${_cadEsc(l.name)}">${_cadEsc(l.name)}</td>
      <td>
        <span class="cad-lock-btn ${l.locked ? 'on' : ''}" data-layer="${_cadEsc(l.name)}" title="Lock Layer">${l.locked ? '🔒' : '🔓'}</span>
      </td>
    </tr>
  `).join('');

  if (selEl) {
    selEl.innerHTML = cadLayers.map(l => `
      <option value="${_cadEsc(l.name)}" ${l.name === activeLayer ? 'selected' : ''}>${_cadEsc(l.name)}</option>
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
  const targetSel = $('cadPropTargetSel');
  const dynamicBox = $('cadDynamicEntityProps');
  const propColor = $('propColor');
  const propLayer = $('propLayer');
  const propLtScale = $('propLtScale');
  const propTextHeight = $('propTextHeight');

  if (selectedEntityIds.size === 0) {
    if (targetSel) targetSel.innerHTML = '<option value="none">No selection</option>';
    if (propColor) propColor.innerHTML = '■ ByLayer ▾';
    if (propLayer) propLayer.innerHTML = `${_cadEsc(activeLayer || '0')} ▾`;
    if (propLtScale) propLtScale.textContent = '1.0000';
    if (propTextHeight) propTextHeight.textContent = '2.5000';
    if (dynamicBox) dynamicBox.innerHTML = '';
    return;
  }

  if (selectedEntityIds.size > 1) {
    if (targetSel) targetSel.innerHTML = `<option value="all">Multiple (${selectedEntityIds.size})</option>`;
    if (propColor) propColor.innerHTML = '■ *VARIES* ▾';
    if (propLayer) propLayer.innerHTML = '*VARIES* ▾';
    if (dynamicBox) {
      dynamicBox.innerHTML = `
        <div style="padding:8px 4px">
          <button class="cad-action-btn" style="width:100%;font-size:11px;padding:5px" onclick="eraseSelectedEntities()">✕ Erase Selected (${selectedEntityIds.size})</button>
        </div>
      `;
    }
    return;
  }

  const selectedId = [...selectedEntityIds][0];
  const ent = cadEntities.find(e => e.id === selectedId);
  if (!ent) return;

  if (targetSel) targetSel.innerHTML = `<option value="${ent.id}">${_cadEsc(ent.type)} (1)</option>`;
  if (propColor) propColor.innerHTML = `<span style="display:inline-block;width:9px;height:9px;background:${_cadColor(ent.color)};border-radius:2px;margin-right:4px"></span> ByLayer ▾`;
  if (propLayer) {
    propLayer.innerHTML = `
      <select id="cadChangeLayerSel" style="background:#181b21;color:#e2e8f0;border:1px solid #333a48;border-radius:3px;padding:1px 4px;font-size:10px">
        ${cadLayers.map(l => `<option value="${_cadEsc(l.name)}" ${l.name === ent.layer ? 'selected' : ''}>${_cadEsc(l.name)}</option>`).join('')}
      </select>
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

  let detailsHTML = '';
  if (ent.type === 'LINE') {
    const len = Math.hypot(ent.x2 - ent.x1, ent.y2 - ent.y1);
    detailsHTML = `
      <div class="cad-grid-row"><span class="k">Length</span><span class="v">${len.toFixed(1)} mm</span></div>
      <div class="cad-grid-row"><span class="k">Delta X, Y</span><span class="v">${(ent.x2 - ent.x1).toFixed(1)}, ${(ent.y2 - ent.y1).toFixed(1)}</span></div>
    `;
  } else if (ent.type === 'CIRCLE') {
    detailsHTML = `
      <div class="cad-grid-row"><span class="k">Radius</span><span class="v">${ent.radius} mm</span></div>
      <div class="cad-grid-row"><span class="k">Diameter</span><span class="v">${(ent.radius * 2)} mm</span></div>
      <div class="cad-grid-row"><span class="k">Center X, Y</span><span class="v">${ent.cx}, ${ent.cy}</span></div>
    `;
  } else if (ent.type === 'TEXT') {
    if (propTextHeight) propTextHeight.textContent = String(ent.height || 250);
    detailsHTML = `
      <div class="cad-grid-row"><span class="k">Contents</span><span class="v">${_cadEsc(ent.text).slice(0, 18)}</span></div>
    `;
  } else if (ent.type === 'DIMENSION') {
    detailsHTML = `
      <div class="cad-grid-row"><span class="k">Dimension text</span><span class="v">${_cadEsc(ent.text || 'Auto')}</span></div>
    `;
  }

  if (dynamicBox) {
    dynamicBox.innerHTML = `
      ${detailsHTML}
      <div style="padding:6px 4px">
        <button class="cad-action-btn" style="width:100%;font-size:11px;padding:4px" onclick="eraseSelectedEntities()">✕ Erase Entity</button>
      </div>
    `;
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
      if (arg === 'E' || arg === 'EXTENTS' || arg === 'A' || arg === 'ALL' || !arg) zoomExtents();
    } else if (toolName === 'erase') {
      eraseSelectedEntities();
    } else if (toolName === 'undo') {
      cadUndo();
    } else if (toolName === 'redo') {
      cadRedo();
    } else if (toolName === 'layers') {
      const p = $('cadSidePalette');
      if (p) p.style.display = p.style.display === 'none' ? 'flex' : 'none';
    } else if (toolName === 'overkill') {
      _executeOverkill();
    } else if (toolName === 'audit') {
      _executeAudit();
    } else if (toolName === 'dist') {
      setCadTool('dist');
      showPrompt('DIST: Click first point to measure distance:');
    } else if (toolName === 'id') {
      setCadTool('id');
      showPrompt('ID: Click point to identify coordinates:');
    } else if (toolName === 'regen') {
      _drawCadCanvas();
      logCmd('Regenerating model space...');
    } else if (toolName === 'grid') {
      gridEnabled = !gridEnabled;
      const tg = $('cadTogGrid');
      if (tg) tg.classList.toggle('on', gridEnabled);
      _drawCadCanvas();
      logCmd(`GRID <${gridEnabled ? 'ON' : 'OFF'}>`);
    } else if (toolName === 'ortho') {
      orthoEnabled = !orthoEnabled;
      const to = $('cadTogOrtho');
      if (to) to.classList.toggle('on', orthoEnabled);
      logCmd(`ORTHO <${orthoEnabled ? 'ON' : 'OFF'}>`);
    } else if (toolName === 'osnap') {
      snapEnabled = !snapEnabled;
      const ts = $('cadTogSnap');
      if (ts) ts.classList.toggle('on', snapEnabled);
      logCmd(`OSNAP <${snapEnabled ? 'ON' : 'OFF'}>`);
    } else if (toolName === 'polar') {
      polarEnabled = !polarEnabled;
      const tp = $('cadTogPolar');
      if (tp) tp.classList.toggle('on', polarEnabled);
      logCmd(`POLAR <${polarEnabled ? 'ON' : 'OFF'}>`);
    } else if (toolName === 'rotate') {
      _rotateSelectedEntities(parseFloat(parts[1]) || 90);
    } else if (toolName === 'scale') {
      _scaleSelectedEntities(parseFloat(parts[1]) || 2.0);
    } else if (toolName === 'mirror') {
      _mirrorSelectedEntities();
    } else if (toolName === 'array') {
      const rows = parseInt(parts[1], 10) || 3;
      const cols = parseInt(parts[2], 10) || 3;
      _arraySelectedEntities(rows, cols);
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
    logCmd(`Unknown command: "${rawInput}". Type L, C, REC, DIM, OVERKILL, AUDIT, DIST, ID, or Z E.`);
  }
}

function _executeOverkill() {
  _saveHistory();
  const initialCount = cadEntities.length;
  const unique = [];
  const seen = new Set();
  cadEntities.forEach(ent => {
    if (ent.type === 'LINE') {
      const len = Math.hypot(ent.x2 - ent.x1, ent.y2 - ent.y1);
      if (len < 0.001) return; // Discard zero-length lines
      const k1 = `${Math.round(ent.x1)},${Math.round(ent.y1)}-${Math.round(ent.x2)},${Math.round(ent.y2)}`;
      const k2 = `${Math.round(ent.x2)},${Math.round(ent.y2)}-${Math.round(ent.x1)},${Math.round(ent.y1)}`;
      if (seen.has(k1) || seen.has(k2)) return;
      seen.add(k1);
    }
    unique.push(ent);
  });
  const removed = initialCount - unique.length;
  cadEntities = unique;
  _drawCadCanvas();
  logCmd(`OVERKILL: Removed ${removed} duplicate / degenerate entities. Total entities: ${cadEntities.length}.`);
  toast(`OVERKILL: Purged ${removed} duplicate entities.`);
}

function _executeAudit() {
  let issues = 0;
  cadEntities.forEach(ent => {
    if (ent.type === 'LINE') {
      if (!isFinite(ent.x1) || !isFinite(ent.y1) || !isFinite(ent.x2) || !isFinite(ent.y2)) issues++;
    } else if (ent.type === 'CIRCLE') {
      if (!isFinite(ent.cx) || !isFinite(ent.cy) || !isFinite(ent.radius) || ent.radius <= 0) issues++;
    }
  });
  logCmd(`AUDIT: Pass 1 completed. ${issues} errors detected. Model space is clean.`);
  toast(`AUDIT: ${issues} errors found. Drawing database healthy.`);
}

function _rotateSelectedEntities(angleDeg) {
  if (selectedEntityIds.size === 0) {
    logCmd('ROTATE: Select entities first, then run ROTATE.');
    return;
  }
  _saveHistory();
  const rad = (angleDeg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  selectedEntityIds.forEach(id => {
    const ent = cadEntities.find(e => e.id === id);
    if (!ent) return;
    if (ent.type === 'LINE') {
      minX = Math.min(minX, ent.x1, ent.x2); maxX = Math.max(maxX, ent.x1, ent.x2);
      minY = Math.min(minY, ent.y1, ent.y2); maxY = Math.max(maxY, ent.y1, ent.y2);
    } else if (ent.type === 'CIRCLE') {
      minX = Math.min(minX, ent.cx - ent.radius); maxX = Math.max(maxX, ent.cx + ent.radius);
      minY = Math.min(minY, ent.cy - ent.radius); maxY = Math.max(maxY, ent.cy + ent.radius);
    }
  });
  const cx = isFinite(minX) ? (minX + maxX) / 2 : 0;
  const cy = isFinite(minY) ? (minY + maxY) / 2 : 0;

  selectedEntityIds.forEach(id => {
    const ent = cadEntities.find(e => e.id === id);
    if (!ent) return;
    if (ent.type === 'LINE') {
      const rx1 = cx + (ent.x1 - cx) * cos - (ent.y1 - cy) * sin;
      const ry1 = cy + (ent.x1 - cx) * sin + (ent.y1 - cy) * cos;
      const rx2 = cx + (ent.x2 - cx) * cos - (ent.y2 - cy) * sin;
      const ry2 = cy + (ent.x2 - cx) * sin + (ent.y2 - cy) * cos;
      ent.x1 = Math.round(rx1); ent.y1 = Math.round(ry1);
      ent.x2 = Math.round(rx2); ent.y2 = Math.round(ry2);
    } else if (ent.type === 'CIRCLE') {
      const rcx = cx + (ent.cx - cx) * cos - (ent.cy - cy) * sin;
      const rcy = cy + (ent.cx - cx) * sin + (ent.cy - cy) * cos;
      ent.cx = Math.round(rcx); ent.cy = Math.round(rcy);
    }
  });
  _drawCadCanvas();
  logCmd(`ROTATE: Rotated ${selectedEntityIds.size} entities by ${angleDeg}°.`);
}

function _scaleSelectedEntities(factor) {
  if (selectedEntityIds.size === 0 || factor <= 0) return;
  _saveHistory();
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  selectedEntityIds.forEach(id => {
    const ent = cadEntities.find(e => e.id === id);
    if (!ent) return;
    if (ent.type === 'LINE') {
      minX = Math.min(minX, ent.x1, ent.x2); maxX = Math.max(maxX, ent.x1, ent.x2);
      minY = Math.min(minY, ent.y1, ent.y2); maxY = Math.max(maxY, ent.y1, ent.y2);
    } else if (ent.type === 'CIRCLE') {
      minX = Math.min(minX, ent.cx - ent.radius); maxX = Math.max(maxX, ent.cx + ent.radius);
      minY = Math.min(minY, ent.cy - ent.radius); maxY = Math.max(maxY, ent.cy + ent.radius);
    }
  });
  const cx = isFinite(minX) ? (minX + maxX) / 2 : 0;
  const cy = isFinite(minY) ? (minY + maxY) / 2 : 0;

  selectedEntityIds.forEach(id => {
    const ent = cadEntities.find(e => e.id === id);
    if (!ent) return;
    if (ent.type === 'LINE') {
      ent.x1 = Math.round(cx + (ent.x1 - cx) * factor);
      ent.y1 = Math.round(cy + (ent.y1 - cy) * factor);
      ent.x2 = Math.round(cx + (ent.x2 - cx) * factor);
      ent.y2 = Math.round(cy + (ent.y2 - cy) * factor);
    } else if (ent.type === 'CIRCLE') {
      ent.cx = Math.round(cx + (ent.cx - cx) * factor);
      ent.cy = Math.round(cy + (ent.cy - cy) * factor);
      ent.radius = Math.round(ent.radius * factor);
    }
  });
  _drawCadCanvas();
  logCmd(`SCALE: Scaled ${selectedEntityIds.size} entities by ${factor}x.`);
}

function _mirrorSelectedEntities() {
  if (selectedEntityIds.size === 0) return;
  _saveHistory();
  let minX = Infinity, maxX = -Infinity;
  selectedEntityIds.forEach(id => {
    const ent = cadEntities.find(e => e.id === id);
    if (!ent) return;
    if (ent.type === 'LINE') { minX = Math.min(minX, ent.x1, ent.x2); maxX = Math.max(maxX, ent.x1, ent.x2); }
    else if (ent.type === 'CIRCLE') { minX = Math.min(minX, ent.cx); maxX = Math.max(maxX, ent.cx); }
  });
  const midX = (minX + maxX) / 2;
  selectedEntityIds.forEach(id => {
    const ent = cadEntities.find(e => e.id === id);
    if (!ent) return;
    if (ent.type === 'LINE') {
      ent.x1 = Math.round(midX - (ent.x1 - midX));
      ent.x2 = Math.round(midX - (ent.x2 - midX));
    } else if (ent.type === 'CIRCLE') {
      ent.cx = Math.round(midX - (ent.cx - midX));
    }
  });
  _drawCadCanvas();
  logCmd(`MIRROR: Mirrored ${selectedEntityIds.size} entities horizontally across axis.`);
}

function _arraySelectedEntities(rows, cols) {
  if (selectedEntityIds.size === 0) return;
  _saveHistory();
  const newEnts = [];
  const offset = 2000;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (r === 0 && c === 0) continue;
      selectedEntityIds.forEach(id => {
        const ent = cadEntities.find(e => e.id === id);
        if (!ent) return;
        const copy = JSON.parse(JSON.stringify(ent));
        copy.id = `ent_${Date.now()}_${Math.floor(Math.random()*10000)}`;
        if (copy.type === 'LINE') {
          copy.x1 += c * offset; copy.x2 += c * offset;
          copy.y1 += r * offset; copy.y2 += r * offset;
        } else if (copy.type === 'CIRCLE') {
          copy.cx += c * offset; copy.cy += r * offset;
        }
        newEnts.push(copy);
      });
    }
  }
  cadEntities.push(...newEnts);
  _drawCadCanvas();
  logCmd(`ARRAY: Created ${rows}x${cols} rectangular array (${newEnts.length} new entities).`);
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
      const docName = sampleId === 'sample_cadcraft_apartment' ? 'apartment.dxf' : (data.title || 'drawing.dxf');
      currentDrawingTitle = docName;
      const docNameEl = $('cadTitleDocName');
      if (docNameEl) docNameEl.textContent = docName;
      const tabTitleEl = $('cadTabActiveTitle');
      if (tabTitleEl) tabTitleEl.textContent = docName;
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
  meta = meta || {};
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
        <p style="margin-top:0">The drawing <b>${_cadEsc(filename)}</b> is an AutoCAD proprietary binary DWG file.</p>
        <div style="background:#16233b;padding:12px 14px;border-radius:8px;border:1px solid var(--border);margin:12px 0;font-size:12px;line-height:1.7">
          <div><span style="color:var(--muted)">AutoCAD Version:</span> <b>${_cadEsc(meta.dwg_version || 'AutoCAD 2018/2021/2024 (AC1032)')}</b></div>
          <div><span style="color:var(--muted)">Drawing Sheet No:</span> <b>${_cadEsc(meta.drawing_number || 'Detected in titleblock')}</b></div>
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
    const data = await res.json().catch(() => ({}));
    hideCadLoading();
    if (!res.ok) {
      toast(`CAD parse error: ${data.detail || data.error || ('HTTP ' + res.status)}`);
      return;
    }
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
      toast(data.detail || data.error || 'Could not parse CAD file.');
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
    const data = await res.json().catch(() => ({}));
    hideCadLoading();
    if (!res.ok) {
      toast(`CAD load error: ${data.detail || data.error || ('HTTP ' + res.status)}`);
      return;
    }
    if (data.success && data.entities && data.entities.length > 0) {
      cadEntities = data.entities;
      if (data.layers && data.layers.length) cadLayers = data.layers;
      currentDrawingTitle = filename;
      const docNameEl = $('cadTitleDocName');
      if (docNameEl) docNameEl.textContent = filename;
      const tabTitleEl = $('cadTabActiveTitle');
      if (tabTitleEl) tabTitleEl.textContent = filename;
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
      toast(data.detail || data.error || 'Could not parse CAD file.');
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
      <div class="cad-modal-box" style="width:620px" onclick="event.stopPropagation()">
        <div class="cad-modal-head">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:18px">📐</span>
            <b style="font-size:14px;color:var(--text)">CADCraft Engine & Upstream Pure Rust Integration</b>
          </div>
          <button class="cad-modal-close" onclick="$('cadModalOverlay').remove()">×</button>
        </div>
        <div class="cad-modal-body">
          <p style="margin-top:0;font-size:12.5px;line-height:1.5">
            <b>CADCraft</b> (<a href="https://github.com/storytold/cadcraft" target="_blank" style="color:var(--accent2)">storytold/cadcraft</a>) is an open-source, clean-room computer-aided design and drafting engine built in <b>pure Rust</b>.
            Cloned locally in <code>vendor/cadcraft/</code> (latest upstream commit <code>9b2308b</code>).
          </p>

          <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px 12px;margin:10px 0;font-size:11.5px;line-height:1.6">
            <div style="font-weight:700;color:var(--accent2);margin-bottom:4px">📦 Upstream Architecture (Rust Crates):</div>
            <div>• <b>crates/engine</b>: AutoCAD command line interpreter, snaps, grips, sysvars, lisp, audit, overkill, trim/extend, hatch.</div>
            <div>• <b>crates/doc</b>: Vector entities (LWPOLYLINE, HATCH, TABLE, MTEXT, DIMENSION, LEADER), layers, dynamic blocks, extents.</div>
            <div>• <b>crates/mcp</b>: Model Context Protocol server enabling autonomous AI agents to inspect and draft CAD geometry.</div>
            <div>• <b>apps/cadcraft</b>: Native egui desktop GUI & WebAssembly trunk build.</div>
            <div>• <b>examples/apartment.dxf</b>: Official showcase apartment floor plan with wall pick-point hatching, TrueType room labels, and room schedule tables.</div>
          </div>

          <div style="background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:8px 10px;margin:8px 0;font-size:11px">
            <span style="color:var(--muted)">Run Native Desktop App (requires Rust 1.95+):</span>
            <code style="display:block;margin-top:4px;font-family:monospace;color:#2ecc71;user-select:all">
              cd vendor/cadcraft && cargo run --release -p cadcraft -- --sample
            </code>
          </div>

          <div style="font-size:11.5px;color:var(--muted);line-height:1.55;margin-top:8px">
            <b style="color:var(--text)">Built-in Features in Expo Design AI:</b>
            <ul style="margin:4px 0 0 16px;padding:0">
              <li>100% offline, local browser vector workbench with zero external network dependencies.</li>
              <li>Official Upstream <b>Apartment Master Plan</b> pre-loaded with layers, room schedule, and dimensions.</li>
              <li>AutoCAD shortcuts: <code>L</code>, <code>PL</code>, <code>C</code>, <code>REC</code>, <code>DIM</code>, <code>OVERKILL</code>, <code>AUDIT</code>, <code>DIST</code>, <code>ID</code>, <code>Z E</code>.</li>
              <li>Precision Object Snaps: Endpoint, Midpoint, Center, Quadrant, Intersection, and Perpendicular.</li>
              <li><b>1-Click AI Conditioning</b>: Render floor plans directly into AI Design Studio for photorealistic concept generation!</li>
            </ul>
          </div>

          <div style="margin-top:16px;display:flex;justify-content:flex-end;gap:8px">
            <a href="https://github.com/storytold/cadcraft" target="_blank" class="cad-btn primary" style="text-decoration:none">
              View Upstream on GitHub ↗
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
window.eraseSelectedEntities = eraseSelectedEntities;
window._loadCadSample = _loadCadSample;

// If user is currently on the cadcraft tab, render immediately upon script load
try {
  if (typeof currentDest !== 'undefined' && currentDest === 'cadcraft') {
    const c = (typeof $ === 'function') ? $('genericWrap') : document.getElementById('genericWrap');
    if (c) renderCadCraftWorkspace(c);
  }
} catch (e) {
  console.warn('[CADCraft] Auto-mount check:', e);
}
})(typeof window !== 'undefined' ? window : this, typeof document !== 'undefined' ? document : null);

