// V1 acceptance: the packaged VSIX in a real VS Code window (Playwright `_electron.launch`), one fresh profile, an
// empty workspace folder, the whole learner journey of V1, then a VS Code restart.
//
//   npm ci --prefer-offline --no-audit --no-fund && npm run package && node scripts/ui-suite/v1_acceptance.mjs
//
//  1. Install the VSIX, open the empty folder, Datapass Build: New Blank Workspace -> catalog.seed "none", trusted
//     Python off, no sample file.
//  2. Build New file: SQL and Python through the quick pick and input box; a second New file with the same name
//     leaves the file on disk unchanged.
//  3. Build Import dataset (VS Code's simple file dialog, typed): a synthetic CSV lands in datasets/; a second
//     import with the same name is renamed, the first copy is never overwritten.
//  4. Setup runtime + Start runtime (the existing Workbench flow); no source.* demo table; Run active SQL gives a
//     real DuckDB row; the Python file is refused while trusted Python is off, then trusted Python is enabled through
//     its confirmation dialog and the file really runs.
//  5. Learning: read, a concept check submitted (checks level, not verified), Run example (ran locally, not graded),
//     a linked Practice Submit (verified), a flashcard rated (self-rated).
//  6. Cloud Lab > Pipelines: lab files, an unknown property planted in the JSON, an activity added from the palette,
//     connected, undo, redo, save; the planted property survives on disk; Dry run shows the new activity's status.
//  7. Infra Lab: tf-first-apply started, the learner's files saved, the reference lines typed in the simulated
//     terminal, Check my work passes.
//  8. Interop: a content/interop/examples exchange imported (files, nothing run, no table created), then exported;
//     the export validates against schemas/mosaic-exchange.schema.json.
//  9. VS Code closed and relaunched: Learning resumes, the four levels and flashcard state persist, Build files and
//     datasets exist, Mosaic query history re-runs, the pipeline edit is still there.
// 10. No uncaught webview console error.
//
// Environment: DATAPASS_UI_VSIX, DATAPASS_UI_PYTHON (base Python for Setup runtime), DATAPASS_UI_CODE /
// VSCODE_TEST_VERSION, DATAPASS_UI_ROOT (profile + workspace root; default a short folder under %TEMP%).
// Output: test-results/vscode-ui/v1-acceptance/report.json (+ failure screenshots and frame text dumps).
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath } from "@vscode/test-electron";
import { _electron } from "playwright-core";

const repo = process.cwd();
const isWindows = process.platform === "win32";
const started = Date.now();
const root = process.env.DATAPASS_UI_ROOT ? path.resolve(process.env.DATAPASS_UI_ROOT) : mkdtempSync(path.join(tmpdir(), "dpa-"));
if (process.env.DATAPASS_UI_ROOT) rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
const out = path.join(repo, "test-results", "vscode-ui", "v1-acceptance");
const workspace = path.join(root, "ws");
const extensionsDir = path.join(root, "x");
const userDataDir = path.join(root, "u");
const inputs = path.join(root, "in");
rmSync(out, { recursive: true, force: true });
for (const dir of [out, workspace, extensionsDir, path.join(userDataDir, "User"), inputs]) mkdirSync(dir, { recursive: true });

const report = { target: "packaged VSIX in real VS Code", vsix: undefined, root, steps: [], webviewErrors: [], completed: false };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const ws = (...parts) => path.join(workspace, ...parts);
const read = file => readFileSync(file, "utf8");
let app;
let page;
let current;

// ---------------------------------------------------------------------------------------------------------------
// Report

function check(name, ok, detail = "") {
  current.checks.push({ name, ok: Boolean(ok), detail: String(detail).slice(0, 400) });
  if (!ok) console.log(`  FAIL ${name}${detail ? ` - ${String(detail).slice(0, 300)}` : ""}`);
  return Boolean(ok);
}
function notAutomated(name, reason) {
  current.notAutomated.push({ name, reason });
}

async function step(id, title, body) {
  current = { id, title, status: "running", checks: [], notAutomated: [], seconds: 0 };
  report.steps.push(current);
  const begin = Date.now();
  try {
    await body();
  } catch (error) {
    current.error = String(error?.message ?? error).split("\n").slice(0, 3).join(" ").slice(0, 600);
  }
  current.seconds = Math.round((Date.now() - begin) / 1000);
  const failed = current.error || current.checks.some(item => !item.ok) || !current.checks.length;
  current.status = failed ? "FAIL" : "PASS";
  console.log(`${current.status} ${id}. ${title} (${current.seconds} s)${current.error ? ` - ${current.error.slice(0, 300)}` : ""}`);
  for (const item of current.notAutomated) console.log(`  NOT AUTOMATED ${item.name} - ${item.reason}`);
  if (failed) await dumpFailure(`step-${id}`);
  // Leave no quick input, dialog or notification behind for the next step.
  if (page && !page.isClosed()) {
    for (let i = 0; i < 3; i++) await page.keyboard.press("Escape").catch(() => undefined);
    await command("Notifications: Clear All Notifications").catch(() => undefined);
  }
}

async function dumpFailure(name) {
  if (!page || page.isClosed()) return;
  await page.screenshot({ path: path.join(out, `${name}.png`) }).catch(() => undefined);
  writeFileSync(path.join(out, `${name}-window.txt`), await page.locator("body").innerText().catch(() => ""));
  for (const [index, frame] of page.frames().entries()) {
    const text = await frame.locator("body").innerText({ timeout: 2000 }).catch(() => undefined);
    if (text && text.trim()) writeFileSync(path.join(out, `${name}-frame-${index}.txt`), text);
  }
}

