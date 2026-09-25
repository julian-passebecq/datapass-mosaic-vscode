import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-missions-ui-"));

try {
  const outfile = path.join(dir, "missions.mjs");
  await esbuild.build({ entryPoints: ["src/platform/missions.ts"], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  const m = await import(pathToFileURL(outfile).href);

  // Every shipped mission reads back with its ticket, criteria, hints and batches.
  const packDir = "content/missions/dbt-v1";
  const pack = JSON.parse(await readFile(`${packDir}/pack.json`, "utf8"));
  const missions = [];
  for (const id of pack.missions) {
    const mission = m.toMissionView(JSON.parse(await readFile(`${packDir}/${id}/mission.json`, "utf8")), "dbt-v1");
    assert.ok(mission, id);
    assert.equal(mission.id, id);
    assert.ok(mission.ticket.body.length > 100 && mission.acceptance.length >= 3 && mission.hints.length >= 3, id);
    assert.ok(mission.batches.length >= 1, id);
    missions.push(mission);
  }
  assert.equal(missions.length, 5);
  assert.deepEqual(missions.find(item => item.id === "sales-board").dctBoards, ["charts/sales.yml"]);
  assert.deepEqual(missions.find(item => item.id === "incremental-order-lines").batches.map(b => b.id), ["day-1", "day-2"]);

  // The learner's copy never gets the reference or the mutants: they are outside project/ and out of the VSIX.
  for (const id of pack.missions) {
    const entries = await readdir(`${packDir}/${id}`);
    assert.ok(entries.includes("project") && entries.includes("solution"), id);
  }
  const vscodeignore = await readFile(".vscodeignore", "utf8");
  assert.match(vscodeignore, /^content\/missions\/\*\/\*\/solution\/\*\*$/m);
  assert.match(vscodeignore, /^content\/missions\/\*\/\*\/mutants\/\*\*$/m);

  // Progress: next batch, status; a malformed progress file is dropped, not trusted.
  const incremental = missions.find(item => item.id === "incremental-order-lines");
  assert.equal(m.nextBatch(incremental, undefined), undefined);
  assert.equal(m.nextBatch(incremental, { started: "t", batches: ["day-1"], hintsShown: 0 }).id, "day-2");
  assert.equal(m.nextBatch(incremental, { started: "t", batches: ["day-1", "day-2"], hintsShown: 0 }), undefined);
  assert.equal(m.missionStatus(undefined), "new");
  assert.equal(m.missionStatus({ started: "t", batches: [], hintsShown: 0 }), "in-progress");
  assert.equal(m.missionStatus({ started: "t", batches: [], hintsShown: 0, passedAt: "t" }), "passed");
  const progress = m.toProgressFile({ missions: { "../x": { started: "t" }, "sales-board": { started: 1, batches: ["a", 2], hintsShown: -3, lastCheck: { nope: 1 } } } });
  assert.deepEqual(progress, { version: 1, missions: { "sales-board": { started: undefined, batches: ["a"], hintsShown: 0, lastCheck: undefined, passedAt: undefined } } });
  assert.throws(() => m.missionFolder("../etc"), /Invalid mission id/);
  assert.equal(m.missionFolder("sales-board"), "missions/sales-board");

  // The checker's answer, as the runtime returns it.
  const check = m.toMissionCheckView({
    status: "not-yet", requires: ["Load the next batch."], checked_at: "2026-09-25T10:00:00+02:00", truth: "Checked for real",
    criteria: [
      { id: "a", text: "A", passed: true, checks: [{ kind: "sql", passed: true, detail: "As expected." }] },
      { id: "b", text: "B", passed: false, checks: [{ kind: "node", passed: false, detail: "fct is a table." }, { kind: "run", passed: true, detail: "ok" }] }
    ]
  });
  assert.deepEqual(check.criteria.map(c => [c.id, c.passed, c.details]), [["a", true, []], ["b", false, ["fct is a table."]]]);
  assert.deepEqual(check.requires, ["Load the next batch."]);
  // Stored in progress.json in the view's own shape, and read back unchanged.
  const stored = m.toProgressFile(JSON.parse(JSON.stringify({ missions: { "sales-board": { started: "t", batches: ["landing"], hintsShown: 2, lastCheck: check } } })));
  assert.deepEqual(stored.missions["sales-board"].lastCheck, check);

  // TICKET.md and the safe Markdown reading of a ticket (no HTML is ever produced).
  const ticket = m.ticketMarkdown(incremental);
  assert.match(ticket, /^# fct_order_lines will lose history from tomorrow$/m);
  assert.match(ticket, /^- \[ \] fct_order_lines is an incremental model/m);
  const blocks = m.ticketBlocks("Hello `code` and **bold**.\n\n```\nlog <b>x</b>\n```\n- one\n- two\n  continued\n1. first\n\nEnd");
  assert.deepEqual(blocks.map(block => block.kind), ["p", "code", "ul", "ol", "p"]);
  assert.deepEqual(blocks[0].spans, [{ kind: "text", text: "Hello " }, { kind: "code", text: "code" }, { kind: "text", text: " and " },
    { kind: "strong", text: "bold" }, { kind: "text", text: "." }]);
  assert.equal(blocks[1].text, "log <b>x</b>");
  assert.equal(blocks[2].items.length, 2);
  assert.equal(blocks[2].items[1].map(span => span.text).join(""), "two continued");

  console.log(`Missions UI smoke passed: ${missions.length} missions.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
