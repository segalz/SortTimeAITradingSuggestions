"""Unit tests for FinnhubNewsProvider, NewsArticle, and NewsSentimentReport."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import httpx

from trading_engine.data.providers.base import ProviderError
from trading_engine.sentiment.finnhub_provider import FinnhubNewsProvider
from trading_engine.sentiment.models import NewsArticle, NewsSentimentReport


def test_news_article_invariants() -> None:
    now_utc = datetime.now(timezone.utc)
    article = NewsArticle(
        id="123",
        headline="Apple reports record earnings",
        summary="Q4 iPhone sales surged 15%.",
        source="Reuters",
        url="https://example.com/aapl",
        timestamp=now_utc,
        symbols=("aapl", "SPY"),
        category="technology",
    )

    assert article.id == "123"
    assert article.headline == "Apple reports record earnings"
    assert article.symbols == ("AAPL", "SPY")
    assert article.category == "technology"

    # Invariant: Empty headline raises ValueError
    with pytest.raises(ValueError, match="headline must not be empty"):
        NewsArticle(
            id="1",
            headline="",
            summary="text",
            source="src",
            url="url",
            timestamp=now_utc,
        )

    # Invariant: Non-UTC timestamp raises ValueError
    naive_dt = datetime(2025, 1, 1, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        NewsArticle(
            id="1",
            headline="Headline",
            summary="text",
            source="src",
            url="url",
            timestamp=naive_dt,
        )


def test_news_article_from_finnhub_dict() -> None:
    data = {
        "id": 789456,
        "headline": "Federal Reserve holds interest rates steady",
        "summary": "The FOMC decided to keep benchmark rate unchanged.",
        "source": "Bloomberg",
        "url": "https://bloomberg.com/fed",
        "datetime": 1741700000,
        "related": "SPY,QQQ",
        "category": "top news",
    }
    article = NewsArticle.from_finnhub_dict(data, symbol="SPY")
    assert article.id == "789456"
    assert article.headline == "Federal Reserve holds interest rates steady"
    assert article.source == "Bloomberg"
    assert "SPY" in article.symbols
    assert "QQQ" in article.symbols
    assert article.timestamp.tzinfo == timezone.utc


def test_news_sentiment_report_validation() -> None:
    now_utc = datetime.now(timezone.utc)
    report = NewsSentimentReport(
        symbol="aapl",
        score=0.75,
        confidence=0.85,
        created_at=now_utc,
        summary="Bullish catalyst on strong earnings",
    )
    assert report.symbol == "AAPL"
    assert report.score == 0.75
    assert report.confidence == 0.85

    # Out-of-range score
    with pytest.raises(ValueError, match="score must be in range"):
        NewsSentimentReport(symbol="AAPL", score=1.5, confidence=0.5, created_at=now_utc)

    # Out-of-range confidence
    with pytest.raises(ValueError, match="confidence must be in range"):
        NewsSentimentReport(symbol="AAPL", score=0.5, confidence=-0.1, created_at=now_utc)


def test_finnhub_provider_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    provider = FinnhubNewsProvider(api_key="")
    now = datetime.now(timezone.utc)
    with pytest.raises(ProviderError, match="Missing Finnhub API key"):
        provider.fetch_company_news("AAPL", now - timedelta(days=2), now)


def test_finnhub_provider_fetch_company_news_and_cache(tmp_path: Path) -> None:
    sample_records = [
        {
            "id": 101,
            "headline": "Tesla expands Gigafactory",
            "summary": "Production capacity increases by 20%.",
            "source": "Reuters",
            "url": "https://example.com/tsla1",
            "datetime": 1741710000,
            "related": "TSLA",
        },
        {
            "id": 102,
            "headline": "Tesla reports record delivery numbers",
            "summary": "Vehicle deliveries exceed expectations.",
            "source": "CNBC",
            "url": "https://example.com/tsla2",
            "datetime": 1741720000,
            "related": "TSLA",
        },
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = sample_records

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = mock_resp

    provider = FinnhubNewsProvider(
        api_key="test_finnhub_token",
        client=mock_client,
        cache_dir=tmp_path / "news_cache",
    )

    now = datetime(2025, 3, 10, tzinfo=timezone.utc)
    start = now - timedelta(days=3)

    # First fetch: calls client.get
    articles = provider.fetch_company_news("TSLA", start=start, end=now, use_cache=True)
    assert len(articles) == 2
    assert articles[0].headline == "Tesla expands Gigafactory"
    assert articles[1].headline == "Tesla reports record delivery numbers"
    assert mock_client.get.call_count == 1

    # Second fetch: uses cache, client.get should NOT be called again
    cached_articles = provider.fetch_company_news("TSLA", start=start, end=now, use_cache=True)
    assert len(cached_articles) == 2
    assert mock_client.get.call_count == 1


def test_finnhub_provider_rate_limit_error(tmp_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 429

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = mock_resp

    provider = FinnhubNewsProvider(
        api_key="test_token",
        client=mock_client,
        cache_dir=tmp_path,
    )

    now = datetime.now(timezone.utc)
    with pytest.raises(ProviderError, match="rate limit exceeded"):
        provider.fetch_company_news("NVDA", now - timedelta(days=1), now, use_cache=False)


def test_finnhub_provider_fetch_market_news(tmp_path: Path) -> None:
    sample_records = [
        {
            "id": 201,
            "headline": "Markets rally on inflation cooling",
            "summary": "CPI came in below forecast.",
            "source": "WSJ",
            "url": "https://example.com/cpi",
            "datetime": 1741750000,
            "category": "general",
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = sample_records

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = mock_resp

    provider = FinnhubNewsProvider(
        api_key="test_token",
        client=mock_client,
        cache_dir=tmp_path,
    )

    articles = provider.fetch_market_news(category="general", use_cache=False)
    assert len(articles) == 1
    assert articles[0].headline == "Markets rally on inflation cooling"
