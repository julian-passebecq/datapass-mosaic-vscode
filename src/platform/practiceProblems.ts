/**
 * The Practice arena's problems: one card per problem, one variant per language.
 *
 * A semantic pack registers each language of a scenario as its own exercise (`<scenario>-<language>`, key
 * `<pack>/<scenario>/<language>`); a plain pack registers one exercise per id. Both share the key shape
 * `<pack>/<problem>/<language>`, so a problem is every exercise whose key has the same `<pack>/<problem>` prefix.
 * Progress stays per variant (the `practice` section of .datapass/progress.json); a problem only summarizes it.
 * Pure functions, shared by the host and the webview; tested by scripts/practice_arena_smoke.mjs.
 */
import type { ExerciseSummary } from "../webview/contracts";
import { practiceStatus, type PracticeFilters, type PracticeProgress, type PracticeStatus } from "./practiceProgress";
import { dueReviews, reviewState } from "./practiceReview";

export interface PracticeProblem {
  /** `<pack>/<problem>`: the variants' keys without their language. */
  key: string;
  packId: string;
  packTitle: string;
  title: string;
  difficulty: string;
  prompt: string;
  topics: string[];
  /** One exercise per language, in LANGUAGE_ORDER. */
  variants: ExerciseSummary[];
}

export interface ProblemSummary {
  /** Solved when a variant is solved, attempted when one is started, else not started. */
  status: PracticeStatus;
  solved: string[];
  attempted: string[];
}

/** SQL first, then its translated dialects, then the dataframe languages, then dbt; anything else after, by name. */
export const LANGUAGE_ORDER = ["sql", "snowflake", "tsql", "bigquery", "sparksql", "python", "polars", "sparklab", "dbt-sql", "dbt"];

export const LANGUAGE_LABELS: Record<string, string> = {
  sql: "SQL",
  snowflake: "Snowflake",
  tsql: "T-SQL",
  bigquery: "BigQuery",
  sparksql: "Spark SQL",
  python: "Python",
  polars: "Polars",
  sparklab: "PySpark",
  "dbt-sql": "dbt",
  dbt: "dbt (drill)"
};

export function languageLabel(language: string): string {
  return LANGUAGE_LABELS[language] ?? language;
}

function languageRank(language: string): number {
  const index = LANGUAGE_ORDER.indexOf(language);
  return index < 0 ? LANGUAGE_ORDER.length : index;
}

/** `<pack>/<problem>` of an exercise key `<pack>/<problem>/<language>`. */
export function problemKeyOf(exerciseKey: string): string {
  const cut = exerciseKey.lastIndexOf("/");
  return cut < 0 ? exerciseKey : exerciseKey.slice(0, cut);
}

/** Group the catalog into problems, keeping the catalog's order of first appearance. */
export function groupProblems(exercises: readonly ExerciseSummary[]): PracticeProblem[] {
  const problems = new Map<string, PracticeProblem>();
  for (const exercise of exercises) {
    const key = problemKeyOf(exercise.key);
    const problem = problems.get(key);
    if (!problem) {
      problems.set(key, {
        key,
        packId: exercise.packId,
        packTitle: exercise.packTitle,
        title: exercise.title,
        difficulty: exercise.difficulty,
        prompt: exercise.prompt,
        topics: [...exercise.topics],
        variants: [exercise]
      });
      continue;
    }
    problem.variants.push(exercise);
    for (const topic of exercise.topics) if (!problem.topics.includes(topic)) problem.topics.push(topic);
  }
  for (const problem of problems.values()) {
    problem.variants.sort((a, b) => languageRank(a.language) - languageRank(b.language) || a.language.localeCompare(b.language));
  }
  return [...problems.values()];
}

export function problemSummary(problem: PracticeProblem, progress: PracticeProgress | undefined): ProblemSummary {
  const solved: string[] = [];
  const attempted: string[] = [];
  for (const variant of problem.variants) {
    const status = practiceStatus(progress?.exercises[variant.key]);
    if (status === "solved") solved.push(variant.language);
    else if (status === "attempted") attempted.push(variant.language);
  }
  return { status: solved.length ? "solved" : attempted.length ? "attempted" : "not-started", solved, attempted };
}

