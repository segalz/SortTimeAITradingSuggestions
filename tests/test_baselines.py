"""Unit tests for quantitative baseline forecasting models."""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.models import BarSeries, Candle
from trading_engine.models.baselines import (
    DriftBaseline,
    Forecast,
    LastValueBaseline,
    MovingAverageBaseline,
)


def _make_series(close_prices: list[float]) -> BarSeries:
    """Helper to construct a BarSeries from close prices."""
    base_time = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base_time + timedelta(hours=i),
            open=c - 1.0,
            high=c + 1.0,
            low=c - 2.0,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(close_prices)
    ]
    return BarSeries(symbol="AAPL", timeframe="1h", bars=tuple(candles))


def test_last_value_baseline_prediction() -> None:
    """LastValueBaseline projects constant last observed price across the horizon."""
    series = _make_series([100.0, 102.0, 105.0])
    model = LastValueBaseline()
    forecast = model.predict(series, horizon_bars=4)

    assert isinstance(forecast, Forecast)
    assert forecast.symbol == "AAPL"
    assert forecast.timeframe == "1h"
    assert forecast.horizon_bars == 4
    assert forecast.point_forecasts == (105.0, 105.0, 105.0, 105.0)


def test_last_value_baseline_empty_raises() -> None:
    """Predicting on empty history raises ValueError."""
    empty = BarSeries(symbol="AAPL", timeframe="1h", bars=())
    model = LastValueBaseline()
    with pytest.raises(ValueError, match="empty history"):
        model.predict(empty, horizon_bars=3)


def test_drift_baseline_positive_drift() -> None:
    """DriftBaseline extrapolates constant linear slope over history."""
    # Prices: 100, 102, 104 -> slope = (104 - 100) / 2 = 2.0 per bar
    series = _make_series([100.0, 102.0, 104.0])
    model = DriftBaseline()
    forecast = model.predict(series, horizon_bars=3)

    assert forecast.horizon_bars == 3
    # Next 3 steps: 104 + 2 = 106, 104 + 4 = 108, 104 + 6 = 110
    assert forecast.point_forecasts == (106.0, 108.0, 110.0)


def test_drift_baseline_single_bar() -> None:
    """Single bar history has zero drift, behaving like last value."""
    series = _make_series([150.0])
    model = DriftBaseline()
    forecast = model.predict(series, horizon_bars=2)
    assert forecast.point_forecasts == (150.0, 150.0)


def test_drift_baseline_negative_drift() -> None:
    """DriftBaseline correctly handles downward slope."""
    # Prices: 100, 95, 90 -> slope = (90 - 100) / 2 = -5.0
    series = _make_series([100.0, 95.0, 90.0])
    model = DriftBaseline()
    forecast = model.predict(series, horizon_bars=2)
    assert forecast.point_forecasts == (85.0, 80.0)


def test_drift_baseline_clamps_at_price_floor() -> None:
    """DriftBaseline clamps to 0.01 floor when downward slope exceeds price."""
    # Prices: 10, 5 -> slope = -5.0 per bar. Without clamp, step 2 = -5.0
    series = _make_series([10.0, 5.0])
    model = DriftBaseline()
    forecast = model.predict(series, horizon_bars=3)
    # Step 1: 5.0 - 5.0 = 0.0 -> clamped to 0.01
    # Step 2: 5.0 - 10.0 = -5.0 -> clamped to 0.01
    # Step 3: 5.0 - 15.0 = -10.0 -> clamped to 0.01
    assert forecast.point_forecasts == (0.01, 0.01, 0.01)


def test_moving_average_baseline_window() -> None:
    """MovingAverageBaseline projects the mean of the last `window` bars."""
    # 5 bars, window=3: last 3 are 10, 20, 30 -> mean = 20.0
    series = _make_series([5.0, 8.0, 10.0, 20.0, 30.0])
    model = MovingAverageBaseline(window=3)
    forecast = model.predict(series, horizon_bars=3)

    assert forecast.point_forecasts == (20.0, 20.0, 20.0)


def test_moving_average_baseline_shorter_than_window() -> None:
    """When history is shorter than window, uses all available bars."""
    # 2 bars: 10, 20 -> mean = 15.0
    series = _make_series([10.0, 20.0])
    model = MovingAverageBaseline(window=5)
    forecast = model.predict(series, horizon_bars=2)

    assert forecast.point_forecasts == (15.0, 15.0)


def test_moving_average_invalid_window() -> None:
    """Non-positive window raises ValueError."""
    with pytest.raises(ValueError, match="Moving average window must be positive"):
        MovingAverageBaseline(window=0)


def test_forecast_dataclass_validation() -> None:
    """Forecast enforces horizon_bars > 0 and point_forecasts length matching."""
    with pytest.raises(ValueError, match="horizon_bars must be positive"):
        Forecast(symbol="AAPL", timeframe="1h", horizon_bars=0, point_forecasts=())

    with pytest.raises(ValueError, match="Expected 3 point forecasts, got 2"):
        Forecast(symbol="AAPL", timeframe="1h", horizon_bars=3, point_forecasts=(1.0, 2.0))
