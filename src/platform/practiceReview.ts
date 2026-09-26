/**
 * Spaced review of Practice exercises: a Leitner schedule per language variant, kept in the variant's record of the
 * `practice` section of .datapass/progress.json (`review: { box, due }`).
 *
 * The schedule (documented in docs/EXERCISE_AUTHORING.md, "Spaced review"):
 * - Six boxes. A passed Submit on a variant that is due (or has never been reviewed) moves it up one box; it is due
 *   again after 1, 3, 7, 14, 30 or 60 days (box 1 to 6). Box 6 stays at 60 days.
 * - A Submit that fails or errors sends it back to box 1, due the next day.
 * - A passed Submit before the due day changes nothing: re-submitting the same day does not climb the boxes.
 * - Run visible never moves a box (it is how a learner iterates).
 * - Only variants the learner has opened or graded are scheduled. A variant started before this schedule existed
 *   is due the day after its last activity (box 1 if solved, box 0 if not).
 * Days are local calendar days (`YYYY-MM-DD`): a variant due tomorrow is due all day tomorrow.
 * Pure functions, shared by the host and the webview; tested by scripts/practice_arena_smoke.mjs.
 */

export const REVIEW_INTERVALS_DAYS = [1, 3, 7, 14, 30, 60];
export const REVIEW_BOXES = REVIEW_INTERVALS_DAYS.length;

export interface ReviewSchedule {
  /** 1 to REVIEW_BOXES. */
  box: number;
  /** Local calendar day `YYYY-MM-DD` from which the variant is due. */
  due: string;
}

/** The parts of a variant's progress record the schedule reads (see platform/practiceProgress.ts). */
export interface ReviewedRecord {
  openedAt?: string;
  attempts: number;
  solved?: { at: string };
  last?: { at: string };
  review?: ReviewSchedule;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The local calendar day of an instant (ISO string or Date). */
export function localDay(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return localDay(new Date(y, m - 1, d + days));
}

/** Whole days from `from` to `to` (both `YYYY-MM-DD`); negative when `to` is earlier. */
export function daysBetween(from: string, to: string): number {
  const at = (day: string) => {
    const [y, m, d] = day.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((at(to) - at(from)) / 86_400_000);
}

export function parseReview(raw: unknown): ReviewSchedule | undefined {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : undefined;
  const box = value?.box;
  const due = value?.due;
  if (typeof box !== "number" || !Number.isInteger(box) || box < 1 || box > REVIEW_BOXES) return undefined;
  if (typeof due !== "string" || !DAY.test(due) || Number.isNaN(Date.parse(due))) return undefined;
  return { box, due };
}

/** The schedule after a grading of this variant at `now`. Run visible leaves it as it was. */
export function nextReview(record: ReviewedRecord, mode: "run" | "submit", status: "passed" | "failed" | "error",
  now: string): ReviewSchedule | undefined {
  if (mode !== "submit") return record.review;
  const today = localDay(now);
  if (status !== "passed") return { box: 1, due: addDays(today, REVIEW_INTERVALS_DAYS[0]) };
  const current = reviewState(record);
  if (current && current.box > 0 && current.due > today) return record.review ?? { box: current.box, due: current.due };
  const box = Math.min(REVIEW_BOXES, (current?.box ?? 0) + 1);
  return { box, due: addDays(today, REVIEW_INTERVALS_DAYS[box - 1]) };
}

/**
 * The variant's place in the schedule: its stored review, or for a variant started before the schedule existed, due
 * the day after its last activity. Undefined when the learner never opened or graded it.
 */
export function reviewState(record: ReviewedRecord | undefined): { box: number; due: string } | undefined {
  if (!record) return undefined;
  if (record.review) return record.review;
  const last = record.last?.at ?? record.solved?.at ?? record.openedAt;
  if (!last || Number.isNaN(Date.parse(last))) return undefined;
  return { box: record.solved ? 1 : 0, due: addDays(localDay(last), REVIEW_INTERVALS_DAYS[0]) };
}

export interface DueReview {
  key: string;
  box: number;
  due: string;
  /** Days past the due day (0 on the day itself). */
  overdue: number;
}

/**
 * The variants due for review on `today`, among `keys` (the installed catalog): the most overdue first, then the
 * lowest box (the weakest), then by key.
 */
export function dueReviews(keys: readonly string[], records: Readonly<Record<string, ReviewedRecord | undefined>>,
  today: string): DueReview[] {
  const due: DueReview[] = [];
  for (const key of keys) {
    const state = reviewState(records[key]);
    if (!state || state.due > today) continue;
    due.push({ key, box: state.box, due: state.due, overdue: daysBetween(state.due, today) });
  }
  return due.sort((a, b) => b.overdue - a.overdue || a.box - b.box || a.key.localeCompare(b.key));
}

/** A short line for a card: "Review due today", "Review due 3 days ago", "Next review in 5 days · box 3 of 6". */
export function reviewLabel(record: ReviewedRecord | undefined, today: string): string | undefined {
  const state = reviewState(record);
  if (!state) return undefined;
  const days = daysBetween(today, state.due);
  const box = state.box > 0 ? ` · box ${state.box} of ${REVIEW_BOXES}` : "";
  if (days <= 0) return `Review due ${days === 0 ? "today" : days === -1 ? "since yesterday" : `for ${-days} days`}${box}`;
  return `Next review ${days === 1 ? "tomorrow" : `in ${days} days`}${box}`;
}
