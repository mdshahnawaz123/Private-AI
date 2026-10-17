/**
 * PdfCraft Studio - Local PDF Intelligence & Workbench for Expo Design AI.
 * Clean-room PDF engineering workbench inspired by storytold/pdfcraft (pure Rust PDF re-implementation).
 * 
 * Features:
 * - 100% Offline & Local: zero network dependencies, atomic safe saves, complete data privacy
 * - High-fidelity Deep Zoom Page Rendering (crisp subpixel typography at any magnification)
 * - Card-Based Page Organizer: visual reordering, rotation (90/180/270), duplication, deletion, blank pages
 * - Search-as-you-Type: reading-order text search with exact bounding boxes and snippet jumping
 * - Document Bookmarks & Outline Tree navigation
 * - Vector Markups & Comments: text highlights, rectangular boxes, sticky notes
 * - Customizable Watermarks: DRAFT, CONFIDENTIAL, APPROVED, REVIEW COPY, and custom stamps
 * - Industry-standard AES-256 Encryption & Permission Locking
 * - Merge & Combine multiple PDFs and Split by page ranges
 * - Generative AI Bridge: render pages directly into AI Design Studio for concept visualization
 */

let _pdfState = {
  docId: null,
  filename: 'No Document Loaded',
  info: null,
  currentPage: 1,
  totalPages: 1,
  zoom: 1.25,
  viewMode: 'reader', // 'reader' or 'organizer'
  activeTool: 'select', // 'select', 'pan', 'highlight', 'rect', 'note'
  leftTab: 'pages', // 'pages', 'outline', 'search', 'properties'
  searchQuery: '',
  searchResults: [],
  selectedSearchIndex: -1,
  organizerPages: [], // local working copy for card-based organizer
  annotations: [],
  isLoading: false,
  isDragging: false,
  panX: 0,
  panY: 0,
  startX: 0,
  startY: 0,
  pageRenderCache: new Map(),
  markups: [], // local session markups [{page, type, rect, content, color}]
  aiChatHistory: [], // [{role: 'user'|'assistant', text, citedPages, model, isVision}]
  aiVisionMode: false,
  aiIsThinking: false,
  auditData: null,
  auditHighlights: [],
  measureScale: '1:100',
  measureUnit: 'm',
  measurePoints: [],
  measurements: []
};

/* ==========================================================================
   RENDER PDFCRAFT WORKSPACE UI
   ========================================================================== */
function renderPdfCraftWorkspace(container) {
  container.innerHTML = `
    <div class="pdf-workspace-root">
      <!-- TOP RIBBON TOOLBAR -->
      <div class="pdf-ribbon">
        <!-- FILE & STORAGE -->
        <div class="pdf-ribbon-group">
          <div class="pdf-group-title">FILE & STORAGE</div>
          <div class="pdf-group-btns">
            <button class="pdf-btn primary" id="pdfOpenProjectBtn" title="Open PDF from current project documents">
              <svg class="ico" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <span>Project PDF</span>
            </button>

            <button class="pdf-btn" id="pdfUploadBtn" title="Upload local PDF from disk">
              <svg class="ico" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              <span>Upload</span>
            </button>
            <input type="file" id="pdfFileInput" accept=".pdf" style="display:none">

            <div class="pdf-dropdown-wrap">
              <button class="pdf-btn" id="pdfSamplesBtn" title="Load architectural & masterplan sample documents">
                <svg class="ico" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/></svg>
                <span>Samples ▼</span>
              </button>
              <div class="pdf-dropdown-menu" id="pdfSamplesMenu" style="display:none">
                <a href="javascript:void(0)" data-sample="sample_expo_masterplan_spec">🏛️ Expo Hills Masterplan &amp; Zoning Spec</a>
                <a href="javascript:void(0)" data-sample="sample_architectural_brief">📐 Tower Architectural &amp; Egress Brief</a>
                <a href="javascript:void(0)" data-sample="sample_structural_calc">🏗️ Concrete Core &amp; Column Seismic Calc</a>
              </div>
            </div>

            <button class="pdf-btn" id="pdfSaveProjectBtn" title="Save modified document into project folder">
              <svg class="ico" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              <span>Save</span>
            </button>

            <button class="pdf-btn" id="pdfExportBtn" title="Download modified PDF file">
              <svg class="ico" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              <span>Export</span>
            </button>
          </div>
        </div>

        <div class="pdf-ribbon-sep"></div>

        <!-- VIEW & CARD ORGANIZER -->
        <div class="pdf-ribbon-group">
          <div class="pdf-group-title">VIEW &amp; ORGANIZER</div>
          <div class="pdf-group-btns">
            <button class="pdf-btn on" id="pdfViewReaderBtn" title="Deep Zoom Reading View">
              <svg class="ico" viewBox="0 0 24 24"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
              <span>Reader</span>
            </button>

            <button class="pdf-btn" id="pdfViewOrganizerBtn" title="Visual Card-Based Page Organizer (Reorder, Rotate, Delete, Duplicate)">
              <svg class="ico" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
              <span>Organizer Cards</span>
            </button>

            <div class="pdf-zoom-control">
              <button class="pdf-icon-btn" id="pdfZoomOutBtn" title="Zoom Out (-)">-</button>
              <select id="pdfZoomSelect" class="pdf-select" title="Deep Zoom Level">
                <option value="0.75">75%</option>
                <option value="1.0">100%</option>
                <option value="1.25" selected>125%</option>
                <option value="1.5">150%</option>
                <option value="2.0">200%</option>
                <option value="3.0">300% (Crisp)</option>
              </select>
              <button class="pdf-icon-btn" id="pdfZoomInBtn" title="Zoom In (+)">+</button>
              <button class="pdf-btn" id="pdfFitWidthBtn" title="Fit to Viewport Width">Fit Width</button>
              <button class="pdf-btn" id="pdfRotatePageBtn" title="Rotate Current Page 90° Clockwise">
                <svg class="ico" viewBox="0 0 24 24"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                <span>90°</span>
              </button>
            </div>
          </div>
        </div>

        <div class="pdf-ribbon-sep"></div>

        <!-- MARKUP & ANNOTATIONS -->
        <div class="pdf-ribbon-group">
          <div class="pdf-group-title">MARKUP &amp; TOOLS</div>
          <div class="pdf-group-btns">
            <button class="pdf-tool-btn on" data-tool="select" title="Select / Cursor Tool"><svg class="ico" viewBox="0 0 24 24"><path d="M3 3l7 18 3-7 7-3L3 3z"/></svg><span>Select</span></button>
            <button class="pdf-tool-btn" data-tool="pan" title="Hand / Pan Viewport"><svg class="ico" viewBox="0 0 24 24"><path d="M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg><span>Pan</span></button>
            <button class="pdf-tool-btn" data-tool="highlight" title="Text Highlight Markup"><svg class="ico" viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg><span>Highlight</span></button>
            <button class="pdf-tool-btn" data-tool="rect" title="Rectangle Markup Box"><svg class="ico" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/></svg><span>Box</span></button>
            <button class="pdf-tool-btn" data-tool="note" title="Sticky Comment Note"><svg class="ico" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><span>Note</span></button>
            <button class="pdf-tool-btn" data-tool="measure-dist" title="Measure Distance (Calibrated 2D)"><svg class="ico" viewBox="0 0 24 24"><path d="M2 17l10 5 10-5M2 12l10 5 10-5M12 2L2 7l10 5 10-5-10-5z"/></svg><span>Distance</span></button>
            <button class="pdf-tool-btn" data-tool="measure-area" title="Measure Polygon Area (Calibrated 2D)"><svg class="ico" viewBox="0 0 24 24"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polygon points="2 17 12 22 22 17"/></svg><span>Area</span></button>
            <button class="pdf-btn" id="pdfWatermarkModalBtn" title="Stamp Watermark across document">
              <svg class="ico" viewBox="0 0 24 24"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>
              <span>Watermark</span>
            </button>
          </div>
        </div>

        <div class="pdf-ribbon-sep"></div>

        <!-- OPERATIONS & AI BRIDGE -->
        <div class="pdf-ribbon-group" style="margin-left:auto">
          <div class="pdf-group-title">OPERATIONS &amp; AI STUDIO</div>
          <div class="pdf-group-btns">
            <button class="pdf-btn" id="pdfAuditBtn" title="Audit Redactions (storytold/pdfcraft crates/audit)" style="border:1px solid rgba(239,68,68,0.45);background:rgba(239,68,68,0.12);color:#fca5a5;font-weight:700">
              <svg class="ico" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              <span>🛡️ Audit Redactions</span>
            </button>

            <button class="pdf-btn" id="pdfStatsBtn" title="Document Statistics &amp; Word Count (pdfcraft text_word_count)">
              <svg class="ico" viewBox="0 0 24 24"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
              <span>📊 Stats</span>
            </button>

            <button class="pdf-btn" id="pdfMergeModalBtn" title="Combine multiple PDF documents into one">
              <svg class="ico" viewBox="0 0 24 24"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/><path d="M12 8v8M8 12h8"/></svg>
              <span>Merge</span>
            </button>

            <button class="pdf-btn" id="pdfSplitModalBtn" title="Split document by page ranges">
              <svg class="ico" viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>
              <span>Split</span>
            </button>

            <button class="pdf-btn" id="pdfSecurityModalBtn" title="AES-256 Security &amp; Permissions">
              <svg class="ico" viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <span>Protect</span>
            </button>

            <button class="pdf-btn ai" id="pdfAskAiBtn" title="Ask Local AI (qwen3.5:9b) questions grounded in this PDF" style="background:linear-gradient(135deg,rgba(47,107,255,0.22),rgba(139,92,246,0.28));border:1px solid rgba(139,92,246,0.5);font-weight:700">
              <svg class="ico" viewBox="0 0 24 24"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><circle cx="12" cy="12" r="9"/></svg>
              <span>✨ Ask Local AI</span>
            </button>

            <button class="pdf-btn ai" id="pdfRenderAiStudioBtn" title="Render page into AI Design Studio for 3D photorealistic concept generation">
              <svg class="ico" viewBox="0 0 24 24"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><circle cx="12" cy="12" r="9"/></svg>
              <span>🎨 Render in AI Studio</span>
            </button>

            <button class="pdf-btn ghost" id="pdfEngineInfoBtn" title="View storytold/pdfcraft Architecture &amp; Clean-Room Info">
              <svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
              <span>PdfCraft Engine</span>
            </button>
          </div>
        </div>
      </div>

      <!-- MAIN CONTENT WORKSPACE -->
      <div class="pdf-center-area">
        <!-- LEFT SIDEBAR -->
        <div class="pdf-sidebar" id="pdfSidebar">
          <div class="pdf-sidebar-tabs">
            <button class="pdf-tab-btn on" data-tab="pages" title="Page Thumbnails">📑 Pages</button>
            <button class="pdf-tab-btn" data-tab="outline" title="Bookmarks Outline">🔖 Outline</button>
            <button class="pdf-tab-btn" data-tab="search" title="Search Text">🔍 Search</button>
            <button class="pdf-tab-btn" data-tab="audit" title="Faux-Redaction Security Audit (pdfcraft-audit)" style="color:#ef4444;font-weight:700">🛡️ Audit</button>
            <button class="pdf-tab-btn" data-tab="measure" title="2D Calibrated Measurements (pdfcraft-measure)" style="color:#38bdf8;font-weight:700">📐 Measure</button>
            <button class="pdf-tab-btn" data-tab="ai" title="Ask Local AI (qwen3.5:9b / vision)" style="color:var(--accent2);font-weight:700">✨ Ask AI</button>
            <button class="pdf-tab-btn" data-tab="properties" title="Document Properties">ℹ️ Info</button>
          </div>

          <div class="pdf-sidebar-content" id="pdfSidebarContent">
            <!-- Dynamic content loaded by _renderSidebarContent -->
          </div>
        </div>

        <!-- CENTER STAGE VIEWPORT -->
        <div class="pdf-viewport-wrap" id="pdfViewportWrap">
          <!-- READER VIEW (DEEP ZOOM) -->
          <div class="pdf-reader-view" id="pdfReaderView">
            <div class="pdf-page-container" id="pdfPageContainer">
              <img id="pdfPageImage" class="pdf-page-img" alt="PDF Page View" style="display:none">
              <div id="pdfMarkupOverlay" class="pdf-markup-overlay"></div>
            </div>

            <!-- FLOATING PAGE NAVIGATION PILL -->
            <div class="pdf-nav-pill" id="pdfNavPill">
              <button class="pdf-pill-btn" id="pdfPrevPageBtn" title="Previous Page (Left Arrow)">◀</button>
              <span id="pdfPageIndicator">Page 1 of 1</span>
              <button class="pdf-pill-btn" id="pdfNextPageBtn" title="Next Page (Right Arrow)">▶</button>
            </div>
          </div>

          <!-- CARD-BASED PAGE ORGANIZER (storytold/pdfcraft clean-room visual workbench) -->
          <div class="pdf-organizer-view" id="pdfOrganizerView" style="display:none">
            <div class="pdf-organizer-toolbar">
              <div style="font-weight:700;font-size:13px;color:var(--text);display:flex;align-items:center;gap:8px">
                <svg class="ico" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                Card-Based Page Workbench (<span id="pdfOrgCount">0</span> Pages)
              </div>
              <div style="margin-left:auto;display:flex;gap:8px">
                <button class="pdf-btn" id="pdfOrgInsertBlankBtn">+ Insert Blank Page</button>
                <button class="pdf-btn" id="pdfOrgResetBtn">Reset Changes</button>
                <button class="pdf-btn primary" id="pdfOrgApplyBtn">✓ Apply &amp; Save Order</button>
              </div>
            </div>
            <div class="pdf-cards-grid" id="pdfCardsGrid">
              <!-- Page cards dynamically rendered here -->
            </div>
          </div>

          <!-- LOADING OVERLAY -->
          <div class="pdf-loading-overlay" id="pdfLoadingOverlay" style="display:none">
            <div class="pdf-spinner"></div>
            <div id="pdfLoadingText" style="font-size:13px;font-weight:600;color:var(--text)">Loading document in PdfCraft...</div>
            <div id="pdfLoadingSub" style="font-size:11px;color:var(--muted)">Extracting vector glyphs, typography &amp; layout...</div>
          </div>
        </div>
      </div>

      <!-- STATUS BAR -->
      <div class="pdf-statusbar">
        <div class="pdf-sb-item" id="pdfDocNameLabel">📄 No document loaded</div>
        <div class="pdf-sb-sep"></div>
        <div class="pdf-sb-item" id="pdfPageDimLabel">Size: —</div>
        <div class="pdf-sb-sep"></div>
        <div class="pdf-sb-item" id="pdfSecurityLabel">Security: None</div>
        <div class="pdf-sb-sep"></div>
        <div class="pdf-sb-item" id="pdfZoomLabel">Zoom: 125%</div>
        <div style="margin-left:auto;display:flex;align-items:center;gap:12px">
          <span style="font-size:11px;color:var(--accent2);font-weight:600">PdfCraft Pure Offline Engine v0.3.2</span>
        </div>
      </div>
    </div>
  `;

  _initPdfCraftStyles();
  _bindPdfEvents();

  // Load pending project PDF, previously opened PDF, or default architectural sample
  if (window._pdfPendingDoc) {
    const p = window._pdfPendingDoc;
    window._pdfPendingDoc = null;
    openPdfProjectDocument(p.filename, p.relPath, p.project, p.targetPage, p.metadata);
  } else if (_pdfState.docId && _pdfState.info) {
    _applyLoadedDocument(_pdfState.docId, _pdfState.filename, _pdfState.info, _pdfState.relPath, _pdfState.metadata);
  } else if (!window._pdfSkipDefaultSample) {
    _loadSampleDocument('sample_expo_masterplan_spec');
  }
}

