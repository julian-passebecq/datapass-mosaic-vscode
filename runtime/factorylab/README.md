# Factory Lab (factorylab)

A local, deterministic simulator of Data Factory pipelines in three flavors:
Microsoft Fabric Data Factory (`fabric`), Azure Data Factory (`adf`) and Azure
Synapse pipelines (`synapse`). It reads real pipeline JSON: Fabric
`pipeline-content.json`, or the Data Factory / Synapse `pipeline/<name>.json`
git files. Nothing connects to Microsoft Fabric, Azure or Databricks.

## Truth model

| Part | What happens |
| --- | --- |
| Orchestration | Simulated with Data Factory semantics: dependency conditions (Succeeded, Failed, Skipped, Completed), AND across dependencies, skip propagation, the leaf rule for the run status, retries and timeouts, Inactive activities, ForEach (sequential or batchCount), If Condition, Switch, Until, Filter, variables, Execute/Invoke pipeline. Times are logical seconds. |
| Expressions | Evaluated by a bounded parser for the expression language (`@`, `@{}` interpolation, `@@`, `?.`, pipeline(), variables(), activity(), item(), common string, collection, logical, conversion, math and date functions). Unsupported functions are rejected by name. |
| Copy, Lookup, Script, stored procedures | Real local execution on the shared catalog (DuckDB) when the source and sink are lab tables (`bronze.orders`, ...). Other stores are simulated. |
| Notebooks | Fabric (TridentNotebook), Synapse (SynapseNotebook) and Azure Databricks (DatabricksNotebook) notebooks run on SparkLab, the bounded fake Spark, statement by statement through its whitelisted AST interpreter. Nothing is eval'd or exec'd. |
| Everything else | Web, Teams, Outlook, Azure Function, dataflows, Get Metadata, Delete: simulated. Their output comes from the scenario. |

A dry run (`data_plane: simulated`) simulates every work activity and changes no table.

A scenario can give an activity a duration, failing attempts, failing ForEach
items, an output merged into its own, or a sequence of outputs, one per run of
the activity, for polling loops.

Design-time rules follow Data Factory's. One of them: a Set variable cannot
reference the variable it sets, so count through a second variable.

## Differences between the products

The same JSON model, with product-specific activities:

| Need | Fabric | Azure Data Factory | Synapse |
| --- | --- | --- | --- |
| Run a notebook | `TridentNotebook` (`notebookId`) | `DatabricksNotebook` (`notebookPath`) | `SynapseNotebook` (`notebook.referenceName`) |
| Notebook exit value | `output.result.exitValue` | `output.runOutput` | `output.status.Output.result.exitValue` |
| Call a pipeline | `InvokePipeline` (legacy `ExecutePipeline`) | `ExecutePipeline` | `ExecutePipeline` |
| Low-code transform | `RefreshDataflow` (Dataflow Gen2) | `ExecuteDataFlow` | `ExecuteDataFlow` |
| Notify | `Teams`, `Office365Outlook` | `WebActivity` to a webhook or Logic App | `WebActivity` |
| Stored procedure | `SqlServerStoredProcedure` | `SqlServerStoredProcedure` | `SqlPoolStoredProcedure` (dedicated SQL pool) |
| Data access | Connections and inline `datasetSettings` | Linked services and datasets by name | Linked services and datasets by name |
| `@pipeline().DataFactory` | Workspace name | Data factory name | Workspace name |

Using an activity in a product that does not have it is a validation error that names the equivalent.

## Lab files

- Stored procedures: `factory/sql/procedures/<schema>.<name>.sql`. The body is
  DuckDB SQL with T-SQL style `@parameters`. An optional
  `CREATE PROCEDURE name @p TYPE [= default] AS` header declares the parameters,
  and calls are checked like SQL Server checks them. T-SQL itself is not emulated.
- Notebooks:
  - Fabric: `factory/fabric/<name>.Notebook/notebook-content.py` (git format).
    Pipeline parameters are injected after the cell marked
    `# PARAMETERS CELL`, or at the top when there is none. At the top, later
    assignments overwrite them, and the lab reports it.
  - Databricks: `factory/databricks/<path>.py` (source format). Parameters are
    read with `dbutils.widgets.get`.
  - Synapse: `factory/synapse/notebook/<name>.py`.
- Notebook helpers: `df.write.mode(...).saveAsTable("layer.table")`. The
  default save mode is errorifexists, as in Spark. Also supported:
  - `spark.sql(...)` (queries become DataFrames, other statements run);
  - `df.count()`;
  - `notebookutils` / `mssparkutils` / `dbutils` `.notebook.exit(value)`;
  - `display` and `print`, which are no-ops.

## Practice exercises

`exercise.py` defines the fixture scenario of the `factory` and `factory-notebook` Practice languages: the product, the
run settings, the lab files, and tables for an isolated local catalog. It also defines the outcome tables that are
graded. `datapass_runtime/factory_grading.py` runs them, and the `cloud-pipelines-v1` pack uses them (see
`docs/EXERCISE_AUTHORING.md`).

## Limits

- At most 120 activities per pipeline.
- Until stops after 100 iterations.
- Child pipelines nest at most 5 levels.
- Lookup reads at most 200 rows, against Data Factory's 5,000.
- Triggers (schedule, tumbling window, storage events) are not simulated. The scenario sets the trigger type and time.
