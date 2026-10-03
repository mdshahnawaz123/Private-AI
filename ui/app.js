/* ============================================================
   EXPO DESIGN AI — V2 Design Workspace (ui/app.js)
   One professional workspace. Navigation = destination,
   toolbar = actions, context panel = selection info,
   Copilot = intelligence, workspace = content.

   Protected wiring reused verbatim from the previous UI:
   - Authorization header injection, auth flow
   - SSE streaming client (stream) + source citation chips (renderEvidence)
   - 3D viewer iframe bridge (postMessage) + element properties
   All data comes from the real backend. No fake buttons: any action
   without a real endpoint is hidden (see UI_FLAGS).
   ============================================================ */

const API = window.location.origin;

/* ---- UI feature flags (mirror server config; conservative defaults) ---- */
const UI_FLAGS = {
  clashAction: false,   // matches config.enable_clash_action (no clash engine yet → hidden)
};

/* ---- state ---- */
let authToken=null, currentUser=null, currentProject=null, projectsData={};
let allDocs=[], lastSel=null, aiHist=[], lastSources=[], lastUsedSources=[];
let currentDest='design', currentRevision='';
let viewerLoaded=false, on3D=false;

try{ authToken=localStorage.getItem('expo_token')||null; }catch(e){}

/* ---- inject Authorization on same-origin fetches (verbatim behavior) ---- */
const _fetch=window.fetch.bind(window);
window.fetch=function(u,o){ o=o||{}; try{ const s=(typeof u==='string')?u:(u&&u.url)||'';
  if(authToken&&(s.indexOf(API)===0||s.charAt(0)==='/')){ const h=new Headers(o.headers||{}); if(!h.has('Authorization'))h.set('Authorization','Bearer '+authToken); o=Object.assign({},o,{headers:h}); } }catch(e){} return _fetch(u,o); };

/* ---- tiny helpers ---- */
const $=id=>document.getElementById(id);
const el=(t,c,h)=>{const d=document.createElement(t); if(c)d.className=c; if(h!=null)d.innerHTML=h; return d;};
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const svg=(p,w)=>`<svg class="ico" viewBox="0 0 24 24" ${w?`style="width:${w}px;height:${w}px"`:''}>${p}</svg>`;
function toast(t){ const e=$('toast'); e.textContent=t; e.classList.add('show'); clearTimeout(e._t); e._t=setTimeout(()=>e.classList.remove('show'),2200); }
function mdLite(s){ let h=esc(s); h=h.replace(/```([\s\S]*?)```/g,(m,c)=>'<pre>'+c+'</pre>');
  h=h.replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/^[-•]\s+(.*)$/gm,'• $1').replace(/\n/g,'<br>'); return h; }
function fmtBytes(n){ if(n==null)return ''; const u=['B','KB','MB','GB']; let i=0,v=n; while(v>=1024&&i<u.length-1){v/=1024;i++;} return v.toFixed(v<10&&i>0?1:0)+' '+u[i]; }
const rx={ ifc:/\.ifc$/i, dwg:/\.(pdf|dwg|dxf)$/i, doc:/\.(pdf|docx?|txt|rtf)$/i, spec:/spec|requirement|criteria|specification/i, sched:/\.(xlsx|xls|csv)$/i };
// Standard project folders (auto-created per project). When a document's
// real `folder` is one of these, that folder is authoritative for which
// workspace it belongs to; filename-extension matching is only a fallback
// for documents that predate folders or sit in an unrecognized folder, so
// nothing silently disappears. This fixes the same PDF showing up in both
// Drawings and Documents just because both regexes match ".pdf".
const STANDARD_FOLDERS=['models','drawings','documents','schedules','specifications','qa & issues','reports'];
function folderName(f){ return String((f&&f.folder)||'').trim().toLowerCase(); }
function hasKnownFolder(f){ return STANDARD_FOLDERS.includes(folderName(f)); }
function byDest(name, fallbackTest){ return f => hasKnownFolder(f) ? folderName(f)===name : fallbackTest(f); }
function fileExt(fn){ return (String(fn||'').split('.').pop()||'').toUpperCase(); }
function fileTypeIcon(ext){ const i={PDF:'📄',DOCX:'📝',DOC:'📝',XLSX:'📊',XLS:'📊',CSV:'📊',DWG:'📐',DXF:'📐',IFC:'🏗️',RVT:'🏗️',PNG:'🖼️',JPG:'🖼️',JPEG:'🖼️',TXT:'📃',RTF:'📃'}; return i[ext]||'📄'; }
function state(msg,kind){ return `<div class="state ${kind==='err'?'err':''}">${kind==='load'?'<div class="spinner"></div>':''}<div>${esc(msg)}</div></div>`; }

/* ---- revision parsing (best-effort, from filename) ---- */
function parseRev(fn){ const s=String(fn||'');
  let m=s.match(/\brev(?:ision)?[ ._-]*([A-Z0-9]{1,3})\b/i); if(m)return m[1].toUpperCase();
  m=s.match(/[-_]R([A-Z0-9]{1,2})[-_. ]/i); if(m)return m[1].toUpperCase();
  m=s.match(/\((\d{1,3})\)\.[a-z0-9]+$/i); if(m)return m[1];
  return ''; }

/* ============================================================
   AUTH
   ============================================================ */
