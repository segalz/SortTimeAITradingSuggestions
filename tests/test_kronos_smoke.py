"""Smoke and lifecycle tests for vendored Kronos-mini model, tokenizer, and adapter."""

from datetime import datetime, timedelta, timezone
import pytest

from trading_engine.contracts.forecast import ForecastRequest, ForecastResult
from trading_engine.data.models import BarSeries, Candle
from trading_engine.models.kronos_adapter import KronosMiniAdapter
from trading_engine.models.vendored.kronos import (
    KronosMiniConfig,
    KronosMiniModel,
    KronosTokenizer,
)


def _make_series(n: int = 20, symbol: str = "SPY", timeframe: str = "1h") -> BarSeries:
    base = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=100.0 + i * 0.5,
            high=101.0 + i * 0.5,
            low=99.0 + i * 0.5,
            close=100.0 + i * 0.5,
            volume=2000.0,
        )
        for i in range(n)
    ]
    return BarSeries(symbol=symbol, timeframe=timeframe, bars=tuple(candles))


def test_kronos_tokenizer_encode_decode() -> None:
    tok = KronosTokenizer(vocab_size=1024, max_return=0.10)
    returns = [-0.05, -0.01, 0.0, 0.02, 0.08]
    tokens = tok.encode_returns(returns)

    assert len(tokens) == len(returns)
    assert all(4 <= t < 1024 for t in tokens)

    # Monotonic token ordering: higher return gives higher token ID
    for i in range(len(tokens) - 1):
        assert tokens[i] < tokens[i + 1]

    # Reconstructed returns should match original within bin width
    decoded = tok.decode_returns(tokens)
    for orig, dec in zip(returns, decoded):
        assert abs(orig - dec) <= tok.bin_width


def test_kronos_tokenizer_price_roundtrip() -> None:
    tok = KronosTokenizer(vocab_size=1024, max_return=0.15)
    prices = [100.0, 101.5, 101.0, 102.5, 105.0]
    tokens = tok.prices_to_tokens(prices)
    assert len(tokens) == len(prices) - 1

    recon_prices = tok.tokens_to_prices(base_price=prices[0], tokens=tokens)
    assert len(recon_prices) == len(tokens)
    # Final price should approximate original final price
    assert abs(recon_prices[-1] - prices[-1]) / prices[-1] < 0.01


def test_kronos_model_generation() -> None:
    config = KronosMiniConfig(vocab_size=512)
    model = KronosMiniModel(config=config, seed=123)

    tokens = [256, 260, 265]
    paths = model.generate(tokens, max_new_tokens=4, sample_count=3, temperature=0.7)

    assert len(paths) == 3
    for path in paths:
        assert len(path) == 4
        assert all(4 <= t < 512 for t in path)


def test_kronos_mini_adapter_lifecycle_and_prediction() -> None:
    adapter = KronosMiniAdapter(sample_count=10, max_horizon_bars=24)
    assert not adapter.is_loaded

    history = _make_series(15)
    req = ForecastRequest(
        symbol="SPY",
        timeframe="1h",
        history=history,
        horizon_bars=6,
        quantiles=(0.10, 0.50, 0.90),
    )

    with pytest.raises(RuntimeError, match="not loaded"):
        adapter.predict(req)

    adapter.load()
    assert adapter.is_loaded

    result = adapter.predict(req)
    assert isinstance(result, ForecastResult)
    assert len(result.point_forecast) == 6
    assert len(result.timestamps) == 6
    assert result.model_id == "kronos-mini"

    # Monotonic quantiles invariant
    for step in range(6):
        assert result.quantile_forecasts[0.10][step] <= result.quantile_forecasts[0.50][step]
        assert result.quantile_forecasts[0.50][step] <= result.quantile_forecasts[0.90][step]

    # Unload
    adapter.unload()
    assert not adapter.is_loaded

    with pytest.raises(RuntimeError, match="not loaded"):
        adapter.predict(req)
