import { Badge, Button, Checkbox, Spinner, Text } from "@fluentui/react-components";
import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  LEVEL_LABELS,
  TRUTH_LABELS,
  parseMarkdown,
  unverifiedSteps,
  type CheckResultRecord,
  type InlineSpan,
  type ProjectStepView,
  type ProjectTruth,
  type ProjectView
} from "../platform/projects";
import type { ProjectsHostState, RuntimeViewState } from "./contracts";
import type { ProjectsViewState } from "../platform/projects";
import type { VsCodeApi } from "./WorkbenchApp";

type Props = { vscode: VsCodeApi; projects: (ProjectsViewState & ProjectsHostState) | undefined; runtime: RuntimeViewState };

const STATE_LABELS: Record<ProjectStepView["state"], string> = {
  verified: "verified",
  manual: "ticked by hand",
  failed: "to redo",
  todo: "to do"
};
const STATE_COLORS = { verified: "success", manual: "brand", failed: "danger", todo: "subtle" } as const;
const TRUTH_COLORS: Record<ProjectTruth, "brand" | "warning" | "informative" | "severe" | "subtle"> = {
  real: "brand",
  simulated: "warning",
  emulation: "informative",
  hybrid: "severe",
  static: "subtle"
};
const TRUTH_TITLES: Record<ProjectTruth, string> = {
  real: "Real local execution (DuckDB, trusted Python)",
  simulated: "Simulation: orchestration, scheduler or a teaching model of the physical design",
  emulation: "Bounded emulation of a product (SparkLab, dbt emulation): results are computed locally",
  hybrid: "Simulated orchestration, activities really run on the local catalog",
  static: "Static analysis of the SQL text: nothing runs"
};

function savedSelection(vscode: VsCodeApi): string | undefined {
  const state = vscode.getState();
  const value = state && typeof state === "object" ? (state as Record<string, unknown>).projectsSelected : undefined;
  return typeof value === "string" ? value : undefined;
}

/** Projects: end-to-end stories across the labs, with verified steps apart from ticks by hand. */
export function ProjectsSurface({ vscode, projects, runtime }: Props) {
  const [selectedId, setSelectedId] = useState<string | undefined>(() => savedSelection(vscode));
  const select = (id: string | undefined) => {
    setSelectedId(id);
    const state = vscode.getState();
    vscode.setState({ ...(state && typeof state === "object" ? state : {}), projectsSelected: id });
  };
  if (!projects) return <div className="loading"><Spinner size="small" label="Loading projects…" /></div>;
  const selected = projects.projects.find(project => project.id === selectedId);
  return (
    <section className="projects-surface">
      {projects.progressError && <div className="error-text">{projects.progressError}</div>}
      {projects.loadErrors.map(error => <div className="error-text" key={error}>{error}</div>)}
      {projects.error && <div className="error-text projects-error">{projects.error}</div>}
      {!projects.hasWorkspace && (
        <div className="projects-notice">Open a folder: progress is kept in <code>{projects.progressPath}</code>.</div>
      )}
      {selected
        ? <ProjectPage vscode={vscode} project={selected} host={projects} runtime={runtime} onBack={() => select(undefined)} />
        : <ProjectList projects={projects.projects} progressPath={projects.progressPath} onOpen={select} />}
    </section>
  );
}

