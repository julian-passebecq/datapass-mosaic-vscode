/** Markdown brief written next to a native exercise solution file. Public data only. */
import type { ExerciseSummary } from "../webview/contracts";

export function exerciseReadme(exercise: ExerciseSummary): string {
  const topics = exercise.topics.length ? exercise.topics.join(", ") : "—";
  const lines = [
    `# ${exercise.title}`,
    "",
    `- Pack: ${exercise.packTitle}`,
    `- Language: ${exercise.language}`,
    `- Difficulty: ${exercise.difficulty}`,
    `- Truth: ${exercise.truth ?? "not specified"}`,
    `- Topics: ${topics}`,
    "",
    "## Task",
    "",
    exercise.prompt,
    ""
  ];
  for (const table of exercise.dataContext) {
    const columns = Object.keys(table.columns);
    lines.push(
      `## Input table \`${table.name}\``,
      "",
      columns.map(column => `\`${column}\` ${table.columns[column]}`).join(" · "),
      ""
    );
    if (table.sampleRows.length) {
      lines.push(
        `| ${columns.join(" | ")} |`,
        `| ${columns.map(() => "---").join(" | ")} |`,
        ...table.sampleRows.map(row => `| ${columns.map(column => markdownCell(row[column])).join(" | ")} |`),
        ""
      );
    } else {
      lines.push("_Empty in the public example._", "");
    }
  }
  for (const section of exercise.sections) {
    lines.push(`## ${section.title}`, "", section.body, "");
  }
  if (exercise.hints.length) {
    lines.push("## Hints", "");
    exercise.hints.forEach((hint, index) => {
      lines.push(`<details><summary>Hint ${index + 1}</summary>`, "", hint, "", "</details>", "");
    });
  }
  lines.push(
    "## Grading",
    "",
    exercise.language === "airflow"
      ? "**Run visible** simulates the public scenario. **Submit** also simulates hidden and edge-case scenarios " +
        "that are not shown here. The DAG file is parsed, never executed."
      : "**Run visible** checks the public example above. **Submit** also runs hidden and edge-case fixtures that are not shown here.",
    "",
    "## Workspace rule",
    "",
    "Edit the solution file next to this brief. Datapass will not overwrite an existing learner solution.",
    ""
  );
  return lines.join("\n");
}

function markdownCell(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return "_NULL_";
  return String(value).replaceAll("|", "\\|").replace(/[\r\n]+/g, " ");
}
