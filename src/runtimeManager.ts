import { spawn, type ChildProcess } from "node:child_process";
import * as path from "node:path";
import * as vscode from "vscode";
import type { RuntimeViewState } from "./webview/contracts";
import { findFreePort, waitForDatapassHealth } from "./platform/runtimeEndpoint";

const HOST = "127.0.0.1";

export interface PipelineCompileResponse {
  valid: boolean;
  source_hash: string;
  truth: string;
  diagnostics: Array<{ line: number; column: number; message: string }>;
  ir: null | {
    id: string;
    schedule: string | null;
    tasks: Array<{
      id: string;
      kind: string;
      retries: number;
      retry_delay: number;
    }>;
    edges: Array<{ source: string; target: string }>;
  };
}

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
    const port = await findFreePort(HOST);
    const url = `http://${HOST}:${port}`;
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
        String(port)
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
      await waitForDatapassHealth(`${url}/api/health`, 6500);
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

  async compilePipeline(source: string): Promise<PipelineCompileResponse> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before compiling a pipeline.");
    return requestJson<PipelineCompileResponse>(
      `${url}/api/pipeline/compile`,
      "POST",
      { source }
    );
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

