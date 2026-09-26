/** BI Lab files: warehouse scripts (bi/warehouse/*.sql, run in name order) and the star model (bi/model.json). */
export interface BiViewState {
  folder: string;
  exists: boolean;
  scripts: readonly { name: string; path: string }[];
  modelPath: string;
  modelExists: boolean;
  /** The model file is not valid JSON (the runtime validates the rest). */
  modelError?: string;
  warnings: readonly string[];
  /** The dbt project of the BI Lab (bi/dbt), run with the Datapass dbt emulation. */
  dbtExists: boolean;
  dbtFiles: number;
}

export type BiRunMode = "build" | "analyze" | "active";

export type BiDbtCommand = "build" | "run" | "test" | "seed" | "snapshot" | "compile" | "parse";

export interface BiDbtNodeView {
  uniqueId: string;
  name: string;
  resourceType: "model" | "seed" | "snapshot" | "test";
  materialized: string;
  relation?: string;
  path: string;
  dependsOn: readonly string[];
  sources: readonly string[];
  tags: readonly string[];
  description: string;
  problem?: string;
}

export interface BiDbtResultView {
  uniqueId: string;
  name: string;
  resourceType: string;
  status: "success" | "error" | "skipped" | "pass" | "fail" | "warn";
  message: string;
  materialized: string;
  relation?: string;
  rowsAffected?: number;
  failures?: number;
  compiled: string;
  failingRows: readonly Record<string, string | number | boolean | null>[];
  path: string;
}

export interface BiDbtView {
  command: BiDbtCommand;
  select: string;
  status: "success" | "error" | "parsed" | "invalid";
  error?: string;
  projectName?: string;
  issues: readonly { path: string; message: string }[];
  nodes: readonly BiDbtNodeView[];
  sources: readonly { name: string; relation: string; description: string }[];
  results: readonly BiDbtResultView[];
  counts?: Readonly<Record<string, number>>;
  now?: string;
  lineage?: BiLineageView;
  truth: string;
  warnings: readonly string[];
}

export interface BiStatementView {
  path: string;
  index: number;
  line: number;
  kind: string;
  target?: string;
  status: "success" | "error";
  message: string;
  affected?: number;
  columns: readonly string[];
  rows: readonly Record<string, string | number | boolean | null>[];
}

export interface BiTableView {
  name: string;
  layer: string;
  rows?: number;
  columns: readonly { name: string; type: string }[];
}

export interface BiLineageColumnView {
  table: string;
  column: string;
  transform: string;
  expression: string;
  sources: readonly string[];
  origins: readonly string[];
}

export interface BiLineageTableView {
  name: string;
  kind: "source" | "table" | "view";
  columns: readonly string[];
  inputs: readonly string[];
  statements: readonly { path: string; line: number; kind: string }[];
}

export interface BiImpactView {
  table: string;
  column: string;
  effect: "value" | "rows";
}

export interface BiLineageView {
  tables: readonly BiLineageTableView[];
  columns: readonly BiLineageColumnView[];
  influence: readonly { table: string; source: string; role: string; origins: readonly string[] }[];
  impact: Readonly<Record<string, readonly BiImpactView[]>>;
  issues: readonly { path: string; line: number; message: string }[];
  truth: string;
}

export interface BiModelTableView {
  name: string;
  role: "fact" | "dimension" | "bridge";
  key?: string;
  businessKey: readonly string[];
  grain: readonly string[];
  unknownMember?: string;
  scdType?: number;
  description: string;
}

export interface BiRelationshipView {
  from: string;
  to: string;
  cardinality: string;
  crossFilter: "single" | "both";
  active: boolean;
  observed?: string;
  fromRows?: number;
  orphans?: number;
  nullKeys?: number;
}

export interface BiCheckView {
  check: string;
  subject: string;
  status: "pass" | "fail" | "warn";
  detail: string;
}

export interface BiModelView {
  name: string;
  description: string;
  tables: readonly BiModelTableView[];
  relationships: readonly BiRelationshipView[];
  checks: readonly BiCheckView[];
}

export interface BiLabView {
  mode: BiRunMode;
  source: string;
  status: "ok" | "error";
  ran: boolean;
  stopped?: { path: string; line: number; message: string };
  statements: readonly BiStatementView[];
  tables: readonly BiTableView[];
  lineage: BiLineageView;
  model?: BiModelView;
  modelError?: string;
  truth: Readonly<Record<string, string>>;
  warnings: readonly string[];
}

export interface BiRuntimeSlice {
  biRun?: BiLabView;
  biDbtRun?: BiDbtView;
}

export interface BiViewSlice {
  bi?: BiViewState;
}

export type BiMessage =
  | { type: "createBiLab" }
  | { type: "refreshBi" }
  | { type: "openBiFile"; path: string }
  | { type: "runBiLab"; mode: BiRunMode }
  | { type: "revealBiLine"; path: string; line: number }
  | { type: "runBiDbt"; command: BiDbtCommand; select: string; fullRefresh: boolean };
