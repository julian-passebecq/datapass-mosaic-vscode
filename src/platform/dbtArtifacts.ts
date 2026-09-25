/**
 * dbt Lab: what a real dbt Core run left in target/ (manifest.json and run_results.json), mapped for the UI.
 * Pure (no vscode import) so scripts/dbt_lab_smoke.mjs can test it on real artifacts.
 */
import type { GraphEdgeView, GraphNodeView, GraphView } from "../webview/contracts";

export type DbtCoreStatus = "success" | "error" | "fail" | "warn" | "pass" | "skipped" | "no-op" | "runtime error";

export interface DbtCoreNodeView {
  uniqueId: string;
  name: string;
  resourceType: string;
  materialized?: string;
  relation?: string;
  path?: string;
  compiledPath?: string;
  tags: string[];
  dependsOn: string[];
  /** For tests: the node they test. */
  attachedTo?: string;
  status?: string;
  message?: string;
  failures?: number;
  executionTime?: number;
  rowsAffected?: number;
}

export interface DbtCoreSourceView {
  uniqueId: string;
  name: string;
  relation: string;
  loadedAtField?: string;
  freshness?: string;
}

export interface DbtCoreRunView {
  truth: string;
  projectName?: string;
  dbtVersion?: string;
  invocationId?: string;
  generatedAt?: string;
  /** The command that produced run_results.json, rebuilt from its args. */
  command?: string;
  elapsedSeconds?: number;
  hasResults: boolean;
  counts: Record<string, number>;
  nodes: DbtCoreNodeView[];
  sources: DbtCoreSourceView[];
  /** Nodes that errored, failed, warned or were skipped, worst first. */
  problems: DbtCoreNodeView[];
  warnings: string[];
}

export const DBT_CORE_TRUTH = "dbt Core (real): read from target/manifest.json and target/run_results.json of your own run";
const MAX_NODES = 3000;
const STATUS_ORDER = ["error", "runtime error", "fail", "warn", "skipped"];
const GRAPH_STATE: Record<string, string> = {
  success: "success", pass: "success", error: "failed", "runtime error": "failed", fail: "failed", warn: "warning",
  skipped: "skipped", "no-op": "skipped"
};

export function toDbtCoreRunView(manifestRaw: unknown, runResultsRaw: unknown | undefined): DbtCoreRunView {
  const manifest = record(manifestRaw);
  if (!manifest || !record(manifest.nodes)) throw new Error("target/manifest.json is not a dbt manifest.");
  const metadata = record(manifest.metadata) ?? {};
  const warnings: string[] = [];
  const schema = str(metadata.dbt_schema_version) ?? "";
  if (!/manifest\/v(1[0-9]|9)\.json$/.test(schema)) warnings.push(`Unexpected manifest schema ${schema || "(none)"}; the view may be incomplete.`);

  const resultsRecord = record(runResultsRaw);
  const results = new Map<string, Record<string, unknown>>();
  for (const item of array(resultsRecord?.results)) {
    const result = record(item);
    const id = str(result?.unique_id);
    if (result && id) results.set(id, result);
  }
  const resultsMeta = record(resultsRecord?.metadata);
  const manifestInvocation = str(metadata.invocation_id);
  const resultsInvocation = str(resultsMeta?.invocation_id);
  if (resultsRecord && manifestInvocation && resultsInvocation && manifestInvocation !== resultsInvocation) {
    warnings.push("manifest.json comes from a later command than run_results.json (for example dbt parse or dbt docs generate): statuses belong to the earlier run.");
  }

  const nodes: DbtCoreNodeView[] = [];
  for (const [uniqueId, raw] of Object.entries(record(manifest.nodes) ?? {})) {
    const node = record(raw);
    if (!node) continue;
    const resourceType = str(node.resource_type) ?? "node";
    if (!["model", "seed", "snapshot", "test", "analysis", "unit_test"].includes(resourceType)) continue;
    if (resourceType === "analysis") continue;
    if (nodes.length >= MAX_NODES) {
      warnings.push(`Only the first ${MAX_NODES} nodes are shown.`);
      break;
    }
    const config = record(node.config) ?? {};
    const result = results.get(uniqueId);
    const adapter = record(result?.adapter_response);
    const materialized = str(config.materialized);
    nodes.push({
      uniqueId,
      name: str(node.name) ?? uniqueId,
      resourceType,
      materialized: resourceType === "model" || resourceType === "snapshot" ? materialized : undefined,
      relation: resourceType === "test" || materialized === "ephemeral" ? undefined : relationOf(node),
      path: str(node.original_file_path),
      compiledPath: str(node.compiled_path),
      tags: array(node.tags).filter((tag): tag is string => typeof tag === "string"),
      dependsOn: array(record(node.depends_on)?.nodes).filter((id): id is string => typeof id === "string"),
      attachedTo: str(node.attached_node),
      status: str(result?.status),
      message: str(result?.message),
      failures: num(result?.failures),
      executionTime: num(result?.execution_time),
      rowsAffected: num(adapter?.rows_affected)
    });
  }
  // Results for nodes the manifest does not describe (it was replaced by a later parse) still count.
  for (const [uniqueId, result] of results) {
    if (nodes.some(node => node.uniqueId === uniqueId)) continue;
    nodes.push({ uniqueId, name: uniqueId.split(".").at(-1) ?? uniqueId, resourceType: uniqueId.split(".")[0] ?? "node",
      tags: [], dependsOn: [], status: str(result.status), message: str(result.message), failures: num(result.failures) });
  }

  const sources: DbtCoreSourceView[] = [];
  for (const [uniqueId, raw] of Object.entries(record(manifest.sources) ?? {})) {
    const source = record(raw);
    if (!source) continue;
    const freshness = record(source.freshness) ?? record(record(source.config)?.freshness);
    const warn = record(freshness?.warn_after);
    const error = record(freshness?.error_after);
    const describe = (after: Record<string, unknown> | undefined) =>
      after && num(after.count) !== undefined && str(after.period) ? `${num(after.count)} ${str(after.period)}` : undefined;
    const rules = [describe(warn) && `warn after ${describe(warn)}`, describe(error) && `error after ${describe(error)}`].filter(Boolean);
    sources.push({
      uniqueId,
      name: `${str(source.source_name) ?? "source"}.${str(source.name) ?? uniqueId}`,
      relation: relationOf(source) ?? "",
      loadedAtField: str(source.loaded_at_field) ?? str(record(source.config)?.loaded_at_field),
      freshness: rules.length ? rules.join(", ") : undefined
    });
  }
  // Source freshness results live in sources.json, not run_results.json; source nodes show their rules only.

  const counts: Record<string, number> = {};
  for (const node of nodes) if (node.status) counts[node.status] = (counts[node.status] ?? 0) + 1;
  const problems = nodes
    .filter(node => node.status && STATUS_ORDER.includes(node.status))
    .sort((a, b) => STATUS_ORDER.indexOf(a.status!) - STATUS_ORDER.indexOf(b.status!) || a.name.localeCompare(b.name));

  return {
    truth: DBT_CORE_TRUTH,
    projectName: str(metadata.project_name),
    dbtVersion: str(resultsMeta?.dbt_version) ?? str(metadata.dbt_version),
    invocationId: resultsInvocation ?? manifestInvocation,
    generatedAt: str(resultsMeta?.generated_at) ?? str(metadata.generated_at),
    command: resultsRecord ? commandFromArgs(record(resultsRecord.args)) : undefined,
    elapsedSeconds: num(resultsRecord?.elapsed_time),
    hasResults: results.size > 0,
    counts,
    nodes,
    sources,
    problems,
    warnings
  };
}