// ---------------------------------------------------------------------------------------------------------------
// VS Code driver

function newestVsix() {
  if (process.env.DATAPASS_UI_VSIX) return path.resolve(process.env.DATAPASS_UI_VSIX);
  const files = readdirSync(repo).filter(name => name.endsWith(".vsix")).map(name => path.join(repo, name))
    .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  if (!files.length) throw new Error("No .vsix in the repository root: run `npm run package` first (or set DATAPASS_UI_VSIX).");
  return files[0];
}

async function launch(executable) {
  app = await _electron.launch({
    executablePath: executable,
    args: [workspace, `--extensions-dir=${extensionsDir}`, `--user-data-dir=${userDataDir}`, "--disable-workspace-trust",
      "--skip-welcome", "--skip-release-notes", "--disable-telemetry", "--new-window",
      ...(isWindows ? [] : ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])],
    timeout: 180000
  });
  page = await app.firstWindow();
  page.setDefaultTimeout(30000);
  page.on("console", message => {
    if (message.type() === "error" && /vscode-webview:/.test(message.location()?.url ?? "")) report.webviewErrors.push(message.text().slice(0, 500));
  });
  await page.waitForSelector(".monaco-workbench", { timeout: 180000 });
  await app.evaluate(({ BrowserWindow }) => { const w = BrowserWindow.getAllWindows()[0]; w.unmaximize(); w.setSize(1500, 1000); });
  // The extension host can take minutes on a first launch: wait until a Datapass command is in the palette.
  if (await page.locator(".part.sidebar").first().isVisible().catch(() => false)) await command("View: Close Primary Side Bar", 180000);
}

async function close() {
  if (!app) return;
  const closing = app;
  app = undefined;
  let timer;
  try {
    await Promise.race([closing.close(), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("VS Code close timed out")), 30000); })]);
  } catch (error) {
    closing.process().kill();
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

const quickInput = () => page.locator(".quick-input-widget .quick-input-box input").first();

/**
 * The first Datapass command after a launch: on a slow first start the extension host can restart after the window
 * is up ("took longer than 60s to send its ready message"), and a command then fails with "command ... not found".
 * Retry until the host has registered it.
 */
async function firstCommand(title) {
  const notFound = page.locator(".notifications-toasts", { hasText: /command '[^']+' not found/ });
  const until = Date.now() + 240000;
  for (;;) {
    await command(title, 180000);
    const missing = await notFound.first().waitFor({ timeout: 2500 }).then(() => true, () => false);
    if (!missing) return;
    if (Date.now() > until) throw new Error(`${title}: the extension host never registered the command`);
    await command("Notifications: Clear All Notifications").catch(() => undefined);
    await sleep(5000);
  }
}

async function command(title, timeout = 30000) {
  await page.keyboard.press("Escape");
  const input = quickInput();
  const center = page.locator(".command-center-center").first();
  if (await center.isVisible().catch(() => false)) await center.click();
  else await page.keyboard.press("F1");
  if (!(await input.isVisible().catch(() => false))) await page.keyboard.press("F1");
  await input.waitFor({ state: "visible" });
  await input.fill(`>${title}`);
  const row = page.locator(".quick-input-list .monaco-list-row", { hasText: title }).first();
  if (!(await row.waitFor({ timeout }).then(() => true, () => false))) {
    await page.screenshot({ path: path.join(out, `palette-miss-${title.replace(/[^A-Za-z]+/g, "-")}.png`) }).catch(() => undefined);
    // A focused terminal or webview can swallow the first keystrokes: reopen the palette once and type again.
    await page.keyboard.press("Escape");
    await page.keyboard.press("F1");
    await input.waitFor({ state: "visible" });
    await input.fill(`>${title}`);
    await row.waitFor({ timeout });
  }
  await page.keyboard.press("Enter");
}

/** The quick input after a command: wait for its title, then fill and accept. */
async function answerInput(titlePattern, value) {
  const input = quickInput();
  if (typeof titlePattern === "function") {
    if (!(await waitFor(titlePattern, 30000))) throw new Error("file dialog did not open");
  } else await page.locator(".quick-input-widget .quick-input-title", { hasText: titlePattern }).first().waitFor();
  if (value !== undefined) await input.fill(value);
  await page.keyboard.press("Enter");
}

async function pickItem(titlePattern, label) {
  await page.locator(".quick-input-widget .quick-input-title", { hasText: titlePattern }).first().waitFor();
  await quickInput().fill(label);
  await page.locator(".quick-input-list .monaco-list-row", { hasText: label }).first().waitFor();
  await page.keyboard.press("Enter");
}

/** VS Code's simple file dialog (files.simpleDialog.enable): type the path, accept until `done()` holds. */
async function fileDialog(titlePattern, filePath, done) {
  // Wait for the dialog itself: right after a command the palette's own input can still be visible.
  const input = quickInput();
  if (typeof titlePattern === "function") {
    if (!(await waitFor(titlePattern, 30000))) throw new Error("file dialog did not open");
  } else await page.locator(".quick-input-widget .quick-input-title", { hasText: titlePattern }).first().waitFor();
  await input.fill(filePath);
  await sleep(400);
  await page.keyboard.press("Enter");
  for (let waited = 0; waited < 15000; waited += 250) {
    if (await done()) return true;
    if (waited === 3000 && await input.isVisible().catch(() => false)) await page.keyboard.press("Enter");
    await sleep(250);
  }
  return Boolean(await done());
}

async function waitFor(predicate, timeout = 30000, interval = 250) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await predicate()) return true;
    await sleep(interval);
  }
  return Boolean(await predicate());
}

