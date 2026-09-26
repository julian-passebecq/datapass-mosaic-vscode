import { randomBytes } from "node:crypto";
import * as http from "node:http";

/**
 * Loopback runtime authentication.
 *
 * The runtime listens on 127.0.0.1, but any local process, or a web page using DNS
 * rebinding, can reach a loopback port. Each launch therefore gets a fresh random
 * token that only the extension and the runtime know: it travels in the child
 * environment and in this header, is never persisted and never logged.
 */
export const RUNTIME_TOKEN_ENV = "DATAPASS_RUNTIME_TOKEN";
export const RUNTIME_PORT_ENV = "DATAPASS_RUNTIME_PORT";
export const RUNTIME_TOKEN_HEADER = "x-datapass-token";

/** 32 random bytes, hex encoded. */
export function newRuntimeToken(): string {
  return randomBytes(32).toString("hex");
}

export function runtimeAuthHeaders(token: string | undefined): Record<string, string> {
  return token ? { [RUNTIME_TOKEN_HEADER]: token } : {};
}

export function requestJson<T>(
  url: string,
  method: "POST",
  body: unknown,
  timeoutMs = 2500,
  token?: string
): Promise<T> {
  return new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body), "utf8");
    const request = http.request(
      url,
      {
        method,
        headers: {
          ...runtimeAuthHeaders(token),
          "content-type": "application/json",
          "content-length": String(payload.length)
        }
      },
      response => collectJson<T>(response, resolve, reject)
    );
    request.setTimeout(timeoutMs, () => request.destroy(new Error("Runtime request timed out.")));
    request.on("error", reject);
    request.end(payload);
  });
}

export function requestGetJson<T>(url: string, timeoutMs = 3000, token?: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { headers: runtimeAuthHeaders(token) }, response =>
      collectJson<T>(response, resolve, reject)
    );
    request.setTimeout(timeoutMs, () => request.destroy(new Error("Runtime request timed out.")));
    request.on("error", reject);
  });
}

function collectJson<T>(
  response: http.IncomingMessage,
  resolve: (value: T) => void,
  reject: (reason: unknown) => void
): void {
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

/** Pull FastAPI's `detail` out of a "Runtime request failed with HTTP 4xx: {...}" error. */
export function runtimeErrorDetail(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const body = /^Runtime request failed with HTTP \d+: (.*)$/s.exec(message)?.[1];
  if (!body) return message;
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map(item => (item && typeof item === "object" && "msg" in item ? String(item.msg) : String(item)))
        .join("; ");
    }
  } catch {
    // Not JSON (e.g. truncated); fall through to the raw message.
  }
  return message;
}
