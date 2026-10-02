// Exercise the actual TypeScript host against a controlled VS Code adapter and real temporary files.
// This does not replace the separate packaged-VSIX UI gate.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import * as model from '../media/learning/model.mjs';
const require = createRequire(import.meta.url);
const ts = require(process.env.TYPESCRIPT_MODULE || 'typescript');
const extensionRoot = fileURLToPath(new URL('..', import.meta.url));
const catalog = model.validateCatalog(JSON.parse(readFileSync(path.join(extensionRoot, 'content/learning/catalog.json'), 'utf8')));
const hostSource = readFileSync(path.join(extensionRoot, 'src/learning/learningWorkspace.ts'), 'utf8');
const compiled = ts.transpileModule(hostSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }, reportDiagnostics: true });
assert.equal(compiled.diagnostics?.length ?? 0, 0);

async function fixture() {
  const folder = await fs.mkdtemp(path.join(tmpdir(), 'mosaic-learning-host-'));
  const saved = new Map(), docs = new Map(), sent = [], calls = [];
  const uri = file => ({ scheme: 'file', fsPath: file, path: file, toString: () => `file://${file}` });
  class EventEmitter { listeners = []; event = listener => { this.listeners.push(listener); return { dispose() {} }; }; fire = value => { for (const fn of this.listeners) fn(value); }; dispose() {} }
  const event = () => ({ dispose() {} });
  const panels = [];
  let progress = { document: { practice: { exercises: {} } } };
  const snapshot = { status: 'running', trustedPython: false };
  const result = () => ({ id: 'run-1', status: 'success', language: 'sql', elapsed_ms: 2, result: { columns: ['n'], rows: [{ n: 1 }] } });
  const runtime = {
    snapshot: () => snapshot, onDidChange: event,
    labs: {
      mosaic: { runSql: async code => { calls.push(['sql', code]); return result(); }, runPython: async code => { calls.push(['python', code]); if (!snapshot.trustedPython) throw new Error('Trusted local Python is disabled'); return result(); }, explainQuery: async code => { calls.push(['explain', code]); return { plan: 'local plan', query: code, elapsed_ms: 3, truth: 'real' }; } },
      sparklab: { runSparkLab: async (...args) => { calls.push(['sparklab', ...args]); return { ...result(), engine: 'sparklab', simulation: { status: 'modeled', stages: [], plan: [], comparisons: [] } }; } }
    }
  };
  const api = {
    Uri: { file: uri, joinPath: (base, ...parts) => uri(path.join(base.fsPath, ...parts)) },
    EventEmitter, TreeItem: class { constructor(label) { this.label = label; } }, ThemeIcon: class {},
    ViewColumn: { Active: -1, One: 1, Two: 2 }, TreeItemCollapsibleState: { Expanded: 2, None: 0 },
    Range: class { constructor(a,b,c,d) { this.start={line:a,character:b};this.end={line:c,character:d}; } },
    Selection: class { constructor(a,b) { this.start=a;this.end=b; } }, RelativePattern: class {},
    commands: { executeCommand: async (...args) => calls.push(['command', ...args]) },
    workspace: { isTrusted: true, workspaceFolders: [{ uri: uri(folder) }], onDidChangeTextDocument: event,
      fs: { readFile: u => fs.readFile(u.fsPath), writeFile: (u, bytes) => fs.writeFile(u.fsPath, bytes) },
      createFileSystemWatcher: () => ({ onDidChange:event, onDidCreate:event, onDidDelete:event, dispose() {} }),
      openTextDocument: async u => {
        if (!docs.has(u.fsPath)) {
          const text = await fs.readFile(u.fsPath, 'utf8'); const doc = { uri:u, text, getText: range => range ? doc.text.slice(range.startOffset,range.endOffset) : doc.text };
          docs.set(u.fsPath, doc);
        }
        return docs.get(u.fsPath);
      }
    },
    window: { activeTextEditor: undefined, showErrorMessage: async text => calls.push(['error', text]), showWarningMessage: async text => calls.push(['warning', text]), showSaveDialog: async () => undefined,
      createWebviewPanel: () => { const panel={ webview:{ cspSource:'vscode-resource:', html:'', asWebviewUri:u=>u.toString(), onDidReceiveMessage:event, postMessage:async msg=>{ sent.push(structuredClone(msg));return true; } },onDidDispose:event,onDidChangeViewState:event,reveal() {},dispose() {} }; panels.push(panel);return panel; },
      showTextDocument: async doc => { const editor={ document:doc,selection:{isEmpty:true},revealRange() {} };api.window.activeTextEditor=editor;return editor; }
    }
  };
  const exercises = catalog.lessons.map(l => ({ key:`learning/${l.exercise.id}/${l.exercise.language}`,id:l.exercise.id,language:l.exercise.language,version:'1',title:l.title,prompt:'Public brief',sections:[],hints:['one'],dataContext:[] }));
  const exports = {};
  const scope = { exports, require: id => {
    if (id === 'vscode') return api;
    if (id === '../exerciseCatalog') return { loadExerciseCatalog:async()=>exercises };
    if (id === '../projectState') return { readProgress:async()=>progress };
    if (id.endsWith('/model.mjs')) return model;
    return require(id);
  }, TextDecoder, TextEncoder, structuredClone, console };
  vm.runInNewContext(compiled.outputText, scope, { filename: 'learningWorkspace.js' });
  const context = { extensionUri:uri(extensionRoot), workspaceState:{ get:key=>saved.get(key),update:async(key,value)=>saved.set(key,structuredClone(value)) } };
  const open = async (view,message) => {
    calls.push(['open',view,message]);
    if (message?.type === 'gradeExercise') {
      snapshot.practiceResult={ exerciseKey:message.exerciseKey,mode:message.mode,status:'passed',truth:'fixture grader',elapsed_ms:1,checks:[] };
      if(message.mode==='submit') progress.document.practice.exercises[message.exerciseKey]={ solved:{version:'1',at:'2026-10-02T12:00:00Z'} };
    }
  };
  const host = new exports.LearningWorkspace(context,runtime,open); await host.show();
  return { host,api,runtime,snapshot,saved,sent,calls,docs,folder,catalog,exercises,context,
    latest:()=>sent.filter(m=>m.type==='state').at(-1),
    close:async()=>{host.dispose();await fs.rm(folder,{recursive:true,force:true});} };
}

