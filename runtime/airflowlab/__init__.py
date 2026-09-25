"""Airflow Lab: a bounded, deterministic Airflow teaching simulator.

DAG files are parsed from a whitelisted AST and never executed. The scheduler
and task-instance model follow Airflow 3 semantics for the supported subset;
nothing here is an Airflow scheduler, executor or worker.
"""
