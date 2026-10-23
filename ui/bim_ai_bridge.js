// Parent-side request/receipt bridge. Only the active same-origin viewer may reply.
(function(){
  async function request(frame, project, operation, actions) {
    if(!frame || !frame.contentWindow) throw new Error('Open the 3D model viewer first');
    const source=frame.contentWindow, requestId=crypto.randomUUID();
    return new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>{cleanup();reject(new Error(operation==='execute'
        ?'Viewer completion is unconfirmed. Check the model before retrying; the action may still be running.'
        :'The model viewer is not ready. Wait for loading to finish and try again.'));},operation==='execute'?60000:10000);
      function cleanup(){clearTimeout(timeout);window.removeEventListener('message',receive);}
      function receive(event){
        const data=event.data||{};
        if(event.origin!==location.origin||event.source!==source||data.type!=='expo:bim:response'||data.requestId!==requestId||data.project!==project)return;
        cleanup();resolve(data.result);
      }
      window.addEventListener('message',receive);
      const msgPayload = operation === 'bimAction'
        ? {type:'expo:bim:request',requestId,project,operation:'bimAction',action:actions.action,items:actions.items}
        : {type:'expo:bim:request',requestId,project,operation,actions};
      source.postMessage(msgPayload,location.origin);
    });
  }
  function candidate(q){return /\b(select|hide|show|isolate|colou?r|highlight|reset|restore|undo|fit|zoom extents|properties|material|paint|conceal|display|remove|make|change)\b/i.test(q);}
  async function run({question,project,frame,isCurrent}) {
    if(!candidate(question))return {handled:false};
    try {
      const context=await request(frame,project,'context');
      if(!context.ready)return {handled:true,message:'Load a model in the 3D viewer first.'};
      const response=await fetch('/api/bim/plan-view-action',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({project,question,categories:context.categories})});
      if(!response.ok)throw new Error('Viewer planning request failed (HTTP '+response.status+').');
      const plan=await response.json();
      if(!plan.handled)return {handled:true,message:'No viewer action was applied. That request could not be represented by the available view tools. Try “hide walls”, “show only columns”, “colour doors red”, “properties of the selected element”, or “reset view”.'};
      if(plan.error)return {handled:true,message:plan.error};
      if(!isCurrent()||frame.contentWindow!==document.getElementById('viewerFrame')?.contentWindow)
        throw new Error('Project or viewer changed; action was not sent.');
      let result;
      if (plan.operation === 'bimAction' && plan.items) {
        result = await request(frame, project, 'bimAction', {action: plan.action || 'isolate', items: plan.items});
        result = {ok: result.ok, message: plan.message || 'Isolated element(s).'};
      } else {
        result = await request(frame, project, 'execute', plan.actions);
      }
      if(!isCurrent())return {handled:true,message:'The action finished in the previous viewer. The current project view was not targeted.'};
      return {handled:true,...result,planner:plan.planner};
    }catch(error){return {handled:true,message:error.message||String(error)};}
  }
  window.ExpoBimChat={request,run,candidate};
})();