async function boot(){
  buildNav(); wireTopbar(); wireCopilot(); buildDesignWorkspace();
  if(!authToken){ showLogin(); return; }
  try{ const r=await fetch(`${API}/auth/me`); if(!r.ok){ showLogin(); return; } const d=await r.json(); currentUser=(d&&d.user)?d.user:d; mustChangePw=!!(d&&d.must_change_password); onAuthed(); }
  catch(e){ showLogin(); }
}
function showLogin(){ $('login').classList.add('show'); $('luser').focus(); }
async function doLogin(){ $('lerr').textContent=''; const u=$('luser').value.trim(),p=$('lpass').value;
  if(!u||!p){$('lerr').textContent='Enter username and password.';return;}
  try{ const r=await _fetch(`${API}/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})}); const d=await r.json();
    if(!r.ok){$('lerr').textContent=d.detail||'Login failed.';return;}
    authToken=d.token; try{localStorage.setItem('expo_token',d.token);}catch(e){} currentUser=d.user; mustChangePw=!!d.must_change_password; $('login').classList.remove('show'); onAuthed();
  }catch(e){ $('lerr').textContent='Could not reach the server.'; } }

let mustChangePw=false;
async function doForcedPwChange(){
  const err=$('pwcErr'); err.textContent='';
  const oldPw=$('pwcOld').value, newPw=$('pwcNew').value, confirmPw=$('pwcConfirm').value;
  if(!oldPw||!newPw){ err.textContent='Enter your current and new password.'; return; }
  if(newPw.length<8){ err.textContent='New password must be at least 8 characters.'; return; }
  if(newPw!==confirmPw){ err.textContent='New passwords do not match.'; return; }
  if(newPw===oldPw){ err.textContent='New password must be different from the current one.'; return; }
  try{
    const r=await _fetch(`${API}/auth/change-password`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:oldPw,new_password:newPw})});
    const d=await r.json();
    if(!r.ok){ err.textContent=d.detail||'Password change failed.'; return; }
    mustChangePw=false; $('pwchange').classList.remove('show'); onAuthed();
  }catch(e){ err.textContent='Could not reach the server.'; }
}
function onAuthed(){
  if(mustChangePw){ $('pwchange').classList.add('show'); return; }
  const nm=(currentUser&&(currentUser.username||currentUser.full_name))||'user';
  $('uav').textContent=nm.slice(0,2).toUpperCase();
  $('uname').textContent=(currentUser.full_name||nm);
  $('urole').textContent=((currentUser.role||'user').replace(/^\w/,c=>c.toUpperCase()));
  const isAdmin=!!(currentUser&&currentUser.role==='admin');
  const navSettings=$('navSettingsLink'); if(navSettings) navSettings.style.display=isAdmin?'':'none';
  loadProjects(); aiGreeting();
}
function logout(){ try{localStorage.removeItem('expo_token');}catch(e){} location.reload(); }
// Matches the backend's /upload role check (admin + lead). Keep this in sync
// with classic.html's uploadBtn/docsUploadBtn gating and main.py's
// auth.require_roles(request, "admin", "lead") on /upload.
function canUpload(){ return !!(currentUser && (currentUser.role==='admin' || currentUser.role==='lead')); }

/* ============================================================
   TOP BAR
   ============================================================ */
function wireTopbar(){
  $('lbtn').onclick=doLogin;
  $('lpass').addEventListener('keydown',e=>{ if(e.key==='Enter')doLogin(); });
  $('pwcBtn').onclick=doForcedPwChange;
  $('pwcConfirm').addEventListener('keydown',e=>{ if(e.key==='Enter')doForcedPwChange(); });
  $('logoutBtn').onclick=logout;
  $('sbToggle').onclick=()=>{ document.body.classList.toggle('sb-collapsed'); document.body.classList.toggle('show-sb'); };
  $('sbCollapse').onclick=()=>document.body.classList.add('sb-collapsed');
  $('aiCollapse').onclick=()=>document.body.classList.toggle('ai-collapsed');
  initAppResizers();
  $('btnHelp').onclick=()=>toast('Expo Design AI — select a destination on the left, work in the center, ask the Copilot on the right.');
  $('btnSettings').onclick=()=>navigate('settings');
  $('btnNotif').onclick=()=>navigate('qa');
  $('projSel').onchange=()=>selectProject($('projSel').value);
  $('revSel').onchange=()=>{ currentRevision=$('revSel').value; if(currentDest!=='design') navigate(currentDest); updateAiCtx(); };
  const gs=$('globalSearch');
  gs.addEventListener('keydown',e=>{ if(e.key==='Enter'&&gs.value.trim()){ $('aiIn').value=gs.value.trim(); gs.value=''; setAiTab('chat'); sendAi(); } });
  document.addEventListener('keydown',e=>{ if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){ e.preventDefault(); gs.focus(); } });
}

/* ============================================================
   PROJECTS + DOCUMENTS
   ============================================================ */
async function loadProjects(){
  try{ const r=await fetch(`${API}/projects`); if(r.status===401){showLogin();return;} projectsData=await r.json()||{};
    const keys=Object.keys(projectsData);
    if(!currentProject||!projectsData[currentProject]) currentProject=keys[0]||null;
    $('projSel').innerHTML=keys.map(n=>`<option ${n===currentProject?'selected':''}>${esc(n)}</option>`).join('')||'<option>No projects</option>';
    if(currentProject) selectProject(currentProject); else { $('pcName').textContent='No projects'; navigate('design'); }
  }catch(e){ toast('Could not load projects'); }
}
function selectProject(p){ currentProject=p; currentRevision=''; viewerLoaded=false; lastSel=null; ctxDoc=null; $('ctxCard').hidden=true;
  currentAttachment=null; $('attachCard').hidden=true; $('attachMenu').hidden=true;
  $('pcName').textContent=p||'—';
  resetViewer();
  loadDocuments().then(()=>{ navigate(currentDest||'design'); });
}
function resetViewer(){ const fr=$('viewerFrame'); if(fr){ try{fr.src='about:blank';}catch(e){} fr.style.display='none'; } const ve=$('vpEmpty'); if(ve)ve.style.display='grid'; }
async function loadDocuments(){
  if(!currentProject){ allDocs=[]; return; }
  try{ const r=await fetch(`${API}/projects/${encodeURIComponent(currentProject)}/documents`); const d=await r.json(); allDocs=(d&&d.documents)||[]; }
  catch(e){ allDocs=[]; }
  // attach best-effort revision to each doc
  allDocs.forEach(f=>{ f._rev=parseRev(f.filename); });
  const c=counts();
  $('pcMeta').textContent=`${c.models} models · ${c.drawings} drawings · ${allDocs.length} files`;
  buildRevSelect();
  refreshBadges();
}
function counts(){ return {
  models:allDocs.filter(byDest('models', f=>rx.ifc.test(f.filename))).length,
  drawings:allDocs.filter(byDest('drawings', f=>rx.dwg.test(f.filename))).length,
  documents:allDocs.filter(byDest('documents', f=>rx.doc.test(f.filename)&&!rx.spec.test((f.folder||'')+' '+f.filename))).length,
  specs:allDocs.filter(byDest('specifications', f=>rx.spec.test((f.folder||'')+' '+f.filename))).length,
  schedules:allDocs.filter(byDest('schedules', f=>rx.sched.test(f.filename))).length,
}; }
function buildRevSelect(){
  const revs=[...new Set(allDocs.map(f=>f._rev).filter(Boolean))].sort();
  if(!revs.length){ $('revWrap').hidden=true; currentRevision=''; return; }
  $('revWrap').hidden=false;
  $('revSel').innerHTML=`<option value="">All revisions</option>`+revs.map(r=>`<option value="${esc(r)}">Rev ${esc(r)}</option>`).join('');
  $('revSel').value=currentRevision||'';
}
function fileURL(rel){ return `${API}/projects/${encodeURIComponent(currentProject)}/file?rel=${encodeURIComponent(rel)}&token=${encodeURIComponent(authToken||'')}`; }
function openFile(rel){ window.open(fileURL(rel),'_blank'); }
function docsBy(filter){ let list=allDocs.filter(filter); if(currentRevision) list=list.filter(f=>f._rev===currentRevision); return list; }

/* ============================================================
   SIDEBAR NAV (destinations)
   ============================================================ */
const DESTS=[
  ['overview','Overview','<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>'],
  ['design','Design Workspace','<path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M12 12l9-5M12 12v10M12 12L3 7"/>'],
  ['models','Models','<path d="M12 2l9 5v10l-9 5-9-5V7z"/>'],
  ['drawings','Drawings','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>'],
  ['documents','Documents','<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>'],
  ['schedules','Schedules','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 3v18"/>'],
  ['specifications','Specifications','<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/>'],
  ['codes','Codes & Standards','<path d="M12 20h9"/><path d="M3 6l9-3 9 3"/><path d="M4 10v8M20 10v8M9 21V10M15 21V10"/>'],
  ['qa','QA & Issues','<path d="M10.3 3.9l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'],
  ['reports','Reports','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17V9M12 17v-5M15 17v-3"/>'],
];
function buildNav(){
  $('navMain').innerHTML=DESTS.map(([k,l,p])=>`<a data-dest="${k}">${svg(p)}<span>${l}</span><span class="badge" data-badge="${k}" hidden></span></a>`).join('');
  document.querySelectorAll('#app .nav a[data-dest]').forEach(a=>a.onclick=()=>navigate(a.dataset.dest));
}
function refreshBadges(){
  // QA badge = open findings count (real)
  fetch(`${API}/api/v1/qa/stats?project=${encodeURIComponent(currentProject)}`).then(r=>r.ok?r.json():null).then(s=>{
    const open=s&&(s.open!=null?s.open:(s.total!=null&&s.resolved!=null?s.total-s.resolved:null));
    const b=document.querySelector('[data-badge="qa"]');
    if(b){ if(open){ b.textContent=open; b.hidden=false; $('notifDot').hidden=false; } else { b.hidden=true; } }
  }).catch(()=>{});
}
function setActiveNav(dest){ document.querySelectorAll('#app .nav a[data-dest]').forEach(a=>a.classList.toggle('on',a.dataset.dest===dest)); }

/* ============================================================
   WORKSPACE ROUTER
   ============================================================ */
function navigate(dest){
  if(dest==='settings' && !(currentUser&&currentUser.role==='admin')){ dest='overview'; }
  currentDest=dest; setActiveNav(dest);
  on3D=(dest==='design');
  const design=$('designWrap');
  if(dest==='design'){
    design.style.display='flex';
    $('genericWrap').style.display='none';
    $('wsTitle').innerHTML='Design Workspace';
    renderDesignTools(); refreshDesignEmpty();
  } else {
    design.style.display='none';
    $('genericWrap').style.display='block';
    const meta=DESTS.find(d=>d[0]===dest);
    $('wsTitle').innerHTML=`${meta?esc(meta[1]):esc(dest)} ${currentRevision?`<span class="sub">· Rev ${esc(currentRevision)}</span>`:''}`;
    $('wsTools').innerHTML='';
    renderGeneric(dest);
  }
  updateCtxActions(); updateAiCtx();
  if(document.body.clientWidth<=1200) document.body.classList.remove('show-sb');
}
function renderGeneric(dest){
  const b=$('genericWrap');
  const R={ overview:renderOverview, models:renderModels, drawings:renderDrawings,
    documents:renderDocuments, schedules:renderSchedules, specifications:renderSpecifications,
    codes:renderCodes, qa:renderQA, reports:renderReports, settings:renderSettings };
  (R[dest]||(()=>{ b.innerHTML=`<div class="ws-scroll">${state('Nothing here yet.')}</div>`; }))(b);
}

/* ---------- Design Workspace (persistent viewer) ---------- */
function buildDesignWorkspace(){
  const wrap=el('div','', `
    <div class="viewport" id="designWrap" style="display:flex">
      <div class="vp-body">
        <iframe id="viewerFrame" title="3D model viewer" src="about:blank"></iframe>
        <div class="vp-empty" id="vpEmpty">
          <div><svg class="ico" viewBox="0 0 24 24" style="width:44px;height:44px;color:var(--faint);stroke-width:1.2"><path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M12 12l9-5M12 12v10M12 12L3 7"/></svg>
          <div style="margin-top:12px" id="vpEmptyMsg">Select a project with an IFC model, then load the 3D engine.</div>
          <button class="primary" id="loadBtn" style="margin-top:14px">Load 3D model</button></div>
        </div>
      </div>
    </div>
    <div id="genericWrap" style="display:none"></div>`);
  $('wsBody').appendChild(wrap);
  $('loadBtn').onclick=loadModels;
}
function renderDesignTools(){
  // The 3D viewer (ui/viewer.js) now ships its own complete toolbar
  // (Fit/Reset/Orbit/Pan/Zoom/Section/Hide/Isolate/Show all/Measure/
  // Display modes/Camera/etc.), so this outer duplicate bar -- which
  // only ever forwarded postMessage commands into the iframe via
  // vcmd() -- has been removed to avoid showing the same controls
  // twice. vcmd() is kept (harmless, unused) in case something else
  // starts forwarding viewer commands from outside the iframe later.
  $('wsTools').innerHTML='';
}
function refreshDesignEmpty(){
  const models=allDocs.filter(f=>rx.ifc.test(f.filename));
  const msg=$('vpEmptyMsg'), lb=$('loadBtn');
  if(!msg)return;
  if(!models.length){ msg.textContent='No IFC models in this project. Upload one in Models / Documents.'; if(lb)lb.style.display='none'; }
  else { msg.textContent=`${models.length} IFC model(s) available. Load the 3D engine.`; if(lb)lb.style.display=''; }
}
// Rels currently loaded in the viewer iframe, kept in sync via the viewer's
// "loaded" postMessage so the "+ Link" action knows what is already in view.
let loadedRels = new Set();
// Load a set of models into the viewer. relList (optional): the exact models to
// open; when omitted/empty, every IFC in the project is loaded. The old 4-model
// cap is gone -- the floating-origin federation keeps a shared-coordinate set
// aligned and precise regardless of count. A soft confirm guards very heavy sets.
function loadModels(relList){
  const ifc=allDocs.filter(f=>rx.ifc.test(f.filename));
  if(!ifc.length){ toast('No IFC models in this project'); return; }
  let chosen = (relList && relList.length) ? relList.slice() : ifc.map(f=>f.rel);
  if(chosen.length>8 && !confirm(`Open ${chosen.length} models together? Large federated sets can be slow to parse and memory-heavy. Continue?`)) return;
  loadedRels = new Set(chosen);
  const rels=chosen.map(r=>'rel='+encodeURIComponent(r)).join('&');
  const url=`/ui/viewer.html?embed=1&project=${encodeURIComponent(currentProject)}&token=${encodeURIComponent(authToken||'')}&${rels}`;
  $('vpEmpty').style.display='none'; $('viewerFrame').style.display='block'; $('viewerFrame').src=url; viewerLoaded=true;
}
// Open exactly the models ticked in the Models table.
function openSelectedModels(){
  const checked=[...document.querySelectorAll('.mdlChk:checked')].map(c=>c.value);
  if(!checked.length){ toast('Tick one or more models first'); return; }
  navigate('design'); loadModels(checked);
}
// Open just one model (per-row "Open").
function openOneModel(btn){ navigate('design'); loadModels([btn.dataset.rel]); }
// Open the Fragments (beta) viewer -- lightweight .frag loading. Phase 2a:
// single model (uses the first ticked model, else the first IFC in the project).
function openFragmentsBeta(){
  const checked=[...document.querySelectorAll('.mdlChk:checked')].map(c=>c.value);
  const ifc=allDocs.filter(f=>rx.ifc.test(f.filename));
  const chosen = checked.length ? checked : (ifc[0] ? [ifc[0].rel] : []);
  if(!chosen.length){ toast('No IFC models in this project'); return; }
  navigate('design');
  const rels=chosen.map(r=>'rel='+encodeURIComponent(r)).join('&');
  const url=`/ui/viewer_frag.html?v=9&embed=1&project=${encodeURIComponent(currentProject)}&token=${encodeURIComponent(authToken||'')}&${rels}`;
  $('vpEmpty').style.display='none'; $('viewerFrame').style.display='block'; $('viewerFrame').src=url; viewerLoaded=true;
}
// Link another model INTO the already-open scene without reloading. Falls back
// to a fresh load when the viewer is not running yet.
function addModelToView(rel){
  if(!viewerLoaded){ navigate('design'); loadModels([rel]); return; }
  if(loadedRels.has(rel)){ toast('That model is already in the view'); return; }
  loadedRels.add(rel);
  navigate('design');
  try{ $('viewerFrame').contentWindow.postMessage({type:'expo:addModel', rel}, '*'); toast('Linking model…'); }
  catch(e){ loadedRels.delete(rel); toast('Could not link model'); }
}

/* ---------- Overview ---------- */
async function renderOverview(b){
  b.innerHTML=`<div class="ws-scroll" id="ovBody">${state('Loading dashboard…','load')}</div>`;
  try{
    const r=await fetch(`${API}/api/v1/dashboard/stats?project=${encodeURIComponent(currentProject)}`);
    const s=await r.json(); const c=counts();
    const dd=s.documents||{}, fnd=s.findings||{}, bim=s.bim||{};
    const tile=(h,big,p)=>`<div class="tile"><h4>${esc(h)}</h4><div class="big">${esc(big)}</div><p>${esc(p||'')}</p></div>`;
    $('ovBody').innerHTML=`<div class="tiles">
      ${tile('Documents', dd.total!=null?dd.total:allDocs.length, `${dd.processed!=null?dd.processed:'—'} processed`)}
      ${tile('3D Models', c.models, 'IFC / BIM')}
      ${tile('Drawings', c.drawings, 'PDF / DWG / DXF')}
      ${tile('BIM Elements', (bim.total_elements!=null?bim.total_elements:(bim.elements!=null?bim.elements:'—')), 'in model store')}
      ${tile('Open Issues', (fnd.open!=null?fnd.open:(fnd.total!=null?fnd.total:'—')), 'QA & compliance')}
      ${tile('Schedules', c.schedules, 'structured data')}
    </div>
    <div style="margin-top:22px" class="tiles">
      ${['design','drawings','documents','schedules','codes','qa','reports'].map(k=>{ const m=DESTS.find(d=>d[0]===k); return `<div class="tile" style="cursor:pointer" onclick="navigate('${k}')"><h4>${svg(m[2])} ${esc(m[1])}</h4><p>Open workspace →</p></div>`; }).join('')}
    </div>`;
  }catch(e){ $('ovBody').innerHTML=state('Dashboard stats unavailable.','err'); }
}

/* ---------- Models ---------- */
async function renderModels(b){
  const ifc=allDocs.filter(f=>rx.ifc.test(f.filename));
  let bimModels=[];
  try{ const r=await fetch(`${API}/api/v1/bim/models?project=${encodeURIComponent(currentProject)}`); const d=await r.json(); bimModels=(d&&d.models)||[]; }catch(e){}
  b.innerHTML=`<div class="ws-scroll">
    <div class="dt-toolbar"><b>IFC / 3D models in project</b>
      <button class="primary" style="margin-left:auto" onclick="openSelectedModels()">Open selected in 3D</button>
      <button class="tb" style="margin-left:8px" onclick="navigate('design');loadModels()">Open all</button>
      <button class="tb" style="margin-left:8px" title="Lightweight Fragments engine (experimental)" onclick="openFragmentsBeta()">⚡ Fragments (beta)</button></div>
    ${ifc.length?`<table class="dt"><thead><tr><th style="width:34px"><input type="checkbox" onclick="document.querySelectorAll('.mdlChk').forEach(c=>c.checked=this.checked)" title="Select all"></th><th>Model</th><th>Revision</th><th>Status</th><th>Size</th><th></th></tr></thead><tbody>
      ${ifc.map(f=>`<tr><td><input type="checkbox" class="mdlChk" value="${esc(f.rel)}"></td><td>🏗️ ${esc(f.filename)}</td><td>${esc(f._rev||'—')}</td><td>${esc(f.status||'ready')}</td><td>${fmtBytes(f.size)}</td>
        <td><button class="tb" data-rel="${esc(f.rel)}" onclick="openOneModel(this)">Open</button><button class="tb" style="margin-left:6px" data-rel="${esc(f.rel)}" onclick="addModelToView(this.dataset.rel)">＋ Link</button></td></tr>`).join('')}
    </tbody></table>`:state('No IFC models uploaded to this project.')}
    ${bimModels.length?`<div class="dt-toolbar" style="margin-top:22px"><b>Registered BIM element models</b></div>
      <table class="dt"><thead><tr><th>Model</th><th>Elements</th></tr></thead><tbody>
      ${bimModels.map(m=>`<tr><td>${esc(m.name||m.model_id||m.filename||'model')}</td><td>${esc(m.element_count!=null?m.element_count:(m.elements!=null?m.elements:'—'))}</td></tr>`).join('')}</tbody></table>`:''}
  </div>`;
}

/* ---------- Drawings ---------- */
function renderDrawings(b){ renderSplitDocs(b, docsBy(byDest('drawings', f=>rx.dwg.test(f.filename))), 'drawing', 'No drawings (PDF/DWG/DXF) in this project.'); }
/* ---------- Documents ---------- */
function renderDocuments(b){ renderSplitDocs(b, docsBy(byDest('documents', f=>rx.doc.test(f.filename)&&!rx.spec.test((f.folder||'')+' '+f.filename))), 'document', 'No documents in this project.'); }
/* ---------- Specifications ---------- */
function renderSpecifications(b){ renderSplitDocs(b, docsBy(byDest('specifications', f=>rx.spec.test((f.folder||'')+' '+f.filename))), 'specification', 'No specification documents detected. Specs are documents whose name/folder mentions spec / requirement / criteria.'); }

function renderSplitDocs(b, list, kind, emptyMsg){
  if(!list.length){ b.innerHTML=`<div class="ws-scroll">${state(emptyMsg)}</div>`; return; }
  b.innerHTML=`<div class="split">
    <div class="list-col" id="docList"></div>
    <div class="gutter" title="Drag to resize"></div>
    <div class="view-col" id="docView">${state('Select a '+kind+' to preview.')}</div>
  </div>`;
  initSplitter(b.querySelector('.split'));
  const lc=$('docList');
  lc.innerHTML=list.map((f,i)=>`<div class="li" data-i="${i}"><div class="fi">${fileTypeIcon(fileExt(f.filename))}</div>
    <div class="fn"><b>${esc(f.filename)}</b><span>${esc(f.category||'')}${f._rev?` · Rev ${esc(f._rev)}`:''}${f.chunks?` · ${f.chunks} chunks`:''}</span></div></div>`).join('');
  lc.querySelectorAll('.li').forEach(li=>li.onclick=()=>{
    lc.querySelectorAll('.li').forEach(x=>x.classList.remove('on')); li.classList.add('on');
    const f=list[+li.dataset.i]; openInViewer(f);
  });
  // auto-open first
  lc.querySelector('.li').click();
}
function openInViewer(f){
  const isPdf=/\.pdf$/i.test(f.filename);
  const v=$('docView');
  if(isPdf){ v.innerHTML=`<div class="docframe-wrap"><iframe class="docframe" src="${fileURL(f.rel)}#toolbar=1"></iframe></div>`; }
  else { v.innerHTML=`<div class="ws-scroll">${state('Preview not available for .'+fileExt(f.filename).toLowerCase()+' — open in a new tab.')}<div style="text-align:center"><button class="primary" onclick="openFile('${esc(f.rel)}')">Open file</button></div></div>`; }
  // set copilot context to this document
  setDocContext(f);
}

/* ---------- Schedules (new endpoint) ---------- */
/* Heuristic: does a row's values look like column headers (short, mostly
   non-numeric labels like "NO.", "%", "INCL. BALCONY") rather than data? */
function _looksLikeHeaderRow(vals){
  const vs=Object.values(vals||{}).map(v=>String(v==null?'':v).trim()).filter(Boolean);
  if(vs.length<2) return false;
  const headerish=vs.filter(v=>v.length<=24 && !/^-?[\d.,]+%?$/.test(v)).length;
  return headerish/vs.length >= 0.7;
}
function _colKeys(group){
  const keys=new Set();
  group.forEach(r=>Object.keys(r.row_values||{}).forEach(k=>keys.add(k)));
  return [...keys].sort((a,b)=>{ const na=parseInt((a.match(/\d+/)||[0])[0],10), nb=parseInt((b.match(/\d+/)||[0])[0],10); return na-nb; });
}

/* ---------- Schedules: upload-your-own-data-file ---------- */
async function _schedulesFolderId(){
  // Reuse (or create) a single "Schedules" folder so uploaded data files land
  // somewhere predictable and permission-scoped, same mechanism classic.html uses.
  try{
    const r=await fetch(`${API}/projects/${encodeURIComponent(currentProject)}/folders`);
    const d=await r.json(); const folders=(d&&d.folders)||d||[];
    const hit=(Array.isArray(folders)?folders:[]).find(f=>String(f.name||'').toLowerCase()==='schedules');
    if(hit) return hit.id;
    const cr=await fetch(`${API}/projects/${encodeURIComponent(currentProject)}/folders`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Schedules'})});
    const cd=await cr.json();
    if(!cr.ok) throw new Error((cd&&cd.detail)||'Could not create a Schedules folder');
    return cd.folder&&cd.folder.id;
  }catch(e){ toast('Could not prepare the Schedules folder: '+(e.message||e)); return null; }
}
/* Same upload mechanics as the Drawings / management screen (classic.html
   uploadDirect): multi-file picker, same accepted types, one folder-scoped
   POST to /upload per file, uploaded one after another. */
function pickScheduleUpload(){
  if(!currentProject){ toast('Select a project first'); return; }
  let inp=$('schUploadInput');
  if(!inp){
    inp=document.createElement('input'); inp.type='file'; inp.id='schUploadInput'; inp.multiple=true;
    inp.accept='.pdf,.docx,.xlsx,.xls,.csv,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.dwg,.dxf';
    inp.style.display='none'; document.body.appendChild(inp);
  }
  inp.value='';
  inp.onchange=async()=>{
    const files=[...inp.files]; inp.value='';
    if(!files.length) return;
    const folderId=await _schedulesFolderId(); if(!folderId) return;
    let anyProcessing=false;
    for(const f of files){
      toast('Uploading '+f.name+' …', true);
      const fd=new FormData(); fd.append('file',f); fd.append('project',currentProject); fd.append('folder_id',folderId);
      try{
        const r=await fetch(`${API}/upload`,{method:'POST',body:fd});
        const j=await r.json().catch(()=>({}));
        if(!r.ok) throw new Error(j.detail||('HTTP '+r.status));
        toast(f.name+' — '+(j.status==='processing'?'processing in background':(j.message||'stored')));
        if(j.status==='processing') anyProcessing=true;
      }catch(err){ toast('Upload failed: '+f.name+' — '+(err.message||err)); }
    }
    await loadDocuments(); // refresh allDocs so the new file's folder is known to the Schedules filter
    if(anyProcessing){ toast('Processing uploaded file(s) in background — this page will refresh automatically.'); _pollSchedulesAfterUpload(); }
    else if($('genericWrap')) renderSchedules($('genericWrap'));
  };
  inp.click();
}
let _schPollTimer=null;
function _pollSchedulesAfterUpload(){
  if(_schPollTimer) clearInterval(_schPollTimer);
  let tries=0, lastCount=-1;
  _schPollTimer=setInterval(async()=>{
    tries++;
    try{
      const r=await fetch(`${API}/api/v1/projects/${encodeURIComponent(currentProject)}/schedules`);
      const d=await r.json(); const n=(d.rows||[]).length+(d.quantities||[]).length;
      if(n!==lastCount){ lastCount=n; await loadDocuments(); if(currentDest==='schedules'&&$('genericWrap')) renderSchedules($('genericWrap')); }
    }catch(e){}
    if(tries>=20){ clearInterval(_schPollTimer); _schPollTimer=null; toast('Still processing — reopen Schedules in a moment if your data isn’t showing yet.'); }
  }, 3000);
}

function _schedTableHTML(tname, group){
  let headerRow=null, dataRows=group;
  const cand=group.find(g=>_looksLikeHeaderRow(g.row_values));
  if(cand){ headerRow=cand.row_values; dataRows=group.filter(g=>g!==cand); }
  const cols=_colKeys(group);
  const colLabel=(k,i)=> headerRow && headerRow[k] ? headerRow[k] : (k.replace(/^col/,'Col ')||('Col '+(i+1)));
  return `<div class="dt-toolbar"><b>${esc(tname)}</b><span class="rr-sched-count" style="margin-left:4px">${dataRows.length} row${dataRows.length===1?'':'s'}</span>
      <div class="dt-search" style="margin-left:auto"><svg class="ico" viewBox="0 0 24 24" style="width:14px;height:14px"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg><input id="schTableFilter" placeholder="Filter this table…"></div></div>
    <div class="rr-table-wrap">
      <div class="rr-table-scroll"><table class="rr-table" id="schDetailTable">
        <thead><tr><th>Key</th>${cols.map((c,i)=>`<th>${esc(colLabel(c,i))}</th>`).join('')}<th>Source</th><th>Page</th><th>Rev</th></tr></thead>
        <tbody>${dataRows.map(row=>{
          const rv=row.row_values||{};
          return `<tr>
            <td><b>${esc(row.row_key)}</b></td>
            ${cols.map(c=>`<td>${esc(rv[c]!=null?rv[c]:'')}</td>`).join('')}
            <td class="src" data-doc="${esc(row.doc)}" style="cursor:pointer;color:var(--accent2)">${esc(row.doc||'')}</td>
            <td>${esc(row.page!=null?row.page:'')}</td><td>${esc(row.revision||'')}</td>
          </tr>`;
        }).join('')}</tbody>
      </table></div>
    </div>`;
}
function _schedQtyHTML(qty){
  return `<div class="dt-toolbar"><b>Quantities</b><span class="rr-sched-count" style="margin-left:4px">${qty.length} rows</span>
      <div class="dt-search" style="margin-left:auto"><svg class="ico" viewBox="0 0 24 24" style="width:14px;height:14px"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg><input id="schTableFilter" placeholder="Filter this table…"></div></div>
    <div class="rr-table-wrap"><div class="rr-table-scroll"><table class="rr-table" id="schDetailTable"><thead><tr><th>Building</th><th>Metric</th><th>Value</th><th>Unit</th><th>Source</th><th>Page</th><th>Rev</th></tr></thead><tbody>
    ${qty.map(q=>`<tr><td>${esc(q.building)}</td><td><b>${esc(q.metric)}</b></td><td>${esc(q.value)}</td><td>${esc(q.unit)}</td>
      <td class="src" data-doc="${esc(q.source_doc)}" style="cursor:pointer;color:var(--accent2)">${esc(q.source_doc)}</td><td>${esc(q.source_page!=null?q.source_page:'')}</td><td>${esc(q.revision||'')}</td></tr>`).join('')}</tbody></table></div></div>`;
}

async function renderSchedules(b){
  b.innerHTML=`<div class="ws-scroll" id="schBody">${state('Loading schedules…','load')}</div>`;
  const canUp=canUpload();
  const uploadBtn=canUp ? `<button class="primary" id="schUploadBtn">${svg('<path d="M12 3v12m0-12 5 5m-5-5-5 5M5 21h14"/>')} Upload data file</button>` : '';
  try{
    const r=await fetch(`${API}/api/v1/projects/${encodeURIComponent(currentProject)}/schedules`);
    const d=await r.json();
    // Scope Schedules to documents actually uploaded INTO the Schedules folder
    // (via the Upload button here) — not every structured table extracted from
    // any document anywhere in the project (that's what made unrelated rows,
    // like ones pulled from a Documents-workspace upload, show up here).
    const schedFiles=new Set(allDocs.filter(f=>String(f.folder||'').toLowerCase()==='schedules').map(f=>f.filename));
    const rows=(d.rows||[]).filter(row=>schedFiles.has(row.doc));
    const qty=(d.quantities||[]).filter(q=>schedFiles.has(q.source_doc));
    if(!rows.length && !qty.length){
      const emptyMsg=canUp
        ? 'Nothing uploaded into Schedules yet. Click "Upload data file" above (Excel, CSV, PDF or Word) and it will be parsed into clean tables here automatically — pick a table from the list and view its data in detail. This view only shows files uploaded here, not every document in the project.'
        : 'Nothing uploaded into Schedules yet. Ask an admin or project lead to upload a schedule file (Excel, CSV, PDF or Word) and it will appear here automatically.';
      b.innerHTML=(canUp?`<div class="ws-scroll"><div class="dt-toolbar">${uploadBtn}</div>`:'<div class="ws-scroll">')+state(emptyMsg)+`</div>`;
      const ub=$('schUploadBtn'); if(ub) ub.onclick=pickScheduleUpload;
      return;
    }

    // group rows by their source table, preserving first-seen order
    const order=[], groups={};
    rows.forEach(r=>{ const k=r.table_name||'(Table)'; if(!groups[k]){ groups[k]=[]; order.push(k); } groups[k].push(r); });

    // List-then-detail split (same pattern as Documents / Drawings / QA): pick a
    // schedule from the list on the left, see its full table on the right.
    b.innerHTML=`<div class="split">
      <div class="list-col" id="schList"></div>
      <div class="gutter" title="Drag to resize"></div>
      <div class="view-col" id="schView">${state('Select a schedule to view its data.')}</div>
    </div>`;
    initSplitter(b.querySelector('.split'));

    const lc=$('schList');
    lc.innerHTML=(uploadBtn?`<div style="padding:10px 10px 6px">${uploadBtn}</div>`:'')
      + `<div class="dt-search" style="margin:0 10px 10px"><svg class="ico" viewBox="0 0 24 24" style="width:14px;height:14px"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg><input id="schListFilter" placeholder="Filter schedules…"></div>`
      + order.map((tname,i)=>`<div class="li" data-i="${i}"><div class="fn"><b>${esc(tname)}</b><span>${groups[tname].length} row${groups[tname].length===1?'':'s'}</span></div></div>`).join('')
      + (qty.length?`<div class="li" data-qty="1"><div class="fn"><b>Quantities</b><span>${qty.length} row${qty.length===1?'':'s'}</span></div></div>`:'');

    function wireDetail(){
      const tf=$('schTableFilter');
      if(tf) tf.oninput=()=>{
        const q=tf.value.toLowerCase();
        $('schDetailTable').querySelectorAll('tbody tr').forEach(tr=>{ tr.style.display=tr.textContent.toLowerCase().includes(q)?'':'none'; });
      };
      if($('schDetailTable')) enableSort($('schDetailTable'));
      $('schView').querySelectorAll('td.src').forEach(td=>{ const doc=td.dataset.doc; const f=allDocs.find(x=>x.filename===doc); if(f){ td.onclick=()=>openFile(f.rel); } });
    }
    function showTable(i){ $('schView').innerHTML=_schedTableHTML(order[i], groups[order[i]]); wireDetail(); }
    function showQty(){ $('schView').innerHTML=_schedQtyHTML(qty); wireDetail(); }

    lc.querySelectorAll('.li').forEach(li=>li.onclick=()=>{
      lc.querySelectorAll('.li').forEach(x=>x.classList.remove('on')); li.classList.add('on');
      if(li.dataset.qty) showQty(); else showTable(+li.dataset.i);
    });
    const firstLi=lc.querySelector('.li'); if(firstLi) firstLi.click();

    const ub2=$('schUploadBtn'); if(ub2) ub2.onclick=pickScheduleUpload;
    const lf=$('schListFilter');
    if(lf) lf.oninput=()=>{
      const q=lf.value.toLowerCase();
      lc.querySelectorAll('.li').forEach(li=>{ li.style.display=li.textContent.toLowerCase().includes(q)?'':'none'; });
    };
  }catch(e){ b.innerHTML=state('Schedules endpoint unavailable.','err'); }
}
function enableSort(table){
  table.querySelectorAll('th').forEach((th,idx)=>{ th.onclick=()=>{
    const tb=table.querySelector('tbody'); const rows=[...tb.querySelectorAll('tr')];
    const asc=!(th._asc); th._asc=asc;
    rows.sort((a,b)=>{ const x=a.children[idx].textContent.trim(), y=b.children[idx].textContent.trim();
      const nx=parseFloat(x), ny=parseFloat(y); if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;
      return asc?x.localeCompare(y):y.localeCompare(x); });
    rows.forEach(r=>tb.appendChild(r)); }; });
}

/* ---------- Codes & Standards ---------- */
async function renderCodes(b){
  b.innerHTML=`<div class="ws-scroll" id="codesBody">${state('Loading codes & standards…','load')}</div>`;
  let kb=[], rules=[];
  try{ const r=await fetch(`${API}/kb`); const d=await r.json(); kb=(d&&d.documents)||[]; }catch(e){}
  try{ const r=await fetch(`${API}/api/v1/compliance/rules`); const d=await r.json(); rules=(d&&d.rules)||[]; }catch(e){}
  $('codesBody').innerHTML=`
    <div class="dt-toolbar"><b>Standards knowledge base (${kb.length})</b>
      <button class="primary" style="margin-left:auto" onclick="setAiTab('chat');$('aiIn').value='Search the codes and standards: ';$('aiIn').focus()">Search codes with AI</button></div>
    ${kb.length?`<div class="tiles">${kb.map(k=>`<div class="tile"><h4>${svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/>')} ${esc(k.filename||k.name||'standard')}</h4><p>${esc((k.chunks!=null?k.chunks+' chunks':'')||'')}</p></div>`).join('')}</div>`:state('No code/standard documents in the knowledge base yet.')}
    <div class="dt-toolbar" style="margin-top:24px"><b>Deterministic compliance rules (${rules.length})</b></div>
    ${rules.length?`<table class="dt"><thead><tr><th>Rule</th><th>Requirement</th><th>Operator</th><th>Value</th><th>Code ref</th></tr></thead><tbody>
      ${rules.map(rl=>`<tr><td><b>${esc(rl.rule_id||rl.id||'')}</b></td><td>${esc(rl.title||rl.description||rl.name||'')}</td>
        <td>${esc(rl.operator||'')}</td><td>${esc((rl.value!=null?rl.value:'')+' '+(rl.unit||''))}</td><td>${esc(rl.code_reference||rl.reference||'')}</td></tr>`).join('')}</tbody></table>
      <p class="muted" style="margin-top:10px">Compliance verdicts (PASS / FAIL / REVIEW) are produced by the deterministic engine — code requirement + project evidence + rule — not by the language model. Run checks from the Copilot's Compliance tab.</p>`:state('No deterministic rules configured.')}`;
}

/* ---------- QA & Issues ---------- */
async function renderQA(b){
  b.innerHTML=`<div class="split"><div class="list-col" id="qaList">${state('Loading findings…','load')}</div><div class="gutter" title="Drag to resize"></div><div class="view-col" id="qaView">${state('Select an issue.')}</div></div>`;
  initSplitter(b.querySelector('.split'));
  try{
    const r=await fetch(`${API}/api/v1/qa/findings?project=${encodeURIComponent(currentProject)}`);
    const d=await r.json(); const list=(d&&d.findings)||[];
    if(!list.length){ $('qaList').innerHTML=state('No QA / compliance findings for this project.'); return; }
    $('qaList').innerHTML=list.map((f,i)=>`<div class="li" data-i="${i}"><div class="fn">
      <b>${esc(f.title||f.finding_id)}</b>
      <span>${statusBadge(f.status)} <span class="sev ${esc((f.severity||'').toLowerCase())}"><span class="d"></span>${esc(f.severity||'')}</span> ${f.discipline?'· '+esc(f.discipline):''}</span></div></div>`).join('');
    $('qaList').querySelectorAll('.li').forEach(li=>li.onclick=()=>{ $('qaList').querySelectorAll('.li').forEach(x=>x.classList.remove('on')); li.classList.add('on'); showFinding(list[+li.dataset.i]); });
    $('qaList').querySelector('.li').click();
  }catch(e){ $('qaList').innerHTML=state('QA findings unavailable.','err'); }
}
function statusBadge(s){ const v=String(s||'').toUpperCase(); const cls=v==='PASS'?'b-pass':v==='FAIL'?'b-fail':v==='REVIEW'?'b-review':'b-neutral'; return `<span class="badge-s ${cls}">${esc(v||'—')}</span>`; }
async function showFinding(f){
  const v=$('qaView');
  v.innerHTML=`<div class="ws-scroll" id="findBody">${state('Loading…','load')}</div>`;
  let full=f;
  try{ const r=await fetch(`${API}/api/v1/qa/findings/${encodeURIComponent(f.finding_id)}`); if(r.ok) full=await r.json(); }catch(e){}
  const row=(k,val)=>val?`<div style="display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #16223a"><span class="muted">${esc(k)}</span><span style="text-align:right">${val}</span></div>`:'';
  $('findBody').innerHTML=`<h3 style="margin:0 0 4px">${esc(full.title||full.finding_id)}</h3>
    <div style="margin:6px 0 14px">${statusBadge(full.status)} <span class="sev ${esc((full.severity||'').toLowerCase())}"><span class="d"></span>${esc(full.severity||'')}</span></div>
    ${row('Finding ID', esc(full.finding_id))}
    ${row('Discipline', esc(full.discipline))}
    ${row('Calculation', esc(full.calculation))}
    ${row('Actual value', esc(full.actual_value))}
    ${row('Expected value', esc(full.expected_value))}
    ${row('Recommendation', esc(full.recommendation))}
    ${row('Source', full.source_doc?`<span class="srclink" data-doc="${esc(full.source_doc)}" style="color:var(--accent2);cursor:pointer">${esc(full.source_doc)}${full.source_page!=null?' · p.'+esc(full.source_page):''}</span>`:'')}
    ${row('Lifecycle', esc(full.lifecycle_state))}
    <div style="margin-top:16px"><button class="ghost" id="findAsk">Ask Design AI to explain</button></div>`;
  const sl=$('findBody').querySelector('.srclink'); if(sl){ sl.onclick=()=>{ const f=allDocs.find(x=>x.filename===full.source_doc); if(f)openFile(f.rel); }; }
  const fa=$('findBody').querySelector('#findAsk'); if(fa){ fa.onclick=()=>askAbout(`Explain this QA finding: ${(full.title||full.finding_id)}. What does it mean and how should it be resolved?`); }
}

/* ---------- Reports ---------- */
async function renderReports(b){
  b.innerHTML=`<div class="ws-scroll" id="repBody">${state('Loading reports…','load')}</div>`;
  await loadReportsList();
  wireReportGen();
}
async function loadReportsList(){
  let reports=[];
  try{ const r=await fetch(`${API}/api/v1/reports/list?project=${encodeURIComponent(currentProject)}`); const d=await r.json(); reports=(d&&d.reports)||[]; }catch(e){}
  $('repBody').innerHTML=`<div class="dt-toolbar"><b>Generated reports (${reports.length})</b>
    <select class="tb" id="repType"><option value="compliance">Compliance report</option><option value="bim_qa">BIM QA report</option><option value="issue_register">Issue register</option></select>
    <select class="tb" id="repFmt"><option value="pdf">PDF</option><option value="xlsx">Excel</option><option value="docx">Word</option></select>
    <button class="primary" id="repGen">Generate</button></div>
    ${reports.length?`<table class="dt"><thead><tr><th>Report</th><th>Size</th><th>Created</th><th></th></tr></thead><tbody>
      ${reports.map(r=>`<tr><td>📄 ${esc(r.filename)}</td><td>${fmtBytes(r.size)}</td><td>${esc((r.created||'').replace('T',' ').slice(0,16))}</td>
        <td><a class="tb" href="${API}/api/v1/reports/${encodeURIComponent(r.filename.replace(/\.[^.]+$/,''))}/download" target="_blank">Download</a></td></tr>`).join('')}</tbody></table>`
      :state('No reports generated yet. Choose a type and click Generate.')}`;
}
function wireReportGen(){ const btn=$('repGen'); if(!btn)return;
  btn.onclick=async()=>{ btn.disabled=true; btn.textContent='Generating…';
    try{
      const r=await fetch(`${API}/api/v1/reports/generate?project=${encodeURIComponent(currentProject)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({report_type:$('repType').value,format:$('repFmt').value})});
      const d=await r.json();
      if(!r.ok){ toast(d.detail||'Report generation failed'); }
      else { toast('Report generated'); await loadReportsList(); wireReportGen(); }
    }catch(e){ toast('Report generation failed'); }
    finally{ if($('repGen')){ $('repGen').disabled=false; $('repGen').textContent='Generate'; } }
  };
}

/* ---------- Settings ---------- */
function renderSettings(b){
  const role=(currentUser&&currentUser.role)||'user';
  const isAdmin=role==='admin';
  const canUp=canUpload();
  const mgmtNote=isAdmin
    ? 'Upload, folders, user accounts and admin tools remain in the existing management screen.'
    : (canUp
        ? 'Upload and folder access for your projects remain in the existing management screen.'
        : 'You have query-only access. Folder access and uploads are managed by an admin or project lead — open the management screen below to view the documents you have access to.');
  const mgmtBtnLabel=canUp ? 'Open management / upload screen' : 'Open documents screen';
  b.innerHTML=`<div class="ws-scroll">
    <h3 style="margin-top:0">Project Settings</h3>
    <div class="tiles">
      <div class="tile"><h4>Project</h4><div class="big" style="font-size:18px">${esc(currentProject||'—')}</div><p>${esc(counts().models)} models · ${esc(allDocs.length)} files</p></div>
      <div class="tile"><h4>Signed in as</h4><div class="big" style="font-size:18px">${esc((currentUser&&(currentUser.full_name||currentUser.username))||'—')}</div><p>Role: ${esc(role)}</p></div>
    </div>
    <p class="muted" style="margin-top:18px">${esc(mgmtNote)}</p>
    <button class="ghost" onclick="window.open('/ui/classic.html','_blank')">${esc(mgmtBtnLabel)}</button>
  </div>`;
}

/* ============================================================
   3D VIEWER BRIDGE (protected contract)
   ============================================================ */
function vcmd(c){ try{ $('viewerFrame').contentWindow.postMessage({type:'expo:cmd',cmd:c},'*'); }catch(e){} }
window.addEventListener('message',ev=>{ const d=ev.data||{}; if(d.source!=='expo-viewer')return;
  if(d.type==='selection'){ lastSel=d.payload; setElementContext(d.payload); }
  else if(d.type==='ready'){ refreshDesignEmpty(); }
  else if(d.type==='loaded'){ if(Array.isArray(d.rels)) loadedRels=new Set(d.rels); if(d.added) toast('Model linked into the view'); } });
function getViewerCtx(){ return new Promise(res=>{ let done=false;
  const h=e=>{const d=e.data||{}; if(d.source==='expo-viewer'&&d.type==='context'){done=true;window.removeEventListener('message',h);res({context:d.context,selection:d.selection});}};
  window.addEventListener('message',h);
  try{$('viewerFrame').contentWindow.postMessage({type:'expo:getContext'},'*');}catch(e){}
  setTimeout(()=>{if(!done){window.removeEventListener('message',h);res({context:'',selection:(lastSel&&lastSel.text)||''});}},1500); }); }
function parseDims(text){ const dim={},loc={},rest=[]; (text||'').split('\n').forEach(l=>{ const m=l.split(':'); if(m.length<2){ if(l.trim())rest.push(l.trim()); return; }
  const k=m[0].trim(), v=m.slice(1).join(':').trim(); const kl=k.toLowerCase();
  if(/(height|length|width|thickness|area|volume|depth|perimeter)/.test(kl)) dim[k]=v;
  else if(/^(x|y|z)$|elevation|position/.test(kl)) loc[k]=v; else rest.push(k+': '+v); }); return {dim,loc,rest}; }

/* ============================================================
   DESIGN AI COPILOT
   ============================================================ */
function wireCopilot(){
  $('aiTabs').querySelectorAll('.ai-tab').forEach(t=>t.onclick=()=>setAiTab(t.dataset.tab));
  $('aiSend').onclick=()=>sendAi();
  $('aiIn').addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); sendAi(); } });
  $('ctxClear').onclick=()=>{ lastSel=null; $('ctxCard').hidden=true; updateCtxActions(); };
  $('aiAttachBtn').onclick=toggleAttachMenu;
  $('attachMenuUpload').onclick=()=>{ hideAttachMenu(); pickChatAttachmentFile(); };
  $('attachClear').onclick=clearAttachment;
  document.addEventListener('click',e=>{
    const m=$('attachMenu'); if(m.hidden) return;
    if(e.target.closest('#attachMenu')||e.target.closest('#aiAttachBtn')) return;
    hideAttachMenu();
  });
}
function setAiTab(tab){
  $('aiTabs').querySelectorAll('.ai-tab').forEach(t=>t.classList.toggle('on',t.dataset.tab===tab));
  ['chat','references','compliance','insights'].forEach(k=>{ const p=$('pane-'+k); if(p)p.hidden=(k!==tab); });
  if(tab==='compliance') renderCompliancePane();
  if(tab==='insights') renderInsightsPane();
  if(tab==='references') renderReferencesPane();
}
function aiGreeting(){ const nm=(currentUser&&(currentUser.full_name||currentUser.username))||'';
  $('aiMsgs').innerHTML=''; aiHist=[];
  addMsg('a','Hi '+esc(nm.split(' ')[0]||'there')+' — I\'m your Design AI Copilot. Pick a workspace on the left, then ask me about the active model, drawing, document, schedule or code. In the 3D model, click an element for a grounded, source-cited answer.');
}
function addMsg(who,html){ const d=el('div','m '+who,`<div class="av">${who==='u'?'U':'AI'}</div><div class="bub">${html}</div>`); $('aiMsgs').appendChild(d); $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight; return d.querySelector('.bub'); }