/* ==========================================================================
   CSS STYLING (MATCHING EXPO DESIGN AI UI TOKENS)
   ========================================================================== */
function _initPdfCraftStyles() {
  if (document.getElementById('pdfcraft-styles')) return;
  const style = document.createElement('style');
  style.id = 'pdfcraft-styles';
  style.textContent = `
    .pdf-workspace-root {
      display: flex;
      flex-direction: column;
      width: 100%;
      height: 100%;
      background: #090d16;
      color: var(--text, #e2e8f0);
      font-family: Inter, -apple-system, sans-serif;
      overflow: hidden;
    }
    .pdf-ribbon {
      display: flex;
      align-items: center;
      background: #0d1424;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      padding: 6px 12px;
      gap: 10px;
      user-select: none;
      overflow-x: auto;
      min-height: 54px;
    }
    .pdf-ribbon-group {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .pdf-group-title {
      font-size: 9.5px;
      font-weight: 700;
      color: var(--muted, #64748b);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .pdf-group-btns {
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .pdf-ribbon-sep {
      width: 1px;
      height: 36px;
      background: var(--border, rgba(255,255,255,0.08));
      margin: 0 4px;
    }
    .pdf-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      background: var(--surface2, #162035);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: var(--r-sm, 6px);
      color: var(--text, #e2e8f0);
      font-size: 11.5px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .pdf-btn:hover {
      background: rgba(47, 107, 255, 0.15);
      border-color: rgba(47, 107, 255, 0.4);
      color: #fff;
    }
    .pdf-btn.primary {
      background: var(--accent2, #2f6bff);
      border-color: var(--accent2, #2f6bff);
      color: #fff;
    }
    .pdf-btn.primary:hover {
      background: #1e56e0;
    }
    .pdf-btn.ai {
      background: linear-gradient(135deg, rgba(168,85,247,0.25), rgba(47,107,255,0.25));
      border-color: rgba(168,85,247,0.5);
      color: #e9d5ff;
    }
    .pdf-btn.ai:hover {
      background: linear-gradient(135deg, rgba(168,85,247,0.4), rgba(47,107,255,0.4));
      color: #fff;
    }
    .pdf-btn.ghost {
      background: transparent;
      border-color: transparent;
      color: var(--muted, #94a3b8);
    }
    .pdf-btn.ghost:hover {
      background: rgba(255,255,255,0.06);
      color: #fff;
    }
    .pdf-btn.on {
      background: rgba(47, 107, 255, 0.22);
      border-color: var(--accent2, #2f6bff);
      color: #38bdf8;
    }
    .pdf-tool-btn {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 5px 8px;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 6px;
      color: var(--muted, #94a3b8);
      font-size: 11.5px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }
    .pdf-tool-btn:hover {
      background: rgba(255,255,255,0.06);
      color: #fff;
    }
    .pdf-tool-btn.on {
      background: rgba(47,107,255,0.2);
      border-color: rgba(47,107,255,0.45);
      color: #38bdf8;
    }
    .pdf-zoom-control {
      display: inline-flex;
      align-items: center;
      background: var(--surface2, #162035);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: 6px;
      padding: 2px 4px;
      gap: 3px;
    }
    .pdf-icon-btn {
      background: transparent;
      border: none;
      color: var(--text, #cbd5e1);
      width: 24px;
      height: 24px;
      border-radius: 4px;
      cursor: pointer;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .pdf-icon-btn:hover {
      background: rgba(255,255,255,0.1);
      color: #fff;
    }
    .pdf-select {
      background: transparent;
      border: none;
      color: var(--text, #fff);
      font-size: 11px;
      font-weight: 600;
      padding: 2px 4px;
      cursor: pointer;
      outline: none;
    }
    .pdf-select option {
      background: #0d1424;
      color: #fff;
    }
    .pdf-dropdown-wrap {
      position: relative;
      display: inline-block;
    }
    .pdf-dropdown-menu {
      position: absolute;
      top: 100%;
      left: 0;
      margin-top: 4px;
      background: #0f172a;
      border: 1px solid var(--border, rgba(255,255,255,0.15));
      border-radius: 8px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
      z-index: 1000;
      min-width: 250px;
      padding: 4px;
    }
    .pdf-dropdown-menu a {
      display: block;
      padding: 8px 12px;
      font-size: 11.5px;
      color: var(--text, #e2e8f0);
      text-decoration: none;
      border-radius: 6px;
    }
    .pdf-dropdown-menu a:hover {
      background: rgba(47,107,255,0.2);
      color: #fff;
    }
    .pdf-center-area {
      display: flex;
      flex: 1;
      overflow: hidden;
      position: relative;
    }
    .pdf-sidebar {
      width: 320px;
      background: #0d1424;
      border-right: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    .pdf-sidebar-tabs {
      display: flex;
      overflow-x: auto;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      background: #070b15;
      white-space: nowrap;
      scrollbar-width: none;
    }
    .pdf-sidebar-tabs::-webkit-scrollbar {
      display: none;
    }
    .pdf-tab-btn {
      flex: 1;
      padding: 8px 6px;
      font-size: 10.5px;
      font-weight: 600;
      color: var(--muted, #64748b);
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      cursor: pointer;
      white-space: nowrap;
    }
    .pdf-tab-btn:hover {
      color: #fff;
    }
    .pdf-tab-btn.on {
      color: var(--accent2, #38bdf8);
      border-bottom-color: var(--accent2, #38bdf8);
      background: rgba(47,107,255,0.05);
    }
    .pdf-sidebar-content {
      flex: 1;
      overflow-y: auto;
      padding: 10px;
    }
    .pdf-thumb-card {
      background: var(--surface2, #162035);
      border: 1px solid var(--border, rgba(255,255,255,0.1));
      border-radius: 6px;
      margin-bottom: 10px;
      padding: 6px;
      cursor: pointer;
      transition: all 0.15s ease;
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    .pdf-thumb-card:hover {
      border-color: rgba(47,107,255,0.4);
      background: #1a2742;
    }
    .pdf-thumb-card.active {
      border-color: var(--accent2, #2f6bff);
      box-shadow: 0 0 0 2px rgba(47,107,255,0.35);
    }
    .pdf-thumb-img {
      max-width: 100%;
      height: auto;
      border-radius: 4px;
      background: #fff;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .pdf-thumb-footer {
      width: 100%;
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
      font-size: 10.5px;
      color: var(--muted, #94a3b8);
      font-weight: 600;
    }
    .pdf-viewport-wrap {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      position: relative;
      background: #070a12;
    }
    .pdf-reader-view {
      flex: 1;
      overflow: auto;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      padding: 24px;
      position: relative;
    }
    .pdf-page-container {
      position: relative;
      box-shadow: 0 14px 40px rgba(0,0,0,0.6);
      border-radius: 4px;
      background: #fff;
      user-select: text;
    }
    .pdf-page-img {
      display: block;
      width: 100%;
      height: auto;
      border-radius: 4px;
    }
    .pdf-markup-overlay {
      position: absolute;
      inset: 0;
      pointer-events: auto;
    }
    .pdf-nav-pill {
      position: absolute;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(13, 20, 36, 0.9);
      border: 1px solid var(--border, rgba(255,255,255,0.15));
      backdrop-filter: blur(8px);
      padding: 6px 14px;
      border-radius: 20px;
      display: flex;
      align-items: center;
      gap: 12px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      font-size: 12px;
      font-weight: 600;
      z-index: 100;
    }
    .pdf-pill-btn {
      background: transparent;
      border: none;
      color: #fff;
      cursor: pointer;
      font-size: 13px;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .pdf-pill-btn:hover {
      background: rgba(255,255,255,0.15);
    }
    .pdf-organizer-view {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      padding: 16px;
    }
    .pdf-organizer-toolbar {
      display: flex;
      align-items: center;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
    }
    .pdf-cards-grid {
      flex: 1;
      overflow-y: auto;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 16px;
      padding: 16px 4px;
    }
    .pdf-org-card {
      background: var(--surface2, #162035);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: 8px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      transition: all 0.15s ease;
      position: relative;
    }
    .pdf-org-card:hover {
      border-color: rgba(47,107,255,0.5);
      box-shadow: 0 8px 24px rgba(0,0,0,0.35);
    }
    .pdf-org-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 11px;
      font-weight: 700;
      color: var(--text, #e2e8f0);
    }
    .pdf-org-thumb-wrap {
      background: #000;
      border-radius: 4px;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 200px;
    }
    .pdf-org-card-actions {
      display: flex;
      justify-content: space-between;
      gap: 4px;
    }
    .pdf-org-btn {
      flex: 1;
      padding: 4px 6px;
      font-size: 10.5px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 4px;
      color: var(--text, #cbd5e1);
      cursor: pointer;
      text-align: center;
    }
    .pdf-org-btn:hover {
      background: rgba(47,107,255,0.2);
      color: #fff;
    }
    .pdf-org-btn.danger:hover {
      background: rgba(239,68,68,0.25);
      color: #f87171;
    }
    .pdf-statusbar {
      display: flex;
      align-items: center;
      height: 26px;
      background: #080c16;
      border-top: 1px solid var(--border, rgba(255,255,255,0.08));
      padding: 0 12px;
      font-size: 11px;
      color: var(--muted, #64748b);
      user-select: none;
    }
    .pdf-sb-item {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .pdf-sb-sep {
      width: 1px;
      height: 14px;
      background: var(--border, rgba(255,255,255,0.08));
      margin: 0 10px;
    }
    .pdf-loading-overlay {
      position: absolute;
      inset: 0;
      background: rgba(9, 13, 22, 0.85);
      backdrop-filter: blur(6px);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      z-index: 500;
    }
    .pdf-spinner {
      width: 32px;
      height: 32px;
      border: 3px solid rgba(47,107,255,0.2);
      border-top-color: var(--accent2, #2f6bff);
      border-radius: 50%;
      animation: pdfSpin 0.8s linear infinite;
    }
    @keyframes pdfSpin {
      to { transform: rotate(360deg); }
    }
    .pdf-modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(5px);
      z-index: 99999;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .pdf-modal-box {
      background: #0d1424;
      border: 1px solid var(--border, rgba(255,255,255,0.15));
      border-radius: 12px;
      box-shadow: 0 18px 45px rgba(0,0,0,0.75);
      padding: 22px;
      width: 600px;
      max-width: 95vw;
      max-height: 88vh;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    @keyframes pdfAiPulse {
      0%, 100% { opacity: 0.3; transform: scale(0.9); }
      50% { opacity: 1; transform: scale(1.1); }
    }
  `;
  document.head.appendChild(style);
}

