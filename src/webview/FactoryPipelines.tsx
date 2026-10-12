import { Badge, Button, Text } from "@fluentui/react-components";
import { useMemo, useState, type KeyboardEvent } from "react";
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
import { designView, factoryGraph, flattenActivities, isControlActivity } from "../platform/factoryRun";
import {
  addActivity,
  addSwitchCase,
  connectActivities,
  defaultActivityName,
  deleteActivities,
  disconnectActivities,
  moveActivity,
  newActivity,
  parsePipeline,
  renameActivity,
  sameScope,
  scopePath,
  setActivityProperty,
  setDependencyConditions,
  validatePipeline,
  DEPENDENCY_CONDITIONS,
  type EditResult,
  type Scope
} from "../platform/factoryDocument";
import { EditorToolbar } from "./factory/EditorToolbar";
import { Palette } from "./factory/Palette";
import { PropertiesPanel, type MoveDestination } from "./factory/PropertiesPanel";
import { useFactoryEditor } from "./factory/useFactoryEditor";
import "./factory/factoryEditor.css";

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

type Raw = Record<string, unknown>;

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
  const [selectedEdge, setSelectedEdge] = useState<string>();
  const [connectCondition, setConnectCondition] = useState<string>("Succeeded");
  const [message, setMessage] = useState<string>();

  const available = pipelines.filter(pipeline => pipeline.flavor === flavor);
  const design = available.find(pipeline => pipeline.name === name) ?? available[0];
  const editor = useFactoryEditor(design && !design.error ? design : undefined);
  const lab = runtime.factoryRun && design && runtime.factoryRun.flavor === design.flavor &&
    runtime.factoryRun.pipelineName === design.name ? runtime.factoryRun : undefined;
  // The canvas shows the edited text; runs and run settings use the saved file.
  const edited = useMemo(
    () => design && editor ? designView(design.flavor, design.name, design.path, editor.text) : design,
    [design, editor?.text]
  );
  const value = useMemo(() => editor ? parsePipeline(editor.text).value : undefined, [editor?.text]);
  const issues = useMemo(() => value && design ? validatePipeline(value, design.flavor) : [], [value, design?.flavor]);
  const errorCount = issues.filter(issue => issue.severity === "error").length;
  const scope: Scope = levels.map(level => ({ activity: level.path.split("/").pop() ?? "", key: level.key }));
  const prefix = levels.length ? `${levels[levels.length - 1].path}/` : "";
  const levelActivities = useMemo(() => activitiesAt(edited, levels), [edited, levels]);
  const graph = useMemo(() => factoryGraph(levelActivities, lab?.run), [levelActivities, lab?.run]);
  const selectedDesign = edited ? flattenActivities(edited.activities).find(activity => activity.path === selectedPath) : undefined;

  const choosePipeline = (nextFlavor: FactoryFlavor, nextName?: string) => {
    setFlavor(nextFlavor);
    setName(nextName);
    setLevels([]);
    setSelectedPath(undefined);
    setSelectedEdge(undefined);
    setMessage(undefined);
    setScenario(current => ({ ...current, parameters: {}, activities: {} }));
  };
  const run = (dataPlane: FactoryScenarioInput["dataPlane"]) => {
    if (!design) return;
    const next = { ...scenario, dataPlane };
    setScenario(next);
    vscode.postMessage({ type: "simulateFactory", flavor: design.flavor, name: design.name, scenario: next });
  };
  /** Apply an edit; an error is shown and nothing changes. */
  const apply = (result: EditResult): string | undefined => {
    if (!editor) return "The pipeline cannot be edited.";
    const error = editor.apply(result);
    setMessage(error);
    return error;
  };
  const save = () => {
    if (!design || !editor?.dirty) return;
    vscode.postMessage({ type: "saveFactoryPipeline", path: design.path, text: editor.text, baseHash: editor.baseHash });
  };
  const select = (path: string | undefined) => {
    setSelectedEdge(undefined);
    setSelectedPath(path);
    if (path && edited) {
      const found = levelsFor(edited.activities, path, []);
      if (found) setLevels(found);
    }
  };
  const addOfType = (type: string): string | undefined => {
    if (!editor || !value) return undefined;
    const activityName = defaultActivityName(type, value);
    if (apply(addActivity(editor.text, scope, newActivity(type, activityName)))) return undefined;
    setSelectedEdge(undefined);
    setSelectedPath(prefix + activityName);
    return prefix + activityName;
  };
  const leaf = (id: string) => id.slice(prefix.length);
  const edgeEnds = (id: string) => {
    const edge = graph.edges.find(item => item.id === id);
    return edge ? { from: leaf(edge.source), to: leaf(edge.target) } : undefined;
  };
  const chain = (steps: ((text: string) => EditResult)[]): EditResult => {
    let text = editor?.text ?? "";
    for (const step of steps) {
      const result = step(text);
      if (result.error !== undefined) return result;
      text = result.text;
    }
    return { text };
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!editor || !(event.ctrlKey || event.metaKey)) return;
    const target = event.target as HTMLElement;
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
    const key = event.key.toLowerCase();
    if (key === "s") { event.preventDefault(); save(); }
    else if (!typing && key === "z" && !event.shiftKey) { event.preventDefault(); editor.undo(); }
    else if (!typing && (key === "y" || (key === "z" && event.shiftKey))) { event.preventDefault(); editor.redo(); }
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
        <div className="button-row">
          <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>Create lab files</Button>
          <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
            Pipeline exercises
          </Button>
        </div>
      </div>
    );
  }

  const selectedRaw = selectedDesign && value ? activityRaw(value, selectedDesign, edited!) : undefined;
  const selectedScope = selectedDesign ? scopeOf(selectedDesign.path, edited!) : undefined;
  const selectedLeaf = selectedDesign?.name ?? "";
  const runsOf = (path: string) => lab?.run ? allRuns(lab.run).filter(r => r.path === path) : [];
  const edgeSelected = selectedEdge ? edgeEnds(selectedEdge) : undefined;

  return (
    <div className="factory-pipelines" onKeyDown={onKeyDown}>
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
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "createFactoryPipeline", flavor })}>
            New pipeline
          </Button>
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "importFactoryPipeline", flavor })}>
            Import JSON…
          </Button>
          {design && (
            <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openFactoryFile", path: design.path })}>
              Open JSON
            </Button>
          )}
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>
            Restore sample files
          </Button>
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
            Pipeline exercises
          </Button>
          <Button size="small" appearance="secondary" disabled={!running || !design || !!design.error || editor?.dirty} onClick={() => run("simulated")}>
            Dry run
          </Button>
          <Button size="small" appearance="primary" disabled={!running || !design || !!design.error || editor?.dirty} onClick={() => run("local")}>
            Run on local lakehouse
          </Button>
        </div>
      </div>
      {!running && <p className="factory-note">Start the runtime to run pipelines. The canvas below is read from the files.</p>}
      {editor?.dirty && <p className="factory-note">A run uses the file as saved: save the pipeline to run your edits.</p>}
      {factory.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}

      {!design ? (
        <p className="factory-note">No {FLAVORS.find(f => f.id === flavor)?.label} pipeline in <code>factory/</code> yet.</p>
      ) : design.error || !edited || !editor ? (
        <p className="factory-error">{design.path}: {design.error ?? "the file could not be read"}</p>
      ) : (
        <>
          {edited.description && <p className="factory-description">{edited.description}</p>}
          <EditorToolbar
            dirty={editor.dirty}
            diskChanged={editor.diskChanged}
            canUndo={editor.canUndo}
            canRedo={editor.canRedo}
            errorCount={errorCount}
            connectCondition={connectCondition}
            onConnectCondition={setConnectCondition}
            onSave={save}
            onUndo={editor.undo}
            onRedo={editor.redo}
            onRevert={() => { editor.reload(); setMessage(undefined); }}
            onExport={() => vscode.postMessage({ type: "exportFactoryPipeline", path: design.path, text: editor.text })}
          />
          {editor.diskChanged && (
            <p className="factory-warning" role="alert">
              {design.path} changed on disk while you were editing.{" "}
              <button type="button" className="factory-link" onClick={editor.reload}>Reload from disk</button> drops your edits;
              saving asks before overwriting the new version.
            </p>
          )}
          {message && <p className="factory-error" role="alert">{message}</p>}
          {issues.length > 0 && (
            <details className="factory-issues" open={errorCount > 0}>
              <summary>{errorCount} error{errorCount === 1 ? "" : "s"}, {issues.length - errorCount} warning{issues.length - errorCount === 1 ? "" : "s"} in this pipeline</summary>
              <ul>
                {issues.map((issue, index) => (
                  <li key={index} className={issue.severity === "error" ? "factory-error" : "factory-warning"}>
                    {issue.path
                      ? <button type="button" className="factory-link" onClick={() => select(issue.path)}>{issue.path}</button>
                      : <span>pipeline</span>}
                    {": "}{issue.message}
                  </li>
                ))}
              </ul>
            </details>
          )}
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
          <div className="factory-editor">
            <Palette flavor={design.flavor} onAdd={addOfType} />
            <SharedGraphCanvas
              graph={graph}
              vscode={vscode}
              storageKey={`factory:${design.flavor}:${design.name}:${levels.map(l => `${l.path}#${l.key}`).join("|")}`}
              onNodeClick={id => { setSelectedEdge(undefined); setSelectedPath(id); }}
              editable
              selectedNodeId={selectedEdge ? "" : selectedPath ?? ""}
              selectedEdgeId={selectedEdge ?? ""}
              onEdgeClick={id => { setSelectedEdge(id); setSelectedPath(undefined); }}
              onConnect={(source, target) => apply(connectActivities(editor.text, scope, leaf(source), leaf(target), connectCondition))}
              onDeleteNodes={ids => {
                if (!apply(deleteActivities(editor.text, scope, ids.map(leaf)))) setSelectedPath(undefined);
              }}
              onDeleteEdges={ids => {
                const ends = ids.map(edgeEnds).filter((end): end is { from: string; to: string } => !!end);
                if (!apply(chain(ends.map(end => text => disconnectActivities(text, scope, end.from, end.to))))) setSelectedEdge(undefined);
              }}
              onDrop={type => addOfType(type)}
            />
          </div>
          {edgeSelected && (
            <EdgePanel
              from={edgeSelected.from}
              to={edgeSelected.to}
              conditions={dependencyConditions(levelActivities, edgeSelected.from, prefix + edgeSelected.to)}
              onConditions={conditions => {
                if (!apply(setDependencyConditions(editor.text, scope, edgeSelected.from, edgeSelected.to, conditions)) && !conditions.length) {
                  setSelectedEdge(undefined);
                }
              }}
            />
          )}
          {selectedDesign && selectedRaw && selectedScope && (
            <PropertiesPanel
              activity={selectedRaw}
              view={selectedDesign}
              siblings={siblingsOf(edited, selectedDesign)}
              destinations={destinations(edited, selectedDesign, selectedScope)}
              issues={issues.filter(issue => issue.path === selectedDesign.path)}
              runs={runsOf(selectedDesign.path)}
              editsSinceRun={!!lab?.run && editor.dirty}
              actions={{
                rename: next => {
                  const error = apply(renameActivity(editor.text, selectedScope, selectedLeaf, next));
                  if (!error) {
                    const old = selectedDesign.path;
                    const renamed = old.slice(0, old.length - selectedLeaf.length) + next;
                    setSelectedPath(renamed);
                    setLevels(levels.map(level => level.path === old || level.path.startsWith(`${old}/`)
                      ? { ...level, path: renamed + level.path.slice(old.length) } : level));
                  }
                  return error;
                },
                set: (path, next) => apply(setActivityProperty(editor.text, selectedScope, selectedLeaf, path, next)),
                connect: (from, condition) => apply(connectActivities(editor.text, selectedScope, from, selectedLeaf, condition)),
                setConditions: (from, conditions) => apply(setDependencyConditions(editor.text, selectedScope, from, selectedLeaf, conditions)),
                remove: () => {
                  if (!apply(deleteActivities(editor.text, selectedScope, [selectedLeaf]))) setSelectedPath(undefined);
                },
                move: target => {
                  const error = apply(moveActivity(editor.text, selectedScope, selectedLeaf, target));
                  if (!error) {
                    const targetPrefix = target.length ? `${levelPath(target)}/` : "";
                    setLevels(levelsOfScope(target));
                    setSelectedPath(targetPrefix + selectedLeaf);
                  }
                  return error;
                },
                openLevel: key => setLevels([...levelsOfScope(selectedScope), { path: selectedDesign.path, key }]),
                addCase: caseValue => apply(addSwitchCase(editor.text, selectedScope, selectedLeaf, caseValue)),
                reveal: () => vscode.postMessage({ type: "revealFactoryActivity", path: design.path, activity: selectedLeaf })
              }}
            />
          )}
          <ScenarioForm design={design} scenario={scenario} onChange={setScenario} />
          {lab && <RunResult lab={lab} onSelect={select} />}
        </>
      )}
      <ProductDifferences />
    </div>
  );
}

