/**
 * Mosaic data tools: which files the import accepts, and the SQL query history. Pure functions, tested by
 * scripts/mosaic_tools_smoke.mjs. The runtime does the real work (DuckDB SUMMARIZE, EXPLAIN ANALYZE, imports).
 */

export type ImportFormat = "csv" | "parquet" | "json";

/** Parquet and JSON travel as base64 content; the runtime refuses more than 10 MB decoded. */
export const FILE_IMPORT_MAX_BYTES = 10_000_000;
export const IMPORT_FILTERS: Record<string, string[]> = {
  "Data files": ["csv", "parquet", "json", "jsonl", "ndjson"],
  CSV: ["csv"],
  Parquet: ["parquet"],
  "JSON / JSON Lines": ["json", "jsonl", "ndjson"]
};

export function importFormat(fileName: string): ImportFormat | undefined {
  const base = fileName.replace(/^.*[\\/]/, "").toLowerCase();
  const dot = base.lastIndexOf(".");
  const extension = dot > 0 ? base.slice(dot + 1) : undefined;
  if (extension === "csv") return "csv";
  if (extension === "parquet") return "parquet";
  if (extension === "json" || extension === "jsonl" || extension === "ndjson") return "json";
  return undefined;
}

export interface QueryHistoryEntry {
  id: string;
  at: string;
  kind: "run" | "explain";
  /** Workspace-relative path of the file the SQL came from, when there was one. */
  file?: string;
  sql: string;
  status: "success" | "error";
  elapsedMs: number;
  rows?: number;
  error?: string;
}

export const QUERY_HISTORY_MAX = 30;
export const QUERY_HISTORY_SQL_MAX = 8000;

/** Newest first; running the same SQL again moves it to the top instead of repeating it. */
export function addQueryHistory(history: readonly QueryHistoryEntry[] | undefined, entry: QueryHistoryEntry,
  max = QUERY_HISTORY_MAX): QueryHistoryEntry[] {
  const sql = entry.sql.length > QUERY_HISTORY_SQL_MAX ? entry.sql.slice(0, QUERY_HISTORY_SQL_MAX) : entry.sql;
  const kept = (history ?? []).filter(item => !(item.sql.trim() === sql.trim() && item.kind === entry.kind));
  return [{ ...entry, sql }, ...kept].slice(0, max);
}

/** History read back from workspace state: malformed entries are dropped. */
export function restoreQueryHistory(raw: unknown): QueryHistoryEntry[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item): QueryHistoryEntry[] => {
    const value = item && typeof item === "object" ? item as Record<string, unknown> : undefined;
    if (!value || typeof value.id !== "string" || typeof value.at !== "string" || typeof value.sql !== "string") return [];
    if (value.kind !== "run" && value.kind !== "explain") return [];
    if (value.status !== "success" && value.status !== "error") return [];
    return [{
      id: value.id,
      at: value.at,
      kind: value.kind,
      file: typeof value.file === "string" ? value.file : undefined,
      sql: value.sql.slice(0, QUERY_HISTORY_SQL_MAX),
      status: value.status,
      elapsedMs: typeof value.elapsedMs === "number" ? value.elapsedMs : 0,
      rows: typeof value.rows === "number" ? value.rows : undefined,
      error: typeof value.error === "string" ? value.error : undefined
    }];
  }).slice(0, QUERY_HISTORY_MAX);
}

/** First line of a query for a compact list, with its length kept honest. */
export function querySummary(sql: string, width = 90): string {
  const line = sql.split(/\r?\n/).map(part => part.trim()).find(part => part && !part.startsWith("--")) ?? sql.trim();
  return line.length > width ? `${line.slice(0, width - 1)}…` : line;
}
