// Drive the packaged VSIX in a real VS Code window with Playwright (`_electron.launch`), the way a learner uses it:
//
//   npm run package && npm run test:ui
//
// 1. Install the newest *.vsix (or DATAPASS_UI_VSIX) into a fresh, disposable profile of a VS Code test build.
// 2. Workbench: Create .datapass project, Setup runtime (managed venv), Start runtime.
// 3. The live runtime refuses a raw request without the launch token (401) and a foreign Host (400).
// 4. Mosaic: the SQL scratch file, Run active SQL, the result row in the webview.
// 5. Practice: Submit the first exercise's starter; the runtime grades it.
// 5b. Infra Lab: a mission started, its commands typed in the simulated terminal, Check my work passes.
// 6. Layout: every module tab, and every lab sub-tab, at a narrow Workbench width. No element may stick out of the
//    webview (the PR #17 class of bug); a screenshot of each lands in the output folder.
// 7. Stop runtime.
// 8. Upgrade: the managed venv is made to look like an older VSIX set it up (another runtime fingerprint in its
//    marker, a changed installed module); after a window reload the Workbench must report it stale ("needs update",
//    no Start runtime), Update runtime must reinstall this VSIX's runtime, and the runtime must start again.
//
// Environment:
//   DATAPASS_UI_VSIX       the VSIX to install (default: the newest *.vsix in the repository root)
//   DATAPASS_UI_ROOT       profile/workspace root, wiped first. Keep it SHORT on Windows (default C:\dpw-ui): the
//                          managed venv lives under the profile and DuckDB's DLL path must stay below MAX_PATH.
//   DATAPASS_UI_OUT        screenshots and results (default test-results/vscode-ui)
//   DATAPASS_UI_PYTHON     base Python for Setup runtime, written to the manifest's runtime.pythonCommand
//                          (default: the manifest's own default, `python` on PATH)
//   VSCODE_TEST_VERSION    VS Code build to download (default stable); DATAPASS_UI_CODE uses an installed Code instead
//   DATAPASS_UI_KEEP=1     keep the profile, so a rerun skips Setup runtime. When the VSIX's runtime changed since
//                          the kept venv was set up, the pass clicks Update runtime instead (the stale-runtime path).
//
// On Linux run under a virtual display with a real screen size:
//   xvfb-run -a --server-args="-screen 0 1600x1000x24" npm run test:ui
import { spawnSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath } from "@vscode/test-electron";
import { _electron } from "playwright-core";

const repo = process.cwd();
const isWindows = process.platform === "win32";
const root = path.resolve(process.env.DATAPASS_UI_ROOT || (isWindows ? "C:\\dpw-ui" : path.join(tmpdir(), "dpw-ui")));
const out = path.resolve(process.env.DATAPASS_UI_OUT || path.join(repo, "test-results", "vscode-ui"));
const workspace = path.join(root, "ws");
const extensionsDir = path.join(root, "x");
const userDataDir = path.join(root, "u");
// Setup runtime's managed venv, in the extension's global storage, and the marker naming the runtime it installed.
const venvRoot = path.join(userDataDir, "User", "globalStorage", "datapass.datapass-mosaic-vscode", "runtime-venv");
const markerFile = path.join(venvRoot, "datapass-runtime.json");
// Workbench width for the layout pass: about a third of a laptop screen, where PR #17's overflow showed.
const NARROW_WIDTH = 520;

