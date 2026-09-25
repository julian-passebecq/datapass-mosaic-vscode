import * as vscode from "vscode";
import { dctValidate, writeDbtProfiles, type DbtToolsManager } from "./dbtLab";
import { findDbtProjects } from "./dbtState";
import {
  emptyProgress,
  missionFolder,
  nextBatch,
  ticketMarkdown,
  toMissionCheckView,
  toMissionView,
  toProgressFile,
  type MissionProgressView,
  type MissionsProgressFile,
  type MissionView
} from "./platform/missions";
import type { RuntimeManager } from "./runtimeManager";

const PROGRESS = [".datapass", "missions", "progress.json"];

/**
 * Missions on the host side: the shipped content (content/missions), the learner's project folder
 * (missions/<id>/, copied once from the pack's base project and the mission's overlay, never overwritten), the
 * progress file (.datapass/missions/progress.json), and the runtime calls that load fixtures and run the checker.
 */
export class MissionsService {
  private cache?: MissionView[];

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly runtime: RuntimeManager,
    private readonly tools: Pick<DbtToolsManager, "binDir" | "venvRoot" | "snapshot">
  ) {}

  /** Every shipped mission of a lab, in the order of its pack. */
  async list(lab = "dbt"): Promise<MissionView[]> {
    if (!this.cache) {
      const root = vscode.Uri.joinPath(this.extensionUri, "content", "missions");
      const missions: MissionView[] = [];
      let packs: [string, vscode.FileType][] = [];
      try {
        packs = await vscode.workspace.fs.readDirectory(root);
      } catch {
        packs = [];
      }
      for (const [packId, type] of packs.sort(([a], [b]) => a.localeCompare(b))) {
        if (!(type & vscode.FileType.Directory)) continue;
        const pack = await readJson(vscode.Uri.joinPath(root, packId, "pack.json")) as { missions?: unknown } | undefined;
        for (const id of Array.isArray(pack?.missions) ? pack!.missions : []) {
          if (typeof id !== "string") continue;
          const mission = toMissionView(await readJson(vscode.Uri.joinPath(root, packId, id, "mission.json")), packId);
          if (mission) missions.push(mission);
        }
      }
      this.cache = missions;
    }
    return this.cache.filter(mission => mission.lab === lab);
  }

  async progress(): Promise<MissionsProgressFile> {
    const root = workspaceRoot();
    if (!root) return emptyProgress();
    return toProgressFile(await readJson(vscode.Uri.joinPath(root, ...PROGRESS)));
  }

  /**
   * Start (or start over): copy the project if the folder does not exist yet (the learner's files are never
   * overwritten), write TICKET.md, and load the first fixture batch, which resets the mission's schemas.
   */
  async start(id: string): Promise<vscode.Uri> {
    const root = requireRoot();
    const mission = await this.mission(id);
    const folder = vscode.Uri.joinPath(root, ...missionFolder(id).split("/"));
    const content = vscode.Uri.joinPath(this.extensionUri, "content", "missions", mission.packId);
    await copyWithoutOverwrite(vscode.Uri.joinPath(content, "base"), folder);
    await copyWithoutOverwrite(vscode.Uri.joinPath(content, id, "project"), folder);
    await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(folder, "TICKET.md"), new TextEncoder().encode(ticketMarkdown(mission)));
    await writeDbtProfiles(root, (await findDbtProjects()).map(project => project.file));
    await this.runtime.missionSetup(id, mission.batches[0].id);
    await this.update(id, () => ({ started: new Date().toISOString(), batches: [mission.batches[0].id], hintsShown: 0 }));
    return folder;
  }

  /** Load the next fixture batch (for example: tomorrow's export). */
  async loadNextBatch(id: string): Promise<string | undefined> {
    const mission = await this.mission(id);
    const progress = (await this.progress()).missions[id];
    const batch = nextBatch(mission, progress);
    if (!batch) return undefined;
    await this.runtime.missionSetup(id, batch.id);
    await this.update(id, current => ({ ...current, batches: [...current.batches, batch.id] }));
    return batch.label;
  }

  async revealHint(id: string): Promise<void> {
    const mission = await this.mission(id);
    await this.update(id, current => ({ ...current, hintsShown: Math.min(mission.hints.length, current.hintsShown + 1) }));
  }

  /** The hidden checker: the runtime judges the catalog, the artifacts and the files; dct validate runs here. */
  async check(id: string): Promise<void> {
    const root = requireRoot();
    const mission = await this.mission(id);
    const folder = vscode.Uri.joinPath(root, ...missionFolder(id).split("/"));
    const dct: Record<string, unknown> = {};
    if (mission.dctBoards.length) {
      const tools = this.tools.snapshot();
      if (tools.status === "ready" && tools.versions?.["dbt-charts"]) {
        const profilesDir = await writeDbtProfiles(root, (await findDbtProjects()).map(project => project.file));
        for (const board of mission.dctBoards) dct[board] = await dctValidate(this.tools, folder, profilesDir, board);
      }
    }
    const result = toMissionCheckView(await this.runtime.missionCheck(id, dct));
    await this.update(id, current => ({
      ...current,
      lastCheck: result,
      passedAt: current.passedAt ?? (result.status === "passed" ? result.checkedAt : undefined)
    }));
  }

  private async mission(id: string): Promise<MissionView> {
    const mission = (await this.list("dbt")).find(item => item.id === id)
      ?? (this.cache ?? []).find(item => item.id === id);
    if (!mission) throw new Error(`Unknown mission ${id}.`);
    return mission;
  }

  private async update(id: string, change: (current: MissionProgressView) => MissionProgressView): Promise<void> {
    const root = requireRoot();
    const file = await this.progress();
    file.missions[id] = change(file.missions[id] ?? { batches: [], hintsShown: 0 });
    const uri = vscode.Uri.joinPath(root, ...PROGRESS);
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(uri, ".."));
    await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(JSON.stringify(file, null, 2) + "\n"));
  }
}

function workspaceRoot(): vscode.Uri | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri;
}

function requireRoot(): vscode.Uri {
  const root = workspaceRoot();
  if (!root) throw new Error("Open a workspace folder first.");
  return root;
}

async function readJson(uri: vscode.Uri): Promise<unknown> {
  try {
    return JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)));
  } catch {
    return undefined;
  }
}

async function copyWithoutOverwrite(source: vscode.Uri, target: vscode.Uri): Promise<void> {
  let entries: [string, vscode.FileType][];
  try {
    entries = await vscode.workspace.fs.readDirectory(source);
  } catch {
    return;
  }
  await vscode.workspace.fs.createDirectory(target);
  for (const [name, type] of entries) {
    const from = vscode.Uri.joinPath(source, name);
    const to = vscode.Uri.joinPath(target, name);
    if (type & vscode.FileType.Directory) {
      await copyWithoutOverwrite(from, to);
      continue;
    }
    try {
      await vscode.workspace.fs.stat(to);
    } catch {
      await vscode.workspace.fs.copy(from, to, { overwrite: false });
    }
  }
}
