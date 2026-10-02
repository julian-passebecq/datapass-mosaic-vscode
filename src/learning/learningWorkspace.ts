import * as vscode from "vscode";
import { createHash, randomBytes } from "node:crypto";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { loadExerciseCatalog } from "../exerciseCatalog";
import type { OpenWorkbench } from "../nativeIntegration";
import { readProgress } from "../projectState";
import type { RuntimeManager } from "../runtimeManager";
import type { ExerciseSummary, PracticeResultView } from "../webview/contracts";
import { lessonStatus, MODES, parseMessage, restoreState, validateCatalog,
  type LearningCatalog, type LearningMode, type LearningState, type Lesson } from "../../media/learning/model.mjs";

const STORE = "datapass.learning.workspace.v1";
const MAX_SOURCE = 64_000;
const digest = (s: string) => createHash("sha256").update(s.replace(/\r\n?/g, "\n")).digest("hex");
const messageOf = (e: unknown) => e instanceof Error ? e.message : String(e);
export interface LearningRun {
  id: string; lesson: string; language: string; scope: "file" | "selection" | "explain";
  sourceHash: string; at: string; evidence: unknown;
}

/** A view orchestrator over the existing runtime/controllers, never another execution engine. */
export class LearningWorkspace implements vscode.Disposable, vscode.TreeDataProvider<LearningNode> {
  private panel: vscode.WebviewPanel | undefined;
  private readonly emitter = new vscode.EventEmitter<LearningNode | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;
  private readonly disposables: vscode.Disposable[] = [];
  private tree: vscode.TreeView<LearningNode> | undefined;
  private catalog!: LearningCatalog;
  private exercises: ExerciseSummary[] = [];
  private state!: LearningState;
  private readonly ready: Promise<void>;
  private saves: Promise<void> = Promise.resolve();
  private busy = false;
  private notice = "";
  private runs = new Map<string, LearningRun>();
  private pinned = new Map<string, LearningRun>();
  private history: Omit<LearningRun, "evidence">[] = [];
  private statuses: Record<string, string> = {};
  private practiceResult: PracticeResultView | undefined;
  private renderSerial = 0;
  private disposed = false;
  private editorUri: vscode.Uri | undefined;

