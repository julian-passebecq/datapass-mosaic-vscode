import * as vscode from "vscode";
import { MODULES } from "../../modules";
import { createDefaultProjectManifest, readProjectManifest, writeProjectManifest } from "../../project/projectManifest";
import type { WorkbenchMessage } from "../../webview/contracts";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";

/** The Workbench shell: module tabs, the runtime card (setup, start, stop, trusted Python), the manifest, the catalog. */
export class WorkbenchController implements LabController<WorkbenchMessage> {
  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<WorkbenchMessage> = {
    ready: () => this.host.refresh(),
    selectModule: async message => {
      if (MODULES.some(module => module.id === message.moduleId)) {
        this.host.showModule(message.moduleId);
        await this.host.refresh();
      }
    },
    createManifest: () => this.createManifest(),
    openManifest: () => this.openManifest(),
    refreshCatalog: () => this.host.runtime.refreshCatalog(),
    reattachCatalog: async () => {
      if (!(await this.host.runtime.reattachCatalog())) {
        void vscode.window.showWarningMessage(this.host.runtime.snapshot().catalogLease?.reattachError ?? "The catalog is still held.");
      }
    },
    setTrustedPython: message => this.setTrustedPython(message.enabled),
    setupRuntime: () => this.setupRuntime(),
    showRuntimeLog: () => this.host.runtime.showLog(),
    startRuntime: () => this.startRuntime(),
    stopRuntime: () => this.host.runtime.stop(),
    openTerminal: async () => {
      await vscode.commands.executeCommand("workbench.action.terminal.new");
    }
  };

  private async startRuntime(): Promise<void> {
    // The runtime's catalog lives in <workspace>/.datapass/data; without a folder every call would fail.
    if (!vscode.workspace.workspaceFolders?.length) {
      void vscode.window.showWarningMessage("Open a folder before starting the Datapass runtime; its local catalog lives in that folder.");
      return;
    }
    const manifest = await readProjectManifest();
    const pythonCommand = manifest.manifest?.runtime?.pythonCommand ?? "python";
    const storage = manifest.manifest?.runtime?.storage ?? "duckdb";
    const trust = await this.host.pythonTrust.resolve();
    await this.host.runtime.start(pythonCommand, storage, trust.effective);
  }

  private async setTrustedPython(enabled: boolean): Promise<void> {
    const changed = enabled ? await this.host.pythonTrust.enable() : await this.host.pythonTrust.disable();
    const status = this.host.runtime.snapshot().status;
    if (changed && (status === "running" || status === "starting")) {
      // Trust is fixed per runtime process, so apply it with a clean restart.
      await this.host.runtime.stopAndWait();
      await this.startRuntime();
    }
    await this.host.refresh();
  }

  private async setupRuntime(): Promise<void> {
    const manifest = await readProjectManifest();
    const pythonCommand = manifest.manifest?.runtime?.pythonCommand ?? "python";
    try {
      await this.host.runtime.setup(pythonCommand);
      void vscode.window.showInformationMessage("Datapass managed runtime is ready.");
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Datapass runtime setup failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }

  private async createManifest(): Promise<void> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating a Datapass project.");
      return;
    }

    const current = await readProjectManifest();
    if (current.exists) {
      await this.openManifest();
      return;
    }

    const uri = await writeProjectManifest(createDefaultProjectManifest(folder.name));
    await this.host.openBeside(uri);
    await this.host.refresh();
  }

  private async openManifest(): Promise<void> {
    const manifest = await readProjectManifest();
    if (!manifest.uri || !manifest.exists) {
      void vscode.window.showInformationMessage("No .datapass/project.json exists yet.");
      return;
    }
    await this.host.openBeside(manifest.uri);
  }
}
