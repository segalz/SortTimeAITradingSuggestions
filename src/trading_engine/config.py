"""Configuration and secrets management for the trading engine.

Loads environment variables from ``keys.env`` in the project root, validates
them strictly (paper-trading only), and exposes an immutable
:class:`Settings` object. Secret values must never be logged; use
:func:`redact_secret` when diagnostics need to mention a secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv is a declared project dependency
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - hard dependency, but fail loudly
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / "keys.env"

# --- API base URLs ---------------------------------------------------------
ALPACA_PAPER_BASE = "https://paper-api.alpaca.markets"
ALPACA_DATA_BASE = "https://data.alpaca.markets"
FINNHUB_BASE = "https://finnhub.io/api/v1"

# --- Environment variable names -------------------------------------------
ENV_ALPACA_KEY_ID = "ALPACA_PAPER_KEY_ID"
ENV_ALPACA_SECRET_KEY = "ALPACA_PAPER_SECRET_KEY"
ENV_FINNHUB_API_KEY = "FINNHUB_API_KEY"
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
ENV_XAI_API_KEY = "XAI_API_KEY"
ENV_GEMINI_API_KEY = "GEMINI_API_KEY"

_MIN_ALPACA_SECRET_LEN = 30


class ConfigError(RuntimeError):
    """Raised when configuration is missing, invalid, or unsafe."""


def redact_secret(val: str | None) -> str:
    """Return a safe, non-sensitive description of a secret value.

    Never returns (or logs) any part of the secret beyond its length and the
    fact that it is present.
    """
    if not val:
        return "<empty>"
    return f"len={len(val)} prefix=set"


@dataclass(frozen=True)
class Settings:
    """Immutable application settings holding API credentials."""

    alpaca_key_id: str
    alpaca_secret_key: str
    finnhub_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    xai_api_key: str = ""
    gemini_api_key: str = ""

    @property
    def alpaca_headers(self) -> dict[str, str]:
        """Headers required to authenticate against the Alpaca API."""
        return {
            "APCA-API-KEY-ID": self.alpaca_key_id,
            "APCA-API-SECRET-KEY": self.alpaca_secret_key,
        }

    def __repr__(self) -> str:
        return self.redacted()

    def redacted(self) -> str:
        """Human-readable summary safe to log."""
        return (
            "Settings("
            f"alpaca_key_id={redact_secret(self.alpaca_key_id)}, "
            f"alpaca_secret_key={redact_secret(self.alpaca_secret_key)}, "
            f"finnhub_api_key={redact_secret(self.finnhub_api_key)}, "
            f"openai_api_key={redact_secret(self.openai_api_key)}, "
            f"anthropic_api_key={redact_secret(self.anthropic_api_key)}, "
            f"xai_api_key={redact_secret(self.xai_api_key)}, "
            f"gemini_api_key={redact_secret(self.gemini_api_key)})"
        )


def _validate_alpaca(key_id: str, secret_key: str) -> None:
    if not key_id:
        raise ConfigError("Missing Alpaca key id (paper trading key required).")
    if key_id.startswith("AK"):
        raise ConfigError(
            "Live trading keys (AK...) are forbidden in this project. "
            "Only paper trading keys (PK...) are allowed."
        )
    if not key_id.startswith("PK"):
        raise ConfigError(
            "Alpaca key id must be a paper-trading key starting with 'PK' "
            f"(got key with prefix {key_id[:2]!r})."
        )
    if not secret_key:
        raise ConfigError("Missing Alpaca secret key.")
    if len(secret_key) < _MIN_ALPACA_SECRET_LEN:
        raise ConfigError(
            "Alpaca secret key is too short "
            f"({redact_secret(secret_key)}; expected at least "
            f"{_MIN_ALPACA_SECRET_LEN} characters)."
        )


def load_settings(
    env_file: Path | None = None,
    *,
    require_alpaca: bool = True,
    require_finnhub: bool = False,
) -> Settings:
    """Load settings from the environment (optionally from ``keys.env``).

    Args:
        env_file: Path to the dotenv file. Defaults to ``keys.env`` in the
            project root. Missing file is not an error; environment values
            may already be set.
        require_alpaca: Validate that Alpaca paper credentials are present
            and valid.
        require_finnhub: If True, require a non-empty Finnhub API key.

    Returns:
        A frozen :class:`Settings` instance.

    Raises:
        ConfigError: On missing/invalid configuration.
    """
    if load_dotenv is not None:
        path = Path(env_file) if env_file is not None else DEFAULT_ENV_FILE
        if path.is_file():
            load_dotenv(path, override=False)

    def get(name: str) -> str:
        value = os.environ.get(name) or ""
        return value.strip()

    key_id = get(ENV_ALPACA_KEY_ID) or get("ALPACA_API_KEY_ID") or get("ALPACA_API_KEY")
    secret_key = get(ENV_ALPACA_SECRET_KEY) or get("ALPACA_API_SECRET_KEY")
    finnhub_key = get(ENV_FINNHUB_API_KEY)

    if key_id.startswith("AK"):
        raise ConfigError(
            "Live trading keys (AK...) are forbidden in this project. "
            "Only paper trading keys (PK...) are allowed."
        )

    if require_alpaca:
        _validate_alpaca(key_id, secret_key)

    if require_finnhub and not finnhub_key:
        raise ConfigError("Missing FINNHUB_API_KEY (required).")

    return Settings(
        alpaca_key_id=key_id,
        alpaca_secret_key=secret_key,
        finnhub_api_key=finnhub_key,
        openai_api_key=get(ENV_OPENAI_API_KEY),
        anthropic_api_key=get(ENV_ANTHROPIC_API_KEY),
        xai_api_key=get(ENV_XAI_API_KEY),
        gemini_api_key=get(ENV_GEMINI_API_KEY),
    )
