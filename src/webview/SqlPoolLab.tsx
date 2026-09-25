import { Badge, Button, Text } from "@fluentui/react-components";
import { useMemo, useState } from "react";
import type {
  FactoryViewState,
  RuntimeViewState,
  SqlPoolFlavor,
  SqlPoolLabView,
  SqlPoolPlanView,
  SqlPoolStatementView,
  SqlPoolTableView
} from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import {
  DEFAULT_SQLPOOL_SCALE,
  SQLPOOL_SCALES,
  defaultStatement,
  distributionBars,
  formatCount,
  movementSummary,
  scanSummary,
  skewLevel
} from "../platform/sqlpoolRun";

const FLAVORS: { id: SqlPoolFlavor; label: string }[] = [
  { id: "synapse", label: "Synapse dedicated SQL pool" },
  { id: "fabric", label: "Fabric Warehouse" }
];

/** Cloud Lab › SQL pool: T-SQL scripts on a simulated dedicated SQL pool or Fabric Warehouse. */
export function SqlPoolLab({
  vscode,
  factory,
  runtime
}: {
  vscode: VsCodeApi;
  factory: FactoryViewState | undefined;
  runtime: RuntimeViewState;
}) {
  const running = runtime.status === "running";
  const scripts = factory?.poolScripts ?? [];
  const lab = runtime.sqlpoolRun;
  const [flavor, setFlavor] = useState<SqlPoolFlavor>(lab?.flavor ?? scripts[0]?.flavor ?? "synapse");
  const [scale, setScale] = useState<number>(lab?.scale ?? DEFAULT_SQLPOOL_SCALE);
  const [path, setPath] = useState<string | undefined>(
    scripts.some(script => script.path === lab?.source) ? lab?.source : scripts[0]?.path
  );
  const script = scripts.find(candidate => candidate.path === path) ?? scripts[0];

  const chooseScript = (next: string) => {
    setPath(next);
    const hint = scripts.find(candidate => candidate.path === next)?.flavor;
    if (hint) setFlavor(hint);
  };
  const run = (source: "file" | "active" | "describe") =>
    vscode.postMessage({ type: "runSqlPool", flavor, scale, source, path: source === "file" ? script?.path : undefined });

  if (!factory?.exists || !scripts.length) {
    return (
      <div className="factory-empty">
        <Text weight="semibold">Create the SQL pool scripts</Text>
        <p>
          The SQL pool tab runs T-SQL scripts from <code>factory/sql/pool/</code> on a simulated Azure Synapse dedicated
          SQL pool or Microsoft Fabric Data Warehouse: CTAS, distributions, indexes, partitions, stored procedures and
          the data movement of each query. The sample scripts build a star schema, monthly partitions and a procedure.
        </p>
        <div className="button-row">
          <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>Create lab files</Button>
          <Button appearance="secondary" disabled={!running} onClick={() => run("active")}>Run active .sql</Button>
          <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
            SQL pool exercises
          </Button>
        </div>
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
              onClick={() => setFlavor(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="button-row">
          <select aria-label="Script" value={script?.path} onChange={event => chooseScript(event.target.value)}>
            {scripts.map(item => (
              <option key={item.path} value={item.path}>{item.name}{item.flavor ? ` (${item.flavor})` : ""}</option>
            ))}
          </select>
          <label className="sqlpool-scale">
            <span>1 lab row =</span>
            <select aria-label="Scale" value={scale} onChange={event => setScale(Number(event.target.value))}>
              {SQLPOOL_SCALES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <span>rows</span>
          </label>
          {script && (
            <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openFactoryFile", path: script.path })}>
              Open script
            </Button>
          )}
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "createFactoryLab" })}>
            Restore sample files
          </Button>
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
            SQL pool exercises
          </Button>
          <Button size="small" appearance="secondary" disabled={!running} onClick={() => run("describe")}>Describe tables</Button>
          <Button size="small" appearance="secondary" disabled={!running} onClick={() => run("active")}>Run active .sql</Button>
          <Button size="small" appearance="primary" disabled={!running || !script} onClick={() => run("file")}>Run script</Button>
        </div>
      </div>
      {!running && <p className="factory-note">Start the runtime to run T-SQL on the simulated pool.</p>}
      {factory.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
      <p className="factory-note">
        <code>dbo</code> is the lab's warehouse layer (<code>warehouse.*</code> in the Mosaic catalog). Tables that don't
        inherit a scale from their sources count each lab row as {formatCount(scale)} real rows, so distribution and
        columnstore rules apply as they would at that size.
      </p>
      {lab && <PoolResult lab={lab} onReveal={line => vscode.postMessage({ type: "revealSqlPoolLine", line })} />}
      <MovementLegend />
      <FlavorDifferences />
    </div>
  );
}

function PoolResult({ lab, onReveal }: { lab: SqlPoolLabView; onReveal: (line: number) => void }) {
  const initial = useMemo(() => defaultStatement(lab.statements), [lab]);
  const [selectedKey, setSelectedKey] = useState<string>();
  const flat = useMemo(() => flatten(lab.statements), [lab]);
  const selected = flat.find(entry => entry.key === selectedKey)?.statement ?? initial;
  const failed = flat.find(entry => entry.statement.status === "error")?.statement;

  return (
    <div className="factory-result">
      <div className="factory-result-head">
        <div>
          <div className="eyebrow">{lab.flavorLabel} · {lab.source || "tables described"}</div>
          <Text size={400} weight="semibold">
            {!lab.statements.length ? "Pool tables" : failed ? `Stopped at statement ${failed.index}` : `${lab.statements.length} statements ran`}
          </Text>
        </div>
        <Badge appearance="filled" color={lab.status === "ok" ? "success" : "danger"}>{lab.status === "ok" ? "ok" : "error"}</Badge>
      </div>
      <p className="factory-note">{lab.truth}</p>
      {lab.warnings.map(warning => <p key={warning} className="factory-warning">{warning}</p>)}
      {lab.statements.length > 0 && (
        <div className="sqlpool-run">
          <table className="factory-runs sqlpool-statements">
            <thead><tr><th>#</th><th>Statement</th><th>Result</th></tr></thead>
            <tbody>
              {flat.map(({ key, statement, depth }) => (
                <tr
                  key={key}
                  className={`${statement === selected ? "is-selected" : ""} ${depth ? "is-inner" : ""}`}
                  onClick={() => setSelectedKey(key)}
                >
                  <td>
                    {depth ? `${key}` : statement.index}
                    {!depth && (
                      <button type="button" className="sqlpool-line" title="Show in the script" onClick={() => onReveal(statement.line)}>
                        L{statement.line}
                      </button>
                    )}
                  </td>
                  <td style={{ paddingLeft: `${6 + depth * 12}px` }}>
                    {statement.kind}
                    {statement.target && <small>{statement.target}</small>}
                  </td>
                  <td>
                    {statement.status === "error"
                      ? <span className="factory-error">{statement.message}</span>
                      : <span>{statement.message}</span>}
                    {statement.plan && <small>{movementSummary(statement.plan)}</small>}
                    {statement.plan && statement.plan.scans.length > 0 && <small>{scanSummary(statement.plan)}</small>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {selected && <StatementDetails statement={selected} />}
        </div>
      )}
      <div className="sqlpool-tables">
        {lab.tables.length === 0
          ? <p className="factory-note">No table in the pool yet: run a script that creates one.</p>
          : lab.tables.map(table => <TableCard key={table.name} table={table} lab={lab} />)}
      </div>
    </div>
  );
}

function StatementDetails({ statement }: { statement: SqlPoolStatementView }) {
  return (
    <div className="sqlpool-details">
      <Text weight="semibold">Statement {statement.index} · {statement.kind}</Text>
      <p className={statement.status === "error" ? "factory-error" : "factory-explanation"}>{statement.message}</p>
      {statement.notes.map(note => <p key={note} className="factory-hint">{note}</p>)}
      {statement.plan && <PlanView plan={statement.plan} />}
      {statement.sql && (
        <details className="sqlpool-sql">
          <summary>What DuckDB ran (translated T-SQL)</summary>
          <pre className="factory-json">{statement.sql}</pre>
        </details>
      )}
      {statement.columns.length > 0 && (
        <div className="retail-preview-wrap">
          <table className="retail-preview">
            <thead><tr>{statement.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {statement.rows.slice(0, 50).map((row, index) => (
                <tr key={index}>{statement.columns.map(column => <td key={column}>{format(row[column])}</td>)}</tr>
              ))}
            </tbody>
          </table>
          {(statement.truncated || statement.rows.length > 50) && <p className="factory-note">Only the first rows are shown.</p>}
        </div>
      )}
    </div>
  );
}

function PlanView({ plan }: { plan: SqlPoolPlanView }) {
  const moves = plan.steps.filter(step => step.operation !== "ReturnOperation");
  return (
    <div className="sqlpool-plan">
      <strong>Distributed plan (simulated)</strong>
      {moves.length > 0 ? (
        <table className="factory-runs">
          <thead><tr><th>Operation</th><th>Rows moved</th><th>Why</th></tr></thead>
          <tbody>
            {moves.map((step, index) => (
              <tr key={index}>
                <td>
                  {step.operation}
                  <small>{step.tables.join(", ")}{step.columns.length ? ` · on ${step.columns.join(", ")}` : ""}</small>
                </td>
                <td>{formatCount(step.rows)}</td>
                <td>{step.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="factory-note">No data movement.</p>
      )}
      {plan.scans.map(scan => (
        <p key={`${scan.table}:${scan.alias}`} className={scan.eliminated ? "factory-hint" : "factory-note"}>
          {scan.table} scans {scan.partitionsScanned} of {scan.partitionsTotal} partitions. {scan.reason}
        </p>
      ))}
      {plan.notes.map(note => <p key={note} className="factory-note">{note}</p>)}
    </div>
  );
}

function TableCard({ table, lab }: { table: SqlPoolTableView; lab: SqlPoolLabView }) {
  // A replicated table has no distributions (a full copy lives on every compute node); an empty one has nothing to spread.
  const stats = table.distributionStats?.shares.length && table.rows > 0 ? table.distributionStats : undefined;
  const bars = stats ? distributionBars(stats.shares) : [];
  const fullest = stats && stats.shares.length ? Math.max(0, ...stats.shares) : 0;
  return (
    <div className="sqlpool-table">
      <div className="factory-details-head">
        <div>
          <Text weight="semibold">{table.name}</Text> <code>{table.label}</code>
          <div className="factory-note">
            {formatCount(table.rows)} lab rows · {formatCount(table.rowsAtScale)} at scale
            {table.scaleFactor !== lab.scale ? ` (${formatCount(table.scaleFactor)} per lab row, from its sources)` : ""}
            {table.createdBy ? ` · ${table.createdBy}` : ""}
          </div>
        </div>
        {table.columnstoreOk !== undefined && (
          <Badge appearance="tint" color={table.columnstoreOk ? "success" : "warning"}>
            {table.columnstoreOk ? "columnstore: full rowgroups" : "columnstore: under 1 M rows per distribution"}
          </Badge>
        )}
      </div>
      {stats && (
        <div className="sqlpool-distribution">
          <div className="sqlpool-bars" role="img" aria-label={`Rows on each of the ${stats.shares.length} distributions`}>
            {bars.map((height, index) => (
              <span
                key={index}
                style={{ height: `${Math.max(height * 100, stats.shares[index] > 0 ? 3 : 0)}%` }}
                title={`Distribution ${index + 1}: ${(stats.shares[index] * 100).toFixed(2)}% of the rows`}
              />
            ))}
            {fullest > 0 && <i style={{ bottom: `${(1 / stats.shares.length / fullest) * 100}%` }} title="Even spread" />}
          </div>
          <div className="sqlpool-skew">
            <Badge appearance="tint" color={skewLevel(stats.skewPct) === "skewed" ? "warning" : "success"}>
              skew {stats.skewPct}%
            </Badge>
            <span>max {stats.maxSharePct}% · min {stats.minSharePct}% of the rows per distribution</span>
            {stats.emptyDistributions > 0 && <span>{stats.emptyDistributions} empty distributions</span>}
            {stats.nullSharePct > 0 && <span>{stats.nullSharePct}% NULL keys on one distribution</span>}
            {stats.heavyValues.length > 0 && (
              <span>frequent keys: {stats.heavyValues.slice(0, 4).map(v => `${v.value} (${v.sharePct}%)`).join(", ")}</span>
            )}
          </div>
        </div>
      )}
      {table.distribution === "REPLICATE" && (
        <p className="factory-note">Replicated: a full copy on every compute node, so joins to it need no data movement.</p>
      )}
      {table.partitions.length > 0 && (
        <table className="factory-runs sqlpool-partitions">
          <thead>
            <tr><th>Partition</th><th>{table.partition?.column} values</th><th>Rows</th><th>At scale</th><th>Per distribution</th><th>Columnstore</th></tr>
          </thead>
          <tbody>
            {table.partitions.map(partition => (
              <tr key={partition.number}>
                <td>{partition.number}</td>
                <td>{rangeLabel(partition.lower, partition.upper, table.partition?.range ?? "LEFT")}</td>
                <td>{partition.rows}</td>
                <td>{formatCount(partition.rowsAtScale)}</td>
                <td>{partition.rowsPerDistribution === undefined ? "" : formatCount(partition.rowsPerDistribution)}</td>
                <td>{partition.columnstoreOk === undefined ? "" : partition.columnstoreOk ? "ok" : "too few rows"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(table.constraints.length > 0 || table.nonclusteredIndexes.length > 0 || table.statistics.length > 0 || table.clusterBy.length > 0) && (
        <div className="factory-tables">
          {table.constraints.map(c => <span key={`${c.kind}:${c.columns.join()}`}>{c.kind} ({c.columns.join(", ")}) {c.enforced ? "" : "NOT ENFORCED"}</span>)}
          {table.nonclusteredIndexes.map(index => <span key={index.name}>index {index.name} ({index.columns.join(", ")})</span>)}
          {table.statistics.map(stat => <span key={stat.name}>statistics {stat.name} ({stat.columns.join(", ")})</span>)}
          {table.clusterBy.length > 0 && <span>CLUSTER BY ({table.clusterBy.join(", ")})</span>}
        </div>
      )}
    </div>
  );
}

function flatten(statements: readonly SqlPoolStatementView[]): { key: string; statement: SqlPoolStatementView; depth: number }[] {
  const out: { key: string; statement: SqlPoolStatementView; depth: number }[] = [];
  const walk = (items: readonly SqlPoolStatementView[], prefix: string, depth: number) => {
    for (const item of items) {
      const key = prefix ? `${prefix}.${item.index}` : String(item.index);
      out.push({ key, statement: item, depth });
      walk(item.children, key, depth + 1);
    }
  };
  walk(statements, "", 0);
  return out;
}

function rangeLabel(lower: string | undefined, upper: string | undefined, range: string): string {
  const [low, high] = range === "RIGHT" ? [">=", "<"] : [">", "<="];
  if (lower === undefined && upper === undefined) return "all";
  if (lower === undefined) return `${high} ${upper}`;
  if (upper === undefined) return `${low} ${lower}`;
  return `${low} ${lower} and ${high} ${upper}`;
}

function format(value: unknown): string {
  return value === null || value === undefined ? "NULL" : String(value);
}

const OPERATIONS: [string, string][] = [
  ["ShuffleMoveOperation", "Rows are re-hashed on a column and sent to the distribution that owns each value (a join or GROUP BY on a column the table is not distributed on)."],
  ["BroadcastMoveOperation", "A full copy of a small table is sent to every distribution (it joins to a much larger one that is not aligned)."],
  ["PartitionMoveOperation", "Partial results of every distribution are gathered on one node (a global aggregate such as COUNT(*) without GROUP BY)."],
  ["ReturnOperation", "The control node returns the result to the client."]
];

function MovementLegend() {
  return (
    <details className="factory-differences">
      <summary>Data movement operations: what they mean</summary>
      <table>
        <tbody>
          {OPERATIONS.map(([operation, meaning]) => <tr key={operation}><th>{operation}</th><td>{meaning}</td></tr>)}
        </tbody>
      </table>
      <p className="factory-note">
        A join runs without data movement when one side is replicated, or when both sides are hash distributed on the
        join column with the same data type. Operation names follow the dedicated SQL pool's EXPLAIN output; the lab
        decides them with documented rules, it does not measure them.
      </p>
    </details>
  );
}

const DIFFERENCES: [string, string, string][] = [
  ["Data layout", "DISTRIBUTION = HASH(col), ROUND_ROBIN (default) or REPLICATE; 60 distributions", "Managed by the service: no DISTRIBUTION option"],
  ["Storage and indexes", "Clustered columnstore (default), ordered CCI, HEAP, clustered and nonclustered indexes", "Delta Parquet in OneLake; no user indexes"],
  ["Partitioning", "PARTITION (col RANGE LEFT | RIGHT FOR VALUES (...)), SWITCH, SPLIT, MERGE", "No partitioned tables; WITH (CLUSTER BY (col, ...)) clusters data"],
  ["CTAS", "Requires a DISTRIBUTION option", "No table options besides CLUSTER BY"],
  ["Keys", "PRIMARY KEY / UNIQUE only NONCLUSTERED NOT ENFORCED; no FOREIGN KEY", "The same, plus FOREIGN KEY ... NOT ENFORCED"],
  ["Types", "T-SQL types", "No money, datetime, nvarchar, nchar, tinyint...: decimal(19,4), datetime2, varchar, char, smallint"],
  ["Rename a table", "RENAME OBJECT", "sp_rename (not simulated)"],
  ["Statistics", "Single and multi-column, created manually or automatically", "Single-column only, manual or automatic"],
  ["Scale", "Compute reserved in DWUs, paused and resumed", "Capacity units shared by the workspace"]
];

function FlavorDifferences() {
  return (
    <details className="factory-differences">
      <summary>Synapse dedicated SQL pool and Fabric Warehouse: what differs</summary>
      <table>
        <thead><tr><th /><th>Synapse dedicated SQL pool</th><th>Fabric Data Warehouse</th></tr></thead>
        <tbody>
          {DIFFERENCES.map(([topic, synapse, fabric]) => <tr key={topic}><th>{topic}</th><td>{synapse}</td><td>{fabric}</td></tr>)}
        </tbody>
      </table>
      <p className="factory-note">
        Both speak T-SQL and use CTAS, views and stored procedures. Moving from a dedicated pool to Fabric mostly means
        removing the physical design options and replacing the types Fabric doesn't have.
      </p>
    </details>
  );
}
