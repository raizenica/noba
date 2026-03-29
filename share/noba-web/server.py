#!/usr/bin/env python3
"""Noba Command Center – server launcher.

Requires FastAPI and uvicorn. Install with:
    pip install fastapi 'uvicorn[standard]' psutil pyyaml
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
HOST  = os.environ.get("HOST", "0.0.0.0")
PORT  = int(os.environ.get("PORT", 8080))
SSL_CERT = os.environ.get("SSL_CERT", "")
SSL_KEY  = os.environ.get("SSL_KEY", "")


def _resolve_ssl() -> dict:
    """Resolve SSL cert/key paths from env vars or YAML config."""
    cert = SSL_CERT
    key = SSL_KEY
    # Fall back to YAML config (set via the GUI)
    if not cert or not key:
        try:
            import yaml
            config_path = os.environ.get(
                "NOBA_CONFIG",
                os.path.expanduser("~/.config/noba/config.yaml"),
            )
            if os.path.isfile(config_path):
                with open(config_path) as f:
                    cfg = yaml.safe_load(f) or {}
                web = cfg.get("web", {})
                cert = cert or web.get("sslCertPath", "")
                key = key or web.get("sslKeyPath", "")
        except Exception:
            pass
    if cert and key and os.path.isfile(cert) and os.path.isfile(key):
        return {"ssl_certfile": cert, "ssl_keyfile": key}
    return {}


if __name__ == "__main__":
    # Ensure the package directory is on sys.path so `from server.app import app` works
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)

    try:
        import uvicorn  # noqa: F401
        from server.app import app  # noqa: F401
    except ImportError as e:
        print(f"[noba] Missing dependency: {e}", file=sys.stderr, flush=True)
        print("[noba] Install with:  pip install fastapi 'uvicorn[standard]' psutil pyyaml",
              file=sys.stderr, flush=True)
        sys.exit(1)

    os.chdir(_HERE)
    uvicorn.run(app, host=HOST, port=PORT, log_config=None, access_log=False, **_resolve_ssl())
