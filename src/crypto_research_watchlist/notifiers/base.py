"""Notifier base contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NotificationOutcome:
    name: str
    status: str  # sent / disabled / failed / partial
    error: str | None = None
