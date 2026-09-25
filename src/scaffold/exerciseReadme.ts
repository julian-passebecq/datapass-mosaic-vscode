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
  const plan = exercise.sparkPlan;
  if (plan) {
    lines.push(
      "## Spark plan checks (simulated)",
      "",
      `Your code is also graded on the Spark plan SparkLab models for it with the \`${plan.profile}\` profile, ` +
        `AQE ${plan.aqe ? "on" : "off"}, at the input sizes below. These sizes are authored for the lesson; ` +
        "no data of that size is processed, and the model applies Spark's planning rules without being Apache Spark.",
      ""
    );
    if (plan.scale.length) {
      lines.push(
        "| Table | Rows | Size | Partitions | Size statistics |",
        "| --- | --- | --- | --- | --- |",
        ...plan.scale.map(table =>
          `| \`${table.table}\` | ${table.rows.toLocaleString("en-US")} | ${formatBytes(table.bytes)} | ` +
          `${table.partitions} | ${table.catalogStatistics ? "available" : "unavailable"} |`
        ),
        ""
      );
    }
    lines.push(...plan.checks.map(check => `- **${check.id}**: ${check.description}`), "");
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
      : exercise.language === "factory" || exercise.language === "factory-notebook"
        ? "**Run visible** runs the pipeline in the public scenario. **Submit** also runs hidden and edge-case " +
          "scenarios that are not shown here. The pipeline is simulated; notebooks run on SparkLab and are never " +
          "executed as Python; local data activities use an isolated catalog, never your workspace lakehouse."
        : exercise.language.startsWith("databricks-")
          ? "**Run visible** runs the job in the public scenario. **Submit** also runs hidden and edge-case scenarios " +
            "that are not shown here. The job is simulated; notebooks run on SparkLab and are never executed as Python; " +
            "each check uses an isolated catalog and Unity Catalog, never your workspace lakehouse."
        : exercise.language === "dbt-sql" || exercise.language === "dbt-yml"
          ? "**Run visible** runs the public check. **Submit** also runs hidden and edge-case checks that are not " +
            "shown here. Your file joins a small dbt project that the Datapass dbt emulation runs on an isolated " +
            "DuckDB catalog, never your workspace: Jinja is rendered in a sandbox and the SQL really runs. It follows " +
            "dbt Core and dbt-duckdb for a documented subset; it is not dbt Core."
        : exercise.language === "warehouse" || exercise.language === "bi-model"
          ? "**Run visible** runs the public check. **Submit** also runs hidden and edge-case checks that are not " +
            "shown here. Each check builds an isolated DuckDB catalog from the tables the exercise describes, never " +
            "your workspace catalog: SQL really runs, model checks are real queries, and column lineage is a static " +
            "analysis of your SQL text."
        : exercise.language === "sqlpool"
          ? "**Run visible** runs your T-SQL on the simulated SQL pool in the public scenario. **Submit** also runs " +
            "hidden and edge-case scenarios that are not shown here. Each check uses an isolated catalog, never your " +
            "workspace lakehouse; data statements really run, while distributions, partitions and data movement are modelled."
          : "**Run visible** checks the public example above. **Submit** also runs hidden and edge-case fixtures that are not shown here." +
            (plan ? " Both also grade the simulated Spark plan checks listed above." : ""),
    "",
    "## Workspace rule",
    "",
    "Edit the solution file next to this brief. Datapass will not overwrite an existing learner solution.",
    ""
  );
  return lines.join("\n");
}

function formatBytes(bytes: number): string {
  const units: [number, string][] = [[1024 ** 4, "TB"], [1024 ** 3, "GB"], [1024 ** 2, "MB"], [1024, "KB"]];
  for (const [size, unit] of units) {
    if (bytes >= size) return `${Number((bytes / size).toFixed(1))} ${unit}`;
  }
  return `${bytes} B`;
}

function markdownCell(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return "_NULL_";
  return String(value).replaceAll("|", "\\|").replace(/[\r\n]+/g, " ");
}
