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
    `export * from ${JSON.stringify(path.resolve("src/platform/practiceReview.ts"))};`,
    `export * from ${JSON.stringify(path.resolve("src/platform/practiceInterview.ts"))};`,
    `export { recordGrade, recordInterview, recordOpened, parsePracticeProgress, practiceStatus, EMPTY_FILTERS } from ${JSON.stringify(path.resolve("src/platform/practiceProgress.ts"))};`
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

  // Spaced review: the Leitner schedule (1, 3, 7, 14, 30, 60 days), per variant, on local calendar days.
  assert.deepEqual(mod.REVIEW_INTERVALS_DAYS, [1, 3, 7, 14, 30, 60]);
  assert.equal(mod.addDays("2026-09-30", 1), "2026-10-01");
  assert.equal(mod.addDays("2026-12-31", 60), "2027-03-01");
  assert.equal(mod.daysBetween("2026-09-25", "2026-10-02"), 7);
  assert.equal(mod.daysBetween("2026-10-02", "2026-09-25"), -7);
  const at = (day, time = "12:00:00") => `${day}T${time}`; // local time, as the host's clock
  const key = "zilla-v1/zilla-001-popular-videos/sql";
  const review = p => p.exercises[key].review;
  let r = mod.recordOpened(undefined, key, at("2026-09-25"));
  assert.equal(review(r), undefined, "opening stores nothing new");
  assert.deepEqual(mod.reviewState(r.exercises[key]), { box: 0, due: "2026-09-26" }, "a started, unsolved variant comes back the next day");
  r = mod.recordGrade(r, key, "1", "run", "failed", at("2026-09-25"));
  assert.equal(review(r), undefined, "Run visible never moves a box");
  r = mod.recordGrade(r, key, "1", "submit", "failed", at("2026-09-25"));
  assert.deepEqual(review(r), { box: 1, due: "2026-09-26" });
  r = mod.recordGrade(r, key, "1", "submit", "passed", at("2026-09-25", "23:30:00"));
  assert.deepEqual(review(r), { box: 1, due: "2026-09-26" }, "a pass before the due day does not climb");
  const climb = [["2026-09-26", 2, "2026-09-29"], ["2026-10-01", 3, "2026-10-08"], ["2026-10-08", 4, "2026-10-22"],
    ["2026-10-22", 5, "2026-11-21"], ["2026-11-25", 6, "2027-01-24"], ["2027-01-24", 6, "2027-03-25"]];
  for (const [day, box, due] of climb) {
    r = mod.recordGrade(r, key, "1", "submit", "passed", at(day, "08:00:00"));
    assert.deepEqual(review(r), { box, due }, `pass on ${day}`);
  }
  r = mod.recordGrade(r, key, "1", "submit", "error", at("2027-02-01"));
  assert.deepEqual(review(r), { box: 1, due: "2027-02-02" }, "an error sends it back to box 1");
  assert.equal(mod.practiceStatus(r.exercises[key]), "solved", "a failure never unsolves");
  const reread = mod.parsePracticeProgress(JSON.parse(JSON.stringify(r)));
  assert.deepEqual(reread.exercises[key].review, { box: 1, due: "2027-02-02" }, "the schedule survives progress.json");
  const odd = mod.parsePracticeProgress({ exercises: {
    "p/a/sql": { attempts: 0, review: { box: 2, due: "2026-10-01" } },
    "p/b/sql": { attempts: 1, openedAt: at("2026-09-01"), review: { box: 7, due: "2026-10-01" } },
    "p/c/sql": { attempts: 1, openedAt: at("2026-09-01"), review: { box: 1, due: "tomorrow" } }
  } });
  assert.deepEqual(odd.exercises["p/a/sql"].review, { box: 2, due: "2026-10-01" }, "a record with only a schedule is kept");
  assert.equal(odd.exercises["p/b/sql"].review, undefined);
  assert.equal(odd.exercises["p/c/sql"].review, undefined);
  const legacy = { attempts: 2, solved: { at: at("2026-09-20"), version: "1" }, last: { at: at("2026-09-21"), mode: "submit", status: "passed", version: "1" } };
  assert.deepEqual(mod.reviewState(legacy), { box: 1, due: "2026-09-22" }, "a variant solved before the schedule existed");

  // The review queue: most overdue first, then the weakest box; one card per problem.
  const records = {
    "zilla-v1/zilla-001-popular-videos/sql": { attempts: 1, review: { box: 3, due: "2026-09-20" } },
    "zilla-v1/zilla-001-popular-videos/polars": { attempts: 1, review: { box: 1, due: "2026-09-25" } },
    "zilla-v1/zilla-002-crm-orders/sql": { attempts: 1, review: { box: 1, due: "2026-09-20" } },
    "zilla-v1/zilla-003-landlord-income/sql": { attempts: 1, review: { box: 2, due: "2026-09-26" } }
  };
  const queue = mod.dueReviews(Object.keys(records), records, "2026-09-25");
  assert.deepEqual(queue.map(item => [item.key.split("/")[1], item.box, item.overdue]),
    [["zilla-002-crm-orders", 1, 5], ["zilla-001-popular-videos", 3, 5], ["zilla-001-popular-videos", 1, 0]]);
  const dueCards = mod.dueProblems(problems, { exercises: records }, "2026-09-25");
  assert.deepEqual(dueCards.map(item => [item.problem.key, item.language, item.alsoDue]),
    [["zilla-v1/zilla-002-crm-orders", "sql", []], ["zilla-v1/zilla-001-popular-videos", "sql", ["polars"]]]);
  assert.deepEqual(mod.upcomingReviews(problems, { exercises: records }, "2026-09-25"), { scheduled: 4, next: "2026-09-26" });
  assert.equal(mod.reviewLabel(records["zilla-v1/zilla-001-popular-videos/sql"], "2026-09-25"), "Review due for 5 days · box 3 of 6");
  assert.equal(mod.reviewLabel(records["zilla-v1/zilla-003-landlord-income/sql"], "2026-09-25"), "Next review tomorrow · box 2 of 6");
  assert.equal(mod.reviewLabel(undefined, "2026-09-25"), undefined);

  // Interview mode: the draw, the tracking, the summary and its history in progress.json.
  assert.equal(mod.problemFamily(zilla)?.id, "logic", "zilla-001 filters rows");
  const familyOf = key => mod.problemFamily(problems.find(p => p.key === key))?.id;
  const classic = problems.filter(p => mod.problemFamily(p)).length;
  assert.ok(classic / problems.length > 0.6, `most problems have a pattern family (${classic}/${problems.length})`);
  const mixed = { format: "mixed", count: 3, difficulty: "", family: "" };
  for (let seed = 1; seed <= 40; seed++) {
    const drawn = mod.drawInterview(problems, mixed, mod.seededRandom(seed));
    assert.deepEqual(drawn.map(item => item.language), ["sql", "python", "sparklab"], "a mixed series cycles SQL, Python, PySpark");
    assert.equal(new Set(drawn.map(item => item.problemKey)).size, 3, "no problem twice");
    assert.equal(new Set(drawn.map(item => item.family)).size, 3, `seed ${seed}: three different patterns`);
    for (const item of drawn) {
      assert.ok(item.family, "only problems with a classic pattern when enough exist");
      assert.equal(item.exerciseKey, `${item.problemKey}/${item.language}`);
      assert.equal(familyOf(item.problemKey), item.family);
    }
  }
  assert.deepEqual(mod.drawInterview(problems, mixed, mod.seededRandom(7)), mod.drawInterview(problems, mixed, mod.seededRandom(7)),
    "a seed replays its draw");
  const six = mod.drawInterview(problems, { ...mixed, count: 6 }, mod.seededRandom(3));
  assert.deepEqual(six.map(item => item.language), ["sql", "python", "sparklab", "sql", "python", "sparklab"]);
  const windows = mod.drawInterview(problems, { format: "fixed", language: "polars", count: 4, difficulty: "hard", family: "windows" },
    mod.seededRandom(11));
  assert.ok(windows.length >= 1);
  for (const item of windows) {
    const problem = problems.find(p => p.key === item.problemKey);
    assert.equal(item.language, "polars");
    assert.equal(problem.difficulty, "hard");
    assert.equal(item.family, "windows");
  }
  const tooMany = mod.drawInterview(problems, { format: "fixed", language: "sql", count: 8, difficulty: "", family: "strings" }, mod.seededRandom(5));
  assert.ok(tooMany.length <= 8 && new Set(tooMany.map(i => i.problemKey)).size === tooMany.length);
  assert.deepEqual(mod.drawInterview(problems, { format: "fixed", language: "cobol", count: 3, difficulty: "", family: "" }, mod.seededRandom(1)), []);
  const remoteOnly = [{ ...zilla, key: "p/remote", variants: [{ ...zilla.variants[0], key: "p/remote/sql", gradingNote: "remote" }] }];
  assert.deepEqual(mod.drawInterview(remoteOnly, { ...mixed, count: 1 }, mod.seededRandom(1)), [], "never a problem graded elsewhere");
  assert.equal(mod.defaultLimitMinutes(3), 45);

  const start = "2026-09-26T10:00:00.000Z";
  const drawn = mod.drawInterview(problems, mixed, mod.seededRandom(2));
  const [first, second, third] = drawn.map(item => item.exerciseKey);
  let recs = { [first]: { attempts: 4, last: { mode: "submit", status: "passed", at: "2026-09-20T10:00:00.000Z" } } };
  let session = mod.startInterview(drawn, mixed, 45, recs, start);
  assert.deepEqual(session.items.map(item => [item.seenAttempts, item.submits]), [[4, 0], [0, 0], [0, 0]]);
  assert.equal(mod.trackInterview(session, recs), session, "nothing new, same session");
  const grade = (key, mode, status, at) => {
    const old = recs[key] ?? { attempts: 0 };
    recs = { ...recs, [key]: { attempts: old.attempts + 1, last: { mode, status, at } } };
    session = mod.trackInterview(session, recs);
  };
  grade(first, "run", "failed", "2026-09-26T10:03:00.000Z");
  grade(first, "submit", "failed", "2026-09-26T10:05:00.000Z");
  grade(first, "submit", "passed", "2026-09-26T10:09:30.000Z");
  grade(first, "submit", "failed", "2026-09-26T10:10:00.000Z");
  grade(third, "submit", "passed", "2026-09-26T10:50:00.000Z");
  assert.deepEqual(session.items.map(item => [item.submits, item.passedAt ?? null]),
    [[3, "2026-09-26T10:09:30.000Z"], [0, null], [1, "2026-09-26T10:50:00.000Z"]]);
  const record = mod.summarizeInterview(session, "2026-09-26T10:52:00.000Z");
  assert.equal(record.elapsedSeconds, 52 * 60);
  assert.deepEqual(record.items.map(item => [item.solved, item.solvedAfterSeconds ?? null, item.submits]),
    [[true, 570, 3], [false, null, 0], [true, 3000, 1]]);
  assert.equal(mod.trackInterview({ ...session, finishedAt: "x" }, {}).finishedAt, "x");
  let kept = mod.recordInterview(undefined, record);
  assert.deepEqual(mod.parsePracticeProgress(JSON.parse(JSON.stringify(kept))).interviews, [record], "the summary survives progress.json");
  for (let i = 0; i < 25; i++) kept = mod.recordInterview(kept, { ...record, at: `2026-10-${String(i + 1).padStart(2, "0")}T10:00:00.000Z` });
  assert.equal(kept.interviews.length, mod.INTERVIEW_HISTORY, "only the last 20 series are kept");
  assert.equal(kept.interviews.at(-1).at, "2026-10-25T10:00:00.000Z");
  assert.throws(() => mod.recordInterview(kept, { ...record, items: [{ key: "../x", solved: true, submits: 1 }] }), /Invalid interview/);
  assert.throws(() => mod.recordInterview(kept, { ...record, format: "exam" }), /Invalid interview/);
  assert.equal(mod.parseInterviews([{ ...record, items: [] }, record, "junk"]).length, 1, "malformed series are dropped");
  assert.equal(mod.clock(0), "0:00");
  assert.equal(mod.clock(754), "12:34");
  assert.equal(mod.clock(3725), "1:02:05");

  console.log(`Practice arena smoke passed: ${problems.length} problems for ${catalog.length} variants.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
