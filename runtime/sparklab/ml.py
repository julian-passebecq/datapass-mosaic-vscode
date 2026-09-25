"""A bounded pyspark.ml subset for notebooks: real fits on the lab rows, predictions compiled to SQL.

Supported:
- `VectorAssembler(inputCols=[...], outputCol="features")`: records which numeric
  columns form the feature vector (the lab keeps them as columns; there is no
  vector type).
- `LinearRegression(featuresCol, labelCol, predictionCol)`: ordinary least squares
  (regParam must stay 0.0), fitted with numpy on the rows the notebook runtime reads.
- `LogisticRegression(featuresCol, labelCol, predictionCol, probabilityCol,
  threshold, maxIter)`: binary logistic regression fitted by Newton's method,
  without regularization. `probability` is the scalar probability of class 1
  (Spark stores a vector [p0, p1]).
- `Pipeline(stages=[...])`: runs the stages in order; `fit` returns a PipelineModel.
- Evaluators: `RegressionEvaluator` (rmse, mse, mae, r2),
  `BinaryClassificationEvaluator` (areaUnderROC) and
  `MulticlassClassificationEvaluator` (accuracy).
- `df.randomSplit([0.8, 0.2], seed=42)` (see sparklab.DataFrame): a stable
  md5-based split, so a seed always gives the same rows in the lab. Spark's own
  split differs, so do not expect Spark's exact rows or metrics.

Models are plain parameters (coefficients, intercept), so predictions are SQL
expressions and models can be logged to the lab's MLflow store and loaded back.
Nothing here imports or runs learner Python.
"""
from __future__ import annotations

import math
from typing import Any

MAX_TRAINING_ROWS = 100_000


class MLError(ValueError):
    pass


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _num(value: float) -> str:
    return repr(float(value))


def _features(df: Any, features_col: str) -> tuple[str, ...]:
    columns = getattr(df, 'vectors', {}).get(features_col)
    if columns is None:
        raise MLError(f"Column '{features_col}' is not a feature vector: run a VectorAssembler with "
                      f"outputCol='{features_col}' first")
    return columns


def _runtime(df: Any) -> Any:
    runtime = df.session.notebook_runtime
    if runtime is None or not hasattr(runtime, 'fetch'):
        raise MLError('Training reads data, so it runs in notebooks run by a job or a pipeline')
    return runtime


def _rows(df: Any, columns: list[str]) -> list[tuple[Any, ...]]:
    projection = ', '.join(_quote(c) for c in columns)
    rows = _runtime(df).fetch(f"SELECT {projection} FROM ({df.sql}) AS ml_source", MAX_TRAINING_ROWS + 1)
    if len(rows) > MAX_TRAINING_ROWS:
        raise MLError(f"The lab trains on at most {MAX_TRAINING_ROWS} rows")
    return rows


def _matrix(df: Any, features: tuple[str, ...], label: str) -> tuple[Any, Any]:
    import numpy as np
    rows = _rows(df, list(features) + [label])
    clean = [r for r in rows if all(v is not None for v in r)]
    if not clean:
        raise MLError('No training rows without NULLs')
    try:
        data = np.array(clean, dtype=float)
    except (TypeError, ValueError):
        raise MLError(f"Features and label must be numeric: {', '.join(features)}, {label}") from None
    return data[:, :-1], data[:, -1]


class VectorAssembler:
    def __init__(self, inputCols: list[str] | None = None, outputCol: str = 'features', handleInvalid: str = 'error'):
        if not inputCols or not all(isinstance(c, str) for c in inputCols):
            raise MLError('VectorAssembler needs inputCols, a list of column names')
        if handleInvalid not in ('error', 'skip', 'keep'):
            raise MLError("handleInvalid must be 'error', 'skip' or 'keep'")
        self.inputCols, self.outputCol, self.handleInvalid = list(inputCols), outputCol, handleInvalid

    def transform(self, df: Any) -> Any:
        known = df.current_columns()
        missing = [c for c in self.inputCols if known is not None and c not in known]
        if missing:
            raise MLError(f"VectorAssembler: no column {', '.join(missing)}")
        out = df._clone()
        if self.handleInvalid == 'skip':
            from .sparklab import Expr, Op
            condition = ' AND '.join(f"{_quote(c)} IS NOT NULL" for c in self.inputCols)
            out.ops.append(Op('filter', {'expr': Expr(f"({condition})")}))
        out.vectors = {**out.vectors, self.outputCol: tuple(self.inputCols)}
        return out

    def fit(self, df: Any) -> 'VectorAssembler':  # a transformer: fitting is a no-op inside a Pipeline
        return self


