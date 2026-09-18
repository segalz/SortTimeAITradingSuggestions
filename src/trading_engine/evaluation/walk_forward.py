"""Walk-forward chronological rolling-origin evaluation splitter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_engine.data.models import BarSeries


@dataclass(frozen=True)
class WalkForwardSplit:
    """Chronological out-of-sample partition representing a single evaluation point."""

    split_index: int
    cutoff: datetime
    train: BarSeries
    test: BarSeries

    def __post_init__(self) -> None:
        """Verify strict non-leakage invariant."""
        if len(self.train) == 0:
            raise ValueError("WalkForwardSplit train series cannot be empty.")
        if len(self.test) == 0:
            raise ValueError("WalkForwardSplit test series cannot be empty.")
        if self.train[-1].timestamp >= self.test[0].timestamp:
            raise ValueError(
                f"Data leakage detected! Train end timestamp ({self.train[-1].timestamp}) "
                f"must strictly precede test start timestamp ({self.test[0].timestamp})."
            )
        if self.cutoff != self.train[-1].timestamp:
            raise ValueError(
                f"Cutoff timestamp ({self.cutoff}) must match the last train bar timestamp ({self.train[-1].timestamp})."
            )


def generate_walk_forward_splits(
    series: BarSeries,
    train_bars: int,
    test_bars: int,
    step_bars: int = 1,
    expanding: bool = False,
) -> list[WalkForwardSplit]:
    """Generate chronological rolling-origin evaluation windows without time travel.

    Parameters
    ----------
    series:
        The input historical BarSeries.
    train_bars:
        Number of bars in the training / calibration window.
    test_bars:
        Number of bars in the out-of-sample test window.
    step_bars:
        Step size (stride) to advance the cutoff in bars.
    expanding:
        If True, training window expands from the initial origin; if False, sliding rolling window.
    """
    if train_bars <= 0:
        raise ValueError(f"train_bars must be positive, got {train_bars}")
    if test_bars <= 0:
        raise ValueError(f"test_bars must be positive, got {test_bars}")
    if step_bars <= 0:
        raise ValueError(f"step_bars must be positive, got {step_bars}")

    total_bars = len(series)
    window_required = train_bars + test_bars
    if total_bars < window_required:
        return []

    splits: list[WalkForwardSplit] = []
    split_index = 0
    start_idx = 0

    while True:
        train_start = 0 if expanding else start_idx
        train_end = start_idx + train_bars
        test_end = train_end + test_bars

        if test_end > total_bars:
            break

        train_bars_slice = series.bars[train_start:train_end]
        test_bars_slice = series.bars[train_end:test_end]

        train_series = BarSeries(symbol=series.symbol, timeframe=series.timeframe, bars=train_bars_slice)
        test_series = BarSeries(symbol=series.symbol, timeframe=series.timeframe, bars=test_bars_slice)

        split = WalkForwardSplit(
            split_index=split_index,
            cutoff=train_series[-1].timestamp,
            train=train_series,
            test=test_series,
        )
        splits.append(split)

        split_index += 1
        start_idx += step_bars

    return splits
