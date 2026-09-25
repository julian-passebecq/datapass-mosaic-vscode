import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

// Mosaic's SQL dialect "kernel": the first-line `-- dialect:` header, the status bar text, and the contract with the
// runtime (runtime/sqldialects): same dialect ids, same labels.
const dir = await mkdtemp(path.join(tmpdir(), "datapass-sql-dialect-"));
const outfile = path.join(dir, "sql-dialect.mjs");

try {
  await esbuild.build({ entryPoints: ["src/platform/sqlDialect.ts"], bundle: true, platform: "node", format: "esm",
    target: "node20", outfile, logLevel: "silent" });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  // Reading the header.
  assert.deepEqual(mod.readDialectHeader("SELECT 1"), { dialect: "duckdb" });
  assert.deepEqual(mod.readDialectHeader("-- dialect: tsql\nSELECT TOP 1 * FROM t"), { dialect: "tsql", line: 0 });
  assert.deepEqual(mod.readDialectHeader("﻿\r\n\r\n  --Dialect:BigQuery  \r\nSELECT 1"), { dialect: "bigquery", line: 2 });
  assert.deepEqual(mod.readDialectHeader("-- dialect: PostgreSQL\n"), { dialect: "postgres", line: 0 }, "aliases");
  assert.deepEqual(mod.readDialectHeader("-- dialect: databricks\n"), { dialect: "spark", line: 0 });
  assert.deepEqual(mod.readDialectHeader("-- dialect: mysql\nSELECT 1"), { dialect: "duckdb", line: 0, unknown: "mysql" });
  assert.deepEqual(mod.readDialectHeader("SELECT 1;\n-- dialect: tsql"), { dialect: "duckdb" }, "only the first line counts");
  assert.deepEqual(mod.readDialectHeader("-- Monthly revenue\n-- dialect: tsql"), { dialect: "duckdb" });

  // What a run sends.
  assert.deepEqual(mod.runDialect("SELECT 1"), {});
  assert.deepEqual(mod.runDialect("-- dialect: snowflake\nSELECT 1"), { dialect: "snowflake" });
  assert.deepEqual(mod.runDialect("-- dialect: duckdb\nSELECT 1"), {}, "an explicit DuckDB header runs as written");
  assert.match(mod.runDialect("-- dialect: oracle\nSELECT 1").error, /Unknown SQL dialect 'oracle' on line 1/);

  // Writing the header: insert, replace, remove, nothing to do.
  assert.deepEqual(mod.dialectHeaderEdit("SELECT 1", "tsql"), { text: "-- dialect: tsql" });
  assert.deepEqual(mod.dialectHeaderEdit("-- dialect: tsql\nSELECT 1", "postgres"), { line: 0, text: "-- dialect: postgres" });
  assert.deepEqual(mod.dialectHeaderEdit("\n-- dialect: tsql\nSELECT 1", "duckdb"), { line: 1, text: undefined });
  assert.equal(mod.dialectHeaderEdit("-- dialect: t-sql\nSELECT 1", "tsql"), undefined);
  assert.equal(mod.dialectHeaderEdit("SELECT 1", "duckdb"), undefined);
  assert.deepEqual(mod.dialectHeaderEdit("-- dialect: mysql\nSELECT 1", "bigquery"), { line: 0, text: "-- dialect: bigquery" });

  // Status bar.
  assert.equal(mod.statusText("duckdb"), "SQL: DuckDB ▾");
  assert.equal(mod.statusText("spark"), "SQL: Spark SQL ▾");

  // The runtime accepts exactly these dialects, and labels them the same way.
  const main = await readFile("runtime/datapass_runtime/main.py", "utf8");
  const literal = /SqlDialect = Literal\[([^\]]+)\]/.exec(main)[1];
  const runtimeIds = [...literal.matchAll(/"([a-z]+)"/g)].map(match => match[1]);
  assert.deepEqual(runtimeIds, mod.SQL_DIALECTS.filter(item => item.id !== "duckdb").map(item => item.id));
  const labels = {};
  for (const file of await readdir("runtime/sqldialects")) {
    if (!file.endsWith(".py")) continue;
    const source = await readFile(path.join("runtime/sqldialects", file), "utf8");
    const id = /^    id = '([a-z]+)'$/m.exec(source)?.[1];
    if (!id) continue;
    const language = /^    language = '([^']+)'$/m.exec(source)[1];
    const engine = /^    engine = '([^']+)'$/m.exec(source)[1];
    labels[id] = `${language} dialect translated to DuckDB, not ${engine}`;
  }
  for (const item of mod.SQL_DIALECTS.filter(entry => entry.id !== "duckdb")) {
    assert.equal(item.label, labels[item.id], `label of ${item.id}`);
  }

  // The status bar command and the activation on SQL files.
  const pkg = JSON.parse(await readFile("package.json", "utf8"));
  assert.ok(pkg.activationEvents.includes("onLanguage:sql"));
  assert.ok(pkg.contributes.commands.some(command => command.command === "datapass.sql.pickDialect"));
  console.log(`SQL dialect smoke passed: ${runtimeIds.length} translated dialects match the runtime.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
