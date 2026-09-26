import * as vscode from "vscode";
import { rowValidation, type RowValidation } from "./platform/practiceFeedback";
import type { ExerciseSectionView, ExerciseSummary, ExerciseTableView, SparkPlanView } from "./webview/contracts";

/** Runtimes whose grading needs something Datapass does not provide locally. */
const NOT_LOCALLY_GRADED: Record<string, string> = {
  "fastapispark-guided-v1":
    "Graded only against an explicitly qualified remote Spark connection. Datapass has no local fallback for this lesson; read and edit it here, grade it where that connection exists."
};

interface RawManifest {
  id?: unknown;
  title?: unknown;
  enabled?: unknown;
}

export async function loadExerciseCatalog(
  extensionUri: vscode.Uri
): Promise<ExerciseSummary[]> {
  const packsRoot = vscode.Uri.joinPath(extensionUri, "content", "exercise-packs");
  let entries: [string, vscode.FileType][];
  try {
    entries = await vscode.workspace.fs.readDirectory(packsRoot);
  } catch {
    return [];
  }

  const catalog: ExerciseSummary[] = [];
  for (const [folderName, fileType] of entries.sort((a, b) => a[0].localeCompare(b[0]))) {
    if ((fileType & vscode.FileType.Directory) === 0) continue;
    const packRoot = vscode.Uri.joinPath(packsRoot, folderName);
    const manifest = await readOptionalJson<RawManifest>(vscode.Uri.joinPath(packRoot, "manifest.json"));
    if (manifest?.enabled === false) continue;

    const packId = stringValue(manifest?.id) ?? folderName;
    const packTitle = stringValue(manifest?.title) ?? packId;

    const exercises = await readOptionalJson<unknown[]>(vscode.Uri.joinPath(packRoot, "exercises.json"));
    if (Array.isArray(exercises)) {
      for (const raw of exercises) {
        const item = normalizeExercise(raw, packId, packTitle);
        if (item) catalog.push(item);
      }
    }

    const scenarios = await readOptionalJson<unknown[]>(vscode.Uri.joinPath(packRoot, "scenarios.json"));
    if (Array.isArray(scenarios)) {
      for (const raw of scenarios) {
        catalog.push(...normalizeScenario(raw, packId, packTitle));
      }
    }
  }

  return catalog.sort((a, b) =>
    a.packTitle.localeCompare(b.packTitle) ||
    a.title.localeCompare(b.title) ||
    a.language.localeCompare(b.language)
  );
}

function normalizeExercise(
  raw: unknown,
  packId: string,
  packTitle: string
): ExerciseSummary | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const value = raw as Record<string, unknown>;
  const id = stringValue(value.id);
  const title = stringValue(value.title);
  const version = stringValue(value.version);
  const language = stringValue(value.language);
  const starterSource = stringValue(value.starter_source);
  if (!id || !title || !version || !language || starterSource === undefined) return undefined;

  // A plain-pack variant that names a semantic problem (a Polars variant of a Spark exercise) joins that
  // problem's card; the key of an exercise without one is unchanged, so saved progress keeps its keys.
  const problem = stringValue(objectValue(value.semantic)?.id) ?? id;

  return {
    key: `${packId}/${problem}/${language}`,
    packId,
    packTitle,
    id,
    version,
    title,
    difficulty: stringValue(value.difficulty) ?? "unspecified",
    language,
    runtime: stringValue(value.runtime),
    prompt: stringValue(value.prompt) ?? "",
    starterSource,
    truth: stringValue(value.truth),
    topics: stringArray(value.topics),
    ...teachingDetails(value),
    sparkPlan: sparkPlan(value.spark_plan),
    gradingNote: NOT_LOCALLY_GRADED[stringValue(value.runtime) ?? ""]
  };
}

