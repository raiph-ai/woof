const test=require('node:test'),assert=require('node:assert/strict'),http=require('node:http');
const {validateConnection,candidateConnection,fetchBridge,testConnection}=require('./client-core.cjs');
const TOKEN='temporary-test-token-never-used-in-production';
test('connection URL, token, protocol and insecure opt-in validation',()=>{
 for(const serverUrl of ['file:///etc/passwd','https://user:pass@example.com','https://example.com?token=x','https://example.com#x'])assert.throws(()=>validateConnection({serverUrl,token:TOKEN}));
 assert.throws(()=>validateConnection({serverUrl:'http://example.com',token:TOKEN}));assert.throws(()=>validateConnection({serverUrl:'https://example.com',token:'short'}));
 assert.equal(validateConnection({serverUrl:'https://example.com/nudge',token:TOKEN}).serverUrl,'https://example.com/nudge/');
 assert(validateConnection({serverUrl:'http://127.0.0.1:47831',token:TOKEN}));assert(validateConnection({serverUrl:'http://example.com',token:TOKEN,allowInsecureHttp:true}));
});
test('saved credential is never reused when changing servers',()=>{const saved=validateConnection({serverUrl:'https://one.example',token:TOKEN});assert(candidateConnection({serverUrl:'https://one.example',token:''},saved));assert.throws(()=>candidateConnection({serverUrl:'https://other.example',token:''},saved));});
test('authenticated API, compatible handshake, redirect refusal and route limits',async()=>{
 let sawToken=false,posts=0;
 const server=http.createServer((req,res)=>{sawToken=req.headers.authorization==='Bearer '+TOKEN;if(req.url==='/api/info')res.end(JSON.stringify({kind:'hermes-nudge',protocol_version:1,profile:'test'}));else if(req.url==='/api/state')res.end(JSON.stringify({notifications:[],jobs:[],status:{profile:'test',hermes_available:true}}));else if(req.url==='/api/request'){posts++;res.writeHead(302,{Location:'/api/state'});res.end();}else{res.writeHead(401);res.end(JSON.stringify({error:'auth'}));}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));try{const conn=validateConnection({serverUrl:`http://127.0.0.1:${server.address().port}`,token:TOKEN});assert.deepEqual(await testConnection(conn),{profile:'test',hermesAvailable:true});assert(sawToken);await assert.rejects(fetchBridge(conn,'request',{prompt:'safe fixture'}));assert.equal(posts,1);await assert.rejects(fetchBridge(conn,'../secret'));await assert.rejects(fetchBridge(conn,'state',{}));await assert.rejects(fetchBridge(conn,'request',{prompt:'x'.repeat(70000)}));await assert.rejects(fetchBridge(conn,'job',{id:'bad'}),/rejected/);}finally{await new Promise(r=>server.close(r));}
});
