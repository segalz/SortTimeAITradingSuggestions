"""Data package for the trading engine."""

from .audit import DepthAuditResult, SplitAnomaly, check_contiguous_depth, detect_split_spikes
from .benchmarks import BENCHMARK_SYMBOLS, get_benchmark_symbols
from .cache import CacheError, ParquetDataCache
from .models import BarSeries, Candle, DataContractError, DataQualityError, filter_completed_candles

__all__ = [
    "BENCHMARK_SYMBOLS",
    "BarSeries",
    "CacheError",
    "Candle",
    "DataContractError",
    "DataQualityError",
    "DepthAuditResult",
    "ParquetDataCache",
    "SplitAnomaly",
    "check_contiguous_depth",
    "detect_split_spikes",
    "filter_completed_candles",
    "get_benchmark_symbols",
]

