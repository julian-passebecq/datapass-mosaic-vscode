import { Badge, Button, Text } from "@fluentui/react-components";
import type { DbtViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { SharedGraphCanvas } from "./SharedGraphCanvas";

export function DbtSurface({
  vscode,
  dbt
}: {
  vscode: VsCodeApi;
  dbt: DbtViewState | undefined;
}) {
  if (!dbt) return <div className="empty-state">dbt state is not available.</div>;

  return (
    <section className="dbt-surface">
      <div className="dbt-toolbar">
        <div>
          <div className="eyebrow">Real dbt project · artifact-first lineage</div>
          <Text size={500} weight="semibold">{dbt.path}</Text>
        </div>
        <div className="button-row">
          <Badge appearance="tint" color={dbt.cli.available && dbt.cli.adapterAvailable ? "success" : "warning"}>
            {!dbt.cli.available
              ? "dbt CLI missing"
              : dbt.cli.adapterAvailable
                ? "dbt + DuckDB ready"
                : "dbt-duckdb missing"}
          </Badge>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "openDbtProject" })}>
            {dbt.exists ? "Open project" : "Create retail sample"}
          </Button>
          <Button appearance="primary" size="small" disabled={!dbt.exists || !dbt.cli.available || !dbt.cli.adapterAvailable} onClick={() => vscode.postMessage({ type: "runDbtBuild" })}>
            Run dbt build
          </Button>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "refreshDbt" })}>
            Refresh
          </Button>
        </div>
      </div>

      <div className="pipeline-facts">
        <span><strong>Project:</strong> {dbt.projectName ?? "unknown"}</span>
        <span><strong>Models:</strong> {dbt.modelCount}</span>
        <span><strong>Seeds:</strong> {dbt.seedCount}</span>
        <span><strong>Lineage:</strong> {dbt.lineageSource}</span>
        {dbt.cli.version && <span><strong>Core:</strong> {dbt.cli.version}</span>}
        {dbt.cli.adapterVersion && <span><strong>DuckDB:</strong> {dbt.cli.adapterVersion}</span>}
      </div>

      {dbt.errors.length > 0 && (
        <div className="pipeline-diagnostics" role="alert">
          {dbt.errors.map((error, index) => <div key={index}>{error}</div>)}
        </div>
      )}

      {(!dbt.cli.available || !dbt.cli.adapterAvailable) && dbt.exists && (
        <div className="pipeline-notice">
          Static lineage works without execution. Install both dbt Core and dbt-duckdb to run this DuckDB project; Datapass will then prefer target/manifest.json.
          {dbt.cli.detail ? ` ${dbt.cli.detail}` : ""}
        </div>
      )}

      <SharedGraphCanvas graph={dbt.graph} vscode={vscode} storageKey="dbt-lineage" />

      <p className="muted pipeline-footnote">
        Manifest lineage is authoritative after a real dbt run. Static lineage only reads project-local ref()/source() declarations and seeds.
      </p>
    </section>
  );
}
