import { runtimeErrorDetail } from "../../platform/runtimeClient";
import type { RuntimeConnection } from "../runtimeConnection";

/**
 * Lakehouse Lab (runtime/lakehouselab): mission folders under lakehouse/<id>/, the learner's SQL run on DuckDB in a
 * process bounded to that folder (or their Polars file as trusted Python), and the hidden checker. The shared catalog
 * is not involved, so a lent catalog does not block it.
 */
export class LakehouseClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  missions(): Promise<unknown> {
    return this.post("list the Lakehouse missions", "missions", {}, 30000);
  }

  start(missionId: string): Promise<{ folder: string; previous?: string | null }> {
    return this.post("start a mission", "start", { mission_id: missionId }, 180000) as Promise<{ folder: string; previous?: string | null }>;
  }

  run(missionId: string, engine: "duckdb" | "polars"): Promise<unknown> {
    return this.post("run the mission's file", "run", { mission_id: missionId, engine }, 240000);
  }

  check(missionId: string): Promise<unknown> {
    return this.post("check a mission", "check", { mission_id: missionId }, 180000);
  }

  storage(missionId: string): Promise<unknown> {
    return this.post("read the mission's storage", "storage", { mission_id: missionId }, 60000);
  }

  private async post(what: string, route: string, body: unknown, timeout: number): Promise<unknown> {
    const url = this.runtime.requireRunning(what);
    try {
      return await this.runtime.postJson<unknown>(`${url}/api/local/lakehouse/${route}`, body, timeout);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }
}
