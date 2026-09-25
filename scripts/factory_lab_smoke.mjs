import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-factory-"));

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
  const outfile = path.join(dir, "factory-run.mjs");
  await esbuild.build({
    entryPoints: ["src/platform/factoryRun.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });
  const factory = await import(pathToFileURL(outfile).href);

  // Every sample file maps to the reference the runtime resolves (see scripts/runtime_smoke.py factory_files).
  const samples = "samples/factory-lab";
  const roles = Object.fromEntries((await walk(samples)).map(file => [file, factory.classifyFactoryPath(file)]));
  assert.deepEqual(roles["fabric/pl_retail_daily.DataPipeline/pipeline-content.json"], { role: "pipeline", flavor: "fabric", name: "pl_retail_daily" });
  assert.deepEqual(roles["fabric/nb_silver_orders.Notebook/notebook-content.py"], { role: "notebook", key: "fabric:nb_silver_orders" });
  assert.deepEqual(roles["adf/pipeline/pl_retail_daily_adf.json"], { role: "pipeline", flavor: "adf", name: "pl_retail_daily_adf" });
  assert.deepEqual(roles["adf/dataset/ds_bronze_orders.json"], { role: "dataset", flavor: "adf", name: "ds_bronze_orders" });
  assert.equal(roles["adf/linkedService/ls_lab_sql.json"], undefined, "linked services are documentation only");
  assert.deepEqual(roles["databricks/Shared/nb_silver_orders_dbx.py"], { role: "notebook", key: "databricks:/Shared/nb_silver_orders_dbx" });
  assert.deepEqual(roles["sql/procedures/warehouse.usp_load_gold_revenue.sql"], { role: "procedure", name: "warehouse.usp_load_gold_revenue" });
  assert.deepEqual(roles["synapse/pipeline/pl_sqlpool_daily.json"], { role: "pipeline", flavor: "synapse", name: "pl_sqlpool_daily" });
  assert.deepEqual(factory.classifyFactoryPath("synapse/notebook/nb_x.py"), { role: "notebook", key: "synapse:nb_x" });
  assert.equal(factory.classifyFactoryPath("fabric/../adf/pipeline/x.json"), undefined);
  assert.equal(factory.pipelineRelativePath("fabric", "p"), "factory/fabric/p.DataPipeline/pipeline-content.json");
  assert.equal(factory.pipelineRelativePath("adf", "p"), "factory/adf/pipeline/p.json");

  // JSON errors carry a line number, as the editor reports them.
  const broken = factory.parseJsonDocument('{\n  "properties": {\n    "activities": [,]\n  }\n}');
  assert.match(broken.error, /^Invalid JSON/);
  assert.equal(factory.designView("adf", "x", "factory/adf/pipeline/x.json", "{}").error, "No properties.activities array: is this a pipeline file?");

  // Design view and canvas of the Fabric sample: conditions become edge labels and classes.
  const fabricPath = `${samples}/fabric/pl_retail_daily.DataPipeline/pipeline-content.json`;
  const design = factory.designView("fabric", "pl_retail_daily", "factory/fabric/pl_retail_daily.DataPipeline/pipeline-content.json",
    await readFile(fabricPath, "utf8"));
  assert.equal(design.error, undefined);
  assert.deepEqual(design.parameters.map(p => [p.name, p.type, p.defaultValue]), [["run_date", "string", "2026-03-05"], ["min_amount", "int", 0]]);
  const ifActivity = design.activities.find(a => a.type === "IfCondition");
  assert.deepEqual(ifActivity.children.map(c => [c.key, c.activities.map(a => a.path)]),
    [["ifTrueActivities", ["Has gold rows/Post to Teams"]], ["ifFalseActivities", ["Has gold rows/Fail empty gold"]]]);
  const graph = factory.factoryGraph(design.activities);
  const alert = graph.edges.find(e => e.target === "Email on notebook failure");
  assert.deepEqual([alert.source, alert.label, alert.className], ["Silver orders", "Failed", "factory-edge cond-failed"]);
  assert.equal(graph.nodes.find(n => n.id === "Has gold rows").detail, "IfCondition · 2 inner");
  const inner = factory.factoryGraph(ifActivity.children[0].activities);
  assert.deepEqual(inner.nodes.map(n => n.id), ["Has gold rows/Post to Teams"]);
  assert.equal(factory.flattenActivities(design.activities).filter(a => !factory.isControlActivity(a.type)).length, 6);

  // Scenario form -> runtime scenario: behaviors map to attempts, blanks keep defaults, bad JSON is reported.
  const { scenario, errors } = factory.toRuntimeScenario({
    dataPlane: "simulated",
    parameters: { run_date: "2026-03-06", min_amount: "  " },
    activities: {
      "Copy orders to bronze": { behavior: "fail_twice", durationSeconds: 45 },
      "Count gold rows": { behavior: "success", output: '{"firstRow": {"segments": 2}}' },
      "Silver orders": { behavior: "fail_always" },
      "Gold revenue": { behavior: "success", output: "[1, 2]" },
      "Post to Teams": { behavior: "success" }
    },
    triggerType: "ScheduleTrigger",
    now: "2026-03-06T06:00"
  });
  assert.deepEqual(scenario, {
    parameters: { run_date: "2026-03-06" },
    activities: {
      "Copy orders to bronze": { fail_attempts: [1, 2], duration_seconds: 45 },
      "Count gold rows": { output: { firstRow: { segments: 2 } } },
      "Silver orders": { fail_attempts: "all" }
    },
    trigger_type: "ScheduleTrigger",
    now: "2026-03-06T06:00:00Z"
  });
  assert.deepEqual(errors, ['Gold revenue: the output must be a JSON object, for example {"firstRow": {"n": 3}}']);

  // Runtime view -> webview view, with the leaf rule explained.
  const view = factory.toFactoryLabView({
    status: "simulated", flavor_label: "Microsoft Fabric Data Factory", truth: "Simulated.", data_plane: "local",
    issues: [], hints: [], pipeline: { warnings: ["w1"] },
    run: {
      pipeline: "pl", run_id: "abc", status: "Failed", evaluated: ["A", "C"], duration_s: 12,
      parameters: {}, variables: { v: "1" }, return_value: null, children: [],
      activity_runs: [
        { name: "A", type: "Copy", path: "A", status: "Failed", start_s: 0, end_s: 10, attempts: 1, input: {}, output: null,
          error: { errorCode: "2200", message: "boom", failureType: "UserError" }, iteration: null, truth: "local", note: "", parent: null },
        { name: "B", type: "Wait", path: "B", status: "Skipped", start_s: 10, end_s: 10, attempts: 0, truth: "simulated", note: "Dependency condition not met" },
        { name: "C", type: "Wait", path: "C", status: "Succeeded", start_s: 10, end_s: 12, attempts: 1, truth: "simulated", note: "" }
      ]
    },
    tables_changed: [{ name: "bronze.orders", rows: 12, producer: "pipeline:pl/A" }]
  }, { flavor: "fabric", pipelineName: "pl", path: "factory/fabric/pl.DataPipeline/pipeline-content.json", scenario: {} });
  assert.equal(view.status, "simulated");
  assert.equal(view.dataPlane, "local");
  assert.deepEqual(view.warnings, ["w1"]);
  assert.equal(view.run.activityRuns[0].error.message, "boom");
  assert.equal(view.run.activityRuns[0].truth, "local");
  assert.equal(view.run.returnValue, undefined);
  assert.match(view.run.explanation, /^Failed: A did not succeed among the evaluated activities A \(Failed\), C \(Succeeded\)/);
  assert.deepEqual(view.tablesChanged, [{ name: "bronze.orders", rows: 12, producer: "pipeline:pl/A" }]);
  const statuses = factory.factoryGraph([{ name: "A", type: "Copy", path: "A", state: "Active", dependsOn: [], children: [] }], view.run);
  assert.equal(statuses.nodes[0].status, "failed");
  const invalid = factory.toFactoryLabView({ status: "invalid", issues: [{ path: "A", message: "bad" }] },
    { flavor: "adf", pipelineName: "p", path: "p", scenario: {} });
  assert.deepEqual([invalid.status, invalid.run, invalid.issues[0].severity], ["invalid", undefined, "error"]);

  console.log("Factory Lab mapping smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
