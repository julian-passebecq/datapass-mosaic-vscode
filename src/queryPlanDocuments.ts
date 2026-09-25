import * as vscode from "vscode";
import type { QueryPlanView } from "./webview/contracts";

/**
 * Read-only documents for Mosaic query plans: DuckDB draws EXPLAIN ANALYZE as wide boxes, which read better in a
 * full editor than in a Mosaic block. The plans live in memory only; closing the tab never asks to save.
 */
export const QUERY_PLAN_SCHEME = "datapass-plan";
const plans = new Map<string, string>();
const changed = new vscode.EventEmitter<vscode.Uri>();

export function registerQueryPlanDocuments(): vscode.Disposable {
  return vscode.workspace.registerTextDocumentContentProvider(QUERY_PLAN_SCHEME, {
    onDidChange: changed.event,
    provideTextDocumentContent: uri => plans.get(uri.toString()) ?? "Explain the query again from Mosaic to see its plan."
  });
}

/** Opens the plan beside the Workbench, under a name that says which file (or selection) it explains. */
export async function openQueryPlan(plan: QueryPlanView): Promise<void> {
  const label = (plan.source ?? "query").replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "query";
  const uri = vscode.Uri.from({ scheme: QUERY_PLAN_SCHEME, path: `/${label}.plan.txt` });
  plans.set(uri.toString(), [
    `-- ${plan.truth}`,
    `-- ${plan.source ?? "query"} · ${plan.elapsed_ms.toFixed(1)} ms`,
    "",
    plan.query,
    "",
    plan.plan,
    ""
  ].join("\n"));
  changed.fire(uri);
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document, { viewColumn: vscode.ViewColumn.Beside, preview: true });
}
