"""Statistical testing and multiplicity correction for backtest evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MultipleTestingCorrectionResult:
    """Result of multiple hypothesis testing correction."""

    p_values: tuple[float, ...]
    adjusted_p_values: tuple[float, ...]
    rejected: tuple[bool, ...]
    alpha: float


def benjamini_hochberg_correction(
    p_values: Sequence[float],
    alpha: float = 0.05,
) -> MultipleTestingCorrectionResult:
    """Apply the Benjamini-Hochberg (BH) procedure to control False Discovery Rate (FDR).

    Parameters
    ----------
    p_values:
        Sequence of unadjusted p-values from multiple candidate models or features.
    alpha:
        Target false discovery rate significance threshold (default: 0.05).

    Returns
    -------
    MultipleTestingCorrectionResult containing adjusted p-values and boolean rejection decisions.
    """
    m = len(p_values)
    if m == 0:
        return MultipleTestingCorrectionResult(
            p_values=(),
            adjusted_p_values=(),
            rejected=(),
            alpha=alpha,
        )

    for p in p_values:
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"p-value must be in range [0, 1], got {p}")

    # Index sorted by p-value ascending
    sorted_indices = sorted(range(m), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in sorted_indices]

    # Compute step-up adjusted p-values
    adjusted_sorted = [0.0] * m
    adjusted_sorted[-1] = sorted_p[-1]

    for i in range(m - 2, -1, -1):
        rank = i + 1  # 1-indexed rank
        adj = (m / rank) * sorted_p[i]
        adjusted_sorted[i] = min(adj, adjusted_sorted[i + 1])

    adjusted_sorted = [min(1.0, max(0.0, p)) for p in adjusted_sorted]

    # Map adjusted p-values back to original input order
    adjusted_p = [0.0] * m
    rejected = [False] * m
    for rank_idx, orig_idx in enumerate(sorted_indices):
        adj = adjusted_sorted[rank_idx]
        adjusted_p[orig_idx] = round(adj, 6)
        rejected[orig_idx] = adj <= alpha

    return MultipleTestingCorrectionResult(
        p_values=tuple(p_values),
        adjusted_p_values=tuple(adjusted_p),
        rejected=tuple(rejected),
        alpha=alpha,
    )
