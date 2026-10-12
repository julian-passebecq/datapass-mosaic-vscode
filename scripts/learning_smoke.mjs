import { loadCatalogDocument } from './learning_catalog.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateCatalog, validateLinks, validateDeck, lessonProgress, levelBadges, nextUnverified, searchAll, initialState, restoreState, lessonStatus, searchLessons, parseMessage, joinDemo, windowDemo, partitionDemo, isCurrentRun, compareRuns } from '../media/learning/model.mjs';
const catalog = loadCatalogDocument(fileURLToPath(new URL('..', import.meta.url)));
const clone = () => structuredClone(catalog);

test('shipped learning catalog is valid and all linked exercises exist', () => {
  assert.equal(validateCatalog(catalog), catalog);
  assert.equal(catalog.paths.length, 13); assert.equal(catalog.lessons.length, 59);
  const content = process.env.MOSAIC_CONTENT_ROOT || path.resolve('content');
  const known = new Set();
  for (const pack of readdirSync(path.join(content, 'exercise-packs'))) {
    const file = path.join(content, 'exercise-packs', pack, 'exercises.json');
    if (existsSync(file)) for (const exercise of JSON.parse(readFileSync(file, 'utf8'))) known.add(`${exercise.id}/${exercise.language}`);
  }
  for (const lesson of catalog.lessons) for (const ref of [lesson.exercise, ...(lesson.checks ?? []), ...(lesson.practice ?? [])].filter(Boolean)) assert.ok(known.has(`${ref.id}/${ref.language}`), `${lesson.id}: ${ref.id}`);
  // Missions, cheatsheets and decks: the shipped files only.
  const missions = new Set(readdirSync(path.join(content, 'missions')).flatMap(pack => JSON.parse(readFileSync(path.join(content, 'missions', pack, 'pack.json'), 'utf8')).missions.map(id => `${pack}/${id}`)));
  const cheatsheets = new Set(readdirSync(path.join(content, 'reference')).filter(n => n.endsWith('.md')).map(n => n.slice(0, -3)));
  const decks = readdirSync(path.join(content, 'learning', 'flashcards')).map(n => validateDeck(JSON.parse(readFileSync(path.join(content, 'learning', 'flashcards', n), 'utf8')), n.replace(/\.json$/, ''), catalog));
  assert.equal(validateLinks(catalog, { exercises: known, missions, cheatsheets, decks: new Set(decks.map(d => d.id)) }), catalog);
  assert.ok(decks.reduce((n, d) => n + d.cards.length, 0) >= 200);
  for (const id of ['sql', 'python', 'polars', 'git', 'de-foundations', 'warehouse', 'lakehouse']) assert.ok(decks.some(d => d.id === id), id);
  for (const id of ['sql', 'python', 'polars', 'git', 'dimensional-modeling', 'dbt', 'lakehouse']) assert.ok(cheatsheets.has(`learning-${id}`), id);
});
test('new lesson fields are optional and strictly validated; a bad reference is rejected', () => {
  // Lessons that have an exercise stay valid without any of the new fields (lessons without one need checks, practice or missions).
  const old = clone(); for (const l of old.lessons) if (l.exercise) for (const f of ['checks', 'practice', 'missions', 'cheatsheet', 'deck']) delete l[f];
  assert.doesNotThrow(() => validateCatalog(old), 'lessons without the new fields stay valid');
  const withExercise = i => clone().lessons.findIndex(l => l.exercise && l.exercise.language !== 'quiz') === i;
  const index = clone().lessons.findIndex(l => l.exercise && l.exercise.language !== 'quiz'); assert.ok(withExercise(index));
  const bad = [
    [l => { l.checks = Array.from({ length: 9 }, (_, i) => ({ id: `c${i}`, language: 'quiz' })); }, /invalid list/],
    [l => { l.checks = []; }, /empty list/],
    [l => { l.checks = [{ id: 'c', language: 'quiz', path: '/etc' }]; }, /unknown field/],
    [l => { l.practice = [{ id: '../x', language: 'sql' }]; }, /invalid exercise id/],
    [l => { l.practice = [{ id: 'x', language: 'SQL;' }]; }, /invalid exercise language/],
    [l => { l.practice = [{ id: 'quiz-item', language: 'quiz' }]; }, /concept checks belong in checks/],
    [l => { l.practice = [structuredClone(l.exercise)]; }, /duplicate exercise/],
    [l => { l.missions = [{ pack: 'terminal-v1', id: 'Bad Id' }]; }, /invalid mission/],
    [l => { l.missions = Array.from({ length: 7 }, (_, i) => ({ pack: 'p', id: `m${i}` })); }, /invalid list/],
    [l => { l.cheatsheet = '../../package.json'; }, /invalid cheatsheet/],
    [l => { l.cheatsheet = 'reference/learning-sql.md'; }, /invalid cheatsheet/],
    [l => { l.deck = 'sql.json'; }, /invalid deck/],
    [l => { delete l.exercise; delete l.practice; delete l.missions; delete l.checks; }, /needs checks, practice or missions/]
  ];
  for (const [change, pattern] of bad) { const c = clone(); change(c.lessons[index]); assert.throws(() => validateCatalog(c), pattern, String(change)); }
  const links = { exercises: new Set(), missions: new Set(['terminal-v1/first-repository']), cheatsheets: new Set(['learning-sql']), decks: new Set(['sql']) };
  let c = clone(); c.lessons[index].cheatsheet = 'learning-nope'; assert.throws(() => validateLinks(c, { cheatsheets: links.cheatsheets }), /unknown cheatsheet/);
  c = clone(); c.lessons[index].missions = [{ pack: 'terminal-v1', id: 'nope' }]; assert.throws(() => validateLinks(c, { missions: links.missions }), /unknown mission/);
  c = clone(); c.lessons[index].deck = 'nope'; assert.throws(() => validateLinks(c, { decks: links.decks }), /unknown flashcard deck/);
  assert.throws(() => validateLinks(clone(), { exercises: links.exercises }), /not installed/);
});
test('four progress levels stay separate: read, checks, ran locally, verified', () => {
  const lesson = structuredClone(catalog.lessons.find(l => l.exercise && l.exercise.language !== 'quiz' && l.practice?.length));
  lesson.checks = [{ id: 'concept-x', language: 'quiz' }];
  const resolve = ref => ({ key: `p/${ref.id}/${ref.language}`, version: '2' });
  const key = ref => resolve(ref).key;
  const state = initialState(catalog);
  let p = lessonProgress(lesson, state, resolve, {});
  assert.deepEqual([p.read, p.checks[0].status, p.executed, p.verified], [false, 'unanswered', undefined, false]);
  state.read[lesson.id] = { version: lesson.version, at: '2026-10-12T08:00:00Z' };
  state.executed[lesson.id] = { version: lesson.version, at: '2026-10-12T08:00:00Z', sourceHash: 'a'.repeat(64), language: 'sql' };
  const practice = { exercises: { [key(lesson.checks[0])]: { attempts: 1, solved: { version: '2', at: 'x' }, last: { mode: 'submit', status: 'passed', version: '2', at: 'x' } } } };
  p = lessonProgress(lesson, state, resolve, practice);
  assert.deepEqual([p.read, p.checks[0].status, Boolean(p.executed), p.verified], [true, 'passed', true, false], 'read + quiz + run never verify');
  assert.deepEqual(levelBadges(lesson, p).map(b => b.level), ['read', 'quiz', 'executed']);
  practice.exercises[key(lesson.checks[0])] = { attempts: 2, last: { mode: 'submit', status: 'failed', version: '2', at: 'y' } };
  assert.equal(lessonProgress(lesson, state, resolve, practice).checks[0].status, 'failed');
  practice.exercises[key(lesson.exercise)] = { attempts: 1, last: { mode: 'run', status: 'passed', version: '2', at: 'z' } };
  assert.equal(lessonProgress(lesson, state, resolve, practice).verified, false, 'Run visible never verifies');
  practice.exercises[key(lesson.exercise)] = { attempts: 2, solved: { version: '1', at: 'z' } };
  assert.equal(lessonProgress(lesson, state, resolve, practice).verified, false, 'a pass on an older version does not count');
  practice.exercises[key(lesson.exercise)] = { attempts: 3, solved: { version: '2', at: 'z' } };
  p = lessonProgress(lesson, state, resolve, practice);
  assert.equal(p.verified, true); assert.deepEqual(levelBadges(lesson, p).map(b => b.level), ['read', 'quiz', 'executed', 'verified']);
  state.executed[lesson.id].version = lesson.version + 1;
  assert.equal(lessonProgress(lesson, state, resolve, practice).executed, undefined, 'a run of another lesson version is not current');
  // An older lesson that links a concept check as its exercise: shown as a check, never as verified.
  const legacy = catalog.lessons.find(l => l.exercise?.language === 'quiz');
  const solvedQuiz = { exercises: { [key(legacy.exercise)]: { attempts: 1, solved: { version: '2', at: 'x' } } } };
  p = lessonProgress(legacy, initialState(catalog), resolve, solvedQuiz);
  assert.equal(p.verified, false); assert.equal(p.checks[0].source, 'exercise'); assert.equal(p.checks[0].status, 'passed');
});
test('next unverified item follows the current path and skips verified work', () => {
  const resolve = ref => ({ key: `p/${ref.id}/${ref.language}`, version: '1' });
  const state = initialState(catalog);
  const first = nextUnverified(catalog, state, resolve, {});
  assert.equal(first.lesson, catalog.paths[0].lessons[0]); assert.equal(first.kind, 'exercise');
  const solved = { exercises: { [resolve(catalog.lessons[0].exercise).key]: { solved: { version: '1' } } } };
  assert.notEqual(nextUnverified(catalog, state, resolve, solved).lesson, catalog.lessons[0].id);
});
test('restored state keeps valid run records and self-rated flashcards, and drops the rest', () => {
  const s = initialState(catalog); const lesson = catalog.lessons[0];
  s.executed[lesson.id] = { version: lesson.version, at: '2026-10-12T08:00:00Z', sourceHash: 'b'.repeat(64), language: 'sql' };
  s.flashcards['sql/inner-join-rows'] = { attempts: 2, review: { box: 2, due: '2026-10-15' }, last: { at: '2026-10-12T08:00:00Z', rating: 'knew' } };
  const parseReview = r => r && Number.isInteger(r.box) && r.box >= 1 && r.box <= 6 && /^\d{4}-\d{2}-\d{2}$/.test(r.due) ? { box: r.box, due: r.due } : undefined;
  assert.deepEqual(restoreState(catalog, s, { parseReview }), s);
  const bad = structuredClone(s);
  bad.executed[lesson.id].sourceHash = 'not-a-hash'; bad.flashcards['sql/inner-join-rows'].review.box = 99; bad.flashcards['../x'] = { attempts: 1 };
  bad.flashcards['sql/gone'] = { attempts: 1 };
  const restored = restoreState(catalog, bad, { parseReview, decks: [{ id: 'sql', cards: [{ id: 'inner-join-rows' }] }] });
  assert.deepEqual(restored.executed, {}); assert.deepEqual(Object.keys(restored.flashcards), ['sql/inner-join-rows']);
  assert.equal(restored.flashcards['sql/inner-join-rows'].review, undefined);
});
test('search covers lessons, cheatsheet titles and flashcard fronts', () => {
  const hits = searchAll(catalog, 'rebase', { cheatsheets: [{ id: 'learning-git', title: 'Git and shell cheatsheet' }], cards: [{ deck: 'git', id: 'rebase', front: 'What does git rebase main do?' }] });
  assert.ok(hits.lessons.some(l => l.id === 'git-merge-rebase')); assert.equal(hits.cards.length, 1);
  assert.equal(searchAll(catalog, 'cheatsheet', { cheatsheets: [{ id: 'learning-git', title: 'Git and shell cheatsheet' }] }).cheatsheets.length, 1);
  assert.deepEqual(searchAll(catalog, '', { cards: [{ deck: 'git', id: 'x', front: 'x' }] }).cards, []);
});
test('new webview messages are bounded to shipped decks, cheatsheets and lesson links', () => {
  const lesson = catalog.lessons.find(l => l.practice?.length && l.cheatsheet && l.deck);
  const extras = { decks: [{ id: 'sql', cards: [{ id: 'inner-join-rows' }] }], cheatsheets: ['learning-sql'] };
  for (const raw of [{ type: 'rate', deck: 'sql', card: 'inner-join-rows', rating: 'perfect' }, { type: 'rate', deck: 'other', card: 'inner-join-rows', rating: 'knew' },
    { type: 'review', deck: '../x' }, { type: 'openCheatsheet', id: 'learning-nope' }, { type: 'openCheatsheet', id: 'learning-sql', path: 'x' },
    { type: 'openPracticeItem', lesson: lesson.id, index: lesson.practice.length }, { type: 'openMission', lesson: lesson.id, index: 0, extra: 1 }]) {
    assert.equal(parseMessage(raw, catalog, extras), undefined, JSON.stringify(raw));
  }
  assert.ok(parseMessage({ type: 'rate', deck: 'sql', card: 'inner-join-rows', rating: 'missed' }, catalog, extras));
  assert.ok(parseMessage({ type: 'review' }, catalog, extras)); assert.ok(parseMessage({ type: 'reviewClose' }, catalog, extras));
  assert.ok(parseMessage({ type: 'openCheatsheet', id: 'learning-sql' }, catalog, extras));
  assert.ok(parseMessage({ type: 'cheatsheet', lesson: lesson.id }, catalog, extras));
  assert.ok(parseMessage({ type: 'openPracticeItem', lesson: lesson.id, index: 0 }, catalog, extras));
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
