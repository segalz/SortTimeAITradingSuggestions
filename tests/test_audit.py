"""Tests for benchmark symbol definitions and data audit utilities."""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.data.audit import check_contiguous_depth, detect_split_spikes
from trading_engine.data.benchmarks import BENCHMARK_SYMBOLS, get_benchmark_symbols
from trading_engine.data.models import BarSeries, Candle


def _make_bars(prices: list[tuple[float, float, float, float]], interval_hours: int = 1) -> BarSeries:
    """Helper to construct BarSeries from (open, high, low, close) tuples."""
    base_time = datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base_time + timedelta(hours=i * interval_hours),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=1000.0,
        )
        for i, (o, h, l, c) in enumerate(prices)
    ]
    return BarSeries(symbol="TEST", timeframe="1h", bars=tuple(candles))


def test_benchmark_symbols_validity() -> None:
    """BENCHMARK_SYMBOLS contains the 5 required liquid tickers."""
    symbols = get_benchmark_symbols()
    assert len(symbols) == 5
    assert set(symbols) == {"SPY", "QQQ", "AAPL", "MSFT", "NVDA"}
    assert BENCHMARK_SYMBOLS == symbols


def test_detect_split_spikes_no_anomalies() -> None:
    """Normal price movement below threshold yields zero split anomalies."""
    # Prices moving within a few percent
    prices = [
        (100.0, 102.0, 99.0, 101.0),
        (101.0, 103.0, 100.0, 102.0),
        (102.5, 104.0, 101.5, 103.0),
    ]
    series = _make_bars(prices)
    anomalies = detect_split_spikes(series, threshold_ratio=0.35)
    assert anomalies == []


def test_detect_split_spikes_forward_split() -> None:
    """A 2-for-1 forward split (50% drop) is flagged as an anomaly."""
    prices = [
        (200.0, 205.0, 198.0, 202.0),
        (101.0, 103.0, 99.0, 102.0),  # Halved from 202.0 to 101.0 (49.9% drop)
        (102.0, 104.0, 101.0, 103.0),
    ]
    series = _make_bars(prices)
    anomalies = detect_split_spikes(series, threshold_ratio=0.35)

    assert len(anomalies) == 1
    assert anomalies[0].index == 1
    assert anomalies[0].prev_close == 202.0
    assert anomalies[0].curr_open == 101.0
    assert anomalies[0].price_change_ratio == pytest.approx(0.5, rel=1e-2)


def test_detect_split_spikes_three_for_two_split() -> None:
    """A 3-for-2 split (~33.3% drop) is caught with the default 0.30 threshold."""
    prices = [
        (150.0, 155.0, 148.0, 150.0),
        (100.0, 103.0, 99.0, 101.0),  # Dropped from 150.0 to 100.0 (33.33% drop)
        (101.0, 104.0, 100.0, 102.0),
    ]
    series = _make_bars(prices)
    anomalies = detect_split_spikes(series)  # Using default threshold 0.30

    assert len(anomalies) == 1
    assert anomalies[0].index == 1
    assert anomalies[0].price_change_ratio == pytest.approx(0.3333, rel=1e-2)


def test_detect_split_spikes_reverse_split() -> None:
    """A 1-for-4 reverse split (300% jump) is flagged as an anomaly."""
    prices = [
        (25.0, 26.0, 24.0, 25.0),
        (100.0, 105.0, 98.0, 102.0),  # Quadrupled from 25.0 to 100.0 (300% jump)
        (102.0, 104.0, 101.0, 103.0),
    ]
    series = _make_bars(prices)
    anomalies = detect_split_spikes(series, threshold_ratio=0.35)

    assert len(anomalies) == 1
    assert anomalies[0].index == 1
    assert anomalies[0].prev_close == 25.0
    assert anomalies[0].curr_open == 100.0
    assert anomalies[0].price_change_ratio == 3.0


def test_check_contiguous_depth_adequate() -> None:
    """Series with sufficient bars and no excessive gaps is marked adequate."""
    prices = [(100.0 + i, 102.0 + i, 99.0 + i, 101.0 + i) for i in range(120)]
    series = _make_bars(prices, interval_hours=1)

    result = check_contiguous_depth(series, min_bars=100, max_allowed_gap_hours=72.0)
    assert result.is_adequate is True
    assert result.bar_count == 120
    assert len(result.warnings) == 0
    assert result.max_gap_seconds == 3600.0


def test_check_contiguous_depth_empty() -> None:
    """Empty BarSeries returns is_adequate=False with warning."""
    empty = BarSeries(symbol="EMPTY", timeframe="1h", bars=())
    result = check_contiguous_depth(empty, min_bars=50)

    assert result.is_adequate is False
    assert result.bar_count == 0
    assert len(result.warnings) == 1
    assert "empty" in result.warnings[0].lower()


def test_check_contiguous_depth_insufficient_bars() -> None:
    """Series with fewer than min_bars returns is_adequate=False."""
    prices = [(100.0, 102.0, 99.0, 101.0) for _ in range(30)]
    series = _make_bars(prices, interval_hours=1)

    result = check_contiguous_depth(series, min_bars=50)
    assert result.is_adequate is False
    assert result.bar_count == 30
    assert any("Insufficient data depth" in w for w in result.warnings)


def test_check_contiguous_depth_gap_detection() -> None:
    """A gap exceeding max_allowed_gap_hours triggers a warning."""
    base_time = datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc)
    candles = [
        Candle(timestamp=base_time, open=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0),
        # 120 hours gap
        Candle(timestamp=base_time + timedelta(hours=120), open=101.0, high=103.0, low=100.0, close=102.0, volume=1000.0),
    ]
    series = BarSeries(symbol="GAP", timeframe="1h", bars=tuple(candles))

    result = check_contiguous_depth(series, min_bars=2, max_allowed_gap_hours=72.0)
    assert result.is_adequate is False
    assert any("exceeds limit" in w for w in result.warnings)
