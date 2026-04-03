# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Site connectivity monitor.

Tracks which sites are 'connectivity-suspect' — meaning the server
cannot reach agents at that site. When a site is suspect, ALL healing
for targets at that site is suppressed to prevent false restarts.

State is in-memory only (like correlation state). Lost on restart,
which is acceptable — the next agent heartbeat cycle re-establishes
reachability within seconds.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("noba")


class ConnectivityMonitor:
    """Thread-safe site connectivity state tracker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._suspect: dict[str, dict] = {}  # site -> {reason, since}

    def mark_suspect(self, site: str, *, reason: str) -> None:
        """Mark a site as connectivity-suspect."""
        with self._lock:
            self._suspect[site] = {"reason": reason, "since": time.time()}
        logger.warning("Site %s marked connectivity-suspect: %s", site, reason)

    def clear_suspect(self, site: str) -> None:
        """Clear connectivity-suspect state for a site."""
        with self._lock:
            if site in self._suspect:
                del self._suspect[site]
                logger.info("Site %s connectivity restored", site)

    def is_suspect(self, site: str) -> bool:
        """Check if a site is currently connectivity-suspect."""
        with self._lock:
            return site in self._suspect

    def should_suppress_healing(self, site: str) -> bool:
        """Check if healing should be suppressed for a site."""
        return self.is_suspect(site)

    def get_suspect_sites(self) -> list[str]:
        """List all currently suspect sites."""
        with self._lock:
            return list(self._suspect.keys())

    def get_suspect_info(self, site: str) -> dict | None:
        """Get details about why a site is suspect."""
        with self._lock:
            return self._suspect.get(site)

    def on_agent_reconnect(self, site: str) -> None:
        """Called when an agent at a suspect site reconnects."""
        self.clear_suspect(site)
