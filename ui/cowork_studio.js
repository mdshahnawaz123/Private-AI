/* ==========================================================================
   EXPO DESIGN AI — MINIMALIST ENGINEERING WORKSPACE (ui/cowork_studio.js)
   Redesigned to match the clean, minimalist, spacious appearance of the
   Claude Code / Desktop reference interface (media_1792425445604_d7208ed9.png)
   while preserving Expo Design AI's engineering identity and all existing backend features.
   ========================================================================== */

(function () {
  'use strict';

  const CWS_STATE = {
    open: true,
    theme: localStorage.getItem('expo_cws_theme') || 'light',
    sidebarCollapsed: false,
    drawerOpen: false,
    activeNav: 'chats', // 'home' | 'projects' | 'chats' | 'knowledge' | 'tools' | 'reports' | 'automations' | 'settings'
    searchQuery: '',
    projectSearchQuery: '',
    webSearchActive: false,
    deepResearchActive: false,
    activeFolder: '', // '' = root workspace
    activeSessionId: null,
    sessions: null,
    customInstructions: {},
    scheduledTasks: [],
    tree: { folders: [], files: [], total_folders: 0, total_files: 0 },
    previewFile: null,
    artifactCategory: 'all',
    streaming: false,
    selectedModel: localStorage.getItem('expo_cws_model') || 'qwen3.5:9b',
    reasoningEffort: localStorage.getItem('expo_cws_effort') || 'Low',
    executionMode: localStorage.getItem('expo_cws_mode') || 'Auto',
    recentsSort: 'desc',
    sectionsCollapsed: { pinned: false, recents: false },
    attachedFiles: [],
    composerModeSeg: 'chat',
  };

  window.CWS_STATE = CWS_STATE;

  let cwsAbortController = null;

  function getProj() {
    if (window.currentProject) return window.currentProject;
    const sel = document.getElementById('projSel');
    if (sel && sel.value) return sel.value;
    if (sel && sel.options && sel.options.length) return sel.options[0].value;
    return '';
  }

  function storageKey(suffix) {
    const p = getProj() || 'default';
    return `expo_cws_${p}_${suffix}`;
  }

  function getAuthToken() {
    return window.authToken || null || '';
  }

  function getAuthHeaders(extra) {
    const token = getAuthToken();
    const h = Object.assign({}, extra || {});
    if (token) h['Authorization'] = 'Bearer ' + token;
    return h;
  }

  const DEFAULT_RECENTS = [];

  function loadLocalData() {
    try {
      const rawSess = localStorage.getItem(storageKey('sessions'));
      CWS_STATE.sessions = rawSess !== null ? JSON.parse(rawSess) : null;
    } catch (e) {
      CWS_STATE.sessions = null;
    }

    if (CWS_STATE.sessions === null) {
      CWS_STATE.sessions = DEFAULT_RECENTS.map((item, idx) => ({
        id: item.id || ('sess-' + (Date.now() - idx * 3600000)),
        title: item.title,
        folder: item.folder || '',
        timeBadge: item.time,
        updatedAt: Date.now() - idx * 3600000,
        messages: []
      }));
    }

    CWS_STATE.sessions = CWS_STATE.sessions.filter(s => !( /^rec-[1-8]$/.test(s.id) && !(s.messages || []).length));

    try {
      const rawInst = localStorage.getItem(storageKey('instructions'));
      CWS_STATE.customInstructions = rawInst ? JSON.parse(rawInst) : {};
    } catch (e) {
      CWS_STATE.customInstructions = {};
    }

    try {
      const rawSched = localStorage.getItem(storageKey('scheduled'));
      CWS_STATE.scheduledTasks = rawSched ? JSON.parse(rawSched) : [];
    } catch (e) {
      CWS_STATE.scheduledTasks = [];
    }

    if (!CWS_STATE.activeSessionId || !CWS_STATE.sessions.find(s => s.id === CWS_STATE.activeSessionId)) {
      if (CWS_STATE.sessions && CWS_STATE.sessions.length) {
        CWS_STATE.activeSessionId = CWS_STATE.sessions[0].id;
      } else {
        CWS_STATE.activeSessionId = 'sess-' + Date.now();
      }
    }
  }

  function saveLocalData() {
    try {
      localStorage.setItem(storageKey('sessions'), JSON.stringify(CWS_STATE.sessions || []));
      localStorage.setItem(storageKey('instructions'), JSON.stringify(CWS_STATE.customInstructions));
      localStorage.setItem(storageKey('scheduled'), JSON.stringify(CWS_STATE.scheduledTasks));
    } catch (e) {}
  }

  function escHtml(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function escAttr(s) {
    return escHtml(s).replace(/'/g, '&#39;');
  }

  function fmtBytes(b) {
    const n = Number(b) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(2) + ' MB';
  }

  function getActiveSession() {
    if (!CWS_STATE.sessions) CWS_STATE.sessions = [];
    let s = CWS_STATE.sessions.find(x => x.id === CWS_STATE.activeSessionId);
    if (!s) {
      s = {
        id: 'sess-' + Date.now(),
        title: 'New chat',
        timeBadge: 'Just now',
        folder: CWS_STATE.activeFolder || '',
        updatedAt: Date.now(),
        messages: []
      };
      CWS_STATE.sessions.unshift(s);
      CWS_STATE.activeSessionId = s.id;
    }
    return s;
  }

  function formatTimeAgo(ts) {
    if (!ts) return '';
    const diff = Math.max(0, Date.now() - ts);
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'Just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  }

  /* --------------------------------------------------------------------------
     SVG ICON LIBRARY
     -------------------------------------------------------------------------- */
  const ICONS = {
    sidebarToggle: `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><line x1="9" y1="3" x2="9" y2="21"/></svg>`,
    splitView: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="3" x2="12" y2="21"/></svg>`,
    arrowLeft: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`,
    arrowRight: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`,
    plus: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
    home: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
    projects: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`,
    chats: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
    knowledge: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>`,
    tools: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    reports: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`,
    automations: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
    settings: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    doc: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
    search: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
    bell: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`,
    sun: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`,
    globe: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`,
    folder: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`,
    research: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
    mic: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>`,
    send: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>`,
    stop: `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`,
    dots: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>`,
    sort: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 15l5 5 5-5"/><path d="M7 9l5-5 5 5"/></svg>`,
    trash: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`,
    chevronRight: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`,
    chevronDown: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`,
    starburst: `<svg width="42" height="42" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M18 3L20.6 13.4L31 16L20.6 18.6L18 29L15.4 18.6L5 16L15.4 13.4L18 3Z" fill="#c96442" fill-opacity="0.14" stroke="#c96442" stroke-width="1.6" stroke-linejoin="round"/><circle cx="18" cy="16" r="2.8" fill="#c96442"/><path d="M8.2 6.2L11.8 9.8M27.8 6.2L24.2 9.8M8.2 25.8L11.8 22.2M27.8 25.8L24.2 22.2" stroke="#c96442" stroke-width="1.4" stroke-linecap="round"/></svg>`,
  };

  /* --------------------------------------------------------------------------
     CSS INJECTION (Clean, Minimalist, Off-White / Neutral Claude Styling)
     -------------------------------------------------------------------------- */
  function injectStyles() {
    if (document.getElementById('cwsStyles')) return;
    const st = document.createElement('style');
    st.id = 'cwsStyles';
    st.textContent = `
      /* Top Mode Switcher in Classic Bar */
      .cws-mode-switch {
        display: inline-flex;
        align-items: center;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.16);
        border-radius: 8px;
        padding: 2px;
        gap: 2px;
        margin-right: 6px;
      }
      .cws-mode-btn {
        border: none;
        background: transparent;
        color: #94a3b8;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11.5px;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 5px;
        transition: all .15s;
      }
      .cws-mode-btn:hover { color: #fff; }
      .cws-mode-btn.active {
        background: #2563eb;
        color: #fff;
        box-shadow: 0 2px 6px rgba(37,99,235,0.35);
      }

      /* Full-Screen Cowork Studio Overlay */
      #coworkStudioOverlay {
        position: fixed;
        inset: 0;
        z-index: 9999;
        display: flex;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        background: #ffffff;
        color: #18181b;
        -webkit-font-smoothing: antialiased;
        overflow: hidden;
      }
      #coworkStudioOverlay[hidden] { display: none !important; }

      /* Light Theme (Default - Clean off-white & minimalist palette) */
      #coworkStudioOverlay {
        --cws-bg: #ffffff;
        --cws-sb-bg: #fbfbfa;
        --cws-surface: #ffffff;
        --cws-surface-hover: #f5f5f4;
        --cws-surface-active: #ececeb;
        --cws-border: #e8e8e7;
        --cws-border-light: #f2f2f1;
        --cws-text: #18181b;
        --cws-text-sec: #52525b;
        --cws-muted: #71717a;
        --cws-faint: #a1a1aa;
        --cws-accent: #c96442;
        --cws-accent-light: #fbf4f1;
        --cws-accent-hover: #b85434;
        --cws-user-bub: #f4f4f5;
        --cws-shadow-sm: 0 1px 3px rgba(0,0,0,0.03);
        --cws-shadow-composer: 0 2px 14px rgba(0,0,0,0.04);
        --cws-shadow-lg: 0 12px 36px rgba(0,0,0,0.08);
        --cws-code-bg: #18181b;
        --cws-avatar-bg: #ede9fe;
        --cws-avatar-text: #6d28d9;
      }

      /* Dark Theme Optional */
      #coworkStudioOverlay.theme-dark {
        --cws-bg: #0f1117;
        --cws-sb-bg: #161821;
        --cws-surface: #1a1d29;
        --cws-surface-hover: #232736;
        --cws-surface-active: #2b3042;
        --cws-border: #2c3144;
        --cws-border-light: #202433;
        --cws-text: #f4f4f5;
        --cws-text-sec: #d4d4d8;
        --cws-muted: #a1a1aa;
        --cws-faint: #71717a;
        --cws-accent: #e07a5f;
        --cws-accent-light: rgba(224,122,95,0.18);
        --cws-accent-hover: #f28b6d;
        --cws-user-bub: #232736;
        --cws-shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
        --cws-shadow-composer: 0 4px 24px rgba(0,0,0,0.5);
        --cws-shadow-lg: 0 12px 36px rgba(0,0,0,0.65);
        --cws-code-bg: #0b0d13;
        --cws-avatar-bg: #3b2866;
        --cws-avatar-text: #d8b4fe;
      }

      /* Scrollbars */
      #coworkStudioOverlay *::-webkit-scrollbar {
        width: 6px;
        height: 6px;
      }
      #coworkStudioOverlay *::-webkit-scrollbar-thumb {
        background: #e2e2e0;
        border-radius: 4px;
      }
      #coworkStudioOverlay.theme-dark *::-webkit-scrollbar-thumb {
        background: #383e54;
      }
      #coworkStudioOverlay *::-webkit-scrollbar-track {
        background: transparent;
      }

      /* ==========================================================================
         A. LEFT SIDEBAR (Collapsible, Slim, Minimalist)
         ========================================================================== */
      .cws-sidebar {
        width: 250px;
        min-width: 250px;
        max-width: 250px;
        background: var(--cws-sb-bg);
        border-right: 1px solid var(--cws-border);
        display: flex;
        flex-direction: column;
        user-select: none;
        transition: margin-left 0.22s cubic-bezier(0.16, 1, 0.3, 1), transform 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        height: 100%;
        max-height: 100%;
        min-height: 0;
        position: relative;
        z-index: 20;
      }
      .cws-sidebar.collapsed {
        margin-left: -250px;
      }

      /* Sidebar Top Tool Bar */
      .cws-sb-top-bar {
        height: 44px;
        padding: 0 10px;
        display: flex;
        align-items: center;
        gap: 3px;
        border-bottom: 1px solid var(--cws-border-light);
      }
      .cws-sb-tool-btn {
        width: 28px;
        height: 28px;
        border-radius: 6px;
        border: none;
        background: transparent;
        color: var(--cws-muted);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: all 0.12s;
      }
      .cws-sb-tool-btn:hover {
        background: var(--cws-surface-hover);
        color: var(--cws-text);
      }

      /* Sidebar Brand Row */
      .cws-brand-row {
        padding: 8px 12px 6px;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .cws-brand-left {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
      }
      .cws-logo-bars {
        display: flex;
        align-items: flex-end;
        gap: 2.5px;
        height: 20px;
      }
      .cws-logo-bar {
        width: 3.5px;
        border-radius: 2px;
      }
      .cws-logo-bar:nth-child(1) { height: 13px; background: #c96442; }
      .cws-logo-bar:nth-child(2) { height: 20px; background: #e07a5f; }
      .cws-logo-bar:nth-child(3) { height: 16px; background: #d97706; }
      .cws-logo-bar:nth-child(4) { height: 11px; background: #b45309; }

      .cws-brand-text {
        display: flex;
        flex-direction: column;
      }
      .cws-brand-title {
        font-size: 13.5px;
        font-weight: 700;
        color: var(--cws-text);
        line-height: 1.2;
        letter-spacing: -0.01em;
      }
      .cws-brand-sub {
        font-size: 10.5px;
        color: var(--cws-muted);
        line-height: 1.2;
      }

      /* Sidebar Actions Row: Search + New Chat Pill */
      .cws-sb-actions-row {
        padding: 4px 10px 8px;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .cws-sb-search-box {
        flex: 1;
        display: flex;
        align-items: center;
        gap: 6px;
        background: #ffffff;
        border: 1px solid var(--cws-border);
        border-radius: 8px;
        padding: 5px 8px;
        font-size: 12px;
        color: var(--cws-muted);
        transition: all 0.12s;
      }
      #coworkStudioOverlay.theme-dark .cws-sb-search-box {
        background: #1a1d29;
      }
      .cws-sb-search-box:focus-within {
        border-color: #cbd5e1;
        box-shadow: 0 0 0 2px rgba(0,0,0,0.03);
      }
      .cws-sb-search-box input {
        border: none;
        background: transparent;
        outline: none;
        font-size: 12px;
        color: var(--cws-text);
        width: 100%;
      }
      .cws-sb-new-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background: #f0f0ee;
        color: #18181b;
        border: 1px solid #e5e5e3;
        border-radius: 8px;
        padding: 5px 10px;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.12s;
        flex-shrink: 0;
      }
      #coworkStudioOverlay.theme-dark .cws-sb-new-pill {
        background: #232736;
        color: #f4f4f5;
        border-color: #2c3144;
      }
      .cws-sb-new-pill:hover {
        background: #e6e6e3;
      }
      #coworkStudioOverlay.theme-dark .cws-sb-new-pill:hover {
        background: #2b3042;
      }

      /* Primary Navigation Menu */
      .cws-nav-list {
        padding: 2px 8px;
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .cws-nav-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 9px;
        border-radius: 7px;
        font-size: 12.5px;
        font-weight: 500;
        color: var(--cws-text-sec);
        background: transparent;
        border: none;
        cursor: pointer;
        transition: all 0.12s;
        width: 100%;
        text-align: left;
      }
      .cws-nav-item:hover {
        background: var(--cws-surface-hover);
        color: var(--cws-text);
      }
      .cws-nav-item.active {
        background: #f0f0ee;
        color: var(--cws-text);
        font-weight: 600;
      }
      #coworkStudioOverlay.theme-dark .cws-nav-item.active {
        background: #232736;
      }
      .cws-nav-left {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .cws-nav-chevron {
        color: var(--cws-faint);
        display: flex;
        align-items: center;
      }

      /* Collapsible Sections (Pinned, Recents) */
      .cws-sb-section {
        margin-top: 6px;
        padding: 0 8px;
        display: flex;
        flex-direction: column;
      }
      .cws-sb-sec-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 5px 8px;
        font-size: 11.5px;
        font-weight: 600;
        color: var(--cws-muted);
        cursor: pointer;
        border-radius: 6px;
        user-select: none;
      }
      .cws-sb-sec-head:hover {
        background: var(--cws-surface-hover);
        color: var(--cws-text);
      }
      .cws-sec-chev {
        display: inline-flex;
        align-items: center;
        transition: transform 0.15s ease;
      }
      .cws-sec-collapsed .cws-sec-chev {
        transform: rotate(-90deg);
      }
      .cws-sb-sort-btn {
        border: none;
        background: transparent;
        color: var(--cws-muted);
        cursor: pointer;
        padding: 2px 4px;
        border-radius: 4px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: all 0.12s;
      }
      .cws-sb-sort-btn:hover {
        color: var(--cws-text);
        background: var(--cws-border);
      }

      /* Recent Chats List with Delete Option */
      .cws-recents-list {
        display: flex;
        flex-direction: column;
        gap: 1px;
        padding: 2px 0 6px;
        overflow-y: auto;
      }
      .cws-recent-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
        padding: 5.5px 8px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 12px;
        color: var(--cws-text-sec);
        text-decoration: none;
        width: 100%;
        border: none;
        background: transparent;
        text-align: left;
        transition: all 0.12s;
        position: relative;
      }
      .cws-recent-row:hover {
        background: var(--cws-surface-hover);
        color: var(--cws-text);
      }
      .cws-recent-row.active {
        background: #f0f0ee;
        color: var(--cws-text);
        font-weight: 600;
      }
      #coworkStudioOverlay.theme-dark .cws-recent-row.active {
        background: #232736;
      }
      .cws-recent-left {
        display: flex;
        align-items: center;
        gap: 7px;
        min-width: 0;
        flex: 1;
      }
      .cws-recent-ico {
        color: var(--cws-muted);
        display: flex;
        align-items: center;
        flex-shrink: 0;
      }
      .cws-recent-title {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: 12px;
      }
      .cws-recent-time {
        font-size: 10.5px;
        color: var(--cws-faint);
        flex-shrink: 0;
      }
      .cws-recent-del-btn {
        display: none;
        align-items: center;
        justify-content: center;
        width: 20px;
        height: 20px;
        border-radius: 4px;
        border: none;
        background: transparent;
        color: var(--cws-muted);
        cursor: pointer;
        padding: 0;
        margin-left: 2px;
        transition: all 0.12s;
        flex-shrink: 0;
      }
      .cws-recent-row:hover .cws-recent-del-btn {
        display: inline-flex;
      }
      .cws-recent-row:hover .cws-recent-time {
        display: none;
      }
      .cws-recent-del-btn:hover {
        background: #fee2e2;
        color: #dc2626;
      }
      #coworkStudioOverlay.theme-dark .cws-recent-del-btn:hover {
        background: #451a1a;
        color: #f87171;
      }

      /* User Profile Footer */
      .cws-profile-footer {
        margin-top: auto;
        padding: 9px 12px;
        border-top: 1px solid var(--cws-border);
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: var(--cws-sb-bg);
        cursor: pointer;
        transition: background 0.12s;
      }
      .cws-profile-footer:hover {
        background: var(--cws-surface-hover);
      }
      .cws-avatar-circle {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: var(--cws-avatar-bg);
        color: var(--cws-avatar-text);
        font-size: 11px;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .cws-profile-info {
        display: flex;
        flex-direction: column;
        min-width: 0;
        margin-left: 8px;
        flex: 1;
      }
      .cws-profile-name {
        font-size: 12px;
        font-weight: 600;
        color: var(--cws-text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.25;
      }
      .cws-profile-role {
        font-size: 10.5px;
        color: var(--cws-muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.25;
        display: flex;
        align-items: center;
        gap: 3px;
      }

      /* ==========================================================================
         B. TOP COMPACT HEADER (Clean, Minimalist, No Default Hardcoded Text)
         ========================================================================== */
      .cws-main {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
        background: var(--cws-bg);
        height: 100%;
        max-height: 100%;
        min-height: 0;
        position: relative;
        overflow: hidden;
      }
      .cws-header {
        height: 48px;
        padding: 0 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid var(--cws-border);
        background: var(--cws-surface);
        flex-shrink: 0;
        z-index: 10;
      }
      .cws-header-right {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-left: auto;
      }
      .cws-header-search {
        display: flex;
        align-items: center;
        gap: 6px;
        background: var(--cws-sb-bg);
        border: 1px solid var(--cws-border);
        border-radius: 18px;
        padding: 4px 12px;
        width: 200px;
        transition: all .15s;
      }
      .cws-header-search:focus-within {
        border-color: #cbd5e1;
        background: #ffffff;
        box-shadow: 0 0 0 2px rgba(0,0,0,0.03);
      }
      .cws-header-search svg {
        color: var(--cws-faint);
        flex-shrink: 0;
      }
      .cws-header-search input {
        border: none;
        background: transparent;
        outline: none;
        color: var(--cws-text);
        font-size: 12px;
        width: 100%;
      }
      .cws-icon-btn {
        background: transparent;
        border: none;
        color: var(--cws-muted);
        width: 28px;
        height: 28px;
        border-radius: 6px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: background .12s, color .12s;
        flex-shrink: 0;
      }
      .cws-icon-btn:hover {
        background: var(--cws-surface-hover);
        color: var(--cws-text);
      }

      /* Generic Buttons */
      .cws-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        padding: 5px 11px;
        border-radius: 7px;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.12s;
        border: 1px solid var(--cws-border);
        background: var(--cws-surface);
        color: var(--cws-text);
      }
      .cws-btn:hover {
        background: var(--cws-surface-hover);
      }
      .cws-btn.primary {
        background: var(--cws-accent);
        color: #ffffff;
        border-color: var(--cws-accent);
      }
      .cws-btn.primary:hover {
        background: var(--cws-accent-hover);
      }

      /* ==========================================================================
         C. MAIN WORKSPACE & WELCOME SCREEN
         ========================================================================== */
      .cws-stage-body {
        flex: 1 1 0;
        min-height: 0;
        max-height: 100%;
        overflow-y: auto;
        padding: 16px 20px 20px;
        display: flex;
        flex-direction: column;
        align-items: center;
        position: relative;
      }

      /* Welcome Screen Hero */
      .cws-welcome-stage {
        width: 100%;
        max-width: 760px;
        margin: auto;
        padding: 32px 16px 24px;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        animation: cwsFadeIn 0.25s ease-out;
      }
      @keyframes cwsFadeIn {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
      }
      .cws-hero-emblem {
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 14px;
      }
      .cws-hero-heading {
        margin: 0;
        font-family: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
        font-size: 32px;
        font-weight: 500;
        color: #18181b;
        letter-spacing: -0.015em;
        line-height: 1.25;
      }
      #coworkStudioOverlay.theme-dark .cws-hero-heading {
        color: #f4f4f5;
      }
      .cws-hero-subtitle {
        margin: 6px 0 0;
        font-size: 14.5px;
        color: var(--cws-muted);
      }
      .cws-hero-badge {
        margin-top: 12px;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #f7f7f6;
        border: 1px solid #eaeaea;
        border-radius: 16px;
        padding: 4px 11px;
        font-size: 11.5px;
        color: #52525b;
      }
      #coworkStudioOverlay.theme-dark .cws-hero-badge {
        background: #1a1d29;
        border-color: #2c3144;
        color: #d4d4d8;
      }
      .cws-hero-dot {
        width: 6.5px;
        height: 6.5px;
        border-radius: 50%;
        background: #16a34a;
        box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.15);
      }
      .cws-hero-composer-slot {
        width: 100%;
        max-width: 720px;
        margin-top: 22px;
      }

      /* Quick-Start Suggestions Grid */
      .cws-quick-wrap {
        width: 100%;
        max-width: 720px;
        margin-top: 22px;
      }
      .cws-quick-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 9px;
        width: 100%;
      }
      @media (max-width: 720px) {
        .cws-quick-grid {
          grid-template-columns: 1fr;
        }
      }
      .cws-quick-card {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        background: #ffffff;
        border: 1px solid var(--cws-border);
        border-radius: 12px;
        padding: 10px 13px;
        text-align: left;
        cursor: pointer;
        transition: all 0.14s ease;
        width: 100%;
      }
      #coworkStudioOverlay.theme-dark .cws-quick-card {
        background: #1a1d29;
      }
      .cws-quick-card:hover {
        background: #f9f9f8;
        border-color: #d4d4d2;
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(0,0,0,0.03);
      }
      #coworkStudioOverlay.theme-dark .cws-quick-card:hover {
        background: #232736;
        border-color: #383e54;
      }
      .cws-quick-icon {
        font-size: 16px;
        line-height: 1.2;
        flex-shrink: 0;
      }
      .cws-quick-details {
        display: flex;
        flex-direction: column;
        min-width: 0;
      }
      .cws-quick-title {
        font-size: 12.5px;
        font-weight: 600;
        color: var(--cws-text);
      }
      .cws-quick-sub {
        font-size: 11px;
        color: var(--cws-muted);
        margin-top: 1px;
      }

      /* ==========================================================================
         D. CHAT COMPOSER (Modern, Rounded, Responsive)
         ========================================================================== */
      .cws-composer-wrap {
        width: 100%;
        padding: 8px 20px 18px;
        display: flex;
        justify-content: center;
        flex-shrink: 0;
        background: linear-gradient(180deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.92) 20%, #ffffff 100%);
        z-index: 20;
        position: sticky;
        bottom: 0;
      }
      #coworkStudioOverlay.theme-dark .cws-composer-wrap {
        background: linear-gradient(180deg, rgba(15,17,23,0) 0%, rgba(15,17,23,0.92) 20%, #0f1117 100%);
      }
      .cws-composer-wrap.in-hero {
        padding: 0;
        background: transparent;
      }
      .cws-composer-inner {
        width: 100%;
        max-width: 720px;
        display: flex;
        flex-direction: column;
      }
      .cws-composer-card {
        width: 100%;
        background: #ffffff;
        border: 1px solid #e5e5e4;
        border-radius: 16px;
        box-shadow: var(--cws-shadow-composer);
        display: flex;
        flex-direction: column;
        padding: 12px 14px 10px;
        transition: border-color 0.15s, box-shadow 0.15s;
        position: relative;
      }
      #coworkStudioOverlay.theme-dark .cws-composer-card {
        background: #1a1d29;
        border-color: #2c3144;
      }
      .cws-composer-card:focus-within {
        border-color: #c5c5c3;
        box-shadow: 0 2px 20px rgba(0,0,0,0.06);
      }
      #coworkStudioOverlay.theme-dark .cws-composer-card:focus-within {
        border-color: #4b526d;
      }
      .cws-composer-ta {
        width: 100%;
        border: none;
        background: transparent;
        outline: none;
        color: var(--cws-text);
        font-size: 14.5px;
        line-height: 1.5;
        resize: none;
        min-height: 32px;
        max-height: 180px;
        font-family: inherit;
        padding: 2px 4px 6px;
      }
      .cws-composer-ta::placeholder {
        color: #a1a1aa;
      }
      .cws-composer-bottom-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 6px;
        padding-top: 4px;
      }
      .cws-cb-left {
        display: flex;
        align-items: center;
        gap: 5px;
      }
      .cws-cb-right {
        display: flex;
        align-items: center;
        gap: 5px;
      }
      .cws-cb-icon-btn {
        width: 28px;
        height: 28px;
        border-radius: 7px;
        border: 1px solid transparent;
        background: transparent;
        color: #71717a;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: all 0.12s;
      }
      .cws-cb-icon-btn:hover {
        background: #f4f4f3;
        color: #18181b;
      }
      #coworkStudioOverlay.theme-dark .cws-cb-icon-btn:hover {
        background: #232736;
        color: #f4f4f5;
      }
      .cws-cb-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 8px;
        border-radius: 7px;
        border: 1px solid #e8e8e7;
        background: #ffffff;
        color: #3f3f46;
        font-size: 11.5px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.12s;
        user-select: none;
      }
      #coworkStudioOverlay.theme-dark .cws-cb-pill {
        background: #1a1d29;
        border-color: #2c3144;
        color: #d4d4d8;
      }
      .cws-cb-pill:hover {
        background: #f8f8f7;
        border-color: #d8d8d6;
        color: #18181b;
      }
      #coworkStudioOverlay.theme-dark .cws-cb-pill:hover {
        background: #232736;
        color: #f4f4f5;
      }
      .cws-cb-pill-chev {
        color: #a1a1aa;
        display: flex;
        align-items: center;
      }
      .cws-cb-send-btn {
        width: 30px;
        height: 30px;
        border-radius: 50%;
        border: none;
        background: #c96442;
        color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: all 0.14s ease;
        flex-shrink: 0;
        box-shadow: 0 1px 4px rgba(201, 100, 66, 0.3);
      }
      .cws-cb-send-btn:hover {
        background: #b55333;
        transform: scale(1.05);
      }
      .cws-cb-send-btn.is-disabled {
        background: #f4f4f5 !important;
        color: #a1a1aa !important;
        cursor: not-allowed;
        transform: none !important;
        box-shadow: none !important;
      }
      #coworkStudioOverlay.theme-dark .cws-cb-send-btn.is-disabled {
        background: #232736 !important;
        color: #71717a !important;
      }
      .cws-cb-send-btn.is-stopping {
        background: #dc2626 !important;
        color: #ffffff !important;
        box-shadow: 0 1px 4px rgba(220, 38, 38, 0.3) !important;
      }

      /* Attachment Preview Cards in Composer (Matches Reference Image 3) */
      .cws-composer-attachments {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
        padding: 4px 2px 12px;
        width: 100%;
      }
      .cws-attachment-card {
        position: relative;
        width: 98px;
        height: 128px;
        border-radius: 8px;
        border: 1px solid #e2e8f0;
        background: #ffffff;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.03);
        overflow: hidden;
        cursor: pointer;
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        flex-shrink: 0;
        user-select: none;
      }
      #coworkStudioOverlay.theme-dark .cws-attachment-card {
        background: #1a1d29;
        border-color: #2c3144;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
      }
      .cws-attachment-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.09);
        border-color: #cbd5e1;
      }
      #coworkStudioOverlay.theme-dark .cws-attachment-card:hover {
        border-color: #4b5563;
      }
      .cws-attachment-thumb-wrap {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #fbfbfc;
        overflow: hidden;
        position: relative;
      }
      #coworkStudioOverlay.theme-dark .cws-attachment-thumb-wrap {
        background: #151821;
      }
      .cws-attachment-thumb-img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        object-position: top center;
        display: block;
      }
      .cws-attachment-skeleton {
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        padding: 12px 10px;
        gap: 6px;
        background: #ffffff;
        box-sizing: border-box;
      }
      #coworkStudioOverlay.theme-dark .cws-attachment-skeleton {
        background: #1a1d29;
      }
      .cws-att-sk-line {
        height: 4px;
        border-radius: 2px;
        background: #e2e8f0;
      }
      #coworkStudioOverlay.theme-dark .cws-att-sk-line {
        background: #2d3345;
      }
      .cws-attachment-badge {
        position: absolute;
        bottom: 6px;
        left: 6px;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid #e2e8f0;
        border-radius: 5px;
        padding: 1.5px 5.5px;
        font-size: 9.5px;
        font-weight: 800;
        color: #18181b;
        letter-spacing: 0.5px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
        pointer-events: none;
        z-index: 2;
      }
      #coworkStudioOverlay.theme-dark .cws-attachment-badge {
        background: rgba(26, 29, 41, 0.95);
        border-color: #2c3144;
        color: #f4f4f5;
      }
      .cws-attachment-remove {
        position: absolute;
        top: 5px;
        right: 5px;
        width: 19px;
        height: 19px;
        border-radius: 50%;
        background: rgba(24, 24, 27, 0.75);
        color: #ffffff;
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        line-height: 1;
        opacity: 0;
        transition: opacity 0.14s ease, background 0.12s;
        z-index: 3;
      }
      .cws-attachment-card:hover .cws-attachment-remove {
        opacity: 1;
      }
      .cws-attachment-remove:hover {
        background: #dc2626 !important;
      }
      .cws-attachment-spinner {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(255, 255, 255, 0.7);
        z-index: 1;
      }
      #coworkStudioOverlay.theme-dark .cws-attachment-spinner {
        background: rgba(26, 29, 41, 0.7);
      }
      .cws-spinner-dot {
        width: 16px;
        height: 16px;
        border: 2px solid #e2e8f0;
        border-top-color: #c96442;
        border-radius: 50%;
        animation: cwsSpin 0.75s linear infinite;
      }
      @keyframes cwsSpin {
        to { transform: rotate(360deg); }
      }
      .cws-composer-card.is-drag-over {
        border-color: #c96442 !important;
        background: #fffcfb !important;
        box-shadow: 0 0 0 2px rgba(201, 100, 66, 0.18) !important;
      }
      #coworkStudioOverlay.theme-dark .cws-composer-card.is-drag-over {
        background: #231e22 !important;
      }

      /* Segmented Mode Button [ Chat | Cowork ] in Composer Bottom Bar */
      .cws-mode-segmented {
        display: inline-flex;
        align-items: center;
        background: #f0f0ee;
        border: 1px solid #e5e5e3;
        border-radius: 20px;
        padding: 2px;
        gap: 2px;
        margin-left: 2px;
      }
      #coworkStudioOverlay.theme-dark .cws-mode-segmented {
        background: #232736;
        border-color: #2c3144;
      }
      .cws-mode-seg-btn {
        border: none;
        background: transparent;
        padding: 3px 10px;
        border-radius: 16px;
        font-size: 11.5px;
        font-weight: 500;
        color: #71717a;
        cursor: pointer;
        transition: all 0.12s;
        font-family: inherit;
        line-height: 1.2;
      }
      .cws-mode-seg-btn:hover {
        color: #18181b;
      }
      #coworkStudioOverlay.theme-dark .cws-mode-seg-btn:hover {
        color: #f4f4f5;
      }
      .cws-mode-seg-btn.active {
        background: #ffffff;
        color: #18181b;
        font-weight: 600;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
      }
      #coworkStudioOverlay.theme-dark .cws-mode-seg-btn.active {
        background: #1a1d29;
        color: #f4f4f5;
      }

      /* Attached Cards in User Message Bubble */
      .cws-msg-attachments {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }
      .cws-msg-att-card {
        position: relative;
        width: 90px;
        height: 118px;
        border-radius: 7px;
        border: 1px solid #e2e8f0;
        background: #ffffff;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        overflow: hidden;
        cursor: pointer;
        transition: transform 0.12s, box-shadow 0.12s;
        flex-shrink: 0;
      }
      .cws-msg-att-card:hover {
        transform: translateY(-1.5px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.1);
      }

      /* Image 2: Composer Subbar & Project / Folder Dropdown */
      .cws-composer-subbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 8px;
        width: 100%;
        padding: 0 4px;
      }
      .cws-composer-subbar-right {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .cws-cb-sub-btn {
        background: transparent;
        border: none;
        font-size: 13px;
        color: #71717a;
        font-weight: 500;
        cursor: pointer;
        padding: 4px 6px;
        border-radius: 6px;
        transition: all 0.12s;
        user-select: none;
        font-family: inherit;
      }
      .cws-cb-sub-btn:hover {
        color: var(--cws-text);
        background: var(--cws-surface-hover);
      }
      .cws-proj-dropdown-anchor {
        position: relative;
        display: inline-block;
      }
      .cws-cb-pill.is-open {
        background: #f0f0ee !important;
        border-color: #d0d0ce !important;
      }
      #coworkStudioOverlay.theme-dark .cws-cb-pill.is-open {
        background: #2a2f42 !important;
        border-color: #3b425b !important;
      }
      .cws-proj-dropdown-menu {
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        width: 275px;
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        box-shadow: 0 12px 28px -4px rgba(0, 0, 0, 0.12), 0 4px 8px -2px rgba(0, 0, 0, 0.04);
        z-index: 100;
        overflow: hidden;
        padding: 6px 0;
        font-family: inherit;
        animation: cwsModalPop 0.12s ease-out;
      }
      #coworkStudioOverlay.theme-dark .cws-proj-dropdown-menu {
        background: #1a1d29;
        border-color: #2c3144;
        box-shadow: 0 12px 28px -4px rgba(0, 0, 0, 0.5);
      }
      .cws-proj-dropdown-search {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px 6px;
      }
      .cws-proj-dropdown-search input {
        border: none;
        outline: none;
        background: transparent;
        font-size: 13.5px;
        color: var(--cws-text);
        flex: 1;
        font-family: inherit;
        min-width: 0;
      }
      .cws-proj-dropdown-search input::placeholder {
        color: #9ca3af;
      }
      .cws-proj-dropdown-divider {
        height: 1px;
        background: #f1f2f4;
        margin: 4px 0;
      }
      #coworkStudioOverlay.theme-dark .cws-proj-dropdown-divider {
        background: #272b3c;
      }
      .cws-proj-dropdown-section-title {
        font-size: 11.5px;
        font-weight: 600;
        color: #888888;
        padding: 4px 14px 4px;
        letter-spacing: 0.015em;
      }
      #coworkStudioOverlay.theme-dark .cws-proj-dropdown-section-title {
        color: #71717a;
      }
      .cws-proj-dropdown-list {
        max-height: 160px;
        overflow-y: auto;
        padding: 2px 0;
      }
      .cws-proj-dropdown-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 7px 14px;
        font-size: 13.5px;
        color: var(--cws-text);
        cursor: pointer;
        transition: background 0.1s;
        user-select: none;
      }
      .cws-proj-dropdown-item:hover {
        background: #f4f4f5;
      }
      #coworkStudioOverlay.theme-dark .cws-proj-dropdown-item:hover {
        background: #232736;
      }
      .cws-proj-dropdown-item.active {
        font-weight: 600;
      }
      .cws-proj-dropdown-item-name {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: 1;
      }
      .cws-proj-box-icon {
        flex-shrink: 0;
        color: #52525b;
      }
      #coworkStudioOverlay.theme-dark .cws-proj-box-icon {
        color: #a1a1aa;
      }
      .cws-proj-dropdown-action {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 14px;
        font-size: 13.5px;
        color: var(--cws-text);
        cursor: pointer;
        transition: background 0.1s;
        user-select: none;
        font-weight: 500;
      }
      .cws-proj-dropdown-action:hover {
        background: #f4f4f5;
      }
      #coworkStudioOverlay.theme-dark .cws-proj-dropdown-action:hover {
        background: #232736;
      }

      /* ==========================================================================
         E. CONVERSATION FLOW (User bubbles, Assistant markdown, Code blocks)
         ========================================================================== */
      .cws-stream-col {
        width: 100%;
        max-width: 720px;
        display: flex;
        flex-direction: column;
        gap: 20px;
        padding: 16px 0 32px;
      }
      .cws-msg-user {
        align-self: flex-end;
        max-width: 82%;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 5px;
      }
      .cws-msg-user-bub {
        background: var(--cws-user-bub);
        color: var(--cws-text);
        padding: 9px 15px;
        border-radius: 17px;
        font-size: 14px;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .cws-msg-ai {
        align-self: flex-start;
        width: 100%;
        font-size: 14px;
        line-height: 1.65;
        color: var(--cws-text);
        word-break: break-word;
      }
      .cws-msg-ai p {
        margin: 0 0 10px 0;
      }
      .cws-msg-ai h1, .cws-msg-ai h2, .cws-msg-ai h3, .cws-msg-ai h4 {
        margin: 18px 0 8px;
        font-weight: 600;
        color: var(--cws-text);
        line-height: 1.35;
      }
      .cws-msg-ai h1 { font-size: 19px; }
      .cws-msg-ai h2 {
        font-size: 16.5px;
        border-bottom: 1px solid var(--cws-border);
        padding-bottom: 5px;
      }
      .cws-msg-ai h3 { font-size: 15px; }
      .cws-msg-ai h4 { font-size: 13.5px; }
      .cws-msg-ai ul, .cws-msg-ai ol {
        margin: 8px 0 12px;
        padding-left: 22px;
      }
      .cws-msg-ai li {
        margin-bottom: 4px;
        line-height: 1.55;
      }
      .cws-msg-ai hr.cws-hr {
        border: none;
        border-top: 1px solid var(--cws-border);
        margin: 18px 0;
      }
      .cws-msg-ai blockquote {
        margin: 10px 0;
        padding: 8px 14px;
        border-left: 3px solid var(--cws-accent);
        background: var(--cws-accent-light);
        color: var(--cws-text-sec);
        border-radius: 0 6px 6px 0;
      }
      .cws-inline-code {
        background: var(--cws-surface-hover);
        color: var(--cws-accent);
        padding: 2px 5px;
        border-radius: 4px;
        font-family: Consolas, monospace;
        font-size: 12px;
        border: 1px solid var(--cws-border);
      }
      .cws-table-wrap {
        width: 100%;
        overflow-x: auto;
        margin: 14px 0;
        border-radius: 9px;
        border: 1px solid var(--cws-border);
        background: var(--cws-surface);
        box-shadow: 0 1px 3px rgba(0,0,0,0.02);
      }
      .cws-msg-ai table {
        width: 100%;
        border-collapse: collapse;
        margin: 0;
        font-size: 12.5px;
      }
      .cws-msg-ai th, .cws-msg-ai td {
        border-bottom: 1px solid var(--cws-border);
        border-right: 1px solid var(--cws-border);
        padding: 8px 12px;
        text-align: left;
        white-space: nowrap;
      }
      .cws-msg-ai th:last-child, .cws-msg-ai td:last-child {
        border-right: none;
      }
      .cws-msg-ai tr:last-child td {
        border-bottom: none;
      }
      .cws-msg-ai th {
        background: var(--cws-surface-hover);
        font-weight: 600;
        color: var(--cws-text);
      }
      .cws-msg-ai tr:hover td {
        background: rgba(0, 0, 0, 0.015);
      }
      #coworkStudioOverlay.theme-dark .cws-msg-ai tr:hover td {
        background: rgba(255, 255, 255, 0.02);
      }
      .cws-src-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 9px;
        border-radius: 6px;
        background: var(--cws-surface-hover);
        border: 1px solid var(--cws-border);
        color: var(--cws-text);
        font-size: 11.5px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.12s;
        margin: 2px 3px 2px 0;
        vertical-align: middle;
      }
      .cws-src-pill:hover {
        background: var(--cws-surface-active);
        border-color: var(--cws-accent);
        color: var(--cws-accent);
      }
      .cws-code-block {
        position: relative;
        background: var(--cws-code-bg);
        border-radius: 9px;
        margin: 12px 0;
        overflow: hidden;
      }
      .cws-code-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 12px;
        background: rgba(255,255,255,0.06);
        border-bottom: 1px solid rgba(255,255,255,0.08);
      }
      .cws-code-lang {
        font-size: 11px;
        font-weight: 600;
        color: #94a3b8;
        letter-spacing: 0.5px;
      }
      .cws-code-copy-btn {
        background: transparent;
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 5px;
        color: #cbd5e1;
        font-size: 11px;
        padding: 2px 7px;
        cursor: pointer;
        transition: all 0.12s;
      }
      .cws-code-copy-btn:hover {
        background: rgba(255,255,255,0.12);
        color: #ffffff;
      }

      /* Secondary Views Grids & Cards */
      .cws-grid-cards {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: 12px;
        margin-top: 14px;
        width: 100%;
      }
      .cws-card {
        background: var(--cws-surface);
        border: 1px solid var(--cws-border);
        border-radius: 10px;
        padding: 14px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        gap: 12px;
        transition: all 0.12s;
      }
      .cws-card:hover {
        border-color: #cbd5e1;
        box-shadow: var(--cws-shadow-sm);
      }

      /* Right Split-Pane Drawer (Artifact Inspector) */
      .cws-drawer {
        width: clamp(480px, 42vw, 760px);
        min-width: 480px;
        background: var(--cws-surface);
        border-left: 1px solid var(--cws-border);
        display: flex;
        flex-direction: column;
        height: 100vh;
        box-shadow: -4px 0 24px rgba(0,0,0,0.06);
        z-index: 50;
      }
      .cws-drawer[hidden] { display: none !important; }
      .cws-drawer-head {
        height: 48px;
        padding: 0 14px;
        border-bottom: 1px solid var(--cws-border);
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 13px;
        font-weight: 700;
        gap: 8px;
      }
      .cws-drawer-tabs {
        display: flex;
        gap: 3px;
        background: var(--cws-surface-hover);
        padding: 2.5px;
        border-radius: 7px;
        border: 1px solid var(--cws-border);
      }
      .cws-tab-btn {
        border: none;
        background: transparent;
        color: var(--cws-muted);
        padding: 3px 9px;
        border-radius: 5px;
        font-size: 11px;
        font-weight: 600;
        cursor: pointer;
        transition: all .12s;
      }
      .cws-tab-btn.active {
        background: var(--cws-surface);
        color: var(--cws-text);
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      }
      .cws-drawer-body {
        flex: 1;
        overflow-y: auto;
        padding: 14px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .cws-pdf-viewer {
        width: 100%;
        height: 100%;
        min-height: 480px;
        border: 1px solid var(--cws-border);
        border-radius: 8px;
      }
      .cws-code-editor {
        width: 100%;
        height: 380px;
        background: var(--cws-code-bg);
        color: #f8fafc;
        border: 1px solid var(--cws-border);
        border-radius: 8px;
        padding: 12px;
        font-family: Consolas, "Courier New", monospace;
        font-size: 12px;
        line-height: 1.5;
        resize: vertical;
        outline: none;
      }
    
      /* ==========================================================================
         PROJECTS VIEW & CREATE PROJECT MODAL (Matches 2nd Reference Screenshot)
         ========================================================================== */
      .cws-projects-wrapper {
        width: 100%;
        max-width: 960px;
        margin: 0 auto;
        padding: 24px 20px 48px;
        animation: cwsFadeIn 0.2s ease-out;
      }
      .cws-projects-top-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 24px;
        gap: 16px;
      }
      .cws-projects-title {
        font-family: Georgia, Cambria, "Times New Roman", Times, serif;
        font-size: 28px;
        font-weight: 500;
        color: var(--cws-text);
        margin: 0;
        letter-spacing: -0.015em;
      }
      .cws-projects-actions {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .cws-btn-new-project-pill {
        background: #000000;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 7px 15px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: opacity 0.15s, transform 0.1s;
      }
      .cws-btn-new-project-pill:hover {
        opacity: 0.88;
      }
      .cws-btn-new-project-pill:active {
        transform: scale(0.98);
      }
      #coworkStudioOverlay.theme-dark .cws-btn-new-project-pill {
        background: #ffffff;
        color: #000000;
      }
      .cws-project-cards-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 16px;
        margin-bottom: 32px;
      }
      .cws-project-card {
        background: var(--cws-card-bg);
        border: 1px solid var(--cws-border);
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        transition: border-color 0.15s, box-shadow 0.15s, transform 0.1s;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 120px;
        position: relative;
      }
      .cws-project-card:hover {
        border-color: #bbb;
        box-shadow: 0 4px 14px rgba(0,0,0,0.06);
        transform: translateY(-1px);
      }
      #coworkStudioOverlay.theme-dark .cws-project-card:hover {
        border-color: #4b5563;
        box-shadow: 0 4px 14px rgba(0,0,0,0.3);
      }
      .cws-proj-card-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .cws-proj-card-name {
        font-size: 15px;
        font-weight: 700;
        color: var(--cws-text);
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .cws-proj-star-btn {
        background: transparent;
        border: none;
        font-size: 14px;
        color: #d1d5db;
        cursor: pointer;
        padding: 0;
        line-height: 1;
        transition: color 0.12s, transform 0.12s;
      }
      .cws-proj-star-btn.active {
        color: #eab308;
      }
      .cws-proj-star-btn:hover {
        transform: scale(1.15);
      }
      .cws-proj-card-desc {
        font-size: 13px;
        color: var(--cws-muted);
        line-height: 1.45;
        margin: 8px 0 16px;
        overflow: hidden;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
      }
      .cws-proj-card-bottom {
        font-size: 11.5px;
        color: var(--cws-faint);
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: auto;
      }

      /* Create Project Modal Dialog (Matches 2nd reference image) */
      .cws-modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.45);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        backdrop-filter: blur(2px);
        animation: cwsFadeIn 0.15s ease-out;
      }
      .cws-modal-card {
        background: #ffffff;
        border-radius: 14px;
        width: 490px;
        max-width: 92vw;
        padding: 24px;
        box-shadow: 0 20px 45px rgba(0, 0, 0, 0.18);
        position: relative;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        animation: cwsModalPop 0.18s ease-out;
      }
      @keyframes cwsModalPop {
        from { opacity: 0; transform: scale(0.96) translateY(8px); }
        to { opacity: 1; transform: scale(1) translateY(0); }
      }
      #coworkStudioOverlay.theme-dark .cws-modal-card {
        background: #1a1c23;
        border: 1px solid #333;
        color: #eee;
      }
      .cws-modal-close-btn {
        background: none;
        border: none;
        font-size: 17px;
        color: #888;
        cursor: pointer;
        padding: 4px;
        line-height: 1;
        border-radius: 4px;
      }
      .cws-modal-close-btn:hover {
        color: #111;
        background: rgba(0,0,0,0.06);
      }
      #coworkStudioOverlay.theme-dark .cws-modal-close-btn:hover {
        color: #fff;
        background: rgba(255,255,255,0.1);
      }
      .cws-modal-input-blue {
        width: 100%;
        border: 1.5px solid #2563eb;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 14px;
        outline: none;
        box-sizing: border-box;
        background: var(--cws-input-bg);
        color: var(--cws-text);
        font-family: inherit;
        box-shadow: 0 0 0 1px rgba(37,99,235,0.2);
      }
      .cws-modal-textarea-desc {
        width: 100%;
        border: 1px solid #dcdcdc;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 13.5px;
        outline: none;
        box-sizing: border-box;
        background: var(--cws-input-bg);
        color: var(--cws-text);
        resize: vertical;
        font-family: inherit;
        line-height: 1.45;
      }
      .cws-modal-textarea-desc:focus {
        border-color: #2563eb;
      }
      #coworkStudioOverlay.theme-dark .cws-modal-textarea-desc {
        border-color: #3b4252;
      }
      .cws-context-toggle-btn {
        border: 1px solid #e0e0e0;
        background: transparent;
        border-radius: 8px;
        padding: 6px 12px;
        font-size: 12.5px;
        color: var(--cws-muted);
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        transition: all 0.12s;
      }
      .cws-context-toggle-btn:hover {
        background: var(--cws-surface-hover);
        color: var(--cws-text);
      }
      .cws-modal-cancel {
        background: transparent;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        color: var(--cws-text);
      }
      .cws-modal-cancel:hover {
        background: var(--cws-surface-hover);
      }
      .cws-modal-submit {
        background: #000000;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 8px 18px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.15s;
      }
      .cws-modal-submit:hover {
        opacity: 0.88;
      }
      #coworkStudioOverlay.theme-dark .cws-modal-submit {
        background: #ffffff;
        color: #000000;
      }
    `;

    document.head.appendChild(st);
  }

  /* --------------------------------------------------------------------------
     BUILD OVERLAY DOM (Claude Code/Desktop minimal layout)
     -------------------------------------------------------------------------- */
  function buildOverlayDOM() {
    if (document.getElementById('coworkStudioOverlay')) return;
    const ov = document.createElement('div');
    ov.id = 'coworkStudioOverlay';
    ov.className = 'theme-' + CWS_STATE.theme;
    ov.hidden = !CWS_STATE.open;
    ov.innerHTML = `
      <!-- A. LEFT SIDEBAR -->
      <aside class="cws-sidebar" id="cwsSidebar">
        <!-- Top Tool Bar: collapse, split-view, back, forward -->
        <div class="cws-sb-top-bar">
          <button type="button" class="cws-sb-tool-btn" onclick="window.cwsToggleSidebar()" title="Toggle sidebar">
            ${ICONS.sidebarToggle}
          </button>
          <button type="button" class="cws-sb-tool-btn" onclick="window.cwsToggleDrawer()" title="Project Files &amp; Inspector">
            ${ICONS.splitView}
          </button>
          <button type="button" class="cws-sb-tool-btn" onclick="window.cwsHistoryBack()" title="Back">
            ${ICONS.arrowLeft}
          </button>
          <button type="button" class="cws-sb-tool-btn" onclick="window.cwsHistoryForward()" title="Forward">
            ${ICONS.arrowRight}
          </button>
        </div>

        <!-- Brand Row -->
        <div class="cws-brand-row">
          <div class="cws-brand-left" onclick="window.cwsSetNav('chats')" title="Expo Design AI">
            <div class="cws-logo-bars">
              <span class="cws-logo-bar"></span>
              <span class="cws-logo-bar"></span>
              <span class="cws-logo-bar"></span>
              <span class="cws-logo-bar"></span>
            </div>
            <div class="cws-brand-text">
              <span class="cws-brand-title">Expo Design AI</span>
              <span class="cws-brand-sub">Engineering Workspace</span>
            </div>
          </div>
        </div>

        <!-- Action Row: Search input + + New button -->
        <div class="cws-sb-actions-row">
          <div class="cws-sb-search-box">
            ${ICONS.search}
            <input type="text" placeholder="Search" oninput="window.cwsOnRecentSearch(this.value)">
          </div>
          <button type="button" class="cws-sb-new-pill" onclick="window.cwsNewTask()" title="Start New Chat">
            ${ICONS.plus}
            <span>New</span>
          </button>
        </div>

        <!-- Primary Navigation Menu -->
        <nav class="cws-nav-list" id="cwsPrimaryNav">
          <button type="button" class="cws-nav-item" data-nav="home" onclick="window.cwsSetNav('home')" title="Home">
            <span class="cws-nav-left">${ICONS.home}<span>Home</span></span>
          </button>
          <button type="button" class="cws-nav-item" data-nav="projects" onclick="window.cwsSetNav('projects')" title="Projects">
            <span class="cws-nav-left">${ICONS.projects}<span>Projects</span></span>
            <span class="cws-nav-chevron">${ICONS.chevronRight}</span>
          </button>
          <button type="button" class="cws-nav-item active" data-nav="chats" onclick="window.cwsSetNav('chats')" title="Chats">
            <span class="cws-nav-left">${ICONS.chats}<span>Chats</span></span>
          </button>
          <button type="button" class="cws-nav-item" data-nav="knowledge" onclick="window.cwsSetNav('knowledge')" title="Knowledge Base">
            <span class="cws-nav-left">${ICONS.knowledge}<span>Knowledge Base</span></span>
          </button>
          <button type="button" class="cws-nav-item" data-nav="tools" onclick="window.cwsSetNav('tools')" title="AI Tools">
            <span class="cws-nav-left">${ICONS.tools}<span>AI Tools</span></span>
          </button>
          <button type="button" class="cws-nav-item" data-nav="reports" onclick="window.cwsSetNav('reports')" title="Reports">
            <span class="cws-nav-left">${ICONS.reports}<span>Reports</span></span>
          </button>
          <button type="button" class="cws-nav-item" data-nav="automations" onclick="window.cwsSetNav('automations')" title="Automations">
            <span class="cws-nav-left">${ICONS.automations}<span>Automations</span></span>
          </button>
          <button type="button" class="cws-nav-item" data-nav="settings" onclick="window.cwsSetNav('settings')" title="Settings">
            <span class="cws-nav-left">${ICONS.settings}<span>Settings</span></span>
          </button>
        </nav>

        <!-- Collapsible Sections: Pinned & Recents -->
        <div class="cws-sb-section" id="cwsPinnedSec">
          <div class="cws-sb-sec-head" onclick="window.cwsToggleSection('pinned')" title="Pinned chats">
            <span style="display:flex;align-items:center;gap:4px">Pinned <span class="cws-sec-chev">${ICONS.chevronRight}</span></span>
          </div>
        </div>

        <div class="cws-sb-section" id="cwsRecentsSec" style="flex:1;min-height:0;display:flex;flex-direction:column">
          <div class="cws-sb-sec-head" onclick="window.cwsToggleSection('recents')" title="Recent chats">
            <span style="display:flex;align-items:center;gap:4px">Recents <span class="cws-sec-chev">${ICONS.chevronRight}</span></span>
            <div style="display:flex;align-items:center;gap:2px">
              <button type="button" class="cws-sb-sort-btn" onclick="event.stopPropagation();window.cwsSortRecents()" title="Sort chats">
                ${ICONS.sort}
              </button>
              <button type="button" class="cws-sb-sort-btn" onclick="event.stopPropagation();window.cwsClearAllRecents()" title="Clear all recent chats">
                ${ICONS.trash}
              </button>
            </div>
          </div>
          <div class="cws-recents-list" id="cwsRecentsList"></div>
        </div>

        <!-- User Profile Footer -->
        <div class="cws-profile-footer" onclick="window.cwsShowUserMenu()" title="Account &amp; Workspace Profile">
          <div class="cws-avatar-circle" id="cwsUserAvatar">MS</div>
          <div class="cws-profile-info">
            <span class="cws-profile-name" id="cwsUserName">Md Shahnawaz</span>
            <span class="cws-profile-role" id="cwsUserRole">BIM Associate ${ICONS.chevronDown}</span>
          </div>
        </div>
      </aside>

      <!-- B. MAIN CONVERSATION WORKSPACE -->
      <main class="cws-main">
        <!-- Top Compact Header (Clean, Minimalist, No Default Hardcoded Text) -->
        <header class="cws-header">
          <div style="display:flex;align-items:center;gap:10px">
            <button type="button" class="cws-icon-btn" id="cwsSbOpenBtn" onclick="window.cwsToggleSidebar()" hidden title="Expand sidebar">
              ${ICONS.sidebarToggle}
            </button>
          </div>

          <div class="cws-header-right">
            <!-- Project Search Pill -->
            <div class="cws-header-search">
              ${ICONS.search}
              <input type="text" placeholder="Search in project..." oninput="window.cwsOnProjectSearch(this.value)">
            </div>
            <!-- Notification Bell -->
            <button type="button" class="cws-icon-btn" onclick="window.toast && window.toast('No unread notifications')" title="Notifications">
              ${ICONS.bell}
            </button>
            <!-- Theme Toggle Sun -->
            <button type="button" class="cws-icon-btn" onclick="window.cwsToggleTheme()" title="Toggle theme">
              ${ICONS.sun}
            </button>
            <!-- User Avatar Circle -->
            <div class="cws-avatar-circle" style="width:28px;height:28px;font-size:11px;cursor:pointer" onclick="window.cwsShowUserMenu()">MS</div>
            <!-- Exit Cowork Studio Button (Returns to classic chat) -->
            <button type="button" class="cws-btn" onclick="window.closeCoworkStudio()" title="Switch to Classic Chat" style="padding:4px 9px;font-size:11.5px">Exit Cowork</button>
          </div>
        </header>

        <!-- Main Stage Canvas -->
        <div class="cws-stage-body" id="cwsStageBody"></div>

        <!-- Centered / Bottom Message Composer -->
        <div class="cws-composer-wrap" id="cwsComposerWrap">
          <div class="cws-composer-inner">
            <div class="cws-composer-card" id="cwsComposerCard">
              <!-- Hidden dedicated file input for attachments -->
              <input type="file" id="cwsComposerFileInput" multiple style="display:none" onchange="window.cwsOnFilesSelected(event)" accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.png,.jpg,.jpeg,.webp,.svg,.dwg,.dxf,.ifc" />

              <!-- Attachment Preview Cards Container (above textarea, matches Image 3) -->
              <div class="cws-composer-attachments" id="cwsComposerAttachments" style="display:none"></div>

              <!-- Multiline Text Input -->
              <textarea class="cws-composer-ta" id="cwsInput" rows="1" placeholder="How can I help you today?"></textarea>
              
              <div class="cws-composer-bottom-bar">
                <!-- Left side: Attach (+) and Mode Segmented [ Chat | Cowork ] -->
                <div class="cws-cb-left">
                  <button type="button" class="cws-cb-icon-btn" onclick="window.cwsTriggerAttach()" title="Attach file or upload document">
                    ${ICONS.plus}
                  </button>

                  <!-- Segmented switch matching Image 3 -->
                  <div class="cws-mode-segmented">
                    <button type="button" class="cws-mode-seg-btn ${CWS_STATE.composerModeSeg === 'chat' ? 'active' : ''}" id="cwsModeSegChat" onclick="window.cwsSetModeSeg('chat')">Chat</button>
                    <button type="button" class="cws-mode-seg-btn ${CWS_STATE.composerModeSeg === 'cowork' ? 'active' : ''}" id="cwsModeSegCowork" onclick="window.cwsSetModeSeg('cowork')">Cowork</button>
                  </div>
                </div>

                <!-- Right side: Mic with chevron + Send button -->
                <div class="cws-cb-right">
                  <button type="button" class="cws-cb-icon-btn" onclick="window.cwsTriggerVoice()" title="Voice Dictation" style="gap:2px">
                    ${ICONS.mic}
                    <span style="font-size:9px;color:#a1a1aa;margin-left:1px">${ICONS.chevronDown}</span>
                  </button>
                  <button type="button" class="cws-cb-send-btn is-disabled" id="cwsSendBtn" onclick="window.cwsOnSendOrStop()" title="Send prompt (Enter)">
                    ${ICONS.send}
                  </button>
                </div>
              </div>
            </div>

            <!-- Subbar below composer card (Matches Image 2) -->
            <div class="cws-composer-subbar">
              <!-- Left side: Project or folder ⌄ dropdown -->
              <div class="cws-proj-dropdown-anchor">
                <button type="button" class="cws-cb-pill" id="cwsComposerProjBtn" onclick="window.cwsToggleProjectDropdown(event)" title="Select project or folder">
                  <span class="cws-cb-pill-text" id="cwsComposerProjName">${escHtml(getProj() || 'Project or folder')}</span>
                  <span class="cws-cb-pill-chev">${ICONS.chevronDown}</span>
                </button>
                
                <!-- Image 2 Dropdown Menu -->
                <div class="cws-proj-dropdown-menu" id="cwsProjectDropdownMenu" style="display:none" onclick="event.stopPropagation()">
                  <!-- Search Row with Sliders / Tune Icon -->
                  <div class="cws-proj-dropdown-search">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" style="flex-shrink:0"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                    <input type="text" id="cwsProjectSearchInput" placeholder="Search or create a project" oninput="window.cwsOnDropdownProjectSearch(this.value)" onkeydown="if(event.key==='Enter')window.cwsOnDropdownProjectSearchEnter(this.value)">
                    <button type="button" class="cws-icon-btn" style="width:20px;height:20px;padding:0;color:#9ca3af;cursor:pointer" onclick="window.cwsSetNav('projects');window.cwsCloseProjectDropdown()" title="View all projects">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>
                    </button>
                  </div>
                  
                  <div class="cws-proj-dropdown-divider"></div>
                  
                  <!-- Pinned Section -->
                  <div class="cws-proj-dropdown-section-title">Pinned</div>
                  <div class="cws-proj-dropdown-list" id="cwsProjectDropdownList"></div>
                  
                  <div class="cws-proj-dropdown-divider"></div>
                  
                  <!-- Actions (Matches Image 2) -->
                  <div class="cws-proj-dropdown-action" onclick="window.cwsCloseProjectDropdown();window.cwsShowCreateProjectModal()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="flex-shrink:0;color:#6b7280">
                      <line x1="12" y1="5" x2="12" y2="19"></line>
                      <line x1="5" y1="12" x2="19" y2="12"></line>
                    </svg>
                    <span>New project</span>
                  </div>
                  <div class="cws-proj-dropdown-action" onclick="window.cwsCloseProjectDropdown();window.cwsCreateFolderPrompt()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;color:#6b7280">
                      <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"></path>
                      <line x1="12" y1="10" x2="12" y2="16"></line>
                      <line x1="9" y1="13" x2="15" y2="13"></line>
                    </svg>
                    <span>Add folder</span>
                  </div>
                </div>
              </div>

              <!-- Right side: Model selection, reasoning effort, auto mode -->
              <div class="cws-composer-subbar-right">
                <button type="button" class="cws-cb-sub-btn" onclick="window.cwsCycleModel()" title="Select AI Model">
                  <span id="cwsComposerModelName">Qwen 3.5 9B</span>
                </button>
                <button type="button" class="cws-cb-sub-btn" disabled title="Reasoning depth control is not available">
                  <span id="cwsComposerEffort">Default depth</span>
                </button>
                <button type="button" class="cws-cb-sub-btn" disabled title="Python tasks require the isolated worker; direct host execution is unavailable">
                  <span id="cwsComposerMode">Isolated Python</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      <!-- RIGHT SPLIT-PANE DRAWER (Artifact & Project Files Inspector) -->
      <aside class="cws-drawer" id="cwsRightDrawer" hidden>
        <div class="cws-drawer-head">
          <div style="display:flex;align-items:center;gap:6px;min-width:0;flex:1">
            <span id="cwsDrawerTitle" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Project Files</span>
          </div>
          <div id="cwsDrawerTabsWrap" style="display:none"></div>
          <div style="display:flex;gap:4px;flex-shrink:0">
            <button type="button" class="cws-btn" style="padding:3px 8px;font-size:11px" onclick="window.cwsOpenNewFileEditor()">+ New</button>
            <button type="button" class="cws-icon-btn" onclick="window.cwsToggleDrawer(false)">✕</button>
          </div>
        </div>
        <div class="cws-drawer-body" id="cwsDrawerBody"></div>
      </aside>

      <!-- Create a Project Modal Dialog (Matches 2nd reference image) -->
      <div class="cws-modal-backdrop" id="cwsCreateProjectModal" style="display:none" onclick="if(event.target===this)window.cwsCloseCreateProjectModal()">
        <div class="cws-modal-card">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
            <h3 style="margin:0;font-size:18px;font-weight:700;color:var(--cws-text)">Create a project</h3>
            <button type="button" class="cws-modal-close-btn" onclick="window.cwsCloseCreateProjectModal()">✕</button>
          </div>
          <div style="margin-bottom:14px">
            <label style="display:block;font-size:13px;font-weight:600;color:var(--cws-text);margin-bottom:6px">What are you working on?</label>
            <input type="text" id="cwsModalProjName" class="cws-modal-input-blue" placeholder="Name your project" onkeydown="if(event.key==='Enter')window.cwsSubmitCreateProject()" />
          </div>
          <div style="margin-bottom:14px">
            <label style="display:block;font-size:13px;font-weight:600;color:var(--cws-text);margin-bottom:6px">What are you trying to achieve?</label>
            <textarea id="cwsModalProjDesc" class="cws-modal-textarea-desc" rows="3" placeholder="Describe your project, goals, subject, etc..."></textarea>
          </div>
          <div style="margin-bottom:20px">
            <div style="font-size:13px;font-weight:600;color:var(--cws-text);margin-bottom:6px">Context <span style="font-size:12px;font-weight:400;color:var(--cws-muted);margin-left:4px">optional</span></div>
            <button type="button" class="cws-context-toggle-btn" id="cwsModalCtxBtn" onclick="window.cwsToggleContextRow()">+ Add context</button>
            <div id="cwsModalCtxRow" style="display:none;margin-top:8px">
              <input type="text" id="cwsModalProjContext" class="cws-modal-input-blue" style="font-size:13px;border-color:var(--cws-border)" placeholder="e.g. Dubai Building Code, Hospitality / Residential, Structural LOD 350" />
            </div>
          </div>
          <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:18px">
            <button type="button" class="cws-modal-cancel" onclick="window.cwsCloseCreateProjectModal()">Cancel</button>
            <button type="button" class="cws-modal-submit" id="cwsModalSubmitBtn" onclick="window.cwsSubmitCreateProject()">Create project</button>
          </div>
        </div>
      </div>

    `;

    document.body.appendChild(ov);

    // Textarea handling (Enter to send, Shift+Enter for newline, auto-expansion)
    const ta = document.getElementById('cwsInput');
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        window.cwsOnSendOrStop();
      }
    });
    ta.addEventListener('input', () => {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 180) + 'px';
      updateSendBtnState();
    });

    // Drag and Drop files onto Composer Card
    const compCard = document.getElementById('cwsComposerCard');
    if (compCard) {
      compCard.addEventListener('dragover', e => {
        e.preventDefault();
        compCard.classList.add('is-drag-over');
      });
      compCard.addEventListener('dragleave', () => {
        compCard.classList.remove('is-drag-over');
      });
      compCard.addEventListener('drop', async e => {
        e.preventDefault();
        compCard.classList.remove('is-drag-over');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          if (window.cwsAddAttachedFiles) {
            await window.cwsAddAttachedFiles(Array.from(e.dataTransfer.files));
          }
        }
      });
    }
  }

  function injectLaunchButtons() {
    const tright = document.querySelector('#top .tright');
    if (tright && !document.getElementById('cwsTopSwitcher')) {
      const sw = document.createElement('div');
      sw.id = 'cwsTopSwitcher';
      sw.className = 'cws-mode-switch';
      sw.innerHTML = `
        <button type="button" class="cws-mode-btn" id="cwsTopChatBtn" onclick="window.closeCoworkStudio()" title="Standard Workspace">💬 Classic</button>
        <button type="button" class="cws-mode-btn active" id="cwsTopCoworkBtn" onclick="window.openCoworkStudio()" title="Open Full-Screen CoWork Studio">⚡ CoWork</button>
      `;
      tright.insertBefore(sw, tright.firstChild);
    }
  }

  /* --------------------------------------------------------------------------
     WORKSPACE REFRESH & DATA
     -------------------------------------------------------------------------- */
  async function refreshWorkspaceTree() {
    const proj = getProj();
    if (!proj) {
      renderAll();
      return;
    }
    try {
      const r = await fetch(`/projects/${encodeURIComponent(proj)}/agent/workspace`, {
        headers: getAuthHeaders()
      });
      if (r.ok) {
        CWS_STATE.tree = await r.json();
        window.lastCoworkTree = CWS_STATE.tree;
      }
    } catch (e) {}
    renderAll();
  }

  function openCoworkStudio(folderPath) {
    injectStyles();
    buildOverlayDOM();
    loadLocalData();
    if (typeof folderPath === 'string') {
      CWS_STATE.activeFolder = folderPath;
      window.currentCoworkFolder = folderPath;
    } else if (window.currentCoworkFolder) {
      CWS_STATE.activeFolder = window.currentCoworkFolder;
    }
    CWS_STATE.open = true;
    try { localStorage.setItem('expo_cowork_open', 'true'); } catch (e) {}

    const ov = document.getElementById('coworkStudioOverlay');
    if (ov) ov.hidden = false;

    const bChat = document.getElementById('cwsTopChatBtn');
    const bCo = document.getElementById('cwsTopCoworkBtn');
    if (bChat && bCo) {
      bChat.classList.remove('active');
      bCo.classList.add('active');
    }

    renderAll();
    refreshWorkspaceTree();
  }

  function closeCoworkStudio() {
    CWS_STATE.open = false;
    try { localStorage.setItem('expo_cowork_open', 'false'); } catch (e) {}
    const ov = document.getElementById('coworkStudioOverlay');
    if (ov) ov.hidden = true;

    const bChat = document.getElementById('cwsTopChatBtn');
    const bCo = document.getElementById('cwsTopCoworkBtn');
    if (bChat && bCo) {
      bCo.classList.remove('active');
      bChat.classList.add('active');
    }
  }

  window.openCoworkStudio = openCoworkStudio;
  window.closeCoworkStudio = closeCoworkStudio;

  /* --------------------------------------------------------------------------
     UI CONTROLS & STATE HELPERS
     -------------------------------------------------------------------------- */
  const AVAILABLE_MODELS = [
    { id: 'qwen3.5:9b', label: 'Qwen 3.5 9B' },
    { id: 'qwen2.5:7b', label: 'Qwen 2.5 7B' }
  ];

  window.cwsCycleModel = function () {
    const curIdx = AVAILABLE_MODELS.findIndex(m => m.id === CWS_STATE.selectedModel);
    const nextIdx = (curIdx + 1) % AVAILABLE_MODELS.length;
    CWS_STATE.selectedModel = AVAILABLE_MODELS[nextIdx].id;
    try { localStorage.setItem('expo_cws_model', CWS_STATE.selectedModel); } catch (e) {}
    const label = document.getElementById('cwsComposerModelName');
    if (label) label.textContent = AVAILABLE_MODELS[nextIdx].label;
    if (window.toast) window.toast(`Model switched to ${AVAILABLE_MODELS[nextIdx].label}`);
  };

  window.cwsCycleEffort = window.cwsCycleMode = function () {
    if (window.toast) window.toast('This control is unavailable. Python tasks always require isolation.');
  };

  async function refreshSandboxBadge() {
    const badge = document.getElementById('cwsSandboxStatus');
    if (!badge) return;
    try {
      const response = await fetch('/agent/sandbox-status', {headers:getAuthHeaders(), cache:'no-store'});
      if (!response.ok) throw new Error('Status unavailable');
      const status = await response.json();
      if (!badge.isConnected) return;
      badge.textContent = status.ready ? 'Isolated Python worker ready' : 'Isolated Python worker unavailable';
      badge.title = status.message || '';
    } catch (_) {
      if (badge.isConnected) badge.textContent = 'Isolated Python worker status unavailable';
    }
  }

  window.cwsSortRecents = function () {
    CWS_STATE.recentsSort = CWS_STATE.recentsSort === 'desc' ? 'asc' : 'desc';
    renderSidebar();
    if (window.toast) window.toast(`Sorted chats ${CWS_STATE.recentsSort === 'desc' ? 'newest first' : 'oldest first'}`);
  };

  window.cwsToggleSection = function (sec) {
    if (CWS_STATE.sectionsCollapsed[sec] !== undefined) {
      CWS_STATE.sectionsCollapsed[sec] = !CWS_STATE.sectionsCollapsed[sec];
      renderSidebar();
    }
  };

  window.cwsDeleteSession = function (sessId) {
    if (!sessId || !CWS_STATE.sessions) return;
    const idx = CWS_STATE.sessions.findIndex(s => s.id === sessId);
    if (idx < 0) return;
    const item = CWS_STATE.sessions[idx];
    const name = item.title || 'this chat';
    if (!confirm(`Delete chat "${name}"?`)) return;

    CWS_STATE.sessions.splice(idx, 1);
    saveLocalData();

    if (CWS_STATE.activeSessionId === sessId) {
      if (CWS_STATE.sessions.length > 0) {
        CWS_STATE.activeSessionId = CWS_STATE.sessions[0].id;
      } else {
        window.cwsNewTask();
        return;
      }
    }
    if (window.toast) window.toast('Chat deleted');
    renderSidebar();
    renderStage();
  };

  window.cwsClearAllRecents = function () {
    if (!confirm('Clear all recent chat history?')) return;
    CWS_STATE.sessions = [];
    saveLocalData();
    window.cwsNewTask();
    if (window.toast) window.toast('All chat history cleared');
  };

  /* --------------------------------------------------------------------------
     PROJECT CREATION & MODAL ACTIONS (Matches 2nd Reference Screenshot)
     -------------------------------------------------------------------------- */
  window.cwsShowCreateProjectModal = function () {
    const modal = document.getElementById('cwsCreateProjectModal');
    if (!modal) return;
    modal.style.display = 'flex';
    const nameInput = document.getElementById('cwsModalProjName');
    const descInput = document.getElementById('cwsModalProjDesc');
    const ctxInput = document.getElementById('cwsModalProjContext');
    const ctxRow = document.getElementById('cwsModalCtxRow');
    if (nameInput) { nameInput.value = ''; nameInput.focus(); }
    if (descInput) descInput.value = '';
    if (ctxInput) ctxInput.value = '';
    if (ctxRow) ctxRow.style.display = 'none';
  };

  window.cwsCloseCreateProjectModal = function () {
    const modal = document.getElementById('cwsCreateProjectModal');
    if (modal) modal.style.display = 'none';
  };

  window.cwsToggleContextRow = function () {
    const ctxRow = document.getElementById('cwsModalCtxRow');
    if (ctxRow) {
      ctxRow.style.display = ctxRow.style.display === 'none' ? 'block' : 'none';
      if (ctxRow.style.display === 'block') {
        const inp = document.getElementById('cwsModalProjContext');
        if (inp) inp.focus();
      }
    }
  };

  window.cwsSubmitCreateProject = async function () {
    const nameInput = document.getElementById('cwsModalProjName');
    const descInput = document.getElementById('cwsModalProjDesc');
    const ctxInput = document.getElementById('cwsModalProjContext');
    const submitBtn = document.getElementById('cwsModalSubmitBtn');

    const name = nameInput ? nameInput.value.trim() : '';
    if (!name) {
      if (nameInput) {
        nameInput.style.borderColor = '#ef4444';
        nameInput.focus();
      }
      return;
    }

    const description = descInput ? descInput.value.trim() : '';
    const context = ctxInput ? ctxInput.value.trim() : '';

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Creating...';
    }

    try {
      const r = await fetch('/projects', {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ name, description, context })
      });
      if (r.ok) {
        const data = await r.json();
        window.cwsCloseCreateProjectModal();
        if (window.toast) window.toast(`Project "${name}" created successfully!`);

        // Update active project
        window.currentProject = name;
        const sel = document.getElementById('projSel');
        if (sel) {
          const opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          opt.selected = true;
          sel.appendChild(opt);
          sel.value = name;
          sel.dispatchEvent(new Event('change'));
        }

        // Re-fetch overview and workspace
        if (typeof fetchProjectsOverview === 'function') {
          await fetchProjectsOverview();
        }
        await refreshWorkspaceTree();
        renderAll();
      } else {
        let err = 'Failed to create project';
        try { const d = await r.json(); if (d.detail) err = d.detail; } catch (e) {}
        alert('Error: ' + err);
      }
    } catch (e) {
      alert('Error creating project: ' + (e.message || e));
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create project';
      }
    }
  };

  window.cwsSelectAndOpenProject = async function (projectName) {
    if (!projectName) return;
    window.currentProject = projectName;
    const sel = document.getElementById('projSel');
    if (sel) {
      sel.value = projectName;
      sel.dispatchEvent(new Event('change'));
    }
    if (typeof selectProject === 'function') {
      try { selectProject(projectName); } catch (e) {}
    }
    if (window.toast) window.toast(`Switched to project: ${projectName}`);
    await refreshWorkspaceTree();
    renderAll();
  };

  window.cwsToggleProjectStar = function (projectName) {
    if (!projectName) return;
    CWS_STATE.starredProjects = CWS_STATE.starredProjects || [];
    const idx = CWS_STATE.starredProjects.indexOf(projectName);
    if (idx >= 0) {
      CWS_STATE.starredProjects.splice(idx, 1);
    } else {
      CWS_STATE.starredProjects.push(projectName);
    }
    try {
      localStorage.setItem('expo_cws_starred', JSON.stringify(CWS_STATE.starredProjects));
    } catch (e) {}
    const stage = document.getElementById('cwsStageBody');
    if (stage && CWS_STATE.activeNav === 'projects') {
      renderProjectsView(stage);
    }
  };

  window.cwsFilterProjectsPrompt = function () {
    const q = window.prompt('Filter projects by name or description:', CWS_STATE.projectFilterQuery || '');
    if (q === null) return;
    CWS_STATE.projectFilterQuery = q.trim();
    const stage = document.getElementById('cwsStageBody');
    if (stage && CWS_STATE.activeNav === 'projects') {
      renderProjectsView(stage);
    }
  };

  window.cwsSortProjectsToggle = function () {
    CWS_STATE.projectsSort = CWS_STATE.projectsSort === 'asc' ? 'desc' : 'asc';
    const stage = document.getElementById('cwsStageBody');
    if (stage && CWS_STATE.activeNav === 'projects') {
      renderProjectsView(stage);
    }
    if (window.toast) window.toast(`Sorted projects ${CWS_STATE.projectsSort === 'asc' ? 'A-Z' : 'by recents / starred'}`);
  };

  window.cwsCreateFolderPrompt = async function () {
    const name = window.prompt("Enter new folder name (e.g. 'Structural_Drawings', 'Calculations', 'Reports'):");
    if (!name || !name.trim()) return;
    const clean = name.trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    if (!clean) return;

    const proj = getProj();
    if (!proj) {
      alert('Please select or specify a project before creating folders.');
      return;
    }
    try {
      const r = await fetch(`/projects/${encodeURIComponent(proj)}/agent/workspace-folder`, {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ path: clean })
      });
      if (r.ok) {
        if (window.toast) window.toast(`Folder "${clean}" created successfully!`);
        await refreshWorkspaceTree();
        renderAll();
      } else {
        let err = 'Failed to create folder';
        try { const d = await r.json(); if (d.detail) err = d.detail; } catch (e) {}
        alert('Error creating folder: ' + err);
      }
    } catch (e) {
      alert('Error creating folder: ' + (e.message || e));
    }
  };

  window.cwsDeleteFolder = async function (folderPath) {
    if (!folderPath) return;
    const name = folderPath.split('/').pop() || folderPath;
    if (!confirm(`Are you sure you want to delete folder "${name}" and all its contents?`)) return;
    const proj = getProj();
    try {
      const r = await fetch(`/projects/${encodeURIComponent(proj)}/agent/workspace-file?path=${encodeURIComponent(folderPath)}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
      });
      if (r.ok) {
        if (window.toast) window.toast(`Folder "${name}" deleted`);
        await refreshWorkspaceTree();
        renderAll();
      } else {
        alert('Failed to delete folder');
      }
    } catch (e) {
      alert('Error deleting folder: ' + (e.message || e));
    }
  };

  window.cwsDeleteWorkspaceFile = async function (filePath) {
    if (!filePath) return;
    const name = filePath.split('/').pop() || filePath;
    if (!confirm(`Are you sure you want to delete "${name}"?`)) return;
    const proj = getProj();
    try {
      const r = await fetch(`/projects/${encodeURIComponent(proj)}/agent/workspace-file?path=${encodeURIComponent(filePath)}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
      });
      if (r.ok) {
        if (window.toast) window.toast(`Deleted ${name}`);
        if (CWS_STATE.previewFile && CWS_STATE.previewFile.path === filePath) {
          CWS_STATE.previewFile = null;
        }
        await refreshWorkspaceTree();
        renderAll();
      } else {
        alert('Failed to delete file');
      }
    } catch (e) {
      alert('Error deleting file: ' + (e.message || e));
    }
  };

  window.cwsHistoryBack = function () {
    if (window.history.length > 1) window.history.back();
    else if (window.toast) window.toast('No previous navigation history');
  };

  window.cwsHistoryForward = function () {
    window.history.forward();
  };

  window.cwsToggleTheme = function () {
    CWS_STATE.theme = CWS_STATE.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('expo_cws_theme', CWS_STATE.theme); } catch (e) {}
    const ov = document.getElementById('coworkStudioOverlay');
    if (ov) ov.className = 'theme-' + CWS_STATE.theme;
  };

  window.cwsToggleSidebar = function () {
    CWS_STATE.sidebarCollapsed = !CWS_STATE.sidebarCollapsed;
    const sb = document.getElementById('cwsSidebar');
    const openBtn = document.getElementById('cwsSbOpenBtn');
    if (sb) sb.classList.toggle('collapsed', CWS_STATE.sidebarCollapsed);
    if (openBtn) openBtn.hidden = !CWS_STATE.sidebarCollapsed;
  };

  window.cwsToggleDrawer = function (force) {
    CWS_STATE.drawerOpen = typeof force === 'boolean' ? force : !CWS_STATE.drawerOpen;
    const dr = document.getElementById('cwsRightDrawer');
    if (dr) dr.hidden = !CWS_STATE.drawerOpen;
    if (CWS_STATE.drawerOpen) renderDrawer();
  };

  /* --------------------------------------------------------------------------
     ATTACHMENT HANDLING & PREVIEW CARDS (Matches Reference Image 3)
     -------------------------------------------------------------------------- */
  window.cwsTriggerAttach = function () {
    const fileInp = document.getElementById('cwsComposerFileInput');
    if (fileInp) {
      fileInp.click();
      return;
    }
    const aiFiles = document.getElementById('aiCoworkFilesInput') || document.getElementById('fileInput');
    if (aiFiles) aiFiles.click();
  };

  window.cwsOnFilesSelected = async function (e) {
    const files = e && e.target && e.target.files;
    if (!files || !files.length) return;
    await window.cwsAddAttachedFiles(Array.from(files));
    if (e.target) e.target.value = '';
  };

  window.cwsAddAttachedFiles = async function (fileList) {
    if (!fileList || !fileList.length) return;
    const proj = getProj();

    for (const file of fileList) {
      const ext = (file.name.split('.').pop() || '').toLowerCase();
      let badge = 'DOC';
      if (ext === 'pdf') badge = 'PDF';
      else if (['png', 'jpg', 'jpeg', 'webp', 'svg', 'gif'].includes(ext)) badge = 'IMG';
      else if (['dwg', 'dxf'].includes(ext)) badge = 'CAD';
      else if (ext === 'ifc') badge = 'IFC';
      else if (['xlsx', 'xls', 'csv'].includes(ext)) badge = 'XLS';
      else if (['doc', 'docx'].includes(ext)) badge = 'DOC';
      else if (['py', 'js', 'ts', 'json', 'html', 'css'].includes(ext)) badge = 'CODE';

      const att = {
        id: 'att-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7),
        file: file,
        name: file.name,
        size: file.size,
        ext: ext,
        badge: badge,
        previewUrl: '',
        blobUrl: URL.createObjectURL(file),
        serverPath: file.name,
        status: 'uploading'
      };
      if (!CWS_STATE.attachedFiles) CWS_STATE.attachedFiles = [];
      CWS_STATE.attachedFiles.push(att);
      renderComposerAttachments();
      updateSendBtnState();

      // 1. Instant preview for images
      if (['png', 'jpg', 'jpeg', 'webp', 'svg', 'gif'].includes(ext)) {
        att.previewUrl = att.blobUrl;
        renderComposerAttachments();
      }

      // 2. Client-side PDF thumbnail via PDF.js (zero latency display)
      if (ext === 'pdf' && window.ExpoPDF) {
        att.previewPromise = (async () => {
        let pdfDoc;
        try {
          const arrayBuffer = await file.arrayBuffer();
          pdfDoc = await window.ExpoPDF.open(arrayBuffer);
          const page = await pdfDoc.getPage(1);
          const viewport = page.getViewport({ scale: 0.35 });
          const canvas = document.createElement('canvas');
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          const ctx = canvas.getContext('2d');
          await page.render({ canvasContext: ctx, viewport }).promise;
          att.previewUrl = canvas.toDataURL('image/png');
            renderComposerAttachments();
        } catch (err) {
          console.warn('Local PDF preview unavailable:', err);
        } finally {
          if (pdfDoc) await pdfDoc.destroy().catch(() => {});
        }
        })();
      }

      // 3. Upload file to server in background
      att.uploadPromise = (async (curAtt, curFile, curExt) => {
        try {
          const form = new FormData();
          form.append('project', proj);
          form.append('file', curFile);
          const r = await fetch('/chat/attachments', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: form
          });
          if (r.ok) {
            const res = await r.json().catch(() => ({}));
            if (res && res.id) {
              curAtt.attachmentId = res.id;
              curAtt.serverPath = res.filename || curFile.name;
            }
            if (!curAtt.attachmentId) throw new Error('Upload did not return an attachment ID');
            curAtt.status = res.status === 'ready' ? 'ready' : 'processing';
            renderComposerAttachments();
            updateSendBtnState();
            await window.ExpoAttachmentProcessing.waitReady(curAtt.attachmentId, {
              headers: getAuthHeaders(),
              onProgress: record => {
                curAtt.status = record.status === 'ready' ? 'ready' : 'processing';
                const progress = record.progress;
                curAtt.processingLabel = progress ? `${progress.stage}${progress.total ? ` ${progress.done}/${progress.total}` : ''}` : 'Waiting for processing';
                renderComposerAttachments();
                updateSendBtnState();
              }
            });
            curAtt.status = 'ready';
            curAtt.processingLabel = 'Ready';
            renderComposerAttachments();
            updateSendBtnState();
            refreshWorkspaceTree();
          } else {
            const detail = await r.json().catch(() => ({}));
            throw new Error(detail.detail || `Upload failed (${r.status})`);
          }
        } catch (e) {
          curAtt.status = 'error';
          curAtt.processingLabel = e.message || 'Upload or processing failed';
          renderComposerAttachments();
          updateSendBtnState();
        }
      })(att, file, ext);
    }
  };

  function renderComposerAttachments() {
    const container = document.getElementById('cwsComposerAttachments');
    if (!container) return;
    const files = CWS_STATE.attachedFiles || [];
    if (!files.length) {
      container.style.display = 'none';
      container.innerHTML = '';
      return;
    }
    container.style.display = 'flex';
    container.innerHTML = files.map((att, idx) => `
      <div class="cws-attachment-card" onclick="window.cwsPreviewAttachment('${att.id}')" title="${escAttr(att.name)} (Click to view)">
        <div class="cws-attachment-thumb-wrap">
          ${att.previewUrl ? `
            <img class="cws-attachment-thumb-img" src="${escAttr(att.previewUrl)}" alt="${escAttr(att.name)}" />
          ` : `
            <div class="cws-attachment-skeleton">
              <div class="cws-att-sk-line" style="width:75%"></div>
              <div class="cws-att-sk-line" style="width:90%"></div>
              <div class="cws-att-sk-line" style="width:60%"></div>
              <div class="cws-att-sk-line" style="width:80%;margin-top:4px"></div>
              <div class="cws-att-sk-line" style="width:85%"></div>
              <div class="cws-att-sk-line" style="width:70%"></div>
              <div class="cws-att-sk-line" style="width:50%;margin-top:4px"></div>
            </div>
          `}
          ${att.status === 'rendering' || att.status === 'uploading' || att.status === 'processing' ? `
            <div class="cws-attachment-spinner">
              <div class="cws-spinner-dot"></div>
            </div>
          ` : ''}
        </div>
        <div class="cws-attachment-badge">${escHtml(att.badge || 'PDF')} · ${escHtml(att.status === 'processing' ? (att.processingLabel || 'Processing') : att.status === 'error' ? (att.processingLabel || 'Failed') : att.status === 'ready' ? 'Ready' : 'Uploading')}</div>
        <button type="button" class="cws-attachment-remove" onclick="event.stopPropagation();window.cwsRemoveAttachment(${idx})" title="Remove attachment">✕</button>
      </div>
    `).join('');
  }

  window.cwsRemoveAttachment = function (idx) {
    if (CWS_STATE.attachedFiles && CWS_STATE.attachedFiles[idx]) {
      CWS_STATE.attachedFiles.splice(idx, 1);
      renderComposerAttachments();
      updateSendBtnState();
    }
  };

  window.cwsPreviewAttachment = function (id) {
    const att = (CWS_STATE.attachedFiles || []).find(x => x.id === id);
    if (!att) return;
    if (att.blobUrl) {
      window.cwsToggleDrawer(true);
      CWS_STATE.previewFile = {
        path: att.serverPath || att.name,
        name: att.name,
        content: '',
        editable: false,
        size: att.size,
        modeTab: 'preview',
        blobUrl: att.blobUrl
      };
      renderDrawer();
    } else if (att.serverPath) {
      window.cwsInspectFile(att.serverPath);
    }
  };

  window.cwsSetModeSeg = function (mode) {
    CWS_STATE.composerModeSeg = mode;
    const chatBtn = document.getElementById('cwsModeSegChat');
    const coworkBtn = document.getElementById('cwsModeSegCowork');
    if (chatBtn) chatBtn.classList.toggle('active', mode === 'chat');
    if (coworkBtn) coworkBtn.classList.toggle('active', mode === 'cowork');
    if (window.toast) window.toast(`Mode switched to ${mode === 'chat' ? 'Chat' : 'Cowork'}`);
  };

  window.cwsPdfActionPrompt = function (action, filename) {
    let promptText = '';
    if (action === 'fill_form') {
      promptText = `Please inspect the attached document "${filename}". Identify all form fields, checklists, and inspection criteria, and propose or fill out the appropriate engineering values.`;
    } else if (action === 'annotate') {
      promptText = `Please review the attached document "${filename}" against the Dubai Building Code and engineering standards. Highlight key requirements, flag deviations, and add review annotations.`;
    } else if (action === 'stamp') {
      promptText = `Please evaluate "${filename}" for quality assurance and place an engineering status stamp (APPROVED / DRAFT / CONFIDENTIAL) along with an executive approval summary note.`;
    } else if (action === 'sign') {
      promptText = `Please locate the sign-off / certification block on "${filename}" and assist with placing an engineering signature, license verification, and today's approval timestamp.`;
    }
    if (promptText) {
      const inp = document.getElementById('cwsInput');
      if (inp) {
        inp.value = promptText;
        inp.focus();
        updateSendBtnState();
      }
    }
  };

  window.cwsTriggerVoice = function () {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      try {
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        const rec = new SpeechRec();
        rec.continuous = false;
        rec.interimResults = false;
        rec.lang = 'en-US';
        rec.onstart = () => { if (window.toast) window.toast('Listening… Speak now'); };
        rec.onresult = (ev) => {
          const transcript = ev.results[0][0].transcript;
          const inp = document.getElementById('cwsInput');
          if (inp) {
            inp.value = (inp.value ? inp.value + ' ' : '') + transcript;
            inp.focus();
            updateSendBtnState();
          }
        };
        rec.onerror = () => { if (window.toast) window.toast('Voice recognition error'); };
        rec.start();
        return;
      } catch (e) {}
    }
    if (window.toast) window.toast('Voice input is ready');
  };

  window.cwsOnRecentSearch = function (q) {
    CWS_STATE.searchQuery = (q || '').trim().toLowerCase();
    renderSidebar();
  };

  window.cwsOnProjectSearch = function (q) {
    CWS_STATE.projectSearchQuery = (q || '').trim().toLowerCase();
    if (CWS_STATE.activeNav !== 'chats' && CWS_STATE.activeNav !== 'home') {
      renderStage();
    }
  };

  /* --------------------------------------------------------------------------
     IMAGE 2: COMPOSER PROJECT & FOLDER DROPDOWN (Matches Claude AI Reference)
     -------------------------------------------------------------------------- */
  window.cwsToggleProjectDropdown = function (ev) {
    if (ev) ev.stopPropagation();
    const menu = document.getElementById('cwsProjectDropdownMenu');
    if (!menu) return;
    const isVisible = menu.style.display !== 'none';
    if (isVisible) {
      window.cwsCloseProjectDropdown();
    } else {
      window.cwsOpenProjectDropdown();
    }
  };

  window.cwsCloseProjectDropdown = function () {
    const menu = document.getElementById('cwsProjectDropdownMenu');
    if (menu) menu.style.display = 'none';
    const btn = document.getElementById('cwsComposerProjBtn');
    if (btn) btn.classList.remove('is-open');
  };

  window.cwsOpenProjectDropdown = function () {
    const menu = document.getElementById('cwsProjectDropdownMenu');
    if (!menu) return;
    menu.style.display = 'block';
    const btn = document.getElementById('cwsComposerProjBtn');
    if (btn) btn.classList.add('is-open');

    // Populate list
    renderProjectDropdownList('');

    const searchInput = document.getElementById('cwsProjectSearchInput');
    if (searchInput) {
      searchInput.value = '';
      setTimeout(() => searchInput.focus(), 60);
    }

    // Refresh overview in background if needed
    if (!CWS_STATE.projectsOverview || !CWS_STATE.projectsOverview.length) {
      fetchProjectsOverview().then(res => {
        if (res) renderProjectDropdownList(document.getElementById('cwsProjectSearchInput')?.value || '');
      });
    }
  };

  function renderProjectDropdownList(query) {
    const listEl = document.getElementById('cwsProjectDropdownList');
    if (!listEl) return;
    const q = (query || '').trim().toLowerCase();

    let list = CWS_STATE.projectsOverview || [];
    if (!list.length) {
      const sel = document.getElementById('projSel');
      if (sel && sel.options.length) {
        list = Array.from(sel.options).map(o => ({ name: o.value, description: '' }));
      }
    }
    // If still empty, supply default project so pinned section is populated
    if (!list.length) {
      const cur = getProj();
      list = [{ name: cur || 'Expo AI Model', description: 'Workspace project' }];
    }

    const currentP = getProj();
    const starred = CWS_STATE.starredProjects || [];

    // Filter
    let filtered = list.filter(p => !q || (p.name || '').toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q));

    // Sort: starred first, then alphabetically
    filtered.sort((a, b) => {
      const aStar = starred.includes(a.name) ? 1 : 0;
      const bStar = starred.includes(b.name) ? 1 : 0;
      if (aStar !== bStar) return bStar - aStar;
      return (a.name || '').localeCompare(b.name || '');
    });

    let html = '';
    if (filtered.length > 0) {
      html += filtered.map(p => {
        const isActive = p.name === currentP;
        return `
          <div class="cws-proj-dropdown-item ${isActive ? 'active' : ''}" onclick="window.cwsSelectProject(${escAttr(JSON.stringify(p.name))})" title="${escAttr(p.name)}">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="cws-proj-box-icon">
              <rect x="4" y="5" width="16" height="3" rx="1.5"></rect>
              <path d="M5 8.5v8.5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5"></path>
              <line x1="10" y1="12" x2="14" y2="12"></line>
            </svg>
            <span class="cws-proj-dropdown-item-name">${escHtml(p.name)}</span>
            ${isActive ? '<span style="margin-left:auto;font-size:12px;color:#2563eb;font-weight:600">✓</span>' : ''}
          </div>
        `;
      }).join('');
    }

    // If search text does not match an existing project, offer quick creation
    if (q) {
      const exactMatch = list.some(p => (p.name || '').toLowerCase() === q);
      if (!exactMatch) {
        html += `
          <div class="cws-proj-dropdown-item" style="color:#2563eb;font-weight:500" onclick="window.cwsCreateProjectQuick(${escAttr(JSON.stringify(query.trim()))})">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="flex-shrink:0">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            <span>Create project "${escHtml(query.trim())}"</span>
          </div>
        `;
      }
    } else if (!filtered.length) {
      html = `<div style="padding:8px 14px;font-size:12px;color:var(--cws-muted);text-align:center">No projects yet</div>`;
    }

    listEl.innerHTML = html;
  }

  window.cwsOnDropdownProjectSearch = function (val) {
    renderProjectDropdownList(val);
  };

  window.cwsOnDropdownProjectSearchEnter = function (val) {
    const q = (val || '').trim();
    if (!q) return;
    const list = CWS_STATE.projectsOverview || [];
    const match = list.find(p => (p.name || '').toLowerCase() === q.toLowerCase());
    if (match) {
      window.cwsSelectProject(match.name);
    } else {
      window.cwsCreateProjectQuick(q);
    }
  };

  window.cwsSelectProject = async function (projectName) {
    if (!projectName) return;
    window.currentProject = projectName;
    const sel = document.getElementById('projSel');
    if (sel) {
      const exists = Array.from(sel.options).some(o => o.value === projectName);
      if (!exists) {
        const opt = document.createElement('option');
        opt.value = projectName;
        opt.textContent = projectName;
        sel.appendChild(opt);
      }
      sel.value = projectName;
      sel.dispatchEvent(new Event('change'));
    }
    window.cwsCloseProjectDropdown();
    const lbl = document.getElementById('cwsComposerProjName');
    if (lbl) lbl.textContent = projectName;
    await refreshWorkspaceTree();
    renderAll();
    if (window.toast) window.toast(`Active project: ${projectName}`);
  };

  window.cwsCreateProjectQuick = function (projectName) {
    window.cwsCloseProjectDropdown();
    window.cwsShowCreateProjectModal();
    const nameInput = document.getElementById('cwsModalProjName');
    if (nameInput) {
      nameInput.value = projectName || '';
      const descInput = document.getElementById('cwsModalProjDesc');
      if (descInput) descInput.focus();
    }
  };

  window.cwsPromptProjectSwitch = function (ev) {
    window.cwsToggleProjectDropdown(ev);
  };

  // Close dropdown on outside click or Escape
  document.addEventListener('click', (ev) => {
    const menu = document.getElementById('cwsProjectDropdownMenu');
    const btn = document.getElementById('cwsComposerProjBtn');
    if (menu && menu.style.display !== 'none') {
      if (!menu.contains(ev.target) && (!btn || !btn.contains(ev.target))) {
        window.cwsCloseProjectDropdown();
      }
    }
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      window.cwsCloseProjectDropdown();
    }
  });

  window.cwsShowUserMenu = function () {
    if (window.toast) {
      window.toast(`Logged in as ${document.getElementById('cwsUserName').textContent || 'Md Shahnawaz'} (BIM Associate)`);
    }
  };

  window.cwsSetNav = function (nav) {
    CWS_STATE.activeNav = nav || 'chats';
    renderAll();
  };

  window.cwsSelectSession = function (sessId) {
    CWS_STATE.activeSessionId = sessId;
    CWS_STATE.activeNav = 'chats';
    renderAll();
  };

  window.cwsNewTask = function (inFolder) {
    if (!CWS_STATE.sessions) CWS_STATE.sessions = [];
    const targetFolder = typeof inFolder === 'string' ? inFolder : (CWS_STATE.activeFolder || '');
    const sess = {
      id: 'sess-' + Date.now(),
      title: 'New chat',
      folder: targetFolder,
      timeBadge: 'Just now',
      updatedAt: Date.now(),
      messages: []
    };
    CWS_STATE.sessions.unshift(sess);
    CWS_STATE.activeSessionId = sess.id;
    CWS_STATE.activeFolder = targetFolder;
    CWS_STATE.activeNav = 'chats';
    saveLocalData();
    renderAll();
    const inp = document.getElementById('cwsInput');
    if (inp) {
      inp.value = '';
      inp.focus();
      updateSendBtnState();
    }
  };

  function updateSendBtnState() {
    const btn = document.getElementById('cwsSendBtn');
    const ta = document.getElementById('cwsInput');
    if (!btn) return;
    if (CWS_STATE.streaming) {
      btn.innerHTML = ICONS.stop;
      btn.disabled = false;
      btn.classList.add('is-stopping');
      btn.classList.remove('is-disabled');
      btn.title = 'Stop generation';
    } else {
      btn.innerHTML = ICONS.send;
      btn.classList.remove('is-stopping');
      const hasText = ta && ta.value.trim().length > 0;
      const hasFiles = CWS_STATE.attachedFiles && CWS_STATE.attachedFiles.length > 0;
      const filesReady = !hasFiles || CWS_STATE.attachedFiles.every(file => file.status === 'ready');
      const canSend = (hasText || hasFiles) && filesReady;
      btn.disabled = !canSend;
      btn.classList.toggle('is-disabled', !canSend);
      btn.title = !filesReady ? 'Wait for document processing to complete; remove failed attachments to continue' : canSend ? 'Send prompt (Enter)' : 'Enter a prompt or attach a document to send';
    }
  }

  window.cwsOnSendOrStop = function () {
    if (CWS_STATE.streaming) {
      if (cwsAbortController) {
        try { cwsAbortController.abort(); } catch (e) {}
      }
      CWS_STATE.streaming = false;
      updateSendBtnState();
      if (window.toast) window.toast('Generation stopped');
      return;
    }
    window.cwsSendMessage();
  };

  /* --------------------------------------------------------------------------
     MESSAGE FORMATTER
     -------------------------------------------------------------------------- */
  function formatCoworkMessage(rawContent) {
    if (!rawContent) return '';
    let s = String(rawContent);

    // 1. Code blocks (preserve without altering contents)
    const codeBlocks = [];
    s = s.replace(/```\s*([a-zA-Z0-9_\-\.]*)?\s*\r?\n([\s\S]*?)```/g, (_, lang, code) => {
      const idx = codeBlocks.length;
      const cleanLang = (lang || 'code').trim().toUpperCase();
      const escapedCode = escHtml(code.trim());
      codeBlocks.push(
        `<pre class="cws-code-block"><div class="cws-code-header"><span class="cws-code-lang">${cleanLang}</span><button type="button" class="cws-code-copy-btn" onclick="navigator.clipboard.writeText(this.closest('pre').querySelector('code').innerText);window.toast&&window.toast('Copied code')">Copy</button></div><code>${escapedCode}</code></pre>`
      );
      return `%%CWS_CODE_${idx}%%`;
    });
    // Handle unclosed code block during streaming
    s = s.replace(/```\s*([a-zA-Z0-9_\-\.]*)?\s*\r?\n([\s\S]*)$/g, (_, lang, code) => {
      const idx = codeBlocks.length;
      const cleanLang = (lang || 'code').trim().toUpperCase();
      const escapedCode = escHtml(code.trim());
      codeBlocks.push(
        `<pre class="cws-code-block"><div class="cws-code-header"><span class="cws-code-lang">${cleanLang} (typing...)</span></div><code>${escapedCode}</code></pre>`
      );
      return `%%CWS_CODE_${idx}%%`;
    });

    // 2. Escape HTML in remaining text
    s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // 3. Collapsible action pills & status chips
    s = s.replace(/&lt;details\s+class="cws-action-pill"&gt;([\s\S]*?)&lt;\/details&gt;/g, (m, inner) => {
      return `<details class="cws-action-pill">${inner}</details>`;
    });
    s = s.replace(/\[STATUS:([^\]]+)\]/g, (m, pill) => {
      return `\n<div class="cws-status-chip">${pill}</div>\n`;
    });

    // 4. Clean up inline '---' separating sections if jammed into a single line
    s = s.replace(/\s+---\s+(#{1,4})/g, '\n\n---\n\n$1');
    s = s.replace(/\s+---\s+/g, '\n\n---\n\n');
    s = s.replace(/\s+(#{1,4})\s+/g, '\n\n$1 ');

    // 5. Tables (Markdown pipe tables)
    const tablePattern = /^(\|.+\|)\r?\n(\|[\s\-:|]+\|)\r?\n((?:\|.+\|\r?\n?)+)/gm;
    s = s.replace(tablePattern, (match, header, sep, bodyBlock) => {
      const hCells = header.split('|').filter(c => c.trim());
      const rows = bodyBlock.trim().split('\n');
      let html = '<div class="cws-table-wrap"><table><thead><tr>';
      hCells.forEach(c => {
        let cellText = c.trim();
        cellText = cellText.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html += `<th>${cellText}</th>`;
      });
      html += '</tr></thead><tbody>';
      rows.forEach(row => {
        const cells = row.split('|').filter(c => c.trim());
        if (!cells.length || cells.every(c => /^[\s\-:]+$/.test(c))) return;
        html += '<tr>';
        cells.forEach(c => {
          let cellText = c.trim();
          cellText = cellText.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
          html += `<td>${cellText}</td>`;
        });
        html += '</tr>';
      });
      html += '</tbody></table></div>';
      return html;
    });

    // 6. Headers (Clean any redundant inner **)
    s = s.replace(/^#### (.+)$/gm, (_, t) => `<h4>${t.replace(/^\*\*(.*)\*\*$/, '$1')}</h4>`);
    s = s.replace(/^### (.+)$/gm, (_, t) => `<h3>${t.replace(/^\*\*(.*)\*\*$/, '$1')}</h3>`);
    s = s.replace(/^## (.+)$/gm, (_, t) => `<h2>${t.replace(/^\*\*(.*)\*\*$/, '$1')}</h2>`);
    s = s.replace(/^# (.+)$/gm, (_, t) => `<h1>${t.replace(/^\*\*(.*)\*\*$/, '$1')}</h1>`);

    // 7. Blockquotes
    s = s.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

    // 8. Horizontal rules
    s = s.replace(/^(?:---|\*\*\*|___)$/gm, '<hr class="cws-hr" />');

    // 9. Unordered lists (- or *)
    s = s.replace(/(?:^|\n)((?:[\t ]*[-*•]\s+.+\n?)+)/g, (match, block) => {
      const items = block.trim().split('\n').map(line => {
        return '<li>' + line.replace(/^[\t ]*[-*•]\s+/, '') + '</li>';
      }).join('');
      return `<ul>${items}</ul>`;
    });

    // 10. Ordered lists (1., 2.)
    s = s.replace(/(?:^|\n)((?:[\t ]*\d+\.\s+.+\n?)+)/g, (match, block) => {
      const items = block.trim().split('\n').map(line => {
        return '<li>' + line.replace(/^[\t ]*\d+\.\s+/, '') + '</li>';
      }).join('');
      return `<ol>${items}</ol>`;
    });

    // 11. Clickable UI Provenance Sources: [SOURCE: filename | PAGE n]
    s = s.replace(/\[SOURCE:\s*([^\]|\n]+?)\s*(?:\|\s*PAGE\s+([^\]|\n]+?))?\]/gi, (marker, name, page) => {
      const cleanName = name.trim();
      const pageStr = page ? ` · Page ${page.trim()}` : '';
      return `<button type="button" class="cws-src-pill" onclick="window.cwsInspectFile(${escAttr(JSON.stringify(cleanName))})" title="Inspect ${escAttr(cleanName)}">` +
             `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>` +
             `<span>${escHtml(cleanName)}${pageStr}</span><span style="opacity:0.65;font-size:10px">↗</span></button>`;
    });

    // 12. Inline formatting
    s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    s = s.replace(/`([^`]+)`/g, '<code class="cws-inline-code">$1</code>');

    // 13. Links
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:var(--cws-accent)">$1</a>');

    // 14. Paragraphs and line breaks
    s = s.replace(/\n\n+/g, '</p><p>');
    s = s.replace(/\n/g, '<br>');

    // Clean excessive breaks after/before block elements
    s = s.replace(/(<\/(?:h[1-4]|table|div|ul|ol|pre|hr|blockquote)>)(?:<br>|<\/?p>)+/g, '$1');
    s = s.replace(/(?:<br>|<\/?p>)+(<(?:h[1-4]|table|div|ul|ol|pre|hr|blockquote))/g, '$1');

    // Wrap in paragraph if needed
    if (!s.startsWith('<h') && !s.startsWith('<div') && !s.startsWith('<pre') && !s.startsWith('<table') && !s.startsWith('<ul') && !s.startsWith('<ol')) {
      s = `<p>${s}</p>`;
    }

    // 15. Restore Code Blocks
    codeBlocks.forEach((block, i) => {
      s = s.replace(`%%CWS_CODE_${i}%%`, block);
    });

    return s;
  }

  /* --------------------------------------------------------------------------
     SIDEBAR RENDERING
     -------------------------------------------------------------------------- */
  function renderSidebar() {
    const recentsEl = document.getElementById('cwsRecentsList');
    if (!recentsEl) return;

    // Update nav active classes
    document.querySelectorAll('#cwsPrimaryNav .cws-nav-item').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.nav === CWS_STATE.activeNav);
    });

    const q = CWS_STATE.searchQuery;
    let filteredSessions = (CWS_STATE.sessions || []).filter(s => !q || (s.title || '').toLowerCase().includes(q));

    if (CWS_STATE.recentsSort === 'asc') {
      filteredSessions = [...filteredSessions].sort((a, b) => (a.updatedAt || 0) - (b.updatedAt || 0));
    } else {
      filteredSessions = [...filteredSessions].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    }

    const recentsSec = document.getElementById('cwsRecentsSec');
    if (recentsSec) {
      recentsSec.classList.toggle('cws-sec-collapsed', !!CWS_STATE.sectionsCollapsed.recents);
    }
    const pinnedSec = document.getElementById('cwsPinnedSec');
    if (pinnedSec) {
      pinnedSec.classList.toggle('cws-sec-collapsed', !!CWS_STATE.sectionsCollapsed.pinned);
    }

    if (CWS_STATE.sectionsCollapsed.recents) {
      recentsEl.innerHTML = '';
      return;
    }

    recentsEl.innerHTML = filteredSessions.slice(0, 24).map(s => {
      const isActive = s.id === CWS_STATE.activeSessionId && CWS_STATE.activeNav === 'chats';
      const timeStr = s.timeBadge || formatTimeAgo(s.updatedAt);
      return `
        <div class="cws-recent-row ${isActive ? 'active' : ''}" onclick="window.cwsSelectSession(${escAttr(JSON.stringify(s.id))})" title="${escAttr(s.title)}">
          <div class="cws-recent-left">
            <span class="cws-recent-ico">${ICONS.doc}</span>
            <span class="cws-recent-title">${escHtml(s.title || 'Untitled chat')}</span>
          </div>
          <span class="cws-recent-time">${escHtml(timeStr)}</span>
          <button type="button" class="cws-recent-del-btn" onclick="event.stopPropagation();window.cwsDeleteSession(${escAttr(JSON.stringify(s.id))})" title="Delete chat">
            ${ICONS.trash}
          </button>
        </div>
      `;
    }).join('');
  }

  /* --------------------------------------------------------------------------
     HEADER (Clean, Minimalist, No Default Hardcoded Text)
     -------------------------------------------------------------------------- */
  function renderHeader() {
    const compProjName = document.getElementById('cwsComposerProjName');
    const proj = getProj();

    if (compProjName) compProjName.textContent = proj || 'Project or folder';

    const compWrap = document.getElementById('cwsComposerWrap');
    if (compWrap) {
      compWrap.style.display = (CWS_STATE.activeNav === 'chats' || CWS_STATE.activeNav === 'home') ? 'flex' : 'none';
    }
  }

  /* --------------------------------------------------------------------------
     COMPOSER POSITIONING (Hero vs Docked Bottom)
     -------------------------------------------------------------------------- */
  function positionComposer(inHero) {
    const comp = document.getElementById('cwsComposerWrap');
    if (!comp) return;
    if (inHero) {
      const slot = document.getElementById('cwsHeroComposerSlot');
      if (slot && comp.parentElement !== slot) {
        slot.appendChild(comp);
        comp.classList.add('in-hero');
      }
    } else {
      const main = document.querySelector('.cws-main');
      if (main && comp.parentElement !== main) {
        main.appendChild(comp);
        comp.classList.remove('in-hero');
      }
    }
  }

  /* --------------------------------------------------------------------------
     STAGE ROUTING & VIEWS
     -------------------------------------------------------------------------- */
  function renderStage() {
    const stage = document.getElementById('cwsStageBody');
    if (!stage) return;
    const main = document.querySelector('.cws-main');
    const comp = document.getElementById('cwsComposerWrap');
    if (comp && main && comp.parentElement !== main) {
      main.appendChild(comp);
      comp.classList.remove('in-hero');
    }

    if (CWS_STATE.activeNav === 'projects') {
      positionComposer(false);
      renderProjectsView(stage);
      return;
    }
    if (CWS_STATE.activeNav === 'knowledge') {
      positionComposer(false);
      renderKnowledgeView(stage);
      return;
    }
    if (CWS_STATE.activeNav === 'tools') {
      positionComposer(false);
      renderToolsView(stage);
      return;
    }
    if (CWS_STATE.activeNav === 'reports') {
      positionComposer(false);
      renderReportsView(stage);
      return;
    }
    if (CWS_STATE.activeNav === 'automations') {
      positionComposer(false);
      renderAutomationsView(stage);
      return;
    }
    if (CWS_STATE.activeNav === 'settings') {
      positionComposer(false);
      renderSettingsView(stage);
      return;
    }

    // Default: 'chats' or 'home'
    const sess = getActiveSession();

    // Welcome Screen when no messages exist (Matches reference screenshot)
    if (!sess.messages || !sess.messages.length) {
      const currentProj = getProj();
      const statusText = currentProj ? `Active: <strong>${escHtml(currentProj)}</strong> · <span id="cwsSandboxStatus">Checking isolated Python worker…</span>` : `<span id="cwsSandboxStatus">Checking isolated Python worker…</span>`;
      stage.innerHTML = `
        <div class="cws-welcome-stage">
          <div class="cws-hero-emblem" aria-hidden="true"></div>
          <h1 class="cws-hero-heading">Engineering Intelligence</h1>
          <p class="cws-hero-subtitle">How can I help with your project today?</p>
          <div class="cws-hero-badge">
            <span class="cws-hero-dot"></span>
            <span>${statusText}</span>
          </div>
          <div class="cws-hero-composer-slot" id="cwsHeroComposerSlot"></div>
        </div>
      `;
      refreshSandboxBadge();
      positionComposer(true);
      updateSendBtnState();
      return;
    }

    // Active conversation layout
    positionComposer(false);
    let html = `<div class="cws-stream-col" id="cwsStreamCol">`;
    html += sess.messages.map(m => {
      if (m.role === 'user') {
        const atts = m.attachments || [];
        const attsHtml = atts.length ? `
          <div class="cws-msg-attachments">
            ${atts.map(a => `
              <div class="cws-msg-att-card" onclick="window.cwsInspectFile(${escAttr(JSON.stringify(a.serverPath || a.name))})" title="${escAttr(a.name)} (Click to view)">
                <div class="cws-attachment-thumb-wrap">
                  ${a.previewUrl ? `<img class="cws-attachment-thumb-img" src="${escAttr(a.previewUrl)}" alt="${escAttr(a.name)}" />` : `
                    <div class="cws-attachment-skeleton">
                      <div class="cws-att-sk-line" style="width:75%"></div>
                      <div class="cws-att-sk-line" style="width:90%"></div>
                      <div class="cws-att-sk-line" style="width:60%"></div>
                      <div class="cws-att-sk-line" style="width:80%;margin-top:3px"></div>
                      <div class="cws-att-sk-line" style="width:70%"></div>
                    </div>
                  `}
                </div>
                <div class="cws-attachment-badge">${escHtml(a.badge || 'PDF')}</div>
              </div>
            `).join('')}
          </div>
        ` : '';
        return `
          <div class="cws-msg-user">
            <div class="cws-msg-user-bub">
              ${attsHtml}
              ${m.content ? `<div>${escHtml(m.content)}</div>` : ''}
            </div>
          </div>
        `;
      } else {
        const formattedText = formatCoworkMessage(m.content || '');
        const artifactsHtml = (m.artifacts && m.artifacts.length) ? `
          <div style="margin-top:12px;padding:12px 14px;border-radius:10px;background:var(--cws-accent-light);border:1px solid #fed7aa;display:flex;flex-direction:column;gap:8px">
            <div style="font-size:12px;font-weight:700;color:var(--cws-accent)">🧩 Saved to Workspace (${m.artifacts.length} file${m.artifacts.length === 1 ? '' : 's'})</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              ${m.artifacts.map(fp => `
                <span style="display:inline-flex;align-items:center;gap:6px;background:var(--cws-surface);border:1px solid var(--cws-border);padding:6px 11px;border-radius:8px;font-size:12px">
                  <b>📄 ${escHtml(fp)}</b>
                  <button type="button" class="cws-btn" style="padding:2px 7px;font-size:11px" onclick="window.cwsInspectFile(${escAttr(JSON.stringify(fp))})">👁️ Preview</button>
                  <button type="button" class="cws-btn" style="padding:2px 7px;font-size:11px" onclick="window.downloadCoworkFile(${escAttr(JSON.stringify(fp))})">⬇️ Download</button>
                  <button type="button" class="cws-btn" style="padding:2px 7px;font-size:11px;color:#dc2626;border-color:#fca5a5" onclick="window.cwsDeleteWorkspaceFile(${escAttr(JSON.stringify(fp))})" title="Delete file">🗑️ Delete</button>
                </span>
              `).join('')}
            </div>
          </div>
        ` : '';
        return `<div class="cws-msg-ai">${formattedText}${artifactsHtml}</div>`;
      }
    }).join('');
    html += `</div>`;

    stage.innerHTML = html;
    stage.scrollTop = stage.scrollHeight;
    updateSendBtnState();
  }

  /* --------------------------------------------------------------------------
     SECONDARY VIEWS (Projects, Knowledge, Tools, Reports, Automations, Settings)
     -------------------------------------------------------------------------- */
    /* --------------------------------------------------------------------------
     PROJECTS VIEW (Matches 2nd Reference Screenshot)
     -------------------------------------------------------------------------- */
  async function fetchProjectsOverview() {
    try {
      const r = await fetch('/api/projects/overview', { headers: getAuthHeaders() });
      if (r.ok) {
        const d = await r.json();
        if (d && Array.isArray(d.projects)) {
          CWS_STATE.projectsOverview = d.projects;
          return d.projects;
        }
      }
    } catch (e) {}
    return null;
  }

  function renderProjectsView(stage) {
    const list = CWS_STATE.projectsOverview || [];
    const starred = CWS_STATE.starredProjects || [];
    const q = (CWS_STATE.projectFilterQuery || '').toLowerCase();
    let filtered = list.filter(p => !q || (p.name || '').toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q));
    
    if (CWS_STATE.projectsSort === 'asc') {
      filtered = [...filtered].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    } else {
      filtered = [...filtered].sort((a, b) => {
        const aStar = starred.includes(a.name) ? 1 : 0;
        const bStar = starred.includes(b.name) ? 1 : 0;
        if (aStar !== bStar) return bStar - aStar;
        return (new Date(b.updated_at || b.created_at || 0)) - (new Date(a.updated_at || a.created_at || 0));
      });
    }

    const currentP = getProj();

    stage.innerHTML = `
      <div class="cws-projects-wrapper">
        <!-- Top Header: Title & Actions (Matches 2nd Reference Screenshot) -->
        <div class="cws-projects-top-bar">
          <h1 class="cws-projects-title">Projects</h1>
          <div class="cws-projects-actions">
            <button type="button" class="cws-icon-btn" onclick="window.cwsFilterProjectsPrompt()" title="Search projects">
              ${ICONS.search}
            </button>
            <button type="button" class="cws-icon-btn" onclick="window.cwsSortProjectsToggle()" title="Sort projects">
              ${ICONS.sort}
            </button>
            <button type="button" class="cws-btn-new-project-pill" onclick="window.cwsShowCreateProjectModal()">
              New project
            </button>
          </div>
        </div>

        <!-- Project Cards Grid (Matches 2nd Reference Screenshot) -->
        <div class="cws-project-cards-grid">
          ${filtered.length > 0 ? filtered.map(p => {
            const isStar = starred.includes(p.name);
            const isActive = p.name === currentP;
            const desc = p.description || 'Workspace project for design review and analysis';
            const timeAgo = formatTimeAgo(new Date(p.updated_at || p.created_at || Date.now()));
            return `
              <div class="cws-project-card ${isActive ? 'active' : ''}" onclick="window.cwsSelectAndOpenProject(${escAttr(JSON.stringify(p.name))})" title="Open project: ${escAttr(p.name)}">
                <div class="cws-proj-card-top">
                  <div class="cws-proj-card-name">
                    <span>${escHtml(p.name)}</span>
                    <button type="button" class="cws-proj-star-btn ${isStar ? 'active' : ''}" onclick="event.stopPropagation();window.cwsToggleProjectStar(${escAttr(JSON.stringify(p.name))})" title="${isStar ? 'Unstar' : 'Star project'}">★</button>
                  </div>
                  <div style="display:flex;align-items:center;gap:4px" onclick="event.stopPropagation()">
                    ${isActive ? '<span style="font-size:11px;padding:2px 6px;border-radius:4px;background:#e0f2fe;color:#0284c7;font-weight:600">Active</span>' : ''}
                  </div>
                </div>
                <div class="cws-proj-card-desc">${escHtml(desc)}</div>
                <div class="cws-proj-card-bottom">
                  <span>${escHtml(timeAgo)}</span>
                  <span>${p.file_count || 0} file(s) · ${escHtml(p.created_by || 'admin')}</span>
                </div>
              </div>
            `;
          }).join('') : `
            <div style="grid-column:1/-1;text-align:center;padding:48px 20px;border:1px dashed var(--cws-border);border-radius:12px;color:var(--cws-muted)">
              <p style="margin:0 0 12px;font-size:14px">No projects found.</p>
              <button type="button" class="cws-btn-new-project-pill" onclick="window.cwsShowCreateProjectModal()">Create a project</button>
            </div>
          `}
        </div>
      </div>
    `;

    // Fetch fresh overview asynchronously if not fetched yet
    if (!CWS_STATE.projectsOverviewFetched) {
      CWS_STATE.projectsOverviewFetched = true;
      fetchProjectsOverview().then(res => {
        if (res && CWS_STATE.activeNav === 'projects') {
          renderProjectsView(stage);
        }
      });
    }
  }


  function renderKnowledgeView(stage) {
    const files = (CWS_STATE.tree && CWS_STATE.tree.files) || [];
    const proj = getProj();
    stage.innerHTML = `
      <div class="cws-stream-col">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
          <div>
            <h2 style="margin:0;font-size:20px;font-weight:700">Knowledge Base &amp; Documents</h2>
            <p style="margin:4px 0 0;font-size:13px;color:var(--cws-muted)">Indexed drawings, technical specifications, and standards ${proj ? 'for ' + escHtml(proj) : ''}.</p>
          </div>
          <button type="button" class="cws-btn primary" onclick="window.cwsTriggerAttach()">+ Add Document</button>
        </div>

        <div class="cws-grid-cards">
          ${!files.length ? `
            <div style="grid-column:1/-1;padding:32px;text-align:center;color:var(--cws-muted);border:1px dashed var(--cws-border);border-radius:12px">
              No files in the knowledge base yet. Upload drawings or documents to begin analysis.
            </div>
          ` : files.map(fl => `
            <div class="cws-card">
              <div>
                <div style="font-size:14px;font-weight:600;word-break:break-word">📄 ${escHtml(fl.name)}</div>
                <div style="font-size:11.5px;color:var(--cws-muted);margin-top:4px">${fmtBytes(fl.size)} · Folder: ${escHtml(fl.folder || '/')}</div>
              </div>
              <div style="display:flex;gap:6px">
                <button type="button" class="cws-btn primary" onclick="window.cwsInspectFile(${escAttr(JSON.stringify(fl.path))})">Inspect</button>
                <button type="button" class="cws-btn" onclick="window.downloadCoworkFile(${escAttr(JSON.stringify(fl.path))})">Download</button>
                <button type="button" class="cws-btn" style="color:#dc2626;border-color:#fca5a5" onclick="window.cwsDeleteWorkspaceFile(${escAttr(JSON.stringify(fl.path))})" title="Delete file">🗑️ Delete</button>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function renderToolsView(stage) {
    stage.innerHTML = `
      <div class="cws-stream-col">
        <div>
          <h2 style="margin:0;font-size:20px;font-weight:700">Engineering AI Tools</h2>
          <p style="margin:4px 0 0;font-size:13px;color:var(--cws-muted)">Integrated execution engines for architectural, structural, and MEP workflows.</p>
        </div>
        <div class="cws-grid-cards">
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">📄 PDF Drawing &amp; Spec Reading (pdf-reading)</div>
              <p style="font-size:12px;color:var(--cws-muted);margin:6px 0 0">Extract material callouts, title blocks, schedules, and general notes from multi-page drawing sets.</p>
            </div>
            <button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Extract all material specifications, titleblock metadata, and drawing notes from this project.')">Extract Drawing Specs</button>
          </div>
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">📑 PDF Split, Merge &amp; Stamps (pdf)</div>
              <p style="font-size:12px;color:var(--cws-muted);margin:6px 0 0">Split multi-discipline packages (Arch, Struct, MEP), merge addenda, and stamp engineering approvals.</p>
            </div>
            <button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Split drawing package into discipline-specific sets (Arch, Struct, MEP) and apply approval stamps.')">Split &amp; Stamp PDF</button>
          </div>
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">📊 Construction Takeoffs &amp; BOQ (xlsx)</div>
              <p style="font-size:12px;color:var(--cws-muted);margin:6px 0 0">Generate Bill of Quantities, material schedules, and cost estimates with embedded Excel formulas.</p>
            </div>
            <button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Convert extracted drawing schedules into an editable construction takeoff spreadsheet (.xlsx) with formulas.')">Generate Takeoff (.xlsx)</button>
          </div>
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">📝 Technical Specs &amp; Reports (docx)</div>
              <p style="font-size:12px;color:var(--cws-muted);margin:6px 0 0">Draft CSI MasterFormat specifications, site inspection logs, and engineering compliance reports.</p>
            </div>
            <button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Draft a CSI MasterFormat specification document in DOCX format for this project.')">Draft Spec (.docx)</button>
          </div>
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">🔍 Smart AEC Document Routing (file-reading)</div>
              <p style="font-size:12px;color:var(--cws-muted);margin:6px 0 0">Auto-detect drawing sets, BIM models (.ifc), CAD drawings (.dwg/.dxf), and route to optimal local parser.</p>
            </div>
            <button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Inspect all files in this workspace, identify document types, and compile a coordination summary.')">Inspect Workspace Files</button>
          </div>
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">🐍 Python Calculation Sandbox</div>
              <p style="font-size:12px;color:var(--cws-muted);margin:6px 0 0">Run isolated pandas, openpyxl, and numpy scripts against project files.</p>
            </div>
            <button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Use Python to verify all Excel schedules in this project and output summary tables.')">Run Python Audit</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderReportsView(stage) {
    const proj = getProj();
    stage.innerHTML = `
      <div class="cws-stream-col">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
          <div>
            <h2 style="margin:0;font-size:20px;font-weight:700">Engineering Reports &amp; Summaries</h2>
            <p style="margin:4px 0 0;font-size:13px;color:var(--cws-muted)">Generated Markdown, PDF, and Excel reports ${proj ? 'compiled for ' + escHtml(proj) : ''}.</p>
          </div>
          <button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Generate a comprehensive engineering review report in Markdown and save as review_report.md.')">+ Generate New Report</button>
        </div>
        <div class="cws-grid-cards">
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">📊 Latest Engineering Review</div>
              <div style="font-size:12px;color:var(--cws-muted);margin-top:4px">Synthesis of architectural, structural, and MEP observations.</div>
            </div>
            <button type="button" class="cws-btn" onclick="window.cwsQuickPrompt('Show me the latest Engineering Review Report.')">View Report</button>
          </div>
          <div class="cws-card">
            <div>
              <div style="font-size:15px;font-weight:700">📋 Area &amp; GFA Audit Summary</div>
              <div style="font-size:12px;color:var(--cws-muted);margin-top:4px">Whole-sheet Mixed Use GFA calculations and schedule checks.</div>
            </div>
            <button type="button" class="cws-btn" onclick="window.cwsQuickPrompt('Compute whole-sheet Mixed Use GFA and display area summary table.')">View Schedule</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderAutomationsView(stage) {
    const tasks = CWS_STATE.scheduledTasks || [];
    stage.innerHTML = `
      <div class="cws-stream-col">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
          <div>
            <h2 style="margin:0;font-size:20px;font-weight:700">Saved workflows</h2>
            <p style="margin:4px 0 0;font-size:13px;color:var(--cws-muted)">These workflows run only when you click Run Workflow. Automatic scheduling is unavailable.</p>
          </div>
        </div>
        <div class="cws-grid-cards">
          ${tasks.map(t => `
            <div class="cws-card">
              <div>
                <span class="cws-badge" style="background:#f1f5f9;color:#475569;padding:2px 7px;border-radius:6px;font-size:11px;font-weight:700">${escHtml(t.badge)}</span>
                <div style="font-size:15px;font-weight:700;margin-top:6px">${escHtml(t.title)}</div>
                <div style="font-size:12px;color:var(--cws-muted);margin-top:4px">${escHtml(t.prompt)}</div>
              </div>
              <button type="button" class="cws-btn primary" onclick="window.cwsSetNav('chats');window.cwsQuickPrompt(${escAttr(JSON.stringify(t.prompt))})">▶ Run Workflow</button>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function renderSettingsView(stage) {
    const customInst = CWS_STATE.customInstructions[CWS_STATE.activeFolder || '__root__'] || '';
    stage.innerHTML = `
      <div class="cws-stream-col">
        <div>
          <h2 style="margin:0;font-size:20px;font-weight:700">Workspace Settings &amp; Custom Instructions</h2>
          <p style="margin:4px 0 0;font-size:13px;color:var(--cws-muted)">Configure custom guidelines, measurement units, and calculation behavior for this project.</p>
        </div>
        <div class="cws-card" style="margin-top:16px">
          <div style="font-size:13.5px;font-weight:700">Project System Instructions (Applied to All Prompts)</div>
          <textarea id="cwsInstTextarea" rows="6" style="width:100%;border:1px solid var(--cws-border);border-radius:8px;padding:12px;font-size:13px;color:var(--cws-text);background:var(--cws-surface);resize:vertical" placeholder="e.g. Always output dimensions in millimeters (mm) and areas in square meters (m²).">${escHtml(customInst)}</textarea>
          <div style="display:flex;justify-content:flex-end">
            <button type="button" class="cws-btn primary" onclick="window.cwsSaveCustomInstructions()">Save Settings</button>
          </div>
        </div>
      </div>
    `;
  }

  window.cwsSaveCustomInstructions = function () {
    const ta = document.getElementById('cwsInstTextarea');
    if (!ta) return;
    const val = ta.value.trim();
    CWS_STATE.customInstructions[CWS_STATE.activeFolder || '__root__'] = val;
    saveLocalData();
    if (window.toast) window.toast('Project instructions saved successfully');
  };

  /* --------------------------------------------------------------------------
     DRAWER RENDERING (File Inspector & File Management with Delete)
     -------------------------------------------------------------------------- */
  function renderDrawer() {
    const body = document.getElementById('cwsDrawerBody');
    const title = document.getElementById('cwsDrawerTitle');
    const tabsWrap = document.getElementById('cwsDrawerTabsWrap');
    if (!body) return;

    if (CWS_STATE.previewFile) {
      const pf = CWS_STATE.previewFile;
      if (title) title.textContent = pf.name || 'File Preview';
      const ext = (pf.path.split('.').pop() || '').toLowerCase();

      if (tabsWrap) {
        tabsWrap.style.display = 'flex';
        tabsWrap.innerHTML = `
          <div class="cws-drawer-tabs">
            <button type="button" class="cws-tab-btn ${pf.modeTab === 'preview' ? 'active' : ''}" onclick="window.cwsSetPreviewTab('preview')">Preview</button>
            <button type="button" class="cws-tab-btn ${pf.modeTab === 'code' ? 'active' : ''}" onclick="window.cwsSetPreviewTab('code')">Code / Text</button>
            ${['xlsx', 'xls', 'csv'].includes(ext) ? `<button type="button" class="cws-tab-btn ${pf.modeTab === 'table' ? 'active' : ''}" onclick="window.cwsSetPreviewTab('table')">Table</button>` : ''}
          </div>
        `;
      }

      let contentHtml = '';
      if (ext === 'pdf') {
        contentHtml = `
          <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;padding-bottom:4px;border-bottom:1px solid var(--cws-border)">
            <button type="button" class="cws-btn" onclick="window.cwsClearPreview()">← Back</button>
            <div style="display:flex;gap:4px;flex-wrap:wrap">
              <button type="button" class="cws-btn" onclick="window.cwsPdfActionPrompt('fill_form', ${escAttr(JSON.stringify(pf.name))})" title="Analyze and fill out form fields and inspection checklists">📝 Fill Form</button>
              <button type="button" class="cws-btn" onclick="window.cwsPdfActionPrompt('annotate', ${escAttr(JSON.stringify(pf.name))})" title="Annotate, highlight and review against Dubai Building Code">🖍️ Annotate</button>
              <button type="button" class="cws-btn" onclick="window.cwsPdfActionPrompt('stamp', ${escAttr(JSON.stringify(pf.name))})" title="Stamp approval or engineering status">🏷️ Stamp</button>
              <button type="button" class="cws-btn" onclick="window.cwsPdfActionPrompt('sign', ${escAttr(JSON.stringify(pf.name))})" title="Place signature or approval sign-off">✍️ Sign</button>
              <button type="button" class="cws-btn" onclick="window.downloadCoworkFile(${escAttr(JSON.stringify(pf.path))})">⬇️ Download</button>
              <button type="button" class="cws-btn" style="color:#dc2626;border-color:#fca5a5" onclick="window.cwsDeleteWorkspaceFile(${escAttr(JSON.stringify(pf.path))})" title="Delete File">🗑️</button>
            </div>
          </div>
          <iframe class="cws-pdf-viewer" src="${escAttr(pf.blobUrl || `/projects/${encodeURIComponent(getProj())}/agent/workspace-file?path=${encodeURIComponent(pf.path)}&inline=1`)}"></iframe>
        `;
      } else if (['xlsx', 'xls', 'csv'].includes(ext)) {
        if (pf.modeTab === 'table') {
          const lines = (pf.content || '').split('\n').filter(l => l.trim());
          const rows = lines.map(l => l.split(/\t|,|\|/).map(c => c.trim()));
          const header = rows[0] || [];
          const bodyRows = rows.slice(1, 100);
          contentHtml = `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
              <button type="button" class="cws-btn" onclick="window.cwsClearPreview()">← Back</button>
              <div style="display:flex;gap:6px">
                <button type="button" class="cws-btn" onclick="window.downloadCoworkFile(${escAttr(JSON.stringify(pf.path))})">⬇️ Download Excel</button>
                <button type="button" class="cws-btn" style="color:#dc2626;border-color:#fca5a5" onclick="window.cwsDeleteWorkspaceFile(${escAttr(JSON.stringify(pf.path))})">🗑️ Delete File</button>
              </div>
            </div>
            <div style="flex:1;overflow:auto;border:1px solid var(--cws-border);border-radius:8px">
              <table class="cws-table-viewer" style="width:100%;border-collapse:collapse;font-size:12px">
                <thead><tr>${header.map(h => `<th style="padding:6px 10px;background:var(--cws-surface-hover);border:1px solid var(--cws-border)">${escHtml(h)}</th>`).join('')}</tr></thead>
                <tbody>${bodyRows.map(r => `<tr>${r.map(c => `<td style="padding:6px 10px;border:1px solid var(--cws-border)">${escHtml(c)}</td>`).join('')}</tr>`).join('')}</tbody>
              </table>
            </div>
          `;
        } else {
          contentHtml = `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
              <button type="button" class="cws-btn" onclick="window.cwsClearPreview()">← Back</button>
              <div style="display:flex;gap:6px">
                <button type="button" class="cws-btn" onclick="window.downloadCoworkFile(${escAttr(JSON.stringify(pf.path))})">⬇️ Download</button>
                <button type="button" class="cws-btn" style="color:#dc2626;border-color:#fca5a5" onclick="window.cwsDeleteWorkspaceFile(${escAttr(JSON.stringify(pf.path))})">🗑️ Delete File</button>
              </div>
            </div>
            <textarea id="cwsDrawerEditor" readonly style="width:100%;flex:1;min-height:480px;background:var(--cws-code-bg);color:#f8fafc;border:1px solid var(--cws-border);border-radius:8px;padding:12px;font-family:Consolas,monospace;font-size:12px">${escHtml(pf.content || '')}</textarea>
          `;
        }
      } else {
        contentHtml = `
          <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
            <button type="button" class="cws-btn" onclick="window.cwsClearPreview()">← Back</button>
            <div style="display:flex;gap:6px">
              ${ext === 'py' ? `<button type="button" class="cws-btn primary" onclick="window.cwsQuickPrompt('Run script ' + ${escAttr(JSON.stringify(pf.path))} + ' in Python sandbox and report findings.')">▶ Run Sandbox</button>` : ''}
              <button type="button" class="cws-btn" onclick="window.downloadCoworkFile(${escAttr(JSON.stringify(pf.path))})">⬇️ Download</button>
              <button type="button" class="cws-btn" style="color:#dc2626;border-color:#fca5a5" onclick="window.cwsDeleteWorkspaceFile(${escAttr(JSON.stringify(pf.path))})">🗑️ Delete File</button>
            </div>
          </div>
          <textarea id="cwsDrawerEditor" ${pf.editable ? '' : 'readonly'} style="width:100%;flex:1;min-height:480px;background:var(--cws-code-bg);color:#f8fafc;border:1px solid var(--cws-border);border-radius:8px;padding:12px;font-family:Consolas,monospace;font-size:12px">${escHtml(pf.content || '')}</textarea>
        `;
      }

      body.innerHTML = contentHtml;
      return;
    }

    // Default: List Project Files
    if (tabsWrap) tabsWrap.style.display = 'none';
    const folder = CWS_STATE.activeFolder || '';
    if (title) title.textContent = folder ? `📁 ${folder}` : '📁 Project Files';
    const files = ((CWS_STATE.tree && CWS_STATE.tree.files) || []).filter(f => (f.folder || '') === folder);

    body.innerHTML = `
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button type="button" class="cws-btn primary" onclick="window.cwsTriggerAttach()">⬆️ Upload Files</button>
        <button type="button" class="cws-btn" onclick="window.cwsCreateFolderPrompt()">+ Folder</button>
      </div>
      <div style="font-size:11.5px;font-weight:700;color:var(--cws-muted);margin-top:4px">FILES IN PROJECT (${files.length})</div>
      ${!files.length ? `<div style="padding:24px;border:1px dashed var(--cws-border);border-radius:8px;text-align:center;color:var(--cws-muted);font-size:13px">No files in this folder yet.</div>` : files.map(fl => `
        <div style="padding:10px 12px;border:1px solid var(--cws-border);border-radius:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;background:var(--cws-sb-bg)">
          <div style="min-width:0;flex:1;cursor:pointer" onclick="window.cwsInspectFile(${escAttr(JSON.stringify(fl.path))})">
            <div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">📄 ${escHtml(fl.name)}</div>
            <div style="font-size:11px;color:var(--cws-muted)">${fmtBytes(fl.size)}</div>
          </div>
          <div style="display:flex;gap:6px">
            <button type="button" class="cws-btn" style="padding:3px 8px;font-size:11.5px" onclick="window.cwsInspectFile(${escAttr(JSON.stringify(fl.path))})">Preview</button>
            <button type="button" class="cws-btn" style="padding:3px 8px;font-size:11.5px;color:#dc2626;border-color:#fca5a5" onclick="event.stopPropagation();window.cwsDeleteWorkspaceFile(${escAttr(JSON.stringify(fl.path))})" title="Delete file">🗑️</button>
          </div>
        </div>
      `).join('')}
    `;
  }

  window.cwsSetPreviewTab = function (tab) {
    if (CWS_STATE.previewFile) {
      CWS_STATE.previewFile.modeTab = tab;
      renderDrawer();
    }
  };

  window.cwsClearPreview = function () {
    CWS_STATE.previewFile = null;
    renderDrawer();
  };

  window.downloadCoworkFile = function (path) {
    const proj = getProj();
    if (!proj || !path) return;
    const a = document.createElement('a');
    a.href = `/projects/${encodeURIComponent(proj)}/agent/workspace-file?path=${encodeURIComponent(path)}`;
    a.download = path.split('/').pop();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  window.cwsInspectFile = async function (path) {
    const proj = getProj();
    if (!proj || !path) return;
    window.cwsToggleDrawer(true);

    const ext = (path.split('.').pop() || '').toLowerCase();
    const defaultTab = ext === 'pdf' ? 'preview' : (['xlsx', 'xls', 'csv'].includes(ext) ? 'table' : (['md', 'html'].includes(ext) ? 'preview' : 'code'));

    CWS_STATE.previewFile = {
      path,
      name: path.split('/').pop(),
      content: 'Loading file…',
      editable: false,
      size: 0,
      modeTab: defaultTab,
      blobUrl: null
    };
    renderDrawer();

    try {
      if (ext === 'pdf') {
        const token = getAuthToken();
        const tokenQuery = token ? `` : '';
        const urlInline = `/projects/${encodeURIComponent(proj)}/agent/workspace-file?path=${encodeURIComponent(path)}&inline=1${tokenQuery}`;
        const rBlob = await fetch(urlInline, { headers: getAuthHeaders() });
        if (rBlob.ok) {
          const blob = await rBlob.blob();
          CWS_STATE.previewFile.blobUrl = URL.createObjectURL(blob);
          CWS_STATE.previewFile.name = path.split('/').pop();
          renderDrawer();
          return;
        }
      }

      const r = await fetch(`/projects/${encodeURIComponent(proj)}/agent/workspace-file?path=${encodeURIComponent(path)}&limit=24000`, {
        headers: getAuthHeaders()
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));

      CWS_STATE.previewFile.name = d.name || path.split('/').pop();
      CWS_STATE.previewFile.content = d.content || '';
      CWS_STATE.previewFile.editable = !!d.editable;
      CWS_STATE.previewFile.size = d.size || 0;
      CWS_STATE.previewFile.isNew = false;
      renderDrawer();
    } catch (e) {
      CWS_STATE.previewFile.content = 'Error loading file: ' + (e.message || e);
      renderDrawer();
    }
  };

  /* --------------------------------------------------------------------------
     QUICK PROMPT & STREAMING EXECUTION
     -------------------------------------------------------------------------- */
  window.cwsQuickPrompt = function (text) {
    const inp = document.getElementById('cwsInput');
    if (!inp) return;
    inp.value = text;
    updateSendBtnState();
    window.cwsSendMessage();
  };

  /* --------------------------------------------------------------------------
     SEND MESSAGE & STREAMING EXECUTION (Robust abort & error handling)
     -------------------------------------------------------------------------- */
  function getConversationAttachment(messages) {
    for (let i = messages.length - 1; i >= 0; i--) {
      const attachment = (messages[i].attachments || []).find(a => a.attachmentId);
      if (attachment) return attachment;
    }
    return null;
  }

  window.cwsSendMessage = async function () {
    if (CWS_STATE.streaming) return;
    const inp = document.getElementById('cwsInput');
    const q = (inp && inp.value || '').trim();
    const hasFiles = CWS_STATE.attachedFiles && CWS_STATE.attachedFiles.length > 0;
    if (!q && !hasFiles) return;

    if (hasFiles && CWS_STATE.attachedFiles.some(att => att.status !== 'ready')) {
      if (window.toast) window.toast('Wait for document processing to finish, or remove a failed attachment.');
      return;
    }

    if (hasFiles) {
      for (const att of CWS_STATE.attachedFiles) {
        if (att.uploadPromise && !att.attachmentId) {
          try { await att.uploadPromise; } catch (e) {}
        }
      }
    }

    const attachedSnapshot = (CWS_STATE.attachedFiles || []).slice();
    CWS_STATE.attachedFiles = [];
    renderComposerAttachments();

    inp.value = '';
    inp.style.height = 'auto';
    updateSendBtnState();

    const proj = getProj();
    const sess = getActiveSession();
    if (!sess.messages.length || sess.title === 'New chat') {
      const summaryTitle = q ? (q.slice(0, 36) + (q.length > 36 ? '…' : '')) : (attachedSnapshot[0] ? attachedSnapshot[0].name : 'Document Review');
      sess.title = summaryTitle;
    }
    sess.updatedAt = Date.now();
    sess.timeBadge = 'Just now';
    sess.messages.push({
      role: 'user',
      content: q,
      attachments: attachedSnapshot.map(a => ({
        name: a.name,
        size: a.size,
        ext: a.ext,
        badge: a.badge,
        attachmentId: a.attachmentId || null,
        status: a.status,
        previewUrl: a.previewUrl,
        serverPath: a.serverPath || a.name
      }))
    });

    const aiMsg = { role: 'assistant', content: '⏳ *Thinking…*', artifacts: [] };
    sess.messages.push(aiMsg);
    saveLocalData();
    renderAll();

    CWS_STATE.streaming = true;
    updateSendBtnState();

    cwsAbortController = new AbortController();

    const folderScope = CWS_STATE.activeFolder
      ? `[Active Cowork Folder: "${CWS_STATE.activeFolder}"] `
      : `[Active Cowork Workspace Root] `;
    const customInst = CWS_STATE.customInstructions[CWS_STATE.activeFolder || '__root__'] || '';
    const instPrefix = customInst ? `[Instructions: ${customInst}]\n` : '';
    const searchPrefix = ''; // No verified search tool is configured.
    const researchPrefix = ''; // No verified research workflow is configured.
    const attachedPrefix = attachedSnapshot.length
      ? `[Attached Document${attachedSnapshot.length > 1 ? 's' : ''}: ${attachedSnapshot.map(a => `"${a.serverPath || a.name}"`).join(', ')}]\n`
      : '';

    const effectiveQuery = (attachedPrefix + q).trim() || `Please review and inspect the attached document${attachedSnapshot.length > 1 ? 's' : ''}.`;

    const historyForApi = sess.messages.slice(0, -2).slice(-8).map(m => ({
      role: m.role,
      content: m.content
    }));

    let ans = '';
    const changedSet = new Set();

    const firstAtt = attachedSnapshot[0] || getConversationAttachment(sess.messages);
    try {
      const r = await fetch(`/ask_stream`, {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        signal: cwsAbortController.signal,
        body: JSON.stringify({
          project: proj,
          query: instPrefix + folderScope + searchPrefix + researchPrefix + effectiveQuery,
          messages: historyForApi,
          attachment_id: firstAtt ? (firstAtt.attachmentId || null) : null,
          focus_doc: (firstAtt && !firstAtt.attachmentId && firstAtt.isProjectDoc) ? (firstAtt.serverPath || firstAtt.name) : '',
          k: 8,
          model: CWS_STATE.selectedModel || 'qwen3.5:9b',
          mode: CWS_STATE.composerModeSeg || 'chat'
        })
      });

      if (!r.ok) {
        let errTxt = 'Error ' + r.status;
        try { const fd = await r.json(); if (fd && fd.detail) errTxt = fd.detail; } catch (e) {}
        aiMsg.content = `**Error:** ${errTxt}`;
        CWS_STATE.attachedFiles = attachedSnapshot;
        renderComposerAttachments();
        if (inp) inp.value = q;
        CWS_STATE.streaming = false;
        updateSendBtnState();
        renderStage();
        return;
      }

      const rd = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await rd.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i);
          buf = buf.slice(i + 2);
          const dl = line.split('\n').find(l => l.startsWith('data:'));
          if (!dl) continue;
          let d;
          try { d = JSON.parse(dl.slice(5).trim()); } catch (e) { continue; }
          if (d.type === 'token') {
            ans += d.text;
            aiMsg.content = ans;
            renderStage();
          } else if (d.type === 'error') {
            ans += '\n[Error] ' + d.message;
            aiMsg.content = ans;
            renderStage();
          } else if (d.type === 'cowork_workspace_updated') {
            (d.files || []).forEach(f => { if (f) changedSet.add(String(f)); });
            aiMsg.artifacts = Array.from(changedSet);
            refreshWorkspaceTree();
          }
        }
      }

      if (changedSet.size > 0) {
        aiMsg.artifacts = Array.from(changedSet);
        refreshWorkspaceTree();
      }
      aiMsg.content = ans || aiMsg.content || '*(Completed)*';
      saveLocalData();
    } catch (e) {
      if (e.name === 'AbortError') {
        aiMsg.content = (ans || '') + '\n\n*(Generation stopped by user)*';
      } else {
        aiMsg.content = `**Error:** ${e.message || e}`;
        if (inp) inp.value = q;
      }
    } finally {
      CWS_STATE.streaming = false;
      cwsAbortController = null;
      updateSendBtnState();
      saveLocalData();
      renderStage();
    }
  };

  window.cwsRefresh = refreshWorkspaceTree;
  window.cwsRenderAll = renderAll;
  window.cwsRenderStage = renderStage;
  window.cwsRenderComposerAttachments = renderComposerAttachments;
  window.cwsUpdateSendBtnState = updateSendBtnState;

  function renderAll() {
    if (!CWS_STATE.open) return;
    renderSidebar();
    renderHeader();
    renderStage();
    if (CWS_STATE.drawerOpen) renderDrawer();
  }

  // Auto-initialize on DOM ready
  function init() {
    injectStyles();
    buildOverlayDOM();
    injectLaunchButtons();
    loadLocalData();

    // Hook project selector changes
    const sel = document.getElementById('projSel');
    if (sel) {
      sel.addEventListener('change', () => {
        loadLocalData();
        refreshWorkspaceTree();
      });
    }

    // If projects are still loading asynchronously, poll briefly
    if (!getProj()) {
      let tries = 0;
      const t = setInterval(() => {
        tries++;
        if (getProj() || tries > 15) {
          clearInterval(t);
          loadLocalData();
          refreshWorkspaceTree();
        }
      }, 300);
    }

    const shouldOpen = localStorage.getItem('expo_cowork_open') !== 'false';
    if (shouldOpen) {
      openCoworkStudio();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  setTimeout(injectLaunchButtons, 600);
})();
