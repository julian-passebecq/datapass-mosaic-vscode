import type {
  FactoryActivityRunView,
  FactoryDesignActivityView,
  FactoryDesignView,
  FactoryFlavor,
  FactoryLabView,
  FactoryParameterView,
  FactoryRunView,
  FactoryScenarioInput,
  GraphView
} from "../webview/contracts";

type Raw = Record<string, unknown>;

export const FACTORY_FOLDER = "factory";
export const FACTORY_FLAVORS: readonly FactoryFlavor[] = ["fabric", "adf", "synapse"];
/** The runtime accepts these pipeline names (Data Factory allows at most 140 characters). */
export const PIPELINE_NAME = /^[A-Za-z0-9][A-Za-z0-9 _-]{0,139}$/;
export const FACTORY_LIMITS = { pipelines: 40, datasets: 80, procedures: 40, notebooks: 40, textChars: 40_000 };

/** What a file under factory/ is, following each product's git layout. */
export type FactoryFileRole =
  | { role: "pipeline"; flavor: FactoryFlavor; name: string }
  | { role: "dataset"; flavor: "adf" | "synapse"; name: string }
  | { role: "procedure"; name: string }
  | { role: "notebook"; key: string }
  | { role: "poolScript"; name: string };

/**
 * Classify a path relative to the factory folder:
 * - fabric/<name>.DataPipeline/pipeline-content.json and fabric/<name>.Notebook/notebook-content.py (Fabric git)
 * - adf|synapse/pipeline/<name>.json and adf|synapse/dataset/<name>.json (Data Factory / Synapse git)
 * - synapse/notebook/<name>.py, databricks/<workspace path>.py (Databricks source format)
 * - sql/procedures/<schema>.<name>.sql
 * - sql/pool/<name>.sql (T-SQL scripts of the SQL pool tab)
 */
export function classifyFactoryPath(relative: string): FactoryFileRole | undefined {
  const parts = relative.replaceAll("\\", "/").split("/").filter(Boolean);
  if (parts.some(part => part === "." || part === "..")) return undefined;
  const [top, second, third] = parts;
  if (top === "fabric" && parts.length === 3) {
    if (second.endsWith(".DataPipeline") && third === "pipeline-content.json") {
      return { role: "pipeline", flavor: "fabric", name: second.slice(0, -".DataPipeline".length) };
    }
    if (second.endsWith(".Notebook") && third === "notebook-content.py") {
      return { role: "notebook", key: `fabric:${second.slice(0, -".Notebook".length)}` };
    }
  }
  if ((top === "adf" || top === "synapse") && parts.length === 3) {
    if (second === "pipeline" && third.endsWith(".json")) return { role: "pipeline", flavor: top, name: third.slice(0, -5) };
    if (second === "dataset" && third.endsWith(".json")) return { role: "dataset", flavor: top, name: third.slice(0, -5) };
    if (top === "synapse" && second === "notebook" && third.endsWith(".py")) {
      return { role: "notebook", key: `synapse:${third.slice(0, -3)}` };
    }
  }
  if (top === "databricks" && parts.length >= 2 && parts[parts.length - 1].endsWith(".py")) {
    return { role: "notebook", key: `databricks:/${parts.slice(1).join("/").slice(0, -3)}` };
  }
  if (top === "sql" && second === "procedures" && parts.length === 3 && third.endsWith(".sql")) {
    return { role: "procedure", name: third.slice(0, -4) };
  }
  if (top === "sql" && second === "pool" && parts.length === 3 && third.endsWith(".sql")) {
    return { role: "poolScript", name: third.slice(0, -4) };
  }
  return undefined;
}

export function pipelineRelativePath(flavor: FactoryFlavor, name: string): string {
  return flavor === "fabric"
    ? `${FACTORY_FOLDER}/fabric/${name}.DataPipeline/pipeline-content.json`
    : `${FACTORY_FOLDER}/${flavor}/pipeline/${name}.json`;
}

/** JSON.parse with a line/column message, as editors report it. */
export function parseJsonDocument(text: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(text) };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const position = /position (\d+)/.exec(message);
    if (position) {
      const offset = Number(position[1]);
      const before = text.slice(0, offset).split("\n");
      return { error: `Invalid JSON at line ${before.length}, column ${before[before.length - 1].length + 1}: ${message.replace(/ in JSON at position \d+.*$/, "")}` };
    }
    return { error: `Invalid JSON: ${message}` };
  }
}

/** Design view of a pipeline document, read by the host for the canvas. The runtime validates it. */
export function designView(flavor: FactoryFlavor, name: string, path: string, text: string): FactoryDesignView {
  const parsed = parseJsonDocument(text);
  const empty: FactoryDesignView = { flavor, name, path, description: "", parameters: [], variables: [], activities: [] };
  if (parsed.error) return { ...empty, error: parsed.error };
  const root = asRecord(parsed.value);
  const properties = asRecord(root.properties ?? root);
  if (!Array.isArray(properties.activities)) {
    return { ...empty, error: "No properties.activities array: is this a pipeline file?" };
  }
  return {
    ...empty,
    description: typeof properties.description === "string" ? properties.description : "",
    parameters: typedEntries(properties.parameters),
    variables: typedEntries(properties.variables),
    activities: designActivities(properties.activities, "")
  };
}

