"""Safe AST evaluator for the SparkLab teaching API.

This module intentionally accepts only a narrow PySpark-like subset. It never
executes submitted Python with eval/exec. Supported syntax is converted into
SparkLab DataFrame/Expr objects, which can then compile to relational SQL and
feed the virtual runtime model.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from .sparklab import DataFrame, Expr, GroupedData, SparkSession, Window, WindowSpec, functions as F


class SparkLabSyntaxError(ValueError):
    pass


@dataclass
class ParseResult:
    dataframe: DataFrame
    symbols: dict[str, Any]
    target_name: str
    action: str = 'notebook_preview'


class SafeSparkParser:
    """Interpret a whitelisted PySpark-like AST without executing Python."""

    def __init__(self, spark: SparkSession):
        self.spark = spark
        self.symbols: dict[str, Any] = {
            "spark": spark,
            "F": F,
            "Window": Window,
        }
        self.last_dataframe_name: str | None = None

    def parse(self, source: str) -> ParseResult:
        self.last_dataframe_name = None
        self.action = 'notebook_preview'
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            raise SparkLabSyntaxError(str(exc)) from exc

        for stmt in tree.body:
            self._stmt(stmt)

        if not self.last_dataframe_name:
            raise SparkLabSyntaxError("No DataFrame result assignment found")
        value = self.symbols.get(self.last_dataframe_name)
        if not isinstance(value, DataFrame):
            raise SparkLabSyntaxError("Final result is not a DataFrame")
        return ParseResult(value, dict(self.symbols), self.last_dataframe_name, self.action)

    def _stmt(self, node: ast.stmt) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._handle_import(node)
            return
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise SparkLabSyntaxError("Only simple variable assignments are supported")
            name = node.targets[0].id
            value = self._expr(node.value)
            self.symbols[name] = value
            if isinstance(value, DataFrame):
                self.last_dataframe_name = name
            return
        if isinstance(node, ast.Expr):
            value = self._expr(node.value)
            if isinstance(value, DataFrame):
                self.symbols['_cell_result'] = value
                self.last_dataframe_name = '_cell_result'
            return
        raise SparkLabSyntaxError(f"Unsupported statement: {type(node).__name__}")

    def _handle_import(self, node: ast.Import | ast.ImportFrom) -> None:
        """Accept common PySpark SQL imports and bind their aliases safely.

        Imports are compatibility syntax only: no Python module is imported or
        executed. Names are mapped to SparkLab's already-whitelisted objects.
        """
        allowed_modules = {"pyspark.sql", "pyspark.sql.functions", "pyspark.sql.window"}
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in allowed_modules:
                    raise SparkLabSyntaxError("Only PySpark SQL imports are allowed")
                if alias.asname:
                    if alias.name == "pyspark.sql.functions":
                        self.symbols[alias.asname] = F
                    elif alias.name == "pyspark.sql.window":
                        self.symbols[alias.asname] = Window
                    else:
                        raise SparkLabSyntaxError("Import pyspark.sql submodules explicitly (functions/window)")
            return

        module = node.module or ""
        if module not in allowed_modules:
            raise SparkLabSyntaxError("Only PySpark SQL imports are allowed")

        for alias in node.names:
            target = alias.asname or alias.name
            if module == "pyspark.sql.functions":
                if not hasattr(F, alias.name) or alias.name.startswith("_"):
                    raise SparkLabSyntaxError(f"Unsupported PySpark function import: {alias.name}")
                self.symbols[target] = getattr(F, alias.name)
            elif module == "pyspark.sql.window":
                if alias.name != "Window":
                    raise SparkLabSyntaxError(f"Unsupported pyspark.sql.window import: {alias.name}")
                self.symbols[target] = Window
            elif module == "pyspark.sql":
                if alias.name == "functions":
                    self.symbols[target] = F
                elif alias.name == "Window":
                    self.symbols[target] = Window
                else:
                    raise SparkLabSyntaxError(f"Unsupported pyspark.sql import: {alias.name}")

    def _expr(self, node: ast.expr) -> Any:
        if isinstance(node, ast.Name):
            if node.id not in self.symbols:
                raise SparkLabSyntaxError(f"Unknown name: {node.id}")
            return self.symbols[node.id]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(self._expr(x) for x in node.elts)
        if isinstance(node, ast.List):
            return [self._expr(x) for x in node.elts]
        if isinstance(node, ast.Subscript):
            base = self._expr(node.value)
            key = self._expr(node.slice)
            if isinstance(base, DataFrame) and isinstance(key, str):
                return F.col(key)
            raise SparkLabSyntaxError("Only DataFrame string column access is supported in subscripts")
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.Attribute):
            base = self._expr(node.value)
            return self._attribute(base, node.attr)
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise SparkLabSyntaxError("Chained comparisons are not supported")
            left = self._expr(node.left)
            right = self._expr(node.comparators[0])
            if not isinstance(left, Expr):
                raise SparkLabSyntaxError("Comparison left side must be a Spark expression")
            op = node.ops[0]
            mapping = {
                ast.Eq: left.__eq__, ast.NotEq: left.__ne__, ast.Gt: left.__gt__,
                ast.GtE: left.__ge__, ast.Lt: left.__lt__, ast.LtE: left.__le__,
            }
            fn = mapping.get(type(op))
            if not fn:
                raise SparkLabSyntaxError(f"Unsupported comparison: {type(op).__name__}")
            return fn(right)
        if isinstance(node, ast.BinOp):
            left, right = self._expr(node.left), self._expr(node.right)
            if not isinstance(left, Expr):
                raise SparkLabSyntaxError("Binary expression left side must be a Spark expression")
            mapping = {
                ast.Add: left.__add__, ast.Sub: left.__sub__, ast.Mult: left.__mul__, ast.Div: left.__truediv__,
                ast.BitAnd: left.__and__, ast.BitOr: left.__or__,
            }
            fn = mapping.get(type(node.op))
            if not fn:
                raise SparkLabSyntaxError(f"Unsupported binary operator: {type(node.op).__name__}")
            return fn(right)
        if isinstance(node, ast.BoolOp):
            raise SparkLabSyntaxError("PySpark Columns use parenthesized & and |, not Python and/or")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value = self._expr(node.operand)
            if not isinstance(value, (int, float)):
                raise SparkLabSyntaxError("Unary minus is only supported for numeric literals")
            return -value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            value = self._expr(node.operand)
            if not isinstance(value, Expr):
                raise SparkLabSyntaxError("~ is only supported for Spark expressions")
            return ~value
        raise SparkLabSyntaxError(f"Unsupported expression: {type(node).__name__}")

    def _attribute(self, base: Any, attr: str) -> Any:
        allowed_attrs = {
            SparkSession: {"table", "read"}, DataFrame: {
                "filter", "where", "select", "withColumn", "withColumnRenamed", "drop", "dropDuplicates", "distinct",
                "groupBy", "join", "orderBy", "sort", "alias", "limit", "repartition", "coalesce",
            }, Expr: {"alias", "over", "desc", "asc", "isNull", "isNotNull", "eqNullSafe", "cast", "isin", "between", "otherwise", "when"},
            WindowSpec: {"partitionBy", "orderBy", "rowsBetween"},
            GroupedData: {"agg"},
        }
        if base is F:
            allowed = {
                "col", "lit", "when", "sum", "avg", "min", "max", "count", "countDistinct",
                "row_number", "lag", "lead", "to_date", "date_trunc", "coalesce", "broadcast",
            }
            if attr not in allowed:
                raise SparkLabSyntaxError(f"Unsupported F function: {attr}")
            return getattr(base, attr)
        if base is Window:
            if attr not in {"partitionBy", "orderBy", "unboundedPreceding", "unboundedFollowing", "currentRow"}:
                raise SparkLabSyntaxError(f"Unsupported Window function/constant: {attr}")
            return getattr(base, attr)
        if hasattr(base, "parquet") and attr == "parquet":
            return getattr(base, attr)
        for typ, allowed in allowed_attrs.items():
            if isinstance(base, typ):
                if attr not in allowed:
                    if attr == 'selectExpr':
                        raise SparkLabSyntaxError('selectExpr SQL strings are unsupported; use select(F.col(...), F.sum(...).alias(...))')
                    raise SparkLabSyntaxError(f"Unsupported {typ.__name__} attribute: {attr}")
                return getattr(base, attr)
        raise SparkLabSyntaxError(f"Attribute access is not allowed: {attr}")

    def _call(self, node: ast.Call) -> Any:
        fn = self._expr(node.func)
        if not callable(fn):
            raise SparkLabSyntaxError("Call target is not callable")
        if any(kw.arg is None for kw in node.keywords):
            raise SparkLabSyntaxError('Expanded **kwargs are not supported by this teaching kernel')
        args = [self._expr(a) for a in node.args]
        if getattr(fn, '__name__', '') in {'filter', 'where'} and args and isinstance(args[0], str):
            raise SparkLabSyntaxError('SQL-string filter is valid in real PySpark but unsupported here; use F.col expressions')
        kwargs = {kw.arg: self._expr(kw.value) for kw in node.keywords if kw.arg}
        try:
            return fn(*args, **kwargs)
        except (TypeError, ValueError) as exc:
            raise SparkLabSyntaxError(str(exc)) from exc
