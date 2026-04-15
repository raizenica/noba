#!/usr/bin/env python3
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""trace.py — Debug trace middleware for NOBA server.

Adds request/response logging, performance profiling, and error tracing.
Can be enabled at runtime without modifying app.py.

Usage:
    # Start server with tracing enabled
    NOBA_TRACE=1 python -m uvicorn server.app:app ...

    # Or inject trace middleware into running app
    python -c "from dev.trace import attach; attach()"

    # Analyze trace logs
    python dev/trace.py analyze /tmp/noba-trace.log
    python dev/trace.py slow /tmp/noba-trace.log --threshold 500
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

TRACE_LOG = Path(os.environ.get("NOBA_TRACE_LOG", "/tmp/noba-trace.log"))
TRACE_ENABLED = os.environ.get("NOBA_TRACE", "").lower() in ("1", "true", "yes")

logger = logging.getLogger("noba.trace")


class TraceMiddleware:
    """ASGI middleware that logs request/response details and timing."""

    def __init__(self, app):
        self.app = app
        self._setup_logging()

    def _setup_logging(self):
        handler = logging.FileHandler(str(TRACE_LOG))
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("Trace middleware attached")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope.get("method", "?")
        path = scope.get("path", "?")
        query = scope.get("query_string", b"").decode()
        start = time.time()
        status_code = 0
        response_size = 0
        error_detail = ""

        async def send_wrapper(message):
            nonlocal status_code, response_size
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            elif message["type"] == "http.response.body":
                response_size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            error_detail = f" ERROR={e.__class__.__name__}: {e}"
            # Log full traceback
            logger.error(f"EXCEPTION {method} {path}\n{traceback.format_exc()}")
            raise
        finally:
            elapsed = (time.time() - start) * 1000
            log_line = (
                f"{method} {path}"
                f"{'?' + query if query else ''}"
                f" → {status_code}"
                f" {elapsed:.1f}ms"
                f" {response_size}B"
                f"{error_detail}"
            )
            if status_code >= 500:
                logger.error(log_line)
            elif elapsed > 1000:
                logger.warning(f"SLOW {log_line}")
            else:
                logger.info(log_line)


def attach():
    """Attach trace middleware to the running NOBA app.

    Call this from startup or import it in app.py:
        if os.environ.get("NOBA_TRACE"): from dev.trace import attach; attach()
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "share" / "noba-web"))
    from server.app import app
    app.middleware("http")(TraceMiddleware(app))
    print(f"Trace middleware attached. Logging to {TRACE_LOG}")


# ── Log analysis ─────────────────────────────────────────────────────

def parse_trace_log(log_path: Path) -> list[dict]:
    """Parse trace log into structured entries."""
    entries = []
    pattern = re.compile(
        r"(\d+:\d+:\d+)\s+(\w+)\s+"
        r"(?:SLOW\s+)?"
        r"(\w+)\s+(/\S+)"
        r"\s+→\s+(\d+)"
        r"\s+([\d.]+)ms"
        r"\s+(\d+)B"
        r"(.*)"
    )
    if not log_path.exists():
        return entries

    for line in log_path.read_text().splitlines():
        m = pattern.match(line)
        if m:
            entries.append({
                "time": m.group(1),
                "level": m.group(2),
                "method": m.group(3),
                "path": m.group(4),
                "status": int(m.group(5)),
                "elapsed_ms": float(m.group(6)),
                "size_bytes": int(m.group(7)),
                "error": m.group(8).strip(),
            })
    return entries


def cmd_analyze(log_path: Path):
    """Show summary statistics from trace log."""
    entries = parse_trace_log(log_path)
    if not entries:
        print("No trace entries found")
        return

    print(f"\nTrace log: {log_path} ({len(entries)} requests)\n")

    # Status code distribution
    status_counts = defaultdict(int)
    for e in entries:
        bucket = f"{e['status'] // 100}xx"
        status_counts[bucket] += 1

    print("Status codes:")
    for bucket in sorted(status_counts):
        count = status_counts[bucket]
        color = GREEN if bucket == "2xx" else (YELLOW if bucket == "4xx" else RED)
        print(f"  {color}{bucket}: {count}{NC}")

    # Slowest endpoints
    sorted_by_time = sorted(entries, key=lambda e: e["elapsed_ms"], reverse=True)
    print("\nSlowest requests:")
    for e in sorted_by_time[:10]:
        color = RED if e["elapsed_ms"] > 1000 else YELLOW
        print(f"  {color}{e['elapsed_ms']:>8.1f}ms{NC} {e['method']} {e['path']} → {e['status']}")

    # Most called endpoints
    path_counts = defaultdict(int)
    for e in entries:
        path_counts[f"{e['method']} {e['path']}"] += 1

    print("\nMost called:")
    for path, count in sorted(path_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count:>5}× {path}")

    # Errors
    errors = [e for e in entries if e["status"] >= 500]
    if errors:
        print(f"\n{RED}Errors ({len(errors)}):{NC}")
        for e in errors[:10]:
            print(f"  {e['method']} {e['path']} → {e['status']} {e['error']}")


def cmd_slow(log_path: Path, threshold_ms: float = 500):
    """Show requests slower than threshold."""
    entries = parse_trace_log(log_path)
    slow = [e for e in entries if e["elapsed_ms"] > threshold_ms]

    if not slow:
        print(f"No requests slower than {threshold_ms}ms")
        return

    print(f"\n{len(slow)} requests slower than {threshold_ms}ms:\n")
    for e in sorted(slow, key=lambda e: -e["elapsed_ms"]):
        print(f"  {e['elapsed_ms']:>8.1f}ms {e['method']} {e['path']} → {e['status']}")


# Colors for terminal
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
NC = "\033[0m"


def main():
    parser = argparse.ArgumentParser(description="NOBA Trace Log Analyzer")
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser("analyze", help="Show trace log summary")
    p_analyze.add_argument("log", nargs="?", type=Path, default=TRACE_LOG)

    p_slow = sub.add_parser("slow", help="Show slow requests")
    p_slow.add_argument("log", nargs="?", type=Path, default=TRACE_LOG)
    p_slow.add_argument("--threshold", type=float, default=500, help="Threshold in ms")

    sub.add_parser("clear", help="Clear trace log")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args.log)
    elif args.command == "slow":
        cmd_slow(args.log, args.threshold)
    elif args.command == "clear":
        TRACE_LOG.write_text("")
        print(f"Cleared {TRACE_LOG}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
