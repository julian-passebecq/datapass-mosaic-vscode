import { toAirflowLabView, toRuntimeScenario } from "../../platform/airflowRun";
import type { AirflowScenarioInput } from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

/** Airflow Lab: a deterministic scheduling simulator; DAG files are parsed, never executed. */
export class AirflowClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /** Airflow Lab: the DAG file's TEXT is parsed and simulated by the runtime, never executed. */
  async simulateAirflow(source: string, fileName: string, scenario: AirflowScenarioInput): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before simulating an Airflow DAG.");
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/airflow/simulate`,
      { source, scenario: toRuntimeScenario(scenario) },
      20000
    );
    const airflowRun = toAirflowLabView(raw, fileName, scenario);
    this.runtime.update({
      detail: airflowRun.status === "simulated"
        ? `Airflow DAG ${airflowRun.dag?.dagId ?? ""} simulated: ${airflowRun.totalRuns} run(s); nothing was executed.`
        : `Airflow DAG not simulated: ${airflowRun.error?.message ?? "unknown error"}`,
      airflowRun
    });
  }
}
