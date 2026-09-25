/**
 * Practice feedback on VISIBLE fixtures only: expected vs actual rows with the differences marked, compared with
 * the grader's own rules (runtime/datapass_runtime/exercise_validation.py): ordered or not, duplicates, numeric
 * tolerance, extra columns. Hidden and edge fixtures never reach the extension with their rows.
 * Pure functions, shared by the host and the webview; tested by scripts/practice_feedback_smoke.mjs.
 */

/** The parts of an exercise's `validation` contract the diff follows. */
export interface RowValidation {
  ordered?: boolean;
  duplicateSensitive?: boolean;
  relativeTolerance?: number;
  absoluteTolerance?: number;
  forbiddenExtraColumns?: boolean;
  exactSchema?: string[];
  /** Set when the grader compares aggregates of columns instead of rows. */
  aggregates?: Record<string, string>;
}

export type Row = Readonly<Record<string, unknown>>;
export type DiffRowKind = "match" | "differs" | "missing" | "unexpected";
export interface DiffRow {
  kind: DiffRowKind;
  expected?: Row;
  actual?: Row;
  /** Columns whose values differ (ordered comparison only). */
  cells: string[];
}
export interface RowDiff {
  columns: string[];
  /** In the expected rows, absent from the result. */
  missingColumns: string[];
  /** In the result only; a failure when the contract forbids extra columns. */
  extraColumns: string[];
  extraColumnsForbidden: boolean;
  /** exact_schema: the result's column order differs from the contract's. */
  columnOrderDiffers: boolean;
  ordered: boolean;
  rows: DiffRow[];
  counts: Record<DiffRowKind, number>;
  /** Plain-language notes on how the rows were compared. */
  notes: string[];
}

