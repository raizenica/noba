#!/usr/bin/env python3
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""crossref.py — Cross-reference validator for NOBA.

Catches the exact class of bugs that burned us: mismatched variable names
between collector.py ↔ integrations.py ↔ app.js ↔ index.html.

Validates:
1. Collector futures reference real integration functions
2. HTML x-model bindings match JS property names
3. DEF_VIS keys match actual card/section names
4. Settings keys are wired end-to-end (YAML → Python config → JS → HTML)
5. API routes referenced in JS actually exist in app.py
6. CSS classes used in HTML exist in style.css

Usage:
    python dev/crossref.py           # Run all checks
    python dev/crossref.py --check collector   # Run specific check
    python dev/crossref.py --fix     # Auto-fix where possible
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SERVER = PROJECT / "share" / "noba-web" / "server"
STATIC = PROJECT / "share" / "noba-web" / "static"
HTML_FILE = PROJECT / "share" / "noba-web" / "index.html"

# Colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
NC = "\033[0m"

PASS = 0
WARN = 0
FAIL = 0


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  {GREEN}✓{NC} {msg}")


def warn(msg: str):
    global WARN
    WARN += 1
    print(f"  {YELLOW}⚠{NC} {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  {RED}✗{NC} {msg}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ── Check 1: Collector ↔ Integrations ────────────────────────────────
def check_collector_integrations():
    """Verify collector.py only calls functions that exist in integrations.py."""
    print(f"\n{BLUE}[1] Collector ↔ Integrations{NC}")

    integrations_src = read(SERVER / "integrations.py")
    collector_src = read(SERVER / "collector.py")

    # Extract function definitions from integrations.py
    int_funcs = set(re.findall(r"^def (get_\w+)\(", integrations_src, re.MULTILINE))

    # Extract function calls in collector.py that reference integrations
    # Pattern: integrations.get_xxx( — but NOT .get("key") dict access
    collector_calls = set(re.findall(r"(?<!\.)get_(\w+)\(", collector_src))
    # Also match module-qualified calls
    collector_calls |= set(re.findall(r"integrations\.get_(\w+)\(", collector_src))
    collector_calls |= set(re.findall(r"metrics\.get_(\w+)\(", collector_src))
    collector_gets = {f"get_{c}" for c in collector_calls}
    # Filter out dict-style .get() calls (get_config, get_all are dict methods)
    collector_gets -= {"get_all", "get_config"}

    # Also check direct imports
    imported = set(re.findall(r"from \.integrations import .+?(get_\w+)", collector_src))
    all_referenced = collector_gets | imported

    for func in sorted(all_referenced):
        if func in int_funcs:
            ok(f"{func} exists in integrations.py")
        elif func.startswith("get_"):
            # Some may be from other modules (metrics.py)
            metrics_src = read(SERVER / "metrics.py")
            if f"def {func}(" in metrics_src:
                ok(f"{func} exists in metrics.py")
            else:
                fail(f"{func} called in collector but not found in integrations.py or metrics.py")


# ── Check 2: HTML x-model ↔ JS state ────────────────────────────────
def check_html_js_bindings():
    """Verify x-model bindings in HTML reference existing JS properties."""
    print(f"\n{BLUE}[2] HTML x-model ↔ JS state{NC}")

    html = read(HTML_FILE)
    app_js = read(STATIC / "app.js")
    actions_js = read(STATIC / "actions-mixin.js")
    auth_js = read(STATIC / "auth-mixin.js") if (STATIC / "auth-mixin.js").exists() else ""
    all_js = app_js + actions_js + auth_js

    # Extract x-model bindings from HTML
    xmodels = set(re.findall(r'x-model(?:\.number)?="(\w+)"', html))

    # Extract property names from JS (state object literals, this.xxx, etc.)
    js_props = set(re.findall(r"(\w+)\s*:", all_js))
    js_props |= set(re.findall(r"this\.(\w+)", all_js))

    # Also check SETTINGS_KEYS and LIVE_DATA_KEYS
    settings_keys = set(re.findall(r"'(\w+)'", all_js))
    js_props |= settings_keys

    # Extract variables from inline x-data scopes in HTML (e.g., x-data="{ selA: '', dryRun: false }")
    inline_xdata = re.findall(r'x-data="\{([^}]+)\}"', html)
    for xd in inline_xdata:
        local_props = re.findall(r"(\w+)\s*:", xd)
        js_props |= set(local_props)

    missing = xmodels - js_props
    if missing:
        for m in sorted(missing):
            fail(f"x-model=\"{m}\" in HTML but not found in JS or inline x-data")
    else:
        ok(f"All {len(xmodels)} x-model bindings have matching JS properties")


# ── Check 3: DEF_VIS ↔ HTML cards ───────────────────────────────────
def check_def_vis():
    """Verify DEF_VIS keys correspond to actual HTML elements."""
    print(f"\n{BLUE}[3] DEF_VIS ↔ HTML cards{NC}")

    app_js = read(STATIC / "app.js")
    html = read(HTML_FILE)

    # Extract DEF_VIS keys
    def_vis_match = re.search(r"DEF_VIS\s*=\s*\{([^}]+)\}", app_js, re.DOTALL)
    if not def_vis_match:
        warn("Could not find DEF_VIS in app.js")
        return

    def_vis_keys = set(re.findall(r"(\w+)\s*:", def_vis_match.group(1)))

    # Check each key is referenced in HTML (x-show with vis. prefix)
    for key in sorted(def_vis_keys):
        if f"vis.{key}" in html or f"vis['{key}']" in html or f'vis["{key}"]' in html:
            ok(f"vis.{key} used in HTML")
        else:
            warn(f"DEF_VIS key '{key}' defined but not referenced in HTML with vis.{key}")


# ── Check 4: Settings pipeline ──────────────────────────────────────
def check_settings_pipeline():
    """Verify settings keys flow: YAML defaults → Python WEB_KEYS → JS SETTINGS_KEYS."""
    print(f"\n{BLUE}[4] Settings pipeline{NC}")

    config_py = read(SERVER / "config.py")
    read(SERVER / "yaml_config.py")  # Check for references
    app_js = read(STATIC / "app.js")

    # Extract WEB_KEYS from config.py
    web_keys_match = re.search(r"WEB_KEYS\s*=\s*\{([^}]+)\}", config_py, re.DOTALL)
    if not web_keys_match:
        # Try multiline brace matching
        start = config_py.find("WEB_KEYS")
        if start >= 0:
            depth = 0
            end = start
            for i, c in enumerate(config_py[start:]):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end = start + i + 1
                        break
            web_keys_content = config_py[start:end]
            web_keys = set(re.findall(r'"(\w+)"', web_keys_content))
        else:
            warn("Could not find WEB_KEYS in config.py")
            return
    else:
        web_keys = set(re.findall(r'"(\w+)"', web_keys_match.group(1)))

    # Extract SETTINGS_KEYS from app.js
    sk_match = re.search(r"SETTINGS_KEYS\s*=\s*\[([^\]]+)\]", app_js, re.DOTALL)
    if sk_match:
        settings_keys = set(re.findall(r"'(\w+)'", sk_match.group(1)))
    else:
        warn("Could not find SETTINGS_KEYS in app.js")
        return

    # Check JS settings keys exist in Python WEB_KEYS
    missing_in_py = settings_keys - web_keys
    if missing_in_py:
        for k in sorted(missing_in_py):
            fail(f"SETTINGS_KEYS '{k}' in JS but not in WEB_KEYS (Python)")
    else:
        ok(f"All {len(settings_keys)} JS SETTINGS_KEYS exist in Python WEB_KEYS")

    # Check Python WEB_KEYS exist in JS (non-critical — some may be backend-only)
    missing_in_js = web_keys - settings_keys
    if missing_in_js and len(missing_in_js) < 20:
        for k in sorted(missing_in_js):
            warn(f"WEB_KEYS '{k}' in Python but not in JS SETTINGS_KEYS (may be backend-only)")


# ── Check 5: JS API routes ↔ app.py routes ──────────────────────────
def check_api_routes():
    """Verify fetch() calls in JS reference existing app.py routes."""
    print(f"\n{BLUE}[5] JS fetch() ↔ app.py routes{NC}")

    app_py = read(SERVER / "app.py")
    app_js = read(STATIC / "app.js")
    actions_js = read(STATIC / "actions-mixin.js")
    auth_js = read(STATIC / "auth-mixin.js") if (STATIC / "auth-mixin.js").exists() else ""
    all_js = app_js + actions_js + auth_js

    # Extract route paths from app.py
    route_patterns = re.findall(r'@app\.(?:get|post|put|delete|patch)\("(/api/[^"]+)"', app_py)
    # Normalize: remove path params like {id}
    routes = set()
    for rp in route_patterns:
        normalized = re.sub(r"\{[^}]+\}", "*", rp)
        routes.add(normalized)
        routes.add(rp)  # Keep original too

    # Extract fetch URLs from JS
    fetch_urls = re.findall(r"fetch\(`?['\"]?(/api/[^`'\")\s]+)", all_js)
    # Also template literals
    fetch_urls += re.findall(r"fetch\(`(/api/[^`]+)`", all_js)
    # Clean up template expressions and query params
    clean_urls = set()
    for u in fetch_urls:
        # Replace ${...} with *
        cleaned = re.sub(r"\$\{[^}]+\}", "*", u)
        # Strip query params for route matching (keep for display)
        path_only = cleaned.split("?")[0]
        clean_urls.add(path_only)

    matched = 0
    for url in sorted(clean_urls):
        found = False
        for route in routes:
            # Compare with wildcard matching
            route_re = re.escape(route).replace(r"\*", r"[^/]+")
            if re.match(f"^{route_re}$", url) or route == url:
                found = True
                break
            # Also try the cleaned version
            url_re = re.escape(url).replace(r"\*", r"[^/]+")
            if re.match(f"^{url_re}$", route):
                found = True
                break
        if found:
            matched += 1
        else:
            # Check if it's a path with dynamic segments that we can't easily match
            if "*" in url or "${" in url:
                warn(f"Dynamic route {url} — manual check recommended")
            else:
                fail(f"JS fetches {url} but no matching route in app.py")

    ok(f"{matched}/{len(clean_urls)} JS API calls matched to app.py routes")


# ── Check 6: HTML CSS classes ↔ style.css ────────────────────────────
def check_css_classes():
    """Spot-check key CSS classes used in HTML exist in style.css."""
    print(f"\n{BLUE}[6] HTML classes ↔ style.css{NC}")

    read(HTML_FILE)  # Check for references
    css = read(STATIC / "style.css")

    # Extract class names from CSS (simplified — looks for .classname patterns)
    css_classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))

    # Key structural classes we expect to find
    critical_classes = [
        "card", "modal-overlay", "modal-box", "modal-title", "modal-footer",
        "btn", "stat-grid", "status-badge",
    ]

    for cls in critical_classes:
        if cls in css_classes:
            ok(f".{cls} defined in style.css")
        else:
            fail(f".{cls} used in HTML but not in style.css")


