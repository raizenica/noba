# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Heal event correlation: immediate-on-first with absorption window."""
from __future__ import annotations

import threading
import time

from .models import HealEvent, HealRequest


class HealCorrelator:
    """Correlate heal events by target.

    First event for a target emits a HealRequest immediately.
    Subsequent events for the same target within the absorption window
    are absorbed (return None).
    """

    def __init__(self, absorption_window: float = 60.0) -> None:
        self._window = absorption_window
        self._lock = threading.Lock()
        self._active: dict[str, float] = {}  # correlation_key -> expiry timestamp

    def correlate(self, event: HealEvent) -> HealRequest | None:
        key = self._make_key(event)
        now = time.time()

        with self._lock:
            # Purge expired entries
            expired = [k for k, exp in self._active.items() if now >= exp]
            for k in expired:
                del self._active[k]

            # Check if absorbed
            if key in self._active:
                return None

            # First event — register and emit
            self._active[key] = now + self._window

        return HealRequest(
            correlation_key=key,
            events=[event],
            primary_target=event.target,
            severity=event.severity,
            created_at=now,
        )

    @staticmethod
    def _make_key(event: HealEvent) -> str:
        return f"{event.target}:{event.rule_id}"
