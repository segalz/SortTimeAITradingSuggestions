"""Model adapter abstract interface and baseline adapter wrapper."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.data.models import BarSeries, Candle, DataContractError
from trading_engine.models.baselines import BaselineModel


@dataclass(frozen=True)
class ModelAdapterCapabilities:
    """Declared capabilities and execution constraints of a model adapter."""

    model_id: str
    supports_quantiles: bool
    supported_timeframes: tuple[str, ...]
    max_horizon_bars: int
    requires_features: bool = False
    device: str = "cpu"

    def __post_init__(self) -> None:
        if not self.model_id or not isinstance(self.model_id, str):
            raise DataContractError("model_id must be a non-empty string")
        if not self.supported_timeframes:
            raise DataContractError("supported_timeframes must not be empty")
        if self.max_horizon_bars <= 0:
            raise DataContractError("max_horizon_bars must be positive")
        object.__setattr__(self, "supported_timeframes", tuple(self.supported_timeframes))


class ModelAdapter(ABC):
    """Abstract lifecycle interface for all forecasting models."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Unique model identifier."""
        ...

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Check if model weights and resources are loaded into memory."""
        ...

    @abstractmethod
    def load(self) -> None:
        """Load weights, tokenizers, or dependencies into memory."""
        ...

    @abstractmethod
    def predict(self, request: ForecastRequest) -> ForecastResult:
        """Run inference on the provided historical series and produce a ForecastResult."""
        ...

    @abstractmethod
    def unload(self) -> None:
        """Unload model from memory and release resources."""
        ...

    @abstractmethod
    def capabilities(self) -> ModelAdapterCapabilities:
        """Return capabilities and execution limits."""
        ...


def infer_timeframe_delta(timeframe: str) -> timedelta:
    """Map common timeframe strings to standard timedeltas."""
    tf = timeframe.lower().strip()
    if tf.endswith("m") and tf[:-1].isdigit():
        return timedelta(minutes=int(tf[:-1]))
    if tf.endswith("h") and tf[:-1].isdigit():
        return timedelta(hours=int(tf[:-1]))
    if tf.endswith("d") and tf[:-1].isdigit():
        return timedelta(days=int(tf[:-1]))
    if tf.endswith("w") and tf[:-1].isdigit():
        return timedelta(weeks=int(tf[:-1]))
    raise ValueError(f"Unrecognized timeframe format: {timeframe}")


class BaselineAdapter(ModelAdapter):
    """Adapter wrapping any BaselineModel into the standard ModelAdapter contract."""

    def __init__(
        self,
        model_id: str,
        baseline: BaselineModel,
        supported_timeframes: Sequence[str] = ("1m", "5m", "15m", "1h", "1d"),
        max_horizon_bars: int = 100,
    ) -> None:
        self._model_id = model_id
        self._baseline = baseline
        self._is_loaded = False
        self._capabilities = ModelAdapterCapabilities(
            model_id=model_id,
            supports_quantiles=True,
            supported_timeframes=tuple(supported_timeframes),
            max_horizon_bars=max_horizon_bars,
            requires_features=False,
            device="cpu",
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def load(self) -> None:
        self._is_loaded = True

    def unload(self) -> None:
        self._is_loaded = False

    def capabilities(self) -> ModelAdapterCapabilities:
        return self._capabilities

    def predict(self, request: ForecastRequest) -> ForecastResult:
        if not self._is_loaded:
            raise RuntimeError(f"Model {self._model_id} is not loaded. Call load() first.")

        if request.timeframe not in self._capabilities.supported_timeframes:
            raise ValueError(
                f"Timeframe '{request.timeframe}' is not supported by {self._model_id}. "
                f"Supported: {self._capabilities.supported_timeframes}"
            )

        if request.horizon_bars > self._capabilities.max_horizon_bars:
            raise ValueError(
                f"Requested horizon {request.horizon_bars} exceeds maximum "
                f"{self._capabilities.max_horizon_bars}"
            )

        step_delta = infer_timeframe_delta(request.timeframe)
        cutoff = request.history[-1].timestamp
        future_ts = tuple(cutoff + (i + 1) * step_delta for i in range(request.horizon_bars))

        # Generate point forecasts using wrapped baseline
        forecast = self._baseline.predict(request.history, request.horizon_bars)
        point_forecast = tuple(float(p) for p in forecast.point_forecasts)

        # Baseline quantile generation: deterministic baseline centers quantiles
        # with small pseudo-spread proportional to (q - 0.5) to maintain monotonicity
        quantile_forecasts: dict[float, tuple[float, ...]] = {}
        for q in request.quantiles:
            # Spread offset factor: e.g. for q=0.5 -> 0, for q=0.1 -> -0.01, for q=0.9 -> +0.01
            offset_factor = (float(q) - 0.5) * 0.02
            quantile_series = tuple(
                max(0.01, round(p * (1.0 + offset_factor), 6)) for p in point_forecast
            )
            quantile_forecasts[float(q)] = quantile_series

        # Determine directional probabilities
        last_close = request.history[-1].close
        final_price = point_forecast[-1]
        if final_price > last_close:
            p_up, p_down = 0.60, 0.40
        elif final_price < last_close:
            p_up, p_down = 0.40, 0.60
        else:
            p_up, p_down = 0.50, 0.50

        return ForecastResult(
            request=request,
            timestamps=future_ts,
            point_forecast=point_forecast,
            quantile_forecasts=quantile_forecasts,
            model_id=self._model_id,
            created_at=cutoff,
            probabilities={"up": p_up, "down": p_down},
        )
