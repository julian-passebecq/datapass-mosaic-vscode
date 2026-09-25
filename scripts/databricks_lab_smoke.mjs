import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-databricks-"));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  return import(pathToFileURL(outfile).href);
}

async function walk(root, prefix = "") {
  const found = [];
  for (const entry of await readdir(path.join(root, prefix), { withFileTypes: true })) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) found.push(...await walk(root, relative));
    else found.push(relative);
  }
  return found;
}

try {
  const dbx = await bundle("src/platform/databricksRun.ts", "databricks-run.mjs");
  const factory = await bundle("src/platform/factoryRun.ts", "factory-run.mjs");

  // Every sample file of factory/databricks has a role, keyed as the runtime resolves it.
  const samples = "samples/factory-lab/databricks";
  const roles = Object.fromEntries((await walk(samples)).map(file => [file, factory.classifyFactoryPath(`databricks/${file}`)]));
  assert.ok(Object.values(roles).every(Boolean), JSON.stringify(roles));
  assert.deepEqual(roles["jobs/retail_daily_dbx.json"], { role: "dbxJob", name: "retail_daily_dbx" });
  assert.deepEqual(roles["Shared/ml/nb_train_power_model.py"], { role: "notebook", key: "databricks:/Shared/ml/nb_train_power_model" });
  assert.deepEqual(roles["Shared/sql/gold_checks.sql"], { role: "dbxSql", key: "databricks:/Shared/sql/gold_checks.sql" });
  assert.deepEqual([roles["compute.json"], roles["unity_catalog.json"], roles["grants.sql"]],
    [{ role: "dbxCompute" }, { role: "dbxUnity" }, { role: "dbxGrants" }]);
  assert.equal(factory.classifyFactoryPath("databricks/jobs/nested/x.json"), undefined);
  assert.equal(factory.classifyFactoryPath("databricks/other.json"), undefined);

  // Design view and canvas of the retail job: condition outcomes and run_if become edge labels.
  const retail = dbx.jobDesignView("retail_daily_dbx", "factory/databricks/jobs/retail_daily_dbx.json",
    await readFile(`${samples}/jobs/retail_daily_dbx.json`, "utf8"));
  assert.equal(retail.error, undefined);
  assert.deepEqual(retail.parameters, [{ name: "run_date", defaultValue: "{{job.start_time.iso_date}}" }, { name: "min_amount", defaultValue: "0" }]);
  assert.deepEqual(retail.clusters, [{ key: "etl_cluster", label: "Standard_DS3_v2, 2 workers" }]);
  assert.deepEqual(retail.tasks.map(t => [t.key, t.kind, t.compute]), [
    ["ingest_orders", "notebook", "job cluster etl_cluster"], ["has_new_rows", "condition", ""],
    ["silver_orders", "notebook", "job cluster etl_cluster"], ["gold_revenue", "notebook", "job cluster etl_cluster"],
    ["gold_checks", "sql", "warehouse serverless-sql"], ["alert_on_failure", "notebook", "serverless"]]);
  assert.equal(retail.tasks[1].detail, "{{tasks.ingest_orders.values.new_rows}} > 0");
  const graph = dbx.databricksGraph(retail);
  const branch = graph.edges.find(e => e.target === "silver_orders");
  assert.deepEqual([branch.source, branch.label, branch.className], ["has_new_rows", "(true)", "factory-edge cond-succeeded"]);
  const handler = graph.edges.find(e => e.target === "alert_on_failure");
  assert.deepEqual([handler.label, handler.className], ["at least one failed", "factory-edge cond-failed"]);
  const power = dbx.jobDesignView("power_model_training", "p", await readFile(`${samples}/jobs/power_model_training.json`, "utf8"));
  assert.equal(power.runAs, "sp-ml-training");
  const loop = dbx.jobDesignView("segment_reports", "p", await readFile(`${samples}/jobs/segment_reports.json`, "utf8"));
  assert.equal(loop.tasks[0].inner.key, "segment_report");
  assert.equal(loop.tasks[0].inner.compute, "all-purpose analytics-shared");
  assert.match(dbx.jobDesignView("x", "p", "{}").error, /No tasks array/);
  assert.match(dbx.jobDesignView("x", "p", "{ nope").error, /^Invalid JSON/);

  // Run settings -> runtime scenario.
  const { scenario, errors } = dbx.toDatabricksScenario({
    dataPlane: "simulated",
    jobParameters: { run_date: "2026-03-09", min_amount: " " },
    tasks: {
      ingest_orders: { behavior: "fail_once", durationSeconds: 30, values: '{"new_rows": 0}' },
      silver_orders: { behavior: "fail_always" },
      gold_revenue: { behavior: "success", values: "[1]" },
      gold_checks: { behavior: "success" }
    },
    triggerType: "periodic",
    now: "2026-03-09T06:00",
    clusterStates: { "analytics-shared": "RUNNING" }
  });
  assert.deepEqual(scenario, {
    job_parameters: { run_date: "2026-03-09" },
    tasks: { ingest_orders: { fail_attempts: [1], duration_seconds: 30, values: { new_rows: 0 } }, silver_orders: { fail_attempts: "all" } },
    trigger_type: "periodic",
    cluster_states: { "analytics-shared": "RUNNING" },
    now: "2026-03-09T06:00:00Z"
  });
  assert.deepEqual(errors, ['gold_revenue: task values must be a JSON object, for example {"new_rows": 0}']);

  // Runtime view -> webview view (the shape of datapass_runtime.databricks_workspace.run).
  const raw = {
    status: "simulated", truth: "Simulated Azure Databricks.", data_plane: "local", issues: [], warnings: ["w1"],
    run: {
      run_id: 42, job_id: 7, result_state: "SUCCESS_WITH_FAILURES", status_label: "Succeeded with failures", explanation: "x",
      leaves: ["b"], duration_s: 420, principal: "sp", start_time: "2026-03-05T06:00:00+00:00", trigger_type: "one_time",
      parameters: { run_date: "2026-03-05" }, notes: [],
      tasks: [
        { key: "a", kind: "notebook", state: "failed", state_label: "Failed", start_s: 300, end_s: 420, duration_s: 120,
          attempts: [{ number: 1, start_s: 300, end_s: 420, status: "failed", error: "boom" }], compute: "Job cluster c",
          parameters: { run_date: "2026-03-05" }, outcome: null, condition: null, exit_value: null, values: {}, error: "boom",
          error_code: "UnauthorizedError", tables_written: [], notes: [], columns: [], rows: [], iterations: [], reason: "" },
        { key: "c", kind: "condition", state: "success", state_label: "Succeeded", start_s: 0, end_s: 0, duration_s: 0,
          attempts: [], compute: "", parameters: {}, outcome: "false",
          condition: { left: "0", op: ">", right: "0", left_expression: "{{tasks.a.values.n}}", right_expression: "0", result: false },
          values: {}, error: "", error_code: "", tables_written: [], notes: [], columns: [], rows: [], iterations: [], reason: "" },
        { key: "b", kind: "sql", state: "excluded", state_label: "Excluded", start_s: 0, end_s: 0, duration_s: 0, attempts: [],
          compute: "", parameters: {}, values: { n: 3 }, error: "", error_code: "", tables_written: [], notes: [],
          columns: ["n"], rows: [{ n: 1, extra: [1, 2] }], iterations: [], reason: "all its dependencies were excluded" }
      ],
      compute: [{ key: "c", kind: "job_cluster", label: "Job cluster c", requested_s: 0, ready_s: 300, end_s: 420, startup_s: 300,
                  billed_s: 420, nodes: 3, dbu_per_hour: 2.25, dbu: 0.2625, rate: 0.3, cost: 0.0788, tasks: ["a"],
                  idle_after_s: 0, idle_dbu: 0, idle_cost: 0, notes: ["n"] }],
      cost: { dbu: 0.2625, cost: 0.0788, idle_dbu: 0, idle_cost: 0 }
    },
    tables_changed: [{ name: "gold.x", rows: 4, producer: "job:j/a" }],
    unity: { catalog: "main", lab_user: "you@datapass.lab", groups: { g: ["u"] }, owners: { "main.gold.x": "sp" },
             grants: [{ privilege: "SELECT", securable: "SCHEMA", name: "main.gold", principal: "g" }],
             schemas: [{ name: "main.gold", read_only: false, tables: [{ name: "main.gold.x", table: "gold.x", rows: 4, owner: "sp" }],
                         models: [{ name: "main.ml.m", owner: "sp", versions: 2, aliases: { champion: 2 } }] }], warnings: [] },
    mlflow: { experiments: [{ name: "/Shared/e", id: "1000", runs: [{ run_id: "abc", run_name: "r", status: "FINISHED", params: { a: "1" },
                                                                   metrics: { rmse: 0.5 }, tags: {}, models: ["model"], start: "s" }] }],
              models: [{ name: "main.ml.m", owner: "sp", aliases: { champion: 2 }, versions: [{ version: 1, run_id: "abc", created: "c",
                          metrics: { rmse: 0.5 }, kind: "LinearRegressionModel", signature: { inputs: ["x"], outputs: [] } }] }] },
    compute_catalog: { clusters: [{ cluster_id: "a", name: "A", node_type: "n", workers: 2, autotermination_minutes: 60, running: false }],
                       warehouses: [{ id: "w", name: "W", size: "2X-Small", serverless: true }] }
  };
  const view = dbx.toDatabricksLabView(raw, { jobName: "j", path: "p", scenario: {}, warnings: ["host"] });
  assert.equal(view.status, "simulated");
  assert.deepEqual(view.warnings, ["host", "w1"]);
  assert.equal(view.run.statusLabel, "Succeeded with failures");
  assert.equal(view.run.tasks[0].errorCode, "UnauthorizedError");
  assert.equal(view.run.tasks[1].condition.leftExpression, "{{tasks.a.values.n}}");
  assert.equal(view.run.tasks[1].outcome, "false");
  assert.deepEqual(view.run.tasks[2].rows, [{ n: 1, extra: "[1,2]" }]);
  assert.equal(view.run.compute[0].startupS, 300);
  const state = dbx.toDatabricksStateView(raw);
  assert.deepEqual(state.unity.schemas[0].models[0].aliases, { champion: 2 });
  assert.equal(state.mlflow.models[0].versions[0].inputs[0], "x");
  assert.equal(state.computeCatalog.clusters[0].autoterminationMinutes, 60);

  // Graph colors after a run, and what each state means.
  const colored = dbx.databricksGraph(retail, { ...view.run, tasks: [{ ...view.run.tasks[0], key: "ingest_orders" }] });
  assert.equal(colored.nodes.find(n => n.id === "ingest_orders").status, "failed");
  assert.match(dbx.explainTask(view.run.tasks[1]), /0 > 0 is false: the false branch runs/);
  assert.match(dbx.explainTask(view.run.tasks[2]), /^Excluded: all its dependencies were excluded/);
  assert.match(dbx.explainTask(view.run.tasks[0]), /^Failed \(UnauthorizedError\): boom/);
  assert.equal(dbx.formatSeconds(45), "45 s");
  assert.equal(dbx.formatSeconds(320), "5 min 20 s");
  assert.equal(dbx.formatSeconds(3720), "1 h 2 min");

  console.log("Databricks Lab smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
