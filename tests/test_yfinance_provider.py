"""Tests for YFinanceDataProvider market data fetching and error handling."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from trading_engine.data.models import BarSeries
from trading_engine.data.providers.base import ProviderError
from trading_engine.data.providers.yfinance import YFinanceDataProvider


def _create_mock_df() -> pd.DataFrame:
    """Create a sample OHLCV DataFrame matching yfinance output."""
    dates = pd.date_range(start="2026-03-01 00:00:00+00:00", periods=3, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [150.0, 153.0, 155.0],
            "High": [155.0, 157.0, 159.0],
            "Low": [149.0, 152.0, 154.0],
            "Close": [154.0, 156.0, 158.0],
            "Volume": [1000.0, 1200.0, 1100.0],
        },
        index=dates,
    )


def test_yfinance_fetch_valid_daily() -> None:
    """A valid DataFrame returned by yfinance yields properly populated BarSeries."""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _create_mock_df()
    mock_factory = MagicMock(return_value=mock_ticker)

    provider = YFinanceDataProvider(ticker_factory=mock_factory)
    result = provider.fetch_bars(
        "AAPL",
        "1d",
        start=datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 3, 4, 0, 0, tzinfo=timezone.utc),
    )

    mock_factory.assert_called_once_with("AAPL")
    assert isinstance(result, BarSeries)
    assert len(result) == 3
    assert result.symbol == "AAPL"
    assert result.timeframe == "1d"
    assert result[0].close == 154.0
    assert result[2].high == 159.0


def test_yfinance_unsupported_timeframe() -> None:
    """Unsupported timeframe raises ProviderError."""
    provider = YFinanceDataProvider()
    with pytest.raises(ProviderError, match="Unsupported timeframe"):
        provider.fetch_bars(
            "AAPL",
            "2h",
            start=datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        )


def test_yfinance_naive_datetime_rejected() -> None:
    """Passing naive datetime raises ValueError."""
    provider = YFinanceDataProvider()
    with pytest.raises(ValueError, match="must be timezone-aware"):
        provider.fetch_bars("AAPL", "1d", start=datetime(2026, 3, 1, 0, 0))


def test_yfinance_empty_data_rejected() -> None:
    """Empty DataFrame from yfinance raises ProviderError."""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_factory = MagicMock(return_value=mock_ticker)

    provider = YFinanceDataProvider(ticker_factory=mock_factory)
    with pytest.raises(ProviderError, match="No market data returned"):
        provider.fetch_bars(
            "AAPL",
            "1d",
            start=datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        )


def test_yfinance_history_exception_wrapped() -> None:
    """Underlying ticker exception is wrapped in ProviderError."""
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = RuntimeError("Network timeout")
    mock_factory = MagicMock(return_value=mock_ticker)

    provider = YFinanceDataProvider(ticker_factory=mock_factory)
    with pytest.raises(ProviderError, match="Failed to fetch market data"):
        provider.fetch_bars(
            "AAPL",
            "1d",
            start=datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        )


def test_yfinance_is_timeframe_supported() -> None:
    """Checks supported timeframes return True and others return False."""
    provider = YFinanceDataProvider()
    for tf in ["1m", "5m", "15m", "1h", "1d"]:
        assert provider.is_timeframe_supported(tf) is True
    assert provider.is_timeframe_supported("4h") is False
    assert provider.is_timeframe_supported("1w") is False


def test_yfinance_missing_column() -> None:
    """Missing required column raises ProviderError."""
    df = _create_mock_df().drop(columns=["Volume"])
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    mock_factory = MagicMock(return_value=mock_ticker)

    provider = YFinanceDataProvider(ticker_factory=mock_factory)
    with pytest.raises(ProviderError, match="Missing required column 'Volume'"):
        provider.fetch_bars("AAPL", "1d", start=datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc))


def test_yfinance_drops_nan_bars() -> None:
    """Rows with NaN values are cleanly dropped."""
    df = _create_mock_df()
    df.loc[df.index[1], "Close"] = None  # NaN on second row
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    mock_factory = MagicMock(return_value=mock_ticker)

    provider = YFinanceDataProvider(ticker_factory=mock_factory)
    result = provider.fetch_bars("AAPL", "1d", start=datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc))
    assert len(result) == 2

