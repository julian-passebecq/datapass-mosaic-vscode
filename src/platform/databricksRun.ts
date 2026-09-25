import type {
  DatabricksComputeCatalogView,
  DatabricksJobDesignView,
  DatabricksLabView,
  DatabricksMlflowView,
  DatabricksRunView,
  DatabricksScenarioInput,
  DatabricksStateView,
  DatabricksTaskDesignView,
  DatabricksTaskKind,
  DatabricksTaskRunView,
  DatabricksUnityView,
  GraphView
} from "../webview/contracts";
import { parseJsonDocument } from "./factoryRun";

type Raw = Record<string, unknown>;
type Cell = string | number | boolean | null;

export const DATABRICKS_FOLDER = "factory/databricks";
export const DATABRICKS_LIMITS = { jobs: 40, notebooks: 60, sqlFiles: 40, textChars: 40_000 };
/** The runtime accepts these job names (see DatabricksRunRequest). */
export const JOB_NAME = /^[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}$/;
const KINDS: [string, DatabricksTaskKind][] = [
  ["notebook_task", "notebook"], ["condition_task", "condition"], ["sql_task", "sql"], ["for_each_task", "for_each"]
];
const OPS: Record<string, string> = {
  EQUAL_TO: "==", NOT_EQUAL: "!=", GREATER_THAN: ">", GREATER_THAN_OR_EQUAL: ">=", LESS_THAN: "<", LESS_THAN_OR_EQUAL: "<="
};

/** Design view of a job file, read by the host for the canvas. The runtime validates the job when it runs. */
export function jobDesignView(name: string, path: string, text: string): DatabricksJobDesignView {
  const empty: DatabricksJobDesignView = { name, path, description: "", parameters: [], clusters: [], tasks: [] };
  const parsed = parseJsonDocument(text);
  if (parsed.error) return { ...empty, error: parsed.error };
  const root = asRecord(parsed.value);
  const settings = asRecord(root.settings ?? root);
  if (!Array.isArray(settings.tasks)) return { ...empty, error: "No tasks array: is this a Databricks job file (Jobs API JSON)?" };
  const runAs = asRecord(settings.run_as);
  const schedule = asRecord(settings.schedule);
  return {
    ...empty,
    name: str(settings.name, name),
    description: str(settings.description, ""),
    parameters: list(settings.parameters).map(item => {
      const parameter = asRecord(item);
      return { name: str(parameter.name, "?"), defaultValue: typeof parameter.default === "string" ? parameter.default : JSON.stringify(parameter.default ?? "") };
    }),
    runAs: optionalString(runAs.service_principal_name) ?? optionalString(runAs.user_name),
    schedule: optionalString(schedule.quartz_cron_expression),
    clusters: list(settings.job_clusters).map(item => {
      const cluster = asRecord(item);
      const spec = asRecord(cluster.new_cluster);
      const scale = asRecord(spec.autoscale);
      const workers = spec.autoscale ? `autoscale ${num(scale.min_workers)}-${num(scale.max_workers)}` : `${num(spec.num_workers)} workers`;
      return { key: str(cluster.job_cluster_key, "?"), label: `${str(spec.node_type_id, "pool")}, ${workers}` };
    }),
    tasks: list(settings.tasks).map(taskDesign)
  };
}

function taskDesign(value: unknown): DatabricksTaskDesignView {
  const raw = asRecord(value);
  const [field, kind] = KINDS.find(([key]) => key in raw) ?? ["", "notebook" as DatabricksTaskKind];
  const spec = asRecord(raw[field]);
  const detail = kind === "notebook" ? str(spec.notebook_path, "")
    : kind === "sql" ? str(asRecord(spec.file).path, "")
      : kind === "condition" ? `${str(spec.left, "?")} ${OPS[str(spec.op, "")] ?? "?"} ${str(spec.right, "?")}`
        : `for each in ${str(spec.inputs, "?")}`;
  const compute = typeof raw.job_cluster_key === "string" ? `job cluster ${raw.job_cluster_key}`
    : typeof raw.existing_cluster_id === "string" ? `all-purpose ${raw.existing_cluster_id}`
      : kind === "sql" ? `warehouse ${str(spec.warehouse_id, "?")}`
        : kind === "condition" || kind === "for_each" ? "" : "serverless";
  const parameters = asRecord(kind === "sql" ? spec.parameters : spec.base_parameters);
  return {
    key: str(raw.task_key, "task"),
    kind,
    detail,
    runIf: str(raw.run_if, "ALL_SUCCESS"),
    dependsOn: list(raw.depends_on).map(item => {
      const dependency = asRecord(item);
      return { taskKey: str(dependency.task_key, "?"), outcome: optionalString(dependency.outcome) };
    }),
    compute,
    maxRetries: num(raw.max_retries),
    timeoutSeconds: num(raw.timeout_seconds),
    parameters: Object.fromEntries(Object.entries(parameters).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)])),
    inner: kind === "for_each" && spec.task ? taskDesign(spec.task) : undefined
  };
}