/* --- context card (element / document) --- */
function setElementContext(p){
  if(!p||p.kind==='none'){ if(currentDest==='design'){ $('ctxCard').hidden=true; } updateCtxActions(); return; }
  if(p.kind==='category'){ showCtx('Category', p.name, p.count+' elements', '▣'); updateCtxActions(); return; }
  const label=p.name||p.typeName||'Element';
  const sub=[p.typeName,p.objType].filter(Boolean).join(' · ')||'IFC element';
  showCtx(p.typeName||'Element', label, sub, '🧱', p.text);
  updateCtxActions();
}
function setDocContext(f){
  showCtx(f.category||'Document', f.filename, [f._rev?('Rev '+f._rev):'', f.discipline||''].filter(Boolean).join(' · ')||fileExt(f.filename), fileTypeIcon(fileExt(f.filename)));
  ctxDoc=f; updateCtxActions();
}
let ctxDoc=null;
function showCtx(kind, title, sub, icon, detail){
  $('ctxCard').hidden=false;
  $('ctxBody').innerHTML=`<div class="thumb">${icon||'▣'}</div><div style="min-width:0"><span class="muted" style="font-size:10.5px;text-transform:uppercase;letter-spacing:.4px">${esc(kind)}</span><b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(title)}</b><span>${esc(sub||'')}</span></div>`;
}

