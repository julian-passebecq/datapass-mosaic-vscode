// Build (src/build): the blank workspace manifest (catalog.seed "none", trusted Python off) and its schema, safe file
// names with the kind's extension, datasets never replacing a file, Today not suggesting demo-table steps on a blank
// workspace, and the five commands contributed and registered.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';
import * as esbuild from 'esbuild';

const root = fileURLToPath(new URL('../..', import.meta.url));
const dir = await mkdtemp(path.join(tmpdir(), 'datapass-build-'));
after(() => rm(dir, { recursive: true, force: true }));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [path.join(root, entry)], bundle: true, platform: 'node', format: 'esm', target: 'node20', outfile, logLevel: 'silent' });
  return import(pathToFileURL(outfile).href);
}

const b = await bundle('src/build/buildModel.ts', 'build.mjs');
const m = await bundle('src/project/projectManifestModel.ts', 'manifest.mjs');
const { homeView } = await bundle('src/labs/workbench/home.ts', 'home.mjs');
const ajv = new Ajv2020({ allErrors: true, strict: false });
const projectSchema = ajv.compile(JSON.parse(await readFile(path.join(root, 'schemas/project.schema.json'), 'utf8')));

test('a blank workspace manifest: seed none, trusted Python off, valid for the extension and the schema', () => {
  const blank = m.createBlankProjectManifest('My Lab');
  assert.equal(blank.catalog.seed, 'none');
  assert.equal(blank.runtime.trustedLocalPython, false, 'nothing becomes trusted automatically');
  assert.equal(blank.project.id, 'my-lab');
  assert.deepEqual(m.validateProjectManifest(blank), []);
  assert.ok(projectSchema(blank), ajv.errorsText(projectSchema.errors));
  assert.equal(m.catalogSeed(blank), 'none');
});

test('absent seed means demo: today\'s manifests and catalogs are unchanged', () => {
  const demo = m.createDefaultProjectManifest('x');
  assert.equal(demo.catalog, undefined, 'the default manifest does not gain a catalog field');
  assert.equal(m.catalogSeed(demo), 'demo');
  assert.equal(m.catalogSeed(undefined), 'demo');
  assert.equal(m.catalogSeed({ ...demo, catalog: {} }), 'demo');
  assert.equal(m.catalogSeed({ ...demo, catalog: { seed: 'demo' } }), 'demo');
  for (const catalog of [{ seed: 'empty' }, [], 'none']) {
    const broken = { ...demo, catalog };
    assert.ok(m.validateProjectManifest(broken).length > 0, `refused: ${JSON.stringify(catalog)}`);
    if (typeof catalog === 'object' && !Array.isArray(catalog)) assert.ok(!projectSchema(broken), 'the schema agrees');
  }
});

test('file names: a single safe name, the kind\'s extension added or enforced', () => {
  assert.deepEqual(b.fileNameForKind('revenue', 'sql'), { fileName: 'revenue.sql' });
  assert.deepEqual(b.fileNameForKind('revenue.SQL', 'sql'), { fileName: 'revenue.sql' });
  assert.deepEqual(b.fileNameForKind('clean orders', 'polars'), { fileName: 'clean orders.py' });
  assert.deepEqual(b.fileNameForKind('notes', 'markdown'), { fileName: 'notes.md' });
  assert.deepEqual(b.fileNameForKind('v1.2 draft', 'sql'), { fileName: 'v1.2 draft.sql' }, 'a version dot is not an extension');
  assert.match(b.fileNameForKind('revenue.py', 'sql').error, /ends with \.sql, not \.py/);
  for (const bad of ['', '   ', '../x', 'a/b', 'a\\b', '.hidden', 'con', 'NUL.sql', 'x?.sql', 'a..b', 'x'.repeat(81), 'name.']) {
    assert.ok(b.fileNameError(bad), `refused: ${JSON.stringify(bad)}`);
  }
  assert.equal(b.titleFromFileName('daily_revenue-check.sql'), 'Daily revenue check');
});

