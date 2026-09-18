"""Leakage Test 4: Incomplete live candle exclusion test.

Verifies that unclosed/forming candles are strictly excluded from decision sets,
preventing intra-candle lookahead distortion.
"""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.models import BarSeries, Candle, filter_completed_candles


def _make_hourly_series() -> BarSeries:
    """Create 3 hourly candles: 14:00, 15:00, 16:00 UTC."""
    base = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    candles = [
        Candle(timestamp=base, open=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0),
        Candle(timestamp=base + timedelta(hours=1), open=101.0, high=103.0, low=100.0, close=102.0, volume=1100.0),
        Candle(timestamp=base + timedelta(hours=2), open=102.0, high=104.0, low=101.0, close=103.0, volume=1200.0),
    ]
    return BarSeries(symbol="AAPL", timeframe="1h", bars=tuple(candles))


def test_filter_completed_candles_excludes_active_forming_candle() -> None:
    """At 16:45 UTC, the 16:00 candle is still forming and must be excluded."""
    series = _make_hourly_series()
    # At 16:45 UTC:
    # 14:00 bar completed at 15:00
    # 15:00 bar completed at 16:00
    # 16:00 bar completes at 17:00 -> INCOMPLETE
    current_time = datetime(2026, 3, 1, 16, 45, tzinfo=timezone.utc)
    filtered = filter_completed_candles(series, current_time=current_time)

    assert len(filtered) == 2
    assert filtered[-1].timestamp == datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)


def test_filter_completed_candles_includes_just_closed_candle() -> None:
    """At exactly 17:00 UTC, the 16:00-17:00 candle has closed and is included."""
    series = _make_hourly_series()
    current_time = datetime(2026, 3, 1, 17, 0, tzinfo=timezone.utc)
    filtered = filter_completed_candles(series, current_time=current_time)

    assert len(filtered) == 3
    assert filtered[-1].timestamp == datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc)


def test_filter_completed_candles_rejects_naive_datetime() -> None:
    """Naive current_time raises ValueError."""
    series = _make_hourly_series()
    with pytest.raises(ValueError, match="must be timezone-aware"):
        filter_completed_candles(series, current_time=datetime(2026, 3, 1, 17, 0))


def test_filter_completed_candles_unsupported_timeframe() -> None:
    """Series with unregistered timeframe raises ValueError."""
    candle = Candle(
        timestamp=datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=500.0,
    )
    custom_series = BarSeries(symbol="AAPL", timeframe="3m", bars=(candle,))
    with pytest.raises(ValueError, match="Unknown timeframe duration"):
        filter_completed_candles(custom_series, current_time=datetime(2026, 3, 1, 14, 5, tzinfo=timezone.utc))
