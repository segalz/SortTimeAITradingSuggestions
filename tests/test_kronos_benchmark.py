"""Benchmark measuring KronosMiniAdapter latency at sample_count=1 vs sample_count=15 across walk-forward splits."""

from datetime import datetime, timedelta, timezone
import statistics
import time
import pytest

from trading_engine.contracts.device import get_process_rss_mb
from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.data.benchmarks import BENCHMARK_SYMBOLS
from trading_engine.data.models import BarSeries, Candle
from trading_engine.evaluation.walk_forward import generate_walk_forward_splits
from trading_engine.models.kronos_adapter import KronosMiniAdapter


def _build_series(symbol: str, n_bars: int = 60) -> BarSeries:
    base = datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc)
    candles = []
    px = 150.0
    for i in range(n_bars):
        px = max(10.0, px + 0.2 * ((i % 3) - 1))
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=i),
                open=px - 0.2,
                high=px + 0.4,
                low=px - 0.4,
                close=px,
                volume=3000.0,
            )
        )
    return BarSeries(symbol=symbol, timeframe="1h", bars=tuple(candles))


def test_kronos_sample_count_latency_comparison_and_memory() -> None:
    adapter_single = KronosMiniAdapter(sample_count=1, max_horizon_bars=24)
    adapter_multi = KronosMiniAdapter(sample_count=15, max_horizon_bars=24)

    adapter_single.load()
    adapter_multi.load()

    series = _build_series("SPY", n_bars=60)
    splits = generate_walk_forward_splits(
        series,
        train_bars=25,
        test_bars=5,
        step_bars=10,
        expanding=False,
    )
    assert len(splits) > 0

    latencies_single: list[float] = []
    latencies_multi: list[float] = []

    for split in splits:
        req = ForecastRequest(
            symbol="SPY",
            timeframe="1h",
            history=split.train,
            horizon_bars=len(split.test),
            quantiles=(0.10, 0.50, 0.90),
        )

        t0 = time.perf_counter()
        res_single = adapter_single.predict(req)
        latencies_single.append((time.perf_counter() - t0) * 1000.0)

        t1 = time.perf_counter()
        res_multi = adapter_multi.predict(req)
        latencies_multi.append((time.perf_counter() - t1) * 1000.0)

        assert isinstance(res_single, ForecastResult)
        assert isinstance(res_multi, ForecastResult)

    rss_mb = get_process_rss_mb()

    adapter_single.unload()
    adapter_multi.unload()

    mean_single = statistics.mean(latencies_single)
    mean_multi = statistics.mean(latencies_multi)
    p50_multi = statistics.median(latencies_multi)
    p95_multi = sorted(latencies_multi)[int(0.95 * len(latencies_multi))]

    # Single-sample should be faster than multi-sample
    assert mean_single <= mean_multi

    # Invariants: P50 latency < 250ms, P95 < 500ms, RSS < 1024MB
    assert p50_multi < 250.0, f"P50 latency {p50_multi:.2f}ms exceeds 250ms"
    assert p95_multi < 500.0, f"P95 latency {p95_multi:.2f}ms exceeds 500ms"
    assert rss_mb < 1024.0, f"RSS memory {rss_mb:.2f}MB exceeds 1024MB"
