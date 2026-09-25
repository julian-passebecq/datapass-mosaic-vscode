/**
 * Projects: end-to-end stories whose steps are done in the Workbench labs (content/projects/<id>/project.json,
 * schema in runtime/datapass_runtime/projects.py). Pure functions only, tested by scripts/projects_ui_smoke.mjs.
 *
 * Truth model: a step is "verified" only when the runtime verified every one of its checks; a learner's tick is
 * "manual" (coché à la main) and never becomes verified. Progress is a native workspace file,
 * .datapass/progress.json, next to the project manifest (which it never touches).
 */
import type { ModuleId } from "../modules";

export const PROGRESS_PATH = ".datapass/progress.json";
export const PROJECT_SCAFFOLDS = ["project", "factory", "bi", "retail_demo", "airflow", "pipeline", "sparklab"] as const;
export type ProjectScaffold = typeof PROJECT_SCAFFOLDS[number];
export type ProjectTruth = "real" | "simulated" | "emulation" | "hybrid" | "static";
export type ProjectLevel = "beginner" | "intermediate" | "advanced";
export type StepState = "verified" | "manual" | "failed" | "todo";

const TRUTHS: readonly ProjectTruth[] = ["real", "simulated", "emulation", "hybrid", "static"];
const FILE_ROOTS = ["projects/", "factory/", "bi/", "airflow/dags/", "pipelines/", "notebooks/", "notes/", "datasets/"];
const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const EXERCISE_KEY = /^[A-Za-z0-9_-]+\/[A-Za-z0-9_-]+\/[a-z0-9-]+$/;

export const TRUTH_LABELS: Record<ProjectTruth, string> = {
  real: "réel",
  simulated: "simulé",
  emulation: "émulé",
  hybrid: "hybride",
  static: "analyse statique"
};
export const LEVEL_LABELS: Record<ProjectLevel, string> = {
  beginner: "débutant",
  intermediate: "intermédiaire",
  advanced: "avancé"
};

export interface ProjectCheckSpec { kind: string; label: string }
export interface ProjectOpenAction {
  module: ModuleId;
  tab?: string;
  file?: string;
  exercise?: string;
  scaffold: ProjectScaffold[];
}
export interface ProjectStepContent {
  id: string;
  title: string;
  module: ModuleId;
  optional: boolean;
  instructions: string;
  open: ProjectOpenAction;
  checks: ProjectCheckSpec[];
}
export interface ProjectContent {
  id: string;
  version: string;
  order: number;
  title: string;
  summary: string;
  level: ProjectLevel;
  durationMinutes: number;
  story: string;
  goals: string[];
  steps: ProjectStepContent[];
}

export interface CheckResultRecord {
  kind: string;
  label: string;
  status: "passed" | "failed";
  truth: ProjectTruth;
  message: string;
  at?: string;
}
export interface VerificationRecord { at: string; status: "passed" | "failed"; checks: CheckResultRecord[] }
export interface StepProgress {
  /** The learner's own tick: a declaration, shown as "coché à la main", never as verified. */
  manual?: { checked: boolean; at: string };
  /** The last verification where every check passed. Kept when a later verification fails. */
  verified?: VerificationRecord;
  /** The latest verification, passed or failed. */
  last?: VerificationRecord;
}
export interface ProjectProgress { version: string; steps: Record<string, StepProgress> }
export interface ProgressDocument { schema_version: 1; projects: Record<string, ProjectProgress> }

export interface ProjectStepView extends ProjectStepContent {
  moduleLabel: string;
  state: StepState;
  manual: { checked: boolean; at?: string };
  verified?: VerificationRecord;
  last?: VerificationRecord;
  /** Verified earlier, but the latest verification failed (a later step or project changed shared tables). */
  regressed: boolean;
  /** Truths of the step's checks as last seen, for the badges ("simulé", "émulé"...). */
  truths: ProjectTruth[];
}
export interface ProjectSummary {
  /** Steps counted in the progress bar (optional steps are not). */
  required: number;
  verified: number;
  manual: number;
  done: number;
  percent: number;
}
export interface ProjectView extends Omit<ProjectContent, "steps"> {
  steps: ProjectStepView[];
  progress: ProjectSummary;
  modules: ModuleId[];
  nextStepId?: string;
  started: boolean;
}
export interface ProjectsViewState {
  projects: ProjectView[];
  progressPath: string;
  progressError?: string;
  loadErrors: string[];
  hasWorkspace: boolean;
}

