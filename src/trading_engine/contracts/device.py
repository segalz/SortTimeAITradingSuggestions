"""CPU thread clamping, core affinity, and device resource management helpers."""

from __future__ import annotations

import contextlib
import os
from typing import Iterator, Sequence


def clamp_cpu_threads(num_threads: int = 2) -> int:
    """Clamp BLAS/OpenMP and torch math threads to avoid CPU saturation.

    Sets environment variables and applies torch.set_num_threads if PyTorch
    is installed. Returns the number of threads configured.
    """
    if num_threads < 1:
        raise ValueError("num_threads must be >= 1")

    str_val = str(num_threads)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[var] = str_val

    try:
        import torch  # type: ignore

        torch.set_num_threads(num_threads)
    except ImportError:
        pass

    return num_threads


@contextlib.contextmanager
def cpu_thread_limit(num_threads: int = 2) -> Iterator[int]:
    """Context manager temporarily clamping CPU execution threads."""
    if num_threads < 1:
        raise ValueError("num_threads must be >= 1")

    vars_to_track = (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    old_env = {var: os.environ.get(var) for var in vars_to_track}

    old_torch_threads = None
    torch_mod = None
    try:
        import torch  # type: ignore

        torch_mod = torch
        old_torch_threads = torch.get_num_threads()
    except (ImportError, AttributeError):
        pass

    clamp_cpu_threads(num_threads)
    try:
        yield num_threads
    finally:
        for var, prev_val in old_env.items():
            if prev_val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev_val

        if torch_mod is not None and old_torch_threads is not None:
            torch_mod.set_num_threads(old_torch_threads)


def set_cpu_affinity(cpus: Sequence[int] | None = None) -> list[int] | None:
    """Clamp CPU affinity to specific core IDs where supported (Linux/Windows via psutil or sched)."""
    if cpus is None:
        return None

    cpu_list = [int(c) for c in cpus]
    if not cpu_list or any(c < 0 for c in cpu_list):
        raise ValueError("CPU core list must be non-empty and contain non-negative core indices")

    # Method 1: Linux os.sched_setaffinity
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(cpu_list))  # type: ignore[attr-defined]
        return cpu_list

    # Method 2: psutil if installed
    try:
        import psutil  # type: ignore

        p = psutil.Process()
        p.cpu_affinity(cpu_list)
        return cpu_list
    except (ImportError, AttributeError, OSError):
        pass

    return None


def get_process_rss_mb() -> float:
    """Return current process resident set size (RSS) memory in megabytes."""
    # Method 1: psutil
    try:
        import psutil  # type: ignore

        return float(psutil.Process().memory_info().rss) / (1024.0 * 1024.0)
    except (ImportError, AttributeError, OSError):
        pass

    # Method 2: Linux resource
    try:
        import resource  # type: ignore

        # ru_maxrss is in kilobytes on Linux
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return float(kb) / 1024.0
    except (ImportError, AttributeError):
        pass

    # Method 3: Windows psapi via ctypes
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        psapi = ctypes.WinDLL("psapi.dll")
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_PMC),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        h_proc = ctypes.windll.kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(h_proc, ctypes.byref(pmc), pmc.cb):
            return float(pmc.WorkingSetSize) / (1024.0 * 1024.0)
    except Exception:
        pass

    return 0.0
