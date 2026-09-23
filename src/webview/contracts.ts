import type { ModuleId, WorkbenchModule } from "../modules";

export type RuntimeStatus = "stopped" | "starting" | "running" | "error";
export type ScratchKind = "sql" | "python" | "notes";

export interface RuntimeViewState {
  status: RuntimeStatus;
  url?: string;
  detail?: string;
}

export interface WorkspaceViewState {
  folderName?: string;
  manifestExists: boolean;
  manifestValid: boolean;
  projectTitle?: string;
  errors: string[];
}

export interface WorkbenchViewState {
  selectedModule: ModuleId;
  modules: readonly WorkbenchModule[];
  workspace: WorkspaceViewState;
  runtime: RuntimeViewState;
}

export type HostToWebviewMessage = {
  type: "state";
  state: WorkbenchViewState;
};

export type WebviewToHostMessage =
  | { type: "ready" }
  | { type: "selectModule"; moduleId: ModuleId }
  | { type: "createManifest" }
  | { type: "openManifest" }
  | { type: "startRuntime" }
  | { type: "stopRuntime" }
  | { type: "openTerminal" }
  | { type: "openScratch"; kind: ScratchKind };