/* ==========================================================================
   EVENT WIRING & WORKSPACE LOGIC
   ========================================================================== */
function _bindPdfEvents() {
  const fileInput = document.getElementById('pdfFileInput');
  const uploadBtn = document.getElementById('pdfUploadBtn');
  if (uploadBtn && fileInput) {
    uploadBtn.onclick = () => fileInput.click();
    fileInput.onchange = (e) => {
      if (e.target.files && e.target.files[0]) {
        _uploadPdfFile(e.target.files[0]);
      }
    };
  }

  // Open Project PDF modal
  const openProjBtn = document.getElementById('pdfOpenProjectBtn');
  if (openProjBtn) openProjBtn.onclick = _openProjectPdfsModal;

  // Samples dropdown
  const samplesBtn = document.getElementById('pdfSamplesBtn');
  const samplesMenu = document.getElementById('pdfSamplesMenu');
  if (samplesBtn && samplesMenu) {
    samplesBtn.onclick = (e) => {
      e.stopPropagation();
      samplesMenu.style.display = samplesMenu.style.display === 'none' ? 'block' : 'none';
    };
    document.addEventListener('click', () => { samplesMenu.style.display = 'none'; });
    samplesMenu.querySelectorAll('a[data-sample]').forEach(a => {
      a.onclick = () => {
        _loadSampleDocument(a.dataset.sample);
        samplesMenu.style.display = 'none';
      };
    });
  }

  // View Mode toggle
  const readerBtn = document.getElementById('pdfViewReaderBtn');
  const orgBtn = document.getElementById('pdfViewOrganizerBtn');
  const readerView = document.getElementById('pdfReaderView');
  const orgView = document.getElementById('pdfOrganizerView');

  if (readerBtn && orgBtn) {
    readerBtn.onclick = () => {
      _pdfState.viewMode = 'reader';
      readerBtn.classList.add('on');
      orgBtn.classList.remove('on');
      readerView.style.display = 'flex';
      orgView.style.display = 'none';
      _renderCurrentPage();
    };
    orgBtn.onclick = () => {
      _pdfState.viewMode = 'organizer';
      orgBtn.classList.add('on');
      readerBtn.classList.remove('on');
      orgView.style.display = 'flex';
      readerView.style.display = 'none';
      _renderOrganizerGrid();
    };
  }

  // Zoom controls
  const zoomSelect = document.getElementById('pdfZoomSelect');
  const zoomIn = document.getElementById('pdfZoomInBtn');
  const zoomOut = document.getElementById('pdfZoomOutBtn');
  const fitWidth = document.getElementById('pdfFitWidthBtn');

  if (zoomSelect) {
    zoomSelect.onchange = () => {
      _pdfState.zoom = parseFloat(zoomSelect.value);
      _renderCurrentPage();
    };
  }
  if (zoomIn) {
    zoomIn.onclick = () => {
      _pdfState.zoom = Math.min(4.0, _pdfState.zoom + 0.25);
      if (zoomSelect) zoomSelect.value = _pdfState.zoom.toFixed(2);
      _renderCurrentPage();
    };
  }
  if (zoomOut) {
    zoomOut.onclick = () => {
      _pdfState.zoom = Math.max(0.5, _pdfState.zoom - 0.25);
      if (zoomSelect) zoomSelect.value = _pdfState.zoom.toFixed(2);
      _renderCurrentPage();
    };
  }
  if (fitWidth) {
    fitWidth.onclick = () => {
      const wrap = document.getElementById('pdfViewportWrap');
      if (wrap && _pdfState.info && _pdfState.info.pages[_pdfState.currentPage - 1]) {
        const pw = _pdfState.info.pages[_pdfState.currentPage - 1].width;
        _pdfState.zoom = Math.max(0.5, Math.min(3.0, (wrap.clientWidth - 80) / pw));
        _renderCurrentPage();
      }
    };
  }

  // Rotate page
  const rotateBtn = document.getElementById('pdfRotatePageBtn');
  if (rotateBtn) {
    rotateBtn.onclick = async () => {
      await _rotateActivePage(90);
    };
  }

  // Page navigation
  const prevBtn = document.getElementById('pdfPrevPageBtn');
  const nextBtn = document.getElementById('pdfNextPageBtn');
  if (prevBtn) prevBtn.onclick = () => _goToPage(_pdfState.currentPage - 1);
  if (nextBtn) nextBtn.onclick = () => _goToPage(_pdfState.currentPage + 1);

  // Keyboard navigation
  window.addEventListener('keydown', (e) => {
    if (typeof currentDest !== 'undefined' && currentDest !== 'pdfcraft') return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'ArrowLeft') _goToPage(_pdfState.currentPage - 1);
    if (e.key === 'ArrowRight') _goToPage(_pdfState.currentPage + 1);
  });

  // Sidebar tab buttons
  document.querySelectorAll('.pdf-tab-btn').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.pdf-tab-btn').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      _pdfState.leftTab = btn.dataset.tab;
      _renderSidebarContent();
    };
  });

  // Tool buttons
  document.querySelectorAll('.pdf-tool-btn').forEach(tb => {
    tb.onclick = () => {
      document.querySelectorAll('.pdf-tool-btn').forEach(b => b.classList.remove('on'));
      tb.classList.add('on');
      _pdfState.activeTool = tb.dataset.tool;
      if (tb.dataset.tool && tb.dataset.tool.startsWith('measure')) {
        _pdfState.leftTab = 'measure';
        document.querySelectorAll('.pdf-tab-btn').forEach(b => b.classList.toggle('on', b.dataset.tab === 'measure'));
        _renderSidebarContent();
      }
    };
  });

  // Save to project
  const saveBtn = document.getElementById('pdfSaveProjectBtn');
  if (saveBtn) saveBtn.onclick = _saveToProjectModal;

  // Export PDF
  const exportBtn = document.getElementById('pdfExportBtn');
  if (exportBtn) exportBtn.onclick = () => {
    if (!_pdfState.docId) return;
    window.open(`${API}/api/v1/pdf/export?doc_id=${encodeURIComponent(_pdfState.docId)}&filename=${encodeURIComponent(_pdfState.filename)}`, '_blank');
  };

  // Audit Redactions (storytold/pdfcraft crates/audit)
  const auditBtn = document.getElementById('pdfAuditBtn');
  if (auditBtn) {
    auditBtn.onclick = () => {
      _pdfState.leftTab = 'audit';
      document.querySelectorAll('.pdf-tab-btn').forEach(b => b.classList.toggle('on', b.dataset.tab === 'audit'));
      _renderSidebarContent();
      _runRedactionAudit();
    };
  }

  // Document Statistics (pdfcraft text_word_count)
  const statsBtn = document.getElementById('pdfStatsBtn');
  if (statsBtn) statsBtn.onclick = _showDocumentStatsModal;

  // Modals
  const watermarkBtn = document.getElementById('pdfWatermarkModalBtn');
  if (watermarkBtn) watermarkBtn.onclick = _openWatermarkModal;

  const securityBtn = document.getElementById('pdfSecurityModalBtn');
  if (securityBtn) securityBtn.onclick = _openSecurityModal;

  const mergeBtn = document.getElementById('pdfMergeModalBtn');
  if (mergeBtn) mergeBtn.onclick = _openMergeModal;

  const splitBtn = document.getElementById('pdfSplitModalBtn');
  if (splitBtn) splitBtn.onclick = _openSplitModal;

  const askAiBtn = document.getElementById('pdfAskAiBtn');
  if (askAiBtn) {
    askAiBtn.onclick = () => {
      _pdfState.leftTab = 'ai';
      document.querySelectorAll('.pdf-tab-btn').forEach(b => b.classList.toggle('on', b.dataset.tab === 'ai'));
      _renderSidebarContent();
      const inp = document.getElementById('pdfAiInput');
      if (inp) inp.focus();
    };
  }

  const aiRenderBtn = document.getElementById('pdfRenderAiStudioBtn');
  if (aiRenderBtn) aiRenderBtn.onclick = _renderPageForAiStudio;

  const infoBtn = document.getElementById('pdfEngineInfoBtn');
  if (infoBtn) infoBtn.onclick = _showPdfCraftEngineModal;
}

/* ==========================================================================
   DOCUMENT LOADING & RENDERING
   ========================================================================== */

function _showLoading(text = 'Loading document...', sub = 'Extracting typography & vectors...') {
  const ol = document.getElementById('pdfLoadingOverlay');
  if (ol) {
    document.getElementById('pdfLoadingText').textContent = text;
    document.getElementById('pdfLoadingSub').textContent = sub;
    ol.style.display = 'flex';
  }
}

function _hideLoading() {
  const ol = document.getElementById('pdfLoadingOverlay');
  if (ol) ol.style.display = 'none';
}

async function _loadSampleDocument(sampleId) {
  _showLoading(`Loading sample '${sampleId}'...`, 'Clean-room pure Rust engine format');
  try {
    const res = await fetch(`${API}/api/v1/pdf/sample/${encodeURIComponent(sampleId)}`);
    if (!res.ok) throw new Error('Failed to load sample document');
    const data = await res.json();
    _applyLoadedDocument(data.doc_id, data.filename, data.info);
  } catch (err) {
    toast(`Sample load error: ${err.message}`);
  } finally {
    _hideLoading();
  }
}

async function _uploadPdfFile(file) {
  _showLoading(`Uploading ${file.name}...`, 'Opening local document session');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`${API}/api/v1/pdf/open`, { method: 'POST', body: fd });
    if (!res.ok) throw new Error('Failed to open PDF document');
    const data = await res.json();
    _applyLoadedDocument(data.doc_id, data.filename, data.info);
    toast(`✅ Opened ${file.name} in PdfCraft`);
  } catch (err) {
    toast(`Error opening file: ${err.message}`);
  } finally {
    _hideLoading();
  }
}

async function openPdfProjectDocument(filename, relPath, project, targetPage = 1, metadata = null) {
  _showLoading(`Loading ${filename}...`, 'Opening from project storage');
  const proj = project || (typeof currentProject !== 'undefined' ? currentProject : null);
  const fd = new FormData();
  if (proj) fd.append('project', proj);
  if (filename) fd.append('filename', filename);
  if (relPath) fd.append('rel', relPath);
  try {
    const res = await fetch(`${API}/api/v1/pdf/open`, { method: 'POST', body: fd });
    if (!res.ok) {
      let errDetail = 'Document open error';
      try { const errJson = await res.json(); errDetail = errJson.detail || errDetail; } catch(e){}
      throw new Error(errDetail);
    }
    const data = await res.json();
    _applyLoadedDocument(data.doc_id, data.filename, data.info, relPath, metadata || { folder: data.folder, project: data.project });
    const p = parseInt(targetPage, 10);
    if (Number.isInteger(p) && p > 1) {
      _goToPage(p);
    }
    toast(`Loaded ${filename} in PdfCraft Studio`);
  } catch (err) {
    toast(`Failed to open project document: ${err.message}`);
  } finally {
    _hideLoading();
  }
}

function _applyLoadedDocument(docId, filename, info, relPath = null, metadata = null) {
  _pdfState.docId = docId;
  _pdfState.filename = filename;
  _pdfState.relPath = relPath || filename;
  _pdfState.metadata = metadata || {};
  _pdfState.info = info;
  _pdfState.currentPage = 1;
  _pdfState.totalPages = info.page_count || 1;
  _pdfState.organizerPages = info.pages ? JSON.parse(JSON.stringify(info.pages)) : [];
  _pdfState.pageRenderCache.clear();
  _pdfState.aiChatHistory = []; // Reset local chat for newly opened document

  // Sync with App Copilot context
  if (typeof setDocContext === 'function') {
    const rev = (metadata && metadata._rev) || '';
    const fldr = (metadata && (metadata.folder || metadata.category)) || (info && info.folder) || 'Documents';
    setDocContext({
      filename: filename,
      rel: relPath || filename,
      folder: fldr,
      _rev: rev,
      ...(metadata || {})
    });
  }

  // Status bar updates
  const revStr = (metadata && metadata._rev) ? ` · Rev ${metadata._rev}` : '';
  const nameEl = document.getElementById('pdfDocNameLabel');
  if (nameEl) nameEl.textContent = `📄 ${filename}${revStr} (${info.page_count} Pages)`;
  const secEl = document.getElementById('pdfSecurityLabel');
  if (secEl) secEl.textContent = info.is_encrypted ? '🔒 AES-256 Protected' : '🔓 Unlocked (Full Access)';

  _renderSidebarContent();
  _renderCurrentPage();
  _renderOrganizerGrid();
}

