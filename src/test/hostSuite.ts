/**
 * Extension Development Host E2E suite (run by scripts/extension_host_e2e.mjs).
 *
 * Runs inside a real VS Code extension host against a disposable workspace.
 * Webview button clicks are not automated; instead the suite drives the same
 * host classes the Workbench panel uses, against a real local runtime, in the
 * order of the documented manual smoke path.
 *
 * The runner injects DATAPASS_TRUSTED_PYTHON=1 into the host environment on
 * purpose: the runtime must still start with trusted Python disabled.
 */
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { loadAirflowState } from "../airflowState";
import { loadDbtState } from "../dbtState";
import { loadExerciseCatalog } from "../exerciseCatalog";
import { MODULES } from "../modules";
import { decodeCsvBytes, suggestBronzeAsset, validateBronzeAsset } from "../platform/csvImport";
import { readMosaicLayout, writeMosaicLayout } from "../mosaicLayoutStore";
import { loadPipelineState } from "../pipelineState";
import {
  createDefaultProjectManifest,
  readProjectManifest,
  withTrustedLocalPython,
  writeProjectManifest
} from "../project/projectManifest";
import { ACKNOWLEDGED_KEY, PythonTrustController } from "../pythonTrustController";
import { RuntimeManager } from "../runtimeManager";
import { retailOrdersCsv, retailSqlStarter } from "../scaffold/retailDemo";
import { airflowStarter, pipelineStarter, scratchSpec } from "../scaffold/starters";

const EXTENSION_ID = "datapass.datapass-mosaic-vscode";

