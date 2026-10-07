const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(require('path').join(__dirname, '../ui/app.js'), 'utf8');
const start = source.indexOf('async function stream(');
const end = source.indexOf('/* Open a cited source', start);
const bubble = { innerHTML: '' };
const history = [];
const context = {
  addMsg: () => bubble,
  fetch: async () => ({ ok: false, status: 503, json: async () => ({ detail: 'Local AI is busy. Please retry shortly. <unsafe>' }) }),
  esc: value => value.replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
  aiHist: history,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.stream('', '/ask_stream', { query: 'Question' });
  assert(bubble.innerHTML.includes('Local AI is busy. Please retry shortly.'));
  assert(bubble.innerHTML.includes('&lt;unsafe&gt;'));
  assert(!bubble.innerHTML.includes('<unsafe>'));
  assert.strictEqual(history.length, 0);
  console.log('PASS: busy response is readable, escaped, and excluded from answer history');
})().catch(error => { console.error(error); process.exitCode = 1; });
