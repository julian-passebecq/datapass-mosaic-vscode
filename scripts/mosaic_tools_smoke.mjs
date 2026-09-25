import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

// Mosaic data tools (V1-6): accepted import files and the SQL query history.
const dir = await mkdtemp(path.join(tmpdir(), "datapass-mosaic-tools-"));
const outfile = path.join(dir, "mosaic-tools.mjs");

try {
  await esbuild.build({ entryPoints: ["src/platform/mosaicTools.ts"], bundle: true, platform: "node", format: "esm",
    target: "node20", outfile, logLevel: "silent" });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  assert.equal(mod.importFormat("Orders.CSV"), "csv");
  assert.equal(mod.importFormat("C:/data/orders.parquet"), "parquet");
  for (const name of ["events.json", "events.jsonl", "events.ndjson"]) assert.equal(mod.importFormat(name), "json");
  assert.equal(mod.importFormat("orders.xlsx"), undefined);
  assert.equal(mod.importFormat("parquet"), undefined, "a name without an extension is not a format");
  assert.deepEqual(mod.IMPORT_FILTERS["Data files"], ["csv", "parquet", "json", "jsonl", "ndjson"]);

  const entry = (id, sql, kind = "run", status = "success") => ({ id, at: `2026-09-25T10:00:0${id}Z`, kind, sql, status, elapsedMs: 1 });
  let history = mod.addQueryHistory(undefined, entry("1", "SELECT 1"));
  history = mod.addQueryHistory(history, entry("2", "SELECT 2"));
  history = mod.addQueryHistory(history, entry("3", "  SELECT 1  "));
  assert.deepEqual(history.map(item => item.id), ["3", "2"], "running the same SQL again moves it to the top");
  history = mod.addQueryHistory(history, entry("4", "SELECT 2", "explain"));
  assert.deepEqual(history.map(item => item.id), ["4", "3", "2"], "a plan and a run of the same SQL are two entries");
  let many = [];
  for (let i = 0; i < 40; i += 1) many = mod.addQueryHistory(many, entry(String(i), `SELECT ${i}`));
  assert.equal(many.length, mod.QUERY_HISTORY_MAX);
  assert.equal(many[0].sql, "SELECT 39");
  const long = mod.addQueryHistory([], entry("x", "S".repeat(mod.QUERY_HISTORY_SQL_MAX + 50)));
  assert.equal(long[0].sql.length, mod.QUERY_HISTORY_SQL_MAX);

  const restored = mod.restoreQueryHistory([
    entry("1", "SELECT 1"),
    { id: "2", at: "t", kind: "delete", sql: "x", status: "success" },
    { id: "3", at: "t", kind: "run", sql: 5, status: "success" },
    "junk",
    { ...entry("4", "SELECT 4", "run", "error"), error: "boom", file: "notebooks/scratch.sql", rows: "3" }
  ]);
  assert.deepEqual(restored.map(item => item.id), ["1", "4"]);
  assert.equal(restored[1].error, "boom");
  assert.equal(restored[1].rows, undefined, "a malformed row count is dropped");
  assert.deepEqual(mod.restoreQueryHistory({}), []);

  assert.equal(mod.querySummary("-- revenue by day\n\nSELECT order_date, SUM(amount)\nFROM orders"), "SELECT order_date, SUM(amount)");
  assert.equal(mod.querySummary("SELECT " + "x, ".repeat(60), 20).length, 20);

  // A dialect file's run keeps its dialect, so a rerun translates it again; the same SQL in DuckDB is another entry.
  let dialects = mod.addQueryHistory(undefined, { ...entry("1", "SELECT TOP 1 1"), dialect: "tsql" });
  dialects = mod.addQueryHistory(dialects, entry("2", "SELECT TOP 1 1"));
  assert.deepEqual(dialects.map(item => item.id), ["2", "1"]);
  const withDialects = mod.restoreQueryHistory([...dialects, { ...entry("3", "SELECT 3"), dialect: "oracle" }]);
  assert.equal(withDialects.find(item => item.id === "1").dialect, "tsql");
  assert.ok(!("dialect" in withDialects.find(item => item.id === "2")) && !("dialect" in withDialects.find(item => item.id === "3")));

  console.log("Mosaic tools smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
