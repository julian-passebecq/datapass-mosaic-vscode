import * as vscode from "vscode";
import {
  MOSAIC_LAYOUT_PATH,
  parseMosaicLayoutDocument,
  sanitizeMosaicLayout,
  serializeMosaicLayout,
  type MosaicLayoutItem
} from "./platform/mosaicLayout";

function layoutUri(): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  return root ? vscode.Uri.joinPath(root, ...MOSAIC_LAYOUT_PATH.split("/")) : undefined;
}

export async function readMosaicLayout(): Promise<MosaicLayoutItem[] | undefined> {
  const uri = layoutUri();
  if (!uri) return undefined;
  try {
    return parseMosaicLayoutDocument(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)));
  } catch {
    return undefined;
  }
}

/** Validates webview input before it touches the workspace. Returns false when rejected. */
export async function writeMosaicLayout(raw: unknown): Promise<boolean> {
  const uri = layoutUri();
  const layout = sanitizeMosaicLayout(raw);
  if (!uri || !layout) return false;
  const text = serializeMosaicLayout(layout);
  try {
    if (new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)) === text) return true;
  } catch {
    // Missing file: fall through and create it.
  }
  await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(uri, ".."));
  await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(text));
  return true;
}
