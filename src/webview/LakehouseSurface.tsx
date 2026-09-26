import { Badge, Button, Text } from "@fluentui/react-components";
import type { LakehouseRunView, LakehouseStorageView, LakehouseViewState, RuntimeViewState } from "./contracts";
import type { MissionView } from "../platform/missions";
import type { VsCodeApi } from "./WorkbenchApp";
import { MissionsPanel } from "./MissionsPanel";

const CONCEPTS: readonly { id: string; title: string; text: string; handled: boolean }[] = [
  { id: "parquet", title: "Parquet", handled: true,
    text: "A columnar file format: each column is stored (and compressed) apart, with min/max statistics per row group, so a query reads only the columns and row groups it needs." },
  { id: "hive", title: "Hive-style partitions", handled: true,
    text: "Folders named key=value (year=2025/month=3/) split a dataset by the values of a few columns. The values live in the folder names, not in the files." },
  { id: "pruning", title: "Partition pruning", handled: true,
    text: "A filter on the partition columns is checked on the folder names before any file opens. DuckDB's EXPLAIN ANALYZE shows it as Total Files Read." },
  { id: "small-files", title: "The small-files problem", handled: true,
    text: "Streaming and frequent appends write many tiny files. Each file costs an open, a footer read and metadata; compaction rewrites them into fewer, larger files." },
  { id: "ducklake", title: "DuckLake", handled: true,
    text: "An open table format whose catalog is a database (here a DuckDB file) and whose data are Parquet files. Every commit is a snapshot: time travel, schema evolution and MERGE come from the catalog." },
  { id: "time-travel", title: "Snapshots and time travel", handled: true,
    text: "Reading a table AT (VERSION => n) shows it as it was at snapshot n. Fixing a mistake is a new snapshot; the history keeps the mistake." },
  { id: "schema-evolution", title: "Schema evolution", handled: true,
    text: "ALTER TABLE … ADD COLUMN is a catalog change: old Parquet files are not rewritten, and read NULL for the new column." },
  { id: "merge", title: "MERGE and atomic commits", handled: true,
    text: "MERGE INTO applies inserts, updates and deletes from one source in one statement. One transaction is one snapshot: readers see all of it or none." },
  { id: "delta-iceberg", title: "Delta Lake", handled: true,
    text: "Fabric and Databricks store tables as Delta: Parquet files plus a _delta_log folder of JSON commits, each listing the files it adds or removes. Here DuckDB's official delta extension really reads Delta tables (any version: time travel) and appends to them; it cannot create one, so the mission ships its table. OPTIMIZE, VACUUM and MERGE on Delta are Spark / Fabric features, not handled here." },
  { id: "iceberg", title: "Apache Iceberg", handled: false,
    text: "Snowflake, AWS and others use Iceberg: metadata JSON, manifest lists and manifests over Parquet. Same ideas as DuckLake and Delta (snapshots, time travel, schema evolution, compaction with rewrite_data_files)." }
];

/**
 * Lakehouse Lab: storage layout on local files and DuckLake tables. Everything runs for real on this machine: the
 * learner's SQL on DuckDB (a process bounded to the mission folder), their Polars file as trusted local Python; the
 * checker measures files on disk and queries the mission's DuckLake catalog.
 */
export function LakehouseSurface({
  vscode,
  lakehouse,
  runtime
}: {
  vscode: VsCodeApi;
  lakehouse: LakehouseViewState | undefined;
  runtime: RuntimeViewState;
}) {
  if (!lakehouse) return <div className="empty-state">Lakehouse Lab state is not available.</div>;
  const running = runtime.status === "running";
  const ducklake = lakehouse.ducklake;

  return (
    <section className="lakehouse-surface">
      <div className="dbt-toolbar">
        <div className="button-row">
          <Badge appearance="tint" color="success">DuckDB · real</Badge>
          {ducklake && (
            <Badge appearance="tint" color={ducklake.installed ? "success" : "warning"}>
              {ducklake.installed ? `DuckLake extension ${ducklake.version ?? ""}` : "DuckLake extension not installed"}
            </Badge>
          )}
          <Badge appearance="tint" color={lakehouse.trustedPython ? "success" : "informative"}>
            {lakehouse.trustedPython ? "Polars · trusted Python on" : "Polars · trusted Python off"}
          </Badge>
        </div>
        <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "refreshLakehouseLab" })}>Refresh</Button>
      </div>

      <p className="factory-note">
        Real and local: <strong>Run</strong> executes your mission file on DuckDB, in a process that can only read and
        write inside the mission folder (or your Polars file as trusted local Python). <strong>Check my work</strong> measures
        the files on disk and queries the mission's DuckLake catalog or Delta table. Iceberg is explained, not handled.
      </p>
      {ducklake && ducklake.installed && !ducklake.delta && (
        <div className="pipeline-notice" role="status">
          <strong>The Delta mission needs DuckDB's delta extension.</strong> Run <em>Datapass: Setup runtime</em> once with
          a network connection: it installs it.
        </div>
      )}
      {ducklake && !ducklake.installed && (
        <div className="pipeline-notice" role="status">
          <strong>The DuckLake missions need DuckDB's ducklake extension.</strong> Run <em>Datapass: Setup runtime</em> once
          with a network connection: it installs it, and it works offline afterwards. The Parquet missions work without it.
        </div>
      )}
      {lakehouse.error && <div className="pipeline-notice" role="alert">{lakehouse.error}</div>}

      <MissionsPanel
        state={lakehouse.missions}
        vscode={vscode}
        canRun={running}
        blockedReason={running ? undefined : "Start the runtime: it builds the mission folder, runs your file and checks it."}
        openLabel="Open ticket and file"
        send={(action, missionId) => vscode.postMessage({ type: "lakehouseMission", action: action as never, missionId })}
        folderNote={mission => <>Folder: <code>lakehouse/{mission.id}</code>. The ticket is <code>TICKET.md</code> there.</>}
        extra={mission => (
          <MissionWork vscode={vscode} mission={mission} lakehouse={lakehouse} running={running} />
        )}
      />

      <section className="lakehouse-concepts" aria-label="Concepts">
        <Text weight="semibold">Concepts</Text>
        <dl>
          {CONCEPTS.map(concept => (
            <div key={concept.id} className="lakehouse-concept">
              <dt>{concept.title} {!concept.handled && <Badge appearance="outline" size="small">explained, not handled here</Badge>}</dt>
              <dd>{concept.text}</dd>
            </div>
          ))}
        </dl>
      </section>
    </section>
  );
}

