import * as vscode from "vscode";
import { AIRFLOW_STARTER_FILE, airflowPaths } from "../../airflowState";
import { copyBiSamples } from "../../biState";
import { copyFactorySamples } from "../../factoryState";
import {
  applyVerification,
  emptyProgress,
  isProjectFilePath,
  serializeProgress,
  setManual,
  type ProjectContent,
  type ProjectScaffold
} from "../../platform/projects";
import { safeRelativeParts } from "../../platform/workspacePaths";
import { readProjectManifest } from "../../project/projectManifest";
import { copyProjectFiles, loadProjectContents, progressUri, readProgress, writeProgress } from "../../projectState";
import { airflowStarter, pipelineStarter, scratchSpec } from "../../scaffold/starters";
import type { ProjectsHostState, ProjectsMessage } from "../../webview/contracts";
import { exists, writeIfMissing } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";

/** What a project step opens in the other labs. */
export interface ProjectStepLabs {
  openExercise(exerciseKey: string): Promise<void>;
  writeRetailDemoFiles(): Promise<vscode.Uri | undefined>;
}

/**
 * Projects: end-to-end stories whose steps are done in the labs. "Verify" runs the runtime's checks on the workspace;
 * a tick by hand is kept apart and never becomes a verification.
 */
export class ProjectsController implements LabController<ProjectsMessage> {
  readonly refreshOnSave = "projects" as const;
  /** A project verification in flight, or the last one's error. */
  private projectsHost: ProjectsHostState = {};

  constructor(private readonly host: WorkbenchHost, private readonly labs: ProjectStepLabs) {}

  readonly handlers: MessageHandlers<ProjectsMessage> = {
    prepareProject: message => this.prepareProject(message.projectId),
    openProjectStep: message => this.openProjectStep(message.projectId, message.stepId),
    verifyProjectSteps: message => this.verifyProjectSteps(message.projectId, message.stepIds),
    setProjectStepManual: message => this.setProjectStepManual(message.projectId, message.stepId, message.checked),
    openProgressFile: () => this.openProgressFile()
  };

  contribute(): Partial<WorkbenchStateExtras> {
    return { projects: this.projectsHost };
  }

  private async findProject(projectId: string): Promise<ProjectContent | undefined> {
    const project = (await loadProjectContents(this.host.context.extensionUri)).projects.find(p => p.id === projectId);
    if (!project) void vscode.window.showErrorMessage(`Project not found: ${projectId}`);
    return project;
  }

