const path=require('node:path');
// Login items belong to this desktop, never to the configured (possibly remote) bridge.
function createStartupSettings({app,platform=process.platform,execPath=process.execPath}){
 function unavailable(){
  if(platform!=='darwin')return 'Launch at login is available only on macOS.';
  if(!app.isPackaged)return 'Launch at login is disabled in development. Install Woof.app first.';
  if(!path.isAbsolute(execPath)||!/^\/.+\.app\/Contents\/MacOS\/[^/]+$/.test(execPath)||execPath.includes('/AppTranslocation/')||execPath.startsWith('/Volumes/'))return 'Move Woof.app to Applications and reopen it before enabling launch at login.';
  return '';
 }
 function get(){
  const reason=unavailable();if(reason)return {supported:false,enabled:false,reason};
  const settings=app.getLoginItemSettings();
  if(typeof settings.openAtLogin!=='boolean')throw Error('macOS returned an invalid login item status.');
  return {supported:true,enabled:settings.openAtLogin,reason:''};
 }
 function set(enabled){
  if(typeof enabled!=='boolean')throw Error('Launch at login must be a boolean.');
  const reason=unavailable();if(reason)throw Error(reason);
  app.setLoginItemSettings({openAtLogin:enabled,path:execPath});
  const status=get();if(status.enabled!==enabled)throw Error('Launch at login change was not confirmed by macOS. Check System Settings > General > Login Items.');
  return status;
 }
 return {get,set};
}
module.exports={createStartupSettings};
