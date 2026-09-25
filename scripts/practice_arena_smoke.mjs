import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

// Practice arena (V2-1): one card per problem with a language switch, over the real packs.
const dir = await mkdtemp(path.join(tmpdir(), "datapass-practice-arena-"));
const entry = path.join(dir, "entry.ts");
const outfile = path.join(dir, "practice-arena.mjs");

try {
  await writeFile(entry, [
    `export * from ${JSON.stringify(path.resolve("src/platform/practiceProblems.ts"))};`,
    `export { recordGrade, recordOpened, EMPTY_FILTERS } from ${JSON.stringify(path.resolve("src/platform/practiceProgress.ts"))};`
  ].join("\n"));
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  // The catalog as src/exerciseCatalog.ts builds it (key, id and order), from the shipped packs.
  const packsRoot = path.resolve("content/exercise-packs");
  const catalog = [];
  const scenarioIds = new Map();
  for (const folder of (await readdir(packsRoot)).sort()) {
    const read = async name => existsSync(path.join(packsRoot, folder, name))
      ? JSON.parse(await readFile(path.join(packsRoot, folder, name), "utf8")) : undefined;
    const manifest = await read("manifest.json");
    if (manifest?.enabled === false) continue;
    const packId = manifest?.id ?? folder;
    const packTitle = manifest?.title ?? packId;
    const base = { packId, packTitle, version: "1", starterSource: "", sections: [], hints: [], dataContext: [] };
    for (const item of (await read("exercises.json")) ?? []) {
      catalog.push({ ...base, key: `${packId}/${item.id}/${item.language}`, id: item.id, title: item.title,
        difficulty: item.difficulty ?? "unspecified", language: item.language, prompt: item.prompt ?? "", topics: item.topics ?? [] });
    }
    for (const scenario of (await read("scenarios.json")) ?? []) {
      const id = scenario.semantic.id;
      scenarioIds.set(`${packId}/${id}`, Object.keys(scenario.variants));
      for (const language of Object.keys(scenario.variants)) {
        catalog.push({ ...base, key: `${packId}/${id}/${language}`, id: `${id}-${language}`, title: scenario.common.title,
          difficulty: scenario.common.difficulty ?? "unspecified", language, prompt: scenario.common.prompt ?? "",
          topics: scenario.common.topics ?? [] });
      }
    }
  }
  catalog.sort((a, b) => a.packTitle.localeCompare(b.packTitle) || a.title.localeCompare(b.title) || a.language.localeCompare(b.language));

  const problems = mod.groupProblems(catalog);
  assert.equal(problems.reduce((n, p) => n + p.variants.length, 0), catalog.length, "every variant is on exactly one card");
  assert.ok(scenarioIds.size >= 70, "the semantic packs ship their scenarios");
  for (const [key, languages] of scenarioIds) {
    const problem = problems.find(p => p.key === key);
    assert.ok(problem, `semantic scenario ${key} is one problem`);
    assert.deepEqual(problem.variants.map(v => v.language).sort(), [...languages].sort(), `${key}: one variant per language`);
    const order = problem.variants.map(v => mod.LANGUAGE_ORDER.indexOf(v.language));
    assert.deepEqual(order, [...order].sort((a, b) => a - b), `${key}: SQL first, then dialects, dataframes, dbt`);
  }
  const zilla = problems.find(p => p.key === "zilla-v1/zilla-001-popular-videos");
  assert.deepEqual(zilla.variants.map(v => mod.languageLabel(v.language)), ["SQL", "Snowflake", "Python", "Polars", "PySpark", "dbt"]);
  assert.ok(problems.length < catalog.length / 1.5, `${problems.length} cards for ${catalog.length} variants`);

  // Progress stays per variant; the card summarizes it.
  const now = "2026-09-25T18:00:00Z";
  let progress = mod.recordGrade(undefined, "zilla-v1/zilla-001-popular-videos/polars", "1", "submit", "passed", now);
  progress = mod.recordOpened(progress, "zilla-v1/zilla-001-popular-videos/sql", now);
  assert.deepEqual(mod.problemSummary(zilla, progress), { status: "solved", solved: ["polars"], attempted: ["sql"] });
  assert.equal(Object.keys(progress.exercises).length, 2, "no problem-level record is written");
  const counts = mod.problemCounts(problems, progress);
  assert.deepEqual([counts.solved, counts.attempted, counts["not-started"]], [1, 0, problems.length - 1]);

  // Filters: the language filter keeps problems offered in it, and the status then reads that variant.
  const only = filters => mod.filterProblems(problems, progress, { ...mod.EMPTY_FILTERS, ...filters }).map(p => p.key);
  assert.deepEqual(only({ status: "solved" }), [zilla.key]);
  assert.deepEqual(only({ status: "solved", language: "polars" }), [zilla.key]);
  assert.deepEqual(only({ status: "solved", language: "sql" }), []);
  assert.ok(only({ status: "attempted", language: "sql" }).includes(zilla.key));
  assert.ok(only({ language: "tsql" }).every(key => problems.find(p => p.key === key).variants.some(v => v.language === "tsql")));
  assert.deepEqual(only({ query: "zilla-001-popular-videos-snowflake" }), [zilla.key], "a variant id finds its problem");
  assert.ok(only({ query: "snowflake" }).includes(zilla.key), "the language label is searchable");

  // The variant a card shows.
  assert.equal(mod.pickVariant(zilla, {}).language, "sql");
  assert.equal(mod.pickVariant(zilla, { preferred: "polars" }).language, "polars");
  assert.equal(mod.pickVariant(zilla, { filter: "snowflake", preferred: "polars" }).language, "snowflake");
  assert.equal(mod.pickVariant(zilla, { chosen: "python", filter: "snowflake" }).language, "python");
  assert.equal(mod.pickVariant(zilla, { chosen: "tsql", preferred: "cobol" }).language, "sql", "unknown languages fall back");
  assert.equal(mod.problemKeyOf("zilla-v1/zilla-001-popular-videos/dbt-sql"), zilla.key);
  assert.deepEqual(mod.restoreLanguages({ a: "sql", b: 3, c: "../x" }), { a: "sql" });
  assert.deepEqual(mod.restoreLanguages(["sql"]), {});

  console.log(`Practice arena smoke passed: ${problems.length} problems for ${catalog.length} variants.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
