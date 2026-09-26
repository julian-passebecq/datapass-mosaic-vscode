import * as vscode from "vscode";
import type { DbtTerminalSession, DbtToolsManager } from "../dbtLab";
import type { InfraLabSession } from "../infraLab";
import type { MissionsService } from "../missions";
import type { ModuleId } from "../modules";
import type { PythonTrustController } from "../pythonTrustController";
import type { RuntimeManager } from "../runtimeManager";
import type { TerminalLabSession } from "../terminalLab";
import type { WebviewToHostMessage, WorkbenchFocus } from "../webview/contracts";
import type { WorkbenchStateExtras } from "../workbenchState";
import type { MessageHandlers } from "./messageTable";

export { buildMessageTable, type MessageHandlers } from "./messageTable";

/**
 * The labs' host services: the dbt Lab's managed dbt tools and the terminal that runs real dbt Core commands, the
 * missions (shared by the dbt Lab, the Terminal Lab and the Infra Lab), the Terminal Lab's shells and terminals, and
 * the Infra Lab's simulated terminals.
 */
export interface LabServices {
  tools: DbtToolsManager;
  terminal: DbtTerminalSession;
  missions: MissionsService;
  terminalLab: TerminalLabSession;
  infraLab: InfraLabSession;
}

/** What the Workbench panel gives every lab controller. */
export interface WorkbenchHost {
  readonly context: vscode.ExtensionContext;
  readonly runtime: RuntimeManager;
  readonly pythonTrust: PythonTrustController;
  readonly services: LabServices;
  /** The module the Workbench shows. */
  readonly selectedModule: ModuleId;
  /** Show a module, and a tab or filter in it (a project step); the next refresh posts it. */
  showModule(module: ModuleId, focus?: Omit<WorkbenchFocus, "module" | "seq">): void;
  /** Post the Workbench state again (only the newest refresh lands). */
  refresh(): Promise<void>;
  /** Open a file next to the Workbench so the webview and the file stay visible together. */
  openBeside(uri: vscode.Uri): Promise<void>;
  /** Open a file next to the Workbench with the cursor on a position of it (a statement's line, an activity). */
  revealBeside(uri: vscode.Uri, locate: (document: vscode.TextDocument) => vscode.Position): Promise<void>;
  /** The last focused file with this extension (".sql", ".py"), so "Run active …" works when the Workbench hides it. */
  lastDocument(extension: ".sql" | ".py"): vscode.Uri | undefined;
  /** Run an action, show its error as "<what>: <message>", then refresh. */
  guarded(what: string, action: () => Promise<void>): Promise<void>;
}

/**
 * A lab's host side: the webview messages it answers, what it adds to the Workbench state, and its subscriptions.
 * `M` is the lab's message union from src/webview/contracts/<lab>.ts.
 */
export interface LabController<M extends WebviewToHostMessage = WebviewToHostMessage> {
  readonly handlers: MessageHandlers<M>;
  /** Saving a file refreshes the Workbench while this module is shown (its view reads workspace files). */
  readonly refreshOnSave?: ModuleId;
  /** What this lab adds to the next state message; `selected` is the module being shown. */
  contribute?(selected: ModuleId): Promise<Partial<WorkbenchStateExtras>> | Partial<WorkbenchStateExtras>;
  dispose?(): void;
}

/** A 1-based line as a position (the last line when the file is shorter). */
export function atLine(line: number): (document: vscode.TextDocument) => vscode.Position {
  return document => new vscode.Position(Math.min(line, document.lineCount) - 1, 0);
}

/**
 * The active file with this extension, saved. Clicking the Workbench hides a file that shares its tab group, so the
 * active editor falls back to a visible one, then to the last focused file.
 */
export async function activeSavedDocument(
  extension: string,
  label: string,
  remembered?: vscode.Uri
): Promise<vscode.TextDocument | undefined> {
  const matches = (candidate: vscode.TextDocument | undefined) =>
    candidate?.uri.scheme === "file" && candidate.fileName.toLowerCase().endsWith(extension);
  const document =
    (matches(vscode.window.activeTextEditor?.document) ? vscode.window.activeTextEditor!.document : undefined) ??
    vscode.window.visibleTextEditors.map(editor => editor.document).find(matches) ??
    vscode.workspace.textDocuments.find(candidate =>
      !candidate.isClosed && matches(candidate) && candidate.uri.toString() === remembered?.toString()
    );
  if (!document) {
    void vscode.window.showWarningMessage(`Open a ${label} file in VS Code before running it.`);
    return undefined;
  }
  if (document.isDirty && !(await document.save())) {
    void vscode.window.showWarningMessage(`Save the ${label} file before running it.`);
    return undefined;
  }
  return document;
}

/** A run uses the files as saved, like the other labs: save the dirty editors under a lab folder. */
export async function saveDirtyUnder(root: vscode.Uri | undefined): Promise<void> {
  if (!root) return;
  for (const document of vscode.workspace.textDocuments) {
    if (document.isDirty && document.uri.toString().startsWith(root.toString() + "/")) await document.save();
  }
}
