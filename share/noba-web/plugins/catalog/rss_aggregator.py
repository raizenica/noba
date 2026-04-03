# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""RSS/Atom Feed Aggregator -- Pull feeds and display on dashboard.

Monitors RSS/Atom feeds for security advisories, release notes,
or any other content.  Supports keyword filtering and highlights.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import xml.etree.ElementTree as ET

PLUGIN_ID = "rss_aggregator"
PLUGIN_NAME = "RSS Feed Aggregator"
PLUGIN_VERSION = "1.0.0"
PLUGIN_ICON = "fa-rss"
PLUGIN_DESCRIPTION = "Aggregate RSS/Atom feeds for security advisories, release notes, and homelab news."
PLUGIN_INTERVAL = 15

PLUGIN_CONFIG_SCHEMA = {
    "feeds": {
        "type": "list",
        "label": "Feed URLs",
        "default": [
            "https://github.com/advisories.atom",
        ],
    },
    "refresh_interval_minutes": {
        "type": "number",
        "label": "Refresh interval (minutes)",
        "default": 30,
        "min": 5,
        "max": 1440,
    },
    "max_items": {
        "type": "number",
        "label": "Max items to display",
        "default": 20,
        "min": 5,
        "max": 100,
    },
    "keyword_filter": {
        "type": "string",
        "label": "Keyword filter (comma-separated)",
        "default": "",
        "placeholder": "critical,CVE,vulnerability",
    },
    "highlight_keywords": {
        "type": "boolean",
        "label": "Highlight matching keywords",
        "default": True,
    },
}

_lock = threading.Lock()
_items: list[dict] = []
_error: str = ""
_last_fetch: float = 0
_ctx = None


def _parse_rss(xml_text: str, feed_url: str) -> list[dict]:
    """Parse RSS or Atom feed XML into item dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Detect Atom vs RSS
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    if root.tag == "{http://www.w3.org/2005/Atom}feed" or root.tag == "feed":
        # Atom feed
        for entry in root.findall("atom:entry", ns) or root.findall("entry"):
            title = ""
            link = ""
            published = ""
            title_el = entry.find("atom:title", ns)
            if title_el is None:
                title_el = entry.find("title")
            if title_el is not None:
                title = (title_el.text or "").strip()
            link_el = entry.find("atom:link", ns)
            if link_el is None:
                link_el = entry.find("link")
            if link_el is not None:
                link = link_el.get("href", "")
            pub_el = entry.find("atom:updated", ns) or entry.find("atom:published", ns)
            if pub_el is None:
                pub_el = entry.find("updated") or entry.find("published")
            if pub_el is not None:
                published = (pub_el.text or "").strip()
            items.append({
                "title": title,
                "link": link,
                "published": published,
                "feed": feed_url,
                "id": hashlib.md5(f"{feed_url}:{link}:{title}".encode()).hexdigest()[:12],
            })
    else:
        # RSS 2.0
        channel = root.find("channel")
        if channel is None:
            channel = root
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            published = (item.findtext("pubDate") or item.findtext("dc:date") or "").strip()
            items.append({
                "title": title,
                "link": link,
                "published": published,
                "feed": feed_url,
                "id": hashlib.md5(f"{feed_url}:{link}:{title}".encode()).hexdigest()[:12],
            })
    return items


def _fetch_feeds(cfg: dict) -> tuple[list[dict], str]:
    """Fetch and parse all configured feeds."""
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        return [], "httpx not available"

    feeds = cfg.get("feeds", [])
    max_items = int(cfg.get("max_items", 20))
    keywords = [k.strip().lower() for k in cfg.get("keyword_filter", "").split(",") if k.strip()]

    all_items = []
    errors = []
    for feed_url in feeds:
        if not feed_url:
            continue
        try:
            r = httpx.get(feed_url, timeout=15, follow_redirects=True)
            r.raise_for_status()
            parsed = _parse_rss(r.text, feed_url)
            all_items.extend(parsed)
        except Exception as e:
            errors.append(f"{feed_url}: {e}")

    # Filter by keywords if set
    if keywords:
        all_items = [
            item for item in all_items
            if any(kw in item["title"].lower() for kw in keywords)
        ]

    # Sort by published date (newest first), truncate
    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    all_items = all_items[:max_items]

    error_str = "; ".join(errors) if errors else ""
    return all_items, error_str


def _fetch_loop(cfg: dict) -> None:
    """Background loop to periodically refresh feeds."""
    global _last_fetch  # noqa: PLW0603
    interval = max(int(cfg.get("refresh_interval_minutes", 30)), 5) * 60
    while True:
        now = time.time()
        if now - _last_fetch >= interval:
            items, error = _fetch_feeds(cfg)
            with _lock:
                global _error  # noqa: PLW0603
                _items.clear()
                _items.extend(items)
                _error = error
            _last_fetch = now
        time.sleep(30)


def register(ctx) -> None:
    """Start RSS fetcher in background."""
    global _ctx  # noqa: PLW0603
    _ctx = ctx
    cfg = ctx.get_config()
    feeds = cfg.get("feeds", [])
    if not feeds or not any(feeds):
        return
    t = threading.Thread(target=_fetch_loop, args=(cfg,), daemon=True, name="rss-aggregator")
    t.start()


def collect() -> dict:
    """Return current feed items."""
    with _lock:
        return {
            "items": list(_items),
            "error": _error,
            "item_count": len(_items),
        }


def render(data: dict) -> str:
    """Render dashboard card HTML."""
    error = data.get("error", "")
    items = data.get("items", [])

    html = ""
    if error:
        html += f'<div style="color:var(--warning);font-size:.7rem;margin-bottom:.3rem">{error}</div>'
    if not items:
        return html + '<div style="color:var(--text-muted);font-size:.8rem">No feed items yet. Check your feed URLs.</div>'

    for item in items[:8]:
        title = item.get("title", "Untitled")[:80]
        link = item.get("link", "#")
        pub = item.get("published", "")[:16]
        # Sanitize for basic XSS prevention
        title = re.sub(r'[<>&"\']', '', title)
        html += (
            f'<div style="padding:2px 0;font-size:.78rem;border-bottom:1px solid var(--border)">'
            f'<a href="{link}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">'
            f'{title}</a>'
            f'<span style="float:right;font-size:.6rem;color:var(--text-dim)">{pub}</span>'
            f'</div>'
        )
    if len(items) > 8:
        html += f'<div style="font-size:.65rem;color:var(--text-dim);margin-top:.3rem">+{len(items) - 8} more items</div>'
    return html


def teardown() -> None:
    pass
