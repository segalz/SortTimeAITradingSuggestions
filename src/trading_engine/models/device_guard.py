"""CPU-only device guard enforcing strict non-GPU execution."""

from __future__ import annotations

import os
from typing import Any


class DeviceGuardError(RuntimeError):
    """Raised when non-CPU hardware (CUDA, MPS, DirectML) is requested or detected."""


_FORBIDDEN_DEVICE_SUBSTRINGS = (
    "cuda",
    "gpu",
    "mps",
    "dml",
    "directml",
    "npu",
    "tpu",
    "rocm",
    "xpu",
)


def assert_cpu_only(device: str | Any = "cpu") -> str:
    """Validate that the requested device specification is strictly CPU.

    Raises DeviceGuardError if any GPU or accelerator backend is specified.
    """
    if not isinstance(device, str):
        # Handle torch.device objects if torch is used
        device_str = str(device).lower().strip()
    else:
        device_str = device.lower().strip()

    if not device_str or device_str != "cpu":
        for forbidden in _FORBIDDEN_DEVICE_SUBSTRINGS:
            if forbidden in device_str:
                raise DeviceGuardError(
                    f"Hardware acceleration '{device_str}' is forbidden. "
                    "This engine is strictly configured for lightweight CPU-only inference."
                )
        if device_str != "cpu":
            raise DeviceGuardError(
                f"Unsupported device target '{device_str}'. Only 'cpu' is allowed."
            )

    return "cpu"


def enforce_cpu_environment() -> None:
    """Isolate runtime process environment to prevent accidental GPU allocation."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ["ROCM_VISIBLE_DEVICES"] = "-1"
    os.environ["HIP_VISIBLE_DEVICES"] = "-1"

    try:
        import torch  # type: ignore

        if hasattr(torch, "cuda") and hasattr(torch.cuda, "is_available") and torch.cuda.is_available():
            raise DeviceGuardError("CUDA is detected active despite CPU-only isolation.")
    except (ImportError, AttributeError):
        pass