  /** Create the lab files a step needs, never overwriting the learner's files. */
  private async runScaffolds(project: ProjectContent, names: readonly ProjectScaffold[]): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) return;
    const extensionUri = this.host.context.extensionUri;
    for (const name of new Set(names)) {
      switch (name) {
        case "project":
          await copyProjectFiles(extensionUri, project.id);
          break;
        case "factory":
          await copyFactorySamples(extensionUri);
          break;
        case "bi":
          await copyBiSamples(extensionUri);
          break;
        case "retail_demo":
          await this.labs.writeRetailDemoFiles();
          break;
        case "airflow": {
          const { dagsParts } = await airflowPaths();
          await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, ...dagsParts));
          await writeIfMissing(vscode.Uri.joinPath(root, ...dagsParts, AIRFLOW_STARTER_FILE), airflowStarter());
          break;
        }
        case "pipeline": {
          const manifest = await readProjectManifest();
          const directory = vscode.Uri.joinPath(root, ...safeRelativeParts(manifest.manifest?.assets?.pipelines, "pipelines"));
          await vscode.workspace.fs.createDirectory(directory);
          await writeIfMissing(vscode.Uri.joinPath(directory, "main.pipeline.py"), pipelineStarter());
          break;
        }
        case "sparklab": {
          const manifest = await readProjectManifest();
          const directory = vscode.Uri.joinPath(root, ...safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks"));
          const spec = scratchSpec("sparklab");
          await vscode.workspace.fs.createDirectory(directory);
          await writeIfMissing(vscode.Uri.joinPath(directory, spec.fileName), spec.content);
          break;
        }
      }
    }
  }

  /** Every file the project's steps need: its starter files and the lab samples. */
  private async prepareProject(projectId: string): Promise<void> {
    if (!vscode.workspace.workspaceFolders?.length) {
      void vscode.window.showWarningMessage("Open a workspace folder before preparing a project.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project) return;
    await this.runScaffolds(project, project.steps.flatMap(step => step.open.scaffold));
    void vscode.window.showInformationMessage(
      `Files for "${project.title}" are ready (projects/${project.id}/ and the lab samples). Existing files were kept.`
    );
    await this.host.refresh();
  }

  /** "Open in <lab>": create the step's files, open its file or exercise beside, and show its lab and tab. */
  private async openProjectStep(projectId: string, stepId: string): Promise<void> {
    const project = await this.findProject(projectId);
    const step = project?.steps.find(s => s.id === stepId);
    if (!project || !step) return;
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before opening a project step.");
      return;
    }
    await this.runScaffolds(project, step.open.scaffold);
    let query: string | undefined;
    if (step.open.exercise) {
      await this.labs.openExercise(step.open.exercise);
      query = step.open.exercise.split("/")[1];
    } else if (step.open.file && isProjectFilePath(step.open.file)) {
      const uri = vscode.Uri.joinPath(root, ...step.open.file.split("/"));
      if (await exists(uri)) await this.host.openBeside(uri);
      else void vscode.window.showWarningMessage(`Fichier introuvable : ${step.open.file}`);
    }
    this.host.showModule(step.open.module, { tab: step.open.tab, query, exerciseKey: step.open.exercise });
    await this.host.refresh();
  }

  /** "Verify": the runtime checks the steps on the workspace; the result is kept in .datapass/progress.json. */
  private async verifyProjectSteps(projectId: string, stepIds: string[]): Promise<void> {
    if (this.host.runtime.snapshot().status !== "running") {
      void vscode.window.showWarningMessage("Start the Datapass runtime to verify steps: it reads the catalog and the journal of what the labs ran.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project || !Array.isArray(stepIds)) return;
    const known = stepIds.filter(id => project.steps.some(step => step.id === id && step.checks.length));
    if (!known.length) return;
    this.projectsHost = { verifying: { projectId, stepIds: known } };
    await this.host.refresh();
    try {
      const progress = await readProgress();
      if (progress.error) throw new Error(`${progress.error} Fix or delete the file, then verify again.`);
      const result = await this.host.runtime.labs.projects.checkProject(projectId, known);
      await writeProgress(applyVerification(progress.document, project, result, new Date().toISOString()));
      this.projectsHost = {};
    } catch (error) {
      this.projectsHost = { error: `Verification failed: ${error instanceof Error ? error.message : String(error)}` };
    }
    await this.host.refresh();
  }

  /** The learner ticks a step by hand: kept as a declaration, never as a verification. */
  private async setProjectStepManual(projectId: string, stepId: string, checked: boolean): Promise<void> {
    if (!vscode.workspace.workspaceFolders?.length) {
      void vscode.window.showWarningMessage("Open a workspace folder to keep project progress.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project || !project.steps.some(step => step.id === stepId)) return;
    const progress = await readProgress();
    if (progress.error) {
      void vscode.window.showErrorMessage(`${progress.error} Fix or delete the file.`);
      return;
    }
    await writeProgress(setManual(progress.document, project, stepId, checked === true, new Date().toISOString()));
    await this.host.refresh();
  }

  private async openProgressFile(): Promise<void> {
    const uri = progressUri();
    if (!uri) return;
    if (!(await exists(uri))) {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(uri, ".."));
      await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(serializeProgress(emptyProgress())));
    }
    await this.host.openBeside(uri);
  }
}