/* --- private chat attachments: the Copilot "+" button. Uploaded here, these
   are visible only to the uploading user (and to admins read-only) and are
   never added to the project's shared Documents/Drawings/Schedules — see
   /chat/attachments in main.py. Scoped to the current project; reset on
   project switch in selectProject(). --- */
let currentAttachment=null;   // {id, filename, status}
let _attachPollTimer=null;
function toggleAttachMenu(){ const m=$('attachMenu'); if(m.hidden) showAttachMenu(); else hideAttachMenu(); }
function hideAttachMenu(){ $('attachMenu').hidden=true; }
async function showAttachMenu(){
  if(!currentProject){ toast('Select a project first'); return; }
  const m=$('attachMenu'); m.hidden=false;
  const list=$('attachMenuList'), sep=$('attachMenuSep');
  list.innerHTML=`<div class="muted" style="padding:8px 9px;font-size:11.5px">Loading your uploads…</div>`;
  try{
    const r=await fetch(`${API}/chat/attachments?project=${encodeURIComponent(currentProject)}`);
    const d=await r.json(); const items=d.attachments||[];
    if(!items.length){ list.innerHTML=''; sep.hidden=true; return; }
    sep.hidden=false;
    list.innerHTML=items.map(a=>`<button class="attach-menu-item" data-id="${a.id}">
        ${svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',14)}
        <span class="fn">${esc(a.filename)}</span><span class="st">${a.status==='ready'?'':(a.status==='error'?'failed':'processing…')}</span>
      </button>`).join('');
    list.querySelectorAll('.attach-menu-item').forEach(btn=>{
      btn.onclick=()=>{ const a=items.find(x=>String(x.id)===btn.dataset.id); hideAttachMenu(); if(a) attachExisting(a); };
    });
  }catch(e){ list.innerHTML=`<div class="muted" style="padding:8px 9px;font-size:11.5px">Could not load your uploads.</div>`; sep.hidden=true; }
}
function pickChatAttachmentFile(){
  if(!currentProject){ toast('Select a project first'); return; }
  let inp=$('chatAttachInput');
  if(!inp){
    inp=document.createElement('input'); inp.type='file'; inp.id='chatAttachInput';
    inp.accept='.pdf,.docx,.xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff';
    inp.style.display='none'; document.body.appendChild(inp);
  }
  inp.value='';
  inp.onchange=async()=>{
    const f=inp.files[0]; inp.value=''; if(!f) return;
    toast('Uploading '+f.name+' …', true);
    const fd=new FormData(); fd.append('file',f); fd.append('project',currentProject);
    try{
      const r=await fetch(`${API}/chat/attachments`,{method:'POST',body:fd});
      const j=await r.json().catch(()=>({}));
      if(!r.ok) throw new Error(j.detail||('HTTP '+r.status));
      attachExisting(j);
      toast(f.name+' attached — only you can see this.');
    }catch(err){ toast('Attach failed: '+(err.message||err)); }
  };
  inp.click();
}
function attachExisting(att){
  currentAttachment={id:att.id, filename:att.filename, status:att.status||'processing'};
  showAttachChip(currentAttachment);
  if(currentAttachment.status!=='ready' && currentAttachment.status!=='error') pollAttachment(currentAttachment.id);
}
function pollAttachment(id){
  if(_attachPollTimer) clearInterval(_attachPollTimer);
  let tries=0;
  _attachPollTimer=setInterval(async()=>{
    tries++;
    try{
      const r=await fetch(`${API}/chat/attachments/${id}`);
      if(r.ok){ const a=await r.json();
        if(currentAttachment && currentAttachment.id===id){ currentAttachment.status=a.status; showAttachChip(currentAttachment); }
        if(a.status==='ready'||a.status==='error'){ clearInterval(_attachPollTimer); _attachPollTimer=null; return; }
      }
    }catch(e){}
    if(tries>=20){ clearInterval(_attachPollTimer); _attachPollTimer=null; }
  }, 2000);
}
function showAttachChip(att){
  $('attachCard').hidden=false;
  const statusTxt=att.status==='ready'?'Ready — Design AI will use this first':(att.status==='error'?'Could not read this file':'Processing…');
  $('attachBody').innerHTML=`<div class="thumb">${fileTypeIcon(fileExt(att.filename))}</div><div style="min-width:0"><span class="muted" style="font-size:10.5px;text-transform:uppercase;letter-spacing:.4px">Private · only you</span><b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(att.filename)}</b><span>${esc(statusTxt)}</span></div>`;
}
function clearAttachment(){
  if(_attachPollTimer){ clearInterval(_attachPollTimer); _attachPollTimer=null; }
  currentAttachment=null; $('attachCard').hidden=true;
}

