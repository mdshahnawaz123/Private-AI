/* BIM Data panel: quantity take-off, rooms, storeys, phases, types, attribute search.
   Backed by /api/ifc/* (SQLite index built from the project's IFC files). Drives the 3D
   viewer through window.bimAction(action, [{model, step_id}]) defined in viewer_fragments.js. */
(function () {
  const params = new URLSearchParams(location.search);
  const project = params.get('project') || '';
  if (!project) return;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const num = (n, d = 1) => (n == null ? '-' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
  const api = async (path, opts) => {
    const token = params.get('token') || (window.parent && window.parent.authToken) || '';
    const headers = Object.assign({}, (opts && opts.headers) || {});
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const r = await fetch('/api/ifc/' + path, Object.assign({ credentials: 'include' }, opts || {}, { headers }));
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    return r.json();
  };
  const qs = (o) => Object.entries(o).filter(([, v]) => v !== '' && v != null).map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');

  const css = document.createElement('style');
  css.textContent = `
  #bimPanel{position:absolute;right:136px;top:12px;width:470px;max-height:calc(100% - 90px);display:none;flex-direction:column;background:var(--panel,#131b26);border:1px solid var(--border,#2a3a50);border-radius:12px;box-shadow:0 14px 44px rgba(0,0,0,.6);z-index:14;color:var(--text,#dce6f5);font-size:12px}
  #bimPanel.open{display:flex}
  #bimPanel .bhd{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-bottom:1px solid var(--border,#2a3a50);font-weight:700;font-size:12.5px}
  #bimPanel .bhd span.x{cursor:pointer;color:var(--muted,#8aa0bd);font-size:17px;line-height:1}
  #bimTabs{display:flex;gap:2px;padding:6px 8px 0;border-bottom:1px solid var(--border,#2a3a50);flex-wrap:wrap}
  #bimTabs button{background:none;border:none;color:var(--muted,#8aa0bd);padding:6px 9px;border-radius:7px 7px 0 0;cursor:pointer;font-size:11.5px;font-weight:600}
  #bimTabs button.on{background:var(--panel2,#1b2533);color:#fff;box-shadow:inset 0 -2px 0 var(--accent,#4d7cfe)}
  #bimBar{display:flex;gap:5px;flex-wrap:wrap;padding:8px 10px;border-bottom:1px solid var(--border,#2a3a50);align-items:center}
  #bimBar select,#bimBar input,#bimSearchBox input,#bimSearchBox select{background:var(--panel2,#1b2533);border:1px solid var(--border,#2a3a50);color:var(--text,#dce6f5);border-radius:6px;padding:4px 6px;font-size:11.5px;max-width:130px;font-family:inherit}
  #bimBody{overflow:auto;padding:0 0 8px;min-height:120px}
  #bimBody table{width:100%;border-collapse:collapse}
  #bimBody th{position:sticky;top:0;background:var(--panel,#131b26);text-align:right;padding:6px 8px;color:var(--muted,#8aa0bd);font-weight:600;border-bottom:1px solid var(--border,#2a3a50)}
  #bimBody th:first-child,#bimBody td:first-child{text-align:left}
  #bimBody td{padding:5px 8px;text-align:right;border-bottom:1px solid rgba(255,255,255,.05);white-space:nowrap;max-width:210px;overflow:hidden;text-overflow:ellipsis}
  #bimBody tr.r{cursor:pointer}#bimBody tr.r:hover td{background:rgba(77,124,254,.14)}
  #bimBody tr.tot td{font-weight:700;background:var(--panel,#131b26);border-top:1px solid var(--border,#2a3a50);position:sticky;bottom:0}
  #bimFoot{display:flex;gap:6px;align-items:center;padding:7px 10px;border-top:1px solid var(--border,#2a3a50);color:var(--muted,#8aa0bd);font-size:11px}
  #bimFoot .sp{flex:1}
  #bimPanel .bb{background:var(--panel2,#1b2533);border:1px solid var(--border,#2a3a50);color:var(--text,#dce6f5);border-radius:6px;padding:4px 9px;cursor:pointer;font-size:11.5px;text-decoration:none}
  #bimPanel .bb:hover{border-color:var(--accent,#4d7cfe)}
  #bimMsg{padding:18px 14px;line-height:1.6;color:var(--muted,#8aa0bd)}
  #bimSearchBox{display:flex;flex-wrap:wrap;gap:5px;padding:8px 10px}
  #bimProps{max-height:150px;overflow:auto;border-top:1px dashed var(--border,#2a3a50);padding:6px 10px;font-size:11px}
  #bimProps b{color:#9fb3cc}`;
  document.head.appendChild(css);

  const panel = document.createElement('div');
  panel.id = 'bimPanel';
  panel.innerHTML = `
    <div class="bhd"><span>BIM Data &mdash; model quantities &amp; attributes</span><span class="x" id="bimClose">&times;</span></div>
    <div id="bimTabs"></div>
    <div id="bimBar"></div>
    <div id="bimBody"><div id="bimMsg">Loading&hellip;</div></div>
    <div id="bimProps" style="display:none"></div>
    <div id="bimFoot"><span id="bimInfo"></span><span class="sp"></span>
      <select id="bimMode" class="bb"><option value="highlight">On click: Highlight</option><option value="isolate">On click: Isolate</option><option value="hide">On click: Hide</option></select>
      <button class="bb" id="bimReset">Reset view</button></div>`;
  (document.getElementById('view') || document.body).appendChild(panel);

  // toolbar button
  const anchor = $('btnMeasureTool');
  const btn = document.createElement('button');
  btn.className = 'ib'; btn.id = 'btnBimData'; btn.title = 'BIM Data: quantity take-off, rooms, storeys, phases, types, search';
  btn.innerHTML = '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>';
  if (anchor && anchor.parentElement) { const g = document.createElement('div'); g.className = 'grp'; g.appendChild(btn); anchor.parentElement.after(g); }

  const TABS = [['qto', 'Quantities', 'class'], ['rooms', 'Rooms'], ['storey', 'Storeys', 'storey'], ['phase', 'Phasing', 'phase'], ['type', 'Types', 'type'], ['search', 'Search']];
  const GROUP_PARAM = { class: 'cls', type: 'type', storey: 'storey', phase: 'phase', material: 'material', category: 'category', model: 'model' };
  let tab = 'qto', summary = null, state = { cls: '', storey: '', phase: '', q: '', group: 'class' }, pollTimer = null;

  const tabsEl = $('bimTabs');
  TABS.forEach(([id, label]) => { const b = document.createElement('button'); b.dataset.tab = id; b.textContent = label; b.onclick = () => { tab = id; render(); }; tabsEl.appendChild(b); });

  const mode = () => $('bimMode').value;
  async function act(items, label) {
    if (!items.length) { $('bimInfo').textContent = 'No matching elements.'; return; }
    if (typeof window.bimAction !== 'function') { $('bimInfo').textContent = 'Viewer not ready yet.'; return; }
    $('bimInfo').textContent = `${mode()}: ${items.length.toLocaleString()} elements${label ? ' - ' + label : ''}`;
    await window.bimAction(mode(), items);
  }
  $('bimReset').onclick = () => { if (window.bimAction) window.bimAction('reset', []); $('bimInfo').textContent = 'View reset.'; };
  $('bimClose').onclick = () => panel.classList.remove('open');
  btn.onclick = () => { panel.classList.toggle('open'); btn.classList.toggle('on', panel.classList.contains('open')); if (panel.classList.contains('open')) boot(); };

  function sel(id, opts, cur, first) {
    return `<select id="${id}"><option value="">${first}</option>${opts.map((o) => `<option value="${esc(o)}"${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
  }

  async function boot() {
    try {
      const st = await api('status?' + qs({ project }));
      if (!st.indexed) {
        $('bimBody').innerHTML = `<div id="bimMsg">The IFC data index for this project has not been built yet (${st.files} IFC file(s)).<br><br><button class="bb" id="bimBuild">Build index now</button><div id="bimJob" style="margin-top:8px"></div></div>`;
        $('bimBar').innerHTML = '';
        $('bimBuild').onclick = async () => { await api('index?' + qs({ project }), { method: 'POST' }); watch(); };
        if (st.job && st.job.state === 'running') watch();
        return;
      }
      if (!summary) summary = await api('summary?' + qs({ project }));
      render();
    } catch (e) { $('bimBody').innerHTML = `<div id="bimMsg">Could not load BIM data: ${esc(e.message)}</div>`; }
  }
  function watch() {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      const st = await api('status?' + qs({ project })).catch(() => null);
      if (!st) return;
      const j = st.job;
      const el = $('bimJob');
      if (el && j) el.textContent = `${j.state}: ${j.done_files}/${j.total_files} files ${j.current || ''}`;
      if (j && j.state !== 'running') { clearInterval(pollTimer); summary = null; boot(); }
    }, 2500);
  }

  function render() {
    [...tabsEl.children].forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
    $('bimProps').style.display = 'none';
    if (!summary) return;
    if (tab === 'rooms') return renderRooms();
    if (tab === 'search') return renderSearch();
    const preset = TABS.find((t) => t[0] === tab)[2];
    if (tab === 'qto') {
      state.group = state.group && !['storey', 'phase', 'type'].includes(state.group) ? state.group : 'class';
    } else state.group = preset;
    renderGrouped();
  }

  async function renderGrouped() {
    const g = state.group;
    $('bimBar').innerHTML =
      (tab === 'qto' ? `<select id="fGroup">${['class', 'type', 'storey', 'phase', 'material', 'category', 'model'].map((x) => `<option value="${x}"${x === g ? ' selected' : ''}>Group by ${x}</option>`).join('')}</select>` : '') +
      sel('fCls', summary.classes.map((c) => c.cls), state.cls, 'All classes') +
      sel('fSt', summary.storeys.map((s) => s.storey), state.storey, 'All storeys') +
      sel('fPh', summary.phases.map((p) => p.phase), state.phase, 'All phases') +
      `<input id="fQ" placeholder="name / type…" value="${esc(state.q)}">` +
      `<a class="bb" id="fCsv" target="_blank">CSV</a>`;
    const bind = (id, key) => { const e = $(id); if (e) e.onchange = () => { state[key] = e.value; renderGrouped(); }; };
    bind('fGroup', 'group'); bind('fCls', 'cls'); bind('fSt', 'storey'); bind('fPh', 'phase');
    $('fQ').onkeydown = (e) => { if (e.key === 'Enter') { state.q = e.target.value; renderGrouped(); } };
    const f = { project, group: state.group, cls: state.cls, storey: state.storey, phase: state.phase, q: state.q };
    $('fCsv').href = '/api/ifc/qto.csv?' + qs(f);
    $('bimBody').innerHTML = '<div id="bimMsg">Loading…</div>';
    try {
      const d = await api('qto?' + qs(f));
      let rows = d.rows;
      if (state.group === 'storey') { const ord = new Map(summary.storeys.map((s, i) => [s.storey, i])); rows = rows.slice().sort((a, b) => (ord.get(a.key) ?? 1e9) - (ord.get(b.key) ?? 1e9)); }
      $('bimBody').innerHTML = `<table><thead><tr><th>${esc(state.group)}</th><th>Count</th><th>Area m²</th><th>Vol m³</th><th>Len m</th></tr></thead><tbody>` +
        rows.map((r, i) => `<tr class="r" data-i="${i}"><td title="${esc(r.key)}">${esc(r.key)}</td><td>${num(r.count, 0)}</td><td>${num(r.area)}</td><td>${num(r.volume)}</td><td>${num(r.length)}</td></tr>`).join('') +
        `<tr class="tot"><td>TOTAL</td><td>${num(d.total.count, 0)}</td><td>${num(d.total.area)}</td><td>${num(d.total.volume)}</td><td>${num(d.total.length)}</td></tr></tbody></table>`;
      $('bimInfo').textContent = 'Click a row to ' + mode() + ' those elements in 3D.';
      $('bimBody').querySelectorAll('tr.r').forEach((tr) => tr.onclick = async () => {
        const r = rows[+tr.dataset.i];
        const ef = { project, cls: state.cls, storey: state.storey, phase: state.phase, q: state.q, limit: 20000 };
        const p = GROUP_PARAM[state.group]; if (p) ef[p] = r.key === '(none)' ? '' : r.key;
        const e = await api('elements?' + qs(ef));
        act(e.elements, r.key);
      });
    } catch (e) { $('bimBody').innerHTML = `<div id="bimMsg">${esc(e.message)}</div>`; }
  }

  async function renderRooms() {
    $('bimBar').innerHTML = `<input id="rQ" placeholder="filter rooms…" style="max-width:170px">` + sel('rSt', summary.storeys.map((s) => s.storey), '', 'All storeys') + `<span id="rTot" style="margin-left:auto;color:var(--muted)"></span>`;
    $('bimBody').innerHTML = '<div id="bimMsg">Loading…</div>';
    let d;
    try { d = await api('spaces?' + qs({ project })); } catch (e) { $('bimBody').innerHTML = `<div id="bimMsg">${esc(e.message)}</div>`; return; }
    if (!d.spaces.length) { $('bimBody').innerHTML = '<div id="bimMsg">No rooms (IfcSpace) exist in this project\'s IFC models.</div>'; return; }
    const draw = () => {
      const t = $('rQ').value.toLowerCase(), st = $('rSt').value;
      const rows = d.spaces.filter((s) => (!st || s.storey === st) && (!t || `${s.name} ${s.number}`.toLowerCase().includes(t)));
      const tot = rows.reduce((a, s) => a + (s.area || 0), 0);
      $('rTot').textContent = `${rows.length.toLocaleString()} rooms · ${num(tot)} m²`;
      $('bimBody').innerHTML = `<table><thead><tr><th>Room</th><th>No.</th><th>Storey</th><th>Area m²</th></tr></thead><tbody>` +
        rows.slice(0, 600).map((s, i) => `<tr class="r" data-i="${i}"><td title="${esc(s.name)}">${esc(s.name)}</td><td>${esc(s.number || '')}</td><td>${esc(s.storey || '')}</td><td>${num(s.area, 2)}</td></tr>`).join('') + '</tbody></table>' +
        (rows.length > 600 ? `<div id="bimMsg">Showing first 600 of ${rows.length}. Use the filters.</div>` : '');
      $('bimBody').querySelectorAll('tr.r').forEach((tr) => tr.onclick = () => { const s = rows[+tr.dataset.i]; act([{ model: s.model, step_id: s.step_id }], s.name); });
    };
    $('rQ').oninput = draw; $('rSt').onchange = draw; draw();
    $('bimInfo').textContent = 'Click a room to ' + mode() + ' it in 3D (rooms must be loaded in the viewer).';
  }

  async function renderSearch() {
    $('bimBar').innerHTML = '';
    let names = [];
    try { names = (await api('prop-names?' + qs({ project }))).props; } catch (e) {}
    $('bimBody').innerHTML = `<div id="bimSearchBox">
      <input id="sQ" placeholder="text / GlobalId" style="flex:1 1 120px">
      <input id="sP" list="sPL" placeholder="property (e.g. Mark)" style="flex:1 1 110px"><datalist id="sPL">${[...new Set(names.map((n) => n.name))].slice(0, 200).map((n) => `<option value="${esc(n)}">`).join('')}</datalist>
      <input id="sV" placeholder="value contains" style="flex:1 1 110px">
      ${sel('sC', summary.classes.map((c) => c.cls), '', 'Any class')}
      <button class="bb" id="sGo">Search</button><button class="bb" id="sAll" style="display:none">${'Apply to all'}</button></div><div id="sRes"></div>`;
    let results = [];
    const go = async () => {
      const f = { project, q: $('sQ').value, prop: $('sP').value, value: $('sV').value, cls: $('sC').value, limit: 2000 };
      if (!f.q && !f.prop && !f.value) { $('sRes').innerHTML = '<div id="bimMsg">Enter text, a property name, or a value.</div>'; return; }
      $('sRes').innerHTML = '<div id="bimMsg">Searching…</div>';
      try { results = (await api('search?' + qs(f))).results; } catch (e) { $('sRes').innerHTML = `<div id="bimMsg">${esc(e.message)}</div>`; return; }
      $('sAll').style.display = results.length ? '' : 'none';
      $('sRes').innerHTML = `<table><thead><tr><th>Name</th><th>Class</th><th>Storey</th><th>Type</th></tr></thead><tbody>` +
        results.slice(0, 500).map((r, i) => `<tr class="r" data-i="${i}"><td title="${esc(r.name)}">${esc(r.name)}</td><td>${esc(r.cls.replace('IFC', ''))}</td><td>${esc(r.storey || '')}</td><td title="${esc(r.type_name)}">${esc(r.type_name || '')}</td></tr>`).join('') + '</tbody></table>';
      $('bimInfo').textContent = `${results.length.toLocaleString()} match(es).`;
      $('sRes').querySelectorAll('tr.r').forEach((tr) => tr.onclick = async () => {
        const r = results[+tr.dataset.i];
        act([{ model: r.model, step_id: r.step_id }], r.name);
        const p = await api('element-props?' + qs({ project, id: r.id })).catch(() => ({ props: [] }));
        const by = {}; p.props.forEach((x) => (by[x.pset] = by[x.pset] || []).push(`${esc(x.name)}: ${esc(x.value)}`));
        $('bimProps').style.display = 'block';
        $('bimProps').innerHTML = Object.entries(by).map(([k, v]) => `<div><b>${esc(k)}</b><br>${v.join(' &middot; ')}</div>`).join('');
      });
    };
    $('sGo').onclick = go; ['sQ', 'sP', 'sV'].forEach((id) => $(id).onkeydown = (e) => e.key === 'Enter' && go());
    $('sAll').onclick = () => act(results.map((r) => ({ model: r.model, step_id: r.step_id })), 'search results');
  }
})();
