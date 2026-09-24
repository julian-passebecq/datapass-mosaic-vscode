import * as vscode from "vscode";
import {
  DATAPASS_MANIFEST_PATH,
  DataPassProjectManifest,
  validateProjectManifest
} from "./projectManifestModel";

export * from "./projectManifestModel";

export interface ManifestReadResult {
  exists: boolean;
  uri?: vscode.Uri;
  manifest?: DataPassProjectManifest;
  errors: string[];
}

export async function readProjectManifest(): Promise<ManifestReadResult> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) return { exists: false, errors: [] };

  const uri = vscode.Uri.joinPath(root, ...DATAPASS_MANIFEST_PATH.split("/"));
  try {
    await vscode.workspace.fs.stat(uri);
  } catch {
    return { exists: false, uri, errors: [] };
  }

  try {
    const bytes = await vscode.workspace.fs.readFile(uri);
    const raw = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
    const errors = validateProjectManifest(raw);
    return errors.length
      ? { exists: true, uri, errors }
      : { exists: true, uri, manifest: raw as DataPassProjectManifest, errors: [] };
  } catch (error) {
    return {
      exists: true,
      uri,
      errors: [`Invalid JSON: ${error instanceof Error ? error.message : String(error)}`]
    };
  }
}

export async function writeProjectManifest(
  manifest: DataPassProjectManifest
): Promise<vscode.Uri> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) {
    throw new Error("Open a workspace folder before creating a Datapass project.");
  }

  const directory = vscode.Uri.joinPath(root, ".datapass");
  const uri = vscode.Uri.joinPath(directory, "project.json");
  await vscode.workspace.fs.createDirectory(directory);
  await vscode.workspace.fs.writeFile(
    uri,
    new TextEncoder().encode(JSON.stringify(manifest, null, 2) + "\n")
  );
  return uri;
}
