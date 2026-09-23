function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function normalizeLanguage(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'python3' || normalized === 'py') return 'python';
  if (normalized === 'spark' || normalized === 'spark-python') return 'pyspark';
  if (normalized === 'postgresql' || normalized === 'postgres' || normalized === 'tsql') return 'sql';
  return normalized;
}

function explicitCellLanguage(metadata: unknown): string | undefined {
  if (!isRecord(metadata)) return undefined;
  for (const candidate of [
    metadata.language,
    metadata.languageId,
    isRecord(metadata.vscode) ? metadata.vscode.languageId : undefined,
    isRecord(metadata.datapass) ? metadata.datapass.language : undefined,
  ]) {
    if (typeof candidate === 'string' && candidate.trim()) return normalizeLanguage(candidate);
  }
  if (Array.isArray(metadata.tags)) {
    for (const tag of metadata.tags) {
      if (typeof tag !== 'string') continue;
      const match = tag.trim().toLowerCase().match(/^(?:language|lang)[:=-](.+)$/);
      if (match?.[1]) return normalizeLanguage(match[1]);
      if (['sql', 'python', 'pyspark'].includes(tag.trim().toLowerCase())) return normalizeLanguage(tag);
    }
  }
  return undefined;
}

function withoutLeadingComments(source: string): string {
  let output = source.trimStart();
  while (output.startsWith('--') || output.startsWith('/*')) {
    if (output.startsWith('--')) {
      const newline = output.indexOf('\n');
      output = newline < 0 ? '' : output.slice(newline + 1).trimStart();
      continue;
    }
    const end = output.indexOf('*/', 2);
    if (end < 0) return output;
    output = output.slice(end + 2).trimStart();
  }
  return output;
}

function looksLikeSql(source: string): boolean {
  const candidate = withoutLeadingComments(source)
    .replace(/^%%?sql\b[^\n]*\n?/i, '')
    .trimStart();
  return /^(?:select\b|insert\s+into\b|update\s+[\w.[\]`"]+\s+set\b|delete\s+from\b|merge\s+into\b|create\s+(?:or\s+replace\s+)?(?:table|view)\b|alter\s+(?:table|view)\b|drop\s+(?:table|view)\b|explain\b|show\b|describe\b|use\b|with\s+[\w"`\[\]]+\s+as\s*\()/i.test(candidate);
}

function looksLikePySpark(source: string): boolean {
  return /(?:^|\n)\s*(?:from\s+pyspark\b|import\s+pyspark\b)/m.test(source)
    || /\bSparkSession\b/.test(source);
}

/** Resolve explicit cell metadata first, then conservative source signatures. */
export function detectCodeCellLanguage(source: string, metadata: unknown, notebookLanguage: string): string {
  const explicit = explicitCellLanguage(metadata);
  if (explicit) return explicit;
  if (looksLikePySpark(source)) return 'pyspark';
  if (looksLikeSql(source)) return 'sql';
  return normalizeLanguage(notebookLanguage) || 'text';
}

export function detectNotebookLanguage(metadata: unknown, fallback?: string): string {
  if (!isRecord(metadata)) return normalizeLanguage(fallback ?? 'text') || 'text';
  if (isRecord(metadata.kernelspec)) {
    const kernelIdentity = [metadata.kernelspec.name, metadata.kernelspec.display_name]
      .filter((candidate): candidate is string => typeof candidate === 'string')
      .join(' ')
      .toLowerCase();
    if (kernelIdentity.includes('pyspark')) return 'pyspark';
    if (kernelIdentity.includes('sql')) return 'sql';
  }
  if (isRecord(metadata.language_info) && typeof metadata.language_info.name === 'string' && metadata.language_info.name.trim()) {
    return normalizeLanguage(metadata.language_info.name);
  }
  if (isRecord(metadata.kernelspec) && typeof metadata.kernelspec.language === 'string' && metadata.kernelspec.language.trim()) {
    return normalizeLanguage(metadata.kernelspec.language);
  }
  return normalizeLanguage(fallback ?? 'text') || 'text';
}
