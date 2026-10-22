// Mosaic Studio's .ipynb interchange (src/platform/studioNotebook.ts): the committed Studio fixtures
// (content/interop/examples/studio, written by Studio's own export_notebook) import into native files and export back
// to the same cells; cycles and dangling references are refused; an import never overwrites; nothing is executed;
// unknown metadata is kept. The round trip against Studio's real Python code is scripts/interop/studio_roundtrip.py.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';

const root = fileURLToPath(new URL('../..', import.meta.url));
const dir = await mkdtemp(path.join(tmpdir(), 'datapass-studio-nb-'));
after(() => rm(dir, { recursive: true, force: true }));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [path.join(root, entry)], bundle: true, platform: 'node', format: 'esm', target: 'node20', outfile, logLevel: 'silent' });
  return import(pathToFileURL(outfile).href);
}

const s = await bundle('src/platform/studioNotebook.ts', 'studio.mjs');
const { createExclusiveAt } = await bundle('src/build/exclusiveFile.ts', 'exclusive.mjs');
const fixtureDir = path.join(root, 'content/interop/examples/studio');
const fixtures = await Promise.all((await readdir(fixtureDir)).filter(n => n.endsWith('.ipynb')).sort()
  .map(async name => ({ name, text: await readFile(path.join(fixtureDir, name), 'utf8') })));
const allKinds = () => JSON.parse(fixtures.find(f => f.name === 'studio-all-kinds.ipynb').text);

test('fallback notebook ids stay unique beside existing and inert cell ids', () => {
  const base = { kind: 'sql', title: 'SQL', content: 'select 1', dependsOn: [] };
  const built = s.buildStudioNotebook([
    { ...base, id: 'cell-2' },
    { ...base, id: 'a'.repeat(80) },
    { ...base, id: 'cell-4', kind: 'inert', content: JSON.stringify({ cell_type: 'raw', id: 'cell-4', metadata: {}, source: [] }) },
    { ...base, id: 'b'.repeat(80) }
  ], '2026-10-22T12:00:00Z');
  assert.ok(built.ok, JSON.stringify(built.errors));
  const ids = built.notebook.cells.map(cell => cell.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.every(id => /^[A-Za-z0-9_-]{1,64}$/.test(id)));
  assert.equal(ids[0], 'cell-2');
  assert.equal(ids[2], 'cell-4');
});

function parse(doc, name = 'test.ipynb') {
  return s.parseStudioNotebook(typeof doc === 'string' ? doc : JSON.stringify(doc), name);
}

/** Import into a virtual workspace, then export from the record with the files as written. */
function roundTrip(text, name, edit = files => files) {
  const parsed = parse(text, name);
  assert.ok(parsed.ok, `${name}: ${JSON.stringify(parsed.errors)}`);
  const plan = s.planStudioImport(parsed.notebook, 'notebooks', '2026-10-13T08:00:00Z', name);
  const record = JSON.parse(JSON.stringify(plan.record.content));
  const files = edit(new Map(plan.files.map(f => [f.path, f.content])));
  const built = s.buildStudioNotebook(s.studioCellsFromRecord(record, files), '2026-10-13T09:00:00Z', record.metadata);
  assert.ok(built.ok, `${name} export: ${JSON.stringify(built.errors)}`);
  return { parsed, plan, built, again: parse(built.text, name) };
}

const facts = cells => cells.map(c => ({ id: c.id, kind: c.kind, title: c.title, content: c.kind === 'inert' ? JSON.parse(c.content).source : c.content, dependsOn: c.dependsOn,
  chart: c.metadata?.datapass?.chart, outputTable: c.metadata?.datapass?.outputTable }));

test('the committed Studio fixtures exist and every one is nbformat 4 written by Studio', () => {
  assert.deepEqual(fixtures.map(f => f.name), ['studio-all-kinds.ipynb', 'studio-e2e01-export.ipynb', 'studio-wind-reference.ipynb']);
  for (const { name, text } of fixtures) {
    const doc = JSON.parse(text);
    assert.equal(doc.nbformat, 4, name);
    assert.equal(doc.metadata.datapass.format, 'datapass.notebook', `${name}: Studio's metadata.datapass`);
    for (const cell of doc.cells) if (cell.cell_type === 'code') assert.deepEqual(cell.outputs, [], `${name}: no outputs`);
  }
  assert.match(readFileSync(path.join(fixtureDir, 'README.md'), 'utf8'), /Studio commit: [0-9a-f]{40}/);
});

