// Allowlisted Fragments view tools. No file writes, generated JavaScript or guessed IDs.
const TOOLS = new Set(['hide','show','isolate','color','properties','reset','undo','fit']);
const MAX_FILTER_ITEMS = 2000;
const DATA_CONFIG = { attributesDefault:true, relations:{
  IsDefinedBy:{attributes:true,relations:true},
  HasAssociations:{attributes:true,relations:true},
  IsTypedBy:{attributes:true,relations:true},
} };

// IFC relations are graphs, including references back to the same object.
// Produce bounded, serializable evidence rather than recursing forever or dropping properties.
export function readableIfc(value, seen=new WeakSet(), depth=0, budget={left:15000}) {
  if(value===null||typeof value!=='object')return typeof value==='string'&&value.length>4000?value.slice(0,4000)+' [truncated]':value;
  const id=value._localId?.value??value._localId??null;
  if(seen.has(value))return {reference:id};
  if(depth>14||budget.left--<=0)return {reference:id,note:'Property graph truncated; inspect the source model for full relations.'};
  seen.add(value);
  if(Array.isArray(value)){
    const result=value.slice(0,500).map(item=>readableIfc(item,seen,depth+1,budget));
    if(value.length>500)result.push({note:'Property graph truncated; inspect the source model for full relations.'});
    return result;
  }
  return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,readableIfc(v,seen,depth+1,budget)]));
}

