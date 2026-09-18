from abc import ABC, abstractmethod
from datetime import datetime

from trading_engine.data.models import BarSeries


class ProviderError(RuntimeError):
    pass


class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime | None = None) -> BarSeries:
        """Fetch historical bars for a symbol and timeframe between start and end (UTC)."""
        ...

    @abstractmethod
    def is_timeframe_supported(self, timeframe: str) -> bool:
        """Check whether the provider supports the requested timeframe."""
        ...
