"""Unit tests for ModelAdapter, BaselineAdapter, and CPU device helpers."""

from datetime import datetime, timedelta, timezone
import os
import pytest

from trading_engine.contracts.adapter import (
    BaselineAdapter,
    ModelAdapterCapabilities,
    infer_timeframe_delta,
)
from trading_engine.contracts.device import (
    clamp_cpu_threads,
    cpu_thread_limit,
    set_cpu_affinity,
)
from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.data.models import BarSeries, Candle, DataContractError
from trading_engine.models.baselines import (
    DriftBaseline,
    LastValueBaseline,
    MovingAverageBaseline,
)


def _make_series(n: int = 10, symbol: str = "SPY", timeframe: str = "1h") -> BarSeries:
    base = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.0 + i,
            volume=500.0,
        )
        for i in range(n)
    ]
    return BarSeries(symbol=symbol, timeframe=timeframe, bars=tuple(candles))


def test_device_clamp_cpu_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="num_threads must be >= 1"):
        clamp_cpu_threads(0)

    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)

    val = clamp_cpu_threads(2)
    assert val == 2
    assert os.environ["OMP_NUM_THREADS"] == "2"
    assert os.environ["MKL_NUM_THREADS"] == "2"


def test_device_cpu_thread_limit_context() -> None:
    os.environ["OMP_NUM_THREADS"] = "8"
    try:
        with cpu_thread_limit(2):
            assert os.environ["OMP_NUM_THREADS"] == "2"
        assert os.environ["OMP_NUM_THREADS"] == "8"
    finally:
        os.environ.pop("OMP_NUM_THREADS", None)


def test_device_set_cpu_affinity() -> None:
    assert set_cpu_affinity(None) is None

    with pytest.raises(ValueError, match="non-empty"):
        set_cpu_affinity([])

    with pytest.raises(ValueError, match="non-negative"):
        set_cpu_affinity([-1])

    # Valid call gracefully handles platform support
    set_cpu_affinity([0])


def test_infer_timeframe_delta() -> None:
    assert infer_timeframe_delta("1m") == timedelta(minutes=1)
    assert infer_timeframe_delta("15m") == timedelta(minutes=15)
    assert infer_timeframe_delta("1h") == timedelta(hours=1)
    assert infer_timeframe_delta("1d") == timedelta(days=1)
    assert infer_timeframe_delta("1w") == timedelta(weeks=1)

    with pytest.raises(ValueError, match="Unrecognized timeframe"):
        infer_timeframe_delta("invalid")


def test_adapter_capabilities_validation() -> None:
    with pytest.raises(DataContractError, match="model_id"):
        ModelAdapterCapabilities(
            model_id="",
            supports_quantiles=True,
            supported_timeframes=("1h",),
            max_horizon_bars=24,
        )

    with pytest.raises(DataContractError, match="supported_timeframes"):
        ModelAdapterCapabilities(
            model_id="m1",
            supports_quantiles=True,
            supported_timeframes=(),
            max_horizon_bars=24,
        )

    with pytest.raises(DataContractError, match="max_horizon_bars"):
        ModelAdapterCapabilities(
            model_id="m1",
            supports_quantiles=True,
            supported_timeframes=("1h",),
            max_horizon_bars=0,
        )


def test_baseline_adapter_lifecycle() -> None:
    adapter = BaselineAdapter(
        "last_value",
        LastValueBaseline(),
        supported_timeframes=("1h",),
        max_horizon_bars=12,
    )
    assert adapter.model_id == "last_value"
    assert not adapter.is_loaded

    caps = adapter.capabilities()
    assert caps.model_id == "last_value"
    assert caps.supported_timeframes == ("1h",)
    assert caps.max_horizon_bars == 12

    history = _make_series(5)
    req = ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=4)

    # Must raise before load()
    with pytest.raises(RuntimeError, match="not loaded"):
        adapter.predict(req)

    # Idempotent load()
    adapter.load()
    adapter.load()
    assert adapter.is_loaded

    # Exceeding horizon limit
    req_too_long = ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=15)
    with pytest.raises(ValueError, match="exceeds maximum"):
        adapter.predict(req_too_long)

    # Unsupported timeframe
    history_5m = BarSeries(symbol="SPY", timeframe="5m", bars=history.bars)
    req_unsupported_tf = ForecastRequest(symbol="SPY", timeframe="5m", history=history_5m, horizon_bars=4)
    with pytest.raises(ValueError, match="is not supported"):
        adapter.predict(req_unsupported_tf)

    # Valid prediction
    result = adapter.predict(req)
    assert isinstance(result, ForecastResult)
    assert len(result.point_forecast) == 4
    assert len(result.timestamps) == 4
    assert result.model_id == "last_value"
    assert result.created_at == history[-1].timestamp
    assert set(result.quantile_forecasts.keys()) == {0.10, 0.50, 0.90}

    # Verify unloading and idempotency
    adapter.unload()
    adapter.unload()
    assert not adapter.is_loaded

    # Predict after unload must raise
    with pytest.raises(RuntimeError, match="not loaded"):
        adapter.predict(req)


def test_baseline_adapter_drift_and_ma() -> None:
    history = _make_series(10)
    req = ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=3)

    # Drift adapter
    drift_adapter = BaselineAdapter("drift", DriftBaseline())
    drift_adapter.load()
    drift_res = drift_adapter.predict(req)
    assert drift_res.point_forecast[0] > history[-1].close
    assert drift_res.probabilities["up"] > drift_res.probabilities["down"]

    # Moving Average adapter
    ma_adapter = BaselineAdapter("ma", MovingAverageBaseline(window=3))
    ma_adapter.load()
    ma_res = ma_adapter.predict(req)
    assert len(ma_res.point_forecast) == 3
