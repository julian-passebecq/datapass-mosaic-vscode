import type { ModuleFamily, ModuleId, WorkbenchView } from "../../modules";
import type { PythonTrustState } from "../../platform/pythonTrust";

export type RuntimeStatus = "stopped" | "starting" | "running" | "error";

export interface LocalCatalogAssetView {
  name: string;
  layer: string;
  row_count: number;
  fresh: boolean;
  producer?: string;
}

export interface RuntimeEnvironmentView {
  /** "stale": the managed venv holds the runtime of another extension build; Update runtime reinstalls it. */
  status: "missing" | "setting-up" | "ready" | "stale" | "error";
  python?: string;
  detail?: string;
  /** Present while status is "setting-up". */
  progress?: RuntimeSetupProgressView;
}

export interface RuntimeSetupProgressView {
  step: number;
  totalSteps: number;
  label: string;
  /** Latest recognised pip/venv activity, e.g. "Downloading polars (35.2 MB)". */
  activity?: string;
  /** Epoch milliseconds when setup started. */
  startedAt: number;
}

export interface CatalogLeaseView {
  /** The command line that borrows .datapass/data/workspace.duckdb. */
  holder: string;
  since: string;
  /** The last reattach attempt failed (the file is still held); the text says why. */
  reattachError?: string;
}

export interface PythonTrustView {
  state: PythonTrustState;
  effective: boolean;
  reason: string;
  /** The running runtime was started with a different trust setting. */
  restartRequired: boolean;
}

export interface WorkspaceViewState {
  folderName?: string;
  manifestExists: boolean;
  manifestValid: boolean;
  projectTitle?: string;
  errors: string[];
}

export interface WorkbenchFocus {
  module: ModuleId;
  tab?: string;
  query?: string;
  /** Practice: the exercise (`<pack>/<problem>/<language>`) whose language the problem card should show. */
  exerciseKey?: string;
  seq: number;
}

/** The runtime state every lab shares: the process, its environment and the local catalog. */
export interface WorkbenchRuntimeSlice {
  status: RuntimeStatus;
  url?: string;
  detail?: string;
  /** Reported by the running runtime itself (GET /api/capabilities), not assumed. */
  trustedPython?: boolean;
  catalog?: readonly LocalCatalogAssetView[];
  /** Set while the catalog file is lent to a dbt Core or dct command in the dbt Lab terminal. */
  catalogLease?: CatalogLeaseView;
  environment?: RuntimeEnvironmentView;
}

/** The Workbench shell: the Today home, the family and module tabs, the runtime card, the project manifest and the shared catalog. */
export type WorkbenchMessage =
  | { type: "ready" }
  | { type: "selectModule"; moduleId: ModuleId }
  | { type: "selectHome" }
  | { type: "openFolder" }
  | { type: "createManifest" }
  | { type: "openManifest" }
  | { type: "refreshCatalog" }
  | { type: "reattachCatalog" }
  | { type: "setTrustedPython"; enabled: boolean }
  | { type: "setupRuntime" }
  | { type: "showRuntimeLog" }
  | { type: "startRuntime" }
  | { type: "stopRuntime" }
  | { type: "openTerminal" };

/** The Today home: progress read from .datapass/progress.json and the next suggested step (src/labs/workbench/home.ts). */
export interface HomeViewState {
  hasWorkspace: boolean;
  progressError?: string;
  projects: {
    total: number;
    started: number;
    completed: number;
    /** The started project with the most recent progress that is not complete. */
    current?: HomeProjectView;
    list: HomeProjectView[];
  };
  practice: {
    total: number;
    solved: number;
    attempted: number;
    /** Exercises whose spaced review is due today or earlier (platform/practiceReview.ts dueReviews). */
    dueReviews: number;
  };
  next: HomeNextStep;
}

export interface HomeProjectView {
  id: string;
  title: string;
  percent: number;
  done: number;
  required: number;
  nextStep?: { id: string; title: string; module: ModuleId; moduleLabel: string };
}

export type HomeNextStep =
  | { kind: "open-folder"; title: string; detail: string }
  | { kind: "project-step"; title: string; detail: string; projectId: string; stepId: string; module: ModuleId }
  | { kind: "reviews"; title: string; detail: string }
  | { kind: "start-project"; title: string; detail: string; projectId: string }
  | { kind: "practice"; title: string; detail: string };

export interface HomeViewSlice {
  /** Present when the Today home is shown. */
  home?: HomeViewState;
  families: readonly ModuleFamily[];
}

export type { WorkbenchView };