/** The selected dependency: its conditions, editable with the keyboard. */
function EdgePanel({
  from,
  to,
  conditions,
  onConditions
}: {
  from: string;
  to: string;
  conditions: string[];
  onConditions: (conditions: string[]) => void;
}) {
  return (
    <section className="factory-properties" aria-label={`Dependency ${from} to ${to}`}>
      <Text weight="semibold">{to} runs after {from} ends with</Text>
      <fieldset className="factory-dependency">
        <legend>Conditions (any of them)</legend>
        {DEPENDENCY_CONDITIONS.map(condition => (
          <label key={condition} className={`cond-${condition.toLowerCase()}`}>
            <input
              type="checkbox"
              checked={conditions.includes(condition)}
              onChange={event => onConditions(event.target.checked ? [...conditions, condition] : conditions.filter(item => item !== condition))}
            />
            {condition}
          </label>
        ))}
        <Button size="small" appearance="subtle" onClick={() => onConditions([])}>Remove dependency</Button>
      </fieldset>
      <p className="factory-note">Completed means Succeeded or Failed. Press Delete on the canvas to remove the selected dependency.</p>
    </section>
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

/** The drill-down levels that show the activity at `path`. */
function levelsFor(activities: readonly FactoryDesignActivityView[], path: string, trail: Level[]): Level[] | undefined {
  for (const activity of activities) {
    if (activity.path === path) return trail;
    for (const child of activity.children) {
      const found = levelsFor(child.activities, path, [...trail, { path: activity.path, key: child.key }]);
      if (found) return found;
    }
  }
  return undefined;
}

function scopeOf(path: string, design: FactoryDesignView): Scope {
  return (levelsFor(design.activities, path, []) ?? []).map(level => ({ activity: level.path.split("/").pop() ?? "", key: level.key }));
}

function levelsOfScope(scope: Scope): Level[] {
  return scope.map((step, index) => ({ path: scope.slice(0, index + 1).map(item => item.activity).join("/"), key: step.key }));
}

function levelPath(scope: Scope): string {
  return scope.map(step => step.activity).join("/");
}

function activityRaw(value: Raw, activity: FactoryDesignActivityView, design: FactoryDesignView): Raw | undefined {
  const path = scopePath(value, scopeOf(activity.path, design));
  let current: unknown = value;
  for (const step of path ?? []) current = (current as Record<string | number, unknown> | undefined)?.[step];
  const found = Array.isArray(current) ? current.find(item => item && typeof item === "object" && (item as Raw).name === activity.name) : undefined;
  return found as Raw | undefined;
}

function siblingsOf(design: FactoryDesignView, activity: FactoryDesignActivityView): string[] {
  const levels = levelsFor(design.activities, activity.path, []) ?? [];
  return activitiesAt(design, levels).map(item => item.name).filter(item => item !== activity.name);
}

function dependencyConditions(activities: readonly FactoryDesignActivityView[], from: string, targetPath: string): string[] {
  return activities.find(activity => activity.path === targetPath)?.dependsOn.find(dependency => dependency.activity === from)?.conditions ?? [];
}

/** Every level the activity can move to: the top level and each container branch, except its own and its insides. */
function destinations(design: FactoryDesignView, activity: FactoryDesignActivityView, current: Scope): MoveDestination[] {
  const found: MoveDestination[] = [{ label: `${design.name} (top level)`, scope: [] }];
  const walk = (activities: readonly FactoryDesignActivityView[], scope: Scope) => {
    for (const item of activities) {
      if (item.path === activity.path) continue;
      for (const child of item.children) {
        const inner = [...scope, { activity: item.name, key: child.key }];
        found.push({ label: `${item.path} › ${child.key}`, scope: inner });
        walk(child.activities, inner);
      }
    }
  };
  walk(design.activities, []);
  return found.filter(destination => !sameScope(destination.scope, current));
}

function allRuns(run: FactoryRunView): FactoryActivityRunView[] {
  return [...run.activityRuns, ...run.children.flatMap(allRuns)];
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