  constructor(private readonly context: vscode.ExtensionContext, private readonly runtime: RuntimeManager, private readonly open: OpenWorkbench) {
    this.ready = this.initialize();
    void this.ready.catch(error => { this.notice = messageOf(error); });
    this.disposables.push(vscode.workspace.onDidChangeTextDocument(event => {
      if (this.editorUri && event.document.uri.toString() === this.editorUri.toString()) void this.refresh();
    }));
    this.disposables.push(runtime.onDidChange(() => { void this.refresh(); }));
    const root = vscode.workspace.workspaceFolders?.[0];
    if (root) {
      const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, ".datapass/progress.json"));
      watcher.onDidChange(() => void this.refresh()); watcher.onDidCreate(() => void this.refresh()); watcher.onDidDelete(() => void this.refresh());
      this.disposables.push(watcher);
    }
  }

  private async initialize(): Promise<void> {
    const raw = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(this.context.extensionUri, "content", "learning", "catalog.json"));
    if (raw.length > 512_000) throw new Error("Learning catalog is too large.");
    this.catalog = validateCatalog(JSON.parse(new TextDecoder().decode(raw)));
    this.exercises = await loadExerciseCatalog(this.context.extensionUri);
    for (const lesson of this.catalog.lessons) if (!this.exercise(lesson)) throw new Error(`Learning exercise is not installed: ${lesson.exercise.id}`);
    this.state = restoreState(this.catalog, this.context.workspaceState.get(STORE));
  }
  private exercise(lesson: Lesson): ExerciseSummary | undefined {
    return this.exercises.find(e => e.id === lesson.exercise.id && e.language === lesson.exercise.language);
  }
  attachTree(tree: vscode.TreeView<LearningNode>): void { this.tree = tree; }
  async show(): Promise<void> {
    await this.ready;
    if (!this.panel) {
      const media = vscode.Uri.joinPath(this.context.extensionUri, "media", "learning");
      const panel = vscode.window.createWebviewPanel("datapass.learning", "Mosaic Learning", vscode.ViewColumn.Active,
        { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [media] });
      this.panel = panel;
      const nonce = randomBytes(18).toString("base64");
      const script = panel.webview.asWebviewUri(vscode.Uri.joinPath(media, "view.mjs"));
      const css = panel.webview.asWebviewUri(vscode.Uri.joinPath(media, "view.css"));
      panel.webview.html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${panel.webview.cspSource} data:; style-src ${panel.webview.cspSource}; script-src 'nonce-${nonce}' ${panel.webview.cspSource}; connect-src 'none'; font-src ${panel.webview.cspSource};"><title>Mosaic Learning</title><link rel="stylesheet" href="${css}"></head><body><main id="learning-root" aria-label="Mosaic Learning"><p>Loading the learning paths...</p></main><script type="module" nonce="${nonce}" src="${script}"></script></body></html>`;
      panel.webview.onDidReceiveMessage(raw => { void this.handle(raw).catch(e => this.report(e)); }, undefined, this.disposables);
      panel.onDidDispose(() => { if (this.panel === panel) this.panel = undefined; });
      panel.onDidChangeViewState(() => { if (panel.visible) void this.refresh(); }, undefined, this.disposables);
    } else this.panel.reveal(undefined, true);
    await this.refresh();
  }
  private report(error: unknown): void {
    this.notice = messageOf(error); void vscode.window.showWarningMessage(`Mosaic Learning: ${this.notice}`); void this.refresh();
  }
  private async save(change: (current: LearningState) => LearningState): Promise<void> {
    const task = this.saves.then(async () => {
      const next = change(this.state);
      await this.context.workspaceState.update(STORE, next);
      this.state = next;
    });
    this.saves = task.catch(() => undefined);
    await task;
  }
  async select(pathId: string, lessonId: string, mode: LearningMode = "read"): Promise<void> {
    await this.ready;
    if (!this.catalog.paths.some(p => p.id === pathId && p.lessons.includes(lessonId)) || !MODES.includes(mode)) throw new Error("Unknown learning destination.");
    await this.save(s => ({ ...s, path: pathId, lesson: lessonId, mode }));
    this.notice = ""; this.editorUri = undefined;
    await this.show();
  }
  /** Incoming targets must refer to the shipped catalog. No webview-supplied filename, SQL or command is accepted. */
  async handle(raw: unknown): Promise<void> {
    await this.ready;
    const msg = parseMessage(raw, this.catalog);
    if (!msg) throw new Error("Unsupported learning action.");
    if (msg.type === "ready") { await this.refresh(); return; }
    if (msg.type === "select") { await this.select(msg.path, msg.lesson); return; }
    if (msg.type === "rail") { await this.save(s => ({ ...s, railHidden: msg.hidden })); await this.refresh(); return; }
    if (msg.type === "layout") { await this.save(s => ({ ...s, layout: msg.layout })); await this.refresh(); return; }
    if (msg.type === "openRuntime") { await this.open("home"); return; }
    if (msg.type === "nativePath") { await vscode.commands.executeCommand("datapass.learning.path.focus"); return; }
    if (msg.type === "export") { await this.exportProgress(); return; }
    if (!("lesson" in msg)) return;
    // An old hidden webview must not run actions against a newly selected lesson.
    if (msg.lesson !== this.state.lesson) throw new Error("The lesson changed. Use the controls of the current lesson.");
    const lesson = this.catalog.lessons.find(l => l.id === msg.lesson)!;
    if (msg.type === "mode") {
      await this.save(s => ({ ...s, mode: msg.mode }));
      if (msg.mode === "try") await this.openExample(lesson);
      if (msg.mode === "exercise") await this.openExercise(lesson);
    } else if (msg.type === "read") {
      await this.save(s => ({ ...s, read: { ...s.read, [lesson.id]: { version: lesson.version, at: new Date().toISOString() } } }));
    } else if (msg.type === "note") {
      await this.save(s => ({ ...s, notes: { ...s.notes, [lesson.id]: msg.text } }));
      this.notice = "Notes saved in workspace storage.";
    } else if (msg.type === "next" || msg.type === "previous") {
      const p = this.catalog.paths.find(p => p.id === this.state.path)!;
      const index = p.lessons.indexOf(lesson.id) + (msg.type === "next" ? 1 : -1);
      if (p.lessons[index]) await this.select(p.id, p.lessons[index]);
    } else if (msg.type === "openExample") await this.openExample(lesson);
    else if (msg.type === "run" || msg.type === "runSelection" || msg.type === "explain") await this.run(lesson, msg.type);
    else if (msg.type === "grade") await this.grade(lesson, msg.mode);
    else if (msg.type === "hint") {
      await this.open("practice", { type: "revealHint", exerciseKey: this.exercise(lesson)!.key });
      this.panel?.reveal(vscode.ViewColumn.Two, true);
    }
    else if (msg.type === "openPractice") await this.open("practice", { type: "openExercise", exerciseKey: this.exercise(lesson)!.key });
    else if (msg.type === "openLab") await this.open(lesson.lab);
    else if (msg.type === "focusStep") await this.focusStep(lesson, msg.index);
    else if (msg.type === "pin") {
      const run = this.runs.get(lesson.id);
      if (!run) throw new Error("Run this lesson before pinning a baseline.");
      this.pinned.set(lesson.id, structuredClone(run)); this.notice = "Baseline pinned for this session. Run a changed example, then Compare.";
    }
    await this.refresh();
  }
  private root(): string {
    const uri = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!uri || uri.scheme !== "file") throw new Error("Open a local workspace folder before creating or running lesson files.");
    if (!vscode.workspace.isTrusted) throw new Error("This workspace is in Restricted Mode. Reading lessons is available; execution is disabled.");
    return uri.fsPath;
  }
  /** Traverses each owned component; refuses symbolic links and never overwrites a learner's file. */
  private async exampleUri(lesson: Lesson, create: boolean): Promise<vscode.Uri> {
    if (lesson.code.language === "none") throw new Error("This lesson uses its existing lab or exercise; it has no runnable scratch example.");
    const root = await fs.realpath(this.root());
    let dir = root;
    for (const part of ["notebooks", "learning", lesson.id]) {
      dir = path.join(dir, part);
      let info = await fs.lstat(dir).catch(e => { if (e.code === "ENOENT") return undefined; throw e; });
      if (!info && create) { await fs.mkdir(dir).catch(e => { if (e.code !== "EEXIST") throw e; }); info = await fs.lstat(dir); }
      if (!info || !info.isDirectory() || info.isSymbolicLink()) throw new Error("The lesson directory is missing or is a symbolic link.");
    }
    const file = path.join(dir, lesson.code.language === "sql" ? "example.sql" : "example.py");
    if (create) await fs.writeFile(file, lesson.code.source, { flag: "wx", encoding: "utf8" }).catch(e => { if (e.code !== "EEXIST") throw e; });
    const info = await fs.lstat(file);
    if (!info.isFile() || info.isSymbolicLink() || info.size > MAX_SOURCE) throw new Error("Lesson source must be a regular, bounded file, not a symbolic link.");
    return vscode.Uri.file(file);
  }
  private async source(lesson: Lesson, create = false): Promise<{ uri: vscode.Uri; document: vscode.TextDocument; text: string }> {
    const uri = await this.exampleUri(lesson, create);
    const document = await vscode.workspace.openTextDocument(uri);
    const text = document.getText();
    if (text.length > MAX_SOURCE) throw new Error("Lesson source exceeds the 64 KB limit.");
    return { uri, document, text };
  }
  private async openExample(lesson: Lesson): Promise<void> {
    if (lesson.code.language === "none") { this.notice = "Use Exercise or Open lab for this guided topic. Nothing is executed automatically."; return; }
    const src = await this.source(lesson, true); this.editorUri = src.uri;
    this.panel?.reveal(vscode.ViewColumn.Two, true);
    await vscode.window.showTextDocument(src.document, { viewColumn: vscode.ViewColumn.One, preview: false, preserveFocus: false });
  }
  private async openExercise(lesson: Lesson): Promise<void> {
    this.root();
    await this.open("practice", { type: "openExercise", exerciseKey: this.exercise(lesson)!.key });
    const expected = this.exercise(lesson)!;
    const slug = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const editors = [vscode.window.activeTextEditor, ...(vscode.window.visibleTextEditors ?? [])];
    const editor = editors.find(candidate => {
      if (!candidate || candidate.document.uri.scheme !== "file") return false;
      const file = candidate.document.uri.fsPath;
      const relative = path.relative(this.root(), file);
      return !relative.startsWith("..") && !path.isAbsolute(relative) && /^solution\./.test(path.basename(file))
        && path.basename(path.dirname(file)) === slug(expected.language)
        && path.basename(path.dirname(path.dirname(file))) === slug(expected.id);
    });
    this.editorUri = editor?.document.uri;
    this.panel?.reveal(vscode.ViewColumn.Two, true);
    if (editor) await vscode.window.showTextDocument(editor.document, { viewColumn: vscode.ViewColumn.One, preview: false });
  }
  private async grade(lesson: Lesson, mode: "run" | "submit"): Promise<void> {
    this.root();
    if (this.busy) throw new Error("A Learning operation is already running.");
    this.busy = true; await this.refresh();
    try {
      await this.open("practice", { type: "gradeExercise", exerciseKey: this.exercise(lesson)!.key, mode });
      const result = this.runtime.snapshot().practiceResult;
      this.practiceResult = result?.exerciseKey === this.exercise(lesson)!.key ? structuredClone(result) : undefined;
      this.panel?.reveal(vscode.ViewColumn.Two, true);
    } finally { this.busy = false; }
  }
  private async run(lesson: Lesson, action: "run" | "runSelection" | "explain"): Promise<void> {
    this.root();
    if (this.busy) throw new Error("A Learning operation is already running.");
    if (this.runtime.snapshot().status !== "running") throw new Error("Start the Datapass runtime with its existing Setup/Start controls. Learning never installs or starts it silently.");
    const src = await this.source(lesson);
    let code = src.text;
    if (action === "runSelection") {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.document.uri.toString() !== src.uri.toString() || editor.selection.isEmpty) throw new Error("Select code in this lesson's own native example file first.");
      code = src.document.getText(editor.selection);
    }
    if (!code.trim()) throw new Error("The example is empty.");
    const scope = action === "runSelection" ? "selection" : action === "explain" ? "explain" : "file";
    const run: LearningRun = { id: randomBytes(8).toString("hex"), lesson: lesson.id, language: lesson.code.language,
      scope, sourceHash: digest(src.text), at: new Date().toISOString(), evidence: undefined };
    this.busy = true; this.notice = ""; await this.refresh();
    try {
      if (action === "explain") {
        if (lesson.code.language !== "sql") throw new Error("Run SparkLab or Polars to get its plan. EXPLAIN ANALYZE here is for SQL only.");
        run.evidence = await this.runtime.labs.mosaic.explainQuery(code, "Learning example");
      } else if (lesson.code.language === "sql") run.evidence = await this.runtime.labs.mosaic.runSql(code);
      else if (lesson.code.language === "sparklab" || lesson.code.language === "polars") {
        run.evidence = await this.runtime.labs.sparklab.runSparkLab(code, src.uri.fsPath, "generic_8x8", true, lesson.code.language);
      } else if (lesson.code.language === "python") run.evidence = await this.runtime.labs.mosaic.runPython(code);
      else throw new Error("No runner for this lesson.");
      this.runs.set(lesson.id, structuredClone(run));
      const { evidence: _evidence, ...meta } = run;
      this.history = [meta, ...this.history].slice(0, 20);
      // A late result is stored under its original lesson, never relabelled as the current one.
    } finally { this.busy = false; }
  }
  private async focusStep(lesson: Lesson, index: number): Promise<void> {
    const lines = lesson.visual.steps[index].lines;
    if (!lines) return; // A teaching step is not an invented debugger/source-map event.
    const src = await this.source(lesson);
    if (digest(src.text) !== digest(lesson.code.source)) throw new Error("The example was edited. Authored line highlights are no longer authoritative.");
    const editor = await vscode.window.showTextDocument(src.document, { viewColumn: vscode.ViewColumn.One, preview: false });
    const range = new vscode.Range(lines[0] - 1, 0, lines[1] - 1, 10000);
    editor.selection = new vscode.Selection(range.start, range.end); editor.revealRange(range);
  }
  private async exportProgress(): Promise<void> {
    const target = await vscode.window.showSaveDialog({ filters: { JSON: ["json"] }, saveLabel: "Export reading progress" });
    if (!target) return;
    await vscode.workspace.fs.writeFile(target, new TextEncoder().encode(JSON.stringify({ format: "datapass.learning-progress", version: 1,
      savedAt: new Date().toISOString(), state: this.state, note: "Reading acknowledgements and notes only. Grading remains in the workspace Practice progress." }, null, 2)));
  }
  async refresh(): Promise<void> {
    if (this.disposed) return;
    try {
      await this.ready; const serial = ++this.renderSerial;
      const current = this.state; const lesson = this.catalog.lessons.find(l => l.id === current.lesson)!;
      const progress = await readProgress(); const exercise = this.exercise(lesson)!;
      this.statuses = Object.fromEntries(this.catalog.lessons.map(l => [l.id, lessonStatus(l, current, this.exercise(l), progress.document.practice)]));
      let sourceHash: string | undefined;
      if (lesson.code.language !== "none" && vscode.workspace.isTrusted && vscode.workspace.workspaceFolders?.length) {
        try { sourceHash = digest((await this.source(lesson)).text); } catch { /* No example yet: reading needs no files. */ }
      }
      if (serial !== this.renderSerial || this.disposed) return;
      this.emitter.fire(undefined);
      const record = progress.document.practice?.exercises[exercise.key];
      const result = this.runtime.snapshot().practiceResult;
      const practiceResult = result?.exerciseKey === exercise.key ? result : this.practiceResult?.exerciseKey === exercise.key ? this.practiceResult : undefined;
      await this.panel?.webview.postMessage({ type: "state", catalog: this.catalog, state: current, statuses: this.statuses,
        runtime: { status: this.runtime.snapshot().status, trustedPython: this.runtime.snapshot().trustedPython },
        busy: this.busy, notice: this.notice, sourceHash, hasWorkspace: Boolean(vscode.workspace.workspaceFolders?.length), trusted: vscode.workspace.isTrusted,
        run: this.runs.get(lesson.id), pinned: this.pinned.get(lesson.id), history: this.history,
        exercise: { key: exercise.key, title: exercise.title, prompt: exercise.prompt, language: exercise.language, truth: exercise.truth,
          sections: exercise.sections, dataContext: exercise.dataContext, gradingNote: exercise.gradingNote, sparkPlan: exercise.sparkPlan,
          hints: exercise.hints.slice(0, record?.hintsRevealed ?? 0), hintsRemaining: Math.max(0, exercise.hints.length - (record?.hintsRevealed ?? 0)) }, practiceResult,
        progressError: progress.error });
    } catch (error) {
      // Refresh runs on runtime notifications too; never allow an unhandled rejection.
      this.notice = messageOf(error);
      await this.panel?.webview.postMessage({ type: "error", message: this.notice });
    }
  }
  async getChildren(node?: LearningNode): Promise<LearningNode[]> {
    await this.ready;
    if (!node) return this.catalog.paths.map(p => new LearningNode(p.id, p.title, true));
    if (node.pathOnly) return this.catalog.paths.find(p => p.id === node.id)!.lessons.map(id => {
      const lesson = this.catalog.lessons.find(l => l.id === id)!;
      return new LearningNode(id, lesson.title, false, node.id, this.statuses[id]);
    });
    return [];
  }
  getTreeItem(node: LearningNode): vscode.TreeItem { return node; }
  dispose(): void { this.disposed = true; this.panel?.dispose(); this.emitter.dispose(); this.disposables.forEach(d => d.dispose()); }
}

