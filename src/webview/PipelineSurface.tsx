import { Badge, Button, Text } from "@fluentui/react-components";
import type { PipelineViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { SharedGraphCanvas } from "./SharedGraphCanvas";

export function PipelineSurface({
  vscode,
  pipeline
}: {
  vscode: VsCodeApi;
  pipeline: PipelineViewState | undefined;
}) {
  if (!pipeline) {
    return <div className="empty-state">Pipeline state is not available.</div>;
  }

  const tone =
    pipeline.compileStatus === "valid"
      ? "success"
      : pipeline.compileStatus === "invalid" || pipeline.compileStatus === "error"
        ? "danger"
        : pipeline.compileStatus === "runtime-required"
          ? "warning"
          : "informative";

  return (
    <section className="pipeline-surface">
      <div className="pipeline-toolbar">
        <div>
          <div className="eyebrow">Source → bounded AST → graph</div>
          <Text size={500} weight="semibold">{pipeline.path}</Text>
        </div>
        <div className="button-row">
          <Badge appearance="tint" color={tone}>{pipeline.compileStatus}</Badge>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "openPipelineSource" })}>
            {pipeline.exists ? "Open source" : "Create starter"}
          </Button>
          <Button appearance="secondary" size="small" onClick={() => vscode.postMessage({ type: "refreshPipeline" })}>
            Refresh graph
          </Button>
        </div>
      </div>

      <div className="pipeline-facts">
        <span><strong>Truth:</strong> {pipeline.truth ?? "not compiled"}</span>
        <span><strong>Schedule:</strong> {pipeline.schedule ?? "manual / none"}</span>
        <span><strong>Tasks:</strong> {pipeline.graph.nodes.length}</span>
      </div>

      {pipeline.compileStatus === "runtime-required" && (
        <div className="pipeline-notice">
          Start the local runtime to compile this design. The compiler parses source but never executes it.
        </div>
      )}

      {pipeline.diagnostics.length > 0 && (
        <div className="pipeline-diagnostics" role="alert">
          {pipeline.diagnostics.map((diagnostic, index) => (
            <div key={`${diagnostic.line}-${diagnostic.column}-${index}`}>
              Line {diagnostic.line}, column {diagnostic.column}: {diagnostic.message}
            </div>
          ))}
        </div>
      )}

      <SharedGraphCanvas
        graph={pipeline.graph}
        vscode={vscode}
        storageKey="pipeline-main"
      />

      <p className="muted pipeline-footnote">
        Dragging nodes changes this visual view only. Edit dependency expressions in the native source file to change pipeline semantics.
      </p>
    </section>
  );
}
