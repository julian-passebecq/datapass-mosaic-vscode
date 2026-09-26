/**
 * Practice interview mode: a random series of problems, a timer, no hints, and a summary at the end.
 *
 * - Two formats. "fixed": every problem in one language the learner picks. "mixed": a classic data-engineering
 *   interview, cycling SQL, Python and PySpark, one problem per slot.
 * - The draw favours coverage: each problem gets a pattern family from its topics (joins, aggregation, window
 *   functions, deduplication, time series, nulls and data quality, strings and parsing, filtering and logic), and a
 *   series avoids repeating a family while it can. Only problems graded locally are drawn.
 * - The timer runs into overtime: Submit stays open after the limit and the summary shows the overtime.
 * - An interview Submit is a normal grading (it solves the variant and moves the spaced review). The series is
 *   tracked from the variants' progress records; its summary is kept in `practice.interviews` of
 *   .datapass/progress.json (the last INTERVIEW_HISTORY series).
 * Pure functions, shared by the host and the webview; tested by scripts/practice_arena_smoke.mjs.
 */
import type { PracticeProblem } from "./practiceProblems";

export type InterviewFormat = "fixed" | "mixed";
export const MIXED_LANGUAGES = ["sql", "python", "sparklab"];
export const INTERVIEW_HISTORY = 20;
export const MAX_INTERVIEW_PROBLEMS = 8;

export interface PatternFamily { id: string; label: string; topics: string[] }

/** Classic interview patterns, in the order a problem's family is looked up. */
export const PATTERN_FAMILIES: PatternFamily[] = [
  { id: "windows", label: "Window functions and ranking", topics: ["window-functions", "windows", "row-number", "dense-rank",
    "ranking", "lag", "lead", "partition-by", "frames", "window-frames", "running-total", "top-n", "qualify", "ties"] },
  { id: "time", label: "Dates and time series", topics: ["gaps-and-islands", "sessionization", "cohorts", "funnel",
    "time-series", "generate-series", "dates", "datetime"] },
  { id: "dedup", label: "Deduplication and change tracking", topics: ["deduplication", "duplicates", "distinct", "scd2",
    "change-detection", "merge", "upsert", "incremental-load"] },
  { id: "joins", label: "Joins", topics: ["joins", "left-join", "inner-join", "self-join", "semi-join", "anti-join",
    "full-outer-join", "full-join", "cross-join", "asof-join", "broadcast-join", "fan-out"] },
  { id: "aggregation", label: "Aggregation and grouping", topics: ["aggregation", "group-by", "having", "grouping-sets",
    "rollup", "cube", "conditional-aggregation", "count", "counting", "pivot", "median", "statistics"] },
  { id: "quality", label: "Nulls and data quality", topics: ["nulls", "coalesce", "data-quality", "outliers",
    "reconciliation", "casting", "normalization"] },
  { id: "strings", label: "Strings and parsing", topics: ["strings", "regular-expressions", "parsing", "unnest", "arrays"] },
  { id: "logic", label: "Filtering and logic", topics: ["filtering", "conditional-logic", "case-when", "conditionals",
    "subquery", "cte", "union", "sets", "ordering", "projection"] }
];

/** The problem's pattern family: the first family, in PATTERN_FAMILIES order, that one of its topics belongs to. */
export function problemFamily(problem: Pick<PracticeProblem, "topics">): PatternFamily | undefined {
  return PATTERN_FAMILIES.find(family => family.topics.some(topic => problem.topics.includes(topic)));
}

export function familyLabel(id: string | undefined): string {
  return PATTERN_FAMILIES.find(family => family.id === id)?.label ?? "Other";
}

export interface InterviewOptions {
  format: InterviewFormat;
  /** The language of a fixed series. */
  language?: string;
  count: number;
  /** "" for any difficulty. */
  difficulty: string;
  /** A PATTERN_FAMILIES id, or "" for any (fixed series only). */
  family: string;
}

