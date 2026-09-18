"""Unit tests for ForecastRequest and ForecastResult contracts."""

from datetime import datetime, timedelta, timezone
from types import MappingProxyType
import pytest

from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.data.models import BarSeries, Candle, DataContractError


def _make_sample_candle(ts: datetime, close: float = 100.0) -> Candle:
    return Candle(
        timestamp=ts,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1000.0,
    )


def _make_sample_series(n: int = 10, symbol: str = "SPY", timeframe: str = "1h") -> BarSeries:
    base = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    candles = [
        _make_sample_candle(base + timedelta(hours=i), close=100.0 + i)
        for i in range(n)
    ]
    return BarSeries(symbol=symbol, timeframe=timeframe, bars=tuple(candles))


def test_forecast_request_valid() -> None:
    history = _make_sample_series(5)
    req = ForecastRequest(
        symbol="spy",
        timeframe="1h",
        history=history,
        horizon_bars=3,
        quantiles=[0.10, 0.50, 0.90],  # list should be coerced to tuple
        metadata={"source": "unit_test"},
    )
    assert req.symbol == "SPY"
    assert req.horizon_bars == 3
    assert req.quantiles == (0.10, 0.50, 0.90)
    assert isinstance(req.quantiles, tuple)
    assert isinstance(req.metadata, MappingProxyType)
    assert req.metadata["source"] == "unit_test"

    # Verify immutability of metadata
    with pytest.raises(TypeError):
        req.metadata["new_key"] = "forbidden"  # type: ignore


def test_forecast_request_invalid_inputs() -> None:
    history = _make_sample_series(5, symbol="SPY", timeframe="1h")

    with pytest.raises(DataContractError, match="symbol"):
        ForecastRequest(symbol="", timeframe="1h", history=history, horizon_bars=3)

    with pytest.raises(DataContractError, match="timeframe"):
        ForecastRequest(symbol="SPY", timeframe="", history=history, horizon_bars=3)

    # Symbol and timeframe mismatch
    with pytest.raises(DataContractError, match="does not match history symbol"):
        ForecastRequest(symbol="QQQ", timeframe="1h", history=history, horizon_bars=3)

    with pytest.raises(DataContractError, match="does not match history timeframe"):
        ForecastRequest(symbol="SPY", timeframe="5m", history=history, horizon_bars=3)

    # Horizon bars validations including bool rejection
    with pytest.raises(DataContractError, match="horizon_bars"):
        ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=0)

    with pytest.raises(DataContractError, match="bool rejected"):
        ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=True)

    with pytest.raises(DataContractError, match="history"):
        ForecastRequest(
            symbol="SPY",
            timeframe="1h",
            history=BarSeries(symbol="SPY", timeframe="1h", bars=()),
            horizon_bars=3,
        )

    # Quantiles checks
    with pytest.raises(DataContractError, match="quantiles must not be empty"):
        ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=3, quantiles=())

    with pytest.raises(DataContractError, match="iterable"):
        ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=3, quantiles=0.5)  # type: ignore

    with pytest.raises(DataContractError, match="strictly in"):
        ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=3, quantiles=(0.0, 0.5))

    with pytest.raises(DataContractError, match="strictly increasing"):
        ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=3, quantiles=(0.5, 0.2))

    with pytest.raises(DataContractError, match="bool rejected"):
        ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=3, quantiles=(True, 0.5))


