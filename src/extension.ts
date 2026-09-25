import * as vscode from "vscode";
import { registerCatalogTree } from "./catalogTree";
import { LabTreeProvider } from "./labTree";
import { MODULES } from "./modules";
import { PythonTrustController } from "./pythonTrustController";
import { RuntimeManager } from "./runtimeManager";
import { WorkbenchPanel } from "./workbenchPanel";

export function activate(context: vscode.ExtensionContext): void {
  const runtimeManager = new RuntimeManager(context.extensionUri, context.globalStorageUri);
  const pythonTrust = new PythonTrustController(context);

  context.subscriptions.push(
    runtimeManager,
    vscode.window.registerTreeDataProvider("datapass.labs", new LabTreeProvider()),
    ...registerCatalogTree(runtimeManager, () => WorkbenchPanel.show(context, runtimeManager, pythonTrust, "mosaic"))
  );

  for (const module of MODULES) {
    context.subscriptions.push(
      vscode.commands.registerCommand(module.command, () => {
        void WorkbenchPanel.show(context, runtimeManager, pythonTrust, module.id);
      })
    );
  }
}

export function deactivate(): void {}
