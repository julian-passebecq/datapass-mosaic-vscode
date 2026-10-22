// Mosaic exchange (datapass.mosaic-exchange v1, src/platform/mosaicExchange.ts): the shipped examples validate against
// the TypeScript validator and the JSON schema, round trip through import (files + record) and export, cycles and
// broken references are refused, artifacts never carry data, and an import never overwrites a file.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';
import * as esbuild from 'esbuild';

const root = fileURLToPath(new URL('../..', import.meta.url));
const dir = await mkdtemp(path.join(tmpdir(), 'datapass-exchange-'));
after(() => rm(dir, { recursive: true, force: true }));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [path.join(root, entry)], bundle: true, platform: 'node', format: 'esm', target: 'node20', outfile, logLevel: 'silent' });
  return import(pathToFileURL(outfile).href);
}

const x = await bundle('src/platform/mosaicExchange.ts', 'exchange.mjs');
const { createExclusiveAt } = await bundle('src/build/exclusiveFile.ts', 'exclusive.mjs');
const schema = JSON.parse(await readFile(path.join(root, 'schemas/mosaic-exchange.schema.json'), 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: false });
const schemaValid = ajv.compile(schema);
const exampleDir = path.join(root, 'content/interop/examples');
const examples = await Promise.all((await readdir(exampleDir)).filter(n => n.endsWith('.json')).sort()
  .map(async name => ({ name, doc: JSON.parse(await readFile(path.join(exampleDir, name), 'utf8')) })));
const clone = value => structuredClone(value);

test('current datasets survive id collisions and refresh plain file hashes without rewriting run history', () => {
  const doc = clone(examples[0].doc);
  const notebook = doc.notebooks[0];
  const old = 'a'.repeat(64), fresh = 'b'.repeat(64);
  doc.artifacts = [
    { id: 'dataset-orders', kind: 'file', name: 'datasets/orders.csv', sha256: old, custom: 'keep' },
    { id: 'dataset-history', kind: 'file', name: 'datasets/history.csv', sha256: old,
      producedBy: { notebook: notebook.id, cell: notebook.cells[0].id } }
  ];
  const [plan] = x.planImport(doc, 'notebooks', '2026-10-22T12:00:00Z');
  const exported = x.buildExport({
    producerVersion: '0.4.1', exportedAt: '2026-10-22T13:00:00Z', duckdbVersion: '1.5.5', source: 'test',
    notebooks: [x.notebookFromRecord(plan.record.content, new Map(plan.files.map(f => [f.path, f.content])))],
    files: [
      { id: 'dataset-orders', name: 'datasets/orders.csv', sha256: fresh },
      { id: 'dataset-orders', name: 'datasets/orders.json', sha256: fresh },
      { id: 'dataset-history', name: 'datasets/history.csv', sha256: fresh }
    ]
  });
  assert.equal(new Set(exported.artifacts.map(a => a.id)).size, 4);
  const orders = exported.artifacts.find(a => a.name === 'datasets/orders.csv');
  assert.equal(orders.sha256, fresh);
  assert.equal(orders.custom, 'keep');
  assert.equal(exported.artifacts.find(a => a.name === 'datasets/orders.json').sha256, fresh);
  const history = exported.artifacts.filter(a => a.name === 'datasets/history.csv');
  assert.equal(history.find(a => a.producedBy).sha256, old);
  assert.equal(history.find(a => !a.producedBy).sha256, fresh);
  assert.ok(x.validateExchange(exported).ok);
  assert.ok(schemaValid(exported), ajv.errorsText(schemaValid.errors));
});

test('nested unknown producer, runtime and provenance fields survive a round trip', () => {
  const doc = clone(examples[0].doc);
  for (const name of ['producer', 'runtime', 'provenance']) doc[name].custom = { keep: name };
  doc.provenance.commit = 'a'.repeat(40);
  const { exported } = roundTrip(doc);
  for (const name of ['producer', 'runtime', 'provenance']) assert.deepEqual(exported[name].custom, doc[name].custom);
  assert.equal(exported.runtime.engine, 'duckdb-native');
  assert.equal(exported.producer.app, 'datapass-workbench');
  assert.equal(exported.provenance.commit, undefined, 'the new export does not claim the imported commit');
});