function ProjectList({ projects, progressPath, onOpen }: { projects: ProjectView[]; progressPath: string; onOpen: (id: string) => void }) {
  return (
    <>
      <div className="projects-intro">
        <div className="eyebrow">End-to-end projects · verified on your workspace</div>
        <Text size={500} weight="semibold">Stories whose steps are done in the labs</Text>
        <p className="muted">
          Datapass verifies the steps on your local catalog and the journal of what the labs ran, and each check says
          whether it saw a real run, a simulation or an emulation. Steps you tick yourself stay "ticked by hand".
          Progress is a workspace file: <code>{progressPath}</code>.
        </p>
      </div>
      <div className="projects-grid">
        {projects.map(project => (
          <article className="project-card" key={project.id}>
            <div className="project-card-head">
              <Text weight="semibold" size={400}>{project.title}</Text>
              <span className="muted project-meta">
                {LEVEL_LABELS[project.level]} · {formatDuration(project.durationMinutes)} · {project.steps.length} steps
              </span>
            </div>
            <p className="project-summary">{project.summary}</p>
            <div className="project-modules">
              {project.modules.map(module => (
                <Badge key={module} appearance="outline" size="small">{project.steps.find(s => s.module === module)?.moduleLabel ?? module}</Badge>
              ))}
            </div>
            <ProgressLine project={project} />
            <div className="button-row">
              <Button appearance={project.started ? "primary" : "secondary"} onClick={() => onOpen(project.id)}>
                {project.progress.done === project.progress.required ? "Review" : project.started ? "Continue" : "Start"}
              </Button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

/** Verified and hand-ticked steps as two segments of one bar: they never merge into one count. */
function ProgressLine({ project }: { project: ProjectView }) {
  const { required, verified, manual, percent } = project.progress;
  const share = (n: number) => `${required ? (n / required) * 100 : 0}%`;
  return (
    <div className="project-progress">
      <div
        className="project-progress-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={`${verified} steps verified and ${manual} ticked by hand out of ${required}`}
      >
        <span className="segment-verified" style={{ width: share(verified) }} />
        <span className="segment-manual" style={{ width: share(manual) }} />
      </div>
      <span className="muted project-progress-text">
        <span className="legend-verified">{verified} verified</span>
        {" · "}
        <span className="legend-manual">{manual} ticked by hand</span>
        {` · ${required} steps`}
      </span>
    </div>
  );
}

function ProjectPage({ vscode, project, host, runtime, onBack }: {
  vscode: VsCodeApi;
  project: ProjectView;
  host: ProjectsHostState;
  runtime: RuntimeViewState;
  onBack: () => void;
}) {
  const running = runtime.status === "running";
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(project.nextStepId ? [project.nextStepId] : []));
  const [showStory, setShowStory] = useState(!project.started);
  const busy = host.verifying?.projectId === project.id ? new Set(host.verifying.stepIds) : new Set<string>();
  const remaining = useMemo(() => unverifiedSteps(project), [project]);
  const next = project.steps.find(step => step.id === project.nextStepId);
  const nextIndex = project.steps.findIndex(step => step.id === project.nextStepId);

  // Follow the learner: when the next step changes, open it.
  useEffect(() => {
    if (project.nextStepId) setExpanded(current => new Set(current).add(project.nextStepId!));
  }, [project.nextStepId]);

  const toggle = (id: string) => setExpanded(current => {
    const copy = new Set(current);
    if (copy.has(id)) copy.delete(id);
    else copy.add(id);
    return copy;
  });
  const verify = (stepIds: string[]) => vscode.postMessage({ type: "verifyProjectSteps", projectId: project.id, stepIds });
  const open = (stepId: string) => vscode.postMessage({ type: "openProjectStep", projectId: project.id, stepId });

  return (
    <div className="project-page">
      <Button appearance="subtle" size="small" className="project-back" onClick={onBack}>← All projects</Button>
      <div className="project-page-head">
        <Text size={500} weight="semibold">{project.title}</Text>
        <span className="muted project-meta">
          {LEVEL_LABELS[project.level]} · {formatDuration(project.durationMinutes)} · {project.steps.length} steps
        </span>
      </div>
      <ProgressLine project={project} />

      <div className="button-row project-toolbar">
        <Button size="small" appearance="primary" disabled={!running || !remaining.length || busy.size > 0}
          title={running ? undefined : "Start the runtime to verify"} onClick={() => verify(remaining)}>
          Verify remaining steps{remaining.length ? ` (${remaining.length})` : ""}
        </Button>
        <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "prepareProject", projectId: project.id })}>
          Prepare files
        </Button>
        <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "openProgressFile" })}>
          Open progress.json
        </Button>
        <Button size="small" appearance="subtle" onClick={() => setShowStory(value => !value)}>
          {showStory ? "Hide the story" : "Show the story and goals"}
        </Button>
      </div>
      {!running && (
        <div className="projects-notice">
          Start the runtime to verify steps: it reads the local catalog and the journal of what the labs ran.
          Steps you tick by hand do not need it.
        </div>
      )}

      {showStory && (
        <div className="project-story">
          <Markdown source={project.story} />
          <Text weight="semibold">Goals</Text>
          <ul>{project.goals.map(goal => <li key={goal}>{goal}</li>)}</ul>
        </div>
      )}

      {next ? (
        <div className="project-next" aria-live="polite">
          <div className="project-next-text">
            <span className="eyebrow">Suggested next step</span>
            <strong>{nextIndex + 1}. {next.title}</strong>
            <span className="muted">{next.moduleLabel}{next.optional ? " · optional" : ""}</span>
          </div>
          <div className="button-row">
            <Button size="small" appearance="primary" onClick={() => open(next.id)}>Open in {next.moduleLabel}</Button>
            {!expanded.has(next.id) && <Button size="small" appearance="secondary" onClick={() => toggle(next.id)}>Show instructions</Button>}
          </div>
        </div>
      ) : (
        <div className="project-next project-done"><strong>Every step is done.</strong></div>
      )}

      <ol className="project-steps">
        {project.steps.map((step, index) => (
          <StepItem
            key={step.id}
            step={step}
            index={index}
            expanded={expanded.has(step.id)}
            isNext={step.id === project.nextStepId}
            busy={busy.has(step.id)}
            running={running}
            onToggle={() => toggle(step.id)}
            onOpen={() => open(step.id)}
            onVerify={() => verify([step.id])}
            onManual={checked => vscode.postMessage({ type: "setProjectStepManual", projectId: project.id, stepId: step.id, checked })}
          />
        ))}
      </ol>
      <p className="muted project-footnote">
        "verified": Datapass checked the step on your workspace. "ticked by hand": you declared it done; Datapass did
        not check it. A verified step stays verified even if a later project changes the same tables; the latest
        verification is shown next to it.
      </p>
    </div>
  );
}

