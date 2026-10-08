const API_METHODS={state:'GET',info:'GET',custom:'GET',todos:'GET',optimize:'POST','todo-save':'POST','todo-action':'POST','health-check':'POST','health-action':'POST','custom-edit':'POST','custom-delete':'POST',schedule:'POST',request:'POST',refresh:'POST',notification:'POST',job:'POST'};
function validateConnection(input){
 if(!input||typeof input.serverUrl!=='string')throw Error('Enter the Hermes server URL.');
 const raw=input.serverUrl.trim();let u;try{u=new URL(raw);}catch{throw Error('Use a complete URL such as https://hermes.example.com or http://127.0.0.1:47831.');}
 if(!['http:','https:'].includes(u.protocol)||u.username||u.password||u.search||u.hash)throw Error('Use an HTTP(S) server URL without credentials, query parameters, or fragments.');
 const loopback=['localhost','127.0.0.1','[::1]'].includes(u.hostname);
 if(u.protocol==='http:'&&!loopback&&input.allowInsecureHttp!==true)throw Error('Remote HTTP exposes your token and conversations. Use HTTPS, an SSH tunnel, or explicitly allow trusted-network HTTP.');
 const token=input.token;
 if(typeof token!=='string'||token.length<32||token.length>4096||/\s/.test(token))throw Error('Enter the server pairing token (at least 32 characters, no spaces).');
 u.pathname=u.pathname.replace(/\/+$/,'')+'/';
 return {serverUrl:u.href,allowInsecureHttp:input.allowInsecureHttp===true,token};
}
function candidateConnection(input,saved){
 const candidate=validateConnection({...input,token:input?.token||saved?.token});
 if(!input?.token&&candidate.serverUrl!==saved?.serverUrl)throw Error('Enter the pairing token when changing servers.');
 return candidate;
}
async function fetchBridge(connection,route,data,options={}){
 if(!Object.hasOwn(API_METHODS,route))throw Error('Unsupported bridge operation.');
 const method=API_METHODS[route];if(method==='GET'&&data!==undefined)throw Error('Read requests cannot include a body.');
 const body=method==='POST'?JSON.stringify(data??{}):undefined;
 if(body&&Buffer.byteLength(body)>65536)throw Error('Request is too large.');
 const endpoint=new URL('api/'+route,connection.serverUrl);
 let response;
 for(let attempt=0;attempt<(method==='GET'?2:1);attempt++){try{response=await fetch(endpoint,{method,headers:{Authorization:'Bearer '+connection.token,...(body?{'Content-Type':'application/json'}:{})},body,redirect:'error',signal:AbortSignal.timeout(options.timeout||(route==='refresh'?10000:70000))});break;}catch(err){if(method==='GET'&&attempt===0){await new Promise(r=>setTimeout(r,200));continue;}throw Error(err.name==='TimeoutError'?'The Hermes bridge timed out. Check the connection; a submitted action may already be queued.':'Cannot reach the Hermes bridge. Check the URL, network/tunnel, and HTTPS certificate. Redirects are not followed.');}}
 const max=16*1024*1024;let bytes=0;const chunks=[];
 for await(const chunk of response.body){bytes+=chunk.byteLength;if(bytes>max)throw Error('Bridge response is too large.');chunks.push(Buffer.from(chunk));}
 let result;try{result=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw Error('This address did not return the Nudge bridge API. Hermes needs the companion bridge installed beside it.');}
 if(!response.ok||result.error)throw Error(response.status===401?'Pairing token rejected. Check the server token and reconnect.':String(result.error||'Bridge request failed.').slice(0,2000));
 return result;
}
async function testConnection(connection){
 const info=await fetchBridge(connection,'info',undefined,{timeout:10000});
 if(info.kind!=='hermes-nudge'||info.protocol_version!==1)throw Error('This server is not a compatible Hermes Nudge bridge.');
 const state=await fetchBridge(connection,'state',undefined,{timeout:15000});
 if(!state.status||!Array.isArray(state.notifications)||!Array.isArray(state.jobs))throw Error('The bridge returned an invalid state.');
 return {profile:info.profile||state.status.profile,hermesAvailable:!!state.status.hermes_available};
}
function validateExternalLink(value){if(typeof value!=='string'||value.length>8192||/[\s\\]/.test(value))throw Error('Only public HTTPS links can be opened.');let u;try{u=new URL(value);}catch{throw Error('Invalid link.');}const h=u.hostname.toLowerCase().replace(/\.$/,'');if(u.protocol!=='https:'||u.username||u.password||!h||!h.includes('.')||h.endsWith('.localhost')||h.endsWith('.local')||h.endsWith('.internal')||h.endsWith('.test')||/^\d+(?:\.\d+){3}$/.test(h)||h.includes(':'))throw Error('Only public HTTPS links without credentials can be opened.');return u.href;}
module.exports={validateConnection,candidateConnection,fetchBridge,testConnection,API_METHODS,validateExternalLink};
