import * as vscode from "vscode";
import { MODULE_FAMILIES, familyModules, type ModuleFamily, type WorkbenchModule } from "./modules";

class LabTreeItem extends vscode.TreeItem {
  constructor(module: WorkbenchModule) {
    super(module.label, vscode.TreeItemCollapsibleState.None);
    this.description = module.execution;
    this.tooltip = new vscode.MarkdownString(`**${module.label}**\n\n${module.description}\n\nExecution: ${module.execution}`);
    this.command = { command: module.command, title: `Open ${module.label}` };
    this.iconPath = new vscode.ThemeIcon(module.icon);
  }
}

class FamilyTreeItem extends vscode.TreeItem {
  constructor(readonly family: ModuleFamily) {
    super(family.label, vscode.TreeItemCollapsibleState.Expanded);
    this.tooltip = family.description;
  }
}

class HomeTreeItem extends vscode.TreeItem {
  constructor() {
    super("Today", vscode.TreeItemCollapsibleState.None);
    this.description = "Progress and next step";
    this.command = { command: "datapass.openHome", title: "Open Today" };
    this.iconPath = new vscode.ThemeIcon("home");
  }
}

type Item = HomeTreeItem | FamilyTreeItem | LabTreeItem;

/** The Labs view: Today, then the modules grouped by family (content/modules.json). */
export class LabTreeProvider implements vscode.TreeDataProvider<Item> {
  getTreeItem(element: Item): vscode.TreeItem { return element; }
  getChildren(element?: Item): Item[] {
    if (!element) return [new HomeTreeItem(), ...MODULE_FAMILIES.map(family => new FamilyTreeItem(family))];
    return element instanceof FamilyTreeItem ? familyModules(element.family.id).map(module => new LabTreeItem(module)) : [];
  }
}
