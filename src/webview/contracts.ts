import type { ModuleId, WorkbenchModule } from "../modules";
import type { MosaicLayoutItem } from "../platform/mosaicLayout";
import type { PythonTrustState } from "../platform/pythonTrust";

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
}

export interface RuntimeViewState {
  status: RuntimeStatus;
  url?: string;
  detail?: string;
  /** Reported by the running runtime itself (GET /api/capabilities), not assumed. */
  trustedPython?: boolean;
  sparkRun?: SparkLabRunView;
  retailDemo?: RetailDemoRunView;
  catalog?: readonly LocalCatalogAssetView[];
  lastRun?: LocalCellRunView;
  pipelineRun?: PipelineRunView;
  practiceResult?: PracticeResultView;
  environment?: RuntimeEnvironmentView;
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
  prompt: string;
  starterSource: string;
  truth?: string;
  topics: string[];
}

export interface ExerciseCheckView {
  id: string;
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
}

export interface GraphNodeView {
  id: string;
  label: string;
  detail: string;
  truth?: string;
}

export interface GraphEdgeView {
  id: string;
  source: string;
  target: string;
  label: string;
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

export type AirflowTriggerRule = "all_success" | "all_done" | "none_failed_min_one_success";
export type AirflowFailureMode = "none" | "transient" | "permanent";

export interface AirflowTaskView {
  id: string;
  label: string;
  type: "task" | "sensor" | "quality" | "branch";
  dependsOn: string[];
  retries: number;
  retryDelaySeconds: number;
  durationSeconds: number;
  triggerRule: AirflowTriggerRule;
  failureMode: AirflowFailureMode;
}

export interface AirflowDefinitionView {
  dagId: string;
  schedule: string;
  tasks: readonly AirflowTaskView[];
}

export interface AirflowViewState {
  exists: boolean;
  path: string;
  valid: boolean;
  errors: readonly string[];
  definition?: AirflowDefinitionView;
  graph: GraphView;
}

export interface DbtCliView {
  available: boolean;
  adapterAvailable: boolean;
  version?: string;
  adapterVersion?: string;
  detail?: string;
}

export interface DbtViewState {
  exists: boolean;
  path: string;
  projectName?: string;
  modelCount: number;
  seedCount: number;
  lineageSource: "manifest" | "static" | "none";
  graph: GraphView;
  errors: readonly string[];
  cli: DbtCliView;
}

export interface WorkbenchViewState {
  selectedModule: ModuleId;
  modules: readonly WorkbenchModule[];
  workspace: WorkspaceViewState;
  runtime: RuntimeViewState;
  pythonTrust: PythonTrustView;
  /** Project-portable layout from .datapass/mosaic.json, when present and valid. */
  mosaicLayout?: readonly MosaicLayoutItem[];
  sparkProfiles?: readonly SparkLabProfileView[];
  practice?: PracticeViewState;
  pipeline?: PipelineViewState;
  airflow?: AirflowViewState;
  dbt?: DbtViewState;
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
  | { type: "runActiveSql" }
  | { type: "runActivePython" }
  | { type: "runActiveSparkLab"; profileId: string; aqe: boolean }
  | { type: "setTrustedPython"; enabled: boolean }
  | { type: "saveMosaicLayout"; layout: readonly { i: string; x: number; y: number; w: number; h: number }[] }
  | { type: "setupRuntime" }
  | { type: "startRuntime" }
  | { type: "stopRuntime" }
  | { type: "openTerminal" }
  | { type: "openScratch"; kind: ScratchKind }
  | { type: "openExercise"; exerciseKey: string }
  | { type: "gradeExercise"; exerciseKey: string; mode: "run" | "submit" }
  | { type: "openPipelineSource" }
  | { type: "refreshPipeline" }
  | { type: "runPipeline" }
  | { type: "openAirflowSource" }
  | { type: "refreshAirflow" }
  | { type: "openDbtProject" }
  | { type: "refreshDbt" }
  | { type: "runDbtBuild" };
