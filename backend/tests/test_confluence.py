"""Tests for the Confluence Cloud API client.

All HTTP calls are mocked so these run without a Confluence instance.
"""

from unittest.mock import MagicMock, patch

from app.confluence import ConfluenceClient


def _make_client():
    with patch.dict(
        "os.environ",
        {
            "CONFLUENCE_URL": "https://test.atlassian.net",
            "CONFLUENCE_EMAIL": "user@test.com",
            "CONFLUENCE_API_TOKEN": "test_token",
        },
    ):
        return ConfluenceClient()


def test_configured_true():
    client = _make_client()
    assert client.configured is True


def test_configured_false():
    with patch.dict("os.environ", {"CONFLUENCE_URL": "", "CONFLUENCE_EMAIL": "", "CONFLUENCE_API_TOKEN": ""}):
        client = ConfluenceClient()
    assert client.configured is False


@patch("app.confluence.requests.get")
def test_get_pages_in_space(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [{"id": "123", "title": "Closing Docs"}],
        "size": 1,
    }
    mock_get.return_value = mock_resp

    client = _make_client()
    pages = client.get_pages_in_space("HOUSE")
    assert len(pages) == 1
    assert pages[0]["title"] == "Closing Docs"


@patch("app.confluence.requests.get")
def test_get_attachments(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {"title": "deed.pdf", "_links": {"download": "/download/deed.pdf"}},
        ],
    }
    mock_get.return_value = mock_resp

    client = _make_client()
    atts = client.get_attachments("123")
    assert len(atts) == 1
    assert atts[0]["title"] == "deed.pdf"


@patch("app.confluence.requests.get")
def test_download_attachment(mock_get):
    mock_resp = MagicMock()
    mock_resp.content = b"pdf bytes here"
    mock_get.return_value = mock_resp

    client = _make_client()
    result = client.download_attachment("/download/deed.pdf")
    assert result.read() == b"pdf bytes here"


@patch("app.confluence.requests.get")
def test_find_page_by_title_found(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"id": "456", "title": "HOA Rules"}]}
    mock_get.return_value = mock_resp

    client = _make_client()
    page = client.find_page_by_title("HOUSE", "HOA Rules")
    assert page["id"] == "456"


@patch("app.confluence.requests.get")
def test_find_page_by_title_not_found(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_get.return_value = mock_resp

    client = _make_client()
    page = client.find_page_by_title("HOUSE", "Nonexistent")
    assert page is None