test('a current dataset survives deleting its historical producer cell', () => {
  const doc = clone(examples[0].doc);
  const notebook = doc.notebooks[0];
  const producer = notebook.cells[0].id;
  const file = { id: 'dataset-orders', kind: 'file', name: 'datasets/orders.csv', sha256: 'a'.repeat(64) };
  doc.artifacts = [{ ...file, producedBy: { notebook: notebook.id, cell: producer } }];
  const [plan] = x.planImport(doc, 'notebooks', '2026-10-22T12:00:00Z');
  const sources = new Map(plan.files.filter(f => f.cell !== producer).map(f => [f.path, f.content]));
  const exported = x.buildExport({
    producerVersion: '0.4.1', exportedAt: '2026-10-22T13:00:00Z', duckdbVersion: '1.5.6', source: 'test',
    notebooks: [x.notebookFromRecord(plan.record.content, sources)], files: [file]
  });
  assert.deepEqual(exported.artifacts, [file]);
  assert.ok(x.validateExchange(exported).ok);
});

/** Import into a virtual workspace, then export from its records with the files as written. */
function roundTrip(doc) {
  const parsed = x.validateExchange(doc);
  assert.ok(parsed.ok, JSON.stringify(parsed.errors));
  const plans = x.planImport(parsed.exchange, 'notebooks', '2026-10-12T08:00:00Z');
  const files = new Map();
  for (const plan of plans) for (const file of plan.files) files.set(file.path, file.content);
  const records = plans.map(plan => JSON.parse(JSON.stringify(plan.record.content)));
  const exported = x.buildExport({
    producerVersion: '0.3.0', exportedAt: '2026-10-12T09:00:00Z', duckdbVersion: '1.4.1', source: 'datapass-workbench:test',
    notebooks: records.map(record => x.notebookFromRecord(record, files)), files: []
  });
  return { plans, exported };
}

test('every example validates with the TypeScript validator and the JSON schema', () => {
  assert.ok(examples.length >= 2, 'at least two examples ship');
  const engines = new Set();
  for (const { name, doc } of examples) {
    const result = x.validateExchange(doc);
    assert.ok(result.ok, `${name}: ${JSON.stringify(result.errors)}`);
    assert.ok(schemaValid(doc), `${name}: ${ajv.errorsText(schemaValid.errors)}`);
    engines.add(doc.runtime.engine);
  }
  assert.deepEqual([...engines].sort(), ['duckdb-native', 'duckdb-wasm'], 'one example per engine');
});

test('examples round trip: notebooks, cells, dependencies, artifacts, runs and extensions come back', () => {
  for (const { name, doc } of examples) {
    const { exported } = roundTrip(clone(doc));
    const check = x.validateExchange(exported);
    assert.ok(check.ok, `${name} export: ${JSON.stringify(check.errors)}`);
    assert.ok(schemaValid(exported), `${name} export: ${ajv.errorsText(schemaValid.errors)}`);
    assert.deepEqual(exported.notebooks, doc.notebooks, `${name}: notebooks (with unknown cell fields)`);
    assert.deepEqual([...exported.artifacts].sort((a, b) => a.id.localeCompare(b.id)), [...doc.artifacts].sort((a, b) => a.id.localeCompare(b.id)), `${name}: artifacts`);
    assert.deepEqual(exported.provenance.runs, doc.provenance.runs, `${name}: runs keep their own engine`);
    assert.deepEqual(exported.extensions, doc.extensions ?? {}, `${name}: extensions pass through`);
    assert.equal(exported.runtime.engine, 'duckdb-native', 'an export from the Workbench is native DuckDB');
    assert.equal(exported.producer.app, 'datapass-workbench');
  }
});

