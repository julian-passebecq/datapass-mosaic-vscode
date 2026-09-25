import * as vscode from "vscode";
import {
  groupBySchema,
  previewSql,
  scratchContent,
  scratchFileName,
  tableDescription,
  toCatalogSchemaView,
  type CatalogSchemaGroup,
  type CatalogSchemaView,
  type CatalogTableView
} from "./platform/catalogTree";
import type { RuntimeManager } from "./runtimeManager";

type CatalogNode =
  | { kind: "message"; label: string; detail?: string; command?: vscode.Command; icon: string }
  | { kind: "schema"; group: CatalogSchemaGroup }
  | { kind: "table"; table: CatalogTableView }
  | { kind: "column"; table: CatalogTableView; name: string; type: string };

/**
 * Native Catalog view: schemas (layers first) → tables and views → columns, read from the runtime's
 * local DuckDB catalog. Useful to every lab; it follows the runtime's state changes.
 */
export class CatalogTreeProvider implements vscode.TreeDataProvider<CatalogNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<CatalogNode | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  private view?: CatalogSchemaView;
  private error?: string;
  private loading = false;
  private signature = "";
  private timer?: ReturnType<typeof setTimeout>;
  private readonly subscription: vscode.Disposable;

  constructor(private readonly runtime: RuntimeManager) {
    this.subscription = runtime.onDidChange(state => {
      // Refetch when the runtime starts or stops, or when a run changed the catalog listing.
      const next = JSON.stringify([state.status, state.url, state.catalogLease?.holder ?? null,
        (state.catalog ?? []).map(item => [item.name, item.row_count])]);
      if (next === this.signature) return;
      this.signature = next;
      this.schedule();
    });
  }

  /** The last schema read, for tests and for the dbt Lab. */
  snapshot(): CatalogSchemaView | undefined {
    return this.view;
  }

  refresh(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    return this.load();
  }

  getTreeItem(node: CatalogNode): vscode.TreeItem {
    switch (node.kind) {
      case "message": {
        const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.None);
        item.description = node.detail;
        item.tooltip = node.detail ? `${node.label}\n${node.detail}` : node.label;
        item.iconPath = new vscode.ThemeIcon(node.icon);
        item.command = node.command;
        return item;
      }
      case "schema": {
        const { group } = node;
        const item = new vscode.TreeItem(
          group.schema,
          group.tables.length ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None
        );
        item.id = `schema:${group.schema}`;
        item.description = `${group.tables.length} ${group.tables.length === 1 ? "object" : "objects"}${group.layer ? "" : " · not a catalog layer"}`;
        item.iconPath = new vscode.ThemeIcon(group.layer ? "layers" : "folder");
        item.contextValue = "datapassCatalogSchema";
        return item;
      }
      case "table": {
        const { table } = node;
        const item = new vscode.TreeItem(table.name, vscode.TreeItemCollapsibleState.Collapsed);
        item.id = `table:${table.schema}.${table.name}`;
        item.description = tableDescription(table);
        item.iconPath = new vscode.ThemeIcon(table.error ? "warning" : table.kind === "view" ? "eye" : "table");
        const tooltip = new vscode.MarkdownString(
          `**${table.schema}.${table.name}** (${table.kind})\n\n${tableDescription(table)}` +
          (table.error ? `\n\n⚠ ${table.error}` : "") +
          `\n\nClick to open a SQL scratch with \`SELECT * ... LIMIT 100\`.`
        );
        item.tooltip = tooltip;
        item.contextValue = "datapassCatalogTable";
        item.command = { command: "datapass.catalog.openScratch", title: "Open SQL scratch", arguments: [node] };
        return item;
      }
      case "column": {
        const item = new vscode.TreeItem(node.name, vscode.TreeItemCollapsibleState.None);
        item.id = `column:${node.table.schema}.${node.table.name}.${node.name}`;
        item.description = node.type;
        item.iconPath = new vscode.ThemeIcon("symbol-field");
        item.contextValue = "datapassCatalogColumn";
        return item;
      }
    }
  }

  getChildren(node?: CatalogNode): CatalogNode[] {
    if (!node) return this.rootNodes();
    if (node.kind === "schema") return node.group.tables.map(table => ({ kind: "table", table }));
    if (node.kind === "table") {
      return node.table.columns.map(column => ({ kind: "column", table: node.table, name: column.name, type: column.type }));
    }
    return [];
  }

  private rootNodes(): CatalogNode[] {
    const state = this.runtime.snapshot();
    if (state.status !== "running") {
      return [{
        kind: "message",
        label: state.status === "starting" ? "Runtime starting…" : "Runtime not running",
        detail: state.status === "starting" ? undefined : "Start it to browse the catalog",
        icon: state.status === "starting" ? "loading~spin" : "debug-disconnect",
        command: state.status === "starting" ? undefined : { command: "datapass.openMosaic", title: "Open Workbench" }
      }];
    }
    if (state.catalogLease) {
      return [{
        kind: "message",
        label: "Catalog lent to dbt Core / dct",
        detail: state.catalogLease.reattachError ?? state.catalogLease.holder,
        icon: "lock",
        command: { command: "datapass.catalog.reattach", title: "Reattach catalog" }
      }];
    }
    if (this.error) {
      return [{ kind: "message", label: "Catalog unavailable", detail: this.error, icon: "error",
        command: { command: "datapass.catalog.refresh", title: "Retry" } }];
    }
    if (!this.view) return [{ kind: "message", label: "Reading the catalog…", icon: "loading~spin" }];
    const nodes: CatalogNode[] = groupBySchema(this.view).map(group => ({ kind: "schema", group }));
    if (this.view.truncated) nodes.push({ kind: "message", label: "Only the first 500 objects are shown", icon: "info" });
    return nodes;
  }

  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.load();
    }, 250);
  }

  private async load(): Promise<void> {
    const state = this.runtime.snapshot();
    if (state.status !== "running" || state.catalogLease) {
      this.view = undefined;
      this.error = undefined;
      this.changed.fire(undefined);
      return;
    }
    if (this.loading) {
      this.schedule();
      return;
    }
    this.loading = true;
    try {
      this.view = toCatalogSchemaView(await this.runtime.fetchCatalogSchema());
      this.error = undefined;
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    } finally {
      this.loading = false;
      this.changed.fire(undefined);
    }
  }

  dispose(): void {
    if (this.timer) clearTimeout(this.timer);
    this.subscription.dispose();
    this.changed.dispose();
  }
}

