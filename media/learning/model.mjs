/** Inert learning documents and deterministic teaching diagrams. No code evaluation or network access. */
export const MODES = Object.freeze(['read', 'watch', 'try', 'exercise', 'inspect', 'compare']);
export const MODE_LABELS = Object.freeze({ read: 'Read', watch: 'Watch', try: 'Try', exercise: 'Exercise', inspect: 'Explain', compare: 'Compare' });
export const LABS = Object.freeze(['mosaic', 'practice', 'sparklab', 'airflow', 'pipeline', 'bi', 'fabric', 'dbt', 'lakehouse', 'apilab', 'terminal', 'infra']);
export const LANGUAGES = Object.freeze(['sql', 'sparklab', 'python', 'polars', 'none']);
const ID = /^[a-z][a-z0-9-]{0,99}$/;
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const safeId = x => typeof x === 'string' && ID.test(x) && !['constructor', 'prototype'].includes(x);
const fail = message => { throw new Error(`Learning document: ${message}`); };
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

/** Validate before any resource is opened. Destinations are catalog IDs, never commands, URLs or paths. */
export function validateCatalog(raw) {
  keys(raw, ['format', 'version', 'paths', 'lessons'], 'root');
  if (raw.format !== 'datapass.learning' || raw.version !== 1) fail('unsupported version');
  list(raw.paths, 24, 'paths'); list(raw.lessons, 128, 'lessons');
  if (!raw.paths.length || !raw.lessons.length) fail('empty catalog');
  const ids = new Set();
  for (const lesson of raw.lessons) {
    keys(lesson, ['id', 'version', 'title', 'summary', 'minutes', 'concepts', 'prerequisites', 'blocks', 'code', 'exercise', 'lab', 'visual', 'related'], 'lesson');
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
    keys(lesson.exercise, ['id', 'language'], 'exercise');
    if (!safeId(lesson.exercise.id)) fail('invalid exercise id'); text(lesson.exercise.language, 40, 'exercise language');
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

export function initialState(catalog) {
  return { version: 1, path: catalog.paths[0].id, lesson: catalog.paths[0].lessons[0], mode: 'read', railHidden: false, layout: 'balanced', read: {}, notes: {} };
}
/** Stored acknowledgements are self-reports, never grading evidence. Drops removed lessons on catalog upgrades. */
export function restoreState(catalog, raw) {
  const out = initialState(catalog);
  if (!object(raw) || raw.version !== 1) return out;
  const path = catalog.paths.find(p => p.id === raw.path);
  if (path) { out.path = path.id; if (path.lessons.includes(raw.lesson)) out.lesson = raw.lesson; else out.lesson = path.lessons[0]; }
  if (MODES.includes(raw.mode)) out.mode = raw.mode;
  out.railHidden = raw.railHidden === true;
  if (['balanced', 'focus', 'compact'].includes(raw.layout)) out.layout = raw.layout;
  for (const lesson of catalog.lessons) {
    const read = object(raw.read) && Object.hasOwn(raw.read, lesson.id) && raw.read[lesson.id];
    if (object(read) && read.version === lesson.version && typeof read.at === 'string' && Number.isFinite(Date.parse(read.at))) out.read[lesson.id] = { version: read.version, at: read.at };
    const note = object(raw.notes) && Object.hasOwn(raw.notes, lesson.id) && raw.notes[lesson.id];
    if (typeof note === 'string' && note.length <= 8000) out.notes[lesson.id] = note;
  }
  return out;
}
export function lessonStatus(lesson, state, exercise, practice) {
  const record = exercise && practice?.exercises?.[exercise.key];
  if (exercise && record?.solved && record.solved.version === exercise.version) return 'practiced';
  if (state.read[lesson.id]?.version === lesson.version) return 'read';
  return 'new';
}
export function searchLessons(catalog, query) {
  const q = String(query).trim().toLowerCase();
  return catalog.lessons.filter(l => !q || [l.title, l.summary, ...l.concepts].join(' ').toLowerCase().includes(q));
}

const SIMPLE = ['ready', 'read', 'hint', 'openExample', 'run', 'runSelection', 'explain', 'openLab', 'nativePath', 'openRuntime', 'pin', 'export', 'openPractice', 'next', 'previous'];
/** Webview input is untrusted, even though its content is bundled. */
export function parseMessage(raw, catalog) {
  if (!object(raw) || typeof raw.type !== 'string') return undefined;
  const allowed = {
    select: ['type', 'path', 'lesson'], mode: ['type', 'lesson', 'mode'], grade: ['type', 'lesson', 'mode'],
    rail: ['type', 'hidden'], layout: ['type', 'layout'], note: ['type', 'lesson', 'text'], focusStep: ['type', 'lesson', 'index']
  };
  const fields = SIMPLE.includes(raw.type) ? (['ready', 'nativePath', 'export', 'openRuntime'].includes(raw.type) ? ['type'] : ['type', 'lesson']) : Object.hasOwn(allowed, raw.type) ? allowed[raw.type] : undefined;
  if (!fields || Object.keys(raw).some(k => !fields.includes(k))) return undefined;
  if (fields.includes('lesson') && !catalog.lessons.some(l => l.id === raw.lesson)) return undefined;
  if (raw.type === 'select' && !catalog.paths.some(p => p.id === raw.path && p.lessons.includes(raw.lesson))) return undefined;
  if (raw.type === 'mode' && !MODES.includes(raw.mode)) return undefined;
  if (raw.type === 'grade' && !['run', 'submit'].includes(raw.mode)) return undefined;
  if (raw.type === 'rail' && typeof raw.hidden !== 'boolean') return undefined;
  if (raw.type === 'layout' && !['balanced', 'focus', 'compact'].includes(raw.layout)) return undefined;
  if (raw.type === 'note' && (typeof raw.text !== 'string' || raw.text.length > 8000)) return undefined;
  if (raw.type === 'focusStep' && (!Number.isInteger(raw.index) || raw.index < 0 || raw.index >= catalog.lessons.find(l => l.id === raw.lesson).visual.steps.length)) return undefined;
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
