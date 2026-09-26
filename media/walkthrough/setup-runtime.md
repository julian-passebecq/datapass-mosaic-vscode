# The local runtime

Everything Datapass runs happens on your machine: one local service bound to `127.0.0.1`, with its own managed
Python environment. **Set up runtime** creates that environment once (with `uv` it takes well under a minute; with
pip, a few minutes). Then **Start runtime** from the status bar item `Datapass: stopped` or from the Workbench.

Nothing connects to a cloud. Labs say on screen what is real (DuckDB, Polars, dbt Core, your shell) and what is
simulated (Airflow, Fabric and Databricks pipelines, Terraform, Kubernetes).