test('reading, layout and rail controls never run code or install a runtime', async () => {
  const f=await fixture();try{
    const lesson=catalog.lessons[0].id;
    await f.host.handle({type:'read',lesson});await f.host.handle({type:'mode',lesson,mode:'watch'});await f.host.handle({type:'rail',hidden:true});
    assert.equal(f.calls.length,0);assert.equal(f.latest().statuses[lesson],'read');assert.equal(f.latest().state.railHidden,true);
    assert.equal((await fs.readdir(f.folder)).length,0);
  }finally{await f.close();}
});
test('Try uses native files, preserves existing edits and runs the unsaved buffer', async () => {
  const f=await fixture();try{
    const lesson=catalog.lessons[0].id;
    await f.host.handle({type:'mode',lesson,mode:'try'});
    const file=path.join(f.folder,'notebooks','learning',lesson,'example.sql');
    assert.ok((await fs.readFile(file,'utf8')).includes('LEFT JOIN'));
    await fs.writeFile(file,'SELECT 7 AS n;');await f.host.handle({type:'openExample',lesson});
    assert.equal(await fs.readFile(file,'utf8'),'SELECT 7 AS n;');
    f.docs.get(file).text='SELECT 8 AS n; -- unsaved';await f.host.handle({type:'run',lesson});
    assert.equal(f.calls.find(c=>c[0]==='sql')[1],'SELECT 8 AS n; -- unsaved');
    assert.equal(f.latest().run.lesson,lesson);assert.equal(f.latest().run.evidence.result.rows[0].n,1);
  }finally{await f.close();}
});
test('Restricted Mode permits reading but rejects file creation and execution', async () => {
  const f=await fixture();try{
    f.api.workspace.isTrusted=false;await f.host.show();
    await assert.rejects(f.host.handle({type:'openExample',lesson:catalog.lessons[0].id}),/Restricted/);
    await assert.rejects(f.host.handle({type:'run',lesson:catalog.lessons[0].id}),/Restricted/);
    assert.equal(f.calls.length,0);
  }finally{await f.close();}
});
test('lesson files refuse symlinks and messages cannot supply arbitrary files or SQL', async () => {
  const f=await fixture();const outside=await fs.mkdtemp(path.join(tmpdir(),'mosaic-learning-outside-'));try{
    await fs.symlink(outside,path.join(f.folder,'notebooks'),process.platform==='win32'?'junction':'dir');
    await assert.rejects(f.host.handle({type:'openExample',lesson:catalog.lessons[0].id}),/symbolic/);
    await assert.rejects(f.host.handle({type:'run',lesson:catalog.lessons[0].id,code:'SELECT 1'}),/Unsupported/);
    assert.equal((await fs.readdir(outside)).length,0);
  }finally{await f.close();await fs.rm(outside,{recursive:true,force:true});}
});
test('grade actions use the existing Practice controller; only Submit supplies pass evidence', async () => {
  const f=await fixture();try{
    const lesson=catalog.lessons[0].id;
    await f.host.handle({type:'grade',lesson,mode:'run'});assert.equal(f.latest().statuses[lesson],'new');
    await f.host.handle({type:'grade',lesson,mode:'submit'});assert.equal(f.latest().statuses[lesson],'practiced');
    assert.equal(f.calls.filter(c=>c[0]==='open'&&c[1]==='practice').length,2);
    assert.equal(f.calls.filter(c=>c[0]==='sql').length,0);
  }finally{await f.close();}
});
test('changing topics never attaches another exercise grading result to the new lesson', async () => {
  const f=await fixture();try{
    await f.host.handle({type:'grade',lesson:catalog.lessons[0].id,mode:'submit'});
    await f.host.select(catalog.paths[0].id,catalog.paths[0].lessons[1]);
    assert.equal(f.latest().practiceResult,undefined);
    await assert.rejects(f.host.handle({type:'run',lesson:catalog.lessons[0].id}),/lesson changed/);
  }finally{await f.close();}
});
test('late run results retain their origin; pinned baseline stays immutable', async () => {
  const f=await fixture();try{
    const first=catalog.lessons[0].id;await f.host.handle({type:'openExample',lesson:first});
    let resolve;f.runtime.labs.mosaic.runSql=async()=>new Promise(r=>resolve=r);
    const running=f.host.handle({type:'run',lesson:first});
    while(!resolve)await new Promise(r=>setTimeout(r,1));
    await f.host.select(catalog.paths[0].id,catalog.paths[0].lessons[1]);
    resolve({status:'success',elapsed_ms:1,result:{columns:['n'],rows:[{n:1}]}});await running;
    assert.equal(f.latest().run,undefined);
    await f.host.select(catalog.paths[0].id,first);assert.equal(f.latest().run.lesson,first);
    await f.host.handle({type:'pin',lesson:first});const pin=structuredClone(f.latest().pinned);
    f.runtime.labs.mosaic.runSql=async()=>({status:'success',elapsed_ms:2,result:{columns:['n'],rows:[{n:2}]}});
    await f.host.handle({type:'run',lesson:first});assert.deepEqual(f.latest().pinned,pin);
  }finally{await f.close();}
});
test('file edits make a recorded result stale and invalidate authored source highlights', async () => {
  const f=await fixture();try{
    const lesson=catalog.lessons[0].id;await f.host.handle({type:'openExample',lesson});await f.host.handle({type:'run',lesson});
    const file=path.join(f.folder,'notebooks','learning',lesson,'example.sql');f.docs.get(file).text+='\n-- changed';await f.host.refresh();
    assert.notEqual(f.latest().sourceHash,f.latest().run.sourceHash);
    await assert.rejects(f.host.handle({type:'focusStep',lesson,index:0}),/edited/);
  }finally{await f.close();}
});
test('Python runs retain the existing trust gate and source selection is scoped to the example', async () => {
  const f=await fixture();try{
    const p=catalog.paths.find(p=>p.id==='python-foundations'),lesson=p.lessons[0];await f.host.select(p.id,lesson);await f.host.handle({type:'openExample',lesson});
    await assert.rejects(f.host.handle({type:'run',lesson}),/Trusted local Python/);
    await assert.rejects(f.host.handle({type:'runSelection',lesson}),/Select code/);
    assert.equal(f.latest().run,undefined);
  }finally{await f.close();}
});

// Moving the only webview tab to column Two first makes VS Code collapse and renumber column One.
test('Try opens the native editor before moving the Learning panel beside it', async () => {
  const f=await fixture();try{
    const events=[];
    const show=f.api.window.showTextDocument;
    f.api.window.showTextDocument=async(...args)=>{events.push('native editor');return show(...args);};
    f.host.panel.reveal=()=>events.push('learning panel');
    await f.host.handle({type:'openExample',lesson:catalog.lessons[0].id});
    assert.deepEqual(events,['native editor','learning panel']);
  }finally{await f.close();}
});
