import * as vscode from "vscode";
import { readProjectManifest } from "./project/projectManifest";
import type { RuntimeManager } from "./runtimeManager";
import type { GraphView, PipelineViewState } from "./webview/contracts";

const EMPTY_GRAPH: GraphView = { nodes: [], edges: [] };

export async function loadPipelineState(
  runtimeManager: RuntimeManager
): Promise<PipelineViewState> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) {
    return {
      exists: false,
      path: "pipelines/main.pipeline.py",
      compileStatus: "missing",
      diagnostics: [],
      graph: EMPTY_GRAPH
    };
  }

  const manifest = await readProjectManifest();
  const pipelineParts = safeRelativeParts(
    manifest.manifest?.assets?.pipelines,
    "pipelines"
  );
  const uri = vscode.Uri.joinPath(root, ...pipelineParts, "main.pipeline.py");
  const relativePath = vscode.workspace.asRelativePath(uri, false);

  if (!(await exists(uri))) {
    return {
      exists: false,
      path: relativePath,
      compileStatus: "missing",
      diagnostics: [],
      graph: EMPTY_GRAPH
    };
  }

  const source = new TextDecoder().decode(await vscode.workspace.fs.readFile(uri));
  if (runtimeManager.snapshot().status !== "running") {
    return {
      exists: true,
      path: relativePath,
      compileStatus: "runtime-required",
      diagnostics: [],
      graph: EMPTY_GRAPH
    };
  }

  try {
    const compiled = await runtimeManager.compilePipeline(source);
    if (!compiled.valid || !compiled.ir) {
      return {
        exists: true,
        path: relativePath,
        compileStatus: "invalid",
        diagnostics: compiled.diagnostics,
        graph: EMPTY_GRAPH,
        truth: compiled.truth
      };
    }

    return {
      exists: true,
      path: relativePath,
      compileStatus: "valid",
      diagnostics: compiled.diagnostics,
      truth: compiled.truth,
      schedule: compiled.ir.schedule,
      graph: {
        nodes: compiled.ir.tasks.map(task => ({
          id: task.id,
          label: task.id,
          detail: `${task.kind} · retries ${task.retries}`,
          truth: "Compiled design"
        })),
        edges: compiled.ir.edges.map((edge, index) => ({
          id: `dependency-${index + 1}`,
          source: edge.source,
          target: edge.target,
          label: "success"
        }))
      }
    };
  } catch (error) {
    return {
      exists: true,
      path: relativePath,
      compileStatus: "error",
      diagnostics: [{
        line: 1,
        column: 1,
        message: error instanceof Error ? error.message : String(error)
      }],
      graph: EMPTY_GRAPH
    };
  }
}

function safeRelativeParts(value: string | undefined, fallback: string): string[] {
  const normalized = (value ?? fallback).replaceAll("\\", "/");
  const parts = normalized.split("/").filter(Boolean);
  if (
    parts.length === 0 ||
    parts.some(part => part === "." || part === ".." || part.includes(":"))
  ) {
    return [fallback];
  }
  return parts;
}

async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}
