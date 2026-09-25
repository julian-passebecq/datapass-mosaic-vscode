/**
 * Catalog tree view: pure mapping of the runtime's `/api/local/catalog/schema` response
 * (no vscode import, so scripts/catalog_tree_smoke.mjs can test it in Node).
 */

export interface CatalogColumnView {
  name: string;
  type: string;
}

export interface CatalogTableView {
  schema: string;
  name: string;
  kind: "table" | "view";
  /** true for the catalog layers (source, bronze, silver, ...); false for other schemas dbt Core may create. */
  layer: boolean;
  rowCount?: number;
  fresh?: boolean;
  error?: string;
  columns: CatalogColumnView[];
}

export interface CatalogSchemaView {
  engine: string;
  layers: string[];
  tables: CatalogTableView[];
  truncated: boolean;
}

export interface CatalogSchemaGroup {
  schema: string;
  layer: boolean;
  tables: CatalogTableView[];
}

const SIMPLE_IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function toCatalogSchemaView(raw: unknown): CatalogSchemaView {
  const record = objectValue(raw);
  if (!record || !Array.isArray(record.tables)) throw new Error("The runtime returned no catalog schema.");
  const tables: CatalogTableView[] = [];
  for (const item of record.tables) {
    const table = objectValue(item);
    if (!table || typeof table.schema !== "string" || typeof table.name !== "string") continue;
    const columns = Array.isArray(table.columns)
      ? table.columns.flatMap(column => {
        const value = objectValue(column);
        return value && typeof value.name === "string"
          ? [{ name: value.name, type: typeof value.type === "string" ? value.type : "?" }]
          : [];
      })
      : [];
    tables.push({
      schema: table.schema,
      name: table.name,
      kind: table.kind === "view" ? "view" : "table",
      layer: table.layer === true,
      rowCount: typeof table.row_count === "number" ? table.row_count : undefined,
      fresh: typeof table.fresh === "boolean" ? table.fresh : undefined,
      error: typeof table.error === "string" ? table.error : undefined,
      columns
    });
  }
  return {
    engine: typeof record.engine === "string" ? record.engine : "unknown",
    layers: Array.isArray(record.layers) ? record.layers.filter((layer): layer is string => typeof layer === "string") : [],
    tables,
    truncated: record.truncated === true
  };
}

/**
 * Schemas in catalog order: every layer (even an empty one, so the medallion shape is always visible),
 * then the other schemas found in the file, alphabetically.
 */
export function groupBySchema(view: CatalogSchemaView): CatalogSchemaGroup[] {
  const groups = new Map<string, CatalogSchemaGroup>();
  for (const layer of view.layers) groups.set(layer, { schema: layer, layer: true, tables: [] });
  const others: CatalogSchemaGroup[] = [];
  for (const table of view.tables) {
    let group = groups.get(table.schema);
    if (!group) {
      group = { schema: table.schema, layer: false, tables: [] };
      groups.set(table.schema, group);
      others.push(group);
    }
    group.tables.push(table);
  }
  for (const group of groups.values()) group.tables.sort((a, b) => a.name.localeCompare(b.name));
  others.sort((a, b) => a.schema.localeCompare(b.schema));
  return [...view.layers.map(layer => groups.get(layer)!), ...others];
}

export function quoteIdentifier(name: string): string {
  return SIMPLE_IDENT.test(name) ? name : `"${name.replaceAll("\"", "\"\"")}"`;
}

export function qualifiedName(table: Pick<CatalogTableView, "schema" | "name">): string {
  return `${quoteIdentifier(table.schema)}.${quoteIdentifier(table.name)}`;
}

export function previewSql(table: Pick<CatalogTableView, "schema" | "name">, limit = 100): string {
  return `SELECT * FROM ${qualifiedName(table)} LIMIT ${limit};\n`;
}

/** A scratch file per table: `.datapass/scratch/<schema>.<table>.sql`, with unsafe characters replaced. */
export function scratchFileName(table: Pick<CatalogTableView, "schema" | "name">): string {
  const safe = (value: string) => value.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 80) || "_";
  return `${safe(table.schema)}.${safe(table.name)}.sql`;
}

export function scratchContent(table: CatalogTableView): string {
  const columns = table.columns.map(column => `--   ${column.name} ${column.type}`).join("\n");
  return [
    `-- ${table.kind === "view" ? "View" : "Table"} ${table.schema}.${table.name}` +
      (table.rowCount !== undefined ? ` · ${formatRowCount(table.rowCount)}` : ""),
    "-- Columns:",
    columns || "--   (none reported)",
    "-- Run it with Mosaic's Run active SQL (real DuckDB on the local catalog).",
    "",
    previewSql(table)
  ].join("\n");
}

export function formatRowCount(count: number): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? "row" : "rows"}`;
}

export function tableDescription(table: CatalogTableView): string {
  const parts = [table.rowCount !== undefined ? formatRowCount(table.rowCount) : "row count unavailable"];
  if (table.kind === "view") parts.push("view");
  return parts.join(" · ");
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}
