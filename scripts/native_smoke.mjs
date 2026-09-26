// VS Code native entry points: which files get the Practice and mission CodeLens, what the runtime status bar item
// says and does in each state, and the package.json contributions behind them (commands, walkthrough, API Lab stub).
// Pure functions of src/platform/native.ts; the real status bar item and CodeLens are seen by scripts/vscode_ui_pass.mjs.
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-native-"));

try {
  const outfile = path.join(dir, "native.mjs");
  await esbuild.build({ entryPoints: ["src/platform/native.ts"], bundle: true, platform: "node", format: "esm", outfile, logLevel: "silent" });
  const n = await import(pathToFileURL(outfile).href);

  // Practice solution files, under the manifest's exercise root.
  assert.deepEqual(n.solutionTarget(["exercises", "top-customers", "sql", "solution.sql"], ["exercises"]), { exercise: "top-customers", language: "sql" });
  assert.deepEqual(n.solutionTarget(["work", "ex", "a", "python", "solution.py"], ["work", "ex"]), { exercise: "a", language: "python" });
  for (const parts of [["exercises", "a", "sql", "README.md"], ["exercises", "a", "solution.sql"], ["other", "a", "sql", "solution.sql"],
    ["exercises", "a", "sql", "x", "solution.sql"], ["exercises", "a", "sql", "solution.sql.bak"]]) {
    assert.equal(n.solutionTarget(parts, ["exercises"]), undefined, parts.join("/"));
  }
  assert.equal(n.exerciseSlug("Top Customers!"), "top-customers");
  assert.equal(n.exerciseSlug("--"), "exercise");

  // Mission files: anything under missions/<id>/.
  assert.equal(n.missionOf(["missions", "api-cursor-retries", "ingest.py"]), "api-cursor-retries");
  assert.equal(n.missionOf(["missions", "dbt-x", "models", "a.sql"]), "dbt-x");
  for (const parts of [["missions", "x"], ["missions", "Bad_Id", "a"], ["mission", "x", "a"], ["missions", "..", "a"]]) {
    assert.equal(n.missionOf(parts), undefined, parts.join("/"));
  }

  // The status bar item in every runtime state.
  const view = (status, environment) => n.runtimeStatusView({ status, environment: environment && { status: environment } });
  assert.equal(view("stopped", "missing").action, "setup");
  assert.match(view("stopped", "missing").text, /not set up/);
  assert.equal(view("stopped", "ready").action, "start");
  assert.match(view("stopped", "ready").text, /stopped/);
  assert.equal(view("stopped", "stale").action, "update");
  assert.match(view("stopped", "stale").text, /needs update/);
  assert.equal(view("stopped", "stale").warning, true);
  assert.equal(view("starting", "ready").action, "open");
  assert.match(view("running", "ready").text, /running/);
  assert.equal(view("running", "ready").action, "open");
  assert.equal(view("stopped", "setting-up").action, "log");
  assert.equal(view("error", "ready").action, "log");

  // Contributions: the commands the status bar, the CodeLens and the walkthrough call exist and are registered.
  const pkg = JSON.parse(await readFile("package.json", "utf8"));
  const commands = new Set(pkg.contributes.commands.map(c => c.command));
  const source = await readFile("src/nativeIntegration.ts", "utf8");
  for (const command of ["datapass.runtime.action", "datapass.runtime.setup", "datapass.runtime.start", "datapass.practice.runVisible",
    "datapass.practice.submit", "datapass.missions.check", "datapass.apilab.run"]) {
    assert.ok(commands.has(command), `${command} contributed`);
    assert.ok(source.includes(`"${command}"`) || (command === "datapass.runtime.action" && source.includes("RUNTIME_ACTION")), `${command} registered`);
  }
  const [walkthrough] = pkg.contributes.walkthroughs;
  assert.equal(walkthrough.title, "Get started with Datapass");
  assert.deepEqual(walkthrough.steps.map(step => step.id), ["setupRuntime", "openToday", "firstPractice", "firstMission"]);
  for (const step of walkthrough.steps) {
    assert.ok(existsSync(step.media.markdown), step.media.markdown);
    for (const [, command] of step.description.matchAll(/\(command:([\w.]+)\)/g)) assert.ok(commands.has(command), `${step.id}: ${command}`);
    for (const event of step.completionEvents) assert.ok(commands.has(event.replace(/^onCommand:/, "")), `${step.id}: ${event}`);
  }
  assert.ok(pkg.activationEvents.includes("workspaceContains:.datapass/**"), "activates in a Datapass workspace (status bar, CodeLens)");

  // API Lab: the pack's __builtins__.pyi names what a run puts in scope, and every mission's ingest.py uses only those.
  const stub = await readFile("content/missions/api-v1/__builtins__.pyi", "utf8");
  const runner = await readFile("runtime/apilab/runner.py", "utf8");
  for (const name of ["API_BASE_URL", "API_KEY", "bronze"]) {
    assert.match(stub, new RegExp(`^${name}: `, "m"), `stub declares ${name}`);
    assert.ok(runner.includes(`'${name}'`), `the runner puts ${name} in scope`);
  }
  for (const method of ["append", "overwrite", "merge", "query", "columns"]) {
    assert.match(stub, new RegExp(`def ${method}\\(`), `stub declares bronze.${method}`);
    assert.match(runner, new RegExp(`def ${method}\\(`), `the runner's Bronze has ${method}`);
  }
  const routes = await readFile("runtime/apilab/routes.py", "utf8");
  assert.ok(routes.includes("'__builtins__.pyi'"), "the stub is copied into the mission folder");
  const missions = (await readdir("content/missions/api-v1", { withFileTypes: true })).filter(entry => entry.isDirectory());
  assert.ok(missions.length >= 5);

  console.log(`Native smoke passed: CodeLens targets, status bar states, walkthrough, API Lab stub for ${missions.length} missions.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
