"""Transaction cost, spread, slippage, and 2x fee stress testing model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


def _validate_rate(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (bool rejected)")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")
    return float(value)


@dataclass(frozen=True)
class CostBreakdown:
    """Itemized execution cost breakdown in decimal fraction format."""

    fee_rate: float
    half_spread: float
    slippage: float
    total_one_way_cost: float
    total_roundtrip_cost: float

    def __post_init__(self) -> None:
        for name in (
            "fee_rate",
            "half_spread",
            "slippage",
            "total_one_way_cost",
            "total_roundtrip_cost",
        ):
            _validate_rate(name, getattr(self, name))


@dataclass(frozen=True)
class CostEvaluationResult:
    """Result of evaluating a trade setup against baseline and 2x friction."""

    gross_return: float
    total_cost_1x: float
    net_return_1x: float
    total_cost_2x: float
    net_return_2x: float
    gate_passed: bool
    reason: str

    def __post_init__(self) -> None:
        if isinstance(self.gate_passed, bool) is False:
            raise ValueError("gate_passed must be a boolean")
        for name in (
            "gross_return",
            "total_cost_1x",
            "net_return_1x",
            "total_cost_2x",
            "net_return_2x",
        ):
            val = getattr(self, name)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float")


@dataclass(frozen=True)
class CostModel:
    """Configurable friction model covering fees, spread, slippage, and 2x gate."""

    taker_fee_bps: float = 5.0  # 5 basis points = 0.0005
    half_spread_bps: float = 2.5  # 2.5 basis points = 0.00025
    slippage_bps_const: float = 2.5  # 2.5 basis points = 0.00025
    volatility_slippage_coeff: float = 0.05  # alpha * vol

    def __post_init__(self) -> None:
        object.__setattr__(self, "taker_fee_bps", _validate_rate("taker_fee_bps", self.taker_fee_bps))
        object.__setattr__(self, "half_spread_bps", _validate_rate("half_spread_bps", self.half_spread_bps))
        object.__setattr__(self, "slippage_bps_const", _validate_rate("slippage_bps_const", self.slippage_bps_const))
        object.__setattr__(self, "volatility_slippage_coeff", _validate_rate("volatility_slippage_coeff", self.volatility_slippage_coeff))

    def compute_one_way_costs(
        self,
        volatility: float = 0.0,
        order_type: Literal["taker", "maker"] = "taker",
    ) -> CostBreakdown:
        """Calculate one-way execution cost fractions."""
        if order_type not in ("taker", "maker"):
            raise ValueError(f"order_type must be 'taker' or 'maker', got {order_type}")

        vol = _validate_rate("volatility", volatility)

        fee_rate = (self.taker_fee_bps / 10_000.0) if order_type == "taker" else 0.0
        half_spread = self.half_spread_bps / 10_000.0
        slippage = (self.slippage_bps_const / 10_000.0) + (self.volatility_slippage_coeff * vol)

        total_one_way = fee_rate + half_spread + slippage
        total_roundtrip = total_one_way * 2.0

        return CostBreakdown(
            fee_rate=fee_rate,
            half_spread=half_spread,
            slippage=slippage,
            total_one_way_cost=total_one_way,
            total_roundtrip_cost=total_roundtrip,
        )

    def apply_execution_costs(
        self,
        price: float,
        side: Literal["buy", "sell"],
        volatility: float = 0.0,
        multiplier: float = 1.0,
    ) -> float:
        """Adjust raw nominal price by execution friction."""
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError(f"price must be a positive finite number, got {price}")
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side}")
        mult = _validate_rate("multiplier", multiplier)

        costs = self.compute_one_way_costs(volatility=volatility)
        friction = costs.total_one_way_cost * mult

        if side == "buy":
            # Buyer pays price + friction
            return price * (1.0 + friction)
        else:
            # Seller receives price - friction
            return max(0.0001, price * (1.0 - friction))

    def evaluate_trade_viability(
        self,
        entry_price: float,
        exit_price: float,
        side: Literal["long", "short"] = "long",
        volatility: float = 0.0,
    ) -> CostEvaluationResult:
        """Evaluate trade return under 1x and 2x cost sensitivity stress gate."""
        if isinstance(entry_price, bool) or not isinstance(entry_price, (int, float)) or not math.isfinite(entry_price) or entry_price <= 0:
            raise ValueError("entry_price must be a positive finite number")
        if isinstance(exit_price, bool) or not isinstance(exit_price, (int, float)) or not math.isfinite(exit_price) or exit_price <= 0:
            raise ValueError("exit_price must be a positive finite number")
        if side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {side}")

        if side == "long":
            gross_return = (exit_price - entry_price) / entry_price
        else:
            gross_return = (entry_price - exit_price) / entry_price

        breakdown = self.compute_one_way_costs(volatility=volatility)
        total_cost_1x = breakdown.total_roundtrip_cost
        total_cost_2x = total_cost_1x * 2.0

        net_return_1x = gross_return - total_cost_1x
        net_return_2x = gross_return - total_cost_2x

        if gross_return <= 0.0:
            gate_passed = False
            reason = f"Negative gross return ({gross_return:.4%})"
        elif net_return_1x <= 0.0:
            gate_passed = False
            reason = (
                f"Gross return ({gross_return:.4%}) eliminated by standard 1x costs "
                f"({total_cost_1x:.4%})"
            )
        elif net_return_2x <= 0.0:
            gate_passed = False
            reason = (
                f"Trade failed 2x cost sensitivity stress gate: net return under 2x costs "
                f"is negative ({net_return_2x:.4%}, 2x cost: {total_cost_2x:.4%})"
            )
        else:
            gate_passed = True
            reason = (
                f"Trade passed 2x cost sensitivity gate (net 1x: {net_return_1x:.4%}, "
                f"net 2x: {net_return_2x:.4%})"
            )

        return CostEvaluationResult(
            gross_return=gross_return,
            total_cost_1x=total_cost_1x,
            net_return_1x=net_return_1x,
            total_cost_2x=total_cost_2x,
            net_return_2x=net_return_2x,
            gate_passed=gate_passed,
            reason=reason,
        )
