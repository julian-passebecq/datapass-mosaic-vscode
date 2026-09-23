import type { ChallengeDefinition } from './challenge';
import type { ContentValidationResult } from './validation';
import { toCanonicalJsonValue } from './json';
const LANGUAGES = new Set(['python', 'pandas', 'pyspark', 'sql', 'tsql', 'duckdb', 'bigquery', 'dax', 'csharp', 'powershell', 'bash', 'shell', 'yaml', 'dockerfile', 'plaintext']);
function hasOnlyJsonValues(value: unknown, seen = new Set<object>()): boolean {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'object' || seen.has(value)) return false;
  seen.add(value);
  const valid = Object.values(value).every(child => hasOnlyJsonValues(child, seen));
  seen.delete(value);
  return valid;
}

export function validateChallenge(value: unknown): ContentValidationResult {
  const issues: ContentValidationResult['issues'][number][] = [];
  const fail = (path: string, message: string) => issues.push({ code: 'content.challenge.invalid', path, message, severity: 'error' });
  try { toCanonicalJsonValue(value); if (!hasOnlyJsonValues(value)) fail('', 'Challenge must contain only JSON values.'); } catch { fail('', 'Challenge must be serializable JSON.'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    fail('', 'Challenge must be an object.'); return { valid: false, issues };
  }
  const item = value as Record<string, unknown>;
  for (const key of ['id', 'title', 'domain', 'summary']) if (typeof item[key] !== 'string' || !(item[key] as string).trim()) fail(key, `${key} is required.`);
  for (const key of ['schema', 'input', 'example', 'expectedOutput']) if (typeof item[key] !== 'string') fail(key, `${key} must be text.`);
  if (!['Easy', 'Medium', 'Hard'].includes(String(item.difficulty))) fail('difficulty', 'Unknown difficulty.');
  for (const key of ['tags', 'hints']) if (!Array.isArray(item[key]) || !(item[key] as unknown[]).every(v => typeof v === 'string')) fail(key, `${key} must be a text array.`);
  if (!Array.isArray(item.variants) || !item.variants.length) fail('variants', 'At least one variant is required.');
  else {
    const ids = new Set<string>();
    item.variants.forEach((candidate: unknown, index: number) => {
      const v = candidate && typeof candidate === 'object' && !Array.isArray(candidate) ? candidate as Record<string, unknown> : {};
      for (const key of ['id', 'language', 'label', 'monacoLanguage', 'starter', 'solution']) if (typeof v[key] !== 'string' || !(v[key] as string).trim()) fail(`variants[${index}].${key}`, `${key} is required.`);
      if (!LANGUAGES.has(String(v.language))) fail(`variants[${index}].language`, 'Unknown practice language.');
      if (typeof v.id === 'string') { if (ids.has(v.id)) fail(`variants[${index}].id`, 'Variant IDs must be unique.'); ids.add(v.id); }
    });
  }
  if ('execution' in item && item.execution !== 'none') fail('execution', 'V3 practice content does not execute code.');
  return { valid: issues.length === 0, issues };
}

export function assertValidChallenge<T extends ChallengeDefinition>(value: T): T {
  const result = validateChallenge(value);
  if (!result.valid) throw new Error(result.issues.map(issue => `${issue.path}: ${issue.message}`).join('\n'));
  return value;
}