/**
 * Open `.datapass/scratch/<schema>.<table>.sql` (created with a `SELECT * ... LIMIT 100` the first time; an
 * existing scratch is never overwritten, since the learner may have edited it).
 */
export async function openTableScratch(table: CatalogTableView): Promise<vscode.Uri | undefined> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) {
    void vscode.window.showWarningMessage("Open a workspace folder before opening a SQL scratch.");
    return undefined;
  }
  const directory = vscode.Uri.joinPath(root, ".datapass", "scratch");
  const uri = vscode.Uri.joinPath(directory, scratchFileName(table));
  await vscode.workspace.fs.createDirectory(directory);
  try {
    await vscode.workspace.fs.stat(uri);
  } catch {
    await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(scratchContent(table)));
  }
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document, { preview: false });
  return uri;
}

export function registerCatalogTree(runtime: RuntimeManager, openWorkbench: () => Promise<void>): vscode.Disposable[] {
  const provider = new CatalogTreeProvider(runtime);
  const tableOf = (node: unknown): CatalogTableView | undefined =>
    node && typeof node === "object" && (node as CatalogNode).kind === "table" ? (node as { table: CatalogTableView }).table : undefined;
  return [
    provider,
    vscode.window.createTreeView("datapass.catalog", { treeDataProvider: provider, showCollapseAll: true }),
    vscode.commands.registerCommand("datapass.catalog.refresh", () => provider.refresh()),
    vscode.commands.registerCommand("datapass.catalog.reattach", async () => {
      if (!(await runtime.reattachCatalog())) {
        void vscode.window.showWarningMessage(runtime.snapshot().catalogLease?.reattachError ?? "The catalog is still held.");
      }
    }),
    vscode.commands.registerCommand("datapass.catalog.openScratch", async (node: unknown) => {
      const table = tableOf(node);
      if (table) await openTableScratch(table);
    }),
    vscode.commands.registerCommand("datapass.catalog.previewTable", async (node: unknown) => {
      const table = tableOf(node);
      if (!table) return;
      try {
        await runtime.runSql(previewSql(table));
        await openWorkbench();
      } catch (error) {
        void vscode.window.showErrorMessage(`Preview failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    }),
    vscode.commands.registerCommand("datapass.catalog.copyName", async (node: unknown) => {
      const table = tableOf(node);
      if (table) await vscode.env.clipboard.writeText(`${table.schema}.${table.name}`);
    })
  ];
}
