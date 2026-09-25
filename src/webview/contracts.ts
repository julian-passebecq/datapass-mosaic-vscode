import type { ModuleId, WorkbenchModule } from "../modules";
import type { MosaicLayoutItem } from "../platform/mosaicLayout";
import type { PythonTrustState } from "../platform/pythonTrust";
import type { DbtCoreRunView } from "../platform/dbtArtifacts";
import type { MissionProgressView, MissionView } from "../platform/missions";
import type { GitView, ShellId, ShellView } from "../platform/terminalShells";
import type { DbtCommand, DctFormat, DctRenderView, DctValidationView } from "../platform/dbtTools";
import type { ProjectsViewState } from "../platform/projects";
import type { QueryHistoryEntry } from "../platform/mosaicTools";
import type { PracticeProgress } from "../platform/practiceProgress";
import type { RowValidation } from "../platform/practiceFeedback";

export type RuntimeStatus = "stopped" | "starting" | "running" | "error";
export type ScratchKind = "sql" | "python" | "sparklab" | "notes";

export interface RetailDemoStageView {
  id: string;
  label: string;
  rows: number;
  engine: string;
}

export interface RetailDemoRunView {
  status: "success";
  truth: string;
  dataset_path: string;
  database_path: string;
  stages: readonly RetailDemoStageView[];
  polars_quality: {
    rows: number;
    customers: number;
    revenue: number;
  };
  preview: {
    columns: readonly string[];
    rows: readonly Record<string, string | number | boolean | null>[];
    truncated: boolean;
  };
}

export interface LocalCatalogAssetView {
  name: string;
  layer: string;
  row_count: number;
  fresh: boolean;
  producer?: string;
}

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

export interface SparkLabStageView {
  stage_id: number;
  name: string;
  operator: string;
  duration_s: number;
  partitions: number;
  task_count: number;
  shuffle_read_gb: number;
  shuffle_write_gb: number;
  spill_gb: number;
  skewed_tasks: number;
  dependencies: readonly number[];
  notes: readonly string[];
}

export interface SparkLabPlanNodeView {
  id: number;
  operation: string;
  source?: string;
  parents: readonly number[];
  dependency: string;
  concept: string;
}

export interface SparkLabSimulationView {
  status: "modeled" | "unavailable";
  truth?: string;
  reason?: string;
  totalDurationS?: number;
  shuffleGb?: number;
  spillGb?: number;
  clusterUtilizationPct?: number;
  /** Modeled shuffle exchanges (Spark planning rules over assumed sizes), with the reason for each. */
  exchanges?: readonly string[];
  credits?: { total: number; unit: string; fictional: boolean };
  assumptionsKind?: string;
  calibration?: string;
  stages: readonly SparkLabStageView[];
  plan: readonly SparkLabPlanNodeView[];
  comparisons: readonly { profile_id: string; aqe: boolean; duration_s: number; credits: number }[];
}

export interface SparkLabRunView {
  status: "success" | "error";
  fileName: string;
  profileId: string;
  aqe: boolean;
  elapsed_ms: number;
  compiledSql?: string;
  result?: LocalCellRunView["result"];
  error?: { type: string; message: string };
  simulation?: SparkLabSimulationView;
}

export interface SparkLabProfileView {
  id: string;
  label: string;
}

export interface PipelineTaskRunView {
  id: string;
  kind: string;
  status: "success" | "failed" | "skipped";
  attempts: number;
  elapsed_ms: number;
  error?: string | null;
  result?: unknown;
}

export interface PipelineRunView {
  run_id: string;
  pipeline_id: string;
  status: "success" | "failed";
  truth: string;
  tasks: readonly PipelineTaskRunView[];
}

export interface RuntimeEnvironmentView {
  status: "missing" | "setting-up" | "ready" | "error";
  python?: string;
  detail?: string;
  /** Present while status is "setting-up". */
  progress?: RuntimeSetupProgressView;
}

