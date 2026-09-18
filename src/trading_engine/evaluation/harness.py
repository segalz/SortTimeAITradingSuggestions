"""Walk-forward evaluation harness runner executing models across rolling cutoffs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trading_engine.data.models import BarSeries
from trading_engine.evaluation.metrics import EvaluationMetrics, calculate_metrics
from trading_engine.evaluation.walk_forward import WalkForwardSplit, generate_walk_forward_splits
from trading_engine.models.baselines import BaselineModel


@dataclass(frozen=True)
class ModelEvaluationSummary:
    """Aggregated out-of-sample performance for a single model across all splits."""

    model_name: str
    mean_mae: float
    mean_rmse: float
    mean_directional_accuracy: float
    mean_mape: float
    split_count: int


@dataclass(frozen=True)
class HarnessRunResult:
    """Full results of an evaluation run across all models and walk-forward splits."""

    symbol: str
    timeframe: str
    total_splits: int
    summaries: dict[str, ModelEvaluationSummary]


class HarnessRunner:
    """Executes models across chronological walk-forward splits without leakage."""

    def __init__(
        self,
        train_bars: int,
        test_bars: int,
        step_bars: int = 1,
        expanding: bool = False,
    ) -> None:
        self.train_bars = train_bars
        self.test_bars = test_bars
        self.step_bars = step_bars
        self.expanding = expanding

    def run(
        self,
        series: BarSeries,
        models: Mapping[str, BaselineModel],
    ) -> HarnessRunResult:
        """Evaluate all candidate models on the provided series."""
        splits = generate_walk_forward_splits(
            series=series,
            train_bars=self.train_bars,
            test_bars=self.test_bars,
            step_bars=self.step_bars,
            expanding=self.expanding,
        )

        if not splits:
            raise ValueError(
                f"Insufficient data depth for walk-forward evaluation: series length {len(series)} "
                f"is less than required window {self.train_bars + self.test_bars}"
            )

        model_metrics: dict[str, list[EvaluationMetrics]] = {name: [] for name in models}

        for split in splits:
            actual_closes = [b.close for b in split.test]
            base_price = split.train[-1].close

            for name, model in models.items():
                forecast = model.predict(split.train, horizon_bars=self.test_bars)
                metrics = calculate_metrics(
                    actual=actual_closes,
                    predicted=forecast.point_forecasts,
                    base_price=base_price,
                )
                model_metrics[name].append(metrics)

        summaries: dict[str, ModelEvaluationSummary] = {}
        split_count = len(splits)

        for name, metrics_list in model_metrics.items():
            mean_mae = sum(m.mae for m in metrics_list) / split_count
            mean_rmse = sum(m.rmse for m in metrics_list) / split_count
            mean_da = sum(m.directional_accuracy for m in metrics_list) / split_count
            mean_mape = sum(m.mape for m in metrics_list) / split_count

            summaries[name] = ModelEvaluationSummary(
                model_name=name,
                mean_mae=round(mean_mae, 4),
                mean_rmse=round(mean_rmse, 4),
                mean_directional_accuracy=round(mean_da, 4),
                mean_mape=round(mean_mape, 4),
                split_count=split_count,
            )

        return HarnessRunResult(
            symbol=series.symbol,
            timeframe=series.timeframe,
            total_splits=split_count,
            summaries=summaries,
        )
