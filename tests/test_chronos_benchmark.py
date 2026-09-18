"""Walk-forward benchmarking of ChronosBoltTinyAdapter measuring P50/P95 latency and RSS memory."""

from datetime import datetime, timedelta, timezone
import statistics
import time
import pytest

from trading_engine.contracts.device import get_process_rss_mb
from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.data.benchmarks import BENCHMARK_SYMBOLS
from trading_engine.data.models import BarSeries, Candle
from trading_engine.evaluation.walk_forward import generate_walk_forward_splits
from trading_engine.models.chronos_adapter import ChronosBoltTinyAdapter
from tests.test_chronos_smoke import MockChronosPipeline


def _build_synthetic_benchmark_series(symbol: str, n_bars: int = 120) -> BarSeries:
    base = datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc)
    candles = []
    price = 200.0
    for i in range(n_bars):
        # Slight drift plus oscillation
        price = max(10.0, price + 0.15 * ((i % 5) - 2))
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=i),
                open=price - 0.2,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=5000.0,
            )
        )
    return BarSeries(symbol=symbol, timeframe="1h", bars=tuple(candles))


def test_chronos_walk_forward_benchmark_latency_and_memory() -> None:
    adapter = ChronosBoltTinyAdapter(
        pipeline_factory=lambda name: MockChronosPipeline(name),
        max_horizon_bars=24,
    )
    adapter.load()
    assert adapter.is_loaded

    all_latencies_ms: list[float] = []

    for symbol in BENCHMARK_SYMBOLS:
        series = _build_synthetic_benchmark_series(symbol, n_bars=80)
        splits = generate_walk_forward_splits(
            series,
            train_bars=30,
            test_bars=6,
            step_bars=10,
            expanding=False,
        )
        assert len(splits) > 0

        for split in splits:
            req = ForecastRequest(
                symbol=symbol,
                timeframe="1h",
                history=split.train,
                horizon_bars=len(split.test),
                quantiles=(0.10, 0.50, 0.90),
            )

            t0 = time.perf_counter()
            result = adapter.predict(req)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            all_latencies_ms.append(elapsed_ms)

            # Contract checks on benchmark outputs
            assert isinstance(result, ForecastResult)
            assert len(result.point_forecast) == len(split.test)
            assert result.request.symbol == symbol.upper()

    # Memory check while model is loaded
    rss_mb = get_process_rss_mb()

    adapter.unload()

    # Latency percentiles
    all_latencies_ms.sort()
    p50_latency = statistics.median(all_latencies_ms)
    p95_index = int(0.95 * len(all_latencies_ms))
    p95_latency = all_latencies_ms[p95_index]

    # Invariant assertions:
    # 1. P50 latency < 250ms and P95 latency < 500ms
    assert p50_latency < 250.0, f"P50 latency {p50_latency:.2f}ms exceeds 250ms target"
    assert p95_latency < 500.0, f"P95 latency {p95_latency:.2f}ms exceeds 500ms target"

    # 2. Process RSS < 1024 MB
    assert rss_mb < 1024.0, f"Process RSS {rss_mb:.2f} MB exceeds 1GB limit"