const STATE_CLASS: Record<string, string> = {
  success: "success", failed: "failed", timedout: "failed", upstream_failed: "upstream_failed", excluded: "skipped"
};

/** Canvas of a job: tasks as nodes (colored by their state after a run), dependencies as labelled edges. */
export function databricksGraph(design: DatabricksJobDesignView, run?: DatabricksRunView): GraphView {
  const states = new Map((run?.tasks ?? []).map(task => [task.key, task]));
  return {
    nodes: design.tasks.map(task => {
      const state = states.get(task.key);
      const kindLabel = { notebook: "Notebook", condition: "If/else condition", sql: "SQL", for_each: "For each" }[task.kind];
      return {
        id: task.key,
        label: task.key,
        detail: `${kindLabel}${task.compute ? ` · ${task.compute}` : ""}${task.inner ? ` · ${task.inner.key}` : ""}`,
        truth: state?.stateLabel ?? kindLabel,
        status: state ? STATE_CLASS[state.state] ?? "none" : undefined
      };
    }),
    edges: design.tasks.flatMap(task => task.dependsOn.map(dependency => {
      const label = dependency.outcome ? `(${dependency.outcome})` : task.runIf !== "ALL_SUCCESS" ? task.runIf.toLowerCase().replaceAll("_", " ") : "";
      const tone = dependency.outcome === "false" || ["AT_LEAST_ONE_FAILED", "ALL_FAILED"].includes(task.runIf) ? "failed"
        : task.runIf === "ALL_DONE" ? "completed" : "succeeded";
      return { id: `${dependency.taskKey}->${task.key}`, source: dependency.taskKey, target: task.key, label, className: `factory-edge cond-${tone}` };
    }))
  };
}

const FAIL_ATTEMPTS: Record<string, number[] | "all"> = { success: [], fail_once: [1], fail_twice: [1, 2], fail_always: "all" };
const MINUTE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** Run settings -> runtime scenario. Invalid task-value JSON is reported, not sent. */
export function toDatabricksScenario(input: DatabricksScenarioInput): { scenario: Record<string, unknown>; errors: string[] } {
  const errors: string[] = [];
  const tasks: Record<string, Record<string, unknown>> = {};
  for (const [key, task] of Object.entries(input.tasks)) {
    const behavior: Record<string, unknown> = {};
    const fail = FAIL_ATTEMPTS[task.behavior] ?? [];
    if (fail === "all" || fail.length) behavior.fail_attempts = fail;
    if (typeof task.durationSeconds === "number" && Number.isFinite(task.durationSeconds) && task.durationSeconds >= 0) {
      behavior.duration_seconds = task.durationSeconds;
    }
    const values = task.values?.trim();
    if (values) {
      const parsed = parseJsonDocument(values);
      if (parsed.error || !parsed.value || typeof parsed.value !== "object" || Array.isArray(parsed.value)) {
        errors.push(`${key}: task values must be a JSON object, for example {"new_rows": 0}`);
      } else {
        behavior.values = parsed.value;
      }
    }
    if (Object.keys(behavior).length) tasks[key] = behavior;
  }
  const jobParameters: Record<string, string> = {};
  for (const [name, value] of Object.entries(input.jobParameters)) {
    if (value.trim() !== "") jobParameters[name] = value;  // blank: the job default applies
  }
  const scenario: Record<string, unknown> = { job_parameters: jobParameters, tasks, trigger_type: input.triggerType,
    cluster_states: input.clusterStates };
  const now = input.now?.trim();
  if (now) scenario.now = MINUTE.test(now) ? `${now}:00Z` : now;
  return { scenario, errors };
}

