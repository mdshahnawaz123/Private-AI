/**
 * Expo Design AI - motion for charts and diagrams (offline, no dependencies).
 *  - ExpoMotion.attach(chartWrap): animates a chart drawn by ExpoChartRenderer
 *    (bars grow, lines draw, pie slices sweep in) and adds Replay / GIF / Video buttons.
 *  - ExpoMotion.renderMermaidIn(el, text): renders ```mermaid blocks (needs /ui/vendor/mermaid.min.js)
 *    and reveals the diagram step by step, with the same export buttons.
 * Every frame is drawn by setting SVG attributes, so the same function drives the live
 * animation and the frame capture for GIF (assembled server-side by Pillow) and video
 * (MediaRecorder: MP4 where the browser supports it, otherwise WebM).
 */
(function (window) {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const clamp = v => Math.max(0, Math.min(1, v));
  const stagger = (p, i, n, spread) => clamp((p - (n > 1 ? (i / (n - 1)) * spread : 0)) / (1 - spread));

  function prepareChart(svg) {
    const items = [];
    const vb = svg.viewBox && svg.viewBox.baseVal;
    const cx = vb ? vb.width / 2 : 200, cy = vb ? vb.height / 2 : 120;
    const rects = [...svg.querySelectorAll('rect')].filter(r => +r.getAttribute('height') > 0 && (r.getAttribute('fill') || '') !== 'none');
    rects.forEach((r, i) => items.push({ kind: 'bar', el: r, y: +r.getAttribute('y'), h: +r.getAttribute('height'), i, n: rects.length }));
    const lines = [...svg.querySelectorAll('path')].filter(p => (p.getAttribute('fill') || '') === 'none' && p.getAttribute('stroke'));
    lines.forEach(p => { let L = 1000; try { L = p.getTotalLength(); } catch (e) {} items.push({ kind: 'line', el: p, L }); });
    const slices = [...svg.querySelectorAll('path')].filter(p => (p.getAttribute('fill') || 'none') !== 'none' && !lines.includes(p));
    slices.forEach((p, i) => items.push({ kind: 'slice', el: p, i, n: slices.length, cx, cy }));
    const dots = [...svg.querySelectorAll('circle')];
    dots.forEach((c, i) => items.push({ kind: 'dot', el: c, i, n: dots.length }));
    return items;
  }

  function applyChart(items, p) {
    for (const it of items) {
      if (it.kind === 'bar') {
        const e = ease(stagger(p, it.i, it.n, 0.45));
        it.el.setAttribute('height', it.h * e);
        it.el.setAttribute('y', it.y + it.h * (1 - e));
      } else if (it.kind === 'line') {
        const e = ease(clamp(p / 0.85));
        it.el.setAttribute('stroke-dasharray', it.L + ' ' + it.L);
        it.el.setAttribute('stroke-dashoffset', it.L * (1 - e));
      } else if (it.kind === 'slice') {
        const e = ease(stagger(p, it.i, it.n, 0.6));
        it.el.setAttribute('opacity', e);
        it.el.setAttribute('transform', `translate(${it.cx} ${it.cy}) scale(${0.6 + 0.4 * e}) translate(${-it.cx} ${-it.cy})`);
      } else if (it.kind === 'dot') {
        it.el.setAttribute('opacity', ease(stagger(p, it.i, it.n, 0.8)));
      }
    }
  }

  function play(apply, ms) {
    return new Promise(res => {
      const t0 = performance.now();
      const step = now => { const p = clamp((now - t0) / ms); apply(p); p < 1 ? requestAnimationFrame(step) : res(); };
      requestAnimationFrame(step);
    });
  }

  function svgFrame(svg, scale, bg) {
    return new Promise((res, rej) => {
      const vb = svg.viewBox && svg.viewBox.baseVal;
      const w = (vb && vb.width) || svg.getBoundingClientRect().width || 800;
      const h = (vb && vb.height) || svg.getBoundingClientRect().height || 450;
      const clone = svg.cloneNode(true);
      clone.setAttribute('width', w); clone.setAttribute('height', h);
      if (!clone.getAttribute('xmlns')) clone.setAttribute('xmlns', NS);
      const xml = new XMLSerializer().serializeToString(clone);
      const img = new Image();
      img.onload = () => {
        const c = document.createElement('canvas');
        c.width = Math.round(w * scale); c.height = Math.round(h * scale);
        const ctx = c.getContext('2d');
        ctx.fillStyle = bg; ctx.fillRect(0, 0, c.width, c.height);
        ctx.drawImage(img, 0, 0, c.width, c.height);
        res(c);
      };
      img.onerror = rej;
      img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(xml)));
    });
  }

  function download(blob, name) {
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
  }

  async function exportGif(svg, apply, name, btn, bg) {
    const fps = 20, n = 36, frames = [];
    btn && (btn.textContent = '...');
    try {
      for (let k = 0; k <= n; k++) { apply(k / n); frames.push((await svgFrame(svg, 1.5, bg)).toDataURL('image/png')); }
      const token = (() => { try { return localStorage.getItem('expo_token'); } catch (e) { return null; } })();
      const r = await fetch('/api/visualize/gif', { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, token ? { Authorization: 'Bearer ' + token } : {}),
        body: JSON.stringify({ frames, fps, hold_ms: 2000, name }) });
      if (!r.ok) throw new Error('GIF export failed (' + r.status + ')');
      download(await r.blob(), name + '.gif');
    } catch (e) { alert(e.message || e); }
    finally { apply(1); btn && (btn.textContent = 'GIF'); }
  }

  async function exportVideo(svg, apply, name, btn, bg) {
    if (!window.MediaRecorder) { alert('Video recording is not supported in this browser'); return; }
    btn && (btn.textContent = '...');
    try {
      const first = await svgFrame(svg, 2, bg);
      const canvas = document.createElement('canvas'); canvas.width = first.width; canvas.height = first.height;
      const ctx = canvas.getContext('2d');
      const types = ['video/mp4;codecs=avc1', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm'];
      const mime = types.find(t => MediaRecorder.isTypeSupported(t)) || '';
      const rec = new MediaRecorder(canvas.captureStream(30), mime ? { mimeType: mime, videoBitsPerSecond: 6e6 } : {});
      const chunks = []; rec.ondataavailable = e => e.data.size && chunks.push(e.data);
      const stopped = new Promise(r => (rec.onstop = r));
      rec.start();
      const n = 60;
      for (let k = 0; k <= n + 30; k++) {           // 2 s animation + 1 s hold at 30 fps
        apply(Math.min(1, k / n));
        ctx.drawImage(await svgFrame(svg, 2, bg), 0, 0);
        await new Promise(r => setTimeout(r, 33));
      }
      rec.stop(); await stopped;
      download(new Blob(chunks, { type: mime || 'video/webm' }), name + (mime.includes('mp4') ? '.mp4' : '.webm'));
    } catch (e) { alert(e.message || e); }
    finally { apply(1); btn && (btn.textContent = 'Video'); }
  }

  function addButtons(bar, svg, apply, name, bg, ms) {
    if (!bar || bar.querySelector('[data-motion]')) return;
    const style = 'background:#16233b;border:1px solid #28395a;color:#8ea0ba;border-radius:6px;padding:3px 8px;font-size:11px;cursor:pointer';
    [['Replay', () => play(apply, ms)], ['GIF', b => exportGif(svg, apply, name, b, bg)], ['Video', b => exportVideo(svg, apply, name, b, bg)]]
      .forEach(([label, fn]) => {
        const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.dataset.motion = label;
        b.style.cssText = style; b.title = label === 'Replay' ? 'Replay animation' : 'Export animated ' + label;
        b.addEventListener('click', () => fn(b)); bar.appendChild(b);
      });
  }

  function attach(wrap, opts) {
    opts = opts || {};
    const svg = wrap && wrap.querySelector('svg');
    if (!svg) return;
    const items = prepareChart(svg);
    const apply = p => applyChart(items, p);
    const title = (wrap.querySelector('div > div') || {}).textContent || 'chart';
    const name = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 50) || 'chart';
    addButtons(wrap.querySelector('.expo-chart-actions'), svg, apply, name, '#0f1828', 1400);
    apply(0);
    if (opts.delay) setTimeout(() => play(apply, 1400), opts.delay); else play(apply, 1400);
  }

  /* ---------------- diagrams (mermaid) ---------------- */
  let mermaidReady = null;
  function loadMermaid() {
    if (window.mermaid) return Promise.resolve(window.mermaid);
    if (!mermaidReady) mermaidReady = new Promise((res, rej) => {
      const s = document.createElement('script'); s.src = '/ui/vendor/mermaid.min.js';
      s.onload = () => { window.mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict', flowchart: { htmlLabels: false }, themeVariables: { fontFamily: 'Inter, Segoe UI, sans-serif' } }); res(window.mermaid); };
      s.onerror = rej; document.head.appendChild(s);
    });
    return mermaidReady;
  }

  function prepareDiagram(svg) {
    const steps = [];
    const nodes = [...svg.querySelectorAll('g.node, g.actor, rect.actor, g.cluster')];
    const edges = [...svg.querySelectorAll('path.flowchart-link, .edgePaths path, line.messageLine0, line.messageLine1, path.messageLine0, path.messageLine1, path.relation, path.transition')];
    const labels = [...svg.querySelectorAll('g.edgeLabel, text.messageText')];
    // interleave: node, its outgoing edge, next node ...
    const n = Math.max(nodes.length, edges.length);
    for (let i = 0; i < n; i++) {
      if (nodes[i]) steps.push({ el: nodes[i], kind: 'fade' });
      if (edges[i]) { let L = 300; try { L = edges[i].getTotalLength(); } catch (e) {} steps.push({ el: edges[i], kind: 'draw', L, label: labels[i] }); }
    }
    return steps;
  }

  function applyDiagram(steps, p) {
    const n = steps.length || 1;
    steps.forEach((s, i) => {
      const e = ease(clamp(p * n - i));
      if (s.kind === 'fade') s.el.setAttribute('opacity', e);
      else {
        s.el.setAttribute('stroke-dasharray', s.L + ' ' + s.L);
        s.el.setAttribute('stroke-dashoffset', s.L * (1 - e));
        if (s.label) s.label.setAttribute('opacity', e);
      }
    });
    if (p >= 1) steps.forEach(s => { if (s.kind === 'draw') s.el.removeAttribute('stroke-dasharray'); });
  }

  async function renderMermaidIn(el, text) {
    const blocks = [...String(text || '').matchAll(/```mermaid\s*([\s\S]*?)```/gi)].map(m => m[1].trim());
    if (!blocks.length) return;
    let mm; try { mm = await loadMermaid(); } catch (e) { return; }
    // remove the raw code blocks the markdown renderer printed
    el.querySelectorAll('pre, code').forEach(c => { if (/^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|gantt|mindmap|timeline|pie)\b/.test(c.textContent)) (c.closest('pre') || c).remove(); });
    for (let k = 0; k < blocks.length; k++) {
      const box = document.createElement('div');
      box.className = 'expo-chart-widget';
      box.style.cssText = 'background:#0f1828;border:1px solid #1e2c45;border-radius:10px;padding:12px;margin:12px 0;overflow:auto';
      box.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><div style="font-weight:700;font-size:13px;color:#fff">Diagram</div><div class="expo-chart-actions" style="display:flex;gap:6px"></div></div><div class="mm"></div>';
      el.appendChild(box);
      try {
        const { svg } = await mm.render('expo-mm-' + Date.now() + '-' + k, blocks[k]);
        box.querySelector('.mm').innerHTML = svg;
        const svgEl = box.querySelector('svg');
        svgEl.style.maxWidth = '100%'; svgEl.style.maxHeight = '520px'; svgEl.style.width = 'auto'; svgEl.style.height = 'auto'; svgEl.style.display = 'block'; svgEl.style.margin = '0 auto';
        const steps = prepareDiagram(svgEl);
        const apply = p => applyDiagram(steps, p);
        const ms = Math.min(6000, 450 * Math.max(steps.length, 3));
        addButtons(box.querySelector('.expo-chart-actions'), svgEl, apply, 'diagram', '#0f1828', ms);
        apply(0); play(apply, ms);
      } catch (e) {
        box.querySelector('.mm').innerHTML = '<pre style="white-space:pre-wrap;color:#8ea0ba">' + blocks[k].replace(/[<&]/g, c => ({ '<': '&lt;', '&': '&amp;' })[c]) + '</pre>';
      }
    }
  }

  function countUp(el, value, ms) {
    const t0 = performance.now();
    const fmt = v => Number(v).toLocaleString(undefined, { maximumFractionDigits: Math.abs(value) < 100 ? 2 : 0 });
    const step = now => { const p = ease(clamp((now - t0) / (ms || 1200))); el.textContent = fmt(value * p); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  window.ExpoMotion = { attach, renderMermaidIn, countUp, play };
})(window);
