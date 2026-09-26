import type { PracticeProgress } from "../../platform/practiceProgress";
import type { RowValidation } from "../../platform/practiceFeedback";

export interface ExerciseSummary {
  key: string;
  packId: string;
  packTitle: string;
  id: string;
  version: string;
  title: string;
  difficulty: string;
  language: string;
  /** The grading runtime id (for example datapass-dag-design-v1), when the pack declares one. */
  runtime?: string;
  prompt: string;
  starterSource: string;
  truth?: string;
  topics: string[];
  sections: ExerciseSectionView[];
  hints: string[];
  dataContext: ExerciseTableView[];
  /** How the grader compares result rows; the visible-fixture diff follows it. */
  validation: RowValidation;
  /** Why the reference solution works, shown with it. */
  explanation?: string;
  /** The pack ships a reference solution the learner may reveal (after a pass, or after a few failures). */
  solutionAvailable: boolean;
  /** SparkLab exercises only: public checks on the simulated Spark plan. */
  sparkPlan?: SparkPlanView;
  /** Set when Datapass cannot grade the exercise locally; Run/Submit are disabled. */
  gradingNote?: string;
  /** Reference sheets (Markdown shipped with the extension) the card links to; opened natively by the host. */
  references?: string[];
}

/** Plan requirements graded on SparkLab's modeled plan at authored input sizes (not Apache Spark). */
export interface SparkPlanView {
  profile: string;
  aqe: boolean;
  scale: SparkTableScaleView[];
  checks: SparkPlanCheckView[];
}

export interface SparkTableScaleView {
  table: string;
  rows: number;
  bytes: number;
  partitions: number;
  catalogStatistics: boolean;
}

export interface SparkPlanCheckView {
  id: string;
  description: string;
}

export interface ExerciseSectionView {
  title: string;
  body: string;
}

/** Public input table: schema and the visible example rows only. */
export interface ExerciseTableView {
  name: string;
  columns: Record<string, string>;
  sampleRows: Record<string, string | number | boolean | null>[];
}

export interface ExerciseCheckView {
  id: string;
  /** "plan" checks grade the simulated SparkLab plan, not result rows. */
  kind?: "result" | "plan";
  visibility: "visible" | "hidden" | "edge";
  passed: boolean;
  status: "passed" | "failed";
  message: string;
  elapsed_ms: number;
  actual?: readonly Record<string, unknown>[];
  expected?: readonly Record<string, unknown>[];
}

export interface PracticeResultView {
  exerciseKey: string;
  mode: "run" | "submit";
  status: "passed" | "failed" | "error";
  truth: string;
  elapsed_ms: number;
  checks: readonly ExerciseCheckView[];
  runtime?: {
    adapter: string;
    engine: string;
    engine_version: string;
    session_generation: string;
  };
  error?: {
    type: string;
    message: string;
  };
}

export interface PracticeViewState {
  exercises: readonly ExerciseSummary[];
  /** The `practice` section of .datapass/progress.json (solved, attempted; absent means not started). */
  progress: PracticeProgress;
  /** Set when .datapass/progress.json cannot be read; progress is then shown as empty and not saved. */
  progressError?: string;
  /** False without a workspace folder: progress cannot be kept. */
  canSaveProgress: boolean;
  /** Reference solutions the learner revealed in this Workbench, by exercise key. */
  solutions: Record<string, string>;
}

export interface PracticeRuntimeSlice {
  practiceResult?: PracticeResultView;
}

export interface PracticeViewSlice {
  practice?: PracticeViewState;
}

export type PracticeMessage =
  | { type: "openExercise"; exerciseKey: string }
  | { type: "gradeExercise"; exerciseKey: string; mode: "run" | "submit" }
  | { type: "revealHint"; exerciseKey: string }
  | { type: "showSolution"; exerciseKey: string }
  | { type: "compareSolution"; exerciseKey: string }
  | { type: "openReference"; exerciseKey: string; index: number }
  | { type: "saveInterview"; interview: unknown };
