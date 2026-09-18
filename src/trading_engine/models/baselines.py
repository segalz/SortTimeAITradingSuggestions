"""Baseline forecasting models for benchmarking time-series predictors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from trading_engine.data.models import BarSeries


@dataclass(frozen=True)
class Forecast:
    """Out-of-sample forecast container."""

    symbol: str
    timeframe: str
    horizon_bars: int
    point_forecasts: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.horizon_bars <= 0:
            raise ValueError(f"horizon_bars must be positive, got {self.horizon_bars}")
        if len(self.point_forecasts) != self.horizon_bars:
            raise ValueError(
                f"Expected {self.horizon_bars} point forecasts, got {len(self.point_forecasts)}"
            )


class BaselineModel(ABC):
    """Abstract base class for quantitative baseline models."""

    @abstractmethod
    def predict(self, history: BarSeries, horizon_bars: int) -> Forecast:
        """Generate forecasts for the next horizon_bars without using future information."""
        ...


class LastValueBaseline(BaselineModel):
    """Naive persistence baseline projecting the last observed close price."""

    def predict(self, history: BarSeries, horizon_bars: int) -> Forecast:
        if len(history) == 0:
            raise ValueError("Cannot forecast with empty history.")
        if horizon_bars <= 0:
            raise ValueError(f"horizon_bars must be positive, got {horizon_bars}")

        last_price = history[-1].close
        predictions = tuple(last_price for _ in range(horizon_bars))

        return Forecast(
            symbol=history.symbol,
            timeframe=history.timeframe,
            horizon_bars=horizon_bars,
            point_forecasts=predictions,
        )


class DriftBaseline(BaselineModel):
    """Linear drift baseline extrapolating historical return trend."""

    def predict(self, history: BarSeries, horizon_bars: int) -> Forecast:
        if len(history) == 0:
            raise ValueError("Cannot forecast with empty history.")
        if horizon_bars <= 0:
            raise ValueError(f"horizon_bars must be positive, got {horizon_bars}")

        last_price = history[-1].close
        if len(history) == 1:
            drift = 0.0
        else:
            first_price = history[0].close
            drift = (last_price - first_price) / (len(history) - 1)

        # Enforce positive price invariant by clamping to minimum price floor of 0.01
        predictions = tuple(
            max(0.01, last_price + (step + 1) * drift) for step in range(horizon_bars)
        )

        return Forecast(
            symbol=history.symbol,
            timeframe=history.timeframe,
            horizon_bars=horizon_bars,
            point_forecasts=predictions,
        )


class MovingAverageBaseline(BaselineModel):
    """Moving average baseline projecting the rolling mean close price."""

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"Moving average window must be positive, got {window}")
        self.window = window

    def predict(self, history: BarSeries, horizon_bars: int) -> Forecast:
        if len(history) == 0:
            raise ValueError("Cannot forecast with empty history.")
        if horizon_bars <= 0:
            raise ValueError(f"horizon_bars must be positive, got {horizon_bars}")

        effective_window = min(self.window, len(history))
        recent_bars = history[-effective_window:]
        mean_price = sum(bar.close for bar in recent_bars) / effective_window
        predictions = tuple(mean_price for _ in range(horizon_bars))

        return Forecast(
            symbol=history.symbol,
            timeframe=history.timeframe,
            horizon_bars=horizon_bars,
            point_forecasts=predictions,
        )
