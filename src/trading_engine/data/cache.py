"""Local persistent Parquet cache for historical market data."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trading_engine.data.models import BarSeries


class CacheError(RuntimeError):
    """Raised when caching operations fail."""
    pass


def _ensure_utc_optional(dt: datetime | None, name: str) -> datetime | None:
    """Validate that optional datetime is timezone-aware and convert to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (UTC), got naive datetime.")
    return dt.astimezone(timezone.utc)


class ParquetDataCache:
    """Manages persistent Parquet caching for BarSeries data partitioned by symbol."""

    def __init__(self, base_dir: Path | str = "data/cache") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_file_path(self, symbol: str, timeframe: str) -> Path:
        """Return canonical Parquet path: base_dir / <SYMBOL> / <timeframe>.parquet."""
        clean_symbol = symbol.strip().upper()
        clean_tf = timeframe.strip().lower()
        return self.base_dir / clean_symbol / f"{clean_tf}.parquet"

    def save_bars(self, bar_series: BarSeries, merge: bool = True) -> Path:
        """Serialize a BarSeries to Parquet partitioned by symbol.
        
        If merge=True and existing cached data is present, merges with deduplication.
        """
        if len(bar_series) == 0:
            raise CacheError(f"Cannot cache empty BarSeries for {bar_series.symbol}")

        file_path = self.get_file_path(bar_series.symbol, bar_series.timeframe)
        new_df = bar_series.to_dataframe()

        if merge and file_path.exists():
            try:
                existing_df = pd.read_parquet(file_path, engine="pyarrow")
                if not existing_df.empty:
                    # Combine existing and new, keeping the newer entries for duplicate timestamps
                    combined = pd.concat([existing_df, new_df])
                    combined = combined[~combined.index.duplicated(keep="last")]
                    combined = combined.sort_index()
                    new_df = combined
            except Exception as exc:
                raise CacheError(f"Failed to merge existing cache at {file_path}: {exc}") from exc

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = file_path.with_suffix(".tmp")
            new_df.to_parquet(temp_file, engine="pyarrow", index=True)
            temp_file.replace(file_path)
            return file_path
        except Exception as exc:
            raise CacheError(f"Failed to write Parquet cache to {file_path}: {exc}") from exc

    def load_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> BarSeries | None:
        """Load BarSeries from Parquet cache. Returns None if cache miss or range empty."""
        start_utc = _ensure_utc_optional(start, "start")
        end_utc = _ensure_utc_optional(end, "end")

        clean_symbol = symbol.strip().upper()
        clean_tf = timeframe.strip().lower()

        file_path = self.get_file_path(clean_symbol, clean_tf)
        if not file_path.exists():
            return None

        try:
            df = pd.read_parquet(file_path, engine="pyarrow")
        except Exception as exc:
            raise CacheError(f"Failed to read Parquet cache from {file_path}: {exc}") from exc

        if df.empty:
            return None

        # Ensure index has timezone-aware UTC datetime
        if df.index.tz is None:
            df.index = df.index.tz_localize(timezone.utc)
        else:
            df.index = df.index.tz_convert(timezone.utc)

        if start_utc is not None:
            df = df[df.index >= start_utc]
        if end_utc is not None:
            df = df[df.index <= end_utc]

        if df.empty:
            return None

        return BarSeries.from_dataframe(symbol=clean_symbol, timeframe=clean_tf, df=df)
