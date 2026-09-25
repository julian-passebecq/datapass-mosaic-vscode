/**
 * Practice progress: which exercises are solved, attempted or not started, kept in the `practice` section of
 * .datapass/progress.json (the Projects module owns the file's `projects` section; see platform/projects.ts).
 * Pure functions, shared by the host and the webview; tested by scripts/practice_progress_smoke.mjs.
 *
 * Truth model: "solved" means a Submit (visible, hidden and edge checks) passed on the runtime. Run visible never
 * solves an exercise. Opening an exercise or grading it without a pass makes it "attempted".
 */
import type { ExerciseSummary } from "../webview/contracts";

export type PracticeStatus = "solved" | "attempted" | "not-started";
export type GradeMode = "run" | "submit";
export type GradeStatus = "passed" | "failed" | "error";

export interface PracticeAttempt { mode: GradeMode; status: GradeStatus; at: string; version: string }
export interface ExerciseProgressRecord {
  openedAt?: string;
  /** Run visible and Submit gradings, passed or not. */
  attempts: number;
  /** Gradings that did not pass; the reference solution unlocks after a few (platform/practiceFeedback.ts). */
  failures?: number;
  /** Hints revealed one at a time in Practice. */
  hintsRevealed?: number;
  /** When the learner first opened the reference solution. */
  solutionViewedAt?: string;
  /** The first Submit that passed, and the exercise version it passed on. */
  solved?: { at: string; version: string };
  last?: PracticeAttempt;
}
export interface PracticeProgress { exercises: Record<string, ExerciseProgressRecord> }

export interface PracticeFilters {
  query: string;
  difficulty: string;
  topic: string;
  language: string;
  status: PracticeStatus | "";
}

export const EMPTY_FILTERS: PracticeFilters = { query: "", difficulty: "", topic: "", language: "", status: "" };
export const STATUS_LABELS: Record<PracticeStatus, string> = {
  solved: "Solved",
  attempted: "Attempted",
  "not-started": "Not started"
};
const DIFFICULTY_ORDER = ["easy", "medium", "hard"];
/** pack/exercise/language, as ExerciseSummary.key. */
const EXERCISE_KEY = /^[A-Za-z0-9_-]{1,100}\/[A-Za-z0-9_.-]{1,160}\/[A-Za-z0-9_-]{1,40}$/;

