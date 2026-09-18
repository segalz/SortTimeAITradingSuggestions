"""Kronos-mini financial forecasting model adapter for lightweight CPU inference."""

from __future__ import annotations

import gc
from typing import Sequence

from trading_engine.contracts.adapter import (
    ModelAdapter,
    ModelAdapterCapabilities,
    infer_timeframe_delta,
)
from trading_engine.contracts.device import clamp_cpu_threads, cpu_thread_limit
from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.models.device_guard import assert_cpu_only, enforce_cpu_environment
from trading_engine.models.vendored.kronos import (
    KronosMiniConfig,
    KronosMiniModel,
    KronosTokenizer,
)


class KronosMiniAdapter(ModelAdapter):
    """Model adapter for NeoQuasar/Kronos-mini (approx 4.1M params) on CPU."""

    def __init__(
        self,
        model_id: str = "kronos-mini",
        max_horizon_bars: int = 48,
        sample_count: int = 20,
        temperature: float = 0.8,
        num_threads: int = 2,
    ) -> None:
        self._model_id = model_id
        self._max_horizon_bars = max_horizon_bars
        self._sample_count = max(1, sample_count)
        self._temperature = temperature
        self._num_threads = num_threads

        self._tokenizer: KronosTokenizer | None = None
        self._model: KronosMiniModel | None = None
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
        """Initialize Kronos-mini model weights and financial tokenizer onto CPU."""
        assert_cpu_only("cpu")
        enforce_cpu_environment()
        clamp_cpu_threads(self._num_threads)

        self._tokenizer = KronosTokenizer(vocab_size=1024, max_return=0.15)
        self._model = KronosMiniModel(KronosMiniConfig(vocab_size=1024))
        self._is_loaded = True

    def unload(self) -> None:
        """Release Kronos-mini model from memory."""
        self._tokenizer = None
        self._model = None
        self._is_loaded = False
        gc.collect()

    def predict(self, request: ForecastRequest) -> ForecastResult:
        """Run CPU inference generating quantile price trajectories from token paths."""
        if not self._is_loaded or self._tokenizer is None or self._model is None:
            raise RuntimeError(f"Model {self._model_id} is not loaded. Call load() first.")

        assert_cpu_only("cpu")

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

        with cpu_thread_limit(self._num_threads):
            prices = [bar.close for bar in request.history]
            last_price = prices[-1]
            tokens = self._tokenizer.prices_to_tokens(prices)

            # Generate sample_count future paths
            generated_paths = self._model.generate(
                input_ids=tokens,
                max_new_tokens=request.horizon_bars,
                sample_count=self._sample_count,
                temperature=self._temperature,
            )

            # Convert generated token paths to price series
            price_trajectories: list[list[float]] = []
            for path in generated_paths:
                path_prices = self._tokenizer.tokens_to_prices(base_price=last_price, tokens=path)
                # Ensure length matches horizon
                while len(path_prices) < request.horizon_bars:
                    path_prices.append(path_prices[-1] if path_prices else last_price)
                price_trajectories.append(path_prices[: request.horizon_bars])

            # Compute empirical quantiles per step across trajectories
            quantile_forecasts: dict[float, tuple[float, ...]] = {}
            for q in request.quantiles:
                q_series = []
                for step in range(request.horizon_bars):
                    step_prices = sorted(price_trajectories[i][step] for i in range(len(price_trajectories)))
                    idx = int(q * (len(step_prices) - 1))
                    q_series.append(max(0.01, step_prices[idx]))
                quantile_forecasts[float(q)] = tuple(q_series)

            # Enforce quantile monotonicity
            sorted_qs = sorted(request.quantiles)
            for step in range(request.horizon_bars):
                for i in range(len(sorted_qs) - 1):
                    q1, q2 = sorted_qs[i], sorted_qs[i + 1]
                    if quantile_forecasts[q1][step] > quantile_forecasts[q2][step]:
                        repaired = list(quantile_forecasts[q2])
                        repaired[step] = max(repaired[step], quantile_forecasts[q1][step])
                        quantile_forecasts[q2] = tuple(repaired)

            # Point forecast is median (0.50 quantile)
            if 0.50 in quantile_forecasts:
                point_forecast = quantile_forecasts[0.50]
            else:
                mid_q = sorted_qs[len(sorted_qs) // 2]
                point_forecast = quantile_forecasts[mid_q]

            # Future timestamps
            step_delta = infer_timeframe_delta(request.timeframe)
            cutoff = request.history[-1].timestamp
            future_ts = tuple(cutoff + (i + 1) * step_delta for i in range(request.horizon_bars))

            # Directional probabilities
            final_price = point_forecast[-1]
            if final_price > last_price:
                p_up, p_down = 0.65, 0.35
            elif final_price < last_price:
                p_up, p_down = 0.35, 0.65
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
