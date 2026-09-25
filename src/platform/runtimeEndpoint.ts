import * as http from "node:http";
import * as net from "node:net";
import { runtimeAuthHeaders } from "./runtimeClient";

export interface DatapassHealth {
  status: "ok";
  runtime: "local";
  version: string;
}

export async function findFreePort(host = "127.0.0.1"): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen({ host, port: 0, exclusive: true }, () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("Could not resolve a free Datapass runtime port."));
        return;
      }
      const port = address.port;
      server.close(error => {
        if (error) reject(error);
        else resolve(port);
      });
    });
  });
}

export async function probeDatapassHealth(url: string, token?: string): Promise<DatapassHealth> {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { headers: runtimeAuthHeaders(token) }, response => {
      const statusCode = response.statusCode ?? 0;
      const chunks: Buffer[] = [];
      let size = 0;

      response.on("data", chunk => {
        const value = Buffer.from(chunk);
        size += value.length;
        if (size > 64 * 1024) {
          request.destroy(new Error("Health response was unexpectedly large."));
          return;
        }
        chunks.push(value);
      });

      response.on("end", () => {
        if (statusCode < 200 || statusCode >= 300) {
          reject(new Error(`Health endpoint returned HTTP ${statusCode}.`));
          return;
        }

        try {
          const value = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Partial<DatapassHealth>;
          if (
            value.status !== "ok" ||
            value.runtime !== "local" ||
            typeof value.version !== "string" ||
            value.version.length === 0
          ) {
            reject(new Error("Health endpoint is not a Datapass local runtime."));
            return;
          }
          resolve(value as DatapassHealth);
        } catch (error) {
          reject(new Error(
            `Health endpoint returned invalid JSON: ${error instanceof Error ? error.message : String(error)}`
          ));
        }
      });
    });

    request.setTimeout(900, () => request.destroy(new Error("Health request timed out.")));
    request.on("error", reject);
  });
}

/**
 * Poll the health endpoint until it answers or the deadline passes.
 * `abortReason` is checked between probes so a runtime process that already
 * exited fails immediately instead of waiting out the whole timeout.
 */
export async function waitForDatapassHealth(
  url: string,
  timeoutMs: number,
  abortReason: () => string | undefined = () => undefined,
  token?: string
): Promise<DatapassHealth> {
  const deadline = Date.now() + timeoutMs;
  let lastError = "Runtime did not become healthy.";

  while (Date.now() < deadline) {
    const aborted = abortReason();
    if (aborted) throw new Error(aborted);
    try {
      return await probeDatapassHealth(url, token);
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await delay(250);
  }

  throw new Error(`Runtime did not become healthy within ${Math.round(timeoutMs / 1000)} s (${lastError}).`);
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
