"""Unit tests for trading_engine.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_engine.config import (
    ALPACA_DATA_BASE,
    ALPACA_PAPER_BASE,
    FINNHUB_BASE,
    ConfigError,
    Settings,
    load_settings,
    redact_secret,
)

VALID_KEY_ID = "PKTEST1234567890"
VALID_SECRET = "x" * 40
FINNHUB_KEY = "finnhub-key-1234567890"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all config-related env vars before each test."""
    for name in (
        "ALPACA_PAPER_KEY_ID",
        "ALPACA_PAPER_SECRET_KEY",
        "FINNHUB_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def write_env(tmp_path: Path, lines: list[str]) -> Path:
    env_file = tmp_path / "keys.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


class TestRedactSecret:
    def test_empty_string(self) -> None:
        assert redact_secret("") == "<empty>"

    def test_short_string(self) -> None:
        result = redact_secret("abc")
        assert result == "len=3 prefix=set"
        assert "abc" not in result

    def test_normal_string(self) -> None:
        secret = VALID_SECRET
        result = redact_secret(secret)
        assert result == f"len={len(secret)} prefix=set"
        assert secret not in result


from dataclasses import FrozenInstanceError

class TestSettings:
    def test_creation_and_headers(self) -> None:
        settings = Settings(alpaca_key_id=VALID_KEY_ID, alpaca_secret_key=VALID_SECRET)
        assert settings.alpaca_key_id == VALID_KEY_ID
        assert settings.finnhub_api_key == ""
        assert settings.alpaca_headers == {
            "APCA-API-KEY-ID": VALID_KEY_ID,
            "APCA-API-SECRET-KEY": VALID_SECRET,
        }

    def test_frozen(self) -> None:
        settings = Settings(alpaca_key_id=VALID_KEY_ID, alpaca_secret_key=VALID_SECRET)
        with pytest.raises(FrozenInstanceError):
            settings.alpaca_key_id = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        settings = Settings(alpaca_key_id="PK1", alpaca_secret_key="s")
        assert settings.openai_api_key == ""
        assert settings.anthropic_api_key == ""
        assert settings.xai_api_key == ""
        assert settings.gemini_api_key == ""

    def test_repr_and_redacted_never_leak_secrets(self) -> None:
        secret = "super_secret_secret_123456789012345"
        settings = Settings(
            alpaca_key_id=VALID_KEY_ID,
            alpaca_secret_key=secret,
            finnhub_api_key="finnhub_secret_val",
            openai_api_key="sk-secret-openai",
        )
        repr_str = repr(settings)
        redacted_str = settings.redacted()
        assert repr_str == redacted_str
        assert secret not in repr_str
        assert "finnhub_secret_val" not in repr_str
        assert "sk-secret-openai" not in repr_str



class TestConstants:
    def test_base_urls(self) -> None:
        assert ALPACA_PAPER_BASE == "https://paper-api.alpaca.markets"
        assert ALPACA_DATA_BASE == "https://data.alpaca.markets"
        assert FINNHUB_BASE == "https://finnhub.io/api/v1"

class TestLoadSettings:
    def test_success_from_env_file(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [
                f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}",
                f"ALPACA_PAPER_SECRET_KEY={VALID_SECRET}",
                f"FINNHUB_API_KEY={FINNHUB_KEY}",
                "OPENAI_API_KEY=sk-openai",
            ],
        )
        settings = load_settings(env_file)
        assert settings.alpaca_key_id == VALID_KEY_ID
        assert settings.alpaca_secret_key == VALID_SECRET
        assert settings.finnhub_api_key == FINNHUB_KEY
        assert settings.openai_api_key == "sk-openai"

    def test_reject_live_ak_key(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [
                "ALPACA_PAPER_KEY_ID=AKLIVEKEY123",
                f"ALPACA_PAPER_SECRET_KEY={VALID_SECRET}",
            ],
        )
        with pytest.raises(ConfigError, match="Live trading"):
            load_settings(env_file)

    def test_reject_bad_prefix_key(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            ["ALPACA_PAPER_KEY_ID=XXBAD", f"ALPACA_PAPER_SECRET_KEY={VALID_SECRET}"],
        )
        with pytest.raises(ConfigError, match="PK"):
            load_settings(env_file)

    def test_reject_missing_secret(self, tmp_path: Path) -> None:
        env_file = write_env(tmp_path, [f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}"])
        with pytest.raises(ConfigError, match="[Mm]issing"):
            load_settings(env_file)

    def test_reject_short_secret(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}", "ALPACA_PAPER_SECRET_KEY=short"],
        )
        with pytest.raises(ConfigError, match="too short"):
            load_settings(env_file)

    def test_secret_length_29_fails(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}", f"ALPACA_PAPER_SECRET_KEY={'a' * 29}"],
        )
        with pytest.raises(ConfigError, match="too short"):
            load_settings(env_file)

    def test_secret_length_30_passes(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}", f"ALPACA_PAPER_SECRET_KEY={'a' * 30}"],
        )
        settings = load_settings(env_file)
        assert len(settings.alpaca_secret_key) == 30

    def test_reject_ak_even_when_alpaca_not_required(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            ["ALPACA_PAPER_KEY_ID=AKLIVEKEY123"],
        )
        with pytest.raises(ConfigError, match="Live trading"):
            load_settings(env_file, require_alpaca=False)

    def test_missing_key_id(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path, [f"ALPACA_PAPER_SECRET_KEY={VALID_SECRET}"]
        )
        with pytest.raises(ConfigError, match="[Mm]issing"):
            load_settings(env_file)

    def test_finnhub_optional_by_default(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [
                f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}",
                f"ALPACA_PAPER_SECRET_KEY={VALID_SECRET}",
            ],
        )
        settings = load_settings(env_file)
        assert settings.finnhub_api_key == ""

    def test_finnhub_required_missing(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [
                f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}",
                f"ALPACA_PAPER_SECRET_KEY={VALID_SECRET}",
            ],
        )
        with pytest.raises(ConfigError, match="FINNHUB_API_KEY"):
            load_settings(env_file, require_finnhub=True)

    def test_finnhub_required_present(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [
                f"ALPACA_PAPER_KEY_ID={VALID_KEY_ID}",
                f"ALPACA_PAPER_SECRET_KEY={VALID_SECRET}",
                f"FINNHUB_API_KEY={FINNHUB_KEY}",
            ],
        )
        settings = load_settings(env_file, require_finnhub=True)
        assert settings.finnhub_api_key == FINNHUB_KEY

    def test_alpaca_not_required(self, tmp_path: Path) -> None:
        env_file = write_env(tmp_path, [])
        settings = load_settings(env_file, require_alpaca=False)
        assert settings.alpaca_key_id == ""
        assert settings.alpaca_secret_key == ""

    def test_alpaca_aliases(self, tmp_path: Path) -> None:
        env_file = write_env(
            tmp_path,
            [
                f"ALPACA_API_KEY_ID={VALID_KEY_ID}",
                f"ALPACA_API_SECRET_KEY={VALID_SECRET}",
            ],
        )
        settings = load_settings(env_file)
        assert settings.alpaca_key_id == VALID_KEY_ID
        assert settings.alpaca_secret_key == VALID_SECRET

