/** Inert learning documents and deterministic teaching diagrams. No code evaluation or network access. */
export const MODES = Object.freeze(['read', 'watch', 'try', 'exercise', 'inspect', 'compare']);
export const MODE_LABELS = Object.freeze({ read: 'Read', watch: 'Watch', try: 'Try', exercise: 'Exercise', inspect: 'Explain', compare: 'Compare' });
export const LABS = Object.freeze(['mosaic', 'practice', 'sparklab', 'airflow', 'pipeline', 'bi', 'fabric', 'dbt', 'lakehouse', 'apilab', 'terminal', 'infra']);
export const LANGUAGES = Object.freeze(['sql', 'sparklab', 'python', 'polars', 'none']);
const ID = /^[a-z][a-z0-9-]{0,99}$/;
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const safeId = x => typeof x === 'string' && ID.test(x) && !['constructor', 'prototype'].includes(x);
const fail = message => { throw new Error(`Learning document: ${message}`); };
const LANGUAGE_ID = /^[a-z][a-z0-9-]{0,39}$/;
/** Optional lesson fields (format version 1 stays valid without them): checks, practice, missions, cheatsheet, deck. */
export const LESSON_FIELDS = Object.freeze(['id', 'version', 'title', 'summary', 'minutes', 'concepts', 'prerequisites', 'blocks', 'code', 'exercise', 'lab', 'visual', 'related', 'checks', 'practice', 'missions', 'cheatsheet', 'deck']);
export const LIMITS = Object.freeze({ checks: 8, practice: 6, missions: 6, cards: 80, front: 300, back: 1200, tags: 8 });
/**
 * The four progress levels of a lesson, always shown separately and never merged into a score. Labels live here so
 * the rail, the native tree and tests share one wording.
 */
export const LEVEL_LABELS = Object.freeze({
  read: 'Read (self-reported)',
  quiz: 'Concept check, no execution',
  executed: 'Ran locally, not graded',
  verified: 'Practice passed'
});
export const refKey = ref => `${ref.id}/${ref.language}`;
/** Practice languages that are concept checks: answered and recorded by Practice, but nothing runs. */
export const QUIZ_LANGUAGES = Object.freeze(['quiz']);
function exerciseRef(ref, where) {
  keys(ref, ['id', 'language'], where);
  if (!safeId(ref.id)) fail(`${where}: invalid exercise id`);
  text(ref.language, 40, `${where} language`);
  if (!LANGUAGE_ID.test(ref.language)) fail(`${where}: invalid exercise language`);
}
function keys(value, allowed, where) {
  if (!object(value)) fail(`${where} must be an object`);
  for (const k of Object.keys(value)) if (!allowed.includes(k)) fail(`${where}: unknown field ${k}`);
}
function text(value, max, where) {
  if (typeof value !== 'string' || !value.trim() || value.length > max) fail(`${where}: invalid text`);
}
function list(value, max, where) {
  if (!Array.isArray(value) || value.length > max) fail(`${where}: invalid list`);
}
function dag(ids, edges, where) {
  const known = new Set(ids), indegree = new Map(ids.map(id => [id, 0])), children = new Map(ids.map(id => [id, []]));
  if (known.size !== ids.length) fail(`${where}: duplicate id`);
  for (const [from, to] of edges) {
    if (!known.has(from) || !known.has(to)) fail(`${where}: dangling dependency`);
    children.get(from).push(to); indegree.set(to, indegree.get(to) + 1);
  }
  const pending = ids.filter(id => indegree.get(id) === 0); let seen = 0;
  while (pending.length) { const id = pending.shift(); seen++; for (const next of children.get(id)) { indegree.set(next, indegree.get(next) - 1); if (!indegree.get(next)) pending.push(next); } }
  if (seen !== ids.length) fail(`${where}: cycle`);
}

