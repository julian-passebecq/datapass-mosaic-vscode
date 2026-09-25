import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-sqlpool-"));

async function bundle(entry, name) {
  const outfile = path.join(dir, name);
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  return import(pathToFileURL(outfile).href);
}

try {
  const pool = await bundle("src/platform/sqlpoolRun.ts", "sqlpool-run.mjs");
  const factory = await bundle("src/platform/factoryRun.ts", "factory-run.mjs");

  // Sample scripts are SQL pool scripts of factory/sql/pool, and say which flavor they are written for.
  const samples = "samples/factory-lab/sql/pool";
  const flavors = { "01_star_schema.sql": "synapse", "02_partitions.sql": "synapse", "03_procedures.sql": "synapse", "04_fabric_warehouse.sql": "fabric" };
  assert.deepEqual((await readdir(samples)).sort(), Object.keys(flavors));
  for (const [file, flavor] of Object.entries(flavors)) {
    assert.deepEqual(factory.classifyFactoryPath(`sql/pool/${file}`), { role: "poolScript", name: file.slice(0, -4) });
    const text = await readFile(`${samples}/${file}`, "utf8");
    assert.equal(pool.flavorHint(text), flavor, file);
    assert.ok(text.length < pool.SQLPOOL_LIMITS.scriptChars, file);
  }
  assert.equal(pool.flavorHint("SELECT 1;\r\n-- Flavor: Fabric\r\n"), "fabric");
  assert.equal(pool.flavorHint("\n\n\n\n\n-- flavor: fabric"), undefined, "only the first five lines are read");
  assert.equal(pool.flavorHint("-- flavor: oracle"), undefined);
  assert.equal(factory.classifyFactoryPath("sql/pool/nested/x.sql"), undefined);
  assert.equal(factory.classifyFactoryPath("sql/pool/../procedures/x.sql"), undefined);
  assert.deepEqual(factory.classifyFactoryPath("sql/procedures/warehouse.p.sql"), { role: "procedure", name: "warehouse.p" });

  // Scale limits mirror the runtime's request model (1 to 1e12).
  assert.ok(pool.SQLPOOL_SCALES.every(option => pool.isValidScale(option.value)));
  assert.ok(pool.isValidScale(pool.DEFAULT_SQLPOOL_SCALE));
  for (const bad of [0, 0.5, 1e13, Number.NaN, Number.POSITIVE_INFINITY]) assert.equal(pool.isValidScale(bad), false, String(bad));

  // Runtime view -> webview view (the shape of sqlpoollab.lab.pool_view).
  const plan = {
    analyzed: true,
    steps: [
      { operation: "ShuffleMoveOperation", tables: ["dbo.dim_segment", "dbo.f"], columns: ["segment_name"], rows: 12000000, reason: "GROUP BY segment_name: ..." },
      { operation: "ReturnOperation", tables: [], columns: [], rows: 12000000, reason: "The distributions send their results ..." }
    ],
    scans: [{ table: "dbo.f", alias: "o", partitions_scanned: 1, partitions_total: 3, eliminated: true, reason: "Predicates on segment_id let the pool skip 2 of 3 partitions." }],
    notes: ["dbo.f INNER JOIN dbo.dim_segment: dbo.dim_segment is replicated, so the join runs locally."],
    data_movement: true
  };
  const view = pool.toSqlPoolView({
    status: "error", flavor: "synapse", flavor_label: "Azure Synapse dedicated SQL pool", truth: "Simulated SQL pool.",
    scale: 1000000.0, distributions: 60, rowgroup_target: 1000000, plan,
    statements: [
      { index: 1, line: 1, kind: "CTAS", status: "ok", message: "Created dbo.f with 12 rows.", target: "dbo.f", sql: "CREATE TABLE warehouse.f AS SELECT 1",
        columns: [], rows: [], truncated: false, plan: null, notes: ["n1"], children: [] },
      { index: 2, line: 3, kind: "SELECT", status: "ok", message: "2 rows.", target: null, sql: "SELECT 1", columns: [],
        rows: [{ segment_name: "Corporate", n: 3, extra: { a: 1 } }], truncated: false, plan, notes: [], children: [] },
      { index: 3, line: 5, kind: "EXEC", status: "ok", message: "EXEC dbo.p: 1 statement(s) ran.", target: "dbo.p", columns: [], rows: [],
        truncated: false, plan: null, notes: [], children: [
          { index: 1, line: 1, kind: "TRUNCATE", status: "ok", message: "Truncated.", target: "dbo.f", columns: [], rows: [], truncated: false, plan: null, notes: [], children: [] }
        ] },
      { index: 4, line: 9, kind: "CREATE TABLE", status: "error", message: "CTAS requires a DISTRIBUTION option", target: null, columns: [], rows: [],
        truncated: false, plan: null, notes: [], children: [] }
    ],
    tables: [{
      name: "dbo.f", table: "warehouse.f", label: "HASH(customer_id), CLUSTERED COLUMNSTORE INDEX, PARTITION (segment_id RANGE RIGHT, 3 partitions)",
      distribution: "HASH", hash_columns: ["customer_id"], index: "CLUSTERED COLUMNSTORE INDEX", index_columns: [],
      partition: { column: "segment_id", range: "RIGHT", boundaries: ["2", "3"], count: 3 }, cluster_by: [],
      nonclustered_indexes: { ix_f_date: ["order_date"] }, statistics: { st_f: ["customer_id", "segment_id"] },
      constraints: [{ kind: "PRIMARY KEY", name: "pk", columns: ["order_id"], enforced: false }], identity: null,
      rows: 12, scale_factor: 1000000.0, rows_at_scale: 12000000.0, created_by: "CTAS",
      distribution_stats: { shares: [0.25, 0.004167, 0], skew_pct: 98.4, max_share_pct: 25.42, min_share_pct: 0.42, empty_distributions: 1,
        distinct_keys: 7, null_share_pct: 0.0, heavy_values: [{ value: "CORPORATE_ACCOUNT_01", share_pct: 25.0 }] },
      partitions: [
        { number: 1, lower: null, upper: "2", rows: 3, rows_at_scale: 3000000.0, rows_per_distribution: 50000.0, columnstore_ok: false },
        { number: 3, lower: "3", upper: null, rows: 0, rows_at_scale: 0, rows_per_distribution: 0, columnstore_ok: null }
      ],
      columnstore_ok: null
    }]
  }, { flavor: "fabric", scale: 5, source: "factory/sql/pool/01_star_schema.sql", warnings: ["w"] });
  assert.equal(view.status, "error");
  assert.equal(view.flavor, "synapse", "the runtime's flavor wins");
  assert.equal(view.scale, 1000000);
  assert.equal(view.source, "factory/sql/pool/01_star_schema.sql");
  assert.deepEqual(view.warnings, ["w"]);
  const [ctas, select, exec, failed] = view.statements;
  assert.equal(ctas.plan, undefined);
  assert.equal(ctas.sql, "CREATE TABLE warehouse.f AS SELECT 1");
  assert.deepEqual(select.columns, ["segment_name", "n", "extra"], "columns fall back to the first row's keys");
  assert.deepEqual(select.rows[0], { segment_name: "Corporate", n: 3, extra: '{"a":1}' });
  assert.equal(select.plan.scans[0].partitionsScanned, 1);
  assert.equal(select.plan.dataMovement, true);
  assert.equal(exec.children[0].kind, "TRUNCATE");
  assert.equal(failed.status, "error");
  const [table] = view.tables;
  assert.deepEqual(table.partition, { column: "segment_id", range: "RIGHT", boundaries: ["2", "3"], count: 3 });
  assert.deepEqual(table.nonclusteredIndexes, [{ name: "ix_f_date", columns: ["order_date"] }]);
  assert.deepEqual(table.statistics, [{ name: "st_f", columns: ["customer_id", "segment_id"] }]);
  assert.deepEqual(table.constraints, [{ kind: "PRIMARY KEY", columns: ["order_id"], enforced: false }]);
  assert.equal(table.distributionStats.heavyValues[0].sharePct, 25);
  assert.equal(table.partitions[0].lower, undefined);
  assert.equal(table.partitions[1].columnstoreOk, undefined);
  assert.equal(table.columnstoreOk, undefined);

  // The results panel opens on the failing statement, else on the last one with rows or a plan.
  assert.equal(pool.defaultStatement(view.statements), failed);
  assert.equal(pool.defaultStatement(view.statements.slice(0, 3)), select);
  assert.equal(pool.defaultStatement([]), undefined);

  // Presentation helpers.
  assert.deepEqual(pool.distributionBars([0.5, 0.25, 0]), [1, 0.5, 0]);
  assert.deepEqual(pool.distributionBars([0, 0]), [0, 0]);
  assert.equal(pool.skewLevel(9.9), "even");
  assert.equal(pool.skewLevel(10), "skewed");
  assert.equal(pool.formatCount(12_000_000), "12 M");
  assert.equal(pool.formatCount(2_400_000_000), "2.4 B");
  assert.equal(pool.formatCount(83_333.3333), "83.3 K");
  assert.equal(pool.formatCount(250_000), "250 K");
  assert.equal(pool.formatCount(12), "12");
  assert.equal(pool.movementSummary(select.plan), "ShuffleMove on segment_name (dbo.dim_segment, dbo.f)");
  assert.match(pool.movementSummary({ ...select.plan, steps: [select.plan.steps[1]] }), /^No data movement/);
  assert.equal(pool.movementSummary(undefined), "");
  assert.equal(pool.scanSummary(select.plan), "dbo.f: 1 of 3 partitions scanned");
  assert.equal(pool.scanSummary(undefined), "");

  console.log("SQL pool Lab smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
