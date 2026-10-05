// Real packaged VSIX + native editors. Run after npm run package, under xvfb on Linux.
import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath } from '@vscode/test-electron';
import { _electron } from 'playwright-core';
const repo = process.cwd();
const root = mkdtempSync(path.join(tmpdir(), 'dpw-learning-ui-'));
const out = path.join(repo, 'test-results', 'vscode-ui', 'learning');
const workspace = path.join(root, 'ws');
const extensions = path.join(root, 'x');
const profile = path.join(root, 'u');
for (const p of [out,workspace,extensions,path.join(profile,'User')]) mkdirSync(p,{recursive:true});
const report = { target:'packaged VSIX in real VS Code', checks:[], errors:[], completed:false };
const pass = (name,detail='') => { report.checks.push({name,detail,passed:true});console.log(`PASS Learning: ${name}`); };
const files = readdirSync(repo).filter(f=>f.endsWith('.vsix')).map(f=>path.join(repo,f)).sort((a,b)=>statSync(b).mtimeMs-statSync(a).mtimeMs);
const vsix=process.env.DATAPASS_UI_VSIX || files[0];
let app;
let fatal;
let page;
async function close() {
  if(!app)return;
  const closing=app;app=undefined;
  let timer;
  try { await Promise.race([closing.close(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('VS Code close timed out')),30000);})]); }
  catch(error) { closing.process().kill(); throw error; }
  finally { clearTimeout(timer); }
}
async function command(title) {
  await page.keyboard.press('Escape');
  const center=page.locator('.command-center-center').first();
  if(await center.isVisible().catch(()=>false))await center.click();else await page.keyboard.press('F1');
  const input=page.locator('.quick-input-widget input');
  // Wait for the command-center click to finish opening; a second F1 can close it.
  await input.waitFor({state:'visible'});await input.fill(`>${title}`);
  await page.locator('.quick-input-list .monaco-list-row',{hasText:title}).first().waitFor();await page.keyboard.press('Enter');
}
async function learningFrame() {
  const until=Date.now()+30000;
  while(Date.now()<until) {
    for(const frame of page.frames())if(await frame.locator('#learning-root h1').count().catch(()=>0))return frame;
    await new Promise(r=>setTimeout(r,100));
  }
  throw new Error('Learning webview did not become ready');
}
async function mode(name) {
  const f=await learningFrame();await f.getByRole('navigation',{name:'Lesson views'}).getByRole('button',{name,exact:true}).click();
  return f;
}
try {
  assert.ok(vsix,'No VSIX: run npm run package first.');
  writeFileSync(path.join(profile,'User','settings.json'),JSON.stringify({
    'workbench.startupEditor':'none','workbench.tips.enabled':false,'workbench.enableExperiments':false,
    'window.restoreWindows':'none','window.dialogStyle':'custom','window.titleBarStyle':'custom',
    'workbench.secondarySideBar.defaultVisibility':'hidden',
    'update.mode':'none','extensions.autoUpdate':false,'extensions.ignoreRecommendations':true,
    'telemetry.telemetryLevel':'off','security.workspace.trust.enabled':false,'chat.disableAIFeatures':true,
    'git.openRepositoryInParentFolders':'never'
  }));
  const executable=process.env.DATAPASS_UI_CODE || await downloadAndUnzipVSCode(process.env.VSCODE_TEST_VERSION || 'stable');
  const [cli,...args]=resolveCliArgsFromVSCodeExecutablePath(executable);
  const installed=spawnSync(cli,[...args,`--extensions-dir=${extensions}`,`--user-data-dir=${profile}`,'--install-extension',vsix,'--force'],{encoding:'utf8',shell:process.platform==='win32',timeout:600000});
  assert.equal(installed.status,0,installed.stderr || installed.stdout);pass('candidate VSIX installed');
  const launch=async()=>{
    app=await _electron.launch({executablePath:executable,args:[workspace,`--extensions-dir=${extensions}`,`--user-data-dir=${profile}`,'--disable-workspace-trust','--skip-welcome','--skip-release-notes','--disable-telemetry','--new-window',...(process.platform==='win32'?[]:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])],timeout:180000});
    page=await app.firstWindow();page.setDefaultTimeout(30000);
    await page.waitForSelector('.monaco-workbench',{timeout:180000});
    await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setSize(1400,1000);});
    page.on('console',m=>{if(m.type()==='error'&&/vscode-webview:/.test(m.location()?.url??''))report.errors.push(m.text());});
  };
  await launch();await command('View: Close Primary Side Bar');await command('Datapass: Open Learning');let f=await learningFrame();
  await f.getByRole('heading',{name:'Join rows, not circles',exact:true}).waitFor();pass('Learning command opens course without setup or execution');
  await page.screenshot({path:path.join(out,'01-read.png')});
  await f.getByRole('button',{name:'Hide path',exact:true}).click();await f.getByRole('button',{name:'Show path',exact:true}).waitFor();
  assert.equal(await f.getByRole('complementary',{name:'Learning path'}).count(),0);pass('right course rail hides');
  await f.getByRole('button',{name:'Show path',exact:true}).click();await f.getByRole('complementary',{name:'Learning path'}).waitFor();
  await f.getByRole('button',{name:'Mark as read',exact:true}).click();await f.getByText('Read (self-reported)',{exact:true}).first().waitFor();pass('reading persists as self-report');
  await f.locator('.notes summary').click();await f.getByRole('textbox',{name:'Lesson notes'}).fill('Learning UI persistence check');await f.getByRole('button',{name:'Save notes',exact:true}).click();
  await f.getByText('Notes saved in workspace storage.',{exact:true}).waitFor();
  await mode('Try');f=await learningFrame();await f.getByRole('heading',{name:'Work in the native editor',exact:true}).waitFor();
  const source=path.join(workspace,'notebooks','learning','sql-joins','example.sql');
  const until=Date.now()+10000;while(!existsSync(source)&&Date.now()<until)await new Promise(r=>setTimeout(r,100));
  assert.ok(existsSync(source));assert.match(readFileSync(source,'utf8'),/LEFT JOIN/);pass('Try creates a real native SQL example');
  appendFileSync(source,'\n-- preserve learner edit\n');await mode('Read');await mode('Try');
  assert.match(readFileSync(source,'utf8'),/preserve learner edit/);pass('view changes preserve learner source');
  const exercise=path.join(workspace,'exercises','sql-lab-left-preserve-customers','sql','solution.sql');
  const reference=JSON.parse(readFileSync(path.join(repo,'content','exercise-packs','sql-lab-v1','grading.server.json'),'utf8'))['sql-lab-left-preserve-customers'].solution;
  mkdirSync(path.dirname(exercise),{recursive:true});writeFileSync(exercise,reference);
  await mode('Exercise');f=await learningFrame();await f.getByRole('button',{name:'Submit solution',exact:true}).waitFor();
  const untilExercise=Date.now()+10000;while(!existsSync(exercise)&&Date.now()<untilExercise)await new Promise(r=>setTimeout(r,100));
  assert.ok(existsSync(exercise));pass('Exercise delegates to existing Practice native file');
  await page.screenshot({path:path.join(out,'02-exercise.png')});
  // Use the existing Workbench setup flow. No new token, HTTP or kernel bypass is introduced by this gate.
  await command('Datapass: Open Today');
  let wb;
  for(let n=0;n<300&&!wb;n++) {
    for(const frame of page.frames())if(await frame.locator('.module-main').count().catch(()=>0)){wb=frame;break;}
    if(!wb)await new Promise(r=>setTimeout(r,100));
  }
  assert.ok(wb,'Workbench frame not found');
  const create=wb.getByRole('button',{name:'Create .datapass project',exact:true}).first();
  await create.or(wb.getByRole('button',{name:'Setup runtime',exact:true}).first()).first().waitFor();
  if(await create.count()){await create.click();await create.waitFor({state:'detached',timeout:60000});}
  if(process.env.DATAPASS_UI_PYTHON) {
    const file=path.join(workspace,'.datapass','project.json');const manifest=JSON.parse(readFileSync(file,'utf8'));
    manifest.runtime={...manifest.runtime,pythonCommand:process.env.DATAPASS_UI_PYTHON};writeFileSync(file,JSON.stringify(manifest,null,2));
  }
  await wb.getByRole('button',{name:'Setup runtime',exact:true}).first().click();
  await wb.getByRole('button',{name:'Start runtime',exact:true}).first().waitFor({timeout:1200000});
  await wb.getByRole('button',{name:'Start runtime',exact:true}).first().click();
  await wb.getByRole('button',{name:'Stop runtime',exact:true}).first().waitFor({timeout:180000});
  pass('existing managed runtime starts through its own explicit setup flow');
  await command('Datapass: Resume Learning');f=await learningFrame();
  await f.getByRole('button',{name:'Submit solution',exact:true}).click();
  await f.getByRole('heading',{name:'Last submit: passed',exact:true}).waitFor({timeout:90000});
  await f.getByText('Practice passed',{exact:true}).first().waitFor();pass('Learning Submit is really graded by existing Practice and updates its progress');
  await mode('Try');f=await learningFrame();await f.getByRole('button',{name:'Run example',exact:true}).click();
  await f.getByRole('heading',{name:'Real local result rows',exact:true}).waitFor({timeout:60000});pass('native SQL example returns real local DuckDB rows in Learning');
  await mode('Read');f=await learningFrame();await f.getByRole('button',{name:'Learning map',exact:true}).click();
  await f.getByRole('searchbox',{name:'Search lessons'}).fill('broadcast');
  await f.locator('.map').getByRole('button',{name:'Broadcast a small dimension',exact:true}).click();await f.getByRole('heading',{name:'Broadcast a small dimension',exact:true}).waitFor();
  pass('curriculum search crosses lab boundaries');await mode('Watch');f=await learningFrame();
  await f.getByLabel('Operation',{exact:true}).selectOption('coalesce');await f.getByLabel('Requested partitions',{exact:true}).selectOption('8');
  assert.equal(await f.locator('.partitions').nth(1).locator('.partition').count(),4);pass('partition illustration respects coalesce limits');
  await page.screenshot({path:path.join(out,'03-spark.png')});
  await mode('Try');f=await learningFrame();
  await f.getByRole('button',{name:'Run example',exact:true}).click();
  await f.getByText('SIMULATED DISTRIBUTED BEHAVIOR',{exact:true}).waitFor({timeout:60000});
  await f.getByRole('heading',{name:'Real local result rows',exact:true}).waitFor();
  pass('SparkLab uses real local result rows with separately labelled simulated stages');
  await mode('Watch');f=await learningFrame();
  // Native window resize rather than injecting layout CSS into a production webview.
  await app.evaluate(({BrowserWindow})=>{const window=BrowserWindow.getAllWindows()[0];window.unmaximize();window.setSize(900,1000);});
  await f.waitForTimeout(300);
  assert.ok(await f.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));pass('narrow native editor group has no page overflow');
  await close();await launch();await command('Datapass: Resume Learning');f=await learningFrame();
  await f.getByRole('heading',{name:'Broadcast a small dimension',exact:true}).waitFor();pass('topic and view resume across an actual VS Code restart');
  await f.getByRole('button',{name:'Learning map',exact:true}).click();await f.getByRole('searchbox',{name:'Search lessons'}).fill('Join rows');
  await f.locator('.map').getByRole('button',{name:'Join rows, not circles',exact:true}).click();await f.getByText('Practice passed',{exact:true}).first().waitFor();
  await f.locator('.notes summary').click();assert.equal(await f.getByRole('textbox',{name:'Lesson notes'}).inputValue(),'Learning UI persistence check');
  pass('reading acknowledgements and notes survive restart');
  assert.equal(report.errors.length,0,report.errors.join('\n'));pass('no Learning webview console errors');
  report.completed=true;
}catch(error){
  fatal=error;report.failure=String(error);console.error(error);
  if(page&&!page.isClosed()) {
    await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>undefined);
    writeFileSync(path.join(out,'failure-dom.txt'),await page.locator('body').innerText().catch(()=>''));
    for(const [i,frame] of page.frames().entries()) {
      const text=await frame.locator('body').innerText().catch(()=>undefined);
      if(text)writeFileSync(path.join(out,`failure-frame-${i}.txt`),text);
    }
  }
}
finally{
  try{await close();}catch(error){fatal ||= error;report.failure=String(error);}
  writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
}
if(fatal || !report.completed)process.exitCode=1;
