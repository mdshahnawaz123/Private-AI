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
window.API = API;

/* ---- UI feature flags (mirror server config; conservative defaults) ---- */
const UI_FLAGS = {
  clashAction: false,   // matches config.enable_clash_action (no clash engine yet → hidden)
};

/* ---- state ---- */
let authToken=null, currentUser=null, currentProject=null, projectsData={};
let allDocs=[], lastSel=null, aiHist=[], lastSources=[], lastUsedSources=[];
let currentDest='design', currentRevision='';
let viewerLoaded=false, on3D=false;
// Admin-only Coding Agent mode: ported from classic.html's coworkMode (see
// ~line 1113/1353 there) but wired to this Copilot panel instead of a parallel
// chat UI. When on, /ask_stream is sent mode:'cowork' -- gated admin-only by
// the server (auth.require_roles) in addition to this client-side check.
let coworkMode=false;

try{ authToken=localStorage.getItem('expo_token')||null; }catch(e){}

/* ---- inject Authorization on same-origin fetches (verbatim behavior) ---- */
const _fetch=window.fetch.bind(window);
window.fetch=function(u,o){ o=o||{}; try{ const s=(typeof u==='string')?u:(u&&u.url)||'';
  if(authToken&&(s.indexOf(API)===0||s.charAt(0)==='/')){ const h=new Headers(o.headers||{}); if(!h.has('Authorization'))h.set('Authorization','Bearer '+authToken); o=Object.assign({},o,{headers:h}); } }catch(e){} return _fetch(u,o); };

/* ---- tiny helpers ---- */
const $=id=>document.getElementById(id);
window.$ = $;
const el=(t,c,h)=>{const d=document.createElement(t); if(c)d.className=c; if(h!=null)d.innerHTML=h; return d;};
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const svg=(p,w)=>`<svg class="ico" viewBox="0 0 24 24" ${w?`style="width:${w}px;height:${w}px"`:''}>${p}</svg>`;
function toast(t){ const e=$('toast'); e.textContent=t; e.classList.add('show'); clearTimeout(e._t); e._t=setTimeout(()=>e.classList.remove('show'),2200); }
window.toast = toast;
function mdLite(s){
  // Escape before formatting: source text and model output are never HTML.
  const inline=t=>esc(t).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\[SOURCE:\s*([^\]\n]+?)\s*\|\s*PAGE\s+(\d+|UNPAGINATED)\s*\]/gi,
      (marker,name,page)=>'<details class="source-detail"><summary>Source · '+(page==='UNPAGINATED'?'unpaginated':'page '+page)+'</summary><div class="source-full">'+marker+'</div></details>')
    .replace(/\[([^\]]+)\]\(cadcraft:([^)]+)\)/gi,
      (m,label,fname)=>'<div style="margin:8px 0"><button class="cad-action-btn" onclick="openCadDrawingFromProject(\''+esc(fname)+'\')"><svg class="ico" style="width:14px;height:14px;vertical-align:middle;margin-right:6px" viewBox="0 0 24 24"><path d="M3 3h18v18H3zM3 9h18M9 3v18"/><circle cx="15" cy="15" r="3"/></svg>'+esc(label)+'</button></div>');
  const lines=String(s==null?'':s).replace(/\r\n/g,'\n').split('\n');
  const out=[]; let i=0;
  // Citation markers are valid inside Markdown table cells. Protect their
  // internal separator while splitting columns, then restore it before the
  // normal inline citation renderer processes the cell.
  const cells=t=>t.replace(/\[SOURCE:\s*([^\]\n]+?)\s*\|\s*PAGE\s+(\d+|UNPAGINATED)\s*\]/gi,
    marker=>marker.replace('|','\uE000')).trim().replace(/^\|/,'').replace(/\|$/,'').split('|')
    .map(x=>x.replace(/\uE000/g,'|').trim());
  while(i<lines.length){
    const line=lines[i];
    if(/^```/.test(line)){const code=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))code.push(lines[i++]);if(i<lines.length)i++;out.push('<pre><code>'+esc(code.join('\n'))+'</code></pre>');continue;}
    if(!line.trim()){i++;continue;}
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i+1])){
      const head=cells(line);i+=2;const rows=[];
      while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){
        const row=cells(lines[i]);if(row.length!==head.length)break;
        rows.push('<tr>'+row.map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>');i++;
      }
      out.push('<div class="answer-table"><table><thead><tr>'+head.map(c=>'<th scope="col">'+inline(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>');continue;
    }
    const list=line.match(/^\s*(?:([-•])\s+|\d+[.)]\s+)(.*)$/);
    if(list){const ordered=!list[1];const tag=ordered?'ol':'ul';const items=[];
      const pattern=ordered?/^\s*\d+[.)]\s+(.*)$/:/^\s*[-•]\s+(.*)$/;
      while(i<lines.length){const m=lines[i].match(pattern);if(!m)break;items.push('<li>'+inline(m[1])+'</li>');i++;}
      out.push('<'+tag+'>'+items.join('')+'</'+tag+'>');continue;
    }
    const heading=line.match(/^#{1,6}\s+(.*)$/);
    out.push(heading?'<h4>'+inline(heading[1])+'</h4>':'<div class="answer-paragraph">'+inline(line)+'</div>');i++;
  }
  return out.join('');
}
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
function documentWorkspaceFile(f){
  return byDest('documents',x=>rx.doc.test(x.filename)&&!rx.spec.test((x.folder||'')+' '+x.filename))(f)
    || (['reports','schedules'].includes(folderName(f))&&rx.doc.test(f.filename));
}
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
  const coworkBtn=$('aiCoworkToggle');
  if($('aiCoworkFolder')) $('aiCoworkFolder').hidden=!isAdmin;
  if($('aiCoworkFiles')) $('aiCoworkFiles').hidden=!isAdmin;
  if(coworkBtn){
    coworkBtn.hidden=!isAdmin;
    if(!isAdmin){ coworkMode=false; coworkBtn.classList.remove('on'); coworkBtn.textContent='Coding Agent'; }
  }
  loadProjects(); aiGreeting();
}
function logout(){ try{localStorage.removeItem('expo_token');}catch(e){} location.reload(); }
// Matches the backend's /upload role check (admin + lead). Keep this in sync
// with classic.html's uploadBtn/docsUploadBtn gating and main.py's
// auth.require_roles(request, "admin", "lead") on /upload.
function canUpload(){ return !!(currentUser && (currentUser.role==='admin' || currentUser.role==='lead')); }
// Matches main.py's auth.require_roles(request, "admin") gate on mode:'cowork'
// in /ask_stream. The toggle itself is also hidden for non-admins (onAuthed),
// this is the defense-in-depth check at the point the request is built.
function isAdminUser(){ return !!(currentUser && currentUser.role==='admin'); }

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
  $('aiExpand').onclick=()=>setChatExpanded(!document.body.classList.contains('chat-expanded'));
  $('aiCollapse').onclick=()=>{if(document.body.classList.contains('chat-expanded')){setChatExpanded(false);return;}if(document.body.clientWidth<=1200)document.body.classList.remove('show-ai');else document.body.classList.toggle('ai-collapsed');};
  $('aiToggle').onclick=()=>{if(document.body.clientWidth<=1200)document.body.classList.toggle('show-ai');else document.body.classList.toggle('ai-collapsed');};
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
  documents:allDocs.filter(documentWorkspaceFile).length,
  specs:allDocs.filter(byDest('specifications', f=>rx.spec.test((f.folder||'')+' '+f.filename))).length,
  schedules:allDocs.filter(byDest('schedules', f=>rx.sched.test(f.filename))).length,
}; }
function buildRevSelect(){
  const revs=[...new Set(allDocs.map(f=>f._rev).filter(Boolean))].sort();
  if(!revs.length){ $('revWrap').hidden=true; currentRevision=''; return; }
  $('revWrap').hidden=false;
  $('revSel').innerHTML=`<option value="">All revisions</option>`+revs.map(r=>`<option value="${esc(r)}">File Rev ${esc(r)}</option>`).join('');
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
  ['studio','AI Design Studio','<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><circle cx="12" cy="12" r="9"/>'],
  ['models','Models','<path d="M12 2l9 5v10l-9 5-9-5V7z"/>'],
  ['drawings','Drawings','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>'],
  ['cadcraft','CADCraft Studio','<path d="M3 3h18v18H3zM3 9h18M9 3v18"/><circle cx="15" cy="15" r="3"/>'],
  ['documents','Documents','<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>'],
  ['schedules','Schedules','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 3v18"/>'],
  ['specifications','Specifications','<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/>'],
  ['codes','Codes & Standards','<path d="M12 20h9"/><path d="M3 6l9-3 9 3"/><path d="M4 10v8M20 10v8M9 21V10M15 21V10"/>'],
  ['qa','QA & Issues','<path d="M10.3 3.9l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'],
  ['reports','Reports','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17V9M12 17v-5M15 17v-3"/>'],
  ['video','AI Video Studio','<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>'],
  ['mpd','MPD','<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>'],
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
  if(currentDest==='studio' && dest!=='studio' && _studioPollTimer){ clearInterval(_studioPollTimer); _studioPollTimer=null; }
  if(currentDest==='video' && dest!=='video' && _videoPollTimer){ clearInterval(_videoPollTimer); _videoPollTimer=null; }
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
    if(dest==='mpd' || dest==='cadcraft'){
      $('genericWrap').style.position='absolute';
      $('genericWrap').style.inset='0';
      $('genericWrap').style.overflow='hidden';
    } else {
      $('genericWrap').style.position='';
      $('genericWrap').style.inset='';
      $('genericWrap').style.overflow='';
    }
    const meta=DESTS.find(d=>d[0]===dest);
    $('wsTitle').innerHTML=`${meta?esc(meta[1]):esc(dest)} ${currentRevision?`<span class="sub">· Rev ${esc(currentRevision)}</span>`:''}`;
    $('wsTools').innerHTML='';
    renderGeneric(dest);
  }
  updateCtxActions(); updateAiCtx();
  if(document.body.clientWidth<=1200) document.body.classList.remove('show-sb');
}
function renderCadCraft(c){
  const fn = (typeof renderCadCraftWorkspace === 'function') ? renderCadCraftWorkspace : (typeof window !== 'undefined' && typeof window.renderCadCraftWorkspace === 'function' ? window.renderCadCraftWorkspace : null);
  if (fn) {
    fn(c);
  } else {
    c.innerHTML = '<div class="ws-scroll" style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;text-align:center"><div class="state" style="padding:40px"><div style="font-size:14px;font-weight:600;margin-bottom:8px">Loading CADCraft Studio...</div><p style="color:var(--muted);font-size:12px;margin-bottom:16px">The AutoCAD clean-room drafting workspace is initializing.</p></div></div>';
    let tries = 0;
    const checkCad = setInterval(() => {
      tries++;
      const readyFn = (typeof renderCadCraftWorkspace === 'function') ? renderCadCraftWorkspace : (typeof window !== 'undefined' ? window.renderCadCraftWorkspace : null);
      if (typeof readyFn === 'function') {
        clearInterval(checkCad);
        if (typeof currentDest === 'undefined' || currentDest === 'cadcraft') readyFn(c);
      } else if (tries > 60) {
        clearInterval(checkCad);
      }
    }, 50);
  }
}
function renderMPD(c){
  const fn = (typeof renderMPDWorkspace === 'function') ? renderMPDWorkspace : (typeof window !== 'undefined' ? window.renderMPDWorkspace : null);
  if(fn) fn(c);
  else c.innerHTML = '<div class="ws-scroll" style="display:flex;align-items:center;justify-content:center;height:100%"><div class="state">Loading MPD Workspace...</div></div>';
}
function renderGeneric(dest){
  const b=$('genericWrap');
  const R={ overview:renderOverview, studio:renderStudio, video:renderVideoStudio, mpd:renderMPD, models:renderModels, drawings:renderDrawings,
    cadcraft:renderCadCraft,
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
  $('loadBtn').onclick=()=>openFragments();
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
  const url=`/ui/viewer.html?v=42&embed=1&project=${encodeURIComponent(currentProject)}&token=${encodeURIComponent(authToken||'')}&${rels}`;
  $('vpEmpty').style.display='none'; $('viewerFrame').style.display='block'; $('viewerFrame').src=url; viewerLoaded=true;
}
// PRIMARY engine: the Fragments viewer (fast .frag loading + federation). This
// is now what "Open in 3D" uses. relList optional; empty/omitted = all IFCs.
function openFragments(relList){
  const ifc=allDocs.filter(f=>rx.ifc.test(f.filename));
  if(!ifc.length){ toast('No IFC models in this project'); return; }
  let chosen = (relList && relList.length) ? relList.slice() : ifc.map(f=>f.rel);
  if(chosen.length>8 && !confirm(`Open ${chosen.length} models together? Large sets can be memory-heavy. Continue?`)) return;
  loadedRels = new Set(chosen);
  navigate('design');
  const rels=chosen.map(r=>'rel='+encodeURIComponent(r)).join('&');
  const url=`/ui/viewer.html?v=42&embed=1&project=${encodeURIComponent(currentProject)}&token=${encodeURIComponent(authToken||'')}&${rels}`;
  $('vpEmpty').style.display='none'; $('viewerFrame').style.display='block'; $('viewerFrame').src=url; viewerLoaded=true;
}
// Open exactly the models ticked in the Models table (Fragments engine).
function openSelectedModels(){
  const checked=[...document.querySelectorAll('.mdlChk:checked')].map(c=>c.value);
  if(!checked.length){ toast('Tick one or more models first'); return; }
  openFragments(checked);
}
// Open just one model (per-row "Open").
function openOneModel(btn){ openFragments([btn.dataset.rel]); }
// Back-compat alias.
function openFragmentsBeta(){ openFragments(); }
// Link another model INTO the already-open scene without reloading. Falls back
// to a fresh load when the viewer is not running yet.
// Add a model to the current Fragments scene by reopening with the combined set
// (the Fragments viewer federates all rels at load).
function addModelToView(rel){
  if(loadedRels.has(rel)){ toast('That model is already in the view'); return; }
  const set = new Set(loadedRels); set.add(rel);
  openFragments([...set]);
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
      ${['design','studio','video','cadcraft','drawings','documents','schedules','codes','qa','reports'].map(k=>{ const m=DESTS.find(d=>d[0]===k); return `<div class="tile" style="cursor:pointer" onclick="navigate('${k}')"><h4>${svg(m[2])} ${esc(m[1])}</h4><p>Open workspace →</p></div>`; }).join('')}
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
      <button class="primary" style="margin-left:auto" title="Fast Fragments engine" onclick="openSelectedModels()">⚡ Open selected in 3D</button>
      <button class="tb" style="margin-left:8px" onclick="openFragments()">Open all</button>
      <button class="tb" style="margin-left:8px" title="Original web-ifc viewer (raw IFC, slower)" onclick="navigate('design');loadModels()">Classic viewer</button></div>
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
function renderDocuments(b){ renderSplitDocs(b, docsBy(documentWorkspaceFile), 'document', 'No documents in this project.'); }
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
    <div class="fn"><b>${esc(f.filename)}</b><span>${esc(f.folder||f.category||'')}${f._rev?` · File Rev ${esc(f._rev)}`:''}${f.chunks?` · ${f.chunks} chunks`:''}</span></div></div>`).join('');
  lc.querySelectorAll('.li').forEach(li=>li.onclick=()=>{
    lc.querySelectorAll('.li').forEach(x=>x.classList.remove('on')); li.classList.add('on');
    const f=list[+li.dataset.i]; openInViewer(f);
  });
  // auto-open first
  lc.querySelector('.li').click();
}
let pdfPreviewSequence=0, pdfPreviewObjectUrl=null;
async function openPdfPreview(f,page=1,highlightSnippet=null,highlightRects=null){
  const v=$('docView'); if(!v)return;
  const sequence=++pdfPreviewSequence;
  setDocContext(f);
  v.innerHTML=state('Loading source page…','load');
  try{
    let url = `${API}/projects/${encodeURIComponent(currentProject)}/page-preview?rel=${encodeURIComponent(f.rel)}&page=${page}`;
    if(highlightSnippet) url += `&highlight_snippet=${encodeURIComponent(highlightSnippet)}`;
    if(highlightRects) url += `&highlight_rects=${encodeURIComponent(JSON.stringify(highlightRects))}`;
    const response=await fetch(url);
    if(!response.ok)throw new Error((await response.json()).detail||'Source preview unavailable');
    const pages=Number(response.headers.get('X-PDF-Pages'));
    const isHighlighted = response.headers.get('X-Evidence-Highlighted') === '1';
    const pixels=await response.blob();
    if(sequence!==pdfPreviewSequence||!v.isConnected)return;
    if(pdfPreviewObjectUrl)URL.revokeObjectURL(pdfPreviewObjectUrl);
    pdfPreviewObjectUrl=URL.createObjectURL(pixels);
    const hlBadge = isHighlighted ? '<span class="badge-s b-pass" style="margin-left:8px;font-size:11px">📍 Evidence Highlighted</span>' : '';
    v.innerHTML=`<div class="dt-toolbar"><button class="tb" id="pdfPrev" ${page<=1?'disabled':''}>Previous</button><span>Source page ${page} / ${pages}</span>${hlBadge}<button class="tb" id="pdfNext" ${page>=pages?'disabled':''}>Next</button><button class="tb" id="pdfZoom">Zoom in</button><button class="tb" id="pdfOriginal" style="margin-left:auto">Open original PDF</button></div><div style="height:calc(100% - 48px);overflow:auto;background:#fff"><img id="pdfSourcePage" alt="Source page ${page}: ${esc(f.filename)}" style="display:block;width:100%;height:auto" src="${pdfPreviewObjectUrl}"></div>`;
    $('pdfPrev').onclick=()=>openPdfPreview(f,page-1,highlightSnippet,highlightRects);
    $('pdfNext').onclick=()=>openPdfPreview(f,page+1,highlightSnippet,highlightRects);
    $('pdfOriginal').onclick=()=>openFile(f.rel);
    $('pdfZoom').onclick=()=>{const image=$('pdfSourcePage');const fitted=image.style.width==='100%';image.style.width=fitted?'auto':'100%';$('pdfZoom').textContent=fitted?'Fit width':'Zoom in';};
  }catch(error){if(sequence===pdfPreviewSequence&&v.isConnected)v.innerHTML=state(error.message||'Source preview unavailable.','err');}
}
function openInViewer(f){
  const isPdf=/\.pdf$/i.test(f.filename);
  const isCad=/\.(dwg|dxf)$/i.test(f.filename);
  const v=$('docView');
  if(isPdf){ openPdfPreview(f,1); }
  else if(isCad){
    v.innerHTML=`
      <div class="ws-scroll" style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;text-align:center;padding:40px 20px">
        <div style="width:68px;height:68px;border-radius:14px;background:rgba(47,107,255,0.12);display:flex;align-items:center;justify-content:center;margin-bottom:18px;border:1px solid rgba(47,107,255,0.28);box-shadow:0 8px 24px rgba(0,0,0,0.25)">
          <svg class="ico" style="width:36px;height:36px;color:var(--accent2)" viewBox="0 0 24 24"><path d="M3 3h18v18H3zM3 9h18M9 3v18"/><circle cx="15" cy="15" r="3"/></svg>
        </div>
        <h3 style="margin:0 0 8px 0;font-size:16px;color:var(--text)">${esc(f.filename)}</h3>
        <p style="color:var(--muted);max-width:460px;margin:0 0 22px 0;font-size:12.5px;line-height:1.55">
          AutoCAD 2D vector drawing detected. Open in <b>CADCraft Studio</b> to view vector layers, snap to geometry, edit dimensions, draw new features, and render directly into the AI Design Studio.
        </p>
        <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:center">
          <button class="primary" style="display:inline-flex;align-items:center;gap:7px;padding:9px 18px" onclick="openCadDrawingFromProject('${esc(f.filename)}')">
            <span>✏️ Open & Redesign in CADCraft</span>
          </button>
          <button class="ghost" style="padding:9px 16px" onclick="openFile('${esc(f.rel)}')">Download file</button>
        </div>
      </div>
    `;
  }
  else { v.innerHTML=`<div class="ws-scroll">${state('Preview not available for .'+fileExt(f.filename).toLowerCase()+' — open in a new tab.')}<div style="text-align:center"><button class="primary" onclick="openFile('${esc(f.rel)}')">Open file</button></div></div>`; }
  // set copilot context to this document
  setDocContext(f);
}

