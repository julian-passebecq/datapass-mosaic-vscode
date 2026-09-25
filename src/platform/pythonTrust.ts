/**
 * Trusted local Python/Polars resolution.
 *
 * Arbitrary Python runs as real local code. The runtime worker is process
 * isolated for lifecycle reasons only; it is NOT a security sandbox. Python is
 * therefore enabled only when all three hold:
 *
 * 1. the project manifest opts in (`runtime.trustedLocalPython: true`) — portable
 *    and reviewable, but a cloned repository could set it, so it is not enough;
 * 2. the user confirmed the opt-in on this machine for this workspace;
 * 3. VS Code Workspace Trust is granted.
 */

import { RUNTIME_PORT_ENV, RUNTIME_TOKEN_ENV } from "./runtimeClient";

export const TRUSTED_PYTHON_ENV = "DATAPASS_TRUSTED_PYTHON";

export type PythonTrustState =
  | "disabled"
  | "requested"
  | "blocked-untrusted-workspace"
  | "enabled";

export interface PythonTrustInputs {
  manifestOptIn: boolean;
  acknowledged: boolean;
  workspaceTrusted: boolean;
}

export interface PythonTrustResolution {
  state: PythonTrustState;
  effective: boolean;
  reason: string;
}

export function resolvePythonTrust(inputs: PythonTrustInputs): PythonTrustResolution {
  if (!inputs.manifestOptIn) {
    return {
      state: "disabled",
      effective: false,
      reason: "Trusted local Python is off. SQL and bounded SparkLab still run; Python/Polars files are not executed."
    };
  }
  if (!inputs.workspaceTrusted) {
    return {
      state: "blocked-untrusted-workspace",
      effective: false,
      reason: "The project requests trusted local Python, but VS Code Workspace Trust is not granted."
    };
  }
  if (!inputs.acknowledged) {
    return {
      state: "requested",
      effective: false,
      reason: "The project manifest requests trusted local Python. Confirm on this machine before any Python is executed."
    };
  }
  return {
    state: "enabled",
    effective: true,
    reason: "Trusted local Python is on. Python/Polars files run as real local code with your user permissions; this is not a sandbox."
  };
}

export interface RuntimeProcessEnvOptions {
  contentRoot: string;
  storage: "duckdb" | "ducklake";
  trustedPython: boolean;
  workspaceRoot?: string;
  /** This launch's random token (see runtimeClient.ts); the runtime refuses every request without it. */
  runtimeToken: string;
  runtimePort: number;
}

/**
 * Build the runtime process environment. An inherited DATAPASS_TRUSTED_PYTHON is
 * always discarded so a shell variable can never silently enable Python, and an
 * inherited runtime token or port is replaced by this launch's own.
 */
export function runtimeProcessEnv(
  base: Readonly<Record<string, string | undefined>>,
  options: RuntimeProcessEnvOptions
): Record<string, string> {
  const replaced = new Set([TRUSTED_PYTHON_ENV, RUNTIME_TOKEN_ENV, RUNTIME_PORT_ENV]);
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(base)) {
    if (value !== undefined && !replaced.has(key.toUpperCase())) env[key] = value;
  }
  env.DATAPASS_CONTENT_ROOT = options.contentRoot;
  env.DATAPASS_STORAGE = options.storage;
  if (options.workspaceRoot) env.DATAPASS_WORKSPACE_ROOT = options.workspaceRoot;
  if (options.trustedPython) env[TRUSTED_PYTHON_ENV] = "1";
  env[RUNTIME_TOKEN_ENV] = options.runtimeToken;
  env[RUNTIME_PORT_ENV] = String(options.runtimePort);
  return env;
}
