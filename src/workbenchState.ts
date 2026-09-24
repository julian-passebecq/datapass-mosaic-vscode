import * as vscode from "vscode";
import { loadAirflowState } from "./airflowState";
import { loadDbtState } from "./dbtState";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { MODULES, type ModuleId } from "./modules";
import { loadPipelineState } from "./pipelineState";
import { readProjectManifest } from "./project/projectManifest";
import type { PythonTrustController } from "./pythonTrustController";
import type { RuntimeManager } from "./runtimeManager";
import type { SparkLabProfileView, WorkbenchViewState } from "./webview/contracts";

export async function collectWorkbenchState(
  selectedModule: ModuleId,
  runtimeManager: RuntimeManager,
  extensionUri: vscode.Uri,
  pythonTrust: PythonTrustController
): Promise<WorkbenchViewState> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  const manifest = await readProjectManifest();
  const practice = selectedModule === "practice"
    ? { exercises: await loadExerciseCatalog(extensionUri) }
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
    sparkProfiles,
    practice,
    pipeline,
    airflow,
    dbt
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
