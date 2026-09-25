import { Badge, Button, Text } from "@fluentui/react-components";
import { useMemo, useState } from "react";
import type { DbtViewState, RuntimeViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { SharedGraphCanvas } from "./SharedGraphCanvas";
import { countsLine, dbtCoreGraph, type DbtCoreNodeView } from "../platform/dbtArtifacts";
import {
  DBT_COMMANDS,
  buildDbtCommand,
  supportsFullRefresh,
  supportsSelection,
  type DbtCommand
} from "../platform/dbtTools";

const STATUS_BADGE: Record<string, "success" | "danger" | "warning" | "informative" | "subtle"> = {
  success: "success", pass: "success", error: "danger", "runtime error": "danger", fail: "danger", warn: "warning",
  skipped: "subtle", "no-op": "subtle"
};

export function DbtSurface({
  vscode,
  dbt,
  runtime
}: {
  vscode: VsCodeApi;
  dbt: DbtViewState | undefined;
  runtime: RuntimeViewState;
}) {
  const [command, setCommand] = useState<DbtCommand>("build");
  const [select, setSelect] = useState("");
  const [exclude, setExclude] = useState("");
  const [fullRefresh, setFullRefresh] = useState(false);
  const [withTests, setWithTests] = useState(false);
  const [chosen, setChosen] = useState<string>();
  const run = dbt?.run;
  const graph = useMemo(() => (run ? dbtCoreGraph(run, withTests) : { nodes: [], edges: [] }), [run, withTests]);
  if (!dbt) return <div className="empty-state">dbt Lab state is not available.</div>;

  let preview = "";
  let previewError: string | undefined;
  try {
    preview = buildDbtCommand({ command, select, exclude, fullRefresh });
  } catch (error) {
    previewError = error instanceof Error ? error.message : String(error);
  }
  const ready = dbt.tools.status === "ready";
  const lease = runtime.catalogLease;
  const node = run?.nodes.find(item => item.uniqueId === chosen);

  return (
    <section className="dbt-surface">
      <div className="dbt-toolbar">
        <div className="button-row">
          <ToolsBadge dbt={dbt} />
          <Badge appearance="tint" color={lease ? "warning" : runtime.status === "running" ? "success" : "informative"}>
            {lease ? "Catalog lent to dbt" : runtime.status === "running" ? "Catalog attached" : "Runtime stopped"}
          </Badge>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "refreshDbt" })}>Refresh</Button>
        </div>
      </div>

      {lease && (
        <div className="pipeline-notice dbt-lease" role="status">
          <strong>The catalog file is lent to <code>{lease.holder}</code></strong> since {formatTime(lease.since)}.
          {" "}DuckDB lets one process write <code>.datapass/data/workspace.duckdb</code>: the runtime closed it for this
          command and reattaches it when the command ends.
          {lease.reattachError && <div className="factory-error">{lease.reattachError}</div>}
          {!dbt.shellIntegration && <div>This terminal does not report when a command ends: reattach once it has finished.</div>}
          <div className="button-row">
            <Button size="small" appearance="primary" onClick={() => vscode.postMessage({ type: "reattachCatalog" })}>Reattach catalog</Button>
          </div>
        </div>
      )}

      {dbt.tools.status !== "ready" && <ToolsCard dbt={dbt} vscode={vscode} />}

      {dbt.projects.length === 0 ? (
        <div className="factory-empty">
          <Text weight="semibold">No dbt project in this workspace yet</Text>
          <p>
            The dbt Lab works on any folder with a <code>dbt_project.yml</code>. Start with the retail sample (seeds, staging
            and marts, tests), or open a mission.
          </p>
          <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createDbtSample" })}>Create retail sample</Button>
        </div>
      ) : (
        <div className="bi-panel bi-wide">
          <div className="factory-toolbar">
            <div className="button-row">
              <label className="bi-check">
                Project{" "}
                <select aria-label="dbt project" value={dbt.selected ?? ""}
                  onChange={event => vscode.postMessage({ type: "selectDbtProject", path: event.target.value })}>
                  {dbt.projects.map(project => (
                    <option key={project.path} value={project.path}>
                      {project.path || "."}{project.name ? ` (${project.name})` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <select aria-label="dbt command" value={command} onChange={event => setCommand(event.target.value as DbtCommand)}>
                {DBT_COMMANDS.map(item => <option key={item} value={item}>dbt {item}</option>)}
              </select>
              <input className="bi-select" aria-label="--select" placeholder="--select  e.g. +fct_sales tag:daily"
                disabled={!supportsSelection(command)} value={select} onChange={event => setSelect(event.target.value)} />
              <input className="bi-select" aria-label="--exclude" placeholder="--exclude"
                disabled={!supportsSelection(command)} value={exclude} onChange={event => setExclude(event.target.value)} />
              <label className="bi-check">
                <input type="checkbox" disabled={!supportsFullRefresh(command)} checked={fullRefresh}
                  onChange={event => setFullRefresh(event.target.checked)} /> --full-refresh
              </label>
            </div>
            <div className="button-row">
              <Button size="small" appearance="primary" disabled={!ready || Boolean(previewError)}
                onClick={() => vscode.postMessage({ type: "runDbtCommand", command, select, exclude, fullRefresh })}>
                Run in terminal
              </Button>
              <Button size="small" appearance="secondary" disabled={!ready} onClick={() => vscode.postMessage({ type: "openDbtTerminal" })}>
                Open terminal
              </Button>
              <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openDbtFile", path: "dbt_project.yml" })}>
                Open dbt_project.yml
              </Button>
            </div>
          </div>
          <p className="factory-note">
            {previewError
              ? <span className="factory-error">{previewError}</span>
              : <>Types <code>{preview}</code> in a terminal in <code>{dbt.selected || "."}</code>; edit it and press Enter to run it again.</>}
            {" "}Profiles: <code>{dbt.profilesPath}</code> (generated, local DuckDB only, no secrets).
          </p>
        </div>
      )}

      {dbt.artifactError && <div className="pipeline-diagnostics" role="alert">{dbt.artifactError}</div>}

      {dbt.projects.length > 0 && !run && !dbt.artifactError && (
        <p className="factory-note">
          No <code>target/</code> yet in this project. Run <code>dbt parse</code> (it needs no database) to see the DAG, or
          <code> dbt build</code> to build it on the local catalog.
        </p>
      )}

      {run && (
        <div className="bi-grid">
          <div className="bi-panel bi-wide">
            <div className="factory-result-head">
              <div>
                <div className="eyebrow">
                  dbt Core (real){run.dbtVersion ? ` ${run.dbtVersion}` : ""} · {run.command ?? "manifest only"}
                  {run.generatedAt ? ` · ${formatTime(run.generatedAt)}` : ""}
                  {run.elapsedSeconds !== undefined ? ` · ${run.elapsedSeconds.toFixed(1)} s` : ""}
                </div>
                <Text weight="semibold">
                  {run.hasResults ? countsLine(run.counts) : `${run.nodes.length} nodes parsed, nothing ran`}
                </Text>
              </div>
              <div className="button-row">
                {Object.entries(run.counts).map(([status, count]) => (
                  <Badge key={status} appearance="tint" color={STATUS_BADGE[status] ?? "informative"}>{count} {status}</Badge>
                ))}
                <label className="bi-check">
                  <input type="checkbox" checked={withTests} onChange={event => setWithTests(event.target.checked)} /> tests in the graph
                </label>
              </div>
            </div>
            <p className="factory-note">{run.truth}{run.invocationId ? ` · invocation ${run.invocationId}` : ""}.</p>
            {run.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
            <SharedGraphCanvas graph={graph} vscode={vscode} storageKey={withTests ? "dbt-core-dag-tests" : "dbt-core-dag"}
              onNodeClick={id => setChosen(id)} />
          </div>

          {run.problems.length > 0 && (
            <div className="bi-panel">
              <Text weight="semibold">Failures and warnings</Text>
              <table className="factory-runs">
                <thead><tr><th>Node</th><th>Status</th><th>Message</th></tr></thead>
                <tbody>
                  {run.problems.map(problem => (
                    <tr key={problem.uniqueId} className={chosen === problem.uniqueId ? "is-selected" : ""} onClick={() => setChosen(problem.uniqueId)}>
                      <td>{problem.name}<small>{problem.resourceType}</small></td>
                      <td className={`bi-dbt-${problem.status}`}>{problem.status}{problem.failures ? ` (${problem.failures})` : ""}</td>
                      <td><small>{firstLine(problem.message)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {node && <NodeDetail node={node} vscode={vscode} />}
        </div>
      )}
    </section>
  );
}

function ToolsBadge({ dbt }: { dbt: DbtViewState }) {
  const versions = dbt.tools.versions ?? {};
  if (dbt.tools.status === "ready") {
    return (
      <Badge appearance="tint" color="success">
        dbt Core {versions["dbt-core"]} · dbt-duckdb {versions["dbt-duckdb"]}
      </Badge>
    );
  }
  return (
    <Badge appearance="tint" color={dbt.tools.status === "error" ? "danger" : "warning"}>
      {dbt.tools.status === "installing" ? "Installing dbt tools…" : dbt.tools.status === "error" ? "dbt tools install failed" : "dbt tools not installed"}
    </Badge>
  );
}

function ToolsCard({ dbt, vscode }: { dbt: DbtViewState; vscode: VsCodeApi }) {
  const progress = dbt.tools.progress;
  return (
    <div className="factory-empty">
      <Text weight="semibold">Install the dbt tools</Text>
      <p>
        The dbt Lab runs the real dbt Core with dbt-duckdb on your local catalog. Datapass installs them in a separate,
        managed Python environment (Python 3.10–3.13, in the extension's storage) only when you ask. Nothing connects to a
        cloud warehouse, and dbt's anonymous usage statistics are turned off.
      </p>
      {progress && (
        <p className="factory-note">
          Step {progress.step}/{progress.totalSteps}: {progress.label}{progress.activity ? ` · ${progress.activity}` : ""}
        </p>
      )}
      {dbt.tools.status === "error" && dbt.tools.detail && <p className="factory-error">{dbt.tools.detail}</p>}
      <div className="button-row">
        <Button appearance="primary" disabled={dbt.tools.status === "installing"}
          onClick={() => vscode.postMessage({ type: "installDbtTools" })}>
          {dbt.tools.status === "error" ? "Retry install" : "Install dbt tools"}
        </Button>
        <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "showDbtToolsLog" })}>Show log</Button>
      </div>
    </div>
  );
}

function NodeDetail({ node, vscode }: { node: DbtCoreNodeView; vscode: VsCodeApi }) {
  return (
    <div className="bi-panel">
      <Text weight="semibold">{node.name}</Text>
      <p className="factory-note">
        {node.resourceType}{node.materialized ? ` · ${node.materialized}` : ""}{node.relation ? ` → ${node.relation}` : ""}
        {node.tags.length ? ` · tags ${node.tags.join(", ")}` : ""}
        {node.executionTime !== undefined ? ` · ${node.executionTime.toFixed(2)} s` : ""}
        {node.rowsAffected !== undefined ? ` · ${node.rowsAffected} rows` : ""}
      </p>
      {node.status && (
        <p className={node.status === "error" || node.status === "fail" ? "factory-error" : "factory-note"}>
          {node.status}{node.failures ? ` · ${node.failures} failing rows` : ""}{node.message ? `: ${node.message}` : ""}
        </p>
      )}
      <div className="button-row">
        {node.path && (
          <button type="button" className="bi-link" onClick={() => vscode.postMessage({ type: "openDbtFile", path: node.path! })}>
            Open {node.path}
          </button>
        )}
        {node.compiledPath && (
          <button type="button" className="bi-link" onClick={() => vscode.postMessage({ type: "openDbtFile", path: node.compiledPath! })}>
            Open compiled SQL
          </button>
        )}
      </div>
    </div>
  );
}

function firstLine(text: string | undefined): string {
  return (text ?? "").split(/\r?\n/)[0] ?? "";
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}