async function _renderCurrentPage() {
  if (!_pdfState.docId) return;
  const pNum = _pdfState.currentPage;
  const imgEl = document.getElementById('pdfPageImage');
  const overlay = document.getElementById('pdfMarkupOverlay');
  const indicator = document.getElementById('pdfPageIndicator');
  const dimLabel = document.getElementById('pdfPageDimLabel');
  const zoomLabel = document.getElementById('pdfZoomLabel');

  if (indicator) indicator.textContent = `Page ${pNum} of ${_pdfState.totalPages}`;
  if (zoomLabel) zoomLabel.textContent = `Zoom: ${Math.round(_pdfState.zoom * 100)}%`;

  if (_pdfState.info && _pdfState.info.pages && _pdfState.info.pages[pNum - 1]) {
    const pMeta = _pdfState.info.pages[pNum - 1];
    if (dimLabel) dimLabel.textContent = `Size: ${pMeta.width} × ${pMeta.height} pt (${pMeta.is_landscape ? 'Landscape' : 'Portrait'})`;
  }

  const cacheKey = `${_pdfState.docId}_p${pNum}_z${_pdfState.zoom.toFixed(2)}`;
  let imgUrl = _pdfState.pageRenderCache.get(cacheKey);

  if (!imgUrl) {
    imgUrl = `${API}/api/v1/pdf/render-page?doc_id=${encodeURIComponent(_pdfState.docId)}&page=${pNum}&zoom=${_pdfState.zoom.toFixed(2)}&v=${Date.now()}`;
    _pdfState.pageRenderCache.set(cacheKey, imgUrl);
  }

  imgEl.src = imgUrl;
  imgEl.style.display = 'block';
  imgEl.onload = () => {
    _renderMarkupOverlay();
  };
  _renderMarkupOverlay();

  if (overlay) overlay.onclick = _handleOverlayClick;

  // Highlight active thumbnail in sidebar
  document.querySelectorAll('.pdf-thumb-card').forEach(c => {
    c.classList.toggle('active', parseInt(c.dataset.page) === pNum);
  });
}

function _goToPage(pNum) {
  if (pNum < 1 || pNum > _pdfState.totalPages) return;
  _pdfState.currentPage = pNum;
  _renderCurrentPage();
}

/* ==========================================================================
   SIDEBAR TABS: PAGES, OUTLINE, SEARCH, PROPERTIES
   ========================================================================== */

function _renderSidebarContent() {
  const content = document.getElementById('pdfSidebarContent');
  if (!content) return;

  const tab = _pdfState.leftTab;
  if (tab === 'pages') {
    if (!_pdfState.info || !_pdfState.info.pages || !_pdfState.info.pages.length) {
      content.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:30px">No pages available</div>';
      return;
    }
    content.innerHTML = _pdfState.info.pages.map(p => `
      <div class="pdf-thumb-card ${p.page_number === _pdfState.currentPage ? 'active' : ''}" data-page="${p.page_number}" onclick="_goToPage(${p.page_number})">
        <img class="pdf-thumb-img" src="${API}/api/v1/pdf/thumbnail?doc_id=${encodeURIComponent(_pdfState.docId)}&page=${p.page_number}&width=220" loading="lazy">
        <div class="pdf-thumb-footer">
          <span>Page ${p.page_number}</span>
          <span>${Math.round(p.width)}×${Math.round(p.height)}</span>
        </div>
      </div>
    `).join('');
  } else if (tab === 'outline') {
    const toc = _pdfState.info ? _pdfState.info.toc : [];
    if (!toc || !toc.length) {
      content.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:30px">No bookmarks or outline tree defined in document.</div>';
      return;
    }
    content.innerHTML = `
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:8px;text-transform:uppercase">Document Bookmarks</div>
      <div style="display:flex;flex-direction:column;gap:4px">
        ${toc.map(item => `
          <div style="padding:6px 8px;padding-left:${(item.level - 1) * 16 + 8}px;font-size:11.5px;color:var(--text);border-radius:4px;cursor:pointer;background:rgba(255,255,255,0.03)"
               onmouseover="this.style.background='rgba(47,107,255,0.15)'" onmouseout="this.style.background='rgba(255,255,255,0.03)'"
               onclick="_goToPage(${item.page})">
            🔖 ${_esc(item.title)} <span style="float:right;color:var(--muted);font-size:10px">p.${item.page}</span>
          </div>
        `).join('')}
      </div>
    `;
  } else if (tab === 'search') {
    content.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:10px">
        <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">Search as you Type</div>
        <div style="display:flex;gap:6px">
          <input type="text" id="pdfSearchInput" value="${_esc(_pdfState.searchQuery)}" placeholder="Find in document..."
                 style="flex:1;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:6px 10px;font-size:12px;color:#fff">
          <button class="pdf-btn primary" id="pdfSearchBtn" style="padding:5px 10px">Find</button>
        </div>
        <div id="pdfSearchResultsList" style="display:flex;flex-direction:column;gap:6px;max-height:450px;overflow-y:auto">
          ${_renderSearchResultsHtml()}
        </div>
      </div>
    `;
    const sInput = document.getElementById('pdfSearchInput');
    const sBtn = document.getElementById('pdfSearchBtn');
    if (sBtn) sBtn.onclick = () => _executeSearch(sInput.value);
    if (sInput) {
      sInput.onkeydown = (e) => { if (e.key === 'Enter') _executeSearch(sInput.value); };
    }
  } else if (tab === 'ai') {
    _renderAiChatContent(content);
  } else if (tab === 'properties') {
    const meta = (_pdfState.info && _pdfState.info.metadata) || {};
    const perms = (_pdfState.info && _pdfState.info.permissions) || {};
    content.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:10px;font-size:11.5px">
        <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">Document Properties</div>
        <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px">
          <div style="margin-bottom:6px"><b>Title:</b> ${_esc(meta.title || _pdfState.filename)}</div>
          <div style="margin-bottom:6px"><b>Author:</b> ${_esc(meta.author || '—')}</div>
          <div style="margin-bottom:6px"><b>Subject:</b> ${_esc(meta.subject || '—')}</div>
          <div style="margin-bottom:6px"><b>Format:</b> ${_esc(meta.format || 'PDF 1.7')}</div>
          <div style="margin-bottom:6px"><b>Encryption:</b> <span style="color:${_pdfState.info.is_encrypted ? 'var(--amber)' : 'var(--green)'}">${_esc(meta.encryption || 'None')}</span></div>
          <div><b>Pages:</b> ${_pdfState.totalPages}</div>
        </div>

        <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;margin-top:6px">Security &amp; Permissions</div>
        <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px;line-height:1.6">
          <div>${perms.can_print ? '✅' : '❌'} Printing: <b>${perms.can_print ? 'Allowed' : 'Restricted'}</b></div>
          <div>${perms.can_copy ? '✅' : '❌'} Content Copying: <b>${perms.can_copy ? 'Allowed' : 'Restricted'}</b></div>
          <div>${perms.can_modify ? '✅' : '❌'} Document Modification: <b>${perms.can_modify ? 'Allowed' : 'Restricted'}</b></div>
          <div>${perms.can_annotate ? '✅' : '❌'} Commenting &amp; Markup: <b>${perms.can_annotate ? 'Allowed' : 'Restricted'}</b></div>
        </div>
      </div>
    `;
  } else if (tab === 'audit') {
    _renderAuditTabContent(content);
  } else if (tab === 'measure') {
    _renderMeasureTabContent(content);
  }
}

function _renderAiChatContent(content) {
  const history = _pdfState.aiChatHistory || [];
  const isThinking = _pdfState.aiIsThinking || false;
  const visionMode = _pdfState.aiVisionMode || false;

  content.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;min-height:0;gap:8px">
      <!-- HEADER / MODEL STATUS -->
      <div style="background:rgba(47,107,255,0.08);border:1px solid rgba(47,107,255,0.22);border-radius:8px;padding:8px 10px;display:flex;align-items:center;justify-content:space-between">
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:6px">
            <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#10b981;box-shadow:0 0 6px #10b981"></span>
            <span>Local AI Model</span>
          </div>
          <div style="font-size:10px;color:var(--muted)">${visionMode ? 'qwen2.5vl:7b (Vision Page Analysis)' : 'qwen3.5:9b (Grounded Text &amp; Tables)'}</div>
        </div>
        <label style="display:flex;align-items:center;gap:4px;font-size:10.5px;color:var(--text);cursor:pointer" title="Enable to let local vision model visually read drawings/plans on the current page">
          <input type="checkbox" id="pdfAiVisionToggle" ${visionMode ? 'checked' : ''} style="cursor:pointer">
          <span>Vision Mode</span>
        </label>
      </div>

      <!-- QUICK PROMPT PILLS -->
      <div style="display:flex;flex-wrap:wrap;gap:4px">
        <button class="pdf-btn" style="font-size:10px;padding:3px 7px;background:rgba(255,255,255,0.04)" onclick="_askAiQuick('Summarize this document and its key architectural/engineering requirements.')">📋 Summarize</button>
        <button class="pdf-btn" style="font-size:10px;padding:3px 7px;background:rgba(255,255,255,0.04)" onclick="_askAiQuick('Explain what is on Page ' + _pdfState.currentPage + ' in detail.')">📄 Page ${_pdfState.currentPage}</button>
        <button class="pdf-btn" style="font-size:10px;padding:3px 7px;background:rgba(255,255,255,0.04)" onclick="_askAiQuick('Extract all numbers, dimensions, and table specifications.')">📊 Tables</button>
        <button class="pdf-btn" style="font-size:10px;padding:3px 7px;background:rgba(255,255,255,0.04)" onclick="_askAiQuick('List all compliance rules, fire ratings, or code requirements.')">⚖️ Compliance</button>
      </div>

      <!-- CHAT MESSAGE THREAD -->
      <div id="pdfAiMessageThread" style="flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding:4px 2px">
        ${history.length === 0 ? `
          <div style="color:var(--muted);font-size:11.5px;text-align:center;padding:26px 14px;line-height:1.6">
            <div style="font-size:24px;margin-bottom:8px">✨</div>
            <b>Ask Your Local AI Model</b>
            <p style="margin:4px 0 0 0;font-size:11px">Ask any question about <b>${_esc(_pdfState.filename)}</b>. The local model reads the exact text, tables, and dimensions offline with zero cloud transmission.</p>
          </div>
        ` : history.map((msg, i) => `
          <div style="display:flex;flex-direction:column;gap:3px;align-self:${msg.role === 'user' ? 'flex-end' : 'flex-start'};max-width:92%">
            <div style="font-size:9.5px;font-weight:700;color:var(--muted);text-transform:uppercase;margin-left:2px">
              ${msg.role === 'user' ? 'You' : `🤖 ${msg.model || 'Local AI'}`}
            </div>
            <div style="background:${msg.role === 'user' ? 'linear-gradient(135deg,#2563eb,#1d4ed8)' : '#070b15'};color:#fff;border:${msg.role === 'user' ? 'none' : '1px solid rgba(255,255,255,0.09)'};border-radius:10px;padding:8px 12px;font-size:12px;line-height:1.55;word-break:break-word">
              ${_formatAiResponseHtml(msg.text)}
            </div>
            ${(msg.citedPages && msg.citedPages.length) ? `
              <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:2px">
                ${msg.citedPages.map(p => `
                  <span onclick="_goToPage(${p})" style="font-size:10px;background:rgba(47,107,255,0.18);color:var(--accent2);border:1px solid rgba(47,107,255,0.3);border-radius:4px;padding:1px 6px;cursor:pointer;font-weight:600" title="Click to jump to Page ${p}">
                    📍 Page ${p}
                  </span>
                `).join('')}
              </div>
            ` : ''}
          </div>
        `).join('')}

        ${isThinking ? `
          <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:10px;max-width:85%">
            <div style="width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 6px var(--accent);animation:pdfAiPulse 1.2s infinite ease-in-out"></div>
            <span style="font-size:11.5px;color:var(--muted)">Local AI is analyzing document data...</span>
          </div>
        ` : ''}
      </div>

      <!-- INPUT BOX -->
      <div style="display:flex;flex-direction:column;gap:6px;border-top:1px solid rgba(255,255,255,0.08);padding-top:8px">
        <div style="display:flex;gap:6px">
          <input type="text" id="pdfAiInput" placeholder="Ask question about this PDF..."
                 style="flex:1;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:7px 10px;font-size:12px;color:#fff" ${isThinking ? 'disabled' : ''}>
          <button class="pdf-btn primary" id="pdfAiSendBtn" style="padding:5px 12px;font-size:12px;font-weight:600" ${isThinking ? 'disabled' : ''}>Ask</button>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:10px;color:var(--muted)">Press Enter to send · 100% Offline</span>
          ${history.length > 0 ? `<button class="pdf-btn ghost" style="font-size:10px;padding:2px 6px" onclick="_clearAiChat()">Clear Thread</button>` : ''}
        </div>
      </div>
    </div>
  `;

  const thread = document.getElementById('pdfAiMessageThread');
  if (thread) thread.scrollTop = thread.scrollHeight;

  const inputEl = document.getElementById('pdfAiInput');
  const sendBtn = document.getElementById('pdfAiSendBtn');
  const visionToggle = document.getElementById('pdfAiVisionToggle');

  if (visionToggle) {
    visionToggle.onchange = (e) => {
      _pdfState.aiVisionMode = e.target.checked;
      _renderSidebarContent();
    };
  }

  if (sendBtn && inputEl) {
    sendBtn.onclick = () => {
      const q = inputEl.value.trim();
      if (q) _sendAiQuestion(q);
    };
    inputEl.onkeydown = (e) => {
      if (e.key === 'Enter') {
        const q = inputEl.value.trim();
        if (q) _sendAiQuestion(q);
      }
    };
  }
}

function _formatAiResponseHtml(text) {
  if (!text) return '';
  return _esc(text)
    .replace(/\[Page\s+(\d+)\]/gi, (match, pNum) => `<a href="javascript:void(0)" onclick="_goToPage(${pNum})" style="color:var(--accent2);text-decoration:underline;font-weight:700">${match}</a>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.08);padding:2px 5px;border-radius:4px;font-size:11px">$1</code>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>');
}

