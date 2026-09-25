import { Badge, Button, Text } from "@fluentui/react-components";
import { useMemo, useState } from "react";
import type {
  FactoryActivityBehavior,
  FactoryActivityRunView,
  FactoryDesignActivityView,
  FactoryDesignView,
  FactoryFlavor,
  FactoryLabView,
  FactoryRunView,
  FactoryScenarioInput,
  FactoryTriggerType,
  FactoryViewState,
  RuntimeViewState
} from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { SharedGraphCanvas } from "./SharedGraphCanvas";
import { factoryGraph, flattenActivities, isControlActivity } from "../platform/factoryRun";

const FLAVORS: { id: FactoryFlavor; label: string }[] = [
  { id: "fabric", label: "Microsoft Fabric" },
  { id: "adf", label: "Azure Data Factory" },
  { id: "synapse", label: "Azure Synapse" }
];
const BEHAVIORS: [FactoryActivityBehavior, string][] = [
  ["success", "runs normally"],
  ["fail_once", "fails attempt 1"],
  ["fail_twice", "fails attempts 1-2"],
  ["fail_always", "always fails"]
];
const TRIGGERS: FactoryTriggerType[] = ["Manual", "ScheduleTrigger", "TumblingWindowTrigger", "BlobEventsTrigger"];
const DEFAULT_SCENARIO: FactoryScenarioInput = { dataPlane: "local", parameters: {}, activities: {}, triggerType: "Manual" };
const STATUS_TONE: Record<string, "success" | "danger" | "informative" | "warning"> = {
  Succeeded: "success", Failed: "danger", Skipped: "informative", InProgress: "warning"
};

interface Level {
  path: string;
  key: string;
}