class _Summary:
    def __init__(self, metrics: dict[str, float]):
        self.rootMeanSquaredError = metrics.get('rmse')
        self.r2 = metrics.get('r2')
        self.meanAbsoluteError = metrics.get('mae')
        self.areaUnderROC = metrics.get('auc')
        self.accuracy = metrics.get('accuracy')


class LinearRegressionModel:
    kind = 'LinearRegressionModel'

    def __init__(self, features: tuple[str, ...], label: str, prediction: str, coefficients: list[float],
                 intercept: float, features_col: str = 'features', metrics: dict[str, float] | None = None):
        self.features, self.label, self.predictionCol = features, label, prediction
        self.featuresCol = features_col
        self.coefficients = [round(c, 12) for c in coefficients]
        self.intercept = round(intercept, 12)
        self.summary = _Summary(metrics or {})

    def expression(self) -> str:
        terms = [_num(self.intercept)] + [f"{_num(c)} * {_quote(f)}" for c, f in zip(self.coefficients, self.features)]
        return '(' + ' + '.join(terms) + ')'

    def transform(self, df: Any) -> Any:
        from .sparklab import Expr
        _check_columns(df, self.features)
        out = df.withColumn(self.predictionCol, Expr(self.expression()))
        out.vectors = dict(df.vectors)
        return out

    def payload(self) -> dict[str, Any]:
        return {'kind': self.kind, 'features': list(self.features), 'label': self.label,
                'prediction': self.predictionCol, 'coefficients': self.coefficients, 'intercept': self.intercept,
                'features_col': self.featuresCol}


class LogisticRegressionModel:
    kind = 'LogisticRegressionModel'

    def __init__(self, features: tuple[str, ...], label: str, prediction: str, probability: str,
                 coefficients: list[float], intercept: float, threshold: float = 0.5, features_col: str = 'features',
                 metrics: dict[str, float] | None = None):
        self.features, self.label, self.predictionCol, self.probabilityCol = features, label, prediction, probability
        self.featuresCol = features_col
        self.coefficients = [round(c, 12) for c in coefficients]
        self.intercept = round(intercept, 12)
        self.threshold = threshold
        self.summary = _Summary(metrics or {})

    def margin(self) -> str:
        terms = [_num(self.intercept)] + [f"{_num(c)} * {_quote(f)}" for c, f in zip(self.coefficients, self.features)]
        return '(' + ' + '.join(terms) + ')'

    def transform(self, df: Any) -> Any:
        from .sparklab import Expr
        _check_columns(df, self.features)
        probability = f"(1.0 / (1.0 + exp(-{self.margin()})))"
        out = df.withColumn('rawPrediction', Expr(self.margin()))
        out = out.withColumn(self.probabilityCol, Expr(probability))
        out = out.withColumn(self.predictionCol,
                             Expr(f"CASE WHEN {probability} > {_num(self.threshold)} THEN 1.0 ELSE 0.0 END"))
        out.vectors = dict(df.vectors)
        return out

    def payload(self) -> dict[str, Any]:
        return {'kind': self.kind, 'features': list(self.features), 'label': self.label,
                'prediction': self.predictionCol, 'probability': self.probabilityCol,
                'coefficients': self.coefficients, 'intercept': self.intercept, 'threshold': self.threshold,
                'features_col': self.featuresCol}


def _check_columns(df: Any, features: tuple[str, ...]) -> None:
    known = df.current_columns()
    missing = [c for c in features if known is not None and c not in known]
    if missing:
        raise MLError(f"The model needs the columns {', '.join(missing)}")