async function _sendAiQuestion(question) {
  if (!question || !_pdfState.docId || _pdfState.aiIsThinking) return;

  if (!_pdfState.aiChatHistory) _pdfState.aiChatHistory = [];
  _pdfState.aiChatHistory.push({
    role: 'user',
    text: question
  });
  _pdfState.aiIsThinking = true;
  _renderSidebarContent();

  try {
    const res = await fetch(`${API}/api/v1/pdf/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doc_id: _pdfState.docId,
        question: question,
        page_number: _pdfState.currentPage,
        model: _pdfState.aiVisionMode ? 'qwen2.5vl:7b' : 'qwen3.5:9b',
        vision_mode: !!_pdfState.aiVisionMode
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Local AI reasoning failed');
    }

    const data = await res.json();
    _pdfState.aiChatHistory.push({
      role: 'assistant',
      text: data.answer,
      citedPages: data.cited_pages || [],
      model: data.model_used || (_pdfState.aiVisionMode ? 'qwen2.5vl:7b' : 'qwen3.5:9b'),
      isVision: !!data.vision_mode
    });

    if (data.highlights && data.highlights.length) {
      data.highlights.forEach(h => {
        _pdfState.markups.push({
          page: h.page,
          type: 'highlight',
          rect: h.rect,
          content: h.term || 'AI Reference',
          color: 'rgba(47, 107, 255, 0.35)'
        });
      });
      _renderCurrentPage();
    }

  } catch (err) {
    _pdfState.aiChatHistory.push({
      role: 'assistant',
      text: `⚠️ **Local AI Error:** ${err.message}. Please verify local Ollama is running with qwen3.5:9b.`,
      citedPages: [],
      model: 'Error'
    });
  } finally {
    _pdfState.aiIsThinking = false;
    _renderSidebarContent();
  }
}

function _askAiQuick(q) {
  _sendAiQuestion(q);
}

function _clearAiChat() {
  _pdfState.aiChatHistory = [];
  _renderSidebarContent();
}

function _renderSearchResultsHtml() {
  if (!_pdfState.searchResults || !_pdfState.searchResults.length) {
    return _pdfState.searchQuery ? '<div style="color:var(--muted);font-size:11px;padding:12px;text-align:center">No matches found.</div>' : '';
  }
  return `
    <div style="font-size:11px;color:var(--accent2);margin-bottom:4px">Found ${_pdfState.searchResults.length} occurrences:</div>
    ${_pdfState.searchResults.map((m, idx) => `
      <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:8px;cursor:pointer"
           onmouseover="this.style.borderColor='rgba(47,107,255,0.4)'" onmouseout="this.style.borderColor='rgba(255,255,255,0.08)'"
           onclick="_jumpToSearchResult(${idx})">
        <div style="display:flex;justify-content:space-between;font-weight:700;color:var(--accent2);font-size:11px;margin-bottom:2px">
          <span>Match #${idx + 1}</span>
          <span>Page ${m.page}</span>
        </div>
        <div style="font-size:11px;color:var(--text);line-height:1.4">${_esc(m.snippet)}</div>
      </div>
    `).join('')}
  `;
}

async function _executeSearch(query) {
  _pdfState.searchQuery = query;
  if (!query || !_pdfState.docId) {
    _pdfState.searchResults = [];
    _renderSidebarContent();
    return;
  }
  try {
    const res = await fetch(`${API}/api/v1/pdf/search?doc_id=${encodeURIComponent(_pdfState.docId)}&query=${encodeURIComponent(query)}`);
    if (res.ok) {
      const data = await res.json();
      _pdfState.searchResults = data.matches || [];
      _renderSidebarContent();
      if (_pdfState.searchResults.length > 0) {
        _jumpToSearchResult(0);
      }
    }
  } catch (e) {
    console.error('Search error:', e);
  }
}

function _jumpToSearchResult(index) {
  if (!_pdfState.searchResults[index]) return;
  const match = _pdfState.searchResults[index];
  _goToPage(match.page);
}
window._jumpToSearchResult = _jumpToSearchResult;

/* ==========================================================================
   MARKUP OVERLAY, 2D MEASUREMENTS & REDACTION AUDIT
   (Clean-room implementations inspired by storytold/pdfcraft crates:
    crates/audit (PR #2698), crates/measure, crates/automation)
   ========================================================================== */

function _renderMarkupOverlay() {
  const overlay = document.getElementById('pdfMarkupOverlay');
  if (!overlay || !_pdfState.info || !_pdfState.info.pages) return;
  const pMeta = _pdfState.info.pages[_pdfState.currentPage - 1];
  if (!pMeta) return;

  const pw = pMeta.width;
  const ph = pMeta.height;
  const curPage = _pdfState.currentPage;

  let html = '';

  // 1. Audit Highlights (pdfcraft-audit: faux redactions & unapplied marks)
  const pageAudit = (_pdfState.auditHighlights || []).filter(a => a.page === curPage);
  pageAudit.forEach(a => {
    const [x0, y0, x1, y1] = a.rect;
    const l = (x0 / pw) * 100;
    const t = (y0 / ph) * 100;
    const w = Math.max(1.5, ((x1 - x0) / pw) * 100);
    const h = Math.max(1.5, ((y1 - y0) / ph) * 100);
    const isFaux = a.kind === 'faux_redaction';
    html += `
      <div style="position:absolute;left:${l}%;top:${t}%;width:${w}%;height:${h}%;border:2px solid ${isFaux ? '#ef4444' : '#f59e0b'};background:${isFaux ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'};box-shadow:0 0 12px ${isFaux ? 'rgba(239,68,68,0.7)' : 'rgba(245,158,11,0.7)'};pointer-events:none;z-index:20;border-radius:2px">
        <span style="position:absolute;bottom:100%;left:0;margin-bottom:2px;background:${isFaux ? '#ef4444' : '#f59e0b'};color:#fff;font-size:9.5px;font-weight:700;padding:2px 5px;border-radius:3px;white-space:nowrap;box-shadow:0 2px 5px rgba(0,0,0,0.5)">
          ⚠️ ${isFaux ? 'LEAK' : 'UNAPPLIED'}: ${_esc(a.covered_text.slice(0, 24))}
        </span>
      </div>
    `;
  });

  // 2. Search Highlights
  const pageSearch = (_pdfState.searchResults || []).filter(s => s.page === curPage);
  pageSearch.forEach(s => {
    if (s.rect && s.rect.length === 4) {
      const [x0, y0, x1, y1] = s.rect;
      const l = (x0 / pw) * 100;
      const t = (y0 / ph) * 100;
      const w = Math.max(1, ((x1 - x0) / pw) * 100);
      const h = Math.max(1, ((y1 - y0) / ph) * 100);
      html += `
        <div style="position:absolute;left:${l}%;top:${t}%;width:${w}%;height:${h}%;background:rgba(250,204,21,0.45);border:1px solid #facc15;pointer-events:none;z-index:15"></div>
      `;
    }
  });

  // 3. 2D Calibrated Measurements (pdfcraft-measure)
  const pageMeasures = (_pdfState.measurements || []).filter(m => m.page === curPage);
  pageMeasures.forEach(m => {
    if (m.type === 'distance' && m.points.length === 2) {
      const [p1, p2] = m.points;
      const x1 = (p1.x / pw) * 100;
      const y1 = (p1.y / ph) * 100;
      const x2 = (p2.x / pw) * 100;
      const y2 = (p2.y / ph) * 100;
      const midX = (x1 + x2) / 2;
      const midY = (y1 + y2) / 2;
      html += `
        <svg style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:16">
          <line x1="${x1}%" y1="${y1}%" x2="${x2}%" y2="${y2}%" stroke="#38bdf8" stroke-width="2.5" stroke-dasharray="4,3"/>
          <circle cx="${x1}%" cy="${y1}%" r="4.5" fill="#0284c7" stroke="#fff" stroke-width="1.5"/>
          <circle cx="${x2}%" cy="${y2}%" r="4.5" fill="#0284c7" stroke="#fff" stroke-width="1.5"/>
        </svg>
        <div style="position:absolute;left:${midX}%;top:${midY}%;transform:translate(-50%,-50%);background:#0284c7;color:#fff;font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,0.6);border:1px solid rgba(255,255,255,0.4);pointer-events:none;z-index:22;white-space:nowrap">
          📏 ${_esc(m.valueText)}
        </div>
      `;
    } else if (m.type === 'area' && m.points.length >= 3) {
      const ptsAttr = m.points.map(p => `${(p.x / pw) * 100}%,${(p.y / ph) * 100}%`).join(' ');
      const cx = m.points.reduce((s, p) => s + (p.x / pw) * 100, 0) / m.points.length;
      const cy = m.points.reduce((s, p) => s + (p.y / ph) * 100, 0) / m.points.length;
      html += `
        <svg style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:16">
          <polygon points="${ptsAttr}" fill="rgba(56,189,248,0.22)" stroke="#38bdf8" stroke-width="2.5"/>
        </svg>
        <div style="position:absolute;left:${cx}%;top:${cy}%;transform:translate(-50%,-50%);background:#0284c7;color:#fff;font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,0.6);border:1px solid rgba(255,255,255,0.4);pointer-events:none;z-index:22;white-space:nowrap">
          📐 ${_esc(m.valueText)}
        </div>
      `;
    }
  });

  // 4. In-progress measurement points
  if (_pdfState.measurePoints && _pdfState.measurePoints.length > 0) {
    _pdfState.measurePoints.forEach((p, idx) => {
      const px = (p.x / pw) * 100;
      const py = (p.y / ph) * 100;
      html += `
        <div style="position:absolute;left:${px}%;top:${py}%;transform:translate(-50%,-50%);width:10px;height:10px;border-radius:50%;background:#f59e0b;border:2px solid #fff;box-shadow:0 0 6px #f59e0b;pointer-events:none;z-index:25"></div>
      `;
    });
  }

  overlay.innerHTML = html;
}

function _handleOverlayClick(e) {
  const overlay = document.getElementById('pdfMarkupOverlay');
  if (!overlay || !_pdfState.info || !_pdfState.info.pages) return;
  const pMeta = _pdfState.info.pages[_pdfState.currentPage - 1];
  if (!pMeta) return;

  const rect = overlay.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const clickY = e.clientY - rect.top;

  const pdfX = (clickX / rect.width) * pMeta.width;
  const pdfY = (clickY / rect.height) * pMeta.height;

  if (_pdfState.activeTool === 'measure-dist') {
    _pdfState.measurePoints.push({ x: pdfX, y: pdfY });
    if (_pdfState.measurePoints.length === 2) {
      const [p1, p2] = _pdfState.measurePoints;
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const ptsDist = Math.hypot(dx, dy);
      const scaleRatios = { '1:50': 50, '1:100': 100, '1:200': 200, '1:500': 500, '1:1': 1 };
      const ratio = scaleRatios[_pdfState.measureScale] || 100;
      let valText = '';
      if (_pdfState.measureScale === '1:1') {
        valText = `${Math.round(ptsDist)} pt`;
      } else {
        const realMeters = (ptsDist * 0.352778 * ratio) / 1000;
        valText = realMeters >= 1 ? `${realMeters.toFixed(2)} m` : `${(realMeters * 1000).toFixed(0)} mm`;
      }

      _pdfState.measurements.push({
        page: _pdfState.currentPage,
        type: 'distance',
        points: [..._pdfState.measurePoints],
        valueText: valText
      });
      _pdfState.measurePoints = [];
      _renderMarkupOverlay();
      _renderSidebarContent();
      toast(`Measured Distance: ${valText}`);
    } else {
      _renderMarkupOverlay();
      toast('Click 2nd point to finish distance measurement');
    }
  } else if (_pdfState.activeTool === 'measure-area') {
    _pdfState.measurePoints.push({ x: pdfX, y: pdfY });
    if (_pdfState.measurePoints.length >= 3) {
      const p0 = _pdfState.measurePoints[0];
      const cur = _pdfState.measurePoints[_pdfState.measurePoints.length - 1];
      if (Math.hypot(cur.x - p0.x, cur.y - p0.y) < 18 || e.detail >= 2) {
        let area = 0;
        const pts = _pdfState.measurePoints;
        for (let i = 0; i < pts.length; i++) {
          const j = (i + 1) % pts.length;
          area += pts[i].x * pts[j].y;
          area -= pts[j].x * pts[i].y;
        }
        area = Math.abs(area) / 2;
        const scaleRatios = { '1:50': 50, '1:100': 100, '1:200': 200, '1:500': 500, '1:1': 1 };
        const ratio = scaleRatios[_pdfState.measureScale] || 100;
        const realSqMeters = area * Math.pow((0.352778 * ratio) / 1000, 2);
        const valText = `${realSqMeters.toFixed(2)} m²`;

        _pdfState.measurements.push({
          page: _pdfState.currentPage,
          type: 'area',
          points: [...pts],
          valueText: valText
        });
        _pdfState.measurePoints = [];
        _renderMarkupOverlay();
        _renderSidebarContent();
        toast(`Measured Area: ${valText}`);
      } else {
        _renderMarkupOverlay();
        toast(`Point ${_pdfState.measurePoints.length} added. Click near start or double-click to complete.`);
      }
    } else {
      _renderMarkupOverlay();
      toast(`Point ${_pdfState.measurePoints.length} added. Need 3+ points for area.`);
    }
  }
}

function _removeMeasurement(idx) {
  const curPageMeasures = _pdfState.measurements.filter(m => m.page === _pdfState.currentPage);
  if (curPageMeasures[idx]) {
    const target = curPageMeasures[idx];
    _pdfState.measurements = _pdfState.measurements.filter(m => m !== target);
    _renderMarkupOverlay();
    _renderSidebarContent();
  }
}
window._removeMeasurement = _removeMeasurement;

function _renderAuditTabContent(content) {
  if (!_pdfState.docId) {
    content.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:30px">Open a document first</div>';
    return;
  }

  if (!_pdfState.auditData) {
    content.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;text-align:center;padding:24px 10px;gap:12px">
        <div style="font-size:32px">🛡️</div>
        <div style="font-size:13px;font-weight:700;color:var(--text)">Redaction Security Audit</div>
        <div style="font-size:11px;color:var(--muted);line-height:1.5">
          Based on <b>storytold/pdfcraft</b> clean-room audit engine (PR #2698 / M8).<br>
          Detects faux redactions (opaque shapes covering extractable text) and unapplied redaction marks.
        </div>
        <button class="pdf-btn primary" id="pdfRunAuditBtn" style="padding:8px 16px;font-size:12px;font-weight:700">
          🔍 Scan Document for Leaks
        </button>
      </div>
    `;
    const runBtn = document.getElementById('pdfRunAuditBtn');
    if (runBtn) runBtn.onclick = _runRedactionAudit;
    return;
  }

  const data = _pdfState.auditData;
  const findings = data.findings || [];
  const safe = findings.length === 0;

  content.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">Redaction Security Audit</div>
        <button class="pdf-btn" id="pdfRescanAuditBtn" style="font-size:10px;padding:3px 7px">↻ Rescan</button>
      </div>

      <div style="background:${safe ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)'};border:1px solid ${safe ? '#10b981' : '#ef4444'};border-radius:8px;padding:12px;display:flex;align-items:center;gap:10px">
        <div style="font-size:24px">${safe ? '✅' : '⚠️'}</div>
        <div>
          <div style="font-size:12px;font-weight:700;color:#fff">${safe ? 'Document is Safe' : `${findings.length} Leak(s) Detected`}</div>
          <div style="font-size:10.5px;color:var(--muted)">
            ${safe ? 'Zero faux redactions or unapplied redaction marks found.' : `${data.summary.faux_redactions} faux redaction(s), ${data.summary.unapplied_marks} unapplied mark(s).`}
          </div>
        </div>
      </div>

      ${!safe ? `
        <button class="pdf-btn primary" id="pdfSanitizeAllBtn" style="background:#dc2626;border-color:#b91c1c;padding:8px 12px;font-size:11.5px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:6px">
          <span>🔒 Sanitize &amp; Burn Redactions</span>
        </button>
      ` : ''}

      <div style="display:flex;flex-direction:column;gap:8px;max-height:420px;overflow-y:auto">
        ${findings.map((f, idx) => `
          <div style="background:#070b15;border:1px solid rgba(239,68,68,0.3);border-radius:6px;padding:10px;cursor:pointer"
               onmouseover="this.style.borderColor='#ef4444'" onmouseout="this.style.borderColor='rgba(239,68,68,0.3)'"
               onclick="_jumpToAuditFinding(${idx})">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
              <span class="badge-s ${f.kind === 'faux_redaction' ? 'b-fail' : 'b-warn'}" style="font-size:9px;text-transform:uppercase">
                ${f.kind === 'faux_redaction' ? '🔴 Faux Redaction' : '🟠 Unapplied Mark'}
              </span>
              <span style="font-size:10px;color:var(--muted);font-weight:600">Page ${f.page}</span>
            </div>
            <div style="font-size:11px;color:#fca5a5;font-family:monospace;background:rgba(0,0,0,0.4);padding:4px 6px;border-radius:4px;word-break:break-all;margin-bottom:4px">
              "${_esc(f.covered_text)}"
            </div>
            <div style="font-size:10px;color:var(--muted)">${_esc(f.description)}</div>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  const rescanBtn = document.getElementById('pdfRescanAuditBtn');
  if (rescanBtn) rescanBtn.onclick = _runRedactionAudit;

  const sanitizeBtn = document.getElementById('pdfSanitizeAllBtn');
  if (sanitizeBtn) sanitizeBtn.onclick = _applyRedactionsSanitize;
}

async function _runRedactionAudit() {
  if (!_pdfState.docId) return;
  toast('Running Redaction Security Audit (pdfcraft-audit)...');
  try {
    const res = await fetch(`${API}/api/v1/pdf/audit?doc_id=${encodeURIComponent(_pdfState.docId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _pdfState.auditData = data;
    _pdfState.auditHighlights = data.findings || [];
    _renderSidebarContent();
    _renderCurrentPage();
    if (data.total_findings > 0) {
      toast(`⚠️ Audit complete: ${data.total_findings} security leak(s) found!`);
      const first = data.findings[0];
      if (first && first.page !== _pdfState.currentPage) {
        _goToPage(first.page);
      }
    } else {
      toast('✅ Document is clean! Zero redaction leaks found.');
    }
  } catch (err) {
    toast(`Audit failed: ${err.message}`);
  }
}
window._runRedactionAudit = _runRedactionAudit;

async function _applyRedactionsSanitize() {
  if (!_pdfState.docId || !_pdfState.auditData || !_pdfState.auditData.findings) return;
  const findings = _pdfState.auditData.findings;
  if (!findings.length) return;

  if (!confirm(`Permanently burn and sanitize ${findings.length} redaction area(s)?\n\nThis will strip and destroy the underlying text and vectors, rendering the document leak-proof.`)) {
    return;
  }

  toast('Applying permanent redactions (stripping text bytes)...');
  try {
    const res = await fetch(`${API}/api/v1/pdf/redact-apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doc_id: _pdfState.docId,
        redactions: findings.map(f => ({ page: f.page, rect: f.rect }))
      })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _pdfState.info = data.info;
    _pdfState.pageRenderCache.clear();
    toast(`✅ Successfully sanitized document! ${data.applied_count} redaction(s) burned permanently.`);
    await _runRedactionAudit();
  } catch (err) {
    toast(`Failed to apply redactions: ${err.message}`);
  }
}

function _jumpToAuditFinding(idx) {
  if (!_pdfState.auditData || !_pdfState.auditData.findings || !_pdfState.auditData.findings[idx]) return;
  const f = _pdfState.auditData.findings[idx];
  _goToPage(f.page);
}
window._jumpToAuditFinding = _jumpToAuditFinding;

function _renderMeasureTabContent(content) {
  content.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">2D Calibrated Measurements</div>

      <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px;display:flex;flex-direction:column;gap:8px">
        <div>
          <label style="font-size:10.5px;color:var(--muted);display:block;margin-bottom:4px">Drawing Scale Preset</label>
          <select id="pdfMeasureScaleSel" class="pdf-select" style="width:100%;background:#162035;color:#fff;border-radius:4px;padding:5px">
            <option value="1:50" ${_pdfState.measureScale === '1:50' ? 'selected' : ''}>1:50 (1 cm = 0.5 m)</option>
            <option value="1:100" ${_pdfState.measureScale === '1:100' ? 'selected' : ''}>1:100 (1 cm = 1.0 m)</option>
            <option value="1:200" ${_pdfState.measureScale === '1:200' ? 'selected' : ''}>1:200 (1 cm = 2.0 m)</option>
            <option value="1:500" ${_pdfState.measureScale === '1:500' ? 'selected' : ''}>1:500 (1 cm = 5.0 m)</option>
            <option value="1:1" ${_pdfState.measureScale === '1:1' ? 'selected' : ''}>1:1 (PDF Points)</option>
          </select>
        </div>

        <div style="display:flex;gap:6px">
          <button class="pdf-btn ${_pdfState.activeTool === 'measure-dist' ? 'primary' : ''}" id="pdfMeasureDistBtn" style="flex:1;padding:6px;font-size:11px">
            📏 Distance
          </button>
          <button class="pdf-btn ${_pdfState.activeTool === 'measure-area' ? 'primary' : ''}" id="pdfMeasureAreaBtn" style="flex:1;padding:6px;font-size:11px">
            📐 Area
          </button>
        </div>

        <div style="font-size:10px;color:var(--muted);line-height:1.4">
          ${_pdfState.activeTool === 'measure-dist' ? '👉 Click two points on the drawing to measure real-world distance.' : (_pdfState.activeTool === 'measure-area' ? '👉 Click 3+ points to measure enclosed polygon area. Click near first point to close.' : 'Select Distance or Area to start measuring.')}
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:11px;font-weight:700;color:var(--muted)">Measurements (${_pdfState.measurements.filter(m => m.page === _pdfState.currentPage).length})</span>
        <button class="pdf-btn" id="pdfClearMeasureBtn" style="font-size:10px;padding:2px 6px">Clear Page</button>
      </div>

      <div style="display:flex;flex-direction:column;gap:6px;max-height:300px;overflow-y:auto">
        ${_pdfState.measurements.filter(m => m.page === _pdfState.currentPage).map((m, idx) => `
          <div style="background:#070b15;border:1px solid rgba(56,189,248,0.25);border-radius:6px;padding:8px;display:flex;justify-content:space-between;align-items:center">
            <div>
              <span style="font-size:10px;color:var(--muted);text-transform:uppercase">${m.type}:</span>
              <b style="font-size:12px;color:var(--accent2);margin-left:4px">${_esc(m.valueText)}</b>
            </div>
            <button class="pdf-btn" onclick="_removeMeasurement(${idx})" style="font-size:9px;padding:2px 5px">✕</button>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  const scaleSel = document.getElementById('pdfMeasureScaleSel');
  if (scaleSel) {
    scaleSel.onchange = () => {
      _pdfState.measureScale = scaleSel.value;
      _renderCurrentPage();
    };
  }

  const distBtn = document.getElementById('pdfMeasureDistBtn');
  if (distBtn) distBtn.onclick = () => {
    document.querySelectorAll('.pdf-tool-btn').forEach(b => b.classList.toggle('on', b.dataset.tool === 'measure-dist'));
    _pdfState.activeTool = 'measure-dist';
    _renderSidebarContent();
  };

  const areaBtn = document.getElementById('pdfMeasureAreaBtn');
  if (areaBtn) areaBtn.onclick = () => {
    document.querySelectorAll('.pdf-tool-btn').forEach(b => b.classList.toggle('on', b.dataset.tool === 'measure-area'));
    _pdfState.activeTool = 'measure-area';
    _renderSidebarContent();
  };

  const clrBtn = document.getElementById('pdfClearMeasureBtn');
  if (clrBtn) {
    clrBtn.onclick = () => {
      _pdfState.measurements = _pdfState.measurements.filter(m => m.page !== _pdfState.currentPage);
      _pdfState.measurePoints = [];
      _renderSidebarContent();
      _renderCurrentPage();
    };
  }
}

async function _showDocumentStatsModal() {
  if (!_pdfState.docId) {
    toast('No document loaded.');
    return;
  }
  toast('Calculating document word count & statistics...');
  try {
    const res = await fetch(`${API}/api/v1/pdf/stats?doc_id=${encodeURIComponent(_pdfState.docId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const m = document.createElement('div');
    m.className = 'pdf-modal-backdrop';
    m.innerHTML = `
      <div class="pdf-modal-card" style="max-width:540px">
        <div class="pdf-modal-header">
          <div class="pdf-modal-title">📊 Document Statistics &amp; Word Count</div>
          <button class="pdf-modal-close" onclick="this.closest('.pdf-modal-backdrop').remove()">✕</button>
        </div>
        <div class="pdf-modal-body">
          <div style="font-size:11px;color:var(--muted);margin-bottom:12px">
            Based on <b>storytold/pdfcraft</b> <code>text_word_count</code> specification.
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px">
            <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px;text-align:center">
              <div style="font-size:20px;font-weight:700;color:var(--accent2)">${data.total_words.toLocaleString()}</div>
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Total Words</div>
            </div>
            <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px;text-align:center">
              <div style="font-size:20px;font-weight:700;color:var(--green)">${data.total_characters.toLocaleString()}</div>
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Characters</div>
            </div>
            <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px;text-align:center">
              <div style="font-size:20px;font-weight:700;color:#fff">${data.page_count}</div>
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Pages</div>
            </div>
          </div>

          <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px;margin-bottom:14px">
            <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px">EMBEDDED FONTS (${data.font_count})</div>
            <div style="font-size:11px;color:var(--text);font-family:monospace;max-height:80px;overflow-y:auto;line-height:1.5">
              ${(data.fonts && data.fonts.length) ? data.fonts.map(f => `<div>• ${_esc(f)}</div>`).join('') : '<div>No embedded Type1/TrueType fonts detected.</div>'}
            </div>
          </div>

          <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px">PER-PAGE BREAKDOWN</div>
          <div style="max-height:160px;overflow-y:auto;border:1px solid rgba(255,255,255,0.08);border-radius:6px">
            <table style="width:100%;border-collapse:collapse;font-size:11px">
              <thead style="background:#070b15;color:var(--muted);position:sticky;top:0">
                <tr><th style="padding:6px;text-align:left">Page</th><th style="padding:6px;text-align:right">Words</th><th style="padding:6px;text-align:right">Chars</th><th style="padding:6px;text-align:right">Dimensions</th></tr>
              </thead>
              <tbody>
                ${(data.per_page || []).map(p => `
                  <tr style="border-top:1px solid rgba(255,255,255,0.04)">
                    <td style="padding:5px 6px">Page ${p.page}</td>
                    <td style="padding:5px 6px;text-align:right;color:var(--accent2);font-weight:600">${p.words}</td>
                    <td style="padding:5px 6px;text-align:right">${p.characters}</td>
                    <td style="padding:5px 6px;text-align:right;color:var(--muted)">${p.dimensions}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
        <div class="pdf-modal-footer">
          <button class="pdf-btn primary" onclick="this.closest('.pdf-modal-backdrop').remove()">Close</button>
        </div>
      </div>
    `;
    document.body.appendChild(m);
  } catch (err) {
    toast(`Failed to load stats: ${err.message}`);
  }
}
window._showDocumentStatsModal = _showDocumentStatsModal;


/* ==========================================================================
   CARD-BASED PAGE ORGANIZER (STORYTOLD/PDFCRAFT CLEAN-ROOM BENCHMARK)
   ========================================================================== */

function _renderOrganizerGrid() {
  const grid = document.getElementById('pdfCardsGrid');
  const countEl = document.getElementById('pdfOrgCount');
  if (!grid) return;

  const pages = _pdfState.organizerPages;
  if (countEl) countEl.textContent = String(pages.length);

  grid.innerHTML = pages.map((p, idx) => `
    <div class="pdf-org-card" data-idx="${idx}">
      <div class="pdf-org-card-header">
        <span>Page ${idx + 1} (Orig ${p.page_number})</span>
        <span style="color:var(--muted);font-size:10px">${Math.round(p.width)}×${Math.round(p.height)} pt</span>
      </div>
      <div class="pdf-org-thumb-wrap">
        <img src="${API}/api/v1/pdf/thumbnail?doc_id=${encodeURIComponent(_pdfState.docId)}&page=${p.page_number}&width=240"
             style="max-width:100%;height:auto;transform:rotate(${p.rotation || 0}deg)" loading="lazy">
      </div>
      <div class="pdf-org-card-actions">
        <button class="pdf-org-btn" onclick="_rotateOrgCard(${idx})" title="Rotate 90°">🔄 90°</button>
        <button class="pdf-org-btn" onclick="_duplicateOrgCard(${idx})" title="Duplicate Page">📑 Copy</button>
        <button class="pdf-org-btn danger" onclick="_deleteOrgCard(${idx})" title="Delete Page">🗑️</button>
      </div>
      <div style="display:flex;gap:4px">
        <button class="pdf-org-btn" onclick="_moveOrgCard(${idx}, -1)" ${idx === 0 ? 'disabled' : ''}>◀ Move</button>
        <button class="pdf-org-btn" onclick="_moveOrgCard(${idx}, 1)" ${idx === pages.length - 1 ? 'disabled' : ''}>Move ▶</button>
      </div>
    </div>
  `).join('');

  // Wire buttons in organizer toolbar
  const insertBlankBtn = document.getElementById('pdfOrgInsertBlankBtn');
  const resetBtn = document.getElementById('pdfOrgResetBtn');
  const applyBtn = document.getElementById('pdfOrgApplyBtn');

  if (insertBlankBtn) {
    insertBlankBtn.onclick = () => {
      _pdfState.organizerPages.push({
        page_number: _pdfState.organizerPages.length + 1,
        width: 595.32,
        height: 841.92,
        rotation: 0,
        is_landscape: false,
        is_new_blank: true
      });
      _renderOrganizerGrid();
      toast('Added blank A4 page');
    };
  }
  if (resetBtn) {
    resetBtn.onclick = () => {
      _pdfState.organizerPages = JSON.parse(JSON.stringify(_pdfState.info.pages));
      _renderOrganizerGrid();
      toast('Reset page order');
    };
  }
  if (applyBtn) {
    applyBtn.onclick = _applyPageReorganization;
  }
}

function _rotateOrgCard(idx) {
  const p = _pdfState.organizerPages[idx];
  p.rotation = ((p.rotation || 0) + 90) % 360;
  _renderOrganizerGrid();
}

function _duplicateOrgCard(idx) {
  const copy = JSON.parse(JSON.stringify(_pdfState.organizerPages[idx]));
  _pdfState.organizerPages.splice(idx + 1, 0, copy);
  _renderOrganizerGrid();
  toast(`Duplicated page ${idx + 1}`);
}

function _deleteOrgCard(idx) {
  if (_pdfState.organizerPages.length <= 1) {
    toast('Cannot delete the only page in the document.');
    return;
  }
  _pdfState.organizerPages.splice(idx, 1);
  _renderOrganizerGrid();
}

function _moveOrgCard(idx, delta) {
  const target = idx + delta;
  if (target < 0 || target >= _pdfState.organizerPages.length) return;
  const temp = _pdfState.organizerPages[idx];
  _pdfState.organizerPages[idx] = _pdfState.organizerPages[target];
  _pdfState.organizerPages[target] = temp;
  _renderOrganizerGrid();
}

async function _applyPageReorganization() {
  _showLoading('Reorganizing PDF pages...', 'Atomic save with incremental updates');
  const ops = {
    reorder: _pdfState.organizerPages.map(p => p.page_number),
    rotate: _pdfState.organizerPages.map((p, idx) => ({ page: idx + 1, angle: p.rotation || 0 }))
  };

  try {
    const res = await fetch(`${API}/api/v1/pdf/organize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_id: _pdfState.docId, ...ops })
    });
    if (!res.ok) throw new Error('Failed to reorganize pages');
    const data = await res.json();
    _applyLoadedDocument(_pdfState.docId, _pdfState.filename, data.info);
    toast('✅ Successfully updated PDF pages order & rotation!');
    // Switch back to reader view
    document.getElementById('pdfViewReaderBtn').click();
  } catch (err) {
    toast(`Error reorganizing pages: ${err.message}`);
  } finally {
    _hideLoading();
  }
}

async function _rotateActivePage(angle = 90) {
  _showLoading(`Rotating page ${_pdfState.currentPage}...`, 'Applying lossless rotation');
  try {
    const res = await fetch(`${API}/api/v1/pdf/organize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doc_id: _pdfState.docId,
        rotate: [{ page: _pdfState.currentPage, angle: angle }]
      })
    });
    if (!res.ok) throw new Error('Rotate failed');
    const data = await res.json();
    _pdfState.pageRenderCache.clear();
    _pdfState.info = data.info;
    _renderCurrentPage();
    toast(`Rotated page ${_pdfState.currentPage} by 90°`);
  } catch (err) {
    toast(`Error: ${err.message}`);
  } finally {
    _hideLoading();
  }
}

/* ==========================================================================
   MODALS: OPEN PROJECT, MERGE, SPLIT, WATERMARK, SECURITY
   ========================================================================== */

async function _openProjectPdfsModal() {
  const proj = (typeof currentProject !== 'undefined' && currentProject) ? currentProject : 'C3085 - 3EH -Expo Hills';
  _removeExistingModal();

  const modal = _createModal(`
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
        <svg class="ico" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        Open PDF Document from ${_esc(proj)}
      </div>
      <button class="pdf-icon-btn" onclick="_removeExistingModal()">&times;</button>
    </div>
    <div id="pdfProjectListBody" style="flex:1;overflow-y:auto;max-height:360px;border:1px solid rgba(255,255,255,0.08);border-radius:6px;background:#070b15">
      <div style="padding:30px;text-align:center;color:var(--muted)">Loading project PDFs...</div>
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px">
      <button class="pdf-btn" onclick="_removeExistingModal()">Cancel</button>
    </div>
  `);

  try {
    const res = await fetch(`${API}/api/v1/pdf/project-files?project=${encodeURIComponent(proj)}`);
    const data = await res.json();
    const listEl = modal.querySelector('#pdfProjectListBody');
    if (!data.files || !data.files.length) {
      listEl.innerHTML = '<div style="padding:30px;text-align:center;color:var(--muted)">No PDF documents found in this project. Use Upload to bring in your PDF.</div>';
      return;
    }
    listEl.innerHTML = data.files.map(f => `
      <div style="padding:10px 14px;border-bottom:1px solid rgba(255,255,255,0.05);display:flex;justify-content:space-between;align-items:center;cursor:pointer"
           onmouseover="this.style.background='rgba(47,107,255,0.12)'" onmouseout="this.style.background='transparent'"
           onclick="openPdfProjectDocument('${_esc(f.filename)}', '${_esc(f.rel)}', '${_esc(proj)}'); _removeExistingModal();">
        <div>
          <div style="font-weight:700;color:var(--text);font-size:12.5px">${_esc(f.filename)}</div>
          <div style="font-size:10.5px;color:var(--muted)">${_esc(f.folder)} · ${(f.size / 1024).toFixed(0)} KB</div>
        </div>
        <button class="pdf-btn primary" style="font-size:11px;padding:3px 10px">Open</button>
      </div>
    `).join('');
  } catch (e) {
    console.error(e);
  }
}

function _openWatermarkModal() {
  _removeExistingModal();
  const modal = _createModal(`
    <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
      <svg class="ico" viewBox="0 0 24 24"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>
      Stamp Document Watermark
    </div>
    <div style="display:flex;flex-direction:column;gap:12px;font-size:12px">
      <div>
        <label style="display:block;margin-bottom:4px;color:var(--muted);font-weight:600">Watermark Text:</label>
        <input type="text" id="wmTextInput" value="CONFIDENTIAL" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px;color:#fff;font-size:13px">
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div>
          <label style="display:block;margin-bottom:4px;color:var(--muted);font-weight:600">Preset:</label>
          <select id="wmPresetSelect" class="pdf-select" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px">
            <option value="CONFIDENTIAL">CONFIDENTIAL</option>
            <option value="DRAFT">DRAFT - NOT FOR CONSTRUCTION</option>
            <option value="APPROVED">APPROVED FOR TENDER</option>
            <option value="REVIEW COPY">REVIEW COPY ONLY</option>
          </select>
        </div>
        <div>
          <label style="display:block;margin-bottom:4px;color:var(--muted);font-weight:600">Font Size:</label>
          <input type="number" id="wmSizeInput" value="52" min="20" max="120" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px;color:#fff">
        </div>
      </div>
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:8px">
      <button class="pdf-btn" onclick="_removeExistingModal()">Cancel</button>
      <button class="pdf-btn primary" id="wmApplyBtn">Stamp Watermark</button>
    </div>
  `);

  const presetSel = modal.querySelector('#wmPresetSelect');
  const textInput = modal.querySelector('#wmTextInput');
  if (presetSel && textInput) {
    presetSel.onchange = () => { textInput.value = presetSel.value; };
  }

  const applyBtn = modal.querySelector('#wmApplyBtn');
  if (applyBtn) {
    applyBtn.onclick = async () => {
      const txt = textInput.value.trim();
      const sz = parseInt(modal.querySelector('#wmSizeInput').value) || 52;
      _removeExistingModal();
      _showLoading('Stamping watermark...', 'Vector stamp applied across document');
      try {
        const res = await fetch(`${API}/api/v1/pdf/watermark`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ doc_id: _pdfState.docId, text: txt, font_size: sz })
        });
        if (!res.ok) throw new Error('Watermark stamping failed');
        _pdfState.pageRenderCache.clear();
        _renderCurrentPage();
        toast(`✅ Stamped watermark '${txt}' across document!`);
      } catch (e) {
        toast(`Error: ${e.message}`);
      } finally {
        _hideLoading();
      }
    };
  }
}

function _openSecurityModal() {
  _removeExistingModal();
  const isEncrypted = _pdfState.info && _pdfState.info.is_encrypted;
  const modal = _createModal(`
    <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
      <svg class="ico" viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
      AES-256 PDF Security &amp; Permissions
    </div>
    <div style="display:flex;flex-direction:column;gap:12px;font-size:12px">
      <div>
        <label style="display:block;margin-bottom:4px;color:var(--muted);font-weight:600">Document Open Password:</label>
        <input type="password" id="secPasswordInput" placeholder="Enter password to encrypt" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px;color:#fff">
      </div>
      <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px">
        <div style="font-weight:700;color:var(--muted);margin-bottom:8px;text-transform:uppercase;font-size:11px">Document Permission Flags</div>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><input type="checkbox" id="secPermPrint" checked> Allow High-Resolution Printing</label>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><input type="checkbox" id="secPermCopy" checked> Allow Copying Text &amp; Graphics</label>
        <label style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><input type="checkbox" id="secPermAnnotate" checked> Allow Adding Comments &amp; Form Fill</label>
      </div>
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:8px">
      <button class="pdf-btn" onclick="_removeExistingModal()">Cancel</button>
      <button class="pdf-btn primary" id="secApplyBtn">Encrypt with AES-256</button>
    </div>
  `);

  const applyBtn = modal.querySelector('#secApplyBtn');
  if (applyBtn) {
    applyBtn.onclick = async () => {
      const pw = modal.querySelector('#secPasswordInput').value.trim();
      if (!pw) { toast('Please enter a password'); return; }
      const canPrint = modal.querySelector('#secPermPrint').checked;
      const canCopy = modal.querySelector('#secPermCopy').checked;
      const canAnnot = modal.querySelector('#secPermAnnotate').checked;

      _removeExistingModal();
      _showLoading('Encrypting PDF...', 'Applying AES-256 standard security');
      try {
        const res = await fetch(`${API}/api/v1/pdf/security`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            doc_id: _pdfState.docId,
            user_password: pw,
            can_print: canPrint,
            can_copy: canCopy,
            can_annotate: canAnnot,
            can_modify: false
          })
        });
        if (!res.ok) throw new Error('Encryption failed');
        toast('🔒 Document successfully protected with AES-256 encryption!');
        const secEl = document.getElementById('pdfSecurityLabel');
        if (secEl) secEl.textContent = '🔒 AES-256 Protected';
      } catch (e) {
        toast(`Security error: ${e.message}`);
      } finally {
        _hideLoading();
      }
    };
  }
}

