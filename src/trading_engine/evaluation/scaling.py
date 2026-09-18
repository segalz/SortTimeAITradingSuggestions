"""Window scaler preventing future lookahead leakage in features."""

from __future__ import annotations

import numpy as np

from trading_engine.data.models import BarSeries


class WindowScaler:
    """Scales series features strictly calibrated on historical window with no future visibility."""

    def __init__(self) -> None:
        self.mean: float | None = None
        self.std: float | None = None

    def fit(self, series: BarSeries) -> "WindowScaler":
        """Fit mean and std strictly on historical calibration window."""
        if len(series) == 0:
            raise ValueError("Cannot fit scaler on empty BarSeries.")
        closes = [b.close for b in series]
        self.mean = float(np.mean(closes))
        std = float(np.std(closes))
        self.std = std if std > 1e-8 else 1.0
        return self

    def transform(self, series: BarSeries) -> list[float]:
        """Apply calibration parameters to any series."""
        if self.mean is None or self.std is None:
            raise RuntimeError("Scaler must be fit before calling transform.")
        return [(b.close - self.mean) / self.std for b in series]

    def fit_transform(self, series: BarSeries) -> list[float]:
        """Fit on historical series and return transformed series."""
        return self.fit(series).transform(series)
