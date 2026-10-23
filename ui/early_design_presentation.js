/* Geometry references and presentation for Early Design. No model-generated quantities. */
(function () {
  const H = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));

  function massingScene(result, option, reverse = false) {
    const points = result.plot.shapes.flatMap((s) => s.outer);
    const cx = points.reduce((n, p) => n + p[0], 0) / points.length;
    const cy = points.reduce((n, p) => n + p[1], 0) / points.length;
    const sign = reverse ? -1 : 1;
    const project = ([x, y], z = 0) => {
      x = (x - cx) * sign; y = (y - cy) * sign;
      return [(x - y) * Math.cos(Math.PI / 6), (x + y) / 2 - z];
    };
    const depth = (ring, z) => ring.reduce((n, p) => n + ((p[0] - cx) + (p[1] - cy)) * sign, 0) / ring.length + z;
    const ringPath = (ring, z) => 'M' + ring.map((p) => project(p, z).join(',')).join('L') + 'Z';
    const shapePath = (s, z) => ringPath(s.outer, z) + (s.holes || []).map((r) => ringPath(r, z)).join('');
    const faces = [], projected = points.map((p) => project(p));
    // Base/podium surfaces must precede upper masses; a global face-centroid sort
    // can otherwise paint a podium roof across the lower half of a tower.
    [...option.masses].sort((a, b) => a.base_m - b.base_m ||
      depth(a.shapes[0].outer, 0) - depth(b.shapes[0].outer, 0)).forEach((m, order) => m.shapes.forEach((s) => {
      [s.outer, ...(s.holes || [])].forEach((ring) => ring.forEach((p, i) => {
        const q = ring[(i + 1) % ring.length];
        const a = project(p, m.base_m), b = project(q, m.base_m);
        const c = project(q, m.top_m), d = project(p, m.top_m);
        projected.push(a, b, c, d);
        const lines = [];
        for (let f = 1; f < m.floors; f++) {
          const z = m.base_m + (m.top_m - m.base_m) * f / m.floors;
          lines.push('M' + project(p, z).join(',') + 'L' + project(q, z).join(','));
        }
        faces.push({order, depth: depth([p, q], (m.base_m + m.top_m) / 2),
          path: 'M' + [a, b, c, d].map((pt) => pt.join(',')).join('L') + 'Z',
          fill: m.use === 'podium' ? '#bdc5cc' : '#dce2e6', lines: lines.join('')});
      }));
      faces.push({order, depth: depth(s.outer, m.top_m), path: shapePath(s, m.top_m), fill: '#f5f3ee'});
    }));
    const xs = projected.map((p) => p[0]), ys = projected.map((p) => p[1]);
    const pad = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * 0.08;
    const viewBox = [Math.min(...xs) - pad, Math.min(...ys) - pad,
      Math.max(...xs) - Math.min(...xs) + 2 * pad, Math.max(...ys) - Math.min(...ys) + 2 * pad];
    const sw = viewBox[2] / 900;
    let content = result.plot.shapes.map((s) => `<path d="${shapePath(s, 0)}" fill="#e0e9dc" fill-rule="evenodd" stroke="#acb8a6" stroke-width="${sw}"/>`).join('');
    faces.sort((a, b) => a.order - b.order || a.depth - b.depth).forEach((f) => {
      content += `<path d="${f.path}" fill="${f.fill}" fill-rule="evenodd" stroke="#75828c" stroke-width="${sw}"/>`;
      if (f.lines) content += `<path d="${f.lines}" fill="none" stroke="#83919c" stroke-width="${sw * 0.55}"/>`;
    });
    return {content, viewBox};
  }

  function massingSvg(result, option, reverse = false) {
    const scene = massingScene(result, option, reverse);
    return `<svg xmlns="http://www.w3.org/2000/svg" width="1344" height="768" viewBox="${scene.viewBox.join(' ')}"><rect x="${scene.viewBox[0]}" y="${scene.viewBox[1]}" width="${scene.viewBox[2]}" height="${scene.viewBox[3]}" fill="#f8f7f3"/>${scene.content}</svg>`;
  }

  function selectWorkflow(list) {
    const eligible = list.filter((w) => w.available === true && w.category !== 'video' &&
      (w.parameters || []).some((p) => p.name === 'input_image_path' && p.type === 'image') &&
      !(w.parameters || []).some((p) => p.required && p.type === 'image' && p.name !== 'input_image_path'));
    return eligible.find((w) => w.id === 'sketch_to_render') || eligible.find((w) => w.category === 'sketch') || eligible[0];
  }

  function referencePrompt(option, description) {
    const masses = option.masses.map((m) => `${m.use}: ${m.floors} floors, base ${m.base_m} m, top ${m.top_m} m`).join('; ');
    return 'In <ref_image_0>, edit only the facade finish, lighting and planting to create a realistic architectural material study. ' +
      'Use the supplied axonometric massing image as the design reference. Preserve the exact building silhouette, straight vertical walls, floor lines, flat rooflines, camera, plot outline, footprints, courtyards and podium. ' +
      `Keep every existing floor: ${masses}. Do not remove or add floors, introduce stepped terraces or setbacks, reshape the tower, or switch to an eye-level view. ` +
      `Apply these surface and lighting changes only: ${description}\n` +
      'Keep the original massing; add facade finish, glazing and planting without changing its outline. One view, no collage or lettering. This is a visual concept, not verified CAD geometry.';
  }

  async function png(svg) {
    const image = new Image();
    const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'}));
    try {
      await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error('Could not prepare the geometry reference')); image.src = url; });
      const canvas = document.createElement('canvas'); canvas.width = 1344; canvas.height = 768;
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
      return await new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Could not export the geometry reference')), 'image/png'));
    } finally { URL.revokeObjectURL(url); }
  }

  function drawingSvg(markup, fit) {
    const svg = markup.match(/<svg\b[\s\S]*?<\/svg>/)?.[0];
    if (!svg) return '<p>Plan not available.</p>';
    return svg.replace(/\s+id="[^"]*"/g, '').replace(/viewBox="[^"]*"/, `viewBox="${fit}"`)
      .replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" width="1344" height="768" ');
  }

  function board({title, option, site, floor, massing, visuals = []}) {
    const m = option.metrics;
    const panel = (name, body, dark = false) => `<figure><figcaption>${H(name)}</figcaption><div class="ed-board-panel${dark ? ' dark' : ''}">${body}</div></figure>`;
    return `<article class="ed-board"><header><h2>${H(title)} — early design concept</h2><p>${H(option.name)} · GFA ${H(m.gfa)} m² · FAR ${H(m.far)} · Height ${H(m.height_m)} m</p></header>
      <div class="ed-board-grid">${panel('Site plan — calculated geometry', site, true)}${panel('Floor zoning — calculated geometry', floor)}${panel('Massing — calculated geometry', massing)}
      ${visuals.map((v) => panel(v.reverse ? 'Reverse view — AI visual concept' : 'Primary view — AI visual concept', `<img alt="AI visual concept" src="${H(v.src)}">`)).join('')}</div>
      <footer><p>Target GFA: ${H(m.target_gfa)} m² · Achieved: ${H(m.gfa_pct_of_target)}%. Parking demand estimate: ${H(m.parking_required)} bays; ${H(m.basements_needed)} basement level(s) estimated from area, not a drawn parking layout.</p>
      <p>${H(option.summary)}</p><p>Floor zoning shows unit envelopes, circulation and cores; detailed rooms and basement layouts are not included. AI visuals may depart from geometry. Plans and views are concepts; rule checks use the configured inputs and do not establish authority approval.</p></footer></article>`;
  }

  const css = '.ed-board{background:#fff;color:#202a35;padding:24px;font:14px/1.5 Arial,sans-serif}.ed-board h2{margin:0;font-size:23px}.ed-board header{border-bottom:2px solid #283b4a;margin-bottom:18px}.ed-board-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.ed-board figure{margin:0;border:1px solid #d6dde1;overflow:hidden}.ed-board figcaption{padding:8px 12px;background:#edf1f3;font-weight:bold}.ed-board-panel{aspect-ratio:7/4;background:#fbfbfc;display:flex;align-items:center;justify-content:center;overflow:hidden}.ed-board-panel.dark{background:#111827;color:#fff}.ed-board-panel svg,.ed-board-panel img{width:100%;height:100%;object-fit:contain}.ed-board footer{font-size:12px;border-top:1px solid #ddd;margin-top:18px}@media(max-width:700px){.ed-board-grid{grid-template-columns:1fr}}@media print{.ed-board figure{break-inside:avoid}.ed-board{padding:0}}';
  window.EarlyDesignPresentation = {massingScene, massingSvg, selectWorkflow, referencePrompt, png, drawingSvg, board, css};
})();
