/**
 * What an exercise folder needs besides its solution file, so VS Code shows it well:
 * readable tab labels (every solution file is called solution.*) and no false Pylance warnings
 * for the packages Datapass simulates (pyspark, airflow) or the names its runtime injects (spark, display...).
 * Pure functions; src/exerciseWorkspace.ts writes the result.
 */

/** Workspace folder the extension copies content/pylance-stubs to; added to python.analysis.extraPaths. */
export const PYLANCE_STUBS_FOLDER = ".datapass/pylance-stubs";

/** Languages whose solution is a .py file analysed by Pylance. */
const PYTHON_FILE_LANGUAGES = new Set([
  "python",
  "pandas",
  "polars",
  "sparklab",
  "pyspark",
  "airflow",
  "factory-notebook",
  "databricks-notebook"
]);

/** Languages graded by the trusted Python kernel, which injects query/display/publish and the fixture tables. */
const PYTHON_KERNEL_LANGUAGES = new Set(["python", "pandas", "polars"]);

/** Pipeline Lab design exercises: the calls the pipeline compiler accepts (runtime/datapass_runtime/pipeline_compiler.py). */
const PIPELINE_DESIGN_RUNTIME = "datapass-dag-design-v1";
const PIPELINE_CALLS = ["pipeline", "DAG", "sql", "quality", "python", "polars", "dbt"];

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PYTHON_KEYWORDS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
  "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
  "not", "or", "pass", "raise", "return", "try", "while", "with", "yield"
]);

export function isPythonExerciseLanguage(language: string): boolean {
  return PYTHON_FILE_LANGUAGES.has(language);
}

/**
 * workbench.editor.customLabels.patterns entries for exercise folders (<root>/<exercise>/<language>/...).
 * ${dirname} is the language folder and ${dirname(1)} the exercise folder above it.
 */
export function exerciseLabelPatterns(exerciseRoot: string[]): Record<string, string> {
  const root = exerciseRoot.join("/");
  return {
    [`**/${root}/*/*/solution.*`]: "${dirname(1)} · ${dirname}",
    [`**/${root}/*/*/README.md`]: "${dirname(1)} · brief"
  };
}

/** files.exclude entries: the generated __builtins__.pyi stays on disk for Pylance but out of the Explorer. */
export function exerciseFileExcludes(exerciseRoot: string[]): Record<string, boolean> {
  return { [`**/${exerciseRoot.join("/")}/*/*/__builtins__.pyi`]: true };
}

/** The entries merged into the current workspace value, or undefined when nothing changes. */
export function mergeMissing<T>(
  current: Record<string, T> | undefined,
  wanted: Record<string, T>
): Record<string, T> | undefined {
  const base = current ?? {};
  // An entry the learner already set keeps their value.
  const missing = Object.entries(wanted).filter(([key]) => !(key in base));
  return missing.length ? { ...base, ...Object.fromEntries(missing) } : undefined;
}

/** python.analysis.extraPaths with the stubs folder added, or undefined when it is already there. */
export function mergeExtraPaths(current: readonly string[] | undefined, folder = PYLANCE_STUBS_FOLDER): string[] | undefined {
  const paths = [...(current ?? [])];
  const normalized = (value: string) => value.replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/+$/, "");
  return paths.some(path => normalized(path) === folder) ? undefined : [...paths, folder];
}

/**
 * The __builtins__.pyi written next to a Python solution: the names the Datapass runtime provides when it runs
 * this exercise. Pylance reads a __builtins__.pyi from the file's own folder, so the names are known only there.
 * Returns undefined when the language needs none.
 */
export function exerciseBuiltinsStub(
  language: string,
  tableNames: readonly string[],
  runtime?: string
): string | undefined {
  const lines: string[] = [];
  if (runtime === PIPELINE_DESIGN_RUNTIME) {
    // Pipeline Lab source: compiled by the bounded AST compiler, never run as Python.
    lines.push(...PIPELINE_CALLS.map(name => `def ${name}(*args: Any, **kwargs: Any) -> Any: ...`));
  } else if (PYTHON_KERNEL_LANGUAGES.has(language)) {
    const tables = tableNames.filter(name => IDENTIFIER.test(name) && !PYTHON_KEYWORDS.has(name));
    lines.push(
      "Rows = list[dict[str, Any]]",
      "",
      "def query(sql: str) -> Rows: ...",
      "def display(value: Any, columns: list[str] | None = None) -> None: ...",
      "def publish(name: str, value: Any) -> Any: ...",
      "input_rows: Rows",
      "tables: dict[str, Rows]",
      ...tables.map(name => `${name}: Rows`)
    );
  } else if (language === "sparklab" || language === "pyspark") {
    lines.push("spark: Any");
  } else if (language === "databricks-notebook") {
    lines.push("spark: Any", "dbutils: Any", "def display(value: Any) -> None: ...");
  } else if (language === "factory-notebook") {
    lines.push("spark: Any", "notebookutils: Any", "mssparkutils: Any", "def display(value: Any) -> None: ...");
  } else {
    return undefined;
  }
  return [
    "# Names the Datapass runtime provides when it runs this exercise. Pylance reads this file so it does",
    "# not report them as undefined. Nothing here runs, and Datapass does not grade it. Rewritten when the",
    "# exercise is opened.",
    "from typing import Any",
    "",
    ...lines,
    ""
  ].join("\n");
}