class LinearRegression:
    def __init__(self, featuresCol: str = 'features', labelCol: str = 'label', predictionCol: str = 'prediction',
                 regParam: float = 0.0, elasticNetParam: float = 0.0, maxIter: int = 100, fitIntercept: bool = True,
                 standardization: bool = True):
        if regParam:
            raise MLError('regParam is not simulated: the lab fits ordinary least squares (regParam=0.0)')
        self.featuresCol, self.labelCol, self.predictionCol = featuresCol, labelCol, predictionCol
        self.fitIntercept = bool(fitIntercept)

    def fit(self, df: Any) -> LinearRegressionModel:
        import numpy as np
        features = _features(df, self.featuresCol)
        x, y = _matrix(df, features, self.labelCol)
        design = np.column_stack([np.ones(len(x)), x]) if self.fitIntercept else x
        solution, *_ = np.linalg.lstsq(design, y, rcond=None)
        intercept = float(solution[0]) if self.fitIntercept else 0.0
        coefficients = [float(c) for c in (solution[1:] if self.fitIntercept else solution)]
        predicted = design @ solution
        return LinearRegressionModel(features, self.labelCol, self.predictionCol, coefficients, intercept,
                                     self.featuresCol, _regression_metrics(y, predicted))


class LogisticRegression:
    def __init__(self, featuresCol: str = 'features', labelCol: str = 'label', predictionCol: str = 'prediction',
                 probabilityCol: str = 'probability', maxIter: int = 100, regParam: float = 0.0, threshold: float = 0.5,
                 family: str = 'auto'):
        if regParam:
            raise MLError('regParam is not simulated: the lab fits an unregularized logistic regression')
        if family not in ('auto', 'binomial'):
            raise MLError("The lab fits binary logistic regression only (family='binomial')")
        if not 0 < float(threshold) < 1:
            raise MLError('threshold must be between 0 and 1')
        self.featuresCol, self.labelCol, self.predictionCol = featuresCol, labelCol, predictionCol
        self.probabilityCol, self.maxIter, self.threshold = probabilityCol, int(maxIter), float(threshold)

    def fit(self, df: Any) -> LogisticRegressionModel:
        import numpy as np
        features = _features(df, self.featuresCol)
        x, y = _matrix(df, features, self.labelCol)
        if not set(np.unique(y)) <= {0.0, 1.0}:
            raise MLError(f"The label {self.labelCol} must be 0 or 1 for binary logistic regression")
        design = np.column_stack([np.ones(len(x)), x])
        weights = np.zeros(design.shape[1])
        for _ in range(max(1, min(self.maxIter, 500))):
            margin = np.clip(design @ weights, -30, 30)
            p = 1 / (1 + np.exp(-margin))
            gradient = design.T @ (y - p)
            hessian = design.T @ (design * (p * (1 - p))[:, None]) + np.eye(design.shape[1]) * 1e-9
            step = np.linalg.solve(hessian, gradient)
            weights = weights + step
            if float(np.max(np.abs(step))) < 1e-8:
                break
        probability = 1 / (1 + np.exp(-np.clip(design @ weights, -30, 30)))
        predicted = (probability > self.threshold).astype(float)
        metrics = {'auc': _auc(y, probability), 'accuracy': float(np.mean(predicted == y))}
        return LogisticRegressionModel(features, self.labelCol, self.predictionCol, self.probabilityCol,
                                       [float(w) for w in weights[1:]], float(weights[0]), self.threshold,
                                       self.featuresCol, metrics)


class PipelineModel:
    kind = 'PipelineModel'

    def __init__(self, stages: list[Any]):
        self.stages = stages

    def transform(self, df: Any) -> Any:
        for stage in self.stages:
            df = stage.transform(df)
        return df

    def payload(self) -> dict[str, Any]:
        stages = []
        for stage in self.stages:
            if isinstance(stage, VectorAssembler):
                stages.append({'kind': 'VectorAssembler', 'inputCols': stage.inputCols, 'outputCol': stage.outputCol})
            else:
                stages.append(stage.payload())
        return {'kind': self.kind, 'stages': stages}


class Pipeline:
    def __init__(self, stages: list[Any] | None = None):
        if not stages:
            raise MLError('Pipeline needs stages')
        for stage in stages:
            if not isinstance(stage, (VectorAssembler, LinearRegression, LogisticRegression)):
                raise MLError(f"Unsupported pipeline stage: {type(stage).__name__}")
        self.stages = list(stages)

    def fit(self, df: Any) -> PipelineModel:
        fitted = []
        for stage in self.stages:
            if isinstance(stage, VectorAssembler):
                fitted.append(stage)
                df = stage.transform(df)
            else:
                model = stage.fit(df)
                fitted.append(model)
                df = model.transform(df)
        return PipelineModel(fitted)


