"""Unit tests for transaction cost, slippage, and 2x sensitivity gate model."""

import pytest

from trading_engine.risk.cost_model import (
    CostBreakdown,
    CostEvaluationResult,
    CostModel,
)


def test_cost_model_defaults() -> None:
    model = CostModel()
    costs = model.compute_one_way_costs()

    # 5 bps fee = 0.0005, 2.5 bps half spread = 0.00025, 2.5 bps slippage = 0.00025
    # Total one-way = 0.0010 (10 bps); roundtrip = 0.0020 (20 bps)
    assert costs.fee_rate == pytest.approx(0.0005)
    assert costs.half_spread == pytest.approx(0.00025)
    assert costs.slippage == pytest.approx(0.00025)
    assert costs.total_one_way_cost == pytest.approx(0.0010)
    assert costs.total_roundtrip_cost == pytest.approx(0.0020)


def test_cost_model_validation() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        CostModel(taker_fee_bps=-1.0)

    with pytest.raises(ValueError, match="bool rejected"):
        CostModel(half_spread_bps=True)  # type: ignore

    with pytest.raises(ValueError, match="finite number"):
        CostModel(slippage_bps_const=float("nan"))


def test_maker_vs_taker_costs() -> None:
    model = CostModel(taker_fee_bps=10.0, half_spread_bps=2.0, slippage_bps_const=3.0)
    taker_costs = model.compute_one_way_costs(order_type="taker")
    maker_costs = model.compute_one_way_costs(order_type="maker")

    assert taker_costs.fee_rate == pytest.approx(0.0010)
    assert maker_costs.fee_rate == pytest.approx(0.0)
    assert maker_costs.total_one_way_cost < taker_costs.total_one_way_cost

    with pytest.raises(ValueError, match="order_type"):
        model.compute_one_way_costs(order_type="invalid")  # type: ignore


def test_volatility_slippage_scaling() -> None:
    model = CostModel(slippage_bps_const=2.0, volatility_slippage_coeff=0.1)
    calm_costs = model.compute_one_way_costs(volatility=0.0)
    volatile_costs = model.compute_one_way_costs(volatility=0.02)  # 2% volatility

    assert volatile_costs.slippage > calm_costs.slippage
    # extra slippage = 0.1 * 0.02 = 0.002 (20 bps)
    assert volatile_costs.slippage - calm_costs.slippage == pytest.approx(0.0020)


def test_apply_execution_costs() -> None:
    model = CostModel(taker_fee_bps=10.0, half_spread_bps=0.0, slippage_bps_const=0.0)
    # One-way cost = 10 bps = 0.001

    buy_px = model.apply_execution_costs(100.0, side="buy")
    assert buy_px == pytest.approx(100.10)

    sell_px = model.apply_execution_costs(100.0, side="sell")
    assert sell_px == pytest.approx(99.90)

    # 2x multiplier
    buy_px_2x = model.apply_execution_costs(100.0, side="buy", multiplier=2.0)
    assert buy_px_2x == pytest.approx(100.20)

    with pytest.raises(ValueError, match="side must be 'buy' or 'sell'"):
        model.apply_execution_costs(100.0, side="hold")  # type: ignore

    with pytest.raises(ValueError, match="positive finite number"):
        model.apply_execution_costs(-10.0, side="buy")

    with pytest.raises(ValueError, match="positive finite number"):
        model.apply_execution_costs(True, side="buy")  # type: ignore


def test_2x_sensitivity_gate_pass_and_fail() -> None:
    model = CostModel()  # roundtrip = 20 bps = 0.0020; 2x roundtrip = 40 bps = 0.0040

    # Case 1: Strong long trade (gross +1.0% = 0.0100 > 0.0040) -> PASS
    res1 = model.evaluate_trade_viability(entry_price=100.0, exit_price=101.0, side="long")
    assert res1.gate_passed is True
    assert res1.gross_return == pytest.approx(0.01)
    assert res1.net_return_1x == pytest.approx(0.0080)
    assert res1.net_return_2x == pytest.approx(0.0060)

    # Case 2: Marginal long trade (gross +0.25% = 0.0025 > 0.0020, but < 0.0040) -> FAILS 2X GATE
    res2 = model.evaluate_trade_viability(entry_price=100.0, exit_price=100.25, side="long")
    assert res2.gross_return == pytest.approx(0.0025)
    assert res2.net_return_1x > 0.0  # profitable at 1x
    assert res2.net_return_2x < 0.0  # negative under 2x
    assert res2.gate_passed is False
    assert "2x cost sensitivity stress gate" in res2.reason

    # Case 3: Negative gross trade -> FAILS
    res3 = model.evaluate_trade_viability(entry_price=100.0, exit_price=99.0, side="long")
    assert res3.gate_passed is False
    assert res3.gross_return < 0

    # Case 4: Short trade profitable after 2x costs -> PASS
    res4 = model.evaluate_trade_viability(entry_price=100.0, exit_price=98.5, side="short")
    assert res4.gross_return == pytest.approx(0.015)
    assert res4.gate_passed is True
    assert res4.net_return_2x > 0.0
