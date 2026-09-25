import { randomBytes } from "node:crypto";
import type * as vscode from "vscode";

/**
 * Webview security helpers adapted from the earlier DataPass VS Code control-plane.
 * Keep custom Datapass UI locked to extension-owned resources and explicit scripts.
 */
const NONCE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

/** A CSP nonce from the OS CSPRNG. Bytes >= 248 (4 x 62) are skipped so every symbol is equally likely. */
export function makeNonce(length = 32): string {
  let value = "";
  while (value.length < length) {
    for (const byte of randomBytes(length)) {
      if (byte < 248 && value.length < length) value += NONCE_CHARS.charAt(byte % NONCE_CHARS.length);
    }
  }
  return value;
}

/** Images come only from the extension (webview.cspSource) or inline data: URLs (dct PNG renders); never the network. */
export function contentSecurityPolicy(
  webview: Pick<vscode.Webview, "cspSource">,
  nonce?: string
): string {
  const script = nonce ? ` script-src 'nonce-${nonce}';` : "";
  return `default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource};${script}`;
}
