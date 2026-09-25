import { Badge, Button, Text } from "@fluentui/react-components";
import { useMemo, useState } from "react";
import type {
  DatabricksJobDesignView,
  DatabricksLabView,
  DatabricksScenarioInput,
  DatabricksStateView,
  DatabricksTaskBehavior,
  DatabricksTaskDesignView,
  DatabricksTaskRunView,
  DatabricksTriggerType,
  FactoryViewState,
  RuntimeViewState
} from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { SharedGraphCanvas } from "./SharedGraphCanvas";
import { databricksGraph, explainTask, formatSeconds } from "../platform/databricksRun";

type Section = "jobs" | "catalog" | "mlflow" | "compute";
const BEHAVIORS: [DatabricksTaskBehavior, string][] = [
  ["success", "runs normally"], ["fail_once", "fails attempt 1"], ["fail_twice", "fails attempts 1-2"], ["fail_always", "always fails"]
];
const TRIGGERS: DatabricksTriggerType[] = ["one_time", "periodic", "file_arrival", "table", "continuous"];
const DEFAULT_SCENARIO: DatabricksScenarioInput = { dataPlane: "local", jobParameters: {}, tasks: {}, triggerType: "one_time", clusterStates: {} };
const TONE: Record<string, "success" | "danger" | "informative" | "warning"> = {
  success: "success", failed: "danger", timedout: "danger", upstream_failed: "warning", excluded: "informative",
  SUCCESS: "success", SUCCESS_WITH_FAILURES: "warning", FAILED: "danger"
};

