import * as vscode from "vscode";
import { safeRelativeParts } from "../../platform/workspacePaths";
import { readProjectManifest } from "../../project/projectManifest";
import { pipelineStarter } from "../../scaffold/starters";
import type { PipelineMessage } from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";

/** Pipeline Lab: <assets.pipelines>/main.pipeline.py, compiled and run by the runtime (never eval/exec'd). */
export class PipelineController implements LabController<PipelineMessage> {
  readonly refreshOnSave = "pipeline" as const;

  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<PipelineMessage> = {
    openPipelineSource: () => this.openPipelineSource(),
    refreshPipeline: () => this.host.refresh(),
    runPipeline: () => this.runPipeline()
  };

  private async runPipeline(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before running a pipeline.");
      return;
    }
    const manifest = await readProjectManifest();
    const pipelineRoot = safeRelativeParts(manifest.manifest?.assets?.pipelines, "pipelines");
    const uri = vscode.Uri.joinPath(root, ...pipelineRoot, "main.pipeline.py");
    if (!(await exists(uri))) {
      await this.openPipelineSource();
      return;
    }

    const source = new TextDecoder().decode(await vscode.workspace.fs.readFile(uri));
    try {
      await this.host.runtime.labs.pipeline.runPipeline(source);
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Pipeline execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }

  /** Create the starter pipeline if it is missing, and open it beside the Workbench. */
  async openPipelineSource(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating a Datapass pipeline.");
      return;
    }

    const manifest = await readProjectManifest();
    const pipelineRoot = safeRelativeParts(manifest.manifest?.assets?.pipelines, "pipelines");
    const directory = vscode.Uri.joinPath(root, ...pipelineRoot);
    const uri = vscode.Uri.joinPath(directory, "main.pipeline.py");

    await vscode.workspace.fs.createDirectory(directory);
    if (!(await exists(uri))) {
      await vscode.workspace.fs.writeFile(
        uri,
        new TextEncoder().encode(pipelineStarter())
      );
    }

    await this.host.openBeside(uri);
    await this.host.refresh();
  }
}
