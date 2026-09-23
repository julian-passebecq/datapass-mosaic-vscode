import * as vscode from "vscode";
import { LabTreeProvider } from "./labTree";
import { MODULES } from "./modules";
import { RuntimeManager } from "./runtimeManager";
import { WorkbenchPanel } from "./workbenchPanel";

export function activate(context: vscode.ExtensionContext): void {
  const runtimeManager = new RuntimeManager(context.extensionUri);

  context.subscriptions.push(
    runtimeManager,
    vscode.window.registerTreeDataProvider("datapass.labs", new LabTreeProvider())
  );

  for (const module of MODULES) {
    context.subscriptions.push(
      vscode.commands.registerCommand(module.command, () => {
        void WorkbenchPanel.show(context, runtimeManager, module.id);
      })
    );
  }
}

export function deactivate(): void {}
