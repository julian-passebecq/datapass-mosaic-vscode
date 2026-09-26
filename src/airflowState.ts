import * as vscode from "vscode";
import { readProjectManifest } from "./project/projectManifest";
import type { AirflowViewState } from "./webview/contracts";
import { safeRelativeParts } from "./platform/workspacePaths";
import { exists } from "./workspaceFiles";

export const AIRFLOW_STARTER_FILE = "retail_daily.py";

/** Where Airflow Lab DAG files live: <assets.airflow>/dags, as in an Airflow deployment. */
export async function airflowPaths(): Promise<{ root?: vscode.Uri; dagsParts: string[]; airflowParts: string[] }> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  const manifest = await readProjectManifest();
  const airflowParts = safeRelativeParts(manifest.manifest?.assets?.airflow, "airflow");
  return { root, dagsParts: [...airflowParts, "dags"], airflowParts };
}

export async function loadAirflowState(): Promise<AirflowViewState> {
  const { root, dagsParts, airflowParts } = await airflowPaths();
  const dagsFolder = dagsParts.join("/");
  const starterPath = [...dagsParts, AIRFLOW_STARTER_FILE].join("/");
  if (!root) return { dagsFolder, starterPath, starterExists: false };
  const legacy = vscode.Uri.joinPath(root, ...airflowParts, "main.dag.json");
  return {
    dagsFolder,
    starterPath,
    starterExists: await exists(vscode.Uri.joinPath(root, ...dagsParts, AIRFLOW_STARTER_FILE)),
    legacySpecPath: (await exists(legacy)) ? [...airflowParts, "main.dag.json"].join("/") : undefined
  };
}
