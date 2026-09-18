"""Yahoo Finance market data provider based on ``yfinance``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from trading_engine.data.models import BarSeries, Candle
from trading_engine.data.providers.base import MarketDataProvider, ProviderError


class YFinanceDataProvider(MarketDataProvider):
    """Fetch OHLCV bars from Yahoo Finance via the ``yfinance`` package."""

    SUPPORTED_TIMEFRAMES = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d"}

    def __init__(self, ticker_factory: Any | None = None) -> None:
        self._ticker_factory = ticker_factory or yf.Ticker

    def is_timeframe_supported(self, timeframe: str) -> bool:
        return timeframe in self.SUPPORTED_TIMEFRAMES

    def fetch_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime | None = None) -> BarSeries:
        start_utc = self._to_utc(start, "start")
        end_utc = self._to_utc(end, "end") if end is not None else None

        mapped_tf = self.SUPPORTED_TIMEFRAMES.get(timeframe)
        if mapped_tf is None:
            raise ProviderError(f"Unsupported timeframe: {timeframe}")

        try:
            ticker = self._ticker_factory(symbol.upper())
        except Exception as e:
            raise ProviderError(f"Failed to create ticker for {symbol}: {e}") from e

        try:
            df = ticker.history(
                interval=mapped_tf,
                start=start_utc,
                end=end_utc,
                auto_adjust=True,
            )
        except Exception as e:
            raise ProviderError(f"Failed to fetch market data for {symbol}: {e}") from e

        if df is None or df.empty:
            raise ProviderError(f"No market data returned for {symbol} ({timeframe})")

        # Drop any rows with NaN in OHLCV
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                raise ProviderError(f"Missing required column {col!r} in market data for {symbol}")

        df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        if df.empty:
            raise ProviderError(f"No valid OHLCV market data returned for {symbol} ({timeframe})")

        candles: list[Candle] = []
        for ts, row in df.iterrows():
            try:
                timestamp = self._index_to_utc_datetime(ts)
                candles.append(
                    Candle(
                        timestamp=timestamp,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]),
                    )
                )
            except Exception as e:
                raise ProviderError(f"Malformed market data bar for {symbol} ({timeframe}): {e}") from e

        return BarSeries(symbol=symbol, timeframe=timeframe, bars=tuple(candles))

    @staticmethod
    def _to_utc(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware, got naive datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _index_to_utc_datetime(ts: Any) -> datetime:
        """Convert a DataFrame index entry into a timezone-aware UTC datetime."""
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        elif not isinstance(ts, datetime):
            ts = pd.Timestamp(ts).to_pydatetime()
        if ts.tzinfo is None or ts.utcoffset() is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
