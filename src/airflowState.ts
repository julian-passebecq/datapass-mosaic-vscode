import * as vscode from "vscode";
import { readProjectManifest } from "./project/projectManifest";
import type {
  AirflowDefinitionView,
  AirflowFailureMode,
  AirflowTaskView,
  AirflowTriggerRule,
  AirflowViewState,
  GraphView
} from "./webview/contracts";

const EMPTY_GRAPH: GraphView = { nodes: [], edges: [] };
const ID = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/;
const TASK_TYPES = new Set(["task", "sensor", "quality", "branch"]);
const TRIGGER_RULES = new Set<AirflowTriggerRule>([
  "all_success",
  "all_done",
  "none_failed_min_one_success"
]);
const FAILURE_MODES = new Set<AirflowFailureMode>(["none", "transient", "permanent"]);

export async function loadAirflowState(): Promise<AirflowViewState> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) {
    return {
      exists: false,
      path: "airflow/main.dag.json",
      valid: false,
      errors: [],
      graph: EMPTY_GRAPH
    };
  }

  const manifest = await readProjectManifest();
  const parts = safeRelativeParts(manifest.manifest?.assets?.airflow, "airflow");
  const uri = vscode.Uri.joinPath(root, ...parts, "main.dag.json");
  const path = vscode.workspace.asRelativePath(uri, false);

  if (!(await exists(uri))) {
    return { exists: false, path, valid: false, errors: [], graph: EMPTY_GRAPH };
  }

  let raw: unknown;
  try {
    raw = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)));
  } catch (error) {
    return {
      exists: true,
      path,
      valid: false,
      errors: [`Invalid JSON: ${error instanceof Error ? error.message : String(error)}`],
      graph: EMPTY_GRAPH
    };
  }

  const parsed = validateDefinition(raw);
  if (!parsed.definition) {
    return {
      exists: true,
      path,
      valid: false,
      errors: parsed.errors,
      graph: EMPTY_GRAPH
    };
  }

  return {
    exists: true,
    path,
    valid: parsed.errors.length === 0,
    errors: parsed.errors,
    definition: parsed.definition,
    graph: parsed.errors.length === 0 ? projectGraph(parsed.definition) : EMPTY_GRAPH
  };
}

