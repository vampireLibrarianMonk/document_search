"""Tests for the BookStack API client.

All HTTP calls are mocked so these run without a BookStack instance.
"""

import base64
from unittest.mock import MagicMock, patch

from app.bookstack import BookStackClient


def _make_client():
    """Create a BookStackClient with test credentials."""
    with patch.dict(
        "os.environ",
        {
            "BOOKSTACK_URL": "http://bookstack:80",
            "BOOKSTACK_TOKEN_ID": "test_id",
            "BOOKSTACK_TOKEN_SECRET": "test_secret",  # pragma: allowlist secret,
        },
    ):
        return BookStackClient()


def test_configured_true():
    client = _make_client()
    assert client.configured is True


def test_configured_false():
    with patch.dict("os.environ", {"BOOKSTACK_TOKEN_ID": "", "BOOKSTACK_TOKEN_SECRET": ""}):
        client = BookStackClient()
    assert client.configured is False


@patch("app.bookstack.requests.get")
def test_list_books(mock_get):
    mock_get.return_value.json.return_value = {"data": [{"id": 1, "name": "HOA"}]}
    mock_get.return_value.raise_for_status = MagicMock()

    client = _make_client()
    books = client.list_books()
    assert len(books) == 1
    assert books[0]["name"] == "HOA"


@patch("app.bookstack.requests.get")
def test_get_all_pdf_attachments(mock_get):
    mock_get.return_value.json.return_value = {
        "data": [
            {"id": 1, "name": "rules.pdf", "extension": "pdf"},
            {"id": 2, "name": "photo.jpg", "extension": "jpg"},
            {"id": 3, "name": "deed.PDF", "extension": "PDF"},
        ],
    }
    mock_get.return_value.raise_for_status = MagicMock()

    client = _make_client()
    pdfs = client.get_all_pdf_attachments()
    assert len(pdfs) == 2  # rules.pdf and deed.PDF, not photo.jpg


@patch("app.bookstack.requests.get")
def test_download_attachment_file(mock_get):
    """File attachments come back as base64-encoded content."""
    content = base64.b64encode(b"fake pdf bytes").decode()
    mock_get.return_value.json.return_value = {
        "name": "test.pdf",
        "content": content,
        "external": False,
        "extension": "pdf",
    }
    mock_get.return_value.raise_for_status = MagicMock()

    client = _make_client()
    name, data = client.download_attachment(1)
    assert name == "test.pdf"
    assert data.read() == b"fake pdf bytes"


@patch("app.bookstack.requests.post")
@patch("app.bookstack.requests.get")
def test_find_or_create_book_existing(mock_get, mock_post):
    """Should find an existing book by name without creating a new one."""
    mock_get.return_value.json.return_value = {"data": [{"id": 5, "name": "Closing Documents"}]}
    mock_get.return_value.raise_for_status = MagicMock()

    client = _make_client()
    book_id = client.find_or_create_book("Closing Documents")
    assert book_id == 5
    mock_post.assert_not_called()


@patch("app.bookstack.requests.post")
@patch("app.bookstack.requests.get")
def test_find_or_create_book_new(mock_get, mock_post):
    """Should create a new book if none exists with that name."""
    mock_get.return_value.json.return_value = {"data": []}
    mock_get.return_value.raise_for_status = MagicMock()
    mock_post.return_value.json.return_value = {"id": 10, "name": "Insurance"}
    mock_post.return_value.raise_for_status = MagicMock()

    client = _make_client()
    book_id = client.find_or_create_book("Insurance")
    assert book_id == 10
    mock_post.assert_called_once()


@patch("app.bookstack.requests.post")
def test_upload_attachment(mock_post):
    mock_post.return_value.json.return_value = {"id": 99}
    mock_post.return_value.raise_for_status = MagicMock()

    client = _make_client()
    result = client.upload_attachment(1, "test.pdf", b"content")
    assert result["id"] == 99
