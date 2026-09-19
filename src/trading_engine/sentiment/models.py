"""Data models for news articles, catalysts, and sentiment reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Sequence


@dataclass(frozen=True)
class NewsArticle:
    """Immutable representation of a market or company news article."""

    id: str
    headline: str
    summary: str
    source: str
    url: str
    timestamp: datetime
    symbols: tuple[str, ...] = field(default_factory=tuple)
    category: str = "general"

    def __post_init__(self) -> None:
        if not self.headline or not self.headline.strip():
            raise ValueError("headline must not be empty")

        if self.timestamp.tzinfo != timezone.utc:
            raise ValueError("timestamp must be timezone-aware UTC")

        # Normalize symbols to uppercase tuple
        normalized_symbols = tuple(s.upper().strip() for s in self.symbols if s.strip())
        object.__setattr__(self, "symbols", normalized_symbols)

    @classmethod
    def from_finnhub_dict(cls, data: dict, symbol: str | None = None) -> NewsArticle:
        """Construct NewsArticle from Finnhub API response record."""
        raw_id = str(data.get("id") or "")
        headline = data.get("headline", "").strip()
        summary = data.get("summary", "").strip()
        source = data.get("source", "").strip()
        url = data.get("url", "").strip()
        category = data.get("category", "general").strip()

        # Finnhub timestamps are unix epoch seconds
        raw_datetime = data.get("datetime")
        if raw_datetime:
            dt = datetime.fromtimestamp(int(raw_datetime), tz=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        # Generate deterministic id if missing
        if not raw_id:
            raw_id = hashlib.sha256(f"{headline}:{dt.isoformat()}".encode()).hexdigest()[:16]

        syms = []
        if symbol:
            syms.append(symbol)
        related = data.get("related", "")
        if related:
            syms.extend([s.strip() for s in related.split(",") if s.strip()])

        return cls(
            id=raw_id,
            headline=headline or "No headline provided",
            summary=summary,
            source=source or "Finnhub",
            url=url,
            timestamp=dt,
            symbols=tuple(sorted(set(syms))),
            category=category,
        )


@dataclass(frozen=True)
class NewsSentimentReport:
    """Aggregated sentiment score and catalyst analysis for a specific symbol."""

    symbol: str
    score: float  # Normalized in [-1.0, 1.0] (-1 bearish, +1 bullish)
    confidence: float  # In [0.0, 1.0]
    created_at: datetime
    articles: tuple[NewsArticle, ...] = field(default_factory=tuple)
    summary: str = ""

    def __post_init__(self) -> None:
        if not (-1.0 <= self.score <= 1.0):
            raise ValueError(f"score must be in range [-1.0, 1.0], got {self.score}")

        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in range [0.0, 1.0], got {self.confidence}")

        if self.created_at.tzinfo != timezone.utc:
            raise ValueError("created_at must be timezone-aware UTC")

        object.__setattr__(self, "symbol", self.symbol.upper().strip())