/** The shipped catalog is an index (content/learning/catalog.json: the path order) plus one file per path
 * (content/learning/paths/<id>.json: the path and the lessons it defines). readPath(id) returns that file's JSON;
 * the result is the single catalog document validateCatalog checks. */
export function assembleCatalog(index, readPath) {
  keys(index, ['format', 'version', 'paths'], 'index');
  if (index.format !== 'datapass.learning' || index.version !== 1) fail('unsupported version');
  list(index.paths, 24, 'paths');
  const paths = [], lessons = [];
  for (const id of index.paths) {
    if (!safeId(id)) fail('invalid path id');
    const file = readPath(id);
    keys(file, ['format', 'version', 'path', 'lessons'], 'path file');
    if (file.format !== 'datapass.learning-path' || file.version !== 1) fail(`unsupported path file ${id}`);
    if (!object(file.path) || file.path.id !== id) fail(`path file ${id} names another path`);
    list(file.lessons, 64, 'path lessons');
    paths.push(file.path); lessons.push(...file.lessons);
  }
  return { format: index.format, version: index.version, paths, lessons };
}

/** Validate before any resource is opened. Destinations are catalog IDs, never commands, URLs or paths. */
export function validateCatalog(raw) {
  keys(raw, ['format', 'version', 'paths', 'lessons'], 'root');
  if (raw.format !== 'datapass.learning' || raw.version !== 1) fail('unsupported version');
  list(raw.paths, 24, 'paths'); list(raw.lessons, 128, 'lessons');
  if (!raw.paths.length || !raw.lessons.length) fail('empty catalog');
  const ids = new Set();
  for (const lesson of raw.lessons) {
    keys(lesson, LESSON_FIELDS, 'lesson');
    if (!safeId(lesson.id) || ids.has(lesson.id)) fail('invalid or duplicate lesson id'); ids.add(lesson.id);
    if (!Number.isInteger(lesson.version) || lesson.version < 1) fail('invalid lesson version');
    text(lesson.title, 140, 'title'); text(lesson.summary, 1000, 'summary');
    if (!Number.isInteger(lesson.minutes) || lesson.minutes < 1 || lesson.minutes > 180) fail('invalid duration');
    for (const field of ['concepts', 'prerequisites', 'related']) {
      list(lesson[field], 20, field); lesson[field].forEach(x => text(x, 160, field));
    }
    if (!LABS.includes(lesson.lab)) fail('unknown lab');
    list(lesson.blocks, 16, 'blocks');
    for (const block of lesson.blocks) {
      keys(block, ['kind', 'title', 'body'], 'block');
      if (!['text', 'callout', 'check'].includes(block.kind)) fail('unknown block type');
      text(block.title, 160, 'block title'); text(block.body, 8000, 'block body');
    }
    keys(lesson.code, ['language', 'source'], 'code');
    if (!LANGUAGES.includes(lesson.code.language) || typeof lesson.code.source !== 'string' || lesson.code.source.length > 64000) fail('invalid code');
    if (lesson.code.language !== 'none' && !lesson.code.source.trim()) fail('missing example');
    // The linked exercise is optional only for a lesson that is practised elsewhere (extra exercises or missions).
    if (lesson.exercise !== undefined) exerciseRef(lesson.exercise, 'exercise');
    else if (!lesson.practice?.length && !lesson.missions?.length && !lesson.checks?.length) fail('a lesson without an exercise needs checks, practice or missions');
    const linked = new Set(lesson.exercise ? [refKey(lesson.exercise)] : []);
    for (const [field, max] of [['checks', LIMITS.checks], ['practice', LIMITS.practice]]) {
      if (lesson[field] === undefined) continue;
      list(lesson[field], max, field); if (!lesson[field].length) fail(`${field}: empty list`);
      for (const ref of lesson[field]) {
        exerciseRef(ref, field);
        if (field === 'practice' && QUIZ_LANGUAGES.includes(ref.language)) fail('practice: concept checks belong in checks');
        if (linked.has(refKey(ref))) fail(`${field}: duplicate exercise ${refKey(ref)}`); linked.add(refKey(ref));
      }
    }
    if (lesson.missions !== undefined) {
      list(lesson.missions, LIMITS.missions, 'missions'); if (!lesson.missions.length) fail('missions: empty list');
      const seen = new Set();
      for (const mission of lesson.missions) {
        keys(mission, ['pack', 'id'], 'mission');
        if (!safeId(mission.pack) || !safeId(mission.id)) fail('invalid mission reference');
        if (seen.has(`${mission.pack}/${mission.id}`)) fail('duplicate mission'); seen.add(`${mission.pack}/${mission.id}`);
      }
    }
    // Reference ids, never paths: the host resolves a cheatsheet inside content/reference/ only.
    if (lesson.cheatsheet !== undefined && !safeId(lesson.cheatsheet)) fail('invalid cheatsheet id');
    if (lesson.deck !== undefined && !safeId(lesson.deck)) fail('invalid deck id');
    keys(lesson.visual, ['kind', 'title', 'steps', 'nodes', 'edges'], 'visual');
    if (!['join', 'window', 'partitions', 'dag', 'grain', 'storage', 'timeline'].includes(lesson.visual.kind)) fail('unknown visual');
    text(lesson.visual.title, 160, 'visual title'); list(lesson.visual.steps, 16, 'steps');
    if (!lesson.visual.steps.length) fail('visual has no steps');
    for (const step of lesson.visual.steps) {
      keys(step, ['title', 'body', 'lines'], 'step'); text(step.title, 160, 'step title'); text(step.body, 2000, 'step body');
      if (step.lines && (!Array.isArray(step.lines) || step.lines.length !== 2 || step.lines.some(x => !Number.isInteger(x) || x < 1) || step.lines[1] < step.lines[0] || step.lines[1] > lesson.code.source.split('\n').length)) fail('invalid code range');
    }
    const nodes = lesson.visual.nodes ?? [], edges = lesson.visual.edges ?? [];
    list(nodes, 32, 'nodes'); list(edges, 64, 'edges');
    for (const node of nodes) { keys(node, ['id', 'title'], 'node'); if (!safeId(node.id)) fail('invalid node id'); text(node.title, 100, 'node title'); }
    for (const edge of edges) if (!Array.isArray(edge) || edge.length !== 2) fail('invalid edge');
    dag(nodes.map(n => n.id), edges, 'visual DAG');
  }
  const pathIds = new Set(), covered = new Set();
  for (const path of raw.paths) {
    keys(path, ['id', 'title', 'summary', 'lessons'], 'path');
    if (!safeId(path.id) || pathIds.has(path.id)) fail('invalid or duplicate path id'); pathIds.add(path.id);
    text(path.title, 140, 'path title'); text(path.summary, 1000, 'path summary'); list(path.lessons, 64, 'path lessons');
    if (!path.lessons.length || new Set(path.lessons).size !== path.lessons.length) fail('empty or duplicate path lesson');
    for (const id of path.lessons) { if (!ids.has(id)) fail('unknown lesson destination'); covered.add(id); }
  }
  for (const lesson of raw.lessons) for (const id of [...lesson.prerequisites, ...lesson.related]) if (!ids.has(id)) fail('unknown related lesson');
  if (covered.size !== ids.size) fail('unreachable lesson');
  dag([...ids], raw.lessons.flatMap(l => l.prerequisites.map(p => [p, l.id])), 'prerequisites');
  return raw;
}

