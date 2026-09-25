import * as vscode from "vscode";
import { loadAirflowState } from "./airflowState";
import { loadBiState } from "./biState";
import { loadDbtState } from "./dbtState";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { loadFactoryState } from "./factoryState";
import { MODULES, type ModuleId } from "./modules";
import { readMosaicLayout } from "./mosaicLayoutStore";
import { loadPipelineState } from "./pipelineState";
import { readProjectManifest } from "./project/projectManifest";
import type { PythonTrustController } from "./pythonTrustController";
import type { RuntimeManager } from "./runtimeManager";
import { loadProjectsState, readProgress } from "./projectState";
import { emptyPracticeProgress } from "./platform/practiceProgress";
import type { PracticeViewState, ProjectsHostState, SparkLabProfileView, WorkbenchFocus, WorkbenchViewState } from "./webview/contracts";

export async function collectWorkbenchState(
  selectedModule: ModuleId,
  runtimeManager: RuntimeManager,
  extensionUri: vscode.Uri,
  pythonTrust: PythonTrustController,
  extras: { focus?: WorkbenchFocus; projects?: ProjectsHostState } = {}
): Promise<WorkbenchViewState> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  const manifest = await readProjectManifest();
  const practice = selectedModule === "practice"
    ? await loadPracticeState(extensionUri)
    : undefined;
  const pipeline = selectedModule === "pipeline"
    ? await loadPipelineState(runtimeManager)
    : undefined;
  const airflow = selectedModule === "airflow"
    ? await loadAirflowState()
    : undefined;
  const dbt = selectedModule === "dbt"
    ? await loadDbtState()
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
    projects,
    focus: extras.focus
  };
}

async function loadPracticeState(extensionUri: vscode.Uri): Promise<PracticeViewState> {
  const progress = await readProgress();
  return {
    exercises: await loadExerciseCatalog(extensionUri),
    progress: progress.document.practice ?? emptyPracticeProgress(),
    progressError: progress.error,
    canSaveProgress: Boolean(vscode.workspace.workspaceFolders?.length)
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
