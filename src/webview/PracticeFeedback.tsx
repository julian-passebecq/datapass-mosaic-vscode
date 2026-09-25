import { Button } from "@fluentui/react-components";
import { useMemo } from "react";
import {
  SOLUTION_AFTER_FAILURES,
  diffRows,
  solutionUnlocked,
  type DiffRow,
  type Row,
  type RowValidation
} from "../platform/practiceFeedback";
import type { ExerciseProgressRecord } from "../platform/practiceProgress";
import type { ExerciseCheckView, ExerciseSummary } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

const MAX_DIFF_ROWS = 60;

/** Expected vs actual rows of a VISIBLE check, compared with the grader's rules. */
export function RowDiffView({ check, validation }: { check: ExerciseCheckView; validation: RowValidation }) {
  const diff = useMemo(
    () => diffRows((check.expected ?? []) as Row[], (check.actual ?? []) as Row[], validation),
    [check, validation]
  );
  const shown = diff.rows.filter(row => row.kind !== "match" || diff.rows.length <= MAX_DIFF_ROWS).slice(0, MAX_DIFF_ROWS);
  const summary = [
    diff.counts.match && `${diff.counts.match} matching`,
    diff.counts.differs && `${diff.counts.differs} with different values`,
    diff.counts.missing && `${diff.counts.missing} missing`,
    diff.counts.unexpected && `${diff.counts.unexpected} unexpected`
  ].filter(Boolean).join(" · ");

  return (
    <div className="row-diff" aria-label={`Expected and actual rows for ${check.id}`}>
      <div className="row-diff-summary">
        <strong>Expected vs your result</strong>
        <span className="muted">{summary || "no rows on either side"}</span>
      </div>
      {diff.missingColumns.length > 0 && (
        <div className="row-diff-note">Missing column{diff.missingColumns.length > 1 ? "s" : ""}: {diff.missingColumns.join(", ")}</div>
      )}
      {diff.extraColumns.length > 0 && (
        <div className="row-diff-note">
          Extra column{diff.extraColumns.length > 1 ? "s" : ""}: {diff.extraColumns.join(", ")}
          {diff.extraColumnsForbidden ? " (this exercise expects exactly the listed columns)" : " (ignored by the grader)"}
        </div>
      )}
      {diff.columnOrderDiffers && (
        <div className="row-diff-note">The columns are right but in a different order than the exercise asks for.</div>
      )}
      <div className="row-diff-scroll">
        <table>
          <thead>
            <tr>
              <th aria-label="Row status" />
              {diff.columns.map(column => (
                <th key={column} className={diff.missingColumns.includes(column) || (diff.extraColumnsForbidden && diff.extraColumns.includes(column)) ? "row-diff-col-bad" : undefined}>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => <DiffRowView key={index} row={row} columns={diff.columns} />)}
          </tbody>
        </table>
      </div>
      {diff.rows.length > shown.length && (
        <small className="muted">{diff.rows.length - shown.length} more rows not shown.</small>
      )}
      <small className="muted">{diff.notes.join(" ")} Hidden and edge-case fixtures are graded on Submit and never shown.</small>
    </div>
  );
}

function DiffRowView({ row, columns }: { row: DiffRow; columns: string[] }) {
  const label = { match: "=", differs: "≠", missing: "−", unexpected: "+" }[row.kind];
  const title = {
    match: "Matches an expected row",
    differs: "Expected (top) and your row (bottom) differ in the marked cells",
    missing: "Expected but missing from your result",
    unexpected: "In your result but not expected"
  }[row.kind];
  if (row.kind === "differs") {
    return (
      <>
        <tr className="row-diff-expected">
          <td title={title} rowSpan={2} className="row-diff-mark">{label}</td>
          {columns.map(column => (
            <td key={column} className={row.cells.includes(column) ? "row-diff-cell-expected" : undefined}>{format(row.expected?.[column])}</td>
          ))}
        </tr>
        <tr className="row-diff-actual">
          {columns.map(column => (
            <td key={column} className={row.cells.includes(column) ? "row-diff-cell-actual" : undefined}>{format(row.actual?.[column])}</td>
          ))}
        </tr>
      </>
    );
  }
  const values = row.kind === "unexpected" ? row.actual : row.expected;
  return (
    <tr className={`row-diff-${row.kind}`}>
      <td title={title} className="row-diff-mark">{label}</td>
      {columns.map(column => <td key={column}>{values && column in values ? format(values[column]) : ""}</td>)}
    </tr>
  );
}

function format(value: unknown): string {
  if (value === null) return "NULL";
  if (value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Hints revealed one at a time; the count is kept in .datapass/progress.json. */
export function HintsBlock({ exercise, record, vscode }: {
  exercise: ExerciseSummary;
  record?: ExerciseProgressRecord;
  vscode: VsCodeApi;
}) {
  if (!exercise.hints.length) return null;
  const revealed = Math.min(record?.hintsRevealed ?? 0, exercise.hints.length);
  return (
    <div className="practice-hints">
      {revealed > 0 && (
        <ol>
          {exercise.hints.slice(0, revealed).map((hint, index) => <li key={index}>{hint}</li>)}
        </ol>
      )}
      {revealed < exercise.hints.length && (
        <Button appearance="subtle" size="small"
          onClick={() => vscode.postMessage({ type: "revealHint", exerciseKey: exercise.key })}>
          {revealed === 0 ? "Show a hint" : "Show the next hint"} ({revealed + 1} of {exercise.hints.length})
        </Button>
      )}
    </div>
  );
}

/** The reference solution and its explanation: after a pass, or on request after a few failed gradings. */
export function SolutionBlock({ exercise, record, code, vscode }: {
  exercise: ExerciseSummary;
  record?: ExerciseProgressRecord;
  code?: string;
  vscode: VsCodeApi;
}) {
  if (!exercise.solutionAvailable) return null;
  if (code !== undefined) {
    return (
      <div className="practice-solution">
        <div className="status-row">
          <strong>Reference solution</strong>
          <Button appearance="secondary" size="small"
            onClick={() => vscode.postMessage({ type: "compareSolution", exerciseKey: exercise.key })}>
            Compare with my solution
          </Button>
        </div>
        <pre><code>{code}</code></pre>
        {exercise.explanation && <p className="practice-explanation">{exercise.explanation}</p>}
      </div>
    );
  }
  const unlocked = solutionUnlocked(record);
  const failures = record?.failures ?? 0;
  return (
    <div className="practice-solution-locked">
      <Button appearance="subtle" size="small" disabled={!unlocked}
        onClick={() => vscode.postMessage({ type: "showSolution", exerciseKey: exercise.key })}>
        {record?.solved ? "Show the reference solution and explanation" : "Show the reference solution"}
      </Button>
      {!unlocked && (
        <small className="muted">
          Opens once you solve it, or after {SOLUTION_AFTER_FAILURES} gradings that do not pass ({failures} so far).
        </small>
      )}
    </div>
  );
}
