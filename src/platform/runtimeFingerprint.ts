import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import * as path from "node:path";

/**
 * Stale managed runtime detection. Setup installs the extension's bundled `runtime/` package into the managed venv
 * (`<globalStorage>/runtime-venv`); a newer VSIX ships new runtime sources but the venv keeps the old install. Setup
 * therefore records a fingerprint of the sources it installed in the venv, and the extension compares it with the
 * fingerprint of its own `runtime/` before reporting the environment ready or starting the runtime.
 *
 * The runtime keeps its version number (0.1.0) between extension releases, so the fingerprint is a content hash.
 */

/** The marker Setup writes in the managed venv once the install is verified. */
export const RUNTIME_MARKER_FILE = "datapass-runtime.json";

export interface RuntimeMarker {
  schema: 1;
  /** `sha256:<hex>` of the runtime sources that were installed (runtimeFingerprint). */
  fingerprint: string;
  /** The extension version that installed them, for messages only (it does not change between builds). */
  extensionVersion?: string;
  installedAt: string;
}

export type ManagedRuntimeCheck =
  | { status: "missing" }
  | { status: "ready"; marker: RuntimeMarker }
  | { status: "stale"; reason: string; marker?: RuntimeMarker };

/**
 * Generated in the source folder by an install or an import, never part of what the VSIX ships (.vscodeignore):
 * bytecode, setuptools build output, egg-info, and hidden tool folders.
 */
function ignored(name: string, isDirectory: boolean, depth: number): boolean {
  if (name.startsWith(".")) return true;
  if (isDirectory) {
    return name === "__pycache__" || name === "node_modules" || name.endsWith(".egg-info") ||
      (depth === 0 && (name === "build" || name === "dist"));
  }
  return /\.py[co]$/.test(name);
}

/** The runtime source files, as sorted POSIX paths relative to `runtimeRoot`. */
export function runtimeSourceFiles(runtimeRoot: string): string[] {
  const files: string[] = [];
  const walk = (dir: string, prefix: string, depth: number): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const isDirectory = entry.isDirectory();
      if (!isDirectory && !entry.isFile()) continue;
      if (ignored(entry.name, isDirectory, depth)) continue;
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (isDirectory) walk(path.join(dir, entry.name), relative, depth + 1);
      else files.push(relative);
    }
  };
  walk(runtimeRoot, "", 0);
  // Code-unit order, independent of the platform's collation.
  return files.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

/** `sha256:<hex>` over every source file's relative path and content hash; about 120 files, a few milliseconds. */
export function runtimeFingerprint(runtimeRoot: string): string {
  const files = runtimeSourceFiles(runtimeRoot);
  if (!files.length) throw new Error(`No runtime sources under ${runtimeRoot}.`);
  const hash = createHash("sha256");
  for (const file of files) {
    const content = createHash("sha256").update(readFileSync(path.join(runtimeRoot, ...file.split("/")))).digest("hex");
    hash.update(`${file}\n${content}\n`);
  }
  return `sha256:${hash.digest("hex")}`;
}

export function runtimeMarkerPath(venvRoot: string): string {
  return path.join(venvRoot, RUNTIME_MARKER_FILE);
}

/** The marker, or undefined when it is absent or unreadable (both mean "not known to match"). */
export function readRuntimeMarker(venvRoot: string): RuntimeMarker | undefined {
  try {
    const value = JSON.parse(readFileSync(runtimeMarkerPath(venvRoot), "utf8")) as Partial<RuntimeMarker>;
    if (value?.schema !== 1 || typeof value.fingerprint !== "string" || !value.fingerprint) return undefined;
    return {
      schema: 1,
      fingerprint: value.fingerprint,
      extensionVersion: typeof value.extensionVersion === "string" ? value.extensionVersion : undefined,
      installedAt: typeof value.installedAt === "string" ? value.installedAt : ""
    };
  } catch {
    return undefined;
  }
}

export function writeRuntimeMarker(venvRoot: string, marker: RuntimeMarker): void {
  const target = runtimeMarkerPath(venvRoot);
  const temporary = `${target}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(marker, null, 2)}\n`, "utf8");
  renameSync(temporary, target);
}

/** Before an install: a half-installed venv must never keep a marker that says it matches. */
export function removeRuntimeMarker(venvRoot: string): void {
  rmSync(runtimeMarkerPath(venvRoot), { force: true });
}

/** Compare the managed venv with this extension's runtime sources. */
export function checkManagedRuntime(input: {
  pythonExists: boolean;
  marker?: RuntimeMarker;
  fingerprint: string;
  extensionVersion?: string;
}): ManagedRuntimeCheck {
  if (!input.pythonExists) return { status: "missing" };
  const { marker } = input;
  if (!marker) {
    return {
      status: "stale",
      reason: "The managed runtime was installed by an earlier Datapass version that did not record its runtime. Update it before starting."
    };
  }
  if (marker.fingerprint === input.fingerprint) return { status: "ready", marker };
  const by = marker.extensionVersion ? `Datapass ${marker.extensionVersion}` : "another Datapass build";
  const sameVersion = marker.extensionVersion && marker.extensionVersion === input.extensionVersion
    ? " (same version number, different runtime sources)"
    : "";
  return {
    status: "stale",
    reason: `The managed runtime was installed by ${by} and does not match this extension's runtime${sameVersion}. Update it before starting.`,
    marker
  };
}

/** The extension's own version from its package.json, or undefined. */
export function extensionVersion(extensionRoot: string): string | undefined {
  const file = path.join(extensionRoot, "package.json");
  if (!existsSync(file)) return undefined;
  try {
    const version = (JSON.parse(readFileSync(file, "utf8")) as { version?: unknown }).version;
    return typeof version === "string" ? version : undefined;
  } catch {
    return undefined;
  }
}
