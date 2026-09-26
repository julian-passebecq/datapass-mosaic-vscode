import * as vscode from "vscode";
import { registerCatalogTree } from "./catalogTree";
import { DbtTerminalSession, DbtToolsManager } from "./dbtLab";
import { MissionsService } from "./missions";
import { LabTreeProvider } from "./labTree";
import { TerminalLabSession } from "./terminalLab";
import { InfraLabSession } from "./infraLab";
import { MODULES } from "./modules";
import { PythonTrustController } from "./pythonTrustController";
import { registerReferenceSolutions } from "./referenceSolutions";
import { registerQueryPlanDocuments } from "./queryPlanDocuments";
import { RuntimeManager } from "./runtimeManager";
import { registerSqlDialectStatus } from "./sqlDialectStatus";
import { WorkbenchPanel } from "./workbenchPanel";

export function activate(context: vscode.ExtensionContext): void {
  const runtimeManager = new RuntimeManager(context.extensionUri, context.globalStorageUri);
  const pythonTrust = new PythonTrustController(context);
  const dbtTools = new DbtToolsManager(context.globalStorageUri);
  const dbtLab = {
    tools: dbtTools,
    terminal: new DbtTerminalSession(runtimeManager, dbtTools),
    missions: new MissionsService(context.extensionUri, runtimeManager, dbtTools),
    terminalLab: new TerminalLabSession(context.globalState),
    infraLab: new InfraLabSession(runtimeManager, context.workspaceState)
  };

  context.subscriptions.push(
    runtimeManager,
    dbtLab.tools,
    dbtLab.terminal,
    dbtLab.terminalLab,
    dbtLab.infraLab,
    vscode.window.registerTreeDataProvider("datapass.labs", new LabTreeProvider()),
    registerReferenceSolutions(context.extensionUri),
    registerQueryPlanDocuments(),
    ...registerSqlDialectStatus(),
    ...registerCatalogTree(runtimeManager, () => WorkbenchPanel.show(context, runtimeManager, pythonTrust, "mosaic", dbtLab))
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("datapass.openHome", () => {
      void WorkbenchPanel.show(context, runtimeManager, pythonTrust, "home", dbtLab);
    })
  );
  for (const module of MODULES) {
    context.subscriptions.push(
      vscode.commands.registerCommand(module.command, () => {
        void WorkbenchPanel.show(context, runtimeManager, pythonTrust, module.id, dbtLab);
      })
    );
  }
}

export function deactivate(): void {}
