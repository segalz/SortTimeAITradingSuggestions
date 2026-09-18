"""Smoke tests, cold-load timer, and lifecycle tests for ChronosBoltTinyAdapter."""

from datetime import datetime, timedelta, timezone
import sys
import time
from typing import Any
import pytest

from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.data.models import BarSeries, Candle
from trading_engine.models.chronos_adapter import ChronosBoltTinyAdapter


def _make_series(n: int = 15, symbol: str = "SPY", timeframe: str = "1h") -> BarSeries:
    base = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.0 + i,
            volume=1000.0,
        )
        for i in range(n)
    ]
    return BarSeries(symbol=symbol, timeframe=timeframe, bars=tuple(candles))


class MockChronosPipeline:
    """Mock pipeline simulating Chronos-Bolt-Tiny quantile predictions."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def predict(
        self,
        context_prices: list[float],
        prediction_length: int,
        quantiles: tuple[float, ...],
    ) -> dict[float, list[float]]:
        last_price = context_prices[-1]
        results: dict[float, list[float]] = {}
        for q in quantiles:
            spread = (float(q) - 0.5) * 0.04
            series = [round(last_price * (1.0 + spread) + i * 0.1, 4) for i in range(prediction_length)]
            results[float(q)] = series
        return results


class MockTensor:
    """Minimal tensor-like mock supporting squeeze, tolist, and indexing."""

    def __init__(self, data: list[Any]) -> None:
        self.data = data

    def dim(self) -> int:
        if isinstance(self.data, list) and len(self.data) > 0 and isinstance(self.data[0], list):
            if isinstance(self.data[0][0], list):
                return 3
            return 2
        return 1

    def squeeze(self, axis: int = 0) -> "MockTensor":
        if axis == 0 and isinstance(self.data, list):
            return MockTensor(self.data[0])
        return self

    def __getitem__(self, item: Any) -> "MockTensor":
        # Supports [:, idx] slicing
        if isinstance(item, tuple) and item[0] == slice(None):
            col_idx = item[1]
            return MockTensor([row[col_idx] for row in self.data])
        return MockTensor(self.data[item])

    def tolist(self) -> list[Any]:
        return self.data


class MockOfficialChronosBoltPipeline:
    """Mock simulating the official chronos-forecasting predict_quantiles API."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def predict_quantiles(
        self,
        inputs: Any,
        prediction_length: int,
        quantile_levels: list[float],
        **predict_kwargs: Any,
    ) -> tuple[MockTensor, MockTensor]:
        # returns (quantiles_tensor, mean_tensor)
        # 3D: (1, prediction_length, num_quantiles)
        last_price = float(inputs[-1]) if hasattr(inputs, "__getitem__") else 100.0
        matrix_3d = []
        rows = []
        for step in range(prediction_length):
            row = [round(last_price * (1.0 + (q - 0.5) * 0.04) + step * 0.1, 4) for q in quantile_levels]
            rows.append(row)
        matrix_3d.append(rows)

        mean_2d = [[last_price + step * 0.1 for step in range(prediction_length)]]
        return MockTensor(matrix_3d), MockTensor(mean_2d)


def test_chronos_missing_dependencies_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deterministically verify missing dependency branch
    monkeypatch.setitem(sys.modules, "chronos", None)
    monkeypatch.setitem(sys.modules, "torch", None)

    adapter = ChronosBoltTinyAdapter()
    with pytest.raises(ImportError, match="Cannot load"):
        adapter.load()


def test_chronos_adapter_mock_smoke_and_latency() -> None:
    adapter = ChronosBoltTinyAdapter(
        pipeline_factory=lambda name: MockChronosPipeline(name),
        max_horizon_bars=24,
    )
    assert not adapter.is_loaded

    # Cold-load timer
    t0 = time.perf_counter()
    adapter.load()
    load_time_ms = (time.perf_counter() - t0) * 1000.0
    assert adapter.is_loaded
    assert load_time_ms < 500.0

    history = _make_series(20)
    req = ForecastRequest(
        symbol="SPY",
        timeframe="1h",
        history=history,
        horizon_bars=6,
        quantiles=(0.10, 0.50, 0.90),
    )

    t1 = time.perf_counter()
    result = adapter.predict(req)
    infer_time_ms = (time.perf_counter() - t1) * 1000.0

    assert isinstance(result, ForecastResult)
    assert infer_time_ms < 100.0
    assert len(result.point_forecast) == 6
    assert len(result.timestamps) == 6
    assert result.model_id == "chronos-bolt-tiny"

    # Invariant: monotonic quantiles
    for step in range(6):
        assert result.quantile_forecasts[0.10][step] <= result.quantile_forecasts[0.50][step]
        assert result.quantile_forecasts[0.50][step] <= result.quantile_forecasts[0.90][step]

    # Lifecycle unload
    adapter.unload()
    assert not adapter.is_loaded

    with pytest.raises(RuntimeError, match="not loaded"):
        adapter.predict(req)


def test_chronos_adapter_official_api_mock() -> None:
    adapter = ChronosBoltTinyAdapter(
        pipeline_factory=lambda name: MockOfficialChronosBoltPipeline(name),
        max_horizon_bars=24,
    )
    adapter.load()
    history = _make_series(10)
    req = ForecastRequest(
        symbol="SPY",
        timeframe="1h",
        history=history,
        horizon_bars=5,
        quantiles=(0.10, 0.50, 0.90),
    )

    result = adapter.predict(req)
    assert isinstance(result, ForecastResult)
    assert len(result.point_forecast) == 5
    assert set(result.quantile_forecasts.keys()) == {0.10, 0.50, 0.90}
    adapter.unload()