export function emptyPracticeProgress(): PracticeProgress {
  return { exercises: {} };
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function attempt(raw: unknown): PracticeAttempt | undefined {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : undefined;
  if (!value) return undefined;
  const at = text(value.at);
  const version = text(value.version);
  const mode = value.mode === "run" || value.mode === "submit" ? value.mode : undefined;
  const status = value.status === "passed" || value.status === "failed" || value.status === "error" ? value.status : undefined;
  return at && version && mode && status ? { mode, status, at, version } : undefined;
}

/** The `practice` section of progress.json; entries that do not parse are dropped, never guessed. */
export function parsePracticeProgress(raw: unknown): PracticeProgress {
  const progress = emptyPracticeProgress();
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const exercises = value.exercises && typeof value.exercises === "object" ? value.exercises as Record<string, unknown> : {};
  for (const [key, item] of Object.entries(exercises)) {
    if (!EXERCISE_KEY.test(key) || !item || typeof item !== "object") continue;
    const entry = item as Record<string, unknown>;
    const record: ExerciseProgressRecord = {
      attempts: typeof entry.attempts === "number" && Number.isInteger(entry.attempts) && entry.attempts >= 0 ? entry.attempts : 0
    };
    const openedAt = text(entry.openedAt);
    if (openedAt) record.openedAt = openedAt;
    const count = (v: unknown) => typeof v === "number" && Number.isInteger(v) && v > 0 ? v : undefined;
    if (count(entry.failures)) record.failures = count(entry.failures);
    if (count(entry.hintsRevealed)) record.hintsRevealed = count(entry.hintsRevealed);
    const viewed = text(entry.solutionViewedAt);
    if (viewed) record.solutionViewedAt = viewed;
    const solved = entry.solved && typeof entry.solved === "object" ? entry.solved as Record<string, unknown> : undefined;
    if (solved && text(solved.at) && text(solved.version)) record.solved = { at: text(solved.at)!, version: text(solved.version)! };
    const last = attempt(entry.last);
    if (last) record.last = last;
    if (record.openedAt || record.attempts || record.solved || record.last || record.hintsRevealed || record.solutionViewedAt) {
      progress.exercises[key] = record;
    }
  }
  return progress;
}

function withRecord(progress: PracticeProgress | undefined, key: string,
  update: (record: ExerciseProgressRecord) => ExerciseProgressRecord): PracticeProgress {
  if (!EXERCISE_KEY.test(key)) throw new Error(`Invalid exercise key ${key}`);
  const current = progress ?? emptyPracticeProgress();
  return { ...current, exercises: { ...current.exercises, [key]: update(current.exercises[key] ?? { attempts: 0 }) } };
}

/** The learner opened the exercise's solution file. */
export function recordOpened(progress: PracticeProgress | undefined, key: string, now: string): PracticeProgress {
  return withRecord(progress, key, record => ({ ...record, openedAt: record.openedAt ?? now }));
}

/** A grading the runtime returned. Only a passed Submit solves; a later failure never unsolves. */
export function recordGrade(progress: PracticeProgress | undefined, key: string, version: string, mode: GradeMode,
  status: GradeStatus, now: string): PracticeProgress {
  return withRecord(progress, key, record => ({
    ...record,
    attempts: record.attempts + 1,
    ...(status === "passed" ? {} : { failures: (record.failures ?? 0) + 1 }),
    last: { mode, status, at: now, version },
    ...(mode === "submit" && status === "passed" && !record.solved ? { solved: { at: now, version } } : {})
  }));
}

/** One more hint revealed, never beyond the exercise's hints. */
export function revealHint(progress: PracticeProgress | undefined, key: string, total: number): PracticeProgress {
  return withRecord(progress, key, record => ({ ...record, hintsRevealed: Math.min(total, (record.hintsRevealed ?? 0) + 1) }));
}

export function recordSolutionViewed(progress: PracticeProgress | undefined, key: string, now: string): PracticeProgress {
  return withRecord(progress, key, record => ({ ...record, solutionViewedAt: record.solutionViewedAt ?? now }));
}

export function practiceStatus(record: ExerciseProgressRecord | undefined): PracticeStatus {
  if (record?.solved) return "solved";
  if (record && (record.attempts > 0 || record.openedAt)) return "attempted";
  return "not-started";
}

export function filterExercises(exercises: readonly ExerciseSummary[], progress: PracticeProgress | undefined,
  filters: PracticeFilters): ExerciseSummary[] {
  const needle = filters.query.trim().toLowerCase();
  return exercises.filter(exercise =>
    (!filters.difficulty || exercise.difficulty === filters.difficulty) &&
    (!filters.topic || exercise.topics.includes(filters.topic)) &&
    (!filters.language || exercise.language === filters.language) &&
    (!filters.status || practiceStatus(progress?.exercises[exercise.key]) === filters.status) &&
    (!needle || [exercise.id, exercise.title, exercise.packTitle, exercise.language, exercise.difficulty, exercise.prompt,
      ...exercise.topics].some(value => value.toLowerCase().includes(needle)))
  );
}

export function practiceCounts(exercises: readonly ExerciseSummary[], progress: PracticeProgress | undefined):
  Record<PracticeStatus, number> {
  const counts: Record<PracticeStatus, number> = { solved: 0, attempted: 0, "not-started": 0 };
  for (const exercise of exercises) counts[practiceStatus(progress?.exercises[exercise.key])] += 1;
  return counts;
}

/** The values each filter offers, from the installed catalog. */
export function filterOptions(exercises: readonly ExerciseSummary[]): { difficulties: string[]; topics: string[]; languages: string[] } {
  const unique = (values: string[]) => [...new Set(values)].sort((a, b) => a.localeCompare(b));
  const rank = (value: string) => {
    const index = DIFFICULTY_ORDER.indexOf(value);
    return index < 0 ? DIFFICULTY_ORDER.length : index;
  };
  return {
    difficulties: unique(exercises.map(e => e.difficulty)).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b)),
    topics: unique(exercises.flatMap(e => e.topics)),
    languages: unique(exercises.map(e => e.language))
  };
}

/** Filters restored from the webview's saved state: unknown values fall back to "all". */
export function restoreFilters(raw: unknown): PracticeFilters {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const pick = (key: keyof PracticeFilters) => typeof value[key] === "string" ? value[key] as string : "";
  const status = pick("status");
  return {
    query: pick("query"),
    difficulty: pick("difficulty"),
    topic: pick("topic"),
    language: pick("language"),
    status: status === "solved" || status === "attempted" || status === "not-started" ? status : ""
  };
}
