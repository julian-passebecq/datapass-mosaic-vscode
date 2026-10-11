import * as vscode from "vscode";
import { createHash, randomBytes } from "node:crypto";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { loadExerciseCatalog } from "../exerciseCatalog";
import type { OpenWorkbench } from "../nativeIntegration";
import { dueReviews, localDay, nextReview, parseReview } from "../platform/practiceReview";
import { readProgress } from "../projectState";
import type { RuntimeManager } from "../runtimeManager";
import type { ExerciseSummary, PracticeResultView } from "../webview/contracts";
import { assembleCatalog, cardKey, LABS, LEVEL_LABELS, lessonProgress, lessonStatus, levelBadges, MODES, nextUnverified, parseMessage,
  restoreState, validateCatalog, validateDeck, validateLinks,
  type ExerciseRef, type FlashcardDeck, type LearningCatalog, type LearningMode, type LearningState, type Lesson } from "../../media/learning/model.mjs";

const STORE = "datapass.learning.workspace.v1";
const MAX_SOURCE = 64_000;
const MAX_JSON = 512_000;
/** New flashcards introduced per review session, after the due ones. */
const NEW_CARDS_PER_SESSION = 10;
const digest = (s: string) => createHash("sha256").update(s.replace(/\r\n?/g, "\n")).digest("hex");
const messageOf = (e: unknown) => e instanceof Error ? e.message : String(e);
const SAFE_ID = /^[a-z][a-z0-9-]{0,99}$/;
export interface LearningRun {
  id: string; lesson: string; language: string; scope: "file" | "selection" | "explain";
  sourceHash: string; at: string; evidence: unknown;
}
interface MissionInfo { pack: string; id: string; lab: string; title: string }
interface Cheatsheet { id: string; title: string }

/** A view orchestrator over the existing runtime/controllers, never another execution engine. */
export class LearningWorkspace implements vscode.Disposable, vscode.TreeDataProvider<LearningNode> {
  private panel: vscode.WebviewPanel | undefined;
  private readonly emitter = new vscode.EventEmitter<LearningNode | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;
  private readonly disposables: vscode.Disposable[] = [];
  private tree: vscode.TreeView<LearningNode> | undefined;
  private catalog!: LearningCatalog;
  private exercises: ExerciseSummary[] = [];
  private decks: FlashcardDeck[] = [];
  private missions = new Map<string, MissionInfo>();
  private cheatsheets = new Map<string, Cheatsheet>();
  private state!: LearningState;
  private readonly ready: Promise<void>;
  private saves: Promise<void> = Promise.resolve();
  private busy = false;
  private notice = "";
  private runs = new Map<string, LearningRun>();
  private pinned = new Map<string, LearningRun>();
  private history: Omit<LearningRun, "evidence">[] = [];
  private statuses: Record<string, string> = {};
  private badges: Record<string, { level: string; text: string; title?: string }[]> = {};
  private dueCount = 0;
  private practiceResult: PracticeResultView | undefined;
  /** A flashcard session (self-rated); session-local, the ratings themselves persist. */
  private reviewing: { deck?: string; newShown: number } | undefined;
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

