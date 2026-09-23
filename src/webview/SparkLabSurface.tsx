import { Badge, Button, Card, CardHeader, Text } from "@fluentui/react-components";
import type { RuntimeViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

const OPERATIONS = [
  ["Read", "spark.table(), parquet()", "Supported teaching sources"],
  ["Rows", "filter(), where(), select()", "Core DataFrame transformations"],
  ["Shape", "withColumn(), drop(), distinct()", "Bounded semantic emulation"],
  ["Join", "join()", "Supported exercise patterns only"],
  ["Group", "groupBy().agg()", "Common aggregation concepts"],
  ["Window", "partition/order/rank patterns", "Exercise-pack dependent"],
  ["Sort", "orderBy(), sort()", "Local deterministic results"],
  ["Limit", "limit()", "Bounded collection"]
] as const;

export function SparkLabSurface({
  vscode,
  runtime
}: {
  vscode: VsCodeApi;
  runtime: RuntimeViewState;
}) {
  return (
    <section className="lab-surface">
      <div className="lab-toolbar">
        <div>
          <div className="eyebrow">PySpark concepts without a cluster</div>
          <Text size={500} weight="semibold">SparkLab / ZilaCode</Text>
        </div>
        <Badge appearance="tint" color={runtime.status === "running" ? "success" : "informative"}>
          {runtime.status === "running" ? "runtime ready" : "start local runtime for execution"}
        </Badge>
      </div>

      <div className="sparklab-hero">
        <div>
          <h3>Learn DataFrame semantics first</h3>
          <p>
            SparkLab maps a deliberately limited PySpark-style API to local execution and simulated physical metrics.
            It is not a Spark cluster and does not claim distributed parity.
          </p>
        </div>
        <div className="button-row">
          <Button appearance="primary" onClick={() => vscode.postMessage({ type: "openScratch", kind: "python" })}>
            Open Spark scratch file
          </Button>
          <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>
            Browse Spark exercises
          </Button>
        </div>
      </div>

      <div className="spark-operation-grid">
        {OPERATIONS.map(([group, api, note]) => (
          <Card key={group} className="spark-operation-card">
            <CardHeader
              header={<Text weight="semibold">{group}</Text>}
              description={<Text>{api}</Text>}
            />
            <div className="lab-card-body"><span className="muted">{note}</span></div>
          </Card>
        ))}
      </div>

      <div className="truth-table">
        <TruthRow capability="DataFrame result semantics" truth="Bounded semantic emulation" note="Validated only for supported operations and fixtures." />
        <TruthRow capability="Physical engine" truth="Local" note="DuckDB/local engines may execute supported work." />
        <TruthRow capability="Shuffle / stages / credits" truth="Simulated" note="Teaching metrics only; never presented as measured Spark telemetry." />
        <TruthRow capability="Cluster behavior" truth="Not provided" note="Executors, JVM internals and true distributed failure modes require real Spark." />
      </div>
    </section>
  );
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
