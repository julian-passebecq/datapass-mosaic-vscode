import * as vscode from "vscode";
import { MODULES, type ModuleId } from "./modules";
import { createDefaultProjectManifest, readProjectManifest, writeProjectManifest } from "./project/projectManifest";
import type { RuntimeManager } from "./runtimeManager";
import { collectWorkbenchState } from "./workbenchState";
import { contentSecurityPolicy, makeNonce } from "./webview/security";
import type { WebviewToHostMessage } from "./webview/contracts";

export class WorkbenchPanel {
  private static current?: WorkbenchPanel;

  static async show(
    context: vscode.ExtensionContext,
    runtimeManager: RuntimeManager,
    initialModule: ModuleId
  ): Promise<void> {
    if (WorkbenchPanel.current) {
      WorkbenchPanel.current.selectedModule = initialModule;
      WorkbenchPanel.current.panel.reveal(vscode.ViewColumn.One, true);
      await WorkbenchPanel.current.refresh();
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      "datapass.workbench",
      "Datapass Workbench",
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "dist")]
      }
    );

    WorkbenchPanel.current = new WorkbenchPanel(
      panel,
      context,
      runtimeManager,
      initialModule
    );
  }

  private selectedModule: ModuleId;
  private readonly disposables: vscode.Disposable[] = [];

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly context: vscode.ExtensionContext,
    private readonly runtimeManager: RuntimeManager,
    initialModule: ModuleId
  ) {
    this.selectedModule = initialModule;
    this.panel.webview.html = this.html(this.panel.webview);

    this.disposables.push(
      this.panel.onDidDispose(() => this.dispose()),
      this.panel.webview.onDidReceiveMessage(message => {
        void this.handleMessage(message as WebviewToHostMessage);
      }),
      this.runtimeManager.onDidChange(() => {
        void this.refresh();
      })
    );
  }

  private async handleMessage(message: WebviewToHostMessage): Promise<void> {
    switch (message.type) {
      case "ready":
        await this.refresh();
        return;
      case "selectModule":
        if (MODULES.some(module => module.id === message.moduleId)) {
          this.selectedModule = message.moduleId;
          await this.refresh();
        }
        return;
      case "createManifest":
        await this.createManifest();
        return;
      case "openManifest":
        await this.openManifest();
        return;
      case "startRuntime": {
        const manifest = await readProjectManifest();
        const pythonCommand = manifest.manifest?.runtime?.pythonCommand ?? "python";
        await this.runtimeManager.start(pythonCommand);
        return;
      }
      case "stopRuntime":
        this.runtimeManager.stop();
        return;
      case "openTerminal":
        await vscode.commands.executeCommand("workbench.action.terminal.new");
        return;
    }
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
    await openTextDocument(uri);
    await this.refresh();
  }

  private async openManifest(): Promise<void> {
    const manifest = await readProjectManifest();
    if (!manifest.uri || !manifest.exists) {
      void vscode.window.showInformationMessage("No .datapass/project.json exists yet.");
      return;
    }
    await openTextDocument(manifest.uri);
  }

  private async refresh(): Promise<void> {
    const state = await collectWorkbenchState(this.selectedModule, this.runtimeManager);
    await this.panel.webview.postMessage({ type: "state", state });
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "dist", "webview.js")
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "dist", "webview.css")
    );

    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="${contentSecurityPolicy(webview, nonce)}">
  <link rel="stylesheet" href="${styleUri}">
  <title>Datapass Workbench</title>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }

  private dispose(): void {
    if (WorkbenchPanel.current === this) {
      WorkbenchPanel.current = undefined;
    }
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }
}

async function openTextDocument(uri: vscode.Uri): Promise<void> {
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document, { preview: false });
}
