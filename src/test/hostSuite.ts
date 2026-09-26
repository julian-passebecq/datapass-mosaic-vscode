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
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import { loadAirflowState } from "../airflowState";
import { CatalogTreeProvider, openTableScratch } from "../catalogTree";
import { biFileUri, collectBiDbtFiles, collectBiScripts, copyBiSamples, loadBiState, readBiModel } from "../biState";
import { DbtTerminalSession, writeDbtProfiles } from "../dbtLab";
import { findDbtProjects, loadDbtState } from "../dbtState";
import { MissionsService } from "../missions";
import { TerminalLabSession } from "../terminalLab";
import { InfraLabSession } from "../infraLab";
import { ticketPath } from "../platform/missions";
import { buildDctCommand } from "../platform/dbtTools";
import { loadExerciseCatalog } from "../exerciseCatalog";
import { prepareExerciseWorkspace } from "../exerciseWorkspace";
import { loadReferenceSolution, referenceUri } from "../referenceSolutions";
import { collectDatabricksFiles, collectFactoryFiles, copyFactorySamples, loadFactoryState, readPoolScript } from "../factoryState";
import { MODULES } from "../modules";
import { runDialect } from "../platform/sqlDialect";
import { decodeCsvBytes, suggestBronzeAsset, validateBronzeAsset } from "../platform/csvImport";
import { readMosaicLayout, writeMosaicLayout } from "../mosaicLayoutStore";
import { loadPipelineState } from "../pipelineState";
import { applyVerification, setManual } from "../platform/projects";
import { copyProjectFiles, loadProjectContents, loadProjectsState, readProgress, updateProgress, writeProgress } from "../projectState";
import { practiceStatus, recordGrade, recordOpened } from "../platform/practiceProgress";
import {
  createDefaultProjectManifest,
  readProjectManifest,
  withTrustedLocalPython,
  writeProjectManifest
} from "../project/projectManifest";
import { ACKNOWLEDGED_KEY, PythonTrustController } from "../pythonTrustController";
import { RuntimeManager } from "../runtimeManager";
import { managedVenvPython } from "../platform/runtimeEnvironment";
import { runtimeFingerprint, writeRuntimeMarker } from "../platform/runtimeFingerprint";
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
  const dbtPython = process.env.DATAPASS_DBT_PYTHON?.trim();
  let runtime: RuntimeManager | undefined;

  const write = (relative: string, content: string) =>
    vscode.workspace.fs.writeFile(vscode.Uri.joinPath(root, ...relative.split("/")), new TextEncoder().encode(content));

  const hostSteps: Step[] = [
    ["extension activates and registers every Workbench command", async () => {
      await extension.activate();
      const commands = await vscode.commands.getCommands(true);
      for (const module of MODULES) assert.ok(commands.includes(module.command), module.command);
      for (const command of ["datapass.catalog.refresh", "datapass.catalog.openScratch", "datapass.catalog.previewTable"]) {
        assert.ok(commands.includes(command), command);
      }
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
    ["Cloud Lab samples land in factory/ and every pipeline is read for the canvas", async () => {
      assert.equal((await loadFactoryState()).exists, false);
      await copyFactorySamples(extension.extensionUri);
      const factory = await loadFactoryState();
      assert.deepEqual(factory.warnings, []);
      assert.deepEqual(factory.pipelines.map(p => `${p.flavor}:${p.name}`),
        ["fabric:pl_retail_daily", "adf:pl_retail_daily_adf", "synapse:pl_sqlpool_daily"]);
      assert.ok(factory.pipelines.every(p => !p.error && p.activities.length >= 4));
      const { files, warnings } = await collectFactoryFiles("adf");
      assert.deepEqual(warnings, []);
      assert.deepEqual(Object.keys(files.pipelines), ["pl_retail_daily_adf"]);
      assert.deepEqual(Object.keys(files.datasets).sort(), ["ds_bronze_orders", "ds_source_orders"]);
      assert.deepEqual(Object.keys(files.procedures), ["warehouse.usp_load_gold_revenue"]);
      // Pipelines can call every notebook of the lab, including the Databricks job notebooks.
      assert.ok(["databricks:/Shared/nb_silver_orders_dbx", "fabric:nb_silver_orders"].every(key => key in files.notebooks));
      assert.deepEqual(factory.poolScripts.map(script => `${script.name}:${script.flavor}`),
        ["01_star_schema:synapse", "02_partitions:synapse", "03_procedures:synapse", "04_fabric_warehouse:fabric"]);
      assert.ok((await readPoolScript("factory/sql/pool/01_star_schema.sql")).text?.includes("DISTRIBUTION = REPLICATE"));
      for (const outside of ["factory/sql/procedures/warehouse.usp_load_gold_revenue.sql", "factory/../x.sql", "other/sql/pool/x.sql"]) {
        assert.match((await readPoolScript(outside)).error ?? "", /is not a script/, outside);
      }
      assert.equal(factory.databricks.exists, true);
      assert.deepEqual(factory.databricks.jobs.map(job => job.name).sort(), ["power_model_training", "retail_daily_dbx", "segment_reports"]);
      assert.ok(factory.databricks.jobs.every(job => !job.error && job.tasks.length >= 1));
      assert.deepEqual(factory.databricks.sqlFiles, ["/Shared/sql/gold_checks.sql"]);
    }],
    ["Airflow starter is a Python DAG file under airflow/dags", async () => {
      assert.equal((await loadAirflowState()).starterExists, false);
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, "airflow", "dags"));
      await write("airflow/dags/retail_daily.py", airflowStarter());
      const airflow = await loadAirflowState();
      assert.equal(airflow.dagsFolder, "airflow/dags");
      assert.equal(airflow.starterPath, "airflow/dags/retail_daily.py");
      assert.equal(airflow.starterExists, true);
      assert.equal(airflow.legacySpecPath, undefined);
    }],
    ["opening an exercise labels its tab and declares the runtime's names for Pylance", async () => {
      const labels = () => vscode.workspace.getConfiguration("workbench.editor", root)
        .inspect<Record<string, string>>("customLabels.patterns")?.workspaceValue ?? {};
      await vscode.workspace.getConfiguration("workbench.editor", root)
        .update("customLabels.patterns", { "**/*.test.ts": "test ${filename}" }, vscode.ConfigurationTarget.Workspace);
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const spark = catalog.find(item => item.language === "sparklab" && item.packId === "spark-lab-v1");
      assert.ok(spark, "a SparkLab exercise is in the catalog");
      const directory = vscode.Uri.joinPath(root, "exercises", "spark-e2e", "sparklab");
      const logged: string[] = [];
      await prepareExerciseWorkspace(extension.extensionUri, root, ["exercises"], directory, spark, m => logged.push(m));
      await prepareExerciseWorkspace(extension.extensionUri, root, ["exercises"], directory, spark, m => logged.push(m));
      assert.deepEqual(logged, [], logged.join("; "));
      assert.deepEqual(labels(), {
        "**/*.test.ts": "test ${filename}",
        "**/exercises/*/*/solution.*": "${dirname(1)} · ${dirname}",
        "**/exercises/*/*/README.md": "${dirname(1)} · brief"
      }, "the learner's pattern is kept and ours added once");
      const builtins = new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(directory, "__builtins__.pyi")));
      assert.match(builtins, /^spark: Any$/m);
      const excludes = vscode.workspace.getConfiguration("files", root).get<Record<string, boolean>>("exclude") ?? {};
      assert.equal(excludes["**/exercises/*/*/__builtins__.pyi"], true, "the generated stub is hidden from the Explorer");
      await vscode.workspace.fs.stat(vscode.Uri.joinPath(root, ".datapass", "pylance-stubs", "pyspark", "sql", "functions.py"));
    }],
    ["dbt Lab finds the workspace's dbt projects and claims no run before target/ exists", async () => {
      await copyDirectory(
        vscode.Uri.joinPath(extension.extensionUri, "samples", "dbt", "retail-dbt"),
        vscode.Uri.joinPath(root, "dbt", "retail-dbt")
      );
      const dbt = await loadDbtState({ tools: { status: "missing" } });
      const retail = dbt.projects.find(project => project.path === "dbt/retail-dbt");
      assert.deepEqual(retail, { path: "dbt/retail-dbt", name: "datapass_retail", profile: "datapass_retail" });
      assert.equal(dbt.selected, dbt.projects[0].path);
      assert.equal(dbt.run, undefined);
      const profilesDir = await writeDbtProfiles(root, (await findDbtProjects()).map(project => project.file));
      const profiles = new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(profilesDir, "profiles.yml")));
      assert.match(profiles, /^datapass_retail:$/m);
      assert.match(profiles, /path: '.*\/\.datapass\/data\/workspace\.duckdb'/);
      assert.doesNotMatch(profiles, /^\s*(password|token|secret|user)\s*:/im);
    }]
  ];

  const runtimeSteps: Step[] = !python ? [] : [
    ["Projects: content loads, starter files never overwrite, a tick by hand is only a declaration", async () => {
      const { projects, errors } = await loadProjectContents(extension.extensionUri);
      assert.deepEqual(errors, []);
      assert.deepEqual(projects.map(project => project.id), ["retail-fabric", "databricks-ml", "synapse-to-fabric"]);
      const written = await copyProjectFiles(extension.extensionUri, "retail-fabric");
      assert.ok(written.includes("projects/retail-fabric/web_orders_2026-03-05.csv"), written.join(", "));
      await write("projects/retail-fabric/silver_web_orders.sql", "-- mine\n");
      assert.deepEqual(await copyProjectFiles(extension.extensionUri, "retail-fabric"), [], "existing files are kept");
      const kept = new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(root, "projects", "retail-fabric", "silver_web_orders.sql")));
      assert.equal(kept, "-- mine\n");
      await vscode.workspace.fs.delete(vscode.Uri.joinPath(root, "projects", "retail-fabric", "silver_web_orders.sql"));
      await copyProjectFiles(extension.extensionUri, "retail-fabric");

      const retail = projects[0];
      const progress = await readProgress();
      assert.equal(progress.error, undefined);
      await writeProgress(setManual(progress.document, retail, "runbook", true, new Date().toISOString()));
      const state = await loadProjectsState(extension.extensionUri);
      const runbook = state.projects[0].steps.find(step => step.id === "runbook")!;
      assert.equal(runbook.state, "manual");
      assert.equal(runbook.verified, undefined);
      assert.equal(state.projects[0].progress.manual, 1);
      assert.equal(state.projects[0].nextStepId, "import-web-orders");
      await vscode.commands.executeCommand("datapass.openProjects");
    }],
    ["Practice progress shares progress.json with Projects; concurrent saves both land", async () => {
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const [first, second] = catalog.filter(item => item.packId === "sql-lab-v1");
      const retail = (await loadProjectContents(extension.extensionUri)).projects[0];
      const at = new Date().toISOString();
      await Promise.all([
        updateProgress(doc => ({ ...doc, practice: recordOpened(doc.practice, first.key, at) })),
        updateProgress(doc => ({ ...doc, practice: recordGrade(doc.practice, second.key, second.version, "submit", "passed", at) })),
        // Re-tick the step the previous test ticked (later steps rely on it); the new timestamp proves the write.
        updateProgress(doc => setManual(doc, retail, "runbook", true, at))
      ]);
      const saved = await readProgress();
      assert.equal(saved.error, undefined);
      assert.equal(practiceStatus(saved.document.practice?.exercises[first.key]), "attempted");
      assert.equal(practiceStatus(saved.document.practice?.exercises[second.key]), "solved");
      assert.deepEqual(saved.document.projects["retail-fabric"].steps.runbook.manual, { checked: true, at }, "the Projects write landed too");
      await vscode.commands.executeCommand("datapass.openPractice");
    }],
    ["a managed runtime installed by another extension build is reported stale, never ready", async () => {
      // No interpreter is run here: the decision reads the venv's marker only (scripts/vscode_ui_pass.mjs covers the
      // real update of a packaged VSIX's venv).
      const storage = vscode.Uri.file(await mkdtemp(path.join(tmpdir(), "datapass-e2e-venv-")));
      const environment = () => {
        const manager = new RuntimeManager(extension.extensionUri, storage);
        const view = manager.snapshot().environment;
        manager.dispose();
        return view;
      };
      assert.equal(environment()?.status, "missing");
      const venvRoot = path.join(storage.fsPath, "runtime-venv");
      const fakePython = managedVenvPython(venvRoot);
      await mkdir(path.dirname(fakePython), { recursive: true });
      await writeFile(fakePython, "");
      const unrecorded = environment();
      assert.equal(unrecorded?.status, "stale", "a venv set up before fingerprints existed");
      assert.match(unrecorded?.detail ?? "", /Update it before starting/);
      const marker = { schema: 1 as const, extensionVersion: "0.0.9", installedAt: new Date().toISOString() };
      writeRuntimeMarker(venvRoot, { ...marker, fingerprint: "sha256:" + "0".repeat(64) });
      const older = environment();
      assert.equal(older?.status, "stale");
      assert.match(older?.detail ?? "", /installed by Datapass 0\.0\.9 and does not match/);
      writeRuntimeMarker(venvRoot, { ...marker, fingerprint: runtimeFingerprint(path.join(extension.extensionPath, "runtime")) });
      assert.equal(environment()?.status, "ready", "the marker matches this extension's runtime/");
    }],
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
      await runtime!.labs.mosaic.runSql(scratchSpec("sql").content);
      const run = runtime!.snapshot().lastRun;
      assert.equal(run?.status, "success", run?.error?.message);
      assert.deepEqual(run?.result?.rows, [{ datapass_ready: 1 }]);
    }],
    ["Python is refused while untrusted", async () => {
      await assert.rejects(runtime!.labs.mosaic.runPython(scratchSpec("python").content), /Trusted local Python is disabled/);
    }],
    ["SparkLab scratch runs bounded; unsafe source is rejected", async () => {
      await runtime!.labs.sparklab.runSparkLab(scratchSpec("sparklab").content, "notebooks/sparklab.py", "generic_8x8", true);
      const ok = runtime!.snapshot().sparkRun;
      assert.equal(ok?.status, "success", ok?.error?.message);
      assert.deepEqual(ok?.result?.columns, ["customer_id", "revenue"]);
      assert.equal(ok?.simulation?.status, "modeled");
      assert.ok(ok?.simulation?.stages.length);
      assert.equal(ok?.simulation?.credits?.fictional, true);

      await runtime!.labs.sparklab.runSparkLab("import os\nos.system('echo unsafe')\n", "bad.py", "generic_8x8", true);
      const rejected = runtime!.snapshot().sparkRun;
      assert.equal(rejected?.status, "error");
      assert.equal(rejected?.error?.type, "SparkLabSyntaxError");
    }],
    ["Airflow Lab simulates the starter DAG without executing it", async () => {
      const clock = { now: "2026-03-05T12:00", tasks: {} };
      await runtime!.labs.airflow.simulateAirflow(airflowStarter(), "airflow/dags/retail_daily.py", clock);
      const lab = runtime!.snapshot().airflowRun!;
      assert.equal(lab.status, "simulated", lab.error?.message);
      assert.equal(lab.dag?.dagId, "retail_daily");
      assert.equal(lab.dag?.schedule.kind, "cron_trigger");
      assert.equal(lab.totalRuns, 1, "catchup=False: only the latest run");
      const states = (run: typeof lab.runs[number]) =>
        Object.fromEntries(run.instances.map(instance => [instance.taskId, instance.state]));
      assert.deepEqual(states(lab.runs[0]), {
        wait_for_orders: "success", choose_load: "success", full_load: "skipped",
        incremental_load: "success", publish: "success", cleanup: "success"
      });
      assert.ok(lab.runs[0].events.length > 0 && lab.runs[0].rendered.some(row => row.value.includes("2026-03-05")));

      await runtime!.labs.airflow.simulateAirflow(airflowStarter(), "airflow/dags/retail_daily.py", {
        ...clock, tasks: { incremental_load: { behavior: "fail_always" } }
      });
      const failed = runtime!.snapshot().airflowRun!;
      const failedStates = states(failed.runs[0]);
      assert.equal(failedStates.incremental_load, "failed");
      assert.equal(failed.runs[0].instances.find(item => item.taskId === "incremental_load")?.tryNumber, 2, "default_args retries=1");
      assert.equal(failedStates.publish, "upstream_failed");
      assert.equal(failedStates.cleanup, "success", "all_done cleanup still runs");

      await runtime!.labs.airflow.simulateAirflow("from airflow.sdk import DAG\nimport os\n", "broken.py", clock);
      const broken = runtime!.snapshot().airflowRun!;
      assert.equal(broken.status, "invalid");
      assert.equal(broken.error?.line, 2);
    }],
    ["Cloud Lab runs the Fabric and ADF sample pipelines on the local lakehouse", async () => {
      const scenario = { dataPlane: "local" as const, parameters: { run_date: "2026-03-06" }, activities: {}, triggerType: "Manual" as const };
      for (const [flavor, name] of [["fabric", "pl_retail_daily"], ["adf", "pl_retail_daily_adf"]] as const) {
        const { files, warnings } = await collectFactoryFiles(flavor);
        await runtime!.labs.fabric.simulateFactory({ flavor, name, path: name, document: files.pipelines[name], files, scenario, warnings });
        const lab = runtime!.snapshot().factoryRun!;
        assert.equal(lab.status, "simulated", JSON.stringify(lab.issues));
        assert.equal(lab.run?.status, "Succeeded", lab.run?.explanation);
        const silver = lab.run!.activityRuns.find(run => run.name === "Silver orders")!;
        assert.equal(silver.truth, "local", silver.note);
        assert.ok(lab.tablesChanged.some(table => table.name === "gold.revenue_by_segment" && table.rows === 4));
      }
      assert.ok(runtime!.snapshot().catalog?.some(item => item.name === "silver.orders"));

      const { files } = await collectFactoryFiles("fabric");
      await runtime!.labs.fabric.simulateFactory({
        flavor: "fabric", name: "pl_retail_daily", path: "p", document: files.pipelines.pl_retail_daily, files, warnings: [],
        scenario: { ...scenario, dataPlane: "simulated", activities: { "Silver orders": { behavior: "fail_always" } } }
      });
      const failed = runtime!.snapshot().factoryRun!;
      assert.equal(failed.dataPlane, "simulated");
      assert.equal(failed.run?.status, "Failed");
      assert.ok(failed.run?.activityRuns.some(run => run.name === "Email on notebook failure" && run.status === "Succeeded"));
      assert.deepEqual(failed.tablesChanged, []);

      await runtime!.labs.fabric.simulateFactory({
        flavor: "adf", name: "pl_retail_daily", path: "p", document: files.pipelines.pl_retail_daily, files, warnings: [], scenario
      });
      const wrongProduct = runtime!.snapshot().factoryRun!;
      assert.equal(wrongProduct.status, "invalid");
      assert.ok(wrongProduct.issues.some(issue => issue.message.includes("DatabricksNotebook")));
    }],
    ["Cloud Lab SQL pool runs the sample T-SQL scripts on the simulated pool", async () => {
      const script = async (name: string) => (await readPoolScript(`factory/sql/pool/${name}.sql`)).text!;
      const errors = (lab: { statements: { status: string; message: string }[] }) =>
        JSON.stringify(lab.statements.filter(statement => statement.status === "error"));
      await runtime!.labs.fabric.runSqlPool({ flavor: "synapse", script: await script("01_star_schema"), scale: 1_000_000, source: "01" });
      const star = runtime!.snapshot().sqlpoolRun!;
      assert.equal(star.status, "ok", errors(star));
      assert.equal(star.statements.length, 9);
      const report = star.statements.find(statement => statement.kind === "SELECT")!;
      assert.deepEqual(report.plan?.steps.map(step => step.operation), ["ShuffleMoveOperation", "ReturnOperation"]);
      assert.ok(report.plan?.notes.some(note => note.includes("dbo.dim_segment is replicated")), JSON.stringify(report.plan));
      const tables = new Map(star.tables.map(table => [table.name, table]));
      assert.equal(tables.get("dbo.dim_segment")?.distribution, "REPLICATE");
      assert.equal(tables.get("dbo.fact_orders")?.distributionStats?.skewPct, 0, "a unique key spreads evenly");
      assert.ok((tables.get("dbo.fact_orders_by_customer")?.distributionStats?.skewPct ?? 0) >= 10, "one account dominates");
      assert.equal(tables.get("dbo.fact_orders")?.distributionStats?.shares.length, 60);
      assert.ok(runtime!.snapshot().catalog?.some(item => item.name === "warehouse.fact_orders"));

      await runtime!.labs.fabric.runSqlPool({ flavor: "synapse", script: await script("02_partitions"), scale: 1_000_000, source: "02" });
      const partitioned = runtime!.snapshot().sqlpoolRun!;
      assert.equal(partitioned.status, "ok", errors(partitioned));
      const scans = partitioned.statements.filter(statement => statement.kind === "SELECT").map(s => s.plan?.scans[0]?.partitionsScanned);
      assert.deepEqual(scans.slice(0, 2), [12, 1], "a function around the partition column scans every partition");
      assert.equal(partitioned.tables.find(table => table.name === "dbo.fact_sales_2026")?.partitions.length, 12);

      await runtime!.labs.fabric.runSqlPool({ flavor: "synapse", script: await script("03_procedures"), scale: 1_000_000, source: "03" });
      const procedures = runtime!.snapshot().sqlpoolRun!;
      assert.equal(procedures.status, "ok", errors(procedures));
      assert.equal(procedures.statements.at(-1)?.message, "Top segment: Corporate");

      await runtime!.labs.fabric.runSqlPool({ flavor: "fabric", script: await script("04_fabric_warehouse"), scale: 1_000_000, source: "04" });
      const fabric = runtime!.snapshot().sqlpoolRun!;
      assert.equal(fabric.status, "ok", errors(fabric));
      assert.equal(fabric.flavorLabel, "Microsoft Fabric Data Warehouse");
      assert.match(fabric.tables.find(table => table.name === "dbo.fact_orders_fw")?.label ?? "", /managed layout/);

      await runtime!.labs.fabric.runSqlPool({ flavor: "fabric", script: await script("01_star_schema"), scale: 1_000_000, source: "01" });
      const refused = runtime!.snapshot().sqlpoolRun!;
      assert.equal(refused.status, "error");
      assert.match(refused.statements.at(-1)!.message, /takes no DISTRIBUTION/);
    }],
    ["Cloud Lab Databricks runs the sample jobs as their principals", async () => {
      const { files, jobs, warnings } = await collectDatabricksFiles();
      assert.deepEqual(warnings, []);
      assert.deepEqual(Object.keys(jobs).sort(), ["power_model_training", "retail_daily_dbx", "segment_reports"]);
      assert.ok(files.grants?.includes("sp-ml-training") && files.compute && files.unity_catalog);
      assert.ok(Object.keys(files.notebooks).includes("databricks:/Shared/ml/nb_train_power_model"));
      const scenario = { dataPlane: "local" as const, jobParameters: {}, tasks: {}, triggerType: "one_time" as const, clusterStates: {} };
      await runtime!.labs.fabric.simulateDatabricks({ name: "retail_daily_dbx", path: "p", document: jobs.retail_daily_dbx, files, scenario, warnings });
      const retail = runtime!.snapshot().databricksRun!;
      assert.equal(retail.run?.statusLabel, "Succeeded", JSON.stringify(retail.issues.concat(retail.run?.tasks.map(t => ({ path: t.key, message: t.error })) ?? [])));
      assert.equal(retail.run?.tasks.find(t => t.key === "alert_on_failure")?.state, "excluded");
      assert.ok(retail.tablesChanged.some(table => table.name === "gold.revenue_by_segment"));
      await runtime!.labs.fabric.simulateDatabricks({ name: "power_model_training", path: "p", document: jobs.power_model_training, files, scenario, warnings });
      const power = runtime!.snapshot().databricksRun!;
      assert.equal(power.run?.statusLabel, "Succeeded", JSON.stringify(power.run?.tasks.map(t => [t.key, t.error])));
      assert.equal(power.run?.principal, "sp-ml-training");
      const state = runtime!.snapshot().databricksState!;
      assert.equal(state.mlflow.models[0]?.name, "main.ml.power_model");
      assert.equal(state.unity.owners["main.ml.power_model"], "sp-ml-training");
      await runtime!.labs.fabric.simulateDatabricks({ name: "retail_daily_dbx", path: "p", document: jobs.retail_daily_dbx, files, warnings,
        scenario: { ...scenario, dataPlane: "simulated", tasks: { ingest_orders: { behavior: "fail_always" } } } });
      const failed = runtime!.snapshot().databricksRun!;
      assert.equal(failed.run?.statusLabel, "Failed");
      assert.equal(failed.run?.tasks.find(t => t.key === "alert_on_failure")?.state, "success");
      await runtime!.labs.fabric.exploreDatabricks(files);
      assert.equal(runtime!.snapshot().databricksState?.unity.catalog, "main");
    }],
    ["BI Lab builds the sample warehouse, traces its lineage and checks its star model", async () => {
      await copyBiSamples(extension.extensionUri);
      const state = await loadBiState();
      assert.deepEqual(state.scripts.map(script => script.name), [
        "00_sources.sql", "01_dim_date.sql", "02_dim_customer.sql", "03_dim_product.sql", "04_dim_order_profile.sql",
        "05_fct_sales.sql", "06_fct_returns.sql"]);
      assert.ok(state.modelExists && !state.modelError);
      assert.equal(biFileUri("bi/../factory/x.sql"), undefined);
      const { scripts, warnings } = await collectBiScripts();
      assert.deepEqual(warnings, []);
      const model = await readBiModel();
      await runtime!.labs.bi.runBiLab({ mode: "build", source: "bi/warehouse", scripts, model: model.model, warnings });
      const built = runtime!.snapshot().biRun!;
      assert.equal(built.status, "ok", JSON.stringify(built.stopped));
      assert.equal(built.statements.length, 14);
      assert.equal(built.tables.find(table => table.name === "gold.fct_sales")?.rows, 16);
      assert.ok(built.model && built.model.checks.every(check => check.status === "pass"),
        JSON.stringify(built.model?.checks.filter(check => check.status !== "pass")));
      assert.equal(built.model?.relationships.find(r => r.from === "gold.fct_sales.ship_date_key")?.active, false);
      const net = built.lineage.columns.find(c => c.table === "gold.fct_sales" && c.column === "net_amount");
      assert.deepEqual(net?.sources, ["source.shop_order_lines.discount_amount", "source.shop_order_lines.quantity",
        "source.shop_order_lines.unit_price"]);
      assert.ok(built.lineage.impact["source.erp_products.unit_cost"]?.some(i => i.table === "gold.fct_sales" && i.column === "cost_amount"));
      assert.ok(runtime!.snapshot().catalog?.some(item => item.name === "gold.dim_customer" && item.row_count === 9));

      // A broken model is reported, not run: the scripts are only analyzed this time.
      const broken = JSON.parse(JSON.stringify(model.model)) as { relationships: { active: boolean }[] };
      broken.relationships[1].active = true;
      await runtime!.labs.bi.runBiLab({ mode: "analyze", source: "analysis only", scripts, model: broken, warnings: [] });
      const analyzed = runtime!.snapshot().biRun!;
      assert.equal(analyzed.ran, false);
      assert.deepEqual(analyzed.statements, []);
      assert.ok(analyzed.model?.checks.some(c => c.check === "single_active_path" && c.status === "fail"));
    }],
    ["BI Lab dbt tab runs the sample project with the Datapass dbt emulation", async () => {
      const { files, warnings } = await collectBiDbtFiles();
      assert.deepEqual(warnings, []);
      assert.ok("dbt_project.yml" in files && "models/marts/fct_sales.sql" in files && !("README.md" in files));
      assert.equal((await loadBiState()).dbtExists, true);
      await runtime!.labs.bi.runBiDbt({ command: "build", select: [], selectText: "", fullRefresh: false, files, warnings });
      const built = runtime!.snapshot().biDbtRun!;
      assert.equal(built.status, "success", JSON.stringify(built.results.filter(r => r.status === "error")));
      assert.equal(built.counts?.success, 12);
      assert.equal(built.counts?.pass, 19);
      assert.match(built.truth, /not dbt Core/);
      assert.ok(runtime!.snapshot().catalog?.some(item => item.name === "warehouse.fct_sales" && item.row_count === 16));
      const lineage = built.lineage?.columns.find(c => c.table === "warehouse.fct_sales" && c.column === "cost_amount");
      assert.deepEqual(lineage?.origins, ["source.erp_products.unit_cost", "source.shop_order_lines.quantity"]);
      await runtime!.labs.bi.runBiDbt({ command: "build", select: ["+fct_returns"], selectText: "+fct_returns", fullRefresh: false, files, warnings });
      assert.ok(runtime!.snapshot().biDbtRun!.results.every(r => r.name !== "dim_date" || r.status === "success"));
      const broken = { ...files, "models/marts/fct_sales.sql": files["models/marts/fct_sales.sql"].replace("-- depends_on: {{ ref('dim_date') }}", "") };
      await runtime!.labs.bi.runBiDbt({ command: "run", select: ["fct_sales"], selectText: "fct_sales", fullRefresh: false, files: broken, warnings });
      const refused = runtime!.snapshot().biDbtRun!.results[0];
      assert.equal(refused.status, "error");
      assert.match(refused.message, /depends_on/);
    }],
    ["the runtime lends the catalog file to another writer and takes it back", async () => {
      assert.equal(await runtime!.releaseCatalog("dbt run --select e2e"), true);
      assert.equal(runtime!.snapshot().catalogLease?.holder, "dbt run --select e2e");
      await assert.rejects(runtime!.labs.mosaic.runSql("SELECT 1"), /409|lent to/);
      const database = path.join(root.fsPath, ".datapass", "data", "workspace.duckdb");
      const writer = spawn(python!, ["-c", [
        "import duckdb, sys",
        "c = duckdb.connect(sys.argv[1])",
        "c.execute('CREATE OR REPLACE TABLE silver.e2e_handoff AS SELECT 7 AS n')",
        "print('ready', flush=True)",
        "sys.stdin.readline()",
        "c.close()"
      ].join("\n"), database], { stdio: ["pipe", "pipe", "inherit"] });
      try {
        await new Promise<void>((resolve, reject) => {
          writer.stdout!.once("data", () => resolve());
          writer.once("exit", code => reject(new Error(`writer exited ${code}`)));
        });
        assert.equal(await runtime!.reattachCatalog(), false, "the file is still held");
        assert.match(runtime!.snapshot().catalogLease?.reattachError ?? "", /still held/);
      } finally {
        writer.stdin!.end("done\n");
        await new Promise(resolve => writer.once("exit", resolve));
      }
      assert.equal(await runtime!.reattachCatalog(), true);
      assert.equal(runtime!.snapshot().catalogLease, undefined);
      assert.ok(runtime!.snapshot().catalog?.some(asset => asset.name === "silver.e2e_handoff"));
    }],
    ...(!dbtPython ? [] : [["dbt Core builds the BI project in a real terminal, with the catalog handed off and back", async () => {
      const binDir = path.dirname(dbtPython);
      const session = new DbtTerminalSession(runtime!, { binDir, venvRoot: path.dirname(binDir) });
      try {
        const projects = await findDbtProjects();
        const profilesDir = await writeDbtProfiles(root, projects.map(project => project.file));
        const leases: string[] = [];
        const watch = runtime!.onDidChange(state => { if (state.catalogLease) leases.push(state.catalogLease.holder); });
        const ended = new Promise<{ commandLine: string; exitCode: number | undefined }>((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error("dbt build did not report its end within 240 s")), 240_000);
          session.onDidEndCommand(event => { clearTimeout(timer); resolve(event); });
        });
        await session.run(vscode.Uri.joinPath(root, "bi", "dbt"), profilesDir, "dbt build");
        const end = await ended;
        watch.dispose();
        assert.equal(end.commandLine.trim(), "dbt build");
        assert.ok(leases.includes("dbt build"), "the catalog was lent while dbt ran");
        assert.equal(runtime!.snapshot().catalogLease, undefined, "and reattached afterwards");
        const dbt = await loadDbtState({ tools: { status: "ready" }, selected: "bi/dbt" });
        assert.equal(dbt.run?.command, "dbt build", dbt.artifactError);
        assert.ok(dbt.run!.truth.startsWith("dbt Core (real)"));
        assert.ok((dbt.run!.counts.success ?? 0) > 5 && (dbt.run!.counts.pass ?? 0) > 5, JSON.stringify(dbt.run!.counts));
        assert.deepEqual(dbt.run!.problems, []);
        assert.equal(end.exitCode ?? 0, 0);
        await runtime!.refreshCatalog();
        assert.ok(runtime!.snapshot().catalog?.some(asset => asset.name === "warehouse.fct_sales"));
      } finally {
        session.dispose();
      }
    }] as Step]),
    ...(!dbtPython || !existsSync(path.join(path.dirname(dbtPython), process.platform === "win32" ? "dct.exe" : "dct")) ? [] : [[
      "dbt Charts renders the retail board for real from the dbt-built mart", async () => {
        const binDir = path.dirname(dbtPython);
        const session = new DbtTerminalSession(runtime!, { binDir, venvRoot: path.dirname(binDir) });
        const runAndWait = async (folder: vscode.Uri, profilesDir: vscode.Uri, commandLine: string) => {
          const ended = new Promise<{ commandLine: string; exitCode: number | undefined }>((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error(`${commandLine} did not report its end within 240 s`)), 240_000);
            const listener = session.onDidEndCommand(event => {
              if (event.commandLine.trim() !== commandLine) return;
              clearTimeout(timer);
              listener.dispose();
              resolve(event);
            });
          });
          await session.run(folder, profilesDir, commandLine);
          return ended;
        };
        try {
          const retail = vscode.Uri.joinPath(root, "dbt", "retail-dbt");
          const profilesDir = await writeDbtProfiles(root, (await findDbtProjects()).map(project => project.file));
          const built = await runAndWait(retail, profilesDir, "dbt build");
          if ((built.exitCode ?? 0) !== 0) {
            const log = new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(retail, "logs", "dbt.log")));
            const errors = log.split(/\r?\n/).filter(line => /error|Error/.test(line)).slice(-12).join("\n");
            assert.fail(`dbt build exited ${built.exitCode}:\n${errors}`);
          }
          await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(retail, "renders"));
          const render = buildDctCommand({ action: "render", board: "charts/revenue.yml", format: "json" });
          assert.equal((await runAndWait(retail, profilesDir, render)).exitCode ?? 0, 0);
          assert.equal((await runAndWait(retail, profilesDir, buildDctCommand({ action: "render", board: "charts/revenue.yml", format: "png" }))).exitCode ?? 0, 0);
          assert.equal(runtime!.snapshot().catalogLease, undefined, "dct gave the catalog back");
          const dbt = await loadDbtState({ tools: { status: "ready" }, selected: "dbt/retail-dbt" });
          const board = dbt.charts?.boards.find(item => item.path === "charts/revenue.yml");
          assert.ok(dbt.charts?.configured && board, JSON.stringify(dbt.charts));
          assert.deepEqual(board!.render?.charts.map(chart => chart.id), ["monthly", "by_customer"], board!.renderError);
          assert.equal(board!.render!.charts[0].totalRows, 4);
          assert.ok(board!.png?.startsWith("data:image/png;base64,"), "the PNG render is shown as a data: image");
        } finally {
          session.dispose();
        }
      }] as Step]),
    ["a mission starts in its own folder, and the hidden checker judges the real result", async () => {
      const binDir = dbtPython ? path.dirname(dbtPython) : path.join(root.fsPath, "no-dbt");
      const tools = { binDir, venvRoot: path.dirname(binDir), snapshot: () => ({ status: "missing" as const }) };
      const missions = new MissionsService(extension.extensionUri, runtime!, tools);
      const list = await missions.list("dbt");
      assert.deepEqual(list.map(m => m.id), ["prod-unique-failure", "source-freshness", "incremental-order-lines", "backfill-daily-sales", "product-price-history", "order-lines-contract", "sales-board"]);
      const folder = await missions.start("prod-unique-failure");
      const read = async (relative: string) => new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(folder, ...relative.split("/"))));
      assert.match(await read("TICKET.md"), /^# \[FAILED\] nightly dbt build/m);
      assert.match(await read("dbt_project.yml"), /raw_schema: uniq_raw/);
      await assert.rejects(Promise.resolve(vscode.workspace.fs.stat(vscode.Uri.joinPath(folder, "solution"))), "the reference is not copied");
      await assert.rejects(Promise.resolve(vscode.workspace.fs.stat(vscode.Uri.joinPath(folder, "fixtures"))), "fixtures are not copied");
      await missions.revealHint("prod-unique-failure");
      await missions.check("prod-unique-failure");
      let progress = (await missions.progress()).missions["prod-unique-failure"];
      assert.equal(progress.hintsShown, 1);
      assert.deepEqual(progress.batches, ["landing"]);
      assert.equal(progress.lastCheck?.status, "not-yet");
      assert.match(progress.lastCheck!.criteria.find(c => c.id === "green")!.details[0], /No target\/run_results\.json yet/);
      if (!dbtPython) return;
      // With real dbt Core: reproduce the failure, fix it as the ticket asks, and pass.
      const session = new DbtTerminalSession(runtime!, tools);
      const build = async () => {
        const ended = new Promise<{ exitCode: number | undefined }>((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error("dbt build did not report its end within 240 s")), 240_000);
          const listener = session.onDidEndCommand(event => {
            if (event.commandLine.trim() !== "dbt build") return;
            clearTimeout(timer);
            listener.dispose();
            resolve(event);
          });
        });
        await session.run(folder, vscode.Uri.joinPath(root, ".datapass", "dbt"), "dbt build");
        return ended;
      };
      try {
        assert.notEqual((await build()).exitCode ?? 1, 0, "the unique test fails as in prod");
        await missions.check("prod-unique-failure");
        progress = (await missions.progress()).missions["prod-unique-failure"];
        assert.equal(progress.lastCheck?.criteria.find(c => c.id === "green")?.passed, false);
        await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(folder, "models", "staging", "stg_shop__orders.sql"), new TextEncoder().encode(
          "select order_id, customer_id, order_date, channel, payment_type, loaded_at\n" +
          "from {{ source('shop', 'shop_orders') }}\n" +
          "qualify row_number() over (partition by order_id order by loaded_at desc) = 1\n"));
        assert.equal((await build()).exitCode ?? 0, 0);
        await missions.check("prod-unique-failure");
        progress = (await missions.progress()).missions["prod-unique-failure"];
        assert.equal(progress.lastCheck?.status, "passed", JSON.stringify(progress.lastCheck?.criteria));
        assert.ok(progress.passedAt);
      } finally {
        session.dispose();
      }
    }],
    ["Terminal Lab: the mission folder is built, a real terminal opens in it, and the checker judges what the commands left", async () => {
      const tools = { binDir: path.join(root.fsPath, "no-dbt"), venvRoot: root.fsPath, snapshot: () => ({ status: "missing" as const }) };
      const missions = new MissionsService(extension.extensionUri, runtime!, tools);
      const list = await missions.list("terminal");
      assert.equal(list.length, 8);
      assert.ok(list.every(mission => mission.lab === "terminal" && mission.batches.length === 0));
      const memory = new Map<string, unknown>();
      const lab = new TerminalLabSession({ keys: () => [...memory.keys()], get: (key: string) => memory.get(key), update: async (key: string, value: unknown) => { memory.set(key, value); } } as vscode.Memento);
      const { shells, git } = await lab.detect();
      assert.ok(git.version, "git is found");
      const bash = shells.find(shell => shell.id === "bash");
      assert.ok(bash?.path, `bash is found: ${bash?.note}`);
      const content = vscode.Uri.joinPath(extension.extensionUri, "content", "missions", "terminal-v1");
      // Plays the learner: types a line in the real terminal, then asks the checker until it passes.
      const playInTerminal = async (id: string, shell: "bash" | "powershell", commandLine: string) => {
        const folder = await missions.start(id);
        const mission = await missions.mission(id);
        const ticket = new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(root, ...ticketPath(mission).split("/"))));
        assert.match(ticket, /Datapass runs none\s+of your commands/);
        await assert.rejects(Promise.resolve(vscode.workspace.fs.stat(vscode.Uri.joinPath(folder, "TICKET.md"))), "the ticket stays out of the mission folder");
        await missions.check(id);
        assert.equal((await missions.progress()).missions[id].lastCheck?.status, "not-yet");
        const terminal = await lab.open(folder, shell, id);
        assert.ok(terminal.name.startsWith(id));
        // As a learner would: type once the prompt is there (pwsh drops input typed while PSReadLine loads).
        const integration = terminal.shellIntegration ?? await new Promise<vscode.TerminalShellIntegration | undefined>(resolve => {
          const timer = setTimeout(() => { listener.dispose(); resolve(undefined); }, 20_000);
          const listener = vscode.window.onDidChangeTerminalShellIntegration(event => {
            if (event.terminal !== terminal) return;
            clearTimeout(timer);
            listener.dispose();
            resolve(event.shellIntegration);
          });
        });
        let output = "";
        if (integration) {
          // The prompt may still be drawing when integration is first reported: give it a moment, then make sure the
          // command really started (a line typed too early is lost), else type it again as text.
          await new Promise(resolve => setTimeout(resolve, 3000));
          const started = new Promise<boolean>(resolve => {
            const timer = setTimeout(() => { listener.dispose(); resolve(false); }, 15_000);
            const listener = vscode.window.onDidStartTerminalShellExecution(event => {
              if (event.terminal !== terminal) return;
              clearTimeout(timer);
              listener.dispose();
              resolve(true);
            });
          });
          const execution = integration.executeCommand(commandLine);
          void (async () => {
            for await (const data of execution.read()) output += data;
          })();
          if (!(await started)) {
            output += "(the command did not start through shell integration: sent as text)";
            terminal.sendText(commandLine, true);
          }
        } else {
          await new Promise(resolve => setTimeout(resolve, 5000));
          terminal.sendText(commandLine, true);
          output = "(no shell integration: the line was sent as text)";
        }
        let status: string | undefined;
        for (let attempt = 0; attempt < 45 && status !== "passed"; attempt++) {
          await new Promise(resolve => setTimeout(resolve, 2000));
          await missions.check(id);
          status = (await missions.progress()).missions[id].lastCheck?.status;
        }
        const last = (await missions.progress()).missions[id].lastCheck;
        const shown = output.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").slice(-1500);
        assert.equal(status, "passed", `${JSON.stringify(last?.criteria)}\nTerminal (${shell}, shell integration: ${Boolean(integration)}): ${shown}`);
        return folder;
      };
      try {
        const identity = "export GIT_AUTHOR_NAME='Alex Learner' GIT_AUTHOR_EMAIL=alex@example.com GIT_COMMITTER_NAME='Alex Learner' GIT_COMMITTER_EMAIL=alex@example.com";
        const solve = vscode.Uri.joinPath(content, "merge-conflict", "solution", "solve.sh").fsPath.replaceAll("\\", "/");
        const folder = await playInTerminal("merge-conflict", "bash", `${identity}; bash '${solve}'`);
        // Start over, as the panel does it: the terminal and Source Control let go of the folder, which goes to the
        // attic (never deleted); the fixture is rebuilt.
        const restore = await lab.release(folder);
        try {
          await missions.start("merge-conflict");
        } finally {
          await restore();
        }
        await missions.check("merge-conflict");
        assert.equal((await missions.progress()).missions["merge-conflict"].lastCheck?.status, "not-yet");
        const attic = await vscode.workspace.fs.readDirectory(vscode.Uri.joinPath(root, ".datapass", "missions", "attic"));
        assert.ok(attic.some(([name]) => name.startsWith("merge-conflict-")), JSON.stringify(attic));
        assert.ok(folder);
        const powershell = shells.find(shell => shell.id === "powershell");
        if (powershell?.path) {
          const script = vscode.Uri.joinPath(content, "server-inventory-report", "solution", "solve.ps1").fsPath;
          lab.closeIn(await playInTerminal("server-inventory-report", "powershell", `& '${script.replaceAll("'", "''")}'`));
        }
      } finally {
        lab.dispose();
      }
    }],
    ["Infra Lab: the mission folder and its simulated world are built, lines typed in the simulated terminal reach the simulators, and the checker judges the simulated world", async () => {
      const tools = { binDir: path.join(root.fsPath, "no-dbt"), venvRoot: root.fsPath, snapshot: () => ({ status: "missing" as const }) };
      const missions = new MissionsService(extension.extensionUri, runtime!, tools);
      const list = await missions.list("infra");
      assert.deepEqual(list.map(mission => mission.id), ["lake-landing-zone", "containerize-ingest-api", "page-on-shir-outage", "zero-downtime-rollout"]);
      const memory = new Map<string, unknown>();
      const lab = new InfraLabSession(runtime!, { keys: () => [...memory.keys()], get: (key: string) => memory.get(key), update: async (key: string, value: unknown) => { memory.set(key, value); } } as vscode.Memento);
      try {
        const id = "page-on-shir-outage";
        const folder = await missions.start(id);
        const mission = await missions.mission(id);
        const ticket = new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(root, ...ticketPath(mission).split("/"))));
        assert.match(ticket, /nothing is provisioned, built or\s+deployed/);
        await vscode.workspace.fs.stat(vscode.Uri.joinPath(folder, ".infralab", "world.json"));
        await missions.check(id);
        assert.equal((await missions.progress()).missions[id].lastCheck?.status, "not-yet");
        const relative = `missions/${id}`;
        const terminal = await lab.open(relative, id);
        assert.match(terminal.name, /Infra Lab \(simulated\)/);
        assert.equal(lab.folder, relative);
        const journal = async () => ((await runtime!.labs.infra.infraState(relative)) as { journal: unknown[] }).journal.length;
        const lines = (await vscode.workspace.fs.readFile(vscode.Uri.joinPath(extension.extensionUri, "content", "missions", "infra-v1", id, "mission.json")))
          .toString();
        const reference = (JSON.parse(lines) as { reference: { infra: string }[] }).reference.map(step => step.infra);
        let ran = 0;
        for (const line of reference) {
          // Typed in the Pseudoterminal as the learner would: no process runs, the line goes to the runtime.
          terminal.sendText(line, true);
          for (let attempt = 0; attempt < 40 && (await journal()) <= ran; attempt++) await new Promise(resolve => setTimeout(resolve, 250));
          ran = await journal();
        }
        assert.equal(ran, reference.length, "every line reached the simulated shell");
        await missions.check(id);
        const last = (await missions.progress()).missions[id].lastCheck;
        assert.equal(last?.status, "passed", JSON.stringify(last?.criteria));
        assert.ok(lab.closeIn(relative));
      } finally {
        lab.dispose();
      }
    }],
    ["Catalog tree lists layers, tables, columns and row counts, and opens a SQL scratch", async () => {
      const tree = new CatalogTreeProvider(runtime!);
      try {
        await tree.refresh();
        const roots = tree.getChildren();
        const labels = roots.map(node => String(tree.getTreeItem(node).label));
        assert.deepEqual(labels.slice(0, 7), ["source", "bronze", "silver", "gold", "warehouse", "features", "metrics"]);
        const warehouse = roots[labels.indexOf("warehouse")];
        const tables = tree.getChildren(warehouse);
        const fact = tables.find(node => tree.getTreeItem(node).label === "fct_sales");
        assert.ok(fact, "warehouse.fct_sales is listed");
        assert.match(String(tree.getTreeItem(fact!).description), /^\d+ rows?$/);
        const columns = tree.getChildren(fact).map(node => [tree.getTreeItem(node).label, tree.getTreeItem(node).description]);
        assert.ok(columns.length > 0 && columns.every(([, type]) => typeof type === "string" && type.length > 0), JSON.stringify(columns));
        const table = tree.snapshot()!.tables.find(item => item.schema === "warehouse" && item.name === "fct_sales")!;
        const uri = await openTableScratch(table);
        assert.ok(uri && uri.path.endsWith("/.datapass/scratch/warehouse.fct_sales.sql"));
        const text = new TextDecoder().decode(await vscode.workspace.fs.readFile(uri!));
        assert.ok(text.endsWith("SELECT * FROM warehouse.fct_sales LIMIT 100;\n"), text);
        await runtime!.labs.mosaic.runSql(text);
        assert.equal(runtime!.snapshot().lastRun?.status, "success", runtime!.snapshot().lastRun?.error?.message);
      } finally {
        tree.dispose();
      }
    }],
    ["Practice exercise: visible run and submission grade for real", async () => {
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const exercise = catalog.find(item => item.id === "demo-sum");
      assert.ok(exercise, "demo-sum exercise missing from catalog");
      for (const mode of ["run", "submit"] as const) {
        await runtime!.labs.practice.gradeExercise(exercise.key, {
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
      await runtime!.labs.practice.gradeExercise(exercise.key, {
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
      const failed = runtime!.snapshot().practiceResult!.checks.find(check => check.visibility === "visible");
      assert.ok(Array.isArray(failed?.expected) && Array.isArray(failed?.actual), "visible checks carry their rows for the diff");
      assert.ok(runtime!.snapshot().practiceResult!.checks.filter(check => check.visibility !== "visible")
        .every(check => check.expected === undefined && check.actual === undefined), "hidden and edge rows never leave the runtime");

      // The reference solution opens as a read-only document for VS Code's diff editor.
      const code = await loadReferenceSolution(extension.extensionUri, exercise);
      assert.equal(code, "SELECT COALESCE(SUM(value), 0) AS total FROM input");
      const document = await vscode.workspace.openTextDocument(referenceUri(exercise, "sql"));
      assert.equal(document.getText(), `${code}
`, "the extension's provider serves the pack's solution");
      assert.equal(document.uri.scheme, "datapass-reference");
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
        await runtime!.labs.practice.gradeExercise(exercise.key, {
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
      assert.equal(catalog.filter(item => item.packId === "engine-lab-v1").length, 103, "68 variants + 17 T-SQL + 18 BigQuery");
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

      // Spark lab: plan checks grade the simulated SparkLab plan next to the result rows.
      const sparkLab = catalog.filter(item => item.packId === "spark-lab-v1");
      assert.equal(sparkLab.length, 19);
      // Polars variants share their Spark exercise's card (key <pack>/<spark id>/polars).
      const sparkPolars = sparkLab.filter(item => item.language === "polars");
      assert.equal(sparkPolars.length, 7);
      assert.ok(sparkPolars.every(item => item.truth === "real" &&
        sparkLab.some(spark => spark.key === item.key.replace(/\/polars$/, "/sparklab"))));
      const sparkGrading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "spark-lab-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const broadcast = sparkLab.find(item => item.id === "spark-broadcast-dimension")!;
      assert.deepEqual(broadcast.sparkPlan?.checks.map(check => check.id), ["plan-broadcast-join", "plan-single-shuffle"]);
      assert.deepEqual(broadcast.sparkPlan?.scale.map(table => table.table), ["sales", "stores"]);
      const planned = await submit(broadcast, sparkGrading[broadcast.id].solution);
      assert.equal(planned.status, "passed", JSON.stringify(planned.checks));
      assert.deepEqual(planned.checks.map(check => check.kind), ["result", "result", "result", "plan", "plan"]);
      const shuffled = await submit(broadcast, broadcast.starterSource);
      assert.equal(shuffled.status, "failed", "a sort-merge join must fail the broadcast lesson");
      assert.ok(shuffled.checks.filter(check => check.kind === "result").every(check => check.passed),
        "the starter's rows are right; only its plan is wrong");
      assert.match(shuffled.checks.find(check => check.id === "plan-single-shuffle")!.message, /3 shuffle exchanges/);
      const visiblePlan = await submit(broadcast, sparkGrading[broadcast.id].solution, "run");
      assert.deepEqual(visiblePlan.checks.map(check => check.kind), ["result", "plan", "plan"],
        "Run visible also grades the public plan checks");

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

      // Cloud Lab pipelines: pipeline JSON and pipeline notebooks, graded on simulated runs; local data
      // activities use an isolated catalog, so the workspace catalog must not change.
      const cloud = catalog.filter(item => item.packId === "cloud-pipelines-v1");
      assert.equal(cloud.length, 16);
      assert.ok(cloud.every(item => ["factory", "factory-notebook"].includes(item.language) && item.truth === "simulated"));
      const cloudGrading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "cloud-pipelines-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      await runtime!.refreshCatalog();
      const catalogBefore = JSON.stringify(runtime!.snapshot().catalog?.map(item => [item.name, item.row_count]));
      const watermark = cloud.find(item => item.id === "cp-incremental-watermark")!;
      const loaded = await submit(watermark, cloudGrading[watermark.id].solution);
      assert.equal(loaded.status, "passed", JSON.stringify(loaded.checks));
      assert.equal(loaded.truth, "simulated");
      const duplicated = await submit(watermark, watermark.starterSource);
      assert.equal(duplicated.status, "failed", "a full reload must duplicate rows on the second run");
      const broken = await submit(watermark, "{ \"properties\": { \"activities\": [ ] ");
      assert.equal(broken.status, "failed");
      assert.match(broken.checks[0].message, /Pipeline rejected: Invalid JSON/);
      const parametersCell = cloud.find(item => item.id === "nb-fabric-parameters-cell")!;
      assert.equal(parametersCell.language, "factory-notebook");
      const injected = await submit(parametersCell, cloudGrading[parametersCell.id].solution);
      assert.equal(injected.status, "passed", JSON.stringify(injected.checks));
      assert.equal((await submit(parametersCell, parametersCell.starterSource)).status, "failed");

      // SQL pool: T-SQL graded on the simulated pool; each check also uses an isolated catalog.
      const sqlpool = catalog.filter(item => item.packId === "sqlpool-v1");
      assert.equal(sqlpool.length, 12);
      assert.ok(sqlpool.every(item => item.language === "sqlpool" && item.truth === "simulated"));
      const poolGrading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "sqlpool-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const replicate = sqlpool.find(item => item.id === "sp-replicate-dimension")!;
      const replicated = await submit(replicate, poolGrading[replicate.id].solution);
      assert.equal(replicated.status, "passed", JSON.stringify(replicated.checks));
      assert.equal(replicated.truth, "simulated");
      assert.equal((await submit(replicate, replicate.starterSource)).status, "failed", "a round-robin dimension is broadcast");
      const fabricPort = sqlpool.find(item => item.id === "sp-fabric-port")!;
      const synapseOptions = await submit(fabricPort, fabricPort.starterSource);
      assert.equal(synapseOptions.status, "failed");
      assert.match(synapseOptions.checks[0].message, /takes no DISTRIBUTION/);
      // Databricks: jobs, notebooks and grants graded on simulated runs, each on an isolated catalog.
      const databricks = catalog.filter(item => item.packId === "databricks-v1");
      assert.equal(databricks.length, 13);
      assert.deepEqual([...new Set(databricks.map(item => item.language))].sort(), ["databricks-grants", "databricks-job", "databricks-notebook"]);
      const dbxGrading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "databricks-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const leastPrivilege = databricks.find(item => item.id === "uc-least-privilege-job")!;
      const granted = await submit(leastPrivilege, dbxGrading[leastPrivilege.id].solution);
      assert.equal(granted.status, "passed", JSON.stringify(granted.checks));
      assert.equal((await submit(leastPrivilege, "GRANT ALL PRIVILEGES ON CATALOG main TO `sp-etl`;")).status, "failed");
      const taskValue = databricks.find(item => item.id === "dbx-task-value-notebook")!;
      assert.equal((await submit(taskValue, dbxGrading[taskValue.id].solution)).status, "passed");
      assert.equal((await submit(taskValue, taskValue.starterSource)).status, "failed", "an exit value is not a task value");
      // BI Lab: warehouse SQL and star models graded on real DuckDB, each check on an isolated catalog.
      const dwh = catalog.filter(item => item.packId === "dwh-v1");
      assert.equal(dwh.length, 20);
      assert.deepEqual([...new Set(dwh.map(item => item.language))].sort(), ["bi-model", "warehouse"]);
      assert.ok(dwh.every(item => item.truth === "real"));
      const dwhGrading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "dwh-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const scd2 = dwh.find(item => item.id === "dwh-scd2-apply")!;
      const versioned = await submit(scd2, dwhGrading[scd2.id].solution);
      assert.equal(versioned.status, "passed", JSON.stringify(versioned.checks));
      assert.equal(versioned.truth, "real");
      assert.equal((await submit(scd2, scd2.starterSource)).status, "failed", "a type 1 overwrite loses the history");
      const governed = dwh.find(item => item.id === "dwh-lineage-governed-revenue")!;
      assert.equal((await submit(governed, dwhGrading[governed.id].solution)).status, "passed");
      const fallback = await submit(governed, "CREATE OR REPLACE TABLE gold.fct_order_revenue AS\nWITH lines AS (SELECT order_id, " +
        "SUM(quantity * unit_price - discount_amount) AS net FROM source.shop_order_lines GROUP BY order_id)\nSELECT o.order_id, " +
        "o.order_date, COALESCE(l.net, o.order_total - o.shipping_fee) AS net_revenue FROM source.shop_orders AS o " +
        "LEFT JOIN lines AS l ON l.order_id = o.order_id;\n");
      assert.equal(fallback.status, "failed", "a fallback to the header total shows in the lineage");
      assert.equal(fallback.checks.find(check => check.visibility === "visible")?.passed, true, "its visible rows are right");
      const starModel = dwh.find(item => item.id === "bi-model-relationships")!;
      assert.equal(starModel.language, "bi-model");
      assert.equal((await submit(starModel, dwhGrading[starModel.id].solution)).status, "passed");
      const notJson = await submit(starModel, "{ \"tables\": [");
      assert.equal(notJson.status, "failed");
      assert.match(notJson.checks[0].message, /Model rejected: not valid JSON/);
      // BI Lab dbt: one file of a dbt project, graded on the emulation with an isolated catalog.
      const dbtPack = catalog.filter(item => item.packId === "dbt-v1");
      assert.equal(dbtPack.length, 12);
      assert.deepEqual([...new Set(dbtPack.map(item => item.language))].sort(), ["dbt-sql", "dbt-yml"]);
      assert.ok(dbtPack.every(item => item.truth === "semantic-emulation"));
      const dbtGrading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "dbt-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const snapshot = dbtPack.find(item => item.id === "dbt-snapshot-timestamp")!;
      const snapped = await submit(snapshot, dbtGrading[snapshot.id].solution);
      assert.equal(snapped.status, "passed", JSON.stringify(snapped.checks));
      assert.equal(snapped.truth, "semantic-emulation");
      assert.equal((await submit(snapshot, snapshot.starterSource)).status, "failed", "the check strategy dates versions with the run");
      const tests = dbtPack.find(item => item.id === "dbt-generic-tests")!;
      assert.equal(tests.language, "dbt-yml");
      assert.equal((await submit(tests, dbtGrading[tests.id].solution)).status, "passed");
      const sandboxed = await submit(dbtPack.find(item => item.id === "dbt-staging-model")!, "select '{{ ''.__class__ }}' as x\n");
      assert.equal(sandboxed.status, "failed");
      await runtime!.refreshCatalog();
      assert.equal(JSON.stringify(runtime!.snapshot().catalog?.map(item => [item.name, item.row_count])), catalogBefore,
        "exercise grading must not touch the workspace catalog");
    }],
    ["Pipeline starter compiles into a graph and runs its activities", async () => {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, "pipelines"));
      await write("pipelines/main.pipeline.py", pipelineStarter());
      const pipeline = await loadPipelineState(runtime!);
      assert.equal(pipeline.compileStatus, "valid", JSON.stringify(pipeline.diagnostics));
      assert.equal(pipeline.graph.nodes.length, 3);
      assert.ok(pipeline.graph.nodes.every(node => node.truth === "Real local execution"));
      await runtime!.labs.pipeline.runPipeline(pipelineStarter());
      const run = runtime!.snapshot().pipelineRun;
      assert.equal(run?.status, "success", JSON.stringify(run?.tasks));
      assert.deepEqual(run?.tasks.map(task => task.status), ["success", "success", "success"]);
    }],
    ["retail demo executes the medallion flow locally", async () => {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, "datasets"));
      await write("datasets/retail_orders.csv", retailOrdersCsv());
      await runtime!.labs.fabric.runRetailDemo("datasets/retail_orders.csv");
      const demo = runtime!.snapshot().retailDemo;
      assert.equal(demo?.status, "success");
      assert.ok(demo && demo.stages.length >= 3);
      assert.ok(demo && demo.preview.rows.length > 0);

      // The generated retail SQL notebook then runs through Mosaic on bronze.orders.
      await runtime!.labs.mosaic.runSql(retailSqlStarter("datasets/retail_orders.csv"));
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
      await runtime!.labs.mosaic.importCsv(asset, text, "City Visits.csv");
      const imported = runtime!.snapshot().csvImport;
      assert.equal(imported?.asset, asset);
      assert.equal(imported?.rows_imported, 2);
      assert.deepEqual(imported?.schema.map(column => column.type), ["VARCHAR", "VARCHAR"]);
      assert.ok(runtime!.snapshot().catalog?.some(item => item.name === asset && item.row_count === 2));
      assert.match(validateBronzeAsset(asset, runtime!.snapshot().catalog!.map(item => item.name)) ?? "", /already exists/);
      await assert.rejects(runtime!.labs.mosaic.importCsv(asset, "city\nParis\n", "again.csv"), /CSV import refused: .*already exists/);

      await runtime!.labs.mosaic.runSql(`SELECT SUM(CAST(visits AS INTEGER)) AS visits FROM ${asset}`);
      const sum = runtime!.snapshot();
      assert.deepEqual(sum.lastRun?.result?.rows, [{ visits: 8 }], sum.lastRun?.error?.message);
      assert.equal(sum.csvImport, undefined, "a newer SQL run replaces the import preview");
    }],
    ["Mosaic data tools: typed JSON import, SUMMARIZE profile, EXPLAIN ANALYZE", async () => {
      const json = JSON.stringify([{ sku: "A1", qty: 2, price: 9.5 }, { sku: "B2", qty: 5, price: 3.25 }]);
      const imported = await runtime!.labs.mosaic.importFile("bronze.skus_e2e", "json", Buffer.from(json).toString("base64"), "skus.json");
      assert.equal(imported.rows_imported, 2);
      assert.equal(imported.format, "json");
      assert.ok(imported.schema.some(column => column.name === "qty" && /INT/.test(column.type)), JSON.stringify(imported.schema));
      await assert.rejects(runtime!.labs.mosaic.importFile("bronze.skus_e2e", "json", Buffer.from(json).toString("base64"), "again.json"),
        /JSON import refused: .*already exists/);
      await runtime!.labs.mosaic.profileTable("bronze.skus_e2e");
      const profile = runtime!.snapshot().tableProfile!;
      assert.equal(profile.asset, "bronze.skus_e2e");
      assert.deepEqual(profile.result.rows.map(row => row.column_name), ["sku", "qty", "price"]);
      const plan = await runtime!.labs.mosaic.explainQuery("SELECT sku, SUM(qty * price) AS revenue FROM bronze.skus_e2e GROUP BY sku", "e2e.sql");
      assert.match(plan.plan, /HASH_GROUP_BY/);
      assert.equal(runtime!.snapshot().queryPlan?.source, "e2e.sql");
      await assert.rejects(runtime!.labs.mosaic.explainQuery("DROP TABLE bronze.skus_e2e"), /EXPLAIN ANALYZE refused/);
    }],
    ["Mosaic SQL dialects: the status bar command writes the header; T-SQL is translated, run and explained", async () => {
      const file = vscode.Uri.joinPath(root, "dialect_e2e.sql");
      await vscode.workspace.fs.writeFile(file, new TextEncoder().encode(
        "SELECT TOP 1 sku, qty / 2 AS half FROM bronze.skus_e2e ORDER BY qty DESC;\n"));
      const document = await vscode.workspace.openTextDocument(file);
      await vscode.window.showTextDocument(document);
      await vscode.commands.executeCommand("datapass.sql.pickDialect", "tsql");
      assert.equal(document.lineAt(0).text, "-- dialect: tsql");
      await document.save();
      const { dialect } = runDialect(document.getText());
      assert.equal(dialect, "tsql");
      const run = await runtime!.labs.mosaic.runSql(document.getText(), dialect);
      assert.equal(run.status, "success", JSON.stringify(run.error));
      assert.deepEqual(run.result?.rows, [{ sku: "B2", half: 2 }], "5 / 2 is an integer division in T-SQL");
      assert.equal(run.dialect?.label, "T-SQL dialect translated to DuckDB, not SQL Server");
      assert.match(run.dialect!.sql, /qty \/\/ 2[\s\S]*LIMIT 1/);
      const plan = await runtime!.labs.mosaic.explainQuery(document.getText(), "dialect_e2e.sql", dialect);
      assert.equal(plan.dialect?.source, "tsql");
      assert.match(plan.truth, /not SQL Server/);
      const refused = await runtime!.labs.mosaic.runSql("SELECT GETDATE() AS now", "tsql");
      assert.equal(refused.status, "error");
      assert.equal(refused.error?.type, "TsqlDialectError");
      await vscode.commands.executeCommand("datapass.sql.pickDialect", "duckdb");
      assert.ok(!document.getText().includes("-- dialect"), "DuckDB needs no header");
      await document.save();
      await vscode.commands.executeCommand("workbench.action.closeActiveEditor");
    }],
    ["Projects: the runtime verifies steps on the workspace and progress.json keeps them", async () => {
      const retail = (await loadProjectContents(extension.extensionUri)).projects[0];
      const csv = new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(root, "projects", "retail-fabric", "web_orders_2026-03-05.csv")));
      await runtime!.labs.mosaic.importCsv("bronze.web_orders", decodeCsvBytes(new TextEncoder().encode(csv)), "web_orders_2026-03-05.csv");
      const result = await runtime!.labs.projects.checkProject("retail-fabric", ["import-web-orders", "silver-web-orders"]) as {
        steps: { id: string; status: string; checks: { truth: string }[] }[];
      };
      assert.deepEqual(result.steps.map(step => [step.id, step.status]), [["import-web-orders", "passed"], ["silver-web-orders", "failed"]]);
      assert.equal(result.steps[0].checks[0].truth, "real");
      const progress = await readProgress();
      await writeProgress(applyVerification(progress.document, retail, result, new Date().toISOString()));
      const state = (await loadProjectsState(extension.extensionUri)).projects[0];
      const byId = Object.fromEntries(state.steps.map(step => [step.id, step]));
      assert.equal(byId["import-web-orders"].state, "verified");
      assert.equal(byId["silver-web-orders"].state, "failed");
      assert.equal(byId["runbook"].state, "manual", "the tick by hand is kept apart");
      assert.equal(state.progress.verified, 1);
      assert.equal(state.nextStepId, "type-imported-text");

      // The exercise step is verified by a real Submit, recorded by the runtime's journal.
      const exercise = (await loadExerciseCatalog(extension.extensionUri)).find(item => item.key === "de-patterns-v1/de-clean-imported-text/sql")!;
      await runtime!.labs.practice.gradeExercise(exercise.key, {
        exercise_id: exercise.id, exercise_version: exercise.version, language: exercise.language,
        code: exercise.starterSource, mode: "submit", notebook_id: "e2e-project", cell_id: "solution", source_revision: 0
      });
      const starter = await runtime!.labs.projects.checkProject("retail-fabric", ["type-imported-text"]) as { steps: { status: string }[] };
      assert.equal(starter.steps[0].status, "failed", "a failing submission does not verify the step");
      await assert.rejects(runtime!.labs.projects.checkProject("nope", []), /Unknown project/);
    }],
    ["explicit trust restarts the runtime and runs Python for real", async () => {
      await runtime!.stopAndWait();
      await runtime!.start(python, "duckdb", true);
      const state = runtime!.snapshot();
      assert.equal(state.status, "running", state.detail);
      assert.equal(state.trustedPython, true);
      await runtime!.labs.mosaic.runPython(scratchSpec("python").content);
      const run = runtime!.snapshot().lastRun;
      assert.equal(run?.status, "success", run?.error?.message);
      assert.match(run?.stdout ?? "", /\(3, 1\)/);
      assert.deepEqual(run?.result?.columns, ["value"]);
    }],
    ["ZillaCode pack grades one exercise in every language, Snowflake SQL translated to DuckDB", async () => {
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const zilla = catalog.filter(item => item.packId === "zilla-v1");
      assert.equal(new Set(zilla.map(item => item.id.replace(/-(sql|snowflake|python|polars|sparklab|dbt-sql)$/, ""))).size, 52);
      const grading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "zilla-v1", "grading.server.json")
      ))) as Record<string, { solutions: Record<string, string> }>;
      const submit = async (exercise: (typeof zilla)[number], code: string) => {
        await runtime!.labs.practice.gradeExercise(exercise.key, {
          exercise_id: exercise.id, exercise_version: exercise.version, language: exercise.language,
          code, mode: "submit", notebook_id: "e2e-zilla", cell_id: "solution", source_revision: 1
        });
        return runtime!.snapshot().practiceResult!;
      };
      const expectedTruth: Record<string, string> = {
        sql: "real", python: "real", polars: "real", snowflake: "semantic-emulation", sparklab: "semantic-emulation",
        "dbt-sql": "semantic-emulation"
      };
      for (const language of ["sql", "snowflake", "python", "polars", "sparklab", "dbt-sql"]) {
        const exercise = zilla.find(item => item.id === `zilla-001-popular-videos-${language}`);
        assert.ok(exercise, `zilla-001 has a ${language} variant`);
        const passed = await submit(exercise, grading["zilla-001-popular-videos"].solutions[language]);
        assert.equal(passed.status, "passed", `${language}: ${JSON.stringify(passed.checks)}`);
        assert.equal(passed.truth, expectedTruth[language], language);
        assert.deepEqual(passed.checks.map(check => check.visibility), ["visible", "hidden", "edge"], language);
        assert.equal((await submit(exercise, exercise.starterSource)).status, "failed", `${language} starter must fail`);
      }
      // Snowflake sorts NULLs first in a descending order: without NULLS LAST, the unscored page wins.
      const pages = zilla.find(item => item.id === "zilla-015-best-pages-snowflake")!;
      const reference = grading["zilla-015-best-pages"].solutions.snowflake;
      assert.equal((await submit(pages, reference)).status, "passed");
      const nullsFirst = await submit(pages, reference.replaceAll(" NULLS LAST", ""));
      assert.equal(nullsFirst.status, "failed", "Snowflake's default NULL order must fail the edge check");
      assert.deepEqual(nullsFirst.checks.map(check => check.passed), [true, true, false]);
      // Functions outside the subset are refused by name, never approximated.
      const refused = await submit(pages, "SELECT domain, HASH(url) AS h FROM pages");
      assert.equal(refused.status, "failed");
      assert.match(refused.checks[0].message, /HASH is not in the supported Snowflake subset.*not Snowflake/);
    }],
    ["Engine lab T-SQL and BigQuery variants: translated to DuckDB and graded, with the dialects' semantics", async () => {
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const engine = catalog.filter(item => item.packId === "engine-lab-v1");
      assert.equal(engine.filter(item => item.language === "tsql").length, 17);
      assert.equal(engine.filter(item => item.language === "bigquery").length, 18);
      const grading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "engine-lab-v1", "grading.server.json")
      ))) as Record<string, { solutions: Record<string, string> }>;
      const submit = async (id: string, code: string) => {
        const exercise = engine.find(item => item.id === id)!;
        await runtime!.labs.practice.gradeExercise(exercise.key, {
          exercise_id: exercise.id, exercise_version: exercise.version, language: exercise.language,
          code, mode: "submit", notebook_id: "e2e-engine", cell_id: "solution", source_revision: 1
        });
        return runtime!.snapshot().practiceResult!;
      };
      const share = await submit("eng-transform-share-tsql", grading["eng-transform-share"].solutions.tsql);
      assert.equal(share.status, "passed", JSON.stringify(share.checks));
      assert.equal(share.truth, "semantic-emulation");
      // T-SQL divides integers as integers: the translation keeps it, so this answer is wrong.
      const integerShare = await submit("eng-transform-share-tsql", "SELECT customer_id, order_id, amount, " +
        "SUM(amount) OVER (PARTITION BY customer_id) AS customer_total, " +
        "CAST(amount AS INT) / CAST(SUM(amount) OVER (PARTITION BY customer_id) AS INT) AS amount_share FROM orders;");
      assert.equal(integerShare.status, "failed");
      const flag = await submit("eng-derived-flag-bigquery", grading["eng-derived-flag"].solutions.bigquery);
      assert.equal(flag.status, "passed", JSON.stringify(flag.checks));
      const unnest = await submit("eng-derived-flag-bigquery", "SELECT x FROM UNNEST([1, 2]) AS x");
      assert.match(unnest.checks[0].message, /not BigQuery/);
    }],
    ["Spark SQL track: Spark SQL translated to DuckDB and graded, with Spark's semantics", async () => {
      const catalog = await loadExerciseCatalog(extension.extensionUri);
      const track = catalog.filter(item => item.packId === "spark-sql-v1");
      assert.equal(track.length, 9);
      assert.ok(track.every(item => item.language === "sparksql" && item.truth === "semantic-emulation"));
      const grading = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(
        vscode.Uri.joinPath(extension.extensionUri, "content", "exercise-packs", "spark-sql-v1", "grading.server.json")
      ))) as Record<string, { solution: string }>;
      const anti = track.find(item => item.id === "sparksql-left-anti-join")!;
      const submit = async (code: string) => {
        await runtime!.labs.practice.gradeExercise(anti.key, {
          exercise_id: anti.id, exercise_version: anti.version, language: anti.language,
          code, mode: "submit", notebook_id: "e2e-sparksql", cell_id: "solution", source_revision: 1
        });
        return runtime!.snapshot().practiceResult!;
      };
      const passed = await submit(grading[anti.id].solution);
      assert.equal(passed.status, "passed", JSON.stringify(passed.checks));
      // NOT IN with a NULL in the subquery returns nothing, in Spark as in DuckDB: the guest-order fixture fails.
      const notIn = await submit(anti.starterSource);
      assert.equal(notIn.status, "failed");
      const exploded = await submit("SELECT EXPLODE(ARRAY(1, 2)) AS x");
      assert.match(exploded.checks[0].message, /not Spark/);
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
