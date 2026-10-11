import * as vscode from "vscode";
import { createExclusiveAt } from "./exclusiveFile";

/**
 * Exclusive create for Build and the Mosaic exchange: the file is written only when it does not exist yet, so a race
 * with another writer never replaces a file. Returns false when it already existed. Local folders only.
 */
export async function createExclusive(uri: vscode.Uri, content: string | Uint8Array): Promise<boolean> {
  if (uri.scheme !== "file") throw new Error("Datapass Build writes to a local folder only.");
  return createExclusiveAt(uri.fsPath, content);
}

/** Entries directly in a folder (an absent folder has none). */
export async function fileNames(folder: vscode.Uri): Promise<{ name: string; isFile: boolean }[]> {
  try {
    return (await vscode.workspace.fs.readDirectory(folder)).map(([name, type]) => ({
      name,
      isFile: (type & vscode.FileType.File) !== 0
    }));
  } catch {
    return [];
  }
}

export function workspaceRoot(): vscode.Uri | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri;
}
