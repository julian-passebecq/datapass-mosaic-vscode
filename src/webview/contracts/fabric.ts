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

/** Cloud Lab (module id `fabric`): the retail demo and the Pipelines, SQL pool and Databricks tabs. */
export interface FabricRuntimeSlice {
  factoryRun?: FactoryLabView;
  sqlpoolRun?: SqlPoolLabView;
  databricksRun?: DatabricksLabView;
  /** Unity Catalog, MLflow and compute of the Databricks tab, refreshed after each job run. */
  databricksState?: DatabricksStateView;
  retailDemo?: RetailDemoRunView;
}

export interface FabricViewSlice {
  factory?: FactoryViewState;
}

export type FabricMessage =
  | { type: "createRetailDemo" }
  | { type: "runRetailDemo" }
  | { type: "createFactoryLab" }
  | { type: "refreshFactory" }
  | { type: "openFactoryFile"; path: string }
  | { type: "revealFactoryActivity"; path: string; activity: string }
  | { type: "simulateFactory"; flavor: FactoryFlavor; name: string; scenario: FactoryScenarioInput }
  | { type: "runSqlPool"; flavor: SqlPoolFlavor; scale: number; source: "file" | "active" | "describe"; path?: string }
  | { type: "revealSqlPoolLine"; line: number }
  | { type: "simulateDatabricks"; name: string; scenario: DatabricksScenarioInput }
  | { type: "refreshDatabricksState" };
