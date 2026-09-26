import { runtimeErrorDetail } from "../../platform/runtimeClient";
import type { RuntimeConnection } from "../runtimeConnection";

/** Missions (dbt Lab, Terminal Lab, Infra Lab): fixtures from the shipped pack and the hidden checker. */
export class MissionsClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /** Missions: load one fixture batch of a shipped mission (the first one starts the mission over). */
  async missionSetup(missionId: string, batchId: string): Promise<void> {
    const url = this.runtime.requireAttached("load a mission's data");
    try {
      await this.runtime.postJson<unknown>(`${url}/api/local/missions/setup`, { mission_id: missionId, batch_id: batchId }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
    await this.runtime.refreshCatalog();
  }

  /**
   * Terminal Lab and Infra Lab missions: the runtime (re)builds `missions/<id>/` from the shipped pack (files and Git
   * history, or files and a simulated world). The catalog is not involved, so a lent catalog does not block it.
   */
  async terminalMissionSetup(missionId: string): Promise<{ folder: string; previous?: string | null }> {
    const url = this.runtime.requireRunning("start a mission");
    try {
      return await this.runtime.postJson<{ folder: string; previous?: string | null }>(`${url}/api/local/missions/setup`, { mission_id: missionId }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }

  /**
   * Missions: the hidden checker. `dct` carries the real `dct validate --json` results for the mission's boards. A
   * Terminal Lab mission reads files and Git only (`catalog: false`), so a lent catalog does not block it.
   */
  async missionCheck(missionId: string, dct: Record<string, unknown>, catalog = true): Promise<unknown> {
    const url = catalog ? this.runtime.requireAttached("check a mission") : this.runtime.requireRunning("check a mission");
    try {
      return await this.runtime.postJson<unknown>(`${url}/api/local/missions/check`, { mission_id: missionId, dct }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }
}
