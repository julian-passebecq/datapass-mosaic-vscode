import { spawn, type ChildProcess } from "node:child_process";
import * as http from "node:http";
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

  async start(pythonCommand = "python", storage: "duckdb" | "ducklake" = "duckdb"): Promise<void> {
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
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          DATAPASS_CONTENT_ROOT: path.join(this.extensionUri.fsPath, "content"),
          DATAPASS_STORAGE: storage,
          ...(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
            ? { DATAPASS_WORKSPACE_ROOT: vscode.workspace.workspaceFolders[0].uri.fsPath }
            : {})
        }
      }
    );

    this.child = child;
    child.stdout?.on("data", chunk => this.output.append(String(chunk)));
    child.stderr?.on("data", chunk => this.output.append(String(chunk)));

    child.once("error", error => {
      if (this.child !== child) return;
      this.child = undefined;
      this.setState({ status: "error", url, detail: error.message });
    });

    child.once("exit", (code, signal) => {
      if (this.child !== child) return;
      this.child = undefined;
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
        await this.refreshCatalog();
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

  async runRetailDemo(datasetPath: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running the retail demo.");
    this.setState({ ...this.state, detail: "Running retail medallion demo…" });
    try {
      const retailDemo = await requestJson<NonNullable<RuntimeViewState["retailDemo"]>>(
        `${url}/api/demo/retail/run`,
        "POST",
        { dataset_path: datasetPath },
        10000
      );
      this.setState({
        ...this.state,
        detail: "Retail demo completed with real local Polars + DuckDB execution.",
        retailDemo
      });
      await this.refreshCatalog();
    } catch (error) {
      this.setState({
        ...this.state,
        detail: error instanceof Error ? error.message : String(error)
      });
      throw error;
    }
  }

  async runSql(code: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running SQL.");
    const lastRun = await requestJson<NonNullable<RuntimeViewState["lastRun"]>>(
      `${url}/api/local/execute`,
      "POST",
      {
        language: "sql",
        code,
        notebook_id: "vscode-sql",
        cell_id: "active-sql"
      },
      10000
    );
    this.setState({
      ...this.state,
      detail: lastRun.status === "success"
        ? `SQL completed in ${lastRun.elapsed_ms.toFixed(1)} ms.`
        : `SQL failed: ${lastRun.error?.message ?? "Unknown error"}`,
      lastRun
    });
    await this.refreshCatalog();
  }

  async refreshCatalog(): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) return;
    try {
      const catalog = await requestGetJson<NonNullable<RuntimeViewState["catalog"]>>(
        `${url}/api/local/catalog`
      );
      this.setState({ ...this.state, catalog });
    } catch (error) {
      this.setState({
        ...this.state,
        detail: `Catalog refresh failed: ${error instanceof Error ? error.message : String(error)}`
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



function requestJson<T>(
  url: string,
  method: "POST",
  body: unknown,
  timeoutMs = 2500
): Promise<T> {
  return new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body), "utf8");
    const request = http.request(
      url,
      {
        method,
        headers: {
          "content-type": "application/json",
          "content-length": String(payload.length)
        }
      },
      response => {
        const chunks: Buffer[] = [];
        response.on("data", chunk => chunks.push(Buffer.from(chunk)));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if ((response.statusCode ?? 500) < 200 || (response.statusCode ?? 500) >= 300) {
            reject(new Error(`Runtime request failed with HTTP ${response.statusCode}: ${text.slice(0, 500)}`));
            return;
          }
          try {
            resolve(JSON.parse(text) as T);
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    request.setTimeout(timeoutMs, () => request.destroy(new Error("Runtime request timed out.")));
    request.on("error", reject);
    request.end(payload);
  });
}


function requestGetJson<T>(url: string, timeoutMs = 3000): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = http.get(url, response => {
      const chunks: Buffer[] = [];
      response.on("data", chunk => chunks.push(Buffer.from(chunk)));
      response.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        if ((response.statusCode ?? 500) < 200 || (response.statusCode ?? 500) >= 300) {
          reject(new Error(`Runtime request failed with HTTP ${response.statusCode}: ${text.slice(0, 500)}`));
          return;
        }
        try {
          resolve(JSON.parse(text) as T);
        } catch (error) {
          reject(error);
        }
      });
    });
    request.setTimeout(timeoutMs, () => request.destroy(new Error("Runtime request timed out.")));
    request.on("error", reject);
  });
}
