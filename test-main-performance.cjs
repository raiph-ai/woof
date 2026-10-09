// Main-process cache checks; no Electron launch, real bridge, or provider actions.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const benchmark=process.argv.includes('--benchmark');
const source=process.argv.find(a=>a.endsWith('.cjs')&&a!==__filename&&a!==process.argv[1])||path.join(__dirname,'main.cjs');
const handlers=new Map(),timers=new Set(),dataDir=fs.mkdtempSync(path.join(process.env.TMPDIR,'woof-main-test-'));let reply,calls=0,fail=false,pending;
const app={setName(){},getPath(){return dataDir;},setPath(){},requestSingleInstanceLock(){return false;},quit(){},on(){}};
const context=vm.createContext({console,process:{env:{}},Buffer,URL,Date,setTimeout(fn,ms){const t={fn,ms,unref(){}};timers.add(t);return t;},clearTimeout(t){timers.delete(t);},require(name){
 if(name==='electron')return {app,safeStorage:{isEncryptionAvailable:()=>true,encryptString:()=>Buffer.from('test-only-encryption-stub')},ipcMain:{handle:(n,h)=>handlers.set(n,h),on(){}}};
 if(name==='./client-core.cjs')return {...require('./client-core.cjs'),testConnection:async()=>({profile:'fixture'}),fetchBridge:async()=>{calls++;if(pending)await pending;if(fail)throw Error('fixture offline');const result=reply;reply=null;return result;}};
 return require(name.startsWith('./')?path.join(__dirname,name):name);
}});
vm.runInContext(fs.readFileSync(source,'utf8'),context);
vm.runInContext("connection={serverUrl:'https://fixture.example',token:'fixture'};panel={webContents:{mainFrame:{}}};notificationSettings={since:new Date(0).toISOString()};",context);
const event=vm.runInContext('({sender:panel.webContents,senderFrame:panel.webContents.mainFrame})',context);
const call=(route,data)=>handlers.get('bridge-api')(event,route,data);
const size=()=>vm.runInContext('latestState?Buffer.byteLength(JSON.stringify(latestState)):0',context);
const expire=()=>{for(const t of [...timers])if(t.ms===70000){timers.delete(t);t.fn();}};
(async()=>{
 if(benchmark){
  assert(global.gc,'Use node --expose-gc for the cache heap benchmark');global.gc();const start=process.memoryUsage().heapUsed;
  reply=JSON.parse(JSON.stringify({notifications:[],jobs:[],body:'x'.repeat(12*1024*1024)}));await call('state');const before=size();await new Promise(setImmediate);global.gc();const retained=process.memoryUsage().heapUsed;
  expire();await new Promise(setImmediate);global.gc();const after=process.memoryUsage().heapUsed;
  console.log(JSON.stringify({source,fixture_body_bytes:12*1024*1024,cache_bytes_before_expiry:before,cache_bytes_after_expiry:size(),heap_start_bytes:start,heap_retained_bytes:retained,heap_after_expiry_bytes:after,heap_released_bytes:retained-after}));return;
 }
 const dir=fs.mkdtempSync(path.join(process.env.TMPDIR,'woof-trim-test-'));
 try{
  const bundle=path.join(dir,'dist/Woof-darwin-arm64/Woof.app/Contents'),resources=path.join(bundle,'Frameworks/Electron Framework.framework/Versions/A/Resources');
  const keep=['en.lproj/locale.pak','en_GB.lproj/locale.pak','Base.lproj/menu','icudtl.dat','../Libraries/libffmpeg.dylib'];
  const lock=path.join(bundle,'Resources/app/node_modules/.package-lock.json');
  for(const file of [...keep.map(f=>path.join(resources,f)),path.join(resources,'fr.lproj/locale.pak'),lock,path.join(bundle,'Resources/app/LICENSE')]){fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,'fixture');}
  fs.mkdirSync(path.join(dir,'scripts'));fs.copyFileSync(path.join(__dirname,'scripts/trim_client.py'),path.join(dir,'scripts/trim_client.py'));
  const run=()=>require('node:child_process').spawnSync('python3',[path.join(dir,'scripts/trim_client.py')],{encoding:'utf8'});
  assert.equal(run().status,0);assert(!fs.existsSync(lock));assert(!fs.existsSync(path.join(resources,'fr.lproj')));
  for(const f of keep)assert(fs.existsSync(path.join(resources,f)));assert(fs.existsSync(path.join(bundle,'Resources/app/LICENSE')));
  assert.equal(run().status,0,'Trim is idempotent without an npm lock');
  fs.mkdirSync(path.join(resources,'de.lproj'));fs.unlinkSync(path.join(resources,'icudtl.dat'));assert.notEqual(run().status,0);assert(fs.existsSync(path.join(resources,'de.lproj')),'Reject incomplete native layout before deleting anything');
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
 reply={notifications:[],jobs:[],status:{profile:'fixture'}};let unblock;pending=new Promise(r=>unblock=r);
 const a=call('state'),b=call('state');assert.equal(calls,1,'Concurrent state GETs coalesce');unblock();await Promise.all([a,b]);pending=null;
 assert(size()>0);assert.equal(timers.size,1,'One cache expiration timer');
 vm.runInContext('cachedOnOpen=true',context);const cached=await call('state');assert.equal(cached.status.profile,'fixture');assert.equal(calls,1,'Reopen uses a fresh cache');
 expire();assert.equal(size(),0,'Expired heavyweight state is released');assert.equal(vm.runInContext('stateOwner',context),null);
 fail=true;assert((await call('state')).error,'Expired state is not returned on failure');fail=false;
 reply={notifications:[],jobs:[]};await call('state');assert(size()>0);reply={ok:true};await call('notification',{id:'fixture'});assert.equal(size(),0);assert.equal(timers.size,0,'Mutation cancels expiration');
 for(const remember of [true,false]){reply={notifications:[],jobs:[]};await call('state');const saved=await handlers.get('connection-save')(event,{serverUrl:'https://replacement.example',token:'fixture-token-012345678901234567890123456789',remember});assert(saved.configured);assert.equal(size(),0);assert.equal(timers.size,0,'Reconnect releases the old cache');}
 reply={notifications:[],jobs:[]};await call('state');await handlers.get('connection-forget')(event);assert.equal(size(),0);assert.equal(timers.size,0,'Forget cancels expiration');
 vm.runInContext("connection={serverUrl:'https://other.example',token:'other'};cachedOnOpen=true",context);reply={notifications:[],jobs:[],status:{profile:'other'}};assert.equal((await call('state')).status.profile,'other');
 let release;pending=new Promise(r=>release=r);reply={notifications:[],jobs:[]};const old=call('state');vm.runInContext("connection={serverUrl:'https://third.example',token:'third'}",context);release();assert.match((await old).error,/Connection changed/);pending=null;
 console.log('Main cache: coalescing, fresh reopen, expiry, mutation/forget cleanup, ownership checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>fs.rmSync(dataDir,{recursive:true,force:true}));