async function openCadDrawingFromProject(filename){
  window._cadSkipDefaultSample = true;
  navigate('cadcraft');
  if(window.openCadProjectDrawing){
    await window.openCadProjectDrawing(filename, currentProject);
  }
  window._cadSkipDefaultSample = false;
}
window.openCadDrawingFromProject = openCadDrawingFromProject;

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
  const scheduleDocuments=docsBy(f=>folderName(f)==='schedules'&&rx.doc.test(f.filename));
  if(currentUser&&currentUser.role!=='admin'&&scheduleDocuments.length){
    renderSplitDocs(b,scheduleDocuments,'schedule document','No schedule documents in this project.');
    return;
  }
  b.innerHTML=`<div class="ws-scroll" id="schBody">${state('Loading schedules…','load')}</div>`;
  const canUp=canUpload();
  const uploadBtn=''; // Removed per request
  try{
    const r=await fetch(`${API}/api/v1/projects/${encodeURIComponent(currentProject)}/schedules`);
    if(!r.ok){
      b.innerHTML=state(r.status===403?'This schedule view is unavailable for your role. Open the PDF in Documents and ask the Copilot about its schedules.':'Could not load schedules. Try again or open the source document.');
      return;
    }
    const d=await r.json();
    // Scope Schedules to documents actually uploaded INTO the Schedules folder
    // (via the Upload button here) — not every structured table extracted from
    // any document anywhere in the project (that's what made unrelated rows,
    // like ones pulled from a Documents-workspace upload, show up here).
    const schedFiles=new Set(allDocs.filter(f=>String(f.folder||'').toLowerCase()==='schedules').map(f=>f.filename));
    const rows=(d.rows||[]).filter(row=>schedFiles.has(row.doc));
    const qty=(d.quantities||[]).filter(q=>schedFiles.has(q.source_doc));
    if(!rows.length && !qty.length){
      const emptyMsg='Nothing uploaded into Schedules yet. Schedule data is extracted automatically from project documents by the backend process.';
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
   AI DESIGN STUDIO — Generative Interface
   ============================================================ */
let _studioPollTimer = null;
let _studioWorkflows = [];
let _studioSelectedAspect = { width: 1024, height: 1024 };
let _studioSelectedFile = null;
let _studioSelectedMask = null;
let _studioActiveJob = null;
let _studioJobs = [];
let _studioEngineStatus = null;

async function renderStudio(b){
  if(_studioPollTimer){ clearInterval(_studioPollTimer); _studioPollTimer = null; }
  if(!currentProject){
    b.innerHTML = `<div class="ws-scroll">${state('Select a project first to use the AI Design Studio.')}</div>`;
    return;
  }
  b.innerHTML = `<div class="ws-scroll" id="studioLoading">${state('Loading AI Design Studio…','load')}</div>`;
  
  try {
    const [wfRes, stRes] = await Promise.all([
      fetch(`${API}/api/image-engine/workflows`),
      fetch(`${API}/api/image-engine/status`)
    ]);
    _studioWorkflows = wfRes.ok ? await wfRes.json() : [];
    _studioEngineStatus = stRes.ok ? await stRes.json() : null;
  } catch(e) {
    _studioWorkflows = [];
    _studioEngineStatus = null;
  }

  // Load recent jobs
  await _loadStudioJobs();

  // Render layout
  b.innerHTML = `
    <div class="studio-layout">
      <!-- SIDEBAR CONTROLS -->
      <div class="studio-sidebar" id="studioSidebar">
        <div style="font-size:13px;font-weight:700;display:flex;align-items:center;gap:7px;margin-bottom:2px">
          <svg class="ico" viewBox="0 0 24 24" style="color:var(--accent);width:18px;height:18px"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><circle cx="12" cy="12" r="9"/></svg>
          Concept Generation
        </div>
        
        <!-- Workflow Selection -->
        <div class="studio-field">
          <label for="studioWfSel">Workflow Engine</label>
          <select class="studio-select" id="studioWfSel">
            ${_studioWorkflows.length ? _studioWorkflows.map(w => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join('') : '<option value="architecture_concept">Architecture Concept Generator</option>'}
          </select>
          <div id="studioWfDesc" style="font-size:11px;color:var(--muted);line-height:1.4;margin-top:2px">
            ${_studioWorkflows[0] ? esc(_studioWorkflows[0].description) : 'Text-to-image architectural generation.'}
          </div>
        </div>

        <!-- Sketch / Reference Dropzone -->
        <div class="studio-field" id="studioDropzoneField">
          <label id="studioDropzoneLabel">Reference Image / Sketch <span style="font-weight:400;color:var(--faint)">(Optional)</span></label>
          <div class="studio-dropzone" id="studioDropzone">
            <div id="studioDropzoneContent">
              <svg class="ico" viewBox="0 0 24 24" style="width:26px;height:26px;margin:0 auto 6px;color:var(--faint)"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
              <div style="font-size:12px;font-weight:600">Drop sketch or image here</div>
              <div style="font-size:10.5px;color:var(--faint);margin-top:2px">or click to browse from disk</div>
            </div>
            <input type="file" id="studioFileInput" accept="image/png,image/jpeg,image/webp">
          </div>
          <div class="studio-preview-wrap" id="studioPreviewWrap" style="display:none">
            <img id="studioPreviewImg" src="" alt="Selected reference">
            <button class="studio-preview-remove" id="studioPreviewRemove" title="Remove reference image">×</button>
          </div>
        </div>

        <div class="studio-field">
          <label for="studioDesignMode">Design intent</label>
          <select class="studio-input" id="studioDesignMode"><option value="concept">New concept</option><option value="materials">Change finishes only</option><option value="enhancement">Improve render quality only</option><option value="creative_facade">Redesign facade screen — keep building shape</option></select>
          <div style="font-size:11px;color:var(--faint);margin-top:6px">Screen redesign changes the outer pattern and screen materials. Keep the building shape, floors, structure, openings and camera fixed. Review generated geometry before use.</div>
          <label for="studioMaskFile">Protect area outside facade screen (optional)</label>
          <input class="studio-input" type="file" id="studioMaskFile" accept="image/png">
          <div style="font-size:11px;color:var(--faint)">Upload an opaque black-and-white PNG matching the upright reference dimensions. White = replace screen area; black = retain original pixels. Include openings and structure in black. This composites the generated screen; inspect alignment and edges.</div>
          <button type="button" class="studio-enhance-btn" id="studioMaskClear">Remove mask</button>
          <label for="studioProtected">Keep unchanged</label>
          <input class="studio-input" id="studioProtected" maxlength="600" placeholder="Additional elements to protect, separated by commas">
          <label for="studioMaterials">Material palette</label>
          <input class="studio-input" id="studioMaterials" maxlength="600" placeholder="For example: warm limestone, bronze screens, clear glass">
          <label for="studioLighting">Lighting</label>
          <input class="studio-input" id="studioLighting" maxlength="300" placeholder="Keep the source lighting, or describe the requested change">
        </div>
        <!-- Prompt Field -->
        <div class="studio-field">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <label for="studioPrompt">Architectural Prompt</label>
            <button type="button" class="studio-enhance-btn" id="studioEnhanceBtn" title="Use AI reasoning (qwen3.5:9b) to enrich materials, lighting, and composition">
              <span>Develop 3 options</span>
            </button>
          </div>
          <textarea class="studio-textarea" id="studioPrompt" placeholder="Describe architectural geometry, materials, facade, lighting, surrounding landscape..."></textarea>
          
          <div id="studioReasoningBox" class="studio-reasoning-box" style="display:none">
            <div class="studio-reasoning-title">
              <span>💡 Architectural Director Reasoning</span>
              <a href="javascript:void(0)" id="studioRevertPrompt" style="color:var(--muted);text-decoration:underline;font-size:10px">Revert brief</a>
            </div>
            <div id="studioConstraintsWrap" class="studio-constraints-wrap" style="display:none"></div>
            <div id="studioReasoningText"></div>
            <div id="studioDesignOptionsWrap" style="display:none">
              <div style="font-size:10px;font-weight:700;color:var(--accent2);letter-spacing:.3px;margin:8px 0 4px 0;text-transform:uppercase">Compare design proposals — select an option</div>
              <div id="studioDesignOptionsList" class="studio-design-options" style="grid-template-columns:1fr"></div>
              <button type="button" class="studio-enhance-btn" id="studioRenderAlternatives">Generate all 3 previews</button>
              <div style="font-size:11px;color:var(--muted);margin-top:6px">Uses the same reference and seed. Compare geometry manually; these previews are not validated drawings.</div>
            </div>
          </div>

          <label style="display:flex;align-items:center;gap:6px;font-size:11px;font-weight:600;cursor:pointer;margin-top:5px;color:var(--muted);user-select:none">
            <input type="checkbox" id="studioAutoEnhance" checked> Auto-apply Reasoning AI before render
          </label>
          
          <div style="font-size:10px;font-weight:700;color:var(--faint);letter-spacing:.4px;margin-top:6px">STYLE & MATERIAL PRESETS</div>
          <div class="studio-chips" id="studioChips">
            <span class="studio-chip" data-chip="parametric timber lamella roof structure">Parametric Timber</span>
            <span class="studio-chip" data-chip="biophilic stepped garden terraces with lush native flora">Biophilic Terraces</span>
            <span class="studio-chip" data-chip="curtain wall glazing with integrated solar shading louvers">High-Tech Glazing</span>
            <span class="studio-chip" data-chip="warm textured rammed earth and fair-faced concrete">Rammed Earth & Concrete</span>
            <span class="studio-chip" data-chip="contemporary Arabesque geometric mashrabiya facade">Contemporary Mashrabiya</span>
            <span class="studio-chip" data-chip="cantilevered canopy pavilion with water reflection pool">Cantilevered Pavilion</span>
            <span class="studio-chip" data-chip="dramatic golden hour ambient lighting, hyperrealistic architectural photography">Golden Hour</span>
            <span class="studio-chip" data-chip="clean minimalist Nordic architectural detailing">Nordic Minimalist</span>
          </div>
        </div>

        <!-- Negative Prompt -->
        <details class="studio-details">
          <summary>Negative Prompt</summary>
          <div style="margin-top:8px" class="studio-field">
            <input class="studio-input" id="studioNegPrompt" value="blurry, distorted geometry, low quality, deformed columns, unrealistic physics, oversaturated, watermarks, grainy, artifacts">
          </div>
        </details>

        <!-- Aspect Ratio -->
        <div class="studio-field">
          <label>Aspect Ratio & Resolution</label>
          <div class="studio-res-group">
            <button type="button" class="studio-res-btn on" data-w="1024" data-h="1024"><b>1:1</b><span>1024×1024</span></button>
            <button type="button" class="studio-res-btn" data-w="1024" data-h="768"><b>4:3</b><span>1024×768</span></button>
            <button type="button" class="studio-res-btn" data-w="768" data-h="1024"><b>3:4</b><span>768×1024</span></button>
          </div>
        </div>

        <!-- Advanced Settings -->
        <details class="studio-details">
          <summary>Advanced Sampling Settings</summary>
          <div style="margin-top:10px;display:flex;flex-direction:column;gap:10px">
            <div>
              <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--muted)"><span>Steps</span><b id="studioStepsVal">25</b></div>
              <input type="range" id="studioSteps" min="10" max="50" value="25" style="width:100%">
            </div>
            <div>
              <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--muted)"><span>CFG Scale</span><b id="studioCfgVal">7.0</b></div>
              <input type="range" id="studioCfg" min="1" max="15" step="0.5" value="7.0" style="width:100%">
            </div>
            <div>
              <div style="font-size:11px;color:var(--muted);margin-bottom:4px">Seed (Optional)</div>
              <input type="number" class="studio-input" id="studioSeed" placeholder="Random (blank or -1)" style="width:100%">
            </div>
          </div>
        </details>

        <!-- Generate Button -->
        <button class="primary" id="studioGenBtn" style="padding:12px;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:8px;margin-top:6px">
          <svg class="ico" viewBox="0 0 24 24" style="width:16px;height:16px"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/></svg>
          <span id="studioGenBtnText">Generate Concept</span>
        </button>
      </div>

      <!-- MAIN WORKSPACE -->
      <div class="studio-main" id="studioMain">
        <!-- Status Bar -->
        <div class="studio-status-bar" id="studioStatusBar">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <div class="studio-pill ${(_studioEngineStatus&&_studioEngineStatus.available)?'online':'offline'}" id="studioStatusPill">
              ${(_studioEngineStatus&&_studioEngineStatus.available)?'🟢 AI Studio Engine Ready':'🔴 AI Studio Engine Offline'}
            </div>
            <button class="tb" id="studioEngineToggleBtn" style="padding:2px 10px;font-size:11px;font-weight:600;border-radius:6px;cursor:pointer;transition:all 0.2s ease;${(_studioEngineStatus&&_studioEngineStatus.available)?'border-color:rgba(224,108,117,0.5);color:#e06c75':'border-color:rgba(152,195,121,0.6);color:#98c379'}">
              ${(_studioEngineStatus&&_studioEngineStatus.available)?'⏹ Stop Engine':'▶ Start Engine'}
            </button>
            <span class="muted" style="font-size:11px" id="studioVramText">
              RTX 5080 (16 GB VRAM)
            </span>
          </div>
          <div style="display:flex;align-items:center;gap:12px">
            <span class="muted" style="font-size:11px" id="studioQueueText">
              Queue: ${(_studioEngineStatus&&_studioEngineStatus.queue_pending)||0} pending
            </span>
            <button class="tb" id="studioRefreshBtn" style="padding:4px 9px">↻ Refresh</button>
          </div>
        </div>

        <!-- Live Progress Card -->
        <div class="studio-progress-card" id="studioProgressCard" style="${_studioActiveJob?'':'display:none'}">
          <div class="studio-progress-h">
            <span id="studioProgressTitle">⚙️ Generating Concept…</span>
            <span id="studioProgressPct">0%</span>
            <button class="tb" id="studioCancelJobBtn" style="color:var(--red);border-color:var(--red);padding:2px 8px;font-size:11px">Cancel Job</button>
          </div>
          <div class="studio-pbar">
            <div class="studio-pbar-fill" id="studioProgressFill" style="width:0%"></div>
          </div>
          <div style="font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" id="studioProgressPrompt"></div>
        </div>

        <!-- Gallery Section -->
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:4px">
          <h3 style="margin:0;font-size:14px;font-weight:700">Project Architectural Concepts & Renders</h3>
          <span class="muted" style="font-size:11px" id="studioOutputCount"></span>
        </div>
        
        <div id="studioGalleryContainer"></div>
      </div>
    </div>
  `;

  _wireStudioControls();
  _updateActiveJobUI();
  _renderStudioGallery();

  // Polling hook
  window._refreshStudio = async () => {
    await _pollStudioStatus();
    await _loadStudioJobs();
    _updateActiveJobUI();
    _renderStudioGallery();
  };

  _studioPollTimer = setInterval(async () => {
    if(currentDest !== 'studio'){ clearInterval(_studioPollTimer); _studioPollTimer = null; return; }
    await _pollStudioStatus();
    if(_studioActiveJob) {
      await _pollActiveJob();
    }
  }, 2500);
}

async function _loadStudioJobs(){
  if(!currentProject){ _studioJobs = []; _studioActiveJob = null; return; }
  try {
    const res = await fetch(`${API}/api/image-engine/jobs?project=${encodeURIComponent(currentProject)}`);
    if(res.ok){
      _studioJobs = await res.json();
      _studioActiveJob = _studioJobs.find(j => j.status === 'queued' || j.status === 'running') || null;
    } else {
      _studioJobs = [];
      _studioActiveJob = null;
    }
  } catch(e) {
    _studioJobs = [];
    _studioActiveJob = null;
  }
}

function _renderEngineStatusUI(){
  if(!_studioEngineStatus) return;
  const pill = $('studioStatusPill');
  if(pill){
    pill.className = `studio-pill ${_studioEngineStatus.available ? 'online' : 'offline'}`;
    pill.textContent = _studioEngineStatus.available ? '🟢 AI Studio Engine Ready' : '🔴 AI Studio Engine Offline';
  }
  const btn = $('studioEngineToggleBtn');
  if(btn && !btn.dataset.loading){
    if(_studioEngineStatus.available){
      btn.textContent = '⏹ Stop Engine';
      btn.style.borderColor = 'rgba(224,108,117,0.5)';
      btn.style.color = '#e06c75';
      btn.title = 'Click to shut down local engine and free VRAM';
    } else {
      btn.textContent = '▶ Start Engine';
      btn.style.borderColor = 'rgba(152,195,121,0.6)';
      btn.style.color = '#98c379';
      btn.title = 'Click to launch local AI Studio Engine on RTX 5080';
    }
  }
  const vram = $('studioVramText');
  if(vram){
    const freeMb = _studioEngineStatus.vram_free_mb;
    vram.textContent = `RTX 5080 (16 GB VRAM)${freeMb ? ` · ${Math.round(freeMb/1024*10)/10} GB free` : ''}`;
  }
  _updateActiveJobUI();
  const q = $('studioQueueText');
  if(q){
    q.textContent = `Queue: ${_studioEngineStatus.queue_pending || 0} pending`;
  }
}

let _pollingStudio = false;
async function _pollStudioStatus(){
  if(_pollingStudio) return;
  _pollingStudio = true;
  try {
    const res = await fetch(`${API}/api/image-engine/status`);
    if(res.ok){
      _studioEngineStatus = await res.json();
      _renderEngineStatusUI();
    }
  } catch(e){}
  finally {
    _pollingStudio = false;
  }
}

async function _toggleEngineService(){
  const btn = $('studioEngineToggleBtn');
  if(!btn || btn.dataset.loading) return;
  const isOnline = _studioEngineStatus && _studioEngineStatus.available;
  const action = isOnline ? 'stop' : 'start';

  btn.dataset.loading = '1';
  btn.disabled = true;
  btn.textContent = isOnline ? '⏳ Stopping…' : '⏳ Starting…';

  try {
    const res = await fetch(`${API}/api/image-engine/service/${action}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    if(!res.ok){
      const err = await res.json().catch(()=>({}));
      throw new Error(err.detail || `Server status ${res.status}`);
    }
    const data = await res.json();
    if(action === 'start'){
      toast('Starting AI Studio Engine… initializing RTX 5080');
      let attempts = 0;
      let checkBusy = false;
      const interval = setInterval(async () => {
        if(checkBusy) return;
        attempts++;
        checkBusy = true;
        try {
          const sRes = await fetch(`${API}/api/image-engine/service/status`);
          if(sRes.ok){
            const s = await sRes.json();
            if(s.available){
              clearInterval(interval);
              delete btn.dataset.loading;
              btn.disabled = false;
              await _pollStudioStatus();
              toast('AI Studio Engine is ready!');
              if(window._refreshStudio) window._refreshStudio();
              return;
            }
          }
        } catch(e){}
        finally {
          checkBusy = false;
        }
        if(attempts >= 25){
          clearInterval(interval);
          delete btn.dataset.loading;
          btn.disabled = false;
          await _pollStudioStatus();
          toast('Engine starting in background, click Refresh in a moment');
        }
      }, 1500);
    } else {
      toast('AI Studio Engine stopped');
      setTimeout(async () => {
        delete btn.dataset.loading;
        btn.disabled = false;
        await _pollStudioStatus();
        if(window._refreshStudio) window._refreshStudio();
      }, 800);
    }
  } catch(err){
    toast('Engine control failed: ' + err.message);
    delete btn.dataset.loading;
    btn.disabled = false;
    _renderEngineStatusUI();
  }
}

async function _pollActiveJob(){
  if(!_studioActiveJob) return;
  try {
    const res = await fetch(`${API}/api/image-engine/jobs/${encodeURIComponent(_studioActiveJob.job_id)}`);
    if(res.ok){
      const updated = await res.json();
      _studioActiveJob = updated;
      
      if(updated.status === 'completed'){
        toast('Generation completed: ' + updated.job_id);
        _studioActiveJob = null;
        await _loadStudioJobs();
        _updateActiveJobUI();
        _renderStudioGallery();
      } else if(updated.status === 'failed'){
        toast('Generation failed: ' + (updated.error || 'unknown error'));
        _studioActiveJob = null;
        await _loadStudioJobs();
        _updateActiveJobUI();
        _renderStudioGallery();
      } else if(updated.status === 'cancelled'){
        toast('Generation cancelled: ' + updated.job_id);
        _studioActiveJob = null;
        await _loadStudioJobs();
        _updateActiveJobUI();
        _renderStudioGallery();
      } else {
        _updateActiveJobUI();
      }
    }
  } catch(e){}
}

function _updateActiveJobUI(){
  const card = $('studioProgressCard');
  const genBtn = $('studioGenBtn');
  const genText = $('studioGenBtnText');
  if(!card) return;

  if(_studioActiveJob){
    card.style.display = '';
    const isRunning = _studioActiveJob.status === 'running';
    const pct = Number.isFinite(_studioActiveJob.progress_percent) ? _studioActiveJob.progress_percent : 0;
    const fill = $('studioProgressFill');
    if(fill) fill.style.width = pct + '%';
    const pctLabel = $('studioProgressPct');
    if(pctLabel) pctLabel.textContent = pct + '%';
    const title = $('studioProgressTitle');
    if(title){
      const stepStr = (_studioActiveJob.current_step != null) ? `Step ${_studioActiveJob.current_step}/${_studioActiveJob.total_steps}` : (isRunning ? 'Processing diffusion model…' : 'Job Queued…');
      title.textContent = `⚙️ ${stepStr}`;
    }
    const promptEl = $('studioProgressPrompt');
    if(promptEl) promptEl.textContent = `"${_studioActiveJob.prompt || ''}"`;
    if(genBtn){ genBtn.disabled = true; genBtn.style.opacity = '0.6'; }
    if(genText) genText.textContent = isRunning ? 'Generating Concept…' : 'Job In Queue…';
  } else {
    card.style.display = 'none';
    if(genBtn){ genBtn.disabled = !_studioEngineStatus?.available; genBtn.style.opacity = genBtn.disabled ? '0.6' : '1'; }
    if(genText) genText.textContent = 'Generate Concept';
  }
}

function _wireStudioControls(){
  // Workflow dropdown change
  const wfSel = $('studioWfSel');
  if(wfSel){
    wfSel.onchange = () => {
      const wf = _studioWorkflows.find(w => w.id === wfSel.value);
      if(wf){
        for(const [name, inputId, labelId] of [['steps','studioSteps','studioStepsVal'],['cfg','studioCfg','studioCfgVal']]){
          const parameter = (wf.parameters || []).find(p => p.name === name);
          const input = $(inputId), label = $(labelId);
          if(parameter && input){
            input.min = parameter.min_value; input.max = parameter.max_value;
            input.value = parameter.default; input.disabled = parameter.min_value === parameter.max_value;
            if(label) label.textContent = parameter.default;
          }
        }
        const desc = $('studioWfDesc');
        if(desc) desc.textContent = wf.description || '';
        const reqImg = (wf.parameters || []).some(p => p.type === 'image' && p.required);
        const auto = $('studioAutoEnhance'), enhance = $('studioEnhanceBtn');
        if(auto){ auto.disabled = reqImg; if(reqImg) auto.checked = false; }
        if(enhance){ enhance.disabled = false; enhance.title = 'Develop three proposals from a structured written brief'; }
        const mode = $('studioDesignMode');
        if(mode){ mode.value = reqImg ? (wf.category === 'enhancement' ? 'enhancement' : 'materials') : 'concept';
          Array.from(mode.options).forEach(option => option.disabled = reqImg ? option.value === 'concept' : option.value !== 'concept'); }
        document.querySelectorAll('.studio-res-btn').forEach(button => {
          button.disabled = reqImg;
          button.title = reqImg ? 'Reference image framing determines the output size' : 'Choose concept output size';
        });
        const negative = $('studioNegPrompt');
        if(negative){ negative.disabled = !(wf.parameters || []).some(p => p.name === 'negative_prompt'); if(negative.disabled) negative.value = ''; }
        const lbl = $('studioDropzoneLabel');
        if(lbl) lbl.innerHTML = reqImg ? 'Reference Image / Sketch <b style="color:var(--accent2)">(Required)</b>' : 'Reference Image / Sketch <span style="font-weight:400;color:var(--faint)">(Optional)</span>';
      }
    };
  }

  if(wfSel && wfSel.onchange) wfSel.onchange();

  // Dropzone drag & drop and file picker
  const dropzone = $('studioDropzone');
  const fileInput = $('studioFileInput');
  const previewWrap = $('studioPreviewWrap');
  const previewImg = $('studioPreviewImg');
  const removeBtn = $('studioPreviewRemove');
  const dropContent = $('studioDropzoneContent');

  function handleFile(f){
    if(!f) return;
    if(!f.type.startsWith('image/')){ toast('Only image files (PNG, JPG, WEBP) are supported'); return; }
    if(f.size > 25 * 1024 * 1024){ toast('Image file exceeds 25 MB limit'); return; }
    _studioSelectedFile = f;
    _studioSelectedMask = null;
    if($('studioMaskFile')) $('studioMaskFile').value = '';
    const url = URL.createObjectURL(f);
    if(previewImg) previewImg.src = url;
    if(previewWrap) previewWrap.style.display = '';
    if(dropContent) dropContent.style.display = 'none';
  }

  if(dropzone && fileInput){
    dropzone.onclick = () => fileInput.click();
    fileInput.onchange = () => { if(fileInput.files.length) handleFile(fileInput.files[0]); };
    dropzone.ondragover = e => { e.preventDefault(); e.stopPropagation(); dropzone.classList.add('dragover'); };
    dropzone.ondragleave = e => { e.preventDefault(); e.stopPropagation(); dropzone.classList.remove('dragover'); };
    dropzone.ondrop = e => {
      e.preventDefault(); e.stopPropagation(); dropzone.classList.remove('dragover');
      if(e.dataTransfer && e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    };
  }

  if(removeBtn){
    removeBtn.onclick = e => {
      e.stopPropagation();
      _studioSelectedFile = null;
      _studioSelectedMask = null;
      if($('studioMaskFile')) $('studioMaskFile').value = '';
      if(fileInput) fileInput.value = '';
      if(previewWrap) previewWrap.style.display = 'none';
      if(dropContent) dropContent.style.display = '';
    };
  }

  const maskInput = $('studioMaskFile');
  if(maskInput) maskInput.onchange = () => {
    const file = maskInput.files[0];
    if(file && (!_studioSelectedFile || file.type !== 'image/png' || file.size > 25*1024*1024)){
      toast('Select a reference first, then a PNG mask up to 25 MB');
      maskInput.value = ''; _studioSelectedMask = null; return;
    }
    _studioSelectedMask = file || null;
  };
  if($('studioMaskClear')) $('studioMaskClear').onclick = () => {
    _studioSelectedMask = null; if(maskInput) maskInput.value = '';
  };

  // Preset chips
  const chips = $('studioChips');
  const promptEl = $('studioPrompt');
  if(chips && promptEl){
    chips.querySelectorAll('.studio-chip').forEach(chip => {
      chip.onclick = () => {
        const text = chip.dataset.chip;
        const cur = promptEl.value.trim();
        promptEl.value = cur ? `${cur}, ${text}` : text;
        promptEl.focus();
      };
    });
  }

  // Enhance Prompt button & Architectural Director
  const enhanceBtn = $('studioEnhanceBtn');
  const reasoningBox = $('studioReasoningBox');
  const reasoningText = $('studioReasoningText');
  const constraintsWrap = $('studioConstraintsWrap');
  const designOptionsWrap = $('studioDesignOptionsWrap');
  const designOptionsList = $('studioDesignOptionsList');
  const revertLink = $('studioRevertPrompt');
  let _preEnhancedPrompt = '';
  let _proposalSnapshot = null;

  const _escHtml = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  if(enhanceBtn && promptEl){
    enhanceBtn.onclick = async () => {
      const curPrompt = promptEl.value.trim();
      if(!curPrompt){
        toast('Enter a design brief or concept first to enhance with reasoning');
        promptEl.focus();
        return;
      }
      enhanceBtn.disabled = true;
      const origBtnHTML = enhanceBtn.innerHTML;
      enhanceBtn.innerHTML = '<span>⏳ Director Reasoning...</span>';
      try {
        const res = await fetch(`${API}/api/image-engine/enhance-prompt`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: curPrompt,
            building_type: 'Architecture',
            architectural_style: 'Contemporary',
            mode: $('studioDesignMode')?.value || 'concept',
            protected_elements: ($('studioProtected')?.value || '').split(',').map(s=>s.trim()).filter(Boolean),
            materials: $('studioMaterials')?.value || '',
            lighting: $('studioLighting')?.value || ''
          })
        });
        if(res.ok){
          const data = await res.json();
          if(data.success && data.enhanced_prompt){
            _preEnhancedPrompt = curPrompt;
            _proposalSnapshot = { project: currentProject, workflow: wfSel.value, reference: _studioSelectedFile, mask: _studioSelectedMask, options: data.design_options };
            if($('studioRenderAlternatives')) $('studioRenderAlternatives').disabled = false;
            promptEl.value = data.enhanced_prompt;
            if(data.error) toast(data.error);

            // Render preserved constraints
            if(constraintsWrap){
              if(data.preserved_constraints && data.preserved_constraints.length){
                constraintsWrap.innerHTML = data.preserved_constraints.map(c => 
                  `<span class="studio-constraint-badge" title="Requested constraint — requires visual verification">Keep: ${_escHtml(c)}</span>`
                ).join('');
                constraintsWrap.style.display = 'flex';
              } else {
                constraintsWrap.style.display = 'none';
              }
            }

            // Render reasoning critique
            if(reasoningText){
              reasoningText.textContent = data.reasoning || 'Architectural Director reasoning applied.';
            }

            // Render design options
            if(designOptionsWrap && designOptionsList){
              if(data.design_options && data.design_options.length){
                designOptionsList.innerHTML = data.design_options.map((opt, idx) => `
                  <div class="studio-design-card ${idx === 0 ? 'active' : ''}" data-idx="${idx}" title="Click to apply this architectural scheme">
                    <div class="studio-design-card-title">
                      <span>${_escHtml(opt.title)}</span>
                    </div>
                    ${opt.style ? `<div class="studio-design-card-style">${_escHtml(opt.style)}</div>` : ''}
                    ${opt.rationale ? `<div style="font-size:12px;line-height:1.5;margin-top:8px">${_escHtml(opt.rationale)}</div>` : ''}
                    <div style="font-size:12px;line-height:1.6;margin-top:6px"><b>Materials:</b> ${_escHtml(opt.materials)}<br><b>Change:</b> ${_escHtml(opt.changes)}<br><b>Shading:</b> ${_escHtml(opt.shading_strategy)}</div>
                    <details style="font-size:11px;margin-top:8px"><summary>Review full rendering brief</summary><div style="white-space:pre-wrap;line-height:1.5">${_escHtml(opt.prompt)}</div></details>
                  </div>
                `).join('');
                designOptionsWrap.style.display = '';

                // Bind click events on design cards
                designOptionsList.querySelectorAll('.studio-design-card').forEach(card => {
                  card.onclick = () => {
                    designOptionsList.querySelectorAll('.studio-design-card').forEach(c => c.classList.remove('active'));
                    card.classList.add('active');
                    const idx = parseInt(card.getAttribute('data-idx'), 10);
                    const chosen = data.design_options[idx];
                    if(chosen && chosen.prompt){
                      promptEl.value = chosen.prompt;
                      toast(`Applied Scheme: ${chosen.title}`);
                    }
                  };
                });
              } else {
                designOptionsWrap.style.display = 'none';
              }
            }

            if(reasoningBox) reasoningBox.style.display = '';
            toast('Prompt director applied with design options');
          } else {
            toast('Reasoning enhancement returned standard prompt');
          }
        } else {
          toast('Reasoning service unavailable, using original prompt');
        }
      } catch(e){
        toast('Reasoning error: ' + (e.message || e));
      } finally {
        enhanceBtn.disabled = false;
        enhanceBtn.innerHTML = origBtnHTML;
      }
    };
  }

  if(revertLink && promptEl){
    revertLink.onclick = () => {
      if(_preEnhancedPrompt){
        promptEl.value = _preEnhancedPrompt;
        _preEnhancedPrompt = '';
        if(reasoningBox) reasoningBox.style.display = 'none';
        if(constraintsWrap) constraintsWrap.style.display = 'none';
        if(designOptionsWrap) designOptionsWrap.style.display = 'none';
        toast('Reverted to original brief');
      }
    };
  }

  const renderAlternatives = $('studioRenderAlternatives');
  if(renderAlternatives) renderAlternatives.onclick = async () => {
    const snapshot = _proposalSnapshot;
    if(!snapshot || snapshot.options.length !== 3){ toast('Develop three options first'); return; }
    if(snapshot.project !== currentProject || snapshot.workflow !== wfSel.value || snapshot.reference !== _studioSelectedFile || snapshot.mask !== _studioSelectedMask){ toast('Reference, mask or workflow changed. Develop the options again.'); return; }
    const wf = _studioWorkflows.find(w=>w.id===snapshot.workflow);
    const requiresImage = (wf.parameters || []).some(p=>p.type==='image' && p.required);
    if(requiresImage && !snapshot.reference){ toast('Upload the reference image first'); return; }
    const randomSeed = new Uint32Array(1); crypto.getRandomValues(randomSeed);
    const requestedSeed = $('studioSeed')?.value.trim();
    const seed = requestedSeed ? Number(requestedSeed) : randomSeed[0];
    if(!Number.isSafeInteger(seed) || seed<0){toast('Enter a valid seed');return;}
    const settings = {width:_studioSelectedAspect.width,height:_studioSelectedAspect.height,steps:Number($('studioSteps')?.value||20),cfg:Number($('studioCfg')?.value||5),seed};
    renderAlternatives.disabled = true;
    let submitted = 0;
    try {
      for(const option of snapshot.options){
        const payload = {project:snapshot.project,workflow_id:snapshot.workflow,prompt:option.prompt,...settings,enhance_prompt:false};
        let response;
        if(snapshot.reference){
          const form = new FormData();Object.entries(payload).forEach(([k,v])=>form.append(k,String(v)));
          form.append('input_image',snapshot.reference);
          if(snapshot.mask) form.append('edit_mask',snapshot.mask);
          response = await fetch(`${API}/api/image-engine/jobs`,{method:'POST',body:form});
        }else response = await fetch(`${API}/api/image-engine/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const result = await response.json();
        if(!response.ok) throw new Error(result.detail || 'Preview submission failed');
        submitted++;
      }
      toast(`Queued ${submitted} previews with the same seed ${seed}`);
    }catch(error){toast(`${submitted} previews queued; ${error.message}. Submitted jobs are retained.`);}
    finally{ renderAlternatives.disabled=submitted>0; await _loadStudioJobs(); _updateActiveJobUI(); }
  };

  // Aspect ratio buttons
  document.querySelectorAll('.studio-res-btn').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.studio-res-btn').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      _studioSelectedAspect = {
        width: parseInt(btn.dataset.w, 10) || 1024,
        height: parseInt(btn.dataset.h, 10) || 1024,
      };
    };
  });

  // Slider live indicators
  const stepsEl = $('studioSteps');
  if(stepsEl) stepsEl.oninput = () => { const v = $('studioStepsVal'); if(v) v.textContent = stepsEl.value; };
  const cfgEl = $('studioCfg');
  if(cfgEl) cfgEl.oninput = () => { const v = $('studioCfgVal'); if(v) v.textContent = parseFloat(cfgEl.value).toFixed(1); };

  // Cancel Job button
  const cancelBtn = $('studioCancelJobBtn');
  if(cancelBtn){
    cancelBtn.onclick = () => {
      if(_studioActiveJob) _cancelStudioJob(_studioActiveJob.job_id);
    };
  }

  // Refresh button
  const refreshBtn = $('studioRefreshBtn');
  if(refreshBtn){
    refreshBtn.onclick = () => {
      if(window._refreshStudio) window._refreshStudio();
    };
  }

  // Engine Start/Stop toggle button
  const engineToggleBtn = $('studioEngineToggleBtn');
  if(engineToggleBtn){
    engineToggleBtn.onclick = _toggleEngineService;
  }

  // Generate button
  const genBtn = $('studioGenBtn');
  if(genBtn){
    genBtn.onclick = async () => {
      if(!currentProject){ toast('Select a project first'); return; }
      const prompt = (promptEl ? promptEl.value : '').trim();
      if(!prompt){ toast('Please enter an architectural prompt'); if(promptEl) promptEl.focus(); return; }

      const wfId = wfSel ? wfSel.value : 'architecture_concept';
      const wf = _studioWorkflows.find(w => w.id === wfId);
      if(wf && (wf.parameters || []).some(p => p.type === 'image' && p.required) && !_studioSelectedFile){
        toast('This workflow requires a reference sketch or image');
        return;
      }

      genBtn.disabled = true;
      const genText = $('studioGenBtnText');
      if(genText) genText.textContent = 'Submitting Job…';

      const neg = ($('studioNegPrompt') ? $('studioNegPrompt').value : '').trim();
      const steps = parseInt((stepsEl ? stepsEl.value : '25'), 10) || 25;
      const cfg = parseFloat((cfgEl ? cfgEl.value : '7.0')) || 7.0;
      const seedVal = ($('studioSeed') ? $('studioSeed').value : '').trim();
      const seed = seedVal ? parseInt(seedVal, 10) : null;
      const autoEnhance = $('studioAutoEnhance') ? $('studioAutoEnhance').checked : true;

      try {
        let res;
        if(_studioSelectedFile){
          const fd = new FormData();
          fd.append('project', currentProject);
          fd.append('workflow_id', wfId);
          fd.append('prompt', prompt);
          if(neg) fd.append('negative_prompt', neg);
          fd.append('width', String(_studioSelectedAspect.width));
          fd.append('height', String(_studioSelectedAspect.height));
          fd.append('steps', String(steps));
          fd.append('cfg', String(cfg));
          if(seed !== null && !isNaN(seed)) fd.append('seed', String(seed));
          fd.append('input_image', _studioSelectedFile);
          if(_studioSelectedMask) fd.append('edit_mask', _studioSelectedMask);
          fd.append('enhance_prompt', String(autoEnhance));

          res = await fetch(`${API}/api/image-engine/jobs`, {
            method: 'POST',
            body: fd,
          });
        } else {
          const payload = {
            project: currentProject,
            workflow_id: wfId,
            prompt: prompt,
            negative_prompt: ($('studioNegPrompt')?.disabled ? null : neg || null),
            width: _studioSelectedAspect.width,
            height: _studioSelectedAspect.height,
            steps: steps,
            cfg: cfg,
            seed: (seed !== null && !isNaN(seed)) ? seed : null,
            enhance_prompt: autoEnhance,
          };
          res = await fetch(`${API}/api/image-engine/jobs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        }

        if(!res.ok){
          let detail = 'Submission failed (' + res.status + ')';
          try { const d = await res.json(); if(d.detail) detail = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail); } catch(_){}
          toast('Error: ' + detail);
          genBtn.disabled = false;
          if(genText) genText.textContent = 'Generate Concept';
          return;
        }

        const job = await res.json();
        _studioActiveJob = job;
        toast('Generation job queued: ' + job.job_id);
        _updateActiveJobUI();
        await _pollStudioStatus();
      } catch(err){
        toast('Submission network error: ' + err.message);
        genBtn.disabled = false;
        if(genText) genText.textContent = 'Generate Concept';
      }
    };
  }
}

async function _cancelStudioJob(jobId){
  if(!jobId) return;
  try {
    const res = await fetch(`${API}/api/image-engine/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    if(res.ok){
      toast('Job cancelled: ' + jobId);
      _studioActiveJob = null;
      await _pollStudioStatus();
      await _loadStudioJobs();
      _updateActiveJobUI();
      _renderStudioGallery();
    } else {
      let msg = 'Could not cancel';
      try { const d = await res.json(); if(d.detail) msg = d.detail; } catch(_){}
      toast(msg);
    }
  } catch(err){
    toast('Cancel error: ' + err.message);
  }
}

function _renderStudioGallery(){
  const container = $('studioGalleryContainer');
  if(!container) return;

  // Flatten all outputs with parent job info
  const items = [];
  (_studioJobs || []).forEach(job => {
    (job.outputs || []).forEach(out => {
      items.push({ output: out, job: job });
    });
  });

  const countEl = $('studioOutputCount');
  if(countEl) countEl.textContent = `${items.length} output${items.length === 1 ? '' : 's'}`;

  if(!items.length){
    container.innerHTML = `
      <div class="state" style="padding:48px 20px">
        <svg class="ico" viewBox="0 0 24 24" style="width:42px;height:42px;color:var(--faint)"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
        <div style="font-weight:600;font-size:13.5px">No generated concepts in this project yet</div>
        <div class="muted" style="font-size:12px">Write an architectural prompt and click "Generate Concept" to visualize ideas.</div>
      </div>
    `;
    return;
  }

  // Sort descending by created_at
  items.sort((a,b) => String(b.output.created_at||'').localeCompare(String(a.output.created_at||'')));

  container.innerHTML = `
    <div class="studio-gallery-grid" id="studioGalleryGrid">
      ${items.map((it, idx) => {
        const out = it.output;
        const job = it.job;
        const thumbUrl = `${API}/api/image-engine/outputs/${encodeURIComponent(out.output_id)}/thumb?token=${encodeURIComponent(authToken||'')}`;
        const fileUrl = `${API}/api/image-engine/outputs/${encodeURIComponent(out.output_id)}/file?token=${encodeURIComponent(authToken||'')}`;
        const downloadName = out.filename || `Architectural_Render_${out.width}x${out.height}.png`;
        const cat = job.workflow_id ? job.workflow_id.split('-')[0] : 'gen';
        const dateStr = (job.created_at || '').replace('T', ' ').slice(0, 16);
        return `
          <div class="studio-card" data-idx="${idx}">
            <div style="position:relative;overflow:hidden">
              <img class="studio-card-thumb" src="${thumbUrl}" alt="${esc(out.metadata?.prompt || "")}" loading="lazy">
              <a href="${fileUrl}" download="${esc(downloadName)}" class="studio-quick-download" title="Download Image" onclick="event.stopPropagation()">
                <svg viewBox="0 0 24 24" width="15" height="15" stroke="currentColor" stroke-width="2.2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              </a>
            </div>
            <div class="studio-card-info">
              <div class="studio-card-prompt">${esc(out.metadata?.prompt || "")}</div>
              <div class="studio-card-meta">
                <span>${out.width}×${out.height} · ${esc(dateStr)}</span>
                <span class="badge-s b-info">${esc(cat)}</span>
              </div>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;

  // Wire lightbox modal click
  container.querySelectorAll('.studio-card').forEach(card => {
    card.onclick = () => {
      const idx = parseInt(card.dataset.idx, 10);
      if(items[idx]){
        _openStudioLightbox(items[idx].output, items[idx].job);
      }
    };
  });
}

function _openStudioLightbox(out, job){
  let modal = $('studioModal');
  if(!modal){
    modal = el('div', 'studio-modal');
    modal.id = 'studioModal';
    document.body.appendChild(modal);
  }

  const fileUrl = `${API}/api/image-engine/outputs/${encodeURIComponent(out.output_id)}/file?token=${encodeURIComponent(authToken||'')}`;
  const dateStr = (job.created_at || '').replace('T', ' ').slice(0, 19);
  const downloadName = out.filename || `Architectural_Render_${out.width}x${out.height}.png`;
  const workflowName = job.workflow_id ? job.workflow_id.replace(/_/g, ' ') : 'Architecture Concept';

  modal.innerHTML = `
    <div class="studio-modal-card" id="studioModalCard">
      <!-- Floating Top Bar -->
      <div class="studio-modal-topbar">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="badge-s b-info" style="font-size:10px;text-transform:uppercase">${esc(workflowName)}</span>
          <span style="font-size:11px;color:#94a3b8;font-weight:500">${out.width} × ${out.height}</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <a href="${fileUrl}" download="${esc(downloadName)}" class="studio-lb-btn primary" id="studioLbDownloadBtn" title="Download High-Resolution Image">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.4" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>Download</span>
          </a>
          <button class="studio-lb-btn ghost" id="studioToggleDetails" title="Toggle prompt & details">
            ℹ️ Details
          </button>
          <button class="studio-lb-btn ghost" id="studioModalClose" title="Close (Esc)" style="padding:6px 11px;font-size:16px;line-height:1">
            ✕
          </button>
        </div>
      </div>

      <!-- Main Full Image View (Clean & professional with no side text!) -->
      <div class="studio-modal-imgwrap">
        <img src="${fileUrl}" alt="${esc(out.metadata?.prompt || "")}">
        <div class="studio-modal-caption">
          <span style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
            ${esc(out.metadata?.prompt || "")}
          </span>
        </div>
      </div>

      <!-- Collapsible Sliding Details Drawer (Hidden by default) -->
      <div class="studio-modal-drawer hidden" id="studioModalDrawer">
        <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,.1);padding-bottom:10px">
          <h4 style="margin:0;font-size:13px;font-weight:700;color:#f8fafc">Concept Details & Rationale</h4>
          <button class="iconbtn" id="studioCloseDrawer" title="Hide Details" style="font-size:16px">✕</button>
        </div>

        <div style="font-size:11.5px;line-height:1.5;background:rgba(255,255,255,.04);padding:10px 12px;border-radius:var(--r-sm);border:1px solid rgba(255,255,255,.08)">
          <div style="font-size:9.5px;font-weight:700;color:var(--faint);letter-spacing:.4px;margin-bottom:4px">GENERATION PROMPT</div>
          ${esc(out.metadata?.prompt || "")}
        </div>

        ${(out.metadata?.reasoning || job.reasoning) ? `
        <div style="font-size:11.5px;line-height:1.5;background:rgba(47,107,255,.08);padding:10px 12px;border-radius:var(--r-sm);border:1px solid rgba(47,107,255,.25)">
          <div style="font-size:9.5px;font-weight:700;color:var(--accent2);letter-spacing:.4px;margin-bottom:4px;display:flex;align-items:center;gap:4px">
            <span>💡 ARCHITECTURAL REASONING</span>
            <span class="badge-s b-info" style="font-size:8.5px">qwen3.5:9b</span>
          </div>
          ${esc(out.metadata?.reasoning || job.reasoning)}
        </div>
        ` : ''}

        ${(out.metadata?.original_prompt && out.metadata?.original_prompt !== out.metadata?.prompt) ? `
        <div style="font-size:11px;color:var(--muted)">
          <span style="font-weight:600">Original Brief:</span> "${esc(out.metadata.original_prompt)}"
        </div>
        ` : ''}

        <div style="font-size:11px;display:flex;flex-direction:column;gap:5px">
          <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span class="muted">Workflow</span><b>${esc(job.workflow_id)}</b></div>
          <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span class="muted">Resolution</span><b>${out.width} × ${out.height}</b></div>
          <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span class="muted">Steps / CFG</span><b>${out.metadata?.steps ?? 4} / CFG ${out.metadata?.cfg ?? 1.0}</b></div>
          <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span class="muted">Seed</span><b>${out.seed!=null?out.seed:'Unavailable'}</b></div>
          <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span class="muted">Generated</span><span>${esc(dateStr)}</span></div>
        </div>

        <div style="margin-top:auto;display:flex;flex-direction:column;gap:8px">
          <a href="${fileUrl}" download="${esc(downloadName)}" class="primary" style="display:flex;align-items:center;justify-content:center;gap:6px;text-decoration:none;padding:8px">
            📥 Download High-Res PNG
          </a>
          <button class="ghost" id="studioReusePrompt" style="padding:7px">📋 Reuse Prompt in Studio</button>
        </div>
      </div>
    </div>
  `;

  modal.style.display = 'flex';

  function closeModal(){
    modal.style.display = 'none';
    document.removeEventListener('keydown', handleKey);
  }

  function handleKey(e){
    if(e.key === 'Escape') closeModal();
  }

  const closeBtn = $('studioModalClose');
  if(closeBtn) closeBtn.onclick = closeModal;

  modal.onclick = e => {
    if(e.target === modal) closeModal();
  };

  document.addEventListener('keydown', handleKey);

  // Toggle details drawer
  const toggleBtn = $('studioToggleDetails');
  const drawer = $('studioModalDrawer');
  const closeDrawerBtn = $('studioCloseDrawer');

  if(toggleBtn && drawer){
    toggleBtn.onclick = (e) => {
      e.stopPropagation();
      drawer.classList.toggle('hidden');
    };
  }
  if(closeDrawerBtn && drawer){
    closeDrawerBtn.onclick = (e) => {
      e.stopPropagation();
      drawer.classList.add('hidden');
    };
  }

  const reuseBtn = $('studioReusePrompt');
  if(reuseBtn){
    reuseBtn.onclick = () => {
      const p = $('studioPrompt');
      if(p){
        p.value = out.metadata?.prompt || job.prompt || '';
        p.focus();
        const rBox = $('studioReasoningBox');
        const rText = $('studioReasoningText');
        const rVal = out.metadata?.reasoning || job.reasoning;
        if(rVal && rBox && rText){
          rText.textContent = rVal;
          rBox.style.display = '';
        }
      }
      closeModal();
      toast('Prompt copied to Studio prompt editor');
    };
  }
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
   AI VIDEO STUDIO (Wan 2.2 TI2V 5B)
   ============================================================ */
let _videoJobs = [];
let _videoEngineStatus = null;
let _videoPollTimer = null;
let _videoMode = 'i2v'; // 'i2v' = Image-to-Video, 't2v' = Text-to-Video
let _videoInputFile = null;
let _videoInputPreview = null;
let _activeHeroVideo = null;
let _videoCameraMotion = 'orbit';
let _videoRes = { width: 1280, height: 704 };
let _videoFrames = 49;
let _videoFps = 16;
let _videoSteps = 20;
let _videoCfg = 5.0;

const CAMERA_PRESETS = [
  { id: 'orbit', label: 'Orbit 360', icon: '🛸', prompt: 'Smooth 360-degree orbital camera rotation around the architectural facade, slow cinematic rotation', desc: 'Continuous exterior sweep' },
  { id: 'drone', label: 'Drone Aerial', icon: '✈️', prompt: 'Cinematic drone aerial fly-through descending slowly towards the building canopy and landscape', desc: 'High-altitude descent' },
  { id: 'walk', label: 'Walkthrough', icon: '🚶', prompt: 'Eye-level cinematic forward walkthrough entering the architectural pavilion, steady glide', desc: 'Ground entrance push' },
  { id: 'dolly', label: 'Dolly Pan', icon: '➡️', prompt: 'Smooth horizontal lateral dolly pan tracking across facade louvers and glass curtain walls', desc: 'Horizontal reveal' },
  { id: 'crane', label: 'Crane Rise', icon: '⬆️', prompt: 'Vertical crane pedestal shot rising gracefully from courtyard reflection pool to rooftop terrace', desc: 'Vertical ascent' },
  { id: 'zoom', label: 'Slow Reveal', icon: '🔍', prompt: 'Slow dramatic cinematic zoom-in revealing intricate material textures, sun reflection, and ambient light', desc: 'Focus on fine details' },
];

const ATMOSPHERE_PRESETS = [
  { label: 'Golden Hour Flare', text: 'dramatic golden hour sunset, warm sunlight glint on glass facade, long soft shadows' },
  { label: 'Twilight Uplighting', text: 'dusk twilight ambiance, warm architectural uplighting on structural columns, glowing interior' },
  { label: 'Moving Cloud Shadows', text: 'dynamic time-lapse sky, soft shifting cloud shadows sweeping over building volume' },
  { label: 'Rainy Reflections', text: 'subtle drizzle, glossy wet pavement reflections, moody cinematic architectural atmosphere' },
  { label: 'Biophilic Breeze', text: 'gentle breeze rustling lush landscaped terraces, soft water ripples in courtyard pool' },
];

async function _loadVideoJobs(){
  if(!currentProject) return;
  try {
    const r = await fetch(`${API}/api/image-engine/jobs?project=${encodeURIComponent(currentProject)}&limit=50`);
    if(r.ok){
      const all = await r.json();
      _videoJobs = all.filter(j => j.workflow_id && j.workflow_id.includes('video'));
    }
  } catch(e){
    _videoJobs = [];
  }
}

async function _fetchVideoStatus(){
  try {
    const r = await fetch(`${API}/api/image-engine/video/status`);
    if(r.ok){
      _videoEngineStatus = await r.json();
      return _videoEngineStatus;
    }
  } catch(e){}
  _videoEngineStatus = null;
  return null;
}

async function renderVideoStudio(b){
  if(_videoPollTimer){ clearInterval(_videoPollTimer); _videoPollTimer = null; }
  if(!currentProject){
    b.innerHTML = `<div class="ws-scroll">${state('Select a project first to use the AI Video Studio.')}</div>`;
    return;
  }

  b.innerHTML = `<div class="ws-scroll" id="videoLoading">${state('Connecting to Wan 2.2 Video Engine…','load')}</div>`;

  await Promise.all([_loadVideoJobs(), _fetchVideoStatus()]);

  const isReady = _videoEngineStatus && _videoEngineStatus.ready;
  const isEngineOnline = _videoEngineStatus && _videoEngineStatus.engine_available;
  const deviceName = _videoEngineStatus ? (_videoEngineStatus.device || 'NVIDIA RTX 5080') : 'RTX 5080';
  const vramFree = _videoEngineStatus && _videoEngineStatus.vram_free_mb ? `${Math.round(_videoEngineStatus.vram_free_mb / 1024)}GB VRAM Free` : '16GB VRAM';

  // Determine latest completed output to display in Hero player
  if(!_activeHeroVideo && _videoJobs.length){
    for(const j of _videoJobs){
      if(j.status === 'completed' && j.outputs && j.outputs.length){
        _activeHeroVideo = { job: j, output: j.outputs[0] };
        break;
      }
    }
  }

  b.innerHTML = `
    <div class="studio-layout">
      <!-- SIDEBAR CONTROLS -->
      <div class="studio-sidebar" id="videoSidebar">
        <div style="font-size:13px;font-weight:700;display:flex;align-items:center;gap:7px;margin-bottom:6px">
          <svg class="ico" viewBox="0 0 24 24" style="color:var(--accent);width:18px;height:18px"><polygon points="23 7 16 12 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
          Architectural Video Studio
        </div>
        <div style="font-size:11px;color:var(--muted);line-height:1.4;margin-bottom:12px">
          Generate cinematic architectural flythroughs, camera pans, and walkthroughs using <b>Wan 2.2 TI2V 5B</b>.
        </div>

        <!-- Mode Tabs -->
        <div class="video-mode-tabs">
          <button type="button" class="video-mode-tab ${_videoMode==='i2v'?'active':''}" id="vTabI2V">
            🎬 Image to Video
          </button>
          <button type="button" class="video-mode-tab ${_videoMode==='t2v'?'active':''}" id="vTabT2V">
            ✍️ Text to Video
          </button>
        </div>

        <!-- Reference Image Dropzone (for Image to Video) -->
        <div class="studio-field" id="videoDropzoneWrap" style="${_videoMode==='t2v'?'display:none':''}">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <label>Initial Frame / Render</label>
            <button type="button" class="studio-enhance-btn" id="vGrab3dBtn" style="padding:2px 8px;font-size:10.5px" title="Capture current 3D viewport canvas as start frame">
              <span>📸 Grab 3D View</span>
            </button>
          </div>
          <div class="studio-dropzone" id="videoDropzone" style="${_videoInputPreview?'display:none':''}">
            <div id="videoDropzoneContent">
              <svg class="ico" viewBox="0 0 24 24" style="width:26px;height:26px;margin:0 auto 6px;color:var(--faint)"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
              <div style="font-size:12px;font-weight:600">Drop starting frame or render</div>
              <div style="font-size:10.5px;color:var(--faint);margin-top:2px">or click to browse</div>
            </div>
            <input type="file" id="videoFileInput" accept="image/png,image/jpeg,image/webp">
          </div>
          <div class="studio-preview-wrap" id="videoPreviewWrap" style="${_videoInputPreview?'display:block':'display:none'}">
            <img id="videoPreviewImg" src="${_videoInputPreview||''}" alt="Initial Frame">
            <button class="studio-preview-remove" id="videoPreviewRemove" title="Remove start frame">×</button>
          </div>
          <div style="font-size:10.5px;color:var(--faint);margin-top:3px">
            Wan 2.2 will preserve building geometry and materials while smoothly animating camera motion and atmospheric lighting.
          </div>
        </div>

        <!-- Camera Motion Presets -->
        <div class="studio-field">
          <label>Camera Trajectory Preset</label>
          <div class="video-camera-grid">
            ${CAMERA_PRESETS.map(c => `
              <div class="video-camera-btn ${c.id===_videoCameraMotion?'active':''}" data-cam="${c.id}" data-prompt="${esc(c.prompt)}">
                <div class="video-camera-btn-title"><span>${c.icon}</span> ${esc(c.label)}</div>
                <div class="video-camera-btn-desc">${esc(c.desc)}</div>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- Prompt Field -->
        <div class="studio-field">
          <label for="videoPrompt">Animation Brief</label>
          <textarea class="studio-textarea" id="videoPrompt" placeholder="Describe the scene, camera movement, light dynamics, reflection ripples, and atmosphere..."></textarea>
          
          <div style="font-size:10px;font-weight:700;color:var(--faint);letter-spacing:.4px;margin-top:4px">ATMOSPHERE & LIGHTING PRESETS</div>
          <div class="studio-chips" id="videoAtmosChips">
            ${ATMOSPHERE_PRESETS.map(a => `<span class="studio-chip" data-text="${esc(a.text)}">${esc(a.label)}</span>`).join('')}
          </div>
        </div>

        <!-- Negative Prompt -->
        <details class="studio-details">
          <summary>Negative Motion Filter</summary>
          <div style="margin-top:8px" class="studio-field">
            <input class="studio-input" id="videoNegPrompt" value="jitter, strobe, flickering, sudden jerk, distorted geometry, warped structural pillars, blurry, noisy artifacts, watermarks">
          </div>
        </details>

        <!-- Video Parameters -->
        <div class="studio-field">
          <label for="videoResSel">Format & Aspect Ratio</label>
          <select class="studio-select" id="videoResSel">
            <option value="1280x704" selected>16:9 Landscape (1280x704) — Recommended 720p</option>
            <option value="704x1280">9:16 Vertical Reel (704x1280) — Mobile Presentation</option>
            <option value="832x480">16:9 Fast Preview (832x480) — Rapid Test</option>
          </select>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <div class="studio-field">
            <label for="videoFramesSel">Duration</label>
            <select class="studio-select" id="videoFramesSel">
              <option value="49" selected>3 seconds (49 frames)</option>
              <option value="81">5 seconds (81 frames)</option>
            </select>
          </div>
          <div class="studio-field">
            <label for="videoFpsSel">Frame Rate</label>
            <select class="studio-select" id="videoFpsSel">
              <option value="16" selected>16 fps (Cinematic)</option>
              <option value="24">24 fps (Smooth)</option>
            </select>
          </div>
        </div>

        <!-- Sampling Settings -->
        <details class="studio-details">
          <summary>Diffusion Sampling & Seed</summary>
          <div style="margin-top:10px;display:flex;flex-direction:column;gap:10px">
            <div class="studio-slider-row">
              <span style="width:75px">Steps: <b id="videoStepsVal">20</b></span>
              <input type="range" id="videoSteps" min="10" max="35" step="1" value="20">
            </div>
            <div class="studio-slider-row">
              <span style="width:75px">CFG: <b id="videoCfgVal">5.0</b></span>
              <input type="range" id="videoCfg" min="1.0" max="10.0" step="0.5" value="5.0">
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <input type="number" class="studio-input" id="videoSeed" placeholder="Random seed" style="flex:1" disabled>
              <label style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--muted);cursor:pointer;white-space:nowrap">
                <input type="checkbox" id="videoRandomSeed" checked> Random
              </label>
            </div>
          </div>
        </details>

        <!-- Generate Button -->
        <button type="button" class="primary" id="videoGenBtn" style="padding:11px 16px;font-size:13px;font-weight:700;margin-top:14px;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:0 4px 14px rgba(47,107,255,.35)">
          <svg class="ico" viewBox="0 0 24 24" style="width:16px;height:16px"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          Generate Cinematic Video
        </button>

        <!-- Progress Card -->
        <div class="studio-progress-card" id="videoProgressCard" style="display:none;margin-top:12px">
          <div class="studio-progress-h">
            <span style="font-size:11.5px;font-weight:700" id="videoProgressLabel">Synthesizing frames…</span>
            <span style="font-size:11.5px;color:var(--accent2);font-weight:700" id="videoProgressPct">0%</span>
          </div>
          <div class="studio-pbar" style="margin-top:7px">
            <div class="studio-pbar-fill" id="videoPbarFill" style="width:0%"></div>
          </div>
          <div style="font-size:10px;color:var(--muted);margin-top:5px;display:flex;justify-content:space-between">
            <span id="videoProgressStep">Diffusion latent sampling…</span>
            <a href="javascript:void(0)" id="videoCancelBtn" style="color:var(--red);text-decoration:none">Cancel</a>
          </div>
        </div>
      </div>

      <!-- MAIN AREA: HERO PLAYER + REEL GALLERY -->
      <div class="studio-main" id="videoMainArea">
        <!-- Top Status Bar -->
        <div class="studio-status-bar" style="margin-bottom:14px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span class="video-badge accent">Wan 2.2 TI2V 5B</span>
            <span class="video-badge">${esc(deviceName)}</span>
            <span class="video-badge">${esc(vramFree)}</span>
            <div class="studio-pill ${isReady?'online':(isEngineOnline?'warn':'offline')}" id="videoStatusPill" style="cursor:pointer" title="Click to view model status & download manager">
              <span class="studio-pill-dot"></span>
              ${isReady ? 'Wan 2.2 Ready' : (isEngineOnline ? '⚡ Wan 2.2 Weights Setup' : 'ComfyUI Offline')}
            </div>
          </div>
          <button type="button" class="studio-enhance-btn" id="videoModelMgrBtn" style="padding:4px 10px;font-size:11px">
            <span>⚙️ Model Weights & Setup</span>
          </button>
        </div>

        <!-- HERO VIDEO PLAYER -->
        <div id="videoHeroContainer">
          ${_renderHeroPlayerHtml(_activeHeroVideo)}
        </div>

        <!-- PROJECT VIDEO TAKES REEL -->
        <div style="margin-top:22px">
          <div class="dt-toolbar">
            <b>Project Video Takes (<span id="videoCountLabel">${_videoJobs.filter(j=>j.outputs&&j.outputs.length).length}</span>)</b>
            <span style="font-size:11px;color:var(--muted);margin-left:auto">Click any take to play in high-definition viewer</span>
          </div>
          <div class="studio-gallery-grid" id="videoGalleryGrid">
            ${_renderVideoGalleryHtml()}
          </div>
        </div>
      </div>
    </div>
  `;

  _wireVideoEvents(b);
}

function _renderHeroPlayerHtml(item){
  if(!item || !item.output){
    return `
      <div class="video-hero-player-wrap" style="padding:46px 20px;text-align:center;background:radial-gradient(ellipse at center, rgba(47,107,255,.07) 0%, #040711 70%)">
        <svg class="ico" viewBox="0 0 24 24" style="width:48px;height:48px;margin:0 auto 14px;color:var(--faint)"><polygon points="23 7 16 12 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
        <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:6px">No video take loaded</div>
        <p style="font-size:12px;color:var(--muted);max-width:480px;margin:0 auto 16px;line-height:1.5">
          Select an architectural camera preset and click <b>Generate Cinematic Video</b> on the left, or click a previously rendered take from the reel below.
        </p>
      </div>
    `;
  }

  const o = item.output;
  const j = item.job || {};
  const meta = o.metadata || {};
  const videoUrl = `${API}/api/image-engine/outputs/${esc(o.output_id)}/file`;
  const promptText = meta.original_prompt || meta.prompt || j.prompt || 'Architectural animation';

  return `
    <div class="video-hero-player-wrap">
      <div class="video-hero-player-bar">
        <div style="display:flex;align-items:center;gap:8px;overflow:hidden">
          <span style="font-size:12px;font-weight:700;color:#fff;white-space:nowrap">🎬 Active Take:</span>
          <span style="font-size:11.5px;color:var(--accent2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(promptText)}</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
          <span class="video-badge accent">${o.width}×${o.height}</span>
          <span class="video-badge">${meta.fps||16} FPS</span>
          <span class="video-badge">${meta.frames||49} Frames</span>
        </div>
      </div>

      <video id="videoHero" class="video-hero-player" controls autoplay loop playsinline preload="auto">
        <source src="${videoUrl}" type="video/mp4">
        Your browser does not support the video tag.
      </video>

      <div class="video-hero-footer">
        <div style="display:flex;align-items:center;gap:6px">
          <span style="font-size:11px;color:var(--muted)">Playback:</span>
          <button type="button" class="tb" style="padding:3px 8px;font-size:10.5px" onclick="document.getElementById('videoHero').playbackRate=0.5">0.5x</button>
          <button type="button" class="tb on" style="padding:3px 8px;font-size:10.5px" onclick="document.getElementById('videoHero').playbackRate=1.0">1.0x</button>
          <button type="button" class="tb" style="padding:3px 8px;font-size:10.5px" onclick="document.getElementById('videoHero').playbackRate=1.5">1.5x</button>
          <button type="button" class="tb" style="padding:3px 8px;font-size:10.5px" onclick="document.getElementById('videoHero').requestFullscreen()">⛶ Fullscreen</button>
        </div>

        <div style="display:flex;align-items:center;gap:8px;margin-left:auto">
          ${o.seed!=null ? `<span class="video-badge" style="font-family:monospace;font-size:10px">Seed: ${o.seed}</span>` : ''}
          <a class="primary" href="${videoUrl}" download="${esc(o.filename)}" style="text-decoration:none;padding:5px 12px;font-size:11px;font-weight:700;display:inline-flex;align-items:center;gap:6px">
            <svg class="ico" viewBox="0 0 24 24" style="width:13px;height:13px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Download MP4
          </a>
        </div>
      </div>
    </div>
  `;
}

function _renderVideoGalleryHtml(){
  const completedJobs = _videoJobs.filter(j => j.status === 'completed' && j.outputs && j.outputs.length);
  if(!completedJobs.length){
    return `<div style="grid-column:1/-1">${state('No architectural video takes generated yet for this project.')}</div>`;
  }

  return completedJobs.flatMap(j => (j.outputs || []).map(o => {
    const meta = o.metadata || {};
    const thumbUrl = o.thumbnail_url ? `${API}${o.thumbnail_url}` : `${API}/api/image-engine/outputs/${o.output_id}/thumb`;
    const promptText = meta.original_prompt || meta.prompt || j.prompt || 'Architectural animation';
    const isHero = _activeHeroVideo && _activeHeroVideo.output && _activeHeroVideo.output.output_id === o.output_id;

    return `
      <div class="studio-card video-card ${isHero?'on':''}" style="cursor:pointer;position:relative" data-job-id="${esc(j.job_id)}" data-output-id="${esc(o.output_id)}">
        <div style="position:relative;aspect-ratio:16/9;background:#050811;overflow:hidden">
          <img class="studio-card-thumb" src="${thumbUrl}" alt="Take" style="aspect-ratio:16/9;object-fit:cover;width:100%;height:100%" onerror="this.src='/ui/favicon.svg'">
          <div class="video-card-play-icon">
            <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>
          </div>
          <div style="position:absolute;bottom:6px;left:6px">
            <span class="video-badge" style="background:rgba(0,0,0,.75);font-size:9.5px;padding:2px 6px">🎬 ${o.width}×${o.height}</span>
          </div>
        </div>
        <div class="studio-card-info" style="padding:8px 10px">
          <div class="studio-card-prompt" style="font-size:11.5px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${esc(promptText)}</div>
          <div class="studio-card-meta" style="margin-top:4px;display:flex;justify-content:space-between;align-items:center">
            <span>${j.completed_at ? new Date(j.completed_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}) : 'Generated'}</span>
            <span style="color:var(--accent2);font-weight:600">${meta.frames||49}f · ${meta.fps||16}fps</span>
          </div>
        </div>
      </div>
    `;
  })).join('');
}

function _wireVideoEvents(b){
  // Mode tabs
  $('vTabI2V').onclick = () => {
    _videoMode = 'i2v';
    $('vTabI2V').classList.add('active');
    $('vTabT2V').classList.remove('active');
    $('videoDropzoneWrap').style.display = 'block';
  };
  $('vTabT2V').onclick = () => {
    _videoMode = 't2v';
    $('vTabT2V').classList.add('active');
    $('vTabI2V').classList.remove('active');
    $('videoDropzoneWrap').style.display = 'none';
  };

  // Dropzone events
  const dropzone = $('videoDropzone');
  const fileInput = $('videoFileInput');
  dropzone.onclick = () => fileInput.click();
  fileInput.onchange = (e) => {
    if(e.target.files && e.target.files[0]) _handleVideoFile(e.target.files[0]);
  };
  dropzone.ondragover = (e) => { e.preventDefault(); dropzone.classList.add('dragover'); };
  dropzone.ondragleave = () => dropzone.classList.remove('dragover');
  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if(e.dataTransfer.files && e.dataTransfer.files[0]) _handleVideoFile(e.dataTransfer.files[0]);
  };
  $('videoPreviewRemove').onclick = () => {
    _videoInputFile = null;
    _videoInputPreview = null;
    $('videoPreviewWrap').style.display = 'none';
    $('videoDropzone').style.display = 'block';
    fileInput.value = '';
  };

  // Grab from 3D viewport
  $('vGrab3dBtn').onclick = () => {
    try {
      const frame = $('viewerFrame');
      if(frame && frame.contentWindow){
        const canvas = frame.contentWindow.document.querySelector('canvas');
        if(canvas){
          canvas.toBlob(blob => {
            if(blob){
              const f = new File([blob], `viewport_${Date.now()}.png`, { type: 'image/png' });
              _handleVideoFile(f);
              toast('Captured 3D viewport camera view as starting frame!');
            }
          }, 'image/png');
          return;
        }
      }
    } catch(err){}
    toast('No active 3D model canvas in view. Upload a render file directly.');
  };

  // Camera presets
  document.querySelectorAll('.video-camera-btn').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.video-camera-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _videoCameraMotion = btn.dataset.cam;
      const promptEl = $('videoPrompt');
      if(!promptEl.value.trim()){
        promptEl.value = btn.dataset.prompt;
      }
    };
  });

  // Atmosphere chips
  $('videoAtmosChips').querySelectorAll('.studio-chip').forEach(chip => {
    chip.onclick = () => {
      const p = $('videoPrompt');
      const text = chip.dataset.text;
      if(!p.value.includes(text)){
        p.value = p.value.trim() ? `${p.value.trim()}, ${text}` : text;
      }
    };
  });

  // Resolution
  $('videoResSel').onchange = (e) => {
    const [w, h] = e.target.value.split('x').map(Number);
    _videoRes = { width: w, height: h };
  };

  // Sliders
  $('videoSteps').oninput = (e) => {
    _videoSteps = Number(e.target.value);
    $('videoStepsVal').textContent = _videoSteps;
  };
  $('videoCfg').oninput = (e) => {
    _videoCfg = Number(e.target.value);
    $('videoCfgVal').textContent = _videoCfg.toFixed(1);
  };
  $('videoRandomSeed').onchange = (e) => {
    $('videoSeed').disabled = e.target.checked;
    if(e.target.checked) $('videoSeed').value = '';
  };

  // Generate button
  $('videoGenBtn').onclick = _submitVideoJob;

  // Model setup modal openers
  $('videoStatusPill').onclick = openVideoModelModal;
  $('videoModelMgrBtn').onclick = openVideoModelModal;

  // Reel card clicks -> load in hero
  document.querySelectorAll('.video-card').forEach(card => {
    card.onclick = () => {
      const jId = card.dataset.jobId;
      const oId = card.dataset.outputId;
      const job = _videoJobs.find(j => j.job_id === jId);
      if(job && job.outputs){
        const out = job.outputs.find(o => o.output_id === oId) || job.outputs[0];
        _activeHeroVideo = { job, output: out };
        $('videoHeroContainer').innerHTML = _renderHeroPlayerHtml(_activeHeroVideo);
        document.querySelectorAll('.video-card').forEach(c => c.classList.toggle('on', c.dataset.outputId === oId));
        $('videoHero').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    };
  });
}

function _handleVideoFile(file){
  if(!file.type.startsWith('image/')){
    toast('Please select a valid image file (PNG, JPG, WEBP).');
    return;
  }
  _videoInputFile = file;
  const reader = new FileReader();
  reader.onload = (e) => {
    _videoInputPreview = e.target.result;
    $('videoPreviewImg').src = _videoInputPreview;
    $('videoPreviewWrap').style.display = 'block';
    $('videoDropzone').style.display = 'none';
  };
  reader.readAsDataURL(file);
}

async function _submitVideoJob(){
  const prompt = $('videoPrompt').value.trim();
  if(!prompt){
    toast('Please enter an architectural animation prompt.');
    $('videoPrompt').focus();
    return;
  }

  if(_videoMode === 'i2v' && !_videoInputFile){
    toast('Image-to-Video requires an initial frame. Upload an image or switch to Text-to-Video.');
    return;
  }

  const negPrompt = $('videoNegPrompt').value.trim();
  const frames = Number($('videoFramesSel').value) || 49;
  const fps = Number($('videoFpsSel').value) || 16;
  const isRandSeed = $('videoRandomSeed').checked;
  const seed = isRandSeed ? Math.floor(Math.random() * 1000000000) : (Number($('videoSeed').value) || 42);

  // Show progress UI
  $('videoProgressCard').style.display = 'block';
  $('videoProgressPct').textContent = '0%';
  $('videoPbarFill').style.width = '0%';
  $('videoProgressLabel').textContent = 'Queuing video job…';
  $('videoProgressStep').textContent = 'Allocating RTX 5080 resources…';
  $('videoGenBtn').disabled = true;

  try {
    let jobId = null;

    if(_videoMode === 'i2v' && _videoInputFile){
      const form = new FormData();
      form.append('project', currentProject);
      form.append('workflow_id', 'video_wan2_2_5b');
      form.append('prompt', prompt);
      if(negPrompt) form.append('negative_prompt', negPrompt);
      form.append('camera_motion', _videoCameraMotion);
      form.append('width', String(_videoRes.width));
      form.append('height', String(_videoRes.height));
      form.append('steps', String(_videoSteps));
      form.append('cfg', String(_videoCfg));
      form.append('frames', String(frames));
      form.append('fps', String(fps));
      form.append('seed', String(seed));
      form.append('image_file', _videoInputFile);

      const r = await fetch(`${API}/api/image-engine/submit-multipart`, {
        method: 'POST',
        body: form
      });
      if(!r.ok){
        const err = await r.json().catch(()=>({}));
        throw new Error(err.detail || `Server returned HTTP ${r.status}`);
      }
      const st = await r.json();
      jobId = st.job_id;
    } else {
      // Text-to-Video mode
      const payload = {
        project: currentProject,
        workflow_id: 'video_wan2_2_5b',
        prompt: prompt,
        negative_prompt: negPrompt || undefined,
        camera_motion: _videoCameraMotion,
        width: _videoRes.width,
        height: _videoRes.height,
        steps: _videoSteps,
        cfg: _videoCfg,
        frames: frames,
        fps: fps,
        seed: seed
      };

      const r = await fetch(`${API}/api/image-engine/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if(!r.ok){
        const err = await r.json().catch(()=>({}));
        throw new Error(err.detail || `Server returned HTTP ${r.status}`);
      }
      const st = await r.json();
      jobId = st.job_id;
    }

    _pollVideoJob(jobId);
  } catch(exc){
    $('videoProgressCard').style.display = 'none';
    $('videoGenBtn').disabled = false;
    toast(`Video generation failed: ${exc.message}`);
  }
}

