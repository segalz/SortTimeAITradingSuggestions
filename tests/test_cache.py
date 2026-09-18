"""Tests for ParquetDataCache persistent market data caching."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from trading_engine.data.cache import CacheError, ParquetDataCache
from trading_engine.data.models import BarSeries, Candle


def _make_sample_series(symbol: str = "AAPL", num_bars: int = 3, start_day: int = 1) -> BarSeries:
    """Helper to generate a sample BarSeries."""
    candles = [
        Candle(
            timestamp=datetime(2026, 3, start_day + i, 14, 30, tzinfo=timezone.utc),
            open=100.0 + i,
            high=105.0 + i,
            low=99.0 + i,
            close=104.0 + i,
            volume=1000.0 * (i + 1),
            vwap=102.0 + i,
        )
        for i in range(num_bars)
    ]
    return BarSeries(symbol=symbol, timeframe="1h", bars=tuple(candles))


def test_cache_file_path_generation(tmp_path: Path) -> None:
    """Canonical file path matches base_dir / SYMBOL / timeframe.parquet."""
    cache = ParquetDataCache(base_dir=tmp_path)
    path = cache.get_file_path("aapl", "1H")
    assert path == tmp_path / "AAPL" / "1h.parquet"


def test_cache_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Saving and loading returns bit-identical BarSeries data."""
    cache = ParquetDataCache(base_dir=tmp_path)
    series = _make_sample_series("MSFT", num_bars=4)

    saved_path = cache.save_bars(series)
    assert saved_path.exists()

    loaded = cache.load_bars("msft", "1h")
    assert loaded is not None
    assert isinstance(loaded, BarSeries)
    assert loaded.symbol == "MSFT"
    assert loaded.timeframe == "1h"
    assert len(loaded) == 4
    for orig, roundtrip in zip(series, loaded):
        assert orig.timestamp == roundtrip.timestamp
        assert orig.open == roundtrip.open
        assert orig.high == roundtrip.high
        assert orig.low == roundtrip.low
        assert orig.close == roundtrip.close
        assert orig.volume == roundtrip.volume


def test_cache_save_empty_series_raises(tmp_path: Path) -> None:
    """Attempting to cache an empty BarSeries raises CacheError."""
    cache = ParquetDataCache(base_dir=tmp_path)
    empty_series = BarSeries(symbol="AAPL", timeframe="1h", bars=())
    with pytest.raises(CacheError, match="Cannot cache empty BarSeries"):
        cache.save_bars(empty_series)


def test_cache_load_miss_returns_none(tmp_path: Path) -> None:
    """Non-existent cache returns None."""
    cache = ParquetDataCache(base_dir=tmp_path)
    assert cache.load_bars("GOOGL", "1d") is None


def test_cache_load_date_range_filter(tmp_path: Path) -> None:
    """Date range filter correctly slices cached bars."""
    cache = ParquetDataCache(base_dir=tmp_path)
    series = _make_sample_series("NVDA", num_bars=5, start_day=1)  # Days 1, 2, 3, 4, 5
    cache.save_bars(series)

    # Filter days 2 to 4
    filtered = cache.load_bars(
        "NVDA",
        "1h",
        start=datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 3, 4, 23, 59, tzinfo=timezone.utc),
    )
    assert filtered is not None
    assert len(filtered) == 3
    assert filtered[0].timestamp.day == 2
    assert filtered[-1].timestamp.day == 4


def test_cache_load_empty_range_returns_none(tmp_path: Path) -> None:
    """Date range completely outside cached data returns None."""
    cache = ParquetDataCache(base_dir=tmp_path)
    series = _make_sample_series("AMD", num_bars=3, start_day=1)
    cache.save_bars(series)

    result = cache.load_bars(
        "AMD",
        "1h",
        start=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert result is None


def test_cache_naive_datetime_rejected(tmp_path: Path) -> None:
    """Naive datetime passed to load_bars raises ValueError."""
    cache = ParquetDataCache(base_dir=tmp_path)
    with pytest.raises(ValueError, match="must be timezone-aware"):
        cache.load_bars("AAPL", "1h", start=datetime(2026, 3, 1, 0, 0))


def test_cache_merge_deduplication(tmp_path: Path) -> None:
    """Incremental save merges and updates duplicate bars without creating duplicates."""
    cache = ParquetDataCache(base_dir=tmp_path)

    # Batch 1: days 1, 2, 3
    batch1 = _make_sample_series("TSLA", num_bars=3, start_day=1)
    cache.save_bars(batch1)

    # Batch 2: days 3, 4, 5 (day 3 has updated close price)
    day3_updated = Candle(
        timestamp=datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc),
        open=102.0,
        high=115.0,
        low=101.0,
        close=114.0,  # Updated from 106.0
        volume=5000.0,
        vwap=108.0,
    )
    day4 = Candle(
        timestamp=datetime(2026, 3, 4, 14, 30, tzinfo=timezone.utc),
        open=103.0,
        high=108.0,
        low=102.0,
        close=107.0,
        volume=2000.0,
        vwap=105.0,
    )
    batch2 = BarSeries(symbol="TSLA", timeframe="1h", bars=(day3_updated, day4))
    cache.save_bars(batch2, merge=True)

    loaded = cache.load_bars("TSLA", "1h")
    assert loaded is not None
    assert len(loaded) == 4  # days 1, 2, 3, 4 (no duplicate day 3)
    assert loaded[2].timestamp.day == 3
    assert loaded[2].close == 114.0  # Updated value was kept
