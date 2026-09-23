import { Badge, Button, Text } from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import type {
  AirflowDefinitionView,
  AirflowTaskView,
  AirflowViewState,
  GraphView
} from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { SharedGraphCanvas } from "./SharedGraphCanvas";

type TaskState = "idle" | "retrying" | "success" | "failed" | "upstream_failed" | "skipped";
type RunStatus = "idle" | "running" | "success" | "failed";

interface TaskRuntime {
  state: TaskState;
  attempts: number;
}

interface Simulation {
  status: RunStatus;
  step: number;
  elapsedSeconds: number;
  tasks: Record<string, TaskRuntime>;
  logs: string[];
}

const TERMINAL = new Set<TaskState>(["success", "failed", "upstream_failed", "skipped"]);

export function AirflowSurface({
  vscode,
  airflow
}: {
  vscode: VsCodeApi;
  airflow: AirflowViewState | undefined;
}) {
  const definition = airflow?.definition;
  const [simulation, setSimulation] = useState<Simulation | null>(
    definition ? createSimulation(definition) : null
  );

  useEffect(() => {
    setSimulation(definition ? createSimulation(definition) : null);
  }, [definition?.dagId, definition?.schedule, JSON.stringify(definition?.tasks ?? [])]);

  const graph = useMemo(
    () => definition && simulation
      ? graphWithTaskStates(airflow?.graph ?? { nodes: [], edges: [] }, simulation)
      : airflow?.graph ?? { nodes: [], edges: [] },
    [airflow?.graph, definition, simulation]
  );

  if (!airflow) return <div className="empty-state">Airflow state is not available.</div>;

  return (
    <section className="airflow-surface">
      <div className="airflow-toolbar">
        <div>
          <div className="eyebrow">Deterministic scheduler simulation</div>
          <Text size={500} weight="semibold">{airflow.path}</Text>
        </div>
        <div className="button-row">
          <Badge appearance="tint" color={airflow.valid ? "success" : airflow.exists ? "danger" : "informative"}>
            {airflow.valid ? "valid DAG" : airflow.exists ? "invalid DAG" : "missing"}
          </Badge>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "openAirflowSource" })}>
            {airflow.exists ? "Open DAG spec" : "Create starter"}
          </Button>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "refreshAirflow" })}>
            Refresh
          </Button>
        </div>
      </div>

      {airflow.errors.length > 0 && (
        <div className="pipeline-diagnostics" role="alert">
          {airflow.errors.map((error, index) => <div key={index}>{error}</div>)}
        </div>
      )}

      {definition && simulation && airflow.valid && (
        <>
          <div className="airflow-runbar">
            <div className="pipeline-facts">
              <span><strong>DAG:</strong> {definition.dagId}</span>
              <span><strong>Schedule:</strong> {definition.schedule}</span>
              <span><strong>Run:</strong> {simulation.status}</span>
              <span><strong>Logical time:</strong> {simulation.elapsedSeconds}s</span>
            </div>
            <div className="button-row">
              <Button size="small" appearance="primary" disabled={isTerminal(simulation.status)} onClick={() => setSimulation(step(definition, simulation))}>
                Step
              </Button>
              <Button size="small" appearance="secondary" disabled={isTerminal(simulation.status)} onClick={() => setSimulation(runToEnd(definition, simulation))}>
                Run to end
              </Button>
              <Button size="small" appearance="secondary" onClick={() => setSimulation(createSimulation(definition))}>
                Reset
              </Button>
            </div>
          </div>

          <SharedGraphCanvas graph={graph} vscode={vscode} storageKey="airflow-main" />

          <div className="airflow-lower">
            <div className="airflow-task-table">
              {definition.tasks.map(task => {
                const runtime = simulation.tasks[task.id];
                return (
                  <div className="airflow-task-row" key={task.id}>
                    <strong>{task.id}</strong>
                    <span>{task.type}</span>
                    <span>{runtime.state}</span>
                    <span>{runtime.attempts} attempt{runtime.attempts === 1 ? "" : "s"}</span>
                  </div>
                );
              })}
            </div>
            <div className="airflow-log">
              {simulation.logs.slice(-12).map((log, index) => <div key={index}>{log}</div>)}
            </div>
          </div>
        </>
      )}

      <p className="muted pipeline-footnote">
        This models DAG dependency, retry and trigger-rule behavior. It does not run an Airflow scheduler, executor or worker.
      </p>
    </section>
  );
}

function createSimulation(definition: AirflowDefinitionView): Simulation {
  return {
    status: "idle",
    step: 0,
    elapsedSeconds: 0,
    tasks: Object.fromEntries(
      definition.tasks.map(task => [task.id, { state: "idle" as const, attempts: 0 }])
    ),
    logs: ["SIMULATED DAG — no Airflow scheduler or worker is running."]
  };
}

