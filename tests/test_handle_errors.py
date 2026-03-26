"""Tests for the handle_errors decorator in deps."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.deps import handle_errors


def test_handle_errors_passes_through_http_exception():
    app = FastAPI()

    @app.get("/test")
    @handle_errors
    def route():
        raise HTTPException(status_code=404, detail="not found")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/test")
    assert r.status_code == 404
    assert r.json()["detail"] == "not found"


def test_handle_errors_converts_unhandled_to_500():
    app = FastAPI()

    @app.get("/boom")
    @handle_errors
    def route():
        raise ValueError("something went wrong")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    assert "something went wrong" in r.json()["detail"]


def test_handle_errors_async_route():
    app = FastAPI()

    @app.get("/async-boom")
    @handle_errors
    async def route():
        raise RuntimeError("async failure")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/async-boom")
    assert r.status_code == 500
    assert "async failure" in r.json()["detail"]


def test_handle_errors_happy_path():
    app = FastAPI()

    @app.get("/ok")
    @handle_errors
    def route():
        return {"status": "ok"}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/ok")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_handle_errors_async_happy_path():
    app = FastAPI()

    @app.get("/async-ok")
    @handle_errors
    async def route():
        return {"status": "ok"}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/async-ok")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_handle_errors_preserves_function_name():
    @handle_errors
    def my_named_function():
        pass

    assert my_named_function.__name__ == "my_named_function"