export interface InterviewItem {
  problemKey: string;
  exerciseKey: string;
  language: string;
  family?: string;
  /** The variant's gradings when the series started, then when the series last read them. */
  seenAttempts: number;
  submits: number;
  /** When the first passing Submit of the series was recorded (ISO). */
  passedAt?: string;
}

export interface InterviewSession {
  startedAt: string;
  limitMinutes: number;
  format: InterviewFormat;
  language?: string;
  items: InterviewItem[];
  finishedAt?: string;
}

/** Deterministic pseudo-random numbers in [0, 1) (mulberry32), so a seed replays a draw. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The languages a series can be drawn in: those with at least one locally graded variant. */
export function interviewLanguages(problems: readonly PracticeProblem[]): string[] {
  const languages = new Set<string>();
  for (const problem of problems) for (const v of problem.variants) if (!v.gradingNote) languages.add(v.language);
  return [...languages];
}

/**
 * Draw a series. Each slot (the fixed language, or SQL, Python, PySpark in turn) takes a random problem offered in
 * that language, preferring one whose pattern family the series does not have yet. Fewer problems come back when
 * the filters leave too few.
 */
export function drawInterview(problems: readonly PracticeProblem[], options: InterviewOptions,
  random: () => number): Omit<InterviewItem, "seenAttempts" | "submits">[] {
  const count = Math.max(1, Math.min(MAX_INTERVIEW_PROBLEMS, Math.floor(options.count)));
  const slots = options.format === "mixed"
    ? Array.from({ length: count }, (_, index) => MIXED_LANGUAGES[index % MIXED_LANGUAGES.length])
    : Array.from({ length: count }, () => options.language ?? "sql");
  const used = new Set<string>();
  const families = new Set<string>();
  const drawn: Omit<InterviewItem, "seenAttempts" | "submits">[] = [];
  for (const language of slots) {
    const candidates = problems.flatMap(problem => {
      if (used.has(problem.key)) return [];
      if (options.difficulty && problem.difficulty !== options.difficulty) return [];
      const variant = problem.variants.find(v => v.language === language && !v.gradingNote);
      if (!variant) return [];
      const family = problemFamily(problem)?.id;
      if (options.format === "fixed" && options.family && family !== options.family) return [];
      return [{ problem, variant, family }];
    });
    if (!candidates.length) continue;
    const fresh = candidates.filter(c => c.family && !families.has(c.family));
    const classic = candidates.filter(c => c.family);
    const pool = fresh.length ? fresh : classic.length ? classic : candidates;
    const pick = pool[Math.floor(random() * pool.length) % pool.length];
    used.add(pick.problem.key);
    if (pick.family) families.add(pick.family);
    drawn.push({ problemKey: pick.problem.key, exerciseKey: pick.variant.key, language, family: pick.family });
  }
  return drawn;
}

/** The default time limit: 15 minutes a problem, as a phone-screen round. */
export function defaultLimitMinutes(count: number): number {
  return Math.max(5, Math.min(120, 15 * Math.max(1, count)));
}

export function startInterview(drawn: readonly Omit<InterviewItem, "seenAttempts" | "submits">[], options: InterviewOptions,
  limitMinutes: number, records: Readonly<Record<string, { attempts: number } | undefined>>, now: string): InterviewSession {
  return {
    startedAt: now,
    limitMinutes: Math.max(1, Math.min(240, Math.round(limitMinutes))),
    format: options.format,
    ...(options.format === "fixed" && options.language ? { language: options.language } : {}),
    items: drawn.map(item => ({ ...item, seenAttempts: records[item.exerciseKey]?.attempts ?? 0, submits: 0 }))
  };
}

interface TrackedRecord { attempts: number; last?: { mode: string; status: string; at: string } }

/**
 * Follow the series through the variants' progress records: every new grading is one more attempt; a Submit made
 * since the start counts, and the first that passed marks the problem solved. Returns the same session when nothing
 * changed.
 */
