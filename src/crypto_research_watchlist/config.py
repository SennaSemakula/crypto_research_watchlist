"""Top-level configuration.

Two layers:
  * AppConfig — yaml-driven (universe, thresholds, sizing). Source of truth
    is config.yml at the repo root.
  * EnvSettings — process-env-driven (secrets, feature flags). Loaded via
    python-dotenv so a local .env works.

The autotrader.config.CryptoConfig is the original Pydantic model written in
the bootstrap session; this module wraps it and adds the env layer + a
factory `load_app_config(path)` callers should prefer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .autotrader.config import CryptoConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class EnvSettings:
    """Runtime knobs sourced from environment variables. None / False by
    default so tests are deterministic."""

    database_url: str = "sqlite:///crypto_research_watchlist.db"
    demo_mode: bool = False

    # Telegram (off by default; opt-in via .env)
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # Paper trading (always on in v1; live trading is a future phase)
    paper_trading: bool = True

    # Third-party data API keys (all optional; modules degrade gracefully).
    coingecko_api_key: str | None = None
    cryptopanic_api_key: str | None = None

    @classmethod
    def from_env(cls) -> EnvSettings:
        # Best-effort .env load. Silent if python-dotenv not installed.
        try:
            from dotenv import load_dotenv  # type: ignore[import-not-found]
            load_dotenv(REPO_ROOT / ".env", override=False)
        except Exception:
            pass
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///crypto_research_watchlist.db"),
            demo_mode=_truthy(os.getenv("DEMO_MODE")),
            telegram_enabled=_truthy(os.getenv("TELEGRAM_ENABLED")),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            paper_trading=_truthy(os.getenv("PAPER_TRADING", "1")),
            coingecko_api_key=os.getenv("COINGECKO_API_KEY") or None,
            cryptopanic_api_key=os.getenv("CRYPTOPANIC_API_KEY") or None,
        )


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# AppConfig — convenience wrapper around CryptoConfig with reports + portfolio
# fields surfaced from config.yml. Keeps callers from reaching into the YAML
# directly.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReportsConfig:
    reports_dir: str = "reports"
    save_markdown: bool = True
    top_n_terminal: int = 10


@dataclass(slots=True)
class PortfolioConfig:
    total_capital_usd: float = 5000.0
    cash_available_usd: float = 5000.0
    currency: str = "USD"
    mode: str = "aggressive"
    target_total_positions: int = 1
    min_suggested_weight: float = 0.05


@dataclass(slots=True)
class NotificationsConfig:
    telegram: bool = False
    terminal: bool = True


@dataclass(slots=True)
class AppConfig:
    crypto: CryptoConfig
    reports: ReportsConfig = field(default_factory=ReportsConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)

    # Convenience access used by older paths.
    @property
    def universe(self):  # type: ignore[no-untyped-def]
        return self.crypto.universe

    @property
    def aggressive(self):  # type: ignore[no-untyped-def]
        return self.crypto.aggressive

    @property
    def passive(self):  # type: ignore[no-untyped-def]
        return self.crypto.passive

    @property
    def learning_summary(self):  # type: ignore[no-untyped-def]
        return self.crypto.learning_summary

    @property
    def risk_limits(self):  # type: ignore[no-untyped-def]
        return self.crypto.risk_limits


def load_app_config(path: Path | str | None = None) -> AppConfig:
    """Load AppConfig from config.yml at the repo root (or explicit path)."""
    if path is None:
        path = REPO_ROOT / "config.yml"
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}

    crypto = load_config(path)
    reports = ReportsConfig(**(raw.get("reports") or {}))
    portfolio = PortfolioConfig(**(raw.get("portfolio") or {}))
    notifications = NotificationsConfig(**(raw.get("notifications") or {}))
    return AppConfig(
        crypto=crypto,
        reports=reports,
        portfolio=portfolio,
        notifications=notifications,
    )
