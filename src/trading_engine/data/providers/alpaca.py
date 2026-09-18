"""Alpaca Market Data provider for historical stock bars."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from trading_engine.config import ALPACA_DATA_BASE, Settings
from trading_engine.data.models import BarSeries, Candle
from trading_engine.data.providers.base import MarketDataProvider, ProviderError


def _ensure_utc(dt: datetime, param_name: str) -> datetime:
    """Ensure datetime is timezone-aware and converted to UTC."""
    if dt.tzinfo is None:
        raise ValueError(f"{param_name} datetime must be timezone-aware (UTC).")
    return dt.astimezone(timezone.utc)


class AlpacaDataProvider(MarketDataProvider):
    """Fetch historical stock bars from the Alpaca Market Data API (v2)."""

    SUPPORTED_TIMEFRAMES = {
        "1m": "1Min",
        "5m": "5Min",
        "15m": "15Min",
        "1h": "1Hour",
        "1d": "1Day",
    }

    def __init__(
        self,
        settings: Settings,
        timeout_s: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._timeout_s = timeout_s
        self._client = client

    # --- MarketDataProvider interface -------------------------------------

    def is_timeframe_supported(self, timeframe: str) -> bool:
        """Check whether the provider supports the requested timeframe."""
        return timeframe in self.SUPPORTED_TIMEFRAMES

    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
    ) -> BarSeries:
        """Fetch historical bars for a symbol and timeframe between start and end (UTC)."""
        mapped_tf = self.SUPPORTED_TIMEFRAMES.get(timeframe)
        if mapped_tf is None:
            supported = ", ".join(sorted(self.SUPPORTED_TIMEFRAMES))
            raise ProviderError(
                f"Unsupported timeframe {timeframe!r} for AlpacaDataProvider "
                f"(supported: {supported})."
            )

        start_utc = _ensure_utc(start, "start")
        end_utc = _ensure_utc(end, "end") if end is not None else None

        endpoint = f"{ALPACA_DATA_BASE}/v2/stocks/{symbol.upper()}/bars"
        headers = self._settings.alpaca_headers

        candles: list[Candle] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {
                "timeframe": mapped_tf,
                "start": start_utc.isoformat(),
                "limit": 10000,
                "adjustment": "split",
                "feed": "iex",
            }
            if end_utc is not None:
                params["end"] = end_utc.isoformat()
            if page_token is not None:
                params["page_token"] = page_token

            try:
                response = self._request(endpoint, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                raise ProviderError(
                    f"Alpaca API returned HTTP error for {symbol.upper()} "
                    f"{timeframe}: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Alpaca API request failed for {symbol.upper()} "
                    f"{timeframe}: {exc}"
                ) from exc
            except Exception as exc:
                raise ProviderError(
                    f"Failed to parse response from Alpaca API for {symbol.upper()} "
                    f"{timeframe}: {exc}"
                ) from exc

            if not isinstance(payload, dict):
                raise ProviderError(
                    f"Unexpected response format from Alpaca API for {symbol.upper()} "
                    f"{timeframe}: expected dict, got {type(payload).__name__}"
                )

            bars = payload.get("bars") or []
            if not isinstance(bars, list):
                raise ProviderError(
                    f"Unexpected bars field format from Alpaca API for {symbol.upper()} "
                    f"{timeframe}: expected list, got {type(bars).__name__}"
                )

            for bar in bars:
                candles.append(self._parse_bar(bar))

            page_token = payload.get("next_page_token")
            if page_token is None:
                break

        return BarSeries(symbol=symbol, timeframe=timeframe, bars=tuple(candles))

    # --- internals ---------------------------------------------------------

    def _request(self, endpoint: str, params: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            return self._client.get(endpoint, params=params, headers=headers)
        with httpx.Client(timeout=self._timeout_s) as client:
            return client.get(endpoint, params=params, headers=headers)

    @staticmethod
    def _parse_bar(bar: dict[str, Any]) -> Candle:
        """Parse a single Alpaca bar dict into a :class:`Candle`."""
        if not isinstance(bar, dict):
            raise ProviderError(f"Expected bar dict, got {type(bar).__name__}")

        try:
            raw_t = bar.get("t")
            if not raw_t:
                raise ProviderError(f"Invalid bar timestamp: {raw_t!r}")
            timestamp = datetime.fromisoformat(str(raw_t))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"Invalid bar timestamp: {bar.get('t')!r}") from exc

        try:
            vwap_raw = bar.get("vw")
            return Candle(
                timestamp=timestamp,
                open=float(bar["o"]),
                high=float(bar["h"]),
                low=float(bar["l"]),
                close=float(bar["c"]),
                volume=float(bar["v"]),
                vwap=float(vwap_raw) if vwap_raw is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"Invalid or missing bar price/volume field: {exc}") from exc