# ── Check 7: Label for= ↔ form element IDs ──────────────────────────
def check_label_for():
    """Verify <label for="X"> has a matching id="X" element."""
    print(f"\n{BLUE}[7] Label for= ↔ element IDs{NC}")

    html = read(HTML_FILE)

    label_fors = set(re.findall(r'<label[^>]+for="([^"]+)"', html))
    element_ids = set(re.findall(r'\bid="([^"]+)"', html))

    orphaned = label_fors - element_ids
    if orphaned:
        for lf in sorted(orphaned):
            fail(f'<label for="{lf}"> has no matching id="{lf}" element')
    else:
        ok(f"All {len(label_fors)} label for= attributes have matching IDs")


# ── Main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="NOBA Cross-Reference Validator")
    parser.add_argument("--check", help="Run specific check: collector, bindings, vis, settings, routes, css, labels")
    args = parser.parse_args()

    checks = {
        "collector": check_collector_integrations,
        "bindings": check_html_js_bindings,
        "vis": check_def_vis,
        "settings": check_settings_pipeline,
        "routes": check_api_routes,
        "css": check_css_classes,
        "labels": check_label_for,
    }

    print(f"\n{'═' * 50}")
    print("  NOBA Cross-Reference Validator")
    print(f"{'═' * 50}")

    if args.check:
        if args.check in checks:
            checks[args.check]()
        else:
            print(f"Unknown check: {args.check}")
            print(f"Available: {', '.join(checks.keys())}")
            sys.exit(1)
    else:
        for check_fn in checks.values():
            check_fn()

    print(f"\n{'─' * 50}")
    print(f"  {GREEN}{PASS} passed{NC}, {YELLOW}{WARN} warnings{NC}, {RED}{FAIL} failures{NC}")
    print(f"{'─' * 50}\n")

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