async function _openMergeModal() {
  _removeExistingModal();
  const proj = (typeof currentProject !== 'undefined' && currentProject) ? currentProject : 'C3085 - 3EH -Expo Hills';
  const modal = _createModal(`
    <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
      <svg class="ico" viewBox="0 0 24 24"><path d="M12 8v8M8 12h8"/></svg>
      Combine &amp; Merge PDF Documents
    </div>
    <div style="font-size:12px;color:var(--muted)">Select documents from <b>${_esc(proj)}</b> to merge into a single master PDF:</div>
    <div id="pdfMergeList" style="flex:1;max-height:280px;overflow-y:auto;border:1px solid rgba(255,255,255,0.08);border-radius:6px;background:#070b15;padding:8px">
      Loading files...
    </div>
    <div>
      <label style="display:block;margin-bottom:4px;color:var(--muted);font-size:11px;font-weight:600">Merged Document Name:</label>
      <input type="text" id="pdfMergeOutName" value="Combined_Master_Document.pdf" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px;color:#fff;font-size:12px">
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:6px">
      <button class="pdf-btn" onclick="_removeExistingModal()">Cancel</button>
      <button class="pdf-btn primary" id="pdfExecuteMergeBtn">Merge Documents</button>
    </div>
  `);

  try {
    const res = await fetch(`${API}/api/v1/pdf/project-files?project=${encodeURIComponent(proj)}`);
    const data = await res.json();
    const listEl = modal.querySelector('#pdfMergeList');
    if (!data.files || data.files.length < 2) {
      listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted)">At least 2 PDF documents are needed to merge. Upload additional PDFs to proceed.</div>';
      return;
    }
    listEl.innerHTML = data.files.map((f, i) => `
      <label style="display:flex;align-items:center;gap:10px;padding:8px;border-bottom:1px solid rgba(255,255,255,0.05);cursor:pointer">
        <input type="checkbox" value="${_esc(f.filename)}" class="pdf-merge-cb" ${i < 2 ? 'checked' : ''}>
        <div>
          <div style="font-weight:600;color:#fff">${_esc(f.filename)}</div>
          <div style="font-size:10px;color:var(--muted)">${_esc(f.folder)} · ${(f.size / 1024).toFixed(0)} KB</div>
        </div>
      </label>
    `).join('');
  } catch (e) {
    console.error(e);
  }

  const execBtn = modal.querySelector('#pdfExecuteMergeBtn');
  if (execBtn) {
    execBtn.onclick = async () => {
      const checked = Array.from(modal.querySelectorAll('.pdf-merge-cb:checked')).map(cb => cb.value);
      if (checked.length < 2) { toast('Please select at least 2 files to merge.'); return; }
      const outName = modal.querySelector('#pdfMergeOutName').value.trim() || 'Merged.pdf';
      _removeExistingModal();
      _showLoading('Merging documents...', 'Preserving bookmarks, forms & vector layers');
      try {
        const res = await fetch(`${API}/api/v1/pdf/merge`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ doc_ids: checked, output_filename: outName, project: proj })
        });
        if (!res.ok) throw new Error('Merge failed');
        const data = await res.json();
        _applyLoadedDocument(data.doc_id, data.filename, data.info);
        toast(`✅ Merged ${checked.length} documents successfully!`);
      } catch (e) {
        toast(`Merge error: ${e.message}`);
      } finally {
        _hideLoading();
      }
    };
  }
}