/**
 * Every lesson link must name something that is shipped: exercises in the installed public Practice catalog,
 * missions in content/missions/<pack>/pack.json, cheatsheets in content/reference/ and decks in
 * content/learning/flashcards/. Each `known` set is optional; a missing set skips that kind (pure tests).
 */
export function validateLinks(catalog, known) {
  for (const lesson of catalog.lessons) {
    if (known.exercises) for (const ref of [lesson.exercise, ...(lesson.checks ?? []), ...(lesson.practice ?? [])].filter(Boolean)) {
      if (!known.exercises.has(refKey(ref))) fail(`${lesson.id}: exercise is not installed: ${refKey(ref)}`);
    }
    if (known.missions) for (const mission of lesson.missions ?? []) {
      if (!known.missions.has(`${mission.pack}/${mission.id}`)) fail(`${lesson.id}: unknown mission ${mission.pack}/${mission.id}`);
    }
    if (known.cheatsheets && lesson.cheatsheet !== undefined && !known.cheatsheets.has(lesson.cheatsheet)) fail(`${lesson.id}: unknown cheatsheet ${lesson.cheatsheet}`);
    if (known.decks && lesson.deck !== undefined && !known.decks.has(lesson.deck)) fail(`${lesson.id}: unknown flashcard deck ${lesson.deck}`);
  }
  return catalog;
}

