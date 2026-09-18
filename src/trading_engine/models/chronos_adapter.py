"""Chronos-Bolt-Tiny forecasting model adapter for lightweight CPU inference."""

from __future__ import annotations

import gc
from typing import Any, Sequence

from trading_engine.contracts.adapter import (
    ModelAdapter,
    ModelAdapterCapabilities,
    infer_timeframe_delta,
)
from trading_engine.contracts.device import clamp_cpu_threads
from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.models.device_guard import assert_cpu_only, enforce_cpu_environment


class ChronosBoltTinyAdapter(ModelAdapter):
    """Model adapter for Amazon Chronos-Bolt-Tiny (9M params) on CPU."""

    def __init__(
        self,
        model_id: str = "chronos-bolt-tiny",
        pretrained_model_name: str = "amazon/chronos-bolt-tiny",
        max_horizon_bars: int = 64,
        num_threads: int = 2,
        pipeline_factory: Any | None = None,
    ) -> None:
        self._model_id = model_id
        self._pretrained_model_name = pretrained_model_name
        self._max_horizon_bars = max_horizon_bars
        self._num_threads = num_threads
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any | None = None
        self._is_loaded = False

        self._capabilities = ModelAdapterCapabilities(
            model_id=model_id,
            supports_quantiles=True,
            supported_timeframes=("1m", "5m", "15m", "1h", "1d"),
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

    def capabilities(self) -> ModelAdapterCapabilities:
        return self._capabilities

    def load(self) -> None:
        """Load Chronos-Bolt-Tiny model weights onto CPU with thread clamps."""
        assert_cpu_only("cpu")
        enforce_cpu_environment()
        clamp_cpu_threads(self._num_threads)

        if self._pipeline_factory is not None:
            self._pipeline = self._pipeline_factory(self._pretrained_model_name)
            self._is_loaded = True
            return

        try:
            import torch  # type: ignore
            from chronos import ChronosBoltPipeline  # type: ignore

            self._pipeline = ChronosBoltPipeline.from_pretrained(
                self._pretrained_model_name,
                device_map="cpu",
                torch_dtype=torch.float32,
            )
            self._is_loaded = True
        except (ImportError, AttributeError) as exc:
            raise ImportError(
                f"Cannot load {self._model_id}: required ML dependencies (torch, chronos) "
                f"are not installed: {exc}"
            ) from exc

    def unload(self) -> None:
        """Unload pipeline from memory and reclaim CPU RAM."""
        self._pipeline = None
        self._is_loaded = False
        gc.collect()

    def predict(self, request: ForecastRequest) -> ForecastResult:
        """Run CPU inference on historical price series."""
        if not self._is_loaded or self._pipeline is None:
            raise RuntimeError(f"Model {self._model_id} is not loaded. Call load() first.")

        norm_tf = request.timeframe.lower().strip()
        if norm_tf not in self._capabilities.supported_timeframes:
            raise ValueError(
                f"Timeframe '{request.timeframe}' is not supported by {self._model_id}. "
                f"Supported: {self._capabilities.supported_timeframes}"
            )

        if request.horizon_bars > self._capabilities.max_horizon_bars:
            raise ValueError(
                f"Requested horizon {request.horizon_bars} exceeds maximum "
                f"{self._capabilities.max_horizon_bars}"
            )

        context_prices = [bar.close for bar in request.history]
        prediction_length = request.horizon_bars
        q_levels = list(request.quantiles)

        quantile_forecasts: dict[float, tuple[float, ...]] = {}
        point_forecast: tuple[float, ...]

        # Case 1: Real Chronos-Bolt API using predict_quantiles
        if hasattr(self._pipeline, "predict_quantiles"):
            try:
                import torch  # type: ignore

                context_tensor = torch.tensor(context_prices, dtype=torch.float32)
            except ImportError:
                context_tensor = context_prices

            q_out, mean_out = self._pipeline.predict_quantiles(
                context_tensor,
                prediction_length=prediction_length,
                quantile_levels=q_levels,
            )

            # Squeeze batch dimension if present
            if hasattr(q_out, "dim") and q_out.dim() == 3:
                q_out = q_out.squeeze(0)
            if hasattr(mean_out, "dim") and mean_out.dim() == 2:
                mean_out = mean_out.squeeze(0)

            for idx, q in enumerate(request.quantiles):
                q_col = q_out[:, idx]
                q_vals = tuple(max(0.01, float(v)) for v in q_col.tolist())
                quantile_forecasts[float(q)] = q_vals

            # Use median (0.50) if present, else mean
            if 0.50 in quantile_forecasts:
                point_forecast = quantile_forecasts[0.50]
            else:
                point_forecast = tuple(max(0.01, float(v)) for v in mean_out.tolist())

        # Case 2: Mock pipeline or alternative callable
        elif hasattr(self._pipeline, "predict"):
            forecast_output = self._pipeline.predict(
                context_prices=context_prices,
                prediction_length=prediction_length,
                quantiles=request.quantiles,
            )

            if not isinstance(forecast_output, dict):
                raise RuntimeError(f"Unexpected mock output format: {type(forecast_output)}")

            for q in request.quantiles:
                q_float = float(q)
                if q_float in forecast_output:
                    q_series = tuple(max(0.01, float(v)) for v in forecast_output[q_float])
                elif str(q_float) in forecast_output:
                    q_series = tuple(max(0.01, float(v)) for v in forecast_output[str(q_float)])
                else:
                    raise RuntimeError(f"Missing quantile {q_float} in pipeline output")
                quantile_forecasts[q_float] = q_series

            if 0.50 in quantile_forecasts:
                point_forecast = quantile_forecasts[0.50]
            else:
                sorted_qs = sorted(request.quantiles)
                point_forecast = quantile_forecasts[sorted_qs[len(sorted_qs) // 2]]
        else:
            raise RuntimeError(f"Pipeline {type(self._pipeline)} does not expose predict_quantiles or predict")

        # Invariant check: quantile monotonicity enforcement
        sorted_qs = sorted(request.quantiles)
        for step in range(prediction_length):
            for i in range(len(sorted_qs) - 1):
                q1, q2 = sorted_qs[i], sorted_qs[i + 1]
                if quantile_forecasts[q1][step] > quantile_forecasts[q2][step]:
                    # Monotonic adjustment: clamp lower to not exceed higher
                    repaired = list(quantile_forecasts[q2])
                    repaired[step] = max(repaired[step], quantile_forecasts[q1][step])
                    quantile_forecasts[q2] = tuple(repaired)

        # Timestamps
        step_delta = infer_timeframe_delta(request.timeframe)
        cutoff = request.history[-1].timestamp
        future_ts = tuple(cutoff + (i + 1) * step_delta for i in range(prediction_length))

        # Directional probabilities
        last_close = request.history[-1].close
        final_price = point_forecast[-1]
        if final_price > last_close:
            p_up, p_down = 0.62, 0.38
        elif final_price < last_close:
            p_up, p_down = 0.38, 0.62
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
