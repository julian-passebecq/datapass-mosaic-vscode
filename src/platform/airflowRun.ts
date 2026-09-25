import type {
  AirflowLabRunView,
  AirflowLabTaskView,
  AirflowLabView,
  AirflowScenarioInput,
  AirflowTaskScenarioInput
} from "../webview/contracts";

type Raw = Record<string, unknown>;

const FAIL_ATTEMPTS: Record<AirflowTaskScenarioInput["behavior"], number[] | "all"> = {
  success: [],
  fail_once: [1],
  fail_twice: [1, 2],
  fail_always: "all"
};
const MINUTE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** "YYYY-MM-DDTHH:MM" from a datetime-local input is UTC in Airflow Lab. */
export function utcInput(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  return MINUTE.test(trimmed) ? `${trimmed}:00Z` : trimmed;
}

/**
 * Scenario form -> runtime scenario. A sensor arrival left unset is omitted: the
 * runtime's Lab default is "condition true on the first poke"; null means never.
 */
export function toRuntimeScenario(input: AirflowScenarioInput): Record<string, unknown> {
  const tasks: Record<string, Record<string, unknown>> = {};
  for (const [taskId, task] of Object.entries(input.tasks)) {
    const behavior: Record<string, unknown> = {};
    const fail = FAIL_ATTEMPTS[task.behavior] ?? [];
    if (fail === "all" || fail.length) behavior.fail_attempts = fail;
    if (typeof task.durationSeconds === "number" && Number.isFinite(task.durationSeconds) && task.durationSeconds >= 0) {
      behavior.duration_seconds = task.durationSeconds;
    }
    if (task.sensorArrivalMinutes === null) {
      behavior.sensor_true_after_seconds = null;
    } else if (typeof task.sensorArrivalMinutes === "number" && task.sensorArrivalMinutes >= 0) {
      behavior.sensor_true_after_seconds = task.sensorArrivalMinutes * 60;
    }
    if (task.branch) behavior.branch = [...task.branch];
    tasks[taskId] = behavior;
  }
  const scenario: Record<string, unknown> = { tasks };
  const now = utcInput(input.now);
  const unpausedAt = utcInput(input.unpausedAt);
  const manualRunAt = utcInput(input.manualRunAt);
  if (now) scenario.now = now;
  if (unpausedAt) scenario.unpaused_at = unpausedAt;
  if (manualRunAt) scenario.manual_runs = [manualRunAt];
  return scenario;
}

/** Runtime `/api/local/airflow/simulate` response -> webview view. Truth labels are kept verbatim. */
export function toAirflowLabView(raw: unknown, fileName: string, scenario: AirflowScenarioInput): AirflowLabView {
  const view = asRecord(raw);
  const status = view.status === "simulated" || view.status === "simulation_error" ? view.status : "invalid";
  const error = asRecord(view.error);
  const dag = view.dag ? asRecord(view.dag) : undefined;
  return {
    fileName,
    status,
    truth: str(view.truth, "Simulated Airflow; the DAG file is parsed, never executed."),
    error: view.error ? { message: str(error.message, "Airflow Lab error"), line: optionalNumber(error.line) } : undefined,
    now: optionalString(view.now),
    unpausedAt: optionalString(view.unpaused_at),
    dag: dag
      ? {
          dagId: str(dag.dag_id, "dag"),
          schedule: {
            kind: str(asRecord(dag.schedule).kind, "none"),
            label: str(asRecord(dag.schedule).label, "None"),
            note: str(asRecord(dag.schedule).note, "")
          },
          startDate: optionalString(dag.start_date),
          endDate: optionalString(dag.end_date),
          catchup: dag.catchup === true,
          tasks: list(dag.tasks).map(toTask),
          edges: list(dag.edges).map(item => {
            const edge = asRecord(item);
            return { upstream: str(edge.upstream, ""), downstream: str(edge.downstream, "") };
          })
        }
      : undefined,
    totalRuns: num(view.total_runs),
    runs: list(view.runs).map(toRun),
    scenario
  };
}

function toTask(item: unknown): AirflowLabTaskView {
  const task = asRecord(item);
  const sensor = task.sensor ? asRecord(task.sensor) : undefined;
  return {
    taskId: str(task.task_id, "task"),
    operator: str(task.operator, "operator"),
    kind: str(task.kind, "task"),
    line: num(task.line),
    triggerRule: str(task.trigger_rule, "all_success"),
    retries: num(task.retries),
    retryDelayS: num(task.retry_delay_s),
    upstream: strings(task.upstream),
    downstream: strings(task.downstream),
    templatedFields: strings(task.templated_fields),
    staticBranch: Array.isArray(task.static_branch) ? strings(task.static_branch) : undefined,
    sensor: sensor
      ? {
          pokeIntervalS: num(sensor.poke_interval_s),
          timeoutS: num(sensor.timeout_s),
          mode: str(sensor.mode, "poke"),
          softFail: sensor.soft_fail === true
        }
      : undefined
  };
}

function toRun(item: unknown): AirflowLabRunView {
  const run = asRecord(item);
  return {
    runId: str(run.run_id, "run"),
    runType: str(run.run_type, "scheduled"),
    logicalDate: str(run.logical_date, ""),
    runAfter: str(run.run_after, ""),
    dataIntervalStart: str(run.data_interval_start, ""),
    dataIntervalEnd: str(run.data_interval_end, ""),
    state: str(run.state, "unknown"),
    durationS: num(run.duration_s),
    instances: list(run.instances).map(entry => {
      const ti = asRecord(entry);
      return {
        taskId: str(ti.task_id, "task"),
        state: str(ti.state, "none"),
        tryNumber: num(ti.try_number),
        startS: optionalNumber(ti.start_s),
        endS: optionalNumber(ti.end_s)
      };
    }),
    events: list(run.events).map(entry => {
      const event = asRecord(entry);
      return {
        t: num(event.t),
        taskId: str(event.task_id, "task"),
        state: str(event.state, "none"),
        tryNumber: num(event.try_number),
        message: str(event.message, "")
      };
    }),
    rendered: list(run.rendered).map(entry => {
      const row = asRecord(entry);
      return { taskId: str(row.task_id, "task"), field: str(row.field, ""), value: str(row.value, "") };
    }),
    renderError: optionalString(run.render_error)
  };
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

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