def model_from_payload(payload: dict[str, Any]) -> Any:
    """Rebuild a logged model (mlflow.spark.load_model)."""
    kind = payload.get('kind')
    if kind == 'LinearRegressionModel':
        return LinearRegressionModel(tuple(payload['features']), payload['label'], payload['prediction'],
                                     list(payload['coefficients']), float(payload['intercept']),
                                     payload.get('features_col', 'features'))
    if kind == 'LogisticRegressionModel':
        return LogisticRegressionModel(tuple(payload['features']), payload['label'], payload['prediction'],
                                       payload['probability'], list(payload['coefficients']),
                                       float(payload['intercept']), float(payload.get('threshold', 0.5)),
                                       payload.get('features_col', 'features'))
    if kind == 'PipelineModel':
        stages = []
        for stage in payload['stages']:
            if stage['kind'] == 'VectorAssembler':
                stages.append(VectorAssembler(stage['inputCols'], stage['outputCol']))
            else:
                stages.append(model_from_payload(stage))
        return PipelineModel(stages)
    raise MLError(f"Unknown model kind: {kind}")


MODEL_TYPES = (LinearRegressionModel, LogisticRegressionModel, PipelineModel)


class RegressionEvaluator:
    def __init__(self, labelCol: str = 'label', predictionCol: str = 'prediction', metricName: str = 'rmse'):
        if metricName not in ('rmse', 'mse', 'mae', 'r2'):
            raise MLError("metricName must be rmse, mse, mae or r2")
        self.labelCol, self.predictionCol, self.metricName = labelCol, predictionCol, metricName

    def evaluate(self, df: Any) -> float:
        import numpy as np
        rows = [r for r in _rows(df, [self.labelCol, self.predictionCol]) if None not in r]
        if not rows:
            raise MLError('Nothing to evaluate: no rows')
        data = np.array(rows, dtype=float)
        return round(_regression_metrics(data[:, 0], data[:, 1])[self.metricName], 10)


class BinaryClassificationEvaluator:
    def __init__(self, labelCol: str = 'label', rawPredictionCol: str = 'rawPrediction',
                 metricName: str = 'areaUnderROC'):
        if metricName != 'areaUnderROC':
            raise MLError("The lab computes metricName='areaUnderROC'")
        self.labelCol, self.rawPredictionCol = labelCol, rawPredictionCol

    def evaluate(self, df: Any) -> float:
        import numpy as np
        rows = [r for r in _rows(df, [self.labelCol, self.rawPredictionCol]) if None not in r]
        if not rows:
            raise MLError('Nothing to evaluate: no rows')
        data = np.array(rows, dtype=float)
        return round(_auc(data[:, 0], data[:, 1]), 10)


class MulticlassClassificationEvaluator:
    def __init__(self, labelCol: str = 'label', predictionCol: str = 'prediction', metricName: str = 'accuracy'):
        if metricName != 'accuracy':
            raise MLError("The lab computes metricName='accuracy'")
        self.labelCol, self.predictionCol = labelCol, predictionCol

    def evaluate(self, df: Any) -> float:
        rows = [r for r in _rows(df, [self.labelCol, self.predictionCol]) if None not in r]
        if not rows:
            raise MLError('Nothing to evaluate: no rows')
        return round(sum(1 for a, b in rows if float(a) == float(b)) / len(rows), 10)


def _regression_metrics(y: Any, predicted: Any) -> dict[str, float]:
    import numpy as np
    residual = y - predicted
    mse = float(np.mean(residual ** 2))
    total = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - float(np.sum(residual ** 2)) / total if total > 0 else (1.0 if mse == 0 else 0.0)
    return {'rmse': math.sqrt(mse), 'mse': mse, 'mae': float(np.mean(np.abs(residual))), 'r2': r2}


def _auc(y: Any, score: Any) -> float:
    """Area under the ROC curve (Mann-Whitney U from average ranks, so ties count half)."""
    import numpy as np
    y, score = np.asarray(y, dtype=float), np.asarray(score, dtype=float)
    positives, negatives = int((y == 1).sum()), int((y == 0).sum())
    if not positives or not negatives:
        return 0.0
    order = np.argsort(score, kind='mergesort')
    ordered = score[order]
    ranks = np.empty(len(score))
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and ordered[end + 1] == ordered[start]:
            end += 1
        ranks[order[start:end + 1]] = (start + end) / 2 + 1
        start = end + 1
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))
