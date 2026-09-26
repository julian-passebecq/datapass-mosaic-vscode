import type { GraphView } from "./graph";

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

export interface PipelineRuntimeSlice {
  pipelineRun?: PipelineRunView;
}

export interface PipelineViewSlice {
  pipeline?: PipelineViewState;
}

export type PipelineMessage =
  | { type: "openPipelineSource" }
  | { type: "refreshPipeline" }
  | { type: "runPipeline" };
