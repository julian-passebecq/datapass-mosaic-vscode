import { Badge, Button, Tab, TabList, Text } from "@fluentui/react-components";
import { useMemo, useState } from "react";
import type { BiCheckView, BiDbtCommand, BiDbtView, BiLabView, BiLineageView, BiViewState, RuntimeViewState } from "./contracts";
import { SharedGraphCanvas } from "./SharedGraphCanvas";
import type { VsCodeApi } from "./WorkbenchApp";
import {
  BI_MODEL_FILE,
  DBT_COMMANDS,
  checkCounts,
  dbtGraph,
  columnLineageGraph,
  influenceOf,
  starGraph,
  tableLineageGraph
} from "../platform/biRun";

type BiTab = "warehouse" | "model" | "lineage" | "dbt" | "concepts";

/** BI Lab: a local data warehouse to learn dimensional modeling, SCD, SQL lineage and star models. */
export function BiSurface({ vscode, bi, runtime }: { vscode: VsCodeApi; bi: BiViewState | undefined; runtime: RuntimeViewState }) {
  const lab = runtime.biRun;
  const [tab, setTab] = useState<BiTab>(lab?.model ? "model" : "warehouse");
  const running = runtime.status === "running";
  const run = (mode: "build" | "analyze" | "active") => vscode.postMessage({ type: "runBiLab", mode });

  return (
    <div className="bi-surface">
      <TabList selectedValue={tab} onTabSelect={(_, data) => setTab(data.value as BiTab)} size="small">
        <Tab value="warehouse">Warehouse</Tab>
        <Tab value="model">Star model</Tab>
        <Tab value="lineage">Lineage</Tab>
        <Tab value="dbt">dbt</Tab>
        <Tab value="concepts">Concepts</Tab>
      </TabList>
      {tab !== "concepts" && tab !== "dbt" && (
        !bi?.exists ? (
          <div className="factory-empty">
            <Text weight="semibold">Create the BI Lab files</Text>
            <p>
              The lab builds a small star schema on the local DuckDB catalog: CRM, ERP and shop sources, a date
              dimension, a type 2 customer dimension, a flattened product hierarchy, a junk dimension, and sales and
              returns facts. Then it traces the lineage of every column and checks the star model (keys, grain, SCD2
              validity, relationships). No pipeline, no cloud, no Power BI.
            </p>
            <div className="button-row">
              <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createBiLab" })}>Create lab files</Button>
              <Button appearance="secondary" disabled={!running} onClick={() => run("active")}>Run active .sql</Button>
              <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
                Warehouse exercises
              </Button>
            </div>
          </div>
        ) : (
          <div className="factory-toolbar">
            <div className="button-row">
              <Button size="small" appearance="primary" disabled={!running} onClick={() => run("build")}>Build warehouse</Button>
              <Button size="small" appearance="secondary" disabled={!running} onClick={() => run("analyze")}>Analyze only</Button>
              <Button size="small" appearance="secondary" disabled={!running} onClick={() => run("active")}>Run active .sql</Button>
              <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openBiFile", path: BI_MODEL_FILE })}>
                Open model.json
              </Button>
              <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "createBiLab" })}>Restore sample files</Button>
              <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
                Warehouse exercises
              </Button>
            </div>
          </div>
        )
      )}
      {tab !== "concepts" && tab !== "dbt" && !running && bi?.exists && <p className="factory-note">Start the runtime to build and analyze the warehouse.</p>}
      {tab !== "concepts" && bi?.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
      {tab === "warehouse" && bi?.exists && <WarehouseTab bi={bi} lab={lab} vscode={vscode} />}
      {tab === "model" && bi?.exists && <ModelTab bi={bi} lab={lab} vscode={vscode} />}
      {tab === "lineage" && bi?.exists && <LineageTab lab={lab} vscode={vscode} />}
      {tab === "dbt" && <DbtTab bi={bi} run={runtime.biDbtRun} running={running} vscode={vscode} />}
      {tab === "concepts" && <ConceptsTab vscode={vscode} />}
    </div>
  );
}

