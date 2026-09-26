import { runtimeErrorDetail } from "../../platform/runtimeClient";
import type { ApiLabApiView, ApiLabRunView } from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

/**
 * API Lab: the runtime starts a simulated REST API on its own loopback port (runtime/apilab) and runs the learner's
 * ingest.py as trusted local Python against it. This client only talks to the runtime (with its launch token, which
 * the simulated API never sees).
 */
export class ApiLabClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /** Start (over): the mission's files, its bronze tables dropped, a fresh simulated API with a new key. */
  async start(missionId: string): Promise<void> {
    await this.post("start an API Lab mission", "start", { mission_id: missionId }, 60000, true);
    await this.runtime.refreshCatalog();
  }

  /** The next day of the simulated API (new and updated records, a schema change). */
  async advance(missionId: string, batchId: string): Promise<void> {
    await this.post("load the next day of the API", "advance", { mission_id: missionId, batch_id: batchId }, 30000);
  }

  /** Run missions/<id>/ingest.py (refused while trusted Python is off). */
  async run(missionId: string): Promise<ApiLabRunView> {
    const result = await this.post<ApiLabRunView>("run the ingestion", "run", { mission_id: missionId }, 90000, true);
    await this.runtime.refreshCatalog();
    return result;
  }

  /** The hidden checker: read-only SQL on bronze and the simulated API's request log. */
  async check(missionId: string): Promise<unknown> {
    return this.post("check a mission", "check", { mission_id: missionId }, 60000, true);
  }

  /** The simulated API of a mission (or the active one): URL, key, day, runs, last requests. */
  async state(missionId?: string): Promise<ApiLabApiView> {
    return this.post("read the API Lab", "state", missionId ? { mission_id: missionId } : {}, 15000);
  }

  private async post<T>(action: string, route: string, body: unknown, timeoutMs: number, catalog = false): Promise<T> {
    const url = catalog ? this.runtime.requireAttached(action) : this.runtime.requireRunning(action);
    try {
      return await this.runtime.postJson<T>(`${url}/api/local/apilab/${route}`, body, timeoutMs);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }
}
