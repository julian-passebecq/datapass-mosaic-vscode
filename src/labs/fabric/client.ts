import type { DatabricksFilesPayload, FactoryFilesPayload } from "../../factoryState";
import { toDatabricksLabView, toDatabricksScenario, toDatabricksStateView } from "../../platform/databricksRun";
import { toFactoryLabView, toRuntimeScenario as toFactoryScenario } from "../../platform/factoryRun";
import { toSqlPoolView } from "../../platform/sqlpoolRun";
import type {
  DatabricksScenarioInput,
  FactoryFlavor,
  FactoryScenarioInput,
  RetailDemoRunView,
  SqlPoolFlavor
} from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

/**
 * Cloud Lab (module id `fabric`): the retail demo, and the Pipelines, SQL pool and Databricks simulators. Nothing
 * connects to Microsoft Fabric, Azure or Databricks.
 */
export class FabricClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  async runRetailDemo(datasetPath: string): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running the retail demo.");
    this.runtime.update({ detail: "Running retail medallion demo…" });
    try {
      const retailDemo = await this.runtime.postJson<RetailDemoRunView>(
        `${url}/api/demo/retail/run`,
        { dataset_path: datasetPath },
        10000
      );
      this.runtime.update({
        detail: "Retail demo completed with real local Polars + DuckDB execution.",
        retailDemo
      });
      await this.runtime.refreshCatalog();
    } catch (error) {
      this.runtime.update({
        detail: error instanceof Error ? error.message : String(error)
      });
      throw error;
    }
  }

  /**
   * Factory Lab: the runtime validates and simulates the pipeline JSON. With the local data plane,
   * Copy, Lookup, Script, stored procedures and SparkLab notebooks act on the local catalog.
   */
  async simulateFactory(request: {
    flavor: FactoryFlavor;
    name: string;
    path: string;
    document: unknown;
    files: FactoryFilesPayload;
    scenario: FactoryScenarioInput;
    warnings: string[];
  }): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running a pipeline.");
    const context = { flavor: request.flavor, pipelineName: request.name, path: request.path, scenario: request.scenario };
    const { scenario, errors } = toFactoryScenario(request.scenario);
    if (errors.length) {
      const factoryRun = toFactoryLabView(
        { status: "error", issues: errors.map(message => ({ path: "scenario", message, severity: "error" })) },
        { ...context, warnings: request.warnings }
      );
      this.runtime.update({ detail: `Pipeline ${request.name} not run: fix the scenario.`, factoryRun });
      return;
    }
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/factory/simulate`,
      {
        flavor: request.flavor,
        name: request.name,
        document: request.document,
        files: request.files,
        scenario,
        data_plane: request.scenario.dataPlane
      },
      60000
    );
    const factoryRun = toFactoryLabView(raw, { ...context, warnings: request.warnings });
    this.runtime.update({
      detail: factoryRun.run
        ? `Pipeline ${request.name} ${factoryRun.run.status.toLowerCase()} (${factoryRun.flavorLabel}, ${factoryRun.dataPlane === "local" ? "local activities ran on the catalog" : "dry run"}).`
        : `Pipeline ${request.name} not run: ${factoryRun.issues[0]?.message ?? factoryRun.status}`,
      factoryRun
    });
    if (factoryRun.tablesChanged.length) await this.runtime.refreshCatalog();
  }

  /**
   * SQL pool Lab: the runtime translates the T-SQL script for a documented subset and runs the data
   * statements on the local catalog; distributions, partitions and plans are modelled. An empty
   * script only describes the pool's tables.
   */
  async runSqlPool(request: { flavor: SqlPoolFlavor; script: string; scale: number; source: string; warnings?: string[] }): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running a SQL pool script.");
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/sqlpool/run`,
      { flavor: request.flavor, script: request.script, scale: request.scale, source: sqlPoolSourceLabel(request.source) },
      60000
    );
    const sqlpoolRun = toSqlPoolView(raw, request);
    const failed = sqlpoolRun.statements.find(statement => statement.status === "error");
    this.runtime.update({
      detail: !request.script.trim()
        ? `SQL pool tables described (${sqlpoolRun.flavorLabel}).`
        : failed
          ? `SQL pool script stopped at statement ${failed.index} (line ${failed.line}): ${failed.message}`
          : `SQL pool script ran: ${sqlpoolRun.statements.length} statement(s) on the simulated ${sqlpoolRun.flavorLabel}.`,
      sqlpoolRun
    });
    if (request.script.trim()) await this.runtime.refreshCatalog();
  }

  /**
   * Databricks Lab: the runtime validates and simulates the job; notebook and SQL tasks run on the local
   * catalog under Unity Catalog rules (or not at all in a dry run).
   */
  async simulateDatabricks(request: {
    name: string;
    path: string;
    document: unknown;
    files: DatabricksFilesPayload;
    scenario: DatabricksScenarioInput;
    warnings: string[];
  }): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running a Databricks job.");
    const context = { jobName: request.name, path: request.path, scenario: request.scenario, warnings: request.warnings };
    const { scenario, errors } = toDatabricksScenario(request.scenario);
    if (errors.length) {
      const databricksRun = toDatabricksLabView({ status: "error", issues: errors.map(message => ({ path: "scenario", message })) }, context);
      this.runtime.update({ detail: `Job ${request.name} not run: fix the run settings.`, databricksRun });
      return;
    }
    const raw = await this.runtime.postJson<unknown>(
      `${url}/api/local/databricks/run`,
      { name: request.name, document: request.document, files: request.files, scenario, data_plane: request.scenario.dataPlane },
      60000
    );
    const databricksRun = toDatabricksLabView(raw, context);
    const record = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
    this.runtime.update({
      detail: databricksRun.run
        ? `Job ${request.name}: ${databricksRun.run.statusLabel} (${databricksRun.dataPlane === "local" ? "tasks ran on the local catalog" : "dry run"}).`
        : `Job ${request.name} not run: ${databricksRun.issues[0]?.message ?? databricksRun.status}`,
      databricksRun,
      databricksState: record.unity ? toDatabricksStateView(raw) : this.runtime.state().databricksState
    });
    if (databricksRun.tablesChanged.length) await this.runtime.refreshCatalog();
  }

  /** Databricks Lab: Unity Catalog, MLflow and compute as they are, without running a job. */
  async exploreDatabricks(files: DatabricksFilesPayload): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) return;
    const raw = await this.runtime.postJson<unknown>(`${url}/api/local/databricks/state`, { files }, 20000);
    this.runtime.update({ databricksState: toDatabricksStateView(raw) });
  }
}

/** The script's workspace path as the run journal's label; anything the runtime would refuse is dropped. */
function sqlPoolSourceLabel(source: string): string {
  return /^[A-Za-z0-9_./ -]{0,200}$/.test(source) ? source : "";
}