function sparkPlan(raw: unknown): SparkPlanView | undefined {
  const plan = objectValue(raw);
  if (!plan) return undefined;
  const checks = (Array.isArray(plan.checks) ? plan.checks : []).flatMap(item => {
    const check = objectValue(item);
    const id = stringValue(check?.id);
    const description = stringValue(check?.description);
    return id && description ? [{ id, description }] : [];
  });
  if (!checks.length) return undefined;
  const scale = Object.entries(objectValue(plan.scale) ?? {}).flatMap(([table, item]) => {
    const size = objectValue(item);
    if (!size || typeof size.rows !== "number" || typeof size.bytes !== "number" || typeof size.partitions !== "number") {
      return [];
    }
    return [{
      table,
      rows: size.rows,
      bytes: size.bytes,
      partitions: size.partitions,
      catalogStatistics: size.catalog_statistics_available !== false
    }];
  });
  return {
    profile: stringValue(plan.profile) ?? "generic_8x8",
    aqe: plan.aqe !== false,
    scale,
    checks
  };
}

function normalizeScenario(
  raw: unknown,
  packId: string,
  packTitle: string
): ExerciseSummary[] {
  if (!raw || typeof raw !== "object") return [];
  const value = raw as Record<string, unknown>;
  const semantic = objectValue(value.semantic);
  const common = objectValue(value.common);
  const variants = objectValue(value.variants);
  if (!common || !variants) return [];

  const id = stringValue(semantic?.id) ?? stringValue(common.id);
  const version = stringValue(semantic?.version) ?? stringValue(common.version);
  const title = stringValue(common.title);
  if (!id || !version || !title) return [];

  const result: ExerciseSummary[] = [];
  for (const [language, candidate] of Object.entries(variants)) {
    const variant = objectValue(candidate);
    const starterSource = stringValue(variant?.starter_source);
    if (starterSource === undefined) continue;

    result.push({
      key: `${packId}/${id}/${language}`,
      packId,
      packTitle,
      // The runtime registers each semantic variant as `<scenario>-<language>`.
      id: `${id}-${language}`,
      version,
      title,
      difficulty: stringValue(common.difficulty) ?? "unspecified",
      language,
      prompt: stringValue(common.prompt) ?? "",
      starterSource,
      truth: stringValue(common.truth),
      topics: stringArray(common.topics),
      ...teachingDetails(common)
    });
  }
  return result;
}

function teachingDetails(value: Record<string, unknown>): {
  sections: ExerciseSectionView[];
  hints: string[];
  dataContext: ExerciseTableView[];
  validation: RowValidation;
  explanation?: string;
  solutionAvailable: boolean;
} {
  const sections = (Array.isArray(value.sections) ? value.sections : []).flatMap(raw => {
    const section = objectValue(raw);
    const title = stringValue(section?.title);
    const body = stringValue(section?.body);
    return title && body ? [{ title, body }] : [];
  });
  const dataContext = (Array.isArray(value.data_context) ? value.data_context : []).flatMap(raw => {
    const table = objectValue(raw);
    const name = stringValue(table?.name);
    const columns = objectValue(table?.columns);
    if (!name || !columns) return [];
    const sampleRows = (Array.isArray(table?.sample_rows) ? table.sample_rows : [])
      .map(row => objectValue(row))
      .filter((row): row is Record<string, unknown> => row !== undefined)
      .map(row => Object.fromEntries(Object.keys(columns).map(column => [column, scalar(row[column])])));
    return [{
      name,
      columns: Object.fromEntries(Object.entries(columns).map(([column, type]) => [column, String(type)])),
      sampleRows
    }];
  });
  return {
    sections,
    hints: stringArray(value.hints),
    dataContext,
    validation: rowValidation(value.validation),
    explanation: stringValue(value.explanation),
    solutionAvailable: objectValue(value.solution)?.available === true
  };
}

function scalar(value: unknown): string | number | boolean | null {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? value : null;
}

async function readOptionalJson<T>(uri: vscode.Uri): Promise<T | undefined> {
  try {
    const bytes = await vscode.workspace.fs.readFile(uri);
    return JSON.parse(new TextDecoder().decode(bytes)) as T;
  } catch {
    return undefined;
  }
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}
