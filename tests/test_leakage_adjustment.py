"""Leakage Test 5: Price adjustment consistency and point-in-time corporate action check.

Verifies that future corporate actions (splits/dividends occurring after cutoff T)
never retroactively alter the point-in-time prices observed at cutoff T.
"""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.adjustment import SplitAction, apply_point_in_time_splits
from trading_engine.data.models import BarSeries, Candle


def test_leakage_test_5_future_split_does_not_leak_into_cutoff_history() -> None:
    """A future split occurring at Day 10 must not alter point-in-time prices at Day 5."""
    base = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    raw_candles = [
        Candle(
            timestamp=base + timedelta(days=i),
            open=200.0,
            high=205.0,
            low=195.0,
            close=200.0,
            volume=1000.0,
        )
        for i in range(5)  # Days 0, 1, 2, 3, 4
    ]
    raw_series = BarSeries(symbol="TEST", timeframe="1d", bars=tuple(raw_candles))

    future_split = SplitAction(
        symbol="TEST",
        effective_date=base + timedelta(days=10),  # In the future!
        split_ratio=2.0,
    )

    cutoff_t = base + timedelta(days=5)

    # Point-in-time adjustment as of Day 5
    pit_adjusted = apply_point_in_time_splits(raw_series, [future_split], as_of_time=cutoff_t)

    # Prices observed at Day 5 remain unchanged (200.0), future split was not leaked
    assert len(pit_adjusted) == 5
    for bar in pit_adjusted:
        assert bar.close == 200.0


def test_leakage_test_5_past_split_is_properly_applied() -> None:
    """A split effective before cutoff correctly adjusts historical bars preceding it."""
    base = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    raw_candles = [
        # Bar 0: Day 1 (before split)
        Candle(timestamp=base, open=200.0, high=205.0, low=195.0, close=200.0, volume=1000.0),
        # Bar 1: Day 3 (after split)
        Candle(timestamp=base + timedelta(days=2), open=100.0, high=103.0, low=98.0, close=100.0, volume=2000.0),
    ]
    raw_series = BarSeries(symbol="TEST", timeframe="1d", bars=tuple(raw_candles))

    past_split = SplitAction(
        symbol="TEST",
        effective_date=base + timedelta(days=1),  # Effective Day 2 (between bar 0 and bar 1)
        split_ratio=2.0,
    )

    as_of = base + timedelta(days=3)
    pit_adjusted = apply_point_in_time_splits(raw_series, [past_split], as_of_time=as_of)

    # Bar 0 (prior to split) is adjusted from 200 to 100
    assert pit_adjusted[0].close == 100.0
    # Bar 1 (after split) remains 100
    assert pit_adjusted[1].close == 100.0


def test_split_action_validation() -> None:
    """SplitAction validates ratio > 0 and timezone awareness."""
    with pytest.raises(ValueError, match="split_ratio must be positive"):
        SplitAction(symbol="AAPL", effective_date=datetime.now(timezone.utc), split_ratio=0.0)

    with pytest.raises(ValueError, match="effective_date must be timezone-aware"):
        SplitAction(symbol="AAPL", effective_date=datetime(2026, 1, 1), split_ratio=2.0)
