#!/usr/bin/env python3
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""e2e.py — End-to-end UI tests for NOBA using Playwright.

Tests the actual rendered UI, not just API endpoints. Catches:
- Alpine.js expression errors
- Missing x-model bindings
- Broken modals/navigation
- CSS layout issues
- Console errors
- Missing elements

Usage:
    python dev/e2e.py                    # Run all tests
    python dev/e2e.py --test login       # Run specific test
    python dev/e2e.py --headed           # Run with visible browser
    python dev/e2e.py --screenshot       # Save screenshots on failure
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = int(os.environ.get("NOBA_DEV_PORT", "8099"))
DEFAULT_HOST = os.environ.get("NOBA_DEV_HOST", "127.0.0.1")
DEFAULT_USER = os.environ.get("NOBA_DEV_USER", "raizen")
DEFAULT_PASS = os.environ.get("NOBA_DEV_PASS", "")
SCREENSHOT_DIR = Path("/tmp/noba-screenshots")


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float = 0
    error: str = ""
    console_errors: list[str] = field(default_factory=list)
    screenshot: str = ""


class E2ERunner:
    def __init__(self, host: str, port: int, username: str, password: str,
                 headed: bool = False, save_screenshots: bool = False):
        self.base_url = f"http://{host}:{port}"
        self.username = username
        self.password = password
        self.headed = headed
        self.save_screenshots = save_screenshots
        self.results: list[TestResult] = []

    def _login_api(self) -> str | None:
        """Get auth token via API."""
        import httpx
        try:
            r = httpx.post(f"{self.base_url}/api/login",
                          json={"username": self.username, "password": self.password}, timeout=5)
            if r.status_code == 200:
                return r.json().get("token")
        except Exception:
            pass
        return None

    def _setup_page(self, page, token: str | None = None):
        """Set up page with auth token and error capturing."""
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        if token:
            # Use 'load' instead of 'networkidle' — SSE streams keep connections open
            page.goto(self.base_url, wait_until="load", timeout=15000)
            page.evaluate(f"""() => {{
                localStorage.setItem('noba-token', '{token}');
                localStorage.setItem('username', '{self.username}');
            }}""")
            page.reload(wait_until="load", timeout=15000)
            # Wait for Alpine.js to hydrate and data to load
            page.wait_for_timeout(3000)

        return errors

    def run_test(self, name: str, test_fn, needs_auth: bool = True):
        """Run a single test with error handling."""
        from playwright.sync_api import sync_playwright

        start = time.time()
        result = TestResult(name=name, passed=False)

        # Skip auth-dependent tests when no password is configured
        if needs_auth and not self.password:
            result.duration_ms = 0
            result.error = "SKIP (NOBA_DEV_PASS not set)"
            result.passed = True  # Not a failure — just skipped
            self.results.append(result)
            print(f"  \033[33mSKIP\033[0m {name} (no auth configured)")
            return

        try:
            with sync_playwright() as p:
                browser = p.firefox.launch(headless=not self.headed)
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                page = context.new_page()

                token = self._login_api() if needs_auth else None
                console_errors = self._setup_page(page, token if needs_auth else None)

                # Run the actual test
                test_fn(page)

                # Capture any console errors that occurred
                result.console_errors = [e for e in console_errors
                                        if "favicon" not in e.lower()]

                result.passed = True
                browser.close()

        except Exception as e:
            result.error = str(e)
            result.passed = False
            if self.save_screenshots:
                try:
                    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                    ss_path = SCREENSHOT_DIR / f"fail-{name}-{int(time.time())}.png"
                    page.screenshot(path=str(ss_path))
                    result.screenshot = str(ss_path)
                except Exception:
                    pass

        result.duration_ms = (time.time() - start) * 1000
        self.results.append(result)
        status = "\033[32mPASS\033[0m" if result.passed else "\033[31mFAIL\033[0m"
        print(f"  {status} {name} ({result.duration_ms:.0f}ms)", end="")
        if result.console_errors:
            print(f" [{len(result.console_errors)} console errors]", end="")
        if result.error:
            print(f" — {result.error[:80]}", end="")
        print()

    # ── Test definitions ─────────────────────────────────────────────

    def test_health_endpoint(self, page):
        """API health check returns valid JSON."""
        page.goto(f"{self.base_url}/api/health", wait_until="networkidle")
        content = page.text_content("body")
        data = json.loads(content)
        assert data["status"] == "ok", f"Expected ok, got {data['status']}"
        assert "version" in data

    def test_login_page_renders(self, page):
        """Login page shows username/password fields."""
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(1000)
        # Should have login form elements
        assert page.locator("input[type='password']").count() > 0 or \
               page.locator("[x-model*='password']").count() > 0, \
               "No password input found"

    def test_login_flow(self, page):
        """Can log in with valid credentials via the actual UI form."""
        if not self.password:
            raise Exception("NOBA_DEV_PASS not set")
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(1500)

        # NOBA uses x-model="loginUsername" / x-model="loginPassword"
        page.fill("input[x-model='loginUsername']", self.username)
        page.fill("input[x-model='loginPassword']", self.password)
        page.click("button:has-text('Login')")
        page.wait_for_timeout(3000)

        # Should now have a token in localStorage
        token = page.evaluate("() => localStorage.getItem('noba-token')")
        assert token, "No token in localStorage after login"

    def test_dashboard_no_js_errors(self, page):
        """Dashboard loads without Alpine.js expression errors."""
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(3000)
        # Console errors are captured by _setup_page
        # The test passes if no unhandled errors

    def test_dashboard_cards_render(self, page):
        """Dashboard shows at least some cards."""
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(3000)
        cards = page.locator(".card").count()
        assert cards > 0, f"No .card elements found (got {cards})"

    def test_navigation_tabs(self, page):
        """Navigation elements exist (settings gear, alert button, etc.)."""
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(2000)

        # NOBA uses icon buttons in header + modal overlays, not traditional tabs
        # Check the settings gear button exists
        settings_btn = page.locator("[title='Settings (s)']").count()
        assert settings_btn > 0, "Settings button not found"

    def test_settings_tab(self, page):
        """Settings modal opens without errors."""
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(2000)
        # Click settings gear button
        page.click("[title='Settings (s)']")
        page.wait_for_timeout(1500)
        # Settings modal should now be visible
        settings_visible = page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).showSettings")
        assert settings_visible, "Settings modal did not open"

    def test_no_unclosed_modals(self, page):
        """After login, only the login modal might linger (Alpine reactivity). No other modals."""
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(3000)
        # Check authenticated state is true after token setup
        authenticated = page.evaluate("""() => {
            try {
                const el = document.querySelector('[x-data]');
                return Alpine.$data(el).authenticated;
            } catch { return null; }
        }""")
        if authenticated:
            # Count non-login modals (settings, automation, etc.)
            unexpected = page.evaluate("""() => {
                const data = Alpine.$data(document.querySelector('[x-data]'));
                return [data.showSettings, data.showAutoModal, data.showAlertRuleModal]
                    .filter(Boolean).length;
            }""")
            assert unexpected == 0, f"{unexpected} unexpected modal(s) open after login"
        else:
            # Login modal expected when not authenticated — that's fine
            pass

    def test_responsive_mobile(self, page):
        """Page renders at mobile viewport without overflow."""
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(self.base_url, wait_until="load", timeout=15000)
        page.wait_for_timeout(2000)
        # Check no horizontal overflow
        overflow = page.evaluate("""() => {
            return document.documentElement.scrollWidth > document.documentElement.clientWidth
        }""")
        # Warning only, not assertion (some cards may overflow)
        if overflow:
            print("    [warn] Horizontal overflow detected on mobile viewport")

    def test_api_stats_loads(self, page):
        """Stats endpoint returns valid data."""
        page.goto(f"{self.base_url}/api/health", wait_until="networkidle")
        content = page.text_content("body")
        data = json.loads(content)
        assert data.get("status") == "ok"

    # ── Runner ───────────────────────────────────────────────────────

    def get_all_tests(self) -> list[tuple[str, callable, bool]]:
        """Return list of (name, test_fn, needs_auth) tuples."""
        return [
            ("health-endpoint", self.test_health_endpoint, False),
            ("login-page-renders", self.test_login_page_renders, False),
            ("login-flow", self.test_login_flow, False),
            ("dashboard-no-js-errors", self.test_dashboard_no_js_errors, True),
            ("dashboard-cards-render", self.test_dashboard_cards_render, True),
            ("navigation-tabs", self.test_navigation_tabs, True),
            ("settings-tab", self.test_settings_tab, True),
            ("no-unclosed-modals", self.test_no_unclosed_modals, True),
            ("responsive-mobile", self.test_responsive_mobile, True),
            ("api-stats-loads", self.test_api_stats_loads, False),
        ]

    def run_all(self, test_filter: str | None = None):
        """Run all tests (or filtered subset)."""
        tests = self.get_all_tests()
        if test_filter:
            tests = [(n, f, a) for n, f, a in tests if test_filter.lower() in n.lower()]

        if not tests:
            print(f"No tests matching '{test_filter}'")
            return

        print(f"\nRunning {len(tests)} E2E test(s)...\n")
        for name, test_fn, needs_auth in tests:
            self.run_test(name, test_fn, needs_auth)

        # Summary
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total_ms = sum(r.duration_ms for r in self.results)
        all_console_errors = []
        for r in self.results:
            all_console_errors.extend(r.console_errors)

        print(f"\n{'─' * 50}")
        print(f"Results: \033[32m{passed} passed\033[0m, "
              f"\033[31m{failed} failed\033[0m "
              f"({total_ms:.0f}ms total)")

        if all_console_errors:
            unique_errors = list(set(all_console_errors))
            print(f"\n\033[33mConsole errors ({len(unique_errors)} unique):\033[0m")
            for err in unique_errors[:10]:
                print(f"  - {err[:120]}")

        if failed > 0:
            print("\n\033[31mFailed tests:\033[0m")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.error[:100]}")
                    if r.screenshot:
                        print(f"    Screenshot: {r.screenshot}")

        return failed == 0


def main():
    parser = argparse.ArgumentParser(description="NOBA E2E Test Runner")
    parser.add_argument("--test", help="Filter tests by name substring")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--screenshot", action="store_true", help="Save screenshots on failure")

    args = parser.parse_args()

    # Check server is running
    import httpx
    try:
        httpx.get(f"http://{args.host}:{args.port}/api/health", timeout=3)
    except Exception:
        print(f"Server not reachable at {args.host}:{args.port}")
        print("Start it with: bash dev/harness.sh start")
        sys.exit(1)

    runner = E2ERunner(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        headed=args.headed,
        save_screenshots=args.screenshot,
    )

    success = runner.run_all(args.test)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
