"""Test OpenAPI schema generation and API docs."""
from __future__ import annotations


def test_openapi_schema_loads(client):
    """The schema should load without errors and contain routes."""
    res = client.get("/api/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert "openapi" in schema
    assert "paths" in schema
    assert len(schema["paths"]) > 50


def test_openapi_has_agent_routes(client):
    """Verify agent routes appear in the schema."""
    res = client.get("/api/openapi.json")
    schema = res.json()
    assert "/api/agents" in schema["paths"]
    assert "/api/agent/report" in schema["paths"]


def test_openapi_has_container_routes(client):
    """Verify container routes appear."""
    res = client.get("/api/openapi.json")
    schema = res.json()
    assert "/api/container-control" in schema["paths"]


def test_openapi_has_monitoring_routes(client):
    """Verify monitoring routes appear."""
    res = client.get("/api/openapi.json")
    schema = res.json()
    assert "/api/endpoints" in schema["paths"]


def test_docs_page_loads(client):
    """Swagger UI should be accessible."""
    res = client.get("/api/docs")
    assert res.status_code == 200
    assert b"swagger" in res.content.lower() or b"openapi" in res.content.lower()


def test_redoc_page_loads(client):
    """ReDoc should be accessible."""
    res = client.get("/api/redoc")
    assert res.status_code == 200
