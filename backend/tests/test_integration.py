"""Integration tests against the live running containers.

These tests hit the actual HTTP and HTTPS endpoints to verify the full
stack works end-to-end: API, Postgres, OpenSearch, Caddy proxy.

Requirements:
  - Docker Compose stack must be running: make up-https
  - Tests upload real files, search, ask, and clean up after themselves

Run with:
  cd backend && python -m pytest tests/test_integration.py -v
"""

import os
import tempfile
import time
import warnings

import pytest
import requests

# Suppress the expected TLS warnings for local dev certs
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Both base URLs we want to test against
HTTP_BASE = "http://localhost:8000"
HTTPS_BASE = "https://api.localhost"

# We'll test both protocols with the same test logic
BASE_URLS = [HTTP_BASE, HTTPS_BASE]


def _is_reachable(url: str) -> bool:
    try:
        return requests.get(f"{url}/health", timeout=3, verify=False).status_code == 200
    except Exception:
        return False


# Skip the whole file if containers aren't running
pytestmark = pytest.mark.skipif(
    not _is_reachable(HTTP_BASE),
    reason="Docker Compose stack not running (run 'make up-https' first)",
)


@pytest.fixture(params=BASE_URLS, ids=["http", "https"])
def api(request):
    """Yields each base URL so every test runs against both HTTP and HTTPS."""
    url = request.param
    if not _is_reachable(url):
        pytest.skip(f"{url} not reachable")
    return url


def _upload_test_file(api: str, content: str, filename: str = "test_doc.txt") -> dict:
    """Helper: upload a text file and return the response JSON."""
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write(content)
        f.flush()
        with open(f.name, "rb") as fh:
            resp = requests.post(
                f"{api}/ingest/upload",
                files={"file": (filename, fh)},
                verify=False,
            )
    os.unlink(f.name)
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    return resp.json()


def _cleanup_doc(api: str, document_id: str):
    """Helper: delete a document after test."""
    requests.delete(f"{api}/documents/{document_id}", verify=False)


# ---------------------------------------------------------------------------
# Health and root
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health(self, api):
        resp = requests.get(f"{api}/health", verify=False)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_root(self, api):
        resp = requests.get(f"{api}/", verify=False)
        assert resp.status_code == 200
        assert "House Document Search" in resp.json()["message"]


# ---------------------------------------------------------------------------
# Upload and document management
# ---------------------------------------------------------------------------