/** The visible webview frame that holds `selector` (Workbench: .module-main, Learning: #learning-root h1). */
async function frameWith(selector, timeout = 60000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    for (const frame of page.frames()) {
      if (await frame.locator(selector).first().isVisible().catch(() => false)) return frame;
    }
    await sleep(150);
  }
  throw new Error(`No visible webview with ${selector}`);
}
const workbench = (timeout) => frameWith(".module-main", timeout);
const learning = (timeout) => frameWith("#learning-root h1", timeout);
const wbButton = async name => (await workbench()).getByRole("button", { name, exact: true }).first();
async function wbText() { return (await workbench()).locator("body").innerText(); }
async function waitText(pattern, timeout = 60000) {
  let text = "";
  const ok = await waitFor(async () => { text = await wbText().catch(() => ""); return pattern.test(text); }, timeout, 400);
  return ok ? pattern.exec(text) : null;
}
async function subtab(name) {
  await (await workbench()).locator(".lab-subtabs").getByRole("tab", { name, exact: true }).click();
}

function filesUnder(dir, base = dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? filesUnder(full, base) : [path.relative(base, full).split(path.sep).join("/")];
  });
}
const jsonFile = file => { try { return JSON.parse(read(file)); } catch { return undefined; } };

// Learning helpers.
async function lessonMode(name) {
  const f = await learning();
  await f.getByRole("navigation", { name: "Lesson views" }).getByRole("button", { name, exact: true }).click();
  return learning();
}
async function openLesson(search, title) {
  let f = await learning();
  const map = f.getByRole("button", { name: "Learning map", exact: true });
  if (await map.count()) await map.click();
  f = await learning();
  await f.getByRole("searchbox", { name: "Search lessons" }).fill(search);
  await f.locator(".map").getByRole("button", { name: title, exact: true }).first().click();
  f = await learning();
  await f.getByRole("heading", { name: title, exact: true }).waitFor();
  return f;
}
async function levelChips() {
  const f = await learning();
  return (await f.locator(".heading .metadata .levels").first().innerText().catch(() => "")).replace(/\s+/g, " ");
}

// ---------------------------------------------------------------------------------------------------------------
// The journey

const SQL_NAME = "acceptance.sql";
const PY_NAME = "acceptance_py.py";
const SQL_TEXT = "-- Acceptance query\nSELECT 40 + 2 AS answer_acc;\n";
const PY_TEXT = "# Acceptance Python\nprint(\"py_answer\", 6 * 7)\n";
const CSV_FIRST = "order_id,amount\n1,10.5\n2,20\n";
const CSV_SECOND = "order_id,amount\n3,99\n";
const PIPELINE = "factory/fabric/pl_retail_daily.DataPipeline/pipeline-content.json";
const MARKER = { keep: "planted by v1_acceptance", list: [1, 2] };
const QUIZ = "concept-formats-partition-evolution";
const JOIN_EXERCISE = "sql-lab-left-preserve-customers";
let executable;
let ratedCard;