function _pollVideoJob(jobId){
  if(_videoPollTimer){ clearInterval(_videoPollTimer); _videoPollTimer = null; }

  $('videoCancelBtn').onclick = async () => {
    try {
      await fetch(`${API}/api/image-engine/jobs/${jobId}/cancel`, { method: 'POST' });
      toast('Video generation canceled.');
    } catch(e){}
    clearInterval(_videoPollTimer);
    $('videoProgressCard').style.display = 'none';
    $('videoGenBtn').disabled = false;
  };

  _videoPollTimer = setInterval(async () => {
    try {
      const r = await fetch(`${API}/api/image-engine/jobs/${jobId}`);
      if(!r.ok) return;
      const st = await r.json();

      const pct = Math.max(0, Math.min(100, st.progress_percent || 0));
      $('videoProgressPct').textContent = `${pct}%`;
      $('videoPbarFill').style.width = `${pct}%`;

      if(st.current_step && st.total_steps){
        $('videoProgressStep').textContent = `Sampling step ${st.current_step} / ${st.total_steps}`;
      } else if(st.status === 'queued'){
        $('videoProgressStep').textContent = 'Waiting in ComfyUI queue…';
      } else {
        $('videoProgressStep').textContent = 'Wan 2.2 TI2V 5B generating video tensors…';
      }

      if(st.status === 'completed'){
        clearInterval(_videoPollTimer);
        _videoPollTimer = null;
        $('videoProgressCard').style.display = 'none';
        $('videoGenBtn').disabled = false;
        toast('🎉 Architectural video generated successfully!');

        await _loadVideoJobs();
        if(st.outputs && st.outputs.length){
          _activeHeroVideo = { job: st, output: st.outputs[0] };
          $('videoHeroContainer').innerHTML = _renderHeroPlayerHtml(_activeHeroVideo);
        }
        $('videoGalleryGrid').innerHTML = _renderVideoGalleryHtml();
        $('videoCountLabel').textContent = _videoJobs.filter(j=>j.outputs&&j.outputs.length).length;
        _wireVideoEvents(document);
      } else if(st.status === 'failed'){
        clearInterval(_videoPollTimer);
        _videoPollTimer = null;
        $('videoProgressCard').style.display = 'none';
        $('videoGenBtn').disabled = false;
        toast(`Video job failed: ${st.error || 'Check ComfyUI logs'}`);
      }
    } catch(err){}
  }, 1500);
}

