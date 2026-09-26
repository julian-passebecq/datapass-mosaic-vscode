import { toBiDbtView, toBiLabView } from "../../platform/biRun";
import type { BiDbtCommand, BiRunMode } from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

/** BI Lab: warehouse scripts on the local catalog, SQL lineage (static), star model checks, and the dbt emulation. */
export class BiClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /**
   * BI Lab: the warehouse scripts run on the local catalog (real DuckDB), then the runtime reports the tables,
   * the SQL lineage of the scripts (static analysis) and the star model checks (real queries).
   */
  async runBiLab(request: {
    mode: BiRunMode;
    source: string;
    scripts: { path: string; text: string }[];
    model: unknown;
    modelError?: string;
    warnings: string[];
  }): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running the BI Lab.");
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/bi/lab`,
      { scripts: request.scripts, model: request.model ?? null, run: request.mode !== "analyze" },
      120000
    );
    const biRun = toBiLabView(raw, request);
    const failed = biRun.statements.find(statement => statement.status === "error");
    this.runtime.update({
      detail: failed
        ? `BI Lab stopped at ${failed.path}, line ${failed.line}: ${failed.message}`
        : biRun.ran
          ? `BI Lab: ${biRun.statements.length} statement(s) ran on the local catalog (${request.source}).`
          : `BI Lab: lineage and model checks refreshed (${request.source}).`,
      biRun
    });
    if (biRun.ran) await this.runtime.refreshCatalog();
  }

  /**
   * BI Lab dbt tab: the Datapass dbt emulation runs the command on the local catalog (Jinja in a sandbox, SQL on
   * DuckDB) and reports the nodes, the results and the column lineage of the models. It is not dbt Core.
   */
  async runBiDbt(request: { command: BiDbtCommand; select: string[]; selectText: string; fullRefresh: boolean;
    files: Record<string, string>; warnings: string[] }): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running dbt.");
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/bi/dbt`,
      { files: request.files, command: request.command, select: request.select, full_refresh: request.fullRefresh },
      120000
    );
    const biDbtRun = toBiDbtView(raw, { command: request.command, select: request.selectText, warnings: request.warnings });
    const counts = biDbtRun.counts ?? {};
    this.runtime.update({
      detail: biDbtRun.status === "invalid"
        ? `dbt ${request.command} not run: ${biDbtRun.error ?? "invalid project"}`
        : biDbtRun.status === "parsed"
          ? `dbt project parsed: ${biDbtRun.nodes.length} nodes.`
          : `dbt ${request.command} (Datapass emulation): ${Object.entries(counts).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(", ") || "nothing selected"}.`,
      biDbtRun
    });
    if (biDbtRun.results.length) await this.runtime.refreshCatalog();
  }
}
