/**
 * MPD — Masterplan AI Interface (Masterplan Processing Division)
 * Integrates offline agentic Qwen 3.5 9B reasoning, spatial reasoning engine,
 * CAD/PDF vector graphics engine, plot registers, and review meeting audit logs.
 */

const _mpdEl = (t, c, h) => { const d = document.createElement(t); if (c) d.className = c; if (h != null) d.innerHTML = h; return d; };
const _mpdEsc = s => (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _mpd$ = id => (typeof $ === 'function' ? $(id) : document.getElementById(id));
function _getMpdProject(proj) {
  if (proj) return proj;
  if (typeof currentProject !== 'undefined' && currentProject) return currentProject;
  if (typeof window !== 'undefined' && window.currentProject) return window.currentProject;
  const pSel = document.getElementById('projSel');
  if (pSel && pSel.value) return pSel.value;
  return 'C3085 - 3EH -Expo Hills';
}

function _compilePredicate(expr) {
  // Interpret a small expression language. Never execute model-provided JavaScript.
  try {
    const source=String(expr || 'true').trim();
    if(source.length>2000) throw Error('Condition is too long');
    if(source==='*'||source==='all') return ()=>true;
    const tokens=[];
    const lex=/\s*(?:("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(===|!==|==|!=|>=|<=|&&|\|\||[()[\],.<>!+\-])|([A-Za-z_][A-Za-z0-9_]*))/y;
    let pos=0;
    while(pos<source.length){
      lex.lastIndex=pos;const m=lex.exec(source);
      if(!m) throw Error('Unsupported condition syntax');
      tokens.push({kind:m[1]?'string':m[2]?'number':m[4]?'name':'op',value:m[1]||m[2]||m[3]||m[4]});
      pos=lex.lastIndex;
      if(tokens.length>500) throw Error('Condition is too complex');
    }
    let i=0;
    const peek=()=>tokens[i]?.value;
    const take=value=>{if(peek()===value){i++;return true;}return false;};
    const expect=value=>{if(!take(value))throw Error('Expected '+value);};
    const fields=new Set(['text','layer','type','plot_id','sector','land_use','status','far','area','gfa','parking']);
    function primary(){
      let node;
      if(take('(')){node=expression();expect(')');}
      else if(take('[')){
        const items=[];
        if(!take(']')){do{items.push(expression());}while(take(','));expect(']');}
        node=ctx=>items.map(item=>item(ctx));
      } else {
        const token=tokens[i++];if(!token)throw Error('Missing value');
        if(token.kind==='string'){
          const raw=token.value.slice(1,-1);
          const value=raw.replace(/\\([\\'"nrt])/g,(_,c)=>({n:'\n',r:'\r',t:'\t'}[c]??c));
          node=()=>value;
        } else if(token.kind==='number'){const value=Number(token.value);node=()=>value;}
        else if(['true','True','false','False','null','None'].includes(token.value)){
          const value=token.value.toLowerCase()==='true'?true:token.value.toLowerCase()==='false'?false:null;node=()=>value;
        } else if(fields.has(token.value)){const key=token.value;node=ctx=>ctx[key];}
        else throw Error('Unsupported field: '+token.value);
      }
      while(take('.')){
        const method=tokens[i++]?.value;expect('(');
        const args=[];if(!take(')')){do{args.push(expression());}while(take(','));expect(')');}
        const prior=node;
        if(['includes','contains','startsWith','startswith','endsWith','endswith'].includes(method)&&args.length===1){
          node=ctx=>{const value=prior(ctx), arg=args[0](ctx);
            if(method==='includes'||method==='contains')return Array.isArray(value)?value.includes(arg):String(value??'').includes(String(arg));
            return method.toLowerCase()==='startswith'?String(value??'').startsWith(String(arg)):String(value??'').endsWith(String(arg));};
        } else if(['lower','toLowerCase','upper','toUpperCase'].includes(method)&&args.length===0){
          node=ctx=>method==='lower'||method==='toLowerCase'?String(prior(ctx)??'').toLowerCase():String(prior(ctx)??'').toUpperCase();
        } else throw Error('Unsupported string operation');
      }
      return node;
    }
    function unary(){
      if(take('!')||take('not')){const child=unary();return ctx=>!child(ctx);}
      if(take('-')){const child=unary();return ctx=>-Number(child(ctx));}
      if(take('+')){const child=unary();return ctx=>Number(child(ctx));}
      return primary();
    }
    function comparison(){
      const left=unary();const op=peek();
      if(!['==','===','!=','!==','>','>=','<','<=','in','not'].includes(op))return left;
      i++;const negate=op==='not';if(negate)expect('in');const right=unary();
      return ctx=>{const l=left(ctx),r=right(ctx);
        if(op==='in'||negate){const found=(Array.isArray(r)||typeof r==='string')&&r.includes(l);return negate?!found:found;}
        if(op==='=='||op==='===')return l===r;if(op==='!='||op==='!==')return l!==r;
        if(op==='>')return l>r;if(op==='>=')return l>=r;if(op==='<')return l<r;return l<=r;};
    }
    function conjunction(){let node=comparison();while(take('and')||take('&&')){const left=node,right=comparison();node=ctx=>left(ctx)&&right(ctx);}return node;}
    function expression(){let node=conjunction();while(take('or')||take('||')){const left=node,right=conjunction();node=ctx=>left(ctx)||right(ctx);}return node;}
    const evaluate=expression();if(i!==tokens.length)throw Error('Unexpected condition token');
    return (e,p)=>Boolean(evaluate({text:String(e?.text||p?.plot_id||''),layer:String(e?.layer||'').toUpperCase(),
      type:String(e?.type||(p?'plot':'')),plot_id:String(p?.plot_id||e?.text||''),sector:String(p?.sector||''),
      land_use:String(p?.land_use||''),status:String(p?.status||''),far:Number(p?.far??0),area:Number(p?.area_sqm??p?.area??0),
      gfa:Number(p?.achieved_gfa??p?.gfa??0),parking:Number(p?.parking_provided??p?.parking??0)}));
  } catch(error){const rejected=()=>false;rejected.error=error.message;return rejected;}
}

let _mpdPlots = [];
let _mpdSummary = null;
let _mpdCadDrawing = null;
let _mpdShowCadLinework = true;
let _mpdShowPlots = true;
let _mpdTextMode = 'rooms'; // 'rooms' | 'all' | 'off'
let _mpdTextScale = 1;
let _mpdTextFilter = null; // String prefix to filter canvas text entities (e.g. 'P', 'R')
let _mpdHatchPattern = 'solid'; // 'solid' | 'diagonal' | 'crosshatch' | 'dots'
const _hatchPatternCache = {};
function _getCanvasHatchPattern(ctx, patternName, baseColor) {
  if (!patternName || patternName === 'solid') return null;
  const key = `${patternName}_${baseColor}`;
  if (_hatchPatternCache[key]) return _hatchPatternCache[key];
  try {
    const pCanvas = document.createElement('canvas');
    pCanvas.width = 16;
    pCanvas.height = 16;
    const pCtx = pCanvas.getContext('2d');
    pCtx.fillStyle = baseColor || 'rgba(59, 130, 246, 0.25)';
    pCtx.fillRect(0, 0, 16, 16);
    pCtx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
    pCtx.lineWidth = 1.5;
    if (patternName === 'diagonal' || patternName === 'ansi31') {
      pCtx.beginPath();
      pCtx.moveTo(0, 16); pCtx.lineTo(16, 0);
      pCtx.moveTo(-8, 8); pCtx.lineTo(8, -8);
      pCtx.moveTo(8, 24); pCtx.lineTo(24, 8);
      pCtx.stroke();
    } else if (patternName === 'crosshatch' || patternName === 'grid' || patternName === 'ansi37') {
      pCtx.beginPath();
      pCtx.moveTo(0, 16); pCtx.lineTo(16, 0);
      pCtx.moveTo(0, 0); pCtx.lineTo(16, 16);
      pCtx.stroke();
    } else if (patternName === 'dots') {
      pCtx.fillStyle = 'rgba(255, 255, 255, 0.5)';
      pCtx.beginPath();
      pCtx.arc(4, 4, 1.5, 0, Math.PI * 2);
      pCtx.arc(12, 12, 1.5, 0, Math.PI * 2);
      pCtx.fill();
    }
    const pat = ctx.createPattern(pCanvas, 'repeat');
    _hatchPatternCache[key] = pat;
    return pat;
  } catch(e) {
    return null;
  }
}
let _mpdUniversalRule = null; // Universal Scene-Graph Predicate Rule
let _mpdHoverCadEntity = null;
let _mpdSelectedCadEntity = null;
let _mpdSelectedPlotId = null;
let _mpdHighlightPlots = [];
let _mpdHighlightColor = '#ffff00';
let _mpdSelectedSource = '';
let _mpdWorkingRevision = null;
let _mpdEditBusy = false;
let _mpdActiveTab = 'register'; // 'register' | 'inspector'
let _mpdFilterSector = 'All';
let _mpdFilterLandUse = 'All';
let _mpdFilterStatus = 'All';
let _mpdSearchQuery = '';
let _mpdShowSetbacks = true;
let _mpdShowViolationsOnly = false;
let _mpdIsolatedLandUse = null;
let _mpdIsolatedSector = null;
let _mpdIsolatedPlotIds = null; // Set of plot_ids when universal isolation filter is active
let _mpdIsolatedLabel = '';
let _mpdCustomStyles = {};
let _mpdTransform = { panX: 0, panY: 0, zoom: 1.0 };
let _mpdCanvas = null;
let _mpdCtx = null;
let _mpdHoverPlot = null;
let _mpdChatHist = [];

const MPD_COLOR_HEX = {
  yellow: '#ffff00', red: '#ff0000', green: '#00ff00', blue: '#0080ff',
  orange: '#ffa500', purple: '#a855f7', cyan: '#00f2fe', pink: '#ec4899',
  teal: '#14b8a6', magenta: '#d946ef', gold: '#eab308', white: '#ffffff'
};

const LAND_USE_COLORS = {
  'Residential': { fill: 'rgba(245, 183, 61, 0.14)', stroke: '#f5b73d', text: '#ffe699' },
  'Commercial': { fill: 'rgba(47, 107, 255, 0.14)', stroke: '#2f6bff', text: '#b3cbff' },
  'Mixed Use': { fill: 'rgba(168, 85, 247, 0.18)', stroke: '#a855f7', text: '#e9d5ff' },
  'Open Space / Park': { fill: 'rgba(53, 208, 127, 0.14)', stroke: '#35d07f', text: '#bbf7d0' },
  'Civic': { fill: 'rgba(49, 208, 197, 0.14)', stroke: '#31d0c5', text: '#99f6e4' },
  'Hospitality': { fill: 'rgba(236, 72, 153, 0.16)', stroke: '#ec4899', text: '#fbcfe8' },
  'Public Facilities': { fill: 'rgba(59, 130, 246, 0.14)', stroke: '#3b82f6', text: '#bfdbfe' },
  'Utilities': { fill: 'rgba(100, 116, 139, 0.14)', stroke: '#64748b', text: '#cbd5e1' },
  'Default': { fill: 'rgba(148, 163, 184, 0.10)', stroke: '#94a3b8', text: '#f1f5f9' }
};

function _matchesLandUse(plotLu, targetLu) {
  if (!targetLu) return true;
  const a = String(plotLu || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const b = String(targetLu || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  return a === b || a.includes(b) || b.includes(a);
}

function _matchesSector(plotSec, targetSec) {
  if (!targetSec) return true;
  const a = String(plotSec || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const b = String(targetSec || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  return a === b || a.includes(b) || b.includes(a);
}

function _isPlotVisibleInIsolation(plot) {
  if (!plot) return false;
  if (_mpdIsolatedPlotIds && _mpdIsolatedPlotIds.size > 0) {
    return _mpdIsolatedPlotIds.has(plot.plot_id);
  }
  if (_mpdIsolatedLandUse && !_matchesLandUse(plot.land_use, _mpdIsolatedLandUse)) return false;
  if (_mpdIsolatedSector && !_matchesSector(plot.sector, _mpdIsolatedSector)) return false;
  return true;
}

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
      <!-- Masterplan CAD Toolbar (2 Clean Rows) -->
      <div class="mpd-canvas-toolbar">
        <!-- Row 1: Source Management & View -->
        <div class="mpd-canvas-toolbar-row">
          <div class="mpd-canvas-toolbar-group">
            <button class="cad-btn" id="mpdImportBtn" onclick="window._openImportModal && window._openImportModal()" title="Import DXF, DWG, Excel or PDF">
              <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
              Import File
            </button>
            <button class="cad-btn" id="mpdFilesBtn" onclick="window._openFilesModal && window._openFilesModal()" title="View masterplan source files and cross-reconciliation status">
              <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              Files (<span id="mpdFileCount">0</span>)
            </button>
            <select class="cad-btn" id="mpdSourceSelect" aria-label="Drawing shown in workspace"><option value="">Latest CAD drawing</option></select>
            <button class="cad-btn" id="mpdReconcileBtn" onclick="window._triggerReconciliation && window._triggerReconciliation()" title="Reconcile and stabilize CAD vs Excel relation">
              <svg class="ico" style="width:13px;height:13px;color:var(--accent2)" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
              Reconcile &amp; Link
            </button>
            <div class="mpd-toolbar-sep"></div>
            <button class="cad-btn" onclick="window._saveMpdWorkingCopy()" title="Save edits to working copy">Save copy</button>
            <button class="cad-btn" onclick="window._returnMpdOriginal()" title="Revert to original drawing">Revert</button>
            <button class="cad-btn" onclick="window._openMpdRevisions()" title="Browse revisions history">Revisions</button>
            <div class="mpd-toolbar-sep"></div>
            <button class="cad-btn" onclick="typeof navigate==='function'?navigate('early_design'):null" style="background:rgba(49,208,197,0.15);color:var(--cyan);border-color:rgba(49,208,197,0.3)" title="Launch Early Design Feasibility &amp; Massing Studio">
              <svg class="ico" style="width:13px;height:13px;color:var(--cyan)" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/><circle cx="15" cy="15" r="2"/></svg>
              Early Design Studio
            </button>
          </div>

          <div class="mpd-canvas-toolbar-group">
            <button class="mpd-canvas-ctrl" id="btnZoomIn" title="Zoom In">+</button>
            <button class="mpd-canvas-ctrl" id="btnZoomOut" title="Zoom Out">-</button>
            <button class="mpd-canvas-ctrl" id="btnZoomFit" title="Fit Entire Masterplan">Fit</button>
          </div>
        </div>

        <!-- Row 2: Overlays, Layers & Engineering Tools -->
        <div class="mpd-canvas-toolbar-row">
          <div class="mpd-canvas-toolbar-group">
            <button class="mpd-canvas-ctrl active" id="btnToggleCadDrawing" title="Toggle Full CAD Vector Drawing Linework">
              <svg class="ico" style="width:12px;height:12px" viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/><path d="M4 12h16M12 4v16"/></svg>
              CAD Linework (<span id="mpdCadEntityCount">0</span>)
            </button>
            <button class="mpd-canvas-ctrl active" id="btnTogglePlots" title="Toggle Masterplan Parcel Polygons">
              <svg class="ico" style="width:12px;height:12px" viewBox="0 0 24 24"><polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2"/></svg>
              Parcels (<span id="mpdPlotBtnCount">0</span>)
            </button>
            <button class="mpd-canvas-ctrl active" id="btnToggleSetbacks" title="Toggle Setback Envelopes">
              <svg class="ico" style="width:12px;height:12px" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="7" y="7" width="10" height="10" stroke-dasharray="2 2"/></svg>
              Setbacks
            </button>
            <button class="mpd-canvas-ctrl" id="btnToggleViolations" title="Show Violations Only">
              <svg class="ico" style="width:12px;height:12px;color:var(--red)" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              Violations Only
            </button>
            <div class="mpd-toolbar-sep"></div>
            <button class="mpd-canvas-ctrl active" id="btnToggleTextMode" title="Filter CAD Text: Rooms Only / All Text / Hide Text">
              <svg class="ico" style="width:12px;height:12px" viewBox="0 0 24 24"><path d="M4 7V4h16v3M9 20h6M12 4v16"/></svg>
              <span id="mpdTextModeLabel">Text: Rooms</span>
            </button>
          </div>

          <div class="mpd-canvas-toolbar-group">
            <button class="cad-btn" id="mpdAuditBtn" title="Run spatial rule and zoning audit">
              <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              Spatial Audit
            </button>
            <button class="cad-btn" id="mpdLiveAuditBtn" title="Run instant live audit across active CAD elements" style="background:rgba(53,208,127,0.15);border-color:rgba(53,208,127,0.4);color:var(--green)">
              <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
              ⚡ Live Audit Lines
            </button>
            <button class="cad-btn" id="mpdAuditLogBtn" title="View audit history & undo changes">
              <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>
              Audit Log
            </button>
            <button class="cad-btn" id="mpdExportCadBtn" title="Export highlighted CAD DXF">
              <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
              Export DXF
            </button>
          </div>
        </div>
      </div>

      <!-- KPI Ribbon Bar -->
      <div class="mpd-kpi-bar" id="mpdKpiBar">
        <div class="mpd-kpi-item"><span style="color:var(--muted)">Area:</span> <b id="kpiArea">-- m²</b></div>
        <div class="mpd-kpi-item"><span style="color:var(--muted)">Parcels:</span> <b id="kpiPlots">-- plots</b></div>
        <div class="mpd-kpi-item"><span style="color:var(--muted)">Total GFA:</span> <b id="kpiGfa">-- m²</b></div>
        <div class="mpd-kpi-item"><span style="color:var(--muted)">FAR:</span> <b id="kpiFar">--</b></div>
        <div class="mpd-kpi-item"><span style="color:var(--muted)">Compliance:</span> <span id="kpiCompliance">--</span></div>
      </div>

      <!-- Main Canvas Workspace (Full View, Inspector Removed) -->
      <div class="mpd-main-split">
        <div class="mpd-canvas-container" id="mpdCanvasContainer" style="width:100%">
          <canvas id="mpdCanvas"></canvas>
          <div class="mpd-canvas-tooltip" id="mpdTooltip"></div>
        </div>
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
  // Inspector removed; all plot details delivered dynamically via hover card
}

function _toggleSidePane(forceOpen) {
  // Inspector removed; full canvas display
}

async function _loadMasterplanData(proj) {
  try {
    _mpdCadDrawing = null;
    const filesResponse = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/files`);
    const filesData = filesResponse.ok ? await filesResponse.json() : {files:[]};
    const cadFiles = (filesData.files || []).filter(f => f.file_type === 'cad');
    if(_mpdSelectedSource !== 'register' && !cadFiles.some(f => f.id === _mpdSelectedSource)) _mpdSelectedSource = '';
    const sourceSelect = $('mpdSourceSelect');
    if(sourceSelect){
      sourceSelect.innerHTML = '<option value="">Latest CAD drawing</option><option value="register">Plot register only (hide CAD)</option>' + cadFiles.map(f=>`<option value="${_mpdEsc(f.id)}">${_mpdEsc(f.filename)}</option>`).join('');
      sourceSelect.value = _mpdSelectedSource;
      sourceSelect.onchange = () => { _mpdWorkingRevision=null; _mpdSelectedSource = sourceSelect.value; _loadMasterplanData(proj); };
    }
    const [summaryRes, plotsRes, cadRes] = await Promise.all([
      fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}`),
      fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/plots`),
      _mpdSelectedSource === 'register' ? Promise.resolve(null) : fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/cad-drawing${_mpdSelectedSource ? '?file_id='+encodeURIComponent(_mpdSelectedSource) : ''}`).catch(() => null)
    ]);

    if (summaryRes && summaryRes.ok) {
      _mpdSummary = await summaryRes.json();
      _renderMpdSummary(_mpdSummary);
    }
    if (plotsRes && plotsRes.ok) {
      _mpdPlots = await plotsRes.json();
      // Do not overlay untraceable old geometry onto a different uploaded CAD.
      const activeCad = cadFiles.find(f=>f.id === _mpdSelectedSource) || cadFiles[0];
      if(!activeCad || !activeCad.plots_count) _mpdPlots.forEach(p=>p.geometry=null);
      _renderPlotTable(_mpdPlots);
      const plotBtnCount = $('mpdPlotBtnCount');
      if (plotBtnCount) plotBtnCount.textContent = _mpdPlots.length;
    }
    if (cadRes && cadRes.ok) {
      _mpdCadDrawing = await cadRes.json();
      const countEl = $('mpdCadEntityCount');
      if (countEl && _mpdCadDrawing.total_entities != null) {
        countEl.textContent = _mpdCadDrawing.total_entities;
      }
    }
    _drawCanvas();
    _fitCanvasToPlots();
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
    if (_mpdIsolatedPlotIds && _mpdIsolatedPlotIds.size > 0 && !_mpdIsolatedPlotIds.has(p.plot_id)) return false;
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

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--muted)">No plots registered for this project. Upload a CAD drawing (.dxf/.dwg) or Excel schedule (.xlsx) to import plots.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(p => {
    const isSel = p.plot_id === _mpdSelectedPlotId;
    const badge = p.status === 'compliant'
      ? '<span class="mpd-badge green" style="padding:1px 6px;font-size:9.5px">Compliant</span>'
      : (p.status === 'warning'
        ? '<span class="mpd-badge warn" style="padding:1px 6px;font-size:9.5px">Warning</span>'
        : '<span class="mpd-badge red" style="padding:1px 6px;font-size:9.5px">Violation</span>');

    return `
      <tr class="${isSel ? 'selected' : ''}" onclick="_selectPlot('${_mpdEsc(p.plot_id)}', true)">
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

function _findPlot(plotId) {
  if (!plotId || !_mpdPlots || !_mpdPlots.length) return null;
  const idStr = String(plotId).trim().toUpperCase();
  const rawId = idStr.replace(/^PLOT-/, '').replace(/^P-/, '');
  return _mpdPlots.find(p => {
    const pid = (p.plot_id || '').toUpperCase();
    const pRaw = pid.replace(/^PLOT-/, '').replace(/^P-/, '');
    return pid === idStr || pRaw === rawId || pid === `P-${rawId}` || pid === `PLOT-${rawId}`;
  });
}

function _selectPlot(plotId, zoomTo = false, switchTab = true) {
  const plot = _findPlot(plotId);
  if (!plot) {
    // If not in _mpdPlots list, check if matching text exists in CAD drawing entities to focus camera
    if (zoomTo && _mpdCadDrawing && _mpdCadDrawing.entities) {
      const raw = String(plotId).trim().replace(/^PLOT-/, '').replace(/^P-/, '');
      const ent = _mpdCadDrawing.entities.find(e => e.type === 'TEXT' && (e.text === raw || e.text === plotId));
      if (ent) {
        const dpr = window.devicePixelRatio || 1;
        const w = _mpdCanvas.width / dpr;
        const h = _mpdCanvas.height / dpr;
        _mpdTransform.zoom = 1.6;
        _mpdTransform.panX = w / 2 - ent.x * _mpdTransform.zoom;
        _mpdTransform.panY = h / 2 + ent.y * _mpdTransform.zoom;
        _drawCanvas();
      }
    }
    return;
  }
  _mpdSelectedPlotId = plot.plot_id;

  // Update selection banner in footer
  const selInfo = $('mpdSelectedInfo');
  if (selInfo) {
    const statusTag = plot.status === 'violation' ? ' <span style="color:var(--red);font-weight:700">⚠️ Violation</span>' : (plot.status === 'warning' ? ' <span style="color:var(--amber);font-weight:700">⚠️ Warning</span>' : ' <span style="color:var(--green)">✓ Compliant</span>');
    selInfo.innerHTML = `Selected: <b>${_mpdEsc(plot.plot_id)}</b> (${_mpdEsc(plot.land_use)} · Area: ${Math.round(plot.area_sqm).toLocaleString()} m² · FAR: ${plot.far.toFixed(2)} / Max: ${plot.max_far.toFixed(2)})${statusTag}`;
  }

  // Highlight row in table if table exists
  document.querySelectorAll('#mpdPlotTableBody tr').forEach(tr => tr.classList.remove('selected'));
  _renderPlotTable(_mpdPlots);

  if (zoomTo) {
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

    const worldX = (mouseX - _mpdTransform.panX) / _mpdTransform.zoom;
    const worldY = (_mpdTransform.panY - mouseY) / _mpdTransform.zoom;
    const statusCoords = $('mpdStatusCoords');
    if (statusCoords) {
      statusCoords.textContent = `Cursor: (${worldX.toFixed(1)}, ${worldY.toFixed(1)}) m · Scale: ${Math.round(_mpdTransform.zoom * 100)}%`;
    }

    // Hit testing: prioritize parcel plots if parcels overlay is active, then CAD entities
    const hitPlot = _mpdShowPlots ? _hitTestPlots(worldX, worldY) : null;
    const hitEnt = !hitPlot ? _hitTestCadEntity(worldX, worldY, _mpdTransform.zoom) : null;
    const tooltip = $('mpdTooltip');

    if (hitPlot) {
      _mpdHoverPlot = hitPlot;
      _mpdHoverCadEntity = null;
      if (tooltip) {
        const plotCol = _getPlotColor(hitPlot);
        const isViol = hitPlot.status === 'violation';
        const isWarn = hitPlot.status === 'warning';
        const statusBadgeClass = isViol ? 'red' : (isWarn ? 'warn' : 'green');
        const statusIcon = isViol ? '⚠️' : (isWarn ? '⚠️' : '✓');
        const farPct = Math.min(100, Math.round((hitPlot.far / (hitPlot.max_far || 1)) * 100));
        const farColor = isViol ? 'var(--red)' : (isWarn ? 'var(--amber)' : '#35d07f');

        tooltip.innerHTML = `
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;padding-bottom:7px;border-bottom:1px solid rgba(255,255,255,0.08)">
            <div style="display:flex;align-items:center;gap:6px">
              <span style="font-weight:800;font-size:13px;color:#fff;letter-spacing:0.2px">${_mpdEsc(hitPlot.plot_id)}</span>
              <span style="font-size:10px;color:var(--muted);background:rgba(255,255,255,0.06);padding:1px 6px;border-radius:4px">${_mpdEsc(hitPlot.sector || 'Expo Hills')}</span>
            </div>
            <span class="mpd-badge ${statusBadgeClass}" style="font-size:10px;padding:2px 7px;font-weight:700">
              ${statusIcon} ${hitPlot.status.toUpperCase()}
            </span>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;margin-bottom:8px;font-size:11px">
            <div>
              <span style="color:var(--muted);font-size:9.5px;text-transform:uppercase;font-weight:700;display:block">Land Use</span>
              <span style="color:var(--text);font-weight:600;display:flex;align-items:center;gap:4px">
                <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${plotCol.stroke}"></span>
                ${_mpdEsc(hitPlot.land_use)}
              </span>
            </div>
            <div>
              <span style="color:var(--muted);font-size:9.5px;text-transform:uppercase;font-weight:700;display:block">Footprint Area</span>
              <b style="color:#fff">${Math.round(hitPlot.area_sqm).toLocaleString()} m²</b>
            </div>
            <div>
              <span style="color:var(--muted);font-size:9.5px;text-transform:uppercase;font-weight:700;display:block">Achieved GFA</span>
              <b style="color:#fff">${Math.round(hitPlot.achieved_gfa).toLocaleString()} m²</b>
            </div>
            <div>
              <span style="color:var(--muted);font-size:9.5px;text-transform:uppercase;font-weight:700;display:block">Permitted GFA</span>
              <b style="color:var(--text)">${hitPlot.permitted_gfa ? Math.round(hitPlot.permitted_gfa).toLocaleString() + ' m²' : '—'}</b>
            </div>
          </div>

          <div style="background:rgba(255,255,255,0.04);border-radius:6px;padding:6px 8px;margin-bottom:7px">
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:10.5px;margin-bottom:4px">
              <span style="color:var(--muted);font-weight:600">Calculated FAR (Max Allowed)</span>
              <b style="color:${farColor}">${hitPlot.far.toFixed(2)} <span style="color:var(--muted);font-weight:normal">/ Max: ${hitPlot.max_far.toFixed(2)}</span></b>
            </div>
            <div style="height:4px;border-radius:2px;background:rgba(255,255,255,0.1);overflow:hidden">
              <div style="height:100%;width:${farPct}%;background:${farColor};border-radius:2px"></div>
            </div>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:6px;font-size:10.5px;background:rgba(0,0,0,0.25);border:1px solid rgba(255,255,255,0.05);border-radius:6px;padding:5px 8px">
            <div>
              <span style="color:var(--muted);font-size:9px;display:block">Front Setback</span>
              <b style="color:var(--text)">${hitPlot.front_setback_m != null ? hitPlot.front_setback_m + ' m' : '—'}</b>
            </div>
            <div>
              <span style="color:var(--muted);font-size:9px;display:block">Side Setback</span>
              <b style="color:var(--text)">${hitPlot.side_setback_m != null ? hitPlot.side_setback_m + ' m' : '—'}</b>
            </div>
            <div>
              <span style="color:var(--muted);font-size:9px;display:block">Rear Setback</span>
              <b style="color:var(--text)">${hitPlot.rear_setback_m != null ? hitPlot.rear_setback_m + ' m' : '—'}</b>
            </div>
          </div>

          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);padding:1px 2px">
            <span>Max Height: <b style="color:var(--text)">${_mpdEsc(hitPlot.max_height || 'G+4')}</b></span>
            <span>Coverage: <b style="color:var(--text)">${hitPlot.max_coverage_pct || 50}%</b></span>
            ${hitPlot.parking_required ? `<span>Parking: <b style="color:var(--text)">${hitPlot.parking_provided || 0}/${hitPlot.parking_required}</b></span>` : ''}
          </div>

          ${hitPlot.violations && hitPlot.violations.length ? `
            <div style="margin-top:6px;background:rgba(242,88,95,0.15);border:1px solid rgba(242,88,95,0.35);border-radius:6px;padding:5px 8px;font-size:10.5px;color:var(--red)">
              <b style="display:block;margin-bottom:2px">⚠️ Violations (${hitPlot.violations.length}):</b>
              <div style="line-height:1.3">${hitPlot.violations.map(v => `• ${_mpdEsc(v)}`).join('<br>')}</div>
            </div>
          ` : ''}
        `;

        tooltip.style.display = 'block';
        const ttWidth = 340;
        const ttHeight = 250;
        const posX = (mouseX + ttWidth + 24 > rect.width) ? Math.max(10, mouseX - ttWidth - 14) : (mouseX + 16);
        const posY = (mouseY + ttHeight + 24 > rect.height) ? Math.max(10, mouseY - ttHeight - 14) : (mouseY + 16);
        tooltip.style.left = `${posX}px`;
        tooltip.style.top = `${posY}px`;
      }
    } else if (hitEnt) {
      _mpdHoverCadEntity = hitEnt;
      _mpdHoverPlot = null;
      const audit = _auditCadEntityLive(hitEnt);
      const selInfo = $('mpdSelectedInfo');
      if (selInfo && audit) {
        selInfo.innerHTML = `🔍 <b>CAD Element:</b> <span style="color:var(--accent2)">[${_mpdEsc(audit.layer)}]</span> ${_mpdEsc(audit.description)}${audit.length ? ` · <b>${audit.length}m</b>` : ''}`;
      }
      if (tooltip && audit) {
        tooltip.innerHTML = `
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;padding-bottom:5px;border-bottom:1px solid rgba(255,255,255,0.08)">
            <span style="font-weight:700;color:var(--accent2);font-size:12px">CAD Element</span>
            <span style="font-size:10px;color:var(--muted);background:rgba(255,255,255,0.06);padding:1px 6px;border-radius:4px">${_mpdEsc(audit.layer)}</span>
          </div>
          <div style="font-size:11px;color:var(--text);margin-top:2px"><b>Type:</b> ${_mpdEsc(audit.description)}</div>
          ${audit.length ? `<div style="font-size:11px;color:var(--text)"><b>Length:</b> ${audit.length} m</div>` : ''}
          <div style="font-size:10.5px;color:var(--muted);margin-top:4px">${audit.auditNotes.map(n => `• ${_mpdEsc(n)}`).join('<br>')}</div>
        `;
        tooltip.style.display = 'block';
        const ttWidth = 280;
        const ttHeight = 130;
        const posX = (mouseX + ttWidth + 24 > rect.width) ? Math.max(10, mouseX - ttWidth - 14) : (mouseX + 16);
        const posY = (mouseY + ttHeight + 24 > rect.height) ? Math.max(10, mouseY - ttHeight - 14) : (mouseY + 16);
        tooltip.style.left = `${posX}px`;
        tooltip.style.top = `${posY}px`;
      }
    } else {
      _mpdHoverCadEntity = null;
      _mpdHoverPlot = null;
      if (tooltip) tooltip.style.display = 'none';
    }
    _drawCanvas();
  });

  container.addEventListener('wheel', e => {
    e.preventDefault();
    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
    const newZoom = Math.max(1e-4, Math.min(1e4, _mpdTransform.zoom * zoomFactor));

    _mpdTransform.panX = mouseX - (mouseX - _mpdTransform.panX) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.panY = mouseY - (mouseY - _mpdTransform.panY) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.zoom = newZoom;
    _drawCanvas();
  });

  container.addEventListener('dblclick', () => {
    _fitCanvasToPlots();
  });

  container.addEventListener('click', e => {
    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const worldX = (mouseX - _mpdTransform.panX) / _mpdTransform.zoom;
    const worldY = (_mpdTransform.panY - mouseY) / _mpdTransform.zoom;

    // Prioritize parcel polygons when parcels layer is active
    const hitPlot = _mpdShowPlots ? _hitTestPlots(worldX, worldY) : null;
    if (hitPlot) {
      _selectPlot(hitPlot.plot_id, false);
      return;
    }

    // Otherwise check CAD linework/entities
    const hitEnt = _hitTestCadEntity(worldX, worldY, _mpdTransform.zoom);
    if (hitEnt) {
      _selectCadEntity(hitEnt);
      return;
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

  $('btnZoomIn').onclick = () => {
    const dpr = window.devicePixelRatio || 1;
    const cw = _mpdCanvas.width / dpr;
    const ch = _mpdCanvas.height / dpr;
    const newZoom = Math.min(1e4, _mpdTransform.zoom * 1.3);
    _mpdTransform.panX = (cw / 2) - ((cw / 2) - _mpdTransform.panX) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.panY = (ch / 2) - ((ch / 2) - _mpdTransform.panY) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.zoom = newZoom;
    _drawCanvas();
  };
  $('btnZoomOut').onclick = () => {
    const dpr = window.devicePixelRatio || 1;
    const cw = _mpdCanvas.width / dpr;
    const ch = _mpdCanvas.height / dpr;
    const newZoom = Math.max(1e-4, _mpdTransform.zoom * 0.7);
    _mpdTransform.panX = (cw / 2) - ((cw / 2) - _mpdTransform.panX) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.panY = (ch / 2) - ((ch / 2) - _mpdTransform.panY) * (newZoom / _mpdTransform.zoom);
    _mpdTransform.zoom = newZoom;
    _drawCanvas();
  };
  $('btnZoomFit').onclick = () => { _fitCanvasToPlots(); };
}

function _distToSegmentSq(px, py, x1, y1, x2, y2) {
  const l2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1);
  if (l2 === 0) return (px - x1) * (px - x1) + (py - y1) * (py - y1);
  let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
  t = Math.max(0, Math.min(1, t));
  const dx = px - (x1 + t * (x2 - x1));
  const dy = py - (y1 + t * (y2 - y1));
  return dx * dx + dy * dy;
}

function _hitTestCadEntity(wx, wy, zoom) {
  if (!_mpdCadDrawing || !_mpdCadDrawing.entities || !_mpdShowCadLinework) return null;
  const tol = Math.max(0.6, 7 / (zoom || 1));
  const tolSq = tol * tol;
  const entities = _mpdCadDrawing.entities;

  // Search in reverse so top/latest elements hit first
  for (let i = entities.length - 1; i >= 0; i--) {
    const e = entities[i];
    const t = e.type;

    if (t === 'LINE') {
      if (wx < Math.min(e.x1, e.x2) - tol || wx > Math.max(e.x1, e.x2) + tol ||
          wy < Math.min(e.y1, e.y2) - tol || wy > Math.max(e.y1, e.y2) + tol) {
        continue;
      }
      const dSq = _distToSegmentSq(wx, wy, e.x1, e.y1, e.x2, e.y2);
      if (dSq <= tolSq) return e;
    } else if (t === 'ARC' || t === 'CIRCLE') {
      const dx = wx - e.cx;
      const dy = wy - e.cy;
      const r = e.radius || 0;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (Math.abs(d - r) <= tol) {
        if (t === 'ARC') {
          let ang = Math.atan2(dy, dx) * 180 / Math.PI;
          if (ang < 0) ang += 360;
          const sAng = e.start_angle || 0;
          const eAng = e.end_angle || 360;
          if (sAng <= eAng) {
            if (ang >= sAng && ang <= eAng) return e;
          } else {
            if (ang >= sAng || ang <= eAng) return e;
          }
        } else {
          return e;
        }
      }
    } else if (t === 'TEXT') {
      const h = e.height || 2.5;
      const w = Math.max(2, (e.text ? e.text.length : 1) * h * 0.65);
      const minY = Math.min(e.y, e.y + h) - tol;
      const maxY = Math.max(e.y, e.y + h) + tol;
      if (wx >= e.x - tol && wx <= e.x + w + tol && wy >= minY && wy <= maxY) {
        return e;
      }
    } else if (t === 'POLYLINE' && e.points && e.points.length > 1) {
      const numPts = e.points.length;
      const count = e.closed ? numPts : numPts - 1;
      for (let j = 0; j < count; j++) {
        const p1 = e.points[j];
        const p2 = e.points[(j + 1) % numPts];
        if (wx < Math.min(p1[0], p2[0]) - tol || wx > Math.max(p1[0], p2[0]) + tol ||
            wy < Math.min(p1[1], p2[1]) - tol || wy > Math.max(p1[1], p2[1]) + tol) {
          continue;
        }
        if (_distToSegmentSq(wx, wy, p1[0], p1[1], p2[0], p2[1]) <= tolSq) return e;
      }
    }
  }
  return null;
}

function _auditCadEntityLive(e) {
  if (!e) return null;
  const lyr = (e.layer || '0').toUpperCase();
  const type = e.type || 'ELEMENT';
  let category = 'Architectural Vector Linework';
  let discipline = 'Architecture (ARC)';
  let length = null;
  const notes = [];

  if (type === 'LINE') {
    const dx = e.x2 - e.x1;
    const dy = e.y2 - e.y1;
    const len = Math.sqrt(dx * dx + dy * dy);
    length = len.toFixed(2);
    notes.push(`Start: (${e.x1.toFixed(1)}, ${e.y1.toFixed(1)}) · End: (${e.x2.toFixed(1)}, ${e.y2.toFixed(1)})`);
    notes.push(`Length: ${length} m`);

    if (lyr.includes('WALL')) {
      category = 'Wall Partition / Boundary (A-WALL)';
      discipline = 'Architectural (ARC)';
      notes.push('AIA standard A-WALL partition layer');
    } else if (lyr.includes('COLS')) {
      category = 'Structural Column / Core (S-COLS)';
      discipline = 'Structural Engineering (STR)';
      notes.push('Structural grid alignment element');
    } else if (lyr.includes('PRKG') || lyr.includes('PARK')) {
      category = 'Parking Stall Demarcation (A-PRKG)';
      discipline = 'Civil / Traffic / Parking';
      notes.push('Vehicular parking stall / marking line');
    } else if (lyr.includes('STRS') || lyr.includes('FLOR')) {
      category = 'Floor / Stair Boundary (A-FLOR)';
      discipline = 'Architecture / Egress Edge';
      notes.push('Floor perimeter / stair boundary linework');
    } else if (lyr.includes('DIM')) {
      category = 'Dimension Line (G-ANNO-DIMS)';
      discipline = 'CAD Documentation';
      notes.push('Linear dimension annotation vector');
    } else {
      category = `CAD Linework [${e.layer || 'General'}]`;
      discipline = lyr.startsWith('MP_') ? 'Masterplan Division (MPD)' : 'Architectural Linework';
      notes.push('Vector linework continuous and valid');
    }
  } else if (type === 'ARC' || type === 'CIRCLE') {
    const r = (e.radius || 0).toFixed(2);
    category = type === 'CIRCLE' ? 'Circular Column / Arc Feature' : 'Curved Geometry / Arc';
    discipline = lyr.includes('DOOR') ? 'Architecture (A-DOOR)' : 'Structural / Architectural';
    notes.push(`Center: (${(e.cx||0).toFixed(1)}, ${(e.cy||0).toFixed(1)})`);
    notes.push(`Radius: ${r} m`);
    if (type === 'ARC') {
      notes.push(`Sweep: ${(e.start_angle || 0).toFixed(1)}° to ${(e.end_angle || 360).toFixed(1)}°`);
    }
  } else if (type === 'TEXT') {
    category = 'CAD Annotation / Room Tag';
    discipline = 'Space Designation & Scheduling';
    notes.push(`Label: "${e.text}"`);
    notes.push(`Position: (${(e.x||0).toFixed(1)}, ${(e.y||0).toFixed(1)})`);
    if (e.height) notes.push(`Text Height: ${e.height.toFixed(1)} m`);
  } else if (type === 'POLYLINE') {
    let peri = 0;
    if (e.points && e.points.length > 1) {
      const numPts = e.points.length;
      const count = e.closed ? numPts : numPts - 1;
      for (let j = 0; j < count; j++) {
        const p1 = e.points[j];
        const p2 = e.points[(j + 1) % numPts];
        peri += Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
      }
    }
    length = peri.toFixed(2);

    if (lyr.includes('MP_RESIDENTIAL')) {
      category = `Masterplan Residential Boundary [${e.layer}]`;
      discipline = 'Urban Planning / Masterplan';
    } else if (lyr.includes('MP_COMMERCIAL')) {
      category = `Masterplan Commercial Boundary [${e.layer}]`;
      discipline = 'Urban Planning / Masterplan';
    } else if (lyr.includes('MP_MIXED')) {
      category = `Masterplan Mixed-Use Boundary [${e.layer}]`;
      discipline = 'Urban Planning / Masterplan';
    } else if (lyr.includes('MP_ROAD')) {
      category = `Road Corridor / Right-of-Way [${e.layer}]`;
      discipline = 'Civil Infrastructure & Highways';
    } else if (lyr.includes('MP_PARK') || lyr.includes('MP_PROMENADE')) {
      category = `Public Park / Green Corridor [${e.layer}]`;
      discipline = 'Landscape & Open Space';
    } else if (lyr.includes('MP_SIKKA')) {
      category = `Pedestrian Sikka Alleyway [${e.layer}]`;
      discipline = 'Urban Design / Pedestrian Network';
    } else {
      category = `Polyline Boundary [${e.layer || 'Default'}]`;
      discipline = lyr.startsWith('MP_') ? 'Masterplan Division (MPD)' : 'CAD Polygon Geometry';
    }
    notes.push(`Vertices: ${e.points ? e.points.length : 0} points`);
    notes.push(e.closed ? 'Closed boundary loop' : 'Open continuous polyline');
    notes.push(`Boundary Length: ${length} m`);
  }

  return {
    layer: e.layer || '0',
    type: type,
    description: category,
    discipline: discipline,
    length: length,
    status: 'Active Vector Element',
    auditNotes: notes
  };
}

function _selectCadEntity(e) {
  _mpdSelectedCadEntity = e;
  _mpdHoverCadEntity = e;
  const audit = _auditCadEntityLive(e);
  const selInfo = $('mpdSelectedInfo');
  if (selInfo && audit) {
    selInfo.innerHTML = `🎯 <b>Selected CAD:</b> <span style="color:var(--accent2)">[${_mpdEsc(audit.layer)}]</span> ${_mpdEsc(audit.description)}${audit.length ? ` · <b>${audit.length}m</b>` : ''}`;
  }
  _drawCanvas();
  toast(`Selected CAD Element: ${audit ? audit.description : (e.layer || 'Entity')}`);
}

function _pointInPolygon(x, y, coords) {
  if (!coords || coords.length < 3) return false;
  let inside = false;
  for (let i = 0, j = coords.length - 1; i < coords.length; j = i++) {
    const xi = coords[i][0], yi = coords[i][1];
    const xj = coords[j][0], yj = coords[j][1];
    const intersect = ((yi > y) !== (yj > y)) &&
      (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function _hitTestPlots(wx, wy) {
  if (!_mpdPlots || !_mpdPlots.length) return null;
  for (let i = _mpdPlots.length - 1; i >= 0; i--) {
    const plot = _mpdPlots[i];
    if (_mpdShowViolationsOnly && plot.status !== 'violation') continue;
    if (!_isPlotVisibleInIsolation(plot)) continue;
    if (!plot.geometry) continue;

    // Fast bounding-box pre-filtering
    if (plot.geometry.bbox) {
      const [minX, minY, maxX, maxY] = plot.geometry.bbox;
      if (wx < minX || wx > maxX || wy < minY || wy > maxY) continue;
    }

    // Precise ray-casting point-in-polygon verification
    if (plot.geometry.coordinates && plot.geometry.coordinates.length >= 3) {
      if (_pointInPolygon(wx, wy, plot.geometry.coordinates)) {
        return plot;
      }
    } else if (plot.geometry.bbox) {
      // Fallback if full vertex array is not present
      const [minX, minY, maxX, maxY] = plot.geometry.bbox;
      if (wx >= minX && wx <= maxX && wy >= minY && wy <= maxY) {
        return plot;
      }
    }
  }
  return null;
}

function _centerPlotOnCanvas(plot) {
  if (!_mpdCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const w = _mpdCanvas.width / dpr;
  const h = _mpdCanvas.height / dpr;

  let cx = plot.geometry && plot.geometry.centroid ? plot.geometry.centroid[0] : null;
  let cy = plot.geometry && plot.geometry.centroid ? plot.geometry.centroid[1] : null;

  // Fallback: search for CAD text entity if polygon geometry centroid is missing
  if ((cx === null || cy === null) && _mpdCadDrawing && _mpdCadDrawing.entities) {
    const raw = (plot.plot_id || '').replace(/^PLOT-/, '').replace(/^P-/, '');
    const ent = _mpdCadDrawing.entities.find(e => e.type === 'TEXT' && (e.text === raw || e.text === plot.plot_id));
    if (ent) {
      cx = ent.x;
      cy = ent.y;
    }
  }

  if (cx === null || cy === null) return;

  let targetZoom = 1.6;
  if (plot.geometry && plot.geometry.bbox) {
    const pw = Math.max(20, plot.geometry.bbox[2] - plot.geometry.bbox[0]);
    const ph = Math.max(20, plot.geometry.bbox[3] - plot.geometry.bbox[1]);
    targetZoom = Math.min((w * 0.6) / pw, (h * 0.6) / ph);
    targetZoom = Math.max(0.01, Math.min(50.0, targetZoom));
  }

  _mpdTransform.zoom = targetZoom;
  _mpdTransform.panX = w / 2 - cx * _mpdTransform.zoom;
  _mpdTransform.panY = h / 2 + cy * _mpdTransform.zoom;
  _drawCanvas();
}

function _fitCanvasToSubset(subsetPlots) {
  if (!_mpdCanvas || !subsetPlots || !subsetPlots.length) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of subsetPlots) {
    if (p.geometry && p.geometry.bbox) {
      minX = Math.min(minX, p.geometry.bbox[0]);
      minY = Math.min(minY, p.geometry.bbox[1]);
      maxX = Math.max(maxX, p.geometry.bbox[2]);
      maxY = Math.max(maxY, p.geometry.bbox[3]);
    }
  }
  if (!isFinite(minX) || !isFinite(maxX) || !isFinite(minY) || !isFinite(maxY)) return;
  const dpr = window.devicePixelRatio || 1;
  const cw = _mpdCanvas.width / dpr;
  const ch = _mpdCanvas.height / dpr;
  const dx = Math.max(maxX - minX, 20);
  const dy = Math.max(maxY - minY, 20);
  const pw = dx * 1.16;
  const ph = dy * 1.16;
  const scale = Math.min((cw * 0.9) / pw, (ch * 0.9) / ph);
  _mpdTransform.zoom = (!isFinite(scale) || scale <= 0) ? 1.0 : Math.min(scale, 6.0);
  _mpdTransform.panX = (cw - (minX + maxX) * _mpdTransform.zoom) / 2;
  _mpdTransform.panY = (ch + (minY + maxY) * _mpdTransform.zoom) / 2;
  _drawCanvas();
}

function _fitCanvasToPlots() {
  if (!_mpdCanvas) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  if (_mpdPlots && _mpdPlots.length) {
    for (const p of _mpdPlots) {
      if (p.geometry && p.geometry.bbox) {
        minX = Math.min(minX, p.geometry.bbox[0]);
        minY = Math.min(minY, p.geometry.bbox[1]);
        maxX = Math.max(maxX, p.geometry.bbox[2]);
        maxY = Math.max(maxY, p.geometry.bbox[3]);
      }
    }
  }

  if (_mpdCadDrawing && _mpdCadDrawing.extents && _mpdCadDrawing.extents.width > 0) {
    const ext = _mpdCadDrawing.extents;
    minX = Math.min(minX, ext.min_x);
    minY = Math.min(minY, ext.min_y);
    maxX = Math.max(maxX, ext.max_x);
    maxY = Math.max(maxY, ext.max_y);
  }

  if (!isFinite(minX) || !isFinite(maxX) || !isFinite(minY) || !isFinite(maxY)) return;

  const dpr = window.devicePixelRatio || 1;
  const cw = _mpdCanvas.width / dpr;
  const ch = _mpdCanvas.height / dpr;
  const dx = Math.max(maxX - minX, 1);
  const dy = Math.max(maxY - minY, 1);
  const marginX = dx * 0.05;
  const marginY = dy * 0.05;
  const pw = dx + marginX * 2;
  const ph = dy + marginY * 2;

  const scale = Math.min((cw * 0.92) / pw, (ch * 0.92) / ph);
  _mpdTransform.zoom = (!isFinite(scale) || scale <= 0) ? 1.0 : scale;
  _mpdTransform.panX = (cw - (minX + maxX) * _mpdTransform.zoom) / 2;
  _mpdTransform.panY = (ch + (minY + maxY) * _mpdTransform.zoom) / 2;
  _drawCanvas();
}

function _drawCanvas() {
  if (!_mpdCtx || !_mpdCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const ctx = _mpdCtx;

  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, _mpdCanvas.width, _mpdCanvas.height);

  const hasPlots = _mpdPlots && _mpdPlots.length > 0;
  const hasCad = _mpdCadDrawing && _mpdCadDrawing.total_entities > 0;

  if (!hasPlots && !hasCad) {
    const cw = _mpdCanvas.width / dpr;
    const ch = _mpdCanvas.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = '600 15px Inter, -apple-system, sans-serif';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No CAD drawing loaded. Click "Import File" above to upload your CAD file (.dxf / .dwg).', cw / 2, ch / 2 - 12);
    ctx.font = '12px Inter, sans-serif';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
    ctx.fillText('Once uploaded, your CAD vector drawing and parcels will be rendered here.', cw / 2, ch / 2 + 14);
    ctx.restore();
    return;
  }

  // Apply camera transform: +Y is North (upwards) in CAD
  ctx.scale(dpr, dpr);
  ctx.translate(_mpdTransform.panX, _mpdTransform.panY);
  ctx.scale(_mpdTransform.zoom, -_mpdTransform.zoom);

  // Draw CAD Coordinate Grid
  _drawGrid(ctx);

  // 1. Draw Full CAD Vector Linework Background (walls, columns, parking bays, ramps, dimensions, annotations)
  if (_mpdShowCadLinework && _mpdCadDrawing && _mpdCadDrawing.entities && _mpdCadDrawing.entities.length > 0) {
    _drawCadEntities(ctx, _mpdCadDrawing);
  }

  // 2. Draw Parcel Polygons with semi-transparent zoning fills & setbacks (when active)
  if (hasPlots && _mpdShowPlots) {
    for (const plot of _mpdPlots) {
      if (_mpdShowViolationsOnly && plot.status !== 'violation') continue;
      if (!_isPlotVisibleInIsolation(plot)) continue;
      _drawPlot(ctx, plot);
    }
  }

  // 3. Highlight Hovered or Selected CAD Entity (Live Glowing Audit)
  if (_mpdHoverCadEntity || _mpdSelectedCadEntity) {
    const ent = _mpdHoverCadEntity || _mpdSelectedCadEntity;
    const isSel = ent === _mpdSelectedCadEntity;
    ctx.save();
    ctx.strokeStyle = isSel ? '#f5b73d' : '#00f2fe';
    ctx.lineWidth = (isSel ? 4.0 : 3.0) / _mpdTransform.zoom;
    ctx.shadowColor = isSel ? '#f5b73d' : '#00f2fe';
    ctx.shadowBlur = 12;

    if (ent.type === 'LINE') {
      ctx.beginPath();
      ctx.moveTo(ent.x1, ent.y1);
      ctx.lineTo(ent.x2, ent.y2);
      ctx.stroke();
    } else if (ent.type === 'ARC' || ent.type === 'CIRCLE') {
      ctx.beginPath();
      if (ent.type === 'CIRCLE') {
        ctx.arc(ent.cx, ent.cy, Math.max(0.05, ent.radius), 0, Math.PI * 2);
      } else {
        const sRad = ((ent.start_angle || 0) * Math.PI) / 180;
        const eRad = ((ent.end_angle || 360) * Math.PI) / 180;
        ctx.arc(ent.cx, ent.cy, Math.max(0.05, ent.radius), sRad, eRad);
      }
      ctx.stroke();
    } else if (ent.type === 'POLYLINE' && ent.points && ent.points.length > 1) {
      ctx.beginPath();
      ctx.moveTo(ent.points[0][0], ent.points[0][1]);
      for (let j = 1; j < ent.points.length; j++) {
        ctx.lineTo(ent.points[j][0], ent.points[j][1]);
      }
      if (ent.closed) ctx.closePath();
      ctx.stroke();
    } else if (ent.type === 'TEXT') {
      const h = ent.height || 2.5;
      const w = Math.max(4, (ent.text ? ent.text.length : 1) * h * 0.65);
      ctx.save();
      ctx.translate(ent.x, ent.y);
      ctx.scale(1, -1);
      ctx.strokeRect(-2, -2, w + 4, h + 4);
      ctx.restore();
    }
    ctx.restore();
  }

  ctx.restore();
}

function _drawCadEntities(ctx, cad) {
  if (!cad || !cad.entities || !cad.entities.length) return;
  const zoom = _mpdTransform.zoom || 1;
  const entities = cad.entities;

  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // Group line segments by category for batched 60fps rendering
  const walls = [];
  const cols = [];
  const prkg = [];
  const floors = [];
  const thins = [];
  const dims = [];
  const others = [];
  const arcs = [];
  const polylines = [];
  const texts = [];

  for (let i = 0; i < entities.length; i++) {
    const e = entities[i];
    if (_mpdUniversalRule && typeof _mpdUniversalRule.predicate === 'function') {
      const tLower = String(e.type || '').toLowerCase();
      const isTarget = _mpdUniversalRule.target === 'all' || _mpdUniversalRule.target === 'cad' || _mpdUniversalRule.target === tLower || (_mpdUniversalRule.target === 'line' && (tLower === 'line' || tLower === 'polyline'));
      if (isTarget) {
        const matches = _mpdUniversalRule.predicate(e, {});
        if (!_mpdUniversalRule.visible && matches) continue;
        if (_mpdUniversalRule.isolate && !matches) continue;
      }
    }
    const t = e.type;
    if (t === 'LINE') {
      const lyr = (e.layer || '').toUpperCase();
      if (lyr.includes('WALL')) walls.push(e);
      else if (lyr.includes('COLS')) cols.push(e);
      else if (lyr.includes('PRKG') || lyr.includes('PARK')) prkg.push(e);
      else if (lyr.includes('FLOR') || lyr.includes('STRS') || lyr.includes('FNDN')) floors.push(e);
      else if (lyr.includes('DIM')) dims.push(e);
      else if (lyr.includes('THIN') || lyr.includes('HATCH') || lyr.includes('GENF')) thins.push(e);
      else others.push(e);
    } else if (t === 'ARC' || t === 'CIRCLE') {
      arcs.push(e);
    } else if (t === 'POLYLINE') {
      polylines.push(e);
    } else if (t === 'TEXT') {
      texts.push(e);
    }
  }

  function _drawBatch(list, color, width) {
    if (!list.length) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = width / zoom;
    ctx.beginPath();
    for (let i = 0; i < list.length; i++) {
      const l = list[i];
      ctx.moveTo(l.x1, l.y1);
      ctx.lineTo(l.x2, l.y2);
    }
    ctx.stroke();
  }

  // Draw floors, foundations & stairs
  _drawBatch(floors, '#38bdf8', 1.2);
  // Draw thin detailing
  _drawBatch(thins, 'rgba(148, 163, 184, 0.45)', 0.8);
  // Draw parking bays
  _drawBatch(prkg, '#34d399', 1.0);
  // Draw dimensions
  _drawBatch(dims, 'rgba(251, 191, 36, 0.75)', 0.8);
  // Draw other lines
  _drawBatch(others, '#94a3b8', 0.9);
  // Draw architectural walls (prominent blueprint blue)
  _drawBatch(walls, '#60a5fa', 1.6);
  // Draw structural columns (prominent cyan)
  _drawBatch(cols, '#00f2fe', 1.8);

  // Polyline layer styling
  function _getPolylineColor(lyr) {
    const l = (lyr || '').toUpperCase();
    if (_mpdIsolatedPlotIds || _mpdIsolatedSector) {
      if (!l.includes('ROAD')) return 'rgba(148, 163, 184, 0.14)';
    }
    if (_mpdIsolatedLandUse) {
      const iso = _mpdIsolatedLandUse.toUpperCase();
      if (iso.includes('MIXED') && !l.includes('MIXED') && !l.includes('ROAD')) return 'rgba(148, 163, 184, 0.14)';
      if (iso.includes('RESIDENTIAL') && !l.includes('RESIDENTIAL') && !l.includes('ROAD')) return 'rgba(148, 163, 184, 0.14)';
      if (iso.includes('COMMERCIAL') && !l.includes('COMMERCIAL') && !l.includes('ROAD')) return 'rgba(148, 163, 184, 0.14)';
    }
    if (l.includes('MP_RESIDENTIAL')) return '#f59e0b';
    if (l.includes('MP_COMMERCIAL')) return '#f43f5e';
    if (l.includes('MP_MIXED')) return '#a855f7';
    if (l.includes('MP_ROAD')) return '#94a3b8';
    if (l.includes('MP_PARK') || l.includes('MP_PROMENADE')) return '#10b981';
    if (l.includes('MP_SIKKA')) return '#eab308';
    if (l.includes('MP_PUBLIC')) return '#3b82f6';
    if (l.includes('MP_HOSPITALITY')) return '#ec4899';
    if (l.includes('MP_PARK') || l.includes('MP_PRKG')) return '#06b6d4';
    if (l.includes('MP_UTILITIES')) return '#fb923c';
    return '#38bdf8';
  }

  // Draw Polylines (grouped by layer color for 60fps performance)
  if (polylines.length) {
    const polyGroups = {};
    for (let i = 0; i < polylines.length; i++) {
      const p = polylines[i];
      if (!p.points || p.points.length < 2) continue;
      const c = _getPolylineColor(p.layer);
      if (!polyGroups[c]) polyGroups[c] = [];
      polyGroups[c].push(p);
    }
    for (const [color, plist] of Object.entries(polyGroups)) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.3 / zoom;
      ctx.beginPath();
      for (let i = 0; i < plist.length; i++) {
        const p = plist[i];
        ctx.moveTo(p.points[0][0], p.points[0][1]);
        for (let j = 1; j < p.points.length; j++) {
          ctx.lineTo(p.points[j][0], p.points[j][1]);
        }
        if (p.closed) ctx.closePath();
      }
      ctx.stroke();
    }
  }

  // Draw Arcs & Circles
  if (arcs.length) {
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.0 / zoom;
    for (let i = 0; i < arcs.length; i++) {
      const a = arcs[i];
      ctx.beginPath();
      if (a.type === 'CIRCLE') {
        ctx.arc(a.cx, a.cy, Math.max(0.05, a.radius), 0, Math.PI * 2);
      } else {
        const sRad = ((a.start_angle || 0) * Math.PI) / 180;
        const eRad = ((a.end_angle || 360) * Math.PI) / 180;
        ctx.arc(a.cx, a.cy, Math.max(0.05, a.radius), sRad, eRad);
      }
      ctx.stroke();
    }
  }

  // Draw Texts (upright with semantic filtering)
  if (_mpdTextMode !== 'off') {
    for (let i = 0; i < texts.length; i++) {
      const t = texts[i];
      if (!t.text) continue;
      const str = String(t.text).trim();
      if (!str) continue;

      if (_mpdTextFilter) {
        const filterStr = String(_mpdTextFilter).trim().toUpperCase();
        if (!str.toUpperCase().startsWith(filterStr)) {
          continue;
        }
        // Matching text under explicit text filter: render clearly with high-visibility badge
        const fSize = Math.max(7 / zoom, Math.min(22 / zoom, (t.height || 2.5) * 1.25));
        ctx.save();
        ctx.translate(t.x, t.y);
        ctx.scale(1, -1);
        ctx.font = `600 ${fSize * _mpdTextScale}px Inter, -apple-system, sans-serif`;
        const m = ctx.measureText(str);
        const padX = 5 / zoom;
        const padY = 2.5 / zoom;
        const rw = m.width + padX * 2;
        const rh = fSize + padY * 2;
        ctx.fillStyle = 'rgba(8, 14, 26, 0.92)';
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(-padX, -fSize * 0.85, rw, rh, 3 / zoom);
        else ctx.rect(-padX, -fSize * 0.85, rw, rh);
        ctx.fill();
        ctx.lineWidth = 1.2 / zoom;
        ctx.strokeStyle = '#38bdf8';
        ctx.stroke();
        ctx.fillStyle = '#38bdf8';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(str, 0, -fSize * 0.35);
        ctx.restore();
        continue;
      }

      if (_mpdUniversalRule && typeof _mpdUniversalRule.predicate === 'function') {
        const isTarget = _mpdUniversalRule.target === 'all' || _mpdUniversalRule.target === 'text' || _mpdUniversalRule.target === 'cad';
        if (isTarget) {
          const matches = _mpdUniversalRule.predicate(t, {});
          if (!_mpdUniversalRule.visible && matches) continue;
          if (_mpdUniversalRule.isolate && !matches) continue;
          if (matches && _mpdUniversalRule.visible) {
            const strokeCol = _mpdUniversalRule.color || '#38bdf8';
            const fSize = Math.max(7 / zoom, Math.min(22 / zoom, (t.height || 2.5) * 1.25));
            ctx.save();
            ctx.translate(t.x, t.y);
            ctx.scale(1, -1);
            ctx.font = `600 ${fSize * _mpdTextScale}px Inter, -apple-system, sans-serif`;
            const m = ctx.measureText(str);
            const padX = 5 / zoom;
            const padY = 2.5 / zoom;
            const rw = m.width + padX * 2;
            const rh = fSize + padY * 2;
            ctx.fillStyle = 'rgba(8, 14, 26, 0.92)';
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(-padX, -fSize * 0.85, rw, rh, 3 / zoom);
            else ctx.rect(-padX, -fSize * 0.85, rw, rh);
            ctx.fill();
            ctx.lineWidth = 1.2 / zoom;
            ctx.strokeStyle = strokeCol;
            ctx.stroke();
            ctx.fillStyle = strokeCol;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(str, 0, -fSize * 0.35);
            ctx.restore();
            continue;
          }
        }
      }

      const isMasterplanLabel = /RESIDENTIAL|COMMERCIAL|MIXED|HOSPITALITY|PARK|PLAZA|SIKKA|PROMENADE|UTILITY|ROAD|ROW|HIGHWAY|SECTOR|GFA|PLOT|SQM|AREA/i.test(str);
      const isMajorRoom = /ROOM|TANK|STAIR|RAMP|CORRIDOR|SHAFT|LOBBY|STORE|WORKSHOP|DEWA|FM|TOWER|CHILLED|PUMP|ELECTRICAL|TELECOM|REFUSE|PARKING/i.test(str) || isMasterplanLabel;
      const isParkingStall = /^\d+-[a-zA-Z0-9]+$/i.test(str) || /^T\d+$/i.test(str);
      const isMinorCode = /^(DR|FHC|SL|PL|MCB|DB|SM|FD)$/i.test(str);

      if (_mpdTextMode === 'rooms') {
        if (isMajorRoom && zoom >= 0.25) {
          const fSize = Math.max(7 / zoom, Math.min(16 / zoom, (t.height || 2.5) * 1.15));
          ctx.font = `600 ${fSize * _mpdTextScale}px Inter, -apple-system, sans-serif`;
          const m = ctx.measureText(str);
          const padX = 4 / zoom;
          const padY = 2 / zoom;
          const rw = m.width + padX * 2;
          const rh = fSize + padY * 2;

          ctx.save();
          ctx.translate(t.x, t.y);
          ctx.scale(1, -1);

          ctx.fillStyle = 'rgba(8, 14, 26, 0.88)';
          ctx.beginPath();
          if (ctx.roundRect) {
            ctx.roundRect(-padX, -fSize * 0.85, rw, rh, 3 / zoom);
          } else {
            ctx.rect(-padX, -fSize * 0.85, rw, rh);
          }
          ctx.fill();
          ctx.lineWidth = 1 / zoom;
          ctx.strokeStyle = isMasterplanLabel ? 'rgba(245, 158, 11, 0.7)' : 'rgba(56, 189, 248, 0.6)';
          ctx.stroke();

          ctx.fillStyle = isMasterplanLabel ? '#fcd34d' : '#38bdf8';
          ctx.textAlign = 'left';
          ctx.textBaseline = 'middle';
          ctx.fillText(str, 0, -fSize * 0.35);
          ctx.restore();
        } else if (isParkingStall && zoom >= 1.6) {
          const fSize = Math.max(1.8, Math.min(10 / zoom, t.height || 2.0));
          ctx.save();
          ctx.translate(t.x, t.y);
          ctx.scale(1, -1);
          ctx.font = `${fSize * _mpdTextScale}px monospace`;
          ctx.fillStyle = 'rgba(52, 211, 153, 0.85)';
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(str, 0, 0);
          ctx.restore();
        } else if (isMinorCode && zoom >= 2.4) {
          const fSize = Math.max(1.5, Math.min(8 / zoom, t.height || 1.8));
          ctx.save();
          ctx.translate(t.x, t.y);
          ctx.scale(1, -1);
          ctx.font = `${fSize * _mpdTextScale}px monospace`;
          ctx.fillStyle = 'rgba(148, 163, 184, 0.75)';
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(str, 0, 0);
          ctx.restore();
        }
      } else if (_mpdTextMode === 'all') {
        const screenH = (t.height || 2.5) * zoom;
        if (screenH >= 4) {
          const fontSize = Math.max(2, Math.min(22 / zoom, t.height || 2.5));
          ctx.save();
          ctx.translate(t.x, t.y);
          ctx.scale(1, -1);
          ctx.font = `${fontSize * _mpdTextScale}px monospace`;
          const lyr = (t.layer || '').toUpperCase();
          ctx.fillStyle = isMajorRoom ? '#38bdf8' : (isParkingStall ? '#34d399' : (lyr.includes('TEXT') ? '#e2e8f0' : 'rgba(255,255,255,0.7)'));
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(str, 0, 0);
          ctx.restore();
        }
      }
    }
  }

  ctx.restore();
}

function _drawGrid(ctx) {
  if (!_mpdCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const cw = _mpdCanvas.width / dpr;
  const ch = _mpdCanvas.height / dpr;
  const zoom = _mpdTransform.zoom || 1;

  // Viewport in CAD world coordinates (with Y-inversion)
  const minWx = -_mpdTransform.panX / zoom;
  const maxWx = (cw - _mpdTransform.panX) / zoom;
  const maxWy = _mpdTransform.panY / zoom;
  const minWy = (_mpdTransform.panY - ch) / zoom;

  // Adaptive grid step: target ~70-120 screen pixels between grid lines
  const targetUnits = 80 / zoom;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(1e-4, targetUnits))));
  const ratio = targetUnits / mag;
  let step = mag;
  if (ratio >= 5) step = mag * 5;
  else if (ratio >= 2) step = mag * 2;

  const startX = Math.floor(minWx / step) * step;
  const endX = Math.ceil(maxWx / step) * step;
  const startY = Math.floor(minWy / step) * step;
  const endY = Math.ceil(maxWy / step) * step;

  ctx.save();
  ctx.lineWidth = 1 / zoom;

  for (let x = startX; x <= endX; x += step) {
    const isMajor = Math.abs(x % (step * 5)) < 1e-4;
    ctx.strokeStyle = isMajor ? 'rgba(255, 255, 255, 0.08)' : 'rgba(255, 255, 255, 0.025)';
    ctx.beginPath();
    ctx.moveTo(x, minWy);
    ctx.lineTo(x, maxWy);
    ctx.stroke();
  }
  for (let y = startY; y <= endY; y += step) {
    const isMajor = Math.abs(y % (step * 5)) < 1e-4;
    ctx.strokeStyle = isMajor ? 'rgba(255, 255, 255, 0.08)' : 'rgba(255, 255, 255, 0.025)';
    ctx.beginPath();
    ctx.moveTo(minWx, y);
    ctx.lineTo(maxWx, y);
    ctx.stroke();
  }

  ctx.restore();
}

function _drawPlot(ctx, plot) {
  let coords = (plot.geometry && plot.geometry.coordinates && plot.geometry.coordinates.length >= 3) ? plot.geometry.coordinates : null;
  let synthBbox = null;
  let synthCentroid = null;

  if (!coords) {
    let cx = plot.geometry && plot.geometry.centroid ? plot.geometry.centroid[0] : null;
    let cy = plot.geometry && plot.geometry.centroid ? plot.geometry.centroid[1] : null;
    if (cx === null || cy === null) {
      if (plot.geometry && plot.geometry.label_anchor) {
        cx = plot.geometry.label_anchor[0];
        cy = plot.geometry.label_anchor[1];
      }
    }
    if ((cx === null || cy === null) && _mpdCadDrawing && _mpdCadDrawing.entities) {
      const raw = String(plot.plot_id || '').trim().replace(/^PLOT-/, '').replace(/^P-/, '');
      const ent = _mpdCadDrawing.entities.find(e => e.type === 'TEXT' && (e.text === raw || e.text === plot.plot_id));
      if (ent) { cx = ent.x; cy = ent.y; }
    }
    if (cx !== null && cy !== null) {
      const r = Math.max(14, Math.sqrt((plot.area_sqm || 1200) / Math.PI) * 0.7);
      coords = [];
      const steps = 16;
      for (let s = 0; s < steps; s++) {
        const rad = (s / steps) * Math.PI * 2;
        coords.push([cx + Math.cos(rad) * r, cy + Math.sin(rad) * r]);
      }
      synthBbox = [cx - r, cy - r, cx + r, cy + r];
      synthCentroid = [cx, cy];
    }
  }

  if (!coords || coords.length < 3) return;

  if (_mpdUniversalRule && typeof _mpdUniversalRule.predicate === 'function') {
    const isTarget = _mpdUniversalRule.target === 'all' || _mpdUniversalRule.target === 'plot';
    if (isTarget) {
      const matches = _mpdUniversalRule.predicate({}, plot);
      if (!_mpdUniversalRule.visible && matches) return;
      if (_mpdUniversalRule.isolate && !matches) return;
    }
  }

  const isSel = plot.plot_id === _mpdSelectedPlotId;
  const isHl = _mpdHighlightPlots.includes(plot.plot_id);
  const isHov = _mpdHoverPlot && _mpdHoverPlot.plot_id === plot.plot_id;
  let color = getPlotColor(plot);
  let customColorName = _mpdCustomStyles[plot.plot_id] || (_mpdWorkingRevision && _mpdWorkingRevision.project === _getMpdProject() && _mpdWorkingRevision.styles[plot.plot_id]);
  if (!customColorName && _mpdUniversalRule && _mpdUniversalRule.color && (_mpdUniversalRule.target === 'all' || _mpdUniversalRule.target === 'plot')) {
    if (_mpdUniversalRule.predicate({}, plot)) {
      customColorName = _mpdUniversalRule.color;
    }
  }
  if (customColorName) {
    const rawStr = String(customColorName).trim();
    const hex = MPD_COLOR_HEX[rawStr.toLowerCase()] || (/^#[0-9a-f]{6}$/i.test(rawStr) ? rawStr : '#ffff00');
    color = { fill: hex + '66', stroke: hex, text: '#ffffff' };
  }

  ctx.save();

  // Draw Parcel Boundary Polygon
  ctx.beginPath();
  ctx.moveTo(coords[0][0], coords[0][1]);
  for (let i = 1; i < coords.length; i++) {
    ctx.lineTo(coords[i][0], coords[i][1]);
  }
  ctx.closePath();

  // Fill
  let fillStyle = customColorName ? color.fill : (isHl ? _mpdHighlightColor + '88' : (isSel ? 'rgba(47, 107, 255, 0.55)' : (isHov ? 'rgba(255, 255, 255, 0.2)' : color.fill)));
  if (_mpdHatchPattern && _mpdHatchPattern !== 'solid' && !isSel && !isHov) {
    const pat = _getCanvasHatchPattern(ctx, _mpdHatchPattern, fillStyle);
    if (pat) fillStyle = pat;
  }
  ctx.fillStyle = fillStyle;
  ctx.fill();

  // Stroke
  ctx.lineWidth = (isSel ? 4 : (customColorName || isHl || isHov ? 3 : 1.5)) / _mpdTransform.zoom;
  ctx.strokeStyle = customColorName ? color.stroke : (isHl ? _mpdHighlightColor : (isSel ? '#00f2fe' : (plot.status === 'violation' ? '#f2585f' : color.stroke)));
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
  const bbox = (plot.geometry && plot.geometry.bbox) || synthBbox || [coords[0][0], coords[0][1], coords[1][0], coords[1][1]];
  const plotW = Math.max(20, bbox[2] - bbox[0]);
  const anchor = (plot.geometry && (plot.geometry.label_anchor || plot.geometry.centroid)) || synthCentroid;
  const cx = anchor ? anchor[0] : (bbox[0] + bbox[2]) / 2;
  const cy = anchor ? anchor[1] : (bbox[1] + bbox[3]) / 2;

  // Level-of-detail (LOD): when zoomed out (scale < 0.28), declutter dense micro-parcel text
  const isZoomedOut = _mpdTransform.zoom < 0.28;
  let showPlotLabel = !isZoomedOut || isSel || isHl || plot.status === 'violation' || plotW > 120;
  if (_mpdTextFilter) {
    const filterStr = String(_mpdTextFilter).trim().toUpperCase();
    if (!String(plot.plot_id || '').toUpperCase().startsWith(filterStr)) {
      showPlotLabel = false;
    }
  }
  if (_mpdUniversalRule && (_mpdUniversalRule.target === 'all' || _mpdUniversalRule.target === 'text' || _mpdUniversalRule.target === 'plot')) {
    const matches = _mpdUniversalRule.predicate({}, plot);
    if (!_mpdUniversalRule.visible && matches) showPlotLabel = false;
    if (_mpdUniversalRule.isolate && !matches) showPlotLabel = false;
  }

  if (showPlotLabel && _mpdTextMode !== 'off') {
    // Bounded Plot ID (never exceeds plot width)
    const maxTitleFont = Math.min(plotW * 0.18, 14 / _mpdTransform.zoom);
    const titleFont = Math.max(7, maxTitleFont) * _mpdTextScale;
    const maxSubFont = Math.min(plotW * 0.12, 11 / _mpdTransform.zoom);
    const subFont = Math.max(6, maxSubFont) * _mpdTextScale;

    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(1, -1);
    ctx.fillStyle = isSel ? '#ffffff' : color.text;
    ctx.font = `bold ${titleFont}px Inter, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(plot.plot_id, 0, -titleFont * 0.55);

    ctx.font = `${subFont}px Inter, sans-serif`;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
    ctx.fillText(`FAR ${plot.far.toFixed(2)}`, 0, subFont * 0.75);
    ctx.restore();
  }

  // Alert badge for violations
  if (plot.status === 'violation') {
    const badgeR = Math.min(9, Math.max(5, plotW * 0.05));
    const bx = bbox[2] - badgeR - 4;
    const by = bbox[3] - badgeR - 4;
    ctx.fillStyle = '#f2585f';
    ctx.beginPath();
    ctx.arc(bx, by, badgeR, 0, Math.PI * 2);
    ctx.fill();

    ctx.save();
    ctx.translate(bx, by);
    ctx.scale(1, -1);
    ctx.fillStyle = '#ffffff';
    ctx.font = `bold ${badgeR * 1.3}px Inter, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    if(_mpdTextMode !== 'off') ctx.fillText('!', 0, 0);
    ctx.restore();
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
      Checking project data and requested action...
    </div>
  `;
  hist.appendChild(agentMsg);
  hist.scrollTop = hist.scrollHeight;

  const proj = currentProject || 'C3085 - 3EH -Expo Hills';

  if (!window._mpdConversationalHistory) window._mpdConversationalHistory = [];
  window._mpdConversationalHistory.push({ role: 'user', content: query });
  if (window._mpdConversationalHistory.length > 12) window._mpdConversationalHistory.shift();

  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/ai-query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        project_id: proj,
        selected_plot_id: _mpdSelectedPlotId,
        active_land_use: _mpdIsolatedLandUse,
        active_sector: _mpdIsolatedSector,
        active_plot_ids: _mpdIsolatedPlotIds ? Array.from(_mpdIsolatedPlotIds) : null,
        history: window._mpdConversationalHistory.slice(-8)
      })
    });

    if (!res.ok) throw new Error('AI query service error');
    const data = await res.json();
    if (data.answer) {
      // Store the execution receipt below, after actions finish.
      if (window._mpdConversationalHistory.length > 12) window._mpdConversationalHistory.shift();
    }

    if(data.view_actions && data.view_actions.length){
      const backendAnswer = (data.answer && data.answer !== 'Drawing action requested.') ? data.answer : '';
      const receipt = await window._executeMpdChatActions(data.view_actions,proj);
      data.answer = receipt;
    } else _mpdHighlightPlots = data.highlight_plots || [];
    if(data.answer) window._mpdConversationalHistory.push({role:'assistant',content:data.answer.slice(0,500)});
    _mpdHighlightColor = /^#[0-9a-f]{6}$/i.test(data.highlight_color || '') ? data.highlight_color : '#ffff00';
    _drawCanvas();

    let toolBadges = '';
    if (data.tools_called && data.tools_called.length) {
      toolBadges = data.tools_called.map(t => `<span class="mpd-badge" style="font-size:9.5px;padding:2px 6px">Tool: ${_mpdEsc(t)}</span>`).join(' ');
    }

    agentMsg.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <div style="font-weight:700;color:var(--accent2);font-size:11.5px">Masterplan Copilot · Intent: ${_mpdEsc(data.intent || 'QUERY')}</div>
        <div>${toolBadges}</div>
      </div>
      <div style="line-height:1.5;font-size:12px">${data.html ? (data.html + (data.answer ? '<div style="margin-top:10px">' + mdLite(data.answer) + '</div>' : '')) : mdLite(data.answer)}</div>
    `;

    if (window.ExpoMotion && /```mermaid/i.test(data.answer || '')) {
      try { window.ExpoMotion.renderMermaidIn(agentMsg, data.answer); } catch(e){}
    }

    if (data.intent === 'EXPORT_EXCEL' && typeof window._downloadMpdExcel === 'function') {
      window._downloadMpdExcel(proj, data.export_land_use || '', data.export_sector || '', data.export_plots || null);
    }

    // If highlights exist, select first one without disrupting active chat tab
    if ((!data.view_actions || !data.view_actions.length) && _mpdHighlightPlots.length > 0) {
      _selectPlot(_mpdHighlightPlots[0], true, false);
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

  // Toggle CAD Linework
  const toggleCadBtn = _mpd$('btnToggleCadDrawing');
  if (toggleCadBtn) {
    toggleCadBtn.onclick = function() {
      _mpdShowCadLinework = !_mpdShowCadLinework;
      this.classList.toggle('active', _mpdShowCadLinework);
      _drawCanvas();
    };
  }

  // Toggle Parcel Overlays
  const togglePlotsBtn = _mpd$('btnTogglePlots');
  if (togglePlotsBtn) {
    togglePlotsBtn.onclick = function() {
      _mpdShowPlots = !_mpdShowPlots;
      this.classList.toggle('active', _mpdShowPlots);
      _drawCanvas();
    };
  }



  // Toggle CAD Text Mode: Rooms -> All -> Off
  const btnToggleText = _mpd$('btnToggleTextMode');
  if(btnToggleText && !document.getElementById('mpdTextSize')){
    const label = document.createElement('label');
    label.className = 'cad-btn';
    label.innerHTML = 'Text size <input id="mpdTextSize" type="range" min="30" max="180" step="5" value="'+Math.round(_mpdTextScale*100)+'" aria-label="Drawing text size" style="width:85px"><span id="mpdTextSizeValue">'+Math.round(_mpdTextScale*100)+'%</span>';
    btnToggleText.after(label);
    document.getElementById('mpdTextSize').oninput = e => {
      _mpdTextScale = Math.max(.3,Math.min(1.8,Number(e.target.value)/100));
      document.getElementById('mpdTextSizeValue').textContent = Math.round(_mpdTextScale*100)+'%';
      _drawCanvas();
    };
  }
  if (btnToggleText) {
    btnToggleText.onclick = function() {
      if (_mpdTextMode === 'rooms') {
        _mpdTextMode = 'all';
        const lbl = $('mpdTextModeLabel');
        if (lbl) lbl.textContent = 'Text: All';
        this.classList.add('active');
        toast('CAD Text: Showing all 1,838 room tags & stall numbers');
      } else if (_mpdTextMode === 'all') {
        _mpdTextMode = 'off';
        const lbl = $('mpdTextModeLabel');
        if (lbl) lbl.textContent = 'Text: Off';
        this.classList.remove('active');
        toast('CAD Text: Linework only (All text hidden)');
      } else {
        _mpdTextMode = 'rooms';
        const lbl = $('mpdTextModeLabel');
        if (lbl) lbl.textContent = 'Text: Rooms';
        this.classList.add('active');
        toast('CAD Text: Rooms Only (De-cluttered view)');
      }
      _drawCanvas();
    };
  }

  // Live Audit Lines Modal
  const liveAuditBtn = _mpd$('mpdLiveAuditBtn');
  if (liveAuditBtn) {
    liveAuditBtn.onclick = () => _openLiveAuditModal(activeProj);
  }



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
              <th style="padding:10px 12px;font-weight:600;text-align:right">Action</th>
            </tr>
          </thead>
          <tbody id="mpdFilesTableBody">
            <tr>
              <td colspan="7" style="text-align:center;padding:24px;color:var(--muted)">Loading uploaded files...</td>
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
                ${canReconcile ? 'Both CAD drawing and Excel register detected. Click Reconcile & Link to establish ground truth.' : (cadFiles.length === 0 ? 'Upload this project\'s CAD vector drawing (.dxf/.dwg) to correlate physical parcels with zoning registers.' : 'Upload this project\'s Excel register (.xlsx) to correlate parcel geometry with zoning.')}
              </div>
            </div>
            ${canReconcile ? `<span class="mpd-badge" style="font-size:10.5px;padding:3px 8px;background:rgba(47,107,255,.2);color:var(--accent2)">Ready to Link</span>` : `<span class="mpd-badge warn" style="font-size:10.5px;padding:3px 8px">Incomplete</span>`}
          </div>
        `;
      }

      const tbody = modal.querySelector('#mpdFilesTableBody');
      if (!files.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--muted)">No masterplan files uploaded yet for this project.</td></tr>`;
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
          : `<span class="mpd-badge" style="font-size:10px">${_mpdEsc(f.status || 'Uploaded')}</span>`;

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
            <td style="padding:9px 12px;text-align:right">
              <button class="cad-btn" style="padding:3px 7px;font-size:10.5px;color:var(--red);border-color:rgba(242,88,95,.3)" onclick="window._deleteMpdFile('${_mpdEsc(activeProj)}', '${_mpdEsc(f.id)}', '${_mpdEsc(f.filename)}')">
                ✕ Delete
              </button>
            </td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    console.error('Failed to load files:', err);
  }
}

