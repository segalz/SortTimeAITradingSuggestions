"""Benchmark symbol definitions and utilities for market data validation."""

from __future__ import annotations

# Five highly liquid benchmark assets spanning broad market, tech, and individual leaders
BENCHMARK_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")


def get_benchmark_symbols() -> tuple[str, ...]:
    """Return the tuple of standard benchmark symbols."""
    return BENCHMARK_SYMBOLS
