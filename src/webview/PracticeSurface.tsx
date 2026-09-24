import { Badge, Button, Card, Input, Text } from "@fluentui/react-components";
import { useMemo, useState } from "react";
import type { ExerciseSummary, RuntimeViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

export function PracticeSurface({
  vscode,
  exercises,
  runtime
}: {
  vscode: VsCodeApi;
  exercises: readonly ExerciseSummary[];
  runtime: RuntimeViewState;
}) {
  const [query, setQuery] = useState("");
  const runtimeReady = runtime.status === "running";

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return exercises;
    return exercises.filter(exercise =>
      [
        exercise.title,
        exercise.packTitle,
        exercise.language,
        exercise.difficulty,
        exercise.prompt,
        ...exercise.topics
      ].some(value => value.toLowerCase().includes(needle))
    );
  }, [exercises, query]);

  return (
    <section className="practice-surface">
      <div className="practice-toolbar">
        <div>
          <div className="eyebrow">Native-file practice · versioned grading</div>
          <Text size={500} weight="semibold">{exercises.length} exercise variants</Text>
        </div>
        <div className="practice-toolbar-actions">
          <Badge appearance="tint" color={runtimeReady ? "success" : "informative"}>
            {runtimeReady ? "grader ready" : "runtime stopped"}
          </Badge>
          <Input
            aria-label="Filter exercises"
            placeholder="Filter SQL, Spark, dbt…"
            value={query}
            onChange={(_, data) => setQuery(data.value)}
          />
        </div>
      </div>

      <div className="practice-list">
        {filtered.map(exercise => {
          const result = runtime.practiceResult?.exerciseKey === exercise.key
            ? runtime.practiceResult
            : undefined;

          return (
            <Card key={exercise.key} className="practice-item">
              <div className="practice-meta">
                <Badge appearance="outline">{exercise.language}</Badge>
                <Badge appearance="tint">{exercise.difficulty}</Badge>
                <span className="muted">{exercise.packTitle} · v{exercise.version}</span>
              </div>
              <Text size={400} weight="semibold">{exercise.title}</Text>
              <p className="practice-prompt">{exercise.prompt}</p>

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
                      <div className="practice-check" key={check.id}>
                        <div>
                          <strong>{check.id}</strong>
                          <small>{check.visibility} · {check.message}</small>
                        </div>
                        <Badge
                          appearance="outline"
                          color={check.passed ? "success" : "danger"}
                        >
                          {check.status}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

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
                    disabled={!runtimeReady}
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
                    disabled={!runtimeReady}
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