function _openSplitModal() {
  _removeExistingModal();
  const modal = _createModal(`
    <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
      <svg class="ico" viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>
      Split PDF Document
    </div>
    <div style="font-size:12px;color:var(--muted)">Extract page ranges into separate files:</div>
    <div>
      <label style="display:block;margin-bottom:4px;color:var(--muted);font-size:11px;font-weight:600">Page Ranges (comma separated, e.g. 1-2, 3-5):</label>
      <input type="text" id="pdfSplitRanges" placeholder="e.g. 1, 2-3" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px;color:#fff;font-size:12px">
      <div style="font-size:10.5px;color:var(--muted);margin-top:4px">Leave empty to split every page into its own single-page PDF.</div>
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:8px">
      <button class="pdf-btn" onclick="_removeExistingModal()">Cancel</button>
      <button class="pdf-btn primary" id="pdfExecuteSplitBtn">Split Document</button>
    </div>
  `);

  const splitBtn = modal.querySelector('#pdfExecuteSplitBtn');
  if (splitBtn) {
    splitBtn.onclick = async () => {
      const ranges = modal.querySelector('#pdfSplitRanges').value.trim();
      _removeExistingModal();
      _showLoading('Splitting PDF...', 'Creating independent document parts');
      const fd = new FormData();
      fd.append('doc_id', _pdfState.docId);
      if (ranges) fd.append('ranges', ranges);
      try {
        const res = await fetch(`${API}/api/v1/pdf/split`, { method: 'POST', body: fd });
        if (!res.ok) throw new Error('Split operation failed');
        const data = await res.json();
        toast(`✅ Split complete: created ${data.total_parts} files.`);
      } catch (e) {
        toast(`Split error: ${e.message}`);
      } finally {
        _hideLoading();
      }
    };
  }
}

