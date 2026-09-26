import type { MissionListView } from "./missions";

export type LakehouseEngine = "duckdb" | "polars";

/** What the Workbench shows of a Lakehouse mission besides its ticket: the engines and the learner's files. */
export interface LakehouseMissionDetail {
  engines: readonly LakehouseEngine[];
  /** The learner's file per engine, relative to lakehouse/<id>/. */
  files: Readonly<Partial<Record<LakehouseEngine, string>>>;
  /** A DuckLake mission: DuckDB SQL on the mission's own DuckLake catalog (lakehouse/<id>/lake/). */
  ducklake: boolean;
  /** Delta tables (folders with a _delta_log) the lab attaches by folder name through DuckDB's delta extension. */
  delta: readonly string[];
  concepts: readonly string[];
}

/** One statement of a Run: rows as text cells (the first 50), or nothing for a statement that returns no rows. */
export interface LakehouseStatementView {
  type: string;
  sql: string;
  columns?: readonly string[];
  rows?: readonly (readonly (string | null)[])[];
  truncated?: boolean;
}

/** The last Run of a mission's file (runtime/lakehouselab/lab.py run). */
export interface LakehouseRunView {
  missionId: string;
  engine: LakehouseEngine;
  file: string;
  truth: string;
  at: string;
  elapsedMs?: number;
  statements?: readonly LakehouseStatementView[];
  error?: string;
  failedStatement?: number;
  exitCode?: number;
  stdout?: string;
  stderr?: string;
}

/** What the mission folder holds (measured on disk), and its DuckLake snapshots (queried). */
export interface LakehouseStorageView {
  missionId: string;
  folders: readonly { path: string; files: number; bytes: number }[];
  snapshots?: readonly { id: number; changes: string }[];
  tables?: readonly { name: string; files: number; bytes: number }[];
  snapshotsError?: string;
}

export interface LakehouseViewState {
  missions: MissionListView;
  details: Readonly<Record<string, LakehouseMissionDetail>>;
  /** The ducklake extension for this DuckDB: installed once by Setup runtime (network), then loaded offline. */
  ducklake?: { installed: boolean; version?: string | null; delta: boolean; deltaVersion?: string | null; error?: string | null };
  trustedPython: boolean;
  lastRun?: LakehouseRunView;
  storage?: LakehouseStorageView;
  error?: string;
}

export interface LakehouseViewSlice {
  lakehouse?: LakehouseViewState;
}

export type LakehouseMissionAction = "startMission" | "restartMission" | "openMission" | "revealMissionHint" | "checkMission";

export type LakehouseMessage =
  | { type: "lakehouseMission"; action: LakehouseMissionAction; missionId: string }
  | { type: "lakehouseRun"; missionId: string; engine: LakehouseEngine }
  | { type: "lakehouseStorage"; missionId: string }
  | { type: "refreshLakehouseLab" };
