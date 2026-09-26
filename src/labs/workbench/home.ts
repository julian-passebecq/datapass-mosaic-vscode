/**
 * The Today home: a summary of .datapass/progress.json (Projects and Practice) and the next suggested step.
 * Pure functions, shared by the Workbench controller and scripts/home_smoke.mjs.
 *
 * The next step, in order: open a folder (progress lives in it); the next step of the first started project that is
 * not complete; the Practice reviews due today; the first project not started yet; else Practice itself.
 */
import type { ExerciseProgressRecord } from "../../platform/practiceProgress";
import { dueReviews } from "../../platform/practiceReview";
import type { ProjectView } from "../../platform/projects";
import type { HomeNextStep, HomeProjectView, HomeViewState } from "../../webview/contracts";

export interface HomeInputs {
  hasWorkspace: boolean;
  progressError?: string;
  projects: readonly ProjectView[];
  exerciseKeys: readonly string[];
  practice: Readonly<Record<string, ExerciseProgressRecord>>;
  /** Local calendar day `YYYY-MM-DD`. */
  today: string;
}

export function homeView(input: HomeInputs): HomeViewState {
  const list = input.projects.map(projectSummary);
  const started = new Set(input.projects.filter(project => project.started).map(project => project.id));
  const completed = list.filter(project => project.required > 0 && project.done >= project.required);
  const current = list.find(project => started.has(project.id) && project.done < project.required);

  const known = new Set(input.exerciseKeys);
  const records = Object.entries(input.practice).filter(([key]) => known.has(key)).map(([, record]) => record);
  const practice = {
    total: known.size,
    solved: records.filter(record => record.solved).length,
    attempted: records.filter(record => !record.solved && (record.attempts > 0 || Boolean(record.openedAt))).length,
    dueReviews: dueReviews(input.exerciseKeys, input.practice, input.today).length
  };
  return {
    hasWorkspace: input.hasWorkspace,
    progressError: input.progressError,
    projects: { total: list.length, started: started.size, completed: completed.length, current, list },
    practice,
    next: nextStep(input, list, current, practice)
  };
}

function projectSummary(project: ProjectView): HomeProjectView {
  const step = project.steps.find(candidate => candidate.id === project.nextStepId);
  return {
    id: project.id,
    title: project.title,
    percent: project.progress.percent,
    done: project.progress.done,
    required: project.progress.required,
    nextStep: step ? { id: step.id, title: step.title, module: step.module, moduleLabel: step.moduleLabel } : undefined
  };
}

function nextStep(input: HomeInputs, list: HomeProjectView[], current: HomeProjectView | undefined,
  practice: HomeViewState["practice"]): HomeNextStep {
  if (!input.hasWorkspace) {
    return { kind: "open-folder", title: "Open a folder", detail: "Your progress, catalog and lab files live in the workspace folder." };
  }
  if (current?.nextStep) {
    return {
      kind: "project-step",
      title: current.nextStep.title,
      detail: `Next step of ${current.title} (${current.done} of ${current.required} done), in ${current.nextStep.moduleLabel}.`,
      projectId: current.id,
      stepId: current.nextStep.id,
      module: current.nextStep.module
    };
  }
  if (practice.dueReviews > 0) {
    const plural = practice.dueReviews === 1 ? "exercise is" : "exercises are";
    return { kind: "reviews", title: "Review in Practice", detail: `${practice.dueReviews} ${plural} due for review today.` };
  }
  const fresh = input.projects.find(project => !project.started);
  if (fresh) {
    const steps = list.find(project => project.id === fresh.id)?.required;
    return {
      kind: "start-project",
      title: `Start ${fresh.title}`,
      detail: steps ? `${fresh.summary} ${steps} steps.` : fresh.summary,
      projectId: fresh.id
    };
  }
  const left = practice.total - practice.solved;
  return {
    kind: "practice",
    title: "Solve an exercise",
    detail: left > 0 ? `${left} of ${practice.total} exercises are not solved yet.` : "Every exercise is solved: try an interview series."
  };
}