/* --- contextual suggested actions (all real: AI query, navigation, or fetch) --- */
function updateCtxActions(){
  const wrap=$('ctxActions'); const acts=[];
  const A=(label,icon,fn)=>acts.push({label,icon,fn});
  const sel=lastSel&&lastSel.kind==='element';
  if(currentDest==='design'){
    if(sel){
      const label=(lastSel.name||lastSel.typeName||'element');
      A('Ask about this element','<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',()=>askElement());
      A('Check compliance with Dubai Building Code','<path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="9"/>',()=>{ setAiTab('chat'); askAbout(`Check compliance of the selected element (${label}) against the Dubai Building Code, citing the relevant clause.`,true); });
      A('Find similar elements','<rect x="3" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><path d="M14 3h7v7"/>',()=>findSimilar());
      A('Check material and fire rating','<path d="M12 2s6 5 6 11a6 6 0 0 1-12 0c0-6 6-11 6-11z"/>',()=>{ setAiTab('chat'); askElement('material and fire rating'); });
      A('Show related specifications','<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/>',()=>{ setAiTab('chat'); askAbout(`Find specifications related to the selected element (${label}).`); });
      A('Compare with drawings','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/>',()=>{ navigate('drawings'); });
      if(UI_FLAGS.clashAction) A('Check for clashes','<path d="M12 2v20M2 12h20"/>',()=>toast('Clash detection not configured'));
    } else {
      A('Load the 3D model','<path d="M12 2l9 5v10l-9 5-9-5V7z"/>',()=>loadModels());
      A('Ask about this model','<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',()=>{ setAiTab('chat'); $('aiIn').focus(); });
    }
  } else if(currentDest==='drawings'){
    A('Ask about this drawing','<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',()=>{ setAiTab('chat'); $('aiIn').focus(); });
    A('Find a requirement in drawings','<path d="M9 12l2 2 4-4"/>',()=>{ setAiTab('chat'); askAbout('Find the requirement or note in this drawing about: '); });
  } else if(currentDest==='documents'||currentDest==='specifications'){
    A('Summarize this document','<path d="M4 6h16M4 12h16M4 18h10"/>',()=>{ if(ctxDoc) askAbout(`Summarize the document "${ctxDoc.filename}".`); else toast('Open a document first'); });
    A('Find a requirement','<path d="M9 12l2 2 4-4"/>',()=>{ setAiTab('chat'); askAbout('Find the requirement about: '); });
    A('Find a reference','<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/>',()=>{ setAiTab('chat'); $('aiIn').focus(); });
  } else if(currentDest==='schedules'){
    A('Ask about these quantities','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 3v18"/>',()=>{ setAiTab('chat'); askAbout('From the project schedules and quantities, '); });
  } else if(currentDest==='codes'){
    A('Search codes & standards','<path d="M12 20h9"/><path d="M3 6l9-3 9 3"/>',()=>{ setAiTab('chat'); askAbout('In the codes and standards, what is required for: ',true); });
  } else if(currentDest==='qa'){
    A('Explain the selected issue','<path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/>',()=>{ setAiTab('chat'); $('aiIn').focus(); });
  } else if(currentDest==='reports'){
    A('Generate a report','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17V9M12 17v-5"/>',()=>{ const g=$('repGen'); if(g)g.click(); });
  } else {
    A('Ask Design AI','<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',()=>{ setAiTab('chat'); $('aiIn').focus(); });
  }
  if(ctxDoc && ctxDoc.rel && /\.pdf$/i.test(ctxDoc.filename||'') && (currentDest==='drawings'||currentDest==='documents'||currentDest==='specifications')){
    A('Re-read with vision (accurate tables)','<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',()=>reextractDoc());
  }
  wrap.innerHTML=`<div class="h">Suggested actions</div>`+acts.map((a,i)=>`<button class="act" data-i="${i}">${svg(a.icon)}${esc(a.label)}</button>`).join('');
  wrap.querySelectorAll('.act').forEach(btn=>btn.onclick=()=>acts[+btn.dataset.i].fn());
}

