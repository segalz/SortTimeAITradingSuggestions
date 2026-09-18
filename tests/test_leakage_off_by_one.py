"""Leakage Test 1: Strict off-by-one bar close timestamp assertion.

Validates that training/calibration sets never include the forecast period's first bar
and that no feature calculation at cutoff T can observe bar close prices from T + 1.
"""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.models import BarSeries, Candle
from trading_engine.evaluation.walk_forward import WalkForwardSplit, generate_walk_forward_splits


def _make_series(num_bars: int = 50) -> BarSeries:
    """Create continuous hourly series."""
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
    return BarSeries(symbol="TEST", timeframe="1h", bars=tuple(candles))


def test_leakage_test_1_off_by_one_timestamp_assertion() -> None:
    """Ensure training window strictly ends at cutoff and test window strictly begins after cutoff."""
    series = _make_series(num_bars=40)
    splits = generate_walk_forward_splits(series=series, train_bars=15, test_bars=5, step_bars=2)

    assert len(splits) > 0

    for split in splits:
        train_last_bar = split.train[-1]
        test_first_bar = split.test[0]

        # 1. Cutoff matches exactly the last available train bar
        assert split.cutoff == train_last_bar.timestamp

        # 2. Strict inequality: train end MUST strictly precede test start
        assert train_last_bar.timestamp < test_first_bar.timestamp

        # 3. Off-by-one check: test start is exactly cutoff + 1 interval (no overlapping bars)
        expected_test_start = train_last_bar.timestamp + timedelta(hours=1)
        assert test_first_bar.timestamp == expected_test_start

        # 4. Set intersection of timestamps between train and test must be completely empty
        train_timestamps = {b.timestamp for b in split.train}
        test_timestamps = {b.timestamp for b in split.test}
        assert train_timestamps.isdisjoint(test_timestamps)


def test_leakage_test_1_detects_deliberate_off_by_one_leak() -> None:
    """Verifies that injecting an off-by-one overlapping bar triggers a data leakage error."""
    series = _make_series(num_bars=10)

    # Deliberately construct an overlapping split (off-by-one leak)
    leaked_train = BarSeries(symbol="TEST", timeframe="1h", bars=series.bars[0:6])
    leaked_test = BarSeries(symbol="TEST", timeframe="1h", bars=series.bars[5:9])  # bar 5 is in both!

    with pytest.raises(ValueError, match="Data leakage detected"):
        WalkForwardSplit(
            split_index=0,
            cutoff=leaked_train[-1].timestamp,
            train=leaked_train,
            test=leaked_test,
        )
