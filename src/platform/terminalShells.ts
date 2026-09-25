/**
 * Terminal Lab shells: where bash and PowerShell live on this machine and how a terminal starts them. Pure (no
 * vscode import) for scripts/terminal_lab_smoke.mjs; the host checks which candidate exists.
 *
 * The learner chooses the shell. Datapass only opens a VS Code terminal with it in the mission folder: every command
 * is typed and run by the learner.
 */
import path from "node:path";

export type ShellId = "bash" | "powershell";

export interface ShellView {
  id: ShellId;
  label: string;
  /** The executable found, or undefined when none is installed. */
  path?: string;
  /** Why it is missing, or which flavour was found (Git Bash, pwsh 7, Windows PowerShell 5.1). */
  note: string;
}

export interface GitView {
  version?: string;
  userName?: string;
  userEmail?: string;
}

export const SHELL_LABEL: Record<ShellId, string> = { bash: "bash", powershell: "PowerShell" };

/**
 * Where bash may be, in order. On Windows it is Git Bash (next to git.exe, or in the usual install folders); never
 * C:\Windows\System32\bash.exe, which starts WSL and would see another file system.
 */
export function bashCandidates(platform: NodeJS.Platform, env: Record<string, string | undefined>, gitPath?: string, configured?: string): string[] {
  const out: string[] = [];
  if (configured?.trim()) out.push(configured.trim());
  if (platform === "win32") {
    const win = path.win32;
    if (gitPath) {
      // ...\Git\cmd\git.exe or ...\Git\bin\git.exe or ...\Git\mingw64\bin\git.exe
      const gitDir = win.dirname(gitPath);
      out.push(win.join(gitDir, "..", "bin", "bash.exe"), win.join(gitDir, "..", "..", "bin", "bash.exe"), win.join(gitDir, "bash.exe"));
    }
    for (const base of [env.ProgramFiles, env["ProgramFiles(x86)"], env.LOCALAPPDATA && win.join(env.LOCALAPPDATA, "Programs")]) {
      if (base) out.push(win.join(base, "Git", "bin", "bash.exe"));
    }
    return [...new Set(out.map(candidate => win.normalize(candidate)))].filter(candidate => !/\\system32\\bash\.exe$/i.test(candidate));
  }
  out.push("/bin/bash", "/usr/bin/bash", "/usr/local/bin/bash", "/opt/homebrew/bin/bash");
  return [...new Set(out)];
}

/** PowerShell 7 (pwsh) first, then Windows PowerShell 5.1 on Windows. */
export function powershellCandidates(platform: NodeJS.Platform, env: Record<string, string | undefined>, pwshOnPath?: string): string[] {
  const out: string[] = [];
  if (pwshOnPath) out.push(pwshOnPath);
  if (platform === "win32") {
    const win = path.win32;
    for (const base of [env.ProgramFiles, env["ProgramW6432"]]) if (base) out.push(win.join(base, "PowerShell", "7", "pwsh.exe"));
    out.push(win.join(env.SystemRoot ?? "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe"));
  } else {
    out.push("/usr/bin/pwsh", "/usr/local/bin/pwsh", "/opt/homebrew/bin/pwsh", "/snap/bin/pwsh");
  }
  return [...new Set(out)];
}

export function shellNote(id: ShellId, found: string | undefined, platform: NodeJS.Platform): string {
  if (!found) {
    return id === "bash"
      ? platform === "win32" ? "Not found: install Git for Windows (it brings Git Bash), or set datapass.terminalLab.bashPath." : "Not found on this machine."
      : "Not found: install PowerShell 7 (pwsh).";
  }
  if (id === "bash") return platform === "win32" ? "Git Bash" : "bash";
  return /powershell\.exe$/i.test(found) ? "Windows PowerShell 5.1" : "PowerShell 7 (pwsh)";
}

/** How the terminal starts the shell. Git Bash as a login shell that stays in the mission folder. */
export function terminalLaunch(id: ShellId, shellPath: string, platform: NodeJS.Platform): { shellPath: string; shellArgs: string[]; env: Record<string, string> } {
  if (id === "bash") {
    // CHERE_INVOKING keeps Git Bash's login profile from changing to the home folder.
    return { shellPath, shellArgs: ["--login", "-i"], env: platform === "win32" ? { CHERE_INVOKING: "1" } : {} };
  }
  return { shellPath, shellArgs: ["-NoLogo"], env: {} };
}

export function toShellId(value: unknown): ShellId | undefined {
  return value === "bash" || value === "powershell" ? value : undefined;
}

/** The shell to offer first: the learner's choice when it is installed, otherwise the first one found. */
export function preferredShell(shells: readonly ShellView[], chosen: ShellId | undefined): ShellId | undefined {
  if (chosen && shells.find(shell => shell.id === chosen)?.path) return chosen;
  return shells.find(shell => shell.path)?.id;
}
