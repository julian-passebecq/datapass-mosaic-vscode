import * as vscode from "vscode";
import type { MissionView } from "../../platform/missions";
import type { MissionMessage } from "../../webview/contracts";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";

/** What a lab with missions does around the shared mission actions. */
export interface MissionLabHooks {
  /** The modal text before Start over. */
  restartWarning(missionId: string): string;
  /** Before (re)building the mission folder; may return what to do once it is built. */
  beforeStart?(missionId: string): Promise<(() => Promise<void>) | void>;
  /** Open the mission: its ticket, and the lab's terminal or project. */
  open(mission: MissionView): Promise<void>;
}

/**
 * Missions (dbt Lab, Terminal Lab, Infra Lab): start, start over, open, load the next batch, reveal a hint, or run the
 * hidden checker. The mission's lab decides what opens; a mission of an unknown lab is a dbt mission.
 */
export class MissionsController implements LabController<MissionMessage> {
  constructor(
    private readonly host: WorkbenchHost,
    private readonly labs: { dbt: MissionLabHooks } & Readonly<Record<string, MissionLabHooks>>
  ) {}

  readonly handlers: MessageHandlers<MissionMessage> = {
    startMission: message => this.missionAction(message.type, message.missionId),
    restartMission: message => this.missionAction(message.type, message.missionId),
    openMission: message => this.missionAction(message.type, message.missionId),
    loadMissionBatch: message => this.missionAction(message.type, message.missionId),
    revealMissionHint: message => this.missionAction(message.type, message.missionId),
    checkMission: message => this.missionAction(message.type, message.missionId)
  };

  private async missionAction(action: MissionMessage["type"], missionId: string): Promise<void> {
    const missions = this.host.services.missions;
    try {
      const mission = await missions.mission(missionId);
      const lab = Object.hasOwn(this.labs, mission.lab) ? this.labs[mission.lab] : this.labs.dbt;
      if (action === "restartMission") {
        const choice = await vscode.window.showWarningMessage(lab.restartWarning(missionId), { modal: true }, "Start over");
        if (choice !== "Start over") return;
      }
      if (action === "startMission" || action === "restartMission") {
        const restore = await lab.beforeStart?.(missionId);
        try {
          await missions.start(missionId);
        } finally {
          await restore?.();
        }
        await lab.open(mission);
      } else if (action === "openMission") {
        await lab.open(mission);
      } else if (action === "loadMissionBatch") {
        const label = await missions.loadNextBatch(missionId);
        if (label) void vscode.window.showInformationMessage(`Loaded: ${label}. Run dbt again, as the nightly job would.`);
      } else if (action === "revealMissionHint") {
        await missions.revealHint(missionId);
      } else if (action === "checkMission") {
        await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Checking the mission…" },
          () => missions.check(missionId));
      }
    } catch (error) {
      void vscode.window.showErrorMessage(`Mission: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.host.refresh();
  }
}
