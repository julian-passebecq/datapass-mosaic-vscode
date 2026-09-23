import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-scaffold-"));
const outfile = path.join(dir, "retail-demo.mjs");
const dbtOutfile = path.join(dir, "dbt-version.mjs");

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
    entryPoints: ["src/platform/dbtVersion.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile: dbtOutfile,
    logLevel: "silent"
  });

  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);
  const dbtMod = await import(pathToFileURL(dbtOutfile).href + `?v=${Date.now()}`);

  const customDataset = "assets/raw/retail_orders.csv";
  const sql = mod.retailSqlStarter(customDataset);
  const python = mod.retailPythonStarter(customDataset);

  assert.match(sql, /read_csv_auto\('assets\/raw\/retail_orders\.csv'\)/);
  assert.match(python, /pl\.read_csv\("assets\/raw\/retail_orders\.csv"\)/);
  assert.ok(!sql.includes("datasets/retail_orders.csv"));
  assert.ok(!python.includes("datasets/retail_orders.csv"));

  const escapedSql = mod.retailSqlStarter("data/o'brien.csv");
  assert.match(escapedSql, /read_csv_auto\('data\/o''brien\.csv'\)/);

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

  const parsedDbt = dbtMod.parseDbtVersionOutput([
    "Core:",
    "  - installed: 1.10.2",
    "  - latest:    1.10.2 - Up to date!",
    "Plugins:",
    "  - duckdb: 1.9.6 - Up to date!"
  ].join("\n"));
  assert.equal(parsedDbt.coreVersion, "1.10.2");
  assert.equal(parsedDbt.duckdbAdapterVersion, "1.9.6");

  const coreOnly = dbtMod.parseDbtVersionOutput("dbt Core v1.10.2");
  assert.equal(coreOnly.coreVersion, "1.10.2");
  assert.equal(coreOnly.duckdbAdapterVersion, undefined);

  console.log("Retail scaffold and dbt detection smoke tests passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
