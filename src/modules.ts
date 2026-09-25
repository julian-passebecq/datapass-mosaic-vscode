export type ModuleId = "projects" | "mosaic" | "practice" | "fabric" | "bi" | "sparklab" | "dbt" | "airflow" | "pipeline";
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
    id:"projects",
    label:"Projects",
    description:"End-to-end projects whose steps are done in the labs, with checkboxes that follow your progress.",
    command:"datapass.openProjects",
    execution:"Steps verified on your workspace; each check says real, simulated or emulated",
    mode:"hybrid",
    highlights:["Three stories across every lab","Verified checks apart from ticks by hand","Progress in .datapass/progress.json"]
  },
  {
    id:"mosaic",
    label:"Mosaic",
    description:"Flexible multi-pane workspace for local Polars, DuckDB, data and charts.",
    command:"datapass.openMosaic",
    execution:"Real DuckDB SQL + opt-in trusted Python/Polars",
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
    label:"Cloud Lab",
    description:"Fabric, Azure Data Factory and Synapse pipelines with notebooks and stored procedures, simulated on the local lakehouse.",
    command:"datapass.openFabricLab",
    execution:"Simulated orchestration + local DuckDB/SparkLab activities",
    mode:"hybrid",
    highlights:["Real pipeline JSON for Fabric, ADF and Synapse","Notebooks and stored procedures on the local lakehouse","Product differences made explicit"]
  },
  {
    id:"bi",
    label:"BI Lab",
    description:"Data warehousing on the local DuckDB catalog: star schemas, slowly changing dimensions, SQL lineage and model checks.",
    command:"datapass.openBiLab",
    execution:"Real DuckDB + SQL lineage analysis",
    mode:"real",
    highlights:["Warehouse SQL runs on DuckDB","Column lineage and impact from the SQL text","Star model checks: keys, grain, SCD2, relationships"]
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
    description:"Airflow 3 DAG files simulated locally: runs, task states, retries and logs.",
    command:"datapass.openAirflowLab",
    execution:"Simulated scheduler",
    mode:"simulated",
    highlights:["Real Airflow 3 DAG files, parsed not run","Runs, catchup and timetables","Grid, replay, trigger rules and retries"]
  },
  {
    id:"pipeline",
    label:"Pipeline Lab",
    description:"Visual orchestration of notebooks, SQL, copy and procedure-like activities.",
    command:"datapass.openPipelineLab",
    execution:"Bounded compiler + real local activity execution",
    mode:"hybrid",
    highlights:["React Flow orchestration","Notebook / SQL / copy activities","Run history and dependency validation"]
  }
] as const;

export function getModule(id: ModuleId): WorkbenchModule {
  const found = MODULES.find(module => module.id === id);
  if (!found) throw new Error(`Unknown Datapass module: ${id}`);
  return found;
}
