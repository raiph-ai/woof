const {app,BrowserWindow,ipcMain,screen,Menu,safeStorage,clipboard,shell}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const {clampPoint,panelPosition}=require('./shell-utils.cjs');
const {validateConnection,candidateConnection,fetchBridge,testConnection,API_METHODS,validateExternalLink}=require('./client-core.cjs');
const {filterNotifications,notificationKind}=require('./web/notification-rules.js');
app.setName('Hermes Nudge');
const legacyUserData=app.getPath('userData');app.setName('Woof');app.setPath('userData',legacyUserData);
// Isolate Chromium preferences as well as connection files when using an explicit data directory.
if(process.env.HERMES_NUDGE_DATA_DIR){fs.mkdirSync(process.env.HERMES_NUDGE_DATA_DIR,{recursive:true,mode:0o700});app.setPath('userData',path.resolve(process.env.HERMES_NUDGE_DATA_DIR));}
let mascot,panel,panelReady,releaseTimer,dragSaveTimer,badgeBusy=false,quitting=false,connection=null,configError='';
const MASCOT_WIDTH=64,MASCOT_HEIGHT=72;let notificationSettings,seenNotifications=new Set(),latestState=null,stateOwner=null,latestStateAt=0,stateFlight=null,stateExpiry,cachedOnOpen=false;
const launchTimestamp=new Date().toISOString();
const userDir=()=>process.env.HERMES_NUDGE_DATA_DIR||app.getPath('userData');
const configPath=()=>path.join(userDir(),'connection.json');
function ensureDir(){fs.mkdirSync(userDir(),{recursive:true,mode:0o700});}
function loadNotificationSettings(){
 const file=path.join(userDir(),'notification-settings.json');
 try{const stored=JSON.parse(fs.readFileSync(file,'utf8'));if(!Number.isFinite(Date.parse(stored.since)))throw Error('Invalid cutoff');notificationSettings={since:stored.since,watchdog:stored.watchdog===true,heartbeat:stored.heartbeat===true,cron:stored.cron===true,sound:['woof','howl','none'].includes(stored.sound)?stored.sound:'woof',sourceEnabledAt:stored.sourceEnabledAt||{}};}
 catch{notificationSettings={since:launchTimestamp,watchdog:false,heartbeat:false,cron:false,sound:'woof'};saveNotificationSettings();}
}
function saveNotificationSettings(){const file=path.join(userDir(),'notification-settings.json');fs.writeFileSync(file+'.new',JSON.stringify(notificationSettings),{mode:0o600});fs.renameSync(file+'.new',file);}
function loadSeenNotifications(){try{const items=JSON.parse(fs.readFileSync(path.join(userDir(),'notification-seen.json'),'utf8'));seenNotifications=new Set(items.filter(v=>typeof v==='string').slice(-2000));}catch{seenNotifications=new Set();}}
function observeNotifications(items){
 const prefix=connection?.serverUrl||'';let newUnread=0,changed=false;
 for(const item of items){const key=prefix+'|'+item.id;if(!seenNotifications.has(key)){seenNotifications.add(key);changed=true;if(!item.read&&(!notificationSettings.sourceEnabledAt?.[notificationKind(item)]||Date.parse(item.created_at)>=notificationSettings.sourceEnabledAt[notificationKind(item)]))newUnread++;}}
 if(changed){while(seenNotifications.size>2000)seenNotifications.delete(seenNotifications.values().next().value);const file=path.join(userDir(),'notification-seen.json');fs.writeFileSync(file+'.new',JSON.stringify([...seenNotifications]),{mode:0o600});fs.renameSync(file+'.new',file);}
 mascot?.webContents.send('badge-update',Math.min(99,items.filter(n=>!n.read).length));
 if(newUnread)mascot?.webContents.send('notification-arrived',{sound:notificationSettings.sound,count:newUnread});
}
function loadConnection(){
 if(!fs.existsSync(configPath()))return;
 try{const stored=JSON.parse(fs.readFileSync(configPath(),'utf8'));if(!safeStorage.isEncryptionAvailable())throw Error('OS credential storage is unavailable. Unlock your login keychain.');connection=validateConnection({...stored,token:safeStorage.decryptString(Buffer.from(stored.encryptedToken,'base64'))});}
 catch{configError='Saved connection could not be unlocked. Re-enter the server address and pairing token.';connection=null;}
}
function publicConfig(){return {configured:!!connection,serverUrl:connection?.serverUrl||'',allowInsecureHttp:!!connection?.allowInsecureHttp,hasSavedToken:!!connection,error:configError,notifications:notificationSettings};}
function trusted(e){return e.sender===panel?.webContents&&e.senderFrame===panel.webContents.mainFrame;}
function wireInvoke(channel,handler){ipcMain.handle(channel,async(e,...args)=>{if(!trusted(e))return {error:'Untrusted caller'};try{return await handler(...args);}catch(err){return {error:String(err.message||'Operation failed')}};});}
wireInvoke('connection-get',()=>publicConfig());
wireInvoke('open-link',async value=>{const url=validateExternalLink(value);if(connection&&new URL(url).hostname===new URL(connection.serverUrl).hostname)throw Error('Bridge-local links cannot be opened.');await shell.openExternal(url);return {ok:true};});
wireInvoke('notifications-set',input=>{for(const key of ['watchdog','heartbeat','cron'])if(typeof input?.[key]!=='boolean')throw Error('Invalid notification preference.');if(!['woof','howl','none'].includes(input.sound))throw Error('Invalid notification sound.');const sourceEnabledAt={...notificationSettings.sourceEnabledAt};for(const key of ['watchdog','heartbeat','cron'])if(input[key]&&!notificationSettings[key])sourceEnabledAt[key]=Date.now();notificationSettings={...notificationSettings,sourceEnabledAt,watchdog:input.watchdog,heartbeat:input.heartbeat,cron:input.cron,sound:input.sound};if(input.sound==='none')mascot?.webContents.send('sound-preview',{sound:'none'});saveNotificationSettings();refreshBackgroundBadge();return notificationSettings;});
wireInvoke('sound-preview',sound=>{if(!['woof','howl','none'].includes(sound))throw Error('Invalid notification sound.');mascot?.webContents.send('sound-preview',{sound});return {ok:true};});
wireInvoke('token-copy',async value=>{
 if(typeof value!=='string'||!value||value.length>4096||/\s/.test(value))throw Error('Enter a token first; tokens must not contain spaces.');
 await clipboard.writeText(value);return {ok:true};
});
wireInvoke('token-paste',async()=>{
 const value=(await clipboard.readText()).trim();
 if(!value||value.length>4096||/\s/.test(value))throw Error('Clipboard does not contain a valid token string.');
 return {value};
});
wireInvoke('connection-save',async input=>{
 const candidate=candidateConnection(input,connection);
 const status=await testConnection(candidate);
 if(input.remember!==true){connection=candidate;clearState();configError='';if(fs.existsSync(configPath()))fs.unlinkSync(configPath());return {...publicConfig(),...status,sessionOnly:true};}
 if(!safeStorage.isEncryptionAvailable())throw Error('OS credential encryption is unavailable. No token was saved.');
 ensureDir();const stored={serverUrl:candidate.serverUrl,allowInsecureHttp:candidate.allowInsecureHttp,encryptedToken:safeStorage.encryptString(candidate.token).toString('base64')};
 const temp=configPath()+'.new';fs.writeFileSync(temp,JSON.stringify(stored),{mode:0o600});fs.renameSync(temp,configPath());connection=candidate;clearState();configError='';return {...publicConfig(),...status};
});
wireInvoke('connection-test',async input=>testConnection(candidateConnection(input,connection)));
wireInvoke('connection-forget',()=>{if(fs.existsSync(configPath()))fs.unlinkSync(configPath());connection=null;clearState();configError='';return publicConfig();});
// ponytail: release state when the existing reopen TTL ends, without copying or truncating payloads.
function clearState(){clearTimeout(stateExpiry);latestState=null;stateOwner=null;}
async function fetchState(){const owner=connection;if(stateFlight?.owner===owner)return stateFlight.promise;const promise=fetchBridge(owner,'state',undefined,{timeout:10000}).then(result=>{if(connection!==owner)throw Error('Connection changed.');clearState();latestState=result;stateOwner=owner;latestStateAt=Date.now();stateExpiry=setTimeout(clearState,70000);stateExpiry.unref();observeNotifications(filterNotifications(result.notifications,notificationSettings));return result;}).finally(()=>{if(stateFlight?.promise===promise)stateFlight=null;});stateFlight={owner,promise};return promise;}
wireInvoke('bridge-api',async(route,data)=>{if(!connection)throw Error('Connect to your Hermes server in Settings.');if(route==='state'){let result;if(cachedOnOpen&&stateOwner===connection&&Date.now()-latestStateAt<70000)result=latestState;cachedOnOpen=false;result=result||await fetchState();return {...result,notifications:filterNotifications(result.notifications,notificationSettings)};}const owner=connection;const result=await fetchBridge(owner,route,data);if(connection!==owner)throw Error('Connection changed. This result was discarded; a submitted mutation may already have been applied on the previous server. Check there before retrying.');if(API_METHODS[route]==='POST'||Array.isArray(API_METHODS[route])&&data!==undefined){clearState();}return result;});
if(!app.requestSingleInstanceLock())app.quit();else{
 app.on('second-instance',()=>{mascot?.show();if(panel)showPanel();});
 app.whenReady().then(async()=>{
  app.dock?.hide();ensureDir();loadNotificationSettings();loadSeenNotifications();loadConnection();
  const area=screen.getPrimaryDisplay().workArea;let saved={x:area.x+area.width-112,y:area.y+area.height-132};
  try{const pos=JSON.parse(fs.readFileSync(path.join(userDir(),'position.json'),'utf8'));if(Number.isFinite(pos.x)&&Number.isFinite(pos.y))saved=pos;}catch{}
  const display=screen.getDisplayNearestPoint({x:Math.round(saved.x),y:Math.round(saved.y)});
  const options={frame:false,show:false,resizable:false,alwaysOnTop:true,skipTaskbar:true,webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,backgroundThrottling:true,autoplayPolicy:'no-user-gesture-required'}};
  mascot=new BrowserWindow({...options,width:MASCOT_WIDTH,height:MASCOT_HEIGHT,transparent:true,hasShadow:false,...clampPoint(saved.x,saved.y,display.workArea,MASCOT_WIDTH,MASCOT_HEIGHT)});
  secureWindow(mascot);
  await mascot.loadFile(path.join(__dirname,'web','mascot.html'));
  mascot.showInactive();
  Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'Woof',submenu:[{label:'Open panels',click:showPanel},{label:'Connection settings',click:showSettings},{label:'Hide panels',click:hidePanel},{type:'separator'},{label:'Quit Woof',click:()=>app.quit(),accelerator:'Cmd+Q'}]},{label:'Edit',submenu:[{role:'undo'},{role:'redo'},{type:'separator'},{role:'cut'},{role:'copy'},{role:'paste'},{role:'selectAll'}]}]));
  if(!connection)await showPanel();
  setInterval(refreshBackgroundBadge,60000).unref();if(connection)refreshBackgroundBadge();
 }).catch(()=>app.quit());
}
function positionPanel(){if(!panel||!mascot)return;const m=mascot.getBounds(),area=screen.getDisplayMatching(m).workArea,h=Math.min(750,area.height-32);panel.setBounds({...panelPosition(m,area,440,h),width:440,height:h});}
function secureWindow(w){w.setVisibleOnAllWorkspaces(true,{visibleOnFullScreen:true});w.webContents.setWindowOpenHandler(()=>({action:'deny'}));w.webContents.on('will-navigate',e=>e.preventDefault());w.webContents.session.setPermissionRequestHandler((_wc,_permission,cb)=>cb(false));}
function preparePanel(){
 if(!panel){cachedOnOpen=true;
  const area=screen.getPrimaryDisplay().workArea;
  panel=new BrowserWindow({frame:false,show:false,resizable:false,alwaysOnTop:true,skipTaskbar:true,width:440,height:Math.min(750,area.height-32),transparent:process.platform==='darwin',backgroundColor:process.platform==='darwin'?'#00000000':'#182026',visualEffectState:'active',hasShadow:true,roundedCorners:true,webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,backgroundThrottling:true}});
  const current=panel;if(process.platform==='darwin')current.setBackgroundColor('rgba(0,0,0,0)');secureWindow(current);
  current.on('close',e=>{if(!quitting){e.preventDefault();hidePanel();}});
  current.on('closed',()=>{if(panel===current){panel=null;panelReady=null;}});
  current.webContents.once('did-finish-load',()=>current.webContents.send('panel-visibility',current.isVisible()));
  panelReady=current.loadFile(path.join(__dirname,'web','index.html'));
 }
 return panelReady;
}
function schedulePanelRelease(){clearTimeout(releaseTimer);if(panel&&!panel.isVisible()){releaseTimer=setTimeout(()=>{if(panel&&!panel.isVisible())panel.destroy();},30000);releaseTimer.unref();}}
async function showPanel(){clearTimeout(releaseTimer);cachedOnOpen=true;await preparePanel();clearTimeout(releaseTimer);if(!panel||panel.isDestroyed())return;positionPanel();panel.show();panel.focus();panel.webContents.send('panel-visibility',true);
}
function hidePanel(){
 if(!panel)return;panel.webContents.send('panel-visibility',false);panel.hide();clearTimeout(releaseTimer);
 // Release hidden renderers; Hermes keeps tasks running.
 schedulePanelRelease();
}
async function showSettings(){await showPanel();panel?.webContents.send('show-settings');}
async function refreshBackgroundBadge(){
 if(!connection||panel?.isVisible()||badgeBusy)return;badgeBusy=true;
 try{await fetchState();}catch{}finally{badgeBusy=false;}
}
ipcMain.on('toggle-panel',e=>{if(e.sender===mascot?.webContents)panel?.isVisible()?hidePanel():showPanel();});
ipcMain.on('hide-panel',e=>{if(trusted(e))hidePanel();});
ipcMain.on('mascot-menu',e=>{if(e.sender===mascot?.webContents)Menu.buildFromTemplate([{label:'Open panels',click:showPanel},{label:'Connection settings',click:showSettings},{type:'separator'},{label:'Quit',click:()=>app.quit()}]).popup({window:mascot});});
ipcMain.on('drag-mascot',(e,p)=>{if(e.sender!==mascot?.webContents||!Number.isFinite(p?.x)||!Number.isFinite(p?.y))return;const area=screen.getDisplayNearestPoint({x:Math.round(p.x),y:Math.round(p.y)}).workArea;const pos=clampPoint(p.x,p.y,area,MASCOT_WIDTH,MASCOT_HEIGHT);mascot.setPosition(pos.x,pos.y);if(panel?.isVisible())positionPanel();clearTimeout(dragSaveTimer);dragSaveTimer=setTimeout(()=>fs.writeFileSync(path.join(userDir(),'position.json'),JSON.stringify(pos),{mode:0o600}),200);});
ipcMain.on('badge',(e,n)=>{if(trusted(e))mascot.webContents.send('badge-update',Math.min(99,Math.max(0,Number(n)||0)));});
app.on('before-quit',()=>{quitting=true;});app.on('window-all-closed',()=>app.quit());
