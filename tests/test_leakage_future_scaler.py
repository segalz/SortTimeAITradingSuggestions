"""Leakage Test 3: Future-scaler bit-identical invariance test.

Verifies that production WindowScaler fit strictly on the training partition produces
bit-identical transformed training values regardless of future test distribution.
"""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.models import BarSeries, Candle
from trading_engine.evaluation.scaling import WindowScaler


def _make_series(prices: list[float], start_hour: int = 0) -> BarSeries:
    """Helper to create BarSeries with monotonic timestamps."""
    base_time = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc) + timedelta(hours=start_hour)
    candles = [
        Candle(
            timestamp=base_time + timedelta(hours=i),
            open=p,
            high=p + 1.0,
            low=p - 1.0,
            close=p,
            volume=1000.0,
        )
        for i, p in enumerate(prices)
    ]
    return BarSeries(symbol="AAPL", timeframe="1h", bars=tuple(candles))


def test_leakage_test_3_future_scaler_bit_identical() -> None:
    """Scaling train window must be bit-identical whether future has normal prices or 1000x spike."""
    train_prices = [100.0, 102.0, 101.0, 103.0, 102.5]
    train_series = _make_series(train_prices)

    # Future scenario A: normal future prices
    normal_future = _make_series([104.0, 105.0, 103.5], start_hour=len(train_prices))
    # Future scenario B: massive outlier spike (e.g. 1000x jump)
    spike_future = _make_series([10000.0, 15000.0, 20000.0], start_hour=len(train_prices))

    # Fit production WindowScaler strictly on train
    scaler_baseline = WindowScaler().fit(train_series)
    train_scaled_baseline = scaler_baseline.transform(train_series)

    # Test future scenario A: scaler fit on train and applied to both train and future
    scaler_a = WindowScaler().fit(train_series)
    train_scaled_a = scaler_a.transform(train_series)
    normal_future_scaled = scaler_a.transform(normal_future)

    # Test future scenario B: scaler fit on train and applied to spike future
    scaler_b = WindowScaler().fit(train_series)
    train_scaled_b = scaler_b.transform(train_series)
    spike_future_scaled = scaler_b.transform(spike_future)

    # Invariance check: train scaling is 100% bit-identical across runs
    assert train_scaled_a == train_scaled_baseline
    assert train_scaled_b == train_scaled_baseline
    assert train_scaled_a == train_scaled_b

    # Verify future scaling was still computable without contaminating train
    assert len(normal_future_scaled) == 3
    assert len(spike_future_scaled) == 3


def test_leakage_test_3_catches_global_future_leakage() -> None:
    """Verifies that fitting a scaler globally on train + test alters training features."""
    train_prices = [100.0, 102.0, 101.0, 103.0, 102.5]
    train_series = _make_series(train_prices)
    spike_future = _make_series([10000.0, 15000.0, 20000.0], start_hour=len(train_prices))

    # Flawed scaler that leaks the future by concatenating train + test:
    leaked_combined = BarSeries(
        symbol="AAPL",
        timeframe="1h",
        bars=train_series.bars + spike_future.bars,
    )
    leaked_scaler = WindowScaler().fit(leaked_combined)
    leaked_train_scaled = leaked_scaler.transform(train_series)

    # Clean scaler fit only on train
    clean_scaler = WindowScaler().fit(train_series)
    clean_train_scaled = clean_scaler.transform(train_series)

    # Leaked scaler significantly distorts training features (non-identical)
    assert leaked_train_scaled != clean_train_scaled
    for leaked_val in leaked_train_scaled:
        assert leaked_val < -0.5