function typedEntries(value: unknown): FactoryParameterView[] {
  return Object.entries(asRecord(value)).map(([name, spec]) => ({
    name,
    type: str(asRecord(spec).type, "String"),
    defaultValue: asRecord(spec).defaultValue
  }));
}

function designActivities(value: unknown, parent: string): FactoryDesignActivityView[] {
  return list(value).map(item => {
    const raw = asRecord(item);
    const name = str(raw.name, "activity");
    const path = parent ? `${parent}/${name}` : name;
    const props = asRecord(raw.typeProperties);
    const children: FactoryDesignActivityView["children"] = [];
    for (const key of ["activities", "ifTrueActivities", "ifFalseActivities", "defaultActivities"]) {
      if (Array.isArray(props[key])) children.push({ key, activities: designActivities(props[key], path) });
    }
    for (const entry of list(props.cases)) {
      const scase = asRecord(entry);
      children.push({ key: `case ${String(scase.value)}`, activities: designActivities(scase.activities, path) });
    }
    return {
      name,
      type: str(raw.type, "Unknown"),
      path,
      state: str(raw.state, "Active"),
      dependsOn: list(raw.dependsOn).map(entry => {
        const dependency = asRecord(entry);
        const conditions = strings(dependency.dependencyConditions);
        return { activity: str(dependency.activity, ""), conditions: conditions.length ? conditions : ["Succeeded"] };
      }),
      children
    };
  });
}

const CONTROL = new Set(["ForEach", "IfCondition", "Switch", "Until", "Wait", "Fail", "SetVariable", "AppendVariable",
  "Filter", "ExecutePipeline", "InvokePipeline"]);

export function isControlActivity(type: string): boolean {
  return CONTROL.has(type);
}

/** Every activity in the design, containers first then their inner activities. */
export function flattenActivities(activities: readonly FactoryDesignActivityView[]): FactoryDesignActivityView[] {
  return activities.flatMap(activity => [activity, ...activity.children.flatMap(child => flattenActivities(child.activities))]);
}

const STATE_CLASS: Record<string, string> = { Succeeded: "success", Failed: "failed", Skipped: "skipped", InProgress: "running" };

/**
 * Canvas of one container level: activities as nodes, dependencies as edges labelled and
 * classed by condition (green Succeeded, red Failed, blue Completed, grey Skipped).
 */
export function factoryGraph(activities: readonly FactoryDesignActivityView[], run?: FactoryRunView): GraphView {
  const statusOf = new Map<string, string>();
  for (const activityRun of run?.activityRuns ?? []) {
    if (!activityRun.iteration) statusOf.set(activityRun.path, activityRun.status);
  }
  return {
    nodes: activities.map(activity => {
      const inner = activity.children.reduce((sum, child) => sum + flattenActivities(child.activities).length, 0);
      const status = statusOf.get(activity.path);
      return {
        id: activity.path,
        label: activity.name,
        detail: `${activity.type}${inner ? ` · ${inner} inner` : ""}${activity.state === "Inactive" ? " · deactivated" : ""}`,
        truth: status ?? (isControlActivity(activity.type) ? "Control" : "Activity"),
        status: status ? STATE_CLASS[status] ?? "none" : undefined
      };
    }),
    edges: activities.flatMap(activity => activity.dependsOn.map(dependency => {
      const source = activity.path.includes("/") ? `${activity.path.slice(0, activity.path.lastIndexOf("/"))}/${dependency.activity}` : dependency.activity;
      const tone = dependency.conditions.length === 1 ? dependency.conditions[0].toLowerCase() : "mixed";
      return {
        id: `${source}->${activity.path}`,
        source,
        target: activity.path,
        label: dependency.conditions.join(" or "),
        className: `factory-edge cond-${tone}`
      };
    }))
  };
}

const FAIL_ATTEMPTS: Record<string, number[] | "all"> = { success: [], fail_once: [1], fail_twice: [1, 2], fail_always: "all" };
const MINUTE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** Scenario form -> runtime request fields (scenario + data_plane). Invalid output JSON is reported, not sent. */
export function toRuntimeScenario(input: FactoryScenarioInput): { scenario: Record<string, unknown>; errors: string[] } {
  const errors: string[] = [];
  const activities: Record<string, Record<string, unknown>> = {};
  for (const [name, activity] of Object.entries(input.activities)) {
    const behavior: Record<string, unknown> = {};
    const fail = FAIL_ATTEMPTS[activity.behavior] ?? [];
    if (fail === "all" || fail.length) behavior.fail_attempts = fail;
    if (typeof activity.durationSeconds === "number" && Number.isFinite(activity.durationSeconds) && activity.durationSeconds >= 0) {
      behavior.duration_seconds = activity.durationSeconds;
    }
    const output = activity.output?.trim();
    if (output) {
      const parsed = parseJsonDocument(output);
      if (parsed.error || !parsed.value || typeof parsed.value !== "object" || Array.isArray(parsed.value)) {
        errors.push(`${name}: the output must be a JSON object, for example {"firstRow": {"n": 3}}`);
      } else {
        behavior.output = parsed.value;
      }
    }
    if (Object.keys(behavior).length) activities[name] = behavior;
  }
  const parameters: Record<string, string> = {};
  for (const [name, value] of Object.entries(input.parameters)) {
    if (value.trim() !== "") parameters[name] = value;  // blank: the pipeline default applies
  }
  const scenario: Record<string, unknown> = { parameters, activities, trigger_type: input.triggerType };
  const now = input.now?.trim();
  if (now) scenario.now = MINUTE.test(now) ? `${now}:00Z` : now;
  return { scenario, errors };
}

