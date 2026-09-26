// Today home and the module registry: content/modules.json is complete and consistent (families, commands, surfaces,
// icons), and the home's summary and next step follow .datapass/progress.json. Pure functions of
// src/modules.ts and src/labs/workbench/home.ts.
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-home-"));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  return import(pathToFileURL(outfile).href);
}

try {
  const { MODULES, MODULE_FAMILIES, familyModules } = await bundle("src/modules.ts", "modules.mjs");
  const { homeView } = await bundle("src/labs/workbench/home.ts", "home.mjs");
  const p = await bundle("src/platform/projects.ts", "projects.mjs");

  // Registry: unique ids, known families, each family used, every command contributed, every module has a surface.
  const ids = MODULES.map(m => m.id);
  assert.equal(new Set(ids).size, ids.length, "module ids are unique");
  assert.deepEqual(MODULE_FAMILIES.map(f => f.id), ["learn", "work"]);
  const pkg = JSON.parse(await readFile("package.json", "utf8"));
  const commands = new Set(pkg.contributes.commands.map(c => c.command));
  assert.ok(commands.has("datapass.openHome"), "the Today command is contributed");
  const app = await readFile("src/webview/WorkbenchApp.tsx", "utf8");
  const moduleIdType = /export type ModuleId = ([^;]+);/.exec(await readFile("src/modules.ts", "utf8"))[1];
  for (const m of MODULES) {
    assert.ok(MODULE_FAMILIES.some(f => f.id === m.family), `${m.id}: family ${m.family}`);
    assert.ok(commands.has(m.command), `${m.id}: ${m.command} in package.json`);
    assert.match(m.icon, /^[a-z-]+$/, `${m.id}: codicon name`);
    assert.ok(m.label && m.description && m.execution && ["real", "simulated", "hybrid"].includes(m.mode), m.id);
    assert.ok(app.includes(`  ${m.id}: (vscode, state) =>`), `${m.id}: a surface in SURFACES`);
    assert.ok(moduleIdType.includes(`"${m.id}"`), `${m.id}: in the ModuleId type`);
  }
  assert.equal((moduleIdType.match(/"/g) ?? []).length / 2, MODULES.length, "ModuleId lists exactly the registry");
  for (const f of MODULE_FAMILIES) assert.ok(familyModules(f.id).length > 0, `${f.id} has modules`);
  assert.deepEqual(familyModules("work").map(m => m.id), ["projects", "dbt", "terminal", "infra"]);

  // Home: fixtures from the shipped projects.
  const labels = Object.fromEntries(MODULES.map(m => [m.id, m.label]));
  const projects = [];
  for (const id of (await readdir("content/projects")).sort()) {
    projects.push(p.normalizeProject(JSON.parse(await readFile(`content/projects/${id}/project.json`, "utf8")), ids).project);
  }
  projects.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  const views = progress => projects.map(project => p.projectView(project, progress[project.id], labels));
  const base = { hasWorkspace: true, exerciseKeys: ["a/x/sql", "a/y/sql", "a/z/python"], practice: {}, today: "2026-09-26" };

  // No folder: open one first.
  assert.equal(homeView({ ...base, hasWorkspace: false, projects: views({}) }).next.kind, "open-folder");

  // Fresh workspace: start the first project; nothing solved.
  let home = homeView({ ...base, projects: views({}) });
  assert.equal(home.next.kind, "start-project");
  assert.equal(home.next.projectId, projects[0].id);
  assert.deepEqual(home.practice, { total: 3, solved: 0, attempted: 0, dueReviews: 0 });
  assert.equal(home.projects.started, 0);
  assert.equal(home.projects.current, undefined);

  // A started project (first step ticked by hand): its next step is suggested, in its lab.
  const first = projects[0];
  const ticked = { [first.id]: { version: first.version, steps: { [first.steps[0].id]: { manual: { checked: true, at: "2026-09-25T10:00:00Z" } } } } };
  home = homeView({ ...base, projects: views(ticked) });
  assert.equal(home.next.kind, "project-step");
  assert.equal(home.next.projectId, first.id);
  assert.equal(home.next.stepId, first.steps[1].id);
  assert.equal(home.next.module, first.steps[1].module);
  assert.equal(home.projects.current.id, first.id);
  assert.equal(home.projects.current.done, 1);

  // Practice: solved, attempted, reviews due (unknown keys ignored); reviews come before starting a new project.
  const practice = {
    "a/x/sql": { attempts: 2, solved: { at: "2026-09-01T10:00:00Z", version: "1" }, review: { box: 2, due: "2026-09-20" } },
    "a/y/sql": { attempts: 1, openedAt: "2026-09-25T10:00:00Z" },
    "gone/q/sql": { attempts: 1, solved: { at: "2026-09-01T10:00:00Z", version: "1" } }
  };
  home = homeView({ ...base, practice, projects: views({}) });
  // Practice schedules attempted exercises too (platform/practiceReview.ts): a/y was opened yesterday.
  assert.deepEqual(home.practice, { total: 3, solved: 1, attempted: 1, dueReviews: 2 });
  assert.equal(home.next.kind, "reviews");
  assert.match(home.next.detail, /^2 exercises are due/);
  // An in-progress project still comes first.
  assert.equal(homeView({ ...base, practice, projects: views(ticked) }).next.kind, "project-step");

  console.log(`Home smoke passed: ${MODULES.length} modules in ${MODULE_FAMILIES.length} families, next-step order checked.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
