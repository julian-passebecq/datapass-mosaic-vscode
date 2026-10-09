import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import { validateCatalog, initialState, restoreState, lessonStatus, searchLessons, parseMessage, joinDemo, windowDemo, partitionDemo, isCurrentRun, compareRuns } from '../media/learning/model.mjs';
const catalog = JSON.parse(readFileSync(new URL('../content/learning/catalog.json', import.meta.url), 'utf8'));
const clone = () => structuredClone(catalog);

test('shipped learning catalog is valid and all linked exercises exist', () => {
  assert.equal(validateCatalog(catalog), catalog);
  assert.equal(catalog.paths.length, 6); assert.equal(catalog.lessons.length, 19);
  const content = process.env.MOSAIC_CONTENT_ROOT || path.resolve('content');
  const known = new Set();
  for (const pack of readdirSync(path.join(content, 'exercise-packs'))) {
    const file = path.join(content, 'exercise-packs', pack, 'exercises.json');
    if (existsSync(file)) for (const exercise of JSON.parse(readFileSync(file, 'utf8'))) known.add(`${exercise.id}/${exercise.language}`);
  }
  for (const lesson of catalog.lessons) assert.ok(known.has(`${lesson.exercise.id}/${lesson.exercise.language}`), lesson.id);
});
test('paths reject unknown references, unreachable lessons and duplicate identifiers', () => {
  let c = clone(); c.paths[0].lessons.push('not-installed'); assert.throws(() => validateCatalog(c), /unknown lesson/);
  c = clone(); c.lessons.push(structuredClone(c.lessons[0])); assert.throws(() => validateCatalog(c), /duplicate/);
  c = clone(); c.paths[0].lessons = []; assert.throws(() => validateCatalog(c), /empty/);
  c = clone(); c.lessons[0].id = '../escape'; assert.throws(() => validateCatalog(c), /invalid/);
});
test('prerequisites reject cycles and unknown lessons', () => {
  let c = clone(); c.lessons[0].prerequisites = [c.lessons[1].id]; c.lessons[1].prerequisites = [c.lessons[0].id]; assert.throws(() => validateCatalog(c), /cycle/);
  c = clone(); c.lessons[0].related = ['unknown']; assert.throws(() => validateCatalog(c), /unknown related/);
});
test('strict documents reject executable fields, bad bounds and source ranges', () => {
  let c = clone(); c.lessons[0].command = 'rm'; assert.throws(() => validateCatalog(c), /unknown field/);
  c = clone(); c.lessons[0].code.source = 'x'.repeat(64001); assert.throws(() => validateCatalog(c), /invalid code/);
  c = clone(); c.lessons[0].visual.steps[0].lines = [1, 999999]; assert.throws(() => validateCatalog(c), /code range/);
  c = clone(); c.lessons[0].visual.nodes = [{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }]; c.lessons[0].visual.edges = [['a', 'b'], ['b', 'a']]; assert.throws(() => validateCatalog(c), /cycle/);
});
test('all destinations and source snippets are inert bounded data', () => {
  for (const lesson of catalog.lessons) {
    assert.ok(!('callback' in lesson)); assert.ok(lesson.blocks.length > 1);
    assert.ok(lesson.visual.steps.length > 1); assert.ok(lesson.minutes > 0);
  }
});
test('initial and restored learning state preserves only supported values', () => {
  const s = initialState(catalog); s.read[catalog.lessons[0].id] = { version: 1, at: '2026-10-02T12:00:00Z' }; s.notes[s.lesson] = 'Remember nulls'; s.mode = 'exercise';
  assert.deepEqual(restoreState(catalog, s), s);
  const bad = { ...s, mode: 'eval', path: 'missing', railHidden: 'yes', notes: { [s.lesson]: 'x'.repeat(8001) }, read: { [s.lesson]: { version: 0, at: s.read[s.lesson].at } } };
  const restored = restoreState(catalog, bad); assert.equal(restored.mode, 'read'); assert.equal(restored.railHidden, false); assert.deepEqual(restored.read, {}); assert.deepEqual(restored.notes, {});
});
test('read acknowledgements never create grading or mastery', () => {
  const lesson = catalog.lessons[0], state = initialState(catalog), e = { key: 'p/e/sql', version: '1' };
  assert.equal(lessonStatus(lesson, state, e, {}), 'new');
  assert.equal(lessonStatus(lesson, state, undefined, {}), 'new');
  state.read[lesson.id] = { version: lesson.version, at: '2026-10-02T12:00:00Z' };
  assert.equal(lessonStatus(lesson, state, e, { exercises: { [e.key]: { attempts: 1, last: { mode: 'run', status: 'passed' } } } }), 'read');
  assert.equal(lessonStatus(lesson, state, e, { exercises: { [e.key]: { solved: { version: '0' } } } }), 'read');
  assert.equal(lessonStatus(lesson, state, undefined, {}), 'read');
  assert.equal(lessonStatus(lesson, state, e, { exercises: { [e.key]: { solved: { version: '1' } } } }), 'practiced');
});
test('messages reject unknown fields, injected targets and prototype names without throwing', () => {
  const lesson = catalog.lessons[0].id;
  for (const raw of [null, [], { type: 'eval', code: '1' }, { type: '__proto__' }, { type: 'constructor' }, { type: 'run', lesson, code: 'DROP TABLE t' }, { type: 'run', lesson: '../../a' }, { type: 'mode', lesson, mode: 'shell' }, { type: 'grade', lesson, mode: 'pass' }, { type: 'select', path: 'unknown', lesson }, { type: 'note', lesson, text: 'x'.repeat(8001) }, { type: 'focusStep', lesson, index: -1 }]) assert.equal(parseMessage(raw, catalog), undefined, JSON.stringify(raw).slice(0, 80));
  assert.deepEqual(parseMessage({ type: 'run', lesson }, catalog), { type: 'run', lesson });
  assert.deepEqual(parseMessage({ type: 'openRuntime' }, catalog), { type: 'openRuntime' });
  assert.equal(parseMessage({ type: 'rail', hidden: true }, catalog).hidden, true);
});
test('left join preserves unmatched rows and duplicate matches', () => {
  const data = joinDemo('left'); assert.equal(data.rows.length, 5);
  assert.equal(data.rows.filter(r => r.name === 'Ada').length, 2);
  assert.equal(data.rows.find(r => r.name === 'Unknown').order, null);
  assert.equal(joinDemo('inner').rows.length, 2); assert.equal(joinDemo('full').rows.length, 7);
});
test('ON and WHERE filters have different outer join semantics', () => {
  assert.equal(joinDemo('left', 'on').rows.length, 4);
  assert.equal(joinDemo('left', 'where').rows.length, 1);
  assert.equal(joinDemo('full', 'on').rows.length, 7);
  assert.equal(joinDemo('semi').rows.length, 1); assert.equal(joinDemo('anti').rows.length, 3);
  assert.throws(() => joinDemo('anti', 'where'), /not projected/);
});
test('join lineage indices refer to visible input rows only', () => {
  for (const kind of ['inner', 'left', 'full', 'semi', 'anti']) for (const filter of ['none', 'on']) {
    const { left, right, rows } = joinDemo(kind, filter);
    for (const row of rows) { assert.ok(row.left === null || row.left < left.length); assert.ok(row.right === null || row.right < right.length); }
  }
});
test('RANGE includes peers while ROWS has a deterministic tie-breaker', () => {
  assert.equal(windowDemo('rows', 1).sum, 70); assert.equal(windowDemo('range', 1).sum, 120);
  assert.equal(windowDemo('range', 1).sum, windowDemo('range', 2).sum);
  assert.equal(windowDemo('rows', 3).sum, 140); assert.throws(() => windowDemo('range', 4));
});
test('partition illustrations conserve row identity and respect coalesce bounds', () => {
  for (const op of ['repartition', 'coalesce', 'broadcast']) for (let n = 1; n <= 8; n++) {
    const demo = partitionDemo(op, n);
    assert.deepEqual(demo.targets.flat().map(r => r.id).sort((a,b) => a-b), demo.source.flat().map(r => r.id).sort((a,b) => a-b));
    assert.equal(demo.targets.length, op === 'coalesce' ? Math.min(n, 4) : op === 'broadcast' ? 4 : n);
  }
  assert.match(partitionDemo('broadcast').exchange, /replication/);
});
test('recorded runs cannot be silently relabelled or compared across contexts', () => {
  const a = { id: 'a', lesson: 'sql-joins', language: 'sql', scope: 'file', sourceHash: 'first' }, b = { ...a, id: 'b', sourceHash: 'second' };
  assert.equal(isCurrentRun(a, a.lesson, 'first'), true); assert.equal(isCurrentRun(a, a.lesson, 'second'), false);
  assert.equal(isCurrentRun(a, 'other', 'first'), false); assert.equal(compareRuns(a, b).compatible, true);
  assert.equal(compareRuns(a, { ...b, scope: 'selection' }).compatible, false);
  assert.equal(compareRuns(a, { ...b, lesson: 'different' }).compatible, false);
  assert.equal(compareRuns(undefined, b).compatible, false);
});
test('lesson discovery searches semantic concepts rather than only lab names', () => {
  assert.ok(searchLessons(catalog, 'broadcast').some(l => l.id === 'spark-broadcast'));
  assert.ok(searchLessons(catalog, 'grain').some(l => l.id === 'warehouse-grain'));
  assert.equal(searchLessons(catalog, 'zz-no-match').length, 0);
});
test('renderer has no raw HTML, code evaluation or network execution bridge', () => {
  const js = readFileSync(new URL('../media/learning/view.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(js, /innerHTML\s*=|outerHTML\s*=|\beval\s*\(|new Function|\bfetch\s*\(|XMLHttpRequest|WebSocket/);
  assert.match(js, /Teaching illustration - not execution evidence/);
  assert.match(js, /SIMULATED DISTRIBUTED BEHAVIOR/);
});