async function openVideoModelModal(){
  const st = await _fetchVideoStatus();
  const models = st ? st.models : {};
  const isReady = st && st.ready;
  const isOnline = st && st.engine_available;
  const dlState = st && st.download_state ? st.download_state : {};

  const modal = el('div', 'studio-modal', `
    <div class="studio-modal-card" style="max-width:680px;padding:24px;border-radius:12px;display:flex;flex-direction:column;gap:16px">
      <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);padding-bottom:12px">
        <div style="display:flex;align-items:center;gap:8px">
          <svg class="ico" viewBox="0 0 24 24" style="color:var(--accent);width:20px;height:20px"><polygon points="23 7 16 12 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
          <span style="font-size:15px;font-weight:700">Wan 2.2 TI2V 5B Model Weights Manager</span>
        </div>
        <button class="tb" id="vModalClose" style="padding:4px 8px;font-size:14px">×</button>
      </div>

      <div style="font-size:12px;color:var(--muted);line-height:1.5">
        To run Wan 2.2 Text/Image-to-Video locally on your <b>RTX 5080 (16GB VRAM)</b>, ComfyUI requires three model weight files. The system checks their presence in <code>C:\\3EH\\ComfyUI\\models</code>.
      </div>

      <div style="display:flex;flex-direction:column;gap:10px">
        ${Object.entries(models).map(([k, m]) => `
          <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px 14px;display:flex;align-items:center;justify-content:space-between">
            <div>
              <div style="font-size:12.5px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:6px">
                <span>${m.present ? '✅' : '⏳'}</span>
                ${esc(m.label)}
              </div>
              <div style="font-size:10.5px;color:var(--muted);margin-top:2px">
                File: <code>${esc(m.filename)}</code> · Size: ~${m.size_gb} GB · Target: <code>${esc(m.folder)}/</code>
              </div>
            </div>
            <div>
              ${m.present ? '<span class="video-badge green">Installed</span>' : '<span class="video-badge warn">Not Downloaded</span>'}
            </div>
          </div>
        `).join('')}
      </div>

      <!-- Download status or trigger -->
      <div id="vDlProgressSection" style="${dlState.active ? 'display:block' : 'display:none'};background:rgba(47,107,255,.08);border:1px solid rgba(47,107,255,.25);border-radius:8px;padding:12px">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;font-weight:700">
          <span id="vDlFileLabel">Downloading ${esc(dlState.current_file||'weights')}…</span>
          <span id="vDlPctLabel" style="color:var(--accent2)">${dlState.percent||0}%</span>
        </div>
        <div class="studio-pbar" style="margin-top:6px">
          <div class="studio-pbar-fill" id="vDlPbarFill" style="width:${dlState.percent||0}%"></div>
        </div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px" id="vDlSpeedLabel">
          Speed: ${dlState.speed_mbps||0} MB/s
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:10px;margin-top:4px">
        ${!isReady ? `
          <button type="button" class="primary" id="vStartDlBtn" style="padding:9px 16px;font-size:12px;font-weight:700;display:inline-flex;align-items:center;gap:6px" ${dlState.active?'disabled':''}>
            <svg class="ico" viewBox="0 0 24 24" style="width:14px;height:14px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            ${dlState.active ? 'Downloading in Background…' : 'Start Automatic Background Download (~16.8 GB)'}
          </button>
        ` : `
          <div class="video-badge green" style="padding:6px 14px;font-size:12px">
            ✨ All Wan 2.2 model weights are installed and ready for inference!
          </div>
        `}
      </div>

      <details class="studio-details" style="margin-top:8px">
        <summary>Manual Download Terminal Commands (Alternative)</summary>
        <div style="margin-top:8px;font-size:11px;color:var(--text);line-height:1.6">
          If you prefer downloading directly via PowerShell terminal:
          <pre style="background:#02050e;border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:10.5px;color:#38bdf8;overflow-x:auto;margin-top:4px">
# 1. Diffusion Model (9.31 GB)
curl.exe -L "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors" -o "C:\\3EH\\ComfyUI\\models\\diffusion_models\\wan2.2_ti2v_5B_fp16.safetensors"

# 2. Text Encoder UMT5-XXL FP8 (6.27 GB)
curl.exe -L "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" -o "C:\\3EH\\ComfyUI\\models\\text_encoders\\umt5_xxl_fp8_e4m3fn_scaled.safetensors"

# 3. VAE (1.31 GB)
curl.exe -L "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors" -o "C:\\3EH\\ComfyUI\\models\\vae\\wan2.2_vae.safetensors"</pre>
        </div>
      </details>
    </div>
  `);

  document.body.appendChild(modal);

  $('vModalClose').onclick = () => modal.remove();
  modal.onclick = (e) => { if(e.target === modal) modal.remove(); };

  const startBtn = $('vStartDlBtn');
  if(startBtn){
    startBtn.onclick = async () => {
      startBtn.disabled = true;
      startBtn.textContent = 'Starting download task…';
      try {
        const r = await fetch(`${API}/api/image-engine/video/download-weights`, { method: 'POST' });
        if(r.ok){
          toast('Background weight download started.');
          $('vDlProgressSection').style.display = 'block';
          // Poll download progress
          const dlTimer = setInterval(async () => {
            const fresh = await _fetchVideoStatus();
            const curState = fresh ? fresh.download_state : null;
            if(curState){
              $('vDlFileLabel').textContent = `Downloading ${esc(curState.current_file || 'weights')}…`;
              $('vDlPctLabel').textContent = `${curState.percent || 0}%`;
              $('vDlPbarFill').style.width = `${curState.percent || 0}%`;
              $('vDlSpeedLabel').textContent = `Speed: ${curState.speed_mbps || 0} MB/s · ${curState.status}`;
              if(!curState.active){
                clearInterval(dlTimer);
                if(curState.status === 'completed'){
                  toast('🎉 All Wan 2.2 model weights downloaded successfully!');
                  modal.remove();
                  renderVideoStudio($('genericWrap'));
                } else if(curState.status === 'failed'){
                  toast(`Download failed: ${curState.error}`);
                  startBtn.disabled = false;
                  startBtn.textContent = 'Retry Download';
                }
              }
            }
          }, 2000);
        }
      } catch(err){
        startBtn.disabled = false;
        startBtn.textContent = 'Download Failed (Click to retry)';
      }
    };
  }
}

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
  const coworkBtn=$('aiCoworkToggle');
  if(coworkBtn) coworkBtn.onclick=toggleCoworkMode;
  $('aiCoworkFolder').onclick=()=>{
    if(!currentProject){ toast('Select a project first'); return; }
    $('aiCoworkFolderInput').click();
  };
  $('aiCoworkFolderInput').onchange=()=>importCoworkFiles('aiCoworkFolderInput','aiCoworkFolder','Add folder');
  $('aiCoworkFiles').onclick=()=>{
    if(!currentProject){ toast('Select a project first'); return; }
    $('aiCoworkFilesInput').click();
  };
  $('aiCoworkFilesInput').onchange=()=>importCoworkFiles('aiCoworkFilesInput','aiCoworkFiles','Add files');
  document.addEventListener('click',e=>{
    const m=$('attachMenu'); if(m.hidden) return;
    if(e.target.closest('#attachMenu')||e.target.closest('#aiAttachBtn')) return;
    hideAttachMenu();
  });
}
/* Admin-only Coding Agent mode: flips mode:'cowork' on for the next /ask_stream
   call. The server still enforces admin-only (auth.require_roles) -- this is
   just the UI side of that same gate, and the button is hidden entirely for
   non-admins in onAuthed(). */
