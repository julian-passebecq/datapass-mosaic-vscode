import { loadCatalogDocument } from './learning_catalog.mjs';
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
const catalog = model.validateCatalog(loadCatalogDocument(extensionRoot));
const hostSource = readFileSync(path.join(extensionRoot, 'src/learning/learningWorkspace.ts'), 'utf8');
const compiled = ts.transpileModule(hostSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }, reportDiagnostics: true });
assert.equal(compiled.diagnostics?.length ?? 0, 0);
// The host imports the Leitner schedule of Practice Review; load that real module too.
const reviewCompiled = ts.transpileModule(readFileSync(path.join(extensionRoot, 'src/platform/practiceReview.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
const practiceReview = {};
vm.runInNewContext(reviewCompiled.outputText, { exports: practiceReview, Date, Math, Number, String }, { filename: 'practiceReview.js' });

async function fixture(options = {}) {
  // The host resolves real paths. Windows runners can spell TEMP differently (C:\WINDOWS vs C:\Windows),
  // so use the same canonical spelling for the adapter's case-sensitive document Map and the assertions.
  const folder = await fs.realpath(await fs.mkdtemp(path.join(tmpdir(), 'mosaic-learning-host-')));
  const saved = options.saved ?? new Map(), docs = new Map(), sent = [], calls = [];
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
    EventEmitter, FileType: { File: 1, Directory: 2 }, TreeItem: class { constructor(label) { this.label = label; } }, ThemeIcon: class {},
    ViewColumn: { Active: -1, One: 1, Two: 2 }, TreeItemCollapsibleState: { Expanded: 2, None: 0 },
    Range: class { constructor(a,b,c,d) { this.start={line:a,character:b};this.end={line:c,character:d}; } },
    Selection: class { constructor(a,b) { this.start=a;this.end=b; } }, RelativePattern: class {},
    commands: { executeCommand: async (...args) => calls.push(['command', ...args]) },
    workspace: { isTrusted: true, workspaceFolders: [{ uri: uri(folder) }], onDidChangeTextDocument: event,
      fs: { readFile: u => { const rel = path.relative(extensionRoot, u.fsPath).split(path.sep).join('/'); return options.files && Object.hasOwn(options.files, rel) ? Promise.resolve(Buffer.from(options.files[rel])) : fs.readFile(u.fsPath); }, writeFile: (u, bytes) => fs.writeFile(u.fsPath, bytes),
        readDirectory: async u => (await fs.readdir(u.fsPath, { withFileTypes: true })).map(d => [d.name, d.isDirectory() ? 2 : 1]) },
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
  const refs = new Map(catalog.lessons.flatMap(l => [l.exercise, ...(l.checks ?? []), ...(l.practice ?? [])].filter(Boolean)).map(r => [`${r.id}/${r.language}`, r]));
  const exercises = [...refs.values()].map(r => ({ key:`learning/${r.id}/${r.language}`,id:r.id,language:r.language,version:'1',title:`Exercise ${r.id}`,prompt:'Public brief',sections:[],hints:['one'],dataContext:[] }));
  const exports = {};
  const scope = { exports, require: id => {
    if (id === 'vscode') return api;
    if (id === '../exerciseCatalog') return { loadExerciseCatalog:async()=>exercises };
    if (id === '../projectState') return { readProgress:async()=>progress };
    if (id === '../platform/practiceReview') return practiceReview;
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
  return { host,api,runtime,snapshot,saved,progress:()=>progress,sent,calls,docs,folder,catalog,exercises,context,
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

// Learning engine v1 additions: links, four progress levels, flashcards, cheatsheets, persistence.
const lessonWith = field => catalog.lessons.find(l => l[field]?.length);
const pathOf = id => catalog.paths.find(p => p.lessons.includes(id)).id;

test('a successful whole-file Run records "ran locally, not graded" in workspace state; explain and errors do not', async () => {
  const f=await fixture();try{
    const lesson=catalog.lessons[0].id;await f.host.handle({type:'openExample',lesson});
    await f.host.handle({type:'explain',lesson});assert.equal(f.saved.get('datapass.learning.workspace.v1')?.executed?.[lesson],undefined);
    f.runtime.labs.mosaic.runSql=async()=>({status:'error',error:{type:'Binder',message:'no column'}});
    await f.host.handle({type:'run',lesson});assert.equal(f.latest().levels[lesson].executed,undefined);
    f.runtime.labs.mosaic.runSql=async()=>({status:'success',elapsed_ms:1,result:{columns:['n'],rows:[{n:1}]}});
    await f.host.handle({type:'run',lesson});
    const record=f.saved.get('datapass.learning.workspace.v1').executed[lesson];
    assert.equal(record.version,catalog.lessons[0].version);assert.equal(record.language,'sql');assert.match(record.sourceHash,/^[0-9a-f]{64}$/);
    const levels=f.latest().levels[lesson];assert.ok(levels.executed);assert.equal(levels.verified,false);
    assert.deepEqual(f.latest().badges[lesson].map(b=>b.level),['executed']);
  }finally{await f.close();}
});
test('a concept check Submit shows passed or failed, never verified; only an exercise Submit verifies', async () => {
  const f=await fixture();try{
    const lesson=lessonWith('checks');
    await f.host.select(pathOf(lesson.id),lesson.id);
    const check=f.exercises.find(e=>e.id===lesson.checks[0].id&&e.language===lesson.checks[0].language);
    f.progress().document.practice.exercises[check.key]={attempts:1,last:{mode:'submit',status:'failed',at:'2026-10-12T08:00:00Z',version:'1'}};
    await f.host.refresh();let p=f.latest().levels[lesson.id];
    assert.equal(p.checks.find(c=>c.id===check.id).status,'failed');assert.equal(p.verified,false);
    f.progress().document.practice.exercises[check.key]={attempts:2,solved:{at:'2026-10-12T09:00:00Z',version:'1'},last:{mode:'submit',status:'passed',at:'2026-10-12T09:00:00Z',version:'1'}};
    await f.host.refresh();p=f.latest().levels[lesson.id];
    assert.equal(p.checks.find(c=>c.id===check.id).status,'passed');assert.equal(p.verified,false);
    assert.ok(!f.latest().badges[lesson.id].some(b=>b.level==='verified'));
    await f.host.handle({type:'read',lesson:lesson.id});
    assert.equal(f.latest().levels[lesson.id].verified,false,'a self-report never verifies');
  }finally{await f.close();}
});
test('links open through existing controllers: checks and practice in Practice, missions in their lab, cheatsheets as Markdown preview', async () => {
  const f=await fixture();try{
    const withPractice=lessonWith('practice');await f.host.select(pathOf(withPractice.id),withPractice.id);
    await f.host.handle({type:'openPracticeItem',lesson:withPractice.id,index:0});
    const opened=f.calls.filter(c=>c[0]==='open'&&c[1]==='practice').at(-1)[2];
    assert.equal(opened.exerciseKey,`learning/${withPractice.practice[0].id}/${withPractice.practice[0].language}`);
    await assert.rejects(f.host.handle({type:'openPracticeItem',lesson:withPractice.id,index:99}),/Unsupported/);
    const withMission=lessonWith('missions');await f.host.select(pathOf(withMission.id),withMission.id);
    await f.host.handle({type:'openMission',lesson:withMission.id,index:0});
    const pack=JSON.parse(readFileSync(path.join(extensionRoot,'content','missions',withMission.missions[0].pack,'pack.json'),'utf8'));
    assert.equal(f.calls.filter(c=>c[0]==='open').at(-1)[1],pack.lab);
    assert.equal((await fs.readdir(f.folder)).length,0,'opening a mission creates nothing');
    const withSheet=catalog.lessons.find(l=>l.cheatsheet);await f.host.select(pathOf(withSheet.id),withSheet.id);
    await f.host.handle({type:'cheatsheet',lesson:withSheet.id});
    const preview=f.calls.filter(c=>c[0]==='command'&&c[1]==='markdown.showPreview').at(-1);
    assert.equal(preview[2].fsPath,path.join(extensionRoot,'content','reference',`${withSheet.cheatsheet}.md`));
    await assert.rejects(f.host.handle({type:'openCheatsheet',id:'../../package'}),/Unsupported/);
    await f.host.handle({type:'openCheatsheet',id:'table-formats'});
    assert.ok(f.latest().cheatsheets.some(s=>s.id==='learning-sql'&&s.title==='SQL cheatsheet'));
  }finally{await f.close();}
});
test('flashcards: show, rate with the Practice Review intervals, kept apart from Practice progress and persisted', async () => {
  const saved=new Map();const f=await fixture({saved});try{
    await f.host.review('sql');const review=f.latest().review;
    assert.equal(review.active,true);assert.equal(review.card.deck,'sql');assert.equal(review.card.isNew,true);
    const first=review.card;
    await f.host.handle({type:'rate',deck:'sql',card:first.id,rating:'knew'});
    let record=saved.get('datapass.learning.workspace.v1').flashcards[`sql/${first.id}`];
    assert.equal(record.review.box,1);assert.equal(record.review.due,practiceReview.addDays(practiceReview.localDay(new Date()),1));assert.equal(record.last.rating,'knew');
    assert.notEqual(f.latest().review.card.id,first.id,'a rated card leaves the session queue');
    const second=f.latest().review.card;
    await f.host.handle({type:'rate',deck:'sql',card:second.id,rating:'missed'});
    record=saved.get('datapass.learning.workspace.v1').flashcards[`sql/${second.id}`];assert.equal(record.review.box,1);assert.equal(record.last.rating,'missed');
    await assert.rejects(f.host.handle({type:'rate',deck:'sql',card:first.id,rating:'knew'}),/not in the current review/);
    await assert.rejects(f.host.handle({type:'rate',deck:'sql',card:'no-such-card',rating:'knew'}),/Unsupported/);
    assert.deepEqual(f.progress().document.practice.exercises,{},'flashcards never write Practice progress');
    assert.equal(f.calls.filter(c=>c[0]==='open').length,0);
    await f.host.handle({type:'reviewClose'});assert.equal(f.latest().review.active,false);
  }finally{await f.close();}
  // A new host on the same workspace storage: the ratings and their schedule survive a restart.
  const g=await fixture({saved});try{
    const restored=g.latest().state.flashcards;assert.equal(Object.keys(restored).length,2);
    assert.ok(Object.values(restored).every(r=>r.review&&r.review.box===1));
  }finally{await g.close();}
});
test('resume names the next unverified item and due flashcards; search data covers cheatsheets and card fronts', async () => {
  const f=await fixture();try{
    const resume=f.latest().resume;assert.equal(resume.lesson,catalog.paths[0].lessons[0]);
    assert.ok(resume.next&&catalog.lessons.some(l=>l.id===resume.next.lesson));assert.equal(resume.dueCards,0);
    const hits=model.searchAll(f.latest().catalog,'git rebase',{cheatsheets:f.latest().cheatsheets,cards:f.latest().cards});
    assert.ok(hits.cards.some(c=>c.deck==='git'));
    assert.ok(model.searchAll(f.latest().catalog,'cheatsheet',{cheatsheets:f.latest().cheatsheets}).cheatsheets.length>=7);
  }finally{await f.close();}
});
test('the host refuses a lesson that links a mission, cheatsheet, deck or exercise that is not shipped', async () => {
  const doc=JSON.parse(readFileSync(path.join(extensionRoot,'content/learning/paths/git-shell.json'),'utf8'));
  const cases=[[l=>{l.missions=[{pack:'terminal-v1',id:'not-a-mission'}];},/unknown mission/],[l=>{l.cheatsheet='not-a-sheet';},/unknown cheatsheet/],
    [l=>{l.deck='not-a-deck';},/unknown flashcard deck/],[l=>{l.practice=[{id:'not-installed',language:'sql'}];},/not installed/]];
  for (const [change,pattern] of cases) {
    const copy=structuredClone(doc);change(copy.lessons[0]);
    await assert.rejects(fixture({files:{'content/learning/paths/git-shell.json':JSON.stringify(copy)}}),pattern);
  }
  const badDeck=JSON.parse(readFileSync(path.join(extensionRoot,'content/learning/flashcards/git.json'),'utf8'));badDeck.cards[0].front='x'.repeat(301);
  await assert.rejects(fixture({files:{'content/learning/flashcards/git.json':JSON.stringify(badDeck)}}),/invalid text/);
});
test('the native tree shows the four levels as separate segments and offers flashcard review', async () => {
  const f=await fixture();try{
    const lesson=catalog.lessons[0].id;await f.host.handle({type:'read',lesson});await f.host.handle({type:'openExample',lesson});await f.host.handle({type:'run',lesson});
    const roots=await f.host.getChildren();assert.ok(roots.some(n=>n.kind==='review'));
    const node=(await f.host.getChildren(roots.find(n=>n.id===catalog.paths[0].id))).find(n=>n.id.endsWith(`/${lesson}`));
    assert.equal(node.description,'Read (self-reported) · Ran locally, not graded');
  }finally{await f.close();}
});