test('import writes native files under notebooks/imported/<id>/ and labels WASM runs as not re-run', () => {
  const studio = examples.find(e => e.doc.runtime.engine === 'duckdb-wasm').doc;
  const [plan] = x.planImport(x.validateExchange(clone(studio)).exchange, 'notebooks', '2026-10-12T08:00:00Z');
  assert.equal(plan.folder, 'notebooks/imported/sensor-daily');
  assert.deepEqual(plan.files.map(f => f.path.split('/').pop()), ['01-intro.md', '02-load.sql', '03-daily.sql', '04-check.sql']);
  for (const file of plan.files) assert.ok(file.path.startsWith(`${plan.folder}/`));
  assert.equal(plan.record.path, '.datapass/interop/sensor-daily.json');
  assert.ok(plan.readme.content.includes(x.WASM_RUN_LABEL), 'WASM runs are history, labelled');
  assert.ok(plan.readme.content.includes('Nothing was executed on import'));
  assert.equal(x.WASM_RUN_LABEL, 'ran in Mosaic Studio (DuckDB-WASM), not re-run here');
  const record = plan.record.content;
  assert.ok(!JSON.stringify(record.exchange.notebooks).includes('"source"'), 'the record keeps no cell source; the files hold it');
  assert.deepEqual(record.exchange.extensions, studio.extensions);
  assert.equal(record.exchange.notebooks[0].cells[3].collapsed, true, 'unknown cell fields are recorded');
});

test('unknown top-level fields are recorded and exported again', () => {
  const doc = { ...clone(examples[0].doc), 'x-studio-session': { tab: 3 } };
  const { plans, exported } = roundTrip(doc);
  assert.deepEqual(x.unknownTopLevel(x.validateExchange(doc).exchange), ['x-studio-session']);
  assert.deepEqual(plans[0].record.content.exchange['x-studio-session'], { tab: 3 });
  assert.deepEqual(exported['x-studio-session'], { tab: 3 });
});

test('cycles, self-dependencies and dangling references are refused', () => {
  const base = examples.find(e => e.doc.runtime.engine === 'duckdb-wasm').doc;
  const cyclic = clone(base);
  cyclic.notebooks[0].cells.find(c => c.id === 'load').dependsOn = ['check'];
  let result = x.validateExchange(cyclic);
  assert.ok(!result.ok && result.errors.some(e => /dependency cycle: .*load/.test(e)), JSON.stringify(result));

  const self = clone(base);
  self.notebooks[0].cells[1].dependsOn = ['load'];
  result = x.validateExchange(self);
  assert.ok(!result.ok && result.errors.some(e => e.includes('depends on itself')));

  const dangling = clone(base);
  dangling.notebooks[0].cells[2].dependsOn = ['missing'];
  result = x.validateExchange(dangling);
  assert.ok(!result.ok && result.errors.some(e => e.includes('"missing"')));

  const producer = clone(base);
  producer.artifacts[0].producedBy.cell = 'nowhere';
  assert.ok(!x.validateExchange(producer).ok, 'producedBy must name a cell');

  const run = clone(base);
  run.provenance.runs[0].cell = 'nowhere';
  assert.ok(!x.validateExchange(run).ok, 'a run must name a cell');

  assert.deepEqual(x.findCycle(new Map([['a', ['b']], ['b', ['c']], ['c', ['a']]])), ['a', 'b', 'c', 'a']);
  assert.equal(x.findCycle(new Map([['a', []], ['b', ['a']], ['c', ['a', 'b']]])), undefined);
});