test('Studio fixtures round trip: ids, kinds, titles, sources, charts, output tables and dependsOn come back', () => {
  for (const { name, text } of fixtures) {
    const { parsed, again, built } = roundTrip(text, name);
    assert.ok(again.ok, `${name}: ${JSON.stringify(again.errors)}`);
    assert.deepEqual(facts(again.notebook.cells), facts(parsed.notebook.cells), name);
    const doc = JSON.parse(built.text);
    assert.equal(doc.nbformat, 4);
    assert.equal(doc.nbformat_minor, 5);
    assert.deepEqual(Object.keys(doc.metadata.datapass).sort(), ['exportedAt', 'format', 'version'], 'Studio\'s notebook metadata.datapass shape');
    for (const cell of doc.cells) {
      if (cell.cell_type === 'code') {
        assert.deepEqual(cell.outputs, [], 'source only: no outputs');
        assert.equal(cell.execution_count, null, 'no execution count');
      }
    }
  }
});

test('all kinds map to native files as Studio defines them', () => {
  const parsed = parse(allKinds(), 'studio-all-kinds.ipynb');
  assert.ok(parsed.ok, JSON.stringify(parsed.errors));
  const plan = s.planStudioImport(parsed.notebook, 'notebooks', '2026-10-13T08:00:00Z', 'studio-all-kinds.ipynb');
  assert.equal(plan.folder, 'notebooks/imported/studio-all-kinds');
  assert.equal(plan.record.path, '.datapass/interop/studio-all-kinds.json');
  assert.deepEqual(plan.files.map(f => f.path.split('/').pop()), [
    '01-intro.md', '02-make-readings.py', '03-daily.sql', '04-ramp-model.model.json', '05-joined.sql', '06-raw-notes.inert.json']);
  const byId = Object.fromEntries(parsed.notebook.cells.map(c => [c.id, c]));
  assert.ok(!byId.daily.content.startsWith('%%sql'), 'the SQL file holds the SQL, not the magic line');
  assert.deepEqual(byId.daily.dependsOn, ['make-readings']);
  assert.deepEqual(byId.joined.dependsOn, ['daily', 'ramp-model']);
  assert.deepEqual(JSON.parse(byId['ramp-model'].content), { model: 'synthetic_ramp', inputs: { slope: 0.5, steps: 12 }, outputTable: 'ramp' });
  assert.equal(JSON.parse(byId['raw-notes'].content).cell_type, 'raw');
  assert.ok(plan.readme.content.includes('Nothing was executed on import'));
  assert.ok(plan.readme.content.includes('never share a database file'));
  assert.ok(!JSON.stringify(plan.record.content).includes('avg(value)'), 'the record keeps no source; the files hold it');
});

test('cycles, self-dependencies, dangling and non-runnable references are refused, nothing planned', () => {
  const cyclic = allKinds();
  cyclic.cells.find(c => c.id === 'make-readings').metadata.datapass.dependsOn = ['joined'];
  let result = parse(cyclic);
  assert.ok(!result.ok && result.errors.some(e => /cycle: .*make-readings/.test(e)), JSON.stringify(result));

  const self = allKinds();
  self.cells.find(c => c.id === 'daily').metadata.datapass.dependsOn = ['daily'];
  result = parse(self);
  assert.ok(!result.ok && result.errors.some(e => e.includes('depends on itself')));

  const dangling = allKinds();
  dangling.cells.find(c => c.id === 'daily').metadata.datapass.dependsOn = ['missing'];
  result = parse(dangling);
  assert.ok(!result.ok && result.errors.some(e => e.includes('"missing"')));

  const note = allKinds();
  note.cells.find(c => c.id === 'daily').metadata.datapass.dependsOn = ['intro'];
  result = parse(note);
  assert.ok(!result.ok && result.errors.some(e => e.includes('not runnable')));

  const export_ = s.buildStudioNotebook([
    { id: 'a', kind: 'sql', title: 'a', content: 'select 1', dependsOn: ['b'] },
    { id: 'b', kind: 'sql', title: 'b', content: 'select 2', dependsOn: ['a'] }
  ], '2026-10-13T09:00:00Z');
  assert.ok(!export_.ok && export_.errors.some(e => e.includes('cycle')), 'export refuses a cycle too');
});

