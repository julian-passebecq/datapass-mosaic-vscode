// Projects module, extension side: content normalization, the progress file and its truth model
// (verified vs ticked by hand), the next suggested step and the Markdown subset. Pure functions of
// src/platform/projects.ts; the runtime checks themselves are covered by scripts/projects_smoke.py.
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-projects-"));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  return import(pathToFileURL(outfile).href);
}

try {
  const p = await bundle("src/platform/projects.ts", "projects.mjs");
  const { MODULES } = await bundle("src/modules.ts", "modules.mjs");
  const ids = MODULES.map(m => m.id);
  const labels = Object.fromEntries(MODULES.map(m => [m.id, m.label]));
  assert.equal(MODULES.find(m => m.id === "projects")?.command, "datapass.openProjects");
  const pkg = JSON.parse(await readFile("package.json", "utf8"));
  assert.ok(pkg.contributes.commands.some(c => c.command === "datapass.openProjects"));

  // Every shipped project normalizes with its steps; instructions written as line lists are joined.
  const projects = [];
  for (const id of (await readdir("content/projects")).sort()) {
    const { project, error } = p.normalizeProject(JSON.parse(await readFile(`content/projects/${id}/project.json`, "utf8")), ids);
    assert.ok(project, `${id}: ${error}`);
    assert.equal(project.id, id);
    assert.ok(project.steps.length >= 8 && project.steps.length <= 12, id);
    assert.ok(project.steps.every(s => s.open.module === s.module && !s.instructions.includes("\n\n\n")), id);
    projects.push(project);
  }
  assert.deepEqual(projects.map(x => x.id).sort(), ["databricks-ml", "retail-fabric", "synapse-to-fabric"]);
  const retail = projects.find(x => x.id === "retail-fabric");
  assert.equal(p.normalizeProject({ ...JSON.parse(await readFile("content/projects/retail-fabric/project.json", "utf8")), id: "../x" }, ids).error,
    "missing or invalid id");
  const badFile = JSON.parse(await readFile("content/projects/retail-fabric/project.json", "utf8"));
  badFile.steps[0].open.file = "../../etc/passwd";
  assert.match(p.normalizeProject(badFile, ids).error, /invalid open action/);

  // Workspace paths: only the project folders, never traversal, absolute paths or other roots.
  for (const ok of ["projects/retail-fabric/a.sql", "factory/fabric/x.json", "bi/model.json", "airflow/dags/d.py"]) assert.ok(p.isProjectFilePath(ok), ok);
  for (const bad of ["../x", "/etc/passwd", "projects/../x", "src/extension.ts", ".datapass/progress.json", "C:/x", "projects//x"]) {
    assert.ok(!p.isProjectFilePath(bad), bad);
  }

  // A fresh workspace: nothing started, the first step is next, optional steps are not counted.
  let doc = p.parseProgress(undefined).document;
  let view = p.projectView(retail, doc.projects[retail.id], labels);
  assert.equal(view.started, false);
  assert.equal(view.nextStepId, "import-web-orders");
  assert.deepEqual(view.progress, { required: 12, verified: 0, manual: 0, done: 0, percent: 0 });
  const dbx = projects.find(x => x.id === "databricks-ml");
  assert.equal(p.projectView(dbx, undefined, labels).progress.required, 9, "the optional Polars step is not counted");
  assert.equal(view.steps[0].moduleLabel, "Mosaic");

  // Ticking by hand is a declaration: "manual", counted apart, never verified.
  const now = "2026-09-25T10:00:00.000Z";
  doc = p.setManual(doc, retail, "runbook", true, now);
  doc = p.setManual(doc, retail, "import-web-orders", true, now);
  view = p.projectView(retail, doc.projects[retail.id], labels);
  assert.equal(view.steps.find(s => s.id === "runbook").state, "manual");
  assert.equal(view.steps.find(s => s.id === "import-web-orders").state, "manual");
  assert.equal(view.steps.find(s => s.id === "import-web-orders").verified, undefined);
  assert.deepEqual(view.progress, { required: 12, verified: 0, manual: 2, done: 2, percent: 17 });
  assert.equal(view.nextStepId, "type-imported-text");
  assert.throws(() => p.setManual(doc, retail, "nope", true, now), /Unknown step/);

  // A runtime verification: passed steps become verified, failed ones keep the step to redo.
  const check = (label, status, truth = "real") => ({ kind: "table", label, status, truth, message: status, at: now });
  const result = (steps) => ({ project_id: "retail-fabric", version: "1", checked_at: now, steps });
  const silverLabels = retail.steps.find(s => s.id === "silver-web-orders").checks.map(c => c.label);
  doc = p.applyVerification(doc, retail, result([
    { id: "import-web-orders", status: "passed", checks: [check(retail.steps[0].checks[0].label, "passed")] },
    { id: "silver-web-orders", status: "failed", checks: [check(silverLabels[0], "passed"), check(silverLabels[1], "failed")] },
    // The runtime reports manual steps as "manual": they are never recorded as verified.
    { id: "runbook", status: "manual", checks: [] },
    // A forged "passed" with fewer checks than the step has is not a verification.
    { id: "fabric-pipeline-web", status: "passed", checks: [check("x", "passed", "hybrid")] }
  ]), now);
  view = p.projectView(retail, doc.projects[retail.id], labels);
  const byId = Object.fromEntries(view.steps.map(s => [s.id, s]));
  assert.equal(byId["import-web-orders"].state, "verified");
  assert.equal(byId["silver-web-orders"].state, "failed");
  assert.equal(byId["runbook"].state, "manual");
  assert.equal(byId["runbook"].verified, undefined);
  assert.notEqual(byId["fabric-pipeline-web"].state, "verified");
  assert.deepEqual(view.progress, { required: 12, verified: 1, manual: 1, done: 2, percent: 17 });
  assert.throws(() => p.applyVerification(doc, retail, { project_id: "other", steps: [] }, now), /no verification/);

  // A later failure keeps the first success and shows the step as regressed; truths are kept for badges.
  doc = p.applyVerification(doc, retail, result([
    { id: "import-web-orders", status: "failed", checks: [check(retail.steps[0].checks[0].label, "failed")] }]), now);
  const regressed = p.projectView(retail, doc.projects[retail.id], labels).steps[0];
  assert.equal(regressed.state, "verified");
  assert.equal(regressed.regressed, true);
  assert.deepEqual(p.unverifiedSteps(p.projectView(retail, doc.projects[retail.id], labels)).slice(0, 2), ["type-imported-text", "silver-web-orders"]);

  // The file round-trips; a hand-edited "verified" record that does not pass is ignored, not trusted.
  const text = p.serializeProgress(doc);
  assert.deepEqual(p.parseProgress(text).document, doc);
  const forged = JSON.parse(text);
  forged.projects["retail-fabric"].steps["quality-gate"] = { verified: { at: now, status: "passed", checks: [check("x", "failed")] } };
  forged.projects["retail-fabric"].steps["runbook"].verified = { at: now, status: "passed", checks: [check("x", "passed")] };
  const reread = p.projectView(retail, p.parseProgress(JSON.stringify(forged)).document.projects["retail-fabric"], labels);
  assert.notEqual(reread.steps.find(s => s.id === "quality-gate").state, "verified");
  assert.equal(reread.steps.find(s => s.id === "runbook").state, "manual", "a step without checks is never verified");
  assert.match(p.parseProgress("{").error, /not valid JSON/);
  assert.match(p.parseProgress("{\"projects\": {}}").error, /schema_version/);

  // Everything done: no next step; unticking brings the step back.
  let all = p.parseProgress(undefined).document;
  for (const step of retail.steps) all = p.setManual(all, retail, step.id, true, now);
  assert.equal(p.projectView(retail, all.projects[retail.id], labels).nextStepId, undefined);
  all = p.setManual(all, retail, "dbt-marts", false, now);
  assert.equal(p.projectView(retail, all.projects[retail.id], labels).nextStepId, "dbt-marts");
  let optional = p.parseProgress(undefined).document;
  for (const step of dbx.steps.filter(s => !s.optional)) optional = p.setManual(optional, dbx, step.id, true, now);
  const dbxView = p.projectView(dbx, optional.projects[dbx.id], labels);
  assert.equal(dbxView.progress.percent, 100);
  assert.equal(dbxView.nextStepId, "residuals-polars", "optional steps come last");

  // Markdown subset: paragraphs, lists, fenced code, **bold** and `code`; no HTML is ever produced.
  const blocks = p.parseMarkdown("Intro **bold** and `code`.\nsame paragraph\n\n1. one\n2. two\n\n- a\n- b\n\n```\nx = 1\n<b>\n```\n<script>");
  assert.deepEqual(blocks.map(b => b.kind), ["paragraph", "list", "list", "code", "paragraph"]);
  assert.deepEqual(blocks[0].spans, [
    { kind: "text", text: "Intro " }, { kind: "bold", text: "bold" }, { kind: "text", text: " and " },
    { kind: "code", text: "code" }, { kind: "text", text: ". same paragraph" }]);
  assert.equal(blocks[1].ordered, true);
  assert.equal(blocks[2].items.length, 2);
  assert.equal(blocks[3].text, "x = 1\n<b>");
  assert.deepEqual(blocks[4].spans, [{ kind: "text", text: "<script>" }]);
  for (const project of projects) {
    for (const step of project.steps) assert.ok(p.parseMarkdown(step.instructions).length, `${project.id}/${step.id}`);
  }

  console.log(`Projects UI smoke passed: ${projects.length} projects, ${projects.reduce((n, x) => n + x.steps.length, 0)} steps.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
