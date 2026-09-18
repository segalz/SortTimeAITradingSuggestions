"""Unit tests for trading_engine.data BarSeries and DataQualityError."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trading_engine.data import BarSeries, Candle, DataQualityError


def make_candle(minute: int = 0, **overrides):
    """Build a valid Candle at a given minute offset, with per-field overrides."""
    fields = dict(
        timestamp=datetime(2025, 1, 1, 0, minute, tzinfo=timezone.utc),
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
    )
    fields.update(overrides)
    return Candle(**fields)


def make_series(**overrides):
    """Build a BarSeries of three ascending candles, allowing overrides."""
    fields = dict(
        symbol="aapl",
        timeframe="1m",
        bars=(
            make_candle(0),
            make_candle(1),
            make_candle(2),
        ),
    )
    fields.update(overrides)
    return BarSeries(**fields)


def test_valid_bar_series():
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc)

    series = make_series()

    assert series.symbol == "AAPL"  # symbol is uppercased
    assert len(series) == 3

    # Indexing works for single items and slices.
    assert series[0].timestamp == start
    assert series[1].timestamp == datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc)
    assert series[2].timestamp == end
    assert len(series[0:2]) == 2

    assert series.start_time() == start
    assert series.end_time() == end


def test_duplicate_timestamp_rejected():
    duplicate = make_candle(1)

    with pytest.raises(DataQualityError):
        make_series(bars=(make_candle(0), duplicate, make_candle(1)))


def test_out_of_order_timestamp_rejected():
    with pytest.raises(DataQualityError):
        make_series(bars=(make_candle(1), make_candle(0)))


def test_empty_bar_series():
    series = make_series(bars=())

    assert len(series) == 0
    assert series.start_time() is None
    assert series.end_time() is None
