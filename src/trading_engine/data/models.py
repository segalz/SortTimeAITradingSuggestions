"""Core data models for the trading engine."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator, Union

import pandas as pd


class DataContractError(ValueError):
    """Raised when data violates the data contract."""


class DataQualityError(DataContractError):
    """Raised when data fails quality checks (e.g. ordering)."""


def _require_utc(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise DataContractError("Timestamp must be UTC")
    if timestamp.utcoffset().total_seconds() != 0:
        raise DataContractError("Timestamp must be UTC")


@dataclass(frozen=True)
class Candle:
    """A single OHLCV bar with an optional VWAP and traded amount."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    amount: float | None = None

    def __post_init__(self) -> None:
        _require_utc(self.timestamp)

        for name in ("open", "high", "low", "close"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise DataContractError(f"{name} must be a finite number > 0")

        volume = float(self.volume)
        if not math.isfinite(volume) or volume < 0:
            raise DataContractError("volume must be a finite number >= 0")

        if self.high < self.low:
            raise DataContractError("high must be >= low")
        if not (self.high >= self.open >= self.low):
            raise DataContractError("open must be within [low, high]")
        if not (self.high >= self.close >= self.low):
            raise DataContractError("close must be within [low, high]")

        for name in ("vwap", "amount"):
            value = getattr(self, name)
            if value is not None:
                numeric = float(value)
                if not math.isfinite(numeric) or numeric <= 0:
                    raise DataContractError(f"{name} must be a finite number > 0 when provided")


@dataclass(frozen=True)
class BarSeries:
    """An ordered, validated series of candles for one symbol/timeframe."""

    symbol: str
    timeframe: str
    bars: tuple[Candle, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).upper())
        object.__setattr__(self, "bars", tuple(self.bars))

        bars = self.bars
        for i in range(1, len(bars)):
            if bars[i].timestamp <= bars[i - 1].timestamp:
                raise DataQualityError("Non-monotonic timestamp")

    def __len__(self) -> int:
        return len(self.bars)

    def __getitem__(self, index: Union[int, slice]) -> Union[Candle, tuple[Candle, ...]]:
        return self.bars[index]

    def __iter__(self) -> Iterator[Candle]:
        return iter(self.bars)

    def start_time(self) -> datetime | None:
        return self.bars[0].timestamp if self.bars else None

    def end_time(self) -> datetime | None:
        return self.bars[-1].timestamp if self.bars else None

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to a pandas DataFrame indexed by a UTC DatetimeIndex."""
        records = []
        for bar in self.bars:
            records.append(
                {
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "vwap": bar.vwap,
                    "amount": bar.amount,
                }
            )
        df = pd.DataFrame(
            records,
            columns=["timestamp", "open", "high", "low", "close", "volume", "vwap", "amount"],
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        for col in ("vwap", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp")
            df.index = pd.DatetimeIndex(df.index, tz="UTC", name="timestamp")
        else:
            df = df.set_index("timestamp")
            df.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
        return df

    @classmethod
    def from_dataframe(cls, symbol: str, timeframe: str, df: pd.DataFrame) -> "BarSeries":
        """Build a BarSeries from a pandas DataFrame.

        The DataFrame must contain OHLCV columns and either a UTC DatetimeIndex
        or a ``timestamp`` column with UTC-aware datetimes.
        """
        if df is None or len(df) == 0:
            return cls(symbol=symbol, timeframe=timeframe, bars=())

        work = df.copy()

        if "timestamp" in work.columns:
            raw_ts = work["timestamp"]
        else:
            raw_ts = work.index

        if not isinstance(raw_ts, pd.DatetimeIndex):
            try:
                dt_index = pd.DatetimeIndex(raw_ts)
            except Exception as e:
                raise DataContractError(f"Cannot parse timestamps: {e}") from e
        else:
            dt_index = raw_ts

        if dt_index.tz is None:
            raise DataContractError(
                "Timestamps in DataFrame must be timezone-aware UTC, got naive timestamps."
            )

        if len(dt_index) > 0 and dt_index[0].utcoffset().total_seconds() != 0:
            raise DataContractError(
                f"Timestamps in DataFrame must be UTC, got non-UTC timezone {dt_index.tz}."
            )

        work.index = dt_index

        required = ("open", "high", "low", "close", "volume")
        missing = [c for c in required if c not in work.columns]
        if missing:
            raise DataContractError(f"Missing required columns: {missing}")

        bars: list[Candle] = []
        for ts, row in work.iterrows():
            bars.append(
                Candle(
                    timestamp=ts.to_pydatetime(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    vwap=float(row["vwap"]) if "vwap" in row and pd.notna(row.get("vwap")) else None,
                    amount=float(row["amount"]) if "amount" in row and pd.notna(row.get("amount")) else None,
                )
            )

        return cls(symbol=symbol, timeframe=timeframe, bars=tuple(bars))


TIMEFRAME_DELTAS: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}


def filter_completed_candles(series: BarSeries, current_time: datetime) -> BarSeries:
    """Filter out any candle that has not fully completed at `current_time`.

    A candle with start timestamp `t` and timeframe duration `delta` is only
    considered closed and completed once `current_time >= t + delta`.
    """
    if current_time.tzinfo is None:
        raise ValueError("current_time must be timezone-aware (UTC).")
    current_utc = current_time.astimezone(timezone.utc)

    delta = TIMEFRAME_DELTAS.get(series.timeframe.lower())
    if delta is None:
        raise ValueError(f"Unknown timeframe duration for {series.timeframe!r}")

    completed_bars = tuple(
        bar for bar in series.bars if bar.timestamp + delta <= current_utc
    )
    return BarSeries(symbol=series.symbol, timeframe=series.timeframe, bars=completed_bars)

