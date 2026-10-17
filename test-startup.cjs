const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {createStartupSettings}=require('./startup.cjs');
function fixture(overrides={}){
 let enabled=false;const writes=[];
 const app={isPackaged:true,getLoginItemSettings:()=>({openAtLogin:enabled}),setLoginItemSettings:options=>{writes.push(options);enabled=options.openAtLogin;}};
 const startup=createStartupSettings({app,platform:'darwin',execPath:'/Applications/Woof.app/Contents/MacOS/Woof',...overrides});
 return {startup,app,writes,setEnabled:value=>{enabled=value;}};
}
test('login preference is OS-owned, explicitly targets installed executable, and verifies writes',()=>{
 const {startup,writes,setEnabled}=fixture();assert.equal(startup.get().enabled,false);
 assert.equal(startup.set(true).enabled,true);assert.deepEqual(writes,[{openAtLogin:true,path:'/Applications/Woof.app/Contents/MacOS/Woof'}]);
 setEnabled(false);assert.equal(startup.get().enabled,false);assert.equal(startup.set(false).enabled,false);
});
test('strict booleans only; unsupported, development and temporary apps never mutate OS settings',()=>{
 for(const value of [undefined,null,0,1,'true',{},[]])assert.throws(()=>fixture().startup.set(value),/boolean/);
 for(const overrides of [{platform:'linux'},{app:{isPackaged:false}},{execPath:'/private/var/folders/x/AppTranslocation/id/d/Woof.app/Contents/MacOS/Woof'},{execPath:'/Volumes/Woof/Woof.app/Contents/MacOS/Woof'},{execPath:'Woof'}]){
  const {startup,writes}=fixture(overrides);assert.equal(startup.get().supported,false);assert.ok(startup.get().reason);assert.throws(()=>startup.set(true));assert.deepEqual(writes,[]);
 }
});
test('OS failures and unconfirmed writes are not reported as success',()=>{
 const {startup,app}=fixture();app.setLoginItemSettings=()=>{throw Error('Permission denied');};assert.throws(()=>startup.set(true),/Permission denied/);
 app.setLoginItemSettings=()=>{};assert.throws(()=>startup.set(true),/not confirmed/);
 app.getLoginItemSettings=()=>{throw Error('Login database unavailable');};assert.throws(()=>startup.get(),/Login database unavailable/);
});
test('settings UI reads OS state, handles errors, and never saves connection preferences',async()=>{
 const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{checked:false,disabled:false,handlers:{},addEventListener(name,fn){this.handlers[name]=fn;}});return nodes.get(id);};
 let enabled=true,writes=0;
 const nudge={onSettings(){},getStartup:async()=>({supported:true,enabled}),setStartup:async value=>{writes++;enabled=value;return {supported:true,enabled};}};
 const context={document:{getElementById:node},window:{nudge}};
 vm.runInNewContext(fs.readFileSync(require.resolve('./web/settings.js'),'utf8'),context);
 await context.loadStartupSettings();const checkbox=node('launch-at-login');assert.equal(checkbox.checked,true);assert.equal(checkbox.disabled,false);
 checkbox.checked=false;await checkbox.handlers.change();assert.equal(writes,1);assert.equal(checkbox.checked,false);assert.match(node('startup-status').textContent,/will not launch/);
 nudge.setStartup=async()=>({error:'Permission denied'});checkbox.checked=true;await checkbox.handlers.change();assert.equal(checkbox.checked,false);assert.equal(node('startup-status').textContent,'Permission denied');
 nudge.getStartup=async()=>({supported:false,enabled:false,reason:'Disabled in development'});await context.loadStartupSettings();assert.equal(checkbox.disabled,true);assert.match(node('startup-status').textContent,/development/);
 nudge.getStartup=async()=>({error:'OS unavailable'});await context.loadStartupSettings();assert.equal(checkbox.disabled,true);assert.equal(node('startup-status').textContent,'OS unavailable');
 context.window.nudge=undefined;await context.loadStartupSettings();assert.equal(checkbox.disabled,true);assert.match(node('startup-status').textContent,/installed macOS/);
 const html=fs.readFileSync(require.resolve('./web/index.html'),'utf8');assert.match(html,/id="launch-at-login"[^>]*disabled/);assert.match(html,/Launch Woof at login/);
});
test('startup IPC uses the existing panel-main-frame trust boundary and preload exposes only narrow methods',async()=>{
 const handlers={},startup=fixture().startup;
 const app={setName(){},getPath:()=>'/unused',setPath(){},requestSingleInstanceLock:()=>false,quit(){},on(){}};
 const electron={app,ipcMain:{handle:(name,fn)=>{handlers[name]=fn;},on(){}}};
 const context={require:name=>name==='electron'?electron:name==='./startup.cjs'?{createStartupSettings:()=>startup}:require(name.startsWith('./')?require.resolve(name):name),process:{env:{},platform:'darwin',execPath:'/Applications/Woof.app/Contents/MacOS/Woof'},console};
 vm.runInNewContext(fs.readFileSync(require.resolve('./main.cjs'),'utf8')+'\nthis.setTestPanel=value=>{panel=value;};',context);
 const mainFrame={},webContents={mainFrame};context.setTestPanel({webContents});
 for(const event of [{sender:{},senderFrame:mainFrame},{sender:webContents,senderFrame:{}}]){
  assert.equal((await handlers['startup-set'](event,true)).error,'Untrusted caller');assert.equal((await handlers['startup-get'](event)).error,'Untrusted caller');
 }
 const trusted={sender:webContents,senderFrame:mainFrame};assert.equal((await handlers['startup-set'](trusted,'true')).error.includes('boolean'),true);
 assert.equal((await handlers['startup-set'](trusted,true)).enabled,true);assert.equal((await handlers['startup-get'](trusted)).enabled,true);
 let exposed;const calls=[];vm.runInNewContext(fs.readFileSync(require.resolve('./preload.cjs'),'utf8'),{require:()=>({contextBridge:{exposeInMainWorld:(_name,value)=>{exposed=value;}},ipcRenderer:{invoke:(...args)=>calls.push(args)}})});
 exposed.getStartup();exposed.setStartup(false);assert.deepEqual(calls,[['startup-get'],['startup-set',false]]);
});
