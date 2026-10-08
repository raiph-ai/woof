// Authenticated bridge owns the schedules; this UI never writes Hermes files.
const customDialog=document.getElementById('custom-manager');
const customEl=id=>document.getElementById(id);
let customEntries=[],customBusy=false,customReturnSettings=false;
function customStatus(text,error=false){const el=customEl('custom-status');el.textContent=text;el.className=error?'error':'hint';}
function customNode(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function customDate(value){return value?new Date(value).toLocaleString():'—';}
function customButtonsDisabled(){for(const b of customDialog.querySelectorAll('button:not(#custom-close)'))b.disabled=customBusy;}
function renderCustom(){
 const list=customEl('custom-list');list.replaceChildren();
 if(!customEntries.length)list.append(customNode('p','No custom notifications saved. Use “Schedule a nudge” to create one.','empty'));
 for(const entry of customEntries){
  const card=customNode('article',undefined,'custom-entry');card.dataset.jobId=entry.id;
  card.append(customNode('h3',entry.title));
  card.append(customNode('p',`${entry.exists===false?'No longer scheduled':entry.enabled?'Active':'Paused'} · ${entry.schedule||'Schedule unavailable'}`,'custom-summary'));
  card.append(customNode('p',`Last run: ${customDate(entry.last_run_at)}${entry.last_status?' · '+entry.last_status:''}\nNext run: ${customDate(entry.next_run_at)}`,'custom-runs'));
  const detail=customNode('details');detail.append(customNode('summary','Task instructions'),customNode('p',entry.prompt||'No instructions available.','custom-prompt'));card.append(detail);
  const actions=customNode('div',undefined,'custom-actions');
  if(entry.exists!==false){for(const [action,label] of [['edit','Edit'],[entry.enabled?'pause':'resume',entry.enabled?'Pause':'Resume']]){const b=customNode('button',label);b.type='button';b.dataset.action=action;b.addEventListener('click',()=>action==='edit'?editCustom(entry):changeCustom(entry,action));actions.append(b);}}
  const remove=customNode('button','Delete');remove.type='button';remove.dataset.action='delete';remove.addEventListener('click',()=>changeCustom(entry,'delete'));actions.append(remove);card.append(actions);list.append(card);
 }
 customButtonsDisabled();
}
async function loadCustom(){
 if(!window.nudgeConnected)throw Error('Connect to your Hermes bridge first.');
 const result=await api('custom');if(!Array.isArray(result.notifications))throw Error('Update the Woof bridge to use custom notification management.');customEntries=result.notifications;renderCustom();
}
async function openCustom(){
 customReturnSettings=customEl('settings').open;if(customReturnSettings)customEl('settings').close();
 customEl('custom-edit-form').hidden=true;customEl('custom-list').hidden=false;customEl('custom-reload').hidden=false;customStatus('Loading saved notifications…');customDialog.showModal();
 try{await loadCustom();customStatus('Schedules are saved on your Hermes server.');}catch(e){customEl('custom-list').replaceChildren();customStatus(e.message,true);}
}
function editCustom(entry){
 if(customBusy)return;
 customEl('custom-id').value=entry.id;customEl('custom-title').value=entry.title.replace(/^\[heartbeat-style\]\s*/,'');customEl('custom-prompt').value=(entry.prompt||'').replace(/^(?:Heartbeat-style interval check \(implemented as Hermes cron\):\n)+/,'');customEl('custom-mode').value=entry.mode||'cron';customEl('custom-schedule').value=entry.schedule||'';
 customEl('custom-edit-form').hidden=false;customEl('custom-list').hidden=true;customEl('custom-reload').hidden=true;customStatus('Changes affect future runs. Active/paused state is preserved.');customEl('custom-title').focus();
}
function cancelCustomEdit(){if(customBusy)return;customEl('custom-edit-form').hidden=true;customEl('custom-list').hidden=false;customEl('custom-reload').hidden=false;customStatus('Schedules are saved on your Hermes server.');}
async function waitCustomAction(request){
 if(!request?.id)throw Error('Bridge did not acknowledge the action.');
 const deadline=Date.now()+60000;
 while(Date.now()<deadline){const state=await api('state'),job=state.requests?.find(r=>r.id===request.id);if(job?.status==='completed')return;if(job?.status==='error')throw Error(job.body||'The action failed.');await new Promise(r=>setTimeout(r,750));}
 throw Error('Action is still pending. Refresh the list before trying again.');
}
async function changeCustom(entry,action){
 if(customBusy)return;
 if(action==='delete'&&!confirm(`Delete “${entry.title}”? This stops future runs. Existing notification results stay in your inbox.`))return;
 customBusy=true;customButtonsDisabled();customStatus(action==='delete'?'Deleting saved notification…':'Updating schedule state…');
 try{if(action==='delete')await api('custom-delete',{id:entry.id});else await waitCustomAction(await api('job',{id:entry.id,action}));await loadCustom();const saved=customEntries.find(i=>i.id===entry.id);if(action==='delete'&&saved)throw Error('Deletion was not confirmed. Refresh and check the schedule.');if(action!=='delete'&&(!saved||saved.enabled!==(action==='resume')))throw Error('Schedule state was not confirmed. Refresh and check the schedule.');customStatus(action==='delete'?'Deleted. Previous results are preserved.':action==='pause'?'Paused. Future runs are stopped until resumed.':'Resumed.');rendering='';await load();}catch(e){customStatus(e.message,true);}finally{customBusy=false;customButtonsDisabled();}
}
customEl('custom-edit-form').addEventListener('submit',async event=>{
 event.preventDefault();if(customBusy)return;
 const data={id:customEl('custom-id').value,title:customEl('custom-title').value.trim(),prompt:customEl('custom-prompt').value.trim(),schedule:customEl('custom-schedule').value.trim(),mode:customEl('custom-mode').value};
 customBusy=true;customButtonsDisabled();customStatus('Saving changes…');
 try{await api('custom-edit',data);await loadCustom();customEl('custom-edit-form').hidden=true;customEl('custom-list').hidden=false;customEl('custom-reload').hidden=false;customStatus('Changes saved and verified on your Hermes server.');rendering='';await load();}catch(e){customStatus(e.message,true);}finally{customBusy=false;customButtonsDisabled();}
});
customEl('manage-custom').addEventListener('click',openCustom);
customEl('custom-cancel').addEventListener('click',cancelCustomEdit);
customEl('custom-reload').addEventListener('click',async()=>{if(customBusy)return;customStatus('Refreshing…');try{await loadCustom();customStatus('List refreshed.');}catch(e){customStatus(e.message,true);}});
customEl('custom-close').addEventListener('click',()=>customDialog.close());
customDialog.addEventListener('close',()=>{if(customReturnSettings){customReturnSettings=false;showConnectionSettings();}});
