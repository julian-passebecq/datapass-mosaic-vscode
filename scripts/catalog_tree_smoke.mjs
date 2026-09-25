import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-catalog-tree-"));

try {
  const outfile = path.join(dir, "catalog-tree.mjs");
  await esbuild.build({ entryPoints: ["src/platform/catalogTree.ts"], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  const tree = await import(pathToFileURL(outfile).href);

  // The runtime response is validated: malformed tables and columns are dropped, not trusted.
  const view = tree.toCatalogSchemaView({
    engine: "duckdb",
    layers: ["source", "bronze", "silver", "gold"],
    truncated: false,
    tables: [
      { schema: "silver", name: "stg_orders", kind: "view", layer: true, row_count: 12, columns: [{ name: "order_id", type: "VARCHAR" }] },
      { schema: "source", name: "orders", kind: "table", layer: true, row_count: 1, fresh: true, columns: [{ name: "net_amount", type: "DOUBLE" }, { bad: 1 }] },
      { schema: "main_marts", name: "Fct Sales", kind: "table", layer: false, row_count: 3, columns: [] },
      { schema: "silver", name: "broken_v", kind: "view", layer: true, row_count: null, error: "Binder Error: column x", columns: [] },
      { name: "no_schema" }
    ]
  });
  assert.equal(view.tables.length, 4);
  assert.deepEqual(view.tables[1].columns, [{ name: "net_amount", type: "DOUBLE" }]);
  assert.equal(view.tables[3].rowCount, undefined);
  assert.throws(() => tree.toCatalogSchemaView({}), /no catalog schema/);

  // Layers first in catalog order (even empty ones), then other schemas; tables sorted by name.
  const groups = tree.groupBySchema(view);
  assert.deepEqual(groups.map(group => [group.schema, group.layer, group.tables.length]), [
    ["source", true, 1], ["bronze", true, 0], ["silver", true, 2], ["gold", true, 0], ["main_marts", false, 1]
  ]);
  assert.deepEqual(groups[2].tables.map(table => table.name), ["broken_v", "stg_orders"]);

  // Preview SQL quotes only what needs quoting; scratch file names are safe.
  assert.equal(tree.previewSql({ schema: "silver", name: "stg_orders" }), "SELECT * FROM silver.stg_orders LIMIT 100;\n");
  assert.equal(tree.previewSql({ schema: "main_marts", name: "Fct \"Sales\"" }), "SELECT * FROM main_marts.\"Fct \"\"Sales\"\"\" LIMIT 100;\n");
  assert.equal(tree.scratchFileName({ schema: "main_marts", name: "Fct Sales/../x" }), "main_marts.Fct_Sales____x.sql");
  const scratch = tree.scratchContent(view.tables[0]);
  assert.match(scratch, /^-- View silver\.stg_orders · 12 rows/);
  assert.match(scratch, /--   order_id VARCHAR/);
  assert.ok(scratch.endsWith("SELECT * FROM silver.stg_orders LIMIT 100;\n"));

  assert.equal(tree.tableDescription(view.tables[1]), "1 row");
  assert.equal(tree.tableDescription(view.tables[0]), "12 rows · view");
  assert.equal(tree.tableDescription(view.tables[3]), "row count unavailable · view");
  assert.equal(tree.formatRowCount(12345), "12,345 rows");

  // The view is contributed to the Datapass container, with its commands hidden from the palette.
  const manifest = JSON.parse(await readFile("package.json", "utf8"));
  assert.ok(manifest.contributes.views.datapass.some(item => item.id === "datapass.catalog"));
  for (const command of ["datapass.catalog.openScratch", "datapass.catalog.previewTable", "datapass.catalog.copyName"]) {
    assert.ok(manifest.contributes.commands.some(item => item.command === command), command);
    assert.ok(manifest.contributes.menus.commandPalette.some(item => item.command === command && item.when === "false"), command);
  }

  console.log("Catalog tree smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
