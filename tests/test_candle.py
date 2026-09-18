"""Unit tests for trading_engine.data Candle and DataContractError."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trading_engine.data import Candle, DataContractError


def make_candle(**overrides):
    """Build a valid Candle, allowing per-field overrides for error cases."""
    fields = dict(
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
        vwap=None,
        amount=None,
    )
    fields.update(overrides)
    return Candle(**fields)


def test_valid_candle():
    candle = make_candle(
        vwap=102.5,
        amount=102500.0,
    )

    assert candle.timestamp == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert candle.open == 100.0
    assert candle.high == 110.0
    assert candle.low == 90.0
    assert candle.close == 105.0
    assert candle.volume == 1000.0
    assert candle.vwap == 102.5
    assert candle.amount == 102500.0


def test_naive_timestamp_rejected():
    with pytest.raises(DataContractError):
        make_candle(timestamp=datetime(2025, 1, 1))


def test_negative_or_zero_price_rejected():
    with pytest.raises(DataContractError):
        make_candle(open=0.0)

    with pytest.raises(DataContractError):
        make_candle(close=-1.0)


def test_inverted_high_low_rejected():
    with pytest.raises(DataContractError):
        make_candle(high=95.0, low=105.0)


def test_open_close_out_of_bounds():
    with pytest.raises(DataContractError):
        make_candle(open=120.0)  # open > high

    with pytest.raises(DataContractError):
        make_candle(close=80.0)  # close < low


def test_negative_volume_rejected():
    with pytest.raises(DataContractError):
        make_candle(volume=-1.0)


def test_optional_vwap_and_amount():
    # Defaults are None.
    candle = make_candle()
    assert candle.vwap is None
    assert candle.amount is None

    # Valid provided values are accepted.
    with_vwap_amount = make_candle(vwap=102.5, amount=102500.0)
    assert with_vwap_amount.vwap == 102.5
    assert with_vwap_amount.amount == 102500.0

    # Invalid (non-positive) values are rejected.
    with pytest.raises(DataContractError):
        make_candle(vwap=-5.0)

    with pytest.raises(DataContractError):
        make_candle(amount=-10.0)
