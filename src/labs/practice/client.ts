import type { PracticeResultView } from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

/** What the runtime grades: the learner's solution file for one exercise version. */
export interface GradeRequest {
  exercise_id: string;
  exercise_version: string;
  language: string;
  code: string;
  mode: "run" | "submit";
  notebook_id: string;
  cell_id: string;
  source_revision: number;
}

/** Practice: real grading through the shared runtime. */
export class PracticeClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  async gradeExercise(exerciseKey: string, request: GradeRequest): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before grading an exercise.");
    const result = await this.runtime.postJson<Omit<PracticeResultView, "exerciseKey" | "mode">>(
      `${url}/api/local/exercise`,
      request,
      30000
    );
    this.runtime.update({
      detail: request.mode === "submit"
        ? `Exercise submission: ${result.status}.`
        : `Visible exercise checks: ${result.status}.`,
      practiceResult: {
        ...result,
        exerciseKey,
        mode: request.mode
      }
    });
  }
}
