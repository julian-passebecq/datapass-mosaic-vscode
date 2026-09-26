import * as vscode from "vscode";
import type { ModuleId } from "../../modules";
import {
  emptyProgress,
  toMissionCheckView,
  toMissionView,
  toProgressFile,
  type MissionProgressView,
  type MissionsProgressFile,
  type MissionView
} from "../../platform/missions";
import type {
  LakehouseEngine,
  LakehouseMessage,
  LakehouseMissionAction,
  LakehouseMissionDetail,
  LakehouseRunView,
  LakehouseStorageView,
  LakehouseViewState
} from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";

const PROGRESS = [".datapass", "lakehouse", "progress.json"];
const ID = /^[a-z0-9][a-z0-9-]{0,47}$/;
const PACK = "lakehouse-v1";

interface MissionList {
  missions: MissionView[];
  details: Record<string, LakehouseMissionDetail>;
  ducklake?: LakehouseViewState["ducklake"];
  trustedPython: boolean;
}

/** Where a Lakehouse mission lives in the workspace. */
export function lakehouseFolder(id: string): string {
  if (!ID.test(id)) throw new Error(`Invalid mission id ${id}.`);
  return `lakehouse/${id}`;
}

/**
 * Lakehouse Lab: storage-layout missions done with the learner's own DuckDB SQL (or Polars, trusted Python) in
 * lakehouse/<id>/. The runtime builds the folder from the pack, runs the learner's file when asked (Run) and judges
 * what it left on disk and in the mission's DuckLake catalog. Progress: .datapass/lakehouse/progress.json.
 */
export class LakehouseController implements LabController<LakehouseMessage> {
  private list?: MissionList;
  private lastRun?: LakehouseRunView;
  private storage?: LakehouseStorageView;
  private error?: string;

  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<LakehouseMessage> = {
    lakehouseMission: message => this.missionAction(message.action, message.missionId),
    lakehouseRun: message => this.run(message.missionId, message.engine),
    lakehouseStorage: async message => {
      await this.readStorage(message.missionId);
      await this.host.refresh();
    },
    refreshLakehouseLab: async () => {
      this.list = undefined;
      await this.host.refresh();
    }
  };

  async contribute(selected: ModuleId): Promise<Partial<WorkbenchStateExtras>> {
    return { lakehouse: selected === "lakehouse" ? await this.state() : undefined };
  }

