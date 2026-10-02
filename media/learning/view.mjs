import { MODES, MODE_LABELS, searchLessons, joinDemo, windowDemo, partitionDemo, compareRuns, isCurrentRun } from './model.mjs';

// The browser only presents bounded documents. Native files and runtime calls stay in the extension host.
const vscode = acquireVsCodeApi();
const root = document.getElementById('learning-root');
let model;
let query = '';
let overview = false;
let timer;
const visuals = new Map();
const drafts = new Map();
const cached = vscode.getState() ?? {};
if (typeof cached.query === 'string') query = cached.query.slice(0, 200);
function el(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}
function add(parent, ...children) { for (const child of children.flat()) if (child) parent.append(child); return parent; }
function button(label, fn, options = {}) {
  const node = el('button', options.primary ? 'button primary' : 'button', label);
  node.type = 'button'; node.disabled = Boolean(options.disabled); node.addEventListener('click', fn);
  if (options.title) node.title = options.title;
  if (options.pressed !== undefined) node.setAttribute('aria-pressed', String(options.pressed));
  node.dataset.focus = options.key ?? label;
  return node;
}
function send(type, extra = {}) {
  const global = ['ready', 'nativePath', 'export', 'rail', 'layout', 'select', 'openRuntime'].includes(type);
  vscode.postMessage({ type, ...(global ? {} : { lesson: model.state.lesson }), ...extra });
}
function lessonById(id) { return model.catalog.lessons.find(item => item.id === id); }
function destination(id) {
  const path = model.catalog.paths.find(p => p.lessons.includes(id));
  if (path) { overview = false; stop(); send('select', { path: path.id, lesson: id }); }
}
function localVisual(lesson) {
  if (!visuals.has(lesson.id)) visuals.set(lesson.id, { step: 0, join: 'left', filter: 'none', frame: 'rows', cursor: 0, partition: 'repartition', count: 2, selectedRow: 0 });
  return visuals.get(lesson.id);
}
function select(label, values, current, change) {
  const wrapper = el('label', 'control'); add(wrapper, el('span', '', label));
  const input = el('select'); input.setAttribute('aria-label', label); input.dataset.focus = label;
  for (const [value, text] of values) { const option = el('option', '', text); option.value = String(value); option.selected = String(value) === String(current); input.append(option); }
  input.addEventListener('change', () => { change(input.value); render(); });
  return add(wrapper, input);
}
function card(title, ...content) { return add(el('section', 'card'), el('h2', '', title), ...content); }
function badge(text, kind = '') { return el('span', `badge ${kind}`, text); }
function prose(text) {
  const body = el('div', 'prose');
  for (const paragraph of String(text).split(/\n\s*\n/)) {
    const p = el('p');
    // An intentionally small Markdown subset: inline code only, never HTML.
    paragraph.split(/(`[^`]+`)/g).forEach(part => p.append(part.startsWith('`') && part.endsWith('`') ? el('code', '', part.slice(1, -1)) : document.createTextNode(part)));
    body.append(p);
  }
  return body;
}
function dataTable(columns, rows, caption, decorate) {
  const box = el('div', 'table-scroll'); const table = el('table');
  table.append(el('caption', 'sr-only', caption));
  const head = el('tr'); columns.forEach(c => head.append(el('th', '', c))); add(table, add(el('thead'), head));
  const body = el('tbody');
  rows.slice(0, 100).forEach((row, i) => {
    const tr = el('tr'); columns.forEach(c => tr.append(el('td', row[c] === null ? 'null' : '', row[c] === null ? 'NULL' : row[c] ?? '')));
    if (decorate) decorate(tr, i); body.append(tr);
  });
  add(table, body); add(box, table);
  if (!rows.length) box.append(el('p', 'empty', 'No rows.'));
  if (rows.length > 100) box.append(el('p', 'muted', `Showing 100 of ${rows.length} returned rows.`));
  return box;
}
function statusName(id) { return model.statuses[id] === 'practiced' ? 'Practice passed' : model.statuses[id] === 'read' ? 'Read (self-reported)' : 'Not started'; }
function stop() { clearInterval(timer); timer = undefined; }
function play(lesson) {
  if (timer) { stop(); render(); return; }
  const visual = localVisual(lesson); visual.step = 0;
  timer = setInterval(() => {
    if (model.state.lesson !== lesson.id || model.state.mode !== 'watch') { stop(); return; }
    if (visual.step >= lesson.visual.steps.length - 1) { stop(); render(); return; }
    visual.step++; render();
  }, 2400);
  render();
}
function header(lesson, path) {
  const top = el('header', 'topbar');
  add(top, add(el('div', 'brand'), el('span', 'logo', 'M'), add(el('div'), el('strong', '', 'Mosaic Learning'), el('div', 'muted', 'Read. Experiment. Practice.'))));
  add(top, add(el('div', 'toolbar'), button(overview ? 'Resume lesson' : 'Learning map', () => { overview = !overview; stop(); render(); }, { key: 'map' }),
    button(model.state.railHidden ? 'Show path' : 'Hide path', () => send('rail', { hidden: !model.state.railHidden }), { key: 'rail' }),
    button('Runtime controls', () => send('openRuntime'), { title: 'Open existing runtime setup/start controls. Nothing starts automatically.' })));
  const heading = add(el('div', 'heading'), el('div', 'eyebrow', path.title), el('h1', '', overview ? 'Your data engineering learning map' : lesson.title));
  add(heading, el('p', 'summary', overview ? 'Six paths connect course notes, native code and the labs already in Workbench.' : lesson.summary));
  add(heading, add(el('div', 'metadata'), badge(`${lesson.minutes} min suggested`), badge(statusName(lesson.id)), badge(`Runtime: ${model.runtime.status}`, model.runtime.status === 'running' ? 'success' : ''), badge('Local-first')));
  const modes = el('nav', 'modes'); modes.setAttribute('aria-label', 'Lesson views');
  MODES.forEach(mode => modes.append(button(MODE_LABELS[mode], () => { overview = false; stop(); send('mode', { mode }); }, { pressed: mode === model.state.mode, key: `mode-${mode}` })));
  add(modes, select('Layout', [['balanced', 'Balanced'], ['focus', 'Focus'], ['compact', 'Compact']], model.state.layout, layout => send('layout', { layout })));
  return add(el('div', 'sticky-header'), top, heading, overview ? undefined : modes);
}
function pathRail(path, lesson) {
  const rail = el('aside', 'learning-rail'); rail.setAttribute('aria-label', 'Learning path');
  add(rail, add(el('div', 'rail-heading'), el('h2', '', 'Learning path'), button('Hide', () => send('rail', { hidden: true }), { key: 'hide-rail' })));
  rail.append(select('Path', model.catalog.paths.map(p => [p.id, p.title]), path.id, id => send('select', { path: id, lesson: model.catalog.paths.find(p => p.id === id).lessons[0] })));
  const passed = path.lessons.filter(id => model.statuses[id] === 'practiced').length;
  rail.append(el('p', 'muted', `${passed} / ${path.lessons.length} linked exercises passed`));
  const list = el('ol', 'path-list');
  path.lessons.forEach((id, i) => {
    const item = lessonById(id); const li = el('li', id === lesson.id ? 'current' : '');
    const title = button(`${i + 1}. ${item.title}`, () => destination(id), { key: `lesson-${id}` });
    if (id === lesson.id) title.setAttribute('aria-current', 'step');
    add(li, title, el('small', '', statusName(id)));
    if (id === lesson.id) {
      const sub = el('div', 'substeps'); ['read', 'watch', 'try', 'exercise'].forEach(mode => sub.append(button(MODE_LABELS[mode], () => { stop(); send('mode', { mode }); }, { pressed: model.state.mode === mode, key: `rail-${mode}` })));
      li.append(sub);
    }
    list.append(li);
  });
  add(rail, list, el('hr'), el('p', 'muted', 'Reading is a self-report. Only the existing Practice grader can mark a linked exercise passed.'),
    button('Open native path tree', () => send('nativePath')), button('Export notes and reading', () => send('export')));
  if (lesson.related.length) add(rail, el('h3', '', 'Related topics'), lesson.related.map(id => button(lessonById(id).title, () => destination(id), { key: `related-${id}` })));
  return rail;
}
function learningMap() {
  const section = el('section', 'map');
  const input = el('input'); input.type = 'search'; input.placeholder = 'Find a concept: joins, retries, grain...'; input.value = query;
  input.setAttribute('aria-label', 'Search lessons'); input.dataset.focus = 'search';
  input.addEventListener('input', () => { query = input.value.slice(0, 200); vscode.setState({ query }); render(); });
  section.append(input);
  const matching = new Set(searchLessons(model.catalog, query).map(l => l.id));
  const cards = el('div', 'map-grid');
  for (const path of model.catalog.paths) {
    const ids = path.lessons.filter(id => matching.has(id)); if (!ids.length) continue;
    const c = card(path.title, prose(path.summary));
    const list = el('div', 'map-lessons');
    ids.forEach(id => add(list, add(el('div'), button(lessonById(id).title, () => destination(id), { key: `map-${id}` }), el('small', '', statusName(id)))));
    add(c, list); cards.append(c);
  }
  add(section, cards); if (!matching.size) section.append(el('p', 'empty', 'No matching lesson. Try a broader topic.'));
  return section;
}
function course(lesson) {
  const content = el('div', 'course');
  lesson.blocks.forEach(block => { const c = card(block.title, prose(block.body)); c.classList.add(`block-${block.kind}`); content.append(c); });
  if (lesson.code.source) {
    const snippet = el('pre', 'source'); add(snippet, el('code', '', lesson.code.source));
    content.append(card('Native example', badge(lesson.code.language), snippet,
      el('p', 'muted', 'This is the shipped example, not your current edited file. Try opens a real VS Code file and preserves edits.'),
      button('Try this example', () => send('mode', { mode: 'try' }), { primary: true })));
  }
  content.append(card('Continue', add(el('div', 'toolbar'), button('Mark as read', () => send('read')), button('Open linked exercise', () => send('mode', { mode: 'exercise' }), { primary: true })),
    el('p', 'muted', 'Marking a lesson read does not pass an exercise or certify mastery.')));
  return content;
}
function joinVisual(lesson, state) {
  const data = joinDemo(state.join, state.filter);
  const box = el('div');
  add(box, add(el('div', 'toolbar'), select('Join type', ['left', 'inner', 'full', 'semi', 'anti'].map(k => [k, k.toUpperCase()]), state.join, value => { state.join = value; if (['semi', 'anti'].includes(value)) state.filter = 'none'; state.selectedRow = 0; }),
    select('Right status filter', [['none', 'No status filter'], ['on', 'ON status = DONE'], ...(['semi', 'anti'].includes(state.join) ? [] : [['where', 'WHERE status = DONE']])], state.filter, value => { state.filter = value; state.selectedRow = 0; })));
  const chosen = data.rows[state.selectedRow];
  add(box, add(el('div', 'two-tables'), card('Customers', dataTable(['key', 'name'], data.left, 'Customers fixture', (tr, i) => { if (chosen?.left === i) tr.classList.add('selected'); })),
    card('Orders', dataTable(['id', 'key', 'status'], data.right, 'Orders fixture', (tr, i) => { if (chosen?.right === i) tr.classList.add('selected'); }))));
  const cols = ['semi', 'anti'].includes(state.join) ? ['customer', 'name'] : ['customer', 'name', 'order', 'status'];
  add(box, el('h3', '', `Result: ${data.rows.length} rows`), dataTable(cols, data.rows, 'Illustrative join output', (tr, i) => {
    if (i === state.selectedRow) tr.classList.add('selected'); tr.tabIndex = 0; tr.dataset.focus = `join-output-${i}`; tr.setAttribute('aria-label', `Inspect output row ${i + 1}`);
    const choose = () => { state.selectedRow = i; render(); }; tr.addEventListener('click', choose); tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(); } });
  }), el('p', 'muted', 'Select an output row to highlight its input matches. Equal NULL keys do not match; duplicate keys can multiply rows. These controls do not edit or execute your SQL.'));
  return box;
}
function windowVisual(state) {
  const data = windowDemo(state.frame, state.cursor); const box = el('div');
  add(box, add(el('div', 'toolbar'), select('Frame', [['rows', 'ROWS: ordered by day, id'], ['range', 'RANGE: ordered by day']], state.frame, value => state.frame = value),
    select('Current row', data.rows.map((row, i) => [i, `Row ${row.id}, day ${row.day}`]), state.cursor, value => state.cursor = Number(value))));
  add(box, dataTable(['id', 'day', 'amount'], data.rows, 'Window frame fixture', (tr, i) => { if (data.members[i]) tr.classList.add('included'); if (i === state.cursor) tr.classList.add('selected'); }),
    add(el('div', 'metric-strip'), metric('Frame rows', data.members.filter(Boolean).length), metric('SUM(amount)', data.sum)),
    el('p', 'muted', 'UNBOUNDED PRECEDING to CURRENT ROW. RANGE includes all peers for the ordering value. ROWS here uses id as a deterministic tie-breaker.'));
  return box;
}
function partitionVisual(state) {
  const data = partitionDemo(state.partition, state.count); const box = el('div');
  add(box, add(el('div', 'toolbar'), select('Operation', [['repartition', 'repartition'], ['coalesce', 'coalesce'], ['broadcast', 'broadcast']], state.partition, value => state.partition = value),
    select('Requested partitions', [1, 2, 4, 8].map(n => [n, n]), state.count, value => state.count = Number(value))));
  function buckets(groups) {
    const row = el('div', 'partitions'); groups.forEach((group, i) => {
      const bucket = add(el('div', 'partition'), el('h4', '', `P${i}`));
      group.forEach(token => bucket.append(el('span', `token key-${token.key}`, `${token.id}:${token.key}`)));
      if (!group.length) bucket.append(el('small', 'muted', 'empty')); row.append(bucket);
    }); return row;
  }
  add(box, el('h3', '', 'Input: four authored partitions'), buckets(data.source), el('p', 'exchange-label', data.exchange),
    el('h3', '', 'Output'), buckets(data.targets));
  if (data.broadcastCopies) add(box, el('p', 'callout', 'Small dimension replicated to four workers; streamed rows stay in place. Broadcast is network movement even though the streamed side is not shuffled.'));
  add(box, el('p', 'muted', 'Numbers are row-id:key. This uses an illustrative bucket rule, not Spark hashing or actual partition membership. coalesce cannot increase the four input partitions. Actual SparkLab plan evidence appears separately after Run.'));
  return box;
}
function stepDiagram(lesson, state) {
  const box = el('div', 'step-diagram'); const nodes = lesson.visual.nodes ?? [];
  if (nodes.length) {
    const graph = el('div', 'node-grid');
    nodes.forEach(node => { const incoming = (lesson.visual.edges ?? []).filter(e => e[1] === node.id).map(e => nodes.find(n => n.id === e[0])?.title ?? e[0]);
      graph.append(add(el('article', 'diagram-node'), el('strong', '', node.title), el('small', 'muted', incoming.length ? `After: ${incoming.join(', ')}` : 'Source / no predecessor'))); });
    add(box, graph, el('p', 'muted', 'Authored dependency diagram. Use Open lab for the existing interactive DAG and actual lab run states.'));
  }
  const list = el('ol', lesson.visual.kind === 'storage' ? 'storage-steps' : 'timeline-steps');
  lesson.visual.steps.forEach((step, i) => add(list, add(el('li', i === state.step ? 'active' : ''), el('strong', '', step.title), prose(step.body))));
  return add(box, list);
}
function visual(lesson) {
  const state = localVisual(lesson); const box = card(lesson.visual.title, badge('Teaching illustration - not execution evidence', 'illustrative'));
  if (lesson.visual.kind === 'join') box.append(joinVisual(lesson, state));
  else if (lesson.visual.kind === 'window') box.append(windowVisual(state));
  else if (lesson.visual.kind === 'partitions') box.append(partitionVisual(state));
  else box.append(stepDiagram(lesson, state));
  const step = lesson.visual.steps[state.step];
  const controls = el('div', 'toolbar');
  add(controls, button('Previous explanation', () => { stop(); state.step = Math.max(0, state.step - 1); render(); }, { disabled: state.step === 0 }),
    el('span', 'muted', `${state.step + 1} / ${lesson.visual.steps.length}`),
    button('Next explanation', () => { stop(); state.step = Math.min(lesson.visual.steps.length - 1, state.step + 1); render(); }, { disabled: state.step === lesson.visual.steps.length - 1 }));
  if (model.state.mode === 'watch') controls.append(button(timer ? 'Pause explanation' : 'Play explanation', () => play(lesson)));
  add(box, add(el('div', 'step-callout'), el('h3', '', step.title), prose(step.body)), controls);
  if (step.lines) box.append(button('Highlight source lines', () => send('focusStep', { index: state.step })));
  return box;
}
function metric(label, value) { return add(el('div', 'metric'), el('span', 'muted', label), el('strong', '', value)); }
function evidence(run, heading = 'Recorded execution') {
  if (!run) return card(heading, el('p', 'empty', 'No execution recorded for this lesson. Open the native example, start the existing runtime, then Run.'));
  const e = run.evidence ?? {}; const box = card(heading);
  add(box, badge(`Scope: ${run.scope}`), badge(e.status ?? 'Plan returned', e.status === 'error' ? 'warning' : ''), el('p', 'muted', `${run.at} | source ${run.sourceHash.slice(0, 12)}`));
  if (e.error) box.append(prose(`${e.error.type}: ${e.error.message}`));
  if (e.elapsed_ms !== undefined) box.append(metric('Measured local request / run ms', Number(e.elapsed_ms).toFixed(1)));
  if (e.result) { add(box, el('h3', '', 'Real local result rows'), dataTable(e.result.columns, e.result.rows, heading)); if (e.result.truncated) box.append(el('p', 'warning', 'Runtime result is truncated.')); }
  if (e.stdout) box.append(add(el('details'), el('summary', '', 'Python output'), el('pre', '', e.stdout)));
  if (e.compiledSql) box.append(add(el('details'), el('summary', '', 'Compiled local SQL'), el('pre', '', e.compiledSql)));
  if (typeof e.plan === 'string') add(box, badge(e.truth ?? 'DuckDB EXPLAIN ANALYZE'), el('pre', 'plan-text', e.plan));
  if (e.polarsPlan) add(box, badge(e.polarsPlan.truth), el('pre', 'plan-text', e.polarsPlan.text));
  if (e.simulation) {
    const simulation = e.simulation;
    add(box, el('hr'), el('h3', '', 'Spark teaching model'), badge('SIMULATED DISTRIBUTED BEHAVIOR', 'illustrative'));
    if (simulation.status === 'unavailable') box.append(prose(simulation.reason ?? 'Model not available for this run.'));
    else {
      add(box, el('p', 'muted', `${simulation.assumptionsKind ?? 'Assumed inputs'} | ${simulation.calibration ?? 'Not measured Spark telemetry'}`),
        add(el('div', 'metric-strip'), metric('Model seconds', simulation.totalDurationS?.toFixed(2) ?? 'n/a'), metric('Model shuffle GB', simulation.shuffleGb?.toFixed(4) ?? 'n/a'), metric('Modeled exchanges', simulation.exchanges?.length ?? 'n/a')));
      if (simulation.plan?.length) {
        const plan = el('ol', 'runtime-plan'); simulation.plan.forEach(node => plan.append(add(el('li'), el('strong', '', `${node.id}. ${node.operation}`), el('span', '', node.concept || node.dependency), el('small', 'muted', `Inputs: ${node.parents.join(', ') || node.source || 'source'}`)))); add(box, el('h4', '', 'Teaching logical plan'), plan);
      }
      if (simulation.exchanges?.length) { const list = el('ul'); simulation.exchanges.forEach(reason => list.append(el('li', '', reason))); add(box, el('h4', '', 'Why data moves'), list); }
      if (simulation.stages?.length) add(box, el('h4', '', 'Modeled stages and tasks'), dataTable(['stage_id', 'name', 'partitions', 'task_count', 'duration_s', 'shuffle_read_gb', 'shuffle_write_gb'], simulation.stages, 'Modeled Spark stages'));
    }
  }
  return box;
}
function tryView(lesson) {
  const box = el('div', 'try-view'); const runAllowed = lesson.code.language !== 'none';
  add(box, card('Work in the native editor', prose(runAllowed ? 'The same example stays on disk when views change. Your unsaved editor buffer is used. No script runs just because you read or open a topic.' : 'This topic uses its specialized lab. Open the lab or its linked exercise; there is no runnable scratch example here.'),
    add(el('div', 'toolbar'), button('Open native example', () => send('openExample'), { disabled: !runAllowed }),
      button('Run example', () => send('run'), { primary: true, disabled: !runAllowed || model.busy || model.runtime.status !== 'running' }),
      button('Run selection', () => send('runSelection'), { disabled: !runAllowed || model.busy || model.runtime.status !== 'running' }),
      button('EXPLAIN ANALYZE', () => send('explain'), { disabled: lesson.code.language !== 'sql' || model.busy || model.runtime.status !== 'running' }),
      button('Open lab', () => send('openLab'))),
    el('p', 'muted', ['python', 'polars'].includes(lesson.code.language) ? 'Python/Polars require the existing explicit trusted-local-Python opt-in. They are not sandboxed.' : 'SparkLab accepts a bounded PySpark subset; unsupported code is rejected, never executed as Python. SQL runs locally on DuckDB.')));
  if (model.run && !isCurrentRun(model.run, lesson.id, model.sourceHash)) box.append(el('p', 'warning', 'Source changed or file unavailable: this recorded result is not current. Run again.'));
  add(box, evidence(model.run), button('Pin this run as baseline', () => send('pin'), { disabled: !model.run || model.busy }));
  return box;
}
function exerciseView() {
  const e = model.exercise; const box = el('div');
  add(box, card(e.title, badge(e.language), badge(e.truth ?? 'See grading result'), prose(e.prompt),
    add(el('div', 'toolbar'), button('Open solution in Practice', () => send('openPractice')), button('Run visible tests', () => send('grade', { mode: 'run' }), { disabled: model.busy || Boolean(e.gradingNote) || model.runtime.status !== 'running' }),
      button('Submit solution', () => send('grade', { mode: 'submit' }), { primary: true, disabled: model.busy || Boolean(e.gradingNote) || model.runtime.status !== 'running' }))));
  add(box, card('Hints', ...(e.hints ?? []).map((hint, i) => prose(`${i + 1}. ${hint}`)), button('Reveal next hint', () => send('hint'), { disabled: !e.hintsRemaining || model.busy })));
  if (e.gradingNote) box.append(el('p', 'warning', e.gradingNote));
  e.sections?.forEach(section => box.append(card(section.title, prose(section.body))));
  for (const table of e.dataContext ?? []) box.append(card(`Input: ${table.name}`, dataTable(Object.keys(table.columns), table.sampleRows, `Public fixture ${table.name}`)));
  if (e.sparkPlan) box.append(card('Plan checks', badge('SparkLab model - not Apache Spark'), e.sparkPlan.checks.map(c => prose(c.description))));
  if (model.practiceResult?.exerciseKey === e.key) {
    const result = model.practiceResult;
    const checks = card(`Last ${result.mode}: ${result.status}`, badge(result.truth));
    result.checks.forEach(check => checks.append(add(el('div', `check ${check.passed ? 'passed' : 'failed'}`), el('strong', '', `${check.passed ? 'PASS' : 'FAIL'} - ${check.id}`), el('small', 'muted', `${check.kind ?? 'result'} | ${check.visibility}`), prose(check.message))));
    if (result.error) checks.append(prose(result.error.message)); box.append(checks);
  } else box.append(el('p', 'empty', 'No grading result for this exercise in the current session. Practice progress is still shown in the path.'));
  add(box, card('Feedback and reference', prose('The existing Practice view retains its hints, detailed expected/actual comparison, reference-solution unlock and spaced review. This page delegates to that same grader; it does not maintain a second score.'), button('Open full Practice feedback', () => send('openPractice'))));
  return box;
}
function compareView() {
  const verdict = compareRuns(model.pinned, model.run); const box = el('div');
  add(box, card('Compare recorded runs', prose(verdict.reason), button('Pin current run', () => send('pin'), { disabled: !model.run || model.busy })));
  if (verdict.compatible) add(box, add(el('div', 'comparison'), evidence(model.pinned, 'Pinned baseline'), evidence(model.run, 'Latest run')));
  else box.append(el('p', 'empty', 'Run an example, pin it, edit the same native file and run again. Comparisons are session-local; notes and reading progress persist.'));
  return box;
}
function notes(lesson) {
  const content = el('details', 'card notes'); add(content, el('summary', '', 'My notes and prediction'));
  const textarea = el('textarea'); textarea.rows = 4; textarea.maxLength = 8000; textarea.setAttribute('aria-label', 'Lesson notes'); textarea.dataset.focus = 'notes';
  textarea.value = drafts.has(lesson.id) ? drafts.get(lesson.id) : model.state.notes[lesson.id] ?? '';
  textarea.addEventListener('input', () => drafts.set(lesson.id, textarea.value));
  add(content, textarea, button('Save notes', () => { send('note', { text: textarea.value }); }), el('p', 'muted', 'Saved in VS Code workspace storage. Export to keep a portable copy. Notes are never sent to an AI or telemetry service.'));
  return content;
}
function render() {
  if (!model) return;
  const active = document.activeElement; const focus = active?.dataset?.focus;
  const selection = active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement ? [active.selectionStart, active.selectionEnd] : undefined;
  const scroll = window.scrollY; const wasNotesOpen = root.querySelector('.notes')?.open;
  const lesson = lessonById(model.state.lesson); const path = model.catalog.paths.find(p => p.id === model.state.path);
  root.className = `layout-${model.state.layout}`;
  const body = el('div', `workspace ${model.state.railHidden ? 'rail-hidden' : ''}`); const main = el('section', 'lesson-main');
  if (overview) main.append(learningMap());
  else {
    if (!model.hasWorkspace || !model.trusted) main.append(el('p', 'notice', 'Reading and teaching diagrams work without execution. Creating files and running code need a trusted local workspace.'));
    if (model.notice) add(main, el('p', 'notice', model.notice));
    if (model.progressError) add(main, el('p', 'warning', `Practice progress could not be read: ${model.progressError}`));
    const mode = model.state.mode;
    if (mode === 'read') add(main, add(el('div', 'read-grid'), course(lesson), visual(lesson)));
    else if (mode === 'watch') main.append(visual(lesson));
    else if (mode === 'try') main.append(tryView(lesson));
    else if (mode === 'exercise') main.append(exerciseView());
    else if (mode === 'inspect') add(main, visual(lesson), evidence(model.run, 'Runtime evidence (separate from illustration)'), button('Open current lab', () => send('openLab')));
    else if (mode === 'compare') main.append(compareView());
    add(main, notes(lesson));
    if (model.history?.length) add(main, add(el('details', 'card'), el('summary', '', 'Recent Learning runs (this session)'), dataTable(['at', 'lesson', 'language', 'scope'], model.history, 'Recorded Learning run metadata'), el('p', 'muted', 'Metadata only. Old source text is not retained or rerun. Pin a result before comparing.')));
    const index = path.lessons.indexOf(lesson.id);
    add(main, add(el('footer', 'lesson-footer'), button('Previous lesson', () => { stop(); send('previous'); }, { disabled: index === 0 }), el('span', 'muted', `${index + 1} / ${path.lessons.length}`), button('Next lesson', () => { stop(); send('next'); }, { primary: true, disabled: index === path.lessons.length - 1 })));
  }
  add(body, main, model.state.railHidden ? undefined : pathRail(path, lesson));
  const loading = el('div', 'sr-only', model.busy ? 'Operation running' : 'Ready'); loading.setAttribute('role', 'status');
  root.replaceChildren(header(lesson, path), body, loading);
  if (wasNotesOpen) { const n = root.querySelector('.notes'); if (n) n.open = true; }
  if (focus) {
    const target = [...root.querySelectorAll('[data-focus]')].find(node => node.dataset.focus === focus);
    if (target) { target.focus({ preventScroll: true }); if (selection && target.setSelectionRange && target.type !== 'search') { try { target.setSelectionRange(...selection); } catch {} } }
  }
  window.scrollTo(0, scroll);
}
window.addEventListener('message', event => {
  const data = event.data;
  if (data?.type === 'error') { stop(); root.replaceChildren(card('Learning workspace unavailable', prose(data.message))); return; }
  if (data?.type !== 'state' || !data.catalog || !data.state) return;
  const changed = model && (model.state.lesson !== data.state.lesson || model.state.mode !== data.state.mode);
  if (changed) stop(); model = data; render(); if (changed) window.scrollTo(0, 0);
});
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
window.addEventListener('beforeunload', stop);
send('ready');
