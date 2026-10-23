/**
 * Early Design – Feasibility & Massing
 * Site from the Masterplan (plot number), a DXF, or a manual size -> massing options
 * with calculated GFA / FAR / coverage / height / units / parking -> typical floor plan
 * -> concept visual on request.
 */
(function () {
  const H = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const N = (v, d = 0) => (v == null || v === '' || isNaN(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const say = (t) => (typeof toast === 'function' ? toast(t) : console.log(t));
  const base = () => (typeof API !== 'undefined' ? API : window.location.origin);
  const jget = async (url, opt) => {
    const r = await fetch(base() + url, opt);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || 'Request failed');
    return j;
  };
  const jpost = (url, body) => jget(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const presentation = window.EarlyDesignPresentation;

  const ST = (window.edState = window.edState && window.edState.v3 ? window.edState : {
    v3: true, source: 'mpd', mpdProject: '', mpdProjects: [], plotList: [], plotNo: '', plotInfo: null,
    inputs: {
      plot_w: 125, plot_d: 100, plot: null, context: [], site_name: '', front_edge: 0, front_edges: [],
      setback_front: 6, setback_side: 4.5, setback_rear: 6,
      target_gfa: 35000, max_far: 5, max_coverage: 45, max_height: 120, max_floors: 40,
      podium_floors: 3, tower_floorplate: 1100, tower_spacing: 18,
      res_share: 80, com_share: 15, avg_unit_nsa: 85, efficiency: 80,
      park_per_unit: 1, park_visitor_pct: 10, park_com_per_m2: 50, bay_area: 30,
    },
    result: null, plans: {}, current: 0, view: 'floor', busy: false, render: {}, showRender: false, openSec: { limits: true },
  });

  const SECTIONS = [
    ['limits', 'Planning limits', [['target_gfa', 'Target GFA (m²)', 500], ['max_far', 'Max FAR', 0.01], ['max_coverage', 'Max coverage (%)', 1],
      ['max_floors', 'Max floors', 1], ['max_height', 'Max height (m)', 1]]],
    ['setbacks', 'Setbacks (m)', [['setback_front', 'Front (road)', 0.5], ['setback_side', 'Side', 0.5], ['setback_rear', 'Rear', 0.5]]],
    ['programme', 'Programme', [['res_share', 'Residential (%)', 1], ['com_share', 'Retail / office (%)', 1],
      ['avg_unit_nsa', 'Avg. unit size (m²)', 1], ['efficiency', 'Efficiency (%)', 1]]],
    ['massing', 'Massing', [['podium_floors', 'Podium floors', 1], ['tower_floorplate', 'Tower floorplate (m²)', 50], ['tower_spacing', 'Tower spacing (m)', 1]]],
    ['parking', 'Parking rules', [['park_per_unit', 'Bays per unit', 0.1], ['park_visitor_pct', 'Visitor (%)', 1],
      ['park_com_per_m2', 'Retail: 1 bay / m²', 5], ['bay_area', 'm² per bay', 1]]],
  ];

  function payload() {
    const i = ST.inputs;
    const plot = i.plot || [[0, 0], [i.plot_w, 0], [i.plot_w, i.plot_d], [0, i.plot_d]];
    const out = { plot, context: i.context || [], front_edge: Number(i.front_edge) || 0, front_edges: i.plot ? i.front_edges || [] : [] };
    for (const [, , list] of SECTIONS) for (const [k] of list) out[k] = Number(i[k]);
    return out;
  }

  // ------------------------------------------------------------------ drawings
  const COL = { podium: '#5b8def', tower: '#2bb3a8', block: '#d9a441', slab: '#d9a441' };
  const PCOL = { stair: '#f6d365', lift: '#9cc3ff', lift_fire: '#ff8f8f', lift_service: '#c4b5fd', lobby: '#f1f3f6', riser: '#b7bdc7', chute: '#c8a98a', store: '#dde1e7' };
  const UCOL = { Studio: '#c9e4f6', '1 Bed': '#cfe8d0', '2 Bed': '#f6e3b8', '3 Bed': '#f3cfc7', Tenancy: '#dcd6f2' };
  const path = (s) => 'M' + s.outer.map((p) => `${p[0]},${-p[1]}`).join('L') + 'Z' + (s.holes || []).map((h) => 'M' + h.map((p) => `${p[0]},${-p[1]}`).join('L') + 'Z').join('');
  const cen = (pts) => [pts.reduce((t, p) => t + p[0], 0) / pts.length, pts.reduce((t, p) => t + p[1], 0) / pts.length];
  function vbox(pts, padF = 0.06) {
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pad = Math.max(x1 - x0, y1 - y0) * padF;
    return [x0 - pad, -(y1 + pad), x1 - x0 + 2 * pad, y1 - y0 + 2 * pad];
  }
  function scaleBar(vb, sw) {
    const len = vb[2] > 300 ? 50 : vb[2] > 120 ? 20 : 10;
    const x = vb[0] + vb[2] * 0.04, y = vb[1] + vb[3] * 0.96;
    return `<line x1="${x}" y1="${y}" x2="${x + len}" y2="${y}" stroke="currentColor" stroke-width="${sw * 2.5}"/><text x="${x}" y="${y - sw * 6}" font-size="${sw * 10}" fill="currentColor">${len} m</text>`;
  }

  // ---- shared CAD-style viewer: real coordinates in metres, pan / zoom / measure / snap
  const fmt = (v) => (Math.round(v * 100) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 });
  function edgeDims(ring, sw, minLen, color, roles, setbacks) {
    let g = '';
    const c = cen(ring);
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i], b = ring[(i + 1) % ring.length];
      const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const role = roles ? roles[i] : null;
      const sb = role && setbacks ? setbacks[role] : null;
      const tip = `Edge ${i + 1} · ${fmt(L)} m${role ? ' · ' + role + (sb != null ? ' (setback ' + sb + ' m)' : '') : ''}`;
      g += `<line class="ed-hit" x1="${a[0]}" y1="${-a[1]}" x2="${b[0]}" y2="${-b[1]}" stroke="transparent" stroke-width="${sw * 8}"><title>${H(tip)}</title></line>`;
      if (L < minLen) continue;
      const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      let nx = -(b[1] - a[1]) / L, ny = (b[0] - a[0]) / L;
      if ((mx + nx - c[0]) ** 2 + (my + ny - c[1]) ** 2 < (mx - c[0]) ** 2 + (my - c[1]) ** 2) { nx = -nx; ny = -ny; }
      let ang = Math.atan2(-(b[1] - a[1]), b[0] - a[0]) * 180 / Math.PI;
      if (ang > 90) ang -= 180; if (ang < -90) ang += 180;
      const tx = mx + nx * sw * 9, ty = my + ny * sw * 9;
      g += `<text x="${tx}" y="${-ty}" font-size="${sw * 8}" fill="${color}" text-anchor="middle" dominant-baseline="middle" transform="rotate(${ang} ${tx} ${-ty})">${fmt(L)}</text>`;
    }
    return g;
  }

  function viewer(key, content, fitVb, light) {
    ST.vb = ST.vb || {};
    const vb = ST.vb[key] && ST.vb[key].fit === fitVb.join(',') ? ST.vb[key].vb : fitVb;
    ST.vb[key] = { vb, fit: fitVb.join(',') };
    return `<div class="ed-vw" data-key="${key}">
      <svg id="edSvg" viewBox="${vb.join(' ')}" class="ed-svg" style="${light ? 'background:#fbfbfc' : ''}" preserveAspectRatio="xMidYMid meet">${content}<g id="edMeasure"></g></svg>
      <div class="ed-vw-tools">
        <button class="tb" onclick="edFit()" title="Zoom to fit">Fit</button>
        ${key === 'floor' ? `<button class="tb ${ST.showGrid !== false ? 'on2' : ''}" onclick="edGridToggle()" title="Show / hide the column grid">Grid</button>` : ''}
        <button class="tb ${ST.measure ? 'on' : ''}" onclick="edMeasureToggle()" title="Click two points to measure (snaps to corners)">Measure</button>
      </div>
      <div class="ed-vw-xy" id="edXY">x – · y – m</div>
    </div>`;
  }

  function snapPoints() {
    const pts = [];
    const res = ST.result; if (!res) return pts;
    const add = (ring) => ring.forEach((p) => pts.push(p));
    res.plot.shapes.forEach((s) => add(s.outer));
    res.buildable.shapes.forEach((s) => add(s.outer));
    const opt = res.options[ST.current];
    opt && opt.masses.forEach((m) => m.shapes.forEach((s) => { add(s.outer); (s.holes || []).forEach(add); }));
    const fp = ST.view === 'floor' ? ST.plans[planKey()] : null;
    if (fp && fp.units) { fp.units.forEach((u) => u.shapes.forEach((s) => add(s.outer))); fp.cores.forEach((s) => add(s.outer)); }
    (ST.cad?.lines || []).forEach((l) => add(l.pts));
    return pts;
  }

  function bindViewer() {
    const svg = document.getElementById('edSvg');
    if (!svg) return;
    const key = svg.parentElement.dataset.key;
    const getVb = () => svg.getAttribute('viewBox').split(/\s+/).map(Number);
    const setVb = (v) => { svg.setAttribute('viewBox', v.join(' ')); ST.vb[key].vb = v; };
    const toWorld = (ev) => {
      const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
      const q = pt.matrixTransform(svg.getScreenCTM().inverse());
      return [q.x, q.y];
    };
    const snaps = key === 'axo' ? [] : snapPoints();
    const snap = (w) => {
      const v = getVb(), tol = v[2] / 60;
      let best = null, bd = tol;
      for (const p of snaps) { const d = Math.hypot(p[0] - w[0], -p[1] - w[1]); if (d < bd) { bd = d; best = p; } }
      return best ? [best[0], -best[1], true] : [w[0], w[1], false];
    };
    svg.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const v = getVb(), w = toWorld(ev), k = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
      setVb([w[0] - (w[0] - v[0]) * k, w[1] - (w[1] - v[1]) * k, v[2] * k, v[3] * k]);
      drawMeasure();
    }, { passive: false });
    let drag = null, moved = false;
    svg.addEventListener('mousedown', (ev) => { drag = { x: ev.clientX, y: ev.clientY, vb: getVb() }; moved = false; });
    window.onmouseup = () => { drag = null; };
    svg.addEventListener('mousemove', (ev) => {
      const w = toWorld(ev);
      const xy = document.getElementById('edXY');
      if (xy && key !== 'axo') {
        const s = ST.measure ? snap(w) : [w[0], w[1], false];
        xy.textContent = `x ${fmt(s[0])} · y ${fmt(-s[1])} m${s[2] ? ' · corner' : ''}`;
        if (ST.measure && ST.mPts && ST.mPts.length === 1) drawMeasure([s[0], s[1]]);
      }
      if (!drag) return;
      const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      const r = svg.getBoundingClientRect(), v = drag.vb;
      const sc = Math.max(v[2] / r.width, v[3] / r.height);
      setVb([v[0] - dx * sc, v[1] - dy * sc, v[2], v[3]]);
    });
    svg.addEventListener('click', (ev) => {
      if (moved || !ST.measure || key === 'axo') return;
      const s = snap(toWorld(ev));
      ST.mPts = (ST.mPts && ST.mPts.length === 1) ? [ST.mPts[0], [s[0], s[1]]] : [[s[0], s[1]]];
      drawMeasure();
    });
    drawMeasure();
  }

  function drawMeasure(live) {
    const g = document.getElementById('edMeasure');
    if (!g) return;
    const svg = document.getElementById('edSvg');
    const v = svg.getAttribute('viewBox').split(/\s+/).map(Number), sw = v[2] / 450;
    const pts = (ST.mPts || []).slice();
    if (live && pts.length === 1) pts.push(live);
    if (!ST.measure || !pts.length) { g.innerHTML = ''; return; }
    let h = pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="${sw * 2.5}" fill="#ff4fd8"/>`).join('');
    if (pts.length === 2) {
      const [a, b] = pts, d = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      h += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#ff4fd8" stroke-width="${sw * 1.6}" stroke-dasharray="${sw * 4} ${sw * 2}"/>
        <rect x="${mx - sw * 26}" y="${my - sw * 16}" width="${sw * 52}" height="${sw * 12}" rx="${sw * 2}" fill="#ff4fd8"/>
        <text x="${mx}" y="${my - sw * 10}" font-size="${sw * 8}" fill="#fff" text-anchor="middle" dominant-baseline="middle" font-weight="700">${fmt(d)} m</text>`;
    }
    g.innerHTML = h;
  }

  function cadBackdrop(sw) {
    let g = '';
    const cad = ST.cad || {};
    (cad.lines || []).forEach((l) => {
      const col = /road/i.test(l.layer) ? '#6b7385' : /plot|mixed|resid|commer|hosp|civic|util|open|park|public/i.test(l.layer) ? '#4d5568' : '#3a4152';
      g += `<polyline points="${l.pts.map((p) => `${p[0]},${-p[1]}`).join(' ')}${l.closed ? ' ' + l.pts[0][0] + ',' + -l.pts[0][1] : ''}" fill="none" stroke="${col}" stroke-width="${sw * 0.8}"><title>${H(l.layer)}</title></polyline>`;
    });
    (cad.labels || []).forEach((t) => (g += `<text x="${t.x}" y="${-t.y}" font-size="${sw * 7}" fill="#7d8597" text-anchor="middle">${H(t.t)}</text>`));
    return g;
  }

  function plotFrame(res, sw, light) {
    let g = '';
    const roles = (res.plot.edges || []).map((e) => e.role);
    const sbs = { front: ST.inputs.setback_front, side: ST.inputs.setback_side, rear: ST.inputs.setback_rear };
    res.plot.shapes.forEach((s) => (g += `<path d="${path(s)}" fill="${light ? 'none' : 'rgba(255,255,255,.02)'}" stroke="#e5534b" stroke-width="${sw * 1.6}"/>`));
    const po = res.plot.shapes[0].outer;
    (res.plot.front_edges || [res.plot.front_edge]).forEach((fe) => {
      const a = po[fe], b = po[(fe + 1) % po.length];
      if (a && b) g += `<line x1="${a[0]}" y1="${-a[1]}" x2="${b[0]}" y2="${-b[1]}" stroke="#e0a526" stroke-width="${sw * 3}"/>`;
    });
    res.buildable.shapes.forEach((s) => (g += `<path d="${path(s)}" fill="none" stroke="#e0a526" stroke-dasharray="${sw * 5} ${sw * 3}" stroke-width="${sw * 0.9}"/>`));
    g += edgeDims(po, sw, 6, light ? '#c0392b' : '#ff8a80', roles, sbs);
    return g;
  }

  function sitePlan(res, opt) {
    let pts = [];
    res.plot.shapes.forEach((s) => (pts = pts.concat(s.outer)));
    const vb = vbox(pts, 0.3), sw = vb[2] / 450;
    let g = cadBackdrop(sw);
    (res.context || []).forEach((c) => (g += `<polygon points="${c.map((p) => `${p[0]},${-p[1]}`).join(' ')}" fill="rgba(138,147,166,.18)" stroke="none"/>`));
    g += plotFrame(res, sw, false);
    const ms = [...opt.masses].sort((a, b) => a.top_m - b.top_m);
    ms.forEach((m) => m.shapes.forEach((s) => {
      g += `<path d="${path(s)}" fill-rule="evenodd" fill="${COL[m.use] || '#888'}" fill-opacity="0.75" stroke="#fff" stroke-width="${sw * 0.8}"><title>${H(m.use)} · ${m.floors} floors · ${N(m.area_m2)} m² · ${m.base_m}–${m.top_m} m</title></path>`;
    }));
    // labels: towers at their centre, podium in its largest free corner (never on top of a tower)
    ms.forEach((m) => m.shapes.forEach((s) => {
      let c = cen(s.outer);
      if (m.use === 'podium') {
        const towers = opt.masses.filter((x) => x.use === 'tower').flatMap((x) => x.shapes.map((q) => cen(q.outer)));
        if (towers.length) {
          c = s.outer.map((p) => [(p[0] * 2 + c[0]) / 3, (p[1] * 2 + c[1]) / 3])
            .sort((a, b) => Math.min(...towers.map((t) => Math.hypot(t[0] - b[0], t[1] - b[1]))) - Math.min(...towers.map((t) => Math.hypot(t[0] - a[0], t[1] - a[1]))))[0];
        }
      }
      const label = m.use === 'podium' ? `Podium ${m.floors}F` : m.use === 'tower' ? `Tower ${m.floors}F` : `${m.floors}F`;
      g += `<text x="${c[0]}" y="${-c[1]}" fill="#fff" font-size="${sw * 9}" font-weight="700" text-anchor="middle" dominant-baseline="middle" style="paint-order:stroke;stroke:#0008;stroke-width:${sw * 2}px">${label}</text>`;
    }));
    g += scaleBar(vb, sw) + northArrow(vb, sw);
    return viewer('site', g, vb, false);
  }

  function northArrow(vb, sw) {
    const x = vb[0] + vb[2] * 0.95, y = vb[1] + vb[3] * 0.08, s = sw * 10;
    return `<g><path d="M${x},${y - s} L${x + s * 0.45},${y + s * 0.6} L${x},${y + s * 0.3} L${x - s * 0.45},${y + s * 0.6}Z" fill="currentColor"/><text x="${x}" y="${y - s * 1.3}" font-size="${sw * 8}" fill="currentColor" text-anchor="middle">N</text></g>`;
  }

  function axo(res, opt) {
    const scene = presentation.massingScene(res, opt);
    return viewer('axo', scene.content, scene.viewBox, true);
  }

  function floorSvg(fp) {
    const res = ST.result, opt = res.options[ST.current];
    let pts = [];
    fp.footprint.forEach((s) => (pts = pts.concat(s.outer)));
    res.plot.shapes.forEach((s) => (pts = pts.concat(s.outer)));
    const vb = vbox(pts, 0.08), sw = vb[2] / 500;
    let g = '';
    // site context drawn exactly as on the site plan (same coordinates and orientation)
    res.plot.shapes.forEach((s) => (g += `<path d="${path(s)}" fill="#eef3ea" stroke="none"/>`));
    g += plotFrame(res, sw, true);
    opt.masses.forEach((m) => m.shapes.forEach((s) => (g += `<path d="${path(s)}" fill-rule="evenodd" fill="#e2e5ea" stroke="#9aa1ad" stroke-width="${sw * 0.7}" stroke-dasharray="${sw * 3} ${sw * 2}"/>`)));
    fp.footprint.forEach((s) => (g += `<path d="${path(s)}" fill-rule="evenodd" fill="#f8f9fa" stroke="none"/>`));
    fp.corridor.forEach((s) => (g += `<path d="${path(s)}" fill-rule="evenodd" fill="#e6e8ec" stroke="#b9bec8" stroke-width="${sw * 0.5}"><title>Corridor ${fp.summary.corridor_width_m} m</title></path>`));
    fp.shafts.forEach((s) => (g += `<path d="${path(s)}" fill="#d0d4db"><title>Shaft / services</title></path>`));
    fp.units.forEach((u) => u.shapes.forEach((s) => {
      g += `<path d="${path(s)}" fill="${UCOL[u.type] || '#ddd'}" stroke="#4a4f59" stroke-width="${sw * 1}"><title>${H(u.type)} ${u.id} · ${u.area_m2} m²</title></path>`;
      const c = cen(s.outer), fs = Math.max(sw * 4, Math.min(sw * 8, Math.sqrt(u.area_m2) * 0.28));
      g += `<text x="${c[0]}" y="${-c[1]}" text-anchor="middle" font-size="${fs}" fill="#22252b" pointer-events="none"><tspan x="${c[0]}" dy="-0.2em" font-weight="700">${H(u.type)}</tspan><tspan x="${c[0]}" dy="1.15em">${u.area_m2} m²</tspan></text>`;
    }));
    if (fp.core_parts && fp.core_parts.length) {
      fp.cores.forEach((s) => (g += `<path d="${path(s)}" fill="#cfd4dc" stroke="none"/>`));
      fp.core_parts.forEach((cp) => {
        const s = cp.shape;
        g += `<path d="${path(s)}" fill="${PCOL[cp.type] || '#ccc'}" stroke="#22252b" stroke-width="${sw * 0.7}"><title>${H(cp.label)}</title></path>`;
        if (cp.type === 'stair') {
          // flight lines
          const o = s.outer, c = cen(o);
          g += `<line x1="${(o[0][0] + o[1][0]) / 2}" y1="${-(o[0][1] + o[1][1]) / 2}" x2="${(o[2][0] + o[3][0]) / 2}" y2="${-(o[2][1] + o[3][1]) / 2}" stroke="#22252b" stroke-width="${sw * 0.5}"/>`;
        }
        if (cp.type.startsWith('lift')) {
          const o = s.outer;
          g += `<line x1="${o[0][0]}" y1="${-o[0][1]}" x2="${o[2][0]}" y2="${-o[2][1]}" stroke="#22252b" stroke-width="${sw * 0.4}"/><line x1="${o[1][0]}" y1="${-o[1][1]}" x2="${o[3][0]}" y2="${-o[3][1]}" stroke="#22252b" stroke-width="${sw * 0.4}"/>`;
        }
        const c = cen(s.outer);
        g += `<text x="${c[0]}" y="${-c[1]}" text-anchor="middle" dominant-baseline="middle" font-size="${sw * 3.6}" fill="#111" font-weight="700" pointer-events="none" style="paint-order:stroke;stroke:#ffffffcc;stroke-width:${sw * 0.8}px">${H(cp.label)}</text>`;
      });
      fp.cores.forEach((s) => (g += `<path d="${path(s)}" fill="none" stroke="#22252b" stroke-width="${sw * 1.6}"/>`));
    } else {
      fp.cores.forEach((s) => {
        g += `<path d="${path(s)}" fill="#3d4350" stroke="#22252b" stroke-width="${sw}"><title>${H(fp.core_label || 'Core')}</title></path>`;
        const c = cen(s.outer);
        g += `<text x="${c[0]}" y="${-c[1]}" text-anchor="middle" dominant-baseline="middle" font-size="${sw * 6}" fill="#fff" font-weight="600" pointer-events="none">${H(fp.core_label || 'CORE')}</text>`;
      });
    }
    if (fp.grid && ST.showGrid !== false) {
      fp.grid.axes.forEach((ax) => {
        const [a, b] = ax.pts;
        g += `<line x1="${a[0]}" y1="${-a[1]}" x2="${b[0]}" y2="${-b[1]}" stroke="#d6453d" stroke-width="${sw * 0.35}" stroke-dasharray="${sw * 6} ${sw * 1.5} ${sw * 1} ${sw * 1.5}" pointer-events="none"/>
          <circle cx="${a[0]}" cy="${-a[1]}" r="${sw * 3.2}" fill="#fff" stroke="#d6453d" stroke-width="${sw * 0.5}"/>
          <text x="${a[0]}" y="${-a[1]}" font-size="${sw * 3.6}" fill="#d6453d" text-anchor="middle" dominant-baseline="middle" font-weight="700">${H(ax.label)}</text>`;
      });
      fp.grid.columns.forEach((c) => (g += `<polygon points="${c.map((p) => `${p[0]},${-p[1]}`).join(' ')}" fill="#22252b"><title>Column</title></polygon>`));
    }
    fp.footprint.forEach((s) => { g += `<path d="${path(s)}" fill="none" stroke="#22252b" stroke-width="${sw * 2.2}"/>`; g += edgeDims(s.outer, sw, 4, '#22252b'); });
    g += `<g style="color:#4a4f59">${scaleBar(vb, sw)}${northArrow(vb, sw)}</g>`;
    return viewer('floor', g, vb, true);
  }

  // ------------------------------------------------------------------ panels
  function sitePanel() {
    const i = ST.inputs;
    const tab = (k, l) => `<button class="ed-seg ${ST.source === k ? 'on' : ''}" onclick="edSource('${k}')">${l}</button>`;
    let body = '';
    if (ST.source === 'mpd') {
      body = `<label class="ed-l">Masterplan
          <select onchange="edMpdProject(this.value)">${ST.mpdProjects.length ? ST.mpdProjects.map((p) => `<option ${p.project_id === ST.mpdProject ? 'selected' : ''} value="${H(p.project_id)}">${H(p.name)}</option>`).join('') : '<option>No masterplan available</option>'}</select></label>
        <label class="ed-l">Plot number
          <div style="display:flex;gap:6px"><input id="edPlotNo" list="edPlotList" value="${H(ST.plotNo)}" placeholder="e.g. P-5210754" onkeydown="if(event.key==='Enter')edLoadPlot()" style="flex:1">
          <button class="primary" onclick="edLoadPlot()">Load</button></div></label>
        <datalist id="edPlotList">${ST.plotList.filter((p) => p.has_outline).map((p) => `<option value="${H(p.plot_id)}">${H(p.land_use || '')} · ${N(p.area_sqm)} m²</option>`).join('')}</datalist>`;
      if (ST.plotInfo) {
        const p = ST.plotInfo;
        body += `<div class="ed-info"><div class="ed-info-h">${H(p.plot_id)} <span>${H(p.land_use || '')}</span></div>
          <div class="ed-kv"><span>Sector</span><b>${H(p.sector || '–')}</b><span>Plot area</span><b>${N(p.area_sqm)} m²</b>
          <span>Permitted GFA</span><b>${N(p.permitted_gfa)} m²</b><span>Height</span><b>${H(p.max_height || '–')}</b>
          <span>Basements</span><b>${p.basements_allowed ?? '–'}</b></div>
          <div class="ed-muted">Limits below are filled from the masterplan plot schedule. Road frontage is detected from the adjoining road plots.</div></div>`;
      }
    } else if (ST.source === 'dxf') {
      body = `<label class="ed-l">Site DXF (closed polyline, layer PLOT / SITE)<input type="file" accept=".dxf" onchange="edLoadDxf(this.files[0])"></label>
        ${i.plot && i.site_name ? `<div class="ed-muted">Loaded <b>${H(i.site_name)}</b> · ${i.plot.length} corners · ${i.context.length} surrounding buildings</div>` : ''}`;
    } else {
      body = `<div class="ed-grid"><label class="ed-l">Width (m)<input type="number" value="${i.plot_w}" onchange="edSet('plot_w',this.value)"></label>
        <label class="ed-l">Depth (m)<input type="number" value="${i.plot_d}" onchange="edSet('plot_d',this.value)"></label></div>
        <label class="ed-l">Road side<select onchange="edSet('front_edge',this.value)">${['South', 'East', 'North', 'West'].map((n, k) => `<option value="${k}" ${+i.front_edge === k ? 'selected' : ''}>${n}</option>`).join('')}</select></label>`;
    }
    let secs = '';
    for (const [key, title, list] of SECTIONS) {
      const open = ST.openSec[key];
      secs += `<div class="ed-acc"><button class="ed-acc-h" onclick="edToggle('${key}')">${H(title)}<span>${open ? '−' : '+'}</span></button>
        ${open ? `<div class="ed-grid">${list.map(([k, l, s]) => `<label class="ed-l">${H(l)}<input type="number" step="${s}" value="${i[k]}" onchange="edSet('${k}',this.value)"></label>`).join('')}</div>` : ''}</div>`;
    }
    return `<div class="ed-card">
        <div class="ed-step"><span>1</span>Site</div>
        <div class="ed-segs">${tab('mpd', 'Masterplan plot')}${tab('dxf', 'DXF')}${tab('manual', 'Manual')}</div>
        ${body}
      </div>
      <div class="ed-card">
        <div class="ed-step"><span>2</span>Brief</div>
        ${secs}
        ${rulesSection()}
        <button class="primary" style="width:100%;margin-top:10px" onclick="edCalculate()" ${ST.busy ? 'disabled' : ''}>${ST.busy ? 'Calculating…' : 'Generate options'}</button>
      </div>`;
  }

  function rulesSection() {
    const open = ST.openSec.rules;
    let body = '';
    if (open) {
      if (!ST.rules) { body = '<div class="ed-muted">Loading…</div>'; loadRules(); }
      else {
        const groups = {};
        ST.rules.rules.forEach((r) => (groups[r.group] = groups[r.group] || []).push(r));
        body = Object.entries(groups).map(([gname, list]) => `<div class="ed-muted" style="margin:8px 0 4px;font-weight:700">${H(gname)}</div>
          <div class="ed-grid">${list.map((r) => `<label class="ed-l" title="${H(r.note || '')}">${H(r.label)}${r.unit ? ' (' + H(r.unit) + ')' : ''}${r.changed ? ' •' : ''}
            <input type="number" step="any" value="${r.value}" ${ST.rules.can_edit ? '' : 'disabled'} onchange="edRuleSet('${r.key}',this.value)"></label>`).join('')}</div>`).join('');
        body += ST.rules.can_edit
          ? `<button class="tb" style="margin-top:6px" onclick="edRulesSave()">Save rules</button> <span class="ed-muted">Placeholders: confirm against the authority rules. • = changed from default.</span>`
          : `<div class="ed-muted">Only admins and leads can change rules.</div>`;
      }
    }
    return `<div class="ed-acc"><button class="ed-acc-h" onclick="edToggle('rules')">Design rules<span>${open ? '−' : '+'}</span></button>${body}</div>`;
  }
  async function loadRules() {
    try { ST.rules = await jget('/api/early-design/rules'); ST.ruleEdits = {}; } catch (e) { say(e.message); ST.rules = { rules: [], can_edit: false }; }
    draw();
  }
  window.edRuleSet = (k, v) => { ST.ruleEdits = ST.ruleEdits || {}; ST.ruleEdits[k] = v; };
  window.edRulesSave = async () => {
    try {
      ST.rules = await jget('/api/early-design/rules', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ changes: ST.ruleEdits || {} }) });
      ST.ruleEdits = {}; ST.plans = {}; say('Rules saved'); draw(); if (ST.view === 'floor') loadPlan(ST.current);
    } catch (e) { say(e.message); }
  };

  function resultsPanel() {
    const res = ST.result;
    if (!res) return `<div class="ed-card ed-empty">Select a masterplan plot (or enter a site) and press <b>Generate options</b>.</div>`;
    const opt = res.options[ST.current] || res.options[0];
    const m = opt.metrics;
    const cards = res.options.map((o, k) => `<button class="ed-opt ${k === ST.current ? 'on' : ''}" onclick="edPick(${k})">
        <div class="ed-opt-t">${H(o.name)}</div>
        <div class="ed-opt-m">${N(o.metrics.gfa)} m² · FAR ${o.metrics.far} · ${o.metrics.storeys} fl.</div>
        <div class="ed-pill ${o.passes ? 'ok' : 'bad'}">${o.passes ? 'Compliant' : o.checks.filter((c) => !c.ok).length + ' issue' + (o.checks.filter((c) => !c.ok).length > 1 ? 's' : '')}</div></button>`).join('');
    const view = (k, l) => `<button class="ed-seg ${ST.view === k ? 'on' : ''}" onclick="edView('${k}')">${l}</button>`;
    const fp = ST.plans[planKey()];
    let drawing;
    if (ST.view === 'floor') drawing = fp ? (fp.error ? `<div class="ed-empty">${H(fp.error)}</div>` : floorSvg(fp)) : `<div class="ed-empty">Preparing floor plan…</div>`;
    else if (ST.view === 'board') drawing = conceptBoard();
    else if (ST.view === 'site') drawing = sitePlan(res, opt);
    else drawing = axo(res, opt);
    const legend = ST.view === 'floor'
      ? (fp && fp.units ? Object.keys(fp.summary.unit_mix).map((t) => `<span><i style="background:${UCOL[t]}"></i>${t}</span>`).join('') + '<span><i style="background:#e6e8ec"></i>Corridor</span><span><i style="background:#f6d365"></i>Stair</span><span><i style="background:#9cc3ff"></i>Lift</span><span><i style="background:#ff8f8f"></i>Fire lift</span><span><i style="background:#c4b5fd"></i>Service lift</span><span><i style="background:#b7bdc7"></i>Risers</span><span><i style="background:#d6453d"></i>Grid</span><span><i style="background:#e2e5ea;border:1px dashed #9aa1ad"></i>Other masses</span><span><i style="background:#e5534b"></i>Plot</span>' : '')
      : `<span><i style="background:#e5534b"></i>Plot</span><span><i style="background:#e0a526"></i>Road frontage / setback line</span>${(res.context || []).length ? '<span><i style="background:#8a93a6"></i>Neighbours</span>' : ''}`;
    const tile = (l, v, s) => `<div class="ed-tile"><div class="ed-muted">${l}</div><div class="ed-big">${v}</div><div class="ed-muted">${s || ''}</div></div>`;
    const checks = opt.checks.map((c) => `<tr><td>${H(c.rule)}</td><td>${H(c.limit)}</td><td>${H(c.value)}</td><td><span class="ed-pill ${c.ok ? 'ok' : 'bad'}">${c.ok ? 'OK' : 'Fails'}</span></td></tr>`).join('');
    const fpBlock = fp && fp.summary ? `<div class="ed-card"><div class="ed-h">${fp.level === 'podium' ? 'Podium level' : 'Typical floor'} – ${H(fp.mass)}${fp.floors ? ' (' + fp.floors + ' floors)' : ''}</div>
        <div class="ed-tiles">${tile(fp.use === 'office' ? 'Tenancies / floor' : 'Units / floor', fp.summary.units_per_floor, N(fp.summary.units_in_this_mass) + ' in this building')}
        ${tile('Efficiency', fp.summary.efficiency_pct + '%', N(fp.summary.net_sellable_m2) + ' / ' + N(fp.summary.gross_m2) + ' m²')}
        ${tile('Unit depth', fp.summary.unit_depth_m + ' m', 'corridor ' + fp.summary.corridor_width_m + ' m · ' + fp.summary.cores + ' core(s)')}</div>
        <table class="ed-tbl"><tr><th>Type</th><th>Count / floor</th></tr>${Object.entries(fp.summary.unit_mix).map(([t, n]) => `<tr><td>${H(t)}</td><td>${n}</td></tr>`).join('')}</table>
        ${fp.checks && fp.checks.length ? `<div class="ed-h" style="margin-top:12px">Cores and escape</div>
          <table class="ed-tbl"><tr><th>Check</th><th>Requirement</th><th>Design</th><th></th></tr>${fp.checks.map((c) => `<tr><td>${H(c.rule)}</td><td>${H(c.limit)}</td><td>${H(c.value)}</td><td><span class="ed-pill ${c.ok ? 'ok' : 'bad'}">${c.ok ? 'OK' : 'Fails'}</span></td></tr>`).join('')}</table>
          <div class="ed-muted" style="margin-top:6px">Rule values are placeholders until confirmed in Brief › Design rules. Travel distance is a straight-line early-design check.</div>` : ''}</div>` : '';
    const r = ST.render[ST.current] || {};
    const renderBlock = ST.showRender ? `<div class="ed-card"><div class="ed-h" style="display:flex;justify-content:space-between">Concept visual <button class="tb" onclick="edShowRender(false)">Close</button></div>
        <div class="ed-render">
          <div class="ed-render-img">${r.img ? `<a href="${r.file}" target="_blank"><img src="${r.img}"></a>` : `<span class="ed-muted">${r.busy ? H(r.status || 'Working…') : r.error ? H(r.error) : 'No visual yet for this option.'}</span>`}</div>
          <div style="flex:1;min-width:240px"><label class="ed-l">Materials, lighting and landscape<textarea id="edPrompt" rows="6">${H(r.description || 'Contemporary architecture with refined facade materials, generous glazing, shaded outdoor spaces and realistic daylight.')}</textarea></label>
          <label class="ed-l">View<select id="edRenderView"><option value="primary">Primary axonometric</option><option value="reverse" ${r.viewKey === 'reverse' ? 'selected' : ''}>Reverse axonometric</option></select></label>
          <div class="ed-muted">Uses a reference from this option’s actual massing. AI output remains a visual concept; compare it with the calculated geometry.</div>
          <label class="ed-chk"><input type="checkbox" id="edRefine" ${ST.refine !== false ? 'checked' : ''} onchange="edState.refine=this.checked"> Enrich the description automatically</label>
          <button class="primary" onclick="edRender()" ${r.busy ? 'disabled' : ''}>${r.busy ? H(r.status || 'Working…') : r.img ? 'Generate again' : 'Generate visual'}</button></div>
        </div></div>` : '';
    return `<div class="ed-opts">${cards}</div>
      <div class="ed-card">
        <div class="ed-bar"><div><div class="ed-h" style="margin:0">${H(opt.name)}</div><div class="ed-muted">${H(opt.summary)}</div></div>
          <div class="ed-actions"><div class="ed-segs" style="margin:0">${view('floor', 'Floor plan')}${view('site', 'Site plan')}${view('axo', '3D massing')}${view('board', 'Concept board')}</div>
          ${ST.view === 'floor' && opt.masses.some((m) => m.use === 'podium') ? `<div class="ed-segs" style="margin:0"><button class="ed-seg ${ST.level !== 'podium' ? 'on' : ''}" onclick="edLevel('typical')">Typical floor</button><button class="ed-seg ${ST.level === 'podium' ? 'on' : ''}" onclick="edLevel('podium')">Podium</button></div>` : ''}
          <button class="tb" onclick="edExportDxf()">Export DXF</button>
          <button class="tb" onclick="edExportBoard()">Export board</button>
          <button class="primary" onclick="edShowRender(true)">Visualise</button></div></div>
        <div class="${ST.view === 'board' ? '' : 'ed-draw'}">${drawing}</div>
        <div class="ed-legend">${legend}</div>
      </div>
      ${renderBlock}
      ${summaryBlock()}
      <div class="ed-cols">
        <div class="ed-card"><div class="ed-h">Key figures</div><div class="ed-tiles">
          ${tile('GFA', N(m.gfa) + ' m²', m.gfa_pct_of_target + '% of ' + N(m.target_gfa))}
          ${tile('FAR', m.far, 'allowed GFA ' + N(m.max_gfa_allowed))}
          ${tile('Coverage', m.coverage_pct + '%', N(m.footprint_m2) + ' m² footprint')}
          ${tile('Height', m.height_m + ' m', m.storeys + ' floors')}
          ${tile('Units', N(m.units), N(m.residential_gfa) + ' m² residential')}
          ${tile('Parking', N(m.parking_required), m.basements_needed + ' basement level(s)')}</div>
          <table class="ed-tbl"><tr><th>Check</th><th>Limit</th><th>Option</th><th></th></tr>${checks}</table>
          ${opt.notes.length ? `<div class="ed-warn">${opt.notes.map(H).join('<br>')}</div>` : ''}</div>
        ${fpBlock}
      </div>`;
  }

  function summaryBlock() {
    const sm = ST.summary || {};
    const body = sm.text
      ? `<div class="ed-sum">${H(sm.text).replace(/\n/g, '<br>')}</div>`
      : `<div class="ed-muted">${sm.busy ? 'Writing the summary…' : sm.error ? H(sm.error) : 'A short written comparison of the options, based on the calculated figures.'}</div>`;
    return `<div class="ed-card"><div class="ed-bar" style="margin-bottom:6px"><div class="ed-h" style="margin:0">Design summary</div>
      <button class="tb" onclick="edSummary()" ${sm.busy ? 'disabled' : ''}>${sm.text ? 'Rewrite' : 'Write summary'}</button></div>${body}</div>`;
  }

  const CSS = `<style>${presentation.css}
    .ed-root{position:absolute;inset:0;overflow:auto;background:var(--bg);color:var(--text);padding:20px 24px 48px;font-size:13px}
    .ed-head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:16px;gap:12px;flex-wrap:wrap}
    .ed-title{font-size:20px;font-weight:700;color:var(--text)}.ed-sub{color:var(--muted);font-size:12.5px;margin-top:2px}
    .ed-layout{display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px;align-items:start}
    @media(max-width:1000px){.ed-layout{grid-template-columns:1fr}}
    .ed-side,.ed-main{display:flex;flex-direction:column;gap:12px;min-width:0}
    .ed-card{background:var(--surface,var(--card));border:1px solid var(--border);border-radius:var(--r-lg,10px);padding:14px}
    .ed-step{display:flex;align-items:center;gap:8px;font-weight:700;margin-bottom:10px}.ed-step span{width:20px;height:20px;border-radius:50%;background:var(--accent);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:11px}
    .ed-h{font-weight:700;margin-bottom:10px}.ed-muted{color:var(--muted);font-size:11.5px;line-height:1.45}
    .ed-l{display:flex;flex-direction:column;gap:4px;font-size:11.5px;color:var(--muted);margin-bottom:8px}
    .ed-l input,.ed-l select,.ed-l textarea,#edPlotNo{width:100%;min-width:0;box-sizing:border-box;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:7px 9px;color:var(--text);font-size:12.5px;font-family:inherit}
    .ed-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 10px}
    .ed-segs{display:inline-flex;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:2px;margin-bottom:12px;gap:2px}
    .ed-seg{border:0;background:transparent;color:var(--muted);padding:5px 11px;border-radius:6px;font-size:12px;cursor:pointer}.ed-seg.on{background:var(--accent);color:#fff}
    .ed-info{border:1px solid var(--border);border-radius:8px;padding:10px;margin-top:4px}.ed-info-h{font-weight:700;margin-bottom:8px}.ed-info-h span{font-weight:500;color:var(--muted);margin-left:6px}
    .ed-kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:12px;margin-bottom:8px}.ed-kv span{color:var(--muted)}.ed-kv b{text-align:right;font-weight:600}
    .ed-acc{border-top:1px solid var(--border)}.ed-acc-h{width:100%;display:flex;justify-content:space-between;background:none;border:0;color:var(--text);padding:9px 0;font-weight:600;font-size:12.5px;cursor:pointer}.ed-acc-h span{color:var(--muted)}
    .ed-opts{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
    .ed-opt{text-align:left;background:var(--surface,var(--card));border:1px solid var(--border);border-radius:10px;padding:11px;cursor:pointer;color:var(--text);display:flex;flex-direction:column;gap:5px}
    .ed-opt.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}.ed-opt-t{font-weight:700;font-size:12.5px}.ed-opt-m{color:var(--muted);font-size:11.5px}
    .ed-pill{display:inline-block;width:fit-content;font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:20px}.ed-pill.ok{background:rgba(46,160,67,.15);color:#3fb950}.ed-pill.bad{background:rgba(229,83,75,.15);color:#e5534b}
    .ed-bar{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px}.ed-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .ed-vw{position:relative;width:100%;height:100%}.ed-vw svg{cursor:grab}.ed-vw svg:active{cursor:grabbing}
    .ed-vw-tools{position:absolute;top:8px;right:8px;display:flex;gap:6px}.ed-vw-tools .tb.on2{border-color:#d6453d;color:#d6453d}.ed-vw-tools .tb.on{background:#ff4fd8;color:#fff;border-color:#ff4fd8}
    .ed-vw-xy{position:absolute;left:8px;bottom:6px;font-size:11px;color:var(--muted);background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:2px 8px;font-variant-numeric:tabular-nums}
    .ed-hit{cursor:help}
    .ed-draw{height:520px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--bg)}.ed-svg{width:100%;height:100%;display:block;color:var(--muted)}
    .ed-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:11.5px;color:var(--muted)}.ed-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
    .ed-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
    .ed-tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}.ed-tile{border:1px solid var(--border);border-radius:8px;padding:8px 10px}.ed-big{font-size:16px;font-weight:700;margin:2px 0}
    .ed-tbl{width:100%;border-collapse:collapse;font-size:12px}.ed-tbl th{text-align:left;color:var(--muted);font-weight:600;padding:6px 4px;border-bottom:1px solid var(--border)}.ed-tbl td{padding:6px 4px;border-bottom:1px solid var(--border)}
    .ed-warn{margin-top:10px;font-size:12px;color:#d29922;background:rgba(210,153,34,.1);border-radius:6px;padding:8px}
    .ed-sum{font-size:13px;line-height:1.6;white-space:normal}
    .ed-chk{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--muted);margin:6px 0}
    .ed-empty{padding:50px 20px;text-align:center;color:var(--muted)}
    .ed-render{display:flex;gap:14px;flex-wrap:wrap}.ed-render-img{flex:1.4;min-width:280px;min-height:240px;border:1px solid var(--border);border-radius:8px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:var(--bg)}.ed-render-img img{max-width:100%;max-height:420px;display:block}
  </style>`;

  function draw() {
    const c = ST.container;
    if (!c || !document.body.contains(c)) return;
    const sc = c.querySelector('.ed-root')?.scrollTop || 0;
    c.innerHTML = `${CSS}<div class="ed-root">
      <div class="ed-head"><div><div class="ed-title">Early Design</div><div class="ed-sub">Feasibility and massing options for a plot, with floor plans and planning checks.</div></div></div>
      <div class="ed-layout"><div class="ed-side">${sitePanel()}</div><div class="ed-main">${resultsPanel()}</div></div></div>`;
    c.querySelector('.ed-root').scrollTop = sc;
    bindViewer();
  }

  // ------------------------------------------------------------------ actions
  window.edSet = (k, v) => { ST.inputs[k] = Number(v); if (k === 'front_edge') ST.inputs.front_edges = []; };
  window.edToggle = (k) => { ST.openSec[k] = !ST.openSec[k]; draw(); };
  window.edView = (v) => { ST.view = v; draw(); if (v === 'floor' || v === 'board') loadPlan(ST.current, v === 'board' ? 'typical' : undefined); };
  window.edPick = (k) => { ST.current = k; ST.mPts = []; draw(); if (ST.view === 'floor' || ST.view === 'board') loadPlan(k, ST.view === 'board' ? 'typical' : undefined); };
  window.edShowRender = (on) => { ST.showRender = on; draw(); };
  window.edSource = async (s) => {
    ST.source = s;
    if (s !== 'mpd') ST.cad = null;
    if (s === 'manual') { ST.inputs.plot = null; ST.inputs.context = []; ST.plotInfo = null; }
    draw();
    if (s === 'mpd') await loadMpdProjects();
  };

  async function loadMpdProjects() {
    if (ST.mpdProjects.length) return;
    try {
      ST.mpdProjects = await jget('/api/early-design/mpd-plots');
      if (!ST.mpdProject && ST.mpdProjects[0]) ST.mpdProject = ST.mpdProjects[0].project_id;
      if (ST.mpdProject) ST.plotList = await jget('/api/early-design/mpd-plots?project=' + encodeURIComponent(ST.mpdProject));
    } catch (e) { say(e.message); }
    draw();
  }
  window.edMpdProject = async (p) => {
    ST.mpdProject = p;
    try { ST.plotList = await jget('/api/early-design/mpd-plots?project=' + encodeURIComponent(p)); } catch (e) { say(e.message); }
    draw();
  };
  window.edLoadPlot = async () => {
    const no = (document.getElementById('edPlotNo')?.value || '').trim();
    if (!no) { say('Enter a plot number'); return; }
    if (!ST.mpdProject) { say('No masterplan is available. Import one in Masterplan (MPD).'); return; }
    ST.plotNo = no;
    try {
      const b = await jget(`/api/early-design/mpd-plot?project=${encodeURIComponent(ST.mpdProject)}&plot=${encodeURIComponent(no)}`);
      ST.plotInfo = b.plot_info;
      ST.plotNo = b.plot_info.plot_id;
      const keep = ['plot', 'context', 'front_edge', 'front_edges', 'target_gfa', 'max_far', 'max_coverage', 'max_floors', 'max_height',
        'setback_front', 'setback_side', 'setback_rear', 'res_share', 'com_share'];
      keep.forEach((k) => { if (b[k] !== undefined) ST.inputs[k] = b[k]; });
      ST.cad = b.cad || null; ST.vb = {}; ST.mPts = [];
      ST.inputs.site_name = '';
      say(`Plot ${b.plot_info.plot_id} loaded`);
      await window.edCalculate();
    } catch (e) { say(e.message); draw(); }
  };

  function planKey(k) {
    const o = ST.result?.options[k ?? ST.current];
    const lv = ST.level === 'podium' && o && o.masses.some((m) => m.use === 'podium') ? 'podium' : 'typical';
    return `${k ?? ST.current}:${lv}`;
  }
  async function loadPlan(k, level) {
    const key = level ? `${k}:${level}` : planKey(k);
    if (!ST.result || ST.plans[key] !== undefined) return;
    ST.plans[key] = null;
    const result = ST.result;
    try {
      const plan = await jpost('/api/early-design/floor-plan', { inputs: ST.calculatedInputs || payload(), option: k, level: key.split(':')[1] });
      if (ST.result !== result) return;
      ST.plans[key] = plan;
    } catch (e) { if (ST.result === result) ST.plans[key] = { error: e.message }; }
    if (ST.result === result && (planKey() === key || ST.view === 'board')) draw();
  }
  window.edLevel = (lv) => { ST.level = lv; ST.mPts = []; draw(); loadPlan(ST.current); };
  window.edFit = () => { if (ST.vb) Object.keys(ST.vb).forEach((k) => delete ST.vb[k]); draw(); };
  window.edGridToggle = () => { ST.showGrid = ST.showGrid === false; draw(); };
  window.edMeasureToggle = () => { ST.measure = !ST.measure; ST.mPts = []; draw(); };

  window.edCalculate = async () => {
    ST.busy = true; draw();
    try {
      const inputs = payload();
      ST.result = await jpost('/api/early-design/generate', inputs);
      ST.calculatedInputs = inputs;
      ST.plans = {}; ST.render = {}; ST.showRender = false; ST.summary = null;
      if (ST.current >= ST.result.options.length) ST.current = 0;
      ST.view = 'floor';
    } catch (e) { say(e.message); }
    ST.busy = false; draw();
    loadPlan(ST.current);
  };

  window.edLoadDxf = async (file) => {
    if (!file) return;
    const fd = new FormData(); fd.append('file', file);
    try {
      const j = await jget('/api/early-design/site-dxf', { method: 'POST', body: fd });
      Object.assign(ST.inputs, { plot: j.plot, context: j.context || [], site_name: file.name, front_edge: 0, front_edges: [] });
      ST.plotInfo = null;
      say(`Plot read from DXF: ${N(j.area_m2)} m²`);
      await window.edCalculate();
    } catch (e) { say(e.message); draw(); }
  };

  window.edExportDxf = async () => {
    try {
      const r = await fetch(`${base()}/api/early-design/export-dxf`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ inputs: ST.calculatedInputs || payload(), option: ST.current }) });
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || 'Export failed'); }
      const blob = await r.blob();
      let name = (r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'EarlyDesign.dxf';
      if (ST.plotInfo) name = name.replace('EarlyDesign_', `EarlyDesign_${ST.plotInfo.plot_id}_`);
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch (e) { say(e.message); }
  };

  window.edSummary = async () => {
    ST.summary = { busy: true }; draw();
    try {
      const j = await jpost('/api/early-design/summary', { inputs: ST.calculatedInputs || payload(), plot_info: ST.plotInfo });
      ST.summary = { text: j.summary || 'No summary was returned.' };
    } catch (e) { ST.summary = { error: e.message }; }
    draw();
  };

  function conceptBoard() {
    const res = ST.result, opt = res.options[ST.current];
    const site = presentation.drawingSvg(sitePlan(res, opt), ST.vb.site.fit);
    const fp = ST.plans[`${ST.current}:typical`];
    const floor = fp && !fp.error ? presentation.drawingSvg(floorSvg(fp), vbox(fp.footprint.flatMap((s) => s.outer), 0.18).join(' ')) : '<p>Typical floor plan is not available yet.</p>';
    const visuals = Object.entries(ST.render[ST.current]?.views || {}).map(([key, v]) => ({src: v.file, reverse: key === 'reverse'}));
    return presentation.board({title: ST.inputs.site_name || ST.plotInfo?.plot_id || 'Design study', option: opt,
      site, floor, massing: presentation.massingSvg(res, opt), visuals});
  }

  window.edExportBoard = async () => {
    if (!ST.result) return;
    try {
      await loadPlan(ST.current, 'typical');
      const fp = ST.plans[`${ST.current}:typical`];
      if (!fp || fp.error) throw new Error('The typical floor plan is not ready. Open Concept board and wait for the plan before exporting.');
      const article = document.createElement('div'); article.innerHTML = conceptBoard();
      // Embed full-resolution images so the downloaded board works without the app session.
      for (const img of article.querySelectorAll('img')) {
        const response = await fetch(img.src);
        if (!response.ok) throw new Error('Could not retrieve a concept image for the board');
        const blob = await response.blob();
        img.src = await new Promise((resolve, reject) => {
          const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob);
        });
      }
      const html = '<!doctype html><html><head><meta charset="utf-8"><title>Early Design concept board</title><style>' + presentation.css + '</style></head><body>' + article.innerHTML + '</body></html>';
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([html], {type:'text/html'}));
      a.download = 'EarlyDesign-concept-board.html'; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch (e) { say(e.message); }
  };

  window.edRender = async () => {
    const idx = ST.current, result = ST.result, opt = result?.options[idx];
    if (!opt || ST.render[idx]?.busy) return;
    const project = typeof currentProject !== 'undefined' ? currentProject : null;
    if (!project) { say('Select a project first'); return; }
    const description = document.getElementById('edPrompt')?.value.trim() || 'Contemporary facade materials and realistic daylight.';
    const reverse = document.getElementById('edRenderView')?.value === 'reverse';
    const key = reverse ? 'reverse' : 'primary';
    const reference = presentation.massingSvg(result, opt, reverse);
    const seed = ST.render[idx]?.seed ?? crypto.getRandomValues(new Uint32Array(1))[0];
    const st = (ST.render[idx] = {description, seed, viewKey:key, views: {...(ST.render[idx]?.views || {})}, busy: true, status: 'Preparing geometry reference…'});
    draw();
    try {
      const list = await jget('/api/image-engine/workflows');
      const workflow = presentation.selectWorkflow(list);
      if (!workflow) throw new Error('No available image-reference workflow. Start ComfyUI and check the Sketch to Render models in AI Design Studio.');
      let detail = description;
      if (ST.refine !== false) {
        st.status = 'Preparing materials and lighting…';
        try {
          const en = await jpost('/api/image-engine/enhance-prompt', {prompt: description, mode:'materials', option_count:1,
            building_type: ST.plotInfo?.land_use || 'Residential', architectural_style:'Contemporary'});
          detail = en.design_options?.[0]?.changes || description;
        } catch (e) { /* The original description remains usable offline. */ }
      }
      const form = new FormData();
      const fields = {project, workflow_id: workflow.id, prompt: presentation.referencePrompt(opt, detail === description ? description : description + '\n' + detail),
        width:1344, height:768, seed, enhance_prompt:false};
      Object.entries(fields).forEach(([k, v]) => form.append(k, String(v)));
      form.append('input_image', await presentation.png(reference), `early-design-${key}.png`);
      if (ST.result !== result) throw new Error('The design changed. Generate a visual for the new option.');
      const job = await jget('/api/image-engine/jobs', {method:'POST', body:form});
      st.jobId = job.job_id;
      let completed = false;
      for (let t = 0; t < 600 && !completed; t++) {
        await new Promise((ok) => setTimeout(ok, 3000));
        if (ST.result !== result) return;
        const s = await jget(`/api/image-engine/jobs/${encodeURIComponent(job.job_id)}`);
        st.status = s.status === 'queued' ? 'Waiting in queue…' : `Generating ${s.progress_percent || 0}%`;
        if (ST.current === idx) { const b = document.querySelector('.ed-render .primary'); if (b) b.textContent = st.status; }
        if (s.status === 'failed' || s.status === 'cancelled') throw new Error(s.error_message || 'The visual could not be generated.');
        if (s.status === 'completed') {
          const o = (await jget(`/api/image-engine/jobs/${encodeURIComponent(job.job_id)}/outputs`))[0];
          if (!o) throw new Error('The visual could not be generated.');
          st.file = `${base()}/api/image-engine/outputs/${encodeURIComponent(o.output_id)}/file`;
          st.img = st.file;
          st.views[key] = {file:st.file, jobId:job.job_id}; completed = true;
        }
      }
      if (!completed) throw new Error('The job is still processing. Check AI Design Studio before submitting another render.');
    } catch (e) { st.error = e.message; say(e.message); }
    st.busy = false;
    if (ST.result === result && ST.current === idx) draw();
  };

  window.renderEarlyDesignWorkspace = function (container) {
    ST.container = container;
    draw();
    if (ST.source === 'mpd') loadMpdProjects();
  };
})();
