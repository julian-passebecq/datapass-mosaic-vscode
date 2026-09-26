import * as vscode from "vscode";
import { createLabControllers } from "./labs/controllers";
import { buildMessageTable, type LabController, type LabServices, type WorkbenchHost } from "./labs/host";
import type { ModuleId, WorkbenchView } from "./modules";
import type { PythonTrustController } from "./pythonTrustController";
import type { RuntimeManager } from "./runtimeManager";
import { contentSecurityPolicy, makeNonce } from "./webview/security";
import type { WebviewToHostMessage, WorkbenchFocus } from "./webview/contracts";
import { collectWorkbenchState, type WorkbenchStateExtras } from "./workbenchState";

/**
 * The Workbench webview. It owns the panel, the state it posts and the editors it remembers; every webview message
 * goes through the message table to the lab controller that handles it (src/labs/<lab>/controller.ts).
 */
export class WorkbenchPanel implements WorkbenchHost {
  private static current?: WorkbenchPanel;

  static async show(
    context: vscode.ExtensionContext,
    runtimeManager: RuntimeManager,
    pythonTrust: PythonTrustController,
    initialModule: WorkbenchView,
    services: LabServices
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
      pythonTrust,
      initialModule,
      services
    );
  }

  /**
   * Open the Workbench on a view and hand it a webview message as if its surface had sent it: the status bar and the
   * CodeLens (src/nativeIntegration.ts) reuse the lab controllers' handlers this way.
   */
  static async dispatch(
    context: vscode.ExtensionContext,
    runtimeManager: RuntimeManager,
    pythonTrust: PythonTrustController,
    view: WorkbenchView,
    services: LabServices,
    message?: WebviewToHostMessage
  ): Promise<void> {
    await WorkbenchPanel.show(context, runtimeManager, pythonTrust, view, services);
    if (message) await WorkbenchPanel.current?.handleMessage(message);
  }

  selectedModule: WorkbenchView;
  private readonly disposables: vscode.Disposable[] = [];
  /** Last focused file per extension, so "Run active ..." works when the Workbench shares a tab group with it. */
  private readonly lastDocuments = new Map<string, vscode.Uri>();
  /** The lab tab (or Practice filter) a project step asked to show. */
  private focus?: WorkbenchFocus;
  private focusSeq = 0;
  /** Only the newest refresh posts its state (see refresh). */
  private refreshSeq = 0;
  private readonly controllers: readonly LabController<never>[];
  private readonly messageTable: ReturnType<typeof buildMessageTable>;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    readonly context: vscode.ExtensionContext,
    readonly runtime: RuntimeManager,
    readonly pythonTrust: PythonTrustController,
    initialModule: WorkbenchView,
    readonly services: LabServices
  ) {
    this.selectedModule = initialModule;
    this.rememberEditor(vscode.window.activeTextEditor);
    this.panel.webview.html = this.html(this.panel.webview);
    this.controllers = Object.values(createLabControllers(this));
    this.messageTable = buildMessageTable(this.controllers);
    // Saving a file refreshes the labs whose view reads workspace files, and any module when the manifest changes.
    const refreshOnSave = new Set<WorkbenchView | undefined>(this.controllers.map(controller => controller.refreshOnSave));

    this.disposables.push(
      this.panel.onDidDispose(() => this.dispose()),
      vscode.window.onDidChangeActiveTextEditor(editor => this.rememberEditor(editor)),
      this.panel.webview.onDidReceiveMessage(message => {
        void this.handleMessage(message as WebviewToHostMessage);
      }),
      this.runtime.onDidChange(() => {
        void this.refresh();
      }),
      vscode.workspace.onDidGrantWorkspaceTrust(() => {
        void this.refresh();
      }),
      vscode.workspace.onDidSaveTextDocument(document => {
        if (document.uri.path.endsWith("/.datapass/project.json") || refreshOnSave.has(this.selectedModule)) {
          void this.refresh();
        }
      })
    );
  }

  private async handleMessage(message: WebviewToHostMessage): Promise<void> {
    await this.messageTable.get(message.type)?.(message);
  }

  showModule(module: ModuleId, focus?: Omit<WorkbenchFocus, "module" | "seq">): void {
    this.selectedModule = module;
    this.focus = focus ? { module, ...focus, seq: ++this.focusSeq } : undefined;
  }

  showHome(): void {
    this.selectedModule = "home";
    this.focus = undefined;
  }

  lastDocument(extension: ".sql" | ".py"): vscode.Uri | undefined {
    return this.lastDocuments.get(extension);
  }

  private rememberEditor(editor: vscode.TextEditor | undefined): void {
    if (editor?.document.uri.scheme !== "file") return;
    const match = /\.(sql|py)$/i.exec(editor.document.fileName);
    if (match) this.lastDocuments.set("." + match[1].toLowerCase(), editor.document.uri);
  }

  private besideColumn(): vscode.ViewColumn {
    return this.panel.viewColumn === vscode.ViewColumn.Two ? vscode.ViewColumn.One : vscode.ViewColumn.Two;
  }

  async openBeside(uri: vscode.Uri): Promise<void> {
    const document = await vscode.workspace.openTextDocument(uri);
    const editor = await vscode.window.showTextDocument(document, { preview: false, viewColumn: this.besideColumn() });
    this.rememberEditor(editor);
  }

  async revealBeside(uri: vscode.Uri, locate: (document: vscode.TextDocument) => vscode.Position): Promise<void> {
    const document = await vscode.workspace.openTextDocument(uri);
    const position = locate(document);
    const editor = await vscode.window.showTextDocument(document, { preview: false, viewColumn: this.besideColumn() });
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
  }

  async guarded(what: string, action: () => Promise<void>): Promise<void> {
    try {
      await action();
    } catch (error) {
      void vscode.window.showErrorMessage(`${what}: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  async refresh(): Promise<void> {
    // A slow refresh (the Practice catalog) must not land after a newer one and switch the module back.
    const seq = ++this.refreshSeq;
    const selected = this.selectedModule;
    const extras: WorkbenchStateExtras = { focus: this.focus };
    for (const controller of this.controllers) {
      if (controller.contribute) Object.assign(extras, await controller.contribute(selected));
    }
    const state = await collectWorkbenchState(selected, this.runtime, this.context.extensionUri, this.pythonTrust, extras);
    if (seq !== this.refreshSeq) return;
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
    for (const controller of this.controllers) controller.dispose?.();
  }
}
