#!/usr/bin/env python3
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""eye.py — Playwright-based screenshot tool for NOBA development.

Gives Claude "eyes" to see the actual rendered UI. Takes screenshots of
any page/state and saves them for visual inspection.

Usage:
    # Screenshot the login page
    python dev/eye.py login

    # Screenshot the dashboard (auto-logs in)
    python dev/eye.py dashboard

    # Screenshot a specific page/modal
    python dev/eye.py dashboard --open-modal settings

    # Screenshot at mobile viewport
    python dev/eye.py dashboard --mobile

    # Screenshot with custom viewport
    python dev/eye.py dashboard --width 1920 --height 1080

    # Full-page screenshot (scrollable content)
    python dev/eye.py dashboard --full-page

    # Screenshot all major views
    python dev/eye.py all

    # Custom URL path
    python dev/eye.py --path /api/health
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Add server to path for config
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "share" / "noba-web"))

DEFAULT_PORT = int(os.environ.get("NOBA_DEV_PORT", "8099"))
DEFAULT_HOST = "127.0.0.1"
SCREENSHOT_DIR = Path("/tmp/noba-screenshots")
DEFAULT_USER = os.environ.get("NOBA_DEV_USER", "raizen")
DEFAULT_PASS = os.environ.get("NOBA_DEV_PASS", "")


