import { Badge, Button, Card, CardHeader, Tab, TabList, Text } from "@fluentui/react-components";
import { useState } from "react";
import type { FactoryViewState, RuntimeViewState } from "./contracts";
import { FactoryPipelines } from "./FactoryPipelines";
import type { VsCodeApi } from "./WorkbenchApp";

/** Cloud Lab: Fabric / Azure Data Factory / Synapse pipelines and the local lakehouse, all simulated locally. */
export function FabricSurface({
  vscode,
  runtime,
  factory
}: {
  vscode: VsCodeApi;
  runtime: RuntimeViewState;
  factory: FactoryViewState | undefined;
}) {
  const running = runtime.status === "running";
  const [tab, setTab] = useState<"pipelines" | "lakehouse">("pipelines");

  return (
    <section className="lab-surface">
      <div className="lab-toolbar">
        <div>
          <div className="eyebrow">Simulated cloud data platform · runs on this machine</div>
          <Text size={500} weight="semibold">Pipelines, notebooks and stored procedures for Fabric, Azure Data Factory and Synapse</Text>
        </div>
        <Badge appearance="tint" color={running ? "success" : "informative"}>
          {running ? "local runtime connected" : "runtime stopped"}
        </Badge>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, data) => setTab(data.value as typeof tab)} size="small">
        <Tab value="pipelines">Pipelines</Tab>
        <Tab value="lakehouse">Lakehouse and notebooks</Tab>
      </TabList>
      {tab === "pipelines"
        ? <FactoryPipelines vscode={vscode} factory={factory} runtime={runtime} />
        : <LakehouseOverview vscode={vscode} runtime={runtime} />}
    </section>
  );
}

function LakehouseOverview({ vscode, runtime }: { vscode: VsCodeApi; runtime: RuntimeViewState }) {
  const running = runtime.status === "running";
  const retailDemo = runtime.retailDemo;

  return (
    <>
      <div className="demo-banner">
        <div>
          <strong>Start with a connected sample</strong>
          <span>Create a small retail project spanning source data, SQL/Polars, pipeline, Airflow and dbt.</span>
        </div>
        <div className="button-row">
          <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "createRetailDemo" })}>
            Create / repair demo files
          </Button>
          <Button
            appearance="primary"
            disabled={!running}
            onClick={() => vscode.postMessage({ type: "runRetailDemo" })}
          >
            Run local medallion flow
          </Button>
        </div>
      </div>

      <div className="lab-flow" aria-label="Cloud Lab learning flow">
        <FlowStep index="1" title="Lakehouse" detail="DuckDB / DuckLake files and tables" truth="Real local" />
        <FlowArrow />
        <FlowStep index="2" title="Notebook" detail="Python, SQL and bounded Spark practice" truth="Hybrid" />
        <FlowArrow />
        <FlowStep index="3" title="Pipeline" detail="Orchestration and activity dependencies" truth="Simulated" />
        <FlowArrow />
        <FlowStep index="4" title="Gold / KPI" detail="Query outputs with explicit provenance" truth="Real local" />
      </div>

      <div className="lab-card-grid">
        <Card className="lab-card">
          <CardHeader
            header={<Text weight="semibold">Notebook workspace</Text>}
            description={<Text>Use native VS Code files for code. Cloud Lab supplies the teaching workflow, not another editor.</Text>}
          />
          <div className="lab-card-body">
            <div className="button-row">
              <Button appearance="primary" size="small" onClick={() => vscode.postMessage({ type: "openScratch", kind: "python" })}>
                Open Python notebook scratch
              </Button>
              <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "openScratch", kind: "sql" })}>
                Open SQL scratch
              </Button>
            </div>
          </div>
        </Card>

        <Card className="lab-card">
          <CardHeader
            header={<Text weight="semibold">Spark exercise path</Text>}
            description={<Text>Spark semantics are intentionally bounded and labeled. Unsupported distributed behavior must not be faked silently.</Text>}
          />
          <div className="lab-card-body">
            <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "sparklab" })}>
              Open SparkLab
            </Button>
          </div>
        </Card>

        <Card className="lab-card">
          <CardHeader
            header={<Text weight="semibold">Pipeline orchestration</Text>}
            description={<Text>Design notebook, SQL, copy-like and validation activities on the shared graph foundation.</Text>}
          />
          <div className="lab-card-body">
            <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "pipeline" })}>
              Open Pipeline Lab
            </Button>
          </div>
        </Card>
      </div>

      {retailDemo && (
        <div className="retail-result">
          <div className="retail-result-header">
            <div>
              <div className="eyebrow">Executed result</div>
              <Text size={500} weight="semibold">Retail medallion run</Text>
              <div className="muted">{retailDemo.truth} · {retailDemo.database_path}</div>
            </div>
            <Badge appearance="tint" color="success">completed</Badge>
          </div>

          <div className="retail-stage-grid">
            {retailDemo.stages.map(stage => (
              <div className="retail-stage" key={stage.id}>
                <span>{stage.engine}</span>
                <strong>{stage.label}</strong>
                <small>{stage.rows} rows</small>
              </div>
            ))}
          </div>

          <div className="retail-kpis">
            <div><span>Silver rows</span><strong>{retailDemo.polars_quality.rows}</strong></div>
            <div><span>Customers</span><strong>{retailDemo.polars_quality.customers}</strong></div>
            <div><span>Revenue</span><strong>{retailDemo.polars_quality.revenue.toFixed(2)}</strong></div>
          </div>

          <div className="retail-preview-wrap">
            <table className="retail-preview">
              <thead>
                <tr>{retailDemo.preview.columns.map(column => <th key={column}>{column}</th>)}</tr>
              </thead>
              <tbody>
                {retailDemo.preview.rows.map((row, index) => (
                  <tr key={index}>
                    {retailDemo.preview.columns.map(column => (
                      <td key={column}>{String(row[column] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="truth-table">
        <TruthRow capability="DuckDB SQL" truth="Real local" note="Executed by local analytical engine." />
        <TruthRow capability="DuckLake storage" truth="Real local" note="Local lakehouse profile; not OneLake." />
        <TruthRow capability="Fabric notebook chrome" truth="Simulated UI" note="Teaching experience only; no Fabric workspace is required." />
        <TruthRow capability="PySpark" truth="Bounded simulation" note="SparkLab covers an explicit DataFrame subset." />
        <TruthRow capability="Pipeline service" truth="Deterministic simulation" note="Data Factory orchestration semantics for Fabric, Azure Data Factory and Synapse pipeline JSON; no cloud execution." />
        <TruthRow capability="Pipeline activities" truth="Real local where supported" note="Copy, Lookup, Script, stored procedures and notebooks run on the local catalog (DuckDB, SparkLab); other activities follow the scenario." />
      </div>
    </>
  );
}

function FlowStep({
  index,
  title,
  detail,
  truth
}: {
  index: string;
  title: string;
  detail: string;
  truth: string;
}) {
  return (
    <div className="lab-flow-step">
      <span className="lab-flow-index">{index}</span>
      <div>
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
      <Badge appearance="outline">{truth}</Badge>
    </div>
  );
}

function FlowArrow() {
  return <span className="lab-flow-arrow" aria-hidden="true">→</span>;
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