/** Cloud Lab › Databricks: jobs, Unity Catalog, MLflow and compute, simulated locally. */
export function DatabricksLab({
  vscode,
  factory,
  runtime
}: {
  vscode: VsCodeApi;
  factory: FactoryViewState | undefined;
  runtime: RuntimeViewState;
}) {
  const [section, setSection] = useState<Section>("jobs");
  const running = runtime.status === "running";
  const databricks = factory?.databricks;

  if (!databricks?.exists) {
    return (
      <div className="factory-empty">
        <Text weight="semibold">Create the Databricks lab files</Text>
        <p>
          The Databricks tab runs jobs from <code>factory/databricks/jobs/*.json</code> (Jobs API JSON) on a simulated
          Azure Databricks workspace: notebook tasks run on SparkLab and SQL tasks on DuckDB against your local
          lakehouse, under Unity Catalog permissions, with MLflow tracking and a model registry. Compute and its cost are
          modelled. The samples include a daily ETL job, a model training job run as a service principal, and a for-each job.
        </p>
        <div className="button-row">
          <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>Create lab files</Button>
          <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>Databricks exercises</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="factory-pipelines">
      <div className="factory-toolbar">
        <div className="factory-flavors" role="tablist" aria-label="Databricks">
          {([["jobs", "Jobs"], ["catalog", "Catalog"], ["mlflow", "Experiments and models"], ["compute", "Compute"]] as [Section, string][]).map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={section === id} className={section === id ? "is-active" : ""}
              onClick={() => {
                setSection(id);
                if (id !== "jobs" && running) vscode.postMessage({ type: "refreshDatabricksState" });
              }}>
              {label}
            </button>
          ))}
        </div>
        <div className="button-row">
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>Restore sample files</Button>
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>Databricks exercises</Button>
        </div>
      </div>
      {!running && <p className="factory-note">Start the runtime to run jobs and see Unity Catalog and MLflow. The job canvas is read from the files.</p>}
      {databricks.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
      {section === "jobs" && <JobsSection vscode={vscode} jobs={databricks.jobs} runtime={runtime} />}
      {section === "catalog" && <CatalogSection state={runtime.databricksState} />}
      {section === "mlflow" && <MlflowSection state={runtime.databricksState} />}
      {section === "compute" && <ComputeSection state={runtime.databricksState} lab={runtime.databricksRun} />}
    </div>
  );
}

function JobsSection({ vscode, jobs, runtime }: { vscode: VsCodeApi; jobs: DatabricksJobDesignView[]; runtime: RuntimeViewState }) {
  const running = runtime.status === "running";
  const [name, setName] = useState<string | undefined>(runtime.databricksRun?.jobName);
  const design = jobs.find(job => job.path.endsWith(`/${name}.json`)) ?? jobs[0];
  const jobKey = design ? design.path.split("/").pop()!.replace(/\.json$/, "") : undefined;
  const lab = runtime.databricksRun && runtime.databricksRun.jobName === jobKey ? runtime.databricksRun : undefined;
  const [scenario, setScenario] = useState<DatabricksScenarioInput>(lab?.scenario ?? DEFAULT_SCENARIO);
  const [selected, setSelected] = useState<string>();
  const graph = useMemo(() => (design ? databricksGraph(design, lab?.run) : { nodes: [], edges: [] }), [design, lab?.run]);
  const task = design?.tasks.find(t => t.key === selected);
  const run = (dataPlane: DatabricksScenarioInput["dataPlane"]) => {
    if (!jobKey) return;
    const next = { ...scenario, dataPlane };
    setScenario(next);
    vscode.postMessage({ type: "simulateDatabricks", name: jobKey, scenario: next });
  };

  if (!design) {
    return <p className="factory-note">No job in <code>factory/databricks/jobs/</code> yet.</p>;
  }
  return (
    <>
      <div className="factory-toolbar">
        <div className="button-row">
          <select aria-label="Job" value={jobKey} onChange={event => { setName(event.target.value); setSelected(undefined); setScenario(DEFAULT_SCENARIO); }}>
            {jobs.map(job => {
              const key = job.path.split("/").pop()!.replace(/\.json$/, "");
              return <option key={key} value={key}>{key}</option>;
            })}
          </select>
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openFactoryFile", path: design.path })}>Open JSON</Button>
        </div>
        <div className="button-row">
          <Button size="small" appearance="secondary" disabled={!running || !!design.error} onClick={() => run("simulated")}>Dry run</Button>
          <Button size="small" appearance="primary" disabled={!running || !!design.error} onClick={() => run("local")}>Run now</Button>
        </div>
      </div>
      {design.error ? (
        <p className="factory-error">{design.path}: {design.error}</p>
      ) : (
        <>
          <p className="factory-description">
            {design.description || design.name}
            {design.runAs && <> · runs as <code>{design.runAs}</code></>}
            {design.schedule && <> · schedule <code>{design.schedule}</code></>}
            {design.clusters.map(cluster => <span key={cluster.key}> · job cluster <code>{cluster.key}</code> ({cluster.label})</span>)}
          </p>
          <div className="factory-breadcrumb">
            <span className="factory-legend">
              <i className="cond-succeeded" /> depends on <i className="cond-failed" /> false branch / failure handler
              <i className="cond-completed" /> all done
            </span>
          </div>
          <SharedGraphCanvas graph={graph} vscode={vscode} storageKey={`databricks:${jobKey}`} onNodeClick={setSelected} />
          {task && <TaskDetails task={task} result={lab?.run?.tasks.find(t => t.key === task.key)} />}
          <RunSettings design={design} scenario={scenario} onChange={setScenario} />
          {lab && <RunResult lab={lab} onSelect={setSelected} />}
        </>
      )}
      <ConceptsTable />
    </>
  );
}

function TaskDetails({ task, result }: { task: DatabricksTaskDesignView; result?: DatabricksTaskRunView }) {
  return (
    <div className="factory-details">
      <div className="factory-details-head">
        <div>
          <Text weight="semibold">{task.key}</Text> <code>{task.kind}_task</code>
          <div className="factory-note">
            {task.detail}
            {task.dependsOn.length > 0 && <> · depends on {task.dependsOn.map(d => `${d.taskKey}${d.outcome ? ` (${d.outcome})` : ""}`).join(", ")} · run if {task.runIf}</>}
            {task.compute && <> · {task.compute}</>}
            {task.maxRetries > 0 && <> · max_retries {task.maxRetries}</>}
            {task.timeoutSeconds > 0 && <> · timeout {task.timeoutSeconds} s</>}
          </div>
        </div>
        {result && <Badge appearance="tint" color={TONE[result.state] ?? "informative"}>{result.stateLabel}</Badge>}
      </div>
      {Object.keys(task.parameters).length > 0 && (
        <p className="factory-note">Parameters: {Object.entries(task.parameters).map(([k, v]) => `${k} = ${v}`).join(" · ")}</p>
      )}
      {task.inner && <p className="factory-note">For each item: {task.inner.key} ({task.inner.detail})</p>}
      {result ? <TaskResult task={result} /> : <p className="factory-note">Run the job to see this task's run.</p>}
    </div>
  );
}

function TaskResult({ task }: { task: DatabricksTaskRunView }) {
  return (
    <div className="databricks-task-result">
      <p className={task.state === "failed" || task.state === "timedout" ? "factory-error" : "factory-explanation"}>{explainTask(task)}</p>
      {Object.keys(task.parameters).length > 0 && (
        <p className="factory-note">Widgets received: {Object.entries(task.parameters).map(([k, v]) => `${k} = "${v}"`).join(" · ")}</p>
      )}
      {task.condition && (
        <p className="factory-note">
          <code>{task.condition.leftExpression}</code> → {task.condition.left} {task.condition.op} {task.condition.right}
          {" "}(<code>{task.condition.rightExpression}</code>) = {String(task.condition.result)}
        </p>
      )}
      {Object.keys(task.values).length > 0 && (
        <p className="factory-note">Task values: {Object.entries(task.values).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join(" · ")}</p>
      )}
      {task.exitValue !== undefined && <p className="factory-note">Notebook exit value: "{task.exitValue}" (not readable by other tasks: use task values)</p>}
      {task.attempts.length > 1 && (
        <p className="factory-note">Attempts: {task.attempts.map(a => `#${a.number} ${a.status} ${formatSeconds(a.startS)}→${formatSeconds(a.endS)}`).join(" · ")}</p>
      )}
      {task.tablesWritten.length > 0 && <p className="factory-note">Tables written: {task.tablesWritten.join(", ")}</p>}
      {task.notes.map(note => <p key={note} className="factory-hint">{note}</p>)}
      {task.columns.length > 0 && (
        <div className="retail-preview-wrap">
          <table className="retail-preview">
            <thead><tr>{task.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{task.rows.map((row, i) => <tr key={i}>{task.columns.map(c => <td key={c}>{String(row[c] ?? "NULL")}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {task.iterations.length > 0 && (
        <table className="factory-runs">
          <thead><tr><th>Input</th><th>State</th><th>Time</th><th>Details</th></tr></thead>
          <tbody>
            {task.iterations.map((iteration, i) => (
              <tr key={i}>
                <td>{JSON.stringify(iteration.input)}</td>
                <td><Badge appearance="tint" color={TONE[iteration.state] ?? "informative"}>{iteration.stateLabel}</Badge></td>
                <td>{formatSeconds(iteration.startS)} → {formatSeconds(iteration.endS)}</td>
                <td>{iteration.error || iteration.tablesWritten.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function RunSettings({ design, scenario, onChange }: { design: DatabricksJobDesignView; scenario: DatabricksScenarioInput; onChange: (next: DatabricksScenarioInput) => void }) {
  const work = design.tasks.filter(task => task.kind !== "condition");
  const setTask = (key: string, patch: Partial<DatabricksScenarioInput["tasks"][string]>) => {
    const current = scenario.tasks[key] ?? { behavior: "success" as const };
    onChange({ ...scenario, tasks: { ...scenario.tasks, [key]: { ...current, ...patch } } });
  };
  const clusters = [...new Set(design.tasks.flatMap(t => [t.compute, t.inner?.compute ?? ""]).filter(c => c.startsWith("all-purpose ")).map(c => c.slice(12)))];
  return (
    <details className="factory-scenario" open>
      <summary>Run settings: job parameters, trigger and task behavior</summary>
      <div className="factory-scenario-grid">
        {design.parameters.map(parameter => (
          <label key={parameter.name}>
            <span>{parameter.name} <small>job parameter</small></span>
            <input value={scenario.jobParameters[parameter.name] ?? ""} placeholder={parameter.defaultValue}
              onChange={event => onChange({ ...scenario, jobParameters: { ...scenario.jobParameters, [parameter.name]: event.target.value } })} />
          </label>
        ))}
        <label>
          <span>Trigger</span>
          <select value={scenario.triggerType} onChange={event => onChange({ ...scenario, triggerType: event.target.value as DatabricksTriggerType })}>
            {TRIGGERS.map(trigger => <option key={trigger} value={trigger}>{trigger}</option>)}
          </select>
        </label>
        <label>
          <span>Start time (UTC)</span>
          <input type="datetime-local" value={scenario.now ?? ""} onChange={event => onChange({ ...scenario, now: event.target.value || undefined })} />
        </label>
        {clusters.map(cluster => (
          <label key={cluster}>
            <span>{cluster} <small>all-purpose cluster</small></span>
            <select value={scenario.clusterStates[cluster] ?? ""} onChange={event => {
              const states = { ...scenario.clusterStates };
              if (event.target.value) states[cluster] = event.target.value as "RUNNING" | "TERMINATED"; else delete states[cluster];
              onChange({ ...scenario, clusterStates: states });
            }}>
              <option value="">as in compute.json</option>
              <option value="RUNNING">running</option>
              <option value="TERMINATED">terminated</option>
            </select>
          </label>
        ))}
      </div>
      <table className="factory-scenario-activities">
        <thead><tr><th>Task</th><th>Behavior</th><th>Duration (s)</th><th>Task values in a dry run (JSON)</th></tr></thead>
        <tbody>
          {work.map(task => {
            const current = scenario.tasks[task.key];
            return (
              <tr key={task.key}>
                <td>{task.key}<small>{task.kind}</small></td>
                <td>
                  <select value={current?.behavior ?? "success"} onChange={event => setTask(task.key, { behavior: event.target.value as DatabricksTaskBehavior })}>
                    {BEHAVIORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </td>
                <td>
                  <input type="number" min={0} value={current?.durationSeconds ?? ""} placeholder="default"
                    onChange={event => setTask(task.key, { durationSeconds: event.target.value === "" ? undefined : Number(event.target.value) })} />
                </td>
                <td><input value={current?.values ?? ""} placeholder='{"new_rows": 0}' onChange={event => setTask(task.key, { values: event.target.value })} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="factory-note">
        Run now executes the notebook and SQL tasks on the local lakehouse; a dry run runs nothing and uses the task values
        above. Job parameters override a task parameter with the same key and reach notebooks as widgets.
      </p>
    </details>
  );
}

function RunResult({ lab, onSelect }: { lab: DatabricksLabView; onSelect: (key: string) => void }) {
  const run = lab.run;
  return (
    <div className="factory-result">
      <div className="factory-result-head">
        <div>
          <div className="eyebrow">{lab.dataPlane === "local" ? "local lakehouse" : "dry run"}{run ? ` · run ${run.runId} · as ${run.principal}` : ""}</div>
          <Text size={400} weight="semibold">{run ? `Run ${run.statusLabel}` : lab.status === "invalid" ? "Job not valid" : "Run not started"}</Text>
          {run && <span className="factory-note"> · {formatSeconds(run.durationS)} simulated</span>}
        </div>
        {run && <Badge appearance="filled" color={TONE[run.resultState] ?? "informative"}>{run.statusLabel}</Badge>}
      </div>
      <p className="factory-note">{lab.truth}</p>
      {lab.issues.map((issue, i) => <p key={i} className="factory-error">{issue.path ? `${issue.path}: ` : ""}{issue.message}</p>)}
      {lab.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
      {run && (
        <>
          <p className="factory-explanation">{run.explanation}</p>
          {Object.keys(run.parameters).length > 0 && (
            <p className="factory-note">Job parameters: {Object.entries(run.parameters).map(([k, v]) => `${k} = "${v}"`).join(" · ")}</p>
          )}
          {run.notes.map(note => <p key={note} className="factory-hint">{note}</p>)}
          <table className="factory-runs">
            <thead><tr><th>Task</th><th>State</th><th>Time</th><th>Details</th></tr></thead>
            <tbody>
              {run.tasks.map(task => (
                <tr key={task.key} onClick={() => onSelect(task.key)}>
                  <td>{task.key}<small>{task.kind}{task.compute ? ` · ${task.compute}` : ""}</small></td>
                  <td><Badge appearance="tint" color={TONE[task.state] ?? "informative"}>{task.stateLabel}</Badge></td>
                  <td>{formatSeconds(task.startS)} → {formatSeconds(task.endS)}{task.attempts.length > 1 ? ` · ${task.attempts.length} attempts` : ""}</td>
                  <td>{task.error ? <span className="factory-error">{task.error}</span> : task.reason || (task.outcome ? `outcome ${task.outcome}` : Object.keys(task.values).map(k => `${k} = ${JSON.stringify(task.values[k])}`).join(", "))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <CostTable lab={lab} />
        </>
      )}
      {lab.tablesChanged.length > 0 && (
        <div className="factory-tables">
          <strong>Tables written on the local lakehouse</strong>
          {lab.tablesChanged.map(table => <span key={table.name}><code>main.{table.name}</code> {table.rows} rows</span>)}
        </div>
      )}
    </div>
  );
}

function CostTable({ lab }: { lab: DatabricksLabView }) {
  const run = lab.run!;
  if (!run.compute.length) return null;
  return (
    <details className="factory-differences" open>
      <summary>Compute and cost (modelled, lab units)</summary>
      <table>
        <thead><tr><th>Compute</th><th>Start-up</th><th>Billed</th><th>DBU</th><th>Cost</th><th>Idle after the run</th></tr></thead>
        <tbody>
          {run.compute.map(usage => (
            <tr key={usage.key + usage.kind}>
              <th>{usage.label}<small className="databricks-block">{usage.tasks.join(", ")}</small></th>
              <td>{formatSeconds(usage.startupS)}</td>
              <td>{formatSeconds(usage.billedS)}</td>
              <td>{usage.dbu.toFixed(3)}</td>
              <td>{usage.cost.toFixed(3)}</td>
              <td>{usage.idleAfterS ? `${formatSeconds(usage.idleAfterS)} · ${usage.idleCost.toFixed(3)}` : ""}</td>
            </tr>
          ))}
          <tr><th>Total</th><td /><td /><td>{run.cost.dbu.toFixed(3)}</td><td>{run.cost.cost.toFixed(3)}</td><td>{run.cost.idleCost ? run.cost.idleCost.toFixed(3) : ""}</td></tr>
        </tbody>
      </table>
      {run.compute.flatMap(usage => usage.notes).filter((n, i, all) => all.indexOf(n) === i).map(note => <p key={note} className="factory-note">{note}</p>)}
    </details>
  );
}

function CatalogSection({ state }: { state?: DatabricksStateView }) {
  const [principal, setPrincipal] = useState("");
  if (!state) return <p className="factory-note">Start the runtime to explore Unity Catalog.</p>;
  const unity = state.unity;
  const principals = [...new Set(unity.grants.map(g => g.principal))].sort();
  const grants = unity.grants.filter(g => !principal || g.principal === principal);
  return (
    <div className="databricks-columns">
      <div className="factory-result">
        <Text weight="semibold">Catalog <code>{unity.catalog}</code></Text>
        <p className="factory-note">
          Schemas are the lab's layers; <code>{unity.catalog}.silver.orders</code> is the lab table <code>silver.orders</code>.
          Objects that already exist are owned by you (<code>{unity.labUser}</code>); a principal owns the tables and models it creates.
        </p>
        {unity.schemas.map(schema => (
          <details key={schema.name} className="databricks-schema" open={schema.tables.length > 0 || schema.models.length > 0}>
            <summary><code>{schema.name}</code> <small>{schema.tables.length} tables{schema.models.length ? ` · ${schema.models.length} models` : ""}{schema.readOnly ? " · read-only" : ""}</small></summary>
            <ul>
              {schema.tables.map(table => <li key={table.name}><code>{table.name}</code> <small>{table.rows} rows · owner {table.owner}</small></li>)}
              {schema.models.map(model => (
                <li key={model.name}><code>{model.name}</code> <small>model · {model.versions} version(s) · owner {model.owner}
                  {Object.entries(model.aliases).map(([alias, version]) => ` · @${alias} → v${version}`).join("")}</small></li>
              ))}
            </ul>
          </details>
        ))}
      </div>
      <div className="factory-result">
        <div className="factory-result-head">
          <Text weight="semibold">Grants</Text>
          <select aria-label="Principal" value={principal} onChange={event => setPrincipal(event.target.value)}>
            <option value="">every principal</option>
            {principals.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <table className="factory-runs">
          <thead><tr><th>Principal</th><th>Privilege</th><th>On</th></tr></thead>
          <tbody>
            {grants.map((grant, i) => <tr key={i}><td>{grant.principal}</td><td>{grant.privilege}</td><td>{grant.securable} <code>{grant.name}</code></td></tr>)}
          </tbody>
        </table>
        <p className="factory-note">
          Plus USE CATALOG on <code>main</code> for all users (the default). Reading needs USE CATALOG, USE SCHEMA and SELECT;
          writing adds MODIFY; creating needs CREATE TABLE (or CREATE MODEL) on the schema. Privileges granted on a schema
          apply to everything in it, including tables created later.
        </p>
        {Object.entries(unity.groups).map(([group, members]) => <p key={group} className="factory-note">Group <code>{group}</code>: {members.join(", ")}</p>)}
        {unity.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
      </div>
    </div>
  );
}

function MlflowSection({ state }: { state?: DatabricksStateView }) {
  if (!state) return <p className="factory-note">Start the runtime to see MLflow experiments and models.</p>;
  const { experiments, models } = state.mlflow;
  return (
    <div className="databricks-columns">
      <div className="factory-result">
        <Text weight="semibold">Experiments</Text>
        {!experiments.length && <p className="factory-note">No experiment yet: run a job whose notebook uses mlflow.</p>}
        {experiments.map(experiment => (
          <div key={experiment.id}>
            <p className="factory-description"><code>{experiment.name}</code></p>
            <table className="factory-runs">
              <thead><tr><th>Run</th><th>Params</th><th>Metrics</th><th>From</th></tr></thead>
              <tbody>
                {[...experiment.runs].reverse().map(run => (
                  <tr key={run.runId}>
                    <td>{run.runName}<small>{run.status} · {run.runId.slice(0, 8)}{run.models.length ? ` · model: ${run.models.join(", ")}` : ""}</small></td>
                    <td>{Object.entries(run.params).map(([k, v]) => `${k}=${v}`).join(", ")}</td>
                    <td>{Object.entries(run.metrics).map(([k, v]) => `${k}=${round(v)}`).join(", ")}</td>
                    <td>{run.job ? `${run.job} / ${run.task}` : ""}<small>{run.user}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <div className="factory-result">
        <Text weight="semibold">Models in Unity Catalog</Text>
        {!models.length && <p className="factory-note">No registered model yet.</p>}
        {models.map(model => (
          <div key={model.name}>
            <p className="factory-description"><code>{model.name}</code> <small>owner {model.owner}</small></p>
            <table className="factory-runs">
              <thead><tr><th>Version</th><th>Aliases</th><th>Metrics</th><th>Signature</th></tr></thead>
              <tbody>
                {[...model.versions].reverse().map(version => (
                  <tr key={version.version}>
                    <td>v{version.version}<small>{version.kind} · {version.user}</small></td>
                    <td>{Object.entries(model.aliases).filter(([, v]) => v === version.version).map(([alias]) => `@${alias}`).join(" ")}</td>
                    <td>{Object.entries(version.metrics).map(([k, v]) => `${k}=${round(v)}`).join(", ")}</td>
                    <td>{version.inputs.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        <p className="factory-note">
          Models in Unity Catalog have three-level names, need a signature, and use aliases (for example <code>@champion</code>) instead of
          stages. <code>models:/main.ml.power_model@champion</code> loads whichever version holds the alias.
        </p>
      </div>
    </div>
  );
}

function ComputeSection({ state, lab }: { state?: DatabricksStateView; lab?: DatabricksLabView }) {
  return (
    <>
      {state && (
        <div className="factory-result">
          <Text weight="semibold">Workspace compute (compute.json)</Text>
          <table className="factory-runs">
            <thead><tr><th>All-purpose cluster</th><th>Nodes</th><th>Auto-termination</th><th>State</th></tr></thead>
            <tbody>
              {state.computeCatalog.clusters.map(cluster => (
                <tr key={cluster.clusterId}><td><code>{cluster.clusterId}</code><small>{cluster.name}</small></td><td>{cluster.nodeType} · {cluster.workers} workers + driver</td>
                  <td>{cluster.autoterminationMinutes ? `${cluster.autoterminationMinutes} min` : "never"}</td><td>{cluster.running ? "running" : "terminated"}</td></tr>
              ))}
            </tbody>
          </table>
          <table className="factory-runs">
            <thead><tr><th>SQL warehouse</th><th>Size</th><th>Type</th></tr></thead>
            <tbody>
              {state.computeCatalog.warehouses.map(w => <tr key={w.id}><td><code>{w.id}</code><small>{w.name}</small></td><td>{w.size}</td><td>{w.serverless ? "serverless" : "pro"}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
      {lab?.run && <CostTable lab={lab} />}
      <details className="factory-differences" open>
        <summary>Which compute for which work</summary>
        <table>
          <thead><tr><th>Compute</th><th>For</th><th>Starts</th><th>Bills</th></tr></thead>
          <tbody>
            <tr><th>Serverless (jobs, notebooks)</th><td>Most new workloads: no configuration</td><td>In seconds</td><td>While tasks run</td></tr>
            <tr><th>Job cluster (job_clusters)</th><td>Scheduled jobs on classic compute; shared by the job's tasks</td><td>A few minutes (faster from a pool)</td><td>From start to termination after the last task; jobs compute rate</td></tr>
            <tr><th>All-purpose cluster</th><td>Interactive notebooks; possible for jobs, but costlier</td><td>A few minutes when terminated</td><td>While up, idle time included, until auto-termination; higher rate than jobs compute</td></tr>
            <tr><th>SQL warehouse</th><td>SQL tasks, dashboards, BI queries</td><td>Seconds (serverless)</td><td>While running</td></tr>
          </tbody>
        </table>
        <p className="factory-note">
          The lab's start times, DBU rates and cost units are teaching values: their order is real, their amounts are not
          Azure prices. The Azure VM bill (spot or on-demand) is not counted.
        </p>
      </details>
    </>
  );
}

const CONCEPTS: [string, string][] = [
  ["Run if", "ALL_SUCCESS (default), AT_LEAST_ONE_SUCCESS, NONE_FAILED, ALL_DONE, AT_LEAST_ONE_FAILED, ALL_FAILED. Unmet: Upstream failed, or Excluded for the failure handlers."],
  ["Excluded", "A task that did not run because of a condition. It counts as successful downstream; a task whose dependencies are all excluded is excluded."],
  ["Run status", "Decided by the leaf tasks: Succeeded, Succeeded with failures (a failure was handled and every leaf succeeded), or Failed."],
  ["If/else condition", "Compares two operands: == and != as text, >, >=, <, <= as numbers. Downstream tasks depend on its (true) or (false) outcome."],
  ["Task values", "dbutils.jobs.taskValues.set(key, value) in a notebook; {{tasks.<task>.values.<key>}} downstream. The notebook exit value is not a task value."],
  ["Parameters", "Job parameters are pushed down to notebook tasks as widgets and win over a task parameter with the same key. Values are text."]
];

function ConceptsTable() {
  return (
    <details className="factory-differences">
      <summary>Databricks jobs: the rules the simulator follows</summary>
      <table><tbody>{CONCEPTS.map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}</tbody></table>
    </details>
  );
}

function round(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}
