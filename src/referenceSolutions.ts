import * as vscode from "vscode";
import { referenceSolution } from "./platform/practiceFeedback";
import type { ExerciseSummary } from "./webview/contracts";

/**
 * Read-only documents for reference solutions, so "Compare with my solution" uses VS Code's own diff editor.
 * The URI names the pack, exercise and language; the text is read from the pack when VS Code asks for it.
 */
export const REFERENCE_SCHEME = "datapass-reference";
const SEGMENT = /^[A-Za-z0-9_.-]{1,160}$/;

export function registerReferenceSolutions(extensionUri: vscode.Uri): vscode.Disposable {
  return vscode.workspace.registerTextDocumentContentProvider(REFERENCE_SCHEME, {
    async provideTextDocumentContent(uri) {
      const [packId, exerciseId, language] = uri.path.split("/").filter(Boolean);
      const code = packId && exerciseId && language
        ? await readReferenceSolution(extensionUri, packId, exerciseId, language)
        : undefined;
      return code === undefined ? "No reference solution for this exercise." : code.endsWith("\n") ? code : `${code}\n`;
    }
  });
}

/** The reference solution shipped with the exercise's pack (grading.server.json), or undefined. */
export async function loadReferenceSolution(extensionUri: vscode.Uri, exercise: ExerciseSummary): Promise<string | undefined> {
  if (!exercise.solutionAvailable) return undefined;
  return readReferenceSolution(extensionUri, exercise.packId, exercise.id, exercise.language);
}

async function readReferenceSolution(extensionUri: vscode.Uri, packId: string, exerciseId: string,
  language: string): Promise<string | undefined> {
  if (![packId, exerciseId, language].every(part => SEGMENT.test(part) && part !== "." && part !== "..")) return undefined;
  try {
    const uri = vscode.Uri.joinPath(extensionUri, "content", "exercise-packs", packId, "grading.server.json");
    return referenceSolution(JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri))), exerciseId, language);
  } catch {
    return undefined;
  }
}

/** datapass-reference:/<pack>/<exercise>/<language>/reference.<ext>: the extension gives the diff its syntax colors. */
export function referenceUri(exercise: ExerciseSummary, extension: string): vscode.Uri {
  return vscode.Uri.from({
    scheme: REFERENCE_SCHEME,
    path: `/${exercise.packId}/${exercise.id}/${exercise.language}/reference.${extension}`
  });
}
