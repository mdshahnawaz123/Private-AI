/**
 * Expo Design AI — Reusable Offline Chart Renderer
 * ui/vendor_components/chart_renderer.js
 *
 * Supports Pie, Donut, Bar, Line, and Stacked-Bar charts using pure local SVG/Canvas.
 * 100% offline, zero external dependencies, responsive sizing, legends, tooltips,
 * percentage formatting, and report export (PNG / SVG / JSON).
 */
(function(window){
  'use strict';

  const COLORS = [
    '#2f6bff', '#35d07f', '#8a6cff', '#f5b73d', '#31d0c5',
    '#f2585f', '#ff8d3b', '#60a5fa', '#a78bfa', '#34d399'
  ];

  const esc = s => (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));

  function formatNum(n){
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function renderChart(spec, container, options){
    options = options || {};
    if (!spec || !container) return null;

    const chartType = String(spec.chart_type || spec.type || 'bar').toLowerCase();
    const title = spec.title || '';
    const subtitle = spec.subtitle || '';
    const units = spec.units ? (' ' + spec.units) : '';
    const showLegend = spec.legend !== false;
    const showTooltips = spec.tooltips !== false;
    const showPercentage = Boolean(spec.percentage);

    const wrap = document.createElement('div');
    wrap.className = 'expo-chart-widget';
    wrap.style.cssText = 'background:#0f1828;border:1px solid #1e2c45;border-radius:10px;padding:16px;margin:12px 0;position:relative;color:#e8eef7;font-family:Inter,sans-serif';

    // Header
    const head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px';
    head.innerHTML = `<div>
      <div style="font-weight:700;font-size:14px;color:#fff">${esc(title)}</div>
      ${subtitle ? `<div style="font-size:11.5px;color:#8ea0ba;margin-top:2px">${esc(subtitle)}</div>` : ''}
    </div>
    <div style="display:flex;gap:6px" class="expo-chart-actions">
      <button type="button" class="expo-chart-btn" data-act="svg" title="Export SVG" style="background:#16233b;border:1px solid #28395a;color:#8ea0ba;border-radius:6px;padding:3px 8px;font-size:11px;cursor:pointer">SVG</button>
      <button type="button" class="expo-chart-btn" data-act="png" title="Export PNG" style="background:#16233b;border:1px solid #28395a;color:#8ea0ba;border-radius:6px;padding:3px 8px;font-size:11px;cursor:pointer">PNG</button>
      <button type="button" class="expo-chart-btn" data-act="json" title="Export JSON" style="background:#16233b;border:1px solid #28395a;color:#8ea0ba;border-radius:6px;padding:3px 8px;font-size:11px;cursor:pointer">JSON</button>
    </div>`;
    wrap.appendChild(head);

    // Tooltip overlay
    const tooltip = document.createElement('div');
    tooltip.className = 'expo-chart-tooltip';
    tooltip.style.cssText = 'position:absolute;display:none;background:#111c30;border:1px solid #28395a;color:#fff;padding:6px 10px;border-radius:6px;font-size:11.5px;pointer-events:none;z-index:20;box-shadow:0 4px 14px rgba(0,0,0,0.4);white-space:nowrap';
    wrap.appendChild(tooltip);

    // SVG Canvas
    const svgWrap = document.createElement('div');
    svgWrap.style.cssText = 'width:100%;min-height:240px;position:relative;display:flex;justify-content:center';
    wrap.appendChild(svgWrap);

    let svgEl = null;

    if (chartType === 'pie' || chartType === 'donut') {
      svgEl = renderPieDonut(spec, chartType === 'donut', units, showPercentage, tooltip);
    } else if (chartType === 'line') {
      svgEl = renderLine(spec, units, tooltip);
    } else if (chartType === 'stacked_bar') {
      svgEl = renderStackedBar(spec, units, tooltip);
    } else {
      // Default: bar
      svgEl = renderBar(spec, units, tooltip);
    }

    if (svgEl) {
      svgWrap.appendChild(svgEl);
    }

    // Legend
    if (showLegend) {
      const legendEl = buildLegend(spec, chartType);
      if (legendEl) wrap.appendChild(legendEl);
    }

    // Actions
    wrap.querySelectorAll('.expo-chart-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const act = btn.dataset.act;
        const fname = (title || 'chart').toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'chart';
        if (act === 'json') {
          downloadFile(JSON.stringify(spec, null, 2), `${fname}.json`, 'application/json');
        } else if (act === 'svg' && svgEl) {
          downloadFile(svgEl.outerHTML, `${fname}.svg`, 'image/svg+xml');
        } else if (act === 'png' && svgEl) {
          svgToPng(svgEl, `${fname}.png`);
        }
      });
    });

    container.appendChild(wrap);
    return wrap;
  }

  /* ---------------- PIE & DONUT ---------------- */
  function renderPieDonut(spec, isDonut, units, showPercentage, tooltip){
    const data = spec.data || (spec.series && spec.series[0] && spec.series[0].data) || [];
    if (!data.length) return null;

    const total = data.reduce((sum, d) => sum + (Number(d.value) || 0), 0);
    if (total <= 0) return null;

    const width = 400, height = 240;
    const cx = 200, cy = 120;
    const r = 95;
    const innerR = isDonut ? 55 : 0;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('style', 'width:100%;max-width:440px;height:auto;overflow:visible');

    let curAngle = -Math.PI / 2;

    data.forEach((d, i) => {
      const val = Number(d.value) || 0;
      const sliceAngle = (val / total) * 2 * Math.PI;
      const nextAngle = curAngle + sliceAngle;
      const color = COLORS[i % COLORS.length];

      const x1 = cx + r * Math.cos(curAngle);
      const y1 = cy + r * Math.sin(curAngle);
      const x2 = cx + r * Math.cos(nextAngle);
      const y2 = cy + r * Math.sin(nextAngle);

      const largeArc = sliceAngle > Math.PI ? 1 : 0;

      let pathD = '';
      if (isDonut) {
        const ix1 = cx + innerR * Math.cos(curAngle);
        const iy1 = cy + innerR * Math.sin(curAngle);
        const ix2 = cx + innerR * Math.cos(nextAngle);
        const iy2 = cy + innerR * Math.sin(nextAngle);
        pathD = `M ${ix1} ${iy1} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} L ${ix2} ${iy2} A ${innerR} ${innerR} 0 ${largeArc} 0 ${ix1} ${iy1} Z`;
      } else {
        pathD = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
      }

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', pathD);
      path.setAttribute('fill', color);
      path.setAttribute('stroke', '#0f1828');
      path.setAttribute('stroke-width', '2');
      path.style.cursor = 'pointer';
      path.style.transition = 'opacity 0.15s ease, transform 0.15s ease';

      const pctStr = ((val / total) * 100).toFixed(1) + '%';
      const labelText = `${d.name}: <b>${formatNum(val)}${units}</b> (${pctStr})`;

      path.addEventListener('mouseenter', (e) => {
        path.setAttribute('opacity', '0.85');
        tooltip.innerHTML = labelText;
        tooltip.style.display = 'block';
      });
      path.addEventListener('mousemove', (e) => {
        const rect = svg.getBoundingClientRect();
        tooltip.style.left = (e.clientX - rect.left + 12) + 'px';
        tooltip.style.top = (e.clientY - rect.top + 10) + 'px';
      });
      path.addEventListener('mouseleave', () => {
        path.setAttribute('opacity', '1');
        tooltip.style.display = 'none';
      });

      svg.appendChild(path);
      curAngle = nextAngle;
    });

    if (isDonut) {
      const centerTxt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      centerTxt.setAttribute('x', cx);
      centerTxt.setAttribute('y', cy + 4);
      centerTxt.setAttribute('text-anchor', 'middle');
      centerTxt.setAttribute('fill', '#8ea0ba');
      centerTxt.setAttribute('font-size', '11');
      centerTxt.textContent = 'Total: ' + formatNum(total);
      svg.appendChild(centerTxt);
    }

    return svg;
  }

  /* ---------------- BAR CHART ---------------- */
  function renderBar(spec, units, tooltip){
    const cats = spec.categories || [];
    const series = spec.series || [];
    if (!cats.length || !series.length) return null;

    const width = 500, height = 260;
    const padding = { top: 20, right: 20, bottom: 40, left: 50 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    let maxVal = 0;
    series.forEach(s => (s.data || []).forEach(v => { if (Number(v) > maxVal) maxVal = Number(v); }));
    if (maxVal === 0) maxVal = 1;
    maxVal *= 1.1; // head room

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('style', 'width:100%;max-width:540px;height:auto;overflow:visible');

    drawAxes(svg, padding, chartW, chartH, maxVal, cats);

    const numSeries = series.length;
    const catBand = chartW / cats.length;
    const barWidth = Math.max(4, Math.min(28, (catBand * 0.7) / numSeries));
    const groupWidth = barWidth * numSeries;

    cats.forEach((cat, cIdx) => {
      const groupX = padding.left + cIdx * catBand + (catBand - groupWidth) / 2;
      series.forEach((s, sIdx) => {
        const val = Number((s.data || [])[cIdx]) || 0;
        const bH = (val / maxVal) * chartH;
        const bX = groupX + sIdx * barWidth;
        const bY = padding.top + chartH - bH;
        const color = COLORS[sIdx % COLORS.length];

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', bX);
        rect.setAttribute('y', bY);
        rect.setAttribute('width', Math.max(2, barWidth - 1));
        rect.setAttribute('height', Math.max(0, bH));
        rect.setAttribute('fill', color);
        rect.setAttribute('rx', '2');
        rect.style.cursor = 'pointer';

        rect.addEventListener('mouseenter', () => {
          tooltip.innerHTML = `<b>${esc(cat)}</b><br>${esc(s.name)}: <b>${formatNum(val)}${units}</b>`;
          tooltip.style.display = 'block';
        });
        rect.addEventListener('mousemove', (e) => {
          const sRect = svg.getBoundingClientRect();
          tooltip.style.left = (e.clientX - sRect.left + 12) + 'px';
          tooltip.style.top = (e.clientY - sRect.top + 10) + 'px';
        });
        rect.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });

        svg.appendChild(rect);
      });
    });

    return svg;
  }

  /* ---------------- STACKED BAR ---------------- */
  function renderStackedBar(spec, units, tooltip){
    const cats = spec.categories || [];
    const series = spec.series || [];
    if (!cats.length || !series.length) return null;

    const width = 500, height = 260;
    const padding = { top: 20, right: 20, bottom: 40, left: 50 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    // Calculate stacked sum per category
    const catSums = cats.map((_, cIdx) => {
      return series.reduce((sum, s) => sum + (Number((s.data || [])[cIdx]) || 0), 0);
    });
    let maxVal = Math.max(...catSums, 1) * 1.1;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('style', 'width:100%;max-width:540px;height:auto;overflow:visible');

    drawAxes(svg, padding, chartW, chartH, maxVal, cats);

    const catBand = chartW / cats.length;
    const barWidth = Math.max(6, Math.min(36, catBand * 0.65));

    cats.forEach((cat, cIdx) => {
      const bX = padding.left + cIdx * catBand + (catBand - barWidth) / 2;
      let curY = padding.top + chartH;

      series.forEach((s, sIdx) => {
        const val = Number((s.data || [])[cIdx]) || 0;
        const segH = (val / maxVal) * chartH;
        curY -= segH;
        const color = COLORS[sIdx % COLORS.length];

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', bX);
        rect.setAttribute('y', curY);
        rect.setAttribute('width', barWidth);
        rect.setAttribute('height', Math.max(0, segH));
        rect.setAttribute('fill', color);
        rect.style.cursor = 'pointer';

        const totalCat = catSums[cIdx];
        const pctStr = totalCat > 0 ? ` (${((val / totalCat) * 100).toFixed(1)}%)` : '';

        rect.addEventListener('mouseenter', () => {
          tooltip.innerHTML = `<b>${esc(cat)}</b><br>${esc(s.name)}: <b>${formatNum(val)}${units}</b>${pctStr}`;
          tooltip.style.display = 'block';
        });
        rect.addEventListener('mousemove', (e) => {
          const sRect = svg.getBoundingClientRect();
          tooltip.style.left = (e.clientX - sRect.left + 12) + 'px';
          tooltip.style.top = (e.clientY - sRect.top + 10) + 'px';
        });
        rect.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });

        svg.appendChild(rect);
      });
    });

    return svg;
  }

  /* ---------------- LINE CHART ---------------- */
  function renderLine(spec, units, tooltip){
    const cats = spec.categories || [];
    const series = spec.series || [];
    if (!cats.length || !series.length) return null;

    const width = 500, height = 260;
    const padding = { top: 20, right: 20, bottom: 40, left: 50 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    let maxVal = 0;
    series.forEach(s => (s.data || []).forEach(v => { if (Number(v) > maxVal) maxVal = Number(v); }));
    if (maxVal === 0) maxVal = 1;
    maxVal *= 1.1;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('style', 'width:100%;max-width:540px;height:auto;overflow:visible');

    drawAxes(svg, padding, chartW, chartH, maxVal, cats);

    const stepX = cats.length > 1 ? chartW / (cats.length - 1) : chartW / 2;

    series.forEach((s, sIdx) => {
      const color = COLORS[sIdx % COLORS.length];
      const points = [];

      (s.data || []).forEach((val, cIdx) => {
        const v = Number(val) || 0;
        const x = padding.left + cIdx * stepX;
        const y = padding.top + chartH - (v / maxVal) * chartH;
        points.push({ x, y, v, cat: cats[cIdx] || '' });
      });

      if (!points.length) return;

      const dStr = points.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', dStr);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', color);
      path.setAttribute('stroke-width', '2.5');
      svg.appendChild(path);

      points.forEach(p => {
        const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot.setAttribute('cx', p.x);
        dot.setAttribute('cy', p.y);
        dot.setAttribute('r', '4');
        dot.setAttribute('fill', color);
        dot.setAttribute('stroke', '#0f1828');
        dot.setAttribute('stroke-width', '2');
        dot.style.cursor = 'pointer';

        dot.addEventListener('mouseenter', () => {
          tooltip.innerHTML = `<b>${esc(p.cat)}</b><br>${esc(s.name)}: <b>${formatNum(p.v)}${units}</b>`;
          tooltip.style.display = 'block';
        });
        dot.addEventListener('mousemove', (e) => {
          const sRect = svg.getBoundingClientRect();
          tooltip.style.left = (e.clientX - sRect.left + 12) + 'px';
          tooltip.style.top = (e.clientY - sRect.top + 10) + 'px';
        });
        dot.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });

        svg.appendChild(dot);
      });
    });

    return svg;
  }

  /* ---------------- AXES & GRID HELPERS ---------------- */
  function drawAxes(svg, padding, chartW, chartH, maxVal, cats){
    // Grid lines (3 ticks)
    for (let t = 0; t <= 3; t++) {
      const y = padding.top + chartH - (t / 3) * chartH;
      const val = (t / 3) * maxVal;

      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', padding.left);
      line.setAttribute('y1', y);
      line.setAttribute('x2', padding.left + chartW);
      line.setAttribute('y2', y);
      line.setAttribute('stroke', '#1e2c45');
      line.setAttribute('stroke-dasharray', '3 3');
      svg.appendChild(line);

      const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      txt.setAttribute('x', padding.left - 8);
      txt.setAttribute('y', y + 3.5);
      txt.setAttribute('text-anchor', 'end');
      txt.setAttribute('fill', '#8ea0ba');
      txt.setAttribute('font-size', '10');
      txt.textContent = formatNum(val);
      svg.appendChild(txt);
    }

    // Category labels
    const catBand = chartW / cats.length;
    cats.forEach((cat, idx) => {
      const x = padding.left + idx * catBand + catBand / 2;
      const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      txt.setAttribute('x', x);
      txt.setAttribute('y', padding.top + chartH + 18);
      txt.setAttribute('text-anchor', 'middle');
      txt.setAttribute('fill', '#8ea0ba');
      txt.setAttribute('font-size', '10.5');
      txt.textContent = cat.length > 14 ? (cat.slice(0, 12) + '…') : cat;
      svg.appendChild(txt);
    });
  }

  /* ---------------- LEGEND ---------------- */
  function buildLegend(spec, chartType){
    let items = [];
    if (chartType === 'pie' || chartType === 'donut') {
      const data = spec.data || (spec.series && spec.series[0] && spec.series[0].data) || [];
      items = data.map((d, i) => ({ name: d.name, color: COLORS[i % COLORS.length] }));
    } else {
      items = (spec.series || []).map((s, i) => ({ name: s.name, color: COLORS[i % COLORS.length] }));
    }

    if (!items.length) return null;

    const legend = document.createElement('div');
    legend.style.cssText = 'display:flex;flex-wrap:wrap;gap:12px;margin-top:14px;justify-content:center;font-size:11.5px;color:#8ea0ba';
    legend.innerHTML = items.map(item => `
      <div style="display:flex;align-items:center;gap:6px">
        <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${item.color}"></span>
        <span>${esc(item.name)}</span>
      </div>`).join('');
    return legend;
  }

  /* ---------------- EXPORTS ---------------- */
  function downloadFile(content, filename, mime){
    const blob = new Blob([content], { type: mime + ';charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  function svgToPng(svgEl, filename){
    try {
      const xml = new XMLSerializer().serializeToString(svgEl);
      const svg64 = btoa(unescape(encodeURIComponent(xml)));
      const b64Start = 'data:image/svg+xml;base64,';
      const image64 = b64Start + svg64;
      const img = new Image();
      img.onload = function(){
        const canvas = document.createElement('canvas');
        canvas.width = svgEl.viewBox.baseVal.width * 2 || 1000;
        canvas.height = svgEl.viewBox.baseVal.height * 2 || 520;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#0f1828';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(blob => {
          if (!blob) return;
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url; a.download = filename;
          document.body.appendChild(a); a.click();
          setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
        });
      };
      img.src = image64;
    } catch(e) {
      if (window.toast) window.toast('PNG export not supported in this browser context');
    }
  }

  window.ExpoChartRenderer = {
    render: renderChart,
    VALID_TYPES: ['pie', 'donut', 'bar', 'line', 'stacked_bar']
  };

})(window);