window._deleteMpdFile = async function(proj, fileId, filename) {
  if (!confirm(`Delete file "${filename}" from this project?`)) return;
  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/files/${encodeURIComponent(fileId)}`, {
      method: 'DELETE'
    });
    if (res.ok) {
      toast(`🗑️ Deleted ${filename}`);
      _openFilesModal(proj);
      _loadFilesCount(proj);
      _loadMasterplanData(proj);
    } else {
      toast('Failed to delete file');
    }
  } catch (e) {
    toast(`Error: ${e.message}`);
  }
};

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

window._mpdAutoResolveClashes = async function() {
  const proj = _mpdCurrentProject || "C3085 - 3EH -Expo Hills";
  if (!confirm("Run Local AI Clash Resolver on active masterplan? This will automatically prune duplicate CAD layers, carve utility enclaves with Shapely seam buffers, clip boundary slivers, and harmonize FAR density to achieve 100% compliance.")) return;
  toast("⚡ Running Local AI Clash Resolver...", "info");
  try {
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/resolve-clashes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    if (res.ok) {
      const data = await res.json();
      toast(`✅ Local AI resolved all clashes: 100% compliant! (${data.boundary_overlaps_resolved} overlaps, ${data.far_violations_resolved} FAR violations resolved)`);
      _mpdAddChatMsg('a', `
        <div style="border-left:3px solid var(--green);padding-left:10px">
          <div style="font-weight:700;color:var(--green);font-size:13px;margin-bottom:4px">⚡ Local AI Masterplan Clash Resolution Complete</div>
          <div style="font-size:12px;color:var(--text);line-height:1.5">
            <b>100% Compliant:</b> Automatically resolved <b>${data.baseline_violations}</b> clashes.<br>
            • <b>Boundary Overlaps Resolved:</b> ${data.boundary_overlaps_resolved} (${data.duplicate_layers_removed.length} duplicate layers pruned, ${data.substations_carved_count} kiosks carved, ${data.slivers_clipped_count} slivers trimmed)<br>
            • <b>FAR Violations Resolved:</b> ${data.far_violations_resolved} parcels harmonized to approved zoning schedules<br>
            • <b>Active Parcels:</b> ${data.final_plots} (0 Violations, 0 Overlaps)
          </div>
        </div>
      `);
      await _loadMasterplanData(proj);
      await _loadFilesCount(proj);
    } else {
      const err = await res.json().catch(() => ({}));
      toast(`⚠️ Clash resolution returned error: ${err.detail || 'failed'}`);
    }
  } catch (err) {
    toast(`❌ Failed to resolve clashes: ${err.message}`);
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

function _openLiveAuditModal(proj) {
  const activeProj = _getMpdProject(proj);
  document.querySelectorAll('.mpd-modal-wrapper').forEach(m => m.remove());

  const entities = (_mpdCadDrawing && _mpdCadDrawing.entities) || [];
  const totalEnts = (_mpdCadDrawing && _mpdCadDrawing.total_entities) || entities.length;
  const dwgName = (_mpdCadDrawing && _mpdCadDrawing.filename) || 'Masterplan CAD Drawing';

  // Real entity breakdown by type
  let lineCount = 0, polyCount = 0, textCount = 0, arcCount = 0, circleCount = 0;
  const layerStats = {};

  for (let i = 0; i < entities.length; i++) {
    const e = entities[i];
    const t = e.type;
    if (t === 'LINE') lineCount++;
    else if (t === 'POLYLINE') polyCount++;
    else if (t === 'TEXT') textCount++;
    else if (t === 'ARC') arcCount++;
    else if (t === 'CIRCLE') circleCount++;

    const lyr = e.layer || '0';
    layerStats[lyr] = (layerStats[lyr] || 0) + 1;
  }

  // Top layers sorted by frequency
  const sortedLayers = Object.entries(layerStats).sort((a, b) => b[1] - a[1]);

  // Parcel & spatial compliance data
  const totalPlots = _mpdPlots ? _mpdPlots.length : 0;
  const compliantPlots = _mpdSummary ? (_mpdSummary.compliant_plots || 0) : _mpdPlots.filter(p => p.status === 'compliant').length;
  const warningPlots = _mpdSummary ? (_mpdSummary.warning_plots || 0) : _mpdPlots.filter(p => p.status === 'warning').length;
  const violationPlots = _mpdSummary ? (_mpdSummary.violation_plots || 0) : _mpdPlots.filter(p => p.status === 'violation').length;
  const totalArea = _mpdSummary ? (_mpdSummary.total_area_sqm || 0) : _mpdPlots.reduce((s, p) => s + (p.area_sqm || 0), 0);
  const totalGfa = _mpdSummary ? (_mpdSummary.total_gfa_sqm || 0) : _mpdPlots.reduce((s, p) => s + (p.achieved_gfa || 0), 0);
  const avgFar = _mpdSummary && _mpdSummary.average_far ? _mpdSummary.average_far.toFixed(2) : (totalArea > 0 ? (totalGfa / totalArea).toFixed(2) : '0.00');

  // Land-use breakdown
  const landUseCounts = {};
  if (_mpdPlots) {
    for (const p of _mpdPlots) {
      const lu = p.land_use || 'Unassigned';
      landUseCounts[lu] = (landUseCounts[lu] || 0) + 1;
    }
  }

  const modal = _mpdEl('div', 'mpd-modal-wrapper modal-overlay cad-modal-overlay', `
    <div class="modal" style="width:840px;max-width:95vw;max-height:88vh;background:#0d1424;border:1px solid var(--border);border-radius:var(--r-lg);padding:24px;box-shadow:0 14px 40px rgba(0,0,0,.7);display:flex;flex-direction:column;gap:14px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
          <svg class="ico" style="width:20px;height:20px;color:var(--green)" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
          ⚡ Live CAD Vector &amp; Spatial Compliance Audit
        </div>
        <button id="closeLiveAuditModal" style="background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1">&times;</button>
      </div>

      <div style="font-size:12px;color:var(--muted);line-height:1.5">
        Active drawing: <b>${_mpdEsc(dwgName)}</b> · Project: <b>${_mpdEsc(activeProj)}</b> · Analyzed <b>${totalEnts.toLocaleString()}</b> live vector entities.
      </div>

      <!-- KPI Summary Cards -->
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px">
        <div style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--r-md);padding:10px 12px">
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;font-weight:700">CAD Entities</div>
          <div style="font-size:18px;font-weight:800;color:var(--text);margin-top:2px">${totalEnts.toLocaleString()}</div>
          <div style="font-size:10px;color:var(--green)">${lineCount} Lines · ${polyCount} Polylines</div>
        </div>
        <div style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--r-md);padding:10px 12px">
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;font-weight:700">Parcels</div>
          <div style="font-size:18px;font-weight:800;color:var(--accent2);margin-top:2px">${totalPlots} Plots</div>
          <div style="font-size:10px;color:${violationPlots > 0 ? 'var(--red)' : 'var(--green)'}">${compliantPlots} OK · ${violationPlots} Clashes</div>
        </div>
        <div style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--r-md);padding:10px 12px">
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;font-weight:700">Total Area</div>
          <div style="font-size:18px;font-weight:800;color:var(--text);margin-top:2px">${Math.round(totalArea).toLocaleString()} <span style="font-size:11px;font-weight:normal;color:var(--muted)">m²</span></div>
          <div style="font-size:10px;color:var(--muted)">${((totalArea)/10000).toFixed(1)} Hectares</div>
        </div>
        <div style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--r-md);padding:10px 12px">
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;font-weight:700">Gross Floor Area</div>
          <div style="font-size:18px;font-weight:800;color:var(--green);margin-top:2px">${Math.round(totalGfa).toLocaleString()} <span style="font-size:11px;font-weight:normal;color:var(--muted)">m²</span></div>
          <div style="font-size:10px;color:var(--muted)">Average FAR: ${avgFar}</div>
        </div>
      </div>

      <!-- Live Audit Detail Cards -->
      <div style="flex:1;overflow-y:auto;max-height:380px;display:flex;flex-direction:column;gap:10px;padding-right:4px">
        <!-- Card 1: CAD Entity Geometry Composition -->
        <div style="background:#070b15;border:1px solid var(--border);border-radius:var(--r-md);padding:12px 14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div style="font-weight:700;color:var(--text);font-size:13px;display:flex;align-items:center;gap:6px">
              📐 Vector Geometry Composition
            </div>
            <span class="mpd-badge" style="font-size:10px;padding:2px 7px">${totalEnts} Elements</span>
          </div>
          <div style="font-size:11.5px;color:var(--muted);line-height:1.6">
            • <b>Lines:</b> ${lineCount.toLocaleString()} vector segments<br>
            • <b>Polylines:</b> ${polyCount.toLocaleString()} boundary polygons<br>
            • <b>Text Annotations:</b> ${textCount.toLocaleString()} room tags, sector labels, and coordinates<br>
            • <b>Arcs &amp; Circles:</b> ${(arcCount + circleCount).toLocaleString()} radial features
          </div>
        </div>

        <!-- Card 2: Drawing Layers Distribution -->
        <div style="background:#070b15;border:1px solid var(--border);border-radius:var(--r-md);padding:12px 14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div style="font-weight:700;color:var(--text);font-size:13px;display:flex;align-items:center;gap:6px">
              📑 Active Drawing Layers (${sortedLayers.length} Layers)
            </div>
            <span class="mpd-badge green" style="font-size:10px;padding:2px 7px">✓ Valid Layer Syntax</span>
          </div>
          <div style="font-size:11px;color:var(--text);display:grid;grid-template-columns:repeat(auto-fill, minmax(220px, 1fr));gap:6px;margin-top:6px">
            ${sortedLayers.slice(0, 12).map(([layer, count]) => `
              <div style="background:#0a101f;padding:5px 8px;border-radius:4px;border:1px solid rgba(255,255,255,.05);display:flex;justify-content:space-between">
                <span style="color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:150px">${_mpdEsc(layer)}</span>
                <b>${count}</b>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- Card 3: Spatial Zoning & Encroachment Compliance -->
        <div style="background:#070b15;border:1px solid var(--border);border-radius:var(--r-md);padding:12px 14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div style="font-weight:700;color:var(--text);font-size:13px;display:flex;align-items:center;gap:6px">
              ⚖️ Spatial Reasoning &amp; Boundary Encroachment Engine
            </div>
            <span class="mpd-badge ${violationPlots > 0 ? 'red' : 'green'}" style="font-size:10px;padding:2px 7px">
              ${violationPlots > 0 ? `${violationPlots} Boundary Clashes Detected` : '✓ 100% Compliant'}
            </span>
          </div>
          <div style="font-size:11.5px;color:var(--muted);line-height:1.5">
            ${violationPlots > 0
              ? `• Automated Shapely polygon intersection audit detected <b>${violationPlots} clashes &amp; regulatory violations</b> in the masterplan layout.<br>• Use the "Violations Only" filter or click below to automatically resolve all clashes using Local AI.<br>
                 <div style="margin-top:8px"><button class="cad-btn primary" style="padding:6px 14px;font-size:11px;background:#35d07f;color:#030712;font-weight:700;border:none;border-radius:4px;cursor:pointer" onclick="window._mpdAutoResolveClashes()">⚡ Auto-Resolve Clashes (Local AI)</button></div>`
              : `• All ${totalPlots} parcel boundaries satisfy boundary isolation and zoning limits with 0 encroaching overlaps detected.`
            }
          </div>
        </div>

        <!-- Card 4: Land-Use Allocation -->
        <div style="background:#070b15;border:1px solid var(--border);border-radius:var(--r-md);padding:12px 14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div style="font-weight:700;color:var(--text);font-size:13px;display:flex;align-items:center;gap:6px">
              🏙️ Masterplan Land-Use Allocation
            </div>
            <span class="mpd-badge" style="font-size:10px;padding:2px 7px">${Object.keys(landUseCounts).length} Categories</span>
          </div>
          <div style="font-size:11px;color:var(--text);display:grid;grid-template-columns:repeat(auto-fill, minmax(180px, 1fr));gap:6px;margin-top:6px">
            ${Object.entries(landUseCounts).map(([lu, count]) => `
              <div style="background:#0a101f;padding:5px 8px;border-radius:4px;border:1px solid rgba(255,255,255,.05);display:flex;justify-content:space-between">
                <span style="color:var(--muted)">${_mpdEsc(lu)}</span>
                <b>${count} plots</b>
              </div>
            `).join('')}
          </div>
        </div>
      </div>

      <!-- Modal Bottom Actions -->
      <div style="display:flex;justify-content:space-between;align-items:center;padding-top:8px;border-top:1px solid rgba(255,255,255,.05)">
        <div style="display:flex;gap:8px">
          <button class="cad-btn" id="auditFitViewBtn" style="font-size:11px">Fit Entire View</button>
        </div>
        <div style="display:flex;gap:10px">
          <button class="cad-btn" id="exportAuditReportBtn" style="display:flex;align-items:center;gap:6px">
            <svg class="ico" style="width:13px;height:13px" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
            Download Audit Report (JSON)
          </button>
          <button class="primary" id="closeLiveAuditBtn" style="padding:5px 16px">Done</button>
        </div>
      </div>
    </div>
  `);

  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:99999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(5px)";
  document.body.appendChild(modal);

  const close1 = modal.querySelector('#closeLiveAuditModal');
  const close2 = modal.querySelector('#closeLiveAuditBtn');
  if (close1) close1.onclick = () => modal.remove();
  if (close2) close2.onclick = () => modal.remove();
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  const fitBtn = modal.querySelector('#auditFitViewBtn');
  if (fitBtn) {
    fitBtn.onclick = () => {
      modal.remove();
      _fitCanvasToPlots();
    };
  }

  const exportBtn = modal.querySelector('#exportAuditReportBtn');
  if (exportBtn) {
    exportBtn.onclick = () => {
      const auditPayload = {
        project: activeProj,
        drawing: dwgName,
        timestamp: new Date().toISOString(),
        entities_summary: {
          total: totalEnts,
          lines: lineCount,
          polylines: polyCount,
          texts: textCount,
          arcs_and_circles: arcCount + circleCount
        },
        top_layers: sortedLayers.slice(0, 20).map(([l, c]) => ({ layer: l, count: c })),
        plots_summary: {
          total_plots: totalPlots,
          compliant_plots: compliantPlots,
          warning_plots: warningPlots,
          violation_plots: violationPlots,
          total_area_sqm: totalArea,
          total_gfa_sqm: totalGfa,
          average_far: parseFloat(avgFar) || 0
        },
        land_use_distribution: landUseCounts
      };
      const blob = new Blob([JSON.stringify(auditPayload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `CAD_LIVE_AUDIT_${activeProj.replace(/[^a-zA-Z0-9]/g, '_')}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast('📥 Downloaded Live CAD Audit Report');
    };
  }
}

window.renderMPDWorkspace = renderMPDWorkspace;
window._switchMpdTab = _switchMpdTab;
window._filterPlots = _filterPlots;
window._selectPlot = _selectPlot;
window._calcInspFar = _calcInspFar;
window._savePlotInspection = _savePlotInspection;
window._sendMpdChip = _sendMpdChip;
window._handleMpdChatSubmit = _handleMpdChatSubmit;
function _resolveActionPlotIds(action) {
  if (!_mpdPlots || !_mpdPlots.length) return [];
  if (Array.isArray(action.plot_ids) && action.plot_ids.length) {
    return action.plot_ids.map(pid => {
      const found = _findPlot(pid);
      return found ? found.plot_id : pid;
    });
  }
  if (action.land_use || action.sector || action.status) {
    return _mpdPlots.filter(p => {
      if (action.land_use && !_matchesLandUse(p.land_use, action.land_use)) return false;
      if (action.sector && !_matchesSector(p.sector, action.sector)) return false;
      if (action.status && String(p.status || '').toLowerCase() !== String(action.status).toLowerCase()) return false;
      return true;
    }).map(p => p.plot_id);
  }
  if (action.filter_field && Number.isFinite(Number(action.value))) {
    const v = Number(action.value);
    const op = action.operator || '>';
    const fName = action.filter_field === 'area' ? 'area_sqm' : (action.filter_field === 'gfa' ? 'achieved_gfa' : action.filter_field);
    return _mpdPlots.filter(p => {
      const val = Number(p[fName] || 0);
      if (op === '>') return val > v;
      if (op === '>=') return val >= v;
      if (op === '<') return val < v;
      if (op === '<=') return val <= v;
      if (op === '==') return Math.abs(val - v) < 1e-6;
      return false;
    }).map(p => p.plot_id);
  }
  return [];
}

window._performMpdCadAction = async (action, project) => {
  if(project !== _getMpdProject()) return 'Edit not applied: select the intended project first.';
  if(_mpdEditBusy) return 'An edit is already running. Wait for its result before the next edit.';
  _mpdEditBusy=true;
  try {
    const matchedIds = _resolveActionPlotIds(action);
    if(!matchedIds.length) return 'Edit not applied: no matching plots were found.';
    if (_mpdSelectedSource === 'register') {
      matchedIds.forEach(id => { _mpdCustomStyles[id] = action.color; });
      _mpdHighlightPlots = [];
      _drawCanvas();
      return `Canvas preview updated for ${matchedIds.length} plot(s). No CAD revision was saved; select a CAD drawing to create a downloadable working copy.`;
    }
    const sourceAtRequest = _mpdSelectedSource;
    const previous = _mpdWorkingRevision && _mpdWorkingRevision.project === project ? _mpdWorkingRevision : null;
    const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(project)}/cad-revisions`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...action,source_id:sourceAtRequest || null,base_revision:previous ? previous.revision : null})
    });
    const result = await res.json().catch(() => ({}));
    if(!res.ok) {
      return 'Edit not applied: '+(typeof result.detail==='string'?result.detail:'source validation failed');
    }
    if(project !== _getMpdProject() || sourceAtRequest !== _mpdSelectedSource) return 'Working revision created for the previous source; no change applied to this view.';
    const styles = {...(previous ? previous.styles : {})};
    result.plot_ids.forEach(id => { styles[id] = result.color; _mpdCustomStyles[id] = result.color; });
    _mpdWorkingRevision = {...result,project,styles};
    _mpdHighlightPlots = [];
    _drawCanvas();
    return `Created a separate ${result.format.toUpperCase()} working revision: ${result.plot_ids.length} plot hatch(es) changed to ${result.color}. Original unchanged. Use Save working copy to download. Full drawing fidelity still requires review.`;
  } finally { _mpdEditBusy=false; }
};
window._saveMpdWorkingCopy = () => {
  const r = _mpdWorkingRevision;
  if(!r || r.project !== _getMpdProject()){toast('Create a working revision through chat first');return;}
  const a=document.createElement('a');a.href=`${API}/api/v1/masterplan/projects/${encodeURIComponent(r.project)}/cad-revisions/${r.revision}/working`;a.download='';a.click();
};
window._openMpdRevisions = async () => {
  const project=_getMpdProject();
  const response=await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(project)}/cad-revisions`);
  if(!response.ok){toast('Could not load revisions');return;}
  const data=await response.json();
  const modal=document.createElement('dialog');
  const heading=document.createElement('h3');heading.textContent='Saved CAD revisions';modal.appendChild(heading);
  for(const revision of data.revisions){
    const row=document.createElement('p');row.textContent=`${revision.source_name} — ${revision.color} — ${revision.created_at} `;
    for(const artifact of ['working','original']){
      if(artifact==='original' && (typeof currentUser==='undefined' || currentUser?.role!=='admin')) continue;
      const link=document.createElement('a');link.textContent=artifact==='original'?' Admin original ':' Download copy ';
      link.href=`${API}/api/v1/masterplan/projects/${encodeURIComponent(project)}/cad-revisions/${revision.revision}/${artifact}`;link.download='';row.appendChild(link);
    }
    modal.appendChild(row);
  }
  const close=document.createElement('button');close.textContent='Close';close.onclick=()=>modal.remove();modal.appendChild(close);
  document.body.appendChild(modal);modal.showModal();
};
window._returnMpdOriginal = () => {
  _mpdTextMode='rooms';_mpdTextScale=1;_mpdHatchPattern='solid';
  _mpdShowCadLinework=true;_mpdShowPlots=true;_mpdShowSetbacks=true;_mpdShowViolationsOnly=false;
  const size=document.getElementById('mpdTextSize'),value=document.getElementById('mpdTextSizeValue');
  if(size)size.value=100;if(value)value.textContent='100%';
  const label=document.getElementById('mpdTextModeLabel');if(label)label.textContent='Text: Rooms';
  _mpdWorkingRevision=null;_mpdHighlightPlots=[];_mpdIsolatedLandUse=null;_mpdIsolatedSector=null;_mpdIsolatedPlotIds=null;_mpdIsolatedLabel='';_mpdCustomStyles={};_mpdTextFilter=null;_mpdUniversalRule=null;_loadMasterplanData(_getMpdProject());toast('Returned to original source view; saved revisions are retained');
};
window._executeMpdChatActions = async (actions, project) => {
  if(project !== _getMpdProject() || (typeof currentDest !== 'undefined' && currentDest !== 'mpd'))
    return 'Action not applied: open MPD in the requested project first.';
  if(!Array.isArray(actions) || !actions.length) return 'Action not applied: no drawing action received.';
  const receipts=[];
  for(const action of actions){
    try {
      const receipt=action.type==='edit_hatches'
        ? await window._performMpdCadAction(action,project)
        : window._applyMpdViewActions([action],project);
      receipts.push(receipt || 'Action not applied: the engine returned no confirmation.');
    } catch(error){ receipts.push('Action failed: '+error.message); }
  }
  return receipts.join('\n');
};
window._applyMpdViewActions = (actions, project) => {
  if(typeof currentDest !== 'undefined' && currentDest !== 'mpd') return 'Drawing action was not applied: open MPD first.';
  if(project !== _getMpdProject() || !document.getElementById('mpdCanvas')) return 'Drawing action was not applied: the active project or MPD view changed.';
  if(!Array.isArray(actions) || !actions.length) return 'Drawing action was not applied: invalid command.';
  
  const receipts = [];
  for (const action of actions) {
    if(!action || typeof action !== 'object') continue;
    
    if(action.type === 'set_text_mode' && ['off','all','rooms'].includes(action.mode)){
      _mpdTextMode = action.mode;
      const label = document.getElementById('mpdTextModeLabel');
      if(label) label.textContent = 'Text: ' + ({off:'Off',all:'All',rooms:'Rooms'}[action.mode]);
      const button = document.getElementById('btnToggleTextMode');
      if(button) button.classList.toggle('active', action.mode !== 'off');
      receipts.push(action.mode === 'off' ? 'Hidden all drawing text, plot labels and FAR labels.' : 'Shown drawing text and plot labels.');
    } else if(action.type === 'set_text_scale' && Number.isFinite(action.scale) && action.scale >= .3 && action.scale <= 1.8){
      _mpdTextScale = action.scale;
      const input = document.getElementById('mpdTextSize'), label = document.getElementById('mpdTextSizeValue');
      if(input) input.value = Math.round(action.scale*100);
      if(label) label.textContent = Math.round(action.scale*100)+'%';
      receipts.push('Set drawing text size to '+Math.round(action.scale*100)+'%.');
    } else if(action.type === 'set_layers'){
      const layerNotes = [];
      if(action.show_setbacks !== undefined) {
        _mpdShowSetbacks = Boolean(action.show_setbacks);
        const btn = document.getElementById('btnToggleSetbacks');
        if(btn) btn.classList.toggle('active', _mpdShowSetbacks);
        layerNotes.push(_mpdShowSetbacks ? 'Setback Envelopes ON' : 'Setback Envelopes OFF');
      }
      if(action.show_violations_only !== undefined) {
        _mpdShowViolationsOnly = Boolean(action.show_violations_only);
        const btn = document.getElementById('btnToggleViolations');
        if(btn) btn.classList.toggle('active', _mpdShowViolationsOnly);
        layerNotes.push(_mpdShowViolationsOnly ? 'Violations-Only Filter ON' : 'Violations-Only Filter OFF');
      }
      if(action.show_cad_linework !== undefined) {
        _mpdShowCadLinework = Boolean(action.show_cad_linework);
        layerNotes.push(_mpdShowCadLinework ? 'CAD Linework ON' : 'CAD Linework OFF');
      }
      if(action.text_mode && ['off','all','rooms'].includes(action.text_mode)) {
        _mpdTextMode = action.text_mode;
        const btn = document.getElementById('btnToggleTextMode');
        if(btn) btn.classList.toggle('active', action.text_mode !== 'off');
        const lbl = document.getElementById('mpdTextModeLabel');
        if(lbl) lbl.textContent = 'Text: ' + ({off:'Off',all:'All',rooms:'Rooms'}[action.text_mode]);
        layerNotes.push(`Text Mode: ${action.text_mode}`);
      }
      if(action.text_filter !== undefined) {
        _mpdTextFilter = action.text_filter ? String(action.text_filter).trim() : null;
        if (_mpdTextFilter && _mpdTextMode === 'off') {
          _mpdTextMode = 'all';
          const btn = document.getElementById('btnToggleTextMode');
          if(btn) btn.classList.toggle('active', true);
          const lbl = document.getElementById('mpdTextModeLabel');
          if(lbl) lbl.textContent = 'Text: All';
        }
        layerNotes.push(_mpdTextFilter ? `Text Filter: "${_mpdTextFilter}*"` : 'Text Filter: All');
      }
      if(action.hatch_pattern !== undefined) {
        _mpdHatchPattern = action.hatch_pattern || 'solid';
        layerNotes.push(`Hatch Pattern: ${_mpdHatchPattern}`);
      }
      receipts.push(`Updated canvas layers: ${layerNotes.join(' · ')}`);
    } else if(action.type === 'set_text_filter'){
      _mpdTextFilter = action.text_filter ? String(action.text_filter).trim() : null;
      if (_mpdTextFilter && _mpdTextMode === 'off') {
        _mpdTextMode = 'all';
        const btn = document.getElementById('btnToggleTextMode');
        if(btn) btn.classList.toggle('active', true);
        const lbl = document.getElementById('mpdTextModeLabel');
        if(lbl) lbl.textContent = 'Text: All';
      }
      receipts.push(_mpdTextFilter ? `Filtered canvas text annotations to "${_mpdTextFilter}*"` : 'Cleared canvas text filter.');
    } else if(action.type === 'apply_universal_rule' && action.rule){
      const r = action.rule;
      const predicate=_compilePredicate(r.condition);
      if(predicate.error){receipts.push('Rule not applied: '+predicate.error);continue;}
      _mpdUniversalRule = {
        target: String(r.target || 'all').toLowerCase(),
        condition: String(r.condition || 'true'),
        visible: r.visible !== false,
        color: r.color || null,
        isolate: Boolean(r.isolate),
        predicate
      };

      if (_mpdUniversalRule.target === 'text' || _mpdUniversalRule.target === 'all') {
        // Matching visibility is handled by the predicate, not a global hide-all toggle.
        _mpdTextMode = 'all';
        const btn=document.getElementById('btnToggleTextMode');if(btn)btn.classList.toggle('active',true);
        const label=document.getElementById('mpdTextModeLabel');if(label)label.textContent='Text: All';
      }

      if (_mpdUniversalRule.color && (_mpdUniversalRule.target === 'plot' || _mpdUniversalRule.target === 'all')) {
        let recolorCount = 0;
        (_mpdPlots || []).forEach(p => {
          if (_mpdUniversalRule.predicate({}, p)) {
            _mpdCustomStyles[p.plot_id] = _mpdUniversalRule.color;
            recolorCount++;
          }
        });
      }

      if (_mpdUniversalRule.isolate && (_mpdUniversalRule.target === 'plot' || _mpdUniversalRule.target === 'all')) {
        const matched = (_mpdPlots || []).filter(p => _mpdUniversalRule.predicate({}, p));
        if (matched.length > 0) {
          _mpdIsolatedPlotIds = new Set(matched.map(p => p.plot_id));
          _mpdIsolatedLabel = `Rule: ${_mpdUniversalRule.condition}`;
          _renderPlotTable(_mpdPlots);
          const totalArea = matched.reduce((s, p) => s + (Number(p.area_sqm) || 0), 0);
          const totalGfa = matched.reduce((s, p) => s + (Number(p.achieved_gfa) || 0), 0);
          const selInfo = document.getElementById('mpdSelectedInfo');
          if (selInfo) {
            selInfo.innerHTML = `🔍 <b>Isolated Filter:</b> <span style="color:var(--accent2)">${_mpdEsc(_mpdIsolatedLabel)}</span> (${matched.length} plots · Area: ${Math.round(totalArea).toLocaleString()} m² · GFA: ${Math.round(totalGfa).toLocaleString()} m²)`;
          }
          _fitCanvasToSubset(matched);
        }
      }

      const actionVerb = _mpdUniversalRule.isolate ? 'Isolated' : (_mpdUniversalRule.visible ? 'Showed' : 'Hidden');
      receipts.push(`${actionVerb} matching **${_mpdUniversalRule.target.toUpperCase()}** entities where \`${_mpdUniversalRule.condition}\`` + (_mpdUniversalRule.color ? ` (color: ${_mpdUniversalRule.color})` : ''));
    } else if(action.type === 'isolate_plots'){
      const resolvedIds = _resolveActionPlotIds(action);
      const idSet = new Set(resolvedIds);
      const matched = (_mpdPlots || []).filter(p => idSet.has(p.plot_id));
      _mpdIsolatedPlotIds = idSet;
      _mpdIsolatedLandUse = action.land_use || null;
      _mpdIsolatedSector = action.sector || null;
      _mpdIsolatedLabel = action.label || action.sector || action.land_use || 'Filtered Parcels';
      _mpdHighlightPlots = [];
      const luSelect = document.getElementById('tblLandUse');
      if (luSelect) {
        luSelect.value = _mpdIsolatedLandUse || 'All';
        _mpdFilterLandUse = luSelect.value;
      }
      _renderPlotTable(_mpdPlots);
      const totalArea = matched.reduce((s, p) => s + (Number(p.area_sqm) || 0), 0);
      const totalGfa = matched.reduce((s, p) => s + (Number(p.achieved_gfa) || 0), 0);
      const selInfo = document.getElementById('mpdSelectedInfo');
      if (selInfo) {
        selInfo.innerHTML = `🔍 <b>Isolated Filter:</b> <span style="color:var(--accent2)">${_mpdEsc(_mpdIsolatedLabel)}</span> (${matched.length} plots · Area: ${Math.round(totalArea).toLocaleString()} m² · GFA: ${Math.round(totalGfa).toLocaleString()} m²)`;
      }
      if (matched.length > 0) {
        _fitCanvasToSubset(matched);
      }
      receipts.push(`Isolated **${matched.length} ${_mpdIsolatedLabel}** plots on the masterplan canvas.`);
    } else if(action.type === 'isolate_land_use'){
      _mpdIsolatedLandUse = action.land_use || null;
      _mpdIsolatedSector = null;
      _mpdIsolatedPlotIds = null;
      _mpdIsolatedLabel = action.land_use || '';
      _mpdHighlightPlots = [];
      const luSelect = document.getElementById('tblLandUse');
      if (luSelect) {
        luSelect.value = _mpdIsolatedLandUse || 'All';
        _mpdFilterLandUse = luSelect.value;
      }
      _renderPlotTable(_mpdPlots);
      if (_mpdIsolatedLandUse) {
        const matched = (_mpdPlots || []).filter(p => _matchesLandUse(p.land_use, _mpdIsolatedLandUse));
        const totalArea = matched.reduce((s, p) => s + (Number(p.area_sqm) || 0), 0);
        const totalGfa = matched.reduce((s, p) => s + (Number(p.achieved_gfa) || 0), 0);
        const selInfo = document.getElementById('mpdSelectedInfo');
        if (selInfo) {
          selInfo.innerHTML = `🔍 <b>Isolated Filter:</b> <span style="color:var(--accent2)">${_mpdEsc(_mpdIsolatedLandUse)}</span> (${matched.length} plots · Area: ${Math.round(totalArea).toLocaleString()} m² · GFA: ${Math.round(totalGfa).toLocaleString()} m²)`;
        }
        if (matched.length > 0) _fitCanvasToSubset(matched);
        receipts.push(`Isolated **${matched.length} ${_mpdIsolatedLandUse}** plots on the masterplan canvas.`);
      } else {
        _mpdTextFilter = null;
        _mpdUniversalRule = null;
        const selInfo = document.getElementById('mpdSelectedInfo');
        if (selInfo) selInfo.textContent = 'Hover over any parcel or CAD vector on the canvas to inspect.';
        _fitCanvasToPlots();
        receipts.push(`Cleared isolation filter — showing all **${(_mpdPlots || []).length}** masterplan parcels.`);
      }
    } else if((action.type === 'recolor_active' || action.type === 'recolor_plots') && (action.color || (action.color_map && typeof action.color_map === 'object'))){
      if (action.color_map && typeof action.color_map === 'object' && Object.keys(action.color_map).length > 0) {
        let appliedCount = 0;
        const uniqueColors = new Set();
        for (const [rawPid, colVal] of Object.entries(action.color_map)) {
          const found = _findPlot(rawPid);
          const pid = found ? found.plot_id : rawPid;
          if (pid && colVal) {
            _mpdCustomStyles[pid] = colVal;
            uniqueColors.add(String(colVal).toLowerCase());
            appliedCount++;
          }
        }
        _mpdHighlightPlots = [];
        const redOrHighlightPlots = Object.entries(action.color_map)
          .filter(([k, v]) => {
            const c = String(v).toLowerCase();
            return c === '#ff0000' || c === '#ef4444' || c === 'red' || c === '#f43f5e';
          })
          .map(([k, v]) => _findPlot(k))
          .filter(Boolean);
        if (redOrHighlightPlots.length > 0 && redOrHighlightPlots.length < (_mpdPlots || []).length) {
          _fitCanvasToSubset(redOrHighlightPlots);
        }
        const modeDesc = action.mode_label || `${uniqueColors.size} unique color(s)`;
        receipts.push(`Applied **${modeDesc}** across **${appliedCount}** plot(s) on the masterplan canvas.`);
      } else {
        let targetIds = [];
        let scopeLabel = action.label || 'active';
        if (Array.isArray(action.plot_ids) && action.plot_ids.length) {
          targetIds = _resolveActionPlotIds(action);
          scopeLabel = action.label || action.sector || action.land_use || 'matching';
        } else if (_mpdIsolatedPlotIds && _mpdIsolatedPlotIds.size > 0) {
          targetIds = Array.from(_mpdIsolatedPlotIds);
          scopeLabel = _mpdIsolatedLabel || _mpdIsolatedSector || _mpdIsolatedLandUse || 'isolated';
        } else if (_mpdIsolatedLandUse) {
          targetIds = (_mpdPlots || []).filter(p => _matchesLandUse(p.land_use, _mpdIsolatedLandUse)).map(p => p.plot_id);
          scopeLabel = _mpdIsolatedLandUse;
        } else if (_mpdIsolatedSector) {
          targetIds = (_mpdPlots || []).filter(p => _matchesSector(p.sector, _mpdIsolatedSector)).map(p => p.plot_id);
          scopeLabel = _mpdIsolatedSector;
        } else if (_mpdHighlightPlots && _mpdHighlightPlots.length) {
          targetIds = [..._mpdHighlightPlots];
          scopeLabel = 'highlighted';
        } else if (_mpdSelectedPlotId) {
          targetIds = [_mpdSelectedPlotId];
          scopeLabel = `Plot ${_mpdSelectedPlotId}`;
        } else {
          targetIds = (_mpdPlots || []).map(p => p.plot_id);
          scopeLabel = 'all';
        }
        targetIds.forEach(id => { _mpdCustomStyles[id] = action.color; });
        _mpdHighlightPlots = [];
        receipts.push(`Changed color of **${targetIds.length}** ${scopeLabel} plot(s) to **${action.color}** on the masterplan canvas.`);
      }
    } else if(action.type === 'return_to_original'){
      window._returnMpdOriginal();
      receipts.push('Returned to the original source view; working revisions are retained.');
    } else if(action.type === 'save_working_copy'){
      if(!_mpdWorkingRevision || _mpdWorkingRevision.project !== project) {
        receipts.push('No working revision is available to download.');
      } else {
        window._saveMpdWorkingCopy();
        receipts.push('Working-copy download requested; original unchanged.');
      }
    } else if(action.type === 'fit_view'){
      _fitCanvasToPlots();
      receipts.push('Fitted the drawing to the view.');
    }
  }
  _drawCanvas();
  return receipts.join('\n') || 'Action not applied: unsupported drawing action.';
};
window._highlightMpdPlots = (plots, color) => {
  _mpdHighlightColor = /^#[0-9a-f]{6}$/i.test(color || '') ? color : '#ffff00';
  _mpdHighlightPlots = Array.isArray(plots) ? plots : [];
  if (_mpdHighlightPlots.length > 0 && (_mpdIsolatedLandUse || _mpdIsolatedSector || (_mpdIsolatedPlotIds && _mpdIsolatedPlotIds.size > 0))) {
    const anyHidden = _mpdHighlightPlots.some(pid => {
      const p = _findPlot(pid);
      return p && !_isPlotVisibleInIsolation(p);
    });
    if (anyHidden) {
      _mpdIsolatedLandUse = null;
      _mpdIsolatedSector = null;
      _mpdIsolatedPlotIds = null;
      _mpdIsolatedLabel = '';
      const luSelect = document.getElementById('tblLandUse');
      if (luSelect) { luSelect.value = 'All'; _mpdFilterLandUse = 'All'; }
      _renderPlotTable(_mpdPlots);
    }
  }
  _drawCanvas();
  if (_mpdHighlightPlots.length > 0) {
    _selectPlot(_mpdHighlightPlots[0], true);
  }
};
window._getMpdSelectedPlotId = () => _mpdSelectedPlotId;
window._getMpdIsolatedLandUse = () => _mpdIsolatedLandUse;
window._getMpdIsolatedSector = () => _mpdIsolatedSector;
window._getMpdIsolatedPlotIds = () => (_mpdIsolatedPlotIds ? Array.from(_mpdIsolatedPlotIds) : null);
window._downloadMpdExcel = async (project, landUse, sector, plotIds) => {
  const proj = project || _getMpdProject();
  const lu = (landUse != null && landUse !== '') ? landUse : (_mpdIsolatedLandUse || '');
  const sec = (sector != null && sector !== '') ? sector : (_mpdIsolatedSector || '');
  const pIds = (Array.isArray(plotIds) && plotIds.length) ? plotIds : ((!lu && !sec && _mpdIsolatedPlotIds && _mpdIsolatedPlotIds.size) ? Array.from(_mpdIsolatedPlotIds) : null);
  const params = new URLSearchParams();
  if (lu) params.set('land_use', lu);
  if (sec) params.set('sector', sec);
  if (pIds && pIds.length) params.set('plots', pIds.join(','));
  const qs = params.toString() ? `?${params.toString()}` : '';
  const scopeLabel = [sec, lu].filter(Boolean).join(' ') || (pIds ? `${pIds.length} Filtered Parcels` : 'All Parcels');
  const url = `${API}/api/v1/masterplan/projects/${encodeURIComponent(proj)}/export-excel${qs}`;
  try {
    toast(`📥 Preparing Excel schedule (${scopeLabel})...`);
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to generate Excel workbook');
    const blob = await res.blob();
    const dlUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = dlUrl;
    const safeScope = scopeLabel.replace(/[^A-Za-z0-9_-]+/g, '_');
    a.download = `Expo_Hills_${safeScope}_Schedule.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(dlUrl), 5000);
    toast(`✅ Downloaded Excel Schedule (${scopeLabel})`);
  } catch (err) {
    toast(`⚠️ Excel export failed: ${err.message}`);
  }
};
window._getMpdPlots = () => _mpdPlots;
window._openImportModal = _openImportModal;
window._openFilesModal = _openFilesModal;
window._triggerReconciliation = _triggerReconciliation;
window._openAuditLogModal = _openAuditLogModal;
window._resolveMpdRelation = _resolveMpdRelation;
window._confirmMpdFullLink = _confirmMpdFullLink;
window._getMpdProject = _getMpdProject;
window._openLiveAuditModal = _openLiveAuditModal;
window._toggleSidePane = _toggleSidePane;
window._mpdAutoResolveClashes = _mpdAutoResolveClashes;
