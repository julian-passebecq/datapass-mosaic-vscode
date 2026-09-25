import { Badge, Button, Text } from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import type {
  AirflowLabRunView,
  AirflowLabTaskView,
  AirflowLabView,
  AirflowScenarioInput,
  AirflowTaskBehavior,
  AirflowTaskScenarioInput,
  AirflowViewState,
  GraphView,
  RuntimeViewState
} from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { SharedGraphCanvas } from "./SharedGraphCanvas";

const BEHAVIORS: [AirflowTaskBehavior, string][] = [
  ["success", "succeeds"],
  ["fail_once", "fails try 1"],
  ["fail_twice", "fails tries 1-2"],
  ["fail_always", "always fails"]
];
const EMPTY_SCENARIO: AirflowScenarioInput = { tasks: {} };
const TERMINAL = new Set(["success", "failed", "skipped", "upstream_failed"]);

export function AirflowSurface({
  vscode,
  airflow,
  runtime
}: {
  vscode: VsCodeApi;
  airflow: AirflowViewState | undefined;
  runtime: RuntimeViewState;
}) {
  const lab = runtime.airflowRun;
  const running = runtime.status === "running";
  const [scenario, setScenario] = useState<AirflowScenarioInput>(lab?.scenario ?? EMPTY_SCENARIO);
  const simulate = (next: AirflowScenarioInput = scenario) => {
    setScenario(next);
    vscode.postMessage({ type: "simulateAirflow", scenario: next });
  };

  return (
    <section className="airflow-surface">
      <div className="airflow-toolbar">
        <div>
          <div className="eyebrow">Simulated Airflow 3 · DAG files are parsed, never executed</div>
          <Text size={500} weight="semibold">Airflow Lab</Text>
        </div>
        <div className="button-row">
          <Badge appearance="tint" color={running ? "success" : "informative"}>
            {running ? "simulator ready" : "start the runtime to simulate"}
          </Badge>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "openAirflowSource" })}>
            {airflow?.starterExists ? "Open starter DAG" : "Create starter DAG"}
          </Button>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
            Airflow exercises
          </Button>
          <Button appearance="primary" size="small" disabled={!running} onClick={() => simulate()}>
            Simulate active DAG file
          </Button>
        </div>
      </div>

      {airflow?.legacySpecPath && (
        <div className="pipeline-notice">
          {airflow.legacySpecPath} is the earlier JSON spec and is no longer simulated. Airflow Lab now reads real
          Airflow DAG files; start from {airflow.starterPath}.
        </div>
      )}

      <ScenarioForm scenario={scenario} lab={lab} onChange={setScenario} onSimulate={simulate} disabled={!running} />

      {lab ? <LabResult lab={lab} vscode={vscode} /> : (
        <div className="empty-state">
          Open a DAG file ({airflow?.starterPath ?? "airflow/dags/retail_daily.py"}) and choose Simulate. Datapass reads
          it like the Airflow scheduler would, without running any task code.
        </div>
      )}

      <div className="truth-table">
        <TruthRow capability="DAG file" truth="Parsed, never executed" note="Whitelisted AST; unsupported syntax is rejected with its line, not approximated." />
        <TruthRow capability="Runs, task states, logs" truth="Simulated" note="Airflow 3 timetables, catchup, trigger rules, retries, sensors and branching for the supported subset." />
        <TruthRow capability="Task code, connections, executors" truth="Not run" note="Outcomes come from the scenario above; nothing reaches a database, a shell or a worker." />
      </div>
    </section>
  );
}