export function rowValidation(raw: unknown): RowValidation {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const number = (v: unknown) => typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : undefined;
  const strings = (v: unknown) => Array.isArray(v) && v.every(item => typeof item === "string") ? v as string[] : undefined;
  const aggregates = value.aggregates && typeof value.aggregates === "object" && !Array.isArray(value.aggregates)
    ? Object.fromEntries(Object.entries(value.aggregates as Record<string, unknown>).filter(([, op]) => typeof op === "string")) as Record<string, string>
    : undefined;
  return {
    ordered: value.ordered === true,
    duplicateSensitive: value.duplicate_sensitive !== false,
    relativeTolerance: number(value.relative_tolerance),
    absoluteTolerance: number(value.absolute_tolerance),
    forbiddenExtraColumns: value.forbidden_extra_columns === true,
    exactSchema: strings(value.exact_schema),
    aggregates: aggregates && Object.keys(aggregates).length ? aggregates : undefined
  };
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Python's math.isclose with the contract's tolerances; other values compare by type and value. */
export function valuesEqual(a: unknown, b: unknown, validation: RowValidation = {}): boolean {
  if (isNumber(a) && isNumber(b)) {
    const rel = validation.relativeTolerance ?? 1e-9;
    const abs = validation.absoluteTolerance ?? 0;
    return a === b || Math.abs(a - b) <= Math.max(rel * Math.max(Math.abs(a), Math.abs(b)), abs);
  }
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return a === b;
  return JSON.stringify(a) === JSON.stringify(b);
}

function rowEqual(actual: Row, expected: Row, validation: RowValidation): boolean {
  const expectedKeys = Object.keys(expected);
  const keysOk = validation.forbiddenExtraColumns
    ? expectedKeys.length === Object.keys(actual).length && expectedKeys.every(key => key in actual)
    : expectedKeys.every(key => key in actual);
  return keysOk && expectedKeys.every(key => valuesEqual(actual[key], expected[key], validation));
}

function unique(rows: readonly Row[], validation: RowValidation): Row[] {
  const out: Row[] = [];
  for (const row of rows) if (!out.some(other => rowEqual(row, other, validation))) out.push(row);
  return out;
}

export function diffRows(expectedRows: readonly Row[], actualRows: readonly Row[], validation: RowValidation = {}): RowDiff {
  const expectedColumns = [...new Set(expectedRows.flatMap(row => Object.keys(row)))];
  const actualColumns = [...new Set(actualRows.flatMap(row => Object.keys(row)))];
  const missingColumns = expectedColumns.filter(column => !actualColumns.includes(column));
  const extraColumns = actualColumns.filter(column => !expectedColumns.includes(column));
  const columns = [...expectedColumns, ...extraColumns];
  const notes: string[] = [];
  const ordered = validation.ordered === true;
  notes.push(ordered ? "Row order matters for this exercise." : "Row order does not matter for this exercise.");
  if (validation.duplicateSensitive === false) notes.push("Duplicate rows count once.");
  if (validation.aggregates) {
    notes.push(`Graded on column aggregates (${Object.entries(validation.aggregates).map(([c, op]) => `${op}(${c})`).join(", ")}), not row by row.`);
  }
  let expected = [...expectedRows];
  let actual = [...actualRows];
  if (validation.duplicateSensitive === false) {
    expected = unique(expected, validation);
    actual = unique(actual, validation);
  }

  const rows: DiffRow[] = [];
  if (ordered) {
    for (let i = 0; i < Math.max(expected.length, actual.length); i += 1) {
      const e = expected[i];
      const a = actual[i];
      if (e && a) {
        const cells = columns.filter(column => (column in e || column in a) && !valuesEqual(a[column], e[column], validation) &&
          (column in e || validation.forbiddenExtraColumns === true));
        rows.push({ kind: rowEqual(a, e, validation) ? "match" : "differs", expected: e, actual: a, cells });
      } else if (e) {
        rows.push({ kind: "missing", expected: e, cells: [] });
      } else if (a) {
        rows.push({ kind: "unexpected", actual: a, cells: [] });
      }
    }
  } else {
    // The grader's bipartite matching, so a tolerance match never hides a valid pairing.
    const owner = new Map<number, number>();
    const tryMatch = (i: number, seen: Set<number>): boolean => {
      for (let j = 0; j < expected.length; j += 1) {
        if (seen.has(j) || !rowEqual(actual[i], expected[j], validation)) continue;
        seen.add(j);
        if (!owner.has(j) || tryMatch(owner.get(j)!, seen)) {
          owner.set(j, i);
          return true;
        }
      }
      return false;
    };
    actual.forEach((_, i) => tryMatch(i, new Set()));
    const matchedActual = new Set(owner.values());
    expected.forEach((row, j) => rows.push(owner.has(j)
      ? { kind: "match", expected: row, actual: actual[owner.get(j)!], cells: [] }
      : { kind: "missing", expected: row, cells: [] }));
    actual.forEach((row, i) => {
      if (!matchedActual.has(i)) rows.push({ kind: "unexpected", actual: row, cells: [] });
    });
  }
  const counts: Record<DiffRowKind, number> = { match: 0, differs: 0, missing: 0, unexpected: 0 };
  for (const row of rows) counts[row.kind] += 1;
  const columnOrderDiffers = Boolean(validation.exactSchema && actualColumns.length &&
    validation.exactSchema.join("\u0000") !== actualColumns.join("\u0000") && !missingColumns.length && !extraColumns.length);
  return {
    columns,
    missingColumns,
    extraColumns,
    extraColumnsForbidden: validation.forbiddenExtraColumns === true,
    columnOrderDiffers,
    ordered,
    rows,
    counts,
    notes
  };
}

/** Failed gradings (Run visible or Submit) after which the reference solution can be shown without a pass. */
export const SOLUTION_AFTER_FAILURES = 3;

export function solutionUnlocked(record: { solved?: unknown; failures?: number } | undefined): boolean {
  return Boolean(record?.solved) || (record?.failures ?? 0) >= SOLUTION_AFTER_FAILURES;
}

/** The reference solution in a pack's grading.server.json: `solution`, or `solutions[language]` for scenario variants. */
export function referenceSolution(grading: unknown, exerciseId: string, language: string): string | undefined {
  const table = grading && typeof grading === "object" ? grading as Record<string, unknown> : {};
  const direct = table[exerciseId];
  if (direct && typeof direct === "object" && typeof (direct as Record<string, unknown>).solution === "string") {
    return (direct as Record<string, string>).solution;
  }
  // Scenario packs register each variant as <scenario>-<language>.
  const suffix = `-${language}`;
  const scenario = exerciseId.endsWith(suffix) ? table[exerciseId.slice(0, -suffix.length)] : undefined;
  const solutions = scenario && typeof scenario === "object" ? (scenario as Record<string, unknown>).solutions : undefined;
  const code = solutions && typeof solutions === "object" ? (solutions as Record<string, unknown>)[language] : undefined;
  return typeof code === "string" ? code : undefined;
}