class LearningNode extends vscode.TreeItem {
  constructor(readonly id: string, label: string, readonly pathOnly: boolean, pathId?: string, status?: string) {
    super(label, pathOnly ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    this.id = pathId ? `${pathId}/${id}` : id;
    this.contextValue = pathOnly ? "learningPath" : "learningLesson";
    this.iconPath = new vscode.ThemeIcon(pathOnly ? "book" : status === "practiced" ? "pass" : status === "read" ? "book-sparkle" : "circle-outline");
    if (!pathOnly) { this.description = status === "practiced" ? "Practice passed" : status === "read" ? "Read (self-reported)" : "";
      this.command = { command: "datapass.learning.select", title: "Open lesson", arguments: [pathId, id] }; }
  }
}
export function registerLearningWorkspace(context: vscode.ExtensionContext, runtime: RuntimeManager, open: OpenWorkbench): vscode.Disposable[] {
  const workspace = new LearningWorkspace(context, runtime, open);
  const tree = vscode.window.createTreeView("datapass.learning.path", { treeDataProvider: workspace, showCollapseAll: true });
  workspace.attachTree(tree);
  const safe = (f: () => Promise<unknown>) => f().catch(e => vscode.window.showErrorMessage(`Mosaic Learning: ${messageOf(e)}`));
  return [workspace, tree,
    vscode.commands.registerCommand("datapass.learning.open", () => safe(() => workspace.show())),
    vscode.commands.registerCommand("datapass.learning.select", (path: string, lesson: string) => safe(() => workspace.select(path, lesson))),
    vscode.commands.registerCommand("datapass.learning.resume", () => safe(() => workspace.show()))
  ];
}
