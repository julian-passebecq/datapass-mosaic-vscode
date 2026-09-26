/**
 * VS Code native entry points (src/nativeIntegration.ts): which workspace file is a Practice solution or a mission
 * file, and what the runtime's status bar item says and does. Pure functions, tested by scripts/native_smoke.mjs.
 */
import type { RuntimeViewState } from "../webview/contracts";

const MISSION_ID = /^[a-z0-9][a-z0-9-]{0,47}$/;
const SOLUTION = /^solution\.[a-z0-9]+$/;

/**
 * A Practice solution file: `<exerciseRoot>/<exercise slug>/<language slug>/solution.<ext>`, as the Practice controller
 * writes it. `parts` is the file's path relative to the workspace root, split on "/".
 */
export function solutionTarget(parts: readonly string[], exerciseRoot: readonly string[]): { exercise: string; language: string } | undefined {
  if (parts.length !== exerciseRoot.length + 3) return undefined;
  if (!exerciseRoot.every((part, index) => parts[index] === part)) return undefined;
  const [exercise, language, file] = parts.slice(exerciseRoot.length);
  return SOLUTION.test(file) && exercise && language ? { exercise, language } : undefined;
}

/** The mission a workspace file belongs to: any file under `missions/<id>/`. */
export function missionOf(parts: readonly string[]): string | undefined {
  return parts.length >= 3 && parts[0] === "missions" && MISSION_ID.test(parts[1]) ? parts[1] : undefined;
}

export type RuntimeAction = "setup" | "update" | "start" | "open" | "log";

export interface RuntimeStatusView {
  text: string;
  tooltip: string;
  action: RuntimeAction;
  /** Shown with the warning background. */
  warning: boolean;
}

/** The status bar item: the runtime's state, and what a click does. */
export function runtimeStatusView(runtime: Pick<RuntimeViewState, "status" | "environment" | "url">): RuntimeStatusView {
  const environment = runtime.environment?.status;
  if (runtime.status === "running") {
    return { text: "$(pass-filled) Datapass: running", tooltip: `Datapass runtime running${runtime.url ? ` on ${runtime.url}` : ""}. Click to open Today.`, action: "open", warning: false };
  }
  if (runtime.status === "starting") {
    return { text: "$(sync~spin) Datapass: starting", tooltip: "The Datapass runtime is starting. Click to open Today.", action: "open", warning: false };
  }
  if (environment === "setting-up") {
    return { text: "$(sync~spin) Datapass: setting up", tooltip: "Setting up the Datapass runtime. Click to show the setup log.", action: "log", warning: false };
  }
  if (environment === "stale") {
    return { text: "$(warning) Datapass: needs update", tooltip: "The managed runtime belongs to another Datapass build. Click to update it.", action: "update", warning: true };
  }
  if (runtime.status === "error" || environment === "error") {
    return { text: "$(error) Datapass: error", tooltip: "The Datapass runtime failed. Click to show its log.", action: "log", warning: true };
  }
  if (environment === "ready") {
    return { text: "$(circle-outline) Datapass: stopped", tooltip: "The Datapass runtime is set up and stopped. Click to start it.", action: "start", warning: false };
  }
  return { text: "$(circle-outline) Datapass: not set up", tooltip: "The Datapass runtime is not set up yet. Click to set it up.", action: "setup", warning: false };
}

/** The folder name the Practice controller gives an exercise id or language (src/labs/practice/controller.ts slug). */
export function exerciseSlug(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "exercise";
}
