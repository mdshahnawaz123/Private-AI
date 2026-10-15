const $=id=>document.getElementById(id);
let jobId=null,job=null,timer=null,loadedDigest=null,loadedPlan=null;
const urls=[];
async function api(path,options={}){
  const headers=new Headers(options.headers||{});
  const token=localStorage.getItem('expo_token');
  if(token)headers.set('Authorization','Bearer '+token);
  const response=await fetch('/api/blender'+path,{...options,headers});
  if(!response.ok){let body=await response.json().catch(()=>({detail:response.statusText}));throw Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));}
  return response;
}
function showError(error){$('message').textContent=error.message;}
async function json(path,body){return(await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();}
async function blobUrl(name){const blob=await(await api(`/jobs/${jobId}/files/${name}`)).blob();const url=URL.createObjectURL(blob);urls.push(url);return url;}
function clearUrls(){for(const url of urls)URL.revokeObjectURL(url);urls.length=0;}
async function refresh(){
  try{
    job=await(await api('/jobs/'+jobId)).json();
    $('state').textContent=job.state.replaceAll('_',' ');$('message').textContent=job.message;
    $('events').textContent=job.events.map(e=>e.state+': '+e.message).join('\n\n');
    $('approve').disabled=job.state!=='awaiting_approval';$('open').disabled=job.state!=='complete';
    const plan=job.plan||job.review?.plan;
    if(plan&&JSON.stringify(plan)!==loadedPlan){
      loadedPlan=JSON.stringify(plan);$('plan').value=JSON.stringify(plan,null,2);
      $('summary').textContent=plan.summary+'\n'+(plan.unknowns||[]).join('\n');
      $('geometry').replaceChildren();
      const table=document.createElement('table');
      for(const row of [['Element','Bounds (metres)','Source evidence'],...plan.footprints.map(p=>[p.kind+' '+p.id,p.bounds_m.join(', '),'Page '+p.page+': '+p.evidence])]){
        const tr=document.createElement('tr');for(const value of row){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);
      }$('geometry').append(table);
      $('pages').replaceChildren();
      for(let n=1;n<=4;n++){try{const image=document.createElement('img');image.src=await blobUrl('page-'+n+'.png');image.alt='Source drawing page '+n;$('pages').append(image);}catch{break;}}
    }
    if(job.review_digest!==loadedDigest){loadedDigest=job.review_digest;$('checked').checked=false;$('furniture').value=JSON.stringify(job.review?.furniture||[],null,2);}
    if(job.state==='complete'&&!$('render').dataset.loaded){
      $('render').src=await blobUrl('render.png');$('render').hidden=false;$('render').dataset.loaded='1';
      for(const name of ['model.blend','render.png','derived.dxf','review.json']){
        const a=document.createElement('a');a.href=await blobUrl(name);a.download=name;a.textContent=name;$('artifacts').append(a);
      }
    }
    clearTimeout(timer);
    if(['queued','reading','planning','furnishing','approved','building'].includes(job.state))timer=setTimeout(refresh,2500);
  }catch(error){showError(error);}
}
function selectJob(id){clearTimeout(timer);clearUrls();jobId=id;job=null;loadedPlan=null;loadedDigest=null;$('jobInput').value=id;$('render').hidden=true;delete $('render').dataset.loaded;$('artifacts').replaceChildren();history.replaceState(null,'','?job='+encodeURIComponent(id));return refresh();}
$('start').onclick=async()=>{try{
  if(!$('pdf').files[0])throw Error('Choose a PDF drawing.');
  if(!$('consent').checked)throw Error('Confirm OpenAI processing of this drawing.');
  $('start').disabled=true;
  const data=new FormData();data.append('project',$('project').value);data.append('cloud_consent','true');data.append('file',$('pdf').files[0]);
  const created=await(await api('/jobs',{method:'POST',body:data})).json();await selectJob(created.id);
}catch(error){showError(error);}finally{$('start').disabled=false;}};
$('load').onclick=()=>selectJob($('jobInput').value.trim());
$('revise').onclick=async()=>{try{if(!jobId)throw Error('Load a job first.');await json(`/jobs/${jobId}/revise`,{plan:JSON.parse($('plan').value),furniture:JSON.parse($('furniture').value)});await refresh();}catch(error){showError(error);}};
$('approve').onclick=async()=>{try{if(!$('checked').checked)throw Error('Review the source and check the confirmation first.');await json(`/jobs/${jobId}/approve`,{review_digest:job.review_digest,source_checked:true,open_blender:$('autoOpen').checked});await refresh();}catch(error){showError(error);}};
$('open').onclick=async()=>{try{await json(`/jobs/${jobId}/open`,{});}catch(error){showError(error);}};
(async()=>{try{const h=await(await api('/health')).json();$('health').textContent=`Blender: ${h.blender_available?'found':'not found'} · OpenAI key: ${h.api_key_configured?'configured':'missing'} · Model: ${h.model||'not configured'}`;}catch(error){$('health').textContent='Sign in to Expo Design AI first. '+error.message;}})();
const query=new URLSearchParams(location.search);if(query.get('project'))$('project').value=query.get('project');if(query.get('job'))selectJob(query.get('job'));