/* Force a vision re-read of the focused PDF so dense tables are captured accurately */
async function reextractDoc(){
  if(!ctxDoc||!ctxDoc.filename||!currentProject){ toast('Open a document first'); return; }
  const name=ctxDoc.filename;
  toast('Vision re-read of "'+name+'" started — reads each page as an image; this can take a while.');
  try{
    const r=await fetch(`${API}/projects/${encodeURIComponent(currentProject)}/reextract`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:name})});
    const d=await r.json();
    if(d&&d.status==='ready'){ toast('Done — '+(d.vision_pages||0)+' page(s) read by vision, '+(d.chunks||0)+' chunks re-indexed. Ask your question again.'); }
    else { toast('Re-read failed: '+((d&&d.detail)||'unknown')); }
  }catch(e){ toast('Re-read failed: '+(e&&e.message||e)); }
}

/* --- AI actions --- */
function askAbout(seed, standards){ setAiTab('chat'); const t=$('aiIn'); t.value=seed;
  if(seed.trim().endsWith(':')||seed.trim().endsWith('about:')){ t.focus(); return; } // waiting for user to complete
  sendAi(standards); }
async function askElement(aspect){
  if(!lastSel||lastSel.kind!=='element'){ toast('Select an element in the 3D model'); return; }
  const label=lastSel.name||lastSel.typeName||'element';
  const ctx=await getViewerCtx();
  setAiTab('chat');
  const q=aspect?`For the selected element (${label}), report its ${aspect} and flag anything missing or inconsistent.`
                :`Explain the selected element (${label}) and flag anything missing or inconsistent based on its IFC properties.`;
  addMsg('u',esc('About: '+label+(aspect?(' — '+aspect):'')));
  await stream(q,`${API}/ask_model`,{project:currentProject,query:q,context:ctx.context||'',selection:ctx.selection||lastSel.text||'',messages:aiHist.slice(-6)});
}
async function findSimilar(){
  if(!lastSel||lastSel.kind!=='element'){ toast('Select an element'); return; }
  const cls=lastSel.typeName||'';
  try{ const r=await fetch(`${API}/api/v1/bim/elements?project=${encodeURIComponent(currentProject)}&ifc_class=${encodeURIComponent(cls)}`); const d=await r.json();
    const n=(d&&d.count)||0;
    addMsg('a', n?`Found <b>${n}</b> element(s) of type <b>${esc(cls||'—')}</b> in the BIM store.`:`No indexed BIM elements match <b>${esc(cls||'—')}</b>. (BIM element indexing may be empty for this project.)`);
  }catch(e){ addMsg('a','BIM element query unavailable.'); }
  setAiTab('chat');
}
function updateAiCtx(){
  const map={ design:'3D model + selection', drawings:'Drawing viewer', documents:'Project documents',
    specifications:'Specifications', schedules:'Schedules & quantities', codes:'Codes / standards (KB)',
    qa:'QA & issues', reports:'Reports', overview:'Project overview', settings:'Project' };
  $('aiCtx').innerHTML=`Context: <b>${esc(map[currentDest]||'Project')}</b>${currentRevision?` · Rev ${esc(currentRevision)}`:''}`;
  const ph={ design:'Ask Design AI about this element, model, drawings, specifications or codes…',
    drawings:'Ask Design AI about this drawing, revision, detail or requirement…',
    documents:'Ask Design AI about this document…', specifications:'Ask Design AI about this specification…',
    schedules:'Ask Design AI about these quantities / data…', codes:'Ask Design AI about this requirement…',
    qa:'Ask Design AI about this issue…', reports:'Ask Design AI to help with a report…' };
  $('aiIn').placeholder=ph[currentDest]||'Ask Design AI…';
}