test('the reader is strict where it matters: nbformat 4, size, cell count, ids', () => {
  assert.ok(!parse('{').ok);
  assert.ok(!parse({ ...allKinds(), nbformat: 3 }).ok, 'nbformat 3 is refused');
  assert.ok(!parse(' '.repeat(s.STUDIO_MAX_BYTES + 1)).ok, 'size before parsing');
  const many = allKinds();
  many.cells = Array.from({ length: 51 }, (_, i) => ({ cell_type: 'markdown', id: `m${i}`, metadata: {}, source: 'x' }));
  assert.ok(!parse(many).ok, 'at most 50 cells (Studio\'s limit)');
  const unsafe = allKinds();
  unsafe.cells[1].metadata.datapass.cellId = '../escape';
  assert.ok(!parse(unsafe).ok, 'an unsafe cell id is refused');
  const twice = allKinds();
  twice.cells[2].metadata.datapass.cellId = 'make-readings';
  assert.ok(!parse(twice).ok, 'a duplicate cell id is refused');
  const badNbId = allKinds();
  badNbId.cells[0].id = 'a/b';
  assert.ok(!parse(badNbId).ok, 'an nbformat id outside its pattern is refused');
  // A plain Jupyter notebook (4.4, no ids): ids are made like Studio makes them.
  const plain = parse({ nbformat: 4, nbformat_minor: 4, metadata: {}, cells: [
    { cell_type: 'markdown', metadata: {}, source: ['# Plain\n', 'text'] },
    { cell_type: 'code', metadata: {}, execution_count: 7, outputs: [{ output_type: 'stream', name: 'stdout', text: 'secret output\n' }], source: 'x = 1' },
    { cell_type: 'code', id: '1abc', metadata: {}, execution_count: null, outputs: [], source: '%%sql\nselect 1' }
  ] }, 'plain.ipynb');
  assert.ok(plain.ok, JSON.stringify(plain.errors));
  assert.deepEqual(plain.notebook.cells.map(c => [c.id, c.kind]), [['note-1', 'note'], ['jupyter-2', 'jupyter'], ['c-1abc', 'sql']]);
  assert.equal(plain.notebook.title, 'Plain');
  const plan = s.planStudioImport(plain.notebook, 'notebooks', '2026-10-13T08:00:00Z', 'plain.ipynb');
  assert.ok(!JSON.stringify(plan).includes('secret output'), 'outputs are not imported');
  assert.ok(plan.readme.content.includes('1 output not imported'));
  assert.ok(plan.readme.content.includes(s.STUDIO_RUN_LABEL), 'what Studio ran is labelled as history');
  // Another kernel language: code is kept inert, never mapped to Python.
  const r = parse({ nbformat: 4, nbformat_minor: 5, metadata: { kernelspec: { name: 'ir', language: 'R', display_name: 'R' } },
    cells: [{ cell_type: 'code', id: 'r1', metadata: {}, execution_count: null, outputs: [], source: 'print(1)' }] });
  assert.ok(r.ok && r.notebook.cells[0].kind === 'inert');
});

test('unknown metadata is kept: notebook keys, cell keys and unknown metadata.datapass fields go back out', () => {
  const doc = allKinds();
  doc.metadata['x-studio-session'] = { tab: 3 };
  doc.cells[1].metadata.tags = ['keep-me'];
  doc.cells[2].metadata.datapass.resultSha256 = 'a'.repeat(64);
  doc.cells[2].metadata.datapass['x-future'] = { level: 2 };
  const { plan, built } = roundTrip(JSON.stringify(doc), 'meta.ipynb');
  assert.deepEqual(plan.record.content.metadata['x-studio-session'], { tab: 3 });
  const out = JSON.parse(built.text);
  assert.deepEqual(out.metadata['x-studio-session'], { tab: 3 });
  assert.deepEqual(out.cells[1].metadata.tags, ['keep-me']);
  assert.equal(out.cells[2].metadata.datapass.resultSha256, 'a'.repeat(64));
  assert.deepEqual(out.cells[2].metadata.datapass['x-future'], { level: 2 });
  assert.ok(plan.readme.content.includes('result hash aaaaaaaaaaaa'), 'a Studio result hash is shown as history');
});

