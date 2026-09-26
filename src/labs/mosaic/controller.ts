import * as vscode from "vscode";
import type { ModuleId } from "../../modules";
import { writeMosaicLayout } from "../../mosaicLayoutStore";
import { decodeCsvBytes, suggestBronzeAsset, validateBronzeAsset } from "../../platform/csvImport";
import {
  FILE_IMPORT_MAX_BYTES,
  IMPORT_FILTERS,
  addQueryHistory,
  importFormat,
  restoreQueryHistory,
  type QueryHistoryEntry
} from "../../platform/mosaicTools";
import { runDialect, type TranslatedDialectId } from "../../platform/sqlDialect";
import { safeRelativeParts } from "../../platform/workspacePaths";
import { readProjectManifest } from "../../project/projectManifest";
import { openQueryPlan, openTranslatedSql } from "../../queryPlanDocuments";
import { scratchSpec } from "../../scaffold/starters";
import type { MosaicMessage, ScratchKind } from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import { activeSavedDocument, type LabController, type MessageHandlers, type WorkbenchHost } from "../host";

/** Mosaic query history, per workspace; not a project file (it may contain ad-hoc SQL). */
const QUERY_HISTORY_KEY = "datapass.mosaic.queryHistory";

/** Mosaic: native SQL/Python files run on the local catalog, imports, profiles, plans, scratch files, query history. */
export class MosaicController implements LabController<MosaicMessage> {
  /** The SQL file of the last Run active SQL: names its translated SQL tab. */
  private lastSqlFile: string | undefined;

  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<MosaicMessage> = {
    importCsv: () => this.importFile(),
    importFile: () => this.importFile(),
    profileTable: message => this.host.guarded("Profile", () => this.host.runtime.labs.mosaic.profileTable(message.asset)),
    explainActiveSql: () => this.explainActiveSql(),
    openQueryPlan: async () => {
      const plan = this.host.runtime.snapshot().queryPlan;
      if (plan) await openQueryPlan(plan);
    },
    openTranslatedSql: async () => {
      const translation = this.host.runtime.snapshot().lastRun?.dialect;
      if (translation) await openTranslatedSql(translation, this.lastSqlFile);
    },
    rerunQuery: message => this.rerunQuery(message.id),
    openQueryFile: message => this.openQueryFile(message.id),
    runActiveSql: () => this.runActiveSql(),
    runActivePython: () => this.runActivePython(),
    saveMosaicLayout: async message => {
      // Persist only inside a Datapass project; never create .datapass/ just by dragging.
      if ((await readProjectManifest()).exists) await writeMosaicLayout(message.layout);
    },
    openScratch: message => this.openScratch(message.kind)
  };

  contribute(selected: ModuleId): Partial<WorkbenchStateExtras> {
    return { queryHistory: selected === "mosaic" ? this.queryHistory() : undefined };
  }

  /** CSV, Parquet or JSON into a new bronze table. The file's CONTENT is sent, never its path. */
  private async importFile(): Promise<void> {
    const runtime = this.host.runtime;
    if (runtime.snapshot().status !== "running") {
      void vscode.window.showWarningMessage("Start the Datapass runtime before importing a file.");
      return;
    }
    const picked = await vscode.window.showOpenDialog({
      canSelectMany: false,
      canSelectFolders: false,
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
      filters: IMPORT_FILTERS,
      openLabel: "Import into catalog",
      title: "Import a CSV, Parquet or JSON file into the local catalog (new bronze table)"
    });
    const uri = picked?.[0];
    if (!uri) return;
    const fileName = uri.path.split("/").pop() ?? "data";
    const format = importFormat(fileName);
    if (!format) {
      void vscode.window.showErrorMessage("Import a .csv, .parquet, .json, .jsonl or .ndjson file.");
      return;
    }
    if (format !== "csv") {
      await this.importTypedFile(uri, fileName, format);
      return;
    }

    let text: string;
    try {
      text = decodeCsvBytes(await vscode.workspace.fs.readFile(uri));
    } catch (error) {
      void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
      return;
    }

    const existing = (runtime.snapshot().catalog ?? []).map(asset => asset.name);
    const asset = await vscode.window.showInputBox({
      title: `Import ${fileName}`,
      prompt: "New bronze table name. Imports never overwrite; every column is stored as text.",
      value: suggestBronzeAsset(fileName, existing),
      valueSelection: [7, Number.MAX_SAFE_INTEGER],
      validateInput: value => validateBronzeAsset(value, existing)
    });
    if (!asset) return;

    try {
      const result = await runtime.labs.mosaic.importCsv(asset.trim(), text, fileName);
      void vscode.window.showInformationMessage(
        `Imported ${result.rows_imported} rows into ${result.asset}. Columns are text; CAST them in SQL when building silver tables.`
      );
    } catch (error) {
      void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
    }
    await this.host.refresh();
  }

