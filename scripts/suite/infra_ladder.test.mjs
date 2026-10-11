import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../..', import.meta.url));
const readJson = relative => JSON.parse(readFileSync(path.join(root, relative), 'utf8'));
const packDir = 'content/missions/infra-v1';

// The Infra Lab ladder: each rung starts with its intro mission, then the intermediate ones.
const RUNGS = [
  ['Terraform', ['tf-first-apply', 'lake-landing-zone', 'datalake-module']],
  ['Docker and Compose', ['docker-first-image', 'containerize-ingest-api', 'compose-keep-the-data']],
  ['VMs and monitoring', ['vm-health-check', 'etl-vm-memory-leak']],
  ['Kubernetes', ['k8s-first-deployment', 'zero-downtime-rollout', 'black-friday-autoscale']],
  ['Observability', ['alert-to-action', 'page-on-shir-outage']],
];

test('infra-v1 lists the missions as a ladder, an intro mission first on every rung', () => {
  const pack = readJson(`${packDir}/pack.json`);
  assert.deepEqual(pack.missions, RUNGS.flatMap(([, ids]) => ids));
  for (const [rung, [intro, ...rest]] of RUNGS) {
    assert.equal(readJson(`${packDir}/${intro}/mission.json`).level, 'intro', `${rung}: ${intro}`);
    for (const id of rest) assert.notEqual(readJson(`${packDir}/${id}/mission.json`).level, 'intro', `${rung}: ${id}`);
  }
});

test('every intro mission is simulated, has a reference, and at least four mutants', () => {
  for (const [, [intro]] of RUNGS) {
    const mission = readJson(`${packDir}/${intro}/mission.json`);
    assert.equal(mission.id, intro);
    assert.equal(mission.lab, 'infra');
    assert.match(mission.ticket.body.join('\n'), /simulated/);
    assert.ok(mission.reference.length >= 3 && mission.reference.every(step => typeof step.infra === 'string'), intro);
    assert.ok(mission.hints.length >= 3, intro);
    const mutants = readdirSync(path.join(root, packDir, intro, 'mutants'));
    assert.ok(mutants.length >= 4, `${intro}: ${mutants.length} mutants`);
    // Lines typed in the simulated shell never use pipes, chaining or substitution (the shell refuses them).
    for (const step of mission.reference) assert.doesNotMatch(step.infra, /[|;`]|&&|\$\(/, step.infra);
  }
});

test('infra-concepts-v1: concept checks only, answers kept server-side, backed by the observability sheet', () => {
  const dir = 'content/exercise-packs/infra-concepts-v1';
  const manifest = readJson(`${dir}/manifest.json`);
  assert.equal(manifest.id, 'infra-concepts-v1');
  const exercises = readJson(`${dir}/exercises.json`);
  const grading = readJson(`${dir}/grading.server.json`);
  assert.ok(exercises.length >= 15, `${exercises.length} cards`);
  const ids = exercises.map(e => e.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.deepEqual(Object.keys(grading).sort(), [...ids].sort());
  const sheet = readFileSync(path.join(root, 'content/reference/observability.md'), 'utf8');
  assert.match(sheet, /^# Observability/);
  for (const exercise of exercises) {
    assert.equal(exercise.language, 'quiz', exercise.id);
    assert.equal(exercise.truth, 'concept-check', exercise.id);
    assert.deepEqual(exercise.context_refs, ['reference/observability.md'], exercise.id);
    assert.ok(existsSync(path.join(root, 'content', exercise.context_refs[0])));
    assert.match(exercise.starter_source, /^Concept check \(no execution\)/);
    assert.match(exercise.starter_source, /\nanswer:\n$/);
    const hidden = grading[exercise.id].fixtures.find(f => f.id === 'answer').scenario;
    assert.ok(hidden.why.length > 40, exercise.id);
    // The private answer and its explanation never reach the public exercise file.
    assert.ok(!JSON.stringify(exercise).includes(hidden.why), exercise.id);
  }
  const topics = new Set(exercises.map(e => e.topics[1]));
  assert.deepEqual([...topics].sort(), ['grafana', 'promql', 'signals', 'slo']);
});