/* --- streaming client (protected: reuse SSE contract verbatim) --- */
async function stream(display,endpoint,body){ const bub=addMsg('a','<span class="faint">…</span>'); let ans=''; let structured=null;
  try{ const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){ bub.innerHTML='<span style="color:var(--red)">Error '+r.status+'</span>'; return; }
    const rd=r.body.getReader(); const dec=new TextDecoder(); let buf='';
    while(true){ const {value,done}=await rd.read(); if(done)break; buf+=dec.decode(value,{stream:true}); let i;
      while((i=buf.indexOf('\n\n'))>=0){ const line=buf.slice(0,i); buf=buf.slice(i+2); const dl=line.split('\n').find(l=>l.startsWith('data:')); if(!dl)continue;
        let d; try{d=JSON.parse(dl.slice(5).trim());}catch(e){continue;}
        if(d.type==='sources'){ lastSources=d.sources||[]; }
        else if(d.type==='token'){ ans+=d.text; bub.innerHTML=mdLite(ans)+(bub._ev||''); $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight; }
        else if(d.type==='error'){ ans+='\n[error] '+d.message; bub.innerHTML=mdLite(ans); }
        else if(d.type==='structured'){ structured=d.data||null; }
      } }
    // Show only the sources the answer actually cited
    { const hasCites=/\[SOURCE:/i.test(ans); const cited=citedSources(ans,lastSources);
      const showSrc = hasCites ? cited : lastSources;
      lastUsedSources = showSrc;
      bub._ev = evHTML(showSrc);
      bub.innerHTML = mdLite(ans)+bub._ev; }
    if(!ans&&!bub._ev) bub.innerHTML='<span class="faint">(no answer)</span>';
    // Response Rendering Engine (additive): for document analysis / tables / metrics /
    // calculations / issues answers, replace the plain bubble with the trusted structured
    // renderer. A plain conversational answer (type "simple_answer") renders null and the
    // bubble above is left exactly as it was.
    try{
      if(structured && window.ExpoResponseRenderer){
        const card=window.ExpoResponseRenderer.render(structured);
        if(card){ bub.innerHTML=''; bub.appendChild(card); $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight; }
      }
    }catch(e){ /* never let the renderer break the plain answer that already rendered */ }
    aiHist.push({role:'user',content:body.query}); aiHist.push({role:'assistant',content:ans});
  }catch(e){ bub.innerHTML='<span style="color:var(--red)">Request failed: '+esc(e.message||e)+'</span>'; } }

/* Open a cited source at its page using the EXISTING document viewer (no second viewer). */
function openSourceTile(rel, page){
  if(!rel){ return; }
  const base=String(rel).replace(/\\/g,'/').split('/').pop();
  const f=allDocs.find(x=>x.rel===rel || x.filename===base || (x.rel&&x.rel.endsWith('/'+base)));
  if(!f){ openFile(rel); return; }
  const dest=/\.(pdf|dwg|dxf)$/i.test(f.filename)?'drawings':(/\.(xlsx|xls|csv)$/i.test(f.filename)?'schedules':'documents');
  if(currentDest!==dest){ try{ navigate(dest); }catch(e){} }
  setTimeout(()=>{
    const isPdf=/\.pdf$/i.test(f.filename);
    const v=$('docView');
    if(v && isPdf){ const pg=page?('#page='+page):''; v.innerHTML=`<div class="docframe-wrap"><iframe class="docframe" src="${fileURL(f.rel)}${pg||'#toolbar=1'}"></iframe></div>`; setDocContext(f); }
    else if(v){ openInViewer(f); }
    else { openFile(f.rel); }
  }, dest===currentDest?0:60);
}
window.openSourceTile = openSourceTile;

