import * as vscode from "vscode";
import { INFRA_BANNER, LineEditor, infraPrompt, isClear, isExit, toTerminal } from "./platform/infraShell";
import type { RuntimeManager } from "./runtimeManager";

const FOLDER_KEY = "datapass.infraLab.folder";

/**
 * The Infra Lab on the host: one simulated terminal per folder. It is a VS Code Pseudoterminal owned by the extension:
 * no shell and no process is started. Each line the learner types goes to the runtime's simulated shell
 * (POST /api/local/infra/command), which simulates terraform, docker, kubectl and az on the folder's files and its
 * `.infralab/world.json`. The terminal only echoes keystrokes and prints the answers.
 */
export class InfraLabSession implements vscode.Disposable {
  private readonly terminals = new Map<string, vscode.Terminal>();
  private readonly ran = new vscode.EventEmitter<string>();
  /** Fires with the folder after each command, so the Workbench can show the new state of the simulated world. */
  readonly onDidRunCommand = this.ran.event;
  private readonly disposables: vscode.Disposable[] = [this.ran];

  constructor(private readonly runtime: RuntimeManager, private readonly state: vscode.Memento) {
    this.disposables.push(vscode.window.onDidCloseTerminal(terminal => {
      for (const [key, owned] of this.terminals) if (owned === terminal) this.terminals.delete(key);
    }));
  }

  /** The folder (relative to the workspace) whose simulated world the Workbench shows. */
  get folder(): string | undefined {
    return this.state.get<string>(FOLDER_KEY);
  }

  async select(folder: string): Promise<void> {
    await this.state.update(FOLDER_KEY, folder);
  }

  /** Show (or open) the simulated terminal of `folder`, a path relative to the workspace such as missions/<id>. */
  async open(folder: string, name: string): Promise<vscode.Terminal> {
    await this.select(folder);
    const existing = this.terminals.get(folder);
    if (existing && existing.exitStatus === undefined) {
      existing.show(false);
      return existing;
    }
    const terminal = vscode.window.createTerminal({
      name: `${name} · Infra Lab (simulated)`,
      pty: new InfraPseudoterminal(this.runtime, folder, () => this.ran.fire(folder)),
      iconPath: new vscode.ThemeIcon("server-environment")
    });
    this.terminals.set(folder, terminal);
    terminal.show(false);
    return terminal;
  }

  /** Close the simulated terminal of a folder (Start over rebuilds it). Returns whether one was open. */
  closeIn(folder: string): boolean {
    const terminal = this.terminals.get(folder);
    if (!terminal) return false;
    terminal.dispose();
    this.terminals.delete(folder);
    return true;
  }

  dispose(): void {
    for (const terminal of this.terminals.values()) terminal.dispose();
    for (const disposable of this.disposables) disposable.dispose();
  }
}

class InfraPseudoterminal implements vscode.Pseudoterminal {
  private readonly writer = new vscode.EventEmitter<string>();
  private readonly closer = new vscode.EventEmitter<number | void>();
  readonly onDidWrite = this.writer.event;
  readonly onDidClose = this.closer.event;
  private readonly editor = new LineEditor();
  private busy = false;
  /** The command waiting for an answer to its prompt. */
  private pending?: string;
  private queue: string[] = [];

  constructor(private readonly runtime: RuntimeManager, private readonly folder: string, private readonly after: () => void) {}

  open(): void {
    this.writer.fire(INFRA_BANNER + "\r\n" + infraPrompt(this.folder));
  }

  close(): void {
    this.writer.dispose();
    this.closer.dispose();
  }

  handleInput(data: string): void {
    if (this.busy) {
      // Typed while a command runs: kept for when it ends (Ctrl+C only drops what was typed ahead).
      if (data === "\x03") this.queue = [];
      else this.queue.push(data);
      return;
    }
    const result = this.editor.feed(data);
    if (result.echo) this.writer.fire(result.echo);
    if (result.interrupted) {
      this.pending = undefined;
      this.writer.fire(infraPrompt(this.folder));
    }
    if (result.submitted.length) void this.submit(result.submitted);
  }

  private async submit(lines: string[]): Promise<void> {
    this.busy = true;
    try {
      for (const line of lines) await this.run(line);
    } finally {
      this.busy = false;
    }
    const typed = this.queue.join("");
    this.queue = [];
    if (typed) this.handleInput(typed);
  }

  private async run(line: string): Promise<void> {
    if (this.pending !== undefined) {
      const command = this.pending;
      this.pending = undefined;
      await this.send(command, line);
      return;
    }
    if (isClear(line)) {
      this.writer.fire("\x1b[2J\x1b[3J\x1b[H" + infraPrompt(this.folder));
      return;
    }
    if (isExit(line)) {
      this.closer.fire(0);
      return;
    }
    if (!line.trim()) {
      this.writer.fire(infraPrompt(this.folder));
      return;
    }
    await this.send(line);
  }

  private async send(line: string, answer?: string): Promise<void> {
    try {
      const result = await this.runtime.labs.infra.infraCommand(this.folder, line, answer);
      if (result.output) this.writer.fire(toTerminal(result.output.endsWith("\n") ? result.output : result.output + "\n"));
      if (result.prompt) {
        this.pending = line;
        this.writer.fire(toTerminal(result.prompt));
        return;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.writer.fire(toTerminal(`\x1b[31m${message}\x1b[0m\n`));
    }
    this.after();
    this.writer.fire(infraPrompt(this.folder));
  }
}
