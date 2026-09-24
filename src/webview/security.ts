import * as vscode from "vscode";

/**
 * Webview security helpers adapted from the earlier DataPass VS Code control-plane.
 * Keep custom Datapass UI locked to extension-owned resources and explicit scripts.
 */
export function makeNonce(length = 32): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let value = "";
  for (let i = 0; i < length; i += 1) {
    value += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return value;
}

export function contentSecurityPolicy(
  webview: vscode.Webview,
  nonce?: string
): string {
  const script = nonce ? ` script-src 'nonce-${nonce}';` : "";
  return `default-src 'none'; img-src ${webview.cspSource} https: data:; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource};${script}`;
}
