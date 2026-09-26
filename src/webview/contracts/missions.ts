import type { MissionProgressView, MissionView } from "../../platform/missions";

/** A lab's ticket-style missions and the learner's progress (.datapass/missions/progress.json). */
export interface MissionListView {
  missions: readonly MissionView[];
  progress: Readonly<Record<string, MissionProgressView>>;
}

/** Missions are shared by the dbt Lab, the Terminal Lab and the Infra Lab; the mission's lab decides what opens. */
export type MissionMessage =
  | { type: "startMission"; missionId: string }
  | { type: "restartMission"; missionId: string }
  | { type: "openMission"; missionId: string }
  | { type: "loadMissionBatch"; missionId: string }
  | { type: "revealMissionHint"; missionId: string }
  | { type: "checkMission"; missionId: string };
