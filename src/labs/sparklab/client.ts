import { toSparkLabRunView } from "../../platform/sparkLabRun";
import type { SparkLabEngine } from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

/** SparkLab: bounded PySpark-style files, or the same lesson in real Polars. */
export class SparkLabClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /**
   * SparkLab: whitelisted AST to local SQL, never executed as Python. Polars: real local Python, which the
   * runtime refuses unless trusted Python is enabled; no simulated Polars output is ever returned.
   */
  async runSparkLab(code: string, fileName: string, profileId: string, aqe: boolean, engine: SparkLabEngine = "sparklab"): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running the Spark Lab.");
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/execute`,
      engine === "polars"
        ? { language: "polars", code, notebook_id: "vscode-sparklab-polars", cell_id: "active-polars" }
        : { language: "sparklab", code, notebook_id: "vscode-sparklab", cell_id: "active-sparklab", profile: profileId, aqe },
      25000
    );
    const sparkRun = toSparkLabRunView(raw, { engine, fileName, profileId, aqe });
    const label = engine === "polars" ? "Polars" : "SparkLab";
    this.runtime.update({
      detail: sparkRun.status === "success"
        ? engine === "polars"
          ? `Polars result computed by real local Polars in ${sparkRun.elapsed_ms.toFixed(1)} ms.`
          : `SparkLab result computed locally in ${sparkRun.elapsed_ms.toFixed(1)} ms; distributed metrics are simulated.`
        : `${label} rejected or failed: ${sparkRun.error?.message ?? "Unknown error"}`,
      sparkRun
    });
    await this.runtime.refreshCatalog();
  }
}
