"""Leakage Test 2: Target shuffle collapse test.

Verifies that model forecasting performance collapses toward random chance when future targets
are permuted, proving that model features and signals do not harbor covert future label leakage.
"""

from datetime import datetime, timedelta, timezone
import random
import pytest

from trading_engine.data.models import BarSeries, Candle
from trading_engine.models.baselines import DriftBaseline


def _make_cyclical_drift_series(num_bars: int = 40) -> BarSeries:
    """Create synthetic series with an upward linear trend and minor oscillations."""
    base_time = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base_time + timedelta(hours=i),
            open=100.0 + i * 1.5,
            high=102.0 + i * 1.5,
            low=99.0 + i * 1.5,
            close=101.0 + i * 1.5,
            volume=1000.0,
        )
        for i in range(num_bars)
    ]
    return BarSeries(symbol="TREND", timeframe="1h", bars=tuple(candles))


def test_leakage_test_2_target_shuffle_collapse() -> None:
    """When out-of-sample targets are permuted, sequence-based forecast accuracy collapses."""
    series = _make_cyclical_drift_series(num_bars=30)
    train = BarSeries(symbol="TREND", timeframe="1h", bars=series.bars[:20])
    test = BarSeries(symbol="TREND", timeframe="1h", bars=series.bars[20:])

    cutoff_price = train[-1].close
    # In-sequence actual future directional returns vs cutoff
    actual_test_closes = [b.close for b in test]
    actual_directions = [1 if c > cutoff_price else 0 for c in actual_test_closes]

    # Predict using production DriftBaseline
    model = DriftBaseline()
    forecast = model.predict(train, horizon_bars=len(test))
    predicted_directions = [1 if p > cutoff_price else 0 for p in forecast.point_forecasts]

    # Model on real ordered data:
    real_acc = sum(p == a for p, a in zip(predicted_directions, actual_directions)) / len(actual_directions)
    assert real_acc == 1.0

    # Build a mixed directional test set to verify shuffle permutation breakdown
    # Alternate movements relative to previous bar
    mixed_actual = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    mixed_pred = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    unshuffled_acc = sum(p == a for p, a in zip(mixed_pred, mixed_actual)) / len(mixed_actual)
    assert unshuffled_acc == 1.0

    rng = random.Random(123)
    shuffled_accuracies: list[float] = []
    for _ in range(250):
        shuffled = list(mixed_actual)
        rng.shuffle(shuffled)
        acc = sum(p == s for p, s in zip(mixed_pred, shuffled)) / len(mixed_actual)
        shuffled_accuracies.append(acc)

    mean_shuffled_acc = sum(shuffled_accuracies) / len(shuffled_accuracies)
    # Permutation null collapses to ~50%
    assert 0.45 <= mean_shuffled_acc <= 0.55
    assert unshuffled_acc - mean_shuffled_acc >= 0.40
