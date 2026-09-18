"""Data package for the trading engine."""

from .audit import DepthAuditResult, SplitAnomaly, check_contiguous_depth, detect_split_spikes
from .benchmarks import BENCHMARK_SYMBOLS, get_benchmark_symbols
from .cache import CacheError, ParquetDataCache
from .models import BarSeries, Candle, DataContractError, DataQualityError

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
    "get_benchmark_symbols",
]

