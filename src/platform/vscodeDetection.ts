import * as vscode from "vscode";
import type { ToolProbe } from "./types";

export function detectExtension(id: string, label: string): ToolProbe {
  const ext = vscode.extensions.getExtension(id);
  return {
    id,
    label,
    available: Boolean(ext),
    version: typeof ext?.packageJSON?.version === "string" ? ext.packageJSON.version : undefined,
    detail: ext ? (ext.isActive ? "Active" : "Installed") : "Not installed"
  };
}

export async function commandAvailable(command: string): Promise<boolean> {
  const commands = new Set(await vscode.commands.getCommands(true));
  return commands.has(command);
}

export async function anyWorkspaceFile(globs: string[]): Promise<boolean> {
  for (const glob of globs) {
    const found = await vscode.workspace.findFiles(glob, "**/{node_modules,.git,dist,out}/**", 1);
    if (found.length > 0) return true;
  }
  return false;
}