  private async importTypedFile(uri: vscode.Uri, fileName: string, format: "parquet" | "json"): Promise<void> {
    const runtime = this.host.runtime;
    const bytes = await vscode.workspace.fs.readFile(uri);
    if (!bytes.byteLength || bytes.byteLength > FILE_IMPORT_MAX_BYTES) {
      void vscode.window.showErrorMessage(`Import files must be 1 byte to ${FILE_IMPORT_MAX_BYTES / 1_000_000} MB; ${fileName} is ${bytes.byteLength.toLocaleString()} bytes.`);
      return;
    }
    const existing = (runtime.snapshot().catalog ?? []).map(asset => asset.name);
    const asset = await vscode.window.showInputBox({
      title: `Import ${fileName}`,
      prompt: `New bronze table name. Imports never overwrite; column types come from the ${format === "parquet" ? "Parquet file" : "JSON (DuckDB read_json_auto)"}.`,
      value: suggestBronzeAsset(fileName, existing),
      valueSelection: [7, Number.MAX_SAFE_INTEGER],
      validateInput: value => validateBronzeAsset(value, existing)
    });
    if (!asset) return;
    try {
      const result = await runtime.labs.mosaic.importFile(asset.trim(), format, Buffer.from(bytes).toString("base64"), fileName);
      void vscode.window.showInformationMessage(`Imported ${result.rows_imported} rows into ${result.asset} with typed columns.`);
    } catch (error) {
      void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
    }
    await this.host.refresh();
  }

  /** EXPLAIN ANALYZE of the active SQL file, or of its selection when there is one. */
  private async explainActiveSql(): Promise<void> {
    const document = await activeSavedDocument(".sql", "SQL", this.host.lastDocument(".sql"));
    if (!document) return;
    const editor = vscode.window.visibleTextEditors.find(candidate => candidate.document === document);
    const selected = editor && !editor.selection.isEmpty ? document.getText(editor.selection) : undefined;
    const sql = selected?.trim() ? selected : document.getText();
    const file = vscode.workspace.asRelativePath(document.uri, false);
    // The dialect is the file's (its first line), also when only a selection is explained.
    const { dialect, error } = runDialect(document.getText());
    if (error) {
      void vscode.window.showErrorMessage(error);
      return;
    }
    await this.recordQuery("explain", sql, file, async () => {
      const plan = await this.host.runtime.labs.mosaic.explainQuery(sql, selected ? `${file} (selection)` : file, dialect);
      return { status: "success", elapsedMs: plan.elapsed_ms };
    }, dialect);
    await this.host.refresh();
  }

  private async rerunQuery(id: string): Promise<void> {
    const entry = this.queryHistory().find(item => item.id === id);
    if (!entry) return;
    await this.recordQuery(entry.kind, entry.sql, entry.file, async () => {
      if (entry.kind === "explain") {
        const plan = await this.host.runtime.labs.mosaic.explainQuery(entry.sql, entry.file, entry.dialect);
        return { status: "success", elapsedMs: plan.elapsed_ms };
      }
      const run = await this.host.runtime.labs.mosaic.runSql(entry.sql, entry.dialect);
      return { status: run.status, elapsedMs: run.elapsed_ms, rows: run.result?.rows.length, error: run.error?.message };
    }, entry.dialect);
    await this.host.refresh();
  }