/** Runtime `/api/local/databricks/run` response -> webview view. Truth labels are kept verbatim. */
export function toDatabricksLabView(
  raw: unknown,
  context: { jobName: string; path: string; scenario: DatabricksScenarioInput; warnings?: string[] }
): DatabricksLabView {
  const view = asRecord(raw);
  const status = view.status === "simulated" || view.status === "error" ? view.status : "invalid";
  return {
    jobName: context.jobName,
    path: context.path,
    status,
    truth: str(view.truth, "Simulated Azure Databricks; nothing connects to Databricks."),
    dataPlane: view.data_plane === "local" ? "local" : "simulated",
    issues: list(view.issues).map(item => {
      const issue = asRecord(item);
      return { path: str(issue.path, ""), message: str(issue.message, "Invalid job") };
    }),
    warnings: [...(context.warnings ?? []), ...strings(view.warnings)],
    run: view.run ? toRun(view.run) : undefined,
    tablesChanged: list(view.tables_changed).map(item => {
      const table = asRecord(item);
      return { name: str(table.name, "table"), rows: num(table.rows), producer: optionalString(table.producer) };
    }),
    scenario: context.scenario
  };
}

/** Unity Catalog, MLflow and compute, from a run response or `/api/local/databricks/state`. */
export function toDatabricksStateView(raw: unknown): DatabricksStateView {
  const view = asRecord(raw);
  return {
    truth: str(view.truth, ""),
    unity: toUnity(view.unity),
    mlflow: toMlflow(view.mlflow),
    computeCatalog: toComputeCatalog(view.compute_catalog),
    warnings: strings(view.warnings)
  };
}

function toRun(value: unknown): DatabricksRunView {
  const run = asRecord(value);
  const cost = asRecord(run.cost);
  return {
    runId: num(run.run_id),
    jobId: num(run.job_id),
    resultState: str(run.result_state, "FAILED"),
    statusLabel: str(run.status_label, "Failed"),
    explanation: str(run.explanation, ""),
    leaves: strings(run.leaves),
    durationS: num(run.duration_s),
    principal: str(run.principal, ""),
    startTime: str(run.start_time, ""),
    triggerType: str(run.trigger_type, "one_time"),
    parameters: stringMap(run.parameters),
    tasks: list(run.tasks).map(toTask),
    compute: list(run.compute).map(item => {
      const usage = asRecord(item);
      return {
        key: str(usage.key, ""), kind: str(usage.kind, ""), label: str(usage.label, ""), requestedS: num(usage.requested_s),
        readyS: num(usage.ready_s), endS: num(usage.end_s), startupS: num(usage.startup_s), billedS: num(usage.billed_s),
        nodes: num(usage.nodes), dbuPerHour: num(usage.dbu_per_hour), dbu: num(usage.dbu), rate: num(usage.rate),
        cost: num(usage.cost), tasks: strings(usage.tasks), idleAfterS: num(usage.idle_after_s), idleDbu: num(usage.idle_dbu),
        idleCost: num(usage.idle_cost), notes: strings(usage.notes)
      };
    }),
    cost: { dbu: num(cost.dbu), cost: num(cost.cost), idleDbu: num(cost.idle_dbu), idleCost: num(cost.idle_cost) },
    notes: strings(run.notes)
  };
}

function toTask(value: unknown): DatabricksTaskRunView {
  const task = asRecord(value);
  const condition = task.condition ? asRecord(task.condition) : undefined;
  return {
    key: str(task.key, "task"),
    kind: str(task.kind, "notebook"),
    state: str(task.state, "failed"),
    stateLabel: str(task.state_label, "Failed"),
    startS: num(task.start_s),
    endS: num(task.end_s),
    durationS: num(task.duration_s),
    attempts: list(task.attempts).map(item => {
      const attempt = asRecord(item);
      return { number: num(attempt.number), startS: num(attempt.start_s), endS: num(attempt.end_s), status: str(attempt.status, ""), error: str(attempt.error, "") };
    }),
    compute: str(task.compute, ""),
    parameters: stringMap(task.parameters),
    outcome: optionalString(task.outcome),
    condition: condition ? {
      left: str(condition.left, ""), op: str(condition.op, ""), right: str(condition.right, ""),
      leftExpression: str(condition.left_expression, ""), rightExpression: str(condition.right_expression, ""),
      result: condition.result === true
    } : undefined,
    exitValue: optionalString(task.exit_value),
    values: asRecord(task.values),
    error: str(task.error, ""),
    errorCode: str(task.error_code, ""),
    tablesWritten: strings(task.tables_written),
    notes: strings(task.notes),
    columns: strings(task.columns),
    rows: list(task.rows).map(row => Object.fromEntries(Object.entries(asRecord(row)).map(([k, v]) => [k, cell(v)]))),
    iterations: list(task.iterations).map(item => ({ ...toTask(item), input: asRecord(item).input })),
    reason: str(task.reason, "")
  };
}

