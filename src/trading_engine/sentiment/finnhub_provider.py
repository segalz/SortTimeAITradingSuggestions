"""Finnhub news provider fetching company and market news with local caching and rate-limiting guards."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import httpx

from trading_engine.config import FINNHUB_BASE, load_settings
from trading_engine.data.providers.base import ProviderError
from trading_engine.sentiment.models import NewsArticle


class FinnhubNewsProvider:
    """News provider interfacing with Finnhub REST API for financial sentiment catalysts."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = FINNHUB_BASE,
        client: httpx.Client | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._cache_dir = cache_dir or Path("data/cache/news")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        if api_key:
            self._api_key = api_key
        else:
            try:
                settings = load_settings()
                self._api_key = settings.finnhub_api_key or os.environ.get("FINNHUB_API_KEY", "")
            except Exception:
                self._api_key = os.environ.get("FINNHUB_API_KEY", "")

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=10.0)

    def _require_api_key(self) -> str:
        if not self._api_key:
            raise ProviderError(
                "Missing Finnhub API key. Configure FINNHUB_API_KEY in keys.env or pass explicitly."
            )
        return self._api_key

    def fetch_company_news(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> tuple[NewsArticle, ...]:
        """Fetch company-specific news articles between start and end dates (UTC)."""
        api_key = self._require_api_key()
        sym = symbol.upper().strip()

        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")
        cache_file = self._cache_dir / f"company_{sym}_{from_str}_{to_str}.json"

        if use_cache and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    raw_records = json.load(f)
                return tuple(NewsArticle.from_finnhub_dict(r, symbol=sym) for r in raw_records)
            except Exception:
                pass  # Fallback to live fetch on corrupt cache

        endpoint = f"{self.base_url}/company-news"
        params = {
            "symbol": sym,
            "from": from_str,
            "to": to_str,
            "token": api_key,
        }

        client = self._get_client()
        try:
            resp = client.get(endpoint, params=params)
            if resp.status_code == 429:
                raise ProviderError("Finnhub rate limit exceeded (HTTP 429)")
            if resp.status_code != 200:
                raise ProviderError(f"Finnhub API error {resp.status_code}: {resp.text}")

            raw_records = resp.json()
            if not isinstance(raw_records, list):
                raw_records = []

            # Save to cache
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(raw_records, f)
            except Exception:
                pass

            articles = [NewsArticle.from_finnhub_dict(r, symbol=sym) for r in raw_records]
            # Sort chronologically by timestamp ascending
            articles.sort(key=lambda a: a.timestamp)
            return tuple(articles)

        except httpx.HTTPError as exc:
            raise ProviderError(f"Finnhub network error: {exc}") from exc

    def fetch_market_news(
        self,
        category: str = "general",
        use_cache: bool = True,
    ) -> tuple[NewsArticle, ...]:
        """Fetch general market news articles from Finnhub."""
        api_key = self._require_api_key()
        cat = category.lower().strip()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_file = self._cache_dir / f"market_{cat}_{today_str}.json"

        if use_cache and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    raw_records = json.load(f)
                return tuple(NewsArticle.from_finnhub_dict(r) for r in raw_records)
            except Exception:
                pass

        endpoint = f"{self.base_url}/news"
        params = {
            "category": cat,
            "token": api_key,
        }

        client = self._get_client()
        try:
            resp = client.get(endpoint, params=params)
            if resp.status_code == 429:
                raise ProviderError("Finnhub rate limit exceeded (HTTP 429)")
            if resp.status_code != 200:
                raise ProviderError(f"Finnhub API error {resp.status_code}: {resp.text}")

            raw_records = resp.json()
            if not isinstance(raw_records, list):
                raw_records = []

            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(raw_records, f)
            except Exception:
                pass

            articles = [NewsArticle.from_finnhub_dict(r) for r in raw_records]
            articles.sort(key=lambda a: a.timestamp)
            return tuple(articles)

        except httpx.HTTPError as exc:
            raise ProviderError(f"Finnhub network error: {exc}") from exc
