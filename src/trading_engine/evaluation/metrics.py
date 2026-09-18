"""Forecast evaluation metrics for quantitative trading models."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class EvaluationMetrics:
    """Out-of-sample forecast accuracy metrics."""

    mae: float
    rmse: float
    directional_accuracy: float
    mape: float


def calculate_metrics(
    actual: Sequence[float],
    predicted: Sequence[float],
    base_price: float | None = None,
) -> EvaluationMetrics:
    """Calculate standard forecast accuracy metrics.

    Parameters
    ----------
    actual:
        Observed true prices.
    predicted:
        Model predicted point forecasts.
    base_price:
        Reference anchor price (e.g. cutoff close price) for directional calculation.
    """
    n = len(actual)
    if n == 0:
        raise ValueError("Cannot calculate metrics on empty sequences.")
    if len(predicted) != n:
        raise ValueError(f"Length mismatch: actual has {n} values, predicted has {len(predicted)}")

    abs_errors = [abs(a - p) for a, p in zip(actual, predicted)]
    sq_errors = [(a - p) ** 2 for a, p in zip(actual, predicted)]
    mae = sum(abs_errors) / n
    rmse = math.sqrt(sum(sq_errors) / n)

    # MAPE (percentage error relative to actual)
    mape_terms = [abs(a - p) / a for a, p in zip(actual, predicted) if a > 0]
    mape = (sum(mape_terms) / len(mape_terms)) * 100.0 if mape_terms else 0.0

    def _sign(x: float, eps: float = 1e-9) -> int:
        if x > eps:
            return 1
        elif x < -eps:
            return -1
        return 0

    # Directional Accuracy
    if base_price is not None:
        scores: list[float] = []
        for a, p in zip(actual, predicted):
            p_sign = _sign(p - base_price)
            a_sign = _sign(a - base_price)
            if p_sign == a_sign:
                scores.append(1.0)
            elif p_sign == 0 and a_sign != 0:
                # Flat prediction gets neutral 0.5 instead of free up-bias
                scores.append(0.5)
            else:
                scores.append(0.0)
        directional_acc = sum(scores) / n
    else:
        # Sequential step directions
        if n == 1:
            directional_acc = 1.0 if abs(actual[0] - predicted[0]) < 1e-9 else 0.0
        else:
            scores = []
            for i in range(1, n):
                p_sign = _sign(predicted[i] - predicted[i - 1])
                a_sign = _sign(actual[i] - actual[i - 1])
                if p_sign == a_sign:
                    scores.append(1.0)
                elif p_sign == 0 and a_sign != 0:
                    scores.append(0.5)
                else:
                    scores.append(0.0)
            directional_acc = sum(scores) / (n - 1)

    return EvaluationMetrics(
        mae=round(mae, 6),
        rmse=round(rmse, 6),
        directional_accuracy=round(directional_acc, 6),
        mape=round(mape, 6),
    )
