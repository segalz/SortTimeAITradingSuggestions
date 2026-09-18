"""Tests for evaluation metrics, Benjamini-Hochberg stats, and walk-forward HarnessRunner."""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.models import BarSeries, Candle
from trading_engine.evaluation.harness import HarnessRunner
from trading_engine.evaluation.metrics import calculate_metrics
from trading_engine.evaluation.stats import benjamini_hochberg_correction
from trading_engine.models.baselines import DriftBaseline, LastValueBaseline, MovingAverageBaseline


def _make_series(num_bars: int = 50) -> BarSeries:
    """Create synthetic continuous hourly series."""
    base_time = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base_time + timedelta(hours=i),
            open=100.0 + i,
            high=102.0 + i,
            low=99.0 + i,
            close=101.0 + i,
            volume=1000.0,
        )
        for i in range(num_bars)
    ]
    return BarSeries(symbol="AAPL", timeframe="1h", bars=tuple(candles))


def test_metrics_calculation_perfect_match() -> None:
    """Perfect prediction yields zero error and 100% directional accuracy."""
    actual = [100.0, 102.0, 105.0]
    predicted = [100.0, 102.0, 105.0]
    metrics = calculate_metrics(actual, predicted, base_price=99.0)

    assert metrics.mae == 0.0
    assert metrics.rmse == 0.0
    assert metrics.directional_accuracy == 1.0
    assert metrics.mape == 0.0


def test_metrics_flat_prediction_neutral_directional_accuracy() -> None:
    """Flat predictions receive 0.5 neutral directional score when actual moved."""
    actual = [105.0, 110.0]
    predicted = [100.0, 100.0]  # Flat at cutoff base_price=100.0
    metrics = calculate_metrics(actual, predicted, base_price=100.0)

    assert metrics.directional_accuracy == 0.5


def test_metrics_calculation_known_values() -> None:
    """Explicit values match standard formula results."""
    actual = [10.0, 20.0]
    predicted = [12.0, 16.0]
    # Abs errors: 2, 4 -> MAE = 3.0
    # Sq errors: 4, 16 = 20 -> RMSE = sqrt(10) = 3.162278
    # MAPE: 2/10 = 0.2, 4/20 = 0.2 -> mean = 0.2 -> 20.0%
    metrics = calculate_metrics(actual, predicted)

    assert metrics.mae == 3.0
    assert metrics.rmse == pytest.approx(3.162278, rel=1e-4)
    assert metrics.mape == 20.0


def test_metrics_empty_or_mismatch_raises() -> None:
    """Empty sequences or length mismatch raise ValueError."""
    with pytest.raises(ValueError, match="empty sequences"):
        calculate_metrics([], [])

    with pytest.raises(ValueError, match="Length mismatch"):
        calculate_metrics([1.0, 2.0], [1.0])


def test_benjamini_hochberg_correction() -> None:
    """Benjamini-Hochberg procedure controls FDR and adjusts p-values monotonically."""
    # 4 p-values: 0.01, 0.04, 0.03, 0.20
    # Ranks:
    # 1: 0.01 -> adj = (4/1)*0.01 = 0.04
    # 2: 0.03 -> adj = (4/2)*0.03 = 0.06
    # 3: 0.04 -> adj = (4/3)*0.04 = 0.0533 -> min with next (0.20)
    # 4: 0.20 -> adj = (4/4)*0.20 = 0.20
    raw_p = [0.01, 0.04, 0.03, 0.20]
    result = benjamini_hochberg_correction(raw_p, alpha=0.05)

    assert len(result.adjusted_p_values) == 4
    # Check that rank 1 (0.01) is rejected at alpha=0.05
    assert result.rejected[0] is True
    # Highest p-value (0.20) is not rejected
    assert result.rejected[3] is False


def test_benjamini_hochberg_empty() -> None:
    """Empty sequence returns empty correction result."""
    result = benjamini_hochberg_correction([])
    assert result.p_values == ()
    assert result.adjusted_p_values == ()


def test_harness_runner_execution() -> None:
    """HarnessRunner evaluates multiple baselines across rolling splits."""
    series = _make_series(num_bars=30)
    models = {
        "last_value": LastValueBaseline(),
        "drift": DriftBaseline(),
        "ma5": MovingAverageBaseline(window=5),
    }

    runner = HarnessRunner(train_bars=15, test_bars=3, step_bars=2)
    result = runner.run(series, models)

    assert result.symbol == "AAPL"
    assert result.timeframe == "1h"
    # Total 30 bars, window 18, step 2:
    # start 0, 2, 4, 6, 8, 10, 12 -> 7 splits
    assert result.total_splits == 7
    assert len(result.summaries) == 3

    for name in ["last_value", "drift", "ma5"]:
        summary = result.summaries[name]
        assert summary.model_name == name
        assert summary.split_count == 7
        assert summary.mean_mae >= 0.0
        assert summary.mean_rmse >= 0.0
        assert 0.0 <= summary.mean_directional_accuracy <= 1.0


def test_harness_runner_insufficient_data_raises() -> None:
    """Series shorter than required window raises ValueError."""
    series = _make_series(num_bars=10)
    models = {"last_value": LastValueBaseline()}
    runner = HarnessRunner(train_bars=10, test_bars=5)

    with pytest.raises(ValueError, match="Insufficient data depth"):
        runner.run(series, models)
