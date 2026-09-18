"""Tests for chronological rolling-origin walk-forward evaluation splitter."""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.models import BarSeries, Candle
from trading_engine.evaluation.walk_forward import WalkForwardSplit, generate_walk_forward_splits


def _make_series(num_bars: int = 50) -> BarSeries:
    """Create synthetic BarSeries with consecutive hourly bars."""
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


def test_generate_splits_basic_rolling() -> None:
    """Rolling window produces correct split count, window sizes, and cutoff times."""
    series = _make_series(num_bars=20)
    splits = generate_walk_forward_splits(
        series=series,
        train_bars=10,
        test_bars=3,
        step_bars=2,
        expanding=False,
    )

    # Total 20 bars, required 13 bars:
    # start 0 -> train [0:10], test [10:13] (ends at index 13)
    # start 2 -> train [2:12], test [12:15]
    # start 4 -> train [4:14], test [14:17]
    # start 6 -> train [6:16], test [16:19]
    # start 8 -> train [8:18], test [18:21] > 20 -> stops
    assert len(splits) == 4

    for i, split in enumerate(splits):
        assert split.split_index == i
        assert len(split.train) == 10
        assert len(split.test) == 3
        assert split.cutoff == split.train[-1].timestamp
        assert split.train[-1].timestamp < split.test[0].timestamp


def test_generate_splits_expanding_window() -> None:
    """Expanding window grows training size from initial origin."""
    series = _make_series(num_bars=20)
    splits = generate_walk_forward_splits(
        series=series,
        train_bars=10,
        test_bars=2,
        step_bars=3,
        expanding=True,
    )

    assert len(splits) == 3
    # Split 0: train [0:10] (len 10)
    # Split 1: train [0:13] (len 13)
    # Split 2: train [0:16] (len 16)
    assert len(splits[0].train) == 10
    assert len(splits[1].train) == 13
    assert len(splits[2].train) == 16
    assert splits[0].train[0].timestamp == splits[1].train[0].timestamp


def test_generate_splits_zero_time_travel() -> None:
    """Strict non-leakage invariant holds for all generated splits."""
    series = _make_series(num_bars=30)
    splits = generate_walk_forward_splits(series=series, train_bars=12, test_bars=4, step_bars=1)

    for split in splits:
        assert split.train[-1].timestamp < split.test[0].timestamp
        # Out-of-sample test start is exactly the next bar
        assert split.test[0].timestamp == split.train[-1].timestamp + timedelta(hours=1)


def test_generate_splits_insufficient_bars() -> None:
    """Series with fewer bars than train_bars + test_bars yields zero splits."""
    series = _make_series(num_bars=10)
    splits = generate_walk_forward_splits(series=series, train_bars=8, test_bars=4)
    assert splits == []


def test_generate_splits_invalid_args() -> None:
    """Non-positive parameters raise ValueError."""
    series = _make_series(num_bars=20)
    with pytest.raises(ValueError, match="train_bars must be positive"):
        generate_walk_forward_splits(series, train_bars=0, test_bars=5)
    with pytest.raises(ValueError, match="test_bars must be positive"):
        generate_walk_forward_splits(series, train_bars=10, test_bars=-1)
    with pytest.raises(ValueError, match="step_bars must be positive"):
        generate_walk_forward_splits(series, train_bars=10, test_bars=5, step_bars=0)


def test_walk_forward_split_leakage_post_init() -> None:
    """WalkForwardSplit dataclass rejects leaked future timestamps in train."""
    series = _make_series(num_bars=10)
    # Inverted: train ends after test starts
    invalid_train = BarSeries(symbol="TEST", timeframe="1h", bars=series.bars[4:8])
    invalid_test = BarSeries(symbol="TEST", timeframe="1h", bars=series.bars[0:3])

    with pytest.raises(ValueError, match="Data leakage detected"):
        WalkForwardSplit(
            split_index=0,
            cutoff=invalid_train[-1].timestamp,
            train=invalid_train,
            test=invalid_test,
        )
