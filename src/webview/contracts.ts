import type { ModuleId, WorkbenchModule } from "../modules";

export type RuntimeStatus = "stopped" | "starting" | "running" | "error";
export type ScratchKind = "sql" | "python" | "notes";

export interface RuntimeViewState {
  status: RuntimeStatus;
  url?: string;
  detail?: string;
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
  title: string;
  difficulty: string;
  language: string;
  prompt: string;
  starterSource: string;
  truth?: string;
  topics: string[];
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
  | { type: "startRuntime" }
  | { type: "stopRuntime" }
  | { type: "openTerminal" }
  | { type: "openScratch"; kind: ScratchKind }
  | { type: "openExercise"; exerciseKey: string }
  | { type: "openPipelineSource" }
  | { type: "refreshPipeline" }
  | { type: "openAirflowSource" }
  | { type: "refreshAirflow" }
  | { type: "openDbtProject" }
  | { type: "refreshDbt" }
  | { type: "runDbtBuild" };
