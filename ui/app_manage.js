/* Expo Design AI - in-app management (2026-10-22).
   Replaces the jump to classic.html: documents (delete / move), folders (create /
   rename / delete / access), recycle bin, deleted projects and users - all inside
   app.html, using the same server endpoints the classic screen used.
   Globals used from app.js: API, currentProject, currentUser, esc, toast, canUpload,
   loadDocuments, allDocs. */
(function(){
  'use strict';
  const H = s => (typeof esc === 'function' ? esc(String(s == null ? '' : s)) : String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
  const P = () => encodeURIComponent(currentProject || '');
  const isAdmin = () => !!(currentUser && currentUser.role === 'admin');
  const canManage = () => (typeof canUpload === 'function') ? canUpload() : isAdmin();
  const say = m => (typeof toast === 'function' ? toast(m) : alert(m));

  async function call(url, opts){
    const r = await fetch(API + url, Object.assign({credentials:'same-origin'}, opts || {}));
    let d = null; try { d = await r.json(); } catch(e) {}
    if(!r.ok) throw new Error((d && (d.detail || d.message)) || ('HTTP ' + r.status));
    return d || {};
  }
  const post = (url, body) => call(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})});
  const del  = url => call(url, {method:'DELETE'});

  // ---------- styles (scoped to .mg) ----------
  const CSS = `
  .mg{margin-top:22px;border:1px solid var(--border,#1e2c45);border-radius:14px;background:var(--panel,#0f1828);overflow:hidden}
  .mg-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid var(--border,#1e2c45)}
  .mg-head h3{margin:0;font-size:15px;letter-spacing:.2px}
  .mg-tabs{display:flex;gap:4px;padding:8px 10px;border-bottom:1px solid var(--border,#1e2c45);flex-wrap:wrap;background:rgba(255,255,255,.015)}
  .mg-tab{border:0;background:transparent;color:var(--muted,#8ea0ba);padding:7px 12px;border-radius:8px;cursor:pointer;font:inherit;font-size:13px;font-weight:600}
  .mg-tab:hover{background:rgba(255,255,255,.05);color:var(--text,#e8eef7)}
  .mg-tab.on{background:rgba(77,124,254,.16);color:#9db6ff}
  .mg-body{padding:14px 18px;max-height:62vh;overflow:auto}
  .mg-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 6px;border-bottom:1px solid rgba(255,255,255,.05)}
  .mg-row:last-child{border-bottom:0}
  .mg-name{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
  .mg-sub{color:var(--muted,#8ea0ba);font-size:11.5px;margin-left:6px}
  .mg-acts{display:flex;gap:6px;flex:none;align-items:center}
  .mg-btn{border:1px solid var(--border2,#28395a);background:transparent;color:var(--text,#e8eef7);padding:5px 10px;border-radius:7px;font-size:12px;cursor:pointer;font:inherit;font-size:12px}
  .mg-btn:hover{border-color:#4d7cfe;color:#9db6ff}
  .mg-btn.pri{background:#4d7cfe;border-color:#4d7cfe;color:#fff}
  .mg-btn.pri:hover{filter:brightness(1.08);color:#fff}
  .mg-btn.dan{color:#ff8f8f;border-color:rgba(255,107,107,.35)}
  .mg-btn.dan:hover{background:rgba(255,107,107,.1);color:#ffb3b3}
  .mg-input,.mg-sel{background:var(--panel2,#14203a);border:1px solid var(--border,#1e2c45);color:var(--text,#e8eef7);border-radius:7px;padding:6px 9px;font:inherit;font-size:12.5px}
  .mg-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
  .mg-empty{color:var(--muted,#8ea0ba);padding:18px 4px;font-size:13px}
  .mg-pill{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:999px;background:rgba(255,255,255,.07);color:var(--muted,#8ea0ba);margin-left:6px;vertical-align:1px}
  .mg-pill.warn{background:rgba(255,181,71,.15);color:#ffc266}
  .mg-pill.ok{background:rgba(52,199,123,.14);color:#5fd99a}
  .mg-note{font-size:12px;color:var(--muted,#8ea0ba);margin:0 0 10px}
  .mg-members{margin:4px 0 8px 18px;padding:8px 10px;border-left:2px solid rgba(77,124,254,.35);background:rgba(77,124,254,.04);border-radius:0 8px 8px 0}`;
  function ensureCss(){
    if(document.getElementById('mgCss')) return;
    const s = document.createElement('style'); s.id = 'mgCss'; s.textContent = CSS; document.head.appendChild(s);
  }

  // ---------- shell ----------
  let tab = 'docs';
  function tabs(){
    const t = [['docs','Documents'],['folders','Folders & access'],['bin','Recycle Bin']];
    if(isAdmin()) t.push(['projbin','Deleted projects'],['users','Users'],['health','System health']);
    return t;
  }
  window.renderManagement = function(host){
    ensureCss();
    if(!host) return;
    if(!canManage()){
      host.innerHTML = `<div class="mg"><div class="mg-head"><h3>Manage</h3></div><div class="mg-body"><p class="mg-note">You have query-only access. Uploads, folders and access are managed by an admin or project lead.</p></div></div>`;
      return;
    }
    host.innerHTML = `<div class="mg">
      <div class="mg-head"><h3>Manage project files &amp; access</h3><span class="mg-sub">${H(currentProject||'')}</span></div>
      <div class="mg-tabs">${tabs().map(([k,l])=>`<button class="mg-tab${k===tab?' on':''}" data-t="${k}">${l}</button>`).join('')}</div>
      <div class="mg-body" id="mgBody"></div></div>`;
    host.querySelectorAll('.mg-tab').forEach(b => b.onclick = () => { tab = b.dataset.t; window.renderManagement(host); });
    const body = host.querySelector('#mgBody');
    ({docs:docsTab, folders:foldersTab, bin:binTab, projbin:projBinTab, users:usersTab, health:healthTab}[tab] || docsTab)(body).catch(e => {
      body.innerHTML = `<div class="mg-empty">Could not load: ${H(e.message)}</div>`;
    });
  };
  const rerender = body => { const host = body.closest('.mg') && body.closest('.mg').parentElement; if(host) window.renderManagement(host); };

  // ---------- Documents ----------
  async function docsTab(body){
    body.innerHTML = '<div class="mg-empty">Loading…</div>';
    const [d, f] = await Promise.all([call(`/projects/${P()}/documents`), call(`/projects/${P()}/folders`)]);
    const docs = d.documents || [], folders = f.folders || [];
    if(!docs.length){ body.innerHTML = '<div class="mg-empty">No documents in this project yet. Use Upload in the Documents or Drawings screen.</div>'; return; }
    const opts = folders.map(x => `<option value="${x.id}">${H(x.name)}</option>`).join('');
    body.innerHTML = `<div class="mg-bar"><input class="mg-input" id="mgDocQ" placeholder="Filter ${docs.length} files…" style="flex:1;min-width:180px"></div>
      <div id="mgDocList">${docs.map((x,i)=>`<div class="mg-row" data-n="${H((x.filename||'').toLowerCase())}">
        <div class="mg-name" title="${H(x.filename)}">${H(x.filename)}<span class="mg-sub">${H(x.folder||x.category||'')}</span>${statusPill(x.status)}</div>
        <div class="mg-acts">
          <select class="mg-sel" data-i="${i}" title="Move to folder"><option value="">Move to…</option>${opts}</select>
          <button class="mg-btn dan" data-del="${i}">Delete</button>
        </div></div>`).join('')}</div>`;
    body.querySelector('#mgDocQ').oninput = e => {
      const q = e.target.value.toLowerCase();
      body.querySelectorAll('#mgDocList .mg-row').forEach(r => r.style.display = r.dataset.n.includes(q) ? '' : 'none');
    };
    body.querySelectorAll('select[data-i]').forEach(s => s.onchange = async () => {
      if(!s.value) return; const x = docs[+s.dataset.i];
      try { await post(`/projects/${P()}/documents/move`, {filename: x.filename, folder_id: +s.value}); say('Moved to ' + s.options[s.selectedIndex].text); if(window.loadDocuments) await loadDocuments(); docsTab(body); }
      catch(e){ say('Move failed: ' + e.message); s.value = ''; }
    });
    body.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      const x = docs[+b.dataset.del];
      if(!confirm(`Delete "${x.filename}"?\n\nIt moves to the Recycle Bin and can be restored for 15 days. It stops appearing in search and answers immediately.`)) return;
      try { await del(`/projects/${P()}/documents/${encodeURIComponent(x.filename)}`); say('Moved to Recycle Bin - recoverable for 15 days.'); if(window.loadDocuments) await loadDocuments(); docsTab(body); }
      catch(e){ say('Delete failed: ' + e.message); }
    });
  }
  function statusPill(s){
    if(!s) return '';
    if(/^(ready|verified|published)$/.test(s)) return '<span class="mg-pill ok">ready</span>';
    if(/warn/.test(s)) return '<span class="mg-pill warn">ready (warnings)</span>';
    return `<span class="mg-pill">${H(s)}</span>`;
  }

  // ---------- Folders & access ----------
  async function foldersTab(body){
    body.innerHTML = '<div class="mg-empty">Loading…</div>';
    const f = await call(`/projects/${P()}/folders`); const folders = f.folders || [];
    body.innerHTML = `<p class="mg-note">A document lives in one folder; a folder's access list decides which non-admin users can see it.</p>
      <div class="mg-bar"><input class="mg-input" id="mgNewFolder" placeholder="New folder name" style="flex:1;min-width:180px"><button class="mg-btn pri" id="mgAddFolder">Create folder</button></div>
      <div>${folders.map(x=>`<div class="mg-row" data-id="${x.id}">
        <div class="mg-name">📁 ${H(x.name)}<span class="mg-sub">${x.doc_count||0} files · ${x.member_count||0} users</span></div>
        <div class="mg-acts"><button class="mg-btn" data-acc="${x.id}">Access</button><button class="mg-btn" data-ren="${x.id}">Rename</button><button class="mg-btn dan" data-rm="${x.id}">Delete</button></div>
      </div><div class="mg-members" id="mgMem${x.id}" style="display:none"></div>`).join('') || '<div class="mg-empty">No folders yet.</div>'}</div>`;
    body.querySelector('#mgAddFolder').onclick = async () => {
      const name = body.querySelector('#mgNewFolder').value.trim(); if(!name) return;
      try { await post(`/projects/${P()}/folders`, {name}); say('Folder created'); foldersTab(body); } catch(e){ say(e.message); }
    };
    body.querySelectorAll('[data-ren]').forEach(b => b.onclick = async () => {
      const x = folders.find(y => y.id == b.dataset.ren); const name = prompt('Rename folder', x.name); if(!name || name === x.name) return;
      try { await post(`/projects/${P()}/folders/${x.id}/rename`, {name}); say('Renamed'); foldersTab(body); } catch(e){ say(e.message); }
    });
    body.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => {
      const x = folders.find(y => y.id == b.dataset.rm);
      if(!confirm(`Delete folder "${x.name}"?` + (x.doc_count ? `\n\nIts ${x.doc_count} file(s) move to the Recycle Bin (recoverable for 15 days).` : ''))) return;
      try { await del(`/projects/${P()}/folders/${x.id}`); say('Folder deleted'); if(window.loadDocuments) await loadDocuments(); foldersTab(body); } catch(e){ say(e.message); }
    });
    body.querySelectorAll('[data-acc]').forEach(b => b.onclick = () => toggleMembers(body, +b.dataset.acc));
  }
  async function toggleMembers(body, id){
    const box = body.querySelector('#mgMem' + id);
    if(box.style.display !== 'none'){ box.style.display = 'none'; return; }
    box.style.display = ''; box.innerHTML = '<span class="mg-sub">Loading…</span>';
    const [m, u] = await Promise.all([call(`/projects/${P()}/folders/${id}/members`), call(`/projects/${P()}/assignable-users`)]);
    const members = m.members || [], users = (u.users || []).filter(x => x.is_active !== false);
    const ids = new Set(members.map(x => x.user_id));
    box.innerHTML = (members.length ? members.map(x => `<div class="mg-row"><div class="mg-name">${H(x.username)}<span class="mg-sub">${H(x.role||'')}</span></div><button class="mg-btn dan" data-unm="${x.user_id}">Remove</button></div>`).join('')
        : '<div class="mg-sub" style="margin:4px 0 8px">Only admins and leads can see this folder.</div>')
      + `<div class="mg-bar" style="margin:8px 0 2px"><select class="mg-sel" id="mgAddUser${id}"><option value="">Add user…</option>${users.filter(x=>!ids.has(x.id)).map(x=>`<option value="${x.id}">${H(x.username)} (${H(x.role)})</option>`).join('')}</select></div>`;
    box.querySelectorAll('[data-unm]').forEach(b => b.onclick = async () => {
      try { await del(`/projects/${P()}/folders/${id}/members/${b.dataset.unm}`); box.style.display = 'none'; toggleMembers(body, id); } catch(e){ say(e.message); }
    });
    box.querySelector('#mgAddUser' + id).onchange = async e => {
      if(!e.target.value) return;
      try { await post(`/projects/${P()}/folders/${id}/members`, {user_id: +e.target.value}); say('Access granted'); box.style.display = 'none'; toggleMembers(body, id); } catch(err){ say(err.message); }
    };
  }

  // ---------- Recycle bin (documents) ----------
  async function binTab(body){
    body.innerHTML = '<div class="mg-empty">Loading…</div>';
    const d = await call(`/projects/${P()}/recycle-bin`); const items = d.items || [];
    if(!items.length){ body.innerHTML = `<div class="mg-empty">The Recycle Bin is empty. Deleted files stay here for ${d.retention_days||15} days.</div>`; return; }
    body.innerHTML = items.map(x => `<div class="mg-row"><div class="mg-name">${H(x.filename)}<span class="mg-sub">${x.days_remaining} day(s) left</span></div>
      <div class="mg-acts"><button class="mg-btn pri" data-rs="${H(x.filename)}">Restore</button><button class="mg-btn dan" data-pg="${H(x.filename)}">Delete permanently</button></div></div>`).join('');
    body.querySelectorAll('[data-rs]').forEach(b => b.onclick = async () => {
      try { await post(`/projects/${P()}/documents/${encodeURIComponent(b.dataset.rs)}/restore`); say('Restored'); if(window.loadDocuments) await loadDocuments(); binTab(body); } catch(e){ say('Restore failed: ' + e.message); }
    });
    body.querySelectorAll('[data-pg]').forEach(b => b.onclick = async () => {
      if(!confirm(`Permanently delete "${b.dataset.pg}"? This cannot be undone.`)) return;
      try { await del(`/projects/${P()}/recycle-bin/${encodeURIComponent(b.dataset.pg)}`); say('Permanently deleted'); binTab(body); } catch(e){ say(e.message); }
    });
  }

  // ---------- Deleted projects (admin) ----------
  async function projBinTab(body){
    body.innerHTML = '<div class="mg-empty">Loading…</div>';
    const d = await call('/admin/recycle-bin/projects'); const items = d.items || [];
    if(!items.length){ body.innerHTML = `<div class="mg-empty">No deleted projects. A deleted project can be restored for ${d.retention_days||15} days.</div>`; return; }
    body.innerHTML = items.map(x => { const n = x.project || x.name; return `<div class="mg-row"><div class="mg-name">${H(n)}<span class="mg-sub">${x.days_remaining!=null?x.days_remaining+' day(s) left':''}</span></div>
      <div class="mg-acts"><button class="mg-btn pri" data-rs="${H(n)}">Restore</button><button class="mg-btn dan" data-pg="${H(n)}">Delete permanently</button></div></div>`; }).join('');
    body.querySelectorAll('[data-rs]').forEach(b => b.onclick = async () => {
      try { await post(`/projects/${encodeURIComponent(b.dataset.rs)}/restore`); say('Project restored'); if(window.loadProjects) loadProjects(); projBinTab(body); } catch(e){ say(e.message); }
    });
    body.querySelectorAll('[data-pg]').forEach(b => b.onclick = async () => {
      if(!confirm(`Permanently delete project "${b.dataset.pg}" and all its files? This cannot be undone.`)) return;
      try { await del(`/admin/recycle-bin/projects/${encodeURIComponent(b.dataset.pg)}`); say('Project permanently deleted'); projBinTab(body); } catch(e){ say(e.message); }
    });
  }

  // ---------- Users (admin) ----------
  const TEST_NAME = /^(cad|test|stress|bench|tmp|demo|fix\d*|qa|audit|probe|e2e|pw)_?[a-z]*_?[0-9a-f]{4,}$|_[0-9a-f]{6}$/i;
  async function usersTab(body){
    body.innerHTML = '<div class="mg-empty">Loading…</div>';
    const d = await call('/admin/users'); const users = (d.users || []).filter(u => u.username !== 'system');
    const tests = users.filter(u => TEST_NAME.test(u.username) && u.is_active !== false);
    body.innerHTML = `${tests.length ? `<p class="mg-note" style="color:#ffc266">⚠ ${tests.length} active account(s) look like leftover automated-test users${tests.some(u=>u.role==='admin')?' - some with admin rights':''}. Deactivate them unless they are real people.</p>` : ''}
      <div class="mg-bar">
        <input class="mg-input" id="mgUN" placeholder="Username" style="width:140px">
        <input class="mg-input" id="mgFN" placeholder="Full name" style="width:150px">
        <input class="mg-input" id="mgEM" type="email" placeholder="Work email (for company sign-in)" style="width:210px">
        <input class="mg-input" id="mgPW" type="password" placeholder="Temporary password (blank = company sign-in only)" style="width:160px" title="Leave blank for users who will only sign in with company sign-in">
        <select class="mg-sel" id="mgRole"><option value="user">user (query)</option><option value="lead">lead (upload)</option><option value="admin">admin</option></select>
        <button class="mg-btn pri" id="mgAddU">Add user</button>
        ${tests.length ? `<button class="mg-btn dan" id="mgDeactTests">Deactivate ${tests.length} test account(s)</button>` : ''}
      </div>
      <div>${users.map(u => `<div class="mg-row">
        <div class="mg-name">${H(u.username)}<span class="mg-sub">${H(u.full_name||'')}${u.email?' · '+H(u.email):''}</span><span class="mg-pill" title="How this user signs in">${u.auth_provider&&u.auth_provider!=='local'?H(u.auth_provider.charAt(0).toUpperCase()+u.auth_provider.slice(1))+' sign-in':'Password'}</span>${u.is_active===false?'<span class="mg-pill">inactive</span>':''}${TEST_NAME.test(u.username)?'<span class="mg-pill warn">test?</span>':''}</div>
        <div class="mg-acts">
          <select class="mg-sel" data-role="${u.id}" ${u.id===currentUser.id?'disabled title="You cannot change your own role"':''}>${['user','lead','admin'].map(r=>`<option${r===u.role?' selected':''}>${r}</option>`).join('')}</select>
          ${u.id===currentUser.id ? '' : `<button class="mg-btn${u.is_active===false?'':' dan'}" data-act="${u.id}" data-to="${u.is_active===false?1:0}">${u.is_active===false?'Activate':'Deactivate'}</button>`}
          ${u.id===currentUser.id ? '' : `<button class="mg-btn dan" data-deluser="${u.id}" data-un="${H(u.username)}" title="Permanently delete this account and its personal data">Delete</button>`}
        </div></div>`).join('')}</div>`;
    body.querySelector('#mgAddU').onclick = async () => {
      const username = body.querySelector('#mgUN').value.trim(), password = body.querySelector('#mgPW').value;
      const email = body.querySelector('#mgEM').value.trim();
      if(!username){ say('Username is required'); return; }
      if(password && password.length < 8){ say('A temporary password must be at least 8 characters'); return; }
      if(!password && !email){ say('Give a temporary password, or a work email for company sign-in'); return; }
      try { await post('/admin/users', {username, password, email, role: body.querySelector('#mgRole').value, full_name: body.querySelector('#mgFN').value.trim()}); say(password ? 'User created - they will be asked to change the password' : 'User created for company sign-in'); usersTab(body); } catch(e){ say(e.message); }
    };
    body.querySelectorAll('[data-role]').forEach(s => s.onchange = async () => {
      try { await post(`/admin/users/${s.dataset.role}/role`, {role: s.value}); say('Role updated'); } catch(e){ say(e.message); usersTab(body); }
    });
    body.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
      try { await post(`/admin/users/${b.dataset.act}/active`, {active: b.dataset.to === '1'}); usersTab(body); } catch(e){ say(e.message); }
    });
    body.querySelectorAll('[data-deluser]').forEach(b => b.onclick = async () => {
      const un = b.dataset.un;
      const typed = prompt(`Permanently delete "${un}"?\n\nThis removes the account, name, email, password, company sign-in link, project/folder access and their private chat attachments. It cannot be undone.\nProject documents, chats and images they created stay in the project (no longer linked to them). The security audit log keeps its history.\n\nType the username to confirm:`);
      if(typed === null) return;
      if(typed.trim() !== un){ say('Username did not match - nothing was deleted'); return; }
      try { const r = await call(`/admin/users/${b.dataset.deluser}`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({confirm_username: typed.trim()})}); say(`Deleted ${un}` + (r && r.private_files_removed ? ` and ${r.private_files_removed} private file(s)` : '')); usersTab(body); } catch(e){ say(e.message); }
    });
    const dt = body.querySelector('#mgDeactTests');
    if(dt) dt.onclick = async () => {
      if(!confirm(`Deactivate these ${tests.length} account(s)?\n\n${tests.map(u=>u.username).join(', ')}\n\nThey can be re-activated later.`)) return;
      let n = 0; for(const u of tests){ if(u.id === currentUser.id) continue; try { await post(`/admin/users/${u.id}/active`, {active:false}); n++; } catch(e){} }
      say(`Deactivated ${n} account(s)`); usersTab(body);
    };
  }

  // ---------- System health (admin) ----------
  async function healthTab(body){
    body.innerHTML = '<div class="mg-empty">Checking…</div>';
    const h = await call('/admin/system-health');
    const ok = v => v ? '<span class="mg-pill" style="color:#5fd38d">OK</span>' : '<span class="mg-pill warn">Problem</span>';
    const b = h.backup || {}, q = h.queue || {}, d = h.disk || {}, s = h.services || {}, sec = h.security || {};
    const row = (k, v) => `<div class="mg-row"><div class="mg-name">${H(k)}</div><div class="mg-acts" style="text-align:right">${v}</div></div>`;
    body.innerHTML = `
      ${(h.warnings||[]).length ? `<div class="mg-note" style="color:#ffc266">${h.warnings.map(w=>'⚠ '+H(w)).join('<br>')}</div>` : '<p class="mg-note" style="color:#5fd38d">✓ No problems found.</p>'}
      <div class="mg-bar"><button class="mg-btn pri" id="mgBackupNow" ${b.running?'disabled':''}>${b.running?'Backup running…':'Back up now'}</button><button class="mg-btn" id="mgHealthRefresh">Refresh</button></div>
      <h4 style="margin:12px 0 4px">Backups</h4>
      ${row('Last good backup', b.last_ok_at ? `${H(b.last_ok_at.replace('T',' '))} (${H(b.age_hours)} h ago)` : 'Never')}
      ${row('Last run', b.finished_at ? `${H(b.trigger||'')} · ${b.ok?'OK':'Failed: '+H(b.error||'')} · ${H(b.files_copied||0)} files, ${H(b.mb_copied||0)} MB, ${H(b.duration_s||0)} s` : '—')}
      ${row('Backup folder', H(b.backup_dir) + (b.same_disk_as_data ? ' <span class="mg-pill warn">same disk as data</span>' : ''))}
      ${row('Schedule', b.enabled ? `Nightly at ${H(b.hour)}:00, keeps ${H(b.keep)} database snapshots` : 'Off')}
      <h4 style="margin:12px 0 4px">AI services and storage</h4>
      ${row('Language models (Ollama)', ok(s.ollama&&s.ollama.ok) + (s.ollama&&s.ollama.models ? ' '+H(s.ollama.models.length)+' models' : ''))}
      ${row('Image engine (ComfyUI)', ok(s.comfyui&&s.comfyui.ok) + (s.comfyui&&s.comfyui.gpu ? ` ${H(s.comfyui.gpu)}, ${H(s.comfyui.vram_free_gb)} GB VRAM free` : ''))}
      ${row('Disk (data drive)', d.free_gb!=null ? `${H(d.free_gb)} GB free of ${H(d.total_gb)} GB (${H(d.used_pct)}% used)` : '—')}
      ${row('Processing queue', Object.keys(q).length ? Object.entries(q).map(([k,v])=>`${H(k)}: ${H(v)}`).join(' · ') : 'empty')}
      ${row('Documents needing attention', Object.keys(h.document_problems||{}).length ? Object.entries(h.document_problems).map(([k,v])=>`${H(k)}: ${H(v)}`).join(' · ') : 'none')}
      ${(h.problem_documents||[]).map(p => `<div class="mg-row"><div class="mg-name">${H(p.filename)}<span class="mg-sub">${H(p.project)}</span></div><div class="mg-acts"><span class="mg-pill warn">${H(p.status)}</span></div></div>`).join('')}
      <h4 style="margin:12px 0 4px">Security</h4>
      ${row('Active users / admins', `${H(sec.active_users)} / ${H(sec.active_admins)}`)}
      ${row('Company sign-in', sec.sso_providers && sec.sso_providers.length ? H(sec.sso_providers.join(', ')) : 'Not configured (password login)')}
      ${row('HTTPS for network users', sec.https ? 'On' : 'Off (local use only)')}
      ${row('Login stays valid while in use', `${H(sec.session_hours)} h, renewed automatically`)}
      ${row('Server up for', `${H(h.uptime_hours)} h`)}`;
    body.querySelector('#mgHealthRefresh').onclick = () => healthTab(body);
    body.querySelector('#mgBackupNow').onclick = async () => {
      try { const r = await post('/admin/backup/run'); say(r.message || 'Backup started'); setTimeout(() => healthTab(body), 4000); } catch(e){ say(e.message); }
    };
  }

  // ---------- Delete button on every document row (Documents / Drawings / Specs) ----------
  window.mgDeleteDoc = async function(filename){
    if(!canManage()) return;
    if(!confirm(`Delete "${filename}"?\n\nIt moves to the Recycle Bin and can be restored for 15 days.`)) return;
    try { await del(`/projects/${P()}/documents/${encodeURIComponent(filename)}`); say('Moved to Recycle Bin - recoverable for 15 days.'); if(window.loadDocuments) await loadDocuments(); if(window.navigate && window._curDest) navigate(window._curDest); }
    catch(e){ say('Delete failed: ' + e.message); }
  };

  // ---------- one-time cleanup of leftover test keys in this browser ----------
  try {
    if(!localStorage.getItem('expo_ls_cleaned_v1')){
      Object.keys(localStorage).filter(k => /^__/.test(k)).forEach(k => localStorage.removeItem(k));
      localStorage.setItem('expo_ls_cleaned_v1', '1');
    }
  } catch(e) {}
})();
