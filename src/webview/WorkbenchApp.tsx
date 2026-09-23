import {
  Badge,
  Button,
  Card,
  CardHeader,
  FluentProvider,
  Spinner,
  Tab,
  TabList,
  Text,
  webDarkTheme,
  webLightTheme
} from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import type {
  HostToWebviewMessage,
  WebviewToHostMessage,
  WorkbenchViewState
} from "./contracts";
import { MosaicSurface } from "./MosaicSurface";
import { PipelineSurface } from "./PipelineSurface";
import { PracticeSurface } from "./PracticeSurface";

export interface VsCodeApi {
  postMessage(message: WebviewToHostMessage): void;
  getState(): unknown;
  setState(state: unknown): void;
}

export function WorkbenchApp({ vscode }: { vscode: VsCodeApi }) {
  const [state, setState] = useState<WorkbenchViewState | null>(null);
  const [dark, setDark] = useState(isDarkTheme());

  useEffect(() => {
    const onMessage = (event: MessageEvent<HostToWebviewMessage>) => {
      if (event.data?.type === "state") setState(event.data.state);
    };
    window.addEventListener("message", onMessage);

    const observer = new MutationObserver(() => setDark(isDarkTheme()));
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });

    vscode.postMessage({ type: "ready" });
    return () => {
      window.removeEventListener("message", onMessage);
      observer.disconnect();
    };
  }, [vscode]);

  const selected = useMemo(
    () => state?.modules.find(module => module.id === state.selectedModule),
    [state]
  );

  if (!state || !selected) {
    return (
      <FluentProvider theme={dark ? webDarkTheme : webLightTheme}>
        <div className="loading"><Spinner label="Loading Datapass Workbench…" /></div>
      </FluentProvider>
    );
  }

  const runtimeTone =
    state.runtime.status === "running"
      ? "success"
      : state.runtime.status === "error"
        ? "danger"
        : state.runtime.status === "starting"
          ? "warning"
          : "informative";

  return (
    <FluentProvider theme={dark ? webDarkTheme : webLightTheme}>
      <div className="shell">
        <header className="topbar">
          <div>
            <div className="eyebrow">Local-first data engineering</div>
            <h1>Datapass Workbench</h1>
          </div>
          <div className="runtime-status">
            <Badge appearance="tint" color={runtimeTone}>{state.runtime.status}</Badge>
            {state.runtime.status === "running" ? (
              <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "stopRuntime" })}>
                Stop runtime
              </Button>
            ) : (
              <Button size="small" appearance="primary" disabled={state.runtime.status === "starting"} onClick={() => vscode.postMessage({ type: "startRuntime" })}>
                Start runtime
              </Button>
            )}
          </div>
        </header>

        <nav className="module-tabs" aria-label="Datapass modules">
          <TabList
            selectedValue={state.selectedModule}
            onTabSelect={(_, data) => vscode.postMessage({ type: "selectModule", moduleId: data.value as typeof state.selectedModule })}
          >
            {state.modules.map(module => (
              <Tab key={module.id} value={module.id}>{module.label}</Tab>
            ))}
          </TabList>
        </nav>

        <main className="content-grid">
          <section className="module-main">
            <div className="module-heading">
              <div>
                <div className="eyebrow">{selected.mode} execution model</div>
                <h2>{selected.label}</h2>
                <p>{selected.description}</p>
              </div>
              <Badge appearance="outline">{selected.execution}</Badge>
            </div>

            {selected.id === "mosaic" ? (
              <MosaicSurface vscode={vscode} runtime={state.runtime} />
            ) : selected.id === "practice" ? (
              <PracticeSurface vscode={vscode} exercises={state.practice?.exercises ?? []} />
            ) : selected.id === "pipeline" ? (
              <PipelineSurface vscode={vscode} pipeline={state.pipeline} />
            ) : (
              <>
                <div className="feature-grid">
                  {selected.highlights.map(highlight => (
                    <Card key={highlight}>
                      <CardHeader header={<Text weight="semibold">{highlight}</Text>} />
                    </Card>
                  ))}
                </div>

                <Card className="surface-card">
                  <CardHeader
                    header={<Text size={500} weight="semibold">VS Code-native boundary</Text>}
                    description={<Text>Files, editors, terminals, Git and Jupyter stay native. Datapass adds the teaching surface and local execution services.</Text>}
                  />
                  <div className="button-row">
                    <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "openTerminal" })}>Open terminal</Button>
                  </div>
                </Card>
              </>
            )}
          </section>

          <aside className="side-column">
            <Card>
              <CardHeader
                header={<Text weight="semibold">Workspace</Text>}
                description={<Text>{state.workspace.folderName ?? "No folder open"}</Text>}
              />
              <div className="stack">
                <StatusRow label="Project manifest" value={
                  !state.workspace.manifestExists ? "Not created" :
                  state.workspace.manifestValid ? "Valid" : "Needs attention"
                } />
                {state.workspace.projectTitle && <StatusRow label="Project" value={state.workspace.projectTitle} />}
                {state.workspace.errors.map(error => <div className="error-text" key={error}>{error}</div>)}
                <div className="button-row">
                  {!state.workspace.manifestExists ? (
                    <Button appearance="primary" onClick={() => vscode.postMessage({ type: "createManifest" })}>Create .datapass project</Button>
                  ) : (
                    <Button appearance="secondary" onClick={() => vscode.postMessage({ type: "openManifest" })}>Open project manifest</Button>
                  )}
                </div>
              </div>
            </Card>

            <Card>
              <CardHeader header={<Text weight="semibold">Local runtime</Text>} />
              <div className="stack">
                <StatusRow label="Status" value={state.runtime.status} />
                {state.runtime.url && <StatusRow label="Endpoint" value={state.runtime.url} />}
                {state.runtime.detail && <div className={state.runtime.status === "error" ? "error-text" : "muted"}>{state.runtime.detail}</div>}
              </div>
            </Card>
          </aside>
        </main>
      </div>
    </FluentProvider>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return <div className="status-row"><span className="muted">{label}</span><strong>{value}</strong></div>;
}

function isDarkTheme(): boolean {
  return document.body.classList.contains("vscode-dark") ||
    document.body.classList.contains("vscode-high-contrast");
}
