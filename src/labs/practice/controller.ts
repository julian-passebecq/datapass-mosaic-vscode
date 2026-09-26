import * as vscode from "vscode";
import { loadExerciseCatalog, REFERENCE_SHEET } from "../../exerciseCatalog";
import { prepareExerciseWorkspace } from "../../exerciseWorkspace";
import { SOLUTION_AFTER_FAILURES, solutionUnlocked } from "../../platform/practiceFeedback";
import { recordGrade, recordInterview, recordOpened, recordSolutionViewed, revealHint } from "../../platform/practiceProgress";
import { safeRelativeParts } from "../../platform/workspacePaths";
import { readProjectManifest } from "../../project/projectManifest";
import { readProgress, updateProgress } from "../../projectState";
import { loadReferenceSolution, referenceUri } from "../../referenceSolutions";
import { exerciseReadme } from "../../scaffold/exerciseReadme";
import type { PracticeMessage } from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";

/** Practice: exercises as native solution files, graded by the shared runtime; progress in .datapass/progress.json. */
export class PracticeController implements LabController<PracticeMessage> {
  /** Reference solutions revealed in this panel, by exercise key (the text is read from the pack on demand). */
  private readonly revealedSolutions = new Map<string, string>();
  /** A broken progress.json is reported once per panel, not on every grading. */
  private practiceProgressWarned = false;

  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<PracticeMessage> = {
    openExercise: message => this.openExercise(message.exerciseKey),
    gradeExercise: message => this.gradeExercise(message.exerciseKey, message.mode),
    revealHint: message => this.revealHint(message.exerciseKey),
    showSolution: async message => {
      await this.showSolution(message.exerciseKey);
    },
    compareSolution: message => this.compareSolution(message.exerciseKey),
    openReference: message => this.openReference(message.exerciseKey, message.index),
    saveInterview: message => this.saveInterview(message.interview)
  };

  contribute(): Partial<WorkbenchStateExtras> {
    return { practiceSolutions: Object.fromEntries(this.revealedSolutions) };
  }

  /** Create the exercise's solution file and README (never overwriting) and open it beside the Workbench. */
  async openExercise(exerciseKey: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before opening a Datapass exercise.");
      return;
    }

    const extensionUri = this.host.context.extensionUri;
    const catalog = await loadExerciseCatalog(extensionUri);
    const exercise = catalog.find(item => item.key === exerciseKey);
    if (!exercise) {
      void vscode.window.showErrorMessage(`Exercise not found: ${exerciseKey}`);
      return;
    }

    const manifest = await readProjectManifest();
    const exerciseRoot = safeRelativeParts(manifest.manifest?.assets?.exercises, "exercises");
    const directory = vscode.Uri.joinPath(
      root,
      ...exerciseRoot,
      slug(exercise.id),
      slug(exercise.language)
    );
    const starterUri = vscode.Uri.joinPath(directory, `solution.${extensionFor(exercise.language)}`);
    const readmeUri = vscode.Uri.joinPath(directory, "README.md");

    await vscode.workspace.fs.createDirectory(directory);
    if (!(await exists(starterUri))) {
      await vscode.workspace.fs.writeFile(
        starterUri,
        new TextEncoder().encode(ensureTrailingNewline(exercise.starterSource))
      );
    }
    if (!(await exists(readmeUri))) {
      await vscode.workspace.fs.writeFile(
        readmeUri,
        new TextEncoder().encode(exerciseReadme(exercise))
      );
    }
    await prepareExerciseWorkspace(extensionUri, root, exerciseRoot, directory, exercise, console.warn);
    await this.savePracticeProgress(document => ({
      ...document,
      practice: recordOpened(document.practice, exercise.key, new Date().toISOString())
    }));