export interface RuntimeSetupProgressView {
  step: number;
  totalSteps: number;
  label: string;
  /** Latest recognised pip/venv activity, e.g. "Downloading polars (35.2 MB)". */
  activity?: string;
  /** Epoch milliseconds when setup started. */
  startedAt: number;
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

export interface RuntimeViewState {
  status: RuntimeStatus;
  url?: string;
  detail?: string;
  /** Reported by the running runtime itself (GET /api/capabilities), not assumed. */
  trustedPython?: boolean;
  sparkRun?: SparkLabRunView;
  airflowRun?: AirflowLabView;
  factoryRun?: FactoryLabView;
  sqlpoolRun?: SqlPoolLabView;
  databricksRun?: DatabricksLabView;
  /** Unity Catalog, MLflow and compute of the Databricks tab, refreshed after each job run. */
  databricksState?: DatabricksStateView;
  biRun?: BiLabView;
  biDbtRun?: BiDbtView;
  retailDemo?: RetailDemoRunView;
  catalog?: readonly LocalCatalogAssetView[];
  /** Set while the catalog file is lent to a dbt Core or dct command in the dbt Lab terminal. */
  catalogLease?: CatalogLeaseView;
  lastRun?: LocalCellRunView;
  /** Latest Mosaic CSV import; cleared when a newer SQL/Python run replaces the preview. */
  csvImport?: CsvImportView;
  tableProfile?: TableProfileView;
  queryPlan?: QueryPlanView;
  pipelineRun?: PipelineRunView;
  practiceResult?: PracticeResultView;
  environment?: RuntimeEnvironmentView;
}

export interface CatalogLeaseView {
  /** The command line that borrows .datapass/data/workspace.duckdb. */
  holder: string;
  since: string;
  /** The last reattach attempt failed (the file is still held); the text says why. */
  reattachError?: string;
}

export interface PythonTrustView {
  state: PythonTrustState;
  effective: boolean;
  reason: string;
  /** The running runtime was started with a different trust setting. */
  restartRequired: boolean;
}

export interface WorkspaceViewState {
  folderName?: string;
  manifestExists: boolean;
  manifestValid: boolean;
  projectTitle?: string;
  errors: string[];
}

export interface ExerciseSummary {
  key: string;
  packId: string;
  packTitle: string;
  id: string;
  version: string;
  title: string;
  difficulty: string;
  language: string;
  /** The grading runtime id (for example datapass-dag-design-v1), when the pack declares one. */
  runtime?: string;
  prompt: string;
  starterSource: string;
  truth?: string;
  topics: string[];
  sections: ExerciseSectionView[];
  hints: string[];
  dataContext: ExerciseTableView[];
  /** How the grader compares result rows; the visible-fixture diff follows it. */
  validation: RowValidation;
  /** Why the reference solution works, shown with it. */
  explanation?: string;
  /** The pack ships a reference solution the learner may reveal (after a pass, or after a few failures). */
  solutionAvailable: boolean;
  /** SparkLab exercises only: public checks on the simulated Spark plan. */
  sparkPlan?: SparkPlanView;
  /** Set when Datapass cannot grade the exercise locally; Run/Submit are disabled. */
  gradingNote?: string;
}

/** Plan requirements graded on SparkLab's modeled plan at authored input sizes (not Apache Spark). */
export interface SparkPlanView {
  profile: string;
  aqe: boolean;
  scale: SparkTableScaleView[];
  checks: SparkPlanCheckView[];
}

export interface SparkTableScaleView {
  table: string;
  rows: number;
  bytes: number;
  partitions: number;
  catalogStatistics: boolean;
}

export interface SparkPlanCheckView {
  id: string;
  description: string;
}

export interface ExerciseSectionView {
  title: string;
  body: string;
}

/** Public input table: schema and the visible example rows only. */
export interface ExerciseTableView {
  name: string;
  columns: Record<string, string>;
  sampleRows: Record<string, string | number | boolean | null>[];
}

export interface ExerciseCheckView {
  id: string;
  /** "plan" checks grade the simulated SparkLab plan, not result rows. */
  kind?: "result" | "plan";
  visibility: "visible" | "hidden" | "edge";
  passed: boolean;
  status: "passed" | "failed";
  message: string;
  elapsed_ms: number;
  actual?: readonly Record<string, unknown>[];
  expected?: readonly Record<string, unknown>[];
}

export interface PracticeResultView {
  exerciseKey: string;
  mode: "run" | "submit";
  status: "passed" | "failed" | "error";
  truth: string;
  elapsed_ms: number;
  checks: readonly ExerciseCheckView[];
  runtime?: {
    adapter: string;
    engine: string;
    engine_version: string;
    session_generation: string;
  };
  error?: {
    type: string;
    message: string;
  };
}

export interface PracticeViewState {
  exercises: readonly ExerciseSummary[];
  /** The `practice` section of .datapass/progress.json (solved, attempted; absent means not started). */
  progress: PracticeProgress;
  /** Set when .datapass/progress.json cannot be read; progress is then shown as empty and not saved. */
  progressError?: string;
  /** False without a workspace folder: progress cannot be kept. */
  canSaveProgress: boolean;
  /** Reference solutions the learner revealed in this Workbench, by exercise key. */
  solutions: Record<string, string>;
}

export interface GraphNodeView {
  id: string;
  label: string;
  detail: string;
  truth?: string;
  /** Optional state used to color the node (Airflow task states). */
  status?: string;
  /** Initial position when the graph has its own layout (the BI Lab star); dragged positions still win. */
  position?: { x: number; y: number };
  /** Connection points on all four sides, for layouts that are not left to right (edges then name their sides). */
  allSides?: boolean;
}

export type GraphSide = "top" | "right" | "bottom" | "left";

export interface GraphEdgeView {
  id: string;
  source: string;
  target: string;
  label: string;
  /** Optional CSS class (Factory Lab colors dependency conditions). */
  className?: string;
  /** Sides the edge leaves and enters by, between nodes with allSides (default: right to left). */
  sourceSide?: GraphSide;
  targetSide?: GraphSide;
}

export interface GraphView {
  nodes: readonly GraphNodeView[];
  edges: readonly GraphEdgeView[];
}

export interface PipelineDiagnostic {
  line: number;
  column: number;
  message: string;
}

export interface PipelineViewState {
  exists: boolean;
  path: string;
  compileStatus: "missing" | "runtime-required" | "valid" | "invalid" | "error";
  diagnostics: readonly PipelineDiagnostic[];
  graph: GraphView;
  truth?: string;
  schedule?: string | null;
}

/** Airflow Lab project files: DAGs are Python files under <assets.airflow>/dags. */
export interface AirflowViewState {
  dagsFolder: string;
  starterPath: string;
  starterExists: boolean;
  /** Pre-simulator JSON spec (airflow/main.dag.json), no longer simulated. */
  legacySpecPath?: string;
}

export type AirflowTaskBehavior = "success" | "fail_once" | "fail_twice" | "fail_always";

/** What the learner chooses in the Airflow Lab scenario form. Times are UTC, "YYYY-MM-DDTHH:MM". */
export interface AirflowTaskScenarioInput {
  behavior: AirflowTaskBehavior;
  durationSeconds?: number;
  /** Sensors: minutes after the sensor starts when its file/condition appears; null = never. */
  sensorArrivalMinutes?: number | null;
  /** Branch tasks: the task ids it chooses. Omitted: its literal return value, if any. */
  branch?: string[];
}

export interface AirflowScenarioInput {
  now?: string;
  unpausedAt?: string;
  manualRunAt?: string;
  tasks: Record<string, AirflowTaskScenarioInput>;
}

export interface AirflowLabTaskView {
  taskId: string;
  operator: string;
  kind: string;
  line: number;
  triggerRule: string;
  retries: number;
  retryDelayS: number;
  upstream: string[];
  downstream: string[];
  templatedFields: string[];
  staticBranch?: string[];
  sensor?: { pokeIntervalS: number; timeoutS: number; mode: string; softFail: boolean };
}

export interface AirflowLabInstanceView {
  taskId: string;
  state: string;
  tryNumber: number;
  startS?: number;
  endS?: number;
}

export interface AirflowLabEventView {
  t: number;
  taskId: string;
  state: string;
  tryNumber: number;
  message: string;
}

export interface AirflowLabRunView {
  runId: string;
  runType: string;
  logicalDate: string;
  runAfter: string;
  dataIntervalStart: string;
  dataIntervalEnd: string;
  state: string;
  durationS: number;
  instances: AirflowLabInstanceView[];
  events: AirflowLabEventView[];
  rendered: { taskId: string; field: string; value: string }[];
  renderError?: string;
}

/** Runtime simulation of one DAG file: parsed, never executed. */
export interface AirflowLabView {
  fileName: string;
  status: "simulated" | "invalid" | "simulation_error";
  truth: string;
  error?: { message: string; line?: number };
  now?: string;
  unpausedAt?: string;
  dag?: {
    dagId: string;
    schedule: { kind: string; label: string; note: string };
    startDate?: string;
    endDate?: string;
    catchup: boolean;
    tasks: AirflowLabTaskView[];
    edges: { upstream: string; downstream: string }[];
  };
  totalRuns: number;
  runs: AirflowLabRunView[];
  scenario: AirflowScenarioInput;
}

/** Cloud Lab › Pipelines (Factory Lab): Fabric, Azure Data Factory and Synapse pipelines, simulated locally. */
export type FactoryFlavor = "fabric" | "adf" | "synapse";

export interface FactoryParameterView {
  name: string;
  type: string;
  defaultValue: unknown;
}

export interface FactoryDesignActivityView {
  name: string;
  type: string;
  /** Container path, for example "Loop/Copy table". */
  path: string;
  state: string;
  dependsOn: { activity: string; conditions: string[] }[];
  children: { key: string; activities: FactoryDesignActivityView[] }[];
}

/** A pipeline file as the host reads it for the canvas; the runtime validates it when it runs. */
export interface FactoryDesignView {
  flavor: FactoryFlavor;
  name: string;
  /** Workspace-relative path of the pipeline file. */
  path: string;
  description: string;
  parameters: FactoryParameterView[];
  variables: FactoryParameterView[];
  activities: FactoryDesignActivityView[];
  error?: string;
}

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

export interface FactoryViewState {
  folder: string;
  exists: boolean;
  pipelines: FactoryDesignView[];
  /** T-SQL scripts for the SQL pool tab (factory/sql/pool/*.sql). */
  poolScripts: SqlPoolScriptView[];
  /** Jobs and files of the Databricks tab (factory/databricks). */
  databricks: DatabricksViewState;
  warnings: string[];
}

export type FactoryActivityBehavior = "success" | "fail_once" | "fail_twice" | "fail_always";

export interface FactoryActivityScenarioInput {
  behavior: FactoryActivityBehavior;
  durationSeconds?: number;
  /** JSON object text merged into the activity output (for example a Lookup's firstRow). */
  output?: string;
}

export type FactoryTriggerType = "Manual" | "ScheduleTrigger" | "TumblingWindowTrigger" | "BlobEventsTrigger";

export interface FactoryScenarioInput {
  /** local: Copy, Lookup, Script, procedures and notebooks act on the local catalog; simulated: dry run. */
  dataPlane: "local" | "simulated";
  /** Text as typed; the runtime converts it to each parameter's type. Blank keeps the default. */
  parameters: Record<string, string>;
  activities: Record<string, FactoryActivityScenarioInput>;
  triggerType: FactoryTriggerType;
  /** UTC "YYYY-MM-DDTHH:MM"; pipeline().TriggerTime and utcNow(). */
  now?: string;
}

export interface FactoryActivityRunView {
  name: string;
  type: string;
  path: string;
  status: string;
  startS: number;
  endS: number;
  attempts: number;
  input: unknown;
  output: unknown;
  error?: { code: string; message: string; failureType: string };
  iteration?: string;
  truth: "local" | "simulated";
  note: string;
  parent?: string;
}

export interface FactoryRunView {
  pipeline: string;
  runId: string;
  status: string;
  evaluated: string[];
  durationS: number;
  parameters: Record<string, unknown>;
  variables: Record<string, unknown>;
  returnValue: unknown;
  activityRuns: FactoryActivityRunView[];
  children: FactoryRunView[];
  explanation: string;
}

export interface FactoryLabView {
  flavor: FactoryFlavor;
  flavorLabel: string;
  pipelineName: string;
  path: string;
  status: "simulated" | "invalid" | "error";
  truth: string;
  dataPlane: "local" | "simulated";
  issues: { path: string; message: string; severity: string }[];
  hints: string[];
  warnings: string[];
  run?: FactoryRunView;
  tablesChanged: { name: string; rows: number; producer?: string }[];
  scenario: FactoryScenarioInput;
}

/** Cloud Lab › Databricks: jobs, compute, Unity Catalog and MLflow, simulated locally. */
export type DatabricksTaskKind = "notebook" | "condition" | "sql" | "for_each";

export interface DatabricksTaskDesignView {
  key: string;
  kind: DatabricksTaskKind;
  /** Notebook path, SQL file, condition expression or for-each inputs. */
  detail: string;
  runIf: string;
  dependsOn: { taskKey: string; outcome?: string }[];
  compute: string;
  maxRetries: number;
  timeoutSeconds: number;
  parameters: Record<string, string>;
  inner?: DatabricksTaskDesignView;
}

/** A job file as the host reads it for the canvas; the runtime validates it when it runs. */
export interface DatabricksJobDesignView {
  name: string;
  /** Workspace-relative path of the job file. */
  path: string;
  description: string;
  parameters: { name: string; defaultValue: string }[];
  runAs?: string;
  schedule?: string;
  clusters: { key: string; label: string }[];
  tasks: DatabricksTaskDesignView[];
  error?: string;
}

export interface DatabricksViewState {
  exists: boolean;
  jobs: DatabricksJobDesignView[];
  notebooks: string[];
  sqlFiles: string[];
  warnings: string[];
}

export type DatabricksTaskBehavior = "success" | "fail_once" | "fail_twice" | "fail_always";

export interface DatabricksTaskBehaviorInput {
  behavior: DatabricksTaskBehavior;
  durationSeconds?: number;
  /** JSON object text: task values the task sets in a dry run. */
  values?: string;
}

export type DatabricksTriggerType = "one_time" | "periodic" | "file_arrival" | "table" | "continuous";

export interface DatabricksScenarioInput {
  /** local: notebook and SQL tasks run on the local catalog; simulated: dry run. */
  dataPlane: "local" | "simulated";
  /** Text as typed; blank keeps the job's default. */
  jobParameters: Record<string, string>;
  tasks: Record<string, DatabricksTaskBehaviorInput>;
  triggerType: DatabricksTriggerType;
  /** UTC "YYYY-MM-DDTHH:MM": the run's start time. */
  now?: string;
  clusterStates: Record<string, "RUNNING" | "TERMINATED">;
}

export interface DatabricksAttemptView {
  number: number;
  startS: number;
  endS: number;
  status: string;
  error: string;
}

export interface DatabricksTaskRunView {
  key: string;
  kind: string;
  state: string;
  stateLabel: string;
  startS: number;
  endS: number;
  durationS: number;
  attempts: DatabricksAttemptView[];
  compute: string;
  parameters: Record<string, string>;
  outcome?: string;
  condition?: { left: string; op: string; right: string; leftExpression: string; rightExpression: string; result: boolean };
  exitValue?: string;
  values: Record<string, unknown>;
  error: string;
  errorCode: string;
  tablesWritten: string[];
  notes: string[];
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  iterations: (DatabricksTaskRunView & { input: unknown })[];
  reason: string;
}

export interface DatabricksComputeUsageView {
  key: string;
  kind: string;
  label: string;
  requestedS: number;
  readyS: number;
  endS: number;
  startupS: number;
  billedS: number;
  nodes: number;
  dbuPerHour: number;
  dbu: number;
  rate: number;
  cost: number;
  tasks: string[];
  idleAfterS: number;
  idleDbu: number;
  idleCost: number;
  notes: string[];
}

export interface DatabricksRunView {
  runId: number;
  jobId: number;
  resultState: string;
  statusLabel: string;
  explanation: string;
  leaves: string[];
  durationS: number;
  principal: string;
  startTime: string;
  triggerType: string;
  parameters: Record<string, string>;
  tasks: DatabricksTaskRunView[];
  compute: DatabricksComputeUsageView[];
  cost: { dbu: number; cost: number; idleDbu: number; idleCost: number };
  notes: string[];
}

export interface DatabricksUnityView {
  catalog: string;
  labUser: string;
  groups: Record<string, string[]>;
  grants: { privilege: string; securable: string; name: string; principal: string }[];
  owners: Record<string, string>;
  schemas: {
    name: string;
    readOnly: boolean;
    tables: { name: string; table: string; rows: number; owner: string; producer?: string }[];
    models: { name: string; owner: string; versions: number; aliases: Record<string, number> }[];
  }[];
  warnings: string[];
}

export interface DatabricksMlflowView {
  experiments: {
    name: string;
    id: string;
    runs: {
      runId: string;
      runName: string;
      status: string;
      params: Record<string, string>;
      metrics: Record<string, number>;
      models: string[];
      start: string;
      job?: string;
      task?: string;
      user?: string;
    }[];
  }[];
  models: {
    name: string;
    owner: string;
    aliases: Record<string, number>;
    versions: { version: number; runId: string; created: string; metrics: Record<string, number>; kind?: string; inputs: string[]; user?: string }[];
  }[];
}

export interface DatabricksComputeCatalogView {
  clusters: { clusterId: string; name: string; nodeType: string; workers: number; autoterminationMinutes: number; running: boolean }[];
  warehouses: { id: string; name: string; size: string; serverless: boolean }[];
}

export interface DatabricksStateView {
  truth: string;
  unity: DatabricksUnityView;
  mlflow: DatabricksMlflowView;
  computeCatalog: DatabricksComputeCatalogView;
  warnings: string[];
}

export interface DatabricksLabView {
  jobName: string;
  path: string;
  status: "simulated" | "invalid" | "error";
  truth: string;
  dataPlane: "local" | "simulated";
  issues: { path: string; message: string }[];
  warnings: string[];
  run?: DatabricksRunView;
  tablesChanged: { name: string; rows: number; producer?: string }[];
  scenario: DatabricksScenarioInput;
}

/** Cloud Lab › SQL pool: a simulated Azure Synapse dedicated SQL pool or Microsoft Fabric Data Warehouse. */
export type SqlPoolFlavor = "synapse" | "fabric";

export interface SqlPoolScriptView {
  name: string;
  /** Workspace-relative path. */
  path: string;
  /** From a "-- flavor: synapse|fabric" comment at the top of the script. */
  flavor?: SqlPoolFlavor;
}

export interface SqlPoolPlanStepView {
  operation: string;
  tables: string[];
  columns: string[];
  /** Rows moved, at scale. */
  rows: number;
  reason: string;
}

export interface SqlPoolScanView {
  table: string;
  alias: string;
  partitionsScanned: number;
  partitionsTotal: number;
  eliminated: boolean;
  reason: string;
}

export interface SqlPoolPlanView {
  analyzed: boolean;
  steps: SqlPoolPlanStepView[];
  scans: SqlPoolScanView[];
  notes: string[];
  dataMovement: boolean;
}

export interface SqlPoolStatementView {
  index: number;
  line: number;
  kind: string;
  status: "ok" | "error";
  message: string;
  target?: string;
  /** The DuckDB SQL the statement was translated to, when it ran SQL. */
  sql?: string;
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  truncated: boolean;
  plan?: SqlPoolPlanView;
  notes: string[];
  children: SqlPoolStatementView[];
}

export interface SqlPoolDistributionView {
  /** Share of the rows on each of the 60 distributions (0..1). */
  shares: number[];
  skewPct: number;
  maxSharePct: number;
  minSharePct: number;
  emptyDistributions: number;
  distinctKeys?: number;
  nullSharePct: number;
  heavyValues: { value: string; sharePct: number }[];
}

export interface SqlPoolPartitionView {
  number: number;
  lower?: string;
  upper?: string;
  rows: number;
  rowsAtScale: number;
  rowsPerDistribution?: number;
  columnstoreOk?: boolean;
}

export interface SqlPoolTableView {
  name: string;
  label: string;
  distribution: string;
  hashColumns: string[];
  index: string;
  indexColumns: string[];
  partition?: { column: string; range: string; boundaries: string[]; count: number };
  clusterBy: string[];
  constraints: { kind: string; columns: string[]; enforced: boolean }[];
  nonclusteredIndexes: { name: string; columns: string[] }[];
  statistics: { name: string; columns: string[] }[];
  rows: number;
  scaleFactor: number;
  rowsAtScale: number;
  createdBy: string;
  distributionStats?: SqlPoolDistributionView;
  partitions: SqlPoolPartitionView[];
  /** Unpartitioned clustered columnstore tables: at least 1 million rows per distribution. */
  columnstoreOk?: boolean;
}

export interface SqlPoolLabView {
  flavor: SqlPoolFlavor;
  flavorLabel: string;
  status: "ok" | "error";
  truth: string;
  scale: number;
  distributions: number;
  rowgroupTarget: number;
  /** What ran: a script path, "active editor" or "" when the tables were only described. */
  source: string;
  statements: SqlPoolStatementView[];
  tables: SqlPoolTableView[];
  warnings: string[];
}

/** The managed dbt tools environment (dbt Core, dbt-duckdb, dbt Charts), installed only on an explicit action. */
export interface DbtToolsView {
  status: "missing" | "installing" | "ready" | "error";
  python?: string;
  binDir?: string;
  /** Installed package versions (dbt-core, dbt-duckdb, duckdb, dbt-charts), read from package metadata. */
  versions?: Readonly<Record<string, string | null>>;
  detail?: string;
  progress?: { step: number; totalSteps: number; label: string; activity?: string; startedAt: number };
}

export interface DbtProjectRef {
  /** Folder relative to the workspace root, with forward slashes. */
  path: string;
  name?: string;
  profile?: string;
}

export interface DbtViewState {
  projects: readonly DbtProjectRef[];
  /** The selected project's folder (relative), when there is one. */
  selected?: string;
  tools: DbtToolsView;
  /** `.datapass/dbt/profiles.yml`, generated; no secrets. */
  profilesPath: string;
  /** What the last real dbt Core command left in target/ (manifest.json, run_results.json). */
  run?: DbtCoreRunView;
  artifactError?: string;
  /** The dbt terminal reports command start and end (VS Code shell integration), so the handoff is automatic. */
  shellIntegration?: boolean;
  /** dbt Charts boards of the selected project (charts/*.yml) and what dct last rendered for them. */
  charts?: DbtChartsView;
  /** Ticket-style missions of the dbt Lab and the learner's progress (.datapass/missions/progress.json). */
  missions?: { missions: readonly MissionView[]; progress: Readonly<Record<string, MissionProgressView>> };
}

/** Terminal Lab: the learner's shells and Git, their choice, and the lab's missions. Datapass runs no command. */
export interface TerminalViewState {
  shells: readonly ShellView[];
  /** The shell the terminal opens with: the learner's choice when installed, otherwise the first one found. */
  shell?: ShellId;
  git: GitView;
  missions: { missions: readonly MissionView[]; progress: Readonly<Record<string, MissionProgressView>> };
}

export interface DbtBoardView {
  /** Relative to the project: `charts/revenue.yml`. */
  path: string;
  /** renders/<stem>.png as a data: URI (the Workbench CSP allows data: images; nothing else is injected). */
  png?: string;
  pngAt?: string;
  /** renders/<stem>.html, when dct rendered it (opened outside the Workbench: it carries scripts). */
  html?: string;
  /** renders/<stem>.json: the resolved board with each chart's data. */
  render?: DctRenderView;
  renderError?: string;
  /** The last `dct validate --json` of this board. */
  validation?: DctValidationView;
}

export interface DbtChartsView {
  /** dbt_charts.yml at the project root. */
  configured: boolean;
  boards: readonly DbtBoardView[];
  /** The loopback `dct serve` URL while it runs. */
  serveUrl?: string;
}

export interface WorkbenchViewState {
  selectedModule: ModuleId;
  modules: readonly WorkbenchModule[];
  workspace: WorkspaceViewState;
  runtime: RuntimeViewState;
  pythonTrust: PythonTrustView;
  /** Project-portable layout from .datapass/mosaic.json, when present and valid. */
  mosaicLayout?: readonly MosaicLayoutItem[];
  /** Mosaic SQL runs and plans in this workspace, newest first (VS Code workspace state, not a project file). */
  queryHistory?: readonly QueryHistoryEntry[];
  sparkProfiles?: readonly SparkLabProfileView[];
  practice?: PracticeViewState;
  pipeline?: PipelineViewState;
  airflow?: AirflowViewState;
  factory?: FactoryViewState;
  bi?: BiViewState;
  dbt?: DbtViewState;
  terminal?: TerminalViewState;
  projects?: ProjectsViewState & ProjectsHostState;
  /** A lab tab or Practice filter to show, set when a project step opens a lab; seq changes on each request. */
  focus?: WorkbenchFocus;
}

export interface WorkbenchFocus {
  module: ModuleId;
  tab?: string;
  query?: string;
  /** Practice: the exercise (`<pack>/<problem>/<language>`) whose language the problem card should show. */
  exerciseKey?: string;
  seq: number;
}

/** What the host is doing for the Projects module: a verification in flight, or the last one's error. */
export interface ProjectsHostState {
  verifying?: { projectId: string; stepIds: string[] };
  error?: string;
}

export type HostToWebviewMessage = {
  type: "state";
  state: WorkbenchViewState;
};

export type WebviewToHostMessage =
  | { type: "ready" }
  | { type: "selectModule"; moduleId: ModuleId }
  | { type: "createManifest" }
  | { type: "openManifest" }
  | { type: "createRetailDemo" }
  | { type: "runRetailDemo" }
  | { type: "refreshCatalog" }
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
  | { type: "runActiveSparkLab"; profileId: string; aqe: boolean }
  | { type: "setTrustedPython"; enabled: boolean }
  | { type: "saveMosaicLayout"; layout: readonly { i: string; x: number; y: number; w: number; h: number }[] }
  | { type: "setupRuntime" }
  | { type: "showRuntimeLog" }
  | { type: "startRuntime" }
  | { type: "stopRuntime" }
  | { type: "openTerminal" }
  | { type: "openScratch"; kind: ScratchKind }
  | { type: "openExercise"; exerciseKey: string }
  | { type: "gradeExercise"; exerciseKey: string; mode: "run" | "submit" }
  | { type: "revealHint"; exerciseKey: string }
  | { type: "showSolution"; exerciseKey: string }
  | { type: "compareSolution"; exerciseKey: string }
  | { type: "openPipelineSource" }
  | { type: "refreshPipeline" }
  | { type: "runPipeline" }
  | { type: "openAirflowSource" }
  | { type: "refreshAirflow" }
  | { type: "simulateAirflow"; scenario: AirflowScenarioInput }
  | { type: "revealAirflowLine"; line: number }
  | { type: "createFactoryLab" }
  | { type: "refreshFactory" }
  | { type: "openFactoryFile"; path: string }
  | { type: "revealFactoryActivity"; path: string; activity: string }
  | { type: "simulateFactory"; flavor: FactoryFlavor; name: string; scenario: FactoryScenarioInput }
  | { type: "runSqlPool"; flavor: SqlPoolFlavor; scale: number; source: "file" | "active" | "describe"; path?: string }
  | { type: "revealSqlPoolLine"; line: number }
  | { type: "simulateDatabricks"; name: string; scenario: DatabricksScenarioInput }
  | { type: "refreshDatabricksState" }
  | { type: "createBiLab" }
  | { type: "refreshBi" }
  | { type: "openBiFile"; path: string }
  | { type: "runBiLab"; mode: BiRunMode }
  | { type: "revealBiLine"; path: string; line: number }
  | { type: "runBiDbt"; command: BiDbtCommand; select: string; fullRefresh: boolean }
  | { type: "createDbtSample" }
  | { type: "selectDbtProject"; path: string }
  | { type: "refreshDbt" }
  | { type: "installDbtTools" }
  | { type: "showDbtToolsLog" }
  | { type: "runDbtCommand"; command: DbtCommand; select: string; exclude: string; fullRefresh: boolean }
  | { type: "openDbtTerminal" }
  | { type: "openDbtFile"; path: string }
  | { type: "reattachCatalog" }
  | { type: "runDct"; action: "validate" | "render"; board: string; format?: DctFormat }
  | { type: "serveDct" }
  | { type: "stopDctServe" }
  | { type: "openDctHtml"; board: string }
  | { type: "selectTerminalShell"; shell: ShellId }
  | { type: "openLabTerminal"; missionId?: string }
  | { type: "refreshTerminalLab" }
  | { type: "startMission"; missionId: string }
  | { type: "restartMission"; missionId: string }
  | { type: "openMission"; missionId: string }
  | { type: "loadMissionBatch"; missionId: string }
  | { type: "revealMissionHint"; missionId: string }
  | { type: "checkMission"; missionId: string }
  | { type: "prepareProject"; projectId: string }
  | { type: "openProjectStep"; projectId: string; stepId: string }
  | { type: "verifyProjectSteps"; projectId: string; stepIds: string[] }
  | { type: "setProjectStepManual"; projectId: string; stepId: string; checked: boolean }
  | { type: "openProgressFile" };
