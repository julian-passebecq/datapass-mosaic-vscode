import * as vscode from "vscode";
import type { SparkLabEngine, SparkLabMessage } from "../../webview/contracts";
import { activeSavedDocument, type LabController, type MessageHandlers, type WorkbenchHost } from "../host";

/**
 * Spark Lab: the active .py file on the bounded SparkLab runtime (never executed as Python), or on real
 * Polars when the learner picks the Polars engine (trusted local Python only; the runtime enforces it).
 */
export class SparkLabController implements LabController<SparkLabMessage> {
  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<SparkLabMessage> = {
    runActiveSparkLab: message => this.runActiveSparkLab(message.engine ?? "sparklab", message.profileId, message.aqe)
  };

  private async runActiveSparkLab(engine: SparkLabEngine, profileId: string, aqe: boolean): Promise<void> {
    const label = engine === "polars" ? "Polars" : "SparkLab";
    const document = await activeSavedDocument(".py", `${label} (.py)`, this.host.lastDocument(".py"));
    if (!document) return;

    try {
      await this.host.runtime.labs.sparklab.runSparkLab(
        document.getText(),
        vscode.workspace.asRelativePath(document.uri),
        profileId,
        aqe,
        engine
      );
    } catch (error) {
      void vscode.window.showErrorMessage(
        `${label} execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }
}
