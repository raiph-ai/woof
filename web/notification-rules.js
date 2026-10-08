// Shared by the desktop API proxy and its badge polling; preferences never delete server data.
function notificationKind(item){
 if(item.custom===true||String(item.id||'').startsWith('created-'))return 'message';
 if(['watchdog','heartbeat','cron','message'].includes(item.category))return item.category;
 const source=String(item.source||'').toLowerCase(),title=String(item.title||''),firstLine=String(item.body||'').split('\n')[0].trim();
 if(/watchdog/.test(source)||(/^watchdog[\s:_-]/i.test(title))||(item.job_id&&/\bwatchdog\b/i.test(title))||/^\[watchdog(?:[: \]]|$)|^WATCHDOG_(?:OK|ALERT|ERROR|WARNING)\b/.test(firstLine))return 'watchdog';
 if(/heartbeat/.test(source)||/^\[heartbeat(?:-style)?\]/i.test(title)||(item.job_id&&/\bheartbeat\b/i.test(title))||/^HEARTBEAT_(?:OK|ALERT)\b/.test(firstLine))return 'heartbeat';
 if(item.job_id||source==='cron'||source==='scheduler')return 'cron';
 return 'message';
}
function notificationVisible(item,settings){const timestamp=Date.parse(item.created_at),cutoff=Date.parse(settings.since);if(!Number.isFinite(cutoff)||!Number.isFinite(timestamp)||timestamp<cutoff)return false;const kind=notificationKind(item);return kind==='message'||settings[kind]===true;}
function filterNotifications(items,settings){return (items||[]).filter(item=>notificationVisible(item,settings)).map(item=>({...item,category:notificationKind(item)}));}
if(typeof module!=='undefined')module.exports={notificationKind,notificationVisible,filterNotifications};
