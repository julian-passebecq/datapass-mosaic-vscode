// Runtime transport and lifecycle regressions. No Python, SQL engine or provider executes here.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';

const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = await mkdtemp(path.join(tmpdir(), 'mosaic-readiness-'));
after(() => rm(temp, { recursive: true, force: true }));
const stubs = {
  vscode: `export const workspace={workspaceFolders:[]}; export const window={};`,
  child: `import {EventEmitter} from 'node:events';
    export function spawn(){ const child=new EventEmitter();child.stdout=new EventEmitter();child.stderr=new EventEmitter();
      child.kill=()=>{child.killed=true;};globalThis.__runtimeStart.children.push(child);return child; }`,
  endpoint: `export const findFreePort=async()=>12345; export const waitForDatapassHealth=async()=>({status:'ok'});`,
  manifest: `export const readProjectManifest=async()=>({manifest:{catalog:{seed:'none'}}});export const catalogSeed=()=> 'none';`
};
const outfile = path.join(temp, 'runtime.mjs');
await esbuild.build({
  stdin: { contents: `export {RuntimeManager} from './src/runtimeManager'; export {MosaicClient} from './src/labs/mosaic/client'; export {requestJson, RuntimeRequestTimeoutError} from './src/platform/runtimeClient';`, resolveDir: root, loader: 'ts' },
  bundle:true,platform:'node',format:'esm',target:'node20',outfile,logLevel:'silent',
  plugins:[{name:'runtime-boundaries',setup(build){
    build.onResolve({filter:/^(vscode|node:child_process|.*runtimeEndpoint|.*projectManifest)$/},args=>{
      const key=args.path==='vscode'?'vscode':args.path==='node:child_process'?'child':args.path.endsWith('runtimeEndpoint')?'endpoint':'manifest';
      if((key==='endpoint'||key==='manifest')&&!args.importer.endsWith('runtimeManager.ts'))return;
      return {path:key,namespace:'stub'};
    });
    build.onLoad({filter:/.*/,namespace:'stub'},args=>({contents:stubs[args.path],loader:'js'}));
  }}]
});
const { RuntimeManager, MosaicClient, requestJson, RuntimeRequestTimeoutError } = await import(pathToFileURL(outfile).href);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};

test('native SQL waits for a valid response beyond the old ten-second client cutoff, without retry',async()=>{
  let posts=0,timer;
  const response={status:'success',elapsed_ms:1,result:{columns:['answer'],rows:[[42]]}};
  const server=http.createServer((req,res)=>{posts++;req.resume();req.on('end',()=>{
    timer=setTimeout(()=>{res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(response));},11000);
  });});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const url=`http://127.0.0.1:${server.address().port}`;
  const runtime={runningUrl:()=>url,postJson:(url,body,timeout)=>requestJson(url,'POST',body,timeout),update:()=>{},refreshCatalog:async()=>{}};
  try { assert.deepEqual(await new MosaicClient(runtime).runSql('SELECT 42 AS answer'),response); assert.equal(posts,1); }
  finally {clearTimeout(timer);server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});

function startingRuntime(){
  const catalog=deferred(),requested=deferred(),events=[];
  globalThis.__runtimeStart={children:[]};
  const manager=Object.create(RuntimeManager.prototype);
  Object.assign(manager,{state:{status:'stopped'},extensionUri:{fsPath:temp},
    output:{appendLine(){},append(){},show(){}},changed:{fire:state=>events.push({...state})},
    runtimeRoot:()=>temp,managedPythonPath:()=>path.join(temp,'absent-python'),
    getJson:async url=>{
      if(url.endsWith('/api/capabilities'))return{runtime:{trusted_local_python:false}};
      assert.ok(url.endsWith('/api/local/catalog'));requested.resolve();return catalog.promise;
    }});
  return{manager,catalog,requested,events};
}

test('a SQL transport timeout reports uncertain execution and never retries',async()=>{
  let posts=0;
  const runtime={runningUrl:()=> 'http://127.0.0.1',postJson:async()=>{posts++;throw new RuntimeRequestTimeoutError();}};
  await assert.rejects(new MosaicClient(runtime).runSql('INSERT INTO orders VALUES (42)'),/may still have completed.*do not assume it was rolled back/);
  assert.equal(posts,1);
});

test('health alone does not enable execution before the initial catalog is ready',async()=>{
  const s=startingRuntime(),starting=s.manager.start('fake-python');
  await s.requested.promise;
  try{assert.equal(s.manager.state.status,'starting');assert.equal(s.manager.connection().runningUrl(),undefined);}
  finally{s.catalog.resolve({tables:[]});await starting;}
  assert.equal(s.manager.state.status,'running');assert.deepEqual(s.manager.state.catalog,{tables:[]});
});

test('Stop while initial catalog is pending cannot publish running later',async()=>{
  const s=startingRuntime(),starting=s.manager.start('fake-python');
  await s.requested.promise;s.manager.stop();const stoppedAt=s.events.length;
  s.catalog.resolve({tables:[]});await starting;
  assert.equal(s.manager.state.status,'stopped');assert.equal(s.manager.connection().runningUrl(),undefined);
  assert.equal(s.events.slice(stoppedAt).length,0,'the stopped launch cannot publish stale state');
});

test('a stopped launch failing initialization cannot clobber a successor child',async()=>{
  const s=startingRuntime(),starting=s.manager.start('fake-python');
  await s.requested.promise;s.manager.stop();
  const successor={kill(){throw new Error('must not kill successor');}};
  s.manager.child=successor;s.manager.state={status:'starting',url:'http://successor'};
  s.catalog.reject(new Error('old initialization failed'));await starting;
  assert.equal(s.manager.child,successor);assert.deepEqual(s.manager.state,{status:'starting',url:'http://successor'});
});