// Plain text: no control characters other than newline and tab.
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f]/;
function plain(value, max, where) { text(value, max, where); if (CONTROL.test(value)) fail(`${where}: control character`); }
/**
 * content/learning/flashcards/<id>.json: {format:"datapass.flashcards", version:1, id, title, path, cards:[{id, front,
 * back, lesson?, tags[]}]}. `expectedId` is the file name; `catalog` (optional) checks the path and lesson references.
 */
export function validateDeck(raw, expectedId, catalog) {
  keys(raw, ['format', 'version', 'id', 'title', 'path', 'cards'], 'deck');
  if (raw.format !== 'datapass.flashcards' || raw.version !== 1) fail('unsupported flashcard deck');
  if (!safeId(raw.id) || (expectedId !== undefined && raw.id !== expectedId)) fail('deck id must match its file name');
  plain(raw.title, 140, 'deck title');
  if (!safeId(raw.path)) fail('invalid deck path');
  if (catalog && !catalog.paths.some(p => p.id === raw.path)) fail(`deck ${raw.id}: unknown learning path ${raw.path}`);
  list(raw.cards, LIMITS.cards, 'cards'); if (!raw.cards.length) fail('empty deck');
  const ids = new Set();
  for (const card of raw.cards) {
    keys(card, ['id', 'front', 'back', 'lesson', 'tags'], 'card');
    if (!safeId(card.id) || ids.has(card.id)) fail('invalid or duplicate card id'); ids.add(card.id);
    plain(card.front, LIMITS.front, 'card front'); plain(card.back, LIMITS.back, 'card back');
    if (card.lesson !== undefined) {
      if (!safeId(card.lesson)) fail('invalid card lesson');
      if (catalog && !catalog.lessons.some(l => l.id === card.lesson)) fail(`card ${card.id}: unknown lesson ${card.lesson}`);
    }
    list(card.tags, LIMITS.tags, 'card tags'); card.tags.forEach(tag => { plain(tag, 40, 'card tag'); });
  }
  return raw;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const HASH = /^[0-9a-f]{64}$/;
const isInstant = x => typeof x === 'string' && x.length <= 40 && Number.isFinite(Date.parse(x));
export const cardKey = (deck, card) => `${deck}/${card}`;

export function initialState(catalog) {
  return { version: 1, path: catalog.paths[0].id, lesson: catalog.paths[0].lessons[0], mode: 'read', railHidden: false, layout: 'balanced', read: {}, notes: {}, executed: {}, flashcards: {} };
}
/**
 * Stored acknowledgements are self-reports, never grading evidence. Drops removed lessons on catalog upgrades.
 * `options.decks` drops ratings of removed cards; `options.parseReview` (the Practice Review parser) validates the
 * stored Leitner schedule of a card; without it, schedules are dropped.
 */
export function restoreState(catalog, raw, options = {}) {
  const out = initialState(catalog);
  if (!object(raw) || raw.version !== 1) return out;
  const path = catalog.paths.find(p => p.id === raw.path);
  if (path) { out.path = path.id; if (path.lessons.includes(raw.lesson)) out.lesson = raw.lesson; else out.lesson = path.lessons[0]; }
  if (MODES.includes(raw.mode)) out.mode = raw.mode;
  out.railHidden = raw.railHidden === true;
  if (['balanced', 'focus', 'compact'].includes(raw.layout)) out.layout = raw.layout;
  const own = (bag, key) => object(bag) && Object.hasOwn(bag, key) ? bag[key] : undefined;
  for (const lesson of catalog.lessons) {
    const read = own(raw.read, lesson.id);
    if (object(read) && read.version === lesson.version && isInstant(read.at)) out.read[lesson.id] = { version: read.version, at: read.at };
    const note = own(raw.notes, lesson.id);
    if (typeof note === 'string' && note.length <= 8000) out.notes[lesson.id] = note;
    const run = own(raw.executed, lesson.id);
    if (object(run) && run.version === lesson.version && isInstant(run.at) && typeof run.sourceHash === 'string' && HASH.test(run.sourceHash) && LANGUAGES.includes(run.language) && run.language !== 'none') {
      out.executed[lesson.id] = { version: run.version, at: run.at, sourceHash: run.sourceHash, language: run.language };
    }
  }
  const cards = options.decks ? new Set(options.decks.flatMap(d => d.cards.map(c => cardKey(d.id, c.id)))) : undefined;
  if (object(raw.flashcards)) for (const [key, value] of Object.entries(raw.flashcards).slice(0, 5000)) {
    if (!/^[a-z][a-z0-9-]{0,99}\/[a-z][a-z0-9-]{0,99}$/.test(key) || (cards && !cards.has(key)) || !object(value)) continue;
    if (!Number.isInteger(value.attempts) || value.attempts < 0 || value.attempts > 1e6) continue;
    const record = { attempts: value.attempts };
    const review = options.parseReview ? options.parseReview(value.review) : undefined;
    if (review) record.review = review;
    if (object(value.last) && isInstant(value.last.at) && ['knew', 'missed'].includes(value.last.rating)) record.last = { at: value.last.at, rating: value.last.rating };
    out.flashcards[key] = record;
  }
  return out;
}
/** Legacy single status, kept for callers that need one word. The four separate levels come from lessonProgress. */
export function lessonStatus(lesson, state, exercise, practice) {
  const record = exercise && practice?.exercises?.[exercise.key];
  if (exercise && record?.solved && record.solved.version === exercise.version) return 'practiced';
  if (state.read[lesson.id]?.version === lesson.version) return 'read';
  return 'new';
}
/**
 * The four progress levels of a lesson, kept apart:
 * - read: the learner's own acknowledgement (self-report);
 * - checks: the last Submit recorded by Practice on each `checks` item (passed/failed/unanswered); a concept check runs
 *   nothing;
 * - executed: a Learning Run of this lesson version returned without an error (ran locally, not graded);
 * - verified: a passed Practice Submit on the lesson's exercise (or, without one, on one of its `practice` items).
 * `resolve(ref)` returns the installed exercise {key, version} or undefined.
 */
export function lessonProgress(lesson, state, resolve, practice) {
  const records = object(practice?.exercises) ? practice.exercises : {};
  const record = ref => { const e = resolve(ref); return e ? { e, r: Object.hasOwn(records, e.key) ? records[e.key] : undefined } : undefined; };
  const solved = ref => { const x = record(ref); return Boolean(x?.r?.solved && x.r.solved.version === x.e.version); };
  const check = (ref, source, index) => {
    const x = record(ref); let status = 'unanswered';
    if (x?.r?.last?.mode === 'submit' && x.r.last.version === x.e.version) status = x.r.last.status === 'passed' ? 'passed' : 'failed';
    else if (x?.r?.solved && x.r.solved.version === x.e.version) status = 'passed';
    return { id: ref.id, language: ref.language, status, source, index };
  };
  // A concept check (language quiz) never verifies a lesson, even when an older lesson links one as its exercise.
  const quizExercise = Boolean(lesson.exercise && QUIZ_LANGUAGES.includes(lesson.exercise.language));
  const checks = [...(quizExercise ? [check(lesson.exercise, 'exercise', 0)] : []), ...(lesson.checks ?? []).map((ref, i) => check(ref, 'checks', i))];
  const extra = (lesson.practice ?? []).map(ref => ({ id: ref.id, language: ref.language, passed: solved(ref) }));
  const exercise = lesson.exercise && !quizExercise ? solved(lesson.exercise) : undefined;
  const run = state.executed?.[lesson.id];
  return {
    read: state.read[lesson.id]?.version === lesson.version,
    checks,
    executed: run && run.version === lesson.version ? run : undefined,
    verified: exercise ?? extra.some(p => p.passed),
    exercise, practice: extra
  };
}
/** Short separate labels for the four levels (rail, tree). An empty level is omitted, never shown as a zero score. */
export function levelBadges(lesson, progress, labels = LEVEL_LABELS) {
  const out = [];
  if (progress.read) out.push({ level: 'read', text: labels.read });
  if (progress.checks.length) {
    const passed = progress.checks.filter(c => c.status === 'passed').length, failed = progress.checks.filter(c => c.status === 'failed').length;
    if (passed || failed) out.push({ level: 'quiz', text: `Checks ${passed}/${progress.checks.length} passed${failed ? `, ${failed} failed` : ''}`, title: labels.quiz });
  }
  if (progress.executed) out.push({ level: 'executed', text: labels.executed });
  if (progress.verified) out.push({ level: 'verified', text: labels.verified, title: 'Verified by a passed Practice Submit' });
  return out;
}
/** The next lesson item still to verify, current path first: an unpassed check, then an unpassed exercise. */
export function nextUnverified(catalog, state, resolve, practice) {
  const order = [catalog.paths.find(p => p.id === state.path), ...catalog.paths.filter(p => p.id !== state.path)].filter(Boolean);
  const start = order[0]?.lessons.indexOf(state.lesson) ?? 0;
  for (const [i, path] of order.entries()) {
    const ids = i === 0 ? [...path.lessons.slice(Math.max(0, start)), ...path.lessons.slice(0, Math.max(0, start))] : path.lessons;
    for (const id of ids) {
      const lesson = catalog.lessons.find(l => l.id === id); const p = lessonProgress(lesson, state, resolve, practice);
      const check = p.checks.find(c => c.status !== 'passed');
      if (check) return { path: path.id, lesson: id, kind: 'check', id: check.id, language: check.language };
      if (p.exercise === false) return { path: path.id, lesson: id, kind: 'exercise', id: lesson.exercise.id, language: lesson.exercise.language };
    }
  }
  return undefined;
}
export function searchLessons(catalog, query) {
  const q = String(query).trim().toLowerCase();
  return catalog.lessons.filter(l => !q || [l.title, l.summary, ...l.concepts].join(' ').toLowerCase().includes(q));
}
/** Lessons, cheatsheet titles and flashcard fronts. An empty query lists lessons only. */
export function searchAll(catalog, query, extras = {}) {
  const q = String(query).trim().toLowerCase();
  const lessons = searchLessons(catalog, q);
  if (!q) return { lessons, cheatsheets: [], cards: [] };
  const cheatsheets = (extras.cheatsheets ?? []).filter(s => `${s.title} ${s.id}`.toLowerCase().includes(q));
  const cards = (extras.cards ?? []).filter(c => c.front.toLowerCase().includes(q)).slice(0, 20);
  return { lessons, cheatsheets, cards };
}

const SIMPLE = ['ready', 'read', 'hint', 'openExample', 'run', 'runSelection', 'explain', 'openLab', 'nativePath', 'openRuntime', 'pin', 'export', 'openPractice', 'next', 'previous', 'cheatsheet', 'openDeck', 'reviewClose'];
const GLOBAL = ['ready', 'nativePath', 'export', 'openRuntime', 'reviewClose'];
/**
 * Webview input is untrusted, even though its content is bundled. `extras.decks` (validated decks) and
 * `extras.cheatsheets` (ids) bound the flashcard and cheatsheet targets.
 */
export function parseMessage(raw, catalog, extras = {}) {
  if (!object(raw) || typeof raw.type !== 'string') return undefined;
  const allowed = {
    select: ['type', 'path', 'lesson'], mode: ['type', 'lesson', 'mode'], grade: ['type', 'lesson', 'mode'],
    rail: ['type', 'hidden'], layout: ['type', 'layout'], note: ['type', 'lesson', 'text'], focusStep: ['type', 'lesson', 'index'],
    openCheck: ['type', 'lesson', 'index'], openPracticeItem: ['type', 'lesson', 'index'], openMission: ['type', 'lesson', 'index'],
    review: ['type', 'deck'], rate: ['type', 'deck', 'card', 'rating'], openCheatsheet: ['type', 'id']
  };
  const fields = SIMPLE.includes(raw.type) ? (GLOBAL.includes(raw.type) ? ['type'] : ['type', 'lesson']) : Object.hasOwn(allowed, raw.type) ? allowed[raw.type] : undefined;
  if (!fields || Object.keys(raw).some(k => !fields.includes(k))) return undefined;
  if (fields.includes('lesson') && !catalog.lessons.some(l => l.id === raw.lesson)) return undefined;
  const lesson = fields.includes('lesson') ? catalog.lessons.find(l => l.id === raw.lesson) : undefined;
  const decks = extras.decks ?? [];
  const index = (value, items) => Number.isInteger(value) && value >= 0 && value < (items?.length ?? 0);
  if (raw.type === 'select' && !catalog.paths.some(p => p.id === raw.path && p.lessons.includes(raw.lesson))) return undefined;
  if (raw.type === 'mode' && !MODES.includes(raw.mode)) return undefined;
  if (raw.type === 'grade' && !['run', 'submit'].includes(raw.mode)) return undefined;
  if (raw.type === 'rail' && typeof raw.hidden !== 'boolean') return undefined;
  if (raw.type === 'layout' && !['balanced', 'focus', 'compact'].includes(raw.layout)) return undefined;
  if (raw.type === 'note' && (typeof raw.text !== 'string' || raw.text.length > 8000)) return undefined;
  if (raw.type === 'focusStep' && !index(raw.index, lesson.visual.steps)) return undefined;
  if (raw.type === 'openCheck' && !index(raw.index, lesson.checks)) return undefined;
  if (raw.type === 'openPracticeItem' && !index(raw.index, lesson.practice)) return undefined;
  if (raw.type === 'openMission' && !index(raw.index, lesson.missions)) return undefined;
  if (raw.type === 'cheatsheet' && lesson.cheatsheet === undefined) return undefined;
  if (raw.type === 'openDeck' && lesson.deck === undefined) return undefined;
  if (raw.type === 'review' && raw.deck !== undefined && !decks.some(d => d.id === raw.deck)) return undefined;
  if (raw.type === 'rate' && (!['knew', 'missed'].includes(raw.rating) || !decks.some(d => d.id === raw.deck && d.cards.some(c => c.id === raw.card)))) return undefined;
  if (raw.type === 'openCheatsheet' && !(extras.cheatsheets ?? []).includes(raw.id)) return undefined;
  return raw;
}

/** A deliberately small, completely visible fixture, not execution of the learner's SQL. SQL NULL != NULL. */
export function joinDemo(kind = 'left', filter = 'none') {
  if (!['inner', 'left', 'full', 'semi', 'anti'].includes(kind) || !['none', 'on', 'where'].includes(filter)) throw new Error('Unknown join option');
  if (['semi', 'anti'].includes(kind) && filter === 'where') throw new Error('Right-side columns are not projected by a semi/anti join');
  const left = [{ key: 1, name: 'Ada' }, { key: 2, name: 'Ben' }, { key: 3, name: 'Chloe' }, { key: null, name: 'Unknown' }];
  const right = [{ id: 101, key: 1, status: 'DONE' }, { id: 102, key: 1, status: 'OPEN' }, { id: 103, key: 4, status: 'DONE' }, { id: 104, key: null, status: 'DONE' }];
  const rows = [], matched = new Set();
  for (let i = 0; i < left.length; i++) {
    const matches = right.map((r, j) => ({ r, j })).filter(({ r }) => left[i].key !== null && r.key !== null && left[i].key === r.key && (filter !== 'on' || r.status === 'DONE'));
    if (kind === 'semi' || kind === 'anti') { if (Boolean(matches.length) === (kind === 'semi')) rows.push({ name: left[i].name, customer: left[i].key, left: i, right: null }); continue; }
    for (const { r, j } of matches) { matched.add(j); rows.push({ name: left[i].name, customer: left[i].key, order: r.id, status: r.status, left: i, right: j }); }
    if (!matches.length && kind !== 'inner') rows.push({ name: left[i].name, customer: left[i].key, order: null, status: null, left: i, right: null });
  }
  if (kind === 'full') right.forEach((r, j) => { if (!matched.has(j)) rows.push({ name: null, customer: null, order: r.id, status: r.status, left: null, right: j }); });
  return { left, right, rows: filter === 'where' ? rows.filter(r => r.status === 'DONE') : rows };
}
export function windowDemo(frame = 'rows', cursor = 0) {
  if (!['rows', 'range'].includes(frame) || !Number.isInteger(cursor) || cursor < 0 || cursor > 3) throw new Error('Invalid window');
  const rows = [{ id: 1, day: 1, amount: 100 }, { id: 2, day: 2, amount: -30 }, { id: 3, day: 2, amount: 50 }, { id: 4, day: 4, amount: 20 }];
  const members = rows.map((r, i) => frame === 'rows' ? i <= cursor : r.day <= rows[cursor].day);
  return { rows, members, sum: rows.reduce((sum, r, i) => sum + (members[i] ? r.amount : 0), 0) };
}
/** Four authored input partitions. Hash buckets are illustrative, NOT Spark's hash function or task scheduler. */
export function partitionDemo(kind = 'repartition', count = 2) {
  if (!['repartition', 'coalesce', 'broadcast'].includes(kind) || !Number.isInteger(count) || count < 1 || count > 8) throw new Error('Invalid partitions');
  const source = Array.from({ length: 4 }, (_, p) => Array.from({ length: 3 }, (_, i) => ({ id: p * 3 + i, key: (p * 3 + i) % 3 })));
  if (kind === 'broadcast') return { source, targets: source.map(a => [...a]), broadcastCopies: 4, exchange: 'Broadcast replication; no shuffle of the streamed side' };
  const n = kind === 'coalesce' ? Math.min(4, count) : count;
  const targets = Array.from({ length: n }, () => []);
  source.forEach((group, p) => group.forEach(row => targets[kind === 'coalesce' ? Math.floor(p * n / 4) : row.key % n].push(row)));
  return { source, targets, broadcastCopies: 0, exchange: kind === 'coalesce' ? 'No shuffle exchange; only merges existing partitions' : 'Shuffle exchange; keys are reassigned to buckets' };
}
export function isCurrentRun(run, lesson, hash) { return Boolean(run && run.lesson === lesson && run.sourceHash === hash); }
export function compareRuns(a, b) {
  if (!a || !b || a.lesson !== b.lesson || a.language !== b.language || a.scope !== b.scope) return { compatible: false, reason: 'Pin and run the same lesson, language and execution scope.' };
  return { compatible: true, reason: 'Recorded runs, not a benchmark. Workspace inputs may have changed between runs.' };
}