  private async state(): Promise<LakehouseViewState> {
    const running = this.host.runtime.snapshot().status === "running";
    if (!this.list && running) {
      try {
        this.list = parseList(await this.host.runtime.labs.lakehouse.missions());
        this.error = undefined;
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error);
      }
    }
    return {
      missions: { missions: this.list?.missions ?? [], progress: (await readProgress()).missions },
      details: this.list?.details ?? {},
      ducklake: this.list?.ducklake,
      trustedPython: this.list?.trustedPython ?? false,
      lastRun: this.lastRun,
      storage: this.storage,
      error: running ? this.error : undefined
    };
  }

  private mission(id: string): MissionView {
    const mission = this.list?.missions.find(item => item.id === id);
    if (!mission) throw new Error(`Unknown Lakehouse mission ${id}.`);
    return mission;
  }

  private async missionAction(action: LakehouseMissionAction, missionId: string): Promise<void> {
    try {
      const mission = this.mission(missionId);
      const lab = this.host.runtime.labs.lakehouse;
      if (action === "restartMission") {
        const choice = await vscode.window.showWarningMessage(
          `Start the mission over? ${lakehouseFolder(missionId)} is moved to .datapass/lakehouse/attic/ (nothing is deleted) and rebuilt as the ticket found it, with a fresh lake.`,
          { modal: true }, "Start over");
        if (choice !== "Start over") return;
      }
      if (action === "startMission" || action === "restartMission") {
        await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Building the mission folder…" },
          () => lab.start(missionId));
        await vscode.workspace.fs.writeFile(this.uri(missionId, "TICKET.md"), new TextEncoder().encode(ticketMarkdown(mission, this.list?.details[missionId])));
        await updateProgress(missionId, () => ({ started: new Date().toISOString(), batches: [], hintsShown: 0 }));
        if (this.lastRun?.missionId === missionId) this.lastRun = undefined;
        await this.readStorage(missionId);
        await this.open(mission);
      } else if (action === "openMission") {
        await this.open(mission);
      } else if (action === "revealMissionHint") {
        await updateProgress(missionId, current => ({ ...current, hintsShown: Math.min(mission.hints.length, current.hintsShown + 1) }));
      } else if (action === "checkMission") {
        const raw = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Checking the mission…" },
          () => lab.check(missionId));
        const result = toMissionCheckView(raw);
        await updateProgress(missionId, current => ({
          ...current,
          lastCheck: result,
          passedAt: current.passedAt ?? (result.status === "passed" ? result.checkedAt : undefined)
        }));
        await this.readStorage(missionId);
      }
    } catch (error) {
      void vscode.window.showErrorMessage(`Lakehouse Lab: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.host.refresh();
  }

  /** The ticket beside the Workbench, then the learner's file for the first engine. */
  private async open(mission: MissionView): Promise<void> {
    const ticket = this.uri(mission.id, "TICKET.md");
    if (await exists(ticket)) await this.host.openBeside(ticket);
    const detail = this.list?.details[mission.id];
    const file = detail?.files[detail.engines[0]];
    if (file) {
      const uri = this.uri(mission.id, file);
      if (await exists(uri)) await vscode.window.showTextDocument(uri, { viewColumn: vscode.ViewColumn.Beside, preview: false });
    }
  }

  /** Run the learner's file: saved first, then DuckDB (bounded to the folder) or Polars (trusted Python). */
  private async run(missionId: string, engine: LakehouseEngine): Promise<void> {
    try {
      const file = this.list?.details[missionId]?.files[engine];
      if (!file) throw new Error(`This mission has no ${engine} file.`);
      const document = vscode.workspace.textDocuments.find(doc => doc.uri.toString() === this.uri(missionId, file).toString());
      if (document?.isDirty) await document.save();
      const raw = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Running ${file}…` },
        () => this.host.runtime.labs.lakehouse.run(missionId, engine));
      this.lastRun = toRunView(raw, missionId, engine, file);
      await this.readStorage(missionId);
    } catch (error) {
      this.lastRun = { missionId, engine, file: "", truth: "", at: new Date().toISOString(), error: error instanceof Error ? error.message : String(error) };
    }
    await this.host.refresh();
  }

  private async readStorage(missionId: string): Promise<void> {
    try {
      this.storage = { missionId, ...(await this.host.runtime.labs.lakehouse.storage(missionId) as Omit<LakehouseStorageView, "missionId">) };
    } catch (error) {
      this.storage = { missionId, folders: [], snapshotsError: error instanceof Error ? error.message : String(error) };
    }
  }

  private uri(missionId: string, file: string): vscode.Uri {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) throw new Error("Open a workspace folder first.");
    return vscode.Uri.joinPath(root, ...lakehouseFolder(missionId).split("/"), ...file.split("/"));
  }
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function parseList(raw: unknown): MissionList {
  const body = record(raw) ?? {};
  const missions: MissionView[] = [];
  const details: Record<string, LakehouseMissionDetail> = {};
  for (const item of Array.isArray(body.missions) ? body.missions : []) {
    const view = toMissionView(item, PACK);
    const fields = record(item);
    if (!view || !fields) continue;
    missions.push(view);
    const engines = (Array.isArray(fields.engines) ? fields.engines : []).filter((e): e is LakehouseEngine => e === "duckdb" || e === "polars");
    const files: Partial<Record<LakehouseEngine, string>> = {};
    for (const engine of engines) {
      const file = record(fields.files)?.[engine];
      if (typeof file === "string") files[engine] = file;
    }
    details[view.id] = {
      engines, files, ducklake: fields.ducklake === true,
      delta: (Array.isArray(fields.delta) ? fields.delta : []).filter((d): d is string => typeof d === "string"),
      concepts: (Array.isArray(fields.concepts) ? fields.concepts : []).filter((c): c is string => typeof c === "string")
    };
  }
  const ducklake = record(body.ducklake);
  return {
    missions, details, trustedPython: body.trusted_python === true,
    ducklake: ducklake ? {
      installed: ducklake.installed === true, version: typeof ducklake.version === "string" ? ducklake.version : null,
      delta: ducklake.delta === true, deltaVersion: typeof ducklake.delta_version === "string" ? ducklake.delta_version : null,
      error: typeof ducklake.error === "string" ? ducklake.error : null
    } : undefined
  };
}

