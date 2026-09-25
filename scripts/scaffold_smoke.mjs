import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-scaffold-"));
const outfile = path.join(dir, "retail-demo.mjs");
const readmeOutfile = path.join(dir, "exercise-readme.mjs");

try {
  await esbuild.build({
    entryPoints: ["src/scaffold/retailDemo.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });

  await esbuild.build({
    entryPoints: ["src/scaffold/exerciseReadme.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile: readmeOutfile,
    logLevel: "silent"
  });

  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);
  const readmeMod = await import(pathToFileURL(readmeOutfile).href + `?v=${Date.now()}`);

  const customDataset = "assets/raw/retail_orders.csv";
  const sql = mod.retailSqlStarter(customDataset);
  const python = mod.retailPythonStarter(customDataset);

  // SQL builds on the catalog: file table functions are blocked in Mosaic SQL.
  assert.match(sql, /loads assets\/raw\/retail_orders\.csv into bronze\.orders/);
  assert.match(sql, /from bronze\.orders/);
  assert.ok(!/read_csv|read_parquet|read_json/i.test(sql), "SQL starter must not use blocked file functions");
  assert.match(python, /pl\.read_csv\("assets\/raw\/retail_orders\.csv"\)/);
  assert.ok(!sql.includes("datasets/retail_orders.csv"));
  assert.ok(!python.includes("datasets/retail_orders.csv"));

  // A path can only appear inside a comment line; newlines cannot inject SQL.
  const injected = mod.retailSqlStarter("data/x.csv\ndrop table bronze.orders;");
  assert.ok(!injected.split("\n").some(line => line.startsWith("drop table")));

  const readme = mod.retailDemoReadme({
    dataset: "assets/raw/retail_orders.csv",
    sqlNotebook: "lab/notebooks/retail_medallion.sql",
    pythonNotebook: "lab/notebooks/retail_quality.py",
    pipeline: "orchestration/main.pipeline.py",
    airflow: "scheduler/main.dag.json",
    dbtProject: "analytics/retail-dbt"
  });
  for (const expected of [
    "assets/raw/retail_orders.csv",
    "lab/notebooks/retail_medallion.sql",
    "lab/notebooks/retail_quality.py",
    "orchestration/main.pipeline.py",
    "scheduler/main.dag.json",
    "analytics/retail-dbt"
  ]) {
    assert.ok(readme.includes(expected), `README missing configured path: ${expected}`);
  }

  const rows = mod.retailOrdersCsv().trim().split("\n");
  assert.equal(rows.length, 11);
  assert.equal(rows[0], "order_id,customer_id,order_date,amount,status");
  assert.ok(rows.some(row => row.includes("refund")));
  assert.ok(rows.some(row => row.includes("cancelled")));

  const brief = readmeMod.exerciseReadme({
    key: "sql-lab-v1/x/sql", packId: "sql-lab-v1", packTitle: "SQL lab", id: "x", version: "1",
    title: "Keep customers", difficulty: "easy", language: "sql", prompt: "Return every customer.",
    starterSource: "SELECT 1", truth: "real", topics: ["left-join"],
    sections: [{ title: "Common pitfall", body: "WHERE removes NULL rows." }],
    hints: ["Put the preserved table on the left."],
    dataContext: [
      { name: "customers", columns: { customer_id: "INTEGER", note: "VARCHAR" },
        sampleRows: [{ customer_id: 1, note: "a|b" }, { customer_id: 2, note: null }] },
      { name: "orders", columns: { order_id: "INTEGER" }, sampleRows: [] }
    ]
  });
  assert.match(brief, /## Input table `customers`/);
  assert.match(brief, /\| customer_id \| note \|/);
  assert.ok(brief.includes("| 1 | a\\|b |"), "pipes inside cells are escaped");
  assert.match(brief, /\| 2 \| _NULL_ \|/, "NULL is shown explicitly");
  assert.match(brief, /_Empty in the public example\._/);
  assert.match(brief, /<details><summary>Hint 1<\/summary>/);
  assert.match(brief, /## Common pitfall/);
  assert.match(brief, /hidden and edge-case fixtures that are not shown/);
  assert.ok(!brief.includes("Spark plan checks"), "no plan section without spark_plan");

  const sparkBrief = readmeMod.exerciseReadme({
    key: "spark-lab-v1/b/sparklab", packId: "spark-lab-v1", packTitle: "Spark lab", id: "b", version: "1",
    title: "Broadcast", difficulty: "medium", language: "sparklab", prompt: "Revenue per region.",
    starterSource: "x", truth: "semantic-emulation", topics: ["joins"], sections: [], hints: [], dataContext: [],
    sparkPlan: {
      profile: "generic_8x8", aqe: true,
      scale: [
        { table: "sales", rows: 600000000, bytes: 72 * 1024 ** 3, partitions: 576, catalogStatistics: true },
        { table: "stores", rows: 40000, bytes: 48 * 1024 ** 2, partitions: 1, catalogStatistics: false }
      ],
      checks: [{ id: "plan-broadcast-join", description: "The join is a broadcast hash join." }]
    }
  });
  assert.match(sparkBrief, /## Spark plan checks \(simulated\)/);
  assert.match(sparkBrief, /`generic_8x8` profile, AQE on/);
  assert.ok(sparkBrief.includes("| `sales` | 600,000,000 | 72 GB | 576 | available |"), sparkBrief);
  assert.ok(sparkBrief.includes("| `stores` | 40,000 | 48 MB | 1 | unavailable |"));
  assert.match(sparkBrief, /- \*\*plan-broadcast-join\*\*: The join is a broadcast hash join\./);
  assert.match(sparkBrief, /Both also grade the simulated Spark plan checks/);

  const airflowBrief = readmeMod.exerciseReadme({
    key: "airflow-lab-v1/a/airflow", packId: "airflow-lab-v1", packTitle: "Airflow lab", id: "a", version: "1",
    title: "Retries", difficulty: "easy", language: "airflow", prompt: "Retry the API call.",
    starterSource: "x", truth: "simulated", topics: ["retries"],
    sections: [{ title: "Simulator", body: "Parsed, never executed." }], hints: [], dataContext: []
  });
  assert.match(airflowBrief, /- Truth: simulated/);
  assert.match(airflowBrief, /\*\*Run visible\*\* simulates the public scenario/);
  assert.match(airflowBrief, /The DAG file is parsed, never executed\./);

  console.log("Retail scaffold and exercise brief smoke tests passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
