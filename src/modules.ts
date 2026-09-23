export type ModuleId = "mosaic" | "practice" | "fabric" | "sparklab" | "dbt" | "airflow" | "pipeline";

export interface WorkbenchModule {
  id: ModuleId;
  label: string;
  description: string;
  command: string;
  execution: string;
}

export const MODULES: readonly WorkbenchModule[] = [
  {id:"mosaic",label:"Mosaic",description:"Flexible multi-pane workspace for local Polars, DuckDB, data and charts.",command:"datapass.openMosaic",execution:"Real Polars + DuckDB"},
  {id:"practice",label:"Practice",description:"LeetCode-style data-engineering exercises using native VS Code files and tests.",command:"datapass.openPractice",execution:"Native files + local runners"},
  {id:"fabric",label:"Fabric Lab",description:"Fabric-inspired local lakehouse, notebook and pipeline practice without Fabric.",command:"datapass.openFabricLab",execution:"DuckDB/DuckLake + SparkLab"},
  {id:"sparklab",label:"SparkLab / ZilaCode",description:"Deterministic PySpark DataFrame training without a cluster.",command:"datapass.openSparkLab",execution:"Spark-like API over local engines"},
  {id:"dbt",label:"dbt Lab",description:"dbt models, tests and manifest-backed lineage.",command:"datapass.openDbtLab",execution:"Real dbt Core + DuckDB"},
  {id:"airflow",label:"Airflow Lab",description:"DAG scheduling, retries, task states and logs as a local simulator.",command:"datapass.openAirflowLab",execution:"Simulated scheduler"},
  {id:"pipeline",label:"Pipeline Lab",description:"Visual orchestration of notebooks, SQL, copy and procedure-like activities.",command:"datapass.openPipelineLab",execution:"Local workflow engine"}
] as const;

export function getModule(id: ModuleId): WorkbenchModule {
  const found = MODULES.find(module => module.id === id);
  if (!found) throw new Error(`Unknown Datapass module: ${id}`);
  return found;
}