/**
 * Problems matching the filters. The language filter keeps problems offered in that language, and the status filter
 * then reads that variant's status; without a language, it reads the problem's summary.
 */
export function filterProblems(problems: readonly PracticeProblem[], progress: PracticeProgress | undefined,
  filters: PracticeFilters): PracticeProblem[] {
  const needle = filters.query.trim().toLowerCase();
  return problems.filter(problem => {
    if (filters.difficulty && problem.difficulty !== filters.difficulty) return false;
    if (filters.topic && !problem.topics.includes(filters.topic)) return false;
    const variant = filters.language ? problem.variants.find(v => v.language === filters.language) : undefined;
    if (filters.language && !variant) return false;
    if (filters.status) {
      const status = variant ? practiceStatus(progress?.exercises[variant.key]) : problemSummary(problem, progress).status;
      if (status !== filters.status) return false;
    }
    if (!needle) return true;
    return [problem.key, problem.title, problem.packTitle, problem.difficulty, problem.prompt, ...problem.topics,
      ...problem.variants.flatMap(v => [v.id, v.language, languageLabel(v.language)])]
      .some(value => value.toLowerCase().includes(needle));
  });
}

export function problemCounts(problems: readonly PracticeProblem[], progress: PracticeProgress | undefined):
  Record<PracticeStatus, number> {
  const counts: Record<PracticeStatus, number> = { solved: 0, attempted: 0, "not-started": 0 };
  for (const problem of problems) counts[problemSummary(problem, progress).status] += 1;
  return counts;
}

/**
 * The variant a card shows: the learner's choice for this problem, else the language filter, else the language the
 * learner last picked anywhere, else the first language offered.
 */
export function pickVariant(problem: PracticeProblem, choice: { chosen?: string; filter?: string; preferred?: string }):
  ExerciseSummary {
  for (const language of [choice.chosen, choice.filter, choice.preferred]) {
    const variant = language ? problem.variants.find(v => v.language === language) : undefined;
    if (variant) return variant;
  }
  return problem.variants[0];
}

/** The per-problem language choices restored from the webview state; anything malformed is dropped. */
export function restoreLanguages(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw as Record<string, unknown>)
    .filter((entry): entry is [string, string] => typeof entry[1] === "string" && /^[A-Za-z0-9_-]{1,40}$/.test(entry[1]))
    .slice(0, 2000));
}

export interface DueProblem {
  problem: PracticeProblem;
  /** The most overdue language of the problem: the card opens on it. */
  language: string;
  /** Other languages of the same problem that are due too. */
  alsoDue: string[];
  overdue: number;
}

/** Problems with a variant due for review on `today` (a local `YYYY-MM-DD`), most overdue first. */
export function dueProblems(problems: readonly PracticeProblem[], progress: PracticeProgress | undefined,
  today: string): DueProblem[] {
  const byKey = new Map<string, { problem: PracticeProblem; language: string }>();
  for (const problem of problems) for (const variant of problem.variants) byKey.set(variant.key, { problem, language: variant.language });
  const result = new Map<string, DueProblem>();
  for (const due of dueReviews([...byKey.keys()], progress?.exercises ?? {}, today)) {
    const { problem, language } = byKey.get(due.key)!;
    const existing = result.get(problem.key);
    if (existing) existing.alsoDue.push(language);
    else result.set(problem.key, { problem, language, alsoDue: [], overdue: due.overdue });
  }
  return [...result.values()];
}

/** How many variants are scheduled, and the first day one falls due after `today`. */
export function upcomingReviews(problems: readonly PracticeProblem[], progress: PracticeProgress | undefined,
  today: string): { scheduled: number; next?: string } {
  let scheduled = 0;
  let next: string | undefined;
  for (const problem of problems) {
    for (const variant of problem.variants) {
      const state = reviewState(progress?.exercises[variant.key]);
      if (!state) continue;
      scheduled += 1;
      if (state.due > today && (!next || state.due < next)) next = state.due;
    }
  }
  return { scheduled, next };
}
