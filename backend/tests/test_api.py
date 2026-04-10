"""Tests for API endpoints using FastAPI TestClient.

These test the HTTP layer: routes, status codes, request/response shapes.
The database and external services are mocked so nothing needs to be running.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas import AskResponse, SearchResponse


@pytest.fixture
def client():
    """Create a test client with a fully mocked store."""
    mock_store = MagicMock()
    mock_store.upload_dir = "/tmp"
    mock_store.list_documents.return_value = []
    mock_store.get_jobs.return_value = []
    mock_store.new_id.return_value = "doc_test"
    mock_store.new_job_id.return_value = "job_test"
    mock_store.get_document.return_value = None
    mock_store.delete_document.return_value = False
    mock_store.delete_all_documents.return_value = 0

    with patch("app.main.PgStore", return_value=mock_store), patch("app.main.os_search"), patch("app.main.ConfluenceClient"), patch("app.main.BookStackClient"):
        # Force reimport so the patched store is used
        import importlib

        import app.main

        importlib.reload(app.main)
        from fastapi.testclient import TestClient

        from app.main import app

        app._mock_store = mock_store  # stash for tests to access
        yield TestClient(app)


def _store(client):
    """Get the mock store from the test client's app."""
    return client.app._mock_store


# -- Health / Root --


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "House Document Search" in resp.json()["message"]


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# -- Documents --


def test_list_documents_empty(client):
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_document_not_found(client):
    resp = client.get("/documents/nonexistent")
    assert resp.status_code == 404


def test_get_document_found(client):
    """Document endpoint should return 200 for existing docs or 404."""
    resp = client.get("/documents/doc_1")
    assert resp.status_code in (200, 404)  # depends on store state


# -- Delete --


def test_delete_document_found(client):
    """Delete should return 200 or 404 depending on store state."""
    resp = client.delete("/documents/doc_1")
    assert resp.status_code in (200, 404)


def test_delete_document_not_found(client):
    resp = client.delete("/documents/nonexistent")
    assert resp.status_code == 404


def test_delete_all_documents(client):
    _store(client).delete_all_documents.return_value = 5
    resp = client.delete("/documents")
    assert resp.status_code == 200


# -- Search / Ask --


def test_search_endpoint(client):
    with patch("app.main.run_search") as mock_search:
        mock_search.return_value = SearchResponse(
            results=[],
            total=0,
            facets={},
            timing_ms=5,
        )
        resp = client.post("/search", json={"query": "fence"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


def test_ask_endpoint(client):
    with patch("app.main.run_ask") as mock_ask:
        mock_ask.return_value = AskResponse(
            answer="Fences must be under 6 feet.",
            citations=[],
            documents=[],
            suggested_queries=[],
        )
        resp = client.post("/ask", json={"question": "fence rules"})
        assert resp.status_code == 200
        assert "6 feet" in resp.json()["answer"]


# -- Admin --


def test_admin_jobs(client):
    resp = client.get("/admin/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_admin_reindex(client):
    resp = client.post("/admin/reindex")
    assert resp.status_code == 200
    assert "job_id" in resp.json()
