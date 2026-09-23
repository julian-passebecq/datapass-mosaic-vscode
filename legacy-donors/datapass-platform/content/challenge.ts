import type { FigureSpec } from './contracts';
import type { JsonValue } from './json';

export type ChallengeLanguage = 'python' | 'pandas' | 'pyspark' | 'sql' | 'tsql' | 'duckdb' | 'bigquery' | 'dax' | 'csharp' | 'powershell' | 'bash' | 'shell' | 'yaml' | 'dockerfile' | 'plaintext';
export type ChallengeDifficulty = 'Easy' | 'Medium' | 'Hard';
export interface ChallengeVariant {
  id: string;
  language: ChallengeLanguage;
  label: string;
  monacoLanguage: string;
  starter: string;
  solution: string;
  explanation?: string;
  note?: string;
}
/** The former Studio-only challenge contract, extended additively for real consumers. */
export interface ChallengeDefinition {
  id: string;
  title: string;
  domain: string;
  difficulty: ChallengeDifficulty;
  tags: string[];
  summary: string;
  schema: string;
  input: string;
  example: string;
  expectedOutput: string;
  hints: string[];
  visualization?: 'join';
  variants: ChallengeVariant[];
  figure?: FigureSpec;
}
export interface PracticeSource {
  repository: string;
  revision: string;
  itemId: string;
  collection: string;
  sourcePack?: string;
  officialSources?: JsonValue;
}
export interface PracticeItem extends ChallengeDefinition {
  trackId: string;
  concept: string;
  why: string;
  pitfall: string;
  source: PracticeSource;
  /** Preserves original pedagogy metadata without copying a legacy renderer. */
  sourceRecord: JsonValue;
  execution: 'none';
}
export interface PracticeTrack { id: string; name: string; description: string; collection: string }
export interface PracticeCheatSheet {
  id: string; label: string; subtitle: string; language: string;
  sections: [string, string][]; mentalModels: string[]; useFor: string[]; starter: string;
}
export interface PracticeCatalog {
  schemaVersion: 1;
  source: { repository: string; revision: string };
  items: PracticeItem[];
  tracks: PracticeTrack[];
  cheatSheets: PracticeCheatSheet[];
}
