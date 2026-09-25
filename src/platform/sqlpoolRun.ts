import type {
  SqlPoolDistributionView,
  SqlPoolFlavor,
  SqlPoolLabView,
  SqlPoolPartitionView,
  SqlPoolPlanView,
  SqlPoolStatementView,
  SqlPoolTableView
} from "../webview/contracts";

type Raw = Record<string, unknown>;
type Cell = string | number | boolean | null;

/** T-SQL scripts of the Cloud Lab SQL pool tab live next to the pipeline files. */
export const SQLPOOL_FOLDER = "factory/sql/pool";
export const SQLPOOL_FLAVORS: readonly SqlPoolFlavor[] = ["synapse", "fabric"];
/** The runtime accepts scripts up to 60,000 characters and a scale from 1 to 1e12. */
export const SQLPOOL_LIMITS = { scriptChars: 60_000, scripts: 60, minScale: 1, maxScale: 1e12 };
/** How many real rows one lab row stands for, for tables that don't carry their own scale. */
export const SQLPOOL_SCALES: readonly { value: number; label: string }[] = [
  { value: 1, label: "1 (lab size)" },
  { value: 1_000, label: "1 thousand" },
  { value: 1_000_000, label: "1 million" },
  { value: 100_000_000, label: "100 million" }
];
export const DEFAULT_SQLPOOL_SCALE = 1_000_000;

const FLAVOR_COMMENT = /^\s*--\s*flavor\s*:\s*(synapse|fabric)\b/im;

/** The "-- flavor: synapse|fabric" comment in the first five lines of a script, when there is one. */
export function flavorHint(text: string): SqlPoolFlavor | undefined {
  const match = FLAVOR_COMMENT.exec(text.split(/\r?\n/, 5).join("\n"));
  return match ? (match[1].toLowerCase() as SqlPoolFlavor) : undefined;
}

export function isValidScale(value: number): boolean {
  return Number.isFinite(value) && value >= SQLPOOL_LIMITS.minScale && value <= SQLPOOL_LIMITS.maxScale;
}

/** Runtime `/api/local/sqlpool/run` response -> webview view. Truth labels are kept verbatim. */
export function toSqlPoolView(
  raw: unknown,
  context: { flavor: SqlPoolFlavor; scale: number; source: string; warnings?: string[] }
): SqlPoolLabView {
  const view = asRecord(raw);
  return {
    flavor: view.flavor === "synapse" || view.flavor === "fabric" ? view.flavor : context.flavor,
    flavorLabel: str(view.flavor_label, context.flavor),
    status: view.status === "ok" ? "ok" : "error",
    truth: str(view.truth, "Simulated SQL pool: nothing connects to Azure or Fabric."),
    scale: num(view.scale, context.scale),
    distributions: num(view.distributions, 60),
    rowgroupTarget: num(view.rowgroup_target, 1_000_000),
    source: context.source,
    statements: list(view.statements).map(toStatement),
    tables: list(view.tables).map(toTable),
    warnings: context.warnings ?? []
  };
}

function toStatement(value: unknown): SqlPoolStatementView {
  const statement = asRecord(value);
  const rows = list(statement.rows).map(row => Object.fromEntries(Object.entries(asRecord(row)).map(([k, v]) => [k, cell(v)])));
  const columns = strings(statement.columns);
  return {
    index: num(statement.index),
    line: num(statement.line, 1),
    kind: str(statement.kind, "STATEMENT"),
    status: statement.status === "error" ? "error" : "ok",
    message: str(statement.message, ""),
    target: optionalString(statement.target),
    sql: optionalString(statement.sql),
    columns: columns.length ? columns : Object.keys(rows[0] ?? {}),
    rows,
    truncated: statement.truncated === true,
    plan: statement.plan ? toPlan(statement.plan) : undefined,
    notes: strings(statement.notes),
    children: list(statement.children).map(toStatement)
  };
}

function toPlan(value: unknown): SqlPoolPlanView {
  const plan = asRecord(value);
  return {
    analyzed: plan.analyzed !== false,
    steps: list(plan.steps).map(item => {
      const step = asRecord(item);
      return {
        operation: str(step.operation, "Operation"),
        tables: strings(step.tables),
        columns: strings(step.columns),
        rows: num(step.rows),
        reason: str(step.reason, "")
      };
    }),
    scans: list(plan.scans).map(item => {
      const scan = asRecord(item);
      return {
        table: str(scan.table, "table"),
        alias: str(scan.alias, ""),
        partitionsScanned: num(scan.partitions_scanned),
        partitionsTotal: num(scan.partitions_total),
        eliminated: scan.eliminated === true,
        reason: str(scan.reason, "")
      };
    }),
    notes: strings(plan.notes),
    dataMovement: plan.data_movement === true
  };
}

