"""Tests for Pydantic schemas.

Makes sure our API request/response models validate correctly
and reject bad input.
"""

import pytest
from pydantic import ValidationError

from app.schemas import AskRequest, DocumentResponse, SearchRequest


def test_search_request_requires_query():
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_search_request_defaults():
    req = SearchRequest(query="fence rules")
    assert req.mode == "hybrid"
    assert req.page == 1
    assert req.page_size == 10
    assert req.filters == {}


def test_ask_request_defaults():
    req = AskRequest(question="What about the roof?")
    assert req.top_k == 15
    assert req.filters == {}


def test_ask_request_requires_question():
    with pytest.raises(ValidationError):
        AskRequest(question="")


def test_document_response_defaults():
    doc = DocumentResponse(
        document_id="doc_123",
        title="test.pdf",
        source_type="uploaded_file",
        source_url="/tmp/test.pdf",
        document_type="general",
        status="indexed",
    )
    assert doc.category == "Uncategorized"
    assert doc.tags == []
