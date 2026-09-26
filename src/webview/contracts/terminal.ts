import type { MissionListView } from "./missions";
import type { GitView, ShellId, ShellView } from "../../platform/terminalShells";

/** Terminal Lab: the learner's shells and Git, their choice, and the lab's missions. Datapass runs no command. */
export interface TerminalViewState {
  shells: readonly ShellView[];
  /** The shell the terminal opens with: the learner's choice when installed, otherwise the first one found. */
  shell?: ShellId;
  git: GitView;
  missions: MissionListView;
}

export interface TerminalViewSlice {
  terminal?: TerminalViewState;
}

export type TerminalMessage =
  | { type: "selectTerminalShell"; shell: ShellId }
  | { type: "openLabTerminal"; missionId?: string }
  | { type: "refreshTerminalLab" };
