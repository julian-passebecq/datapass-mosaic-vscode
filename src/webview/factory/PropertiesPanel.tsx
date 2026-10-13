import { Badge, Button, Text } from "@fluentui/react-components";
import { useEffect, useState } from "react";
import type { FactoryActivityRunView, FactoryDesignActivityView } from "../contracts";
import { FACTORY_ACTIVITY_TYPES } from "../../platform/factoryActivityTypes";
import { DEPENDENCY_CONDITIONS, type JsonPath, type PipelineIssue, type Scope } from "../../platform/factoryDocument";

type Raw = Record<string, unknown>;

const STATUS_TONE: Record<string, "success" | "danger" | "informative" | "warning"> = {
  Succeeded: "success", Failed: "danger", Skipped: "informative", InProgress: "warning"
};
/** typeProperties keys that hold inner activities: edited as levels of the canvas, not as JSON here. */
const LEVEL_KEYS = new Set(["activities", "ifTrueActivities", "ifFalseActivities", "defaultActivities", "cases"]);

export interface MoveDestination {
  label: string;
  scope: Scope;
}

export interface PropertiesActions {
  rename(name: string): string | undefined;
  set(path: JsonPath, value: unknown): string | undefined;
  connect(from: string, condition: string): string | undefined;
  setConditions(from: string, conditions: string[]): string | undefined;
  remove(): void;
  move(scope: Scope): string | undefined;
  openLevel(key: string): void;
  addCase(value: string): string | undefined;
  reveal(): void;
}