// ---- Content --------------------------------------------------------------------------------------------

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function text(value: unknown): string | undefined {
  if (Array.isArray(value) && value.every(line => typeof line === "string")) return value.join("\n");
  return str(value);
}

/** A workspace-relative path under the folders projects may open or create files in. */
export function isProjectFilePath(value: string): boolean {
  const parts = value.split("/");
  return /^[A-Za-z0-9_./ -]{1,200}$/.test(value) && !value.startsWith("/") && !parts.includes("..") &&
    !parts.includes("") && !parts.includes(".") && FILE_ROOTS.some(root => value.startsWith(root));
}

/** A project.json, normalized; undefined with a reason when it cannot be shown. The runtime validates it strictly. */
export function normalizeProject(raw: unknown, modules: readonly ModuleId[]): { project?: ProjectContent; error?: string } {
  if (!raw || typeof raw !== "object") return { error: "not a JSON object" };
  const value = raw as Record<string, unknown>;
  const id = str(value.id);
  if (!id || !ID.test(id)) return { error: "missing or invalid id" };
  const steps: ProjectStepContent[] = [];
  for (const item of Array.isArray(value.steps) ? value.steps : []) {
    const step = item && typeof item === "object" ? item as Record<string, unknown> : {};
    const open = step.open && typeof step.open === "object" ? step.open as Record<string, unknown> : {};
    const stepId = str(step.id);
    const module = str(step.module) as ModuleId | undefined;
    const title = str(step.title);
    const instructions = text(step.instructions);
    if (!stepId || !ID.test(stepId) || !module || !modules.includes(module) || !title || !instructions) {
      return { error: `invalid step ${stepId ?? steps.length + 1}` };
    }
    const openModule = str(open.module) as ModuleId | undefined;
    const file = str(open.file);
    const exercise = str(open.exercise);
    if (openModule !== module || (file && !isProjectFilePath(file)) || (exercise && !EXERCISE_KEY.test(exercise))) {
      return { error: `invalid open action in step ${stepId}` };
    }
    const scaffold = (Array.isArray(open.scaffold) ? open.scaffold : [])
      .filter((s): s is ProjectScaffold => PROJECT_SCAFFOLDS.includes(s as ProjectScaffold));
    const checks = (Array.isArray(step.checks) ? step.checks : []).flatMap(check => {
      const c = check && typeof check === "object" ? check as Record<string, unknown> : {};
      const kind = str(c.kind);
      const label = str(c.label);
      return kind && label ? [{ kind, label }] : [];
    });
    steps.push({
      id: stepId, title, module, optional: step.optional === true, instructions,
      open: { module, tab: str(open.tab), file, exercise, scaffold }, checks
    });
  }
  const title = str(value.title);
  const story = text(value.story);
  if (!title || !story || !steps.length) return { error: "missing title, story or steps" };
  const level = (["beginner", "intermediate", "advanced"] as const).find(l => l === value.level) ?? "intermediate";
  return {
    project: {
      id,
      version: str(value.version) ?? "1",
      order: typeof value.order === "number" ? value.order : 0,
      title,
      summary: str(value.summary) ?? "",
      level,
      durationMinutes: typeof value.duration_minutes === "number" ? value.duration_minutes : 0,
      story,
      goals: (Array.isArray(value.goals) ? value.goals : []).filter((g): g is string => typeof g === "string"),
      steps
    }
  };
}

// ---- Progress file --------------------------------------------------------------------------------------

export function emptyProgress(): ProgressDocument {
  return { schema_version: 1, projects: {} };
}

function checkRecord(raw: unknown): CheckResultRecord | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const value = raw as Record<string, unknown>;
  const kind = str(value.kind);
  const label = str(value.label);
  const truth = TRUTHS.find(t => t === value.truth);
  if (!kind || !label || !truth || (value.status !== "passed" && value.status !== "failed")) return undefined;
  return { kind, label, status: value.status, truth, message: typeof value.message === "string" ? value.message : "",
    ...(str(value.at) ? { at: str(value.at) } : {}) };
}

