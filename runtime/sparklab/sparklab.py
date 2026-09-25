"""SparkLab: a deliberately small PySpark-style teaching runtime.

SparkLab does NOT implement Apache Spark. It provides two separate teaching paths:
1. compile supported PySpark-style DataFrame operations to DuckDB-compatible SQL so
   the transformation can run against real Parquet/DuckLake data;
2. estimate Spark-like distributed behaviour from measured case-study statistics.

The distributed estimates are educational, not cluster telemetry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
import json
import re


@dataclass(frozen=True, eq=False)
class WindowSpec:
    partition_cols: tuple[str, ...] = ()
    order_exprs: tuple[str, ...] = ()
    frame: str | None = None

    def partitionBy(self, *cols: str) -> "WindowSpec":
        return WindowSpec(tuple(cols), self.order_exprs, self.frame)

    def orderBy(self, *cols: str | "Expr") -> "WindowSpec":
        exprs = tuple(_order_sql(c) for c in cols)
        return WindowSpec(self.partition_cols, exprs, self.frame)

    def rowsBetween(self, start: int, end: int) -> "WindowSpec":
        if type(start) is not int or type(end) is not int or start > end:
            raise ValueError('rowsBetween requires integer bounds with start <= end')
        return WindowSpec(self.partition_cols, self.order_exprs, f"ROWS BETWEEN {_frame_bound(start)} AND {_frame_bound(end)}")

    def sql(self) -> str:
        bits: list[str] = []
        if self.partition_cols:
            bits.append("PARTITION BY " + ", ".join(_quote(c) for c in self.partition_cols))
        if self.order_exprs:
            bits.append("ORDER BY " + ", ".join(self.order_exprs))
        if self.frame:
            bits.append(self.frame)
        return " ".join(bits)


class Window:
    # Match the commonly used PySpark constants closely enough for explicit
    # rowsBetween() training syntax. Spark treats sufficiently extreme bounds
    # as unbounded; using the canonical 64-bit sentinels keeps the API familiar.
    unboundedPreceding = -9223372036854775808
    unboundedFollowing = 9223372036854775807
    currentRow = 0

    @staticmethod
    def partitionBy(*cols: str) -> WindowSpec:
        return WindowSpec(partition_cols=tuple(cols))

    @staticmethod
    def orderBy(*cols: str | "Expr") -> WindowSpec:
        return WindowSpec(order_exprs=tuple(_order_sql(c) for c in cols))


@dataclass(frozen=True, eq=False)
class Expr:
    sql: str
    label: str | None = None

    def alias(self, name: str) -> "Expr":
        return Expr(self.sql, name)

    def over(self, window: WindowSpec) -> "Expr":
        if self.sql.startswith(('ROW_NUMBER()', 'LAG(', 'LEAD(')) and not window.order_exprs:
            raise ValueError('Ranking and offset windows require orderBy; include a tie-breaker for deterministic rows')
        if self.sql.startswith(('LAG(', 'LEAD(')) and window.frame:
            raise ValueError('lag/lead do not accept an explicit window frame; apply rowsBetween only to aggregates')
        return Expr(f"{self.sql} OVER ({window.sql()})", self.label)

    def desc(self) -> "Expr":
        return Expr(f"{self.sql} DESC NULLS LAST", self.label)

    def asc(self) -> "Expr":
        return Expr(f"{self.sql} ASC NULLS FIRST", self.label)

    def isNull(self) -> "Expr":
        return Expr(f"({self.sql} IS NULL)")

    def isNotNull(self) -> "Expr":
        return Expr(f"({self.sql} IS NOT NULL)")

    def cast(self, data_type: str) -> "Expr":
        normalized = str(data_type).strip().lower()
        simple = {
            "string": "VARCHAR", "str": "VARCHAR",
            "int": "INTEGER", "integer": "INTEGER",
            "long": "BIGINT", "bigint": "BIGINT",
            "double": "DOUBLE", "float": "REAL",
            "boolean": "BOOLEAN", "bool": "BOOLEAN",
            "date": "DATE", "timestamp": "TIMESTAMP",
        }
        if re.fullmatch(r"decimal\(\s*\d{1,2}\s*,\s*\d{1,2}\s*\)", normalized):
            precision, scale = map(int, re.findall(r'\d+', normalized))
            if not 1 <= precision <= 38 or not 0 <= scale <= precision:
                raise ValueError('decimal precision must be 1..38 and scale 0..precision')
            target = normalized.upper()
        else:
            target = simple.get(normalized)
        if target is None:
            raise ValueError(f"Unsupported cast type: {data_type}")
        return Expr(f"CAST({self.sql} AS {target})", self.label)

    def isin(self, *values: Any) -> "Expr":
        if not values:
            return Expr("FALSE")
        return Expr(f"({self.sql} IN ({', '.join(_literal(v) for v in values)}))")

    def between(self, lower: Any, upper: Any) -> "Expr":
        return Expr(f"({self.sql} BETWEEN {_literal(lower)} AND {_literal(upper)})")

    def otherwise(self, value: Any) -> "Expr":
        marker = " END"
        if not self.sql.startswith("CASE WHEN ") or not self.sql.endswith(marker):
            raise ValueError("otherwise() is only valid on an expression created by when()")
        return Expr(self.sql[:-len(marker)] + f" ELSE {_literal(value) if not isinstance(value, Expr) else value.sql} END", self.label)

    def when(self, condition: "Expr", value: Any) -> "Expr":
        marker = " END"
        if not self.sql.startswith("CASE WHEN ") or not self.sql.endswith(marker):
            raise ValueError("when() chaining is only valid on an expression created by when()")
        rendered = value.sql if isinstance(value, Expr) else _literal(value)
        return Expr(self.sql[:-len(marker)] + f" WHEN {condition.sql} THEN {rendered} END", self.label)

    def _bin(self, op: str, other: Any) -> "Expr":
        rhs = other.sql if isinstance(other, Expr) else _literal(other)
        return Expr(f"({self.sql} {op} {rhs})")

    def __gt__(self, other: Any): return self._bin('>', other)
    def __ge__(self, other: Any): return self._bin('>=', other)
    def __lt__(self, other: Any): return self._bin('<', other)
    def __le__(self, other: Any): return self._bin('<=', other)
    def __eq__(self, other: Any): return self._bin('=', other)  # type: ignore[override]
    def __ne__(self, other: Any): return self._bin('<>', other)  # type: ignore[override]
    def __and__(self, other: Any): return self._bin('AND', other)
    def __or__(self, other: Any): return self._bin('OR', other)
    def __invert__(self): return Expr(f"(NOT {self.sql})")
    def __add__(self, other: Any): return self._bin('+', other)
    def __sub__(self, other: Any): return self._bin('-', other)
    def __mul__(self, other: Any): return self._bin('*', other)
    def __truediv__(self, other: Any): return self._bin('/', other)

    def eqNullSafe(self, other: Any):
        rhs = other.sql if isinstance(other, Expr) else _literal(other)
        return Expr(f"({self.sql} IS NOT DISTINCT FROM {rhs})")

    def __bool__(self):
        raise ValueError('Spark Columns use parenthesized & and |, not Python truth evaluation')


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(v: Any) -> str:
    if v is None: return 'NULL'
    if isinstance(v, bool): return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, float)): return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _frame_bound(value: int) -> str:
    if value <= Window.unboundedPreceding: return "UNBOUNDED PRECEDING"
    if value >= Window.unboundedFollowing: return "UNBOUNDED FOLLOWING"
    if value == 0: return "CURRENT ROW"
    if value < 0: return f"{abs(value)} PRECEDING"
    return f"{value} FOLLOWING"


class functions:
    @staticmethod
    def col(name: str) -> Expr:
        if not isinstance(name, str) or '.' in name:
            raise ValueError('Qualified/nested columns are unsupported; rename columns before joining')
        return Expr(_quote(name), name)
    @staticmethod
    def lit(value: Any) -> Expr: return Expr(_literal(value))
    @staticmethod
    def when(condition: Expr, value: Any) -> Expr:
        rendered = value.sql if isinstance(value, Expr) else _literal(value)
        return Expr(f"CASE WHEN {condition.sql} THEN {rendered} END")
    @staticmethod
    def sum(name: str | Expr) -> Expr: return Expr(f"SUM({_sql(name)})")
    @staticmethod
    def avg(name: str | Expr) -> Expr: return Expr(f"AVG({_sql(name)})")
    @staticmethod
    def min(name: str | Expr) -> Expr: return Expr(f"MIN({_sql(name)})")
    @staticmethod
    def max(name: str | Expr) -> Expr: return Expr(f"MAX({_sql(name)})")
    @staticmethod
    def count(name: str | Expr = '*') -> Expr: return Expr(f"COUNT({_sql(name)})")
    @staticmethod
    def countDistinct(name: str | Expr) -> Expr: return Expr(f"COUNT(DISTINCT {_sql(name)})")
    @staticmethod
    def row_number() -> Expr: return Expr("ROW_NUMBER()")
    @staticmethod
    def lag(name: str | Expr, offset: int = 1, default: Any | None = None) -> Expr:
        args = [_sql(name), str(offset)]
        if default is not None: args.append(_literal(default))
        return Expr(f"LAG({', '.join(args)})")
    @staticmethod
    def lead(name: str | Expr, offset: int = 1, default: Any | None = None) -> Expr:
        args = [_sql(name), str(offset)]
        if default is not None: args.append(_literal(default))
        return Expr(f"LEAD({', '.join(args)})")
    @staticmethod
    def to_date(name: str | Expr) -> Expr: return Expr(f"CAST({_sql(name)} AS DATE)")
    @staticmethod
    def date_trunc(unit: str, name: str | Expr) -> Expr: return Expr(f"DATE_TRUNC({_literal(unit)}, {_sql(name)})")
    @staticmethod
    def coalesce(*items: str | Expr) -> Expr: return Expr("COALESCE(" + ", ".join(_sql(x) for x in items) + ")")
    @staticmethod
    def broadcast(df: "DataFrame") -> "DataFrame":
        clone = df._clone()
        clone.hints.add('broadcast')
        return clone


def _sql(v: str | Expr) -> str:
    if isinstance(v, Expr): return v.sql
    return '*' if v == '*' else _quote(v)


def _order_sql(v: str | Expr) -> str:
    sql = _sql(v)
    return sql if re.search(r'\b(ASC|DESC)\b', sql) else sql + ' ASC NULLS FIRST'


@dataclass
class Op:
    kind: str
    detail: dict[str, Any] = field(default_factory=dict)


class GroupedData:
    def __init__(self, df: "DataFrame", keys: tuple[str, ...]):
        self.df, self.keys = df, keys

    def agg(self, *exprs: Expr) -> "DataFrame":
        clone = self.df._clone()
        clone.ops.append(Op('aggregate', {'keys': self.keys, 'exprs': exprs}))
        return clone


class DataFrame:
    def __init__(self, session: "SparkSession", source: str, ops: list[Op] | None = None):
        self.session = session
        self.source = source
        self.ops = list(ops or [])
        self.hints: set[str] = set()

    def _clone(self) -> "DataFrame":
        c = DataFrame(self.session, self.source, self.ops)
        c.hints = set(self.hints)
        return c

    def filter(self, expr: Expr) -> "DataFrame":
        c = self._clone(); c.ops.append(Op('filter', {'expr': expr})); return c
    where = filter

    def select(self, *cols: str | Expr) -> "DataFrame":
        if len(cols) == 1 and isinstance(cols[0], (list, tuple)):
            cols = tuple(cols[0])
        if not cols or any(not isinstance(c, (str, Expr)) for c in cols):
            raise ValueError('select requires column names or expressions')
        c = self._clone(); c.ops.append(Op('select', {'cols': cols})); return c

    def withColumn(self, name: str, expr: Expr) -> "DataFrame":
        c = self._clone(); c.ops.append(Op('withColumn', {'name': name, 'expr': expr})); return c

    def drop(self, *cols: str) -> "DataFrame":
        c = self._clone(); c.ops.append(Op('drop', {'cols': tuple(cols)})); return c

    def dropDuplicates(self, cols: Iterable[str] | None = None) -> "DataFrame":
        if isinstance(cols, str):
            raise ValueError('dropDuplicates expects a list of column names')
        c = self._clone(); c.ops.append(Op('dedupe', {'cols': None if cols is None else tuple(cols)})); return c

    def distinct(self) -> "DataFrame":
        c = self._clone(); c.ops.append(Op('distinct')); return c

    def groupBy(self, *keys: str) -> GroupedData:
        if len(keys) == 1 and isinstance(keys[0], (list, tuple)):
            keys = tuple(keys[0])
        return GroupedData(self, keys)

    def join(self, other: "DataFrame", on: str | Iterable[str], how: str = 'inner') -> "DataFrame":
        normalized = {'outer':'full', 'leftouter':'left', 'rightouter':'right', 'fullouter':'full', 'leftsemi':'left_semi', 'semi':'left_semi', 'leftanti':'left_anti', 'anti':'left_anti'}.get(how.lower(), how.lower())
        allowed = {'inner', 'left', 'right', 'full', 'left_outer', 'right_outer', 'full_outer', 'left_semi', 'left_anti'}
        if normalized not in allowed:
            raise ValueError(f"Unsupported join type: {how}")
        if isinstance(on, str):
            keys = (on,)
        elif isinstance(on, (list, tuple)) and all(isinstance(key, str) for key in on):
            keys = tuple(on)
        else:
            raise ValueError('join supports same-name string keys; rename columns before joining. Predicate joins are unsupported.')
        if not keys:
            raise ValueError("join() requires at least one key")
        c = self._clone()
        c.ops.append(Op('join', {'other': other, 'on': keys, 'how': normalized, 'broadcast': 'broadcast' in other.hints}))
        return c

    def withColumnRenamed(self, existing: str, new: str) -> "DataFrame":
        if not existing or not new:
            raise ValueError("withColumnRenamed() requires non-empty column names")
        c = self._clone(); c.ops.append(Op('rename', {'existing': existing, 'new': new})); return c

    def orderBy(self, *cols: str | Expr) -> "DataFrame":
        if len(cols) == 1 and isinstance(cols[0], (list, tuple)):
            cols = tuple(cols[0])
        if not cols:
            raise ValueError('orderBy requires at least one column')
        c = self._clone(); c.ops.append(Op('orderBy', {'cols': tuple(cols)})); return c

    sort = orderBy

    def alias(self, name: str) -> "DataFrame":
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_]\w*', name):
            raise ValueError('alias requires a simple name; qualified-column joins are unsupported')
        c = self._clone(); c.ops.append(Op('alias', {'name': name})); return c

    def limit(self, n: int) -> "DataFrame":
        if type(n) is not int or n < 0:
            raise ValueError('limit requires a non-negative integer')
        c = self._clone(); c.ops.append(Op('limit', {'n': n})); return c

    def repartition(self, n: int, *keys: str) -> "DataFrame":
        if type(n) is not int or not 1 <= n <= 4096:
            raise ValueError('Partition count must be an integer from 1 to 4096')
        c = self._clone(); c.ops.append(Op('repartition', {'n': n, 'keys': keys})); return c

    def coalesce(self, n: int) -> "DataFrame":
        if type(n) is not int or not 1 <= n <= 4096:
            raise ValueError('Partition count must be an integer from 1 to 4096')
        c = self._clone(); c.ops.append(Op('coalesce', {'n': n})); return c

    # Actions and writes exist only in pipeline notebooks, where a notebook runtime executes them.
    def count(self) -> int:
        runtime = self.session.notebook_runtime
        if runtime is None:
            raise ValueError('count() is an action; in SparkLab cells, Run shows the result instead')
        return runtime.count(self)

    @property
    def write(self) -> Any:
        from .notebook_utils import DataFrameWriter
        return DataFrameWriter(self)


    def _source_columns(self) -> list[str] | None:
        raw = self.session.profile.get('tables', {}).get(self.source, {}).get('columns')
        return [str(c) for c in raw] if isinstance(raw, list) else None

    def _columns_before(self, stop_index: int) -> list[str] | None:
        columns = self._source_columns()
        if columns is None:
            return None
        for op in self.ops[:stop_index]:
            if op.kind == 'select':
                rendered: list[str] = []
                for item in op.detail['cols']:
                    if isinstance(item, str):
                        if item == '*':
                            rendered.extend(c for c in columns if c not in rendered)
                        else:
                            rendered.append(item)
                    elif isinstance(item, Expr) and item.label:
                        rendered.append(item.label)
                    else:
                        return None
                columns = rendered
            elif op.kind == 'withColumn':
                name = str(op.detail['name'])
                if name not in columns:
                    columns.append(name)
            elif op.kind == 'drop':
                dropped = set(op.detail['cols'])
                columns = [c for c in columns if c not in dropped]
            elif op.kind == 'rename':
                existing, new = str(op.detail['existing']), str(op.detail['new'])
                columns = [new if c == existing else c for c in columns]
            elif op.kind == 'aggregate':
                labels = []
                for expr in op.detail['exprs']:
                    if not expr.label:
                        return None
                    labels.append(expr.label)
                columns = list(op.detail['keys']) + labels
            elif op.kind == 'join':
                if op.detail['how'] in {'left_semi', 'left_anti'}:
                    continue
                other_cols = op.detail['other'].current_columns()
                if other_cols is None:
                    return None
                keys = set(op.detail['on'])
                columns = list(op.detail['on']) + [c for c in columns if c not in keys] + [c for c in other_cols if c not in keys]
        return columns

    def current_columns(self) -> list[str] | None:
        return self._columns_before(len(self.ops))

    @property
    def sql(self) -> str:
        query = f'SELECT * FROM {self.source}'
        for idx, op in enumerate(self.ops):
            if op.kind == 'filter':
                query = f'SELECT * FROM ({query}) q{idx} WHERE {op.detail["expr"].sql}'
            elif op.kind == 'select':
                projection = ', '.join(_render_expr(x) for x in op.detail['cols'])
                query = f'SELECT {projection} FROM ({query}) q{idx}'
            elif op.kind == 'withColumn':
                expr: Expr = op.detail['expr']
                name = op.detail["name"]
                known = self._columns_before(idx)
                if known is not None:
                    projection = [f'{expr.sql} AS {_quote(name)}' if c == name else _quote(c) for c in known]
                    if name not in known:
                        projection.append(f'{expr.sql} AS {_quote(name)}')
                    query = f'SELECT {", ".join(projection)} FROM ({query}) q{idx}'
                else:
                    query = f'SELECT *, {expr.sql} AS {_quote(name)} FROM ({query}) q{idx}'
            elif op.kind == 'drop':
                known = self._columns_before(idx)
                if known is not None:
                    dropped = set(op.detail['cols'])
                    projection = ', '.join(_quote(c) for c in known if c not in dropped)
                    if not projection:
                        raise ValueError('drop() would remove every known column')
                    query = f'SELECT {projection} FROM ({query}) q{idx}'
                else:
                    excluded = ', '.join(_quote(c) for c in op.detail['cols'])
                    query = f'SELECT * EXCLUDE ({excluded}) FROM ({query}) q{idx}'
            elif op.kind == 'rename':
                known = self._columns_before(idx)
                existing, new = str(op.detail['existing']), str(op.detail['new'])
                if known is None:
                    raise ValueError('withColumnRenamed() requires a known schema in SparkLab')
                if existing not in known:
                    projection = ', '.join(_quote(c) for c in known)
                else:
                    projection = ', '.join(f'{_quote(c)} AS {_quote(new)}' if c == existing else _quote(c) for c in known)
                query = f'SELECT {projection} FROM ({query}) q{idx}'
            elif op.kind == 'dedupe':
                cols = op.detail['cols']
                if cols is None:
                    query = f'SELECT DISTINCT * FROM ({query}) q{idx}'
                else:
                    keys = 'PARTITION BY ' + ', '.join(_quote(c) for c in cols) if cols else ''
                    known = self._columns_before(idx)
                    projection = ', '.join(_quote(c) for c in known) if known is not None else '* EXCLUDE (__sparklab_rn)'
                    query = (
                        f'SELECT {projection} FROM ('
                        f'SELECT *, ROW_NUMBER() OVER ({keys}) AS __sparklab_rn '
                        f'FROM ({query}) q{idx}_src) q{idx}_ranked WHERE __sparklab_rn = 1'
                    )
            elif op.kind == 'distinct':
                query = f'SELECT DISTINCT * FROM ({query}) q{idx}'
            elif op.kind == 'aggregate':
                keys = ', '.join(_quote(k) for k in op.detail['keys'])
                vals = ', '.join(_render_expr(e) for e in op.detail['exprs'])
                select_list = ', '.join(x for x in (keys, vals) if x)
                query = f'SELECT {select_list} FROM ({query}) q{idx}'
                if keys:
                    query += f' GROUP BY {keys}'
            elif op.kind == 'join':
                other: DataFrame = op.detail['other']
                keys = tuple(op.detail["on"])
                key_set = set(keys)
                if op.detail['how'] in {'left_semi', 'left_anti'}:
                    predicate = ' AND '.join(f'l.{_quote(k)} = r.{_quote(k)}' for k in keys)
                    negation = 'NOT ' if op.detail['how'] == 'left_anti' else ''
                    query = f'SELECT l.* FROM ({query}) l WHERE {negation}EXISTS (SELECT 1 FROM ({other.sql}) r WHERE {predicate})'
                    continue
                join_sql = _join_sql(op.detail['how'])
                left_cols = self._columns_before(idx)
                right_cols = other.current_columns()
                if right_cols is not None and left_cols is not None:
                    if (set(left_cols) & set(right_cols)) - key_set:
                        raise ValueError('Duplicate non-key join columns are unsupported; use withColumnRenamed before join')
                    right_projection = ', '.join(f'r.{_quote(c)}' for c in right_cols if c not in key_set)
                    output_left = list(keys) + [c for c in left_cols if c not in key_set]
                    left_projection = ', '.join(f'COALESCE(l.{_quote(c)}, r.{_quote(c)}) AS {_quote(c)}' if c in key_set else f'l.{_quote(c)}' for c in output_left)
                    projection = left_projection + (f', {right_projection}' if right_projection else '')
                else:
                    raise ValueError('join requires known schemas; use registered catalog tables')
                using = ', '.join(_quote(key) for key in keys)
                query = f'SELECT {projection} FROM ({query}) l {join_sql} ({other.sql}) r USING ({using})'
            elif op.kind == 'orderBy':
                order = ', '.join(_sql(c) + (' ASC NULLS FIRST' if isinstance(c, str) or not re.search(r'\b(ASC|DESC)\b', c.sql) else '') for c in op.detail['cols'])
                query = f'SELECT * FROM ({query}) q{idx} ORDER BY {order}'
            elif op.kind == 'limit':
                query = f'SELECT * FROM ({query}) q{idx} LIMIT {int(op.detail["n"])}'
            elif op.kind in {'repartition', 'coalesce'}:
                # Partition-count operations affect Spark execution, not relational result semantics.
                continue
        return query

    def explain_training(self) -> dict[str, Any]:
        return self.session._estimate(self)


def _render_expr(value: str | Expr) -> str:
    if isinstance(value, Expr):
        return value.sql + (f' AS {_quote(value.label)}' if value.label else '')
    return '*' if value == '*' else _quote(value)


def _join_sql(how: str) -> str:
    mapping = {
        'inner': 'INNER JOIN',
        'left': 'LEFT JOIN', 'left_outer': 'LEFT JOIN',
        'right': 'RIGHT JOIN', 'right_outer': 'RIGHT JOIN',
        'full': 'FULL OUTER JOIN', 'full_outer': 'FULL OUTER JOIN',
    }
    return mapping[how]


class ReadBuilder:
    def __init__(self, session: "SparkSession"):
        self.session = session

    def parquet(self, path: str) -> DataFrame:
        return DataFrame(self.session, f"read_parquet({_literal(path)})")

    def table(self, name: str) -> DataFrame:
        return self.session.table(name)


class SparkSession:
    def __init__(self, profile: dict[str, Any]):
        self.profile = profile
        self.read = ReadBuilder(self)
        # Set only for pipeline notebooks: executes writes, spark.sql and count() on the local catalog.
        self.notebook_runtime: Any = None

    @classmethod
    def from_profile(cls, path: str | Path, case: str) -> "SparkSession":
        data = json.loads(Path(path).read_text())
        if case not in data:
            raise KeyError(f"Unknown SparkLab case profile: {case}")
        return cls(data[case])

    def table(self, name: str) -> DataFrame:
        runtime = self.notebook_runtime
        if runtime is not None and isinstance(name, str):
            name = runtime.table_name(name)
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?', name):
            raise ValueError('spark.table requires a simple catalog table name')
        if runtime is not None:
            # Tables written earlier in the same notebook exist only in the catalog, so ask it.
            self.profile.setdefault('tables', {})[name] = {'columns': runtime.columns(f'SELECT * FROM {name}')}
        return DataFrame(self, name)

    def sql(self, query: str) -> DataFrame | None:
        """spark.sql in a pipeline notebook: a query becomes a DataFrame, a statement runs at once."""
        runtime = self.notebook_runtime
        if runtime is None:
            raise ValueError('spark.sql runs in pipeline notebooks only; SparkLab cells use the DataFrame API')
        if not isinstance(query, str) or not query.strip():
            raise ValueError('spark.sql needs a SQL string')
        text = query.strip().rstrip(';').strip()
        if re.match(r'(?is)(select|with)\b', text):
            source = f'({text}) AS spark_sql'
            self.profile.setdefault('tables', {})[source] = {'columns': runtime.columns(text)}
            return DataFrame(self, source)
        runtime.statement(text)
        return None

    def _estimate(self, df: DataFrame) -> dict[str, Any]:
        table = self.profile.get('tables', {}).get(df.source, {})
        partitions = int(table.get('partitions', 1))
        bytes_ = int(table.get('bytes', 0))
        rows = int(table.get('rows', 0))
        stages: list[dict[str, Any]] = []
        shuffle_bytes = 0
        notes: list[str] = []
        confidence = 'medium' if bytes_ else 'low'

        window_exchange_seen = False
        for op in df.ops:
            if op.kind in {'filter', 'select', 'withColumn', 'drop', 'distinct', 'dedupe', 'orderBy', 'limit'}:
                boundary = 'narrow'
                if op.kind in {'dedupe', 'distinct', 'orderBy'}:
                    shuffle_bytes += bytes_
                    boundary = 'shuffle'
                if op.kind == 'withColumn':
                    expr_sql = op.detail['expr'].sql
                    if ' OVER (' in expr_sql and 'PARTITION BY' in expr_sql and not window_exchange_seen:
                        shuffle_bytes += bytes_
                        boundary = 'shuffle'
                        window_exchange_seen = True
                        notes.append('Window partitioning introduces one modeled exchange for this DataFrame plan')
                stages.append({'op': op.kind, 'boundary': boundary})
            elif op.kind == 'repartition':
                shuffle_bytes += bytes_
                partitions = int(op.detail['n'])
                stages.append({'op': 'repartition', 'boundary': 'shuffle', 'partitions': partitions})
            elif op.kind == 'coalesce':
                partitions = min(partitions, int(op.detail['n']))
                stages.append({'op': 'coalesce', 'boundary': 'narrow', 'partitions': partitions})
            elif op.kind == 'aggregate':
                shuffle_bytes += bytes_
                stages.append({'op': 'aggregate', 'boundary': 'shuffle'})
            elif op.kind == 'join':
                other: DataFrame = op.detail['other']
                other_t = self.profile.get('tables', {}).get(other.source, {})
                other_bytes = int(other_t.get('bytes', 0))
                other_mb = other_bytes / 1024 / 1024
                threshold = float(self.profile.get('broadcast_threshold_mb', 10))
                forced = bool(op.detail['broadcast'])
                catalog_stats = bool(self.profile.get('catalog_statistics_available', True))
                auto_candidate = catalog_stats and other_mb > 0 and other_mb <= threshold
                should_broadcast = forced or auto_candidate
                if should_broadcast:
                    stages.append({
                        'op': 'broadcast_hash_join', 'boundary': 'broadcast',
                        'right_mb': round(other_mb, 2), 'forced': forced,
                    })
                    mode = 'forced' if forced else 'auto candidate'
                    notes.append(f"Broadcast {mode}: {other.source} ({other_mb:.1f} MB)")
                else:
                    shuffle_bytes += bytes_ + other_bytes
                    stages.append({'op': 'sort_merge_join', 'boundary': 'shuffle', 'right_mb': round(other_mb, 2)})
                    if not catalog_stats and other_mb > 0 and other_mb <= threshold:
                        notes.append(
                            f"No auto broadcast: {other.source} is {other_mb:.1f} MB but catalog size statistics are unavailable"
                        )

        median = table.get('median_partition_mb')
        largest = table.get('largest_partition_mb')
        skew = round(float(largest) / float(median), 2) if median and largest else None
        if skew and skew >= 5:
            notes.append(f"High skew: largest partition is {skew:.1f}x the median")
        elif skew and skew >= 2:
            notes.append(f"Moderate skew: largest partition is {skew:.1f}x the median")

        spill_risk = 'unknown'
        executor_mem = self.profile.get('executor_memory_mb')
        if executor_mem and largest:
            ratio = float(largest) / float(executor_mem)
            spill_risk = 'high' if ratio >= 0.6 else 'medium' if ratio >= 0.3 else 'low'

        return {
            'real_result_engine': 'DuckDB/MotherDuck SQL (or Polars where selected)',
            'distributed_runtime': 'simulated',
            'estimate_confidence': confidence,
            'input_rows': rows,
            'input_gb': round(bytes_ / 1024 / 1024 / 1024, 2),
            'partitions': partitions,
            'estimated_shuffle_gb': round(shuffle_bytes / 1024 / 1024 / 1024, 2),
            'skew_ratio': skew,
            'spill_risk': spill_risk,
            'stages': stages,
            'notes': notes,
        }
