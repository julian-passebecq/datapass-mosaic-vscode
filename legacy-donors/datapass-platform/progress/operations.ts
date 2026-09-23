import {
  type AssessmentAttempt,
  type AssessmentProgress,
  type AssessmentScore,
  type ChallengeProgress,
  type LessonProgress,
  type ProgressBreakdown,
  type ProgressBreakdownMetric,
  type ProgressStateV2
} from './types';

function requiredId(value: string, name: string): string {
  if (!value.trim()) throw new Error(`${name} must be non-empty.`);
  return value;
}

function sortedRecord<T>(record: Readonly<Record<string, T>>): Readonly<Record<string, T>> {
  return Object.fromEntries(Object.keys(record).sort().map((key) => [key, record[key]]));
}

export function setChallengeDraft(
  state: ProgressStateV2,
  challengeId: string,
  variantId: string,
  draft: string,
  updatedAt?: string
): ProgressStateV2 {
  requiredId(challengeId, 'challengeId');
  requiredId(variantId, 'variantId');
  const current: ChallengeProgress = state.challenges[challengeId] ?? {
    id: challengeId,
    status: 'not-started',
    drafts: {},
    mastered: false,
    review: false,
    flagged: false
  };
  const next: ChallengeProgress = {
    ...current,
    status: current.status === 'completed' ? 'completed' : 'in-progress',
    drafts: sortedRecord({ ...current.drafts, [variantId]: draft }),
    ...(updatedAt === undefined ? {} : { updatedAt })
  };
  return { ...state, challenges: sortedRecord({ ...state.challenges, [challengeId]: next }) };
}

export interface ChallengeProgressPatch {
  readonly status?: ChallengeProgress['status'];
  readonly mastered?: boolean;
  readonly review?: boolean;
  readonly flagged?: boolean;
  readonly updatedAt?: string;
}

export function updateChallengeProgress(state: ProgressStateV2, challengeId: string, patch: ChallengeProgressPatch): ProgressStateV2 {
  requiredId(challengeId, 'challengeId');
  const current: ChallengeProgress = state.challenges[challengeId] ?? {
    id: challengeId,
    status: 'not-started',
    drafts: {},
    mastered: false,
    review: false,
    flagged: false
  };
  const mastered = patch.mastered ?? current.mastered;
  const next: ChallengeProgress = {
    ...current,
    ...patch,
    mastered,
    status: patch.status ?? (mastered ? 'completed' : current.status)
  };
  return { ...state, challenges: sortedRecord({ ...state.challenges, [challengeId]: next }) };
}

export interface LessonProgressPatch extends Omit<Partial<LessonProgress>, 'id'> {}

export function updateLessonProgress(state: ProgressStateV2, lessonId: string, patch: LessonProgressPatch): ProgressStateV2 {
  requiredId(lessonId, 'lessonId');
  const current: LessonProgress = state.lessons[lessonId] ?? {
    id: lessonId,
    status: 'not-started',
    completed: false
  };
  const status = patch.status
    ?? (patch.completed === true ? 'completed' : patch.completed === false && current.status === 'completed' ? 'in-progress' : current.status);
  const completed = status === 'completed';
  const next: LessonProgress = { ...current, ...patch, id: lessonId, completed, status };
  return { ...state, lessons: sortedRecord({ ...state.lessons, [lessonId]: next }) };
}

export function createAssessmentScore(earned: number, possible: number, passingPercent?: number): AssessmentScore {
  if (!Number.isFinite(earned) || earned < 0 || !Number.isFinite(possible) || possible < 0 || earned > possible) {
    throw new Error('Assessment score requires 0 <= earned <= possible.');
  }
  if (passingPercent !== undefined && (!Number.isFinite(passingPercent) || passingPercent < 0 || passingPercent > 100)) {
    throw new Error('passingPercent must be between 0 and 100.');
  }
  const percent = possible === 0 ? 0 : Number(((earned / possible) * 100).toFixed(2));
  return { earned, possible, percent, ...(passingPercent === undefined ? {} : { passed: percent >= passingPercent }) };
}

export function appendAssessmentAttempt(state: ProgressStateV2, assessmentId: string, attempt: AssessmentAttempt): ProgressStateV2 {
  requiredId(assessmentId, 'assessmentId');
  if (attempt.assessmentId !== assessmentId) throw new Error(`Attempt assessmentId must be "${assessmentId}".`);
  const current: AssessmentProgress = state.assessments[assessmentId] ?? { id: assessmentId, attempts: [] };
  if (current.attempts.some((candidate) => candidate.id === attempt.id)) throw new Error(`Attempt id "${attempt.id}" already exists.`);
  const next: AssessmentProgress = {
    id: assessmentId,
    attempts: [...current.attempts, attempt],
    ...(attempt.status === 'in-progress' ? { activeAttemptId: attempt.id } : {})
  };
  return { ...state, assessments: sortedRecord({ ...state.assessments, [assessmentId]: next }) };
}

interface MutableBreakdown {
  answers: number;
  correct: number;
  earned: number;
  possible: number;
}

function addBreakdown(map: Map<string, MutableBreakdown>, ids: readonly string[], correct: boolean, earned: number, possible: number): void {
  for (const id of [...new Set(ids)].sort()) {
    const metric = map.get(id) ?? { answers: 0, correct: 0, earned: 0, possible: 0 };
    metric.answers += 1;
    metric.correct += correct ? 1 : 0;
    metric.earned += earned;
    metric.possible += possible;
    map.set(id, metric);
  }
}

function finishBreakdown(map: ReadonlyMap<string, MutableBreakdown>): readonly ProgressBreakdownMetric[] {
  return [...map.entries()].sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0).map(([id, value]) => ({
    id,
    ...value,
    percent: value.possible === 0 ? 0 : Number(((value.earned / value.possible) * 100).toFixed(2))
  }));
}

export function computeProgressBreakdown(state: ProgressStateV2): ProgressBreakdown {
  const domains = new Map<string, MutableBreakdown>();
  const concepts = new Map<string, MutableBreakdown>();
  Object.keys(state.assessments).sort().forEach((assessmentId) => {
    const assessment = state.assessments[assessmentId];
    assessment.attempts.filter((attempt) => attempt.status === 'submitted').forEach((attempt) => {
      Object.keys(attempt.answers).sort().forEach((questionId) => {
        const answer = attempt.answers[questionId];
        if (answer.correct === undefined && answer.pointsEarned === undefined) return;
        const possible = answer.pointsPossible ?? 1;
        const earned = answer.pointsEarned ?? (answer.correct ? possible : 0);
        addBreakdown(domains, answer.domainIds ?? [], answer.correct === true, earned, possible);
        addBreakdown(concepts, answer.conceptIds ?? [], answer.correct === true, earned, possible);
      });
    });
  });
  return { domains: finishBreakdown(domains), concepts: finishBreakdown(concepts) };
}