    await this.host.openBeside(starterUri);
  }

  private async gradeExercise(
    exerciseKey: string,
    mode: "run" | "submit"
  ): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before grading a Datapass exercise.");
      return;
    }

    const catalog = await loadExerciseCatalog(this.host.context.extensionUri);
    const exercise = catalog.find(item => item.key === exerciseKey);
    if (!exercise) {
      void vscode.window.showErrorMessage(`Exercise not found: ${exerciseKey}`);
      return;
    }

    const manifest = await readProjectManifest();
    const exerciseRoot = safeRelativeParts(manifest.manifest?.assets?.exercises, "exercises");
    const directory = vscode.Uri.joinPath(
      root,
      ...exerciseRoot,
      slug(exercise.id),
      slug(exercise.language)
    );
    const starterUri = vscode.Uri.joinPath(
      directory,
      `solution.${extensionFor(exercise.language)}`
    );

    if (!(await exists(starterUri))) {
      await this.openExercise(exerciseKey);
      void vscode.window.showInformationMessage(
        "Exercise starter created. Edit the native solution file, then run the checks."
      );
      return;
    }

    const openDocument = vscode.workspace.textDocuments.find(
      document => document.uri.toString() === starterUri.toString()
    );
    const code = openDocument
      ? openDocument.getText()
      : new TextDecoder().decode(await vscode.workspace.fs.readFile(starterUri));

    if (!code.trim()) {
      void vscode.window.showWarningMessage("The exercise solution file is empty.");
      return;
    }

    try {
      await this.host.runtime.labs.practice.gradeExercise(exercise.key, {
        exercise_id: exercise.id,
        exercise_version: exercise.version,
        language: exercise.language,
        code,
        mode,
        notebook_id: `exercise-${slug(exercise.id)}-${slug(exercise.version)}`,
        cell_id: "solution",
        source_revision: openDocument?.version ?? 0
      });
      const result = this.host.runtime.snapshot().practiceResult;
      if (result?.exerciseKey === exercise.key) {
        await this.savePracticeProgress(document => ({
          ...document,
          practice: recordGrade(document.practice, exercise.key, exercise.version, mode, result.status, new Date().toISOString())
        }));
      }
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Exercise grading failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }

  /** One more hint for an exercise; the count is kept in .datapass/progress.json. */
  private async revealHint(exerciseKey: string): Promise<void> {
    const exercise = (await loadExerciseCatalog(this.host.context.extensionUri)).find(item => item.key === exerciseKey);
    if (!exercise?.hints.length) return;
    await this.savePracticeProgress(document => ({
      ...document,
      practice: revealHint(document.practice, exercise.key, exercise.hints.length)
    }));
    await this.host.refresh();
  }

  /**
   * The pack's reference solution and explanation, once the exercise is solved or after a few failed gradings.
   * Reference solutions ship in the VSIX: this is a teaching choice, not an exam control.
   */
  private async showSolution(exerciseKey: string): Promise<string | undefined> {
    const extensionUri = this.host.context.extensionUri;
    const exercise = (await loadExerciseCatalog(extensionUri)).find(item => item.key === exerciseKey);
    if (!exercise) return undefined;
    const record = (await readProgress()).document.practice?.exercises[exercise.key];
    if (!solutionUnlocked(record)) {
      void vscode.window.showInformationMessage(
        `The reference solution opens once you solve the exercise, or after ${SOLUTION_AFTER_FAILURES} gradings that do not pass.`
      );
      return undefined;
    }
    const code = await loadReferenceSolution(extensionUri, exercise);
    if (code === undefined) {
      void vscode.window.showWarningMessage("This exercise has no reference solution to show.");
      return undefined;
    }
    this.revealedSolutions.set(exercise.key, code);
    await this.savePracticeProgress(document => ({
      ...document,
      practice: recordSolutionViewed(document.practice, exercise.key, new Date().toISOString())
    }));
    await this.host.refresh();
    return code;
  }

  /** VS Code's diff editor: the reference (read-only) on the left, the learner's solution file on the right. */
  private async compareSolution(exerciseKey: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    const exercise = (await loadExerciseCatalog(this.host.context.extensionUri)).find(item => item.key === exerciseKey);
    if (!root || !exercise) return;
    const code = this.revealedSolutions.get(exerciseKey) ?? await this.showSolution(exerciseKey);
    if (code === undefined) return;
    const manifest = await readProjectManifest();
    const exerciseRoot = safeRelativeParts(manifest.manifest?.assets?.exercises, "exercises");
    const extension = extensionFor(exercise.language);
    const mine = vscode.Uri.joinPath(root, ...exerciseRoot, slug(exercise.id), slug(exercise.language), `solution.${extension}`);
    if (!(await exists(mine))) {
      void vscode.window.showWarningMessage("Open the exercise first: there is no solution file to compare yet.");
      return;
    }
    await vscode.commands.executeCommand("vscode.diff", referenceUri(exercise, extension), mine, `${exercise.id}: reference ↔ your solution`, {
      viewColumn: vscode.ViewColumn.Beside
    });
  }

  /** A finished interview's summary, validated before it joins .datapass/progress.json. */
  private async saveInterview(interview: unknown): Promise<void> {
    await this.savePracticeProgress(document => ({ ...document, practice: recordInterview(document.practice, interview) }));
    await this.host.refresh();
  }

  /** A card's reference sheet, opened as a native Markdown preview (the path comes from the pack, never the webview). */
  private async openReference(exerciseKey: string, index: number): Promise<void> {
    const extensionUri = this.host.context.extensionUri;
    const exercise = (await loadExerciseCatalog(extensionUri)).find(item => item.key === exerciseKey);
    const sheet = Number.isInteger(index) ? exercise?.references?.[index] : undefined;
    if (!sheet || !REFERENCE_SHEET.test(sheet)) return;
    const uri = vscode.Uri.joinPath(extensionUri, "content", ...sheet.split("/"));
    if (!(await exists(uri))) {
      void vscode.window.showWarningMessage(`Reference sheet not found: ${sheet}`);
      return;
    }
    await vscode.commands.executeCommand("markdown.showPreview", uri);
  }

  /** Practice progress lives in .datapass/progress.json next to the Projects progress. Saving it never blocks Practice. */
  private async savePracticeProgress(update: Parameters<typeof updateProgress>[0]): Promise<void> {
    if (!vscode.workspace.workspaceFolders?.length) return;
    try {
      await updateProgress(update);
    } catch (error) {
      if (this.practiceProgressWarned) return;
      this.practiceProgressWarned = true;
      void vscode.window.showWarningMessage(
        `Practice progress was not saved: ${error instanceof Error ? error.message : String(error)} Fix or delete .datapass/progress.json.`
      );
    }
  }
}

function extensionFor(language: string): string {
  switch (language.toLowerCase()) {
    case "sql":
    case "dbt":
    case "sqlpool":
    case "databricks-grants":
    case "warehouse":
    case "dbt-sql":
    case "snowflake":
    case "tsql":
    case "bigquery":
    case "sparksql":
      return "sql";
    case "python":
    case "pandas":
    case "polars":
    case "sparklab":
    case "pyspark":
    case "airflow":
    case "factory-notebook":
    case "databricks-notebook":
    case "pytest":
      return "py";
    case "factory":
    case "databricks-job":
    case "bi-model":
      return "json";
    case "powershell":
      return "ps1";
    case "yaml":
    case "yml":
    case "dbt-yml":
      return "yml";
    default:
      return "txt";
  }
}

function slug(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "exercise";
}

function ensureTrailingNewline(value: string): string {
  return value.endsWith("\n") ? value : value + "\n";
}
