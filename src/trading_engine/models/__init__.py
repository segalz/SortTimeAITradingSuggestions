"""Quantitative forecasting, baseline models, and device guards."""

from .baselines import (
    BaselineModel,
    DriftBaseline,
    Forecast,
    LastValueBaseline,
    MovingAverageBaseline,
)
from .device_guard import DeviceGuardError, assert_cpu_only, enforce_cpu_environment

__all__ = [
    "BaselineModel",
    "DeviceGuardError",
    "DriftBaseline",
    "Forecast",
    "LastValueBaseline",
    "MovingAverageBaseline",
    "assert_cpu_only",
    "enforce_cpu_environment",
]
