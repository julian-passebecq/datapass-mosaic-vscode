import * as vscode from "vscode";
import type { QueryHistoryEntry } from "./platform/mosaicTools";
import { loadAirflowState } from "./airflowState";
import { loadBiState } from "./biState";
import { loadDbtState } from "./dbtState";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { loadFactoryState } from "./factoryState";
import { MODULE_FAMILIES, MODULES, type WorkbenchView } from "./modules";
import { readMosaicLayout } from "./mosaicLayoutStore";
import { loadPipelineState } from "./pipelineState";
import { readProjectManifest } from "./project/projectManifest";
import type { PythonTrustController } from "./pythonTrustController";
import type { RuntimeManager } from "./runtimeManager";
import type { DctValidationView } from "./platform/dbtTools";
import { loadProjectsState, readProgress } from "./projectState";
import { emptyPracticeProgress } from "./platform/practiceProgress";
import type { DbtToolsView, HomeViewState, DbtViewState, PracticeViewState, ProjectsHostState, SparkLabProfileView, TerminalViewState, InfraViewState, LakehouseViewState, ApiLabViewState, WorkbenchFocus, WorkbenchViewState } from "./webview/contracts";

/** What the host adds to the state it collects: the focus, and what the lab controllers keep (see src/labs). */
export interface WorkbenchStateExtras {
  focus?: WorkbenchFocus;
  projects?: ProjectsHostState;
  dbtLab?: {
    tools: DbtToolsView;
    selected?: string;
    shellIntegration?: boolean;
    validations?: ReadonlyMap<string, DctValidationView>;
    serveUrl?: string;
    missions?: DbtViewState["missions"];
  };
  practiceSolutions?: Record<string, string>;
  queryHistory?: readonly QueryHistoryEntry[];
  terminal?: TerminalViewState;
  infra?: InfraViewState;
  home?: HomeViewState;
  lakehouse?: LakehouseViewState;
  apilab?: ApiLabViewState;
}

export async function collectWorkbenchState(
  selectedModule: WorkbenchView,
  runtimeManager: RuntimeManager,
  extensionUri: vscode.Uri,
  pythonTrust: PythonTrustController,
  extras: WorkbenchStateExtras = {}
): Promise<WorkbenchViewState> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  const manifest = await readProjectManifest();
  const practice = selectedModule === "practice"
    ? await loadPracticeState(extensionUri, extras.practiceSolutions ?? {})
    : undefined;
  const pipeline = selectedModule === "pipeline"
    ? await loadPipelineState(runtimeManager)
    : undefined;
  const airflow = selectedModule === "airflow"
    ? await loadAirflowState()
    : undefined;
  const dbt = selectedModule === "dbt" && extras.dbtLab
    ? await loadDbtState(extras.dbtLab)
    : undefined;
  const factory = selectedModule === "fabric"
    ? await loadFactoryState()
    : undefined;
  const bi = selectedModule === "bi"
    ? await loadBiState()
    : undefined;
  const projects = selectedModule === "projects"
    ? { ...(await loadProjectsState(extensionUri)), ...extras.projects }
    : undefined;
  const mosaicLayout = selectedModule === "mosaic"
    ? await readMosaicLayout()
    : undefined;
  const sparkProfiles = selectedModule === "sparklab"
    ? await loadSparkProfiles(extensionUri)
    : undefined;
  const runtime = runtimeManager.snapshot();
  const trust = await pythonTrust.resolve();

  return {
    selectedModule,
    modules: MODULES,
    families: MODULE_FAMILIES,
    home: selectedModule === "home" ? extras.home : undefined,
    workspace: {
      folderName: folder?.name,
      manifestExists: manifest.exists,
      manifestValid: manifest.exists && manifest.errors.length === 0,
      projectTitle: manifest.manifest?.project.title,
      errors: manifest.errors
    },
    runtime,
    pythonTrust: {
      ...trust,
      restartRequired: runtime.status === "running" && (runtime.trustedPython === true) !== trust.effective
    },
    mosaicLayout,
    sparkProfiles,
    practice,
    pipeline,
    airflow,
    factory,
    bi,
    dbt,
    terminal: selectedModule === "terminal" ? extras.terminal : undefined,
    infra: selectedModule === "infra" ? extras.infra : undefined,
    lakehouse: selectedModule === "lakehouse" ? extras.lakehouse : undefined,
    apilab: selectedModule === "apilab" ? extras.apilab : undefined,
    projects,
    focus: extras.focus,
    queryHistory: extras.queryHistory
  };
}

async function loadPracticeState(extensionUri: vscode.Uri, solutions: Record<string, string>): Promise<PracticeViewState> {
  const progress = await readProgress();
  return {
    exercises: await loadExerciseCatalog(extensionUri),
    progress: progress.document.practice ?? emptyPracticeProgress(),
    progressError: progress.error,
    canSaveProgress: Boolean(vscode.workspace.workspaceFolders?.length),
    solutions
  };
}

async function loadSparkProfiles(extensionUri: vscode.Uri): Promise<SparkLabProfileView[]> {
  try {
    const uri = vscode.Uri.joinPath(extensionUri, "runtime", "sparklab", "cluster_profiles.json");
    const raw = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri))) as Record<string, { id?: unknown; name?: unknown }>;
    return Object.entries(raw).map(([key, profile]) => ({
      id: typeof profile.id === "string" ? profile.id : key,
      label: typeof profile.name === "string" ? profile.name : key
    }));
  } catch {
    return [{ id: "generic_8x8", label: "generic_8x8" }];
  }
}
