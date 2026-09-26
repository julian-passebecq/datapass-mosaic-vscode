import { Badge, Button, Card, CardHeader, Switch, Text } from "@fluentui/react-components";
import { useState } from "react";
import type { PythonTrustView, RuntimeViewState, SparkLabEngine, SparkLabProfileView, SparkLabRunView } from "./contracts";
import { ResultTable } from "./ResultTable";
import { TrustedPythonControl } from "./TrustedPythonControl";
import type { VsCodeApi } from "./WorkbenchApp";

/** The same DataFrame operation in SparkLab's PySpark subset and in Polars, with SparkLab's note. */
const OPERATIONS = [
  ["Read", "spark.table()", "pl.DataFrame(query(sql)).lazy()", "Shared local catalog tables"],
  ["Rows", "filter(), where(), select()", "filter(), select()", "F.col expressions; no SQL strings"],
  ["Shape", "withColumn(), drop(), distinct()", "with_columns(), drop(), unique()", "Bounded semantic emulation"],
  ["Join", "join()", "join(how=…, coalesce=True)", "Same-name keys; inner/left/right/full/semi/anti"],
  ["Group", "groupBy().agg()", "group_by().agg()", "Common aggregation concepts"],
  ["Window", "Window.partitionBy().orderBy()", "expr.over(), sort first", "lag, running aggregates, row frames"],
  ["Sort", "orderBy(), sort()", "sort()", "Local deterministic results"],
  ["Limit", "limit()", "head(), limit()", "Bounded collection"]
] as const;

