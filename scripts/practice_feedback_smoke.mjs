import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

// Practice feedback (V1-1): visible-fixture row diff with the grader's rules, hints, reference solutions.
const dir = await mkdtemp(path.join(tmpdir(), "datapass-practice-feedback-"));
const outfile = path.join(dir, "practice-feedback.mjs");

try {
  await esbuild.build({ entryPoints: ["src/platform/practiceFeedback.ts"], bundle: true, platform: "node", format: "esm",
    target: "node20", outfile, logLevel: "silent" });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);
  const kinds = diff => diff.rows.map(row => row.kind);

  // The contract as the packs write it.
  const v = mod.rowValidation({ kind: "rows", ordered: false, duplicate_sensitive: true, relative_tolerance: 1e-9,
    absolute_tolerance: 1e-6, forbidden_extra_columns: true, exact_schema: ["id", "amount"] });
  assert.deepEqual(v, { ordered: false, duplicateSensitive: true, relativeTolerance: 1e-9, absoluteTolerance: 1e-6,
    forbiddenExtraColumns: true, exactSchema: ["id", "amount"], aggregates: undefined });
  assert.equal(mod.rowValidation(undefined).ordered, false);
  assert.equal(mod.rowValidation({ duplicate_sensitive: false }).duplicateSensitive, false);

  // Unordered: order does not matter, one missing and one unexpected row are paired as such.
  const expected = [{ id: 1, amount: 10 }, { id: 2, amount: 20 }, { id: 3, amount: 30 }];
  let d = mod.diffRows(expected, [{ id: 3, amount: 30 }, { id: 1, amount: 10 }], v);
  assert.deepEqual(d.counts, { match: 2, differs: 0, missing: 1, unexpected: 0 });
  assert.deepEqual(d.rows.find(row => row.kind === "missing").expected, { id: 2, amount: 20 });
  d = mod.diffRows(expected, [{ id: 1, amount: 10 }, { id: 2, amount: 21 }, { id: 3, amount: 30 }], v);
  assert.deepEqual(d.counts, { match: 2, differs: 0, missing: 1, unexpected: 1 });

  // Tolerance, as math.isclose(rel_tol, abs_tol); types matter ("1" is not 1), NULL equals NULL.
  assert.equal(mod.valuesEqual(0.1 + 0.2, 0.3, v), true);
  assert.equal(mod.valuesEqual(10, 10.0000005, v), true);
  assert.equal(mod.valuesEqual(10, 10.01, v), false);
  assert.equal(mod.valuesEqual("1", 1, v), false);
  assert.equal(mod.valuesEqual(null, null, v), true);
  assert.equal(mod.valuesEqual(true, 1, v), false);

  // Columns: missing, extra (forbidden or ignored), and a right schema in the wrong order.
  d = mod.diffRows([{ id: 1, amount: 10 }], [{ id: 1 }], v);
  assert.deepEqual(d.missingColumns, ["amount"]);
  assert.deepEqual(kinds(d), ["missing", "unexpected"]);
  d = mod.diffRows([{ id: 1, amount: 10 }], [{ id: 1, amount: 10, note: "x" }], v);
  assert.deepEqual(d.extraColumns, ["note"]);
  assert.equal(d.extraColumnsForbidden, true);
  assert.deepEqual(kinds(d), ["missing", "unexpected"], "an extra column fails the row when the contract forbids it");
  d = mod.diffRows([{ id: 1, amount: 10 }], [{ id: 1, amount: 10, note: "x" }], { ...v, forbiddenExtraColumns: false });
  assert.deepEqual(kinds(d), ["match"], "and is ignored otherwise");
  d = mod.diffRows([{ id: 1, amount: 10 }], [{ amount: 10, id: 1 }], v);
  assert.equal(d.columnOrderDiffers, true);
  assert.deepEqual(kinds(d), ["match"]);

  // Ordered: rows are compared position by position and the differing cells are named.
  const ordered = { ...v, ordered: true };
  d = mod.diffRows(expected, [{ id: 1, amount: 10 }, { id: 3, amount: 30 }, { id: 2, amount: 20 }], ordered);
  assert.deepEqual(kinds(d), ["match", "differs", "differs"]);
  assert.deepEqual(d.rows[1].cells, ["id", "amount"]);
  d = mod.diffRows(expected, [{ id: 1, amount: 10 }], ordered);
  assert.deepEqual(kinds(d), ["match", "missing", "missing"]);
  assert.match(d.notes[0], /order matters/);

  // Duplicates: counted unless the contract says they count once.
  d = mod.diffRows([{ id: 1 }], [{ id: 1 }, { id: 1 }], { ...v, forbiddenExtraColumns: false });
  assert.deepEqual(kinds(d), ["match", "unexpected"]);
  d = mod.diffRows([{ id: 1 }], [{ id: 1 }, { id: 1 }], { ...v, forbiddenExtraColumns: false, duplicateSensitive: false });
  assert.deepEqual(kinds(d), ["match"]);

  // Bipartite matching, like the grader: a greedy pairing would leave a valid row unmatched.
  const loose = { ordered: false, absoluteTolerance: 1, relativeTolerance: 0 };
  d = mod.diffRows([{ x: 1 }, { x: 2 }], [{ x: 1.5 }, { x: 1 }], loose);
  assert.deepEqual(d.counts, { match: 2, differs: 0, missing: 0, unexpected: 0 });

  // The reference solution unlocks after a pass or three failed gradings.
  assert.equal(mod.solutionUnlocked(undefined), false);
  assert.equal(mod.solutionUnlocked({ failures: 2 }), false);
  assert.equal(mod.solutionUnlocked({ failures: mod.SOLUTION_AFTER_FAILURES }), true);
  assert.equal(mod.solutionUnlocked({ solved: { at: "t", version: "1" } }), true);

  // Every shipped exercise that offers a solution has one in its pack, direct or per scenario variant.
  let found = 0;
  for (const pack of await readdir("content/exercise-packs")) {
    let grading;
    try {
      grading = JSON.parse(await readFile(path.join("content/exercise-packs", pack, "grading.server.json"), "utf8"));
    } catch {
      continue;
    }
    for (const file of ["exercises.json", "scenarios.json"]) {
      let items;
      try {
        items = JSON.parse(await readFile(path.join("content/exercise-packs", pack, file), "utf8"));
      } catch {
        continue;
      }
      for (const item of items) {
        const entries = item.variants
          ? Object.keys(item.variants).map(language => ({ id: `${item.semantic?.id ?? item.common.id}-${language}`, language, solution: item.common.solution }))
          : [{ id: item.id, language: item.language, solution: item.solution }];
        for (const entry of entries) {
          if (entry.solution?.available !== true) continue;
          const code = mod.referenceSolution(grading, entry.id, entry.language);
          assert.equal(typeof code, "string", `${pack}/${entry.id}/${entry.language} offers a solution the pack does not ship`);
          found += 1;
        }
      }
    }
  }
  assert.ok(found > 250, `found ${found} reference solutions`);
  assert.equal(mod.referenceSolution({ a: { solution: "S" } }, "a", "sql"), "S");
  assert.equal(mod.referenceSolution({ s: { solutions: { pandas: "P" } } }, "s-pandas", "pandas"), "P");
  assert.equal(mod.referenceSolution({}, "nope", "sql"), undefined);

  console.log(`Practice feedback smoke passed (${found} reference solutions found).`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
