import { runtimeErrorDetail } from "../../platform/runtimeClient";
import type { TranslatedDialectId } from "../../platform/sqlDialect";
import type { CsvImportView, LocalCellRunView, QueryPlanView, TableProfileView } from "../../webview/contracts";
import type { RuntimeConnection } from "../runtimeConnection";

/** Mosaic: SQL and trusted Python on the local catalog, file imports, profiles and query plans. */
export class MosaicClient {
  constructor(private readonly runtime: RuntimeConnection) {}

  /** Send CSV TEXT (never a path) to create a new bronze table; the runtime refuses overwrites. */
  async importCsv(asset: string, text: string, fileName: string): Promise<CsvImportView> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before importing a CSV.");
    let response: Omit<CsvImportView, "fileName">;
    try {
      response = await this.runtime.postJson<Omit<CsvImportView, "fileName">>(
        `${url}/api/local/import-csv`,
        { asset, text },
        30000
      );
    } catch (error) {
      throw new Error(`CSV import refused: ${runtimeErrorDetail(error)}`);
    }
    const csvImport: CsvImportView = {
      asset: response.asset,
      fileName,
      rows_imported: response.rows_imported,
      sha256: response.sha256,
      schema: response.schema,
      truth: response.truth,
      result: response.result
    };
    this.runtime.update({
      detail: `Imported ${csvImport.rows_imported} rows from ${fileName} into ${csvImport.asset} (all columns are text).`,
      lastRun: undefined,
      csvImport
    });
    await this.runtime.refreshCatalog();
    return csvImport;
  }

  /** Runs a SQL file on the catalog; with a dialect, the runtime translates it to DuckDB first (runtime/sqldialects). */
  async runSql(code: string, dialect?: TranslatedDialectId): Promise<LocalCellRunView> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running SQL.");
    const lastRun = await this.runtime.postJson<LocalCellRunView>(
      `${url}/api/local/execute`,
      {
        language: "sql",
        code,
        notebook_id: "vscode-sql",
        cell_id: "active-sql",
        ...(dialect ? { dialect } : {})
      },
      dialect ? 30000 : 10000
    );
    const translated = lastRun.dialect ? ` (${lastRun.dialect.label})` : "";
    this.runtime.update({
      detail: lastRun.status === "success"
        ? `SQL completed in ${lastRun.elapsed_ms.toFixed(1)} ms${translated}.`
        : `SQL failed: ${lastRun.error?.message ?? "Unknown error"}`,
      lastRun,
      csvImport: undefined
    });
    await this.runtime.refreshCatalog();
    return lastRun;
  }

  /** Parquet or JSON CONTENT (base64) into a new bronze table; the runtime keeps the file's types. */
  async importFile(asset: string, format: "parquet" | "json", data: string, fileName: string): Promise<CsvImportView> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before importing a file.");
    let response: Omit<CsvImportView, "fileName">;
    try {
      response = await this.runtime.postJson<Omit<CsvImportView, "fileName">>(
        `${url}/api/local/import-file`, { asset, format, data }, 120000);
    } catch (error) {
      throw new Error(`${format === "parquet" ? "Parquet" : "JSON"} import refused: ${runtimeErrorDetail(error)}`);
    }
    const fileImport: CsvImportView = { ...response, fileName, format };
    this.runtime.update({
      detail: `Imported ${fileImport.rows_imported} rows from ${fileName} into ${fileImport.asset} (typed columns).`,
      lastRun: undefined,
      csvImport: fileImport
    });
    await this.runtime.refreshCatalog();
    return fileImport;
  }

  /** DuckDB SUMMARIZE of a catalog table. */
  async profileTable(asset: string): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before profiling a table.");
    let tableProfile: TableProfileView;
    try {
      tableProfile = await this.runtime.postJson<TableProfileView>(`${url}/api/local/profile`, { asset }, 60000);
    } catch (error) {
      throw new Error(`Profile refused: ${runtimeErrorDetail(error)}`);
    }
    this.runtime.update({ detail: `Profiled ${asset} in ${tableProfile.elapsed_ms.toFixed(1)} ms.`, tableProfile });
  }

  /** DuckDB EXPLAIN ANALYZE of one read-only query: it runs once to time each operator. */
  async explainQuery(query: string, source?: string, dialect?: TranslatedDialectId): Promise<QueryPlanView> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before explaining a query.");
    let plan: QueryPlanView;
    try {
      plan = { ...await this.runtime.postJson<QueryPlanView>(`${url}/api/local/explain`, { query, ...(dialect ? { dialect } : {}) }, 60000), source };
    } catch (error) {
      throw new Error(`EXPLAIN ANALYZE refused: ${runtimeErrorDetail(error)}`);
    }
    this.runtime.update({ detail: `Query plan measured in ${plan.elapsed_ms.toFixed(1)} ms.`, queryPlan: plan });
    return plan;
  }

  async runPython(code: string): Promise<void> {
    const url = this.runtime.runningUrl();
    if (!url) throw new Error("Start the Datapass runtime before running Python.");
    if (!this.runtime.state().trustedPython) {
      throw new Error("Trusted local Python is disabled for this runtime. Enable it for the workspace, then restart the runtime.");
    }
    const lastRun = await this.runtime.postJson<LocalCellRunView>(
      `${url}/api/local/execute`,
      {
        language: "python",
        code,
        notebook_id: "vscode-python",
        cell_id: "active-python"
      },
      25000
    );
    this.runtime.update({
      detail: lastRun.status === "success"
        ? `Python completed in ${lastRun.elapsed_ms.toFixed(1)} ms (trusted local execution).`
        : `Python failed: ${lastRun.error?.message ?? "Unknown error"}`,
      lastRun,
      csvImport: undefined
    });
    await this.runtime.refreshCatalog();
  }
}
