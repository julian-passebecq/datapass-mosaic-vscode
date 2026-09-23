export type ModuleId = "mosaic" | "practice" | "fabric" | "sparklab" | "dbt" | "airflow" | "pipeline";
export type ExecutionMode = "real" | "simulated" | "hybrid";

export interface WorkbenchModule {
  id: ModuleId;
  label: string;
  description: string;
  command: string;
  execution: string;
  mode: ExecutionMode;
  highlights: readonly string[];
}

export const MODULES: readonly WorkbenchModule[] = [
  {
    id:"mosaic",
    label:"Mosaic",
    description:"Flexible multi-pane workspace for local Polars, DuckDB, data and charts.",
    command:"datapass.openMosaic",
    execution:"Real Polars + DuckDB",
    mode:"real",
    highlights:["Mosaic notebook/layout core","Polars + DuckDB execution","Data, charts and docs in one workspace"]
  },
  {
    id:"practice",
    label:"Practice",
    description:"LeetCode-style data-engineering exercises using native VS Code files and tests.",
    command:"datapass.openPractice",
    execution:"Native files + local runners",
    mode:"hybrid",
    highlights:["Versioned exercise packs","Native VS Code starter files","Tests, hints and review state"]
  },
  {
    id:"fabric",
    label:"Fabric Lab",
    description:"Fabric-inspired local lakehouse, notebook and pipeline practice without Fabric.",
    command:"datapass.openFabricLab",
    execution:"DuckDB/DuckLake + SparkLab",
    mode:"simulated",
    highlights:["Lakehouse + notebook workflow","Pipeline orchestration canvas","Explicitly local Fabric-style semantics"]
  },
  {
    id:"sparklab",
    label:"SparkLab / ZilaCode",
    description:"Deterministic PySpark DataFrame training without a cluster.",
    command:"datapass.openSparkLab",
    execution:"Spark-like API over local engines",
    mode:"simulated",
    highlights:["Bounded PySpark DataFrame API","Deterministic local execution","Physical/cost teaching profiles"]
  },
  {
    id:"dbt",
    label:"dbt Lab",
    description:"dbt models, tests and manifest-backed lineage.",
    command:"datapass.openDbtLab",
    execution:"Real dbt Core + DuckDB",
    mode:"hybrid",
    highlights:["Real dbt Core where installed","DuckDB development target","Manifest lineage + test results"]
  },
  {
    id:"airflow",
    label:"Airflow Lab",
    description:"DAG scheduling, retries, task states and logs as a local simulator.",
    command:"datapass.openAirflowLab",
    execution:"Simulated scheduler",
    mode:"simulated",
    highlights:["DAG dependencies","Retries + trigger rules","Task state and log simulation"]
  },
  {
    id:"pipeline",
    label:"Pipeline Lab",
    description:"Visual orchestration of notebooks, SQL, copy and procedure-like activities.",
    command:"datapass.openPipelineLab",
    execution:"Local workflow engine",
    mode:"simulated",
    highlights:["React Flow orchestration","Notebook / SQL / copy activities","Run history and dependency validation"]
  }
] as const;

export function getModule(id: ModuleId): WorkbenchModule {
  const found = MODULES.find(module => module.id === id);
  if (!found) throw new Error(`Unknown Datapass module: ${id}`);
  return found;
}
