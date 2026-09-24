export const PROGRESS_SCHEMA_VERSION = 2 as const;
export const DEFAULT_PROGRESS_STORAGE_KEY = 'datapass:progress:v2';
export const LEGACY_CHALLENGE_DRAFTS_KEY = 'datapass:challenge-drafts:v1.1';
export const LEGACY_CHALLENGE_PROGRESS_KEY = 'datapass:challenge-progress:v1.1';

export type ChallengeStatus = 'not-started' | 'in-progress' | 'completed';
export type LessonStatus = 'not-started' | 'in-progress' | 'completed';
export type AssessmentAttemptStatus = 'in-progress' | 'submitted';

export interface ChallengeProgress {
  readonly id: string;
  readonly status: ChallengeStatus;
  /** Draft source keyed by stable variant/language id. */
  readonly drafts: Readonly<Record<string, string>>;
  readonly mastered: boolean;
  readonly review: boolean;
  readonly flagged: boolean;
  readonly updatedAt?: string;
}

export interface LessonPosition {
  readonly sectionId?: string;
  readonly cellId?: string;
  readonly step?: number;
  readonly offset?: number;
}

export interface LessonProgress {
  readonly id: string;
  readonly courseId?: string;
  readonly status: LessonStatus;
  readonly completed: boolean;
  readonly recentPosition?: LessonPosition;
  readonly lastVisitedAt?: string;
  readonly completedAt?: string;
}

export type AssessmentAnswerValue =
  | string
  | number
  | boolean
  | readonly string[]
  | Readonly<Record<string, string>>;

export interface AssessmentAnswer {
  readonly questionId: string;
  readonly value: AssessmentAnswerValue;
  /** Omit until correctness is allowed to be revealed. */
  readonly correct?: boolean;
  readonly pointsEarned?: number;
  readonly pointsPossible?: number;
  readonly domainIds?: readonly string[];
  readonly conceptIds?: readonly string[];
}

export interface AssessmentScore {
  readonly earned: number;
  readonly possible: number;
  readonly percent: number;
  readonly passed?: boolean;
}

export interface AssessmentAttempt {
  readonly id: string;
  readonly assessmentId: string;
  readonly status: AssessmentAttemptStatus;
  readonly startedAt?: string;
  readonly submittedAt?: string;
  readonly answers: Readonly<Record<string, AssessmentAnswer>>;
  readonly score?: AssessmentScore;
}

export interface AssessmentProgress {
  readonly id: string;
  readonly attempts: readonly AssessmentAttempt[];
  readonly activeAttemptId?: string;
}

export interface ProgressStateV2 {
  readonly schemaVersion: typeof PROGRESS_SCHEMA_VERSION;
  readonly challenges: Readonly<Record<string, ChallengeProgress>>;
  readonly lessons: Readonly<Record<string, LessonProgress>>;
  readonly assessments: Readonly<Record<string, AssessmentProgress>>;
}

export interface ProgressBreakdownMetric {
  readonly id: string;
  readonly answers: number;
  readonly correct: number;
  readonly earned: number;
  readonly possible: number;
  readonly percent: number;
}

export interface ProgressBreakdown {
  readonly domains: readonly ProgressBreakdownMetric[];
  readonly concepts: readonly ProgressBreakdownMetric[];
}

export function createEmptyProgressState(): ProgressStateV2 {
  return {
    schemaVersion: PROGRESS_SCHEMA_VERSION,
    challenges: {},
    lessons: {},
    assessments: {}
  };
}