async function importCoworkFiles(inputId,buttonId,label){
  const input=$(inputId);
  const files=Array.from(input.files||[]);
  const project=currentProject;
  if(!project||!isAdminUser()||!files.length) return;
  const button=$(buttonId);button.disabled=true;
  let imported=0,failed=0;const errors=[];
  try{
    for(const file of files){
      button.textContent=`Adding ${imported+failed+1}/${files.length}`;
      const body=new FormData();body.append('file',file);
      body.append('relative_path',file.webkitRelativePath||file.name);
      try{
        const response=await fetch(`${API}/projects/${encodeURIComponent(project)}/agent/workspace-file`,{method:'POST',body});
        if(!response.ok){const data=await response.json();throw new Error(data.detail||`HTTP ${response.status}`);}
        imported++;
      }catch(error){failed++;if(errors.length<5)errors.push(`${file.webkitRelativePath||file.name}: ${error.message}`);}
    }
    addMsg('a',`Copied ${imported} files into the Cowork workspace for <b>${esc(project)}</b>. ${failed} failed. Original files are unchanged.${errors.length?'<br>'+errors.map(esc).join('<br>'):''}<br>Enable Coding Agent and ask it to list the workspace. These copies are separate from uploaded document evidence.`);
  }finally{button.disabled=false;button.textContent=label;input.value='';}
}