function toUnity(value: unknown): DatabricksUnityView {
  const unity = asRecord(value);
  return {
    catalog: str(unity.catalog, "main"),
    labUser: str(unity.lab_user, ""),
    groups: Object.fromEntries(Object.entries(asRecord(unity.groups)).map(([k, v]) => [k, strings(v)])),
    grants: list(unity.grants).map(item => {
      const grant = asRecord(item);
      return { privilege: str(grant.privilege, ""), securable: str(grant.securable, ""), name: str(grant.name, ""), principal: str(grant.principal, "") };
    }),
    owners: stringMap(unity.owners),
    schemas: list(unity.schemas).map(item => {
      const schema = asRecord(item);
      return {
        name: str(schema.name, ""),
        readOnly: schema.read_only === true,
        tables: list(schema.tables).map(t => {
          const table = asRecord(t);
          return { name: str(table.name, ""), table: str(table.table, ""), rows: num(table.rows), owner: str(table.owner, ""), producer: optionalString(table.producer) };
        }),
        models: list(schema.models).map(m => {
          const model = asRecord(m);
          return { name: str(model.name, ""), owner: str(model.owner, ""), versions: num(model.versions), aliases: numberMap(model.aliases) };
        })
      };
    }),
    warnings: strings(unity.warnings)
  };
}

function toMlflow(value: unknown): DatabricksMlflowView {
  const mlflow = asRecord(value);
  return {
    experiments: list(mlflow.experiments).map(item => {
      const experiment = asRecord(item);
      return {
        name: str(experiment.name, ""),
        id: str(experiment.id, ""),
        runs: list(experiment.runs).map(r => {
          const run = asRecord(r);
          return {
            runId: str(run.run_id, ""), runName: str(run.run_name, ""), status: str(run.status, ""), params: stringMap(run.params),
            metrics: numberMap(run.metrics), models: strings(run.models), start: str(run.start, ""),
            job: optionalString(run.job), task: optionalString(run.task), user: optionalString(run.user)
          };
        })
      };
    }),
    models: list(mlflow.models).map(item => {
      const model = asRecord(item);
      return {
        name: str(model.name, ""),
        owner: str(model.owner, ""),
        aliases: numberMap(model.aliases),
        versions: list(model.versions).map(v => {
          const version = asRecord(v);
          return {
            version: num(version.version), runId: str(version.run_id, ""), created: str(version.created, ""),
            metrics: numberMap(version.metrics), kind: optionalString(version.kind),
            inputs: strings(asRecord(version.signature).inputs), user: optionalString(version.user)
          };
        })
      };
    })
  };
}

function toComputeCatalog(value: unknown): DatabricksComputeCatalogView {
  const compute = asRecord(value);
  return {
    clusters: list(compute.clusters).map(item => {
      const cluster = asRecord(item);
      return {
        clusterId: str(cluster.cluster_id, ""), name: str(cluster.name, ""), nodeType: str(cluster.node_type, ""),
        workers: num(cluster.workers), autoterminationMinutes: num(cluster.autotermination_minutes), running: cluster.running === true
      };
    }),
    warehouses: list(compute.warehouses).map(item => {
      const warehouse = asRecord(item);
      return { id: str(warehouse.id, ""), name: str(warehouse.name, ""), size: str(warehouse.size, ""), serverless: warehouse.serverless !== false };
    })
  };
}

/** Seconds as the run timeline shows them: 95 s, 5 min 20 s, 1 h 2 min. */
export function formatSeconds(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
  return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ""}`;
}

/** What a task's state means, in one line. */
export function explainTask(task: DatabricksTaskRunView): string {
  switch (task.state) {
    case "excluded":
      return `Excluded: ${task.reason || "it did not run"}. An excluded task counts as successful downstream.`;
    case "upstream_failed":
      return `Upstream failed: ${task.reason}.`;
    case "timedout":
      return `Timed out: ${task.error}`;
    case "failed":
      return `Failed${task.errorCode ? ` (${task.errorCode})` : ""}: ${task.error}`;
    default:
      return task.kind === "condition" && task.condition
        ? `${task.condition.left} ${task.condition.op} ${task.condition.right} is ${task.condition.result}: the ${task.outcome} branch runs.`
        : "Succeeded.";
  }
}

function cell(value: unknown): Cell {
  if (value === null || value === undefined) return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
  return JSON.stringify(value);
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

function stringMap(value: unknown): Record<string, string> {
  return Object.fromEntries(Object.entries(asRecord(value)).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]));
}

function numberMap(value: unknown): Record<string, number> {
  return Object.fromEntries(Object.entries(asRecord(value)).filter(([, v]) => typeof v === "number") as [string, number][]);
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
