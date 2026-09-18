"""Unit tests for probability calibration (Platt, Isotonic), Brier score, and reliability diagrams."""

import pytest

from trading_engine.evaluation.calibration import (
    IsotonicCalibrator,
    PlattScalingCalibrator,
    ReliabilityDiagramResult,
    brier_score,
    reliability_diagram,
)


def test_brier_score() -> None:
    # Perfect forecast
    assert brier_score([1, 0, 1], [1.0, 0.0, 1.0]) == pytest.approx(0.0)

    # Completely wrong forecast
    assert brier_score([1, 0, 1], [0.0, 1.0, 0.0]) == pytest.approx(1.0)

    # 50/50 forecast
    assert brier_score([1, 0], [0.5, 0.5]) == pytest.approx(0.25)


def test_brier_score_validation() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        brier_score([], [])

    with pytest.raises(ValueError, match="does not match"):
        brier_score([1, 0], [0.5])

    with pytest.raises(ValueError, match="binary 0 or 1"):
        brier_score([2, 0], [0.5, 0.5])

    with pytest.raises(ValueError, match="bool rejected"):
        brier_score([1, 0], [True, 0.5])  # type: ignore

    with pytest.raises(ValueError, match="must be in"):
        brier_score([1, 0], [1.2, 0.5])


def test_reliability_diagram() -> None:
    # Perfectly calibrated synthetic sample: 50 cases of 0.2 (10 pos), 50 cases of 0.8 (40 pos)
    y_true = [1] * 10 + [0] * 40 + [1] * 40 + [0] * 10
    y_prob = [0.2] * 50 + [0.8] * 50

    diag = reliability_diagram(y_true, y_prob, n_bins=5)
    assert isinstance(diag, ReliabilityDiagramResult)
    assert len(diag.bin_centers) == 5
    assert len(diag.bin_counts) == 5
    assert diag.expected_calibration_error < 0.05  # near-zero ECE

    with pytest.raises(ValueError, match="n_bins must be >= 2"):
        reliability_diagram(y_true, y_prob, n_bins=1)


def test_reliability_diagram_bin_boundaries() -> None:
    # Test that p=0.6 with n_bins=5 falls strictly in bin 3 (center 0.7)
    # and p=0.2 falls in bin 1 (center 0.3)
    y_true = [1, 0, 1, 0]
    y_prob = [0.0, 0.2, 0.6, 1.0]

    diag = reliability_diagram(y_true, y_prob, n_bins=5)
    # Bin centers for n_bins=5: 0.1, 0.3, 0.5, 0.7, 0.9
    assert diag.bin_centers == (0.1, 0.3, 0.5, 0.7, 0.9)
    # Bin counts:
    # p=0.0 -> bin 0
    # p=0.2 -> bin 1
    # p=0.6 -> bin 3
    # p=1.0 -> bin 4
    assert diag.bin_counts == (1, 1, 0, 1, 1)


def test_platt_scaling_calibrator() -> None:
    calibrator = PlattScalingCalibrator()
    assert not calibrator.is_fitted

    with pytest.raises(RuntimeError, match="not fitted"):
        calibrator.predict_proba([0.5])

    # Insufficient samples
    with pytest.raises(ValueError, match="at least 5"):
        calibrator.fit([1.0, 2.0, 3.0], [1, 0, 1])

    # Single class only
    with pytest.raises(ValueError, match="both positive and negative"):
        calibrator.fit([1.0, 2.0, 3.0, 4.0, 5.0], [1, 1, 1, 1, 1])

    # Realistic signal: positive score tends to be y=1
    scores = [-2.0, -1.5, -0.5, 0.2, 0.8, 1.5, 2.0, 3.0]
    targets = [0, 0, 0, 0, 1, 1, 1, 1]

    calibrator.fit(scores, targets)
    assert calibrator.is_fitted

    test_scores = [-2.0, 0.0, 3.0]
    probs = calibrator.predict_proba(test_scores)
    assert len(probs) == 3
    # Check strict monotonicity: higher score gives higher probability
    assert probs[0] < probs[1] < probs[2]
    # Check bounds
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_platt_scaling_constant_scores_and_prior() -> None:
    # 8 constant scores, 2 positive, 6 negative
    # Expected probability should match smoothed prior (2+1)/(8+2) = 0.30
    calibrator = PlattScalingCalibrator()
    scores = [1.0] * 8
    targets = [1, 1, 0, 0, 0, 0, 0, 0]

    calibrator.fit(scores, targets)
    probs = calibrator.predict_proba([1.0])
    assert probs[0] == pytest.approx(0.30, abs=0.03)

    # 8 constant scores, 7 positive, 1 negative -> smoothed prior (7+1)/(8+2) = 0.80
    calibrator2 = PlattScalingCalibrator()
    scores2 = [5.0] * 8
    targets2 = [1, 1, 1, 1, 1, 1, 1, 0]

    calibrator2.fit(scores2, targets2)
    probs2 = calibrator2.predict_proba([5.0])
    assert probs2[0] == pytest.approx(0.80, abs=0.03)


def test_isotonic_calibrator() -> None:
    calibrator = IsotonicCalibrator()
    assert not calibrator.is_fitted

    with pytest.raises(RuntimeError, match="not fitted"):
        calibrator.predict_proba([0.5])

    # Monotonic fitting on noisy scores
    scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    targets = [0, 1, 0, 1, 1, 0, 1, 1]

    calibrator.fit(scores, targets)
    assert calibrator.is_fitted

    # Predict over a dense grid
    grid = [0.0, 1.5, 3.5, 5.5, 7.5, 10.0]
    probs = calibrator.predict_proba(grid)
    assert len(probs) == len(grid)

    # Invariant: Isotonic calibration must be non-decreasing everywhere
    for i in range(len(probs) - 1):
        assert probs[i] <= probs[i + 1] + 1e-12

    # Clamping in [0, 1]
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_isotonic_calibrator_ties_invariance() -> None:
    # Tie aggregation: multiset with different orderings must produce identical predictions
    c1 = IsotonicCalibrator().fit([1.0, 1.0, 2.0], [0, 1, 1])
    c2 = IsotonicCalibrator().fit([1.0, 1.0, 2.0], [1, 0, 1])

    p1 = c1.predict_proba([1.0, 1.5, 2.0])
    p2 = c2.predict_proba([1.0, 1.5, 2.0])

    assert p1[0] == pytest.approx(0.5)
    assert p2[0] == pytest.approx(0.5)
    assert p1 == p2
