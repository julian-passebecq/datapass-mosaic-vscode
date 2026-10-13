/**
 * Build: a blank Datapass workspace for the learner's own data work. Pure helpers (no vscode), shared by the
 * commands in buildCommands.ts and scripts/suite/build_workspace.test.mjs. Nothing here writes, runs or trusts code.
 */

/** The folders a blank workspace starts with, all empty. */
export const BUILD_FOLDERS = ["notebooks", "datasets", "notes"] as const;

export type BuildFileKind = "sql" | "python" | "polars" | "markdown";

export interface BuildFileKindSpec {
  kind: BuildFileKind;
  /** Quick pick label. */
  label: string;
  description: string;
  extension: ".sql" | ".py" | ".md";
  /** Where the file goes when no folder is chosen: the manifest's notebooks folder, or notes/. */
  folder: "notebooks" | "notes";
  /** True when running the file needs trusted local Python. */
  needsTrustedPython: boolean;
  defaultName: string;
  /** A few comment lines, no sample data and no table names: the learner's own file. */
  header: (title: string) => string;
}

export const BUILD_FILE_KINDS: readonly BuildFileKindSpec[] = [
  {
    kind: "sql",
    label: "SQL",
    description: "DuckDB SQL on the local catalog (Mosaic: Run active SQL)",
    extension: ".sql",
    folder: "notebooks",
    needsTrustedPython: false,
    defaultName: "query.sql",
    header: title => [
      `-- ${title}`,
      "-- Runs on this workspace's local DuckDB catalog with Mosaic > Run active SQL.",
      "-- Another dialect? Put `-- dialect: snowflake` (or tsql, bigquery, spark, postgres) on the first line.",
      "",
      ""
    ].join("\n")
  },
  {
    kind: "python",
    label: "Python",
    description: "Local Python, run only with trusted local Python on",
    extension: ".py",
    folder: "notebooks",
    needsTrustedPython: true,
    defaultName: "analysis.py",
    header: title => [
      `# ${title}`,
      "# Real local Python. Mosaic > Run active Python runs it only after you enable trusted local Python",
      "# for this workspace yourself; the worker is not a security sandbox. query(sql) reads the local catalog.",
      "",
      ""
    ].join("\n")
  },
  {
    kind: "polars",
    label: "Polars",
    description: "Real Polars, run only with trusted local Python on",
    extension: ".py",
    folder: "notebooks",
    needsTrustedPython: true,
    defaultName: "transform.py",
    header: title => [
      `# ${title}`,
      "# Real Polars, run as local Python only after you enable trusted local Python for this workspace",
      "# yourself. End the file with a LazyFrame to see Polars' own optimized plan next to the result.",
      "import polars as pl",
      "",
      ""
    ].join("\n")
  },
  {
    kind: "markdown",
    label: "Markdown",
    description: "Notes: grain, assumptions, checks, decisions",
    extension: ".md",
    folder: "notes",
    needsTrustedPython: false,
    defaultName: "notes.md",
    header: title => `# ${title}\n\n`
  }
];

export function fileKindSpec(kind: BuildFileKind): BuildFileKindSpec {
  const spec = BUILD_FILE_KINDS.find(candidate => candidate.kind === kind);
  if (!spec) throw new Error(`Unknown file kind ${kind}.`);
  return spec;
}

const WINDOWS_RESERVED = /^(con|prn|aux|nul|com[0-9]|lpt[0-9])$/i;
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9 ._-]*$/;
export const MAX_FILE_NAME = 80;

/**
 * A single safe file name: no folder, no `..`, no leading dot, letters, digits, space, dot, dash and underscore only,
 * not a Windows device name. Returns the error, or undefined.
 */
export function fileNameError(name: string): string | undefined {
  const trimmed = name.trim();
  if (!trimmed) return "Enter a file name.";
  if (trimmed.length > MAX_FILE_NAME) return `Use at most ${MAX_FILE_NAME} characters.`;
  if (/[\\/]/.test(trimmed)) return "Enter a file name only, without a folder.";
  if (trimmed.includes("..")) return "A file name cannot contain '..'.";
  if (!SAFE_NAME.test(trimmed)) return "Use letters, digits, spaces, '.', '-' and '_', starting with a letter or digit.";
  if (trimmed.endsWith(".") || trimmed.endsWith(" ")) return "A file name cannot end with a dot or a space.";
  if (WINDOWS_RESERVED.test(trimmed.split(".")[0])) return `${trimmed.split(".")[0]} is a reserved name on Windows.`;
  return undefined;
}

/**
 * The file name for a kind: the kind's extension is added when the name has none, and another extension is refused
 * (a `.py` name is not a SQL file). Returns the name or the error.
 */
export function fileNameForKind(name: string, kind: BuildFileKind): { fileName: string } | { error: string } {
  const error = fileNameError(name);
  if (error) return { error };
  const trimmed = name.trim();
  const { extension } = fileKindSpec(kind);
  const dot = trimmed.lastIndexOf(".");
  const current = dot > 0 ? trimmed.slice(dot).toLowerCase() : "";
  if (current === extension) return { fileName: trimmed.slice(0, dot) + extension };
  if (current && /^\.[a-z0-9]{1,8}$/.test(current)) {
    return { error: `A ${fileKindSpec(kind).label} file ends with ${extension}, not ${current}.` };
  }
  return { fileName: `${trimmed}${extension}` };
}

/** A readable title for the file's first line, from its name. */
export function titleFromFileName(fileName: string): string {
  const stem = fileName.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim();
  return stem ? stem.charAt(0).toUpperCase() + stem.slice(1) : "Untitled";
}

/** Extensions Import dataset accepts (the same files Mosaic's bronze import reads). */
export const DATASET_EXTENSIONS = [".csv", ".parquet", ".json", ".jsonl", ".ndjson"] as const;

export function datasetExtension(fileName: string): string | undefined {
  const lower = fileName.toLowerCase();
  return DATASET_EXTENSIONS.find(extension => lower.endsWith(extension));
}

/** `orders.csv` -> `orders-2.csv`, `orders-3.csv`, ... : the first name not in `taken` (compared case-insensitively). */
export function nextFreeName(fileName: string, taken: Iterable<string>): string {
  const used = new Set([...taken].map(name => name.toLowerCase()));
  if (!used.has(fileName.toLowerCase())) return fileName;
  const dot = fileName.lastIndexOf(".");
  const stem = dot > 0 ? fileName.slice(0, dot) : fileName;
  const extension = dot > 0 ? fileName.slice(dot) : "";
  for (let index = 2; index < 10_000; index += 1) {
    const candidate = `${stem}-${index}${extension}`;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
  throw new Error(`No free name for ${fileName}.`);
}

/**
 * The name a dataset is copied under: the picked name when it is safe and free, else an error naming a free
 * alternative. Existing files are never replaced.
 */
export function datasetNameError(name: string, taken: Iterable<string>): string | undefined {
  const error = fileNameError(name);
  if (error) return error;
  if (!datasetExtension(name)) return `Keep a dataset extension: ${DATASET_EXTENSIONS.join(", ")}.`;
  const used = [...taken];
  if (used.some(existing => existing.toLowerCase() === name.trim().toLowerCase())) {
    return `datasets/${name.trim()} already exists; it is never replaced. Try ${nextFreeName(name.trim(), used)}.`;
  }
  return undefined;
}

/** True when a folder listing holds no file a learner wrote (folders and dotfiles are ignored). */
export function folderHasNoFiles(entries: readonly { name: string; isFile: boolean }[]): boolean {
  return !entries.some(entry => entry.isFile && !entry.name.startsWith("."));
}
