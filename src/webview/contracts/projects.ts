import type { ProjectsViewState } from "../../platform/projects";

/** What the host is doing for the Projects module: a verification in flight, or the last one's error. */
export interface ProjectsHostState {
  verifying?: { projectId: string; stepIds: string[] };
  error?: string;
}

export interface ProjectsViewSlice {
  projects?: ProjectsViewState & ProjectsHostState;
}

export type ProjectsMessage =
  | { type: "prepareProject"; projectId: string }
  | { type: "openProjectStep"; projectId: string; stepId: string }
  | { type: "verifyProjectSteps"; projectId: string; stepIds: string[] }
  | { type: "setProjectStepManual"; projectId: string; stepId: string; checked: boolean }
  | { type: "openProgressFile" };
