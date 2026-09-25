import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

// Practice progress (V1-2): statuses, filters, and the shared .datapass/progress.json with Projects.
const dir = await mkdtemp(path.join(tmpdir(), "datapass-practice-progress-"));
const entry = path.join(dir, "entry.ts");
const outfile = path.join(dir, "practice-progress.mjs");

try {
  await writeFile(entry, [
    `export * from ${JSON.stringify(path.resolve("src/platform/practiceProgress.ts"))};`,
    `export { parseProgress, serializeProgress, setManual, normalizeProject } from ${JSON.stringify(path.resolve("src/platform/projects.ts"))};`
  ].join("\n"));
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  const key = "sql-lab-v1/sql-left-join/sql";
  const now = "2026-09-25T18:00:00Z";
  let progress = mod.emptyPracticeProgress();
  assert.equal(mod.practiceStatus(progress.exercises[key]), "not-started");

  progress = mod.recordOpened(progress, key, now);
  assert.equal(mod.practiceStatus(progress.exercises[key]), "attempted", "opening an exercise starts it");
  assert.equal(progress.exercises[key].attempts, 0);
  progress = mod.recordOpened(progress, key, "2026-09-26T00:00:00Z");
  assert.equal(progress.exercises[key].openedAt, now, "the first opening is kept");

  progress = mod.recordGrade(progress, key, "1", "run", "passed", now);
  assert.equal(mod.practiceStatus(progress.exercises[key]), "attempted", "Run visible never solves");
  progress = mod.recordGrade(progress, key, "1", "submit", "failed", now);
  assert.equal(mod.practiceStatus(progress.exercises[key]), "attempted");
  progress = mod.recordGrade(progress, key, "1", "submit", "passed", "2026-09-25T18:05:00Z");
  assert.equal(mod.practiceStatus(progress.exercises[key]), "solved");
  assert.deepEqual(progress.exercises[key].solved, { at: "2026-09-25T18:05:00Z", version: "1" });
  progress = mod.recordGrade(progress, key, "2", "submit", "failed", "2026-09-27T00:00:00Z");
  assert.equal(mod.practiceStatus(progress.exercises[key]), "solved", "a later failure never unsolves");
  assert.equal(progress.exercises[key].attempts, 4);
  assert.equal(progress.exercises[key].failures, 2, "failed gradings are counted (they unlock the reference solution)");
  progress = mod.revealHint(progress, key, 2);
  progress = mod.revealHint(progress, key, 2);
  progress = mod.revealHint(progress, key, 2);
  assert.equal(progress.exercises[key].hintsRevealed, 2, "never beyond the exercise's hints");
  progress = mod.recordSolutionViewed(progress, key, now);
  progress = mod.recordSolutionViewed(progress, key, "2026-09-28T00:00:00Z");
  assert.equal(progress.exercises[key].solutionViewedAt, now);
  const hintOnly = mod.parsePracticeProgress({ exercises: { "p/h/sql": { attempts: 0, hintsRevealed: 1 } } });
  assert.equal(hintOnly.exercises["p/h/sql"].hintsRevealed, 1, "a record with only a revealed hint is kept");
  assert.deepEqual(progress.exercises[key].last, { mode: "submit", status: "failed", at: "2026-09-27T00:00:00Z", version: "2" });
  assert.throws(() => mod.recordOpened(progress, "../escape", now), /Invalid exercise key/);

  // Parsing is strict per entry and never invents a solve.
  const parsed = mod.parsePracticeProgress({
    exercises: {
      [key]: progress.exercises[key],
      "bad key": { attempts: 3 },
      "p/x/sql": { attempts: -2, solved: { at: "" }, last: { mode: "run", status: "maybe", at: now, version: "1" } },
      "p/y/sql": { attempts: 1.5, openedAt: now }
    }
  });
  assert.deepEqual(Object.keys(parsed.exercises).sort(), [key, "p/y/sql"].sort());
  assert.equal(parsed.exercises["p/y/sql"].attempts, 0);
  assert.equal(mod.practiceStatus(parsed.exercises["p/y/sql"]), "attempted");

  // The shared file: Projects' parser keeps the practice section and a Projects write does not drop it.
  const file = mod.serializeProgress({ schema_version: 1, projects: {}, practice: progress });
  const read = mod.parseProgress(file);
  assert.equal(read.error, undefined);
  assert.equal(mod.practiceStatus(read.document.practice.exercises[key]), "solved");
  const { project } = mod.normalizeProject({
    id: "demo", title: "Demo", story: "A story.", steps: [{ id: "one", title: "One", module: "practice", instructions: "Do it.",
      open: { module: "practice" } }]
  }, ["practice"]);
  const ticked = mod.setManual(read.document, project, "one", true, now);
  assert.equal(mod.practiceStatus(mod.parseProgress(mod.serializeProgress(ticked)).document.practice.exercises[key]), "solved");
  assert.equal(mod.parseProgress(JSON.stringify({ schema_version: 1, projects: {} })).document.practice, undefined);

  // Filters and counts.
  const exercise = (id, language, difficulty, topics) => ({
    key: `pack/${id}/${language}`, packId: "pack", packTitle: "Pack", id, version: "1", title: `Title ${id}`, difficulty,
    language, prompt: "", starterSource: "", topics, sections: [], hints: [], dataContext: []
  });
  const catalog = [
    exercise("a", "sql", "easy", ["joins"]),
    exercise("b", "sql", "hard", ["windows"]),
    exercise("c", "pandas", "medium", ["joins", "nulls"]),
    exercise("d", "sparklab", "medium", ["partitioning"])
  ];
  let state = mod.recordGrade(undefined, "pack/a/sql", "1", "submit", "passed", now);
  state = mod.recordOpened(state, "pack/c/pandas", now);
  assert.deepEqual(mod.practiceCounts(catalog, state), { solved: 1, attempted: 1, "not-started": 2 });
  const only = filters => mod.filterExercises(catalog, state, { ...mod.EMPTY_FILTERS, ...filters }).map(e => e.id);
  assert.deepEqual(only({}), ["a", "b", "c", "d"]);
  assert.deepEqual(only({ status: "solved" }), ["a"]);
  assert.deepEqual(only({ status: "not-started" }), ["b", "d"]);
  assert.deepEqual(only({ topic: "joins" }), ["a", "c"]);
  assert.deepEqual(only({ topic: "joins", status: "attempted" }), ["c"]);
  assert.deepEqual(only({ difficulty: "medium", language: "sparklab" }), ["d"]);
  assert.deepEqual(only({ query: "title b" }), ["b"]);
  const options = mod.filterOptions(catalog);
  assert.deepEqual(options.difficulties, ["easy", "medium", "hard"], "difficulties keep their natural order");
  assert.deepEqual(options.languages, ["pandas", "sparklab", "sql"]);
  assert.deepEqual(options.topics, ["joins", "nulls", "partitioning", "windows"]);
  assert.deepEqual(mod.restoreFilters({ status: "done", topic: "joins", query: 3 }), { ...mod.EMPTY_FILTERS, topic: "joins" });

  console.log("Practice progress smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
