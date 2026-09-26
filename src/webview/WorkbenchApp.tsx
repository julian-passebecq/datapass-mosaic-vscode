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
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ModuleFamilyId, ModuleId } from "../modules";
import type {
  HostToWebviewMessage,
  RuntimeSetupProgressView,
  WebviewToHostMessage,
  WorkbenchViewState
} from "./contracts";
import { AirflowSurface } from "./AirflowSurface";
import { DbtSurface } from "./DbtSurface";
import { TerminalSurface } from "./TerminalSurface";
import { InfraSurface } from "./InfraSurface";
import { FabricSurface } from "./FabricSurface";
import { HomeSurface, RuntimeActions, runtimeTone } from "./HomeSurface";
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

/**
 * One surface per module (the module list itself is content/modules.json). A new lab adds its entry here; the
 * Record type makes a module without a surface a compile error.
 */
type SurfaceRender = (vscode: VsCodeApi, state: WorkbenchViewState) => ReactNode;
const SURFACES: Record<ModuleId, SurfaceRender> = {
  projects: (vscode, state) => <ProjectsSurface vscode={vscode} projects={state.projects} runtime={state.runtime} />,
  mosaic: (vscode, state) => (
    <MosaicSurface
      vscode={vscode}
      runtime={state.runtime}
      pythonTrust={state.pythonTrust}
      projectLayout={state.mosaicLayout}
      canPersist={state.workspace.manifestExists}
      queryHistory={state.queryHistory}
    />
  ),
  practice: (vscode, state) => (
    <PracticeSurface vscode={vscode} runtime={state.runtime}
      practice={state.practice ?? { exercises: [], progress: { exercises: {} }, canSaveProgress: false, solutions: {} }}
      focus={state.focus?.module === "practice" ? state.focus : undefined} />
  ),
  fabric: (vscode, state) => (
    <FabricSurface vscode={vscode} runtime={state.runtime} factory={state.factory}
      focus={state.focus?.module === "fabric" ? state.focus : undefined} />
  ),
  bi: (vscode, state) => (
    <BiSurface vscode={vscode} runtime={state.runtime} bi={state.bi}
      focus={state.focus?.module === "bi" ? state.focus : undefined} />
  ),
  sparklab: (vscode, state) => (
    <SparkLabSurface vscode={vscode} runtime={state.runtime} profiles={state.sparkProfiles ?? []}
      pythonTrust={state.pythonTrust} />
  ),
  pipeline: (vscode, state) => <PipelineSurface vscode={vscode} pipeline={state.pipeline} runtime={state.runtime} />,
  airflow: (vscode, state) => <AirflowSurface vscode={vscode} airflow={state.airflow} runtime={state.runtime} />,
  dbt: (vscode, state) => <DbtSurface vscode={vscode} dbt={state.dbt} runtime={state.runtime} />,
  terminal: (vscode, state) => <TerminalSurface vscode={vscode} terminal={state.terminal} runtime={state.runtime} />,
  infra: (vscode, state) => <InfraSurface vscode={vscode} infra={state.infra} runtime={state.runtime} />
};

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
  // The module last shown in each family, so switching families comes back to it.
  const lastInFamily = useRef<Partial<Record<ModuleFamilyId, ModuleId>>>({});
  if (selected) lastInFamily.current[selected.family] = selected.id;

  const isHome = state?.selectedModule === "home";
  if (!state || (!selected && !isHome)) {
    return (
      <FluentProvider theme={dark ? webDarkTheme : webLightTheme}>
        <div className="loading"><Spinner label="Loading Datapass Workbench…" /></div>
      </FluentProvider>
    );
  }

  const environment = state.runtime.environment;
  const environmentReady = environment?.status === "ready";
  const environmentSettingUp = environment?.status === "setting-up";
  const environmentStale = environment?.status === "stale";

  return (
    <FluentProvider theme={dark ? webDarkTheme : webLightTheme}>
      <div className="shell">
        <header className="topbar">
          <div>
            <div className="eyebrow">Local-first data engineering</div>
            <h1>Datapass Workbench</h1>
          </div>
          <div className="runtime-status">
            <Badge appearance="tint" color={runtimeTone(state.runtime.status)}>{state.runtime.status}</Badge>
            <RuntimeActions vscode={vscode} runtime={state.runtime} />
          </div>
        </header>

<nav className="module-tabs" aria-label="Datapass modules">
          <TabList
            className="family-tabs"
            size="small"
            selectedValue={selected?.family ?? "home"}
            onTabSelect={(_, data) => {
              const family = data.value as ModuleFamilyId | "home";
              if (family === "home") {
                vscode.postMessage({ type: "selectHome" });
                return;
              }
              const moduleId = lastInFamily.current[family] ?? state.modules.find(module => module.family === family)?.id;
              if (moduleId) vscode.postMessage({ type: "selectModule", moduleId });
            }}
          >
            <Tab value="home">Today</Tab>
            {state.families.map(family => (
              <Tab key={family.id} value={family.id} title={family.description}>{family.label}</Tab>
            ))}
          </TabList>
          {selected && (
            <TabList
              className="family-modules"
              aria-label={`${state.families.find(family => family.id === selected.family)?.label ?? ""} modules`}
              selectedValue={selected.id}
              onTabSelect={(_, data) => vscode.postMessage({ type: "selectModule", moduleId: data.value as ModuleId })}
            >
              {state.modules.filter(module => module.family === selected.family).map(module => (
                <Tab key={module.id} value={module.id}>{module.label}</Tab>
              ))}
            </TabList>
          )}
        </nav>

        <main className="content-grid">
          <section className="module-main">
            {!selected ? (
              <HomeSurface vscode={vscode} home={state.home} runtime={state.runtime}
                modules={state.modules} families={state.families} />
            ) : (
              <>
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
                {SURFACES[selected.id](vscode, state)}
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
                <StatusRow label="Environment" value={environmentStale ? "needs update" : environment?.status ?? "unknown"} />
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
                  <div className={environment.status === "error" || environmentStale ? "error-text" : "muted"}>{environment.detail}</div>
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
