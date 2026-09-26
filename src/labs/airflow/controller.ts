import * as vscode from "vscode";
import { AIRFLOW_STARTER_FILE, airflowPaths } from "../../airflowState";
import { airflowStarter } from "../../scaffold/starters";
import type { AirflowMessage, AirflowScenarioInput } from "../../webview/contracts";
import { exists, writeIfMissing } from "../../workspaceFiles";
import { atLine, type LabController, type MessageHandlers, type WorkbenchHost } from "../host";

/** Airflow Lab: DAG files parsed and simulated by the runtime (never eval/exec'd). */
export class AirflowController implements LabController<AirflowMessage> {
  readonly refreshOnSave = "airflow" as const;
  /** The DAG file Airflow Lab last simulated, to reveal a parser error line in it. */
  private lastAirflowFile?: vscode.Uri;

  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<AirflowMessage> = {
    openAirflowSource: () => this.openAirflowSource(),
    refreshAirflow: () => this.host.refresh(),
    simulateAirflow: message => this.simulateAirflow(message.scenario),
    revealAirflowLine: message => this.revealAirflowLine(message.line)
  };

  /** Create the starter DAG if it is missing, and open it beside the Workbench. */
  async openAirflowSource(): Promise<void> {
    const { root, dagsParts } = await airflowPaths();
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating an Airflow Lab DAG.");
      return;
    }
    const directory = vscode.Uri.joinPath(root, ...dagsParts);
    const uri = vscode.Uri.joinPath(directory, AIRFLOW_STARTER_FILE);
    await vscode.workspace.fs.createDirectory(directory);
    await writeIfMissing(uri, airflowStarter());
    await this.host.openBeside(uri);
    await this.host.refresh();
  }

  /** Simulate the active Airflow DAG file (or the starter). The runtime parses it; nothing is executed. */
  private async simulateAirflow(scenario: AirflowScenarioInput): Promise<void> {
    const document = await this.activeAirflowDocument();
    if (!document) return;
    this.lastAirflowFile = document.uri;
    try {
      await this.host.runtime.labs.airflow.simulateAirflow(
        document.getText(),
        vscode.workspace.asRelativePath(document.uri),
        scenario
      );
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Airflow simulation failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }

  private async activeAirflowDocument(): Promise<vscode.TextDocument | undefined> {
    const isDag = (document: vscode.TextDocument | undefined): document is vscode.TextDocument =>
      document?.uri.scheme === "file" && document.fileName.toLowerCase().endsWith(".py") &&
      /\bairflow\b/.test(document.getText());
    const remembered = this.host.lastDocument(".py")?.toString();
    let document =
      (isDag(vscode.window.activeTextEditor?.document) ? vscode.window.activeTextEditor!.document : undefined) ??
      vscode.window.visibleTextEditors.map(editor => editor.document).find(isDag) ??
      vscode.workspace.textDocuments.find(candidate => !candidate.isClosed && isDag(candidate) && candidate.uri.toString() === remembered);
    if (!document) {
      const { root, dagsParts } = await airflowPaths();
      const starter = root ? vscode.Uri.joinPath(root, ...dagsParts, AIRFLOW_STARTER_FILE) : undefined;
      if (!starter || !(await exists(starter))) {
        void vscode.window.showWarningMessage("Open an Airflow DAG file (.py), or create the starter DAG first.");
        return undefined;
      }
      document = await vscode.workspace.openTextDocument(starter);
    }
    if (document.isDirty && !(await document.save())) {
      void vscode.window.showWarningMessage("Save the DAG file before simulating it.");
      return undefined;
    }
    return document;
  }

  private async revealAirflowLine(line: number): Promise<void> {
    if (!this.lastAirflowFile || !Number.isInteger(line) || line < 1) return;
    await this.host.revealBeside(this.lastAirflowFile, atLine(line));
  }
}