  private async openQueryFile(id: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    const entry = this.queryHistory().find(item => item.id === id);
    if (!root || !entry?.file) return;
    const uri = vscode.Uri.joinPath(root, ...entry.file.split("/"));
    if (await exists(uri)) await this.host.openBeside(uri);
    else void vscode.window.showWarningMessage(`${entry.file} no longer exists.`);
  }

  private queryHistory(): QueryHistoryEntry[] {
    return restoreQueryHistory(this.host.context.workspaceState.get(QUERY_HISTORY_KEY));
  }

  /** Runs one Mosaic query action and keeps it in the workspace's query history, failures included. */
  private async recordQuery(
    kind: QueryHistoryEntry["kind"],
    sql: string,
    file: string | undefined,
    action: () => Promise<{ status: "success" | "error"; elapsedMs: number; rows?: number; error?: string }>,
    dialect?: TranslatedDialectId
  ): Promise<void> {
    let outcome: { status: "success" | "error"; elapsedMs: number; rows?: number; error?: string };
    try {
      outcome = await action();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      outcome = { status: "error", elapsedMs: 0, error: message };
      void vscode.window.showErrorMessage(message);
    }
    const entry: QueryHistoryEntry = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      at: new Date().toISOString(),
      kind,
      file,
      sql,
      ...(dialect ? { dialect } : {}),
      ...outcome
    };
    await this.host.context.workspaceState.update(QUERY_HISTORY_KEY, addQueryHistory(this.queryHistory(), entry));
  }

  private async runActiveSql(): Promise<void> {
    const document = await activeSavedDocument(".sql", "SQL", this.host.lastDocument(".sql"));
    if (!document) return;
    // `-- dialect: <name>` on the first line: the runtime translates the file to DuckDB (the SQL: status bar item).
    const { dialect, error } = runDialect(document.getText());
    if (error) {
      void vscode.window.showErrorMessage(error);
      return;
    }
    this.lastSqlFile = vscode.workspace.asRelativePath(document.uri, false);

    await this.recordQuery("run", document.getText(), vscode.workspace.asRelativePath(document.uri, false), async () => {
      try {
        const run = await this.host.runtime.labs.mosaic.runSql(document.getText(), dialect);
        return { status: run.status, elapsedMs: run.elapsed_ms, rows: run.result?.rows.length, error: run.error?.message };
      } catch (error) {
        throw new Error(`SQL execution failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    }, dialect);
    await this.host.refresh();
  }

  private async runActivePython(): Promise<void> {
    const trust = await this.host.pythonTrust.resolve();
    if (!trust.effective || !this.host.runtime.snapshot().trustedPython) {
      void vscode.window.showWarningMessage(
        trust.effective
          ? "Restart the Datapass runtime to apply trusted local Python."
          : trust.reason
      );
      return;
    }
    const document = await activeSavedDocument(".py", "Python", this.host.lastDocument(".py"));
    if (!document) return;

    try {
      await this.host.runtime.labs.mosaic.runPython(document.getText());
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Python execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }

  private async openScratch(kind: ScratchKind): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating Mosaic scratch files.");
      return;
    }

    const manifest = await readProjectManifest();
    const notebooks = safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks");
    const spec = scratchSpec(kind);
    const directoryParts = kind === "notes" ? ["notes"] : notebooks;
    const directory = vscode.Uri.joinPath(root, ...directoryParts);
    const uri = vscode.Uri.joinPath(directory, spec.fileName);

    await vscode.workspace.fs.createDirectory(directory);
    if (!(await exists(uri))) {
      await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(spec.content));
    }
    await this.host.openBeside(uri);
  }
}
