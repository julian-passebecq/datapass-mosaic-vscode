import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-bi-"));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  return import(pathToFileURL(outfile).href);
}

try {
  const bi = await bundle("src/platform/biRun.ts", "bi-run.mjs");

  // Sample files: scripts run in name order, sources first; the model parses and names the sample's tables.
  const scripts = (await readdir("samples/bi-lab/warehouse")).map(name => ({ name }));
  assert.deepEqual(bi.orderScripts([...scripts].reverse()).map(s => s.name), [
    "00_sources.sql", "01_dim_date.sql", "02_dim_customer.sql", "03_dim_product.sql", "04_dim_order_profile.sql",
    "05_fct_sales.sql", "06_fct_returns.sql"]);
  for (const { name } of scripts) {
    const text = await readFile(`samples/bi-lab/warehouse/${name}`, "utf8");
    assert.ok(text.length < bi.BI_LIMITS.scriptChars, name);
  }
  const model = JSON.parse(await readFile("samples/bi-lab/model.json", "utf8"));
  assert.equal(model.tables.length, 6);
  assert.equal(model.relationships.filter(r => r.active === false).length, 1);
  assert.equal(bi.BI_MODEL_FILE, "bi/model.json");

  // Only paths inside bi/ are opened for the webview.
  assert.ok(bi.isBiPath("bi/warehouse/05_fct_sales.sql"));
  assert.ok(bi.isBiPath("bi\\model.json"));
  for (const bad of ["bi", "factory/x.sql", "bi/../secret.sql", "bi/./x.sql", "bi/C:/x.sql", "../bi/x.sql"]) {
    assert.equal(bi.isBiPath(bad), false, bad);
  }

  // A runtime response (shape of POST /api/local/bi/lab) mapped for the webview.
  const raw = {
    status: "error", ran: true, stopped: { path: "bi/warehouse/05_fct_sales.sql", line: 8, message: "Binder Error: x" },
    statements: [
      { path: "bi/warehouse/00_sources.sql", index: 1, line: 7, kind: "CREATE TABLE", target: "source.crm_customers",
        status: "success", message: "", columns: ["Count"], rows: [], affected: 6 },
      { path: "bi/warehouse/05_fct_sales.sql", index: 1, line: 8, kind: "CREATE TABLE", target: "gold.fct_sales",
        status: "error", message: "Binder Error: x", columns: [], rows: [] }
    ],
    tables: [{ name: "gold.fct_sales", layer: "gold", rows: 16, columns: [{ name: "net_amount", type: "DECIMAL(18,2)" }] }],
    lineage: {
      tables: [
        { name: "source.shop_order_lines", kind: "source", columns: ["quantity", "unit_price", "discount_amount"], statements: [], inputs: [] },
        { name: "gold.fct_sales", kind: "table", columns: ["net_amount", "customer_key"], inputs: ["source.shop_order_lines", "gold.dim_customer"],
          statements: [{ path: "bi/warehouse/05_fct_sales.sql", line: 8, kind: "CREATE TABLE" }] }
      ],
      columns: [
        { table: "gold.fct_sales", column: "net_amount", transform: "expression", expression: "l.quantity * l.unit_price - l.discount_amount",
          sources: ["source.shop_order_lines.discount_amount", "source.shop_order_lines.quantity", "source.shop_order_lines.unit_price"],
          origins: ["source.shop_order_lines.discount_amount", "source.shop_order_lines.quantity", "source.shop_order_lines.unit_price"] },
        { table: "gold.fct_sales", column: "customer_key", transform: "expression", expression: "COALESCE(dc.customer_key, -1)",
          sources: ["gold.dim_customer.customer_key"], origins: ["source.crm_customer_history.customer_id"] }
      ],
      influence: [
        { table: "gold.fct_sales", source: "source.shop_orders.order_date", role: "join", origins: [] },
        { table: "gold.fct_sales", source: "source.shop_orders.order_date", role: "join", origins: [] },
        { table: "gold.fct_sales", source: "gold.dim_customer.valid_from", role: "join", origins: [] }
      ],
      impact: { "source.shop_order_lines.quantity": [{ table: "gold.fct_sales", column: "net_amount", effect: "value" }],
                "source.shop_orders.order_date": [{ table: "gold.fct_sales", column: "*", effect: "rows" }] },
      issues: [], truth: "static analysis of the SQL text (sqlglot, DuckDB dialect); nothing executed"
    },
    model: {
      name: "retail_star", description: "",
      tables: [
        { name: "gold.fct_sales", role: "fact", grain: ["order_id", "line_number"], business_key: [] },
        { name: "gold.dim_date", role: "dimension", key: "date_key", unknown_member: -1, business_key: [], grain: [] },
        { name: "gold.dim_customer", role: "dimension", key: "customer_key", business_key: ["customer_id"], grain: [],
          unknown_member: -1, scd: { type: 2 } }
      ],
      relationships: [
        { from: "gold.fct_sales.order_date_key", to: "gold.dim_date.date_key", cardinality: "many-to-one", cross_filter: "single", active: true },
        { from: "gold.fct_sales.ship_date_key", to: "gold.dim_date.date_key", cardinality: "many-to-one", cross_filter: "single", active: false },
        { from: "gold.fct_sales.customer_key", to: "gold.dim_customer.customer_key", cardinality: "many-to-one", cross_filter: "both", active: true }
      ],
      checks: [
        { check: "grain_unique", subject: "gold.fct_sales", status: "pass", detail: "" },
        { check: "scd2_no_gap", subject: "gold.dim_customer", status: "fail", detail: "1 version(s) end on a different day" },
        { check: "cross_filter", subject: "gold.fct_sales.customer_key -> gold.dim_customer.customer_key", status: "warn", detail: "" }
      ],
      profiles: [
        { relationship: "gold.fct_sales.order_date_key -> gold.dim_date.date_key", observed: "many-to-one", from_rows: 16, orphans: 0, null_keys: 0 }
      ]
    },
    truth: { sql: "real: the scripts run on the local DuckDB catalog", model: "real queries" }
  };
  const view = bi.toBiLabView(raw, { mode: "build", source: "bi/warehouse", warnings: ["w"] });
  assert.equal(view.status, "error");
  assert.deepEqual(view.stopped, { path: "bi/warehouse/05_fct_sales.sql", line: 8, message: "Binder Error: x" });
  assert.deepEqual(view.statements.map(s => [s.status, s.affected]), [["success", 6], ["error", undefined]]);
  assert.equal(view.tables[0].columns[0].type, "DECIMAL(18,2)");
  assert.equal(view.model.tables[2].scdType, 2);
  assert.equal(view.model.tables[1].unknownMember, "-1");
  assert.deepEqual(view.model.relationships.map(r => [r.active, r.crossFilter, r.observed ?? null, r.fromRows ?? null]),
    [[true, "single", "many-to-one", 16], [false, "single", null, null], [true, "both", null, null]]);
  assert.equal(view.truth.sql, "real: the scripts run on the local DuckDB catalog");
  assert.equal(bi.toBiLabView({ ...raw, model: { error: "tables.0.name: bad" } }, { mode: "build", source: "x" }).modelError, "tables.0.name: bad");
  assert.equal(bi.toBiLabView({}, { mode: "analyze", source: "x", modelError: "not JSON" }).modelError, "not JSON");
  assert.deepEqual(bi.checkCounts(view.model.checks), { pass: 1, fail: 1, warn: 1 });

  // The star: the fact in the middle, the dimensions around it, *:1 labels, a dashed inactive role-playing date.
  const star = bi.starGraph(view.model);
  assert.deepEqual(star.nodes.map(n => [n.id, n.truth, n.status]), [
    ["gold.fct_sales", "fact", "warning"], ["gold.dim_date", "dimension", undefined], ["gold.dim_customer", "dimension", "failed"]]);
  assert.ok(star.nodes.every(n => n.position && Number.isFinite(n.position.x) && Number.isFinite(n.position.y)));
  assert.deepEqual(star.edges.map(e => [e.source, e.target, e.label, e.className ?? null]), [
    ["gold.fct_sales", "gold.dim_date", "*:1 order_date_key", null],
    ["gold.fct_sales", "gold.dim_date", "*:1 ship_date_key", "bi-edge-inactive"],
    ["gold.fct_sales", "gold.dim_customer", "*:1 customer_key ⇄", "bi-edge-both"]]);
  assert.deepEqual(star.edges.map(e => [e.sourceSide, e.targetSide]), [["top", "bottom"], ["top", "bottom"], ["bottom", "top"]]);
  assert.ok(star.nodes.every(n => n.allSides));
  assert.deepEqual(bi.facing({ x: 0, y: 0 }, { x: -480, y: 90 }), ["left", "right"]);
  assert.deepEqual(bi.facing(undefined, { x: 1, y: 1 }), ["right", "left"]);
  assert.equal(bi.tableStatus("gold.dim_date", view.model.checks), undefined);

  // Lineage graphs: tables by their inputs; one column back to its sources; row influence without repeats.
  const tables = bi.tableLineageGraph(view.lineage, new Map([["gold.fct_sales", 16]]));
  assert.deepEqual(tables.edges.map(e => e.id), ["source.shop_order_lines->gold.fct_sales", "gold.dim_customer->gold.fct_sales"]);
  assert.match(tables.nodes[1].detail, /16 rows/);
  const column = bi.columnLineageGraph(view.lineage, "gold.fct_sales", "net_amount");
  assert.equal(column.nodes.length, 4);
  assert.equal(column.nodes[0].status, "running");
  assert.equal(column.edges.length, 3);
  assert.ok(column.edges.every(e => e.target === "gold.fct_sales.net_amount"));
  assert.deepEqual(column.nodes.map(n => n.position.x), [420, 0, 0, 0], "the column on the right, its sources on the left");
  assert.deepEqual(bi.influenceOf(view.lineage, "gold.fct_sales"), [
    { source: "source.shop_orders.order_date", role: "join" }, { source: "gold.dim_customer.valid_from", role: "join" }]);
  assert.deepEqual(view.lineage.impact["source.shop_orders.order_date"], [{ table: "gold.fct_sales", column: "*", effect: "rows" }]);
  // dbt tab: which files make the project, bounded selectors, the runtime response and the DAG.
  for (const path of ["dbt_project.yml", "models/marts/fct_sales.sql", "models/staging/_sources.yml", "seeds/raw.csv", "snapshots/s.sql"]) {
    assert.ok(bi.isDbtProjectFile(path), path);
  }
  for (const path of ["README.md", "profiles.yml", "packages.yml", "models/../x.sql", "target/run.sql.bak"]) {
    assert.equal(bi.isDbtProjectFile(path), false, path);
  }
  assert.deepEqual(bi.parseSelect(" +fct_sales  tag:daily "), { selectors: ["+fct_sales", "tag:daily"] });
  assert.ok(bi.parseSelect("--vars x").error);
  assert.ok(bi.parseSelect("a; rm -rf").error);
  const dbtRaw = {
    status: "error", project: { name: "datapass_bi", issues: [{ path: "dbt_project.yml", message: "on-run-start hooks are not run" }] },
    nodes: [
      { unique_id: "model.p.stg", name: "stg", resource_type: "model", materialized: "view", relation: "silver.stg", path: "models/stg.sql",
        depends_on: [], sources: ["shop.orders"], tags: [], description: "", problem: null },
      { unique_id: "model.p.fct", name: "fct", resource_type: "model", materialized: "table", relation: "gold.fct", path: "models/fct.sql",
        depends_on: ["model.p.stg"], sources: [], tags: ["daily"], description: "Facts", problem: null },
      { unique_id: "test.p.not_null_stg_id", name: "not_null_stg_id", resource_type: "test", materialized: "test", relation: null,
        path: "models/schema.yml", depends_on: ["model.p.stg"], sources: [], tags: [], description: "", problem: null }
    ],
    sources: [{ name: "shop.orders", relation: "source.orders", description: "" }],
    run: { status: "error", counts: { success: 1, fail: 1, skipped: 1, pass: 0 }, now: "2026-03-01 06:00:00", results: [
      { unique_id: "model.p.stg", name: "stg", resource_type: "model", status: "success", message: "OK", materialized: "view",
        relation: "silver.stg", rows_affected: null, failures: null, compiled: "select 1", failing_rows: [], path: "models/stg.sql" },
      { unique_id: "test.p.not_null_stg_id", name: "not_null_stg_id", resource_type: "test", status: "fail", message: "Got 1 result",
        materialized: "test", relation: null, rows_affected: null, failures: 1, compiled: "select id", failing_rows: [{ id: null }], path: "models/schema.yml" },
      { unique_id: "model.p.fct", name: "fct", resource_type: "model", status: "skipped", message: "SKIP", materialized: "table",
        relation: "gold.fct", rows_affected: null, failures: null, compiled: "", failing_rows: [], path: "models/fct.sql" }
    ] },
    lineage: { tables: [], columns: [], influence: [], impact: {}, issues: [], truth: "static" },
    truth: "Datapass dbt emulation ... not dbt Core"
  };
  const dbtView = bi.toBiDbtView(dbtRaw, { command: "build", select: "+fct" });
  assert.equal(dbtView.status, "error");
  assert.equal(dbtView.projectName, "datapass_bi");
  assert.deepEqual(dbtView.results.map(r => [r.name, r.status, r.failures ?? null]), [["stg", "success", null], ["not_null_stg_id", "fail", 1], ["fct", "skipped", null]]);
  assert.deepEqual(dbtView.results[1].failingRows, [{ id: null }]);
  assert.deepEqual(dbtView.counts, { success: 1, fail: 1, skipped: 1, pass: 0 });
  assert.match(dbtView.truth, /not dbt Core/);
  const dag = bi.dbtGraph(dbtView);
  assert.deepEqual(dag.nodes.map(n => [n.id, n.status ?? null]), [["source:shop.orders", null], ["model.p.stg", "success"], ["model.p.fct", "skipped"]]);
  assert.deepEqual(dag.edges.map(e => e.id), ["source:shop.orders->model.p.stg", "model.p.stg->model.p.fct"]);
  const withTests = bi.dbtGraph(dbtView, true);
  assert.equal(withTests.nodes.find(n => n.id === "test.p.not_null_stg_id").status, "failed");
  assert.equal(bi.toBiDbtView({ status: "invalid", error: "dbt_project.yml is missing" }, { command: "build", select: "" }).error, "dbt_project.yml is missing");

  // The sample dbt project is a project: every file the host sends is one dbt reads.
  const dbtSample = "samples/bi-lab/dbt";
  async function walk(folder, prefix = "") {
    const found = [];
    for (const entry of await readdir(`${folder}/${prefix}`, { withFileTypes: true })) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) found.push(...await walk(folder, relative));
      else found.push(relative);
    }
    return found;
  }
  const sampleFiles = await walk(dbtSample);
  assert.ok(sampleFiles.includes("dbt_project.yml") && sampleFiles.length >= 15, sampleFiles.join(","));
  const projectFiles = sampleFiles.filter(file => file !== "README.md");
  assert.ok(projectFiles.every(file => bi.isDbtProjectFile(file)), projectFiles.filter(file => !bi.isDbtProjectFile(file)).join(","));
  console.log("BI Lab smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