type Step = [name: string, body: () => Promise<void>];

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension(EXTENSION_ID);
  assert.ok(extension, `${EXTENSION_ID} is not loaded in the extension host.`);
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  assert.ok(root, "The E2E runner must open a workspace folder.");
  const python = process.env.DATAPASS_E2E_PYTHON?.trim();
  let runtime: RuntimeManager | undefined;

  const write = (relative: string, content: string) =>
    vscode.workspace.fs.writeFile(vscode.Uri.joinPath(root, ...relative.split("/")), new TextEncoder().encode(content));

  const hostSteps: Step[] = [
    ["extension activates and registers every Workbench command", async () => {
      await extension.activate();
      const commands = await vscode.commands.getCommands(true);
      for (const module of MODULES) assert.ok(commands.includes(module.command), module.command);
    }],
    ["Mosaic command opens the Workbench webview", async () => {
      await vscode.commands.executeCommand("datapass.openMosaic");
      await waitFor("Workbench webview tab", () =>
        vscode.window.tabGroups.all
          .flatMap(group => group.tabs)
          .some(tab => tab.label === "Datapass Workbench" && tab.input instanceof vscode.TabInputWebview)
      );
    }],
    ["project manifest is created with trusted Python disabled", async () => {
      const folderName = vscode.workspace.workspaceFolders![0].name;
      await writeProjectManifest(createDefaultProjectManifest(folderName));
      const read = await readProjectManifest();
      assert.deepEqual(read.errors, []);
      assert.equal(read.manifest?.runtime?.trustedLocalPython, false);
    }],
    ["trusted Python needs manifest opt-in AND local confirmation", async () => {
      assert.equal(vscode.workspace.isTrusted, true, "runner disables Workspace Trust prompts");
      const trust = new PythonTrustController({ workspaceState: new MemoryMemento() });
      assert.equal((await trust.resolve()).state, "disabled");

      const manifest = (await readProjectManifest()).manifest!;
      await writeProjectManifest(withTrustedLocalPython(manifest, true));
      const requested = await trust.resolve();
      assert.equal(requested.state, "requested", "a manifest flag alone must not enable Python");
      assert.equal(requested.effective, false);

      const confirmed = new PythonTrustController({ workspaceState: new MemoryMemento({ [ACKNOWLEDGED_KEY]: true }) });
      assert.equal((await confirmed.resolve()).effective, true);

      assert.equal(await confirmed.disable(), true);
      assert.equal((await readProjectManifest()).manifest?.runtime?.trustedLocalPython, false);
      assert.equal((await confirmed.resolve()).state, "disabled");
    }],
    ["Mosaic layout persists to .datapass/mosaic.json and rejects bad input", async () => {
      assert.equal(await readMosaicLayout(), undefined, "no project layout before the first save");
      const custom = [
        { i: "python", x: 0, y: 0, w: 12, h: 10 },
        { i: "sql", x: 0, y: 10, w: 6, h: 8 },
        { i: "data", x: 6, y: 10, w: 6, h: 8 },
        { i: "notes", x: 0, y: 18, w: 12, h: 5 }
      ];
      assert.equal(await writeMosaicLayout(custom), true);
      assert.deepEqual(await readMosaicLayout(), custom);
      assert.equal(await writeMosaicLayout([{ i: "evil", x: 0, y: 0, w: 1, h: 1 }]), false);
      assert.deepEqual(await readMosaicLayout(), custom, "rejected input must not overwrite the file");
      await write(".datapass/mosaic.json", "{corrupt");
      assert.equal(await readMosaicLayout(), undefined, "corrupt file falls back to defaults");
    }],
    ["Airflow starter loads as a valid simulated DAG", async () => {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, "airflow"));
      await write("airflow/main.dag.json", airflowStarter());
      const airflow = await loadAirflowState();
      assert.equal(airflow.valid, true, airflow.errors.join("; "));
      assert.equal(airflow.graph.nodes.length, 4);
      assert.equal(airflow.graph.edges.length, 3);
    }],
    ["dbt sample shows static lineage without claiming a run", async () => {
      await copyDirectory(
        vscode.Uri.joinPath(extension.extensionUri, "samples", "dbt", "retail-dbt"),
        vscode.Uri.joinPath(root, "dbt", "retail-dbt")
      );
      const dbt = await loadDbtState();
      assert.equal(dbt.exists, true, dbt.errors.join("; "));
      assert.equal(dbt.lineageSource, "static");
      assert.ok(dbt.modelCount > 0 && dbt.graph.edges.length > 0);
    }]
  ];

  const runtimeSteps: Step[] = !python ? [] : [
    ["runtime starts untrusted even with DATAPASS_TRUSTED_PYTHON=1 inherited", async () => {
      assert.equal(process.env.DATAPASS_TRUSTED_PYTHON, "1", "runner must inject the hostile variable");
      const storage = vscode.Uri.file(await mkdtemp(path.join(tmpdir(), "datapass-e2e-storage-")));
      runtime = new RuntimeManager(extension.extensionUri, storage);
      await runtime.start(python, "duckdb", false);
      const state = runtime.snapshot();
      assert.equal(state.status, "running", state.detail);
      assert.equal(state.trustedPython, false);
      assert.ok(state.catalog?.some(asset => asset.name === "source.orders"));
    }],
    ["Mosaic SQL scratch executes on real DuckDB", async () => {
      await runtime!.runSql(scratchSpec("sql").content);
      const run = runtime!.snapshot().lastRun;
      assert.equal(run?.status, "success", run?.error?.message);
      assert.deepEqual(run?.result?.rows, [{ datapass_ready: 1 }]);
    }],
    ["Python is refused while untrusted", async () => {
      await assert.rejects(runtime!.runPython(scratchSpec("python").content), /Trusted local Python is disabled/);
    }],
    ["SparkLab scratch runs bounded; unsafe source is rejected", async () => {
      await runtime!.runSparkLab(scratchSpec("sparklab").content, "notebooks/sparklab.py", "generic_8x8", true);
      const ok = runtime!.snapshot().sparkRun;
      assert.equal(ok?.status, "success", ok?.error?.message);
      assert.deepEqual(ok?.result?.columns, ["customer_id", "revenue"]);
      assert.equal(ok?.simulation?.status, "modeled");
      assert.ok(ok?.simulation?.stages.length);
      assert.equal(ok?.simulation?.credits?.fictional, true);

      await runtime!.runSparkLab("import os\nos.system('echo unsafe')\n", "bad.py", "generic_8x8", true);
      const rejected = runtime!.snapshot().sparkRun;
      assert.equal(rejected?.status, "error");
      assert.equal(rejected?.error?.type, "SparkLabSyntaxError");
    }],
    ["Practice exercise: visible run and submission grade for real", async () => {
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const exercise = catalog.find(item => item.id === "demo-sum");
      assert.ok(exercise, "demo-sum exercise missing from catalog");
      for (const mode of ["run", "submit"] as const) {
        await runtime!.gradeExercise(exercise.key, {
          exercise_id: exercise.id,
          exercise_version: exercise.version,
          language: exercise.language,
          code: "SELECT COALESCE(SUM(value), 0) AS total FROM input",
          mode,
          notebook_id: "e2e-demo-sum",
          cell_id: "solution",
          source_revision: 1
        });
        const result = runtime!.snapshot().practiceResult;
        assert.equal(result?.mode, mode);
        assert.equal(result?.status, "passed", JSON.stringify(result?.checks));
      }
      await runtime!.gradeExercise(exercise.key, {
        exercise_id: exercise.id,
        exercise_version: exercise.version,
        language: exercise.language,
        code: "SELECT 0 AS total",
        mode: "submit",
        notebook_id: "e2e-demo-sum",
        cell_id: "solution",
        source_revision: 2
      });
      assert.equal(runtime!.snapshot().practiceResult?.status, "failed", "a wrong answer must fail");
    }],
    ["SQL lab multi-table and semantic-variant exercises grade from the catalog", async () => {
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const lab = catalog.filter(item => item.packId === "sql-lab-v1");
      assert.equal(lab.length, 60);
      assert.ok(lab.every(item => item.dataContext.length > 0 && item.hints.length > 0));

      const grading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "sql-lab-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const leftJoin = lab.find(item => item.id === "sql-lab-left-preserve-customers")!;
      assert.deepEqual(leftJoin.dataContext.map(table => table.name), ["customers", "order_detail"]);
      const submit = async (exercise: typeof leftJoin, code: string, mode: "run" | "submit" = "submit") => {
        await runtime!.gradeExercise(exercise.key, {
          exercise_id: exercise.id, exercise_version: exercise.version, language: exercise.language,
          code, mode, notebook_id: "e2e-lab", cell_id: "solution", source_revision: 1
        });
        return runtime!.snapshot().practiceResult!;
      };
      const passed = await submit(leftJoin, grading[leftJoin.id].solution);
      assert.equal(passed.status, "passed", JSON.stringify(passed.checks));
      assert.deepEqual(passed.checks.map(check => check.visibility), ["visible", "hidden", "edge"]);
      const inner = await submit(leftJoin, grading[leftJoin.id].solution.replace("LEFT JOIN", "INNER JOIN"));
      assert.equal(inner.status, "failed", "an INNER JOIN must not pass the LEFT JOIN lesson");
      const visibleOnly = await submit(leftJoin, grading[leftJoin.id].solution, "run");
      assert.deepEqual(visibleOnly.checks.map(check => check.visibility), ["visible"]);

      // Semantic packs expand to `<scenario>-<language>` ids in the runtime.
      const variant = catalog.find(item => item.packId === "unified-retail-v1" && item.language === "sql");
      assert.ok(variant);
      assert.ok(variant.id.endsWith("-sql"), `semantic variant id must be <scenario>-sql, got ${variant.id}`);
      const unified = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "unified-retail-v1", "grading.server.json")
      ))) as Record<string, { solutions: Record<string, string> }>;
      const scenario = variant.id.slice(0, -"-sql".length);
      const semantic = await submit(variant, unified[scenario].solutions.sql);
      assert.equal(semantic.status, "passed", JSON.stringify(semantic.checks));

      // Engine lab: named tables reach SparkLab; Python variants stay behind the trust gate.
      assert.equal(catalog.filter(item => item.packId === "engine-lab-v1").length, 68);
      assert.equal(catalog.filter(item => item.packId === "python-lab-v1").length, 12);
      const engine = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "engine-lab-v1", "grading.server.json")
      ))) as Record<string, { solutions: Record<string, string> }>;
      const antiJoin = catalog.find(item => item.id === "eng-anti-join-sparklab")!;
      assert.deepEqual(antiJoin.dataContext.map(table => table.name), ["orders", "customers"]);
      const spark = await submit(antiJoin, engine["eng-anti-join"].solutions.sparklab);
      assert.equal(spark.status, "passed", JSON.stringify(spark.checks));
      assert.equal(spark.truth, "semantic-emulation");
      const pythonLab = catalog.find(item => item.id === "py-frequency")!;
      const gated = await submit(pythonLab, "display([])");
      assert.equal(gated.status, "error", "Python exercises must not run while trusted Python is off");
      assert.match(gated.checks[0].message, /Trusted local Python is disabled/);

      // Data-engineering patterns: the NULL-safe anti-join passes, NOT IN fails on the guest order.
      assert.equal(catalog.filter(item => item.packId === "de-patterns-v1").length, 16);
      const patterns = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "de-patterns-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const antiJoin2 = catalog.find(item => item.id === "de-not-in-null-trap")!;
      const nullSafe = await submit(antiJoin2, patterns[antiJoin2.id].solution);
      assert.equal(nullSafe.status, "passed", JSON.stringify(nullSafe.checks));
      const notIn = await submit(antiJoin2, "SELECT customer_id, name FROM customers WHERE customer_id NOT IN (SELECT customer_id FROM orders)");
      assert.equal(notIn.status, "failed", "NOT IN must fail once orders.customer_id contains NULL");
      assert.deepEqual(notIn.checks.map(check => check.passed), [true, false, true], "only the guest-order fixture catches NOT IN");

      // Airflow lab: the DAG file is parsed, never executed; scenarios are simulated.
      const airflowLab = catalog.filter(item => item.packId === "airflow-lab-v1");
      assert.equal(airflowLab.length, 13);
      assert.ok(airflowLab.every(item => item.language === "airflow" && item.truth === "simulated"));
      const airflowGrading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "airflow-lab-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const branchJoin = airflowLab.find(item => item.id === "af-branch-join")!;
      const joined = await submit(branchJoin, airflowGrading[branchJoin.id].solution);
      assert.equal(joined.status, "passed", JSON.stringify(joined.checks));
      assert.equal(joined.truth, "simulated");
      const skippedJoin = await submit(branchJoin, branchJoin.starterSource);
      assert.equal(skippedJoin.status, "failed", "a default all_success join after a branch must fail");
      const rejected = await submit(branchJoin, "import os\n");
      assert.equal(rejected.status, "failed");
      assert.match(rejected.checks[0].message, /Unsupported import/);
    }],
    ["Pipeline starter compiles into a graph and runs its activities", async () => {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, "pipelines"));
      await write("pipelines/main.pipeline.py", pipelineStarter());
      const pipeline = await loadPipelineState(runtime!);
      assert.equal(pipeline.compileStatus, "valid", JSON.stringify(pipeline.diagnostics));
      assert.equal(pipeline.graph.nodes.length, 3);
      assert.ok(pipeline.graph.nodes.every(node => node.truth === "Real local execution"));
      await runtime!.runPipeline(pipelineStarter());
      const run = runtime!.snapshot().pipelineRun;
      assert.equal(run?.status, "success", JSON.stringify(run?.tasks));
      assert.deepEqual(run?.tasks.map(task => task.status), ["success", "success", "success"]);
    }],
    ["retail demo executes the medallion flow locally", async () => {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, "datasets"));
      await write("datasets/retail_orders.csv", retailOrdersCsv());
      await runtime!.runRetailDemo("datasets/retail_orders.csv");
      const demo = runtime!.snapshot().retailDemo;
      assert.equal(demo?.status, "success");
      assert.ok(demo && demo.stages.length >= 3);
      assert.ok(demo && demo.preview.rows.length > 0);

      // The generated retail SQL notebook then runs through Mosaic on bronze.orders.
      await runtime!.runSql(retailSqlStarter("datasets/retail_orders.csv"));
      const sql = runtime!.snapshot().lastRun;
      assert.equal(sql?.status, "success", sql?.error?.message);
      assert.deepEqual(sql?.result?.columns, ["customer_id", "orders", "revenue"]);
      assert.equal(sql?.result?.rows[0]?.customer_id, "C005", "highest revenue customer first");
      assert.ok(runtime!.snapshot().catalog?.some(asset => asset.name === "gold.mosaic_customer_revenue"));
    }],
    ["Mosaic CSV import creates a new text-typed bronze table and never overwrites", async () => {
      const text = decodeCsvBytes(new TextEncoder().encode("city,visits\nLyon,3\nNice,5\n"));
      const existing = (runtime!.snapshot().catalog ?? []).map(asset => asset.name);
      const asset = suggestBronzeAsset("City Visits.csv", existing);
      assert.equal(asset, "bronze.city_visits");
      await runtime!.importCsv(asset, text, "City Visits.csv");
      const imported = runtime!.snapshot().csvImport;
      assert.equal(imported?.asset, asset);
      assert.equal(imported?.rows_imported, 2);
      assert.deepEqual(imported?.schema.map(column => column.type), ["VARCHAR", "VARCHAR"]);
      assert.ok(runtime!.snapshot().catalog?.some(item => item.name === asset && item.row_count === 2));
      assert.match(validateBronzeAsset(asset, runtime!.snapshot().catalog!.map(item => item.name)) ?? "", /already exists/);
      await assert.rejects(runtime!.importCsv(asset, "city\nParis\n", "again.csv"), /CSV import refused: .*already exists/);

      await runtime!.runSql(`SELECT SUM(CAST(visits AS INTEGER)) AS visits FROM ${asset}`);
      const sum = runtime!.snapshot();
      assert.deepEqual(sum.lastRun?.result?.rows, [{ visits: 8 }], sum.lastRun?.error?.message);
      assert.equal(sum.csvImport, undefined, "a newer SQL run replaces the import preview");
    }],
    ["explicit trust restarts the runtime and runs Python for real", async () => {
      await runtime!.stopAndWait();
      await runtime!.start(python, "duckdb", true);
      const state = runtime!.snapshot();
      assert.equal(state.status, "running", state.detail);
      assert.equal(state.trustedPython, true);
      await runtime!.runPython(scratchSpec("python").content);
      const run = runtime!.snapshot().lastRun;
      assert.equal(run?.status, "success", run?.error?.message);
      assert.match(run?.stdout ?? "", /\(3, 1\)/);
      assert.deepEqual(run?.result?.columns, ["value"]);
    }]
  ];

  const failures: string[] = [];
  try {
    for (const [name, body] of [...hostSteps, ...runtimeSteps]) {
      try {
        await body();
        console.log(`  ok   ${name}`);
      } catch (error) {
        failures.push(name);
        console.error(`  FAIL ${name}\n${error instanceof Error ? error.stack : String(error)}`);
        break; // Steps build on each other; later failures would only be noise.
      }
    }
  } finally {
    if (runtime) {
      await runtime.stopAndWait();
      runtime.dispose();
    }
  }
  if (!python) {
    console.log("  SKIPPED runtime steps: set DATAPASS_E2E_PYTHON to a Python with ./runtime installed.");
  }
  if (failures.length) throw new Error(`Extension host E2E failed: ${failures.join(", ")}`);
}

class MemoryMemento implements vscode.Memento {
  private readonly values: Map<string, unknown>;

  constructor(initial: Record<string, unknown> = {}) {
    this.values = new Map(Object.entries(initial));
  }

  keys(): readonly string[] {
    return [...this.values.keys()];
  }

  get<T>(key: string, defaultValue?: T): T | undefined {
    return (this.values.has(key) ? this.values.get(key) : defaultValue) as T | undefined;
  }

  async update(key: string, value: unknown): Promise<void> {
    if (value === undefined) this.values.delete(key);
    else this.values.set(key, value);
  }
}

async function waitFor(label: string, condition: () => boolean, timeoutMs = 10000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (condition()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${label}.`);
}

async function copyDirectory(source: vscode.Uri, target: vscode.Uri): Promise<void> {
  await vscode.workspace.fs.createDirectory(target);
  for (const [name, type] of await vscode.workspace.fs.readDirectory(source)) {
    const from = vscode.Uri.joinPath(source, name);
    const to = vscode.Uri.joinPath(target, name);
    if (type & vscode.FileType.Directory) await copyDirectory(from, to);
    else await vscode.workspace.fs.copy(from, to, { overwrite: false });
  }
}