function _saveToProjectModal() {
  _removeExistingModal();
  const proj = (typeof currentProject !== 'undefined' && currentProject) ? currentProject : 'C3085 - 3EH -Expo Hills';
  const modal = _createModal(`
    <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
      <svg class="ico" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/></svg>
      Save Document to Project
    </div>
    <div style="font-size:12px;color:var(--muted)">Atomically save the active PDF workbench into <b>${_esc(proj)}</b>:</div>
    <div>
      <label style="display:block;margin-bottom:4px;color:var(--muted);font-size:11px;font-weight:600">Filename:</label>
      <input type="text" id="pdfSaveFilename" value="${_esc(_pdfState.filename)}" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px;color:#fff;font-size:12px">
    </div>
    <div>
      <label style="display:block;margin-bottom:4px;color:var(--muted);font-size:11px;font-weight:600">Folder:</label>
      <input type="text" id="pdfSaveFolder" value="Documents" style="width:100%;background:#162035;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px;color:#fff;font-size:12px">
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:6px">
      <button class="pdf-btn" onclick="_removeExistingModal()">Cancel</button>
      <button class="pdf-btn primary" id="pdfConfirmSaveBtn">Save to Project</button>
    </div>
  `);

  const confirmBtn = modal.querySelector('#pdfConfirmSaveBtn');
  if (confirmBtn) {
    confirmBtn.onclick = async () => {
      const fn = modal.querySelector('#pdfSaveFilename').value.trim();
      const folder = modal.querySelector('#pdfSaveFolder').value.trim();
      _removeExistingModal();
      _showLoading(`Saving ${fn}...`, 'Writing atomically to project storage');
      try {
        const res = await fetch(`${API}/api/v1/pdf/save-to-project`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            doc_id: _pdfState.docId,
            project: proj,
            filename: fn,
            folder: folder
          })
        });
        if (!res.ok) throw new Error('Save failed');
        const data = await res.json();
        toast(`✅ ${data.message}`);
      } catch (e) {
        toast(`Error saving: ${e.message}`);
      } finally {
        _hideLoading();
      }
    };
  }
}

async function _renderPageForAiStudio() {
  if (!_pdfState.docId) return;
  const proj = (typeof currentProject !== 'undefined' && currentProject) ? currentProject : 'C3085 - 3EH -Expo Hills';
  _showLoading(`Rendering Page ${_pdfState.currentPage} for AI Studio...`, 'Generating high-res conditioning image');
  try {
    const res = await fetch(`${API}/api/v1/pdf/render-for-ai`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doc_id: _pdfState.docId,
        page_number: _pdfState.currentPage,
        project: proj,
        width: 1024,
        height: 1024
      })
    });
    if (!res.ok) throw new Error('Failed to render page for AI Studio');
    const data = await res.json();
    toast(`🎨 Page ${_pdfState.currentPage} sent to AI Design Studio!`);

    // Automatically navigate to studio and set as initial conditioning image if available
    if (typeof navigate === 'function') {
      navigate('studio');
      setTimeout(() => {
        const imgInput = document.getElementById('initImageInput');
        if (imgInput) imgInput.value = data.image_path;
        toast('Loaded PDF page conditioning in Studio');
      }, 250);
    }
  } catch (err) {
    toast(`Error: ${err.message}`);
  } finally {
    _hideLoading();
  }
}

function _showPdfCraftEngineModal() {
  _removeExistingModal();
  _createModal(`
    <div style="font-size:16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px">
      <svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
      PdfCraft Clean-Room Architecture (storytold/pdfcraft)
    </div>
    <div style="font-size:12px;color:var(--text);line-height:1.6">
      <p><b>PdfCraft</b> is an open-source, clean-room reimplementation of Adobe Acrobat built entirely from scratch with a local-first philosophy.</p>
      <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:12px;margin:10px 0">
        <div style="font-weight:700;color:var(--accent2);margin-bottom:6px">🔒 100% Offline &amp; Private</div>
        <div style="color:var(--muted);font-size:11.5px">
          • No cloud calls, no telemetry, no tracking.<br>
          • Atomic saves: writes to temporary files first to guarantee your original PDF bytes are never corrupted.<br>
          • Deep zoom rasterization with tile-based isolation so even broken documents can be repaired safely.<br>
          • AES-256 standard encryption &amp; permission compliance.
        </div>
      </div>
      <div style="background:#070b15;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:12px">
        <div style="font-weight:700;color:var(--accent2);margin-bottom:6px">⚡ Pure Rust Source Code &amp; CLI</div>
        <div style="color:var(--muted);font-size:11.5px">
          Local source code repository cloned at <code>vendor/pdfcraft</code>.<br>
          Run native workbench via <code>cargo run --release -p pdfcraft</code>.
        </div>
      </div>
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:6px">
      <button class="pdf-btn primary" onclick="_removeExistingModal()">Got It</button>
    </div>
  `);
}

function _createModal(htmlContent) {
  _removeExistingModal();
  const backdrop = document.createElement('div');
  backdrop.className = 'pdf-modal-backdrop';
  backdrop.id = 'pdfModalBackdrop';
  backdrop.innerHTML = `<div class="pdf-modal-box">${htmlContent}</div>`;
  backdrop.onclick = (e) => { if (e.target === backdrop) _removeExistingModal(); };
  document.body.appendChild(backdrop);
  return backdrop;
}

function _removeExistingModal() {
  const m = document.getElementById('pdfModalBackdrop');
  if (m) m.remove();
}

function _esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

window.renderPdfCraftWorkspace = renderPdfCraftWorkspace;
window.openPdfProjectDocument = openPdfProjectDocument;
window._goToPage = _goToPage;
window._rotateOrgCard = _rotateOrgCard;
window._duplicateOrgCard = _duplicateOrgCard;
window._deleteOrgCard = _deleteOrgCard;
window._moveOrgCard = _moveOrgCard;
window._jumpToSearchResult = _jumpToSearchResult;
window._removeExistingModal = _removeExistingModal;
window._askAiQuick = _askAiQuick;
window._clearAiChat = _clearAiChat;
window._sendAiQuestion = _sendAiQuestion;

