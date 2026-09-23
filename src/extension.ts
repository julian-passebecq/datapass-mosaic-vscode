import * as vscode from "vscode";
import { LabTreeProvider } from "./labTree";
import { MODULES } from "./modules";
import { openModulePanel } from "./modulePanel";

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(vscode.window.registerTreeDataProvider("datapass.labs", new LabTreeProvider()));
  for (const module of MODULES) {
    context.subscriptions.push(vscode.commands.registerCommand(module.command, () => openModulePanel(context, module)));
  }
}

export function deactivate(): void {}
