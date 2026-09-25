/**
 * The SQL dialect of a Mosaic .sql file, "like a kernel": its first line `-- dialect: <name>` says which dialect the
 * file is written in. The runtime translates it to DuckDB (runtime/sqldialects) and runs it on the local catalog;
 * without a header the file is DuckDB SQL. Pure functions, tested by scripts/sql_dialect_smoke.mjs.
 */

export type SqlDialectId = "duckdb" | "tsql" | "snowflake" | "bigquery" | "spark" | "postgres";
export type TranslatedDialectId = Exclude<SqlDialectId, "duckdb">;

export interface SqlDialectInfo {
  id: SqlDialectId;
  /** Status bar name: "SQL: T-SQL ▾". */
  title: string;
  /** What it covers, for the picker. */
  family: string;
  /** The truth label shown with every result (the runtime's own label for translated dialects). */
  label: string;
}

export const SQL_DIALECTS: readonly SqlDialectInfo[] = [
  { id: "duckdb", title: "DuckDB", family: "The local catalog's engine: runs as written", label: "DuckDB SQL, real execution" },
  { id: "tsql", title: "T-SQL", family: "SQL Server, Azure SQL, Synapse, Fabric Warehouse",
    label: "T-SQL dialect translated to DuckDB, not SQL Server" },
  { id: "snowflake", title: "Snowflake", family: "Snowflake SQL", label: "Snowflake SQL dialect translated to DuckDB, not Snowflake" },
  { id: "bigquery", title: "BigQuery", family: "GoogleSQL", label: "BigQuery SQL dialect translated to DuckDB, not BigQuery" },
  { id: "spark", title: "Spark SQL", family: "ANSI mode: Apache Spark 4, Databricks SQL",
    label: "Spark SQL dialect translated to DuckDB, not Spark" },
  { id: "postgres", title: "PostgreSQL", family: "PostgreSQL", label: "PostgreSQL dialect translated to DuckDB, not PostgreSQL" }
];

const ALIASES: Record<string, SqlDialectId> = {
  duckdb: "duckdb", duck: "duckdb",
  tsql: "tsql", "t-sql": "tsql", sqlserver: "tsql", "sql-server": "tsql", mssql: "tsql", synapse: "tsql", fabric: "tsql",
  snowflake: "snowflake",
  bigquery: "bigquery", bq: "bigquery", googlesql: "bigquery",
  spark: "spark", sparksql: "spark", "spark-sql": "spark", databricks: "spark",
  postgres: "postgres", postgresql: "postgres", pg: "postgres"
};

/** `-- dialect: tsql` (case and spaces free). */
const HEADER = /^\s*--\s*dialect\s*:\s*([A-Za-z][A-Za-z0-9_-]*)\s*$/i;

export interface DialectHeader {
  dialect: SqlDialectId;
  /** Zero-based line of the header, when the file has one. */
  line?: number;
  /** The name written in a header that is not a known dialect (the file is not run). */
  unknown?: string;
}

export function dialectInfo(id: SqlDialectId): SqlDialectInfo {
  return SQL_DIALECTS.find(item => item.id === id) ?? SQL_DIALECTS[0];
}

export function dialectFromName(name: string): SqlDialectId | undefined {
  return ALIASES[name.trim().toLowerCase()];
}

/** The dialect a file declares on its first non-blank line; DuckDB without a header. */
export function readDialectHeader(text: string): DialectHeader {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/);
  const index = lines.findIndex(line => line.trim() !== "");
  const match = index >= 0 ? HEADER.exec(lines[index]) : null;
  if (!match) return { dialect: "duckdb" };
  const dialect = dialectFromName(match[1]);
  return dialect ? { dialect, line: index } : { dialect: "duckdb", line: index, unknown: match[1] };
}

export interface HeaderEdit {
  /** Zero-based line to replace or delete, or undefined to insert a first line. */
  line?: number;
  /** The new line, or undefined to delete `line` (DuckDB needs no header). */
  text?: string;
}

/** The edit that makes a file declare `dialect`: replace the header, insert it as the first line, or remove it. */
export function dialectHeaderEdit(text: string, dialect: SqlDialectId): HeaderEdit | undefined {
  const current = readDialectHeader(text);
  const wanted = dialect === "duckdb" ? undefined : `-- dialect: ${dialect}`;
  if (current.line === undefined) return wanted ? { text: wanted } : undefined;
  if (!current.unknown && current.dialect === dialect) return undefined;
  return { line: current.line, text: wanted };
}

/** The dialect to send with a run: undefined for DuckDB; an error for an unknown header. */
export function runDialect(text: string): { dialect?: TranslatedDialectId; error?: string } {
  const header = readDialectHeader(text);
  if (header.unknown) {
    return { error: `Unknown SQL dialect '${header.unknown}' on line ${header.line! + 1}. Use one of ` +
      `${SQL_DIALECTS.map(item => item.id).join(", ")} (the SQL: status bar item writes it).` };
  }
  return header.dialect === "duckdb" ? {} : { dialect: header.dialect };
}

/** Status bar text: "SQL: T-SQL ▾". */
export function statusText(id: SqlDialectId): string {
  return `SQL: ${dialectInfo(id).title} ▾`;
}
