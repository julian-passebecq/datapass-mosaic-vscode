import { Badge, Button, Card, Input, Select, Text } from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import {
  EMPTY_FILTERS,
  STATUS_LABELS,
  filterExercises,
  filterOptions,
  practiceCounts,
  practiceStatus,
  restoreFilters,
  type PracticeFilters,
  type PracticeStatus
} from "../platform/practiceProgress";
import type { PracticeViewState, RuntimeViewState, WorkbenchFocus } from "./contracts";
import { HintsBlock, RowDiffView, SolutionBlock } from "./PracticeFeedback";
import type { VsCodeApi } from "./WorkbenchApp";

const PYTHON_LANGUAGES = new Set(["python", "polars"]);

export function PracticeSurface({
  vscode,
  practice,
  runtime,
  focus
}: {
  vscode: VsCodeApi;
  practice: PracticeViewState;
  runtime: RuntimeViewState;
  /** An exercise a project step opened: the list is filtered on it. */
  focus?: WorkbenchFocus;
}) {
  const { exercises, progress } = practice;
  const [filters, setFilters] = useState<PracticeFilters>(() => {
    const saved = restoreFilters(readState(vscode).practiceFilters);
    return focus?.query ? { ...EMPTY_FILTERS, query: focus.query } : saved;
  });
  const update = (next: PracticeFilters) => {
    setFilters(next);
    vscode.setState({ ...readState(vscode), practiceFilters: next });
  };
  useEffect(() => {
    // A project step asks for one exercise: show it whatever the other filters were.
    if (focus?.query) update({ ...EMPTY_FILTERS, query: focus.query });
  }, [focus?.seq]);
  const runtimeReady = runtime.status === "running";

  const options = useMemo(() => filterOptions(exercises), [exercises]);
  const filtered = useMemo(() => filterExercises(exercises, progress, filters), [exercises, progress, filters]);
  const counts = useMemo(() => practiceCounts(exercises, progress), [exercises, progress]);
  const filtering = Object.values(filters).some(Boolean);

  return (
    <section className="practice-surface">
      <div className="practice-toolbar">
        <div>
          <div className="eyebrow">Native-file practice · versioned grading</div>
          <Text size={500} weight="semibold">{exercises.length} exercise variants</Text>
          <div className="practice-progress" aria-label="Your progress">
            <span className="practice-progress-solved">{counts.solved} solved</span>
            <span>{counts.attempted} attempted</span>
            <span>{counts["not-started"]} not started</span>
            <small className="muted">
              {practice.canSaveProgress ? "Saved in .datapass/progress.json" : "Open a folder to keep your progress"}
            </small>
          </div>
        </div>
        <div className="practice-toolbar-actions">
          <Badge appearance="tint" color={runtimeReady ? "success" : "informative"}>
            {runtimeReady ? "grader ready" : "runtime stopped"}
          </Badge>
          <Input
            aria-label="Filter exercises"
            placeholder="Filter SQL, Spark, Airflow, dbt…"
            value={filters.query}
            onChange={(_, data) => update({ ...filters, query: data.value })}
          />
        </div>
      </div>

      <div className="practice-filters" role="group" aria-label="Exercise filters">
        <FilterSelect label="Difficulty" all="All difficulties" value={filters.difficulty} values={options.difficulties}
          onChange={difficulty => update({ ...filters, difficulty })} />
        <FilterSelect label="Topic" all="All topics" value={filters.topic} values={options.topics}
          onChange={topic => update({ ...filters, topic })} />
        <FilterSelect label="Language" all="All languages" value={filters.language} values={options.languages}
          onChange={language => update({ ...filters, language })} />
        <FilterSelect label="Status" all="All statuses" value={filters.status}
          values={Object.keys(STATUS_LABELS)} labels={STATUS_LABELS}
          onChange={status => update({ ...filters, status: status as PracticeStatus | "" })} />
        <Button appearance="subtle" size="small" disabled={!filtering} onClick={() => update(EMPTY_FILTERS)}>
          Clear filters
        </Button>
        <span className="muted">{filtered.length} shown</span>
      </div>
      {practice.progressError && (
        <div className="pipeline-notice">
          {practice.progressError} Progress is shown as empty and is not saved until the file is fixed or deleted.
        </div>
      )}

      <div className="practice-list">
        {filtered.map(exercise => {
          const result = runtime.practiceResult?.exerciseKey === exercise.key
            ? runtime.practiceResult
            : undefined;
          const record = progress.exercises[exercise.key];
          const status = practiceStatus(record);

          return (
            <Card key={exercise.key} className="practice-item">
              <div className="practice-meta">
                <Badge appearance="outline">{exercise.language}</Badge>
                <Badge appearance="tint">{exercise.difficulty}</Badge>
                <span className="muted">{exercise.packTitle} · v{exercise.version}</span>
                {status !== "not-started" && (
                  <Badge
                    appearance={status === "solved" ? "filled" : "outline"}
                    color={status === "solved" ? "success" : "warning"}
                    title={record?.last ? `Last ${record.last.mode === "submit" ? "submission" : "visible run"}: ${record.last.status}, ${record.last.at}` : undefined}
                  >
                    {status === "solved" ? "solved" : record?.attempts ? `attempted · ${record.attempts} ${record.attempts === 1 ? "run" : "runs"}` : "opened"}
                  </Badge>
                )}
              </div>
              <Text size={400} weight="semibold">{exercise.title}</Text>
              <p className="practice-prompt">{exercise.prompt}</p>
              {exercise.sparkPlan && (
                <div className="practice-plan">
                  <span className="eyebrow">Also graded on the simulated Spark plan</span>
                  <ul>
                    {exercise.sparkPlan.checks.map(check => <li key={check.id}>{check.description}</li>)}
                  </ul>
                </div>
              )}
              {exercise.gradingNote && (
                <div className="pipeline-notice">{exercise.gradingNote}</div>
              )}
              {PYTHON_LANGUAGES.has(exercise.language.toLowerCase()) && runtimeReady && !runtime.trustedPython && (
                <div className="pipeline-notice">
                  This exercise executes real local Python. Grading reports an error until trusted local Python is
                  enabled for this workspace (Mosaic → Python / Polars).
                </div>
              )}

              {exercise.language === "snowflake" && (
                <div className="pipeline-notice">
                  Snowflake SQL dialect translated to DuckDB, not Snowflake: your query runs on local DuckDB, and
                  functions outside the supported subset are refused rather than approximated.
                </div>
              )}

              {exercise.language === "tsql" && (
                <div className="pipeline-notice">
                  T-SQL dialect translated to DuckDB, not SQL Server: your query runs on local DuckDB, and
                  functions outside the supported subset are refused rather than approximated.
                </div>
              )}

              {exercise.language === "bigquery" && (
                <div className="pipeline-notice">
                  BigQuery SQL dialect translated to DuckDB, not BigQuery: your query runs on local DuckDB, and
                  functions outside the supported subset are refused rather than approximated.
                </div>
              )}

              {result && (
                <div className="practice-result">
                  <div className="practice-result-header">
                    <div>
                      <strong>{result.mode === "submit" ? "Submission" : "Visible checks"}</strong>
                      <small>{result.truth} · {result.elapsed_ms.toFixed(1)} ms</small>
                    </div>
                    <Badge
                      appearance="tint"
                      color={result.status === "passed" ? "success" : result.status === "failed" ? "danger" : "warning"}
                    >
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
                            <small>
                              {check.kind === "plan" ? "simulated plan" : check.visibility} · {check.message}
                            </small>
                          </div>
                          <Badge
                            appearance="outline"
                            color={check.passed ? "success" : "danger"}
                          >
                            {check.status}
                          </Badge>
                        </div>
                        {/* Rows only exist for visible fixtures: the runtime never sends hidden ones. */}
                        {!check.passed && check.visibility === "visible" && check.kind !== "plan" &&
                          Array.isArray(check.expected) && Array.isArray(check.actual) && (
                          <RowDiffView check={check} validation={exercise.validation} />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <HintsBlock exercise={exercise} record={record} vscode={vscode} />
              <SolutionBlock exercise={exercise} record={record} code={practice.solutions[exercise.key]} vscode={vscode} />

              <div className="practice-footer">
                <div className="practice-topics">
                  {exercise.topics.slice(0, 4).map(topic => <span key={topic}>{topic}</span>)}
                </div>
                <div className="button-row">
                  <Button
                    appearance="secondary"
                    size="small"
                    onClick={() => vscode.postMessage({ type: "openExercise", exerciseKey: exercise.key })}
                  >
                    Open solution
                  </Button>
                  <Button
                    appearance="secondary"
                    size="small"
                    disabled={!runtimeReady || Boolean(exercise.gradingNote)}
                    onClick={() => vscode.postMessage({
                      type: "gradeExercise",
                      exerciseKey: exercise.key,
                      mode: "run"
                    })}
                  >
                    Run visible
                  </Button>
                  <Button
                    appearance="primary"
                    size="small"
                    disabled={!runtimeReady || Boolean(exercise.gradingNote)}
                    onClick={() => vscode.postMessage({
                      type: "gradeExercise",
                      exerciseKey: exercise.key,
                      mode: "submit"
                    })}
                  >
                    Submit
                  </Button>
                </div>
              </div>
            </Card>
          );
        })}
        {filtered.length === 0 && (
          <div className="empty-state">No exercises match this filter.</div>
        )}
      </div>
    </section>
  );
}

function FilterSelect({
  label,
  all,
  value,
  values,
  labels,
  onChange
}: {
  label: string;
  all: string;
  value: string;
  values: readonly string[];
  labels?: Record<string, string>;
  onChange: (value: string) => void;
}) {
  return (
    <Select aria-label={label} size="small" value={value} onChange={(_, data) => onChange(data.value)}>
      <option value="">{all}</option>
      {values.map(item => <option key={item} value={item}>{labels?.[item] ?? item}</option>)}
    </Select>
  );
}

function readState(vscode: VsCodeApi): { practiceFilters?: unknown } & Record<string, unknown> {
  const value = vscode.getState();
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}
