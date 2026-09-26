import * as vscode from "vscode";

/** Small file helpers shared by the labs (one copy each). */

export async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

export async function writeIfMissing(uri: vscode.Uri, content: string): Promise<void> {
  if (!(await exists(uri))) {
    await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(content));
  }
}

/** Copy a folder tree, keeping every file that already exists in the target. */
export async function copyWithoutOverwrite(source: vscode.Uri, target: vscode.Uri): Promise<void> {
  await vscode.workspace.fs.createDirectory(target);
  for (const [name, type] of await vscode.workspace.fs.readDirectory(source)) {
    const from = vscode.Uri.joinPath(source, name);
    const to = vscode.Uri.joinPath(target, name);
    if ((type & vscode.FileType.Directory) !== 0) {
      await copyWithoutOverwrite(from, to);
    } else if ((type & vscode.FileType.File) !== 0 && !(await exists(to))) {
      await vscode.workspace.fs.writeFile(to, await vscode.workspace.fs.readFile(from));
    }
  }
}