function WarehouseTab({ bi, lab, vscode }: { bi: BiViewState; lab: BiLabView | undefined; vscode: VsCodeApi }) {
  const [selected, setSelected] = useState<string>();
  const statement = lab?.statements.find(s => `${s.path}:${s.index}` === selected)
    ?? [...(lab?.statements ?? [])].reverse().find(s => s.status === "error");
  const built = new Set((lab?.lineage.tables ?? []).filter(t => t.kind !== "source").map(t => t.name));
  const roles = new Map((lab?.model?.tables ?? []).map(t => [t.name, t.role]));
  return (
    <div className="bi-grid">
      <div className="bi-panel">
        <Text weight="semibold">Scripts</Text>
        <p className="factory-note">Build runs them in name order on the local catalog, each statement for real on DuckDB.</p>
        <ul className="bi-files">
          {bi.scripts.map(script => (
            <li key={script.path}>
              <button type="button" className="bi-link" onClick={() => vscode.postMessage({ type: "openBiFile", path: script.path })}>
                {script.name}
              </button>
            </li>
          ))}
          <li>
            <button type="button" className="bi-link" onClick={() => vscode.postMessage({ type: "openBiFile", path: BI_MODEL_FILE })}>
              model.json
            </button>
            {bi.modelError ? <small className="factory-error">{bi.modelError}</small> : !bi.modelExists ? <small>not created</small> : null}
          </li>
        </ul>
      </div>
      <div className="bi-panel">
        {!lab ? (
          <p className="factory-note">Build the warehouse to run the scripts and see what each statement did.</p>
        ) : (
          <>
            <div className="factory-result-head">
              <div>
                <div className="eyebrow">{lab.source}</div>
                <Text weight="semibold">
                  {!lab.ran ? "Analyzed without running" : lab.stopped ? `Stopped in ${lab.stopped.path}, line ${lab.stopped.line}`
                    : `${lab.statements.length} statements ran`}
                </Text>
              </div>
              <Badge appearance="filled" color={lab.status === "ok" ? "success" : "danger"}>{lab.status}</Badge>
            </div>
            {lab.truth.sql && <p className="factory-note">{lab.truth.sql}</p>}
            {lab.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
            {lab.statements.length > 0 && (
              <table className="factory-runs">
                <thead><tr><th>Script</th><th>Statement</th><th>Result</th></tr></thead>
                <tbody>
                  {lab.statements.map(s => (
                    <tr key={`${s.path}:${s.index}`} className={statement === s ? "is-selected" : ""} onClick={() => setSelected(`${s.path}:${s.index}`)}>
                      <td>
                        {s.path.split("/").pop()}
                        <button type="button" className="sqlpool-line" title="Show in the script"
                          onClick={() => vscode.postMessage({ type: "revealBiLine", path: s.path, line: s.line })}>
                          L{s.line}
                        </button>
                      </td>
                      <td>{s.kind}{s.target && <small>{s.target}</small>}</td>
                      <td>
                        {s.status === "error" ? <span className="factory-error">{s.message}</span>
                          : s.affected !== undefined ? `${s.affected} row${s.affected === 1 ? "" : "s"}` : "ok"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {statement && statement.columns.length > 0 && statement.rows.length > 0 && (
              <ResultTable columns={statement.columns} rows={statement.rows} />
            )}
          </>
        )}
      </div>
      {lab && lab.tables.length > 0 && (
        <div className="bi-panel bi-wide">
          <Text weight="semibold">Catalog tables</Text>
          <table className="factory-runs">
            <thead><tr><th>Table</th><th>Role</th><th>Rows</th><th>Columns</th></tr></thead>
            <tbody>
              {lab.tables.filter(t => t.layer !== "source" || built.has(t.name)).map(t => (
                <tr key={t.name}>
                  <td>{t.name}{built.has(t.name) ? <small>built by the scripts</small> : null}</td>
                  <td>{roles.get(t.name) ?? ""}</td>
                  <td>{t.rows ?? ""}</td>
                  <td><small>{t.columns.map(c => `${c.name} ${c.type.toLowerCase()}`).join(", ")}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ModelTab({ bi, lab, vscode }: { bi: BiViewState; lab: BiLabView | undefined; vscode: VsCodeApi }) {
  const model = lab?.model;
  const graph = useMemo(() => (model ? starGraph(model) : { nodes: [], edges: [] }), [model]);
  if (bi.modelError || lab?.modelError) {
    return <p className="factory-error">{lab?.modelError ?? bi.modelError}</p>;
  }
  if (!bi.modelExists) {
    return <p className="factory-note">No {BI_MODEL_FILE} yet: restore the sample files or write one (see the Concepts tab).</p>;
  }
  if (!model) {
    return <p className="factory-note">Build or analyze the warehouse to check the star model on the tables.</p>;
  }
  const counts = checkCounts(model.checks);
  const ordered = [...model.checks].sort((a, b) => rank(a) - rank(b));
  return (
    <div className="bi-grid">
      <div className="bi-panel bi-wide">
        <div className="factory-result-head">
          <div>
            <div className="eyebrow">{model.name}</div>
            <Text weight="semibold">{model.description || "Star model"}</Text>
          </div>
          <div className="button-row">
            <Badge appearance="tint" color="success">{counts.pass} pass</Badge>
            <Badge appearance="tint" color={counts.fail ? "danger" : "informative"}>{counts.fail} fail</Badge>
            <Badge appearance="tint" color={counts.warn ? "warning" : "informative"}>{counts.warn} warn</Badge>
          </div>
        </div>
        {lab?.truth.model && <p className="factory-note">{lab.truth.model}</p>}
        <SharedGraphCanvas graph={graph} vscode={vscode} storageKey="bi-star-model" />
        <p className="factory-note">
          Edges read fact → dimension: *:1 is many-to-one; a dashed edge is an inactive relationship (a role-playing
          date used on demand); ⇄ filters in both directions.
        </p>
      </div>
      <div className="bi-panel">
        <Text weight="semibold">Relationships on the data</Text>
        <table className="factory-runs">
          <thead><tr><th>Relationship</th><th>Declared</th><th>Observed</th><th>Orphans</th></tr></thead>
          <tbody>
            {model.relationships.map(r => (
              <tr key={`${r.from}->${r.to}`}>
                <td>{r.from}<small>→ {r.to}</small></td>
                <td>{r.cardinality}<small>{r.crossFilter}{r.active ? "" : ", inactive"}</small></td>
                <td>{r.observed ?? ""}<small>{r.fromRows !== undefined ? `${r.fromRows} rows, ${r.nullKeys ?? 0} NULL keys` : ""}</small></td>
                <td>{r.orphans ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="bi-panel">
        <Text weight="semibold">Checks</Text>
        <table className="factory-runs bi-checks">
          <thead><tr><th>Check</th><th>Subject</th><th>Status</th></tr></thead>
          <tbody>
            {ordered.map((c, index) => (
              <tr key={`${c.check}:${c.subject}:${index}`} className={`bi-check-${c.status}`}>
                <td>{c.check}{c.detail && <small>{c.detail}</small>}</td>
                <td><small>{c.subject}</small></td>
                <td>{c.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function rank(check: BiCheckView): number {
  return check.status === "fail" ? 0 : check.status === "warn" ? 1 : 2;
}

function LineageTab({ lab, vscode }: { lab: BiLabView | undefined; vscode: VsCodeApi }) {
  const lineage = lab?.lineage;
  const built = useMemo(() => (lineage?.tables ?? []).filter(t => t.kind !== "source"), [lineage]);
  const [table, setTable] = useState<string>();
  const [column, setColumn] = useState<string>();
  const [view, setView] = useState<"columns" | "tables">("columns");
  const [impactOf, setImpactOf] = useState<string>();
  if (!lineage) return <p className="factory-note">Build or analyze the warehouse to trace the lineage of its columns.</p>;
  const current = built.find(t => t.name === table)
    ?? [...built].sort((a, b) => b.inputs.length - a.inputs.length)[0];
  const columns = lineage.columns.filter(c => c.table === current?.name);
  const chosen = columns.find(c => c.column === column);
  const allColumns = impactChoices(lineage);
  const impactKey = impactOf ?? allColumns[0];
  const rows = new Map((lab?.tables ?? []).map(t => [t.name, t.rows]));
  return (
    <div className="bi-grid">
      <div className="bi-panel bi-wide">
        <div className="factory-toolbar">
          <div className="factory-flavors" role="tablist" aria-label="Lineage view">
            {(["columns", "tables"] as const).map(item => (
              <button key={item} type="button" role="tab" aria-selected={view === item}
                className={view === item ? "is-active" : ""} onClick={() => setView(item)}>
                {item === "columns" ? "Column lineage" : "Table graph"}
              </button>
            ))}
          </div>
          {view === "columns" && (
            <select aria-label="Table" value={current?.name} onChange={event => { setTable(event.target.value); setColumn(undefined); }}>
              {built.map(t => <option key={t.name} value={t.name}>{t.name}</option>)}
            </select>
          )}
        </div>
        <p className="factory-note">{lineage.truth}</p>
        {lineage.issues.map((issue, index) => (
          <p key={index} className="factory-warning">
            {issue.path}, line {issue.line}: {issue.message}
          </p>
        ))}
        {view === "tables" ? (
          <SharedGraphCanvas graph={tableLineageGraph(lineage, rows)} vscode={vscode} storageKey="bi-table-lineage" />
        ) : current ? (
          <table className="factory-runs">
            <thead><tr><th>Column</th><th>How</th><th>Computed from</th><th>Origins</th></tr></thead>
            <tbody>
              {columns.map(c => (
                <tr key={c.column} className={chosen === c ? "is-selected" : ""} onClick={() => setColumn(c.column)}>
                  <td>{c.column}</td>
                  <td>{c.transform}{c.expression && c.transform !== "copy" && <small><code>{c.expression}</code></small>}</td>
                  <td><small>{c.sources.join(", ") || "no column (typed in or generated)"}</small></td>
                  <td><small>{c.origins.join(", ")}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="factory-note">No table built by the scripts.</p>
        )}
      </div>
      {view === "columns" && current && (
        <div className="bi-panel bi-wide">
          <Text weight="semibold">{chosen ? `${current.name}.${chosen.column}` : "Pick a column in the table above"}</Text>
          <div className="bi-column-detail">
            <div>
              {chosen ? (
                <SharedGraphCanvas graph={columnLineageGraph(lineage, current.name, chosen.column)} vscode={vscode} storageKey="bi-column-lineage" />
              ) : (
                <p className="factory-note">Click a column to see the columns it is computed from, hop by hop, and what depends on it.</p>
              )}
            </div>
            <div className="bi-side">
              {chosen && <ImpactList title="A change to this column reaches" items={lineage.impact[`${current.name}.${chosen.column}`] ?? []} />}
              <strong>Rows of {current.name} are decided by</strong>
              <ul className="bi-files">
                {influenceOf(lineage, current.name).map(i => <li key={`${i.source}:${i.role}`}><code>{i.source}</code> <small>{i.role}</small></li>)}
              </ul>
              {current.statements.map((s, index) => (
                <button key={index} type="button" className="bi-link"
                  onClick={() => vscode.postMessage({ type: "revealBiLine", path: s.path, line: s.line })}>
                  {s.kind} in {s.path}, line {s.line}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
      <div className="bi-panel">
        <Text weight="semibold">Impact analysis</Text>
        <p className="factory-note">What breaks or changes if a column is renamed, retyped or recalculated at the source.</p>
        <select aria-label="Column" value={impactKey} onChange={event => setImpactOf(event.target.value)}>
          {allColumns.map(key => <option key={key} value={key}>{key}</option>)}
        </select>
        {impactKey && <ImpactList title={`A change to ${impactKey} reaches`} items={lineage.impact[impactKey] ?? []} />}
      </div>
    </div>
  );
}

/** Source columns first (where changes come from), then the columns the scripts build. */
function impactChoices(lineage: BiLineageView): string[] {
  const sources = lineage.tables.filter(t => t.kind === "source" || t.inputs.length === 0)
    .flatMap(t => t.columns.map(c => `${t.name}.${c}`));
  const built = lineage.columns.map(c => `${c.table}.${c.column}`);
  return [...new Set([...sources, ...built])].filter(key => key in lineage.impact);
}

function ImpactList({ title, items }: { title: string; items: readonly { table: string; column: string; effect: string }[] }) {
  return (
    <div className="bi-impact">
      <strong>{title}</strong>
      {items.length === 0 ? <p className="factory-note">Nothing downstream in these scripts.</p> : (
        <ul className="bi-files">
          {items.map(i => (
            <li key={`${i.table}.${i.column}`}>
              {i.column === "*" ? <><code>{i.table}</code> <small>rows (a filter, join or grouping uses it)</small></>
                : <><code>{i.table}.{i.column}</code> <small>value</small></>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ResultTable({ columns, rows }: { columns: readonly string[]; rows: readonly Record<string, string | number | boolean | null>[] }) {
  return (
    <div className="retail-preview-wrap">
      <table className="retail-preview">
        <thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.slice(0, 50).map((row, index) => (
            <tr key={index}>{columns.map(column => <td key={column}>{row[column] === null ? "NULL" : String(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DBT_BADGE: Record<string, "success" | "danger" | "warning" | "informative"> = {
  success: "success", pass: "success", warn: "warning", fail: "danger", error: "danger", skipped: "informative"
};

function DbtTab({ bi, run, running, vscode }: { bi: BiViewState | undefined; run: BiDbtView | undefined; running: boolean; vscode: VsCodeApi }) {
  const [command, setCommand] = useState<BiDbtCommand>(run?.command === "parse" || !run ? "build" : run.command);
  const [select, setSelect] = useState(run?.select ?? "");
  const [fullRefresh, setFullRefresh] = useState(false);
  const [withTests, setWithTests] = useState(false);
  const [chosen, setChosen] = useState<string>();
  const graph = useMemo(() => (run ? dbtGraph(run, withTests) : { nodes: [], edges: [] }), [run, withTests]);
  const send = (next: BiDbtCommand) => vscode.postMessage({ type: "runBiDbt", command: next, select, fullRefresh });
  if (!bi?.dbtExists) {
    return (
      <div className="factory-empty">
        <Text weight="semibold">Create the BI Lab files</Text>
        <p>
          <code>bi/dbt/</code> holds the same warehouse built the dbt way: sources, staging views, an ephemeral
          intermediate model, the star in marts (with an incremental fact), a snapshot of product prices, tests and
          macros. The Datapass dbt emulation runs it on the local catalog: no dbt install needed.
        </p>
        <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createBiLab" })}>Create lab files</Button>
      </div>
    );
  }
  const node = run?.nodes.find(n => n.uniqueId === chosen);
  const result = run?.results.find(r => r.uniqueId === chosen);
  const columns = node?.relation ? run?.lineage?.columns.filter(c => c.table === node.relation) ?? [] : [];
  return (
    <div className="bi-grid">
      <div className="bi-panel bi-wide">
        <div className="factory-toolbar">
          <div className="button-row">
            <select aria-label="dbt command" value={command} onChange={event => setCommand(event.target.value as BiDbtCommand)}>
              {DBT_COMMANDS.map(item => <option key={item} value={item}>dbt {item}</option>)}
            </select>
            <input className="bi-select" aria-label="Selection" placeholder="--select, e.g. +fct_sales tag:daily"
              value={select} onChange={event => setSelect(event.target.value)} />
            <label className="bi-check">
              <input type="checkbox" checked={fullRefresh} onChange={event => setFullRefresh(event.target.checked)} /> --full-refresh
            </label>
            <Button size="small" appearance="primary" disabled={!running} onClick={() => send(command)}>Run</Button>
            <Button size="small" appearance="secondary" disabled={!running} onClick={() => send("parse")}>Parse only</Button>
            <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openBiFile", path: "bi/dbt/dbt_project.yml" })}>
              Open dbt_project.yml
            </Button>
            <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
              dbt exercises
            </Button>
          </div>
        </div>
        <p className="factory-note">
          {run?.truth ?? "Datapass dbt emulation: Jinja in a sandbox, SQL on DuckDB, dbt Core semantics for a documented subset; not dbt Core."}
          {" "}The sources are the tables of <code>bi/warehouse/00_sources.sql</code>: build the warehouse first.
        </p>
        {!running && <p className="factory-note">Start the runtime to run dbt.</p>}
        {run?.warnings.map(w => <p key={w} className="factory-warning">{w}</p>)}
        {run?.error && <p className="factory-error">{run.error}</p>}
        {run?.issues.map((issue, index) => <p key={index} className="factory-warning">{issue.path}: {issue.message}</p>)}
        {run && (
          <>
            <div className="factory-result-head">
              <div>
                <div className="eyebrow">
                  {run.projectName} · dbt {run.command}{run.select ? ` --select ${run.select}` : ""}{run.now ? ` · ${run.now}` : ""}
                </div>
                <Text weight="semibold">{run.status === "parsed" ? `${run.nodes.length} nodes parsed` : `${run.results.length} nodes ran`}</Text>
              </div>
              <div className="button-row">
                {Object.entries(run.counts ?? {}).filter(([, n]) => n).map(([status, n]) => (
                  <Badge key={status} appearance="tint" color={DBT_BADGE[status] ?? "informative"}>{n} {status}</Badge>
                ))}
                <label className="bi-check">
                  <input type="checkbox" checked={withTests} onChange={event => setWithTests(event.target.checked)} /> tests in the graph
                </label>
              </div>
            </div>
            <SharedGraphCanvas graph={graph} vscode={vscode} storageKey={withTests ? "bi-dbt-dag-tests" : "bi-dbt-dag"}
              onNodeClick={id => setChosen(id)} />
          </>
        )}
      </div>
      {run && run.results.length > 0 && (
        <div className="bi-panel">
          <Text weight="semibold">Results</Text>
          <table className="factory-runs">
            <thead><tr><th>Node</th><th>Status</th><th>Rows / failures</th></tr></thead>
            <tbody>
              {run.results.map(r => (
                <tr key={r.uniqueId} className={chosen === r.uniqueId ? "is-selected" : ""} onClick={() => setChosen(r.uniqueId)}>
                  <td>{r.name}<small>{r.resourceType}{r.materialized && r.resourceType === "model" ? ` · ${r.materialized}` : ""}</small></td>
                  <td className={`bi-dbt-${r.status}`}>{r.status}</td>
                  <td>
                    {r.resourceType === "test" ? (r.failures ?? "") : (r.rowsAffected ?? "")}
                    {r.status === "error" || r.status === "skipped" ? <small>{r.message}</small> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {node && (
        <div className="bi-panel">
          <Text weight="semibold">{node.name}</Text>
          <p className="factory-note">
            {node.resourceType}{node.relation ? ` → ${node.relation}` : ""}{node.tags.length ? ` · tags ${node.tags.join(", ")}` : ""}
          </p>
          {node.description && <p>{node.description}</p>}
          {node.problem && <p className="factory-error">{node.problem}</p>}
          {result?.message && <p className={result.status === "error" ? "factory-error" : "factory-note"}>{result.message}</p>}
          <button type="button" className="bi-link" onClick={() => vscode.postMessage({ type: "openBiFile", path: `bi/dbt/${node.path}` })}>
            Open {node.path}
          </button>
          {result && result.failingRows.length > 0 && (
            <ResultTable columns={Object.keys(result.failingRows[0])} rows={result.failingRows} />
          )}
          {columns.length > 0 && (
            <table className="factory-runs">
              <thead><tr><th>Column</th><th>How</th><th>Origins</th></tr></thead>
              <tbody>
                {columns.map(c => (
                  <tr key={c.column}><td>{c.column}</td><td>{c.transform}</td><td><small>{c.origins.join(", ")}</small></td></tr>
                ))}
              </tbody>
            </table>
          )}
          {result?.compiled && (
            <details className="sqlpool-sql" open={node.resourceType === "test"}>
              <summary>Compiled SQL</summary>
              <pre className="factory-json">{result.compiled}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

interface Concept {
  name: string;
  what: string;
  exercises?: string[];
}

const EXERCISE_LANGUAGE: Record<string, string> = { "bi-model-relationships": "bi-model", "bi-model-bridge": "bi-model" };

const SCD_TYPES: { type: string; change: string; history: string; use: string; exercises?: string[] }[] = [
  { type: "0", change: "Keep the original value", history: "None: the value never changes", use: "Original values: birth date, first signup channel" },
  { type: "1", change: "Overwrite in place (same surrogate key)", history: "None", use: "Corrections and contact data", exercises: ["dwh-scd1-overwrite"] },
  { type: "2", change: "Close the current row, add a row (new surrogate key) with valid_from / valid_to / is_current", history: "Full",
    use: "What analysts slice history by: city, segment, territory", exercises: ["dwh-scd2-apply", "dwh-point-in-time"] },
  { type: "3", change: "Move the current value to a previous_* column", history: "One step", use: "Before / after a reorganisation", exercises: ["dwh-scd3-previous-value"] },
  { type: "4", change: "Keep fast-changing attributes in a separate mini-dimension (or a history table)", history: "Full, apart",
    use: "Attributes that change often: age band, credit score" },
  { type: "6", change: "Type 2 rows plus current-value columns updated on every version (1 + 2 + 3)", history: "Full, and today's value on each row",
    use: "History and today's value side by side", exercises: ["dwh-scd2-type1-attribute"] }
];

const CONCEPTS: { title: string; items: Concept[] }[] = [
  {
    title: "Designing a star (Kimball's four steps)",
    items: [
      { name: "1. Business process", what: "Model one measurable process at a time: sales, returns, inventory, fulfillment." },
      { name: "2. Grain", what: "Say what one fact row is before anything else (one order line). Every measure must be true at that grain.", exercises: ["dwh-grain-allocation"] },
      { name: "3. Dimensions", what: "The who, what, where, when that describe each event: customer, product, store, date." },
      { name: "4. Facts", what: "The numeric measures of the event at that grain: quantity, net amount, cost." }
    ]
  },
  {
    title: "Fact tables",
    items: [
      { name: "Transaction", what: "One row per event (an order line). Measures are usually additive.", exercises: ["dwh-grain-allocation"] },
      { name: "Periodic snapshot", what: "One row per entity and period, even when nothing happened (stock, balance). Measures are semi-additive.", exercises: ["dwh-periodic-snapshot"] },
      { name: "Accumulating snapshot", what: "One row per process instance, updated at each milestone (ordered, shipped, delivered), with lags.", exercises: ["dwh-accumulating-snapshot"] },
      { name: "Factless fact", what: "Records that something happened or was eligible, with no measure (promotion coverage, attendance). Answers 'what did not happen'.", exercises: ["dwh-factless-coverage"] }
    ]
  },
  {
    title: "Keys and members",
    items: [
      { name: "Business (natural) key", what: "The source's identifier (customer_id). It identifies the entity, not the version." },
      { name: "Surrogate key", what: "A meaningless integer owned by the warehouse, one per dimension row (per version in type 2). Facts store it.", exercises: ["dwh-surrogate-unknown"] },
      { name: "Smart date key", what: "yyyymmdd integers for the date dimension: readable, sortable, and stable.", exercises: ["dwh-date-dimension"] },
      { name: "Degenerate dimension", what: "An identifier kept on the fact with no dimension table of its own (order_id)." },
      { name: "Unknown member", what: "A -1 row facts point to when a reference is missing, so no fact disappears from a report.", exercises: ["dwh-surrogate-unknown"] },
      { name: "Inferred member", what: "A placeholder row with the real business key for a dimension that arrives late; completed in place later.", exercises: ["dwh-late-arriving-dimension"] }
    ]
  },
  {
    title: "Dimension patterns",
    items: [
      { name: "Conformed dimension", what: "The same dimension (same keys and values) shared by several facts, so they can be compared: drill across.", exercises: ["dwh-drill-across"] },
      { name: "Role-playing dimension", what: "One dimension used several times by a fact (order date, ship date): one active relationship, the others inactive.", exercises: ["bi-model-relationships"] },
      { name: "Junk dimension", what: "Low-cardinality flags grouped in one small table of their combinations.", exercises: ["dwh-junk-dimension"] },
      { name: "Star vs snowflake", what: "Flatten hierarchies into one dimension table (star) instead of normalizing them (snowflake).", exercises: ["dwh-snowflake-flatten"] },
      { name: "Bridge table", what: "Resolves a many-to-many (joint accounts, several holders) with an allocation factor so totals stay right.", exercises: ["dwh-bridge-allocation", "bi-model-bridge"] }
    ]
  },
  {
    title: "Measures",
    items: [
      { name: "Additive", what: "Can be summed along every dimension: quantity, net amount." },
      { name: "Semi-additive", what: "Can be summed across entities but not across time: stock, account balance. Use the last or the average over time.", exercises: ["dwh-periodic-snapshot"] },
      { name: "Non-additive", what: "Ratios, percentages, averages: never sum them; recompute from additive parts (SUM(margin) / SUM(sales))." }
    ]
  },
  {
    title: "Lineage and governance",
    items: [
      { name: "Column lineage", what: "Which source columns each column is computed from, through every CTE, join and staging table.", exercises: ["dwh-lineage-governed-revenue"] },
      { name: "Impact analysis", what: "What a change to a source column reaches: values computed from it, and tables whose rows it filters or joins." },
      { name: "Sensitive data", what: "Masking or deriving a personal field still carries its lineage: check the outputs, not the intentions.", exercises: ["dwh-lineage-personal-data"] }
    ]
  }
];

function ConceptsTab({ vscode }: { vscode: VsCodeApi }) {
  const open = (id: string) => vscode.postMessage({
    type: "openExercise", exerciseKey: `dwh-v1/${id}/${EXERCISE_LANGUAGE[id] ?? "warehouse"}`
  });
  const links = (ids?: string[]) => ids?.map(id => (
    <button key={id} type="button" className="bi-link bi-exercise" onClick={() => open(id)}>{id}</button>
  ));
  return (
    <div className="bi-concepts">
      <p className="factory-note">
        A data warehousing cheat sheet. Each exercise opens in Practice and is graded on an isolated DuckDB catalog.
      </p>
      <div className="bi-panel bi-wide">
        <Text weight="semibold">Slowly changing dimensions</Text>
        <table className="factory-runs bi-static">
          <thead><tr><th>Type</th><th>On change</th><th>History</th><th>Use it for</th><th>Practice</th></tr></thead>
          <tbody>
            {SCD_TYPES.map(row => (
              <tr key={row.type}>
                <td>{row.type}</td><td>{row.change}</td><td>{row.history}</td><td>{row.use}</td><td>{links(row.exercises)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {CONCEPTS.map(group => (
        <div key={group.title} className="bi-panel">
          <Text weight="semibold">{group.title}</Text>
          <dl className="bi-terms">
            {group.items.map(item => (
              <div key={item.name}>
                <dt>{item.name}</dt>
                <dd>{item.what} {links(item.exercises)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
