import {
  Badge,
  Button,
  Card,
  CardHeader,
  FluentProvider,
  ProgressBar,
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
  RuntimeSetupProgressView,
  WebviewToHostMessage,
  WorkbenchViewState
} from "./contracts";
import { AirflowSurface } from "./AirflowSurface";
import { DbtSurface } from "./DbtSurface";
import { FabricSurface } from "./FabricSurface";
import { BiSurface } from "./BiSurface";
import { MosaicSurface } from "./MosaicSurface";
import { PipelineSurface } from "./PipelineSurface";
import { PracticeSurface } from "./PracticeSurface";
import { ProjectsSurface } from "./ProjectsSurface";
import { SparkLabSurface } from "./SparkLabSurface";

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

  // A project step opened a lab: show it from the top, not at the Projects page's scroll position.
  const focusSeq = state?.focus?.seq;
  useEffect(() => {
    if (focusSeq !== undefined) window.scrollTo({ top: 0 });
  }, [focusSeq]);

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

  const environment = state.runtime.environment;
  const environmentReady = environment?.status === "ready";
  const environmentSettingUp = environment?.status === "setting-up";

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
            {!environmentReady && state.runtime.status !== "running" && (
              <Button
                size="small"
                appearance="primary"
                disabled={environmentSettingUp}
                onClick={() => vscode.postMessage({ type: "setupRuntime" })}
              >
                {environmentSettingUp ? "Setting up runtime…" : "Setup runtime"}
              </Button>
            )}
            {state.runtime.status === "running" ? (
              <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "stopRuntime" })}>
                Stop runtime
              </Button>
            ) : environmentReady ? (
              <Button
                size="small"
                appearance="primary"
                disabled={state.runtime.status === "starting"}
                onClick={() => vscode.postMessage({ type: "startRuntime" })}
              >
                Start runtime
              </Button>
            ) : null}
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
              <Badge appearance="outline" className="execution-badge" title={selected.execution}>
                <span>{selected.execution}</span>
              </Badge>
            </div>

            {selected.id === "projects" ? (
              <ProjectsSurface vscode={vscode} projects={state.projects} runtime={state.runtime} />
            ) : selected.id === "mosaic" ? (
              <MosaicSurface
                vscode={vscode}
                runtime={state.runtime}
                pythonTrust={state.pythonTrust}
                projectLayout={state.mosaicLayout}
                canPersist={state.workspace.manifestExists}
              />
            ) : selected.id === "practice" ? (
              <PracticeSurface vscode={vscode} exercises={state.practice?.exercises ?? []} runtime={state.runtime}
                focus={state.focus?.module === "practice" ? state.focus : undefined} />
            ) : selected.id === "fabric" ? (
              <FabricSurface vscode={vscode} runtime={state.runtime} factory={state.factory}
                focus={state.focus?.module === "fabric" ? state.focus : undefined} />
            ) : selected.id === "bi" ? (
              <BiSurface vscode={vscode} runtime={state.runtime} bi={state.bi}
                focus={state.focus?.module === "bi" ? state.focus : undefined} />
            ) : selected.id === "sparklab" ? (
              <SparkLabSurface vscode={vscode} runtime={state.runtime} profiles={state.sparkProfiles ?? []} />
            ) : selected.id === "pipeline" ? (
              <PipelineSurface vscode={vscode} pipeline={state.pipeline} runtime={state.runtime} />
            ) : selected.id === "airflow" ? (
              <AirflowSurface vscode={vscode} airflow={state.airflow} runtime={state.runtime} />
            ) : selected.id === "dbt" ? (
              <DbtSurface vscode={vscode} dbt={state.dbt} runtime={state.runtime} />
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
                <StatusRow label="Service" value={state.runtime.status} />
                <StatusRow label="Environment" value={environment?.status ?? "unknown"} />
                {environment?.python && (
                  <div className="runtime-python" title={environment.python}>{environment.python}</div>
                )}
                {state.runtime.url && <StatusRow label="Endpoint" value={state.runtime.url} />}
                <StatusRow
                  label="Trusted Python"
                  value={state.runtime.status === "running"
                    ? (state.runtime.trustedPython ? "enabled (not sandboxed)" : "disabled")
                    : (state.pythonTrust.effective ? "enabled on next start" : "disabled")}
                />
                {state.pythonTrust.restartRequired && (
                  <div className="error-text">Restart the runtime to apply the trusted Python setting.</div>
                )}
                {environment?.progress && environmentSettingUp ? (
                  <SetupProgress progress={environment.progress} onShowLog={() => vscode.postMessage({ type: "showRuntimeLog" })} />
                ) : environment?.detail && (
                  <div className={environment.status === "error" ? "error-text" : "muted"}>{environment.detail}</div>
                )}
                {environment?.status === "error" && (
                  <Button appearance="subtle" size="small" onClick={() => vscode.postMessage({ type: "showRuntimeLog" })}>
                    Show setup log
                  </Button>
                )}
                {state.runtime.detail && <div className={state.runtime.status === "error" ? "error-text" : "muted"}>{state.runtime.detail}</div>}
                {state.runtime.status !== "running" && environmentReady && (
                  <Button
                    appearance="secondary"
                    size="small"
                    onClick={() => vscode.postMessage({ type: "setupRuntime" })}
                  >
                    Update runtime environment
                  </Button>
                )}
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

function SetupProgress({ progress, onShowLog }: { progress: RuntimeSetupProgressView; onShowLog: () => void }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="setup-progress" role="status" aria-live="polite">
      <div className="status-row">
        <strong>Step {progress.step} of {progress.totalSteps}: {progress.label}</strong>
        <span className="muted">{formatElapsed(now - progress.startedAt)}</span>
      </div>
      {/* pip and uv report no overall percentage, so the bar only shows that work is ongoing. */}
      <ProgressBar thickness="medium" />
      {progress.activity && <div className="muted setup-activity" title={progress.activity}>{progress.activity}</div>}
      <div className="muted">
        The first setup downloads DuckDB, Polars and pandas. With uv installed it takes well under a minute; with
        pip it can take several minutes, longer while antivirus scans new files.
      </div>
      <Button appearance="subtle" size="small" onClick={onShowLog}>Show setup log</Button>
    </div>
  );
}

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}m ${String(seconds % 60).padStart(2, "0")}s` : `${seconds}s`;
}

function isDarkTheme(): boolean {
  return document.body.classList.contains("vscode-dark") ||
    document.body.classList.contains("vscode-high-contrast");
}
