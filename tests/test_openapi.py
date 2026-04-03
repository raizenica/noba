# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Test OpenAPI schema and API docs are disabled by default (NOBA_DEV=0)."""
from __future__ import annotations


def test_openapi_disabled_by_default(client):
    """OpenAPI schema should not be accessible without NOBA_DEV."""
    res = client.get("/api/openapi.json")
    assert res.status_code == 404


def test_docs_disabled_by_default(client):
    """Swagger UI should not be accessible without NOBA_DEV."""
    res = client.get("/api/docs")
    assert res.status_code == 404


def test_redoc_disabled_by_default(client):
    """ReDoc should not be accessible without NOBA_DEV."""
    res = client.get("/api/redoc")
    assert res.status_code == 404
