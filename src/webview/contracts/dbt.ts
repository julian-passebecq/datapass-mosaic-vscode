import type { MissionListView } from "./missions";
import type { DbtCoreRunView } from "../../platform/dbtArtifacts";
import type { DbtCommand, DctFormat, DctRenderView, DctValidationView } from "../../platform/dbtTools";

/** The managed dbt tools environment (dbt Core, dbt-duckdb, dbt Charts), installed only on an explicit action. */
export interface DbtToolsView {
  status: "missing" | "installing" | "ready" | "error";
  python?: string;
  binDir?: string;
  /** Installed package versions (dbt-core, dbt-duckdb, duckdb, dbt-charts), read from package metadata. */
  versions?: Readonly<Record<string, string | null>>;
  detail?: string;
  progress?: { step: number; totalSteps: number; label: string; activity?: string; startedAt: number };
}

export interface DbtProjectRef {
  /** Folder relative to the workspace root, with forward slashes. */
  path: string;
  name?: string;
  profile?: string;
}

export interface DbtViewState {
  projects: readonly DbtProjectRef[];
  /** The selected project's folder (relative), when there is one. */
  selected?: string;
  tools: DbtToolsView;
  /** `.datapass/dbt/profiles.yml`, generated; no secrets. */
  profilesPath: string;
  /** What the last real dbt Core command left in target/ (manifest.json, run_results.json). */
  run?: DbtCoreRunView;
  artifactError?: string;
  /** The dbt terminal reports command start and end (VS Code shell integration), so the handoff is automatic. */
  shellIntegration?: boolean;
  /** dbt Charts boards of the selected project (charts/*.yml) and what dct last rendered for them. */
  charts?: DbtChartsView;
  /** Ticket-style missions of the dbt Lab and the learner's progress (.datapass/missions/progress.json). */
  missions?: MissionListView;
}

export interface DbtBoardView {
  /** Relative to the project: `charts/revenue.yml`. */
  path: string;
  /** renders/<stem>.png as a data: URI (the Workbench CSP allows data: images; nothing else is injected). */
  png?: string;
  pngAt?: string;
  /** renders/<stem>.html, when dct rendered it (opened outside the Workbench: it carries scripts). */
  html?: string;
  /** renders/<stem>.json: the resolved board with each chart's data. */
  render?: DctRenderView;
  renderError?: string;
  /** The last `dct validate --json` of this board. */
  validation?: DctValidationView;
}

export interface DbtChartsView {
  /** dbt_charts.yml at the project root. */
  configured: boolean;
  boards: readonly DbtBoardView[];
  /** The loopback `dct serve` URL while it runs. */
  serveUrl?: string;
}

export interface DbtViewSlice {
  dbt?: DbtViewState;
}

export type DbtMessage =
  | { type: "createDbtSample" }
  | { type: "selectDbtProject"; path: string }
  | { type: "refreshDbt" }
  | { type: "installDbtTools" }
  | { type: "showDbtToolsLog" }
  | { type: "runDbtCommand"; command: DbtCommand; select: string; exclude: string; fullRefresh: boolean }
  | { type: "openDbtTerminal" }
  | { type: "openDbtFile"; path: string }
  | { type: "runDct"; action: "validate" | "render"; board: string; format?: DctFormat }
  | { type: "serveDct" }
  | { type: "stopDctServe" }
  | { type: "openDctHtml"; board: string };