def test_forecast_result_valid_and_frozen() -> None:
    history = _make_sample_series(5)
    cutoff = history[-1].timestamp
    req = ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=3)

    future_ts = [
        cutoff + timedelta(hours=1),
        cutoff + timedelta(hours=2),
        cutoff + timedelta(hours=3),
    ]
    res = ForecastResult(
        request=req,
        timestamps=future_ts,  # list -> tuple
        point_forecast=[105.0, 106.0, 107.0],  # list -> tuple
        quantile_forecasts={
            0.10: [103.0, 103.5, 104.0],
            0.50: [105.0, 106.0, 107.0],
            0.90: [107.0, 108.5, 110.0],
        },
        model_id="baseline_drift",
        created_at=cutoff,
        probabilities={"up": 0.65, "down": 0.35},
        metadata={"info": "valid"},
    )
    assert isinstance(res.timestamps, tuple)
    assert isinstance(res.point_forecast, tuple)
    assert isinstance(res.quantile_forecasts, MappingProxyType)
    assert isinstance(res.probabilities, MappingProxyType)
    assert isinstance(res.metadata, MappingProxyType)

    # Immutability assertions on nested collections
    with pytest.raises(TypeError):
        res.quantile_forecasts[0.10] = (200.0, 200.0, 200.0)  # type: ignore

    with pytest.raises(TypeError):
        res.probabilities["up"] = 0.99  # type: ignore

    with pytest.raises(TypeError):
        res.metadata["hacked"] = True  # type: ignore


def test_forecast_result_invariants_enforced() -> None:
    history = _make_sample_series(5)
    cutoff = history[-1].timestamp
    req = ForecastRequest(symbol="SPY", timeframe="1h", history=history, horizon_bars=2)
    valid_ts = (cutoff + timedelta(hours=1), cutoff + timedelta(hours=2))

    # Invalid request instance
    with pytest.raises(DataContractError, match="ForecastRequest instance"):
        ForecastResult(
            request="not_a_request",  # type: ignore
            timestamps=valid_ts,
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
        )

    # Missing model_id
    with pytest.raises(DataContractError, match="model_id"):
        ForecastResult(
            request=req,
            timestamps=valid_ts,
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="",
            created_at=cutoff,
        )

    # Non-UTC created_at
    with pytest.raises(DataContractError, match="Timestamp must be UTC"):
        ForecastResult(
            request=req,
            timestamps=valid_ts,
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=datetime(2025, 1, 1, 10, 0),  # naive
        )

    # Timestamps length mismatch
    with pytest.raises(DataContractError, match="timestamps length"):
        ForecastResult(
            request=req,
            timestamps=(valid_ts[0],),
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
        )

    # Timestamp equal to cutoff
    with pytest.raises(DataContractError, match="strictly monotonic"):
        ForecastResult(
            request=req,
            timestamps=(cutoff, cutoff + timedelta(hours=1)),
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
        )

    # Timestamps out of order (ts2 before ts1)
    with pytest.raises(DataContractError, match="strictly monotonic"):
        ForecastResult(
            request=req,
            timestamps=(cutoff + timedelta(hours=2), cutoff + timedelta(hours=1)),
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
        )

    # Negative price in point forecast
    with pytest.raises(DataContractError, match="positive numbers"):
        ForecastResult(
            request=req,
            timestamps=valid_ts,
            point_forecast=(-5.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
        )

    # Bool in point forecast
    with pytest.raises(DataContractError, match="bool rejected"):
        ForecastResult(
            request=req,
            timestamps=valid_ts,
            point_forecast=(True, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
        )

    # Quantile crossing violation (P10 > P50)
    with pytest.raises(DataContractError, match="Quantile monotonicity violated"):
        ForecastResult(
            request=req,
            timestamps=valid_ts,
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (105.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
        )

    # Invalid probability (> 1.0 or bool)
    with pytest.raises(DataContractError, match="Probability for up"):
        ForecastResult(
            request=req,
            timestamps=valid_ts,
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
            probabilities={"up": 1.5},
        )

    with pytest.raises(DataContractError, match="bool rejected"):
        ForecastResult(
            request=req,
            timestamps=valid_ts,
            point_forecast=(100.0, 101.0),
            quantile_forecasts={0.1: (99.0, 100.0), 0.5: (100.0, 101.0), 0.9: (102.0, 103.0)},
            model_id="test_model",
            created_at=cutoff,
            probabilities={"up": True},
        )
