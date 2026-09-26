/**
 * The Infra Lab terminal's line editing, without VS Code: what the Pseudoterminal echoes for each keystroke, and the
 * lines the learner submits. The terminal spawns no process; each submitted line goes to the runtime's simulated
 * shell (runtime/infralab/shell.py).
 */

export const INFRA_BANNER = [
  "\x1b[1mDatapass Infra Lab\x1b[0m \x1b[2m· simulated terminal\x1b[0m",
  "terraform, docker, kubectl and az are simulated here: nothing is provisioned, built or deployed, and no",
  "program is started on your machine. Edit your files in VS Code; type \x1b[1mhelp\x1b[0m for the commands.",
  ""
].join("\r\n");

const MAX_LINE = 2000;
const MAX_HISTORY = 100;

export interface EditorResult {
  /** Text to write back to the terminal (echo, erasing, recalled history). */
  echo: string;
  /** Lines submitted with Enter, in order. */
  submitted: string[];
  /** Ctrl+C was pressed: the current line is dropped. */
  interrupted: boolean;
}

/** A single-line editor: printable characters, Backspace, Enter, Ctrl+C, Ctrl+U, and Up / Down through history. */
export class LineEditor {
  private line = "";
  private readonly history: string[] = [];
  private recall = -1;

  get current(): string {
    return this.line;
  }

  feed(data: string): EditorResult {
    const out: EditorResult = { echo: "", submitted: [], interrupted: false };
    let i = 0;
    while (i < data.length) {
      const rest = data.slice(i);
      if (rest.startsWith("\x1b[A") || rest.startsWith("\x1b[B")) {
        this.move(rest[2] === "A" ? 1 : -1, out);
        i += 3;
        continue;
      }
      if (rest.startsWith("\x1b[")) {
        // Other escape sequences (arrows left/right, Home, End…) are not supported: skip them whole.
        const match = /^\x1b\[[0-9;]*[A-Za-z~]/.exec(rest);
        i += match ? match[0].length : 2;
        continue;
      }
      const ch = data[i++];
      if (ch === "\r" || ch === "\n") {
        if (ch === "\n" && data[i - 2] === "\r") continue;
        out.echo += "\r\n";
        out.submitted.push(this.line);
        if (this.line.trim() && this.history[0] !== this.line) {
          this.history.unshift(this.line);
          this.history.length = Math.min(this.history.length, MAX_HISTORY);
        }
        this.line = "";
        this.recall = -1;
      } else if (ch === "\x7f" || ch === "\b") {
        if (this.line.length) {
          this.line = this.line.slice(0, -1);
          out.echo += "\b \b";
        }
      } else if (ch === "\x03") {
        out.echo += "^C\r\n";
        out.interrupted = true;
        this.line = "";
        this.recall = -1;
      } else if (ch === "\x15") {
        out.echo += "\b \b".repeat(this.line.length);
        this.line = "";
      } else if (ch === "\t") {
        continue;
      } else if (ch >= " " && this.line.length < MAX_LINE) {
        this.line += ch;
        out.echo += ch;
      }
    }
    return out;
  }

  private move(step: number, out: EditorResult): void {
    const next = this.recall + step;
    if (next < -1 || next >= this.history.length) return;
    this.recall = next;
    out.echo += "\b \b".repeat(this.line.length);
    this.line = next === -1 ? "" : this.history[next];
    out.echo += this.line;
  }
}

/** The prompt: the folder the shell works in, relative to the workspace. */
export function infraPrompt(folder: string): string {
  return `\x1b[36minfra\x1b[0m \x1b[2m${folder}\x1b[0m $ `;
}

/** Terminal output needs CRLF line ends. */
export function toTerminal(text: string): string {
  return text.replace(/\r?\n/g, "\r\n");
}

/** `clear` is handled in the terminal itself (it only clears the screen). */
export function isClear(line: string): boolean {
  return /^\s*(clear|cls)\s*$/i.test(line);
}

export function isExit(line: string): boolean {
  return /^\s*(exit|logout)\s*$/i.test(line);
}
