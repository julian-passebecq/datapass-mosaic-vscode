"""Databricks Lab: a local, deterministic simulator of Azure Databricks jobs, compute, Unity Catalog and MLflow.

Job definitions are Jobs API JSON. Notebook tasks run on SparkLab's whitelisted
interpreter and SQL tasks on DuckDB, against the lab's local catalog; the
orchestration, the compute (clusters, serverless, SQL warehouses) and its cost are
simulated. Nothing connects to Azure Databricks.
"""