/** Runtime `/api/local/factory/simulate` response -> webview view. Truth labels are kept verbatim. */
export function toFactoryLabView(
  raw: unknown,
  context: { flavor: FactoryFlavor; pipelineName: string; path: string; scenario: FactoryScenarioInput; warnings?: string[] }
): FactoryLabView {
  const view = asRecord(raw);
  const status = view.status === "simulated" || view.status === "error" ? view.status : "invalid";
  const pipeline = asRecord(view.pipeline);
  return {
    flavor: context.flavor,
    flavorLabel: str(view.flavor_label, context.flavor),
    pipelineName: context.pipelineName,
    path: context.path,
    status,
    truth: str(view.truth, "Simulated Data Factory orchestration; nothing connects to a cloud service."),
    dataPlane: view.data_plane === "local" ? "local" : "simulated",
    issues: list(view.issues).map(item => {
      const issue = asRecord(item);
      return { path: str(issue.path, ""), message: str(issue.message, "Invalid pipeline"), severity: str(issue.severity, "error") };
    }),
    hints: strings(view.hints),
    warnings: [...(context.warnings ?? []), ...strings(pipeline.warnings)],
    run: view.run ? toRun(view.run) : undefined,
    tablesChanged: list(view.tables_changed).map(item => {
      const table = asRecord(item);
      return { name: str(table.name, "table"), rows: num(table.rows), producer: optionalString(table.producer) };
    }),
    scenario: context.scenario
  };
}

function toRun(value: unknown): FactoryRunView {
  const run = asRecord(value);
  const activityRuns = list(run.activity_runs).map(toActivityRun);
  const evaluated = strings(run.evaluated);
  const status = str(run.status, "Unknown");
  return {
    pipeline: str(run.pipeline, "pipeline"),
    runId: str(run.run_id, ""),
    status,
    evaluated,
    durationS: num(run.duration_s),
    parameters: asRecord(run.parameters),
    variables: asRecord(run.variables),
    returnValue: run.return_value ?? undefined,
    activityRuns,
    children: list(run.children).map(toRun),
    explanation: explainStatus(status, evaluated, activityRuns)
  };
}

function toActivityRun(value: unknown): FactoryActivityRunView {
  const run = asRecord(value);
  const error = run.error ? asRecord(run.error) : undefined;
  return {
    name: str(run.name, "activity"),
    type: str(run.type, "Unknown"),
    path: str(run.path, str(run.name, "activity")),
    status: str(run.status, "Unknown"),
    startS: num(run.start_s),
    endS: num(run.end_s),
    attempts: num(run.attempts),
    input: run.input,
    output: run.output,
    error: error
      ? { code: str(error.errorCode, ""), message: str(error.message, "Activity failed"), failureType: str(error.failureType, "") }
      : undefined,
    iteration: optionalString(run.iteration),
    truth: run.truth === "local" ? "local" : "simulated",
    note: str(run.note, ""),
    parent: optionalString(run.parent)
  };
}

/** Data Factory's run status rule, in words: evaluate the leaves; a skipped leaf is replaced by its parents. */
export function explainStatus(status: string, evaluated: readonly string[], runs: readonly FactoryActivityRunView[]): string {
  const top = new Map(runs.filter(run => !run.parent && !run.iteration).map(run => [run.name, run.status]));
  const listed = evaluated.map(name => `${name} (${top.get(name) ?? "?"})`).join(", ");
  if (!evaluated.length) return `${status}: the pipeline has no activities.`;
  const failed = evaluated.filter(name => top.get(name) !== "Succeeded");
  return status === "Succeeded"
    ? `Succeeded: every evaluated activity succeeded: ${listed}. Leaf activities decide the status; a skipped leaf is replaced by its parents.`
    : `Failed: ${failed.join(", ")} did not succeed among the evaluated activities ${listed}. A skipped leaf is replaced by its parents: when a failed activity also has a success path that was skipped, it is evaluated even though its failure path ran ("do if / else"). With only a failure path, the handler is the leaf and the run succeeds ("try / catch").`;
}

function asRecord(value: unknown): Raw {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Raw : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === "string");
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
