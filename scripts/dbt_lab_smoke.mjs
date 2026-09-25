import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-dbt-lab-"));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  return import(pathToFileURL(outfile).href);
}

try {
  const tools = await bundle("src/platform/dbtTools.ts", "dbt-tools.mjs");
  const artifacts = await bundle("src/platform/dbtArtifacts.ts", "dbt-artifacts.mjs");

  // Real command lines, quoted so bash, PowerShell and cmd read them the same way.
  assert.equal(tools.buildDbtCommand({ command: "build" }), "dbt build");
  assert.equal(tools.buildDbtCommand({ command: "build", select: "tag:daily  +fct_sales", fullRefresh: true }),
    "dbt build --select tag:daily \"+fct_sales\" --full-refresh");
  assert.equal(tools.buildDbtCommand({ command: "run", select: "path:models/marts", exclude: "fct_returns" }),
    "dbt run --select path:models/marts --exclude fct_returns");
  assert.equal(tools.buildDbtCommand({ command: "docs generate", select: "dim_date" }), "dbt docs generate --select dim_date");
  assert.equal(tools.buildDbtCommand({ command: "deps", select: "x", fullRefresh: true }), "dbt deps");
  assert.equal(tools.buildDbtCommand({ command: "test", fullRefresh: true }), "dbt test");
  assert.equal(tools.buildDbtCommand({ command: "build", select: "models/*.sql" }), "dbt build --select \"models/*.sql\"");
  for (const bad of ["a;rm", "$(x)", "--vars", "a\"b", "x`y`", "a|b"]) {
    assert.throws(() => tools.buildDbtCommand({ command: "build", select: bad }), /not a dbt selector/, bad);
  }
  assert.throws(() => tools.buildDbtCommand({ command: "clean" }), /Unknown dbt command/);

  // Which command lines borrow the catalog file.
  for (const line of ["dbt build", "dbt run --select x", "  dbt test", "dbt.exe seed", "& dbt snapshot", "dbt docs generate",
    "dct render charts/sales.yml --format png", "dct serve", "dbt parse", "/venv/bin/dbt build"]) {
    assert.equal(tools.isCatalogCommand(line), true, line);
  }
  for (const line of ["dbt --version", "dbt deps", "dbt docs serve", "dct validate", "dct --version", "git status", "dbtx build", "ls dbt"]) {
    assert.equal(tools.isCatalogCommand(line), false, line);
  }

  // Python for dbt: 3.10 to 3.13; py launcher first on Windows; a configured interpreter first of all.
  assert.deepEqual(tools.parsePythonVersion("Python 3.13.1"), [3, 13]);
  assert.equal(tools.isSupportedDbtPython([3, 14]), false);
  assert.equal(tools.isSupportedDbtPython([3, 9]), false);
  assert.equal(tools.isSupportedDbtPython([3, 10]), true);
  assert.deepEqual(tools.pythonCandidates("win32")[0], { command: "py", args: ["-3.13"] });
  assert.deepEqual(tools.pythonCandidates("linux", " /opt/py/bin/python ")[0], { command: "/opt/py/bin/python", args: [] });
  assert.equal(tools.pythonCandidates("linux")[0].command, "python3.13");

  // DuckDB is pinned to the runtime's exact version, so dbt and the runtime share one storage format.
  assert.deepEqual(tools.dbtToolRequirements("1.5.5"),
    ["dbt-core>=1.10,<1.13", "dbt-duckdb>=1.9,<1.12", "dbt-charts>=0.8,<0.9", "duckdb==1.5.5"]);
  assert.deepEqual(tools.dbtToolRequirements("garbage").at(-1), "duckdb>=1.4");

  // profiles.yml: one output per profile, the workspace file, no secrets.
  assert.equal(tools.readProfileName("name: shop\nprofile: 'datapass_shop'  # local\n"), "datapass_shop");
  assert.equal(tools.readProjectName("name: shop\n"), "shop");
  const yaml = tools.profilesYaml(["b_prof", "a_prof", "b_prof", "bad name"], "C:\\ws\\it's\\.datapass\\data\\workspace.duckdb");
  assert.match(yaml, /^a_prof:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n      path: 'C:\/ws\/it''s\/\.datapass\/data\/workspace\.duckdb'\n      schema: dbt_dev\n      threads: 4$/m);
  assert.equal((yaml.match(/^b_prof:$/gm) ?? []).length, 1);
  assert.doesNotMatch(yaml, /bad name/);

  // Terminal environment: managed tools first on PATH (keeping Windows' "Path" key), profiles, no telemetry.
  const env = tools.dbtTerminalEnv({ Path: "C:\\Windows" }, "C:\\venv\\Scripts", "C:\\venv", "C:\\ws\\.datapass\\dbt", ";");
  assert.deepEqual(env, {
    Path: "C:\\venv\\Scripts;C:\\Windows", VIRTUAL_ENV: "C:\\venv", DBT_PROFILES_DIR: "C:\\ws\\.datapass\\dbt",
    DBT_SEND_ANONYMOUS_USAGE_STATS: "false", DO_NOT_TRACK: "1"
  });

  // Artifacts: the shape dbt Core 1.12 writes (manifest v12, run_results v6).
  const manifest = {
    metadata: { dbt_schema_version: "https://schemas.getdbt.com/dbt/manifest/v12.json", dbt_version: "1.12.5", invocation_id: "inv-1", project_name: "shop" },
    nodes: {
      "model.shop.stg_orders": { resource_type: "model", name: "stg_orders", schema: "silver", alias: "stg_orders", config: { materialized: "view" },
        original_file_path: "models/staging/stg_orders.sql", compiled_path: "target/compiled/shop/models/staging/stg_orders.sql",
        depends_on: { nodes: ["source.shop.shop.orders"] }, tags: ["daily"] },
      "model.shop.fct_orders": { resource_type: "model", name: "fct_orders", schema: "warehouse", alias: "fct_orders",
        config: { materialized: "incremental" }, original_file_path: "models/marts/fct_orders.sql",
        depends_on: { nodes: ["model.shop.stg_orders"] }, tags: [] },
      "model.shop.int_x": { resource_type: "model", name: "int_x", schema: "silver", config: { materialized: "ephemeral" }, depends_on: { nodes: [] }, tags: [] },
      "test.shop.unique_fct_orders_order_id.abc": { resource_type: "test", name: "unique_fct_orders_order_id", schema: "dbt_test__audit",
        config: { materialized: "test" }, depends_on: { nodes: ["model.shop.fct_orders"] }, attached_node: "model.shop.fct_orders", tags: [] },
      "analysis.shop.a": { resource_type: "analysis", name: "a" }
    },
    sources: {
      "source.shop.shop.orders": { resource_type: "source", source_name: "shop", name: "orders", schema: "source", identifier: "shop_orders",
        loaded_at_field: "loaded_at", freshness: { warn_after: { count: 12, period: "hour" }, error_after: { count: 24, period: "hour" } } }
    },
    parent_map: {}
  };
  const runResults = {
    metadata: { dbt_schema_version: "https://schemas.getdbt.com/dbt/run-results/v6.json", dbt_version: "1.12.5", invocation_id: "inv-1", generated_at: "2026-09-25T10:00:00Z" },
    elapsed_time: 3.25,
    args: { which: "build", select: ["tag:daily", "fct_orders+"], exclude: [], full_refresh: false },
    results: [
      { unique_id: "model.shop.stg_orders", status: "success", message: "OK", execution_time: 0.1, adapter_response: { rows_affected: 12 }, failures: null },
      { unique_id: "model.shop.fct_orders", status: "success", message: "OK", execution_time: 0.2, adapter_response: {}, failures: null },
      { unique_id: "test.shop.unique_fct_orders_order_id.abc", status: "fail", message: "Got 2 results, configured to fail if != 0", failures: 2 }
    ]
  };
  const view = artifacts.toDbtCoreRunView(manifest, runResults);
  assert.ok(view.truth.startsWith("dbt Core (real)"));
  assert.equal(view.command, "dbt build --select tag:daily fct_orders+");
  assert.equal(view.dbtVersion, "1.12.5");
  assert.equal(view.hasResults, true);
  assert.deepEqual(view.counts, { success: 2, fail: 1 });
  assert.deepEqual(view.warnings, []);
  assert.equal(view.nodes.length, 4, "analyses are not nodes of the DAG");
  const stg = view.nodes.find(node => node.name === "stg_orders");
  assert.equal(stg.relation, "silver.stg_orders");
  assert.equal(stg.rowsAffected, 12);
  assert.equal(view.nodes.find(node => node.name === "int_x").relation, undefined, "ephemeral models are not relations");
  assert.deepEqual(view.problems.map(node => [node.name, node.status, node.failures]), [["unique_fct_orders_order_id", "fail", 2]]);
  assert.deepEqual(view.sources, [{ uniqueId: "source.shop.shop.orders", name: "shop.orders", relation: "source.shop_orders",
    loadedAtField: "loaded_at", freshness: "warn after 12 hour, error after 24 hour" }]);
  assert.equal(artifacts.countsLine(view.counts), "2 success · 1 fail");

  const graph = artifacts.dbtCoreGraph(view);
  assert.deepEqual(graph.nodes.map(node => [node.id, node.status]), [
    ["source.shop.shop.orders", undefined], ["model.shop.stg_orders", "success"], ["model.shop.fct_orders", "success"], ["model.shop.int_x", undefined]
  ]);
  assert.deepEqual(graph.edges.map(edge => edge.id), ["source.shop.shop.orders->model.shop.stg_orders", "model.shop.stg_orders->model.shop.fct_orders"]);
  const withTests = artifacts.dbtCoreGraph(view, true);
  assert.ok(withTests.nodes.some(node => node.id.startsWith("test.") && node.status === "failed"));

  // A later dbt parse replaced the manifest: statuses still show, with a warning.
  const later = artifacts.toDbtCoreRunView({ ...manifest, metadata: { ...manifest.metadata, invocation_id: "inv-2" } }, runResults);
  assert.match(later.warnings[0], /later command/);
  // Manifest only (dbt parse): the DAG without statuses.
  const parsed = artifacts.toDbtCoreRunView(manifest, undefined);
  assert.equal(parsed.hasResults, false);
  assert.equal(parsed.command, undefined);
  assert.throws(() => artifacts.toDbtCoreRunView({}, undefined), /not a dbt manifest/);
  assert.equal(artifacts.commandFromArgs({ which: "generate" }), "dbt docs generate");
  assert.equal(artifacts.commandFromArgs({ which: "run", select: "a", full_refresh: true }), "dbt run --select a --full-refresh");

  // dbt Charts: real dct command lines; board paths stay inside the project; serve is loopback only.
  assert.equal(tools.buildDctCommand({ action: "validate" }), "dct validate");
  assert.equal(tools.buildDctCommand({ action: "validate", board: "charts/revenue.yml" }), "dct validate charts/revenue.yml");
  assert.equal(tools.buildDctCommand({ action: "render", board: "charts/revenue.yml", format: "png" }), "dct render charts/revenue.yml --format png");
  assert.equal(tools.buildDctCommand({ action: "render", board: "charts/sub/sales.yaml", format: "json" }),
    "dct render charts/sub/sales.yaml --format json --output renders/sales.json");
  assert.equal(tools.buildDctCommand({ action: "serve", port: 8765 }), "dct serve --host 127.0.0.1 --port 8765");
  for (const bad of ["../x.yml", "charts/../../x.yml", "/etc/x.yml", "charts/x.yml; rm", "charts/x.txt", "C:/x.yml"]) {
    assert.throws(() => tools.buildDctCommand({ action: "validate", board: bad }), /not a board file/, bad);
  }
  assert.throws(() => tools.buildDctCommand({ action: "serve", port: 80 }), /port/);
  assert.equal(tools.renderPath("charts/sub/sales.yml", "png"), "renders/sales.png");

  const validation = tools.toDctValidation({
    success: true, path: "charts/revenue.yml", errors: [],
    warnings: [{ code: "WARN-DBT-QUERY-COLUMNS-INDETERMINATE", message: "Query uses dbt", range: { start_line: 12 } }]
  }, "charts/revenue.yml", "t");
  assert.deepEqual(validation, { board: "charts/revenue.yml", success: true, errors: [], checkedAt: "t",
    warnings: [{ code: "WARN-DBT-QUERY-COLUMNS-INDETERMINATE", message: "Query uses dbt", line: 12 }] });
  const failed = tools.toDctValidation([{ success: false, path: "charts/a.yml", errors: [{ code: "ERR-VALIDATION-FIELD", message: "bad" }], warnings: [] },
    { success: true, path: "charts/b.yml", errors: [], warnings: [] }], "charts/a.yml", "t");
  assert.equal(failed.success, false);
  assert.equal(failed.errors[0].code, "ERR-VALIDATION-FIELD");

  // The JSON render dct writes: charts with their resolved data (as dct 0.8 prints it).
  const render = tools.toDctRender({
    id: "revenue_over_time", title: "Revenue over time",
    items: [
      { type: "chart", chart: { id: "monthly", title: "", chart_type: "bar", x: "order_month", y: "revenue" },
        data: [{ order_month: "2026-01", revenue: "695.00" }, { order_month: "2026-02", revenue: "920.00" }] },
      { type: "row", items: [{ type: "chart", chart: { id: "by_customer", chart_type: "bar" }, data: [{ customer_name: "Alice", revenue: 1, extra: { a: 1 } }] }] },
      { type: "text", text: "hello" }
    ],
    warnings: [{ code: "WARN-X", message: "m" }]
  });
  assert.equal(render.title, "Revenue over time");
  assert.deepEqual(render.charts.map(chart => [chart.id, chart.type, chart.totalRows]), [["monthly", "bar", 2], ["by_customer", "bar", 1]]);
  assert.deepEqual(render.charts[1].rows[0], { customer_name: "Alice", revenue: 1, extra: "{\"a\":1}" });
  assert.deepEqual(render.warnings, ["WARN-X"]);
  assert.throws(() => tools.toDctRender({ title: "x" }), /Not a dct JSON render/);

  console.log("dbt Lab smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
