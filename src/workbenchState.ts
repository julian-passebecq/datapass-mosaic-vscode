import * as vscode from "vscode";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { MODULES, type ModuleId } from "./modules";
import { loadPipelineState } from "./pipelineState";
import { readProjectManifest } from "./project/projectManifest";
import type { RuntimeManager } from "./runtimeManager";
import type { WorkbenchViewState } from "./webview/contracts";

export async function collectWorkbenchState(
  selectedModule: ModuleId,
  runtimeManager: RuntimeManager,
  extensionUri: vscode.Uri
): Promise<WorkbenchViewState> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  const manifest = await readProjectManifest();
  const practice = selectedModule === "practice"
    ? { exercises: await loadExerciseCatalog(extensionUri) }
    : undefined;
  const pipeline = selectedModule === "pipeline"
    ? await loadPipelineState(runtimeManager)
    : undefined;

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
    runtime: runtimeManager.snapshot(),
    practice,
    pipeline
  };
}
