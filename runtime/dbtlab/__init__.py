"""dbt Lab emulation: dbt projects interpreted by Datapass on the local DuckDB catalog, without dbt Core.

Jinja is rendered in jinja2's sandbox with a dbt-like context (ref, source, config, var, this, is_incremental,
macros); nothing in a project is executed as Python. The SQL it produces really runs on DuckDB. Materializations,
snapshots, tests and `dbt build` follow dbt Core and dbt-duckdb for a documented subset (see README.md); it is not
dbt Core, and `scripts/dbt_oracle_smoke.py` compares it with the real thing when dbt Core is installed.
"""
