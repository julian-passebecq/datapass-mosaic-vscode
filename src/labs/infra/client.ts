import { runtimeErrorDetail } from "../../platform/runtimeClient";
import type { RuntimeConnection } from "../runtimeConnection";

/** One line of the Infra Lab's simulated shell, as the runtime answers it. */
export interface InfraCommandResult {
  output: string;
  exit_code: number;
  /** A question to ask before the command goes on (terraform apply's "Enter a value"). */
  prompt?: string | null;
  tool?: string | null;
}

/** Infra Lab: everything is simulated by the runtime (runtime/infralab); no real terraform, docker, kubectl or az. */
export class InfraClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /**
   * Infra Lab: one line of the simulated shell in `folder` (relative to the workspace). Everything is simulated by
   * the runtime (runtime/infralab); `answer` replies to a prompt such as terraform apply's "Enter a value".
   */
  async infraCommand(folder: string, line: string, answer?: string): Promise<InfraCommandResult> {
    const url = this.runtime.requireRunning("use the Infra Lab shell");
    try {
      return await this.runtime.postJson<InfraCommandResult>(`${url}/api/local/infra/command`,
        answer === undefined ? { folder, line } : { folder, line, answer }, 120000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }

  /** Infra Lab: what the simulated world of `folder` holds (Terraform state, subscription, Docker, cluster). */
  async infraState(folder: string): Promise<unknown> {
    const url = this.runtime.requireRunning("read the Infra Lab's simulated world");
    try {
      return await this.runtime.postJson<unknown>(`${url}/api/local/infra/state`, { folder }, 30000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }
}