test('every kind has a folder and a header; Python and Polars say trusted Python is needed; no demo tables', () => {
  assert.deepEqual(b.BUILD_FILE_KINDS.map(k => k.kind), ['sql', 'python', 'polars', 'markdown']);
  for (const kind of b.BUILD_FILE_KINDS) {
    const header = kind.header('Title');
    assert.ok(header.length > 0 && !/source\.orders|turbine|dim_customer/.test(header), `${kind.kind}: no demo table in the starter`);
    assert.equal(kind.needsTrustedPython, kind.kind === 'python' || kind.kind === 'polars');
    if (kind.needsTrustedPython) assert.match(header, /trusted local Python/);
    assert.equal(b.fileNameForKind(kind.defaultName, kind.kind).fileName, kind.defaultName);
  }
  assert.deepEqual([...b.BUILD_FOLDERS], ['notebooks', 'datasets', 'notes']);
});

test('datasets: never replace a file, suggest name-2', () => {
  assert.equal(b.nextFreeName('orders.csv', []), 'orders.csv');
  assert.equal(b.nextFreeName('orders.csv', ['orders.csv']), 'orders-2.csv');
  assert.equal(b.nextFreeName('orders.csv', ['ORDERS.csv', 'orders-2.csv']), 'orders-3.csv');
  assert.match(b.datasetNameError('orders.csv', ['orders.csv']), /never replaced\. Try orders-2\.csv/);
  assert.equal(b.datasetNameError('orders-2.csv', ['orders.csv']), undefined);
  assert.match(b.datasetNameError('orders.txt', []), /dataset extension/);
  assert.equal(b.datasetExtension('a.PARQUET'), '.parquet');
  assert.equal(b.datasetExtension('a.xlsx'), undefined);
});

test('empty folders: dotfiles ignored, any file or subfolder counts', () => {
  assert.equal(b.folderHasNoFiles([]), true);
  assert.equal(b.folderHasNoFiles([{ name: '.gitkeep', isFile: true }]), true);
  assert.equal(b.folderHasNoFiles([{ name: 'a.sql', isFile: true }]), false);
});

test('Today on a blank workspace suggests no project step or project start (they read the demo tables)', () => {
  const project = { id: 'retail-fabric', title: 'Retail', summary: 'A retail story.', started: false, nextStepId: 's1',
    progress: { percent: 0, done: 0, required: 3 }, steps: [{ id: 's1', title: 'Load', module: 'mosaic', moduleLabel: 'Mosaic' }] };
  const base = { hasWorkspace: true, projects: [project], exerciseKeys: ['k1'], practice: {}, today: '2026-10-12' };
  assert.equal(homeView(base).next.kind, 'start-project', 'a demo workspace still suggests a project');
  assert.equal(homeView({ ...base, blankCatalog: true }).next.kind, 'practice');
  const started = { ...project, started: true };
  assert.equal(homeView({ ...base, projects: [started] }).next.kind, 'project-step');
  assert.notEqual(homeView({ ...base, projects: [started], blankCatalog: true }).next.kind, 'project-step');
});

test('the five Build and exchange commands are contributed and registered once', async () => {
  const pkg = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
  const ids = ['datapass.build.newWorkspace', 'datapass.build.newFile', 'datapass.build.importDataset', 'datapass.interop.import', 'datapass.interop.export'];
  const contributed = pkg.contributes.commands.map(c => c.command);
  const sources = (await Promise.all((await readdir(path.join(root, 'src/build'))).map(n => readFile(path.join(root, 'src/build', n), 'utf8')))).join('\n');
  for (const id of ids) {
    assert.equal(contributed.filter(c => c === id).length, 1, `${id} contributed once`);
    assert.equal(sources.split(`registerCommand("${id}"`).length - 1, 1, `${id} registered once in src/build`);
  }
  const extension = await readFile(path.join(root, 'src/extension.ts'), 'utf8');
  assert.equal(extension.split('registerBuildCommands(context, runtimeManager, pythonTrust)').length - 1, 1);
});

test('the runtime gets the seed from the manifest at launch, and grading catalogs stay seeded', async () => {
  const manager = await readFile(path.join(root, 'src/runtimeManager.ts'), 'utf8');
  assert.match(manager, /DATAPASS_CATALOG_SEED: seed/);
  const main = await readFile(path.join(root, 'runtime/datapass_runtime/main.py'), 'utf8');
  assert.match(main, /seed=os\.getenv\("DATAPASS_CATALOG_SEED", "demo"\)/);
  const catalog = await readFile(path.join(root, 'runtime/datapass_runtime/catalog.py'), 'utf8');
  assert.match(catalog, /seed: str = 'demo'/, 'Catalog(...) without a seed (grading) keeps the demo tables');
});
