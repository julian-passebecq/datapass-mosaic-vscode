import { Badge, Button, Card, Text } from "@fluentui/react-components";
import { practiceStatus, type PracticeProgress } from "../platform/practiceProgress";
import { languageLabel, problemSummary, type PracticeProblem } from "../platform/practiceProblems";
import { localDay, reviewLabel } from "../platform/practiceReview";
import type { ExerciseSummary, RuntimeViewState } from "./contracts";
import { HintsBlock, RowDiffView, SolutionBlock } from "./PracticeFeedback";
import type { VsCodeApi } from "./WorkbenchApp";

const PYTHON_LANGUAGES = new Set(["python", "polars"]);

/** Translated SQL dialects: the query runs on local DuckDB, never on the named engine. */
const DIALECT_NOTICES: Record<string, string> = {
  snowflake: "Snowflake SQL dialect translated to DuckDB, not Snowflake",
  tsql: "T-SQL dialect translated to DuckDB, not SQL Server",
  bigquery: "BigQuery SQL dialect translated to DuckDB, not BigQuery"
};

/** One problem: the prompt once, a language switch, and the selected variant's grading. */
export function PracticeProblemCard({
  vscode,
  problem,
  variant,
  progress,
  runtime,
  solution,
  onLanguage,
  badge,
  interview = false
}: {
  vscode: VsCodeApi;
  problem: PracticeProblem;
  variant: ExerciseSummary;
  progress: PracticeProgress;
  runtime: RuntimeViewState;
  /** The reference solution the learner revealed for this variant. */
  solution?: string;
  onLanguage: (language: string) => void;
  /** A mode's label on the card, for example "Review due". */
  badge?: string;
  /** Interview mode: no hints, no reference solution, no topics (they name the pattern), and the language is fixed. */
  interview?: boolean;
}) {
  const runtimeReady = runtime.status === "running";
  const result = runtime.practiceResult?.exerciseKey === variant.key ? runtime.practiceResult : undefined;
  const record = progress.exercises[variant.key];
  const status = practiceStatus(record);
  const summary = problemSummary(problem, progress);
  const multi = problem.variants.length > 1;
  const statusLine = multi && status !== "not-started"
    ? `${languageLabel(variant.language)}: ${status === "solved" ? "solved" : record?.attempts
      ? `${record.attempts} ${record.attempts === 1 ? "run" : "runs"}, not solved yet` : "opened"}`
    : undefined;
  const review = reviewLabel(record, localDay(new Date()));

  return (
    <Card className="practice-item" data-problem={problem.key}>
      <div className="practice-meta">
        {badge && <Badge appearance="filled" color="brand">{badge}</Badge>}
        <Badge appearance="tint">{problem.difficulty}</Badge>
        <span className="muted">{problem.packTitle} · v{variant.version}</span>
        {!interview && summary.status !== "not-started" && (
          <Badge appearance={summary.status === "solved" ? "filled" : "outline"}
            color={summary.status === "solved" ? "success" : "warning"}>
            {summary.status === "solved"
              ? multi ? `solved in ${summary.solved.length} of ${problem.variants.length}` : "solved"
              : "attempted"}
          </Badge>
        )}
      </div>
      <Text size={400} weight="semibold">{problem.title}</Text>
      <p className="practice-prompt">{problem.prompt}</p>

      <div className="practice-languages" role="radiogroup" aria-label={`Language for ${problem.title}`}>
        {(interview ? [variant] : problem.variants).map(item => {
          const itemStatus = practiceStatus(progress.exercises[item.key]);
          const selected = item.key === variant.key;
          return (
            <button
              key={item.key}
              type="button"
              role="radio"
              aria-checked={selected}
              className={`practice-language${selected ? " selected" : ""} ${itemStatus}`}
              title={`${languageLabel(item.language)}: ${itemStatus === "not-started" ? "not started" : itemStatus}`}
              disabled={interview}
              onClick={() => onLanguage(item.language)}
            >
              {languageLabel(item.language)}
              {itemStatus === "solved" ? <span aria-hidden> ✓</span> : itemStatus === "attempted" ? <span aria-hidden> •</span> : null}
            </button>
          );
        })}
        {!interview && (statusLine || review) && (
          <small className="muted">{[statusLine, review].filter(Boolean).join(" · ")}</small>
        )}
      </div>

      {variant.sparkPlan && (
        <div className="practice-plan">
          <span className="eyebrow">Also graded on the simulated Spark plan</span>
          <ul>
            {variant.sparkPlan.checks.map(check => <li key={check.id}>{check.description}</li>)}
          </ul>
        </div>
      )}
      {variant.gradingNote && <div className="pipeline-notice">{variant.gradingNote}</div>}
      {PYTHON_LANGUAGES.has(variant.language.toLowerCase()) && runtimeReady && !runtime.trustedPython && (
        <div className="pipeline-notice">
          This exercise executes real local Python. Grading reports an error until trusted local Python is
          enabled for this workspace (Mosaic → Python / Polars).
        </div>
      )}
      {DIALECT_NOTICES[variant.language] && (
        <div className="pipeline-notice">
          {DIALECT_NOTICES[variant.language]}: your query runs on local DuckDB, and functions outside the supported
          subset are refused rather than approximated.
        </div>
      )}

      {result && (
        <div className="practice-result">
          <div className="practice-result-header">
            <div>
              <strong>{result.mode === "submit" ? "Submission" : "Visible checks"}</strong>
              <small>{result.truth} · {result.elapsed_ms.toFixed(1)} ms</small>
            </div>
            <Badge appearance="tint"
              color={result.status === "passed" ? "success" : result.status === "failed" ? "danger" : "warning"}>
              {result.status}
            </Badge>
          </div>
          {result.error && <div className="error-text">{result.error.message}</div>}
          <div className="practice-checks">
            {result.checks.map(check => (
              <div className="practice-check-block" key={check.id}>
                <div className="practice-check">
                  <div>
                    <strong>{check.id}</strong>
                    <small>{check.kind === "plan" ? "simulated plan" : check.visibility} · {check.message}</small>
                  </div>
                  <Badge appearance="outline" color={check.passed ? "success" : "danger"}>{check.status}</Badge>
                </div>
                {/* Rows only exist for visible fixtures: the runtime never sends hidden ones. */}
                {!check.passed && check.visibility === "visible" && check.kind !== "plan" &&
                  Array.isArray(check.expected) && Array.isArray(check.actual) && (
                  <RowDiffView check={check} validation={variant.validation} />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {!interview && <HintsBlock exercise={variant} record={record} vscode={vscode} />}
      {!interview && <SolutionBlock exercise={variant} record={record} code={solution} vscode={vscode} />}

      <div className="practice-footer">
        <div className="practice-topics">
          {!interview && problem.topics.slice(0, 4).map(topic => <span key={topic}>{topic}</span>)}
        </div>
        <div className="button-row">
          <Button appearance="secondary" size="small"
            onClick={() => vscode.postMessage({ type: "openExercise", exerciseKey: variant.key })}>
            Open solution
          </Button>
          <Button appearance="secondary" size="small" disabled={!runtimeReady || Boolean(variant.gradingNote)}
            onClick={() => vscode.postMessage({ type: "gradeExercise", exerciseKey: variant.key, mode: "run" })}>
            Run visible
          </Button>
          <Button appearance="primary" size="small" disabled={!runtimeReady || Boolean(variant.gradingNote)}
            onClick={() => vscode.postMessage({ type: "gradeExercise", exerciseKey: variant.key, mode: "submit" })}>
            Submit
          </Button>
        </div>
      </div>
    </Card>
  );
}
