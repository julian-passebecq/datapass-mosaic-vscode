export type LearningMode = 'read' | 'watch' | 'try' | 'exercise' | 'inspect' | 'compare';
export type LearningLanguage = 'sql' | 'sparklab' | 'python' | 'polars' | 'none';
export interface ExerciseRef { id: string; language: string }
export interface MissionRef { pack: string; id: string }
export interface Lesson {
  id: string; version: number; title: string; summary: string; minutes: number;
  concepts: string[]; prerequisites: string[]; related: string[];
  blocks: { kind: 'text' | 'callout' | 'check'; title: string; body: string }[];
  code: { language: LearningLanguage; source: string };
  /** Optional only when the lesson has practice[] or missions[]. */
  exercise?: ExerciseRef;
  /** Practice items, typically concept checks (language quiz); at most 8. */
  checks?: ExerciseRef[];
  /** Extra Practice exercises; at most 6. */
  practice?: ExerciseRef[];
  /** Missions from content/missions/<pack>/pack.json; at most 6. */
  missions?: MissionRef[];
  /** A reference id resolved inside content/reference/ only. */
  cheatsheet?: string;
  /** A flashcard deck id (content/learning/flashcards/<id>.json). */
  deck?: string;
  lab: 'mosaic' | 'practice' | 'sparklab' | 'airflow' | 'pipeline' | 'bi' | 'fabric' | 'dbt' | 'lakehouse' | 'apilab' | 'terminal' | 'infra';
  visual: { kind: 'join' | 'window' | 'partitions' | 'dag' | 'grain' | 'storage' | 'timeline'; title: string;
    steps: { title: string; body: string; lines?: [number, number] }[];
    nodes?: { id: string; title: string }[]; edges?: [string, string][] };
}
export interface LearningPath { id: string; title: string; summary: string; lessons: string[] }
export interface LearningCatalog { format: 'datapass.learning'; version: 1; paths: LearningPath[]; lessons: Lesson[] }
export interface Flashcard { id: string; front: string; back: string; lesson?: string; tags: string[] }
export interface FlashcardDeck { format: 'datapass.flashcards'; version: 1; id: string; title: string; path: string; cards: Flashcard[] }
export interface ReviewScheduleLike { box: number; due: string }
export interface FlashcardRecord { attempts: number; review?: ReviewScheduleLike; last?: { at: string; rating: 'knew' | 'missed' } }
export interface ExecutedRecord { version: number; at: string; sourceHash: string; language: LearningLanguage }
export interface LearningState {
  version: 1; path: string; lesson: string; mode: LearningMode; railHidden: boolean; layout: 'balanced' | 'focus' | 'compact';
  read: Record<string, { version: number; at: string }>; notes: Record<string, string>;
  /** Ran locally, not graded: the last successful Learning Run per lesson version. */
  executed: Record<string, ExecutedRecord>;
  /** Self-rated flashcards, keyed `<deck>/<card>`; separate from Practice Review. */
  flashcards: Record<string, FlashcardRecord>;
}
export interface LessonProgress {
  read: boolean;
  checks: { id: string; language: string; status: 'passed' | 'failed' | 'unanswered'; source: 'exercise' | 'checks'; index: number }[];
  executed: ExecutedRecord | undefined;
  verified: boolean;
  exercise: boolean | undefined;
  practice: { id: string; language: string; passed: boolean }[];
}
export type LearningMessage =
  | { type: 'ready' | 'nativePath' | 'export' | 'openRuntime' | 'reviewClose' }
  | { type: 'read' | 'hint' | 'openExample' | 'run' | 'runSelection' | 'explain' | 'openLab' | 'pin' | 'openPractice' | 'next' | 'previous' | 'cheatsheet' | 'openDeck'; lesson: string }
  | { type: 'select'; path: string; lesson: string }
  | { type: 'mode'; lesson: string; mode: LearningMode }
  | { type: 'grade'; lesson: string; mode: 'run' | 'submit' }
  | { type: 'rail'; hidden: boolean }
  | { type: 'layout'; layout: 'balanced' | 'focus' | 'compact' }
  | { type: 'note'; lesson: string; text: string }
  | { type: 'focusStep' | 'openCheck' | 'openPracticeItem' | 'openMission'; lesson: string; index: number }
  | { type: 'review'; deck?: string }
  | { type: 'rate'; deck: string; card: string; rating: 'knew' | 'missed' }
  | { type: 'openCheatsheet'; id: string };
export const MODES: readonly LearningMode[];
export const MODE_LABELS: Readonly<Record<LearningMode, string>>;
export const LABS: readonly string[];
export const LANGUAGES: readonly LearningLanguage[];
export const LESSON_FIELDS: readonly string[];
export const LIMITS: Readonly<{ checks: number; practice: number; missions: number; cards: number; front: number; back: number; tags: number }>;
export const QUIZ_LANGUAGES: readonly string[];
export const LEVEL_LABELS: Readonly<{ read: string; quiz: string; executed: string; verified: string }>;
export function refKey(ref: ExerciseRef): string;
export function cardKey(deck: string, card: string): string;
export function assembleCatalog(index: unknown, readPath: (id: string) => unknown): unknown;
export function validateCatalog(raw: unknown): LearningCatalog;
export function validateLinks(catalog: LearningCatalog, known: { exercises?: Set<string>; missions?: Set<string>; cheatsheets?: Set<string>; decks?: Set<string> }): LearningCatalog;
export function validateDeck(raw: unknown, expectedId?: string, catalog?: LearningCatalog): FlashcardDeck;
export function initialState(catalog: LearningCatalog): LearningState;
export function restoreState(catalog: LearningCatalog, raw: unknown, options?: { decks?: FlashcardDeck[]; parseReview?: (raw: unknown) => ReviewScheduleLike | undefined }): LearningState;
export function lessonStatus(lesson: Lesson, state: LearningState, exercise: {key: string; version: string} | undefined, practice: unknown): 'new' | 'read' | 'practiced';
export function lessonProgress(lesson: Lesson, state: LearningState, resolve: (ref: ExerciseRef) => { key: string; version: string } | undefined, practice: unknown): LessonProgress;
export function levelBadges(lesson: Lesson, progress: LessonProgress, labels?: { read: string; quiz: string; executed: string; verified: string }): { level: 'read' | 'quiz' | 'executed' | 'verified'; text: string; title?: string }[];
export function nextUnverified(catalog: LearningCatalog, state: LearningState, resolve: (ref: ExerciseRef) => { key: string; version: string } | undefined, practice: unknown):
  { path: string; lesson: string; kind: 'check' | 'exercise'; id: string; language: string } | undefined;
export function parseMessage(raw: unknown, catalog: LearningCatalog, extras?: { decks?: FlashcardDeck[]; cheatsheets?: string[] }): LearningMessage | undefined;
export function searchLessons(catalog: LearningCatalog, query: string): Lesson[];
export function searchAll(catalog: LearningCatalog, query: string, extras?: { cheatsheets?: { id: string; title: string }[]; cards?: { deck: string; id: string; front: string }[] }):
  { lessons: Lesson[]; cheatsheets: { id: string; title: string }[]; cards: { deck: string; id: string; front: string }[] };
export function isCurrentRun(run: {lesson: string; sourceHash: string} | undefined, lesson: string, hash: string): boolean;
export function compareRuns(a: unknown, b: unknown): { compatible: boolean; reason: string };