export function SparkLabSurface({
  vscode,
  runtime,
  profiles,
  pythonTrust
}: {
  vscode: VsCodeApi;
  runtime: RuntimeViewState;
  profiles: readonly SparkLabProfileView[];
  pythonTrust: PythonTrustView;
}) {
  const [engine, setEngine] = useState<SparkLabEngine>("sparklab");
  const [profileId, setProfileId] = useState(profiles[0]?.id ?? "generic_8x8");
  const [aqe, setAqe] = useState(true);
  const running = runtime.status === "running";
  const polars = engine === "polars";
  // Reported by the running runtime itself; Polars never runs without it.
  const polarsReady = running && runtime.trustedPython === true;

  return (
    <section className="lab-surface">
      <div className="lab-toolbar">
        <div>
          <div className="eyebrow">PySpark concepts without a cluster, and Polars on one machine</div>
          <Text size={500} weight="semibold">SparkLab / ZilaCode</Text>
        </div>
        <Badge appearance="tint" color={running ? "success" : "informative"}>
          {running ? "runtime ready" : "start local runtime for execution"}
        </Badge>
      </div>

      <div className="sparklab-hero">
        <div>
          <h3>Run bounded PySpark-style code, or the same lesson in Polars</h3>
          <p>
            SparkLab parses a whitelisted PySpark DataFrame subset without executing Python, compiles it to SQL and
            computes the result locally against the shared catalog. Stages, shuffle, cost and cluster behavior are
            simulated teaching evidence. This is not a Spark cluster and does not claim distributed parity.
          </p>
          <p>
            Polars is the lightweight alternative: a DataFrame engine for one machine, no cluster and no JVM. The
            Polars engine runs your file as real local Python, only with trusted Python enabled, and shows Polars'
            own optimized plan when the file ends with a LazyFrame.
          </p>
        </div>
        <div className="button-row">
          <Button appearance="primary" onClick={() => vscode.postMessage({ type: "openScratch", kind: polars ? "polars" : "sparklab" })}>
            {polars ? "Open Polars scratch" : "Open SparkLab scratch"}
          </Button>
          <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
            Browse Spark exercises
          </Button>
        </div>
      </div>

      <div className="sparklab-runbar">
        <label>
          Engine
          <select value={engine} onChange={event => setEngine(event.target.value as SparkLabEngine)}>
            <option value="sparklab">PySpark (SparkLab, bounded; plans simulated)</option>
            <option value="polars">Polars (real, trusted Python)</option>
          </select>
        </label>
        {polars ? (
          <TrustedPythonControl vscode={vscode} trust={pythonTrust} />
        ) : (
          <>
            <label>
              Virtual cluster profile (simulated)
              <select value={profileId} onChange={event => setProfileId(event.target.value)}>
                {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
              </select>
            </label>
            <Switch
              label="Adaptive query execution (simulated)"
              checked={aqe}
              onChange={(_, data) => setAqe(data.checked)}
            />
          </>
        )}
        <Button
          appearance="primary"
          disabled={polars ? !polarsReady : !running}
          title={polars && running && !polarsReady ? "The running runtime has trusted Python off: enable it, then restart the runtime." : undefined}
          onClick={() => vscode.postMessage({ type: "runActiveSparkLab", engine, profileId, aqe })}
        >
          {polars ? "Run active file with Polars" : "Run active SparkLab file"}
        </Button>
      </div>

      {runtime.sparkRun && <SparkRunResult run={runtime.sparkRun} />}

      <div className="spark-operation-grid">
        {OPERATIONS.map(([group, spark, polarsApi, note]) => (
          <Card key={group} className="spark-operation-card">
            <CardHeader
              header={<Text weight="semibold">{group}</Text>}
              description={<Text>{spark}</Text>}
            />
            <div className="lab-card-body">
              <span>Polars: <code>{polarsApi}</code></span>
              <span className="muted">{note}</span>
            </div>
          </Card>
        ))}
      </div>

      <div className="truth-table">
        <TruthRow capability="Source code" truth="Parsed, never executed" note="SparkLab: whitelisted AST only; unsupported syntax is rejected, not approximated." />
        <TruthRow capability="DataFrame result" truth="Real local computation" note="Compiled SQL runs on the shared DuckDB catalog for supported operations." />
        <TruthRow capability="Shuffle / stages / credits" truth="Simulated" note="Teaching metrics only; never presented as measured Spark telemetry." />
        <TruthRow capability="Cluster behavior" truth="Not provided" note="Executors, JVM internals and true distributed failure modes require real Spark." />
        <TruthRow capability="Polars engine" truth="Real Polars, trusted Python" note="Your file runs as local Python in the runtime's worker, which is not a sandbox; refused while trusted Python is off. Its plan is Polars' own." />
      </div>
    </section>
  );
}

function SparkRunResult({ run }: { run: SparkLabRunView }) {
  const simulation = run.simulation;
  return (
    <div className="sparklab-result">
      <div className="mosaic-run-summary">
        <Badge appearance="tint" color={run.status === "success" ? "success" : "danger"}>
          {run.status === "success" ? "success" : "rejected / failed"}
        </Badge>
        <span>{run.fileName}</span>
        <Badge appearance="outline">{run.engine === "polars" ? "Polars" : "SparkLab"}</Badge>
        <span className="muted">{run.elapsed_ms.toFixed(1)} ms local</span>
      </div>
      {run.error && <div className="error-text">{run.error.type}: {run.error.message}</div>}

      {run.result && (
        <div>
          <h4>
            Result <Badge appearance="outline" color="success">{run.engine === "polars" ? "real Polars" : "real local computation"}</Badge>
            <span className="muted">{run.result.rows.length} preview rows{run.result.truncated ? " (truncated)" : ""}</span>
          </h4>
          <ResultTable result={run.result} maxRows={12} />
        </div>
      )}

      {run.stdout && (
        <div>
          <h4>Output</h4>
          <pre className="sparklab-sql">{run.stdout}</pre>
        </div>
      )}

      {run.polarsPlan && (
        <div>
          <h4>Optimized plan <Badge appearance="outline" color="success">real Polars plan</Badge></h4>
          <pre className="sparklab-sql">{run.polarsPlan.text}</pre>
          <small className="muted">{run.polarsPlan.truth}. Read it bottom-up: the scan is last.</small>
        </div>
      )}

      {run.engine === "polars" && run.status === "success" && !run.polarsPlan && (
        <small className="muted">End the file with a LazyFrame (call .lazy() on a DataFrame) to see Polars' optimized plan.</small>
      )}

      {run.compiledSql && (
        <div>
          <h4>Compiled SQL <Badge appearance="outline">executed locally</Badge></h4>
          <pre className="sparklab-sql">{run.compiledSql}</pre>
        </div>
      )}

      {simulation && simulation.plan.length > 0 && (
        <div>
          <h4>Logical plan <Badge appearance="outline">teaching plan</Badge></h4>
          <div className="sparklab-plan">
            {simulation.plan.map(node => (
              <div key={node.id} className={`sparklab-plan-node${node.dependency === "wide" ? " wide" : ""}`}>
                <strong>{node.id}. {node.operation}{node.source ? ` · ${node.source}` : ""}</strong>
                <small>{node.dependency} dependency{node.parents.length ? ` ← ${node.parents.join(", ")}` : ""}</small>
                <small>{node.concept}</small>
              </div>
            ))}
          </div>
        </div>
      )}

      {simulation && (
        <div className="sparklab-simulated">
          <h4>
            Distributed execution <Badge appearance="tint" color="warning">SIMULATED</Badge>
            <span className="muted">{simulation.status === "modeled" ? simulation.truth : simulation.reason}</span>
          </h4>
          {simulation.status === "modeled" && (
            <>
              <div className="retail-kpis">
                <div><span>Virtual duration</span><strong>{fmt(simulation.totalDurationS)} s</strong></div>
                <div><span>Shuffle / spill</span><strong>{fmt(simulation.shuffleGb)} / {fmt(simulation.spillGb)} GB</strong></div>
                <div
                  title={simulation.exchanges?.length ? simulation.exchanges.join("; ") : "No shuffle exchange in the modeled plan"}
                >
                  <span>Shuffle exchanges</span>
                  <strong>{simulation.exchanges?.length ?? 0}</strong>
                </div>
                <div>
                  <span>{simulation.credits?.unit ?? "Credits"}{simulation.credits?.fictional ? " (fictional)" : ""}</span>
                  <strong>{fmt(simulation.credits?.total, 4)}</strong>
                </div>
              </div>
              <div className="retail-preview-wrap">
                <table className="retail-preview">
                  <thead>
                    <tr><th>Stage</th><th>Operator</th><th>Tasks</th><th>Duration (s)</th><th>Shuffle R/W (GB)</th><th>Skewed</th><th>Notes</th></tr>
                  </thead>
                  <tbody>
                    {simulation.stages.map(stage => (
                      <tr key={stage.stage_id}>
                        <td>{stage.stage_id}</td>
                        <td>{stage.operator}</td>
                        <td>{stage.task_count}</td>
                        <td>{fmt(stage.duration_s)}</td>
                        <td>{fmt(stage.shuffle_read_gb)} / {fmt(stage.shuffle_write_gb)}</td>
                        <td>{stage.skewed_tasks}</td>
                        <td>{stage.notes.join("; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <small className="muted">
                Assumptions: {simulation.assumptionsKind ?? "not reported"} · {simulation.calibration ?? "uncalibrated"}
              </small>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function fmt(value: number | undefined, digits = 2): string {
  return value === undefined ? "—" : value.toFixed(digits);
}

function TruthRow({
  capability,
  truth,
  note
}: {
  capability: string;
  truth: string;
  note: string;
}) {
  return (
    <div className="truth-row">
      <strong>{capability}</strong>
      <span>{truth}</span>
      <small>{note}</small>
    </div>
  );
}