function step(definition: AirflowDefinitionView, current: Simulation): Simulation {
  if (isTerminal(current.status)) return current;
  const next: Simulation = structuredClone(current);
  next.step += 1;
  if (next.status === "idle") next.status = "running";

  for (const task of definition.tasks) {
    const runtime = next.tasks[task.id];
    if (runtime.state === "retrying") {
      runtime.state = "idle";
      next.logs.push(`[${task.id}] retry delay elapsed; task is eligible again.`);
    }
  }

  propagateBlocked(definition, next);
  const runnable = definition.tasks.find(task =>
    next.tasks[task.id].state === "idle" && dependenciesSatisfied(task, next)
  );

  if (!runnable) return finalize(definition, next);

  const runtime = next.tasks[runnable.id];
  runtime.attempts += 1;
  next.elapsedSeconds += runnable.durationSeconds;
  next.logs.push(`[${runnable.id}] attempt ${runtime.attempts} started; simulated duration ${runnable.durationSeconds}s.`);

  const failsTransiently = runnable.failureMode === "transient" && runtime.attempts === 1;
  const failsPermanently = runnable.failureMode === "permanent";

  if (failsTransiently || failsPermanently) {
    if (runtime.attempts <= runnable.retries) {
      runtime.state = "retrying";
      next.elapsedSeconds += runnable.retryDelaySeconds;
      next.logs.push(`[${runnable.id}] simulated failure; retry ${runtime.attempts}/${runnable.retries} after ${runnable.retryDelaySeconds}s.`);
      return next;
    }
    runtime.state = "failed";
    next.logs.push(`[${runnable.id}] failed after ${runtime.attempts} attempt(s).`);
    propagateBlocked(definition, next);
    return finalize(definition, next);
  }

  runtime.state = "success";
  next.logs.push(`[${runnable.id}] success.`);
  propagateBlocked(definition, next);
  return finalize(definition, next);
}

function runToEnd(definition: AirflowDefinitionView, current: Simulation): Simulation {
  let next = current;
  const budget = Math.max(20, definition.tasks.reduce((sum, task) => sum + task.retries + 2, 0) * 2);
  for (let index = 0; index < budget && !isTerminal(next.status); index += 1) {
    next = step(definition, next);
  }
  if (!isTerminal(next.status)) {
    const failed = structuredClone(next);
    failed.status = "failed";
    failed.logs.push("Simulation guard stopped: DAG did not reach a terminal state.");
    return failed;
  }
  return next;
}

function dependenciesSatisfied(task: AirflowTaskView, simulation: Simulation): boolean {
  if (task.dependsOn.length === 0) return true;
  const states = task.dependsOn.map(id => simulation.tasks[id]?.state);
  if (states.some(state => !state || !TERMINAL.has(state))) return false;

  if (task.triggerRule === "all_done") return true;
  if (task.triggerRule === "none_failed_min_one_success") {
    return !states.includes("failed") &&
      !states.includes("upstream_failed") &&
      states.includes("success");
  }
  return states.every(state => state === "success");
}

function propagateBlocked(definition: AirflowDefinitionView, simulation: Simulation): void {
  let changed = true;
  while (changed) {
    changed = false;
    for (const task of definition.tasks) {
      const runtime = simulation.tasks[task.id];
      if (runtime.state !== "idle" || task.dependsOn.length === 0) continue;
      const states = task.dependsOn.map(id => simulation.tasks[id]?.state);
      if (states.some(state => !state || !TERMINAL.has(state))) continue;
      if (dependenciesSatisfied(task, simulation)) continue;

      runtime.state = states.includes("failed") || states.includes("upstream_failed")
        ? "upstream_failed"
        : "skipped";
      simulation.logs.push(`[${task.id}] ${runtime.state}; trigger rule ${task.triggerRule} not satisfied.`);
      changed = true;
    }
  }
}

function finalize(definition: AirflowDefinitionView, simulation: Simulation): Simulation {
  const states = definition.tasks.map(task => simulation.tasks[task.id].state);
  if (!states.every(state => TERMINAL.has(state))) return simulation;

  simulation.status = states.some(state => state === "failed" || state === "upstream_failed")
    ? "failed"
    : "success";
  simulation.logs.push(`DAG finished with status ${simulation.status}.`);
  return simulation;
}

function graphWithTaskStates(graph: GraphView, simulation: Simulation): GraphView {
  return {
    nodes: graph.nodes.map(node => ({
      ...node,
      detail: `${node.detail} · ${simulation.tasks[node.id]?.state ?? "idle"}`,
      truth: "Simulated"
    })),
    edges: graph.edges
  };
}

function isTerminal(status: RunStatus): boolean {
  return status === "success" || status === "failed";
}
