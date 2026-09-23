import { Badge, Button, Card, Input, Text } from "@fluentui/react-components";
import { useMemo, useState } from "react";
import type { ExerciseSummary } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

export function PracticeSurface({
  vscode,
  exercises
}: {
  vscode: VsCodeApi;
  exercises: readonly ExerciseSummary[];
}) {
  const [query, setQuery] = useState("");

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
          <div className="eyebrow">Native-file practice</div>
          <Text size={500} weight="semibold">{exercises.length} harvested exercise variants</Text>
        </div>
        <Input
          aria-label="Filter exercises"
          placeholder="Filter SQL, Spark, dbt…"
          value={query}
          onChange={(_, data) => setQuery(data.value)}
        />
      </div>

      <div className="practice-list">
        {filtered.map(exercise => (
          <Card key={exercise.key} className="practice-item">
            <div className="practice-meta">
              <Badge appearance="outline">{exercise.language}</Badge>
              <Badge appearance="tint">{exercise.difficulty}</Badge>
              <span className="muted">{exercise.packTitle}</span>
            </div>
            <Text size={400} weight="semibold">{exercise.title}</Text>
            <p className="practice-prompt">{exercise.prompt}</p>
            <div className="practice-footer">
              <div className="practice-topics">
                {exercise.topics.slice(0, 4).map(topic => <span key={topic}>{topic}</span>)}
              </div>
              <Button
                appearance="primary"
                size="small"
                onClick={() => vscode.postMessage({ type: "openExercise", exerciseKey: exercise.key })}
              >
                Open starter
              </Button>
            </div>
          </Card>
        ))}
        {filtered.length === 0 && (
          <div className="empty-state">No exercises match this filter.</div>
        )}
      </div>
    </section>
  );
}
