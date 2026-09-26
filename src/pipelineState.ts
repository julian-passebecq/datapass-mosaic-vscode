import * as vscode from "vscode";
import { readProjectManifest } from "./project/projectManifest";
import type { RuntimeManager } from "./runtimeManager";
import type { GraphView, PipelineViewState } from "./webview/contracts";
import { safeRelativeParts } from "./platform/workspacePaths";
import { exists } from "./workspaceFiles";

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
    const compiled = await runtimeManager.labs.pipeline.compilePipeline(source);
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
          truth: activityTruth(task.kind)
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

function activityTruth(kind: string): string {
  switch (kind) {
    case "sql":
    case "quality":
      return "Real local execution";
    case "python":
    case "polars":
      return "Real local execution · trusted Python only";
    case "dbt":
      return "Declared only · not executed (use dbt Lab)";
    default:
      return "Compiled design · not executable";
  }
}