/* Parse [SOURCE: name | PAGE n] citations from the answer and keep only those sources */
function citedSources(ans,sources){
  if(!sources||!sources.length) return [];
  const re=/\[SOURCE:\s*([^\]|]+?)\s*(?:\|\s*PAGE\s*([0-9]+))?\s*\]/gi;
  const cites=[]; let m;
  while((m=re.exec(ans))) cites.push({name:(m[1]||'').trim().toLowerCase(), page:m[2]||null});
  if(!cites.length) return [];
  const base=x=>String(x||'').toLowerCase().split(/[\\/]/).pop();
  const full=x=>String(x||'').toLowerCase();
  const out=[], seen=new Set();
  sources.forEach(s=>{
    const sb=base(s.filename||s.source||s.rel), sf=full(s.filename||s.source||s.rel);
    const hit=cites.some(c=>{
      const cb=base(c.name);
      const nameOk = sb===cb || (cb && (sf.indexOf(cb)>=0 || cb.indexOf(sb)>=0));
      if(!nameOk) return false;
      if(c.page!=null && s.page!=null) return String(s.page)===String(c.page);
      return true;
    });
    if(hit){ const k=sf+'#'+(s.page!=null?s.page:''); if(!seen.has(k)){ seen.add(k); out.push(s); } }
  });
  return out;
}
/* Compact source chips (only the files actually used) */
function evHTML(sources){
  if(!sources||!sources.length) return '';
  return '<div class="evd">'+sources.map(s=>{
    const name=s.filename||s.source||s.rel||'source';
    const b=String(name).split(/[\\/]/).pop();
    const rel=s.rel||s.source||'';
    const ext=fileExt(b);
    const pg=(s.page!=null)?('p.'+s.page):'';
    const rev=s.revision?('Rev '+s.revision):'';
    return `<button class="chip" title="${esc(name)}${pg?' · '+esc(pg):''}" onclick="openFile('${esc(rel)}')">`
      +`<span class="ci">${fileTypeIcon(ext)}</span>`
      +`<span class="cn">${esc(b)}</span>`
      +(pg?`<span class="cp">${esc(pg)}</span>`:'')
      +(rev?`<span class="cp">${esc(rev)}</span>`:'')
      +`</button>`; }).join('')+'</div>';
}

async function sendAi(standards){ const t=$('aiIn'); const q=t.value.trim();
  if(!q){ return; } if(!currentProject){ toast('Select a project'); return; }
  t.value=''; addMsg('u',esc(q));
  const revNote=currentRevision?` (revision ${currentRevision})`:'';
  if(currentDest==='design'&&on3D){ const ctx=await getViewerCtx();
    await stream(q,`${API}/ask_model`,{project:currentProject,query:q+revNote,context:ctx.context||'',selection:ctx.selection||(lastSel&&lastSel.text)||'',messages:aiHist.slice(-6)}); }
  else { const prefix=(standards||currentDest==='codes')?'Using the codes/standards knowledge base, ':'';
    let scoped=q+revNote;
    const _focus=(ctxDoc&&(currentDest==='documents'||currentDest==='specifications'||currentDest==='drawings'))?(ctxDoc.rel||''):'';
    if(_focus) scoped=`Regarding "${ctxDoc.filename}": `+scoped;
    const _attId=(currentAttachment&&currentAttachment.id)||null;
    await stream(q,`${API}/ask_stream`,{project:currentProject,query:prefix+scoped,messages:aiHist.slice(-8),k:8,focus_doc:_focus,attachment_id:_attId}); }
}

/* --- References pane --- */
function renderReferencesPane(){
  const b=$('refBody');
  const refs=(lastUsedSources&&lastUsedSources.length)?lastUsedSources:lastSources;
  if(!refs.length){ b.innerHTML=`<div class="state"><div class="muted">Ask a question — the sources behind the answer appear here with page and revision.</div></div>`; return; }
  b.innerHTML=`<div class="dt-toolbar"><b>Sources used in the last answer</b></div>`+refs.map(s=>{
    const name=s.filename||s.source||s.rel||'source'; const rel=s.rel||s.source||'';
    return `<div class="li" onclick="openFile('${esc(rel)}')"><div class="fi">${fileTypeIcon(fileExt(name))}</div>
      <div class="fn"><b>${esc(name)}</b><span>${s.page!=null?('Page '+s.page):''}${s.revision?(' · Rev '+esc(s.revision)):''}</span></div></div>`; }).join('');
}

/* --- Compliance pane (deterministic engine, not the LLM) --- */
async function renderCompliancePane(){
  const b=$('compBody'); b.innerHTML=state('Loading compliance…','load');
  let findings=[], stats=null;
  try{ const r=await fetch(`${API}/api/v1/qa/findings?project=${encodeURIComponent(currentProject)}`); const d=await r.json(); findings=(d&&d.findings)||[]; }catch(e){}
  try{ const r=await fetch(`${API}/api/v1/qa/stats?project=${encodeURIComponent(currentProject)}`); if(r.ok)stats=await r.json(); }catch(e){}
  const p=findings.filter(f=>String(f.status).toUpperCase()==='PASS').length;
  const fl=findings.filter(f=>String(f.status).toUpperCase()==='FAIL').length;
  const rv=findings.filter(f=>String(f.status).toUpperCase()==='REVIEW').length;
  b.innerHTML=`<div class="tiles" style="grid-template-columns:1fr 1fr 1fr">
      <div class="tile"><h4>Pass</h4><div class="big" style="color:var(--green)">${p}</div></div>
      <div class="tile"><h4>Fail</h4><div class="big" style="color:var(--red)">${fl}</div></div>
      <div class="tile"><h4>Review</h4><div class="big" style="color:var(--amber)">${rv}</div></div></div>
    <p class="muted" style="margin-top:12px">Verdicts come from the deterministic compliance engine (code requirement + project evidence + rule). The language model only explains them.</p>
    ${findings.length?findings.map(f=>`<div class="li" onclick="navigate('qa')"><div class="fn"><b>${esc(f.title||f.finding_id)}</b><span>${statusBadge(f.status)} ${f.discipline?('· '+esc(f.discipline)):''}</span></div></div>`).join(''):state('No compliance findings yet. Run checks from the QA workspace or the deterministic engine.')}`;
}

/* --- Insights pane --- */
async function renderInsightsPane(){
  const b=$('insBody'); b.innerHTML=state('Loading insights…','load');
  try{ const r=await fetch(`${API}/api/v1/dashboard/stats?project=${encodeURIComponent(currentProject)}`); const s=await r.json();
    const dd=s.documents||{}, bim=s.bim||{}, hub=s.knowledge_hub||{};
    const row=(k,v)=>`<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #16223a"><span class="muted">${esc(k)}</span><b>${esc(v)}</b></div>`;
    b.innerHTML=`<div class="dt-toolbar"><b>Project insights</b></div>
      ${row('Documents total', dd.total!=null?dd.total:'—')}
      ${row('Documents processed', dd.processed!=null?dd.processed:'—')}
      ${row('BIM elements', bim.total_elements!=null?bim.total_elements:(bim.elements!=null?bim.elements:'—'))}
      ${row('Knowledge entities', hub.total_entities!=null?hub.total_entities:(hub.entities!=null?hub.entities:'—'))}`;
  }catch(e){ b.innerHTML=state('Insights unavailable.','err'); }
}

/* ============================================================
   START
   ============================================================ */
boot();


/* ---------- Resizable list column (all split workspaces) ---------- */
let _splitDragEl=null;
function initSplitter(splitEl){
  if(!splitEl) return;
  const saved=parseInt(localStorage.getItem('expo_list_w')||'',10);
  if(saved>=200) splitEl.style.setProperty('--list-w', saved+'px');
  let g=splitEl.querySelector('.gutter');
  if(!g){ g=document.createElement('div'); g.className='gutter'; g.title='Drag to resize'; splitEl.appendChild(g); }
  g.onmousedown=function(e){ e.preventDefault(); _splitDragEl=splitEl; g.classList.add('drag'); document.body.classList.add('col-resizing'); };
  g.ondblclick=function(){ splitEl.style.setProperty('--list-w','320px'); try{localStorage.setItem('expo_list_w','320');}catch(_){} };
}
window.addEventListener('mousemove',function(e){
  if(!_splitDragEl) return;
  const r=_splitDragEl.getBoundingClientRect();
  let w=e.clientX-r.left; w=Math.max(200, Math.min(r.width-320, w));
  _splitDragEl.style.setProperty('--list-w', w+'px');
});
window.addEventListener('mouseup',function(){
  if(!_splitDragEl) return;
  const w=parseInt(getComputedStyle(_splitDragEl).getPropertyValue('--list-w'),10);
  if(w){ try{localStorage.setItem('expo_list_w', String(w));}catch(_){} }
  const g=_splitDragEl.querySelector('.gutter'); if(g) g.classList.remove('drag');
  document.body.classList.remove('col-resizing');
  _splitDragEl=null;
});


/* ---------- Resizable side panels: nav (--sb) and Copilot (--ai) ---------- */
function initAppResizers(){
  const root=document.documentElement;
  try{
    const sb=parseInt(localStorage.getItem('expo_sb_w')||'',10); if(sb>=170) root.style.setProperty('--sb',sb+'px');
    const ai=parseInt(localStorage.getItem('expo_ai_w')||'',10); if(ai>=260) root.style.setProperty('--ai',ai+'px');
  }catch(e){}
  const sbH=document.getElementById('sbResize'), aiH=document.getElementById('aiResize');
  let mode=null;
  if(sbH) sbH.onmousedown=e=>{ e.preventDefault(); mode='sb'; sbH.classList.add('drag'); document.body.classList.add('col-resizing'); };
  if(aiH) aiH.onmousedown=e=>{ e.preventDefault(); mode='ai'; aiH.classList.add('drag'); document.body.classList.add('col-resizing'); };
  window.addEventListener('mousemove',e=>{
    if(mode==='sb'){ const w=Math.max(170,Math.min(460,e.clientX)); root.style.setProperty('--sb',w+'px'); }
    else if(mode==='ai'){ const w=Math.max(260,Math.min(560,window.innerWidth-e.clientX)); root.style.setProperty('--ai',w+'px'); }
  });
  window.addEventListener('mouseup',()=>{
    if(!mode) return;
    try{
      if(mode==='sb') localStorage.setItem('expo_sb_w', String(parseInt(getComputedStyle(root).getPropertyValue('--sb'),10)||248));
      if(mode==='ai') localStorage.setItem('expo_ai_w', String(parseInt(getComputedStyle(root).getPropertyValue('--ai'),10)||360));
    }catch(e){}
    if(sbH) sbH.classList.remove('drag'); if(aiH) aiH.classList.remove('drag');
    document.body.classList.remove('col-resizing'); mode=null;
  });
  // double-click to reset to defaults
  if(sbH) sbH.ondblclick=()=>{ root.style.setProperty('--sb','248px'); try{localStorage.setItem('expo_sb_w','248');}catch(_){ } };
  if(aiH) aiH.ondblclick=()=>{ root.style.setProperty('--ai','360px'); try{localStorage.setItem('expo_ai_w','360');}catch(_){ } };
}