function validateDefinition(raw: unknown): {
  definition?: AirflowDefinitionView;
  errors: string[];
} {
  const errors: string[] = [];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { errors: ["DAG definition must be a JSON object."] };
  }

  const doc = raw as Record<string, unknown>;
  if (doc.schemaVersion !== 1) errors.push("schemaVersion must be 1.");

  const dagId = typeof doc.dagId === "string" ? doc.dagId.trim() : "";
  if (!ID.test(dagId)) errors.push("dagId must be a simple identifier up to 64 characters.");

  const schedule = typeof doc.schedule === "string" ? doc.schedule.trim() : "";
  if (!schedule || schedule.length > 100) errors.push("schedule must be a non-empty string up to 100 characters.");

  const rawTasks = Array.isArray(doc.tasks) ? doc.tasks : [];
  if (!Array.isArray(doc.tasks)) errors.push("tasks must be an array.");
  if (rawTasks.length === 0) errors.push("At least one task is required.");
  if (rawTasks.length > 40) errors.push("Airflow Lab supports at most 40 tasks.");

  const tasks: AirflowTaskView[] = [];
  rawTasks.forEach((rawTask, index) => {
    if (!rawTask || typeof rawTask !== "object" || Array.isArray(rawTask)) {
      errors.push(`tasks[${index}] must be an object.`);
      return;
    }
    const task = rawTask as Record<string, unknown>;
    const id = typeof task.id === "string" ? task.id.trim() : "";
    if (!ID.test(id)) errors.push(`tasks[${index}].id is invalid.`);

    const label = typeof task.label === "string" && task.label.trim()
      ? task.label.trim().slice(0, 120)
      : id;

    const type = typeof task.type === "string" && TASK_TYPES.has(task.type)
      ? task.type as AirflowTaskView["type"]
      : "task";
    if (typeof task.type === "string" && !TASK_TYPES.has(task.type)) {
      errors.push(`${id || `tasks[${index}]`}: unsupported type ${task.type}.`);
    }

    const dependsOn = Array.isArray(task.dependsOn)
      ? task.dependsOn.filter((value): value is string => typeof value === "string")
      : [];
    if (!Array.isArray(task.dependsOn)) errors.push(`${id}: dependsOn must be an array.`);

    const retries = boundedInt(task.retries, 0, 5, 0, `${id}.retries`, errors);
    const retryDelaySeconds = boundedInt(task.retryDelaySeconds, 0, 300, 0, `${id}.retryDelaySeconds`, errors);
    const durationSeconds = boundedInt(task.durationSeconds, 0, 3600, 1, `${id}.durationSeconds`, errors);

    const triggerRule = typeof task.triggerRule === "string" && TRIGGER_RULES.has(task.triggerRule as AirflowTriggerRule)
      ? task.triggerRule as AirflowTriggerRule
      : "all_success";
    if (typeof task.triggerRule === "string" && !TRIGGER_RULES.has(task.triggerRule as AirflowTriggerRule)) {
      errors.push(`${id}: unsupported triggerRule ${task.triggerRule}.`);
    }

    const failureMode = typeof task.failureMode === "string" && FAILURE_MODES.has(task.failureMode as AirflowFailureMode)
      ? task.failureMode as AirflowFailureMode
      : "none";
    if (typeof task.failureMode === "string" && !FAILURE_MODES.has(task.failureMode as AirflowFailureMode)) {
      errors.push(`${id}: unsupported failureMode ${task.failureMode}.`);
    }

    tasks.push({
      id,
      label,
      type,
      dependsOn,
      retries,
      retryDelaySeconds,
      durationSeconds,
      triggerRule,
      failureMode
    });
  });

  const ids = tasks.map(task => task.id);
  const idSet = new Set(ids);
  if (idSet.size !== ids.length) errors.push("Task IDs must be unique.");

  for (const task of tasks) {
    if (task.dependsOn.includes(task.id)) errors.push(`${task.id} cannot depend on itself.`);
    for (const dependency of task.dependsOn) {
      if (!idSet.has(dependency)) errors.push(`${task.id} depends on missing task ${dependency}.`);
    }
  }

  if (tasks.length > 0 && hasCycle(tasks)) {
    errors.push("DAG contains a dependency cycle.");
  }

  if (!dagId || !schedule || tasks.length === 0) return { errors };

  return {
    definition: { dagId, schedule, tasks },
    errors
  };
}

function hasCycle(tasks: readonly AirflowTaskView[]): boolean {
  const parents = new Map(tasks.map(task => [task.id, new Set(task.dependsOn)]));
  const resolved = new Set<string>();
  let progress = true;

  while (resolved.size < tasks.length && progress) {
    progress = false;
    for (const task of tasks) {
      if (resolved.has(task.id)) continue;
      const deps = parents.get(task.id) ?? new Set<string>();
      if ([...deps].every(dep => resolved.has(dep))) {
        resolved.add(task.id);
        progress = true;
      }
    }
  }

  return resolved.size !== tasks.length;
}

function projectGraph(definition: AirflowDefinitionView): GraphView {
  const edges: GraphView["edges"] = [];
  for (const task of definition.tasks) {
    for (const dependency of task.dependsOn) {
      edges.push({
        id: `${dependency}-to-${task.id}`,
        source: dependency,
        target: task.id,
        label: task.triggerRule
      });
    }
  }

  return {
    nodes: definition.tasks.map(task => ({
      id: task.id,
      label: task.label,
      detail: `${task.type} · retries ${task.retries}`,
      truth: "Simulated"
    })),
    edges
  };
}

function boundedInt(
  value: unknown,
  min: number,
  max: number,
  fallback: number,
  label: string,
  errors: string[]
): number {
  if (value === undefined) return fallback;
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    errors.push(`${label} must be an integer from ${min} to ${max}.`);
    return fallback;
  }
  return value;
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