test('the contract is strict where it matters: format, version, engine, ids, data, size', () => {
  const base = examples[0].doc;
  const broken = [
    { ...clone(base), format: 'mosaic' },
    { ...clone(base), version: 2 },
    { ...clone(base), runtime: { engine: 'duckdb-remote', version: '1' } },
    { ...clone(base), exportedAt: 'yesterday' },
    { ...clone(base), notebooks: [] }
  ];
  const badId = clone(base);
  badId.notebooks[0].id = '../escape';
  broken.push(badId);
  const twice = clone(base);
  twice.notebooks[0].cells[1].id = twice.notebooks[0].cells[0].id;
  broken.push(twice);
  for (const doc of broken) {
    assert.ok(!x.validateExchange(doc).ok, `refused: ${JSON.stringify(doc).slice(0, 80)}`);
  }
  for (const doc of broken.slice(0, 6)) assert.ok(!schemaValid(doc), 'the schema agrees');
  const data = clone(base);
  data.artifacts.push({ id: 'rows', kind: 'table', name: 'bronze.x', data: [[1]] });
  assert.ok(!x.validateExchange(data).ok && !schemaValid(data), 'an artifact with data is refused');
  assert.ok(!x.parseExchangeText('{').ok);
  assert.ok(!x.parseExchangeText(' '.repeat(x.EXCHANGE_MAX_BYTES + 1)).ok, 'size is checked before parsing');
});

test('an import never overwrites: the second exclusive create of the same plan writes nothing', async () => {
  const workspace = path.join(dir, 'ws');
  const [plan] = x.planImport(x.validateExchange(clone(examples[0].doc)).exchange, 'notebooks', '2026-10-12T08:00:00Z');
  for (const file of plan.files) assert.equal(await createExclusiveAt(path.join(workspace, file.path), file.content), true);
  const first = path.join(workspace, plan.files[0].path);
  await writeFile(first, 'edited by the learner\n');
  for (const file of plan.files) assert.equal(await createExclusiveAt(path.join(workspace, file.path), 'replacement'), false);
  assert.equal(await readFile(first, 'utf8'), 'edited by the learner\n', 'the learner\'s edit is kept');
});

test('export from a plain folder: names and hashes, engine native, deleted cells drop their edges', () => {
  const exported = x.buildExport({
    producerVersion: '0.3.0', exportedAt: '2026-10-12T09:00:00Z', duckdbVersion: 'unknown', source: 'datapass-workbench:ws',
    notebooks: [{ id: 'mine', title: 'mine', cells: [
      { id: 'a', kind: x.cellKindOfFile('a.sql', 'select 1'), source: 'select 1', dependsOn: [] },
      { id: 'b', kind: x.cellKindOfFile('b.py', 'import polars as pl'), source: 'import polars as pl', dependsOn: ['a'] },
      { id: 'c', kind: x.cellKindOfFile('c.py', 'print(1)'), source: 'print(1)', dependsOn: [] }
    ] }],
    files: [{ id: 'dataset-orders-csv', name: 'datasets/orders.csv', sha256: 'a'.repeat(64) }]
  });
  assert.ok(x.validateExchange(exported).ok);
  assert.deepEqual(exported.notebooks[0].cells.map(c => c.kind), ['sql', 'polars', 'python']);
  assert.deepEqual(exported.artifacts, [{ id: 'dataset-orders-csv', kind: 'file', name: 'datasets/orders.csv', sha256: 'a'.repeat(64) }]);
  assert.equal(exported.runtime.engine, 'duckdb-native');

  const studio = examples.find(e => e.doc.runtime.engine === 'duckdb-wasm').doc;
  const [plan] = x.planImport(x.validateExchange(clone(studio)).exchange, 'notebooks', '2026-10-12T08:00:00Z');
  const files = new Map(plan.files.filter(f => f.cell !== 'daily').map(f => [f.path, f.content]));
  const notebook = x.notebookFromRecord(JSON.parse(JSON.stringify(plan.record.content)), files);
  assert.deepEqual(notebook.cells.find(c => c.id === 'check').dependsOn, [], 'the edge to a deleted cell is dropped');
  const again = x.buildExport({ producerVersion: '0.3.0', exportedAt: '2026-10-12T09:00:00Z', duckdbVersion: '1.4.1', source: 's', notebooks: [notebook], files: [] });
  assert.ok(x.validateExchange(again).ok, JSON.stringify(x.validateExchange(again).errors));
  assert.ok(!again.artifacts.some(a => a.producedBy?.cell === 'daily'), 'an artifact of a deleted cell is not exported');
  assert.equal(x.exchangeId('My Notebook.sql'), 'My-Notebook');
  assert.equal(x.exchangeId('...'), 'item');
});
