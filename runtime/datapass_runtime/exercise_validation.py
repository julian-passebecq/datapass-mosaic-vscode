"""Bounded result contracts. No keyword heuristics or client-owned expectations."""
import ast
import math
from numbers import Real


def validate_result(result, expected, spec, source='', language='sql'):
    rows = result.get('rows', [])
    columns = result.get('columns', [])
    if result.get('truncated', True):
        return False
    if spec.source_contract:
        if language not in {'python', 'polars'}:
            return False
        tree = ast.parse(source)
        if not any(isinstance(n, ast.FunctionDef) and n.name == 'solve' for n in tree.body):
            return False
    if not set(spec.required_columns).issubset(columns):
        return False
    if spec.exact_schema is not None and columns != spec.exact_schema:
        return False
    if expected and spec.forbidden_extra_columns and set(columns) != set(expected[0]):
        return False
    if spec.row_count is not None and len(rows) != spec.row_count:
        return False
    if spec.null_semantics == 'forbidden' and any(v is None for r in rows for v in r.values()):
        return False

    def equal(a, b):
        if isinstance(a, Real) and not isinstance(a, bool) and isinstance(b, Real) and not isinstance(b, bool):
            return math.isclose(a, b, rel_tol=spec.relative_tolerance, abs_tol=spec.absolute_tolerance)
        return type(a) is type(b) and a == b

    def row_equal(a, b):
        return (set(a) == set(b) if spec.forbidden_extra_columns else set(b).issubset(a)) and all(equal(a[k], v) for k, v in b.items())

    if spec.aggregates:
        def aggregate(data):
            out = {}
            for col, op in spec.aggregates.items():
                if any(col not in r for r in data):
                    raise ValueError('Missing aggregate column')
                values = [r[col] for r in data if r[col] is not None]
                out[col] = len(values) if op == 'count' else (sum(values) if op == 'sum' else (min(values) if op == 'min' else max(values))) if values else None
            return out
        try:
            return row_equal(aggregate(rows), aggregate(expected))
        except (TypeError, ValueError):
            return False
    if not spec.duplicate_sensitive:
        def unique(data):
            out = []
            for row in data:
                if not any(row_equal(row, other) for other in out):
                    out.append(row)
            return out
        rows, expected = unique(rows), unique(expected)
    if len(rows) != len(expected):
        return False
    if spec.ordered:
        return all(row_equal(a, b) for a, b in zip(rows, expected))
    # Bipartite matching avoids greedy tolerance matches rejecting valid alternatives.
    matches = {}
    def match(i, seen):
        for j, candidate in enumerate(expected):
            if j not in seen and row_equal(rows[i], candidate):
                seen.add(j)
                if j not in matches or match(matches[j], seen):
                    matches[j] = i
                    return True
        return False
    return all(match(i, set()) for i in range(len(rows)))
