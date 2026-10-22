// Drive the real lab controllers with refused saves and save participants. No runtime executes in these tests.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';

const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = await mkdtemp(path.join(tmpdir(), 'mosaic-save-host-'));
after(() => rm(temp, { recursive: true, force: true }));
const stubs = {
  vscode: `
    const s = () => globalThis.__labSave;
    const uri = p => ({ scheme: 'file', path: p, fsPath: p, toString: () => 'file://' + p });
    export const Uri = { file: uri, joinPath: (base, ...parts) => uri(base.path + '/' + parts.join('/')) };
    export const workspace = {
      get textDocuments() { return s().docs; },
      get workspaceFolders() { return [{ uri: uri('/ws') }]; },
      asRelativePath: u => u.path.replace('/ws/', '')
    };
    export const window = { showWarningMessage: async text => { s().warnings.push(text); },
      showErrorMessage: async text => { throw new Error(text); } };
  `,
  factoryState: `
    import { Uri } from 'vscode';
    const s = () => globalThis.__labSave;
    export const factoryRoot = () => Uri.file('/ws/factory');
    export const factoryFileUri = p => Uri.file('/ws/' + p);
    export const readPoolScript = async () => ({ text: s().text });
    export const collectFactoryFiles = async () => { throw new Error('must not collect before saving'); };
    export const collectDatabricksFiles = collectFactoryFiles;
    export const copyFactorySamples = () => {};
    export const databricksJobPath = () => {};
    export const pipelineUri = () => {};
  `,
  biState: `
    import { Uri } from 'vscode';
    export const biRoot = () => Uri.file('/ws/bi');
    export const collectBiScripts = async () => { throw new Error('must not collect before saving'); };
    export const collectBiDbtFiles = collectBiScripts;
    export const biFileUri = () => {};
    export const copyBiSamples = () => {};
    export const readBiModel = () => {};
  `
};
const outfile = path.join(temp, 'controllers.mjs');
await esbuild.build({
  stdin: { contents: `
    export { FabricController } from './src/labs/fabric/controller';
    export { BiController } from './src/labs/bi/controller';
    export { ApiLabController } from './src/labs/apilab/controller';
    export { saveDirtyUnder } from './src/labs/host';`, resolveDir: root, loader: 'ts' },
  bundle: true, platform: 'node', format: 'esm', target: 'node20', outfile, logLevel: 'silent',
  plugins: [{ name: 'host-stubs', setup(build) {
    build.onResolve({ filter: /^(vscode|.*\/(factoryState|biState))$/ }, args => ({
      path: args.path === 'vscode' ? 'vscode' : args.path.split('/').pop(), namespace: 'stub'
    }));
    build.onLoad({ filter: /.*/, namespace: 'stub' }, args => ({ contents: stubs[args.path], loader: 'js' }));
  } }]
});
const { FabricController, BiController, ApiLabController, saveDirtyUnder } = await import(pathToFileURL(outfile).href);
const uri = p => ({ scheme: 'file', path: p, fsPath: p, toString: () => 'file://' + p });
function setup(file, saveResult = false) {
  const state = { docs: [], warnings: [], calls: [], saves: 0, text: 'SELECT 1 AS before_save;' };
  state.docs.push({ uri: uri('/ws/' + file), isDirty: true, getText: () => state.text,
    save: async () => { state.saves++; if (saveResult) state.text = 'SELECT 2 AS after_save;'; return saveResult; } });
  globalThis.__labSave = state;
  const run = async value => { state.calls.push(value); return { status: 'ok' }; };
  const host = { context: { workspaceState: { update: async () => {} } }, refresh: async () => {},
    guarded: async (_label, fn) => fn(), runtime: { labs: {
      fabric: { runSqlPool: run, simulateFactory: run, simulateDatabricks: run },
      bi: { runBiLab: run, runBiDbt: run }, apilab: { run }
    } } };
  return { state, fabric: new FabricController(host, {}), bi: new BiController(host), api: new ApiLabController(host) };
}

for (const [name, file, action] of [
  ['Cloud pipeline', 'factory/pipeline.json', s => s.fabric.handlers.simulateFactory({ flavor: 'fabric', name: 'pipeline', scenario: {} })],
  ['Databricks job', 'factory/job.json', s => s.fabric.handlers.simulateDatabricks({ name: 'job', scenario: {} })],
  ['BI build', 'bi/warehouse/model.sql', s => s.bi.handlers.runBiLab({ mode: 'build' })],
  ['BI dbt', 'bi/dbt/model.sql', s => s.bi.handlers.runBiDbt({ command: 'build', select: '', fullRefresh: false })],
  ['API ingestion', 'missions/paginated/ingest.py', s => s.api.handlers.runApiIngestion({ missionId: 'paginated' })],
  ['SQL pool', 'factory/sql/pool/model.sql', s => s.fabric.handlers.runSqlPool({ flavor: 'synapse', scale: 1, source: 'file', path: 'factory/sql/pool/model.sql' })]
]) {
  test(`${name} refuses to execute when saving fails`, async () => {
    const s = setup(file);
    await action(s);
    assert.equal(s.state.saves, 1);
    assert.deepEqual(s.state.calls, []);
    assert.match(s.state.warnings[0], /before running/);
  });
}

test('SQL pool executes the text after save participants finish', async () => {
  const s = setup('factory/sql/pool/model.sql', true);
  await s.fabric.handlers.runSqlPool({ flavor: 'synapse', scale: 1, source: 'file', path: 'factory/sql/pool/model.sql' });
  assert.equal(s.state.calls.length, 1);
  assert.equal(s.state.calls[0].script, 'SELECT 2 AS after_save;');
});

test('saving a lab leaves a sibling folder untouched', async () => {
  const s = setup('factory-other/script.sql');
  assert.equal(await saveDirtyUnder(uri('/ws/factory')), true);
  assert.equal(s.state.saves, 0);
});