export function trackInterview(session: InterviewSession, records: Readonly<Record<string, TrackedRecord | undefined>>):
  InterviewSession {
  if (session.finishedAt) return session;
  let changed = false;
  const items = session.items.map(item => {
    const record = records[item.exerciseKey];
    if (!record || record.attempts <= item.seenAttempts) return item;
    changed = true;
    const last = record.last;
    const since = last && Date.parse(last.at) >= Date.parse(session.startedAt);
    const submit = Boolean(since && last?.mode === "submit");
    return {
      ...item,
      seenAttempts: record.attempts,
      submits: item.submits + (submit ? 1 : 0),
      ...(!item.passedAt && submit && last?.status === "passed" ? { passedAt: last.at } : {})
    };
  });
  return changed ? { ...session, items } : session;
}

export interface InterviewRecord {
  /** When the series started (ISO). */
  at: string;
  format: InterviewFormat;
  language?: string;
  limitMinutes: number;
  elapsedSeconds: number;
  items: { key: string; family?: string; solved: boolean; solvedAfterSeconds?: number; submits: number }[];
}

export function secondsBetween(from: string, to: string): number {
  return Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 1000));
}

/** The series' summary, as kept in progress.json. */
export function summarizeInterview(session: InterviewSession, finishedAt: string): InterviewRecord {
  return {
    at: session.startedAt,
    format: session.format,
    ...(session.language ? { language: session.language } : {}),
    limitMinutes: session.limitMinutes,
    elapsedSeconds: secondsBetween(session.startedAt, finishedAt),
    items: session.items.map(item => ({
      key: item.exerciseKey,
      ...(item.family ? { family: item.family } : {}),
      solved: Boolean(item.passedAt),
      ...(item.passedAt ? { solvedAfterSeconds: secondsBetween(session.startedAt, item.passedAt) } : {}),
      submits: item.submits
    }))
  };
}

const KEY = /^[A-Za-z0-9_-]{1,100}\/[A-Za-z0-9_.-]{1,160}\/[A-Za-z0-9_-]{1,40}$/;
const count = (value: unknown, max: number) =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= max ? value : undefined;

/** One kept series; anything malformed is dropped, never repaired. */
export function parseInterview(raw: unknown): InterviewRecord | undefined {
  const value = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : undefined;
  if (!value || typeof value.at !== "string" || Number.isNaN(Date.parse(value.at))) return undefined;
  if (value.format !== "fixed" && value.format !== "mixed") return undefined;
  const limitMinutes = count(value.limitMinutes, 240);
  const elapsedSeconds = count(value.elapsedSeconds, 30 * 24 * 3600);
  if (!limitMinutes || elapsedSeconds === undefined || !Array.isArray(value.items)) return undefined;
  if (!value.items.length || value.items.length > MAX_INTERVIEW_PROBLEMS) return undefined;
  const items: InterviewRecord["items"] = [];
  for (const rawItem of value.items) {
    const item = rawItem && typeof rawItem === "object" ? rawItem as Record<string, unknown> : undefined;
    const submits = count(item?.submits, 10_000);
    if (!item || typeof item.key !== "string" || !KEY.test(item.key) || typeof item.solved !== "boolean" || submits === undefined) {
      return undefined;
    }
    const after = count(item.solvedAfterSeconds, 30 * 24 * 3600);
    const family = typeof item.family === "string" && PATTERN_FAMILIES.some(f => f.id === item.family) ? item.family : undefined;
    items.push({ key: item.key, ...(family ? { family } : {}), solved: item.solved,
      ...(item.solved && after !== undefined ? { solvedAfterSeconds: after } : {}), submits });
  }
  const language = typeof value.language === "string" && /^[A-Za-z0-9_-]{1,40}$/.test(value.language) ? value.language : undefined;
  return { at: value.at, format: value.format, ...(language ? { language } : {}), limitMinutes, elapsedSeconds, items };
}

export function parseInterviews(raw: unknown): InterviewRecord[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap(item => parseInterview(item) ?? []).slice(-INTERVIEW_HISTORY);
}

/** "12:05", or "1:02:05" past an hour. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const pad = (n: number) => String(n).padStart(2, "0");
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}