const results = [];
function step(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` - ${detail}` : ""}`);
}

function newestVsix() {
  if (process.env.DATAPASS_UI_VSIX) return path.resolve(process.env.DATAPASS_UI_VSIX);
  const files = readdirSync(repo).filter(name => name.endsWith(".vsix"))
    .map(name => path.join(repo, name))
    .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  if (!files.length) throw new Error("No .vsix in the repository root: run `npm run package` first (or set DATAPASS_UI_VSIX).");
  return files[0];
}

// ---------------------------------------------------------------------------------------------------------------
// Profile and install.

const vsix = newestVsix();
if (process.env.DATAPASS_UI_KEEP !== "1") rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
rmSync(workspace, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
rmSync(out, { recursive: true, force: true });
for (const dir of [workspace, extensionsDir, userDataDir, out]) mkdirSync(dir, { recursive: true });
mkdirSync(path.join(userDataDir, "User"), { recursive: true });
writeFileSync(path.join(userDataDir, "User", "settings.json"), JSON.stringify({
  "workbench.startupEditor": "none",
  "workbench.tips.enabled": false,
  "workbench.secondarySideBar.defaultVisibility": "hidden",
  "workbench.enableExperiments": false,
  "window.restoreWindows": "none",
  "window.dialogStyle": "custom",
  "window.titleBarStyle": "custom",
  "update.mode": "none",
  "extensions.autoUpdate": false,
  "extensions.ignoreRecommendations": true,
  "telemetry.telemetryLevel": "off",
  "security.workspace.trust.enabled": false,
  "chat.disableAIFeatures": true,
  "git.openRepositoryInParentFolders": "never"
}, null, 2));

const executable = process.env.DATAPASS_UI_CODE || await downloadAndUnzipVSCode(process.env.VSCODE_TEST_VERSION || "stable");
const [cli, ...cliArgs] = resolveCliArgsFromVSCodeExecutablePath(executable);
const install = spawnSync(cli, [...cliArgs, `--extensions-dir=${extensionsDir}`, `--user-data-dir=${userDataDir}`,
  "--install-extension", vsix, "--force"], { encoding: "utf8", shell: isWindows, timeout: 600000 });
const installed = readdirSync(extensionsDir).some(name => name.startsWith("datapass.datapass-mosaic-vscode-"));
step("VSIX installed in a fresh profile", install.status === 0 && installed,
  `${path.basename(vsix)}${install.status === 0 ? "" : `: ${(install.stderr || install.stdout || "").trim().slice(-400)}`}`);
if (!installed) finish();

// ---------------------------------------------------------------------------------------------------------------
// VS Code.

const app = await _electron.launch({
  executablePath: executable,
  args: [
    workspace,
    `--extensions-dir=${extensionsDir}`,
    `--user-data-dir=${userDataDir}`,
    "--disable-workspace-trust",
    "--skip-welcome",
    "--skip-release-notes",
    "--disable-telemetry",
    "--new-window",
    ...(isWindows ? [] : ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
  ],
  timeout: 180000
});
const page = await app.firstWindow();
page.setDefaultTimeout(30000);

const webviewErrors = [];
page.on("console", message => {
  if (message.type() === "error" && /vscode-webview:/.test(message.location()?.url ?? "")) webviewErrors.push(message.text());
});

const web = () => page.frameLocator("iframe.webview.ready").frameLocator("iframe#active-frame");
const button = name => web().getByRole("button", { name, exact: true });
const bodyText = () => web().locator("body").innerText();

async function command(title) {
  await page.keyboard.press("Escape");
  await page.keyboard.press("F1");
  const input = page.locator(".quick-input-widget input");
  await input.waitFor();
  await input.fill(`>${title}`);
  await page.locator(".quick-input-list .monaco-list-row", { hasText: title }).first().waitFor();
  await page.keyboard.press("Enter");
}

async function openWorkbench(command_ = "Datapass: Open Mosaic") {
  await command(command_);
  await web().getByRole("tab", { name: "Mosaic" }).waitFor({ timeout: 90000 });
}

async function waitForText(pattern, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let text = "";
  while (Date.now() < deadline) {
    text = await bodyText().catch(() => "");
    const match = pattern.exec(text);
    if (match) return match;
    await page.waitForTimeout(500);
  }
  return null;
}

async function shot(name) {
  await page.screenshot({ path: path.join(out, `${name}.png`), scale: "css" }).catch(() => undefined);
}

function slug(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// Elements that stick out on the right of the webview and are not inside a container that scrolls or clips them
// (tables, graphs and code blocks scroll on purpose). Only the outermost offender of each subtree is reported.
function overflowProbe(_body, options = {}) {
  const planted = document.createElement("div");
  if (options.plant) {
    planted.id = "ui-pass-overflow";
    planted.style.cssText = "width:2000px;height:10px";
    document.querySelector(".module-main")?.appendChild(planted);
  }
  const width = document.documentElement.clientWidth;
  const clipped = element => {
    for (let node = element.parentElement; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
      if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(node).overflowX)) return true;
    }
    return false;
  };
  const offenders = new Set();
  for (const element of document.body.querySelectorAll("*")) {
    const box = element.getBoundingClientRect();
    if (!box.width || !box.height || box.right <= width + 1) continue;
    if (getComputedStyle(element).visibility === "hidden" || clipped(element)) continue;
    if (element.parentElement && offenders.has(element.parentElement)) { offenders.add(element); continue; }
    offenders.add(element);
  }
  const outermost = [...offenders].filter(element => !offenders.has(element.parentElement));
  const chain = [];
  for (let node = planted.parentElement; node; node = node.parentElement) {
    chain.push(`${node.tagName.toLowerCase()}.${String(node.className).split(/\s+/)[0]}:${getComputedStyle(node).overflowX}`);
  }
  const result = {
    planted: options.plant ? { attached: planted.isConnected, right: Math.round(planted.getBoundingClientRect().right), chain } : undefined,
    width,
    scrollWidth: document.documentElement.scrollWidth,
    offenders: outermost.slice(0, 6).map(element => {
      const box = element.getBoundingClientRect();
      const name = `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${element.className && typeof element.className === "string" ? `.${element.className.trim().split(/\s+/).slice(0, 2).join(".")}` : ""}`;
      return `${name} "${(element.textContent || "").trim().slice(0, 40)}" right=${Math.round(box.right)}`;
    })
  };
  planted.remove();
  return result;
}

async function checkLayout(label) {
  await page.waitForTimeout(700);
  const probe = await web().locator("body").evaluate(overflowProbe);
  const overflow = probe.scrollWidth > probe.width + 1 || probe.offenders.length > 0;
  await shot(`layout-${slug(label)}`);
  step(`Layout at ${probe.width}px: ${label}`, !overflow,
    overflow ? `scrollWidth ${probe.scrollWidth}; ${probe.offenders.join("; ")}` : "");
}

async function setWindowWidth(width) {
  await app.evaluate(({ BrowserWindow }, size) => {
    const window = BrowserWindow.getAllWindows()[0];
    window.unmaximize();
    window.setSize(size.width, size.height);
  }, { width, height: 900 });
  await page.waitForTimeout(800);
}

function runtimePort() {
  const logs = [];
  const walk = dir => {
    for (const name of existsSync(dir) ? readdirSync(dir) : []) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (/Datapass Runtime/i.test(name)) logs.push(full);
    }
  };
  walk(path.join(userDataDir, "logs"));
  const text = logs.map(file => readFileSync(file, "utf8")).join("\n");
  return { text, port: [...text.matchAll(/Uvicorn running on http:\/\/127\.0\.0\.1:(\d+)/g)].at(-1)?.[1] };
}

/** The runtime package's __init__.py as installed in the managed venv (Lib/ on Windows, lib/pythonX.Y/ elsewhere). */
function installedRuntimeInit() {
  const sitePackages = [path.join(venvRoot, "Lib", "site-packages")];
  const lib = path.join(venvRoot, "lib");
  for (const name of existsSync(lib) ? readdirSync(lib) : []) sitePackages.push(path.join(lib, name, "site-packages"));
  return sitePackages.map(dir => path.join(dir, "datapass_runtime", "__init__.py")).find(file => existsSync(file));
}

function rawStatus(port, headers) {
  return new Promise(resolve => {
    const request = http.get({ host: "127.0.0.1", port, path: "/api/health", headers, timeout: 10000 }, response => {
      response.resume();
      resolve(response.statusCode);
    });
    request.on("timeout", () => request.destroy(new Error("timeout")));
    request.on("error", error => resolve(String(error)));
  });
}

try {
  await page.waitForSelector(".monaco-workbench", { timeout: 180000 });
  await setWindowWidth(1280);
  await command("View: Close Primary Side Bar");

  // --- Runtime --------------------------------------------------------------------------------------------------
  await openWorkbench();
  step("Workbench opened from the command palette", true);
  const create = button("Create .datapass project");
  if (await create.count()) {
    await create.click();
    await button("Create .datapass project").waitFor({ state: "detached", timeout: 60000 });
    step("Create .datapass project", existsSync(path.join(workspace, ".datapass", "project.json")));
  }
  if (process.env.DATAPASS_UI_PYTHON) {
    const manifestPath = path.join(workspace, ".datapass", "project.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    manifest.runtime = { ...manifest.runtime, pythonCommand: process.env.DATAPASS_UI_PYTHON };
    writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  }
  if (await button("Setup runtime").count()) {
    const started = Date.now();
    await button("Setup runtime").click();
    await button("Start runtime").waitFor({ timeout: 1200000 });
    step("Setup runtime (managed venv)", true, `${Math.round((Date.now() - started) / 1000)} s`);
  } else if (await button("Update runtime").count()) {
    // DATAPASS_UI_KEEP=1 with a VSIX whose runtime changed since the kept venv was set up.
    const started = Date.now();
    await button("Update runtime").click();
    await button("Start runtime").waitFor({ timeout: 1200000 });
    step("Update runtime (kept venv of another build)", true, `${Math.round((Date.now() - started) / 1000)} s`);
  }
  await button("Start runtime").click();
  await button("Stop runtime").waitFor({ timeout: 180000 });
  step("Start runtime", true);

  const { text: runtimeLog, port } = runtimePort();
  step("Runtime port found in the Datapass Runtime log", Boolean(port), `port ${port}`);
  // The token is 32 random bytes in hex. pip's wheel hashes ("sha256=…") have the same shape and are not secrets.
  const tokenLike = [...runtimeLog.matchAll(/(.{0,24})\b([0-9a-f]{64})\b/g)].filter(match => !/sha256[=:]\s*$/i.test(match[1]));
  step("No launch token in the runtime log", tokenLike.length === 0,
    tokenLike.slice(0, 2).map(match => `${match[1].trim()}<64 hex>`).join(" | "));
  if (port) {
    const noToken = await rawStatus(port, {});
    step("Raw request without the launch token is refused (401)", noToken === 401, String(noToken));
    const rebound = await rawStatus(port, { host: `rebind.example:${port}`, "x-datapass-token": "guess" });
    step("Raw request with a foreign Host is refused (400)", rebound === 400, String(rebound));
  }

  // --- Mosaic SQL -----------------------------------------------------------------------------------------------
  // The learner's query goes into the scratch file on disk (typing into Monaco through Electron is flaky); the
  // Workbench then runs the open scratch editor's text.
  mkdirSync(path.join(workspace, "notebooks"), { recursive: true });
  writeFileSync(path.join(workspace, "notebooks", "mosaic.sql"), "SELECT 40 + 2 AS answer_ui;\n");
  await button("Open SQL scratch").click();
  await page.locator(".tab.active", { hasText: "mosaic.sql" }).waitFor();
  await page.locator(".editor-instance .view-lines", { hasText: "answer_ui" }).first().waitFor();
  await openWorkbench();
  await button("Run active SQL").click();
  const sqlRow = await waitForText(/answer_ui\s+42/, 60000);
  step("Mosaic Run active SQL shows the DuckDB result", Boolean(sqlRow), sqlRow ? JSON.stringify(sqlRow[0]) : "no answer_ui row");
  await shot("mosaic-sql");

  // --- Practice Submit ------------------------------------------------------------------------------------------
  // The first card's starter file is created by Open solution; Submit then grades it (the starter is expected to fail).
  await command("Datapass: Open Practice");
  await button("Open solution").first().waitFor({ timeout: 60000 });
  await button("Open solution").first().click();
  // Its editor tab is titled "<exercise> · <language>"; wait for the starter file itself.
  const starterDeadline = Date.now() + 30000;
  while (!readdirSync(workspace, { recursive: true }).some(name => /^exercises[\\/].*solution\.\w+$/.test(String(name)))) {
    if (Date.now() > starterDeadline) throw new Error("Open solution created no exercises/**/solution.* file.");
    await page.waitForTimeout(500);
  }
  await command("Datapass: Open Practice");
  await button("Submit").first().click();
  const graded = await web().locator(".practice-result").first().innerText({ timeout: 90000 }).catch(() => "");
  const status = /^Submission[\s\S]*?\b(passed|failed|error)\b/.exec(graded.trim());
  const errors = status ? [] : await web().locator(".error-text").allInnerTexts().catch(() => []);
  step("Practice Submit graded by the runtime", Boolean(status),
    status ? `status ${status[1]}` : (graded.slice(0, 200) || errors.join(" | ").slice(0, 300) || "no result"));
  await shot("practice-submit");

  // --- Infra Lab ------------------------------------------------------------------------------------------------
  // Start the SHIR alerts mission, type its commands in the simulated terminal (a Pseudoterminal: no process runs;
  // each line goes to the runtime's simulators), then Check my work.
  await command("Datapass: Open Infra Lab");
  await web().getByRole("tab", { name: "Infra Lab", selected: true }).waitFor({ timeout: 60000 });
  await web().locator(".mission-card", { hasText: "self-hosted integration runtime" }).click();
  await button("Start mission").click();
  const infraFolder = path.join(workspace, "missions", "page-on-shir-outage");
  const journalFile = path.join(infraFolder, ".infralab", "journal.jsonl");
  const terminalInput = page.locator(".terminal-wrapper.active .xterm-helper-textarea, .terminal .xterm-helper-textarea").last();
  await page.locator(".terminal-tab, .single-terminal-tab", { hasText: "Infra Lab (simulated)" }).first().waitFor({ timeout: 60000 })
    .catch(() => undefined);
  await terminalInput.waitFor({ timeout: 60000 });
  const infraMission = JSON.parse(readFileSync(path.join(repo, "content", "missions", "infra-v1", "page-on-shir-outage", "mission.json"), "utf8"));
  const lines = infraMission.reference.map(item => item.infra);
  const journalLines = () => existsSync(journalFile) ? readFileSync(journalFile, "utf8").split("\n").filter(Boolean).length : 0;
  for (const [index, line] of lines.entries()) {
    await terminalInput.focus();
    await page.keyboard.type(line, { delay: 2 });
    await page.keyboard.press("Enter");
    for (let waited = 0; journalLines() <= index && waited < 30000; waited += 250) await page.waitForTimeout(250);
  }
  step("Infra Lab: lines typed in the simulated terminal reach the simulators", journalLines() === lines.length,
    `${journalLines()}/${lines.length} commands journaled`);
  await page.waitForTimeout(500);
  await shot("infra-terminal");
  await command("Datapass: Open Infra Lab");
  await button("Check my work").click();
  const infraPassed = await waitForText(/Mission passed\./, 60000);
  step("Infra Lab: the checker passes the mission on the simulated world", Boolean(infraPassed));
  const world = await waitForText(/Simulated clock/, 10000);
  step("Infra Lab: the simulated world is shown", Boolean(world));
  await shot("infra-lab");

  // --- Layout at a narrow width ---------------------------------------------------------------------------------
  // The Workbench sits beside the scratch editor; size the window so the webview is NARROW_WIDTH wide.
  const current = await web().locator("body").evaluate(() => document.documentElement.clientWidth);
  const windowWidth = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getSize()[0]);
  await setWindowWidth(Math.max(800, windowWidth - 2 * (current - NARROW_WIDTH)));
  // The probe must see a real overflow: a too-wide block in the module content.
  const planted = await web().locator("body").evaluate(overflowProbe, { plant: true });
  const seen = planted.offenders.some(text => text.startsWith("div#ui-pass-overflow"));
  step("Overflow probe detects a planted too-wide block", seen, seen ? "" : JSON.stringify(planted));
  const tabs = await web().locator("nav.module-tabs [role=tab]").allInnerTexts();
  step("Module tabs listed", tabs.length >= 9, tabs.join(", "));
  for (const tab of tabs) {
    await web().locator("nav.module-tabs").getByRole("tab", { name: tab, exact: true }).click();
    await web().locator("nav.module-tabs [role=tab][aria-selected=true]", { hasText: tab }).waitFor();
    await checkLayout(tab);
    if (tab === "SparkLab / ZilaCode") {
      // The Polars engine swaps the cluster controls for the trusted Python control.
      await web().locator(".sparklab-runbar select").first().selectOption("polars");
      await button("Run active file with Polars").waitFor();
      await checkLayout(`${tab} › Polars engine`);
      await web().locator(".sparklab-runbar select").first().selectOption("sparklab");
    }
    const subtabs = await web().locator(".lab-subtabs [role=tab]").allInnerTexts();
    for (const subtab of subtabs.slice(1)) {
      await web().locator(".lab-subtabs").getByRole("tab", { name: subtab, exact: true }).click();
      await checkLayout(`${tab} › ${subtab}`);
    }
  }
  await setWindowWidth(1280);

  // --- One action per lab ---------------------------------------------------------------------------------------
  // Each button's message goes through the Workbench's message table to its lab's controller (src/labs/<lab>): every
  // click must leave its mark on disk or in the runtime's answer. It runs after the layout checks, which look at the
  // labs as a fresh workspace shows them. The retail demo also crosses labs (its files come
  // from the Cloud Lab, Pipeline Lab, Airflow Lab and dbt Lab controllers).
  const onDisk = (...parts) => () => existsSync(path.join(workspace, ...parts));
  const shows = pattern => async () => pattern.test(await bodyText().catch(() => ""));
  async function labAction(label, commandTitle, act, checks, timeoutMs = 90000) {
    let detail = "";
    let ok = false;
    try {
      await command(commandTitle);
      await web().locator("nav.module-tabs [role=tab][aria-selected=true]").waitFor({ timeout: 60000 });
      await act();
      const deadline = Date.now() + timeoutMs;
      let pending = checks;
      while (pending.length && Date.now() < deadline) {
        const results = await Promise.all(pending.map(check => check()));
        pending = pending.filter((_, index) => !results[index]);
        if (pending.length) await page.waitForTimeout(500);
      }
      ok = pending.length === 0;
      if (!ok) detail = `${pending.length} of ${checks.length} checks not met`;
    } catch (error) {
      detail = String(error?.message ?? error).split("\n")[0].slice(0, 200);
    }
    step(`Lab controller: ${label}`, ok, detail);
  }
  const subtab = name => web().locator(".lab-subtabs").getByRole("tab", { name, exact: true }).click();
  await labAction("Cloud Lab creates the retail demo across labs", "Datapass: Open Cloud Lab", async () => {
    await subtab("Lakehouse and notebooks");
    await button("Create / repair demo files").click();
  }, [onDisk("datasets", "retail_orders.csv"), onDisk("pipelines", "main.pipeline.py"), onDisk("airflow", "dags", "retail_daily.py"),
    onDisk("dbt", "retail-dbt", "dbt_project.yml")]);
  await labAction("Cloud Lab runs the retail demo in the runtime", "Datapass: Open Cloud Lab", async () => {
    await subtab("Lakehouse and notebooks");
    await button("Run local medallion flow").click();
  }, [shows(/Retail demo completed with real local Polars \+ DuckDB execution/)]);
  await labAction("Cloud Lab copies its pipeline samples", "Datapass: Open Cloud Lab", async () => {
    await subtab("Pipelines");
    await button("Create lab files").click();
  }, [onDisk("factory")]);
  await labAction("BI Lab builds its warehouse", "Datapass: Open BI Lab", async () => {
    await button("Create lab files").first().click();
    await button("Build warehouse").click({ timeout: 60000 });
  }, [onDisk("bi", "model.json"), shows(/BI Lab: \d+ statement\(s\) ran on the local catalog/)], 180000);
  await labAction("Airflow Lab simulates the starter DAG", "Datapass: Open Airflow Lab",
    () => button("Simulate active DAG file").click(), [shows(/Airflow DAG retail_daily simulated/)]);
  await labAction("Pipeline Lab runs the starter pipeline", "Datapass: Open Pipeline Lab",
    () => button("Run pipeline").click({ timeout: 60000 }), [shows(/Pipeline \S+ (completed|finished with failures)\./)]);
  await labAction("Projects prepares a project's files", "Datapass: Open Projects",
    async () => {
      await web().locator(".project-card").first().getByRole("button").first().click();
      await button("Prepare files").click();
    },
    [() => existsSync(path.join(workspace, "projects")) && readdirSync(path.join(workspace, "projects")).length > 0]);
  await labAction("Terminal Lab opens a terminal", "Datapass: Open Terminal Lab",
    () => button("Open a terminal").click({ timeout: 60000 }),
    [async () => (await page.locator(".terminal-tab, .single-terminal-tab, .tabs-list .monaco-list-row", { hasText: "Terminal Lab" }).count()) > 0]);
  await shot("lab-controllers");

  // --- Stop runtime ---------------------------------------------------------------------------------------------
  await button("Stop runtime").click();
  await button("Start runtime").waitFor({ timeout: 60000 });
  step("Stop runtime", true);
  if (port) {
    // Stop sends SIGTERM; on Linux uvicorn then shuts down gracefully, so give it a moment, not forever.
    let after = await rawStatus(port, {});
    for (let waited = 0; typeof after !== "string" && waited < 15000; waited += 500) {
      await new Promise(resolve => setTimeout(resolve, 500));
      after = await rawStatus(port, {});
    }
    step("Runtime port closed after Stop", typeof after === "string", String(after));
  }

  // --- Upgrade over an existing managed venv ---------------------------------------------------------------------
  // What a newer VSIX finds: the venv an older one set up, with that build's marker and that build's installed code.
  const installed = JSON.parse(readFileSync(markerFile, "utf8"));
  step("Setup recorded this VSIX's runtime fingerprint in the managed venv",
    /^sha256:[0-9a-f]{64}$/.test(installed.fingerprint ?? ""), String(installed.fingerprint));
  writeFileSync(markerFile, JSON.stringify({ ...installed, fingerprint: `sha256:${"0".repeat(64)}`, extensionVersion: "0.0.1-older" }));
  const initFile = installedRuntimeInit();
  if (!initFile) throw new Error(`No installed datapass_runtime/__init__.py under ${venvRoot}.`);
  appendFileSync(initFile, "\nINSTALLED_BY_AN_OLDER_VSIX = True\n");
  await command("Developer: Reload Window");
  await page.waitForSelector(".monaco-workbench", { timeout: 180000 });
  await page.waitForTimeout(1500);
  await openWorkbench();
  const stale = await waitForText(/needs update[\s\S]*installed by Datapass 0\.0\.1-older/, 30000);
  const offersUpdate = await button("Update runtime").count() > 0;
  const offersStart = await button("Start runtime").count() > 0;
  step("Stale managed runtime reported after an upgrade (Update runtime, no Start runtime)",
    Boolean(stale) && offersUpdate && !offersStart, `stale text ${Boolean(stale)}, update ${offersUpdate}, start ${offersStart}`);
  await shot("runtime-stale");
  const updateStarted = Date.now();
  await button("Update runtime").click();
  await button("Start runtime").waitFor({ timeout: 1200000 });
  const updated = JSON.parse(readFileSync(markerFile, "utf8"));
  const reinstalled = !readFileSync(initFile, "utf8").includes("INSTALLED_BY_AN_OLDER_VSIX");
  step("Update runtime reinstalled this VSIX's runtime into the existing venv",
    updated.fingerprint === installed.fingerprint && reinstalled,
    `${Math.round((Date.now() - updateStarted) / 1000)} s; marker ${updated.fingerprint === installed.fingerprint ? "matches" : "differs"}; installed module ${reinstalled ? "replaced" : "still the old one"}`);
  await button("Start runtime").click();
  await button("Stop runtime").waitFor({ timeout: 180000 });
  step("Start runtime after the update", true);
  await button("Stop runtime").click();
  await button("Start runtime").waitFor({ timeout: 60000 });
} catch (error) {
  step("UI pass", false, String(error?.message ?? error).split("\n")[0].slice(0, 400));
  await shot("error");
  await button("Stop runtime").click({ timeout: 5000 }).catch(() => undefined);
}

const reactErrors = webviewErrors.filter(text => /Minified React error|Uncaught/.test(text));
step("No uncaught webview errors", reactErrors.length === 0, reactErrors.slice(0, 3).join(" | ").slice(0, 400));
await app.close().catch(() => undefined);
finish();

function finish() {
  const failed = results.filter(result => !result.ok);
  writeFileSync(path.join(out, "results.json"), JSON.stringify({ vsix: path.basename(vsix), results }, null, 2));
  console.log(`${results.length - failed.length}/${results.length} steps passed. Screenshots: ${out}`);
  process.exit(failed.length ? 1 : 0);
}
