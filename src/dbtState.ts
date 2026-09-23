import * as vscode from "vscode";
import { detectCli } from "./platform/detection";
import { readProjectManifest } from "./project/projectManifest";
import type { DbtViewState, GraphView } from "./webview/contracts";

const EMPTY_GRAPH: GraphView = { nodes: [], edges: [] };
const REF = /\{\{\s*ref\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}/g;
const SOURCE = /\{\{\s*source\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}/g;

export async function loadDbtState(): Promise<DbtViewState> {
  const cli = await detectCli({ id: "dbt", label: "dbt Core", command: "dbt" });
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) {
    return {
      exists: false,
      path: "dbt/retail-dbt",
      modelCount: 0,
      seedCount: 0,
      lineageSource: "none",
      graph: EMPTY_GRAPH,
      errors: [],
      cli: { available: cli.available, version: cli.version, detail: cli.detail }
    };
  }

  const manifest = await readProjectManifest();
  const dbtParts = safeRelativeParts(manifest.manifest?.assets?.dbt, "dbt");
  const projectRoot = vscode.Uri.joinPath(root, ...dbtParts, "retail-dbt");
  const projectFile = vscode.Uri.joinPath(projectRoot, "dbt_project.yml");
  const relativePath = vscode.workspace.asRelativePath(projectRoot, false);

  if (!(await exists(projectFile))) {
    return {
      exists: false,
      path: relativePath,
      modelCount: 0,
      seedCount: 0,
      lineageSource: "none",
      graph: EMPTY_GRAPH,
      errors: [],
      cli: { available: cli.available, version: cli.version, detail: cli.detail }
    };
  }

  const errors: string[] = [];
  const projectText = new TextDecoder().decode(await vscode.workspace.fs.readFile(projectFile));
  const projectName = /^name:\s*['"]?([^'"\s]+)['"]?/m.exec(projectText)?.[1];

  const artifact = await readJson(vscode.Uri.joinPath(projectRoot, "target", "manifest.json"));
  if (artifact && typeof artifact === "object") {
    try {
      const manifestGraph = graphFromManifest(artifact as Record<string, unknown>);
      if (manifestGraph.graph.nodes.length > 0) {
        return {
          exists: true,
          path: relativePath,
          projectName,
          modelCount: manifestGraph.modelCount,
          seedCount: manifestGraph.seedCount,
          lineageSource: "manifest",
          graph: manifestGraph.graph,
          errors,
          cli: { available: cli.available, version: cli.version, detail: cli.detail }
        };
      }
    } catch (error) {
      errors.push(`Could not read target/manifest.json: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  const staticGraph = await graphFromSource(projectRoot);
  return {
    exists: true,
    path: relativePath,
    projectName,
    modelCount: staticGraph.modelCount,
    seedCount: staticGraph.seedCount,
    lineageSource: "static",
    graph: staticGraph.graph,
    errors,
    cli: { available: cli.available, version: cli.version, detail: cli.detail }
  };
}

function graphFromManifest(manifest: Record<string, unknown>): {
  graph: GraphView;
  modelCount: number;
  seedCount: number;
} {
  const nodesObject = objectValue(manifest.nodes) ?? {};
  const sourcesObject = objectValue(manifest.sources) ?? {};
  const all = { ...nodesObject, ...sourcesObject };
  const graphNodes = new Map<string, { id: string; label: string; detail: string; truth: string }>();
  let modelCount = 0;
  let seedCount = 0;

  for (const [uniqueId, raw] of Object.entries(all)) {
    const node = objectValue(raw);
    if (!node) continue;
    const resourceType = stringValue(node.resource_type) ?? "resource";
    if (!["model", "seed", "source"].includes(resourceType)) continue;
    if (resourceType === "model") modelCount += 1;
    if (resourceType === "seed") seedCount += 1;
    const config = objectValue(node.config);
    const materialized = stringValue(config?.materialized);
    graphNodes.set(uniqueId, {
      id: uniqueId,
      label: stringValue(node.name) ?? uniqueId,
      detail: materialized ? `${resourceType} · ${materialized}` : resourceType,
      truth: "dbt manifest"
    });
  }

  const edges: Array<{ id: string; source: string; target: string; label: string }> = [];
  const parentMap = objectValue(manifest.parent_map) ?? {};
  for (const [target, rawParents] of Object.entries(parentMap)) {
    if (!graphNodes.has(target) || !Array.isArray(rawParents)) continue;
    for (const parent of rawParents) {
      if (typeof parent !== "string" || !graphNodes.has(parent)) continue;
      edges.push({
        id: `${parent}->${target}`,
        source: parent,
        target,
        label: "depends_on"
      });
    }
  }

  return {
    graph: { nodes: [...graphNodes.values()], edges },
    modelCount,
    seedCount
  };
}

async function graphFromSource(projectRoot: vscode.Uri): Promise<{
  graph: GraphView;
  modelCount: number;
  seedCount: number;
}> {
  const modelFiles = await collectFiles(vscode.Uri.joinPath(projectRoot, "models"), ".sql");
  const seedFiles = await collectFiles(vscode.Uri.joinPath(projectRoot, "seeds"), ".csv");

  const nodes = new Map<string, { id: string; label: string; detail: string; truth: string }>();
  const edges: Array<{ id: string; source: string; target: string; label: string }> = [];

  for (const seed of seedFiles) {
    const name = baseName(seed.path, ".csv");
    nodes.set(name, { id: name, label: name, detail: "seed", truth: "Static lineage" });
  }

  for (const model of modelFiles) {
    const name = baseName(model.path, ".sql");
    nodes.set(name, { id: name, label: name, detail: "model", truth: "Static lineage" });
  }

  for (const model of modelFiles) {
    const target = baseName(model.path, ".sql");
    const sql = new TextDecoder().decode(await vscode.workspace.fs.readFile(model.uri));

    for (const source of matchAll(sql, REF, match => match[1])) {
      if (!nodes.has(source)) {
        nodes.set(source, { id: source, label: source, detail: "unresolved ref", truth: "Static lineage" });
      }
      edges.push({
        id: `${source}->${target}`,
        source,
        target,
        label: "ref"
      });
    }

    for (const source of matchAll(sql, SOURCE, match => `${match[1]}.${match[2]}`)) {
      if (!nodes.has(source)) {
        nodes.set(source, { id: source, label: source, detail: "source", truth: "Static lineage" });
      }
      edges.push({
        id: `${source}->${target}`,
        source,
        target,
        label: "source"
      });
    }
  }

  return {
    graph: { nodes: [...nodes.values()], edges },
    modelCount: modelFiles.length,
    seedCount: seedFiles.length
  };
}

interface FileRef {
  uri: vscode.Uri;
  path: string;
}

async function collectFiles(root: vscode.Uri, extension: string): Promise<FileRef[]> {
  const result: FileRef[] = [];
  let entries: [string, vscode.FileType][];
  try {
    entries = await vscode.workspace.fs.readDirectory(root);
  } catch {
    return result;
  }

  for (const [name, type] of entries) {
    const uri = vscode.Uri.joinPath(root, name);
    if ((type & vscode.FileType.Directory) !== 0) {
      result.push(...await collectFiles(uri, extension));
    } else if ((type & vscode.FileType.File) !== 0 && name.toLowerCase().endsWith(extension)) {
      result.push({ uri, path: uri.path });
    }
  }
  return result;
}

function matchAll(
  value: string,
  regex: RegExp,
  project: (match: RegExpExecArray) => string
): string[] {
  const result: string[] = [];
  regex.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(value)) !== null) result.push(project(match));
  return [...new Set(result)];
}

function baseName(path: string, extension: string): string {
  const normalized = path.replaceAll("\\", "/");
  const file = normalized.split("/").at(-1) ?? normalized;
  return file.toLowerCase().endsWith(extension)
    ? file.slice(0, -extension.length)
    : file;
}

async function readJson(uri: vscode.Uri): Promise<unknown | undefined> {
  try {
    return JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)));
  } catch {
    return undefined;
  }
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
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
