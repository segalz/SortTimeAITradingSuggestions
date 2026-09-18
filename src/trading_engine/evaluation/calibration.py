"""Probability calibration methods (Platt scaling, Isotonic regression) and metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


def _validate_binary_targets(y_true: Sequence[int | float]) -> list[int]:
    if not y_true:
        raise ValueError("y_true must not be empty")
    cleaned = []
    for y in y_true:
        if isinstance(y, bool) or not isinstance(y, (int, float)) or not math.isfinite(y):
            raise ValueError("y_true must contain finite binary values (0 or 1)")
        y_int = int(y)
        if y_int not in (0, 1) or y_int != y:
            raise ValueError(f"y_true elements must be binary 0 or 1, got {y}")
        cleaned.append(y_int)
    return cleaned


def _validate_scores(scores: Sequence[float], expected_len: int | None = None) -> list[float]:
    if not scores:
        raise ValueError("scores must not be empty")
    if expected_len is not None and len(scores) != expected_len:
        raise ValueError(f"scores length ({len(scores)}) does not match targets length ({expected_len})")
    cleaned = []
    for s in scores:
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s):
            raise ValueError("scores must contain finite numeric values (bool rejected)")
        cleaned.append(float(s))
    return cleaned


def brier_score(y_true: Sequence[int], y_prob: Sequence[float]) -> float:
    """Compute the Brier probability score (mean squared error of probabilities)."""
    targets = _validate_binary_targets(y_true)
    probs = _validate_scores(y_prob, expected_len=len(targets))
    for p in probs:
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"Probabilities must be in [0.0, 1.0], got {p}")

    n = len(targets)
    total_sq_err = sum((p - y) ** 2 for p, y in zip(probs, targets))
    return total_sq_err / n


@dataclass(frozen=True)
class ReliabilityDiagramResult:
    """Container for reliability binning analysis and Expected Calibration Error (ECE)."""

    bin_centers: tuple[float, ...]
    accuracies: tuple[float, ...]
    confidences: tuple[float, ...]
    bin_counts: tuple[int, ...]
    expected_calibration_error: float


def reliability_diagram(
    y_true: Sequence[int],
    y_prob: Sequence[float],
    n_bins: int = 5,
) -> ReliabilityDiagramResult:
    """Partition predictions into bins and compute reliability curve and ECE."""
    if n_bins < 2:
        raise ValueError("n_bins must be >= 2")

    targets = _validate_binary_targets(y_true)
    probs = _validate_scores(y_prob, expected_len=len(targets))
    n = len(targets)

    for p in probs:
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"Probabilities must be in [0.0, 1.0], got {p}")

    bin_targets: list[list[int]] = [[] for _ in range(n_bins)]
    bin_probs: list[list[float]] = [[] for _ in range(n_bins)]

    for y, p in zip(targets, probs):
        b = min(n_bins - 1, max(0, int(p * n_bins)))
        bin_targets[b].append(y)
        bin_probs[b].append(p)

    bin_centers = []
    accuracies = []
    confidences = []
    bin_counts = []
    ece = 0.0

    for b in range(n_bins):
        center = (b + 0.5) / n_bins
        bin_centers.append(center)
        count = len(bin_targets[b])
        bin_counts.append(count)

        if count > 0:
            acc = sum(bin_targets[b]) / count
            conf = sum(bin_probs[b]) / count
            accuracies.append(acc)
            confidences.append(conf)
            ece += (count / n) * abs(acc - conf)
        else:
            accuracies.append(0.0)
            confidences.append(center)

    return ReliabilityDiagramResult(
        bin_centers=tuple(bin_centers),
        accuracies=tuple(accuracies),
        confidences=tuple(confidences),
        bin_counts=tuple(bin_counts),
        expected_calibration_error=ece,
    )


class PlattScalingCalibrator:
    """Logistic calibration mapping uncalibrated scores to calibrated probabilities.

    Uses regularized Newton-Raphson optimization with Platt's target smoothing:
    P(y=1 | s) = 1 / (1 + exp(-(A * s + B)))
    """

    def __init__(self) -> None:
        self.a_: float | None = None
        self.b_: float | None = None

    @property
    def is_fitted(self) -> bool:
        return self.a_ is not None and self.b_ is not None

    def fit(self, scores: Sequence[float], y_true: Sequence[int]) -> PlattScalingCalibrator:
        targets = _validate_binary_targets(y_true)
        s_arr = _validate_scores(scores, expected_len=len(targets))

        n = len(targets)
        if n < 5:
            raise ValueError(f"Need at least 5 samples to calibrate, got {n}")

        n_pos = sum(targets)
        n_neg = n - n_pos
        if n_pos == 0 or n_neg == 0:
            raise ValueError("y_true must contain both positive and negative examples")

        # Platt target smoothing
        t_pos = (n_pos + 1.0) / (n_pos + 2.0)
        t_neg = 1.0 / (n_neg + 2.0)
        t = [t_pos if y == 1 else t_neg for y in targets]

        # Initial parameters: A=0, B aligns with smoothed class prior
        a = 0.0
        b = math.log((n_pos + 1.0) / (n_neg + 1.0))

        # Regularized Newton-Raphson optimization
        lambda_reg = 1e-4
        max_iter = 100
        for _ in range(max_iter):
            # Compute probabilities via sigmoid(As + B)
            p = []
            for s in s_arr:
                f = a * s + b
                if f >= 0:
                    p.append(1.0 / (1.0 + math.exp(-f)))
                else:
                    p.append(math.exp(f) / (1.0 + math.exp(f)))

            d1_a = lambda_reg * a
            d1_b = lambda_reg * b
            d2_a = lambda_reg
            d2_b = lambda_reg
            d2_ab = 0.0

            for s, pi, ti in zip(s_arr, p, t):
                d = pi - ti
                w = max(1e-12, pi * (1.0 - pi))
                d1_a += s * d
                d1_b += d
                d2_a += s * s * w
                d2_b += w
                d2_ab += s * w

            det = d2_a * d2_b - d2_ab * d2_ab
            if det <= 1e-14:
                break

            da = -(d2_b * d1_a - d2_ab * d1_b) / det
            db = -(d2_a * d1_b - d2_ab * d1_a) / det

            # Step damping
            da = max(-2.0, min(2.0, da))
            db = max(-2.0, min(2.0, db))

            a += da
            b += db

            if abs(da) < 1e-7 and abs(db) < 1e-7:
                break

        self.a_ = a
        self.b_ = b
        return self

    def predict_proba(self, scores: Sequence[float]) -> tuple[float, ...]:
        if not self.is_fitted:
            raise RuntimeError("Calibrator is not fitted. Call fit() first.")
        s_arr = _validate_scores(scores)

        probs = []
        for s in s_arr:
            f = self.a_ * s + self.b_  # type: ignore[operator]
            if f >= 0:
                prob = 1.0 / (1.0 + math.exp(-f))
            else:
                prob = math.exp(f) / (1.0 + math.exp(f))
            probs.append(min(1.0, max(0.0, prob)))
        return tuple(probs)


class IsotonicCalibrator:
    """Monotonic non-parametric probability calibrator using Pool Adjacent Violators Algorithm (PAVA)."""

    def __init__(self) -> None:
        self.x_knots_: tuple[float, ...] | None = None
        self.y_knots_: tuple[float, ...] | None = None

    @property
    def is_fitted(self) -> bool:
        return self.x_knots_ is not None and self.y_knots_ is not None

    def fit(self, scores: Sequence[float], y_true: Sequence[int]) -> IsotonicCalibrator:
        targets = _validate_binary_targets(y_true)
        s_arr = _validate_scores(scores, expected_len=len(targets))

        n = len(targets)
        if n < 3:
            raise ValueError(f"Need at least 3 samples to fit isotonic calibrator, got {n}")

        # Step 1: Pre-aggregate tied x into weighted groups
        points_map: dict[float, list[int]] = {}
        for s, y in zip(s_arr, targets):
            points_map.setdefault(s, []).append(y)

        sorted_unique_x = sorted(points_map.keys())
        x_vals = sorted_unique_x
        w_vals = [float(len(points_map[ux])) for ux in sorted_unique_x]
        y_vals = [float(sum(points_map[ux])) / len(points_map[ux]) for ux in sorted_unique_x]

        # Step 2: Standard PAVA stack: elements are [weight, sum_wy, x_min, x_max]
        stack: list[list[float]] = []
        for xi, yi, wi in zip(x_vals, y_vals, w_vals):
            cur = [wi, wi * yi, xi, xi]
            while stack and (stack[-1][1] / stack[-1][0]) >= (cur[1] / cur[0]):
                prev = stack.pop()
                cur[0] += prev[0]
                cur[1] += prev[1]
                cur[2] = prev[2]  # maintain overall x_min
            stack.append(cur)

        # Step 3: Extract monotonic knot points
        x_pts: list[float] = []
        y_pts: list[float] = []
        for block in stack:
            w, sum_wy, x_min, x_max = block
            val = min(1.0, max(0.0, sum_wy / w))
            if x_min == x_max:
                x_pts.append(x_min)
                y_pts.append(val)
            else:
                x_pts.extend([x_min, x_max])
                y_pts.extend([val, val])

        self.x_knots_ = tuple(x_pts)
        self.y_knots_ = tuple(y_pts)
        return self

    def predict_proba(self, scores: Sequence[float]) -> tuple[float, ...]:
        if not self.is_fitted:
            raise RuntimeError("Calibrator is not fitted. Call fit() first.")
        s_arr = _validate_scores(scores)

        x_pts = self.x_knots_  # type: ignore[assignment]
        y_pts = self.y_knots_  # type: ignore[assignment]

        probs = []
        for s in s_arr:
            if s <= x_pts[0]:
                probs.append(y_pts[0])
            elif s >= x_pts[-1]:
                probs.append(y_pts[-1])
            else:
                for i in range(len(x_pts) - 1):
                    if x_pts[i] <= s <= x_pts[i + 1]:
                        dx = x_pts[i + 1] - x_pts[i]
                        if dx < 1e-12:
                            p = y_pts[i]
                        else:
                            t = (s - x_pts[i]) / dx
                            p = y_pts[i] + t * (y_pts[i + 1] - y_pts[i])
                        probs.append(min(1.0, max(0.0, p)))
                        break
        return tuple(probs)
