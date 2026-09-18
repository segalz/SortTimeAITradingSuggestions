"""Unit tests for BarSeries DataFrame conversions (to_dataframe / from_dataframe)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from trading_engine.data import BarSeries, Candle, DataContractError


def make_candle(minute: int = 0, **overrides):
    """Build a valid Candle at a given minute offset, with per-field overrides."""
    fields = dict(
        timestamp=datetime(2025, 1, 1, 0, minute, tzinfo=timezone.utc),
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
        vwap=None,
        amount=None,
    )
    fields.update(overrides)
    return Candle(**fields)


def make_series(**overrides):
    """Build a BarSeries of three ascending candles, allowing overrides."""
    fields = dict(
        symbol="aapl",
        timeframe="1m",
        bars=(
            make_candle(0, vwap=102.5, amount=102500.0),
            make_candle(1),
            make_candle(2, vwap=103.5, amount=103500.0),
        ),
    )
    fields.update(overrides)
    return BarSeries(**fields)


def assert_bars_match(actual: BarSeries, expected: BarSeries) -> None:
    """Assert two BarSeries carry equivalent symbols, timeframes and bars."""
    assert actual.symbol == expected.symbol
    assert actual.timeframe == expected.timeframe
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        assert got.timestamp == want.timestamp
        assert got.open == want.open
        assert got.high == want.high
        assert got.low == want.low
        assert got.close == want.close
        assert got.volume == want.volume
        assert got.vwap == want.vwap
        assert got.amount == want.amount


def test_to_dataframe():
    series = make_series()

    df = series.to_dataframe()

    # The index is a UTC DatetimeIndex named "timestamp".
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None and str(df.index.tz) == "UTC"
    assert df.index.name == "timestamp"

    # Column order matches the OHLCV + optional-fields contract.
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "vwap", "amount"]

    # Values mirror the underlying bars.
    assert len(df) == 3
    assert df.index[0] == pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    assert df.index[-1] == pd.Timestamp("2025-01-01 00:02:00", tz="UTC")
    assert df.iloc[0]["open"] == 100.0
    assert df.iloc[0]["vwap"] == 102.5
    assert pd.isna(df.iloc[1]["vwap"])
    assert pd.isna(df.iloc[1]["amount"])
    assert df.iloc[2]["amount"] == 103500.0


def test_from_dataframe_with_index():
    original = make_series()
    df = original.to_dataframe()  # UTC DatetimeIndex

    rebuilt = BarSeries.from_dataframe("aapl", "1m", df)

    assert_bars_match(rebuilt, original)


def test_from_dataframe_with_timestamp_column():
    timestamps = [
        datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc),
    ]
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0, 100.5, 101.0],
            "high": [110.0, 110.5, 111.0],
            "low": [90.0, 90.5, 91.0],
            "close": [105.0, 105.5, 106.0],
            "volume": [1000.0, 1100.0, 1200.0],
        }
    )

    series = BarSeries.from_dataframe("aapl", "1m", df)

    assert series.symbol == "AAPL"
    assert series.timeframe == "1m"
    assert len(series) == 3
    assert series.start_time() == timestamps[0]
    assert series.end_time() == timestamps[-1]
    assert series[1].close == 105.5
    assert series[2].volume == 1200.0


def test_from_dataframe_missing_column():
    df = pd.DataFrame(
        {
            "timestamp": [datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)],
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "volume": [1000.0],
            # "close" is missing.
        }
    )

    with pytest.raises(DataContractError):
        BarSeries.from_dataframe("aapl", "1m", df)


def test_empty_dataframe_roundtrip():
    # An empty DataFrame (no rows) yields an empty BarSeries.
    empty_df = pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume", "vwap", "amount"]
    )
    series = BarSeries.from_dataframe("aapl", "1m", empty_df)
    assert len(series) == 0
    assert series.start_time() is None
    assert series.end_time() is None

    # A fully empty DataFrame also works.
    bare_series = BarSeries.from_dataframe("aapl", "1m", pd.DataFrame())
    assert len(bare_series) == 0

    # Roundtripping an empty BarSeries stays empty.
    df = series.to_dataframe()
    assert df.empty
    roundtripped = BarSeries.from_dataframe("aapl", "1m", df)
    assert len(roundtripped) == 0


def test_from_dataframe_naive_timestamp_rejected():
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [105.0],
            "volume": [1000.0],
        },
        index=pd.to_datetime(["2025-01-01 00:00:00"]),  # Naive (no tz)
    )
    with pytest.raises(DataContractError, match="[Nn]aive"):
        BarSeries.from_dataframe("aapl", "1m", df)


def test_from_dataframe_non_utc_timestamp_rejected():
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [105.0],
            "volume": [1000.0],
        },
        index=pd.to_datetime(["2025-01-01 00:00:00-05:00"]),  # EST (non-UTC)
    )
    with pytest.raises(DataContractError, match="[Uu][Tt][Cc]"):
        BarSeries.from_dataframe("aapl", "1m", df)

