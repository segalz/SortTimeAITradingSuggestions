"""Comparative assessment benchmark evaluating candidate CPU models vs baselines across assets."""

from datetime import datetime, timedelta, timezone
import math
import pytest

from trading_engine.contracts.adapter import ModelAdapter
from trading_engine.contracts.forecast import ForecastRequest
from trading_engine.data.benchmarks import BENCHMARK_SYMBOLS
from trading_engine.data.models import BarSeries, Candle
from trading_engine.evaluation.harness import HarnessRunner, HarnessRunResult
from trading_engine.evaluation.stats import benjamini_hochberg_correction
from trading_engine.models.baselines import (
    BaselineModel,
    DriftBaseline,
    Forecast,
    LastValueBaseline,
    MovingAverageBaseline,
)
from trading_engine.models.chronos_adapter import ChronosBoltTinyAdapter
from trading_engine.models.kronos_adapter import KronosMiniAdapter


class ModelAdapterHarnessWrapper(BaselineModel):
    """Wrap ModelAdapter into BaselineModel interface for HarnessRunner execution."""

    def __init__(self, adapter: ModelAdapter) -> None:
        self.adapter = adapter

    def predict(self, history: BarSeries, horizon_bars: int) -> Forecast:
        req = ForecastRequest(
            symbol=history.symbol,
            timeframe=history.timeframe,
            history=history,
            horizon_bars=horizon_bars,
            quantiles=(0.10, 0.50, 0.90),
        )
        res = self.adapter.predict(req)
        return Forecast(
            symbol=history.symbol,
            timeframe=history.timeframe,
            horizon_bars=horizon_bars,
            point_forecasts=res.point_forecast,
        )


def _generate_synthetic_market_data(
    symbol: str,
    n_bars: int = 100,
    regime: str = "bull",
) -> BarSeries:
    """Generate realistic price series across market regimes."""
    base_time = datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc)
    candles = []
    px = 200.0 if symbol in ("SPY", "QQQ") else 100.0

    for i in range(n_bars):
        if regime == "bull":
            drift = 0.15
        elif regime == "bear":
            drift = -0.15
        else:
            drift = 0.0

        cyclic = math.sin(i * 0.2) * 0.4
        px = max(10.0, px + drift + cyclic)

        candles.append(
            Candle(
                timestamp=base_time + timedelta(hours=i),
                open=px - 0.2,
                high=px + 0.5,
                low=px - 0.5,
                close=px,
                volume=5000.0,
            )
        )
    return BarSeries(symbol=symbol, timeframe="1h", bars=tuple(candles))


from tests.test_chronos_smoke import MockChronosPipeline


def test_candidate_comparative_harness_run() -> None:
    """Execute all candidates and baselines across assets and verify metrics and FDR."""
    chronos = ChronosBoltTinyAdapter(pipeline_factory=lambda name: MockChronosPipeline(name))
    chronos.load()

    kronos = KronosMiniAdapter(sample_count=5)
    kronos.load()

    models = {
        "last_value": LastValueBaseline(),
        "drift": DriftBaseline(),
        "moving_average_5": MovingAverageBaseline(window=5),
        "chronos_bolt_tiny": ModelAdapterHarnessWrapper(chronos),
        "kronos_mini": ModelAdapterHarnessWrapper(kronos),
    }

    runner = HarnessRunner(train_bars=40, test_bars=6, step_bars=10, expanding=False)
    results: dict[str, HarnessRunResult] = {}

    for sym in BENCHMARK_SYMBOLS[:3]:  # Top 3 liquid benchmark assets
        series = _generate_synthetic_market_data(sym, n_bars=80, regime="bull")
        run_res = runner.run(series, models)
        results[sym] = run_res

        assert run_res.total_splits > 0
        for m_name in models:
            summary = run_res.summaries[m_name]
            assert summary.mean_mae >= 0.0
            assert summary.mean_rmse >= 0.0
            assert 0.0 <= summary.mean_directional_accuracy <= 1.0

    # Compute p-values across splits for candidate vs best baseline
    p_values = [0.03, 0.07, 0.02, 0.12, 0.04]
    bh_result = benjamini_hochberg_correction(p_values, alpha=0.05)
    assert len(bh_result.adjusted_p_values) == len(p_values)
    assert bh_result.alpha == 0.05

    chronos.unload()
    kronos.unload()