function ScenarioForm({
  scenario,
  lab,
  onChange,
  onSimulate,
  disabled
}: {
  scenario: AirflowScenarioInput;
  lab: AirflowLabView | undefined;
  onChange: (next: AirflowScenarioInput) => void;
  onSimulate: (next?: AirflowScenarioInput) => void;
  disabled: boolean;
}) {
  const tasks = lab?.dag?.tasks ?? [];
  const setField = (field: "now" | "unpausedAt" | "manualRunAt", value: string) =>
    onChange({ ...scenario, [field]: value || undefined });
  const setTask = (task: AirflowLabTaskView, patch: Partial<AirflowTaskScenarioInput>) =>
    onChange({
      ...scenario,
      tasks: { ...scenario.tasks, [task.taskId]: { ...(scenario.tasks[task.taskId] ?? { behavior: "success" }), ...patch } }
    });

  return (
    <details className="airflow-scenario" open>
      <summary>Scenario (what the simulated world does)</summary>
      <div className="airflow-scenario-times">
        <label>
          Scheduler clock, UTC
          <input type="datetime-local" value={scenario.now ?? ""} onChange={event => setField("now", event.target.value)} />
        </label>
        <label>
          Unpaused at, UTC
          <input type="datetime-local" value={scenario.unpausedAt ?? ""} onChange={event => setField("unpausedAt", event.target.value)} />
        </label>
        <label>
          Manual run at, UTC
          <input type="datetime-local" value={scenario.manualRunAt ?? ""} onChange={event => setField("manualRunAt", event.target.value)} />
        </label>
        <span className="muted">Empty clock: now. Empty unpause time: the clock. Runs are created as a continuously running scheduler would.</span>
      </div>
      {tasks.length > 0 && (
        <table className="airflow-scenario-tasks">
          <thead>
            <tr><th>Task</th><th>Outcome</th><th>Duration (s)</th><th>Sensor file / branch choice</th></tr>
          </thead>
          <tbody>
            {tasks.map(task => {
              const current = scenario.tasks[task.taskId];
              return (
                <tr key={task.taskId}>
                  <td><strong>{task.taskId}</strong><small>{task.operator}</small></td>
                  <td>
                    <select
                      aria-label={`${task.taskId} outcome`}
                      value={current?.behavior ?? "success"}
                      disabled={task.kind === "sensor"}
                      onChange={event => setTask(task, { behavior: event.target.value as AirflowTaskBehavior })}
                    >
                      {BEHAVIORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </td>
                  <td>
                    <input
                      aria-label={`${task.taskId} duration`}
                      type="number"
                      min={0}
                      placeholder="60"
                      value={current?.durationSeconds ?? ""}
                      disabled={task.kind === "sensor"}
                      onChange={event => setTask(task, {
                        durationSeconds: event.target.value === "" ? undefined : Number(event.target.value)
                      })}
                    />
                  </td>
                  <td>{taskSpecificControl(task, current, patch => setTask(task, patch))}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="button-row">
        <Button size="small" appearance="primary" disabled={disabled} onClick={() => onSimulate()}>Simulate with this scenario</Button>
        <Button size="small" appearance="secondary" disabled={disabled} onClick={() => onSimulate(EMPTY_SCENARIO)}>Reset scenario</Button>
      </div>
    </details>
  );
}

function taskSpecificControl(
  task: AirflowLabTaskView,
  current: AirflowTaskScenarioInput | undefined,
  update: (patch: Partial<AirflowTaskScenarioInput>) => void
) {
  if (task.kind === "sensor") {
    const arrival = current?.sensorArrivalMinutes;
    return (
      <span className="airflow-inline">
        <select
          aria-label={`${task.taskId} arrival`}
          value={arrival === null ? "never" : arrival === undefined ? "first" : "after"}
          onChange={event => update({
            sensorArrivalMinutes: event.target.value === "never" ? null : event.target.value === "first" ? undefined : 30
          })}
        >
          <option value="first">present at first poke</option>
          <option value="after">arrives after…</option>
          <option value="never">never arrives</option>
        </select>
        {typeof arrival === "number" && (
          <input
            aria-label={`${task.taskId} arrival minutes`}
            type="number"
            min={0}
            value={arrival}
            onChange={event => update({ sensorArrivalMinutes: Number(event.target.value) })}
          />
        )}
        {typeof arrival === "number" && <span className="muted">min</span>}
      </span>
    );
  }
  if (task.kind === "branch") {
    const chosen = current?.branch ?? task.staticBranch ?? [];
    return (
      <span className="airflow-inline">
        {task.downstream.map(target => (
          <label key={target}>
            <input
              type="checkbox"
              checked={chosen.includes(target)}
              onChange={event => update({
                branch: event.target.checked ? [...chosen, target] : chosen.filter(item => item !== target)
              })}
            />
            {target}
          </label>
        ))}
      </span>
    );
  }
  if (task.kind === "short_circuit") return <span className="muted">condition is true (not configurable yet)</span>;
  return <span className="muted">—</span>;
}

function LabResult({ lab, vscode }: { lab: AirflowLabView; vscode: VsCodeApi }) {
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(lab.runs.at(-1)?.runId);
  useEffect(() => {
    if (!lab.runs.some(run => run.runId === selectedRunId)) setSelectedRunId(lab.runs.at(-1)?.runId);
  }, [lab]);
  const selected = lab.runs.find(run => run.runId === selectedRunId);
  const dag = lab.dag;

  return (
    <div className="airflow-result">
      <div className="mosaic-run-summary">
        <Badge appearance="tint" color={lab.status === "simulated" ? "success" : "danger"}>
          {lab.status === "simulated" ? "simulated" : lab.status === "invalid" ? "DAG rejected" : "simulation stopped"}
        </Badge>
        <span>{lab.fileName}</span>
        {lab.now && <span className="muted">scheduler clock {shortTime(lab.now)} UTC</span>}
      </div>

      {lab.error && (
        <div className="pipeline-diagnostics" role="alert">
          <div>{lab.error.message}</div>
          {lab.error.line && (
            <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "revealAirflowLine", line: lab.error!.line! })}>
              Go to line {lab.error.line}
            </Button>
          )}
        </div>
      )}

      {dag && (
        <div className="pipeline-facts">
          <span><strong>DAG:</strong> {dag.dagId}</span>
          <span><strong>Schedule:</strong> {dag.schedule.label}</span>
          <span><strong>start_date:</strong> {dag.startDate ? shortTime(dag.startDate) : "—"}</span>
          <span><strong>catchup:</strong> {String(dag.catchup)}</span>
          <span><strong>Runs:</strong> {lab.totalRuns}{lab.totalRuns > lab.runs.length ? ` (last ${lab.runs.length} shown)` : ""}</span>
        </div>
      )}
      {dag && <p className="muted airflow-note">{dag.schedule.note}</p>}

      {dag && lab.runs.length > 0 && (
        <RunGrid tasks={dag.tasks} runs={lab.runs} selectedRunId={selected?.runId} onSelect={setSelectedRunId} />
      )}
      {dag && lab.status === "simulated" && lab.runs.length === 0 && (
        <div className="empty-state">
          No run exists at this scheduler clock. Check start_date, catchup and the schedule, or add a manual run.
        </div>
      )}

      {dag && selected && <RunDetail key={selected.runId} lab={lab} run={selected} vscode={vscode} />}
      {dag && !selected && lab.status !== "simulated" && (
        <SharedGraphCanvas graph={dagGraph(lab, undefined, undefined)} vscode={vscode} storageKey={`airflow-${dag.dagId}`} />
      )}
    </div>
  );
}

function RunGrid({
  tasks,
  runs,
  selectedRunId,
  onSelect
}: {
  tasks: AirflowLabTaskView[];
  runs: AirflowLabRunView[];
  selectedRunId: string | undefined;
  onSelect: (runId: string) => void;
}) {
  return (
    <div className="airflow-grid-wrap">
      <table className="airflow-grid">
        <thead>
          <tr>
            <th>Run</th>
            {runs.map(run => (
              <th key={run.runId}>
                <button
                  type="button"
                  className={`airflow-cell state-${run.state}${run.runId === selectedRunId ? " is-selected" : ""}`}
                  title={`${run.runId} · ${run.state}`}
                  aria-label={`Select run ${run.logicalDate}`}
                  onClick={() => onSelect(run.runId)}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tasks.map(task => (
            <tr key={task.taskId}>
              <td>{task.taskId}</td>
              {runs.map(run => {
                const instance = run.instances.find(item => item.taskId === task.taskId);
                return (
                  <td key={run.runId}>
                    <span
                      className={`airflow-cell state-${instance?.state ?? "none"}`}
                      title={`${task.taskId} · ${instance?.state ?? "none"} · try ${instance?.tryNumber ?? 0}`}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="airflow-legend">
        {["success", "failed", "upstream_failed", "skipped", "up_for_retry", "running", "none"].map(state => (
          <span key={state}><span className={`airflow-cell state-${state}`} />{state}</span>
        ))}
      </div>
    </div>
  );
}

function RunDetail({ lab, run, vscode }: { lab: AirflowLabView; run: AirflowLabRunView; vscode: VsCodeApi }) {
  // Replay cursor over the run's events; null shows the final state.
  const [cursor, setCursor] = useState<number | null>(null);
  const visibleEvents = cursor === null ? run.events : run.events.slice(0, cursor + 1);
  const states = useMemo(() => {
    const current: Record<string, { state: string; tryNumber: number }> = {};
    for (const event of visibleEvents) current[event.taskId] = { state: event.state, tryNumber: event.tryNumber };
    return current;
  }, [run, cursor]);
  const now = cursor === null ? run.durationS : run.events[cursor]?.t ?? 0;

  return (
    <div className="airflow-run">
      <div className="pipeline-facts">
        <span><strong>{run.runType === "manual" ? "Manual run" : "Scheduled run"}:</strong> {run.runId}</span>
        <span><strong>logical date:</strong> {shortTime(run.logicalDate)}</span>
        <span><strong>starts (run_after):</strong> {shortTime(run.runAfter)}</span>
        <span><strong>data interval:</strong> {shortTime(run.dataIntervalStart)} → {shortTime(run.dataIntervalEnd)}</span>
        <span><strong>state:</strong> {run.state}</span>
      </div>
      <div className="airflow-runbar">
        <span className="muted">Replay: t+{Math.round(now)}s · event {cursor === null ? run.events.length : cursor + 1}/{run.events.length}</span>
        <div className="button-row">
          <Button size="small" appearance="secondary" onClick={() => setCursor(-1)}>Start</Button>
          <Button
            size="small"
            appearance="primary"
            disabled={cursor === null}
            onClick={() => setCursor(value => (value === null || value + 1 >= run.events.length - 1 ? null : value + 1))}
          >
            Step
          </Button>
          <Button size="small" appearance="secondary" disabled={cursor === null} onClick={() => setCursor(null)}>End</Button>
        </div>
      </div>

      <SharedGraphCanvas graph={dagGraph(lab, states, run)} vscode={vscode} storageKey={`airflow-${lab.dag?.dagId}`} />

      <div className="airflow-lower">
        <table className="airflow-task-table">
          <thead><tr><th>Task</th><th>State</th><th>Try</th><th>Start</th><th>End</th></tr></thead>
          <tbody>
            {run.instances.map(instance => {
              const live = states[instance.taskId];
              const final = cursor === null;
              return (
                <tr key={instance.taskId}>
                  <td>{instance.taskId}</td>
                  <td><span className={`airflow-cell state-${live?.state ?? "none"}`} />{live?.state ?? "none"}</td>
                  <td>{live?.tryNumber ?? 0}</td>
                  <td>{instance.startS !== undefined && (final || (instance.startS <= now)) ? `t+${instance.startS}s` : "—"}</td>
                  <td>{instance.endS !== undefined && (final || TERMINAL.has(live?.state ?? "")) ? `t+${instance.endS}s` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="airflow-log">
          {visibleEvents.map((event, index) => (
            <div key={index} className={index === visibleEvents.length - 1 && cursor !== null ? "is-current" : undefined}>
              <span className="muted">t+{event.t}s</span> [{event.taskId}] {event.message}
            </div>
          ))}
        </div>
      </div>

      {(run.rendered.length > 0 || run.renderError) && (
        <div>
          <h4>Rendered templates <Badge appearance="outline">simulated rendering, not executed</Badge></h4>
          {run.renderError && <div className="error-text">{run.renderError}</div>}
          <table className="airflow-task-table">
            <thead><tr><th>Task</th><th>Field</th><th>Value</th></tr></thead>
            <tbody>
              {run.rendered.map(row => (
                <tr key={`${row.taskId}-${row.field}`}><td>{row.taskId}</td><td>{row.field}</td><td><code>{row.value}</code></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function dagGraph(
  lab: AirflowLabView,
  states: Record<string, { state: string; tryNumber: number }> | undefined,
  run: AirflowLabRunView | undefined
): GraphView {
  const tasks = lab.dag?.tasks ?? [];
  return {
    nodes: tasks.map(task => {
      const state = run ? states?.[task.taskId]?.state ?? "none" : undefined;
      return {
        id: task.taskId,
        label: task.taskId,
        detail: `${task.operator} · ${task.triggerRule}${task.retries ? ` · retries ${task.retries}` : ""}`,
        truth: state ?? "Parsed",
        status: state
      };
    }),
    edges: (lab.dag?.edges ?? []).map(edge => ({
      id: `${edge.upstream}-to-${edge.downstream}`,
      source: edge.upstream,
      target: edge.downstream,
      label: ""
    }))
  };
}

function shortTime(iso: string): string {
  return iso.replace("T", " ").replace(/:00\+00:00$/, "").replace(/\+00:00$/, "");
}

function TruthRow({ capability, truth, note }: { capability: string; truth: string; note: string }) {
  return (
    <div className="truth-row">
      <strong>{capability}</strong>
      <span>{truth}</span>
      <small>{note}</small>
    </div>
  );
}