function toTable(value: unknown): SqlPoolTableView {
  const table = asRecord(value);
  const partition = table.partition ? asRecord(table.partition) : undefined;
  return {
    name: str(table.name, "table"),
    label: str(table.label, ""),
    distribution: str(table.distribution, "ROUND_ROBIN"),
    hashColumns: strings(table.hash_columns),
    index: str(table.index, ""),
    indexColumns: strings(table.index_columns),
    partition: partition
      ? { column: str(partition.column, ""), range: str(partition.range, "LEFT"), boundaries: strings(partition.boundaries),
          count: num(partition.count, 1) }
      : undefined,
    clusterBy: strings(table.cluster_by),
    constraints: list(table.constraints).map(item => {
      const constraint = asRecord(item);
      return { kind: str(constraint.kind, "CONSTRAINT"), columns: strings(constraint.columns), enforced: constraint.enforced === true };
    }),
    nonclusteredIndexes: named(table.nonclustered_indexes),
    statistics: named(table.statistics),
    rows: num(table.rows),
    scaleFactor: num(table.scale_factor, 1),
    rowsAtScale: num(table.rows_at_scale),
    createdBy: str(table.created_by, ""),
    distributionStats: table.distribution_stats ? toDistribution(table.distribution_stats) : undefined,
    partitions: list(table.partitions).map(toPartition),
    columnstoreOk: typeof table.columnstore_ok === "boolean" ? table.columnstore_ok : undefined
  };
}

function toDistribution(value: unknown): SqlPoolDistributionView {
  const stats = asRecord(value);
  return {
    shares: list(stats.shares).map(share => num(share)),
    skewPct: num(stats.skew_pct),
    maxSharePct: num(stats.max_share_pct),
    minSharePct: num(stats.min_share_pct),
    emptyDistributions: num(stats.empty_distributions),
    distinctKeys: typeof stats.distinct_keys === "number" ? stats.distinct_keys : undefined,
    nullSharePct: num(stats.null_share_pct),
    heavyValues: list(stats.heavy_values).map(item => {
      const heavy = asRecord(item);
      return { value: String(heavy.value ?? ""), sharePct: num(heavy.share_pct) };
    })
  };
}

function toPartition(value: unknown): SqlPoolPartitionView {
  const partition = asRecord(value);
  return {
    number: num(partition.number, 1),
    lower: optionalString(partition.lower),
    upper: optionalString(partition.upper),
    rows: num(partition.rows),
    rowsAtScale: num(partition.rows_at_scale),
    rowsPerDistribution: typeof partition.rows_per_distribution === "number" ? partition.rows_per_distribution : undefined,
    columnstoreOk: typeof partition.columnstore_ok === "boolean" ? partition.columnstore_ok : undefined
  };
}

/** Bar heights (0..1) of the 60 distributions, relative to the fullest one. */
export function distributionBars(shares: readonly number[]): number[] {
  const max = Math.max(0, ...shares);
  return shares.map(share => (max > 0 ? share / max : 0));
}

/** Skew at or above 10% is where the Synapse guidance starts to worry. */
export function skewLevel(skewPct: number): "even" | "skewed" {
  return skewPct >= 10 ? "skewed" : "even";
}

/** A plan's data movement in one line. */
export function movementSummary(plan: SqlPoolPlanView | undefined): string {
  if (!plan) return "";
  const moves = plan.steps.filter(step => step.operation !== "ReturnOperation");
  if (!moves.length) return "No data movement: every join and aggregation runs inside the distributions.";
  return moves
    .map(step => `${step.operation.replace(/Operation$/, "")}${step.columns.length ? ` on ${step.columns.join(", ")}` : ""}` +
      ` (${step.tables.join(", ") || "result"})`)
    .join(" → ");
}

/** A plan's partition scans in one line: "dbo.f: 1 of 12 partitions". */
export function scanSummary(plan: SqlPoolPlanView | undefined): string {
  return (plan?.scans ?? [])
    .map(scan => `${scan.table}: ${scan.partitionsScanned} of ${scan.partitionsTotal} partitions scanned`)
    .join("; ");
}

/** Row counts at scale are large: 12 M, 1.2 B. */
export function formatCount(value: number): string {
  const abs = Math.abs(value);
  const units: [number, string][] = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
  for (const [size, unit] of units) {
    if (abs >= size) {
      const scaled = value / size;
      return `${Number(scaled.toFixed(scaled >= 100 ? 0 : 1))} ${unit}`;
    }
  }
  return String(Math.round(value * 100) / 100);
}

/** The last statement with rows or a plan: what the results panel shows first. */
export function defaultStatement(statements: readonly SqlPoolStatementView[]): SqlPoolStatementView | undefined {
  const flat = statements.flatMap(statement => [statement, ...statement.children]);
  return [...flat].reverse().find(statement => statement.status === "error")
    ?? [...flat].reverse().find(statement => statement.plan || statement.rows.length);
}

function named(value: unknown): { name: string; columns: string[] }[] {
  return Object.entries(asRecord(value)).map(([name, columns]) => ({ name, columns: strings(columns) }));
}

function cell(value: unknown): Cell {
  if (value === null || value === undefined) return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
  return JSON.stringify(value);
}

function asRecord(value: unknown): Raw {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Raw : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === "string");
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function optionalString(value: unknown): string | undefined {
  if (typeof value === "number") return String(value);
  return typeof value === "string" && value ? value : undefined;
}
