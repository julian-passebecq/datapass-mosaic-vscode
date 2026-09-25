"""Safe AST evaluator for the SparkLab teaching API.

This module intentionally accepts only a narrow PySpark-like subset. It never
executes submitted Python with eval/exec. Supported syntax is converted into
SparkLab DataFrame/Expr objects, which can then compile to relational SQL and
feed the virtual runtime model.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from . import ml
from .mlflow_api import (ActiveRun, MLflowApi, MlflowClient, MlflowStore, ModelInfo, ModelVersion, RunInfo,
                         Signature, _ModelsModule, _SparkFlavor)
from .notebook_utils import (DataFrameWriter, DbUtils, NotebookExit, NotebookUtils, Row, TaskValueStore, _Jobs,
                             _NotebookApi, _TaskValues, _Widgets, no_op, parameters_cell_end)
from .sparklab import DataFrame, Expr, GroupedData, ReadBuilder, SparkSession, Window, WindowSpec, functions as F

# pyspark.ml names a notebook can import (a bounded, lab-implemented subset).
ML_IMPORTS = {
    'pyspark.ml': {'Pipeline': ml.Pipeline, 'PipelineModel': ml.PipelineModel},
    'pyspark.ml.feature': {'VectorAssembler': ml.VectorAssembler},
    'pyspark.ml.regression': {'LinearRegression': ml.LinearRegression},
    'pyspark.ml.classification': {'LogisticRegression': ml.LogisticRegression},
    'pyspark.ml.evaluation': {'RegressionEvaluator': ml.RegressionEvaluator,
                              'BinaryClassificationEvaluator': ml.BinaryClassificationEvaluator,
                              'MulticlassClassificationEvaluator': ml.MulticlassClassificationEvaluator},
}
MLFLOW_MODULES = {'mlflow', 'mlflow.spark', 'mlflow.models', 'mlflow.tracking'}

NOTEBOOK_STYLES = ('fabric', 'synapse', 'databricks')


class SparkLabSyntaxError(ValueError):
    pass


@dataclass
class ParseResult:
    dataframe: DataFrame
    symbols: dict[str, Any]
    target_name: str
    action: str = 'notebook_preview'


@dataclass
class NotebookRun:
    exited: bool = False
    exit_value: str | None = None
    dataframe: DataFrame | None = None
    parameters_cell: bool = False
    injected: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


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
        self.notebook_mode = False
        self.mlflow: MLflowApi | None = None

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

    def run_notebook(self, source: str, parameters: dict[str, Any], style: str,
                     task_values: TaskValueStore | None = None, mlflow: MlflowStore | None = None) -> NotebookRun:
        """Run a pipeline notebook statement by statement, still without eval/exec.

        The session's notebook runtime performs table writes, spark.sql statements
        and count() as they are reached. Fabric and Synapse receive the pipeline
        parameters as assignments injected after the parameters cell (or at the
        top without one); Databricks reads them with dbutils.widgets.get.
        """
        if style not in NOTEBOOK_STYLES:
            raise SparkLabSyntaxError(f"Unknown notebook style: {style}")
        if self.spark.notebook_runtime is None:
            raise SparkLabSyntaxError('Pipeline notebooks need a local notebook runtime')
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            raise SparkLabSyntaxError(f"line {exc.lineno}: {exc.msg}") from exc
        self.notebook_mode = True
        self.last_dataframe_name = None
        self.symbols.update({'display': self._display, 'print': no_op, 'str': str, 'int': int, 'float': float,
                             'bool': bool, 'round': round, 'len': len, 'abs': abs})
        self.mlflow = MLflowApi(mlflow) if mlflow is not None else None
        if style == 'databricks':
            self.symbols['dbutils'] = DbUtils(dict(parameters), task_values)
        else:
            self.symbols['notebookutils'] = self.symbols['mssparkutils'] = NotebookUtils()
        run = NotebookRun()
        cell_end = parameters_cell_end(source)
        run.parameters_cell = cell_end is not None
        pending = dict(parameters) if style != 'databricks' else {}
        if pending and cell_end is None:
            self._inject(pending, run)
        for stmt in tree.body:
            if pending and not run.injected and cell_end is not None and stmt.lineno >= cell_end:
                self._inject(pending, run)
            try:
                self._stmt(stmt)
            except NotebookExit as done:
                run.exited, run.exit_value = True, done.value
                break
            except Exception as exc:  # SparkLab and catalog errors both stop the notebook at this line
                raise SparkLabSyntaxError(str(exc) if str(exc).startswith('line ') else f"line {stmt.lineno}: {exc}") from exc
            target = stmt.targets[0].id if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name) else None
            if run.injected and target in run.injected:
                where = ('there is no parameters cell, so the pipeline values were injected at the top'
                         if cell_end is None else 'this line runs after the parameters cell')
                run.notes.append(f"line {stmt.lineno}: '{target}' came from the pipeline but is reassigned here "
                                 f"({where})")
        if self.last_dataframe_name:
            value = self.symbols.get(self.last_dataframe_name)
            run.dataframe = value if isinstance(value, DataFrame) else None
        return run

    def _inject(self, parameters: dict[str, Any], run: NotebookRun) -> None:
        for name, value in parameters.items():
            if not isinstance(name, str) or not name.isidentifier() or name in {'spark', 'F', 'Window'}:
                raise SparkLabSyntaxError(f"Notebook parameter name is not a Python identifier: {name!r}")
            self.symbols[name] = value
        run.injected = dict(parameters)

    def _display(self, value: Any = None, *args: Any, **kwargs: Any) -> Any:
        return value

    def _stmt(self, node: ast.stmt) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._handle_import(node)
            return
        if isinstance(node, ast.Assign) and self.notebook_mode and len(node.targets) == 1 and isinstance(
                node.targets[0], (ast.Tuple, ast.List)):
            names = node.targets[0].elts
            if not all(isinstance(n, ast.Name) for n in names):
                raise SparkLabSyntaxError("Unpack into plain names, for example train, test = df.randomSplit(...)")
            values = self._expr(node.value)
            if not isinstance(values, (list, tuple)) or len(values) != len(names):
                raise SparkLabSyntaxError(f"Cannot unpack into {len(names)} names")
            for target, value in zip(names, values):
                self.symbols[target.id] = value
                if isinstance(value, DataFrame):
                    self.last_dataframe_name = target.id
            return
        if isinstance(node, ast.With) and self.notebook_mode:
            self._with(node)
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

    def _with(self, node: ast.With) -> None:
        """`with mlflow.start_run(...) as run:`: the only context manager a notebook can use."""
        if len(node.items) != 1:
            raise SparkLabSyntaxError('with takes one context: with mlflow.start_run() as run:')
        item = node.items[0]
        context = self._expr(item.context_expr)
        if not isinstance(context, ActiveRun):
            raise SparkLabSyntaxError('Only `with mlflow.start_run(...)` is supported as a with block')
        if item.optional_vars is not None:
            if not isinstance(item.optional_vars, ast.Name):
                raise SparkLabSyntaxError('with ... as takes a plain name')
            self.symbols[item.optional_vars.id] = context._lab_enter()
        failed = True
        try:
            for stmt in node.body:
                try:
                    self._stmt(stmt)
                except NotebookExit:
                    raise
                except Exception as exc:
                    raise SparkLabSyntaxError(exc if str(exc).startswith('line ') else f"line {stmt.lineno}: {exc}") from exc
            failed = False
        except NotebookExit:
            failed = False
            raise
        finally:
            context._lab_exit(failed)

    def _import_notebook_libraries(self, node: ast.Import | ast.ImportFrom) -> bool:
        """pyspark.ml and mlflow imports in notebooks; True when handled."""
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
            if all(n in MLFLOW_MODULES for n in names):
                api = self._mlflow_api()
                for alias in node.names:
                    if alias.asname:
                        target = api if alias.name == 'mlflow' else api.spark if alias.name == 'mlflow.spark' else \
                            api.models if alias.name == 'mlflow.models' else api
                        self.symbols[alias.asname] = target
                    else:
                        self.symbols['mlflow'] = api
                return True
            if all(n in ML_IMPORTS for n in names):
                raise SparkLabSyntaxError('Import pyspark.ml names explicitly, for example '
                                          'from pyspark.ml.regression import LinearRegression')
            return False
        module = node.module or ''
        if module in ML_IMPORTS:
            for alias in node.names:
                if alias.name not in ML_IMPORTS[module]:
                    raise SparkLabSyntaxError(f"Unsupported {module} import: {alias.name} (the lab supports "
                                              f"{', '.join(ML_IMPORTS[module])})")
                self.symbols[alias.asname or alias.name] = ML_IMPORTS[module][alias.name]
            return True
        if module in MLFLOW_MODULES:
            api = self._mlflow_api()
            exports = {'mlflow': {'MlflowClient': api.MlflowClient, 'spark': api.spark, 'models': api.models},
                       'mlflow.tracking': {'MlflowClient': api.MlflowClient},
                       'mlflow.models': {'infer_signature': api.models.infer_signature},
                       'mlflow.spark': {'log_model': api.spark.log_model, 'load_model': api.spark.load_model}}[module]
            for alias in node.names:
                if alias.name not in exports:
                    raise SparkLabSyntaxError(f"Unsupported {module} import: {alias.name}")
                self.symbols[alias.asname or alias.name] = exports[alias.name]
            return True
        return False

    def _mlflow_api(self) -> MLflowApi:
        if self.mlflow is None:
            raise SparkLabSyntaxError('MLflow is available in notebooks run by a Databricks job in the lab')
        return self.mlflow

    def _handle_import(self, node: ast.Import | ast.ImportFrom) -> None:
        """Accept common PySpark SQL imports and bind their aliases safely.

        Imports are compatibility syntax only: no Python module is imported or
        executed. Names are mapped to SparkLab's already-whitelisted objects.
        """
        allowed_modules = {"pyspark.sql", "pyspark.sql.functions", "pyspark.sql.window"}
        if self.notebook_mode and self._import_notebook_libraries(node):
            return
        if self.notebook_mode and isinstance(node, (ast.Import, ast.ImportFrom)):
            # Fabric and Synapse notebooks often import their utilities; bind the lab objects instead.
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if all(n in {'notebookutils', 'mssparkutils', 'notebookutils.mssparkutils'} for n in names):
                for alias in node.names:
                    target = alias.asname or alias.name.split('.')[-1]
                    if alias.name not in {'notebookutils', 'mssparkutils'}:
                        raise SparkLabSyntaxError(f"Unsupported notebook utility import: {alias.name}")
                    self.symbols[target] = self.symbols.get('notebookutils') or NotebookUtils()
                return
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
        if isinstance(node, ast.JoinedStr) and self.notebook_mode:
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant):
                    parts.append(str(value.value))
                    continue
                if not isinstance(value, ast.FormattedValue) or value.format_spec is not None or value.conversion not in (-1, 115):
                    raise SparkLabSyntaxError('f-strings may only insert plain {name} values')
                inner = self._expr(value.value)
                if inner is not None and not isinstance(inner, (str, int, float, bool)):
                    raise SparkLabSyntaxError('f-strings may only insert text and numbers')
                parts.append(str(inner))
            return ''.join(parts)
        if isinstance(node, ast.Tuple):
            return tuple(self._expr(x) for x in node.elts)
        if isinstance(node, ast.Dict) and self.notebook_mode:
            if any(k is None for k in node.keys):
                raise SparkLabSyntaxError('Dict unpacking (**) is not supported')
            keys = [self._expr(k) for k in node.keys]
            if not all(isinstance(k, str) for k in keys):
                raise SparkLabSyntaxError('Dict keys must be text')
            return {k: self._expr(v) for k, v in zip(keys, node.values)}
        if isinstance(node, ast.List):
            return [self._expr(x) for x in node.elts]
        if isinstance(node, ast.Subscript):
            base = self._expr(node.value)
            key = self._expr(node.slice)
            if isinstance(base, DataFrame) and isinstance(key, str):
                return F.col(key)
            if self.notebook_mode:
                if isinstance(base, Row):
                    return base[key]
                if isinstance(base, (list, tuple)) and isinstance(key, int) and not isinstance(key, bool):
                    if not -len(base) <= key < len(base):
                        raise SparkLabSyntaxError(f"Index {key} is out of range")
                    return base[key]
                if isinstance(base, dict) and isinstance(key, str):
                    if key not in base:
                        raise SparkLabSyntaxError(f"No key {key!r}")
                    return base[key]
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
            if self.notebook_mode and not isinstance(left, Expr) and not isinstance(right, Expr):
                return self._plain_binop(node.op, left, right)
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

    @staticmethod
    def _plain_binop(op: ast.operator, left: Any, right: Any) -> Any:
        """Text and number arithmetic in pipeline notebooks (for example building a table name)."""
        plain = (str, int, float)
        if not isinstance(left, plain) or not isinstance(right, plain) or isinstance(left, bool) or isinstance(right, bool):
            raise SparkLabSyntaxError('Only text and numbers can be combined outside Spark expressions')
        if isinstance(op, ast.Add) and isinstance(left, str) == isinstance(right, str):
            return left + right
        if not isinstance(left, str) and not isinstance(right, str):
            if isinstance(op, ast.Sub):
                return left - right
            if isinstance(op, ast.Mult):
                return left * right
            if isinstance(op, ast.Div) and right != 0:
                return left / right
        raise SparkLabSyntaxError(f"Unsupported operation {type(op).__name__} on {type(left).__name__} and "
                                  f"{type(right).__name__}")

    def _notebook_attribute(self, base: Any, attr: str) -> tuple[bool, Any]:
        allowed: dict[type, set[str]] = {
            SparkSession: {'sql'}, DataFrame: {'write', 'count', 'collect', 'first', 'columns', 'randomSplit'},
            ReadBuilder: {'table'},
            DataFrameWriter: {'mode', 'format', 'option', 'partitionBy', 'saveAsTable'},
            NotebookUtils: {'notebook'}, _NotebookApi: {'exit', 'run'},
            DbUtils: {'widgets', 'notebook', 'jobs'}, _Widgets: {'text', 'dropdown', 'get'},
            _Jobs: {'taskValues'}, _TaskValues: {'set', 'get'}, Row: {'asDict'},
            ml.VectorAssembler: {'transform', 'fit'}, ml.LinearRegression: {'fit'}, ml.LogisticRegression: {'fit'},
            ml.Pipeline: {'fit'}, ml.PipelineModel: {'transform', 'stages'},
            ml.LinearRegressionModel: {'transform', 'coefficients', 'intercept', 'summary'},
            ml.LogisticRegressionModel: {'transform', 'coefficients', 'intercept', 'summary'},
            ml._Summary: {'rootMeanSquaredError', 'r2', 'meanAbsoluteError', 'areaUnderROC', 'accuracy'},
            ml.RegressionEvaluator: {'evaluate'}, ml.BinaryClassificationEvaluator: {'evaluate'},
            ml.MulticlassClassificationEvaluator: {'evaluate'},
            MLflowApi: {'set_experiment', 'set_registry_uri', 'start_run', 'end_run', 'active_run', 'last_active_run',
                        'log_param', 'log_params', 'log_metric', 'log_metrics', 'set_tag', 'register_model', 'spark',
                        'models', 'MlflowClient'},
            _SparkFlavor: {'log_model', 'load_model'}, _ModelsModule: {'infer_signature'},
            ActiveRun: {'info'}, RunInfo: {'run_id', 'run_name', 'experiment_id'},
            ModelVersion: {'name', 'version', 'aliases', 'run_id'}, ModelInfo: {'model_uri', 'registered_model_version'},
            MlflowClient: {'set_registered_model_alias', 'delete_registered_model_alias', 'get_model_version_by_alias'},
            Signature: {'inputs', 'outputs'},
        }
        for typ, names in allowed.items():
            if isinstance(base, typ) and attr in names:
                return True, getattr(base, attr)
        guarded = tuple(t for t in allowed if t not in (SparkSession, DataFrame, ReadBuilder))
        if isinstance(base, guarded):
            raise SparkLabSyntaxError(f"Unsupported {type(base).__name__.lstrip('_')} attribute: {attr}")
        return False, None

    def _attribute(self, base: Any, attr: str) -> Any:
        if self.notebook_mode:
            found, value = self._notebook_attribute(base, attr)
            if found:
                return value
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
