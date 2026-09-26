import { runtimeErrorDetail } from "../../platform/runtimeClient";
import type { RuntimeConnection } from "../runtimeConnection";

/** Projects: step checks run by the runtime on the workspace catalog and its run journal. */
export class ProjectsClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /**
   * Projects: the runtime verifies steps of a shipped project on the workspace catalog and its run journal.
   * The caller keeps the result in .datapass/progress.json; manual steps are never verified.
   */
  async checkProject(projectId: string, steps: string[]): Promise<unknown> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before verifying project steps.");
    try {
      return await this.runtime.postJson<unknown>(`${url}/api/local/projects/check`, { project_id: projectId, steps }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }
}
