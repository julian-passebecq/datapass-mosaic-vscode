export type LearningMode = 'read' | 'watch' | 'try' | 'exercise' | 'inspect' | 'compare';
export type LearningLanguage = 'sql' | 'sparklab' | 'python' | 'polars' | 'none';
export interface Lesson {
  id: string; version: number; title: string; summary: string; minutes: number;
  concepts: string[]; prerequisites: string[]; related: string[];
  blocks: { kind: 'text' | 'callout' | 'check'; title: string; body: string }[];
  code: { language: LearningLanguage; source: string };
  exercise: { id: string; language: string };
  lab: 'mosaic' | 'practice' | 'sparklab' | 'airflow' | 'pipeline' | 'bi' | 'fabric' | 'dbt' | 'lakehouse' | 'apilab' | 'terminal' | 'infra';
  visual: { kind: 'join' | 'window' | 'partitions' | 'dag' | 'grain' | 'storage' | 'timeline'; title: string;
    steps: { title: string; body: string; lines?: [number, number] }[];
    nodes?: { id: string; title: string }[]; edges?: [string, string][] };
}
export interface LearningPath { id: string; title: string; summary: string; lessons: string[] }
export interface LearningCatalog { format: 'datapass.learning'; version: 1; paths: LearningPath[]; lessons: Lesson[] }
export interface LearningState { version: 1; path: string; lesson: string; mode: LearningMode; railHidden: boolean; layout: 'balanced' | 'focus' | 'compact'; read: Record<string, { version: number; at: string }>; notes: Record<string, string> }
export type LearningMessage =
  | { type: 'ready' | 'nativePath' | 'export' | 'openRuntime' }
  | { type: 'read' | 'hint' | 'openExample' | 'run' | 'runSelection' | 'explain' | 'openLab' | 'pin' | 'openPractice' | 'next' | 'previous'; lesson: string }
  | { type: 'select'; path: string; lesson: string }
  | { type: 'mode'; lesson: string; mode: LearningMode }
  | { type: 'grade'; lesson: string; mode: 'run' | 'submit' }
  | { type: 'rail'; hidden: boolean }
  | { type: 'layout'; layout: 'balanced' | 'focus' | 'compact' }
  | { type: 'note'; lesson: string; text: string }
  | { type: 'focusStep'; lesson: string; index: number };
export const MODES: readonly LearningMode[];
export const MODE_LABELS: Readonly<Record<LearningMode, string>>;
export const LABS: readonly string[];
export const LANGUAGES: readonly LearningLanguage[];
export function validateCatalog(raw: unknown): LearningCatalog;
export function initialState(catalog: LearningCatalog): LearningState;
export function restoreState(catalog: LearningCatalog, raw: unknown): LearningState;
export function lessonStatus(lesson: Lesson, state: LearningState, exercise: {key: string; version: string} | undefined, practice: unknown): 'new' | 'read' | 'practiced';
export function parseMessage(raw: unknown, catalog: LearningCatalog): LearningMessage | undefined;
export function searchLessons(catalog: LearningCatalog, query: string): Lesson[];
export function isCurrentRun(run: {lesson: string; sourceHash: string} | undefined, lesson: string, hash: string): boolean;
export function compareRuns(a: unknown, b: unknown): { compatible: boolean; reason: string };