function StepItem({ step, index, expanded, isNext, busy, running, onToggle, onOpen, onVerify, onManual }: {
  step: ProjectStepView;
  index: number;
  expanded: boolean;
  isNext: boolean;
  busy: boolean;
  running: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onVerify: () => void;
  onManual: (checked: boolean) => void;
}) {
  const automatic = step.checks.length > 0;
  const shown = step.last ?? step.verified;
  return (
    <li className={`project-step project-state-${step.state}${isNext ? " is-next" : ""}`}>
      <div className="project-step-head">
        <Checkbox
          checked={step.state === "verified" || step.manual.checked}
          disabled={step.state === "verified"}
          aria-label={step.state === "verified" ? `${step.title}: verified by Datapass` : `Tick by hand: ${step.title}`}
          title={step.state === "verified" ? "Verified by Datapass" : "Tick by hand (a declaration, not verified)"}
          onChange={(_, data) => onManual(data.checked === true)}
        />
        <button type="button" className="project-step-title" aria-expanded={expanded} onClick={onToggle}>
          <span className="project-step-number">{index + 1}.</span> {step.title}
        </button>
        <div className="project-step-badges">
          <Badge appearance={step.state === "todo" ? "outline" : "filled"} color={STATE_COLORS[step.state]} size="small">
            {STATE_LABELS[step.state]}
          </Badge>
          <Badge appearance="outline" size="small">{step.moduleLabel}</Badge>
          {step.optional && <Badge appearance="outline" size="small" color="subtle">optional</Badge>}
          {!automatic && <Badge appearance="outline" size="small" color="subtle">tick by hand</Badge>}
          {step.truths.filter(truth => truth !== "real").map(truth => (
            <Badge key={truth} appearance="tint" size="small" color={TRUTH_COLORS[truth]} title={TRUTH_TITLES[truth]}>{TRUTH_LABELS[truth]}</Badge>
          ))}
        </div>
      </div>
      {step.state === "verified" && step.verified && (
        <div className="project-step-status muted">
          Verified on {formatTime(step.verified.at)}
          {step.manual.checked ? " · also ticked by hand" : ""}
        </div>
      )}
      {step.state === "manual" && (
        <div className="project-step-status muted">
          Ticked by hand on {formatTime(step.manual.at)}{automatic ? " · not verified by Datapass yet" : ""}
        </div>
      )}
      {step.regressed && step.last && (
        <div className="project-step-status warning-text">
          The latest verification ({formatTime(step.last.at)}) no longer passes: a later step or project probably
          changed the same tables. The verification of {formatTime(step.verified?.at)} still counts.
        </div>
      )}
      {expanded && (
        <div className="project-step-body">
          <Markdown source={step.instructions} />
          {automatic ? (
            <div className="project-checks">
              <Text weight="semibold" size={200}>What Datapass checks</Text>
              <ul>
                {step.checks.map((check, i) => (
                  <CheckLine key={`${check.kind}-${i}`} label={check.label} result={shown?.checks[i]?.label === check.label ? shown.checks[i] : undefined} />
                ))}
              </ul>
              {shown && <div className="muted project-checked-at">Latest verification: {formatTime(shown.at)}</div>}
            </div>
          ) : (
            <div className="projects-notice">This step is not checked automatically: tick it when it is done.</div>
          )}
          <div className="button-row">
            <Button size="small" appearance="primary" onClick={onOpen}>Open in {step.moduleLabel}</Button>
            {automatic && (
              <Button size="small" appearance="secondary" disabled={!running || busy} onClick={onVerify}
                title={running ? undefined : "Start the runtime to verify"}>
                {busy ? "Verifying…" : "Verify"}
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function CheckLine({ label, result }: { label: string; result?: CheckResultRecord }) {
  const status = result?.status;
  return (
    <li className={`project-check ${status ? `check-${status}` : "check-pending"}`}>
      <span className="project-check-icon" aria-hidden="true">{status === "passed" ? "✓" : status === "failed" ? "✗" : "○"}</span>
      <span className="project-check-text">
        <span>{label}</span>
        {result && (
          <span className="project-check-meta">
            <Badge appearance="tint" size="small" color={TRUTH_COLORS[result.truth]} title={TRUTH_TITLES[result.truth]}>
              {TRUTH_LABELS[result.truth]}
            </Badge>
            <span className="muted">{result.message}</span>
          </span>
        )}
      </span>
    </li>
  );
}

function Markdown({ source }: { source: string }) {
  return (
    <div className="project-markdown">
      {parseMarkdown(source).map((block, i) =>
        block.kind === "code" ? <pre key={i}><code>{block.text}</code></pre>
          : block.kind === "list"
            ? (block.ordered
              ? <ol key={i}>{block.items.map((item, j) => <li key={j}><Inline spans={item} /></li>)}</ol>
              : <ul key={i}>{block.items.map((item, j) => <li key={j}><Inline spans={item} /></li>)}</ul>)
            : <p key={i}><Inline spans={block.spans} /></p>
      )}
    </div>
  );
}

function Inline({ spans }: { spans: InlineSpan[] }): ReactNode {
  return spans.map((span, i) => (
    <Fragment key={i}>
      {span.kind === "code" ? <code>{span.text}</code> : span.kind === "bold" ? <strong>{span.text}</strong> : span.text}
    </Fragment>
  ));
}

function formatDuration(minutes: number): string {
  if (!minutes) return "self-paced";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours ? `~${hours} h${rest ? ` ${String(rest).padStart(2, "0")} min` : ""}` : `~${minutes} min`;
}

function formatTime(at: string | undefined): string {
  if (!at) return "?";
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return at;
  return date.toLocaleString("en-GB", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
