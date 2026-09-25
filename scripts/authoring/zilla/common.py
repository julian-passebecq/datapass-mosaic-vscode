"""Spec helpers for the zilla-v1 pack (see scripts/authoring/gen_zilla.py)."""
from __future__ import annotations

import textwrap

SPECS: list[dict] = []


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def rows(columns: str, *values: tuple) -> list[dict]:
    names = columns.split()
    for value in values:
        assert len(value) == len(names), (columns, value)
    return [dict(zip(names, value)) for value in values]


def problem(**spec) -> None:
    """One ZillaCode problem as a Datapass semantic scenario.

    Required: n, slug, title, difficulty, topics, tables {table: {column: TYPE}}, prompt, output, pitfall, hints,
    explanation, sql, python, polars. Optional: rename_tables {source: ours}, rename {source column: ours},
    ordered, order_text, grain, visible / hidden (tables, overriding ZillaCode's tests 1 and 2; hidden=False drops it),
    edges [(check id, description, tables)], sparklab, snowflake ('same' reuses sql), dbt ('auto' derives it from
    sql), dbt_model, mutants {language: [source]}, changes [text], ops [operation], objectives, reflection.
    """
    for key in ("n", "slug", "title", "difficulty", "topics", "tables", "prompt", "output", "pitfall", "hints",
                "explanation", "sql", "python", "polars"):
        assert key in spec, (spec.get("n"), key)
    SPECS.append(spec)
