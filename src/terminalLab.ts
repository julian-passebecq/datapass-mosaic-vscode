import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import * as vscode from "vscode";
import {
  SHELL_LABEL,
  bashCandidates,
  powershellCandidates,
  shellNote,
  terminalLaunch,
  toShellId,
  type GitView,
  type ShellId,
  type ShellView
} from "./platform/terminalShells";

const SHELL_KEY = "datapass.terminalLab.shell";

/**
 * The Terminal Lab on the host: which shells and Git this machine has, the learner's choice of shell, and the VS Code
 * terminals opened in a mission folder. Datapass never types or runs a command in them: the learner does.
 */
export class TerminalLabSession implements vscode.Disposable {
  private readonly terminals = new Map<string, vscode.Terminal>();
  private detected?: Promise<{ shells: ShellView[]; git: GitView }>;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(private readonly state: vscode.Memento) {
    this.disposables.push(
      vscode.window.onDidCloseTerminal(terminal => {
        for (const [key, owned] of this.terminals) if (owned === terminal) this.terminals.delete(key);
      }),
      vscode.workspace.onDidChangeConfiguration(event => {
        if (event.affectsConfiguration("datapass.terminalLab")) this.detected = undefined;
      })
    );
  }

  /** The shells and Git found on this machine (looked up once; Refresh looks again). */
  detect(force = false): Promise<{ shells: ShellView[]; git: GitView }> {
    if (force || !this.detected) this.detected = detectEnvironment();
    return this.detected;
  }

  get chosen(): ShellId | undefined {
    return toShellId(this.state.get(SHELL_KEY));
  }

  async choose(shell: ShellId): Promise<void> {
    await this.state.update(SHELL_KEY, shell);
  }

  /** Show (or open) the terminal of `folder` for `shell`. */
  async open(folder: vscode.Uri, shell: ShellId, name: string): Promise<vscode.Terminal> {
    const key = `${folder.fsPath}|${shell}`;
    const existing = this.terminals.get(key);
    if (existing && existing.exitStatus === undefined) {
      existing.show(false);
      return existing;
    }
    const found = (await this.detect()).shells.find(item => item.id === shell);
    if (!found?.path) throw new Error(`${SHELL_LABEL[shell]} is not installed here. ${found?.note ?? ""}`.trim());
    const launch = terminalLaunch(shell, found.path, process.platform);
    const terminal = vscode.window.createTerminal({
      name: `${name} · ${SHELL_LABEL[shell]}`,
      cwd: folder,
      shellPath: launch.shellPath,
      shellArgs: launch.shellArgs,
      env: launch.env,
      iconPath: new vscode.ThemeIcon(shell === "bash" ? "terminal-bash" : "terminal-powershell")
    });
    this.terminals.set(key, terminal);
    terminal.show(false);
    return terminal;
  }

  /** Close the lab's terminals in `folder` (Start over moves the folder, and a shell inside it would hold it). */
  closeIn(folder: vscode.Uri): boolean {
    const prefix = `${folder.fsPath}|`;
    let closed = false;
    for (const [key, terminal] of [...this.terminals]) {
      if (key.startsWith(prefix)) {
        terminal.dispose();
        this.terminals.delete(key);
        closed = true;
      }
    }
    return closed;
  }

  /**
   * Before the runtime moves `folder` aside (Start over): close the lab's terminals in it and Source Control's watch
   * on its repository, which on Windows keep a folder from being moved. Returns what to call once it is rebuilt.
   */
  async release(folder: vscode.Uri): Promise<() => Promise<void>> {
    const hadTerminal = this.closeIn(folder);
    const reopen = await closeGitRepository(folder);
    // A shell takes a moment to exit once its terminal is closed.
    if (hadTerminal || reopen) await new Promise(resolve => setTimeout(resolve, 1000));
    return async () => {
      if (reopen) await reopenGitRepository(folder);
    };
  }

  dispose(): void {
    for (const disposable of this.disposables) disposable.dispose();
  }
}

interface GitApi {
  repositories: { rootUri: vscode.Uri }[];
}

/**
 * VS Code's Git extension opens the mission's repository (it opens every new .git in the workspace) and watches its
 * .git folder; on Windows that watch keeps the folder from being moved. Close it there before Start over.
 * Returns whether it was open, so the caller can reopen it on the rebuilt folder.
 */
export async function closeGitRepository(folder: vscode.Uri): Promise<boolean> {
  const extension = vscode.extensions.getExtension<{ getAPI(version: 1): GitApi }>("vscode.git");
  if (!extension?.isActive) return false;
  const same = (a: string, b: string) => process.platform === "win32" ? a.toLowerCase() === b.toLowerCase() : a === b;
  const open = extension.exports.getAPI(1).repositories.some(repository => same(repository.rootUri.fsPath, folder.fsPath));
  if (!open) return false;
  try {
    await vscode.commands.executeCommand("git.close", folder);
  } catch {
    return false;
  }
  return true;
}

export async function reopenGitRepository(folder: vscode.Uri): Promise<void> {
  try {
    await vscode.commands.executeCommand("git.openRepository", folder.fsPath);
  } catch {
    // Source Control finds it again on its own when the folder changes.
  }
}

async function detectEnvironment(): Promise<{ shells: ShellView[]; git: GitView }> {
  const platform = process.platform;
  const env = process.env as Record<string, string | undefined>;
  const configured = vscode.workspace.getConfiguration("datapass.terminalLab").get<string>("bashPath");
  const gitPath = onPath("git", env);
  const bash = bashCandidates(platform, env, gitPath, configured).find(candidate => existsSync(candidate))
    ?? (platform === "win32" ? undefined : onPath("bash", env));
  const powershell = powershellCandidates(platform, env, onPath("pwsh", env)).find(candidate => existsSync(candidate));
  const shells: ShellView[] = [
    { id: "bash", label: SHELL_LABEL.bash, path: bash, note: shellNote("bash", bash, platform) },
    { id: "powershell", label: SHELL_LABEL.powershell, path: powershell, note: shellNote("powershell", powershell, platform) }
  ];
  const git: GitView = {};
  if (gitPath) {
    // Read-only questions to the learner's own Git: its version and the identity their commits will carry.
    git.version = (await run(gitPath, ["--version"]))?.replace(/^git version\s*/, "");
    git.userName = await run(gitPath, ["config", "--global", "user.name"]);
    git.userEmail = await run(gitPath, ["config", "--global", "user.email"]);
  }
  return { shells, git };
}

function run(file: string, args: string[]): Promise<string | undefined> {
  return new Promise(resolve => {
    execFile(file, args, { timeout: 5000, windowsHide: true }, (error, stdout) => {
      resolve(error ? undefined : stdout.trim() || undefined);
    });
  });
}

/** An executable on PATH (with PATHEXT on Windows), or undefined. */
function onPath(name: string, env: Record<string, string | undefined>): string | undefined {
  const extensions = process.platform === "win32" ? (env.PATHEXT ?? ".EXE;.CMD;.BAT").split(";").filter(Boolean) : [""];
  for (const dir of (env.PATH ?? env.Path ?? "").split(path.delimiter)) {
    if (!dir) continue;
    for (const extension of extensions) {
      const candidate = path.join(dir, name + extension.toLowerCase());
      if (existsSync(candidate)) return candidate;
    }
  }
  return undefined;
}