  private async readJson(uri: vscode.Uri): Promise<unknown> {
    const raw = await vscode.workspace.fs.readFile(uri);
    if (raw.length > MAX_JSON) throw new Error("Learning content file is too large.");
    return JSON.parse(new TextDecoder().decode(raw));
  }
  /** File names in a shipped content folder; a missing folder is empty. */
  private async names(uri: vscode.Uri, extension: string): Promise<string[]> {
    try {
      const entries = await vscode.workspace.fs.readDirectory(uri);
      return entries.filter(([name, type]) => (type & vscode.FileType.File) !== 0 && name.endsWith(extension))
        .map(([name]) => name.slice(0, -extension.length)).filter(id => SAFE_ID.test(id)).sort();
    } catch { return []; }
  }
  private async initialize(): Promise<void> {
    const content = vscode.Uri.joinPath(this.context.extensionUri, "content");
    const folder = vscode.Uri.joinPath(content, "learning");
    const index = await this.readJson(vscode.Uri.joinPath(folder, "catalog.json"));
    const files = new Map<string, unknown>();
    for (const id of Array.isArray((index as { paths?: unknown }).paths) ? (index as { paths: unknown[] }).paths.slice(0, 24) : []) {
      if (typeof id === "string" && SAFE_ID.test(id)) files.set(id, await this.readJson(vscode.Uri.joinPath(folder, "paths", `${id}.json`)));
    }
    const catalog = validateCatalog(assembleCatalog(index, id => files.get(id)));
    this.exercises = await loadExerciseCatalog(this.context.extensionUri);
    // Decks: content/learning/flashcards/<id>.json, each strictly validated against the catalog.
    const decks: FlashcardDeck[] = [];
    for (const id of (await this.names(vscode.Uri.joinPath(folder, "flashcards"), ".json")).slice(0, 32)) {
      decks.push(validateDeck(await this.readJson(vscode.Uri.joinPath(folder, "flashcards", `${id}.json`)), id, catalog));
    }
    // Missions: the shipped packs only, with their lab and each mission's own title.
    const missions = new Map<string, MissionInfo>();
    for (const [pack, type] of await vscode.workspace.fs.readDirectory(vscode.Uri.joinPath(content, "missions")).then(x => x, () => [] as [string, vscode.FileType][])) {
      if ((type & vscode.FileType.Directory) === 0 || !SAFE_ID.test(pack)) continue;
      const manifest = await this.readJson(vscode.Uri.joinPath(content, "missions", pack, "pack.json")).catch(() => undefined) as { lab?: unknown; missions?: unknown } | undefined;
      if (!manifest || typeof manifest.lab !== "string" || !LABS.includes(manifest.lab) || !Array.isArray(manifest.missions)) continue;
      for (const id of manifest.missions) {
        if (typeof id !== "string" || !SAFE_ID.test(id)) continue;
        const mission = await this.readJson(vscode.Uri.joinPath(content, "missions", pack, id, "mission.json")).catch(() => undefined) as { title?: unknown } | undefined;
        missions.set(`${pack}/${id}`, { pack, id, lab: manifest.lab, title: typeof mission?.title === "string" ? mission.title.slice(0, 160) : id });
      }
    }
    // Cheatsheets: Markdown files in content/reference/ named by id; the title is the first heading.
    const cheatsheets = new Map<string, Cheatsheet>();
    for (const id of (await this.names(vscode.Uri.joinPath(content, "reference"), ".md")).slice(0, 200)) {
      const raw = new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(content, "reference", `${id}.md`)));
      const heading = /^#\s+(.+)$/m.exec(raw.slice(0, 4000))?.[1]?.trim();
      cheatsheets.set(id, { id, title: (heading || id).slice(0, 140) });
    }
    validateLinks(catalog, {
      exercises: new Set(this.exercises.map(e => `${e.id}/${e.language}`)), missions: new Set(missions.keys()),
      cheatsheets: new Set(cheatsheets.keys()), decks: new Set(decks.map(d => d.id))
    });
    this.catalog = catalog; this.decks = decks; this.missions = missions; this.cheatsheets = cheatsheets;
    this.state = restoreState(this.catalog, this.context.workspaceState.get(STORE), { decks, parseReview });
  }
  private resolve = (ref: ExerciseRef): ExerciseSummary | undefined => this.exercises.find(e => e.id === ref.id && e.language === ref.language);
  private exercise(lesson: Lesson): ExerciseSummary | undefined { return lesson.exercise ? this.resolve(lesson.exercise) : undefined; }
  private requireExercise(lesson: Lesson): ExerciseSummary {
    const exercise = this.exercise(lesson);
    if (!exercise) throw new Error("This lesson has no single linked exercise. Use its extra practice or its missions.");
    return exercise;
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
    this.notice = ""; this.editorUri = undefined; this.reviewing = undefined;
    await this.show();
  }
  /** Opens a self-rated flashcard session: due cards first, then a few new ones. Separate from Practice Review. */
  async review(deck?: string): Promise<void> {
    await this.ready;
    if (deck !== undefined && !this.decks.some(d => d.id === deck)) throw new Error("Unknown flashcard deck.");
    if (!this.decks.length) throw new Error("No flashcard deck is installed.");
    this.reviewing = { deck, newShown: 0 };
    await this.show();
  }
  private reviewQueue(): string[] {
    if (!this.reviewing) return [];
    const keys = this.decks.filter(d => !this.reviewing!.deck || d.id === this.reviewing!.deck).flatMap(d => d.cards.map(c => cardKey(d.id, c.id)));
    const due = dueReviews(keys, this.state.flashcards, localDay(new Date())).map(d => d.key);
    const fresh = keys.filter(k => !this.state.flashcards[k]?.review).slice(0, Math.max(0, NEW_CARDS_PER_SESSION - this.reviewing.newShown));
    return [...due, ...fresh];
  }
  private async rate(deck: string, card: string, rating: "knew" | "missed"): Promise<void> {
    const key = cardKey(deck, card);
    if (!this.reviewing || !this.reviewQueue().includes(key)) throw new Error("This flashcard is not in the current review.");
    const isNew = !this.state.flashcards[key]?.review;
    const now = new Date().toISOString();
    await this.save(s => {
      const record = s.flashcards[key] ?? { attempts: 0 };
      // The Leitner intervals of Practice Review, applied to a self-rating: "knew it" climbs, "missed it" restarts.
      const review = nextReview(record, "submit", rating === "knew" ? "passed" : "failed", now);
      return { ...s, flashcards: { ...s.flashcards, [key]: { attempts: record.attempts + 1, ...(review ? { review } : {}), last: { at: now, rating } } } };
    });
    if (isNew) this.reviewing.newShown++;
  }
  /** Incoming targets must refer to the shipped catalog. No webview-supplied filename, SQL or command is accepted. */
  async handle(raw: unknown): Promise<void> {
    await this.ready;
    const msg = parseMessage(raw, this.catalog, { decks: this.decks, cheatsheets: [...this.cheatsheets.keys()] });
    if (!msg) throw new Error("Unsupported learning action.");
    if (msg.type === "ready") { await this.refresh(); return; }
    if (msg.type === "select") { await this.select(msg.path, msg.lesson); return; }
    if (msg.type === "rail") { await this.save(s => ({ ...s, railHidden: msg.hidden })); await this.refresh(); return; }
    if (msg.type === "layout") { await this.save(s => ({ ...s, layout: msg.layout })); await this.refresh(); return; }
    if (msg.type === "openRuntime") { await this.open("home"); return; }
    if (msg.type === "nativePath") { await vscode.commands.executeCommand("datapass.learning.path.focus"); return; }
    if (msg.type === "export") { await this.exportProgress(); return; }
    if (msg.type === "review") { await this.review(msg.deck); return; }
    if (msg.type === "reviewClose") { this.reviewing = undefined; await this.refresh(); return; }
    if (msg.type === "rate") { await this.rate(msg.deck, msg.card, msg.rating); await this.refresh(); return; }
    if (msg.type === "openCheatsheet") { await this.openCheatsheet(msg.id); return; }
    if (!("lesson" in msg)) return;
    // An old hidden webview must not run actions against a newly selected lesson.
    if (msg.lesson !== this.state.lesson) throw new Error("The lesson changed. Use the controls of the current lesson.");
    const lesson = this.catalog.lessons.find(l => l.id === msg.lesson)!;
    if (msg.type === "mode") {
      this.reviewing = undefined;
      await this.save(s => ({ ...s, mode: msg.mode }));
      if (msg.mode === "try") await this.openExample(lesson);
      if (msg.mode === "exercise" && lesson.exercise) await this.openExercise(lesson);
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
      await this.open("practice", { type: "revealHint", exerciseKey: this.requireExercise(lesson).key });
      this.panel?.reveal(vscode.ViewColumn.Two, true);
    }
    else if (msg.type === "openPractice") await this.open("practice", { type: "openExercise", exerciseKey: this.requireExercise(lesson).key });
    else if (msg.type === "openCheck" || msg.type === "openPracticeItem") {
      const ref = (msg.type === "openCheck" ? lesson.checks : lesson.practice)![msg.index];
      this.root();
      await this.open("practice", { type: "openExercise", exerciseKey: this.resolve(ref)!.key });
    }
    else if (msg.type === "openMission") {
      const ref = lesson.missions![msg.index]; const mission = this.missions.get(`${ref.pack}/${ref.id}`)!;
      // Opens the mission's lab; the learner starts the mission there. Nothing is created or run from here.
      await this.open(mission.lab as Lesson["lab"]);
      this.notice = `Open "${mission.title}" in the ${mission.lab} lab. Missions are checked there, by that lab's own checker.`;
    }
    else if (msg.type === "cheatsheet") await this.openCheatsheet(lesson.cheatsheet!);
    else if (msg.type === "openDeck") { await this.review(lesson.deck!); return; }
    else if (msg.type === "openLab") await this.open(lesson.lab);
    else if (msg.type === "focusStep") await this.focusStep(lesson, msg.index);
    else if (msg.type === "pin") {
      const run = this.runs.get(lesson.id);
      if (!run) throw new Error("Run this lesson before pinning a baseline.");
      this.pinned.set(lesson.id, structuredClone(run)); this.notice = "Baseline pinned for this session. Run a changed example, then Compare.";
    }
    await this.refresh();
  }
  /** A cheatsheet is a reference id, resolved inside content/reference/ only and opened as a native Markdown preview. */
  private async openCheatsheet(id: string): Promise<void> {
    if (!this.cheatsheets.has(id)) throw new Error("Unknown cheatsheet.");
    await vscode.commands.executeCommand("markdown.showPreview", vscode.Uri.joinPath(this.context.extensionUri, "content", "reference", `${id}.md`));
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
    // Keep a native editor in group One before moving the Learning tab. Moving the only tab first
    // closes its empty group, renumbers group Two to One and would hide the course on the next open.
    await vscode.window.showTextDocument(src.document, { viewColumn: vscode.ViewColumn.One, preview: false, preserveFocus: false });
    this.panel?.reveal(vscode.ViewColumn.Two, true);
  }
  private async openExercise(lesson: Lesson): Promise<void> {
    this.root();
    const expected = this.requireExercise(lesson);
    await this.open("practice", { type: "openExercise", exerciseKey: expected.key });
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
    if (editor) await vscode.window.showTextDocument(editor.document, { viewColumn: vscode.ViewColumn.One, preview: false });
    this.panel?.reveal(vscode.ViewColumn.Two, true);
  }
  private async grade(lesson: Lesson, mode: "run" | "submit"): Promise<void> {
    this.root();
    const exercise = this.requireExercise(lesson);
    if (this.busy) throw new Error("A Learning operation is already running.");
    this.busy = true; await this.refresh();
    try {
      await this.open("practice", { type: "gradeExercise", exerciseKey: exercise.key, mode });
      const result = this.runtime.snapshot().practiceResult;
      this.practiceResult = result?.exerciseKey === exercise.key ? structuredClone(result) : undefined;
      this.panel?.reveal(vscode.ViewColumn.Two, true);
    } finally { this.busy = false; }
  }
  private async run(lesson: Lesson, action: "run" | "runSelection" | "explain"): Promise<void> {
    this.root();
    if (this.busy) throw new Error("A Learning operation is already running.");
    if (this.runtime.snapshot().status !== "running") throw new Error("Start the Datapass runtime with its existing Setup/Start controls. Learning never installs or starts it silently.");
    this.busy = true; this.notice = ""; await this.refresh();
    try {
      const src = await this.source(lesson);
      let code = src.text;
      if (action === "runSelection") {
        const editor = [vscode.window.activeTextEditor, ...(vscode.window.visibleTextEditors ?? [])]
          .find(candidate => candidate?.document.uri.toString() === src.uri.toString());
        if (!editor || editor.selection.isEmpty) throw new Error("Select code in this lesson's own native example file first.");
        code = src.document.getText(editor.selection);
      }
      if (!code.trim()) throw new Error("The example is empty.");
      const scope = action === "runSelection" ? "selection" : action === "explain" ? "explain" : "file";
      const run: LearningRun = { id: randomBytes(8).toString("hex"), lesson: lesson.id, language: lesson.code.language,
        scope, sourceHash: digest(src.text), at: new Date().toISOString(), evidence: undefined };
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
      // "Ran locally, not graded": a whole-file Run of this lesson version that returned without an error.
      const evidence = run.evidence as { status?: unknown; error?: unknown } | undefined;
      if (scope === "file" && evidence && typeof evidence === "object" && evidence.status !== "error" && !evidence.error) {
        await this.save(s => ({ ...s, executed: { ...s.executed, [lesson.id]: { version: lesson.version, at: run.at, sourceHash: run.sourceHash, language: lesson.code.language } } }));
      }
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
      savedAt: new Date().toISOString(), state: this.state,
      note: "Reading acknowledgements, notes, local run records (not graded) and self-rated flashcards only. Grading remains in the workspace Practice progress." }, null, 2)));
  }
  /** The view of one lesson's links, with titles and the per-item level each one supports. */
  private links(lesson: Lesson, progress: ReturnType<typeof lessonProgress>) {
    const deck = lesson.deck ? this.decks.find(d => d.id === lesson.deck) : undefined;
    return {
      checks: progress.checks.map(c => ({ ...c, title: this.resolve(c)?.title ?? c.id })),
      practice: progress.practice.map(p => ({ ...p, title: this.resolve(p)?.title ?? p.id })),
      missions: (lesson.missions ?? []).map(m => this.missions.get(`${m.pack}/${m.id}`)!),
      cheatsheet: lesson.cheatsheet ? this.cheatsheets.get(lesson.cheatsheet) : undefined,
      deck: deck ? { id: deck.id, title: deck.title, count: deck.cards.length } : undefined
    };
  }
  async refresh(): Promise<void> {
    if (this.disposed) return;
    try {
      await this.ready; const serial = ++this.renderSerial;
      const current = this.state; const lesson = this.catalog.lessons.find(l => l.id === current.lesson)!;
      const progress = await readProgress(); const exercise = this.exercise(lesson);
      const practice = progress.document.practice;
      const levels = Object.fromEntries(this.catalog.lessons.map(l => [l.id, lessonProgress(l, current, this.resolve, practice)]));
      this.statuses = Object.fromEntries(this.catalog.lessons.map(l => [l.id, lessonStatus(l, current, this.exercise(l), practice)]));
      this.badges = Object.fromEntries(this.catalog.lessons.map(l => [l.id, levelBadges(l, levels[l.id])]));
      const allCards = this.decks.flatMap(d => d.cards.map(c => cardKey(d.id, c.id)));
      this.dueCount = dueReviews(allCards, current.flashcards, localDay(new Date())).length;
      let sourceHash: string | undefined;
      if (lesson.code.language !== "none" && vscode.workspace.isTrusted && vscode.workspace.workspaceFolders?.length) {
        try { sourceHash = digest((await this.source(lesson)).text); } catch { /* No example yet: reading needs no files. */ }
      }
      if (serial !== this.renderSerial || this.disposed) return;
      this.emitter.fire(undefined);
      const record = exercise ? practice?.exercises[exercise.key] : undefined;
      const result = this.runtime.snapshot().practiceResult;
      const practiceResult = !exercise ? undefined : result?.exerciseKey === exercise.key ? result : this.practiceResult?.exerciseKey === exercise.key ? this.practiceResult : undefined;
      const next = nextUnverified(this.catalog, current, this.resolve, practice);
      const queue = this.reviewQueue();
      const head = queue[0]?.split("/");
      const headDeck = head ? this.decks.find(d => d.id === head[0]) : undefined;
      const headCard = headDeck?.cards.find(c => c.id === head![1]);
      await this.panel?.webview.postMessage({ type: "state", catalog: this.catalog, state: current, statuses: this.statuses,
        levels, badges: this.badges, labels: LEVEL_LABELS, links: this.links(lesson, levels[lesson.id]),
        decks: this.decks.map(d => ({ id: d.id, title: d.title, path: d.path, count: d.cards.length })),
        cheatsheets: [...this.cheatsheets.values()],
        cards: this.decks.flatMap(d => d.cards.map(c => ({ deck: d.id, id: c.id, front: c.front }))),
        resume: { lesson: current.lesson, path: current.path, mode: current.mode, dueCards: this.dueCount,
          next: next ? { ...next, lessonTitle: this.catalog.lessons.find(l => l.id === next.lesson)!.title, title: this.resolve(next)?.title ?? next.id } : undefined },
        review: this.reviewing ? { active: true, deck: this.reviewing.deck, remaining: queue.length,
          card: headDeck && headCard ? { deck: headDeck.id, deckTitle: headDeck.title, id: headCard.id, front: headCard.front, back: headCard.back, tags: headCard.tags,
            lesson: headCard.lesson, box: current.flashcards[queue[0]]?.review?.box, isNew: !current.flashcards[queue[0]]?.review } : undefined } : { active: false },
        runtime: { status: this.runtime.snapshot().status, trustedPython: this.runtime.snapshot().trustedPython },
        busy: this.busy, notice: this.notice, sourceHash, hasWorkspace: Boolean(vscode.workspace.workspaceFolders?.length), trusted: vscode.workspace.isTrusted,
        run: this.runs.get(lesson.id), pinned: this.pinned.get(lesson.id), history: this.history,
        exercise: exercise ? { key: exercise.key, title: exercise.title, prompt: exercise.prompt, language: exercise.language, truth: exercise.truth,
          sections: exercise.sections, dataContext: exercise.dataContext, gradingNote: exercise.gradingNote, sparkPlan: exercise.sparkPlan,
          hints: exercise.hints.slice(0, record?.hintsRevealed ?? 0), hintsRemaining: Math.max(0, exercise.hints.length - (record?.hintsRevealed ?? 0)) } : undefined, practiceResult,
        progressError: progress.error });
    } catch (error) {
      // Refresh runs on runtime notifications too; never allow an unhandled rejection.
      this.notice = messageOf(error);
      await this.panel?.webview.postMessage({ type: "error", message: this.notice });
    }
  }
  async getChildren(node?: LearningNode): Promise<LearningNode[]> {
    await this.ready;
    if (!node) return [
      ...this.catalog.paths.map(p => new LearningNode(p.id, p.title, "path")),
      ...(this.decks.length ? [new LearningNode("flashcards", "Flashcards (self-rated)", "review", undefined, this.dueCount ? `${this.dueCount} due` : "none due")] : [])
    ];
    if (node.kind === "path") return this.catalog.paths.find(p => p.id === node.id)!.lessons.map(id => {
      const lesson = this.catalog.lessons.find(l => l.id === id)!;
      return new LearningNode(id, lesson.title, "lesson", node.id, undefined, this.badges[id] ?? []);
    });
    return [];
  }
  getTreeItem(node: LearningNode): vscode.TreeItem { return node; }
  dispose(): void { this.disposed = true; this.panel?.dispose(); this.emitter.dispose(); this.disposables.forEach(d => d.dispose()); }
}

