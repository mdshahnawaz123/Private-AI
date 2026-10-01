/* ============================================================
   EXPO DESIGN AI — Response Rendering Engine (frontend half)
   ui/response_renderer.js

   Purely additive. Converts the structured-JSON object the backend
   now attaches to each streamed answer (response_schema.py, SSE
   event type:"structured") into a trusted, hand-built DOM — never
   innerHTML'd from raw AI text. Text and URLs are escaped; nothing
   here executes AI-authored markup.

   Contract: window.ExpoResponseRenderer.render(structured, opts) -> HTMLElement | null
   Returns null for a plain conversational answer (type "simple_answer")
   so the caller (ui/app.js stream()) keeps its existing mdLite() plain
   text bubble exactly as before. Everything else (document_analysis,
   table, calculation, comparison, warning, error, not_found, bim_qa,
   compliance, report) renders as a structured card.

   Does NOT touch: Qwen 4B chat, Qwen 32B vision, document viewer,
   tiling, indexing/retrieval. Source-tile clicks call the EXISTING
   document viewer via window.openSourceTile (added in app.js), which
   reuses openFile/openInViewer — no second viewer is created here.
   ============================================================ */
(function(){
  'use strict';

  const esc = s => (s==null?'':String(s)).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const escAttr = esc;
  let _seq = 0;
  const uid = p => `${p}${++_seq}`;

  const STATUS_COLOR = {
    'EXTRACTED':'blue', 'VERIFIED':'green', 'CALCULATED':'purple', 'PASS':'green',
    'REVIEW REQUIRED':'amber', 'WARNING':'amber', 'ERROR':'red', 'NOT FOUND':'gray'
  };
  const TYPE_LABEL = {
    document_analysis:'Document Analysis', table:'Data Table', calculation:'Calculation',
    comparison:'Comparison', warning:'Warning', error:'Error', not_found:'Not Found',
    bim_qa:'BIM QA Result', drawing_review:'Drawing Review', compliance:'Compliance Result',
    report:'Report', simple_answer:'Answer'
  };

  function statusChip(status){
    const key = String(status||'').toUpperCase();
    const c = STATUS_COLOR[key] || 'gray';
    return `<span class="rr-status rr-c-${c}">${esc(key||'—')}</span>`;
  }
  function confChip(conf){
    const c = conf==='high'?'green':conf==='medium'?'amber':'gray';
    return `<span class="rr-conf rr-c-${c}" title="Confidence based on number of sources and whether the focused document was used">
      <span class="rr-dot"></span>${esc((conf||'medium').toUpperCase())} CONFIDENCE</span>`;
  }

  /* ---------------- metric cards ---------------- */
  function metricsHTML(metrics){
    if(!metrics || !metrics.length) return '';
    return `<div class="rr-metrics">${metrics.map(m=>`
      <div class="rr-metric">
        <div class="rr-metric-label">${esc(m.label)}</div>
        <div class="rr-metric-value">${esc(m.value)}</div>
        ${m.description?`<div class="rr-metric-desc">${esc(m.description)}</div>`:''}
        <div class="rr-metric-badge">${statusChip(m.status||'EXTRACTED')}</div>
      </div>`).join('')}</div>`;
  }

  /* ---------------- data tables (sticky header, search, sort, export) ---------------- */
  function tableHTML(t, idx){
    const tid = uid('rrtbl');
    const cols = t.columns||[];
    const rows = t.rows||[];
    return `<div class="rr-table-wrap" data-rr-table-idx="${idx}">
      <div class="rr-table-toolbar">
        <b>${esc(t.title||('Table '+(idx+1)))}</b>
        <input class="rr-table-search" data-for="${tid}" placeholder="Search table…">
      </div>
      <div class="rr-table-scroll">
      <table class="rr-table" id="${tid}">
        <thead><tr>${cols.map((c,ci)=>`<th data-ci="${ci}">${esc(c)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
      </div>
    </div>`;
  }

  /* ---------------- calculations: source vs calculated ---------------- */
  function calcHTML(calcs){
    if(!calcs || !calcs.length) return '';
    return `<div class="rr-section"><div class="rr-section-h">Calculations</div>
      ${calcs.map(c=>`
      <div class="rr-calc">
        <div class="rr-calc-row"><span class="rr-calc-k">Input</span><span>${esc(c.input||'—')}</span></div>
        <div class="rr-calc-row"><span class="rr-calc-k">Formula</span><span class="rr-mono">${esc(c.formula||'—')}</span></div>
        <div class="rr-calc-row"><span class="rr-calc-k">Result</span><span><b>${esc(c.result)}</b> ${esc(c.units||'')} ${statusChip('CALCULATED')}</span></div>
        ${c.source?`<div class="rr-calc-row"><span class="rr-calc-k">Source</span><span>${esc(c.source)}</span></div>`:''}
      </div>`).join('')}
    </div>`;
  }

  /* ---------------- issues / warnings ---------------- */
  function issuesHTML(issues){
    if(!issues || !issues.length) return '';
    return `<div class="rr-section"><div class="rr-section-h">Issues</div>
      ${issues.map(i=>`<div class="rr-issue rr-c-${STATUS_COLOR[i.severity]||'amber'}">
        ${statusChip(i.severity)}<span>${esc(i.text)}</span></div>`).join('')}
    </div>`;
  }

  /* ---------------- source evidence ---------------- */
  function sourcesHTML(sources){
    if(!sources || !sources.length) return '';
    return `<div class="rr-section"><div class="rr-section-h">Source Evidence</div>
      <div class="rr-sources">${sources.map(s=>{
        const rel = s.rel||s.document||'';
        const label = `${s.document||'source'}${s.page!=null?(' · p.'+s.page):''}${s.section?(' · '+s.section):''}`;
        return `<div class="rr-source">
          <div class="rr-source-main">
            <span class="rr-source-doc">${esc(s.document||'source')}</span>
            ${s.page!=null?`<span class="rr-source-pg">Page ${esc(s.page)}</span>`:''}
            ${s.section?`<span class="rr-source-sec">${esc(s.section)}</span>`:''}
            ${s.revision?`<span class="rr-source-rev">Rev ${esc(s.revision)}</span>`:''}
          </div>
          ${s.tile_id?`<div class="rr-source-tile">Tile: ${esc(s.tile_id)}</div>`:''}
          <button class="rr-btn-sm rr-view-tile" data-rel="${escAttr(rel)}" data-page="${esc(s.page!=null?s.page:'')}">[ VIEW SOURCE TILE ]</button>
        </div>`;
      }).join('')}</div>
    </div>`;
  }

  /* ---------------- export action bar ---------------- */
  function exportsHTML(structured){
    const t = structured.type;
    const buttons = [];
    buttons.push(`<button class="rr-btn" data-rr-act="copy">Copy</button>`);
    if(t==='table' || (structured.tables && structured.tables.length)){
      buttons.push(`<button class="rr-btn" data-rr-act="export-csv">CSV</button>`);
      buttons.push(`<button class="rr-btn" data-rr-act="export-xlsx">Excel</button>`);
    }
    if(t!=='table' && t!=='simple_answer'){
      buttons.push(`<button class="rr-btn" data-rr-act="export-html">HTML</button>`);
      buttons.push(`<button class="rr-btn" data-rr-act="export-json">JSON</button>`);
      if(t==='report') buttons.push(`<button class="rr-btn" data-rr-act="export-xlsx">Excel</button>`);
    }
    return `<div class="rr-exports">${buttons.join('')}</div>`;
  }

  /* ---------------- long-answer collapsible wrapper ---------------- */
  function section(title, bodyHtml, openByDefault){
    if(!bodyHtml) return '';
    const id = uid('rrsec');
    return `<div class="rr-collapse ${openByDefault?'open':''}">
      <div class="rr-collapse-h" data-rr-toggle="${id}"><span class="rr-chev">▸</span>${esc(title)}</div>
      <div class="rr-collapse-b" id="${id}">${bodyHtml}</div>
    </div>`;
  }

  /* ================= main render ================= */
  function render(structured, opts){
    opts = opts || {};
    if(!structured || structured.type === 'simple_answer') return null;

    const t = structured.type;
    const isLong = (structured.full_text||structured.summary||'').length > 900;
    const card = document.createElement('div');
    card.className = 'rr-card rr-type-' + t;
    card._rr = structured;

    const typeLabel = TYPE_LABEL[t] || t;
    const header = `<div class="rr-head">
        <div class="rr-head-top">
          <span class="rr-type-badge">${esc(typeLabel)}</span>
          <span style="display:flex;align-items:center;gap:8px">
            ${confChip(structured.confidence)}
            <button class="rr-btn-sm" data-rr-act="theme" title="Toggle light/dark" style="margin-left:0">🌓</button>
          </span>
        </div>
        ${structured.title?`<div class="rr-title">${esc(structured.title)}</div>`:''}
        ${structured.subtitle?`<div class="rr-subtitle">${esc(structured.subtitle)}</div>`:''}
      </div>`;

    // Only show the prose summary when there's no table/metric data telling the same
    // story below it — avoids restating "353 racks" in a paragraph right above a table
    // that already says it.
    const hasData = (structured.tables&&structured.tables.length) || (structured.metrics&&structured.metrics.length);
    const summary = (structured.summary && !hasData) ? `<div class="rr-summary">${esc(structured.summary)}</div>` : '';
    const metrics = metricsHTML(structured.metrics);
    const tables = (structured.tables||[]).map((tb,i)=>tableHTML(tb,i)).join('');
    const calcs = calcHTML(structured.calculations);
    const issues = issuesHTML(structured.issues);
    const sources = sourcesHTML(structured.sources);
    const exportsBar = exportsHTML(structured);

    let body;
    if(isLong){
      body = section('Summary', summary, true)
           + section('Key Findings / Metrics', metrics, true)
           + section('Data', tables, true)
           + section('Calculations', calcs, false)
           + section('Issues', issues, true)
           + section('Source Evidence', sources, false);
    } else {
      body = summary + metrics + tables + calcs + issues + sources;
    }

    card.innerHTML = header + `<div class="rr-body">${body}</div>` + exportsBar;
    wire(card, structured);
    return card;
  }

  /* ================= interactivity ================= */
  function wire(card, structured){
    card.querySelectorAll('[data-rr-toggle]').forEach(h=>{
      h.addEventListener('click', ()=>{
        const b = card.querySelector('#'+h.dataset.rrToggle);
        const open = h.parentElement.classList.toggle('open');
        if(b) b.style.display = open ? '' : 'none';
      });
    });
    card.querySelectorAll('.rr-collapse:not(.open) .rr-collapse-b').forEach(b=>b.style.display='none');

    card.querySelectorAll('.rr-table-search').forEach(inp=>{
      inp.addEventListener('input', ()=>{
        const tbl = card.querySelector('#'+inp.dataset.for);
        if(!tbl) return;
        const q = inp.value.toLowerCase();
        tbl.querySelectorAll('tbody tr').forEach(tr=>{
          tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
      });
    });
    card.querySelectorAll('.rr-table').forEach(tbl=>{
      tbl.querySelectorAll('th').forEach((th,ci)=>{
        th.addEventListener('click', ()=>{
          const tb = tbl.querySelector('tbody');
          const rows = [...tb.querySelectorAll('tr')];
          const asc = !th._asc; th._asc = asc;
          rows.sort((a,b)=>{
            const x=(a.children[ci]||{}).textContent||'', y=(b.children[ci]||{}).textContent||'';
            const nx=parseFloat(x), ny=parseFloat(y);
            if(!isNaN(nx)&&!isNaN(ny)) return asc?nx-ny:ny-nx;
            return asc?x.localeCompare(y):y.localeCompare(x);
          });
          rows.forEach(r=>tb.appendChild(r));
        });
      });
    });

    card.querySelectorAll('.rr-view-tile').forEach(btn=>{
      btn.addEventListener('click', ()=>{
        const rel = btn.dataset.rel, page = btn.dataset.page;
        if(window.openSourceTile) window.openSourceTile(rel, page ? parseInt(page,10) : null);
      });
    });

    card.querySelectorAll('[data-rr-act]').forEach(btn=>{
      btn.addEventListener('click', ()=>{
        const act = btn.dataset.rrAct;
        try{
          if(act==='theme') card.classList.toggle('rr-light');
          else if(act==='copy') copyText(plainTextOf(structured));
          else if(act==='copy-table') copyText(tableToTSV(structured.tables[+btn.dataset.idx]));
          else if(act==='export-json') downloadFile(JSON.stringify(structured,null,2), fileBase(structured)+'.json', 'application/json');
          else if(act==='export-html') downloadFile(standaloneHTML(structured), fileBase(structured)+'.html', 'text/html');
          else if(act==='export-csv') downloadFile(allTablesToCSV(structured), fileBase(structured)+'.csv', 'text/csv');
          else if(act==='export-table-csv') downloadFile(tableToCSV(structured.tables[+btn.dataset.idx]), fileBase(structured)+'-table'+(+btn.dataset.idx+1)+'.csv', 'text/csv');
          else if(act==='export-xlsx' || act==='export-table-xlsx'){
            const single = act==='export-table-xlsx' ? structured.tables[+btn.dataset.idx] : null;
            downloadFile(buildSpreadsheetXML(structured, single), fileBase(structured)+'.xls', 'application/vnd.ms-excel');
          }
          if(act!=='theme' && window.toast) window.toast('Exported');
        }catch(e){ if(window.toast) window.toast('Export failed: '+(e.message||e)); }
      });
    });
  }

  /* ================= helpers: text / copy ================= */
  function fileBase(structured){
    return (structured.title||structured.type||'response').toLowerCase().replace(/[^a-z0-9]+/g,'-').slice(0,60) || 'response';
  }
  function plainTextOf(structured){
    const lines = [];
    if(structured.title) lines.push(structured.title);
    if(structured.summary) lines.push(structured.summary);
    (structured.metrics||[]).forEach(m=>lines.push(`${m.label}: ${m.value}`));
    (structured.tables||[]).forEach(t=>{
      lines.push(t.title||'');
      lines.push((t.columns||[]).join('\t'));
      (t.rows||[]).forEach(r=>lines.push(r.join('\t')));
    });
    (structured.issues||[]).forEach(i=>lines.push(`[${i.severity}] ${i.text}`));
    return lines.filter(Boolean).join('\n');
  }
  function copyText(text){
    if(navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text);
    else { const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
  }
  function downloadFile(content, filename, mime){
    const blob = new Blob([content], {type: mime+';charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click();
    setTimeout(()=>{ URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  function csvEscape(v){ v=String(v==null?'':v); return /[",\n]/.test(v) ? '"'+v.replace(/"/g,'""')+'"' : v; }
  function tableToCSV(t){ if(!t) return ''; const rows=[t.columns||[]].concat(t.rows||[]); return rows.map(r=>r.map(csvEscape).join(',')).join('\r\n'); }
  function tableToTSV(t){ if(!t) return ''; const rows=[t.columns||[]].concat(t.rows||[]); return rows.map(r=>r.join('\t')).join('\n'); }
  function allTablesToCSV(structured){
    const blocks = (structured.tables||[]).map(t=>`${t.title||''}\r\n${tableToCSV(t)}`);
    if(!blocks.length && structured.metrics && structured.metrics.length){
      blocks.push(['Label,Value,Status'].concat(structured.metrics.map(m=>[m.label,m.value,m.status].map(csvEscape).join(','))).join('\r\n'));
    }
    return blocks.join('\r\n\r\n');
  }

  /* SpreadsheetML (Excel 2003 XML) — no external library, opens natively in Excel,
     supports multiple named sheets + freeze panes + number formatting hints. */
  function xmlEsc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function ssCell(v){
    const n = (typeof v === 'number') ? v : (/^-?[0-9]+(\.[0-9]+)?%?$/.test(String(v||'').trim()) ? parseFloat(v) : NaN);
    if(!isNaN(n) && v !== '' && v != null && !/[a-zA-Z]/.test(String(v))){
      return `<Cell><Data ss:Type="Number">${n}</Data></Cell>`;
    }
    return `<Cell><Data ss:Type="String">${xmlEsc(v)}</Data></Cell>`;
  }
  function ssSheet(name, header, rows){
    return `<Worksheet ss:Name="${xmlEsc(name).slice(0,31)}">
      <Table>
        <Row ss:StyleID="hdr">${(header||[]).map(h=>`<Cell><Data ss:Type="String">${xmlEsc(h)}</Data></Cell>`).join('')}</Row>
        ${(rows||[]).map(r=>`<Row>${r.map(ssCell).join('')}</Row>`).join('')}
      </Table>
      <WorksheetOptions xmlns="urn:schemas-microsoft-com:office:excel">
        <FreezePanes/><FrozenNoSplit/><SplitHorizontal>1</SplitHorizontal><TopRowBottomPane>1</TopRowBottomPane>
        <Selected/>
      </WorksheetOptions>
    </Worksheet>`;
  }
  function buildSpreadsheetXML(structured, singleTable){
    const sheets = [];
    if(!singleTable){
      const summaryRows = [
        ['Title', structured.title||''],
        ['Type', structured.type||''],
        ['Confidence', structured.confidence||''],
        ['Summary', structured.summary||''],
      ];
      sheets.push(ssSheet('Summary', ['Field','Value'], summaryRows));
      if(structured.metrics && structured.metrics.length){
        sheets.push(ssSheet('Metrics', ['Label','Value','Status','Description'],
          structured.metrics.map(m=>[m.label,m.value,m.status,m.description||''])));
      }
      (structured.tables||[]).forEach((t,i)=>{
        sheets.push(ssSheet((t.title||'Table'+(i+1)).slice(0,28), t.columns||[], t.rows||[]));
      });
      if(structured.sources && structured.sources.length){
        sheets.push(ssSheet('Source Evidence', ['Document','Page','Section','Tile','Revision'],
          structured.sources.map(s=>[s.document,s.page!=null?s.page:'',s.section||'',s.tile_id||'',s.revision||''])));
      }
    } else {
      sheets.push(ssSheet(singleTable.title||'Table', singleTable.columns||[], singleTable.rows||[]));
    }
    return `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Styles>
  <Style ss:ID="hdr"><Font ss:Bold="1"/><Interior ss:Color="#E2E8F0" ss:Pattern="Solid"/></Style>
 </Styles>
 ${sheets.join('\n')}
</Workbook>`;
  }

  function standaloneHTML(structured){
    const body = `
    <h1>${esc(structured.title||'Response')}</h1>
    <p class="sub">${esc(structured.subtitle||'')}</p>
    <p>${esc(structured.summary||'')}</p>
    ${(structured.metrics||[]).length?`<h2>Metrics</h2><table>${(structured.metrics||[]).map(m=>`<tr><th>${esc(m.label)}</th><td>${esc(m.value)}</td><td>${esc(m.status)}</td></tr>`).join('')}</table>`:''}
    ${(structured.tables||[]).map(t=>`<h2>${esc(t.title||'Table')}</h2><table><thead><tr>${(t.columns||[]).map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${(t.rows||[]).map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`).join('')}
    ${(structured.issues||[]).length?`<h2>Issues</h2><ul>${(structured.issues||[]).map(i=>`<li><b>[${esc(i.severity)}]</b> ${esc(i.text)}</li>`).join('')}</ul>`:''}
    ${(structured.sources||[]).length?`<h2>Source Evidence</h2><ul>${(structured.sources||[]).map(s=>`<li>${esc(s.document)}${s.page!=null?' · p.'+esc(s.page):''}${s.section?' · '+esc(s.section):''}</li>`).join('')}</ul>`:''}
    <p class="conf">Confidence: ${esc(structured.confidence||'')}</p>`;
    return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(structured.title||'Response')}</title>
    <style>body{font-family:Arial,Helvetica,sans-serif;max-width:900px;margin:32px auto;color:#172033;background:#F4F7FB}
    h1{margin-bottom:2px}.sub{color:#64748B;margin-top:0}
    table{border-collapse:collapse;width:100%;margin:10px 0 20px;background:#fff}
    th,td{border:1px solid #E2E8F0;padding:6px 10px;text-align:left;font-size:13px}
    th{background:#F4F7FB}.conf{color:#64748B;font-size:12px}</style></head>
    <body>${body}</body></html>`;
  }

  window.ExpoResponseRenderer = { render };
})();