function toRunView(raw: unknown, missionId: string, engine: LakehouseEngine, file: string): LakehouseRunView {
  const body = record(raw) ?? {};
  const statements = Array.isArray(body.statements) ? body.statements.flatMap(item => {
    const statement = record(item);
    if (!statement) return [];
    return [{
      type: String(statement.type ?? ""),
      sql: String(statement.sql ?? ""),
      columns: Array.isArray(statement.columns) ? statement.columns.map(String) : undefined,
      rows: Array.isArray(statement.rows) ? statement.rows.map(row => Array.isArray(row) ? row.map(cell => cell === null ? null : String(cell)) : []) : undefined,
      truncated: statement.truncated === true
    }];
  }) : undefined;
  return {
    missionId, engine, file,
    truth: String(body.truth ?? ""),
    at: new Date().toISOString(),
    elapsedMs: typeof body.elapsed_ms === "number" ? body.elapsed_ms : undefined,
    statements,
    error: typeof body.error === "string" ? body.error : undefined,
    failedStatement: typeof body.failed_statement === "number" ? body.failed_statement : undefined,
    exitCode: typeof body.exit_code === "number" ? body.exit_code : undefined,
    stdout: typeof body.stdout === "string" ? body.stdout : undefined,
    stderr: typeof body.stderr === "string" ? body.stderr : undefined
  };
}

/** TICKET.md in the mission folder, next to the learner's files. */
export function ticketMarkdown(mission: MissionView, detail: LakehouseMissionDetail | undefined): string {
  const files = detail ? detail.engines.map(engine => `\`${detail.files[engine]}\` (${engine === "duckdb" ? "DuckDB SQL" : "Polars, trusted Python"})`).join(" or ") : "";
  return [
    `# ${mission.ticket.subject}`,
    "",
    `From: ${mission.ticket.from} · Mission \`${mission.id}\` (${mission.level}${mission.estimate ? `, ${mission.estimate}` : ""})`,
    "",
    mission.ticket.body,
    "",
    "## Acceptance criteria",
    "",
    mission.acceptance.map(item => `- [ ] ${item.text}`).join("\n"),
    "",
    `Work in ${files || "the mission's file"}, then use **Run** in the Lakehouse Lab: it runs the file for real on your`,
    "machine, inside this folder" + (detail?.ducklake ? " (the lab attaches this folder's DuckLake catalog as `lake`)."
      : detail?.delta.length ? ` (the lab attaches the Delta table${detail.delta.length > 1 ? "s" : ""} ${detail.delta.map(d => `\`${d.split("/").pop()}\``).join(", ")}).` : "."),
    "**Check my work** reads what the run left on disk and in the catalog. Hints are there too, one at a time.",
    ""
  ].join("\n");
}

async function readProgress(): Promise<MissionsProgressFile> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) return emptyProgress();
  try {
    return toProgressFile(JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(root, ...PROGRESS)))));
  } catch {
    return emptyProgress();
  }
}

async function updateProgress(id: string, change: (current: MissionProgressView) => MissionProgressView): Promise<void> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) throw new Error("Open a workspace folder first.");
  const file = await readProgress();
  file.missions[id] = change(file.missions[id] ?? { batches: [], hintsShown: 0 });
  const uri = vscode.Uri.joinPath(root, ...PROGRESS);
  await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(uri, ".."));
  await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(JSON.stringify(file, null, 2) + "\n"));
}
