import { spawn, type ChildProcess } from "node:child_process";
import * as http from "node:http";
import * as path from "node:path";
import * as vscode from "vscode";
import type { RuntimeViewState } from "./webview/contracts";

const HOST = "127.0.0.1";
const PORT = 8765;

export class RuntimeManager implements vscode.Disposable {
  private child?: ChildProcess;
  private state: RuntimeViewState = { status: "stopped" };
  private readonly output = vscode.window.createOutputChannel("Datapass Runtime");
  private readonly changed = new vscode.EventEmitter<RuntimeViewState>();

  readonly onDidChange = this.changed.event;

  constructor(private readonly extensionUri: vscode.Uri) {}

  snapshot(): RuntimeViewState {
    return { ...this.state };
  }

  async start(pythonCommand = "python"): Promise<void> {
    if (this.state.status === "running" || this.state.status === "starting") return;

    const runtimeRoot = path.join(this.extensionUri.fsPath, "runtime");
    const url = `http://${HOST}:${PORT}`;
    this.setState({ status: "starting", url, detail: "Starting local FastAPI runtime…" });
    this.output.show(true);
    this.output.appendLine(`Starting Datapass runtime with ${pythonCommand}`);

    const child = spawn(
      pythonCommand,
      [
        "-m",
        "uvicorn",
        "datapass_runtime.main:app",
        "--app-dir",
        runtimeRoot,
        "--host",
        HOST,
        "--port",
        String(PORT)
      ],
      {
        cwd: runtimeRoot,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"]
      }
    );

    this.child = child;
    child.stdout?.on("data", chunk => this.output.append(String(chunk)));
    child.stderr?.on("data", chunk => this.output.append(String(chunk)));

    child.once("error", error => {
      this.child = undefined;
      this.setState({ status: "error", url, detail: error.message });
    });

    child.once("exit", (code, signal) => {
      if (this.child === child) this.child = undefined;
      if (this.state.status !== "error") {
        this.setState({
          status: "stopped",
          detail: `Runtime exited${code !== null ? ` with code ${code}` : ""}${signal ? ` (${signal})` : ""}.`
        });
      }
    });

    try {
      await waitForHealth(`${url}/api/health`, 6500);
      if (this.child === child) {
        this.setState({ status: "running", url, detail: "Local runtime healthy." });
      }
    } catch (error) {
      child.kill();
      this.child = undefined;
      this.setState({
        status: "error",
        url,
        detail: error instanceof Error ? error.message : String(error)
      });
    }
  }

  stop(): void {
    if (!this.child) {
      this.setState({ status: "stopped" });
      return;
    }
    const child = this.child;
    this.child = undefined;
    child.kill();
    this.setState({ status: "stopped", detail: "Local runtime stopped." });
  }

  dispose(): void {
    this.stop();
    this.changed.dispose();
    this.output.dispose();
  }

  private setState(next: RuntimeViewState): void {
    this.state = next;
    this.changed.fire(this.snapshot());
  }
}

async function waitForHealth(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError = "Runtime did not become healthy.";

  while (Date.now() < deadline) {
    try {
      const status = await requestStatus(url);
      if (status >= 200 && status < 300) return;
      lastError = `Health endpoint returned HTTP ${status}.`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await delay(180);
  }

  throw new Error(
    `Datapass runtime failed to start. ${lastError} Check the Datapass Runtime output; Python dependencies may need to be installed from runtime/pyproject.toml.`
  );
}

function requestStatus(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const request = http.get(url, response => {
      response.resume();
      resolve(response.statusCode ?? 0);
    });
    request.setTimeout(900, () => request.destroy(new Error("Health request timed out.")));
    request.on("error", reject);
  });
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
