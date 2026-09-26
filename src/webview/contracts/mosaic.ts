import type { MosaicLayoutItem } from "../../platform/mosaicLayout";
import type { QueryHistoryEntry } from "../../platform/mosaicTools";

export type ScratchKind = "sql" | "python" | "sparklab" | "notes";

/** DuckDB SUMMARIZE of one catalog table (Mosaic → Profile). */
export interface TableProfileView {
  asset: string;
  elapsed_ms: number;
  truth: string;
  result: {
    columns: readonly string[];
    rows: readonly Record<string, string | number | boolean | null>[];
    truncated?: boolean;
  };
}

/** A dialect translated to DuckDB (runtime/sqldialects): what ran, and the rules that kept the engine's result. */
export interface DialectTranslationView {
  source: string;
  target: "duckdb";
  /** "T-SQL dialect translated to DuckDB, not SQL Server". */
  label: string;
  /** The DuckDB SQL that really ran. */
  sql: string;
  rewrites: readonly string[];
}

/** DuckDB EXPLAIN ANALYZE of one read-only query (Mosaic → Explain active SQL). */
export interface QueryPlanView {
  plan: string;
  query: string;
  elapsed_ms: number;
  truth: string;
  /** Workspace-relative file the query came from; "selection" is appended when only a selection was explained. */
  source?: string;
  /** Set when the file declares another dialect: the plan is the translation's. */
  dialect?: DialectTranslationView;
}

export interface LocalCellRunView {
  id: string;
  status: "success" | "error";
  language: string;
  elapsed_ms: number;
  stdout: string;
  result?: {
    columns: readonly string[];
    rows: readonly Record<string, string | number | boolean | null>[];
    truncated?: boolean;
  };
  error?: {
    type: string;
    message: string;
  };
  /** Set when the SQL file declares another dialect (`-- dialect: <name>`). */
  dialect?: DialectTranslationView;
}

export interface CsvImportView {
  asset: string;
  fileName: string;
  /** csv (every column text) when absent; parquet and json keep their types. */
  format?: "csv" | "parquet" | "json";
  rows_imported: number;
  sha256: string;
  schema: readonly { name: string; type: string }[];
  truth: string;
  result: {
    columns: readonly string[];
    rows: readonly Record<string, string | number | boolean | null>[];
    truncated?: boolean;
  };
}

export interface MosaicRuntimeSlice {
  lastRun?: LocalCellRunView;
  /** Latest Mosaic CSV import; cleared when a newer SQL/Python run replaces the preview. */
  csvImport?: CsvImportView;
  tableProfile?: TableProfileView;
  queryPlan?: QueryPlanView;
}

export interface MosaicViewSlice {
  /** Project-portable layout from .datapass/mosaic.json, when present and valid. */
  mosaicLayout?: readonly MosaicLayoutItem[];
  /** Mosaic SQL runs and plans in this workspace, newest first (VS Code workspace state, not a project file). */
  queryHistory?: readonly QueryHistoryEntry[];
}

export type MosaicMessage =
  | { type: "importCsv" }
  | { type: "importFile" }
  | { type: "profileTable"; asset: string }
  | { type: "explainActiveSql" }
  | { type: "openQueryPlan" }
  | { type: "openTranslatedSql" }
  | { type: "rerunQuery"; id: string }
  | { type: "openQueryFile"; id: string }
  | { type: "runActiveSql" }
  | { type: "runActivePython" }
  | { type: "saveMosaicLayout"; layout: readonly { i: string; x: number; y: number; w: number; h: number }[] }
  | { type: "openScratch"; kind: ScratchKind };