export function FactoryPipelines({
  vscode,
  factory,
  runtime
}: {
  vscode: VsCodeApi;
  factory: FactoryViewState | undefined;
  runtime: RuntimeViewState;
}) {
  const running = runtime.status === "running";
  const pipelines = factory?.pipelines ?? [];
  const [flavor, setFlavor] = useState<FactoryFlavor>(runtime.factoryRun?.flavor ?? "fabric");
  const [name, setName] = useState<string | undefined>(runtime.factoryRun?.pipelineName);
  const [scenario, setScenario] = useState<FactoryScenarioInput>(runtime.factoryRun?.scenario ?? DEFAULT_SCENARIO);
  const [levels, setLevels] = useState<Level[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>();

  const available = pipelines.filter(pipeline => pipeline.flavor === flavor);
  const design = available.find(pipeline => pipeline.name === name) ?? available[0];
  const lab = runtime.factoryRun && design && runtime.factoryRun.flavor === design.flavor &&
    runtime.factoryRun.pipelineName === design.name ? runtime.factoryRun : undefined;
  const levelActivities = useMemo(() => activitiesAt(design, levels), [design, levels]);
  const graph = useMemo(() => factoryGraph(levelActivities, lab?.run), [levelActivities, lab?.run]);
  const selectedDesign = design ? flattenActivities(design.activities).find(activity => activity.path === selectedPath) : undefined;

  const choosePipeline = (nextFlavor: FactoryFlavor, nextName?: string) => {
    setFlavor(nextFlavor);
    setName(nextName);
    setLevels([]);
    setSelectedPath(undefined);
    setScenario(current => ({ ...current, parameters: {}, activities: {} }));
  };
  const run = (dataPlane: FactoryScenarioInput["dataPlane"]) => {
    if (!design) return;
    const next = { ...scenario, dataPlane };
    setScenario(next);
    vscode.postMessage({ type: "simulateFactory", flavor: design.flavor, name: design.name, scenario: next });
  };

  if (!factory?.exists) {
    return (
      <div className="factory-empty">
        <Text weight="semibold">Create the Cloud Lab files</Text>
        <p>
          The lab lives in a <code>factory/</code> folder laid out like each product's git integration: Fabric
          <code>*.DataPipeline/pipeline-content.json</code>, Azure Data Factory and Synapse <code>pipeline/*.json</code> with
          datasets, notebooks (Fabric, Databricks) and stored procedures in <code>sql/procedures</code>. The same daily
          retail load is written for each product so you can compare them.
        </p>
        <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>Create lab files</Button>
      </div>
    );
  }

  return (
    <div className="factory-pipelines">
      <div className="factory-toolbar">
        <div className="factory-flavors" role="tablist" aria-label="Product">
          {FLAVORS.map(item => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={flavor === item.id}
              className={flavor === item.id ? "is-active" : ""}
              onClick={() => choosePipeline(item.id)}
            >
              {item.label}
              <small>{pipelines.filter(p => p.flavor === item.id).length}</small>
            </button>
          ))}
        </div>
        <div className="button-row">
          {available.length > 0 && (
            <select aria-label="Pipeline" value={design?.name} onChange={event => choosePipeline(flavor, event.target.value)}>
              {available.map(pipeline => <option key={pipeline.name} value={pipeline.name}>{pipeline.name}</option>)}
            </select>
          )}
          {design && (
            <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openFactoryFile", path: design.path })}>
              Open JSON
            </Button>
          )}
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>
            Restore sample files
          </Button>
          <Button size="small" appearance="secondary" disabled={!running || !design || !!design.error} onClick={() => run("simulated")}>
            Dry run
          </Button>
          <Button size="small" appearance="primary" disabled={!running || !design || !!design.error} onClick={() => run("local")}>
            Run on local lakehouse
          </Button>
        </div>
      </div>
      {!running && <p className="factory-note">Start the runtime to run pipelines. The canvas below is read from the files.</p>}
      {factory.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}

      {!design ? (
        <p className="factory-note">No {FLAVORS.find(f => f.id === flavor)?.label} pipeline in <code>factory/</code> yet.</p>
      ) : design.error ? (
        <p className="factory-error">{design.path}: {design.error}</p>
      ) : (
        <>
          {design.description && <p className="factory-description">{design.description}</p>}
          <div className="factory-breadcrumb">
            <button type="button" onClick={() => setLevels([])}>{design.name}</button>
            {levels.map((level, index) => (
              <span key={`${level.path}:${level.key}`}>
                {" › "}
                <button type="button" onClick={() => setLevels(levels.slice(0, index + 1))}>
                  {level.path.split("/").pop()} · {level.key}
                </button>
              </span>
            ))}
            <span className="factory-legend">
              <i className="cond-succeeded" /> Succeeded <i className="cond-failed" /> Failed
              <i className="cond-completed" /> Completed <i className="cond-skipped" /> Skipped
            </span>
          </div>
          <SharedGraphCanvas
            graph={graph}
            vscode={vscode}
            storageKey={`factory:${design.flavor}:${design.name}:${levels.map(l => `${l.path}#${l.key}`).join("|")}`}
            onNodeClick={setSelectedPath}
          />
          {selectedDesign && (
            <ActivityDetails
              activity={selectedDesign}
              runs={lab?.run ? allRuns(lab.run).filter(r => r.path === selectedDesign.path) : []}
              onOpenLevel={key => setLevels([...levels, { path: selectedDesign.path, key }])}
              onReveal={() => vscode.postMessage({ type: "revealFactoryActivity", path: design.path, activity: selectedDesign.name })}
            />
          )}
          <ScenarioForm design={design} scenario={scenario} onChange={setScenario} />
          {lab && <RunResult lab={lab} onSelect={path => setSelectedPath(path)} />}
        </>
      )}
      <ProductDifferences />
    </div>
  );
}

function activitiesAt(design: FactoryDesignView | undefined, levels: readonly Level[]): FactoryDesignActivityView[] {
  let current = design?.activities ?? [];
  for (const level of levels) {
    const container = current.find(activity => activity.path === level.path);
    current = container?.children.find(child => child.key === level.key)?.activities ?? [];
  }
  return current;
}

function allRuns(run: FactoryRunView): FactoryActivityRunView[] {
  return [...run.activityRuns, ...run.children.flatMap(allRuns)];
}

function ActivityDetails({
  activity,
  runs,
  onOpenLevel,
  onReveal
}: {
  activity: FactoryDesignActivityView;
  runs: FactoryActivityRunView[];
  onOpenLevel: (key: string) => void;
  onReveal: () => void;
}) {
  const [index, setIndex] = useState(0);
  const shown = runs[Math.min(index, runs.length - 1)];
  return (
    <div className="factory-details">
      <div className="factory-details-head">
        <div>
          <Text weight="semibold">{activity.name}</Text> <code>{activity.type}</code>
          {activity.state === "Inactive" && <Badge appearance="outline">deactivated</Badge>}
          <div className="factory-note">
            {activity.dependsOn.length
              ? `Runs after ${activity.dependsOn.map(d => `${d.activity} (${d.conditions.join(" or ")})`).join(" and ")}`
              : "No dependency: starts with its container"}
          </div>
        </div>
        <div className="button-row">
          {activity.children.map(child => (
            <Button key={child.key} size="small" appearance="secondary" onClick={() => onOpenLevel(child.key)}>
              Open {child.key} ({child.activities.length})
            </Button>
          ))}
          <Button size="small" appearance="secondary" onClick={onReveal}>Show in JSON</Button>
        </div>
      </div>
      {runs.length > 1 && (
        <select aria-label="Activity run" value={index} onChange={event => setIndex(Number(event.target.value))}>
          {runs.map((run, i) => <option key={i} value={i}>{run.iteration ?? `run ${i + 1}`} · {run.status}</option>)}
        </select>
      )}
      {shown ? (
        <div className="factory-io">
          <div>
            <strong>Status</strong>
            <p>
              <Badge appearance="tint" color={STATUS_TONE[shown.status] ?? "informative"}>{shown.status}</Badge>{" "}
              <Badge appearance="outline">{shown.truth === "local" ? "ran locally" : "simulated"}</Badge>{" "}
              {shown.attempts > 1 && <span>{shown.attempts} attempts · </span>}
              {shown.startS}s → {shown.endS}s
            </p>
            {shown.note && <p className="factory-note">{shown.note}</p>}
            {shown.error && <p className="factory-error">{shown.error.code}: {shown.error.message}</p>}
          </div>
          <div><strong>Input</strong><Json value={shown.input} /></div>
          <div><strong>Output</strong><Json value={shown.output} /></div>
        </div>
      ) : (
        <p className="factory-note">Run the pipeline to see this activity's input and output.</p>
      )}
    </div>
  );
}

function ScenarioForm({
  design,
  scenario,
  onChange
}: {
  design: FactoryDesignView;
  scenario: FactoryScenarioInput;
  onChange: (next: FactoryScenarioInput) => void;
}) {
  const work = flattenActivities(design.activities).filter(activity => !isControlActivity(activity.type));
  const setActivity = (activityName: string, patch: Partial<FactoryScenarioInput["activities"][string]>) => {
    const current = scenario.activities[activityName] ?? { behavior: "success" as const };
    onChange({ ...scenario, activities: { ...scenario.activities, [activityName]: { ...current, ...patch } } });
  };
  return (
    <details className="factory-scenario" open>
      <summary>Run settings: parameters, trigger and activity behavior</summary>
      <div className="factory-scenario-grid">
        {design.parameters.map(parameter => (
          <label key={parameter.name}>
            <span>{parameter.name} <small>{parameter.type}</small></span>
            <input
              value={scenario.parameters[parameter.name] ?? ""}
              placeholder={parameter.defaultValue === undefined ? "(no default)" : format(parameter.defaultValue)}
              onChange={event => onChange({ ...scenario, parameters: { ...scenario.parameters, [parameter.name]: event.target.value } })}
            />
          </label>
        ))}
        <label>
          <span>Trigger</span>
          <select value={scenario.triggerType} onChange={event => onChange({ ...scenario, triggerType: event.target.value as FactoryTriggerType })}>
            {TRIGGERS.map(trigger => <option key={trigger} value={trigger}>{trigger}</option>)}
          </select>
        </label>
        <label>
          <span>Trigger time (UTC)</span>
          <input type="datetime-local" value={scenario.now ?? ""} onChange={event => onChange({ ...scenario, now: event.target.value || undefined })} />
        </label>
      </div>
      {work.length > 0 && (
        <table className="factory-scenario-activities">
          <thead>
            <tr><th>Work activity</th><th>Behavior</th><th>Duration (s)</th><th>Output to add (JSON)</th></tr>
          </thead>
          <tbody>
            {work.map(activity => {
              const current = scenario.activities[activity.name];
              return (
                <tr key={activity.path}>
                  <td>{activity.name}<small>{activity.type}</small></td>
                  <td>
                    <select value={current?.behavior ?? "success"} onChange={event => setActivity(activity.name, { behavior: event.target.value as FactoryActivityBehavior })}>
                      {BEHAVIORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      value={current?.durationSeconds ?? ""}
                      placeholder="default"
                      onChange={event => setActivity(activity.name, { durationSeconds: event.target.value === "" ? undefined : Number(event.target.value) })}
                    />
                  </td>
                  <td>
                    <input
                      value={current?.output ?? ""}
                      placeholder={activity.type === "Lookup" ? '{"firstRow": {"n": 3}}' : "optional"}
                      onChange={event => setActivity(activity.name, { output: event.target.value })}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="factory-note">
        On the local lakehouse, Copy, Lookup, Script, stored procedures and notebooks really run on DuckDB and SparkLab;
        a dry run simulates them all and changes no table. Behavior and output apply in both modes.
      </p>
    </details>
  );
}

function RunResult({ lab, onSelect }: { lab: FactoryLabView; onSelect: (path: string) => void }) {
  const run = lab.run;
  return (
    <div className="factory-result">
      <div className="factory-result-head">
        <div>
          <div className="eyebrow">{lab.flavorLabel} · {lab.dataPlane === "local" ? "local lakehouse" : "dry run"}</div>
          <Text size={400} weight="semibold">
            {run ? `Run ${run.status}` : lab.status === "invalid" ? "Pipeline not valid" : "Run not started"}
          </Text>
          {run && <span className="factory-note"> · {run.durationS}s simulated · run {run.runId.slice(0, 8)}</span>}
        </div>
        {run && <Badge appearance="filled" color={STATUS_TONE[run.status] ?? "informative"}>{run.status}</Badge>}
      </div>
      <p className="factory-note">{lab.truth}</p>
      {lab.issues.map((issue, i) => (
        <p key={i} className="factory-error">{issue.path ? `${issue.path}: ` : ""}{issue.message}</p>
      ))}
      {lab.hints.map(hint => <p key={hint} className="factory-hint">{hint}</p>)}
      {lab.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
      {run && (
        <>
          <p className="factory-explanation">{run.explanation}</p>
          <RunTable run={run} onSelect={onSelect} />
          {run.children.map(child => (
            <div key={child.runId} className="factory-child">
              <strong>Child pipeline {child.pipeline}: {child.status}</strong>
              <RunTable run={child} onSelect={() => undefined} />
            </div>
          ))}
          {(Object.keys(run.variables).length > 0 || run.returnValue !== undefined) && (
            <div className="factory-variables">
              {Object.entries(run.variables).map(([key, value]) => <span key={key}><code>{key}</code> = {format(value)}</span>)}
              {run.returnValue !== undefined && <span><code>pipelineReturnValue</code> = {format(run.returnValue)}</span>}
            </div>
          )}
        </>
      )}
      {lab.tablesChanged.length > 0 && (
        <div className="factory-tables">
          <strong>Tables written on the local lakehouse</strong>
          {lab.tablesChanged.map(table => (
            <span key={table.name}><code>{table.name}</code> {table.rows} rows{table.producer ? ` · ${table.producer}` : ""}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function RunTable({ run, onSelect }: { run: FactoryRunView; onSelect: (path: string) => void }) {
  return (
    <table className="factory-runs">
      <thead>
        <tr><th>Activity</th><th>Status</th><th>Where</th><th>Time</th><th>Details</th></tr>
      </thead>
      <tbody>
        {run.activityRuns.map((activity, i) => (
          <tr key={i} onClick={() => onSelect(activity.path)} className={activity.parent ? "is-inner" : ""}>
            <td style={{ paddingLeft: `${6 + activity.path.split("/").length * 10 - 10}px` }}>
              {activity.name}
              <small>{activity.type}{activity.iteration ? ` · ${activity.iteration}` : ""}</small>
            </td>
            <td><Badge appearance="tint" color={STATUS_TONE[activity.status] ?? "informative"}>{activity.status}</Badge></td>
            <td>{activity.truth === "local" ? "local" : "simulated"}</td>
            <td>{activity.startS}s → {activity.endS}s{activity.attempts > 1 ? ` · ${activity.attempts} attempts` : ""}</td>
            <td>{activity.error ? <span className="factory-error">{activity.error.message}</span> : activity.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Json({ value }: { value: unknown }) {
  if (value === undefined || value === null) return <p className="factory-note">none</p>;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className="factory-json">{text.length > 4000 ? `${text.slice(0, 4000)}\n…` : text}</pre>;
}

function format(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

const DIFFERENCES: [string, string, string, string][] = [
  ["Run a notebook", "Notebook (TridentNotebook, notebookId)", "Azure Databricks notebook (notebookPath)", "Synapse notebook (notebook.referenceName)"],
  ["Notebook result", "output.result.exitValue", "output.runOutput", "output.status.Output.result.exitValue"],
  ["Notebook parameters", "Injected after the parameters cell", "Widgets: dbutils.widgets.get", "Injected after the parameters cell"],
  ["Call a pipeline", "Invoke pipeline (legacy Execute pipeline)", "Execute pipeline", "Execute pipeline"],
  ["Low-code transform", "Dataflow Gen2", "Mapping data flow", "Mapping data flow"],
  ["Notify", "Teams and Outlook activities", "Web activity to a webhook / Logic App", "Web activity"],
  ["Stored procedure", "Stored procedure (Warehouse, SQL)", "Stored procedure (Azure SQL)", "SQL pool stored procedure"],
  ["Data access", "Connections, inline dataset settings", "Linked services + datasets", "Linked services + datasets"],
  ["@pipeline().DataFactory", "Workspace name", "Data factory name", "Workspace name"],
  ["Git layout", "<name>.DataPipeline/pipeline-content.json", "pipeline/, dataset/, linkedService/", "pipeline/, dataset/, notebook/, sqlscript/"]
];

function ProductDifferences() {
  return (
    <details className="factory-differences">
      <summary>Fabric, Azure Data Factory and Synapse: what differs</summary>
      <table>
        <thead><tr><th /><th>Fabric Data Factory</th><th>Azure Data Factory</th><th>Synapse pipelines</th></tr></thead>
        <tbody>
          {DIFFERENCES.map(([topic, fabric, adf, synapse]) => (
            <tr key={topic}><th>{topic}</th><td>{fabric}</td><td>{adf}</td><td>{synapse}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="factory-note">
        The orchestration model is the same in the three products: dependency conditions, the leaf rule for the run
        status, retries, containers and the expression language.
      </p>
    </details>
  );
}