class TestUpload:
    def test_upload_txt(self, api):
        """Upload a text file and verify it appears in the document list."""
        data = _upload_test_file(api, "HOA rules say fences must be under 6 feet.")
        assert "document_id" in data
        assert "job_id" in data

        # Verify it shows up in the list
        docs = requests.get(f"{api}/documents", verify=False).json()
        ids = [d["document_id"] for d in docs]
        assert data["document_id"] in ids

        _cleanup_doc(api, data["document_id"])

    def test_upload_rejects_unsupported_type(self, api):
        """Uploading a .jpg should fail with 400."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"not a real image")
            f.flush()
            with open(f.name, "rb") as fh:
                resp = requests.post(
                    f"{api}/ingest/upload",
                    files={"file": ("photo.jpg", fh)},
                    verify=False,
                )
        os.unlink(f.name)
        assert resp.status_code == 400

    def test_upload_auto_classifies(self, api):
        """Uploaded documents should be auto-classified by content."""
        data = _upload_test_file(
            api,
            "CLOSING DISCLOSURE. This form is a statement of final loan terms and closing costs.",
            filename="closing_disclosure.txt",
        )
        doc = requests.get(f"{api}/documents/{data['document_id']}", verify=False).json()
        assert doc["category"] == "Closing Documents"
        assert doc["document_type"] == "closing_disclosure"

        _cleanup_doc(api, data["document_id"])

    def test_upload_creates_chunks(self, api):
        """Uploaded documents should be chunked and stored."""
        data = _upload_test_file(api, "A" * 2000)  # long enough to chunk
        chunks = requests.get(
            f"{api}/documents/{data['document_id']}/chunks",
            verify=False,
        ).json()
        assert len(chunks["chunks"]) >= 1

        _cleanup_doc(api, data["document_id"])


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.fixture(autouse=True)
    def _upload_searchable_doc(self, api):
        """Upload a doc before search tests, clean up after."""
        self.data = _upload_test_file(
            api,
            "The architectural review board requires all fences to be under 6 feet. " "Sheds require prior approval from the HOA.",
            filename="hoa_rules.txt",
        )
        self.api = api
        # Force OpenSearch to make the new document searchable
        time.sleep(1)
        requests.post("http://localhost:9200/house_document_chunks/_refresh", verify=False)
        yield
        _cleanup_doc(api, self.data["document_id"])

    def test_search_finds_content(self):
        # Force OpenSearch refresh to make sure the doc is searchable
        requests.post("http://localhost:9200/house_document_chunks/_refresh")
        resp = requests.post(
            f"{self.api}/search",
            json={"query": "architectural review fences", "page": 1, "page_size": 10},
            verify=False,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0

    def test_search_returns_timing(self):
        resp = requests.post(
            f"{self.api}/search",
            json={"query": "fence", "page": 1, "page_size": 10},
            verify=False,
        )
        data = resp.json()
        assert "timing_ms" in data
        assert isinstance(data["timing_ms"], int)

    def test_search_no_results(self):
        resp = requests.post(
            f"{self.api}/search",
            json={"query": "xyznonexistentterm123", "page": 1, "page_size": 10},
            verify=False,
        )
        assert resp.json()["total"] == 0

    def test_search_pagination(self):
        resp = requests.post(
            f"{self.api}/search",
            json={"query": "fence", "page": 1, "page_size": 1},
            verify=False,
        )
        assert len(resp.json()["results"]) <= 1


# ---------------------------------------------------------------------------
# Ask (RAG with Bedrock)
# ---------------------------------------------------------------------------


class TestAsk:
    @pytest.fixture(autouse=True)
    def _upload_askable_doc(self, api):
        self.data = _upload_test_file(
            api,
            "The HOA management company is NRP LLC. " "Their email is Communications@NRPartnersLLC.com and phone is 703-435-3800.",
            filename="hoa_contacts.txt",
        )
        self.api = api
        time.sleep(1)
        yield
        _cleanup_doc(api, self.data["document_id"])

    def test_ask_returns_answer_with_citations(self):
        resp = requests.post(
            f"{self.api}/ask",
            json={"question": "What is the HOA email?"},
            verify=False,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["answer"]) > 0
        assert "citations" in data
        assert "documents" in data


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_single_document(self, api):
        data = _upload_test_file(api, "Temporary document for delete test.")
        resp = requests.delete(f"{api}/documents/{data['document_id']}", verify=False)
        assert resp.status_code == 200

        # Verify it's gone
        resp = requests.get(f"{api}/documents/{data['document_id']}", verify=False)
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, api):
        resp = requests.delete(f"{api}/documents/nonexistent_id", verify=False)
        assert resp.status_code == 404

    def test_delete_all_documents(self, api):
        # Upload two docs
        d1 = _upload_test_file(api, "Doc one for bulk delete.")
        d2 = _upload_test_file(api, "Doc two for bulk delete.")

        resp = requests.delete(f"{api}/documents", verify=False)
        assert resp.status_code == 200

        # Verify both are gone
        docs = requests.get(f"{api}/documents", verify=False).json()
        ids = [d["document_id"] for d in docs]
        assert d1["document_id"] not in ids
        assert d2["document_id"] not in ids


# ---------------------------------------------------------------------------
# HTTPS-specific tests
# ---------------------------------------------------------------------------


class TestHTTPS:
    """Tests that only apply to the HTTPS endpoint."""

    def test_http_redirects_to_https(self):
        """HTTP requests to api.localhost should redirect to HTTPS."""
        resp = requests.get(
            "http://api.localhost/health",
            allow_redirects=False,
            verify=False,
        )
        assert resp.status_code == 301
        assert "https" in resp.headers.get("location", "")

    def test_security_headers(self):
        """HTTPS responses should include security headers."""
        resp = requests.get("https://api.localhost/health", verify=False)
        headers = resp.headers
        assert "strict-transport-security" in headers
        assert "x-content-type-options" in headers
        assert headers["x-content-type-options"] == "nosniff"
        assert "x-frame-options" in headers

    def test_frontend_serves_over_https(self):
        resp = requests.get("https://app.localhost/", verify=False)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# SSE streaming upload
# ---------------------------------------------------------------------------


class TestSSEUpload:
    def test_streaming_upload_sends_events(self, api):
        """The SSE upload endpoint should stream progress events."""
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Test document for SSE streaming upload.")
            f.flush()
            with open(f.name, "rb") as fh:
                resp = requests.post(
                    f"{api}/ingest/upload-stream",
                    files={"files": ("sse_test.txt", fh)},
                    stream=True,
                    verify=False,
                )
        os.unlink(f.name)

        assert resp.status_code == 200
        events = resp.text.strip().split("\n\n")
        # Should have at least: progress, done/error, complete
        assert len(events) >= 2

        # Parse the last event (should be "complete")
        import json

        last_line = [line for line in events[-1].split("\n") if line.startswith("data: ")][0]
        last = json.loads(last_line[6:])
        assert last["type"] == "complete"
        assert last["total"] == 1

        # Clean up the uploaded doc
        if last.get("uploaded", 0) > 0:
            for event in events:
                for line in event.split("\n"):
                    if line.startswith("data: "):
                        d = json.loads(line[6:])
                        if d.get("document_id"):
                            _cleanup_doc(api, d["document_id"])


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class TestAdmin:
    def test_jobs_endpoint(self, api):
        resp = requests.get(f"{api}/admin/jobs", verify=False)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_reindex_endpoint(self, api):
        resp = requests.post(f"{api}/admin/reindex", verify=False)
        assert resp.status_code == 200
        assert "job_id" in resp.json()
