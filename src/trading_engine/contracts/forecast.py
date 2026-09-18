"""Forecast request and result data contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from trading_engine.data.models import BarSeries, DataContractError, _require_utc


def _freeze_dict(d: Mapping[Any, Any] | None) -> MappingProxyType[Any, Any]:
    if d is None:
        return MappingProxyType({})
    if not isinstance(d, (dict, MappingProxyType)):
        raise DataContractError(f"Expected mapping, got {type(d).__name__}")
    return MappingProxyType(dict(d))


@dataclass(frozen=True)
class ForecastRequest:
    """Request contract for model inference.

    Specifies target symbol, timeframe, historical bars, forecast horizon,
    and required quantile targets.
    """

    symbol: str
    timeframe: str
    history: BarSeries
    horizon_bars: int
    quantiles: tuple[float, ...] = (0.10, 0.50, 0.90)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol or not isinstance(self.symbol, str):
            raise DataContractError("symbol must be a non-empty string")
        norm_symbol = self.symbol.upper()
        object.__setattr__(self, "symbol", norm_symbol)

        if not self.timeframe or not isinstance(self.timeframe, str):
            raise DataContractError("timeframe must be a non-empty string")
        if not isinstance(self.history, BarSeries) or len(self.history) == 0:
            raise DataContractError("history must be a non-empty BarSeries")

        if self.history.symbol.upper() != norm_symbol:
            raise DataContractError(
                f"symbol '{norm_symbol}' does not match history symbol '{self.history.symbol}'"
            )
        if self.history.timeframe != self.timeframe:
            raise DataContractError(
                f"timeframe '{self.timeframe}' does not match history timeframe '{self.history.timeframe}'"
            )

        if isinstance(self.horizon_bars, bool) or not isinstance(self.horizon_bars, int) or self.horizon_bars <= 0:
            raise DataContractError("horizon_bars must be an integer >= 1 (bool rejected)")

        try:
            quantiles_tuple = tuple(self.quantiles)
        except TypeError as exc:
            raise DataContractError("quantiles must be an iterable of numbers") from exc

        if not quantiles_tuple:
            raise DataContractError("quantiles must not be empty")

        prev_q = -1.0
        for q in quantiles_tuple:
            if isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q):
                raise DataContractError("All quantiles must be finite numbers (bool rejected)")
            q_float = float(q)
            if not (0.0 < q_float < 1.0):
                raise DataContractError(f"Quantile {q} must be strictly in (0.0, 1.0)")
            if q_float <= prev_q:
                raise DataContractError("quantiles must be strictly increasing")
            prev_q = q_float

        object.__setattr__(self, "quantiles", quantiles_tuple)
        object.__setattr__(self, "metadata", _freeze_dict(self.metadata))


@dataclass(frozen=True)
class ForecastResult:
    """Result contract produced by a model inference adapter.

    Encapsulates point forecasts, quantile forecasts, directional probabilities,
    timestamps, and model metadata with strict validity and monotonicity guarantees.
    """

    request: ForecastRequest
    timestamps: tuple[datetime, ...]
    point_forecast: tuple[float, ...]
    quantile_forecasts: Mapping[float, tuple[float, ...]]
    model_id: str
    created_at: datetime
    probabilities: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_utc(self.created_at)

        if not isinstance(self.request, ForecastRequest):
            raise DataContractError("request must be a ForecastRequest instance")

        if not self.model_id or not isinstance(self.model_id, str):
            raise DataContractError("model_id must be a non-empty string")

        h = self.request.horizon_bars

        try:
            ts_tuple = tuple(self.timestamps)
        except TypeError as exc:
            raise DataContractError("timestamps must be an iterable") from exc

        if len(ts_tuple) != h:
            raise DataContractError(
                f"timestamps length ({len(ts_tuple)}) must equal horizon_bars ({h})"
            )

        cutoff_time = self.request.history[-1].timestamp
        prev_ts = cutoff_time
        for ts in ts_tuple:
            if not isinstance(ts, datetime):
                raise DataContractError("All timestamps must be datetime instances")
            _require_utc(ts)
            if ts <= prev_ts:
                raise DataContractError("Forecast timestamps must be strictly monotonic after cutoff")
            prev_ts = ts
        object.__setattr__(self, "timestamps", ts_tuple)

        try:
            pf_tuple = tuple(self.point_forecast)
        except TypeError as exc:
            raise DataContractError("point_forecast must be an iterable") from exc

        if len(pf_tuple) != h:
            raise DataContractError(
                f"point_forecast length ({len(pf_tuple)}) must equal horizon_bars ({h})"
            )

        for val in pf_tuple:
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
                raise DataContractError("All point forecast values must be finite positive numbers (bool rejected)")
        object.__setattr__(self, "point_forecast", tuple(float(v) for v in pf_tuple))

        if not isinstance(self.quantile_forecasts, (dict, MappingProxyType)):
            raise DataContractError("quantile_forecasts must be a mapping")

        req_quantiles = set(self.request.quantiles)
        res_quantiles = set(self.quantile_forecasts.keys())
        if req_quantiles != res_quantiles:
            raise DataContractError(
                f"quantile_forecasts keys {res_quantiles} must match request quantiles {req_quantiles}"
            )

        frozen_quantiles: dict[float, tuple[float, ...]] = {}
        for q, series in self.quantile_forecasts.items():
            try:
                s_tuple = tuple(series)
            except TypeError as exc:
                raise DataContractError(f"Quantile forecast series for {q} must be an iterable") from exc

            if len(s_tuple) != h:
                raise DataContractError(
                    f"quantile_forecasts[{q}] length ({len(s_tuple)}) must equal horizon_bars ({h})"
                )
            for val in s_tuple:
                if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
                    raise DataContractError(
                        f"Quantile forecast values for {q} must be finite positive numbers (bool rejected)"
                    )
            frozen_quantiles[float(q)] = tuple(float(v) for v in s_tuple)

        # Monotonicity check
        sorted_qs = sorted(self.request.quantiles)
        for step in range(h):
            for i in range(len(sorted_qs) - 1):
                q_low = sorted_qs[i]
                q_high = sorted_qs[i + 1]
                val_low = frozen_quantiles[q_low][step]
                val_high = frozen_quantiles[q_high][step]
                if val_low > val_high:
                    raise DataContractError(
                        f"Quantile monotonicity violated at step {step}: "
                        f"P{q_low*100:g} ({val_low}) > P{q_high*100:g} ({val_high})"
                    )
        object.__setattr__(self, "quantile_forecasts", MappingProxyType(frozen_quantiles))

        # Probabilities validation and freezing
        if not isinstance(self.probabilities, (dict, MappingProxyType)):
            raise DataContractError("probabilities must be a mapping")
        frozen_probs: dict[str, float] = {}
        for label, p in self.probabilities.items():
            if not isinstance(label, str):
                raise DataContractError("Probability key must be a string")
            if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p):
                raise DataContractError(f"Probability for {label} must be a finite number (bool rejected)")
            p_float = float(p)
            if not (0.0 <= p_float <= 1.0):
                raise DataContractError(f"Probability for {label} ({p_float}) must be in [0.0, 1.0]")
            frozen_probs[label] = p_float
        object.__setattr__(self, "probabilities", MappingProxyType(frozen_probs))

        object.__setattr__(self, "metadata", _freeze_dict(self.metadata))
