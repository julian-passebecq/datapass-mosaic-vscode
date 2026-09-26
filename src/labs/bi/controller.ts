import * as vscode from "vscode";
import { biFileUri, biRoot, collectBiDbtFiles, collectBiScripts, copyBiSamples, readBiModel } from "../../biState";
import { BI_LIMITS, BI_MODEL_FILE, DBT_COMMANDS, parseSelect } from "../../platform/biRun";
import type { BiDbtCommand, BiMessage, BiRunMode } from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import { activeSavedDocument, atLine, saveDirtyUnder, type LabController, type MessageHandlers, type WorkbenchHost } from "../host";

/** BI Lab: warehouse scripts, star model checks and SQL lineage over bi/, and its dbt tab (the Datapass emulation). */
export class BiController implements LabController<BiMessage> {
  readonly refreshOnSave = "bi" as const;
  /** The active .sql file the BI Lab last ran (not under bi/), to reveal a statement's line in it. */
  private lastBiActiveFile?: vscode.Uri;

  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<BiMessage> = {
    createBiLab: () => this.createBiLab(),
    refreshBi: () => this.host.refresh(),
    openBiFile: message => this.openBiFile(message.path),
    runBiLab: message => this.runBiLab(message.mode),
    revealBiLine: message => this.revealBiLine(message.path, message.line),
    runBiDbt: message => this.runBiDbt(message.command, message.select, message.fullRefresh)
  };

  /** Copy the BI Lab samples (warehouse scripts and the star model) into bi/, keeping existing files. */
  private async createBiLab(): Promise<void> {
    const root = await copyBiSamples(this.host.context.extensionUri);
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating the BI Lab files.");
      return;
    }
    const model = biFileUri(BI_MODEL_FILE);
    if (model && (await exists(model))) await this.host.openBeside(model);
    void vscode.window.showInformationMessage(
      "BI Lab files are in bi/: warehouse scripts that build a star schema from CRM, ERP and shop sources (bi/warehouse, run in name order) and its star model (bi/model.json). Existing files were kept."
    );
    await this.host.refresh();
  }

  private async openBiFile(relative: string): Promise<void> {
    const uri = biFileUri(relative);
    if (!uri || !(await exists(uri))) {
      void vscode.window.showWarningMessage(`BI Lab file not found: ${relative}`);
      return;
    }
    await this.host.openBeside(uri);
  }

  /**
   * BI Lab: build (run every script of bi/warehouse in name order), run the active .sql file, or only analyze
   * (lineage and model checks on the tables as they are). The scripts run on the local catalog.
   */
  private async runBiLab(mode: BiRunMode): Promise<void> {
    if (mode !== "build" && mode !== "analyze" && mode !== "active") return;
    await saveDirtyUnder(biRoot());
    let scripts: { path: string; text: string }[];
    let warnings: string[];
    let source: string;
    if (mode === "active") {
      const document = await activeSavedDocument(".sql", "SQL", this.host.lastDocument(".sql"));
      if (!document) return;
      const text = document.getText();
      if (text.length > BI_LIMITS.scriptChars) {
        void vscode.window.showWarningMessage(`The script is longer than ${BI_LIMITS.scriptChars} characters.`);
        return;
      }
      source = vscode.workspace.asRelativePath(document.uri, false).replaceAll("\\", "/");
      if (!/^[A-Za-z0-9_./ -]{1,200}$/.test(source) || source.split("/").includes("..")) source = "active.sql";
      this.lastBiActiveFile = document.uri;
      scripts = [{ path: source, text }];
      warnings = [];
    } else {
      ({ scripts, warnings } = await collectBiScripts());
      if (!scripts.length) {
        void vscode.window.showWarningMessage("No warehouse scripts in bi/warehouse. Create the BI Lab files first.");
        return;
      }
      source = mode === "build" ? "bi/warehouse" : "analysis only";
    }
    const model = await readBiModel();
    try {
      await this.host.runtime.labs.bi.runBiLab({ mode, source, scripts, model: model.model, modelError: model.error, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(`BI Lab run failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.host.refresh();
  }

  /** BI Lab dbt tab: run a dbt command on bi/dbt with the Datapass dbt emulation (never dbt Core, never a shell). */
  private async runBiDbt(command: BiDbtCommand, selectText: string, fullRefresh: boolean): Promise<void> {
    if (![...DBT_COMMANDS, "parse"].includes(command)) return;
    const parsed = parseSelect(typeof selectText === "string" ? selectText : "");
    if (parsed.error) {
      void vscode.window.showWarningMessage(parsed.error);
      return;
    }
    await saveDirtyUnder(biRoot());
    const { files, warnings } = await collectBiDbtFiles();
    if (!("dbt_project.yml" in files)) {
      void vscode.window.showWarningMessage("No dbt project in bi/dbt. Create the BI Lab files first.");
      return;
    }
    try {
      await this.host.runtime.labs.bi.runBiDbt({ command, select: parsed.selectors, selectText, fullRefresh: fullRefresh === true, files, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(`dbt run failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.host.refresh();
  }

  private async revealBiLine(relative: string, line: number): Promise<void> {
    if (!Number.isInteger(line) || line < 1) return;
    const uri = biFileUri(relative) ?? (this.lastBiActiveFile && vscode.workspace.asRelativePath(this.lastBiActiveFile, false)
      .replaceAll("\\", "/") === relative ? this.lastBiActiveFile : undefined);
    if (!uri || !(await exists(uri))) return;
    await this.host.revealBeside(uri, atLine(line));
  }
}
