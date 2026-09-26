import type { RuntimeViewState } from "../webview/contracts";

/**
 * What a lab's runtime client uses of the RuntimeManager: the running runtime's URL, JSON requests that carry the
 * per-launch token (the client never sees it), and the shared runtime state the Workbench shows.
 */
export interface RuntimeConnection {
  /** The runtime's base URL while it runs, else undefined. */
  runningUrl(): string | undefined;
  /** The base URL, or the error "Start the Datapass runtime to <action>." */
  requireRunning(action: string): string;
  /** Like requireRunning, and refused while the catalog is lent to a dbt Core or dct command. */
  requireAttached(action: string): string;
  postJson<T>(url: string, body: unknown, timeoutMs?: number): Promise<T>;
  getJson<T>(url: string, timeoutMs?: number): Promise<T>;
  /** The current runtime state. */
  state(): Readonly<RuntimeViewState>;
  /** Merge a patch into the runtime state and tell the Workbench. */
  update(patch: Partial<RuntimeViewState>): void;
  refreshCatalog(): Promise<void>;
}