test('a learner edit and a deleted cell file: the edit is exported, edges to the deleted cell are dropped', () => {
  const { again } = roundTrip(fixtures.find(f => f.name === 'studio-all-kinds.ipynb').text, 'edit.ipynb', files => {
    for (const key of [...files.keys()]) {
      if (key.endsWith('-daily.sql')) files.set(key, 'SELECT 42 AS answer\n');
      if (key.endsWith('-ramp-model.model.json')) files.delete(key);
    }
    return files;
  });
  assert.ok(again.ok, JSON.stringify(again.errors));
  const cells = Object.fromEntries(again.notebook.cells.map(c => [c.id, c]));
  assert.equal(cells.daily.content, 'SELECT 42 AS answer\n');
  assert.equal(cells['ramp-model'], undefined);
  assert.deepEqual(cells.joined.dependsOn, ['daily']);
});

test('export from a plain folder: Studio-safe ids, %%sql, metadata.datapass kinds', () => {
  const cells = s.studioCellsFromPlain([
    { name: '01-intro.md', kind: s.studioKindOfFile('01-intro.md'), content: '# Intro\n' },
    { name: '02-orders.sql', kind: s.studioKindOfFile('02-orders.sql'), content: 'select 1\n' },
    { name: 'Clean.py', kind: s.studioKindOfFile('Clean.py'), content: 'x = 1\n' }
  ]);
  assert.deepEqual(cells.map(c => c.id), ['note-01-intro', 'sql-02-orders', 'jupyter-Clean']);
  const built = s.buildStudioNotebook(cells, '2026-10-13T09:00:00Z');
  assert.ok(built.ok, JSON.stringify(built.errors));
  const doc = JSON.parse(built.text);
  assert.equal(doc.cells[1].source.join(''), '%%sql\nselect 1\n');
  assert.deepEqual(doc.cells.map(c => c.metadata.datapass.kind), [undefined, 'sql', 'python']);
  assert.equal(s.studioKindOfFile('README.txt'), undefined);
  assert.equal(s.studioKindOfExchange('polars'), 'jupyter');
});

test('an import never overwrites: the second exclusive create writes nothing and keeps the learner\'s edit', async () => {
  const workspace = path.join(dir, 'ws');
  const parsed = parse(allKinds(), 'studio-all-kinds.ipynb');
  const plan = s.planStudioImport(parsed.notebook, 'notebooks', '2026-10-13T08:00:00Z', 'studio-all-kinds.ipynb');
  for (const file of plan.files) assert.equal(await createExclusiveAt(path.join(workspace, file.path), file.content), true);
  const first = path.join(workspace, plan.files[1].path);
  await writeFile(first, 'edited by the learner\n');
  for (const file of plan.files) assert.equal(await createExclusiveAt(path.join(workspace, file.path), 'replacement'), false);
  assert.equal(await readFile(first, 'utf8'), 'edited by the learner\n');
});

test('never executes: the module runs nothing and an import that would write a marker writes none', async () => {
  const source = await readFile(path.join(root, 'src/platform/studioNotebook.ts'), 'utf8');
  for (const forbidden of ['child_process', 'eval(', 'new Function', 'node:fs', 'vscode']) assert.ok(!source.includes(forbidden), forbidden);
  const marker = path.join(dir, 'executed.marker').replace(/\\/g, '/');
  const doc = allKinds();
  doc.cells[1].source = [`open(${JSON.stringify(marker)}, "w").write("ran")\n`];
  const parsed = parse(doc);
  assert.ok(parsed.ok);
  s.planStudioImport(parsed.notebook, 'notebooks', '2026-10-13T08:00:00Z', 'x.ipynb');
  assert.ok(!existsSync(marker), 'no cell ran');
});
