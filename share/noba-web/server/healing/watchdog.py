# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Component health watchdog.

Each subsystem registers with the watchdog and sends periodic heartbeats.
The watchdog checks all heartbeats and triggers recovery callbacks when
components stall. If 3+ components fail simultaneously, the system
enters degraded mode (metrics + notifications only).

State is in-memory. Lost on restart, which is fine — components
re-register on startup.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("noba")

_DEGRADED_THRESHOLD = 3  # 3+ failed components = degraded mode


class ComponentWatchdog:
    """Thread-safe component health monitor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._components: dict[str, dict] = {}
        self._degraded = False

    def register(self, name: str, *, interval: float, tolerance: int = 3,
                 on_failure: callable = None) -> None:
        """Register a component for health monitoring."""
        with self._lock:
            self._components[name] = {
                "interval": interval,
                "tolerance": tolerance,
                "on_failure": on_failure,
                "last_heartbeat": time.time(),
                "healthy": True,
                "failure_count": 0,
            }

    def heartbeat(self, name: str) -> None:
        """Record a heartbeat from a component."""
        with self._lock:
            comp = self._components.get(name)
            if comp:
                comp["last_heartbeat"] = time.time()
                comp["healthy"] = True
                comp["failure_count"] = 0

    def check_all(self) -> dict[str, bool]:
        """Check all components. Returns {name: healthy}."""
        now = time.time()
        results = {}
        failed_count = 0

        with self._lock:
            for name, comp in self._components.items():
                max_age = comp["interval"] * comp["tolerance"]
                age = now - comp["last_heartbeat"]
                healthy = age <= max_age

                if not healthy and comp["healthy"]:
                    # Transition to unhealthy
                    comp["failure_count"] += 1
                    logger.warning(
                        "Watchdog: %s stalled (%.0fs since last heartbeat, threshold %.0fs)",
                        name, age, max_age,
                    )
                    if comp["on_failure"]:
                        try:
                            comp["on_failure"](name)
                        except Exception as exc:
                            logger.error("Watchdog recovery for %s failed: %s", name, exc)

                comp["healthy"] = healthy
                results[name] = healthy
                if not healthy:
                    failed_count += 1

            self._degraded = failed_count >= _DEGRADED_THRESHOLD
            if self._degraded:
                logger.critical(
                    "Watchdog: DEGRADED MODE — %d/%d components failed",
                    failed_count, len(self._components),
                )

        return results

    def is_degraded(self) -> bool:
        """Check if system is in degraded mode (3+ failures)."""
        with self._lock:
            return self._degraded

    def get_status(self, name: str) -> dict | None:
        """Get status of a specific component."""
        with self._lock:
            comp = self._components.get(name)
            if not comp:
                return None
            return {
                "healthy": comp["healthy"],
                "last_heartbeat": comp["last_heartbeat"],
                "failure_count": comp["failure_count"],
                "interval": comp["interval"],
                "tolerance": comp["tolerance"],
            }

    def get_health_summary(self) -> dict:
        """Get full health summary for all components + degraded state."""
        with self._lock:
            summary = {}
            for name, comp in self._components.items():
                summary[name] = {
                    "healthy": comp["healthy"],
                    "last_heartbeat": comp["last_heartbeat"],
                    "failure_count": comp["failure_count"],
                }
            summary["degraded"] = self._degraded
            return summary

    def list_components(self) -> list[str]:
        """List registered component names."""
        with self._lock:
            return list(self._components.keys())
