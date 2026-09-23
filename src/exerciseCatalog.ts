import * as vscode from "vscode";
import type { ExerciseSummary } from "./webview/contracts";

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
  const language = stringValue(value.language);
  const starterSource = stringValue(value.starter_source);
  if (!id || !title || !language || starterSource === undefined) return undefined;

  return {
    key: `${packId}/${id}/${language}`,
    packId,
    packTitle,
    id,
    title,
    difficulty: stringValue(value.difficulty) ?? "unspecified",
    language,
    prompt: stringValue(value.prompt) ?? "",
    starterSource,
    truth: stringValue(value.truth),
    topics: stringArray(value.topics)
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
  const title = stringValue(common.title);
  if (!id || !title) return [];

  const result: ExerciseSummary[] = [];
  for (const [language, candidate] of Object.entries(variants)) {
    const variant = objectValue(candidate);
    const starterSource = stringValue(variant?.starter_source);
    if (starterSource === undefined) continue;

    result.push({
      key: `${packId}/${id}/${language}`,
      packId,
      packTitle,
      id,
      title,
      difficulty: stringValue(common.difficulty) ?? "unspecified",
      language,
      prompt: stringValue(common.prompt) ?? "",
      starterSource,
      truth: stringValue(common.truth),
      topics: stringArray(common.topics)
    });
  }
  return result;
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