def ensure_server(host: str, port: int, timeout: int = 10) -> bool:
    """Check if server is running, return True if reachable."""
    import httpx
    url = f"http://{host}:{port}/api/health"
    for _ in range(timeout):
        try:
            r = httpx.get(url, timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def login(page, host: str, port: int, username: str, password: str) -> str | None:
    """Login via API and set auth token. Returns token or None."""
    import httpx
    url = f"http://{host}:{port}/api/login"
    try:
        r = httpx.post(url, json={"username": username, "password": password}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            token = data.get("token", "")
            if token:
                # Set token in localStorage so Alpine.js picks it up
                page.evaluate(f"""() => {{
                    localStorage.setItem('noba-token', '{token}');
                    localStorage.setItem('username', '{username}');
                }}""")
                return token
    except Exception as e:
        print(f"  Login failed: {e}", file=sys.stderr)
    return None


def take_screenshot(
    host: str,
    port: int,
    name: str,
    path: str = "/",
    width: int = 1280,
    height: int = 800,
    full_page: bool = False,
    username: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    wait_ms: int = 2000,
    open_modal: str | None = None,
    click_selector: str | None = None,
    no_login: bool = False,
) -> Path:
    """Take a screenshot and return the file path."""
    from playwright.sync_api import sync_playwright

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    base_url = f"http://{host}:{port}"

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        # If using direct token, inject it before the Vue app boots
        if not no_login and not path.startswith("/api/") and username == "__token__" and password:
            # Navigate to a non-app endpoint to get same-origin localStorage access
            page.goto(f"{base_url}/api/health", wait_until="load", timeout=15000)
            page.evaluate(f"""() => {{
                localStorage.setItem('noba-token', '{password}');
                localStorage.setItem('username', 'apikey');
            }}""")
            # Now navigate to the actual target — Vue boots with token already present
            page.goto(f"{base_url}/{path.lstrip('/')}", wait_until="load", timeout=15000)
            page.wait_for_timeout(wait_ms)
        else:
            # Navigate to the target
            page.goto(f"{base_url}{path}", wait_until="load", timeout=15000)

            # If not /api/* path, try to login
            if not no_login and not path.startswith("/api/") and password:
                token = login(page, host, port, username, password)
                if token:
                    # Reload with auth
                    page.goto(f"{base_url}{path}", wait_until="load", timeout=15000)
                    page.wait_for_timeout(wait_ms)

        # Optionally open a modal by clicking a trigger
        if open_modal:
            modal_triggers = {
                "settings": "[x-on\\:click*='activeTab']",  # settings tab
                "automations": "text=Automations",
                "alerts": "text=Alerts",
                "audit": "[x-on\\:click*='showAudit']",
            }
            selector = modal_triggers.get(open_modal, f"text={open_modal}")
            try:
                page.click(selector, timeout=3000)
                page.wait_for_timeout(1000)
            except Exception as e:
                print(f"  Could not click modal trigger '{open_modal}': {e}", file=sys.stderr)

        # Optionally click a custom selector
        if click_selector:
            try:
                page.click(click_selector, timeout=3000)
                page.wait_for_timeout(1000)
            except Exception as e:
                print(f"  Could not click '{click_selector}': {e}", file=sys.stderr)

        # Take the screenshot
        ts = time.strftime("%H%M%S")
        filename = f"noba-{name}-{ts}.png"
        filepath = SCREENSHOT_DIR / filename
        page.screenshot(path=str(filepath), full_page=full_page)

        # Also capture console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        browser.close()

    print(f"  Screenshot saved: {filepath}")
    if console_errors:
        print(f"  Console errors: {len(console_errors)}")
        for err in console_errors[:5]:
            print(f"    - {err}")

    return filepath


def screenshot_all(host: str, port: int, **kwargs):
    """Take screenshots of all major views in a single browser session."""
    from playwright.sync_api import sync_playwright

    views = [
        ("login", "/", False),
        ("dashboard", "/", True),
        ("agents", "/#/agents", True),
        ("monitoring", "/#/monitoring", True),
        ("security", "/#/security", True),
        ("infrastructure", "/#/infrastructure", True),
        ("automations", "/#/automations", True),
    ]

    width = kwargs.get("width", 1280)
    height = kwargs.get("height", 800)
    wait_ms = kwargs.get("wait_ms", 2000)
    username = kwargs.get("username", DEFAULT_USER)
    password = kwargs.get("password", DEFAULT_PASS)
    base_url = f"http://{host}:{port}"

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        logged_in = False

        for name, path, needs_auth in views:
            url = f"{base_url}/{path.lstrip('/')}"

            if needs_auth and not logged_in and password:
                # Login once, reuse session
                page.goto(f"{base_url}/", wait_until="load", timeout=15000)
                token = login(page, host, port, username, password)
                if token:
                    logged_in = True

            page.goto(url, wait_until="load", timeout=15000)
            if needs_auth and logged_in:
                page.wait_for_timeout(wait_ms)

            ts = time.strftime("%H%M%S")
            filename = f"noba-{name}-{ts}.png"
            filepath = SCREENSHOT_DIR / filename
            page.screenshot(path=str(filepath))
            print(f"  Screenshot saved: {filepath}")
            paths.append(filepath)

        browser.close()
    return paths


def main():
    parser = argparse.ArgumentParser(description="NOBA UI Screenshot Tool")
    parser.add_argument("view", nargs="?", default="dashboard",
                       help="View to screenshot: login, dashboard, all, or custom name")
    parser.add_argument("--path", default="/", help="URL path (default: /)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--mobile", action="store_true", help="Use mobile viewport (375x812)")
    parser.add_argument("--full-page", action="store_true", help="Capture full scrollable page")
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument("--wait", type=int, default=2000, help="Wait ms after login (default: 2000)")
    parser.add_argument("--open-modal", help="Click to open a modal: settings, automations, alerts, audit")
    parser.add_argument("--click", help="CSS selector to click before screenshot")
    parser.add_argument("--no-login", action="store_true", help="Skip login")

    args = parser.parse_args()

    if args.mobile:
        args.width, args.height = 375, 812

    if not ensure_server(args.host, args.port, timeout=3):
        print(f"Server not reachable at {args.host}:{args.port}", file=sys.stderr)
        print("Start it with: python dev/harness.sh start", file=sys.stderr)
        sys.exit(1)

    kwargs = dict(
        width=args.width,
        height=args.height,
        full_page=args.full_page,
        username=args.user,
        password="" if args.no_login else args.password,
        wait_ms=args.wait,
        open_modal=args.open_modal,
        click_selector=args.click,
    )

    if args.view == "all":
        screenshot_all(args.host, args.port, **kwargs)
    elif args.view == "login":
        take_screenshot(args.host, args.port, "login", "/", **{**kwargs, "password": ""})
    else:
        take_screenshot(args.host, args.port, args.view, args.path, **kwargs)


if __name__ == "__main__":
    main()