function MissionWork({ vscode, mission, lakehouse, running }: {
  vscode: VsCodeApi; mission: MissionView; lakehouse: LakehouseViewState; running: boolean;
}) {
  const detail = lakehouse.details[mission.id];
  if (!detail) return null;
  const run = lakehouse.lastRun?.missionId === mission.id ? lakehouse.lastRun : undefined;
  const storage = lakehouse.storage?.missionId === mission.id ? lakehouse.storage : undefined;
  return (
    <div className="lakehouse-work">
      <div className="button-row">
        {detail.engines.map(engine => (
          <Button key={engine} size="small" appearance="secondary"
            disabled={!running || (engine === "polars" && !lakehouse.trustedPython)}
            title={engine === "polars" && !lakehouse.trustedPython ? "Turn on trusted Python for this workspace to run Polars" : undefined}
            onClick={() => vscode.postMessage({ type: "lakehouseRun", missionId: mission.id, engine })}>
            Run {detail.files[engine]} ({engine === "duckdb" ? "DuckDB" : "Polars"})
          </Button>
        ))}
        <Button size="small" appearance="subtle" disabled={!running}
          onClick={() => vscode.postMessage({ type: "lakehouseStorage", missionId: mission.id })}>Measure storage</Button>
        {detail.ducklake && <Badge appearance="outline" size="small">DuckLake: attached as lake</Badge>}
        {detail.delta.map(table => <Badge key={table} appearance="outline" size="small">Delta: {table.split("/").pop()} attached</Badge>)}
      </div>
      {run && <RunOutput run={run} />}
      {storage && <StorageView storage={storage} />}
    </div>
  );
}

function RunOutput({ run }: { run: LakehouseRunView }) {
  return (
    <div className="lakehouse-run" aria-label="Run output">
      <p className="factory-note">
        {run.file && <><code>{run.file}</code> · </>}{run.truth}{run.elapsedMs !== undefined ? ` · ${run.elapsedMs} ms` : ""}
      </p>
      {run.statements?.map((statement, index) => (
        <div key={index} className="lakehouse-statement">
          <code className="lakehouse-sql">{statement.type} · {statement.sql.split("\n")[0].slice(0, 120)}</code>
          {statement.columns && statement.rows && (
            statement.columns.includes("explain_value")
              ? <pre className="factory-json">{statement.rows.map(row => row[row.length - 1]).join("\n")}</pre>
              : (
                <div className="retail-preview-wrap">
                  <table className="retail-preview">
                    <thead><tr>{statement.columns.map((column, i) => <th key={i}>{column}</th>)}</tr></thead>
                    <tbody>
                      {statement.rows.slice(0, 12).map((row, r) => (
                        <tr key={r}>{row.map((cell, c) => <td key={c}>{cell ?? "NULL"}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                  {(statement.rows.length > 12 || statement.truncated) && <small className="muted">First 12 rows shown.</small>}
                </div>
              )
          )}
        </div>
      ))}
      {run.exitCode !== undefined && <p className={run.exitCode === 0 ? "factory-note" : "factory-warning"}>Exit code {run.exitCode}.</p>}
      {run.stdout && <pre className="factory-json">{run.stdout}</pre>}
      {run.stderr && <pre className="factory-json">{run.stderr}</pre>}
      {run.error && (
        <p className="factory-warning" role="alert">
          {run.failedStatement ? `Statement ${run.failedStatement} failed: ` : ""}{run.error}
        </p>
      )}
    </div>
  );
}

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function StorageView({ storage }: { storage: LakehouseStorageView }) {
  return (
    <div className="lakehouse-storage" aria-label="Storage">
      <Text weight="semibold">Storage (measured on disk)</Text>
      {storage.folders.length === 0 ? <p className="muted">No data file yet.</p> : (
        <div className="retail-preview-wrap">
          <table className="retail-preview">
            <thead><tr><th>Folder</th><th>Files</th><th>Bytes</th><th>Average</th></tr></thead>
            <tbody>
              {storage.folders.slice(0, 40).map(folder => (
                <tr key={folder.path}>
                  <td><code>{folder.path}</code></td><td>{folder.files}</td><td>{bytes(folder.bytes)}</td>
                  <td>{bytes(Math.round(folder.bytes / Math.max(1, folder.files)))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {storage.folders.length > 40 && <small className="muted">{storage.folders.length - 40} more folders.</small>}
        </div>
      )}
      {storage.snapshots && (
        <>
          <Text weight="semibold">DuckLake snapshots (queried)</Text>
          <ol className="lakehouse-snapshots">
            {storage.snapshots.map(snapshot => <li key={snapshot.id}><code>{snapshot.id}</code> {snapshot.changes}</li>)}
          </ol>
        </>
      )}
      {storage.snapshotsError && <p className="factory-warning">{storage.snapshotsError}</p>}
    </div>
  );
}