/** `dbt build --select tag:daily --full-refresh`, from run_results.json's args. */
export function commandFromArgs(args: Record<string, unknown> | undefined): string | undefined {
  if (!args) return undefined;
  const which = str(args.which);
  if (!which) return undefined;
  const parts = ["dbt", which === "generate" ? "docs generate" : which];
  const list = (value: unknown) => typeof value === "string" ? [value] : array(value).filter((v): v is string => typeof v === "string");
  const select = list(args.select);
  const exclude = list(args.exclude);
  if (select.length) parts.push("--select", ...select);
  if (exclude.length) parts.push("--exclude", ...exclude);
  if (args.full_refresh === true) parts.push("--full-refresh");
  return parts.join(" ");
}

/** The project's DAG from the real manifest; tests attach to the node they test when shown. */
export function dbtCoreGraph(view: DbtCoreRunView, withTests = false): GraphView {
  const shown = view.nodes.filter(node => node.resourceType !== "unit_test" && (withTests || node.resourceType !== "test"));
  const ids = new Set(shown.map(node => node.uniqueId));
  const usedSources = new Set(shown.flatMap(node => node.dependsOn.filter(id => id.startsWith("source."))));
  const nodes: GraphNodeView[] = [
    ...view.sources.filter(source => usedSources.has(source.uniqueId)).map(source => ({
      id: source.uniqueId, label: source.name, detail: [source.relation, source.freshness].filter(Boolean).join(" · "), truth: "source"
    })),
    ...shown.map(node => ({
      id: node.uniqueId,
      label: node.name,
      detail: [
        node.resourceType === "model" ? node.materialized : node.resourceType,
        node.relation,
        node.status ? node.status + (node.failures ? ` (${node.failures})` : "") : ""
      ].filter(Boolean).join(" · "),
      truth: node.resourceType,
      status: node.status ? GRAPH_STATE[node.status] : undefined
    }))
  ];
  const edges: GraphEdgeView[] = [];
  for (const node of shown) {
    for (const parent of node.dependsOn) {
      if (ids.has(parent) || usedSources.has(parent)) {
        edges.push({ id: `${parent}->${node.uniqueId}`, source: parent, target: node.uniqueId, label: "" });
      }
    }
  }
  return { nodes, edges };
}

export function countsLine(counts: Record<string, number>): string {
  const order = ["success", "pass", "warn", "error", "fail", "skipped", "no-op"];
  const rank = (status: string) => order.includes(status) ? order.indexOf(status) : order.length;
  return Object.entries(counts)
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([status, count]) => `${count} ${status}`)
    .join(" · ");
}

function relationOf(node: Record<string, unknown>): string | undefined {
  const schema = str(node.schema);
  const name = str(node.alias) ?? str(node.identifier) ?? str(node.name);
  return schema && name ? `${schema}.${name}` : undefined;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function num(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