function verification(raw: unknown): VerificationRecord | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const value = raw as Record<string, unknown>;
  const at = str(value.at);
  if (!at || (value.status !== "passed" && value.status !== "failed") || !Array.isArray(value.checks)) return undefined;
  const checks = value.checks.map(checkRecord);
  if (checks.some(c => !c)) return undefined;
  return { at, status: value.status, checks: checks as CheckResultRecord[] };
}

/** Parse .datapass/progress.json. An unreadable file yields an empty document and an error to show. */
export function parseProgress(content: string | undefined): { document: ProgressDocument; error?: string } {
  if (content === undefined || !content.trim()) return { document: emptyProgress() };
  let raw: unknown;
  try {
    raw = JSON.parse(content);
  } catch (error) {
    return { document: emptyProgress(), error: `${PROGRESS_PATH} is not valid JSON: ${error instanceof Error ? error.message : String(error)}` };
  }
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  if (value.schema_version !== 1 || !value.projects || typeof value.projects !== "object") {
    return { document: emptyProgress(), error: `${PROGRESS_PATH} has no schema_version 1 projects object.` };
  }
  const document = emptyProgress();
  for (const [projectId, project] of Object.entries(value.projects as Record<string, unknown>)) {
    if (!ID.test(projectId) || !project || typeof project !== "object") continue;
    const p = project as Record<string, unknown>;
    const steps: Record<string, StepProgress> = {};
    for (const [stepId, step] of Object.entries(p.steps && typeof p.steps === "object" ? p.steps as Record<string, unknown> : {})) {
      if (!ID.test(stepId) || !step || typeof step !== "object") continue;
      const s = step as Record<string, unknown>;
      const manual = s.manual && typeof s.manual === "object" ? s.manual as Record<string, unknown> : undefined;
      const entry: StepProgress = {};
      if (manual && typeof manual.checked === "boolean" && str(manual.at)) entry.manual = { checked: manual.checked, at: str(manual.at)! };
      const verified = verification(s.verified);
      // A verified record needs every check passed; anything else in the file is ignored, not trusted.
      if (verified?.status === "passed" && verified.checks.length && verified.checks.every(c => c.status === "passed")) entry.verified = verified;
      const last = verification(s.last);
      if (last) entry.last = last;
      if (Object.keys(entry).length) steps[stepId] = entry;
    }
    document.projects[projectId] = { version: str(p.version) ?? "1", steps };
  }
  return { document };
}

export function serializeProgress(document: ProgressDocument): string {
  return JSON.stringify(document, null, 2) + "\n";
}

function withStep(document: ProgressDocument, project: ProjectContent, stepId: string,
  update: (step: StepProgress) => StepProgress): ProgressDocument {
  const current = document.projects[project.id] ?? { version: project.version, steps: {} };
  return {
    ...document,
    projects: {
      ...document.projects,
      [project.id]: { version: project.version, steps: { ...current.steps, [stepId]: update(current.steps[stepId] ?? {}) } }
    }
  };
}

/** The learner ticks or unticks a step. This is a declaration: it never touches the verification records. */
export function setManual(document: ProgressDocument, project: ProjectContent, stepId: string, checked: boolean,
  now: string): ProgressDocument {
  if (!project.steps.some(step => step.id === stepId)) throw new Error(`Unknown step ${stepId}`);
  return withStep(document, project, stepId, step => ({ ...step, manual: { checked, at: now } }));
}

/**
 * Record a runtime verification (POST /api/local/projects/check). Only steps that have checks, all passed, are
 * marked verified; a manual step's "manual" status from the runtime is ignored.
 */
