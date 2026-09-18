"""Point-in-time corporate action adjustments preventing retroactive lookahead leakage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from trading_engine.data.models import BarSeries, Candle


@dataclass(frozen=True)
class SplitAction:
    """A corporate split action."""

    symbol: str
    effective_date: datetime
    split_ratio: float  # e.g. 2.0 for 2-for-1 split (new / old)

    def __post_init__(self) -> None:
        if self.split_ratio <= 0:
            raise ValueError(f"split_ratio must be positive, got {self.split_ratio}")
        if self.effective_date.tzinfo is None:
            raise ValueError("effective_date must be timezone-aware (UTC)")


def apply_point_in_time_splits(
    series: BarSeries,
    splits: Sequence[SplitAction],
    as_of_time: datetime,
) -> BarSeries:
    """Adjust historical bars strictly using splits effective on or before as_of_time.

    Any split effective after as_of_time is excluded, preventing retroactive lookahead leakage.
    """
    if as_of_time.tzinfo is None:
        raise ValueError("as_of_time must be timezone-aware (UTC).")
    as_of_utc = as_of_time.astimezone(timezone.utc)

    valid_splits = [
        s for s in splits
        if s.symbol.upper() == series.symbol.upper() and s.effective_date <= as_of_utc
    ]

    adjusted_candles: list[Candle] = []
    for bar in series.bars:
        factor = 1.0
        for s in valid_splits:
            if bar.timestamp < s.effective_date:
                factor *= s.split_ratio

        adjusted_candles.append(
            Candle(
                timestamp=bar.timestamp,
                open=bar.open / factor,
                high=bar.high / factor,
                low=bar.low / factor,
                close=bar.close / factor,
                volume=bar.volume * factor,
            )
        )

    return BarSeries(symbol=series.symbol, timeframe=series.timeframe, bars=tuple(adjusted_candles))
