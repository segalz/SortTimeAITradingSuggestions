"""Tests for AlpacaDataProvider single-page and multi-page bar fetching and error handling."""

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from trading_engine.config import Settings
from trading_engine.data.models import BarSeries
from trading_engine.data.providers.alpaca import AlpacaDataProvider
from trading_engine.data.providers.base import ProviderError


class _DummyResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://mock.alpaca.markets")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("HTTP Error", request=request, response=response)

    def json(self) -> Any:
        return self._payload


class _MultiResponseClient:
    """Minimal stand-in for httpx.Client returning sequential responses."""

    def __init__(self, responses: list[_DummyResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> _DummyResponse:
        self.calls.append({"endpoint": endpoint, "params": params, "headers": headers})
        if not self._responses:
            raise RuntimeError("No more responses queued in _MultiResponseClient")
        return self._responses.pop(0)


def _make_settings() -> Settings:
    return Settings(
        alpaca_key_id="PKTEST012345678901234567890123456789",
        alpaca_secret_key="SKTEST012345678901234567890123456789",
    )


def test_alpaca_fetch_single_page() -> None:
    """A single-page response with next_page_token=None yields one Candle."""
    payload = {
        "bars": [
            {
                "t": "2026-03-01T14:30:00Z",
                "o": 150.0,
                "h": 155.0,
                "l": 149.0,
                "c": 154.0,
                "v": 1000.0,
                "vw": 152.5,
            }
        ],
        "next_page_token": None,
    }
    dummy_client = _MultiResponseClient([_DummyResponse(payload)])
    provider = AlpacaDataProvider(settings=_make_settings(), client=dummy_client)  # type: ignore[arg-type]

    result = provider.fetch_bars(
        "AAPL",
        "1h",
        start=datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
    )

    assert isinstance(result, BarSeries)
    assert len(result) == 1
    assert result[0].close == 154.0
    assert len(dummy_client.calls) == 1


def test_alpaca_fetch_pagination() -> None:
    """AlpacaDataProvider follows next_page_token across multiple requests."""
    page_1 = {
        "bars": [
            {
                "t": "2026-03-01T14:30:00Z",
                "o": 150.0,
                "h": 155.0,
                "l": 149.0,
                "c": 154.0,
                "v": 1000.0,
            }
        ],
        "next_page_token": "page2_token",
    }
    page_2 = {
        "bars": [
            {
                "t": "2026-03-01T15:30:00Z",
                "o": 154.0,
                "h": 158.0,
                "l": 153.0,
                "c": 157.0,
                "v": 1200.0,
            }
        ],
        "next_page_token": None,
    }
    client = _MultiResponseClient([_DummyResponse(page_1), _DummyResponse(page_2)])
    provider = AlpacaDataProvider(settings=_make_settings(), client=client)  # type: ignore[arg-type]

    result = provider.fetch_bars(
        "AAPL",
        "1h",
        start=datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
    )

    assert len(result) == 2
    assert result[0].close == 154.0
    assert result[1].close == 157.0
    assert len(client.calls) == 2
    assert "page_token" not in client.calls[0]["params"]
    assert client.calls[1]["params"]["page_token"] == "page2_token"


def test_alpaca_unsupported_timeframe() -> None:
    """Requesting an unsupported timeframe raises ProviderError."""
    provider = AlpacaDataProvider(settings=_make_settings())
    with pytest.raises(ProviderError, match="Unsupported timeframe '2h'"):
        provider.fetch_bars(
            "AAPL",
            "2h",
            start=datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
        )


def test_alpaca_naive_datetime_rejected() -> None:
    """Passing naive datetime to fetch_bars raises ValueError."""
    provider = AlpacaDataProvider(settings=_make_settings())
    with pytest.raises(ValueError, match="start datetime must be timezone-aware"):
        provider.fetch_bars("AAPL", "1h", start=datetime(2026, 3, 1, 14, 0))


def test_alpaca_http_error() -> None:
    """HTTP 4xx or 5xx raises ProviderError."""
    client = _MultiResponseClient([_DummyResponse({"message": "Forbidden"}, status_code=403)])
    provider = AlpacaDataProvider(settings=_make_settings(), client=client)  # type: ignore[arg-type]

    with pytest.raises(ProviderError, match="Alpaca API returned HTTP error"):
        provider.fetch_bars(
            "AAPL",
            "1h",
            start=datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
        )


def test_alpaca_malformed_bar_payload() -> None:
    """Malformed bar entries missing fields or with invalid values raise ProviderError."""
    payload = {
        "bars": [{"t": "2026-03-01T14:30:00Z", "o": "invalid", "h": 155.0, "l": 149.0, "c": 150.0, "v": 100}],
        "next_page_token": None,
    }
    client = _MultiResponseClient([_DummyResponse(payload)])
    provider = AlpacaDataProvider(settings=_make_settings(), client=client)  # type: ignore[arg-type]

    with pytest.raises(ProviderError, match="Invalid or missing bar price/volume field"):
        provider.fetch_bars(
            "AAPL",
            "1h",
            start=datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
        )


def test_alpaca_is_timeframe_supported() -> None:
    """Supported timeframes return True, others return False."""
    provider = AlpacaDataProvider(settings=_make_settings())
    for tf in ["1m", "5m", "15m", "1h", "1d"]:
        assert provider.is_timeframe_supported(tf) is True
    assert provider.is_timeframe_supported("4h") is False
    assert provider.is_timeframe_supported("1w") is False
