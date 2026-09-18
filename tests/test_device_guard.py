"""Unit tests for CPU-only device guard."""

import os
import sys
from types import ModuleType
import pytest

from trading_engine.models.device_guard import (
    DeviceGuardError,
    assert_cpu_only,
    enforce_cpu_environment,
)


def test_assert_cpu_only_valid() -> None:
    assert assert_cpu_only("cpu") == "cpu"
    assert assert_cpu_only(" CPU ") == "cpu"
    assert assert_cpu_only("Cpu") == "cpu"


def test_assert_cpu_only_forbidden_devices() -> None:
    forbidden = [
        "cuda",
        "cuda:0",
        "cuda:1",
        "gpu",
        "mps",
        "dml",
        "directml",
        "tpu",
        "npu",
        "rocm",
        "xpu",
    ]
    for dev in forbidden:
        with pytest.raises(DeviceGuardError, match="forbidden"):
            assert_cpu_only(dev)


def test_assert_cpu_only_invalid_target() -> None:
    with pytest.raises(DeviceGuardError, match="Unsupported device target"):
        assert_cpu_only("invalid_backend")

    with pytest.raises(DeviceGuardError, match="Unsupported device target"):
        assert_cpu_only("")


def test_assert_cpu_only_object() -> None:
    class DummyDevice:
        def __init__(self, name: str) -> None:
            self._name = name

        def __str__(self) -> str:
            return self._name

    assert assert_cpu_only(DummyDevice("cpu")) == "cpu"

    with pytest.raises(DeviceGuardError, match="forbidden"):
        assert_cpu_only(DummyDevice("cuda:0"))


def test_enforce_cpu_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("ROCM_VISIBLE_DEVICES", "0")
    monkeypatch.setenv("HIP_VISIBLE_DEVICES", "0")

    enforce_cpu_environment()
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "-1"
    assert os.environ["ROCM_VISIBLE_DEVICES"] == "-1"
    assert os.environ["HIP_VISIBLE_DEVICES"] == "-1"


def test_enforce_cpu_environment_detects_active_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = ModuleType("torch")
    fake_cuda = ModuleType("cuda")
    fake_cuda.is_available = lambda: True  # type: ignore[attr-defined]
    fake_torch.cuda = fake_cuda  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    with pytest.raises(DeviceGuardError, match="CUDA is detected active"):
        enforce_cpu_environment()
