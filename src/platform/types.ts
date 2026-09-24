export type StatusLevel = "ready" | "partial" | "missing" | "unbound" | "error";

export interface ToolProbe {
  id: string;
  label: string;
  available: boolean;
  version?: string;
  detail?: string;
}

export interface PlatformAction {
  id: string;
  label: string;
  enabled: boolean;
  kind: "open" | "copy" | "run" | "link" | "configure";
  detail?: string;
}

export interface PlatformState {
  id: string;
  title: string;
  status: StatusLevel;
  summary: string;
  tools: ToolProbe[];
  actions: PlatformAction[];
  details?: string[];
}

export interface ProjectBinding {
  id: string;
  label: string;
  value?: string;
  status: "bound" | "missing" | "unknown";
}

export interface ProjectProfileState {
  id: string;
  title: string;
  active: boolean;
  summary: string;
  bindings: ProjectBinding[];
  actions: PlatformAction[];
}

export interface GalaxyState {
  generatedAt: string;
  project: ProjectProfileState;
  platforms: PlatformState[];
}

export interface PlatformAdapter {
  id: string;
  displayName: string;
  detect(): Promise<PlatformState>;
}
