import { Badge, Button, Spinner, Text } from "@fluentui/react-components";
import type { ModuleFamily, WorkbenchModule } from "../modules";
import type { HomeNextStep, HomeViewState, RuntimeViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

type Props = {
  vscode: VsCodeApi;
  home: HomeViewState | undefined;
  runtime: RuntimeViewState;
  modules: readonly WorkbenchModule[];
  families: readonly ModuleFamily[];
};

/** The Today home: the next suggested step, progress from .datapass/progress.json, the runtime and every lab. */
export function HomeSurface({ vscode, home, runtime, modules, families }: Props) {
  if (!home) return <div className="loading"><Spinner label="Reading your progress…" /></div>;
  const current = home.projects.current;

  return (
    <div className="home-surface">
      <div className="module-heading">
        <div>
          <div className="eyebrow">Today</div>
          <h2>Where you are</h2>
          <p>Your progress in Projects and Practice, read from <code>.datapass/progress.json</code>, and what to do next.</p>
        </div>
      </div>

      {home.progressError && <div className="error-text home-error">{home.progressError}</div>}

      <section className="home-card home-next" aria-label="Next step">
        <div className="eyebrow">Next step</div>
        <Text size={500} weight="semibold" className="home-next-title">{home.next.title}</Text>
        <div className="muted">{home.next.detail}</div>
        <div className="button-row">
          <Button appearance="primary" onClick={() => runNext(vscode, home.next)}>{nextLabel(home.next)}</Button>
        </div>
      </section>

      <div className="home-grid">
        <section className="home-card" aria-label="Projects progress">
          <div className="home-card-head">
            <Text weight="semibold">Projects</Text>
            <span className="muted">{home.projects.completed} of {home.projects.total} complete</span>
          </div>
          {home.projects.list.map(project => (
            <div className="home-project" key={project.id}>
              <div className="status-row">
                <span className="home-project-title" title={project.title}>{project.title}</span>
                <span className="muted">{project.done}/{project.required}</span>
              </div>
              <div className="project-progress-bar" aria-hidden="true">
                <span className="segment-verified" style={{ width: `${project.percent}%` }} />
              </div>
            </div>
          ))}
          {current?.nextStep && (
            <div className="muted">In progress: {current.title}, next in {current.nextStep.moduleLabel}.</div>
          )}
          <div className="button-row">
            <Button size="small" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "projects" })}>Open Projects</Button>
          </div>
        </section>

        <section className="home-card" aria-label="Practice progress">
          <div className="home-card-head">
            <Text weight="semibold">Practice</Text>
            <span className="muted">{home.practice.solved} of {home.practice.total} solved</span>
          </div>
          <div className="project-progress-bar" aria-hidden="true">
            <span className="segment-verified" style={{ width: `${home.practice.total ? Math.round(100 * home.practice.solved / home.practice.total) : 0}%` }} />
          </div>
          <div className="stack home-stack">
            <StatusRow label="Attempted, not solved" value={String(home.practice.attempted)} />
            <StatusRow label="Reviews due today" value={String(home.practice.dueReviews)} />
          </div>
          <div className="button-row">
            <Button size="small" onClick={() => vscode.postMessage({ type: "selectModule", moduleId: "practice" })}>Open Practice</Button>
          </div>
        </section>

        <section className="home-card" aria-label="Runtime">
          <div className="home-card-head">
            <Text weight="semibold">Local runtime</Text>
            <Badge appearance="tint" color={runtimeTone(runtime.status)}>{runtime.status}</Badge>
          </div>
          <div className="muted">
            {runtime.status === "running"
              ? "Running: labs can execute and grade on your local catalog."
              : runtime.environment?.status === "ready"
                ? "Set up. Start it to run SQL, grade exercises and verify project steps."
                : "Not set up yet. The first setup installs DuckDB, Polars and pandas in a managed environment."}
          </div>
          <div className="button-row"><RuntimeActions vscode={vscode} runtime={runtime} /></div>
        </section>
      </div>

      {families.map(family => (
        <section className="home-family" key={family.id} aria-label={family.label}>
          <div className="home-card-head">
            <Text weight="semibold">{family.label}</Text>
            <span className="muted">{family.description}</span>
          </div>
          <div className="home-modules">
            {modules.filter(module => module.family === family.id).map(module => (
              <button
                type="button"
                className="home-module"
                key={module.id}
                title={module.description}
                onClick={() => vscode.postMessage({ type: "selectModule", moduleId: module.id })}
              >
                <strong>{module.label}</strong>
                <span className="muted">{module.execution}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** Setup, update, start or stop the runtime: the same buttons in the top bar and on Today. */
export function RuntimeActions({ vscode, runtime }: { vscode: VsCodeApi; runtime: RuntimeViewState }) {
  const environment = runtime.environment;
  const ready = environment?.status === "ready";
  const settingUp = environment?.status === "setting-up";
  const stale = environment?.status === "stale";
  return (
    <>
      {!ready && runtime.status !== "running" && (
        <Button size="small" appearance="primary" disabled={settingUp} onClick={() => vscode.postMessage({ type: "setupRuntime" })}>
          {settingUp ? "Setting up runtime…" : stale ? "Update runtime" : "Setup runtime"}
        </Button>
      )}
      {runtime.status === "running" ? (
        <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "stopRuntime" })}>Stop runtime</Button>
      ) : ready ? (
        <Button size="small" appearance="primary" disabled={runtime.status === "starting"}
          onClick={() => vscode.postMessage({ type: "startRuntime" })}>
          Start runtime
        </Button>
      ) : null}
    </>
  );
}

export function runtimeTone(status: RuntimeViewState["status"]): "success" | "danger" | "warning" | "informative" {
  return status === "running" ? "success" : status === "error" ? "danger" : status === "starting" ? "warning" : "informative";
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return <div className="status-row"><span className="muted">{label}</span><strong>{value}</strong></div>;
}

function nextLabel(next: HomeNextStep): string {
  switch (next.kind) {
    case "open-folder": return "Open folder";
    case "project-step": return "Open this step";
    case "reviews": return "Start reviews";
    case "start-project": return "Open the project";
    case "practice": return "Open Practice";
  }
}

function runNext(vscode: VsCodeApi, next: HomeNextStep): void {
  switch (next.kind) {
    case "open-folder":
      vscode.postMessage({ type: "openFolder" });
      return;
    case "project-step":
      vscode.postMessage({ type: "openProjectStep", projectId: next.projectId, stepId: next.stepId });
      return;
    case "start-project":
      vscode.postMessage({ type: "selectModule", moduleId: "projects" });
      return;
    case "reviews":
    case "practice":
      vscode.postMessage({ type: "selectModule", moduleId: "practice" });
  }
}