export function applyVerification(document: ProgressDocument, project: ProjectContent, raw: unknown,
  now: string): ProgressDocument {
  const result = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  if (result.project_id !== project.id || !Array.isArray(result.steps)) throw new Error("The runtime returned no verification for this project.");
  let next = document;
  for (const item of result.steps) {
    const entry = item && typeof item === "object" ? item as Record<string, unknown> : {};
    const step = project.steps.find(s => s.id === entry.id);
    if (!step || !step.checks.length || !Array.isArray(entry.checks)) continue;
    const checks = entry.checks.map(checkRecord);
    if (!checks.length || checks.some(c => !c)) continue;
    const records = checks as CheckResultRecord[];
    const passed = entry.status === "passed" && records.length === step.checks.length && records.every(c => c.status === "passed");
    const record: VerificationRecord = { at: typeof result.checked_at === "string" ? result.checked_at : now,
      status: passed ? "passed" : "failed", checks: records };
    next = withStep(next, project, step.id, current => ({ ...current, last: record, ...(passed ? { verified: record } : {}) }));
  }
  return next;
}

// ---- Views ----------------------------------------------------------------------------------------------

export function stepState(step: ProjectStepContent, progress: StepProgress | undefined): StepState {
  if (step.checks.length && progress?.verified) return "verified";
  if (progress?.manual?.checked) return "manual";
  if (step.checks.length && progress?.last?.status === "failed") return "failed";
  return "todo";
}

export function projectView(project: ProjectContent, progress: ProjectProgress | undefined,
  moduleLabels: Partial<Record<ModuleId, string>>): ProjectView {
  const steps: ProjectStepView[] = project.steps.map(step => {
    const saved = progress?.steps[step.id];
    const state = stepState(step, saved);
    const seen = saved?.last ?? saved?.verified;
    return {
      ...step,
      moduleLabel: moduleLabels[step.module] ?? step.module,
      state,
      manual: { checked: saved?.manual?.checked === true, at: saved?.manual?.at },
      verified: step.checks.length ? saved?.verified : undefined,
      last: step.checks.length ? saved?.last : undefined,
      regressed: state === "verified" && saved?.last?.status === "failed",
      truths: [...new Set((seen?.checks ?? []).map(c => c.truth))]
    };
  });
  const required = steps.filter(step => !step.optional);
  const verified = required.filter(step => step.state === "verified").length;
  const manual = required.filter(step => step.state === "manual").length;
  const done = verified + manual;
  const next = steps.find(step => !step.optional && !isDone(step)) ?? steps.find(step => !isDone(step));
  return {
    ...project,
    steps,
    modules: [...new Set(project.steps.map(step => step.module))],
    progress: { required: required.length, verified, manual, done,
      percent: required.length ? Math.round((done / required.length) * 100) : 0 },
    nextStepId: next?.id,
    started: steps.some(step => step.state !== "todo")
  };
}

export function isDone(step: ProjectStepView): boolean {
  return step.state === "verified" || step.state === "manual";
}

/** Steps of a project that have automatic checks and are not verified yet. */
export function unverifiedSteps(view: ProjectView): string[] {
  return view.steps.filter(step => step.checks.length && step.state !== "verified").map(step => step.id);
}

// ---- Markdown subset (paragraphs, lists, **bold**, `code`, fenced code) ----------------------------------

export type InlineSpan = { kind: "text" | "bold" | "code"; text: string };
export type MarkdownBlock =
  | { kind: "paragraph"; spans: InlineSpan[] }
  | { kind: "list"; ordered: boolean; items: InlineSpan[][] }
  | { kind: "code"; text: string };

export function parseInline(line: string): InlineSpan[] {
  const spans: InlineSpan[] = [];
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*/g;
  let index = 0;
  for (const match of line.matchAll(pattern)) {
    if (match.index! > index) spans.push({ kind: "text", text: line.slice(index, match.index) });
    spans.push(match[1] !== undefined ? { kind: "code", text: match[1] } : { kind: "bold", text: match[2] });
    index = match.index! + match[0].length;
  }
  if (index < line.length) spans.push({ kind: "text", text: line.slice(index) });
  return spans;
}

export function parseMarkdown(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", spans: parseInline(paragraph.join(" ")) });
    paragraph = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      flush();
      const code: string[] = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith("```"); i++) code.push(lines[i]);
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    const item = /^\s*(?:([-*])|(\d+)\.)\s+(.*)$/.exec(line);
    if (item) {
      flush();
      const ordered = item[2] !== undefined;
      const last = blocks[blocks.length - 1];
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(parseInline(item[3]));
      else blocks.push({ kind: "list", ordered, items: [parseInline(item[3])] });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}
