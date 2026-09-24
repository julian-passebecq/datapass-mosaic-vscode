import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-csv-import-"));
const outfile = path.join(dir, "csv-import.mjs");

try {
  await esbuild.build({
    entryPoints: ["src/platform/csvImport.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });

  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);
  const { suggestBronzeAsset: suggest, validateBronzeAsset: validate, decodeCsvBytes: decode } = mod;

  assert.equal(suggest("Retail Orders.csv", []), "bronze.retail_orders");
  assert.equal(suggest("C:\\data\\2026-sales (final).csv", []), "bronze.csv_2026_sales_final");
  assert.equal(suggest("/home/me/données.csv", []), "bronze.donn_es");
  assert.equal(suggest("___.csv", []), "bronze.csv");
  assert.equal(suggest("orders.csv", ["bronze.orders", "BRONZE.orders_2"]), "bronze.orders_3");
  assert.ok(suggest(`${"x".repeat(200)}.csv`, []).length <= "bronze.".length + 63);
  for (const name of ["Retail Orders.csv", "2026.csv", "-.csv", "a b c.CSV", `${"y".repeat(90)}.csv`]) {
    assert.equal(validate(suggest(name, []), []), undefined, name);
  }

  assert.equal(validate("bronze.orders", []), undefined);
  assert.equal(validate("  bronze.orders  ", []), undefined);
  assert.match(validate("bronze.orders", ["bronze.ORDERS"]), /already exists/);
  for (const bad of ["orders", "silver.orders", "source.orders", "bronze.1orders", "bronze.or-ders", "bronze.x; DROP TABLE y", `bronze.${"z".repeat(64)}`]) {
    assert.ok(validate(bad, []), bad);
  }

  assert.equal(decode(new TextEncoder().encode("a,b\n1,2\n")), "a,b\n1,2\n");
  assert.throws(() => decode(new Uint8Array([0x61, 0x0a, 0xe9, 0x0a])), /not valid UTF-8/);
  assert.throws(() => decode(new TextEncoder().encode("\uFEFF \n")), /empty/);
  assert.throws(() => decode(new Uint8Array(mod.CSV_IMPORT_MAX_BYTES + 1).fill(0x61)), /1 MB/);

  console.log("CSV import contract smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