export function createBimTools({getModels, getSelected, update, fit, makeColor, getCameraState, restoreCameraState}) {
  const history = [];
  let colors = new Map();
  let busy = false;
  const models = () => getModels().filter(x => x.model);
  const key = row => row.model.modelId;
  async function context(includeSelection=false) {
    const list = models();
    const categories = new Set();
    const summaries = [];
    const counts = {};
    for (const row of list) {
      const family = await row.model.getCategories();
      for (const category of family) categories.add(category);
      const found = await row.model.getItemsOfCategories(family.map(c=>new RegExp('^'+c+'$')));
      const modelCounts = {};
      for (const category of family) {
        const count = new Set(found[category] || []).size;
        modelCounts[category] = count;
        counts[category] = (counts[category] || 0) + count;
      }
      summaries.push({id:key(row),name:row.name||key(row),counts:modelCounts});
    }
    const selected=getSelected();
    const selectedModel=selected && list.find(row=>key(row)===selected.modelId);
    const selectionData=includeSelection&&selectedModel ? (await selectedModel.model.getItemsData([selected.localId],DATA_CONFIG)).map(item=>readableIfc(item)) : [];
    return {ready:!!list.length, models:summaries, counts, counts_complete:true,
      categories:[...categories].sort(), selected:selected||null, selectionData};
  }
  async function capture(list) {
    const state = [];
    for (const row of list) {
      const ids = await row.model.getItemsIdsWithGeometry();
      state.push({row, ids, visible:await row.model.getVisible(ids), objectVisible:row.model.object?.visible??true});
    }
    return {state, camera:getCameraState?.(), colors:new Map([...colors].map(([id,c]) => [id,new Map(c)]))};
  }
  async function restore(snapshot) {
    if(snapshot.state.some(({row})=>!models().some(current=>current.model===row.model)))
      throw new Error('Loaded models changed; undo is unavailable');
    for (const {row,ids,visible,objectVisible} of snapshot.state) {
      await row.model.setVisible(ids.filter((_,i)=>!visible[i]),false);
      await row.model.setVisible(ids.filter((_,i)=>visible[i]),true);
      if(row.model.object)row.model.object.visible=objectVisible;
      const changed = new Set([...(colors.get(key(row))||new Map()).keys(), ...(snapshot.colors.get(key(row))||new Map()).keys()]);
      if (changed.size) await row.model.resetColor([...changed]);
      for (const [id,color] of snapshot.colors.get(key(row))||[]) await row.model.setColor([id],makeColor(color));
    }
    colors = snapshot.colors;
    if(snapshot.camera&&restoreCameraState)await restoreCameraState(snapshot.camera);
    await update();
  }
  async function targets(action, list) {
    const selected = getSelected();
    if (action.selected && !selected) throw new Error('Select an element in the viewer first');
    const result = [];
    for (const row of list) {
      let ids = [];
      const all = new Set(await row.model.getItemsIdsWithGeometry());
      if (action.selected) {
        if (selected.modelId === key(row) && all.has(selected.localId)) ids = [selected.localId];
      } else {
        const cats = await row.model.getCategories();
        const family = cats.filter(c => c === action.category || c === action.category+'STANDARDCASE');
        if (family.length) {
          const found = await row.model.getItemsOfCategories(family.map(c=>new RegExp('^'+c+'$')));
          ids = [...new Set(Object.values(found).flat())].filter(id=>all.has(id));
        }
      }
      result.push({row, ids});
    }
    if (action.text_match) {
      if (result.reduce((n,x)=>n+x.ids.length,0)>MAX_FILTER_ITEMS) throw new Error('Property filter exceeds 2,000 elements; select a smaller category or an individual element');
      for (const target of result) {
        const matched = [];
        for (let i=0;i<target.ids.length;i+=50) {
          const batch=target.ids.slice(i,i+50);
          const data=(await target.row.model.getItemsData(batch,DATA_CONFIG)).map(item=>readableIfc(item));
          if(JSON.stringify(data).includes('Property graph truncated;'))throw new Error('The IFC property graph is too large for a complete text filter; select a smaller set of elements');
          // Preserve IDs returned by Fragments; never assume its data ordering.
          const values = value => value && typeof value==='object'
            ? Object.values(value).flatMap(values) : [String(value??'').toLowerCase()];
          for (const item of data) if (values(item).some(value=>value.includes(action.text_match.toLowerCase()))) {
            const id = item._localId?.value ?? item._localId;
            if (batch.includes(id)) matched.push(id);
          }
        }
        target.ids = matched;
      }
    }
    if (!result.some(x=>x.ids.length)) throw new Error('No loaded geometry matches that selector; the view was not changed');
    return result;
  }
  async function execute(actions) {
    if (busy) return {ok:false,message:'Another viewer action is still running; wait for its result.'};
    busy = true;
    let snapshot;
    try {
      if (!Array.isArray(actions)||!actions.length||actions.length>4) throw new Error('Invalid action list');
      const list=models();
      if (!list.length) throw new Error('Load a model in the 3D viewer first');
      for (const action of actions) {
        if (!TOOLS.has(action.tool)) throw new Error('Unsupported BIM tool');
        if (action.selected && action.category) throw new Error('Use a category or the current selection, not both');
        if (action.category && !/^IFC[A-Z0-9_]{1,90}$/.test(action.category)) throw new Error('Invalid IFC category');
        if (action.text_match && (typeof action.text_match!=='string'||action.text_match.length>100)) throw new Error('Invalid property filter');
        if (!['reset','undo','fit'].includes(action.tool) && !action.category && !action.selected) throw new Error('A category or selection is required');
        if (action.tool==='color'&&!/^#[0-9a-f]{6}$/i.test(action.color||'')) throw new Error('Use a valid colour');
      }
      if (actions.some(a=>a.tool==='undo') && actions.length!==1) throw new Error('Undo must be requested on its own');
      if (actions[0].tool==='undo') {
        if (!history.length) throw new Error('No chat view action to undo');
        await restore(history[history.length-1]); history.pop();
        return {ok:true,message:'Undid the last chat view action. Original IFC files were unchanged.'};
      }
      // Resolve all selectors before mutating any view state.
      const resolved=[];
      for (const action of actions) resolved.push(['reset','fit'].includes(action.tool)?null:await targets(action,list));
      const changes=actions.some(a=>['hide','show','isolate','color','reset','fit'].includes(a.tool));
      if (changes) snapshot=await capture(list);
      const receipts=[]; const sources=[];
      for (let i=0;i<actions.length;i++) {
        const action=actions[i], found=resolved[i];
        if (action.tool==='fit') { await fit(); receipts.push('Fitted the model in the view.'); continue; }
        if (action.tool==='reset') {
          for (const {model} of list) { await model.resetVisible(); await model.resetColor(); if(model.object)model.object.visible=true; }
          colors.clear(); receipts.push('Restored all loaded elements and original model colours.'); continue;
        }
        const count=found.reduce((n,t)=>n+t.ids.length,0);
        if (action.tool==='properties') {
          if (count>25) throw new Error(`Matched ${count} elements. Select an element or narrow the property query to at most 25.`);
          for (const {row,ids} of found) if(ids.length) {
            const data=(await row.model.getItemsData(ids,DATA_CONFIG)).map(item=>readableIfc(item));
            if(!data.length)throw new Error('The model returned no property data for those elements');
            const json=JSON.stringify(data,null,2);
            if(json.length>200000)throw new Error('Property results are too large for chat; select fewer elements or inspect the model property panel');
            sources.push({model:key(row),ids,data});
            receipts.push(`IFC properties from ${row.name||key(row)} (element IDs: ${ids.join(', ')}):\n\n\x60\x60\x60json\n`+json+'\n\x60\x60\x60');
          }
          continue;
        }
        for (const {row,ids} of found) {
          if (action.tool==='isolate') {
            await row.model.setVisible(await row.model.getItemsIdsWithGeometry(),false);
            if (ids.length) {await row.model.setVisible(ids,true);if(row.model.object)row.model.object.visible=true;}
          } else if (ids.length && action.tool==='color') {
            await row.model.setColor(ids,makeColor(action.color));
            if(!colors.has(key(row))) colors.set(key(row),new Map());
            for(const id of ids) colors.get(key(row)).set(id,action.color);
          } else if(ids.length) {await row.model.setVisible(ids,action.tool==='show');if(action.tool==='show'&&row.model.object)row.model.object.visible=true;}
        }
        receipts.push(`${{hide:'Hidden',show:'Shown',isolate:'Isolated',color:'Coloured'}[action.tool]} ${count} matching element(s)${action.color?' '+action.color:''}.`);
      }
      await update();
      if(snapshot) {history.push(snapshot);if(history.length>5)history.shift();}
      return {ok:true,message:receipts.join('\n\n')+(changes?'\n\nView changes only; original IFC files were unchanged. Say “undo” or “reset view” to go back.':''),sources};
    } catch(error) {
      let rollback='';
      if(snapshot) {try {await restore(snapshot);rollback=' Previous view restored.';} catch {rollback=' View restoration failed; use reset view.';}}
      return {ok:false,message:'Action not completed: '+(error.message||String(error))+rollback};
    } finally {busy=false;}
  }
  return {context,execute};
}
