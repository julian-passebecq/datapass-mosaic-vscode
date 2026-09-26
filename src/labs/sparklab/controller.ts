import * as vscode from "vscode";
import type { SparkLabMessage } from "../../webview/contracts";
import { activeSavedDocument, type LabController, type MessageHandlers, type WorkbenchHost } from "../host";

/** SparkLab: the active .py file on the bounded SparkLab runtime (never executed as Python). */
export class SparkLabController implements LabController<SparkLabMessage> {
  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<SparkLabMessage> = {
    runActiveSparkLab: message => this.runActiveSparkLab(message.profileId, message.aqe)
  };

  private async runActiveSparkLab(profileId: string, aqe: boolean): Promise<void> {
    const document = await activeSavedDocument(".py", "SparkLab (.py)", this.host.lastDocument(".py"));
    if (!document) return;

    try {
      await this.host.runtime.labs.sparklab.runSparkLab(
        document.getText(),
        vscode.workspace.asRelativePath(document.uri),
        profileId,
        aqe
      );
    } catch (error) {
      void vscode.window.showErrorMessage(
        `SparkLab execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }
}
