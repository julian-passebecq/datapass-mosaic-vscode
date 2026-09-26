import { toSparkLabRunView } from "../../platform/sparkLabRun";
import type { RuntimeConnection } from "../runtimeConnection";

/** SparkLab: bounded PySpark-style files. */
export class SparkLabClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /** Bounded SparkLab: whitelisted AST to local SQL. Never executed as Python. */
  async runSparkLab(code: string, fileName: string, profileId: string, aqe: boolean): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running SparkLab.");
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/execute`,
      {
        language: "sparklab",
        code,
        notebook_id: "vscode-sparklab",
        cell_id: "active-sparklab",
        profile: profileId,
        aqe
      },
      25000
    );
    const sparkRun = toSparkLabRunView(raw, { fileName, profileId, aqe });
    this.runtime.update({
      detail: sparkRun.status === "success"
        ? `SparkLab result computed locally in ${sparkRun.elapsed_ms.toFixed(1)} ms; distributed metrics are simulated.`
        : `SparkLab rejected or failed: ${sparkRun.error?.message ?? "Unknown error"}`,
      sparkRun
    });
    await this.runtime.refreshCatalog();
  }
}