/** The selected activity: its settings (edited in the JSON), its dependencies, and what its last run did. */
export function PropertiesPanel({
  activity,
  view,
  siblings,
  destinations,
  issues,
  runs,
  editsSinceRun,
  actions
}: {
  activity: Raw;
  view: FactoryDesignActivityView;
  siblings: string[];
  destinations: MoveDestination[];
  issues: PipelineIssue[];
  runs: FactoryActivityRunView[];
  editsSinceRun: boolean;
  actions: PropertiesActions;
}) {
  const [message, setMessage] = useState<string>();
  const report = (error: string | undefined) => setMessage(error);
  useEffect(() => setMessage(undefined), [view.path]);
  const spec = FACTORY_ACTIVITY_TYPES.find(type => type.name === view.type);
  const props = asRecord(activity.typeProperties);
  const policy = asRecord(activity.policy);
  const dependencies = list(activity.dependsOn).map(asRecord);
  const keys = [...new Set([...(spec?.required ?? []), ...Object.keys(props)])].filter(key => !LEVEL_KEYS.has(key));
  const setNumber = (path: JsonPath, value: string) => value.trim() === ""
    ? actions.set(path, undefined)
    : Number.isFinite(Number(value)) ? actions.set(path, Number(value)) : `${path[path.length - 1]} must be a number.`;
  const free = siblings.filter(name => !dependencies.some(dependency => dependency.activity === name));

  return (
    <section className="factory-properties" aria-label={`Properties of ${view.name}`}>
      <div className="factory-details-head">
        <div>
          <Text weight="semibold">{view.name}</Text> <code>{view.type}</code>
          {spec && <span className="factory-note"> · {spec.label}</span>}
          {view.state === "Inactive" && <Badge appearance="outline">deactivated</Badge>}
        </div>
        <div className="button-row">
          {view.children.map(child => (
            <Button key={child.key} size="small" appearance="secondary" onClick={() => actions.openLevel(child.key)}>
              Open {child.key} ({child.activities.length})
            </Button>
          ))}
          <Button size="small" appearance="secondary" onClick={actions.reveal}>Show in saved JSON</Button>
          <Button size="small" appearance="secondary" onClick={actions.remove}>Delete activity</Button>
        </div>
      </div>
      {message && <p className="factory-error" role="alert">{message}</p>}
      {issues.map((issue, index) => (
        <p key={index} className={issue.severity === "error" ? "factory-error" : "factory-warning"}>{issue.message}</p>
      ))}

      <div className="factory-properties-grid">
        <TextField label="Name" value={view.name} onCommit={value => report(actions.rename(value))} />
        <TextField
          label="Description"
          value={typeof activity.description === "string" ? activity.description : ""}
          onCommit={value => report(actions.set(["description"], value === "" ? undefined : value))}
        />
        <label>
          <span>State</span>
          <select
            value={view.state === "Inactive" ? "Inactive" : "Active"}
            onChange={event => report(event.target.value === "Inactive"
              ? actions.set(["state"], "Inactive")
              : actions.set(["state"], undefined))}
          >
            <option value="Active">Active</option>
            <option value="Inactive">Inactive (deactivated)</option>
          </select>
        </label>
        {view.state === "Inactive" && (
          <label>
            <span>Mark as</span>
            <select
              value={typeof activity.onInactiveMarkAs === "string" ? activity.onInactiveMarkAs : "Succeeded"}
              onChange={event => report(actions.set(["onInactiveMarkAs"], event.target.value))}
            >
              {["Succeeded", "Failed", "Skipped"].map(value => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        )}
        {spec && !spec.control && (
          <>
            <TextField label="Timeout (d.hh:mm:ss)" value={str(policy.timeout)} onCommit={value => report(actions.set(["policy", "timeout"], value || undefined))} />
            <TextField label="Retry" value={str(policy.retry)} numeric onCommit={value => report(setNumber(["policy", "retry"], value))} />
            <TextField
              label="Retry interval (s)"
              value={str(policy.retryIntervalInSeconds)}
              numeric
              onCommit={value => report(setNumber(["policy", "retryIntervalInSeconds"], value))}
            />
          </>
        )}
      </div>

      <div className="factory-properties-section">
        <strong>Runs after</strong>
        {!dependencies.length && <p className="factory-note">No dependency: starts with its container.</p>}
        {dependencies.map(dependency => {
          const from = String(dependency.activity);
          const conditions = Array.isArray(dependency.dependencyConditions) ? dependency.dependencyConditions.map(String) : ["Succeeded"];
          return (
            <fieldset key={from} className="factory-dependency">
              <legend>{from}</legend>
              {DEPENDENCY_CONDITIONS.map(condition => (
                <label key={condition} className={`cond-${condition.toLowerCase()}`}>
                  <input
                    type="checkbox"
                    checked={conditions.includes(condition)}
                    onChange={event => report(actions.setConditions(from, event.target.checked
                      ? [...conditions, condition]
                      : conditions.filter(item => item !== condition)))}
                  />
                  {condition}
                </label>
              ))}
              <Button size="small" appearance="subtle" onClick={() => report(actions.setConditions(from, []))}>Remove</Button>
            </fieldset>
          );
        })}
        {free.length > 0 && <AddDependency options={free} onAdd={(from, condition) => report(actions.connect(from, condition))} />}
      </div>

      <div className="factory-properties-section">
        <strong>Settings (typeProperties)</strong>
        <p className="factory-note">
          Each value is JSON: text in quotes, numbers and true/false as is, expressions as {'{"value": "@…", "type": "Expression"}'}.
          Settings the editor has no form for stay in the file as written.
        </p>
        {keys.map(key => (
          <JsonField
            key={`${view.path}:${key}`}
            label={key}
            required={spec?.required.includes(key) ?? false}
            present={key in props}
            value={props[key]}
            onCommit={value => report(actions.set(["typeProperties", key], value))}
          />
        ))}
        <AddSetting onAdd={(key, value) => report(actions.set(["typeProperties", key], value))} />
        {view.type === "Switch" && <AddCase onAdd={value => report(actions.addCase(value))} />}
      </div>

      {destinations.length > 0 && (
        <MoveTo destinations={destinations} onMove={scope => report(actions.move(scope))} />
      )}

      <RunDetails runs={runs} editsSinceRun={editsSinceRun} />
    </section>
  );
}

function TextField({ label, value, numeric, onCommit }: { label: string; value: string; numeric?: boolean; onCommit: (value: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onCommit(draft.trim() === "" && numeric ? "" : draft);
  };
  return (
    <label>
      <span>{label}</span>
      <input
        value={draft}
        inputMode={numeric ? "numeric" : undefined}
        onChange={event => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={event => {
          if (event.key === "Enter") commit();
          if (event.key === "Escape") setDraft(value);
        }}
      />
    </label>
  );
}

function JsonField({
  label, required, present, value, onCommit
}: {
  label: string;
  required: boolean;
  present: boolean;
  value: unknown;
  onCommit: (value: unknown) => void;
}) {
  const shown = present ? JSON.stringify(value, null, 2) : "";
  const [draft, setDraft] = useState(shown);
  const [error, setError] = useState<string>();
  useEffect(() => { setDraft(shown); setError(undefined); }, [shown]);
  const apply = () => {
    if (draft.trim() === "") {
      if (present) onCommit(undefined);
      return;
    }
    try {
      onCommit(JSON.parse(draft));
      setError(undefined);
    } catch (problem) {
      setError(`Not JSON: ${problem instanceof Error ? problem.message : String(problem)}`);
    }
  };
  return (
    <div className="factory-json-field">
      <label>
        <span>
          <code>{label}</code>
          {required && <Badge size="small" appearance="outline" color={present ? "informative" : "danger"}>{present ? "required" : "required, missing"}</Badge>}
        </span>
        <textarea
          value={draft}
          rows={Math.min(10, Math.max(1, draft.split("\n").length))}
          spellCheck={false}
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) apply();
          }}
        />
      </label>
      <div className="button-row">
        <Button size="small" appearance="secondary" disabled={draft === shown} onClick={apply} title="Apply (Ctrl+Enter)">Apply</Button>
        {present && !required && <Button size="small" appearance="subtle" onClick={() => onCommit(undefined)}>Remove</Button>}
      </div>
      {error && <p className="factory-error">{error}</p>}
    </div>
  );
}

function AddSetting({ onAdd }: { onAdd: (key: string, value: unknown) => void }) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string>();
  const add = () => {
    if (!key.trim()) return setError("Name the setting.");
    try {
      onAdd(key.trim(), JSON.parse(value || "null"));
      setKey("");
      setValue("");
      setError(undefined);
    } catch (problem) {
      setError(`Not JSON: ${problem instanceof Error ? problem.message : String(problem)}`);
    }
  };
  return (
    <div className="factory-inline-form">
      <input aria-label="New setting name" placeholder="setting" value={key} onChange={event => setKey(event.target.value)} />
      <input aria-label="New setting JSON value" placeholder='JSON value, e.g. "text" or 5' value={value} onChange={event => setValue(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter") add(); }} />
      <Button size="small" appearance="secondary" onClick={add}>Add setting</Button>
      {error && <span className="factory-error">{error}</span>}
    </div>
  );
}

function AddDependency({ options, onAdd }: { options: string[]; onAdd: (from: string, condition: string) => void }) {
  const [from, setFrom] = useState(options[0]);
  const [condition, setCondition] = useState<string>("Succeeded");
  const chosen = options.includes(from) ? from : options[0];
  return (
    <div className="factory-inline-form">
      <select aria-label="Activity to run after" value={chosen} onChange={event => setFrom(event.target.value)}>
        {options.map(name => <option key={name} value={name}>{name}</option>)}
      </select>
      <select aria-label="Dependency condition" value={condition} onChange={event => setCondition(event.target.value)}>
        {DEPENDENCY_CONDITIONS.map(item => <option key={item} value={item}>{item}</option>)}
      </select>
      <Button size="small" appearance="secondary" onClick={() => onAdd(chosen, condition)}>Add dependency</Button>
    </div>
  );
}

function AddCase({ onAdd }: { onAdd: (value: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="factory-inline-form">
      <input aria-label="New case value" placeholder="case value" value={value} onChange={event => setValue(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter") { onAdd(value); setValue(""); } }} />
      <Button size="small" appearance="secondary" onClick={() => { onAdd(value); setValue(""); }}>Add case</Button>
    </div>
  );
}

function MoveTo({ destinations, onMove }: { destinations: MoveDestination[]; onMove: (scope: Scope) => void }) {
  const [index, setIndex] = useState(0);
  const chosen = destinations[Math.min(index, destinations.length - 1)];
  return (
    <div className="factory-properties-section">
      <strong>Move to another level</strong>
      <p className="factory-note">Dependencies only link activities of the same level: moving drops this activity's dependencies and the ones on it.</p>
      <div className="factory-inline-form">
        <select aria-label="Destination level" value={index} onChange={event => setIndex(Number(event.target.value))}>
          {destinations.map((destination, i) => <option key={destination.label} value={i}>{destination.label}</option>)}
        </select>
        <Button size="small" appearance="secondary" onClick={() => onMove(chosen.scope)}>Move</Button>
      </div>
    </div>
  );
}

function RunDetails({ runs, editsSinceRun }: { runs: FactoryActivityRunView[]; editsSinceRun: boolean }) {
  const [index, setIndex] = useState(0);
  const shown = runs[Math.min(index, runs.length - 1)];
  if (!shown) return <p className="factory-note">Run the pipeline to see this activity's status, input and output.</p>;
  return (
    <div className="factory-properties-section">
      <strong>Last run</strong>
      {editsSinceRun && <p className="factory-warning">The run used the saved file; the pipeline was edited since.</p>}
      {runs.length > 1 && (
        <select aria-label="Activity run" value={index} onChange={event => setIndex(Number(event.target.value))}>
          {runs.map((run, i) => <option key={i} value={i}>{run.iteration ?? `run ${i + 1}`} · {run.status}</option>)}
        </select>
      )}
      <div className="factory-io">
        <div>
          <p>
            <Badge appearance="tint" color={STATUS_TONE[shown.status] ?? "informative"}>{shown.status}</Badge>{" "}
            <Badge appearance="outline">{shown.truth === "local" ? "ran locally" : "simulated"}</Badge>{" "}
            {shown.attempts > 1 && <span>{shown.attempts} attempts · </span>}
            {shown.startS}s → {shown.endS}s
          </p>
          {shown.note && <p className="factory-note">{shown.note}</p>}
          {shown.error && (
            <div className="factory-run-error" role="note">
              <strong>{shown.error.code || "Error"}</strong>
              {shown.error.failureType && <small> · {shown.error.failureType}</small>}
              <p>{shown.error.message}</p>
            </div>
          )}
        </div>
        <div><strong>Input</strong><Json value={shown.input} /></div>
        <div><strong>Output</strong><Json value={shown.output} /></div>
      </div>
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  if (value === undefined || value === null) return <p className="factory-note">none</p>;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className="factory-json">{text.length > 4000 ? `${text.slice(0, 4000)}\n…` : text}</pre>;
}

function asRecord(value: unknown): Raw {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Raw : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function str(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}