class LearningNode extends vscode.TreeItem {
  constructor(readonly id: string, label: string, readonly kind: "path" | "lesson" | "review", pathId?: string, description?: string,
    badges: { level: string; text: string; title?: string }[] = []) {
    super(label, kind === "path" ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    this.id = pathId ? `${pathId}/${id}` : id;
    this.contextValue = kind === "path" ? "learningPath" : kind === "review" ? "learningReview" : "learningLesson";
    const verified = badges.some(b => b.level === "verified"), read = badges.some(b => b.level === "read");
    this.iconPath = new vscode.ThemeIcon(kind === "path" ? "book" : kind === "review" ? "layers" : verified ? "pass" : read ? "book" : "circle-outline");
    if (kind === "review") {
      this.description = description;
      this.command = { command: "datapass.learning.review", title: "Review flashcards" };
    }
    if (kind === "lesson") {
      // The four levels stay separate: each one is its own segment, never folded into one score.
      this.description = badges.map(b => b.text).join(" · ");
      this.tooltip = badges.length ? badges.map(b => b.title ? `${b.text} (${b.title})` : b.text).join("\n") : "Not started";
      this.command = { command: "datapass.learning.select", title: "Open lesson", arguments: [pathId, id] };
    }
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
    vscode.commands.registerCommand("datapass.learning.resume", () => safe(() => workspace.show())),
    vscode.commands.registerCommand("datapass.learning.review", (deck?: unknown) => safe(() => workspace.review(typeof deck === "string" ? deck : undefined)))
  ];
}
