import * as vscode from "vscode";
import { MODULES, WorkbenchModule } from "./modules";

class LabTreeItem extends vscode.TreeItem {
  constructor(module: WorkbenchModule) {
    super(module.label, vscode.TreeItemCollapsibleState.None);
    this.description = module.execution;
    this.tooltip = new vscode.MarkdownString(`**${module.label}**\n\n${module.description}\n\nExecution: ${module.execution}`);
    this.command = { command: module.command, title: `Open ${module.label}` };
    this.iconPath = new vscode.ThemeIcon(module.id === "projects" ? "checklist" : module.id === "terminal" ? "terminal" : module.id === "infra" ? "server-environment" : "beaker");
  }
}

export class LabTreeProvider implements vscode.TreeDataProvider<LabTreeItem> {
  getTreeItem(element: LabTreeItem): vscode.TreeItem { return element; }
  getChildren(): LabTreeItem[] { return MODULES.map(module => new LabTreeItem(module)); }
}