function toggleCoworkMode(){
  if(!isAdminUser()){ coworkMode=false; return; }
  coworkMode=!coworkMode;
  const btn=$('aiCoworkToggle');
  if(btn){
    btn.classList.toggle('on',coworkMode);
    btn.textContent=coworkMode?'Coding Agent: ON':'Coding Agent';
    btn.title=coworkMode
      ? 'Coding Agent mode is ON — the AI can read/write this project\'s sandboxed workspace and propose shell commands, which you must approve before anything runs.'
      : 'Turn on Coding Agent mode (admin only)';
  }
  if(coworkMode){
    addMsg('a','<b>Coding Agent mode enabled.</b> I can read and write files in this project’s sandboxed workspace, and propose shell commands — but nothing runs until you click <b>Approve &amp; Run</b> on the card I show you.');
  }
}
function setAiTab(tab){
  document.body.classList.remove('ai-collapsed');
  if(document.body.clientWidth<=1200)document.body.classList.add('show-ai');
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
function setChatExpanded(expanded){
  document.body.classList.toggle('chat-expanded',expanded);
  const button=$('aiExpand');
  button.setAttribute('aria-pressed',String(expanded));
  button.setAttribute('aria-label',expanded?'Restore Copilot panel':'Expand Copilot chat');
  button.title=expanded?'Restore Copilot panel':'Expand Copilot chat';
  button.textContent=expanded?'↙':'⛶';
}

function addMsg(who,html){
  const label=who==='u'?'You':'Design AI';
  const d=el('div','m '+who,`<div class="av" aria-hidden="true">${who==='u'?'U':'AI'}</div><div class="message-content"><div class="message-label">${label}</div><div class="bub">${html}</div></div>`);
  $('aiMsgs').appendChild(d); $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight; return d.querySelector('.bub');
}

function addAnswerActions(bub,text){
  if(!text.trim())return;
  const bar=el('div','answer-actions');
  const copy=el('button','answer-copy');copy.type='button';copy.textContent='Copy answer';
  copy.setAttribute('aria-label','Copy answer including source citations');
  copy.onclick=async()=>{
    try{await navigator.clipboard.writeText(text);copy.textContent='Copied';}
    catch(e){copy.textContent='Copy unavailable';}
    setTimeout(()=>{copy.textContent='Copy answer';},2000);
  };
  bar.appendChild(copy);bub.appendChild(bar);
}

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
  showCtx(f.folder||f.category||'Document', f.filename, [f._rev?('File Rev '+f._rev):'', f.discipline||''].filter(Boolean).join(' · ')||fileExt(f.filename), fileTypeIcon(fileExt(f.filename)));
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
  } else if(currentDest==='studio'){
    A('Focus concept prompt','<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>',()=>{ const p=$('studioPrompt'); if(p){ p.focus(); } });
    A('Ask Copilot for architectural prompts','<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',()=>{ setAiTab('chat'); $('aiIn').value='Suggest 3 detailed architectural prompts for an innovative exhibition pavilion:'; $('aiIn').focus(); });
    A('Refresh backend status & jobs','<circle cx="12" cy="12" r="9"/>',()=>{ if(window._refreshStudio) window._refreshStudio(); });
  } else if(currentDest==='mpd'){
    A('Check FAR Violations','<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',()=>{ setAiTab('chat'); $('aiIn').value='Check FAR violations across masterplan plots'; sendAi(); });
    A('Audit Setbacks','<rect x="3" y="3" width="18" height="18" rx="2"/><rect x="7" y="7" width="10" height="10" stroke-dasharray="2 2"/>',()=>{ setAiTab('chat'); $('aiIn').value='Audit setback encroachments and buffer compliance'; sendAi(); });
    A('Summarize Land Use GFA','<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17V9M12 17v-5M15 17v-3"/>',()=>{ setAiTab('chat'); $('aiIn').value='Summarize residential, commercial and mixed use GFA breakdown'; sendAi(); });
    A('Check Parking Deficit','<circle cx="12" cy="12" r="9"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/>',()=>{ setAiTab('chat'); $('aiIn').value='Check parking requirements and deficit across all plots'; sendAi(); });
    const selPlot = (typeof window._getMpdSelectedPlotId === 'function') ? window._getMpdSelectedPlotId() : null;
    if(selPlot){
      A(`Inspect Plot (${selPlot})`,'<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',()=>{ setAiTab('chat'); $('aiIn').value=`Inspect plot ${selPlot} parameters, FAR and setback limits`; sendAi(); });
    }
  } else {
    A('Ask Design AI','<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',()=>{ setAiTab('chat'); $('aiIn').focus(); });
  }
  if(canUpload() && ctxDoc && ctxDoc.rel && /\.pdf$/i.test(ctxDoc.filename||'') && (currentDest==='drawings'||currentDest==='documents'||currentDest==='specifications')){
    A('Re-read with vision (requires review)','<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',()=>reextractDoc());
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
  const map={ design:viewerLoaded?'3D model + selection':'Project documents', studio:'AI Design Studio', mpd:'Masterplan (MPD)', drawings:'Drawing viewer', documents:'Project documents',
    specifications:'Specifications', schedules:'Schedules & quantities', codes:'Codes / standards (KB)',
    qa:'QA & issues', reports:'Reports', overview:'Project overview', settings:'Project' };
  $('aiCtx').innerHTML=`Context: <b>${esc(map[currentDest]||'Project')}</b>${currentRevision?` · Rev ${esc(currentRevision)}`:''}`;
  const ph={ design:'Ask Design AI about this element, model, drawings, specifications or codes…',
    studio:'Ask Design AI to craft architectural concept prompts, suggest materials or lighting…',
    mpd:'Ask Design AI about masterplan plots, FAR limits, setbacks, or zoning…',
    drawings:'Ask Design AI about this drawing, revision, detail or requirement…',
    documents:'Ask Design AI about this document…', specifications:'Ask Design AI about this specification…',
    schedules:'Ask Design AI about these quantities / data…', codes:'Ask Design AI about this requirement…',
    qa:'Ask Design AI about this issue…', reports:'Ask Design AI to help with a report…' };
  $('aiIn').placeholder=ph[currentDest]||'Ask Design AI…';
}

