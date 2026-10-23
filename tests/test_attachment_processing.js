const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{},fetch:()=>{},setTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync('ui/attachment_processing.js','utf8'),context);
const wait = context.window.ExpoAttachmentProcessing.waitReady;
// Exercise the real composer function, not a duplicate implementation.
const composerSource = fs.readFileSync('ui/cowork_studio.js','utf8');
const start = composerSource.indexOf('function updateSendBtnState()');
const end = composerSource.indexOf('window.cwsOnSendOrStop', start);
assert.ok(start >= 0 && end > start);
const button = {classList:{add(){},remove(){},toggle(){}}};
const input = {value:'What does the report state?'};
const composer = {CWS_STATE:{streaming:false,attachedFiles:[]}, ICONS:{send:'send',stop:'stop'},
  document:{getElementById:id=>id==='cwsSendBtn'?button:input}};
vm.createContext(composer);
vm.runInContext(composerSource.slice(start,end),composer);
for (const status of ['uploading','processing','error','ready']) {
  composer.CWS_STATE.attachedFiles = [{status}];
  composer.updateSendBtnState();
  assert.equal(button.disabled,status!=='ready',status);
}
for (const page of ['ui/app.html','ui/classic.html']) {
  const html=fs.readFileSync(page,'utf8');
  assert.ok(html.indexOf('attachment_processing.js')>=0 && html.indexOf('attachment_processing.js')<html.indexOf('cowork_studio.js'),page);
}
const historyStart=composerSource.indexOf('function getConversationAttachment(messages)');
const historyEnd=composerSource.indexOf('window.cwsSendMessage =',historyStart);
vm.runInContext(composerSource.slice(historyStart,historyEnd),composer);
assert.equal(composer.getConversationAttachment([]),null);
assert.equal(composer.getConversationAttachment([{attachments:[{attachmentId:5}]},{role:'assistant',content:'answer'}]).attachmentId,5);
assert.equal(composer.getConversationAttachment([{attachments:[{attachmentId:5}]},{attachments:[{attachmentId:9}]}]).attachmentId,9);
assert.match(composerSource,/composerModeSeg:\s*'chat'/);
(async()=>{
  let calls=0, progress=[];
  const result=await wait(12,{fetcher:async()=>({ok:true,json:async()=>++calls===1?{status:'processing',progress:{stage:'reading pages',done:1,total:3}}:{status:'ready'}}),
    pause:async()=>{},onProgress:record=>progress.push(record.status)});
  assert.equal(result.status,'ready');
  assert.deepEqual(progress,['processing','ready']);
  await assert.rejects(wait(12,{fetcher:async()=>({ok:true,json:async()=>({status:'error'})}),pause:async()=>{}}),/processing failed/);
  await assert.rejects(wait(12,{fetcher:async()=>({ok:false,json:async()=>({detail:'Not found'})}),pause:async()=>{}}),/Not found/);
  await assert.rejects(wait(12,{fetcher:async()=>({ok:true,json:async()=>({status:'processing'})}),pause:async()=>{},maxPolls:2}),/longer than expected/);
  console.log('PASS: attachment readiness waits for server extraction, rejects failures, respects authorization failures and bounds waiting.');
})().catch(error=>{console.error(error);process.exitCode=1;});
