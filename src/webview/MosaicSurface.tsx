import ReactGridLayout, {
  useContainerWidth,
  verticalCompactor,
  type Layout
} from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { Badge, Button, Text } from "@fluentui/react-components";
import { useEffect, useRef, useState } from "react";
import { MOSAIC_DEFAULT_LAYOUT, type MosaicLayoutItem } from "../platform/mosaicLayout";
import type { PythonTrustView, RuntimeViewState } from "./contracts";
import { ResultTable } from "./ResultTable";
import { TrustedPythonControl } from "./TrustedPythonControl";
import type { VsCodeApi } from "./WorkbenchApp";

const DEFAULT_LAYOUT: Layout = MOSAIC_DEFAULT_LAYOUT.map(item => ({ ...item }));

interface PersistedWebviewState {
  mosaicLayout?: Layout;
}

export function MosaicSurface({
  vscode,
  runtime,
  pythonTrust,
  projectLayout,
  canPersist
}: {
  vscode: VsCodeApi;
  runtime: RuntimeViewState;
  pythonTrust: PythonTrustView;
  projectLayout?: readonly MosaicLayoutItem[];
  canPersist: boolean;
}) {
  const { width, containerRef, mounted } = useContainerWidth();
  // Precedence: project file (.datapass/mosaic.json) > webview cache > default.
  const [layout, setLayout] = useState<Layout>(
    () => (projectLayout as Layout | undefined) ?? readState(vscode).mosaicLayout ?? DEFAULT_LAYOUT
  );
  const projectKey = projectLayout ? JSON.stringify(projectLayout) : "";
  useEffect(() => {
    if (projectLayout) setLayout(projectLayout as Layout);
  }, [projectKey]);

  // One-time migration of a layout that previously lived only in webview state.
  const migrated = useRef(false);
  useEffect(() => {
    const cached = readState(vscode).mosaicLayout;
    if (!migrated.current && canPersist && !projectLayout && cached) {
      migrated.current = true;
      vscode.postMessage({ type: "saveMosaicLayout", layout: toGeometry(cached) });
    }
  }, [canPersist, projectKey]);

  const pythonRunnable = runtime.status === "running" && runtime.trustedPython === true;
  const pythonBlockedReason = runtime.status !== "running"
    ? "Start the runtime to run Python."
    : !pythonTrust.effective
      ? "Python/Polars files are not executed until trusted local Python is enabled."
      : runtime.trustedPython !== true
        ? "Restart the runtime to apply trusted local Python."
        : undefined;
  const lastRun = runtime.lastRun;

  const saveLayout = (next: Layout) => {
    setLayout(next);
    vscode.setState({ ...readState(vscode), mosaicLayout: next });
    if (canPersist) vscode.postMessage({ type: "saveMosaicLayout", layout: toGeometry(next) });
  };

  return (
    <section className="mosaic-surface">
      <div className="mosaic-toolbar">
        <div>
          <div className="eyebrow">Mosaic workspace</div>
          <Text size={500} weight="semibold">Arrange local data work around native VS Code files</Text>
        </div>
        <div className="button-row">
          <span className="muted" title={canPersist ? ".datapass/mosaic.json" : "Create a .datapass project to keep the layout with the project"}>
            {canPersist ? "Layout saved to .datapass/mosaic.json" : "Layout kept in this window only"}
          </span>
          <Badge appearance="outline">DuckDB SQL · trusted Python/Polars</Badge>
        </div>
      </div>

      <div ref={containerRef} className="mosaic-canvas">
        {mounted && (
          <ReactGridLayout
            width={width}
            layout={layout}
            onDragStop={saveLayout}
            onResizeStop={saveLayout}
            gridConfig={{
              cols: 12,
              rowHeight: 24,
              margin: [12, 12],
              containerPadding: [0, 0]
            }}
            dragConfig={{ enabled: true, handle: ".mosaic-drag-handle" }}
            resizeConfig={{ enabled: true, handles: ["se", "s", "e"] }}
            compactor={verticalCompactor}
          >
            <div key="sql">
              <MosaicBlock title="SQL workspace" subtitle="DuckDB SQL in a real VS Code file">
                <div className="button-row">
                  <Button appearance="primary" size="small" onClick={() => vscode.postMessage({ type: "openScratch", kind: "sql" })}>
                    Open SQL scratch
                  </Button>
                  <Button
                    appearance="secondary"
                    size="small"
                    disabled={runtime.status !== "running"}
                    onClick={() => vscode.postMessage({ type: "runActiveSql" })}
                  >
                    Run active SQL
                  </Button>
                </div>
                {lastRun && lastRun.language === "sql" && <RunSummary run={lastRun} />}
              </MosaicBlock>
            </div>

            <div key="python">
              <MosaicBlock title="Python / Polars" subtitle="Trusted local code in a real VS Code file">
                <div className="button-row">
                  <Button appearance="primary" size="small" onClick={() => vscode.postMessage({ type: "openScratch", kind: "python" })}>
                    Open Python scratch
                  </Button>
                  <Button
                    appearance="secondary"
                    size="small"
                    disabled={!pythonRunnable}
                    title={pythonBlockedReason}
                    onClick={() => vscode.postMessage({ type: "runActivePython" })}
                  >
                    Run active Python
                  </Button>
                </div>
                {pythonBlockedReason && <small className="muted">{pythonBlockedReason}</small>}
                <TrustedPythonControl vscode={vscode} trust={pythonTrust} />
                {lastRun && lastRun.language === "python" && <RunSummary run={lastRun} />}
              </MosaicBlock>
            </div>

            <div key="data">
              <MosaicBlock title="Local data runtime" subtitle="DuckDB / DuckLake catalog and previews">
                <div className="mosaic-runtime-line">
                  <Badge appearance="tint" color={runtime.status === "running" ? "success" : runtime.status === "error" ? "danger" : "informative"}>
                    {runtime.status}
                  </Badge>
                  <span className="muted">{runtime.detail ?? "Start the Datapass runtime from the header."}</span>
                  <Button
                    appearance="subtle"
                    size="small"
                    disabled={runtime.status !== "running"}
                    onClick={() => vscode.postMessage({ type: "refreshCatalog" })}
                  >
                    Refresh
                  </Button>
                  <Button
                    appearance="secondary"
                    size="small"
                    disabled={runtime.status !== "running"}
                    title={runtime.status === "running"
                      ? "Create a new bronze table from a CSV file (up to 1 MB / 5,000 rows; never overwrites)"
                      : "Start the runtime to import a CSV."}
                    onClick={() => vscode.postMessage({ type: "importCsv" })}
                  >
                    Import CSV…
                  </Button>
                </div>
                {runtime.csvImport && (
                  <div className="mosaic-result-preview">
                    <div className="mosaic-result-title">
                      <strong>Imported {runtime.csvImport.fileName} → {runtime.csvImport.asset}</strong>
                      <span>{runtime.csvImport.rows_imported} rows · {runtime.csvImport.schema.length} text columns</span>
                    </div>
                    <small className="muted" title={`sha256 ${runtime.csvImport.sha256}`}>
                      Real local import. Every column is text; CAST in SQL, e.g. <code>CAST(amount AS DOUBLE)</code>.
                    </small>
                    <ResultTable result={runtime.csvImport.result} />
                  </div>
                )}
                {lastRun?.status === "success" && (lastRun.result || lastRun.stdout) && (
                  <div className="mosaic-result-preview">
                    <div className="mosaic-result-title">
                      <strong>Last {lastRun.language === "python" ? "Python" : "SQL"} result</strong>
                      {lastRun.result && <span>{lastRun.result.rows.length} preview rows</span>}
                    </div>
                    {lastRun.stdout && <pre className="run-stdout">{lastRun.stdout}</pre>}
                    {lastRun.result && <ResultTable result={lastRun.result} />}
                  </div>
                )}
                {runtime.catalog && runtime.catalog.length > 0 ? (
                  <div className="catalog-list">
                    {runtime.catalog.map(asset => (
                      <div className="catalog-row" key={asset.name}>
                        <div>
                          <strong>{asset.name}</strong>
                          <small>{asset.producer ?? "local catalog"}</small>
                        </div>
                        <span>{asset.row_count} rows</span>
                        <Badge appearance="outline" color={asset.fresh ? "success" : "informative"}>
                          {asset.fresh ? "fresh" : "untracked"}
                        </Badge>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="muted catalog-empty">
                    {runtime.status === "running" ? "No catalog assets reported." : "Start the runtime to load the catalog."}
                  </div>
                )}
              </MosaicBlock>
            </div>

            <div key="notes">
              <MosaicBlock title="Notes" subtitle="Project-local Markdown notes">
                <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "openScratch", kind: "notes" })}>
                  Open notes
                </Button>
              </MosaicBlock>
            </div>
          </ReactGridLayout>
        )}
      </div>
    </section>
  );
}

function RunSummary({ run }: { run: NonNullable<RuntimeViewState["lastRun"]> }) {
  return (
    <div className="mosaic-run-summary">
      <Badge appearance="tint" color={run.status === "success" ? "success" : "danger"}>
        {run.status}
      </Badge>
      <span>{run.elapsed_ms.toFixed(1)} ms</span>
      {run.error && <small>{run.error.message}</small>}
    </div>
  );
}

function MosaicBlock({
  title,
  subtitle,
  children
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mosaic-block">
      <div className="mosaic-drag-handle" title="Drag block">
        <span>⋮⋮</span>
        <div>
          <strong>{title}</strong>
          <small>{subtitle}</small>
        </div>
      </div>
      <div className="mosaic-block-body">{children}</div>
    </div>
  );
}

function toGeometry(layout: Layout): { i: string; x: number; y: number; w: number; h: number }[] {
  return layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }));
}

function readState(vscode: VsCodeApi): PersistedWebviewState {
  const value = vscode.getState();
  return value && typeof value === "object" ? value as PersistedWebviewState : {};
}
