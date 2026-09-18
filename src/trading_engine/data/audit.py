"""Data adequacy and corporate action split/dividend anomaly audit utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from trading_engine.data.models import BarSeries


@dataclass(frozen=True)
class SplitAnomaly:
    """Represents a potential unadjusted split or dividend price discontinuity."""

    index: int
    timestamp: datetime
    prev_close: float
    curr_open: float
    price_change_ratio: float


@dataclass(frozen=True)
class DepthAuditResult:
    """Summary of data adequacy and contiguous depth check."""

    is_adequate: bool
    bar_count: int
    min_bars_required: int
    start: datetime | None
    end: datetime | None
    max_gap_seconds: float
    warnings: tuple[str, ...]


def detect_split_spikes(series: BarSeries, threshold_ratio: float = 0.30) -> list[SplitAnomaly]:
    """Detect abrupt overnight/adjacent price jumps indicative of unadjusted corporate actions.
    
    A standard 3-for-2 split cuts price by ~33.3%, a 2-for-1 forward split cuts price
    by 50%, while reverse splits increase price by multiples (>100%). A default threshold
    of 30% captures all standard splits (including 3-for-2) while avoiding ordinary
    daily volatility.
    """
    if len(series) < 2:
        return []

    anomalies: list[SplitAnomaly] = []
    for i in range(1, len(series)):
        prev_bar = series[i - 1]
        curr_bar = series[i]

        if prev_bar.close <= 0.0:
            continue

        ratio = abs(curr_bar.open - prev_bar.close) / prev_bar.close
        if ratio >= threshold_ratio:
            anomalies.append(
                SplitAnomaly(
                    index=i,
                    timestamp=curr_bar.timestamp,
                    prev_close=prev_bar.close,
                    curr_open=curr_bar.open,
                    price_change_ratio=round(ratio, 4),
                )
            )

    return anomalies


def check_contiguous_depth(
    series: BarSeries,
    min_bars: int = 100,
    max_allowed_gap_hours: float | None = None,
) -> DepthAuditResult:
    """Audit BarSeries for minimum required sample size and missing contiguous gaps.
    
    Parameters
    ----------
    series:
        The BarSeries to inspect.
    min_bars:
        Minimum number of bars required for statistical adequacy.
    max_allowed_gap_hours:
        Maximum permitted time gap between consecutive bars in hours.
    """
    bar_count = len(series)
    warnings: list[str] = []

    if bar_count == 0:
        return DepthAuditResult(
            is_adequate=False,
            bar_count=0,
            min_bars_required=min_bars,
            start=None,
            end=None,
            max_gap_seconds=0.0,
            warnings=("BarSeries is empty.",),
        )

    start = series[0].timestamp
    end = series[-1].timestamp
    max_gap_seconds = 0.0

    if bar_count < min_bars:
        warnings.append(
            f"Insufficient data depth: series has {bar_count} bars, minimum required is {min_bars}."
        )

    for i in range(1, bar_count):
        gap_sec = (series[i].timestamp - series[i - 1].timestamp).total_seconds()
        if gap_sec > max_gap_seconds:
            max_gap_seconds = gap_sec

        if max_allowed_gap_hours is not None:
            gap_hours = gap_sec / 3600.0
            if gap_hours >= max_allowed_gap_hours:
                warnings.append(
                    f"Gap of {gap_hours:.1f}h exceeds limit of {max_allowed_gap_hours}h "
                    f"at index {i} ({series[i].timestamp})."
                )

    is_adequate = len(warnings) == 0

    return DepthAuditResult(
        is_adequate=is_adequate,
        bar_count=bar_count,
        min_bars_required=min_bars,
        start=start,
        end=end,
        max_gap_seconds=max_gap_seconds,
        warnings=tuple(warnings),
    )