try {
  const vsix = newestVsix();
  report.vsix = path.basename(vsix);
  writeFileSync(path.join(userDataDir, "User", "settings.json"), JSON.stringify({
    "workbench.startupEditor": "none", "workbench.tips.enabled": false, "workbench.enableExperiments": false,
    "workbench.secondarySideBar.defaultVisibility": "hidden", "window.restoreWindows": "none", "window.dialogStyle": "custom",
    "window.titleBarStyle": "custom", "update.mode": "none", "extensions.autoUpdate": false, "extensions.ignoreRecommendations": true,
    "telemetry.telemetryLevel": "off", "security.workspace.trust.enabled": false, "chat.disableAIFeatures": true,
    "git.openRepositoryInParentFolders": "never",
    // File dialogs as a quick input the test can type into, instead of the OS dialog.
    "files.simpleDialog.enable": true
  }, null, 2));
  executable = process.env.DATAPASS_UI_CODE || await downloadAndUnzipVSCode(process.env.VSCODE_TEST_VERSION || "stable");

  await step(1, "Install VSIX, New Blank Workspace: seed none, trusted Python off, no sample files", async () => {
    const [cli, ...cliArgs] = resolveCliArgsFromVSCodeExecutablePath(executable);
    // Electron's CLI directly on Windows: cmd.exe splits unquoted paths such as "Microsoft VS Code".
    const windowsCli = isWindows ? read(cli).match(/"%~dp0([^"\r\n]*cli\.js)"/i)?.[1] : undefined;
    const install = spawnSync(isWindows ? executable : cli, [
      ...(isWindows ? [path.resolve(path.dirname(cli), windowsCli)] : cliArgs),
      `--extensions-dir=${extensionsDir}`, `--user-data-dir=${userDataDir}`, "--install-extension", vsix, "--force"
    ], { encoding: "utf8", timeout: 600000, env: isWindows ? { ...process.env, ELECTRON_RUN_AS_NODE: "1" } : process.env });
    const installed = readdirSync(extensionsDir).some(name => name.startsWith("datapass.datapass-mosaic-vscode-"));
    check("VSIX installed in a fresh profile", install.status === 0 && installed, install.status === 0 ? report.vsix : `${report.vsix} ${(install.stderr || "").trim().slice(-200)}`);
    if (!installed) throw new Error("VSIX not installed");
    await launch(executable);
    check("empty workspace folder before New workspace", filesUnder(workspace).length === 0, filesUnder(workspace).join(", "));
    await firstCommand("Datapass Build: New Blank Workspace");
    const manifestFile = ws(".datapass", "project.json");
    await waitFor(() => existsSync(manifestFile), 30000);
    await sleep(2500);
    const manifest = jsonFile(manifestFile);
    check("manifest written", Boolean(manifest));
    check("catalog.seed is \"none\"", manifest?.catalog?.seed === "none", JSON.stringify(manifest?.catalog));
    check("trusted local Python off", manifest?.runtime?.trustedLocalPython !== true, JSON.stringify(manifest?.runtime));
    const outside = filesUnder(workspace).filter(file => !file.startsWith(".datapass/"));
    check("no sample file created", outside.length === 0, outside.join(", "));
    check("notebooks/, datasets/ and notes/ exist and are empty",
      ["notebooks", "datasets", "notes"].every(dir => existsSync(ws(dir)) && readdirSync(ws(dir)).length === 0));
    report.datapassFilesAfterNewWorkspace = filesUnder(ws(".datapass"));
    await workbench(60000);
    check("Mosaic opens after New workspace", /Mosaic workspace/i.test(await wbText()));
  });

  await step(2, "Build New file: SQL and Python; a second file with the same name does not overwrite", async () => {
    await command("Datapass Build: New File (SQL, Python, Polars, Markdown)");
    await pickItem("New file", "SQL");
    await answerInput(/New SQL file/, SQL_NAME);
    const sqlFile = ws("notebooks", SQL_NAME);
    check("SQL file created in notebooks/", await waitFor(() => existsSync(sqlFile) && read(sqlFile).length > 0));
    check("SQL file opened in a native editor", await page.locator(".tab", { hasText: SQL_NAME }).first().waitFor({ timeout: 15000 }).then(() => true, () => false));
    // The learner's query, saved as a learner would (typing into Monaco through Electron is flaky).
    writeFileSync(sqlFile, SQL_TEXT);
    await sleep(800);
    await command("Datapass Build: New File (SQL, Python, Polars, Markdown)");
    await pickItem("New file", "SQL");
    await answerInput(/New SQL file/, SQL_NAME);
    const refused = await page.locator(".notifications-toasts", { hasText: `notebooks/${SQL_NAME} already exists. It was not changed.` })
      .first().waitFor({ timeout: 15000 }).then(() => true, () => false);
    check("second New file with the same name is refused with a warning", refused);
    check("existing file unchanged on disk", read(sqlFile) === SQL_TEXT);
    check("no other SQL file appeared", readdirSync(ws("notebooks")).filter(name => name.endsWith(".sql")).length === 1, readdirSync(ws("notebooks")).join(", "));
    await page.keyboard.press("Escape");
    await command("Datapass Build: New File (SQL, Python, Polars, Markdown)");
    await pickItem("New file", "Python");
    await answerInput(/New Python file/, PY_NAME);
    const pyFile = ws("notebooks", PY_NAME);
    check("Python file created in notebooks/", await waitFor(() => existsSync(pyFile)));
    // The file can exist before its content is flushed (seen on Linux CI): wait for the header itself.
    check("Python file header says it runs only with trusted Python", await waitFor(() => existsSync(pyFile) && /trusted local Python/.test(read(pyFile)), 10000));
    writeFileSync(pyFile, PY_TEXT);
    check("New file did not turn trusted Python on", jsonFile(ws(".datapass", "project.json"))?.runtime?.trustedLocalPython !== true);
  });

  await step(3, "Build Import dataset: copy into datasets/, same name renamed, never overwritten", async () => {
    mkdirSync(path.join(inputs, "a"), { recursive: true });
    mkdirSync(path.join(inputs, "b"), { recursive: true });
    const first = path.join(inputs, "a", "orders_acc.csv");
    const second = path.join(inputs, "b", "orders_acc.csv");
    writeFileSync(first, CSV_FIRST);
    writeFileSync(second, CSV_SECOND);
    const target = ws("datasets", "orders_acc.csv");
    await command("Datapass Build: Import Dataset");
    check("CSV copied to datasets/", await fileDialog(/Import a dataset/, first, () => existsSync(target)));
    check("copy is byte-identical", existsSync(target) && read(target) === CSV_FIRST);
    await command("Datapass Build: Import Dataset");
    await fileDialog(/Import a dataset/, second, () => page.locator(".quick-input-widget .quick-input-title", { hasText: "Import orders_acc.csv" }).isVisible().catch(() => false));
    const suggested = await quickInput().inputValue().catch(() => "");
    check("same name is not reused: a free name is suggested", suggested === "orders_acc-2.csv", suggested);
    await page.keyboard.press("Enter");
    const renamed = ws("datasets", "orders_acc-2.csv");
    check("second import written under the new name", await waitFor(() => existsSync(renamed)) && read(renamed) === CSV_SECOND);
    check("first dataset never overwritten", read(target) === CSV_FIRST);
    check("datasets/ holds exactly the two copies", readdirSync(ws("datasets")).sort().join(",") === "orders_acc-2.csv,orders_acc.csv", readdirSync(ws("datasets")).join(", "));
  });

  await step(4, "Runtime setup and start; SQL runs on DuckDB; Python refused, then trusted and run", async () => {
    if (process.env.DATAPASS_UI_PYTHON) {
      const file = ws(".datapass", "project.json");
      const manifest = JSON.parse(read(file));
      manifest.runtime = { ...manifest.runtime, pythonCommand: process.env.DATAPASS_UI_PYTHON };
      writeFileSync(file, JSON.stringify(manifest, null, 2));
    }
    await command("Datapass: Open Mosaic");
    await workbench(90000);
    const setupBegin = Date.now();
    await (await wbButton("Setup runtime")).click();
    await (await workbench()).getByRole("button", { name: "Start runtime", exact: true }).first().waitFor({ timeout: 1200000 });
    report.setupRuntimeSeconds = Math.round((Date.now() - setupBegin) / 1000);
    await (await wbButton("Start runtime")).click();
    await (await workbench()).getByRole("button", { name: "Stop runtime", exact: true }).first().waitFor({ timeout: 180000 });
    check("runtime set up and started through the Workbench", true, `setup ${report.setupRuntimeSeconds} s`);
    await command("Datapass: Open Mosaic");
    const f = await workbench();
    await f.getByRole("button", { name: "Refresh", exact: true }).first().click().catch(() => undefined);
    await sleep(1500);
    const catalog = (await f.locator(".catalog-row strong").allInnerTexts().catch(() => [])).join(", ");
    const text = await wbText();
    check("catalog has no source.* demo table", !/(^|, )source\./.test(catalog) && !/\bsource\.orders\b/.test(text), catalog || "(empty catalog)");
    // Run active SQL on the Build SQL file (the last SQL editor).
    await page.locator(".tab", { hasText: SQL_NAME }).first().click();
    await page.locator(".editor-instance .view-lines", { hasText: "answer_acc" }).first().waitFor({ timeout: 15000 }).catch(() => undefined);
    await command("Datapass: Open Mosaic");
    await (await wbButton("Run active SQL")).click();
    const row = await waitText(/answer_acc\s+42/, 60000);
    check("Run active SQL shows the real DuckDB result", Boolean(row));
    // Python while trusted Python is off: the button stays disabled and says why.
    await page.locator(".tab", { hasText: PY_NAME }).first().click();
    await command("Datapass: Open Mosaic");
    const runPython = await wbButton("Run active Python");
    check("Run active Python disabled while trusted Python is off", await runPython.isDisabled());
    check("Mosaic says Python is not executed until trusted", Boolean(await waitText(/not executed until trusted local Python is enabled/, 10000)));
    check("trusted Python off badge", /trusted Python off/.test(await wbText()));
    await (await wbButton("Enable trusted local Python…")).click();
    await page.locator(".monaco-dialog-box").getByRole("button", { name: "Enable trusted local Python" }).click();
    await (await workbench()).getByText("trusted Python on").first().waitFor({ timeout: 120000 });
    await (await workbench()).getByRole("button", { name: "Stop runtime", exact: true }).first().waitFor({ timeout: 180000 });
    check("trusted Python enabled through the confirmation dialog", jsonFile(ws(".datapass", "project.json"))?.runtime?.trustedLocalPython === true);
    const enabled = await waitFor(async () => !(await (await wbButton("Run active Python")).isDisabled().catch(() => true)), 120000, 500);
    check("Run active Python enabled after the runtime restart", enabled);
    await (await wbButton("Run active Python")).click();
    check("Python file really runs (stdout shown)", Boolean(await waitText(/py_answer 42/, 90000)));
  });

  await step(5, "Learning: read, concept check, ran locally, verified, flashcard", async () => {
    await command("Datapass: Open Learning");
    let f = await learning(90000);
    // A concept check: Learning's Submit goes to Practice, which records it; it never verifies the lesson.
    const quizStarter = JSON.parse(read(path.join(repo, "content", "exercise-packs", "concepts-v1", "exercises.json"))).find(item => item.id === QUIZ).starter_source;
    const quizFile = ws("exercises", QUIZ, "quiz", "solution.txt");
    mkdirSync(path.dirname(quizFile), { recursive: true });
    writeFileSync(quizFile, quizStarter.replace(/answer:\s*$/, "answer: a\n"));
    f = await openLesson("partitions and pruning", "Files, partitions and pruning");
    f = await lessonMode("Exercise");
    await f.getByRole("button", { name: "Submit solution", exact: true }).click();
    f = await learning();
    await f.getByRole("heading", { name: "Last submit: passed", exact: true }).waitFor({ timeout: 120000 });
    f = await learning();
    await f.getByText(/Checks 1\/2 passed/).first().waitFor({ timeout: 30000 }).catch(() => undefined);
    let chips = await levelChips();
    check("concept check recorded: quiz level shown", /Checks 1\/2 passed/.test(chips), chips);
    check("concept check does not verify the lesson", !/Practice passed/.test(chips), chips);
    // Read, run (executed, not graded), then verify on the join lesson.
    f = await openLesson("Join rows", "Join rows, not circles");
    f = await lessonMode("Read");
    await f.getByRole("button", { name: "Mark as read", exact: true }).click();
    f = await learning();
    await f.getByText("Read (self-reported)", { exact: true }).first().waitFor();
    check("read level is a self-report", /Read \(self-reported\)/.test(await levelChips()));
    f = await lessonMode("Try");
    const example = ws("notebooks", "learning", "sql-joins", "example.sql");
    check("Try creates the native example", await waitFor(() => existsSync(example), 15000));
    f = await learning();
    await f.getByRole("button", { name: "Run example", exact: true }).click();
    f = await learning();
    await f.getByRole("heading", { name: "Real local result rows", exact: true }).waitFor({ timeout: 90000 });
    await waitFor(async () => /Ran locally, not graded/.test(await levelChips()), 15000);
    chips = await levelChips();
    check("Run example: ran locally, not graded", /Ran locally, not graded/.test(chips), chips);
    check("a local run does not verify", !/Practice passed/.test(chips), chips);
    const reference = JSON.parse(read(path.join(repo, "content", "exercise-packs", "sql-lab-v1", "grading.server.json")))[JOIN_EXERCISE].solution;
    const exerciseFile = ws("exercises", JOIN_EXERCISE, "sql", "solution.sql");
    mkdirSync(path.dirname(exerciseFile), { recursive: true });
    writeFileSync(exerciseFile, reference);
    f = await lessonMode("Exercise");
    await f.getByRole("button", { name: "Submit solution", exact: true }).click();
    f = await learning();
    await f.getByRole("heading", { name: "Last submit: passed", exact: true }).waitFor({ timeout: 120000 });
    await waitFor(async () => /Practice passed/.test(await levelChips()), 30000);
    chips = await levelChips();
    check("linked Practice Submit verifies the lesson", /Practice passed/.test(chips), chips);
    check("the four levels stay separate chips", ["Read (self-reported)", "Ran locally, not graded", "Practice passed"].every(text => chips.includes(text)), chips);
    const progress = jsonFile(ws(".datapass", "progress.json"));
    check("Practice progress records the verified exercise", Boolean(progress?.practice?.exercises?.[`sql-lab-v1/${JOIN_EXERCISE}/sql`]?.solved
      || Object.entries(progress?.practice?.exercises ?? {}).some(([key, value]) => key.includes(JOIN_EXERCISE) && value?.solved)));
    // Flashcards: self-rated, kept apart from Practice.
    await command("Datapass: Review Learning Flashcards");
    f = await learning();
    await f.getByText("Self-rated, not graded", { exact: true }).first().waitFor();
    ratedCard = (await f.locator(".card-front").first().innerText()).trim();
    await f.getByRole("button", { name: "Show answer", exact: true }).click();
    f = await learning();
    await f.getByRole("button", { name: "Knew it", exact: true }).click();
    f = await learning();
    const moved = await waitFor(async () => ((await (await learning()).locator(".card-front").first().innerText().catch(() => "")).trim() !== ratedCard), 15000);
    check("flashcard rated (Knew it) and the session moves on", moved, ratedCard);
    f = await learning();
    await f.getByRole("button", { name: "Close review", exact: true }).click();
    f = await learning();
    await f.getByRole("heading", { name: "Join rows, not circles", exact: true }).waitFor();
    check("review closes back to the lesson", true);
  });

  await step(6, "Cloud Lab Pipelines: palette, connect, undo, redo, save, unknown property kept, run", async () => {
    await command("Datapass: Open Cloud Lab");
    await workbench(60000);
    await subtab("Pipelines");
    const pipelineFile = ws(...PIPELINE.split("/"));
    const create = await wbButton("Create lab files");
    if (await create.count()) await create.click();
    check("Create lab files copies the samples into factory/", await waitFor(() => existsSync(pipelineFile), 30000));
    // An unknown property, planted at the top and inside an activity, before the editor reads the file.
    const planted = JSON.parse(read(pipelineFile));
    planted.x_acceptance_marker = MARKER;
    planted.properties.activities[0].x_acceptance_activity = "kept";
    writeFileSync(pipelineFile, JSON.stringify(planted, null, 2) + "\n");
    await sleep(1500);
    await command("Datapass: Open Cloud Lab");
    await subtab("Pipelines");
    let f = await workbench();
    await f.getByRole("tab", { name: /Microsoft Fabric/ }).click();
    await f.getByRole("toolbar", { name: "Pipeline editor" }).waitFor({ timeout: 30000 });
    await f.getByRole("button", { name: "Add Wait (Wait)", exact: true }).click();
    f = await workbench();
    const props = f.getByRole("region", { name: "Properties of Wait1" });
    check("palette adds Wait1 at the top level", await props.waitFor({ timeout: 15000 }).then(() => true, () => false));
    await props.getByRole("combobox", { name: "Activity to run after" }).selectOption("Has gold rows");
    await props.getByRole("combobox", { name: "Dependency condition" }).selectOption("Completed");
    await props.getByRole("button", { name: "Add dependency", exact: true }).click();
    const dependency = () => f.getByRole("region", { name: "Properties of Wait1" }).getByRole("group", { name: "Has gold rows" });
    check("Wait1 connected after Has gold rows", await dependency().waitFor({ timeout: 10000 }).then(() => true, () => false));
    const toolbar = f.getByRole("toolbar", { name: "Pipeline editor" });
    await toolbar.getByRole("button", { name: "Undo", exact: true }).click();
    check("Undo removes the dependency", await dependency().waitFor({ state: "detached", timeout: 10000 }).then(() => true, () => false));
    await toolbar.getByRole("button", { name: "Redo", exact: true }).click();
    check("Redo restores the dependency", await dependency().waitFor({ timeout: 10000 }).then(() => true, () => false));
    check("file untouched before Save", !read(pipelineFile).includes("Wait1"));
    await toolbar.getByRole("button", { name: "Save", exact: true }).click();
    const saved = await waitFor(() => read(pipelineFile).includes("Wait1"), 20000);
    const disk = jsonFile(pipelineFile);
    const wait = disk?.properties?.activities?.find(activity => activity.name === "Wait1");
    check("Save writes Wait1 with its dependency", saved && wait?.type === "Wait" && wait.dependsOn?.some(dep => dep.activity === "Has gold rows" && dep.dependencyConditions?.includes("Completed")), JSON.stringify(wait));
    check("unknown top-level property preserved on disk", JSON.stringify(disk?.x_acceptance_marker) === JSON.stringify(MARKER));
    check("unknown activity property preserved on disk", disk?.properties?.activities?.[0]?.x_acceptance_activity === "kept");
    f = await workbench();
    await f.getByRole("toolbar", { name: "Pipeline editor" }).getByRole("button", { name: "Save", exact: true }).waitFor();
    await waitFor(async () => (await (await workbench()).getByRole("button", { name: "Dry run", exact: true }).isEnabled().catch(() => false)), 20000);
    await (await wbButton("Dry run")).click();
    f = await workbench();
    const runRow = f.locator(".factory-runs tr", { hasText: "Wait1" }).first();
    const shown = await runRow.waitFor({ timeout: 90000 }).then(() => true, () => false);
    const rowText = shown ? (await runRow.innerText()).replace(/\s+/g, " ") : "";
    check("Dry run shows the new activity's simulated status (Wait1 runs after Has gold rows completes)", shown && /Succeeded/.test(rowText) && /simulated/.test(rowText), rowText);
    check("the run is labelled a dry run", /dry run/i.test(await wbText()));
  });

  await step(7, "Infra Lab: tf-first-apply in the simulated terminal, Check my work passes", async () => {
    await command("Datapass: Open Infra Lab");
    const f = await workbench(60000);
    await f.getByRole("tab", { name: "Infra Lab", selected: true }).waitFor({ timeout: 60000 });
    const mission = JSON.parse(read(path.join(repo, "content", "missions", "infra-v1", "tf-first-apply", "mission.json")));
    await f.locator(".mission-card", { hasText: mission.title }).first().click();
    await (await wbButton("Start mission")).click();
    const folder = ws("missions", "tf-first-apply");
    check("mission folder built from the pack", await waitFor(() => existsSync(path.join(folder, "main.tf")), 60000));
    // The learner's files, saved as a learner would (the pack's solution overlay).
    const solution = path.join(repo, "content", "missions", "infra-v1", "tf-first-apply", "solution");
    for (const name of readdirSync(solution)) writeFileSync(path.join(folder, name), read(path.join(solution, name)));
    const journal = path.join(folder, ".infralab", "journal.jsonl");
    const journalLines = () => existsSync(journal) ? read(journal).split("\n").filter(Boolean).length : 0;
    const terminalInput = page.locator(".terminal-wrapper.active .xterm-helper-textarea, .terminal .xterm-helper-textarea").last();
    await terminalInput.waitFor({ timeout: 60000 });
    const lines = mission.reference.map(item => item.infra);
    const before = journalLines();
    for (const [index, line] of lines.entries()) {
      await terminalInput.focus();
      await page.keyboard.type(line, { delay: 2 });
      await page.keyboard.press("Enter");
      await waitFor(() => journalLines() > before + index, 30000);
    }
    check("every reference line reached the simulators", journalLines() - before === lines.length, `${journalLines() - before}/${lines.length}`);
    await command("Datapass: Open Infra Lab");
    await (await wbButton("Check my work")).click();
    check("Check my work: Mission passed.", Boolean(await waitText(/Mission passed\./, 60000)));
  });

  await step(8, "Interop: import an example (files, nothing run), export validates against the schema", async () => {
    const example = path.join(repo, "content", "interop", "examples", "mosaic-studio-sensors.json");
    const exchange = JSON.parse(read(example));
    const notebook = exchange.notebooks[0];
    const folder = ws("notebooks", "imported", notebook.id);
    await command("Datapass: Import Mosaic Exchange");
    check("import writes notebooks/imported/<id>/", await fileDialog(/Import a Mosaic exchange/, example, () => existsSync(folder) && readdirSync(folder).length > 0));
    await waitFor(() => readdirSync(folder).length >= notebook.cells.length, 10000);
    const files = filesUnder(folder);
    report.importedFiles = files;
    const sources = files.map(file => read(path.join(folder, file)));
    check("each cell is a native file with its source", notebook.cells.filter(cell => cell.kind !== "markdown").every(cell => sources.some(text => text.includes(cell.source.trim().split("\n")[0]))), files.join(", "));
    check("import notification says nothing was run", await page.locator(".notifications-toasts", { hasText: "Nothing was run" }).first().waitFor({ timeout: 15000 }).then(() => true, () => false));
    await command("Datapass: Open Mosaic");
    const f = await workbench();
    await f.getByRole("button", { name: "Refresh", exact: true }).first().click();
    await sleep(1500);
    const catalog = (await f.locator(".catalog-row strong").allInnerTexts().catch(() => [])).join(", ");
    check("imported cells were not executed (no table they create)", !/sensor_readings|sensor_daily/.test(catalog), catalog || "(empty catalog)");
    await command("Datapass: Export Mosaic Exchange");
    await page.locator(".quick-input-widget .quick-input-title", { hasText: "Export a Mosaic exchange" }).first().waitFor();
    await page.keyboard.press("Enter");
    const target = ws(`${notebook.id}.mosaic-exchange.json`);
    check("export written", await fileDialog(async () => /mosaic-exchange\.json$/.test(await quickInput().inputValue().catch(() => "")), target, () => existsSync(target)));
    const exported = jsonFile(target);
    const schema = JSON.parse(read(path.join(repo, "schemas", "mosaic-exchange.schema.json")));
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    const valid = ajv.compile(schema);
    check("export validates against schemas/mosaic-exchange.schema.json", exported && valid(exported), ajv.errorsText(valid.errors));
    check("export holds the imported notebook", exported?.notebooks?.some(item => item.id === notebook.id));
    check("export carries no data (artifacts are names and hashes)", (exported?.artifacts ?? []).every(item => !("rows" in item) && !("data" in item)));
  });

  await step(9, "Close and relaunch VS Code: progress, files, results and pipeline edit persist", async () => {
    await close();
    await launch(executable);
    await firstCommand("Datapass: Resume Learning");
    let f = await learning(120000);
    check("Learning resumes at the same lesson", await f.getByRole("heading", { name: "Join rows, not circles", exact: true }).waitFor({ timeout: 30000 }).then(() => true, () => false));
    const chips = await levelChips();
    check("read, ran locally and verified persist", ["Read (self-reported)", "Ran locally, not graded", "Practice passed"].every(text => chips.includes(text)), chips);
    f = await openLesson("partitions and pruning", "Files, partitions and pruning");
    const quizChips = await levelChips();
    check("concept check level persists and still does not verify", /Checks 1\/2 passed/.test(quizChips) && !/Practice passed/.test(quizChips), quizChips);
    await command("Datapass: Review Learning Flashcards");
    f = await learning();
    await f.getByText("Self-rated, not graded", { exact: true }).first().waitFor();
    const first = (await f.locator(".card-front").first().innerText().catch(() => "")).trim();
    check("flashcard rating persists (the rated card is not offered again)", Boolean(ratedCard) && first !== ratedCard, `rated "${ratedCard}", now "${first}"`);
    await f.getByRole("button", { name: "Close review", exact: true }).click();
    await f.getByRole("heading", { name: "Files, partitions and pruning", exact: true }).waitFor().catch(() => undefined);
    // Back to the join lesson so a later resume finds it again.
    await openLesson("Join rows", "Join rows, not circles");
    check("Build files exist unchanged", read(ws("notebooks", SQL_NAME)) === SQL_TEXT && read(ws("notebooks", PY_NAME)) === PY_TEXT);
    check("datasets exist unchanged", read(ws("datasets", "orders_acc.csv")) === CSV_FIRST && read(ws("datasets", "orders_acc-2.csv")) === CSV_SECOND);
    await command("Datapass: Open Mosaic");
    f = await workbench(90000);
    const history = f.locator(".query-history summary");
    check("Mosaic query history survives the restart", await history.waitFor({ timeout: 30000 }).then(() => true, () => false));
    await (await wbButton("Start runtime")).click();
    await (await workbench()).getByRole("button", { name: "Stop runtime", exact: true }).first().waitFor({ timeout: 180000 });
    f = await workbench();
    await f.locator(".query-history summary").click();
    const entry = f.locator(".query-history-row", { hasText: SQL_NAME }).first();
    check("history entry names the Build SQL file", await entry.waitFor({ timeout: 10000 }).then(() => true, () => false));
    const before = (await entry.innerText()).replace(/\s+/g, " ");
    await entry.getByRole("button", { name: "Run again", exact: true }).click();
    // A re-run replaces the entry of the same SQL with a new one (new time), at the top.
    let after = before;
    await waitFor(async () => {
      after = ((await (await workbench()).locator(".query-history-row").first().innerText().catch(() => "")) || "").replace(/\s+/g, " ");
      return after !== before && after.includes(SQL_NAME);
    }, 60000);
    check("the SQL result is reproducible from history (Run again on the restarted runtime)",
      after !== before && /success/.test(after) && /1 rows/.test(after), `${before} -> ${after}`);
    const disk = jsonFile(ws(...PIPELINE.split("/")));
    check("pipeline edit persisted on disk", disk?.properties?.activities?.some(activity => activity.name === "Wait1") && JSON.stringify(disk?.x_acceptance_marker) === JSON.stringify(MARKER));
    await command("Datapass: Open Cloud Lab");
    await subtab("Pipelines");
    f = await workbench();
    await f.getByRole("tab", { name: /Microsoft Fabric/ }).click();
    check("pipeline editor shows Wait1 after the restart", await f.locator(".factory-editor").getByText("Wait1").first().waitFor({ timeout: 30000 }).then(() => true, () => false));
    await (await wbButton("Stop runtime")).click().catch(() => undefined);
  });

  await step(10, "No uncaught webview console errors", async () => {
    const uncaught = report.webviewErrors.filter(text => /Uncaught|Minified React error|Unhandled/i.test(text));
    check("no uncaught webview error", uncaught.length === 0, uncaught.slice(0, 3).join(" | "));
    check(`webview console errors recorded: ${report.webviewErrors.length}`, true, report.webviewErrors.slice(0, 3).join(" | "));
  });
  report.completed = true;
} catch (error) {
  report.failure = String(error?.stack ?? error).slice(0, 2000);
  console.error(`FAIL setup - ${String(error?.message ?? error).split("\n")[0]}`);
  await dumpFailure("fatal");
} finally {
  try { await close(); } catch (error) { report.closeError = String(error); }
  report.seconds = Math.round((Date.now() - started) / 1000);
  writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
}
const failed = report.steps.filter(item => item.status !== "PASS");
console.log(`${report.steps.length - failed.length}/${report.steps.length} steps passed in ${report.seconds} s. Report: ${path.join(out, "report.json")}`);
process.exitCode = !report.completed || failed.length || report.steps.length < 10 ? 1 : 0;