/* --- streaming client (protected: reuse SSE contract verbatim) --- */
async function stream(display,endpoint,body){ const bub=addMsg('a','<div class="ai-working" role="status"><span class="ai-working-dot"></span><div><strong>Checking project evidence</strong><small>Reading sources and checking the answer. Complex questions may take a minute.</small></div></div>'); let ans=''; let structured=null;
  try{ const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){
      let message='Error '+r.status;
      // Covers 503 (busy) and, since mode:'cowork' is admin-gated server-side
      // (auth.require_roles), a 403 for a non-admin who somehow sent it --
      // show the server's actual reason instead of a bare status code.
      if(endpoint.endsWith('/ask_stream')){
        try{ const failure=await r.json(); if(typeof failure.detail==='string') message=failure.detail; }catch(e){}
      }
      bub.innerHTML='<span style="color:var(--red)">'+esc(message)+'</span>'; return;
    }
    const rd=r.body.getReader(); const dec=new TextDecoder(); let buf='';
    while(true){ const {value,done}=await rd.read(); if(done)break; buf+=dec.decode(value,{stream:true}); let i;
      while((i=buf.indexOf('\n\n'))>=0){ const line=buf.slice(0,i); buf=buf.slice(i+2); const dl=line.split('\n').find(l=>l.startsWith('data:')); if(!dl)continue;
        let d; try{d=JSON.parse(dl.slice(5).trim());}catch(e){continue;}
        if(d.type==='sources'){ lastSources=d.sources||[]; }
        else if(d.type==='token'){ ans+=d.text; bub.innerHTML=(window.__expoVizQ?'<span style="color:var(--muted)">Building the chart from the file…</span>':mdLite(ans))+(bub._ev||''); $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight; }
        else if(d.type==='error'){ ans+='\n[error] '+d.message; bub.innerHTML=mdLite(ans); }
        else if(d.type==='structured'){ structured=d.data||null; }
        else if(d.type==='status'){ if(!ans) bub.innerHTML='<span style="color:var(--muted)">'+esc(d.message||'Working')+'…</span>'; }
        else if(d.type==='command_pending'){
          // Cowork mode's run_command proposal. Nothing has executed -- this is
          // purely a notice that the server queued it under d.pending_id. Render
          // the approval card; the server only runs it once a human clicks
          // Approve & Run on THIS card (see addCommandCard).
          addCommandCard(d);
        }
      } }
    // Handle 3D Viewer AI Commands
      let displayAns = ans;
      const cmdRegex = /\[COMMAND:([A-Z_]+):([^\]]+)\]/gi;
      let match;
      while ((match = cmdRegex.exec(displayAns)) !== null) {
          const cmdType = match[1].toLowerCase();
          const cmdArg = match[2].trim();
          displayAns = displayAns.replace(match[0], '').trim();
          
          if (cmdType === 'isolate' && window.currentDest === 'design') {
              const vf = document.querySelector('.viewer iframe');
              if (vf && vf.contentWindow) {
                  vf.contentWindow.postMessage({ type: 'viewer_command', command: 'isolate', category: cmdArg }, '*');
              }
          }
      }

      // Show only the sources the answer actually cited
      { const hasCites=/\[SOURCE:/i.test(displayAns); const cited=citedSources(displayAns,lastSources);
        const showSrc = hasCites ? cited : lastSources;
        lastUsedSources = showSrc;
        bub._ev = evHTML(showSrc);
        bub.innerHTML = mdLite(displayAns)+bub._ev; }
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
    addAnswerActions(bub,displayAns);
    try{ if(window.ExpoMotion && /```mermaid/i.test(ans)) window.ExpoMotion.renderMermaidIn(bub, ans); }catch(e){}
    $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight;
    aiHist.push({role:'user',content:body.query}); aiHist.push({role:'assistant',content:ans});
  }catch(e){ bub.innerHTML='<span style="color:var(--red)">Request failed: '+esc(e.message||e)+'</span>'; } }

/* --- Cowork run_command approval card ---------------------------------
   Renders a command_pending SSE event as its OWN chat message (never reuses
   the streaming answer bubble, so the later `bub.innerHTML=...` in stream()
   above can't clobber it). Nothing the model proposed has run yet -- the
   buttons are the ONLY way this command can execute, each doing exactly one
   POST naming d.pending_id; the server re-reads its own stored command/cwd
   for that id rather than trusting anything this card sends back. */
function addCommandCard(d){
  const pid=d.pending_id;
  const cmdStr=(Array.isArray(d.command)?d.command:[]).map(String).join(' ');
  const html=`<div class="cmd-card" data-pid="${esc(pid)}">
      <div class="cc-h">Command proposed — approval required</div>
      ${d.reason?`<div class="cc-reason">${esc(d.reason)}</div>`:''}
      <pre>${esc(cmdStr||'(empty command)')}</pre>
      ${d.cwd?`<div class="cc-reason">cwd: ${esc(d.cwd)}</div>`:''}
      <div class="cc-actions">
        <button type="button" class="cc-btn cc-approve">Approve &amp; Run</button>
        <button type="button" class="cc-btn cc-reject">Reject</button>
      </div>
      <div class="cc-result" hidden></div>
    </div>`;
  const bub=addMsg('a',html);
  const card=bub.querySelector('.cmd-card');
  const approveBtn=card.querySelector('.cc-approve');
  const rejectBtn=card.querySelector('.cc-reject');
  const resultBox=card.querySelector('.cc-result');
  const lockButtons=()=>{ approveBtn.disabled=true; rejectBtn.disabled=true; }; // prevent double-submit; pending_id is single-use server-side too
  approveBtn.onclick=async()=>{
    lockButtons(); approveBtn.textContent='Running…';
    resultBox.hidden=false; resultBox.innerHTML='<div class="muted">Running — this can take up to a minute…</div>';
    try{
      const r=await fetch(`${API}/projects/${encodeURIComponent(currentProject)}/agent/run-command`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pending_id:pid})});
      const j=await r.json().catch(()=>({}));
      if(!r.ok){
        resultBox.innerHTML=`<div class="cc-status err">Failed: ${esc((j&&j.detail)||('HTTP '+r.status))}</div>`;
        approveBtn.textContent='Approve & Run';
        return;
      }
      const ec=(j.exit_code===null||j.exit_code===undefined)?'—':j.exit_code;
      resultBox.innerHTML=`<div class="cc-status ${j.exit_code===0?'ok':'err'}">Exit code: ${esc(ec)}</div>`
        +(j.stdout?`<div class="muted" style="margin-top:6px;font-size:11px">stdout</div><pre>${esc(j.stdout)}</pre>`:'')
        +(j.stderr?`<div class="muted" style="margin-top:6px;font-size:11px">stderr</div><pre>${esc(j.stderr)}</pre>`:'');
      approveBtn.textContent='Ran';
    }catch(e){
      resultBox.innerHTML=`<div class="cc-status err">Failed: ${esc(e.message||e)}</div>`;
      approveBtn.textContent='Approve & Run';
    }
    $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight;
  };
  rejectBtn.onclick=async()=>{
    lockButtons(); rejectBtn.textContent='Rejecting…';
    try{
      await fetch(`${API}/projects/${encodeURIComponent(currentProject)}/agent/reject-command`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pending_id:pid})});
    }catch(e){ /* best-effort: it also just expires server-side via TTL */ }
    resultBox.hidden=false; resultBox.innerHTML='<div class="cc-status rej">Rejected — not run.</div>';
    rejectBtn.textContent='Rejected';
  };
  $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight;
}

/* Open a cited source at its page using the EXISTING document viewer (no second viewer). */
function openSourceTile(rel, page, snippet=null, bbox=null){
  if(!rel){ return; }
  const base=String(rel).replace(/\\/g,'/').split('/').pop();
  const f=allDocs.find(x=>x.rel===rel || x.filename===base || (x.rel&&x.rel.endsWith('/'+base)));
  if(!f){ openFile(rel); return; }
  if(/\.pdf$/i.test(f.filename)){
    navigate('documents');
    // A cited accessible PDF may live in Reports or Schedules. Show the
    // actual source without changing its folder or falling back to page 1.
    renderSplitDocs($('genericWrap'),[f],'source document','Source unavailable.');
    const sourcePage=Number.isInteger(Number(page))&&Number(page)>0?Number(page):1;
    openPdfPreview(f,sourcePage,snippet,bbox);
    setDocContext(f);
    return;
  }
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
  return '<details class="evidence-drawer"><summary>View evidence · '+sources.length+' source'+(sources.length===1?'':'s')+'</summary><div class="evd">'+sources.map(s=>{
    const name=s.filename||s.source||s.rel||'source';
    const b=String(name).split(/[\\/]/).pop();
    const rel=s.rel||s.source||'';
    const ext=fileExt(b);
    const pg=(s.page!=null)?('p.'+s.page):'';
    const rev=s.revision?('File Rev '+s.revision):'';
    const sourcePage=Number.isInteger(Number(s.page))&&Number(s.page)>0?Number(s.page):null;
    const snippet=s.snippet||s.text_snippet||'';
    return `<button class="chip" title="${esc(name)}${pg?' · '+esc(pg):''}" onclick="openSourceTile(${esc(JSON.stringify(rel))},${sourcePage},${esc(JSON.stringify(snippet))})">`
      +`<span class="ci">${fileTypeIcon(ext)}</span>`
      +`<span class="cn">${esc(b)}</span>`
      +(pg?`<span class="cp">${esc(pg)}</span>`:'')
      +(rev?`<span class="cp">${esc(rev)}</span>`:'')
      +`</button>`; }).join('')+'</div></details>';
}

async function sendAi(standards){ const t=$('aiIn'); const q=t.value.trim();
  if(!q){ return; } if(!currentProject){ toast('Select a project'); return; }
  t.value=''; addMsg('u',esc(q));
  // Defense-in-depth: only ever request mode:'cowork' when the toggle is on
  // AND the user is actually an admin (the server re-checks this itself via
  // auth.require_roles -- this just avoids sending a mode the user can't use).
  const useCowork=coworkMode&&isAdminUser();
  const revNote=currentRevision?` (revision ${currentRevision})`:'';
  const documentQuestion=/\b(pdf|document|schedule|specification|uploaded|gfa|nsa|nisa|bua|area schedule)\b/i.test(q);
  if(!useCowork&&currentDest==='design'&&on3D&&viewerLoaded&&!documentQuestion&&!standards&&!currentAttachment){ const ctx=await getViewerCtx();
    await stream(q,`${API}/ask_model`,{project:currentProject,query:q+revNote,context:ctx.context||'',selection:ctx.selection||(lastSel&&lastSel.text)||'',messages:aiHist.slice(-6)}); }
  else if(!useCowork&&currentDest==='mpd'&&!standards){
    const selPlot = (typeof window._getMpdSelectedPlotId === 'function') ? window._getMpdSelectedPlotId() : null;
    const bub = addMsg('a', '<div class="ai-working" role="status"><span class="ai-working-dot"></span><div><strong>Masterplan Spatial Reasoning</strong><small>Evaluating zoning, FAR and parcel parameters with Qwen 3.5 9B…</small></div></div>');
    try {
      const res = await fetch(`${API}/api/v1/masterplan/projects/${encodeURIComponent(currentProject)}/ai-query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: q,
          project_id: currentProject,
          selected_plot_id: selPlot
        })
      });
      if(!res.ok){
        const err = await res.json().catch(()=>({detail:'Masterplan AI query error'}));
        bub.innerHTML = `<span style="color:var(--red)">${esc(err.detail || 'Masterplan AI query error')}</span>`;
        return;
      }
      const data = await res.json();
      let toolBadges = '';
      if(data.tools_called && data.tools_called.length){
        toolBadges = '<div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">' + data.tools_called.map(t => `<span class="mpd-badge" style="font-size:9.5px;padding:2px 6px">Tool: ${esc(t)}</span>`).join('') + '</div>';
      }
      bub.innerHTML = `<div>${mdLite(data.answer)}</div>${toolBadges}`;
      aiHist.push({role:'user',content:q});
      aiHist.push({role:'assistant',content:data.answer});

      if(data.highlight_plots && data.highlight_plots.length && typeof window._highlightMpdPlots === 'function'){
        window._highlightMpdPlots(data.highlight_plots);
      }
    } catch(err){
      bub.innerHTML = `<span style="color:var(--red)">Failed to reach masterplan reasoning engine: ${esc(err.message)}</span>`;
    }
    $('aiMsgs').scrollTop = $('aiMsgs').scrollHeight;
    return;
  }
  else { const prefix=(standards||currentDest==='codes')?'Using the codes/standards knowledge base, ':'';
    let scoped=q+revNote;
    const _focus=(ctxDoc&&!useCowork&&['documents','specifications','drawings','schedules'].includes(currentDest))?(ctxDoc.rel||''):'';
    if(_focus) scoped=`Regarding "${ctxDoc.filename}": `+scoped;
    window.__expoVizQ=false; const _attId=useCowork?null:((currentAttachment&&currentAttachment.id)||null);
    const askBody={project:currentProject,query:prefix+scoped,messages:aiHist.slice(-8),k:8,model:'qwen3.5:9b',focus_doc:_focus,attachment_id:_attId};
    if(useCowork) askBody.mode='cowork';
    window.__expoLastQuestion=q; window.__expoVizQ=/\b(chart|graph|plot|visuali[sz]\w*|dashboard|pie|donut|histogram|infographic)\b/i.test(q)&&!/flow\s*chart/i.test(q);
    if(!useCowork&&window.ExpoChartChat&&window.ExpoChartChat.last){ try{ const ed=await window.ExpoChartChat.tryEdit(q,currentProject);
      if(ed){ const b=addMsg('a',esc(ed.reply||'Updated the chart.')); window.ExpoChartChat.render(b,ed); $('aiMsgs').scrollTop=$('aiMsgs').scrollHeight;
        aiHist.push({role:'user',content:q}); aiHist.push({role:'assistant',content:ed.reply||''}); return; } }catch(e){ console.warn('chart edit',e); } }
    await stream(q,`${API}/ask_stream`,askBody); }
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

