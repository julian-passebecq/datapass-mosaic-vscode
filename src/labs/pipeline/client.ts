import type { PipelineRunView } from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

export interface PipelineCompileResponse {
  valid: boolean;
  source_hash: string;
  truth: string;
  diagnostics: Array<{ line: number; column: number; message: string }>;
  ir: null | {
    id: string;
    schedule: string | null;
    tasks: Array<{
      id: string;
      kind: string;
      retries: number;
      retry_delay: number;
    }>;
    edges: Array<{ source: string; target: string }>;
  };
}

/** Pipeline Lab: the source is compiled by the runtime's bounded AST compiler, never eval/exec'd. */
export class PipelineClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  async runPipeline(source: string): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running a pipeline.");
    const pipelineRun = await this.runtime.postJson<PipelineRunView>(
      `${url}/api/pipeline/run`,
      { source },
      30000
    );
    this.runtime.update({
      detail: pipelineRun.status === "success"
        ? `Pipeline ${pipelineRun.pipeline_id} completed.`
        : `Pipeline ${pipelineRun.pipeline_id} finished with failures.`,
      pipelineRun
    });
    await this.runtime.refreshCatalog();
  }

  async compilePipeline(source: string): Promise<PipelineCompileResponse> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before compiling a pipeline.");
    return this.runtime.postJson<PipelineCompileResponse>(
      `${url}/api/pipeline/compile`,
      { source }
    );
  }
}
