/* Follow-up edits on the last chart in a chat ("show labels", "make it a bar chart",
   "only top 5", "add approved GFA too"). The server's local model decides what the
   message means; the values are re-computed in code (POST /api/visualize/edit). */
(function (window) {
  'use strict';
  const HINT = /\b(label|labels|value|values|number|numbers|percent|percentage|%|sort|order|top|largest|smallest|highest|lowest|pie|donut|doughnut|bar|line|stack|stacked|chart|graph|title|rename|legend|remove|exclude|without|only|change|convert|switch|instead|make it|show|hide|add|also|include|compare|filter|limit)\b/i;
  let last = null;
  function remember(spec, question, project) { if (spec) last = { spec, question: question || '', project: project || '' }; }
  function forget() { last = null; }
  async function tryEdit(text, project) {
    if (!last || !text || text.length > 220 || !HINT.test(text)) return null;
    if (project && last.project && project !== last.project) return null;
    if (/\b(from\s+the|from\s+sheet|from\s+table|new\s+chart|another\s+chart|regarding|budget|zoning|population|land use)\b/i.test(text)) return null;
    let token = null; try { token = localStorage.getItem('expo_token'); } catch (e) {}
    const r = await fetch('/api/visualize/edit', { method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, token ? { Authorization: 'Bearer ' + token } : {}),
      body: JSON.stringify({ spec: last.spec, instruction: text, question: last.question, project: project || last.project }) });
    if (!r.ok) return null;
    const d = await r.json();
    if (!d || !d.is_edit) return null;
    if (d.spec) remember(d.spec, d.question || last.question, project || last.project);
    return d;
  }
  function render(bubble, d) {
    if (d.error) { bubble.insertAdjacentHTML('beforeend', '<p style="color:#f2585f">' + String(d.error).replace(/[<&]/g, '') + '</p>'); return; }
    const box = document.createElement('div'); box.style.cssText = 'margin-top:8px;max-width:760px'; bubble.appendChild(box);
    const w = window.ExpoChartRenderer && window.ExpoChartRenderer.render(d.spec, box);
    if (w && window.ExpoMotion) window.ExpoMotion.attach(w);
  }
  window.ExpoChartChat = { remember, forget, tryEdit, render, get last() { return last; } };
})(window);
