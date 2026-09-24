import ReactGridLayout, {
  useContainerWidth,
  verticalCompactor,
  type Layout
} from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { Badge, Button, Text } from "@fluentui/react-components";
import type { RuntimeViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

const DEFAULT_LAYOUT: Layout = [
  { i: "sql", x: 0, y: 0, w: 6, h: 7 },
  { i: "python", x: 6, y: 0, w: 6, h: 7 },
  { i: "data", x: 0, y: 7, w: 7, h: 7 },
  { i: "notes", x: 7, y: 7, w: 5, h: 7 }
];

interface PersistedWebviewState {
  mosaicLayout?: Layout;
}

export function MosaicSurface({
  vscode,
  runtime
}: {
  vscode: VsCodeApi;
  runtime: RuntimeViewState;
}) {
  const { width, containerRef, mounted } = useContainerWidth();
  const persisted = readState(vscode);
  const layout = persisted.mosaicLayout ?? DEFAULT_LAYOUT;

  const saveLayout = (next: Layout) => {
    vscode.setState({ ...readState(vscode), mosaicLayout: next });
  };

  return (
    <section className="mosaic-surface">
      <div className="mosaic-toolbar">
        <div>
          <div className="eyebrow">Mosaic workspace</div>
          <Text size={500} weight="semibold">Arrange local data work around native VS Code files</Text>
        </div>
        <Badge appearance="outline">Polars + DuckDB</Badge>
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
                {runtime.lastRun && runtime.lastRun.language === "sql" && (
                  <div className="mosaic-run-summary">
                    <Badge
                      appearance="tint"
                      color={runtime.lastRun.status === "success" ? "success" : "danger"}
                    >
                      {runtime.lastRun.status}
                    </Badge>
                    <span>{runtime.lastRun.elapsed_ms.toFixed(1)} ms</span>
                    {runtime.lastRun.error && <small>{runtime.lastRun.error.message}</small>}
                  </div>
                )}
              </MosaicBlock>
            </div>

            <div key="python">
              <MosaicBlock title="Python / Polars" subtitle="Local transformation code; no embedded editor">
                <Button appearance="primary" size="small" onClick={() => vscode.postMessage({ type: "openScratch", kind: "python" })}>
                  Open Python scratch
                </Button>
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
                </div>
                {runtime.lastRun?.status === "success" && runtime.lastRun.result && (
                  <div className="mosaic-result-preview">
                    <div className="mosaic-result-title">
                      <strong>Last SQL result</strong>
                      <span>{runtime.lastRun.result.rows.length} preview rows</span>
                    </div>
                    <div className="retail-preview-wrap">
                      <table className="retail-preview">
                        <thead>
                          <tr>{runtime.lastRun.result.columns.map(column => <th key={column}>{column}</th>)}</tr>
                        </thead>
                        <tbody>
                          {runtime.lastRun.result.rows.slice(0, 8).map((row, index) => (
                            <tr key={index}>
                              {runtime.lastRun!.result!.columns.map(column => (
                                <td key={column}>{String(row[column] ?? "")}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
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

function readState(vscode: VsCodeApi): PersistedWebviewState {
  const value = vscode.getState();
  return value && typeof value === "object" ? value as PersistedWebviewState : {};
}
