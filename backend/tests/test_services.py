"""Tests for core services: filename sanitization, keyword scoring, and search fallback.

These test the business logic without needing a database, OpenSearch, or AWS.
External dependencies are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import (
    AskRequest,
    ChunkRecord,
    DocumentResponse,
    SearchRequest,
    SearchResponse,
)
from app.services import (
    _keyword_score,
    _sanitize_filename,
    ingest_file_to_store,
    run_ask,
    run_search,
)

# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


def test_sanitize_normal_filename():
    assert _sanitize_filename("report.pdf") == "report.pdf"


def test_sanitize_spaces():
    assert _sanitize_filename("my report.pdf") == "my_report.pdf"


def test_sanitize_special_chars():
    """Parentheses, commas, and other special chars should be stripped."""
    result = _sanitize_filename("Receipt (with Wire Detail) - Mar 31st, 9_10 AM.pdf")
    assert "(" not in result
    assert ")" not in result
    assert "," not in result
    assert result.endswith(".pdf")


def test_sanitize_preserves_extension():
    assert _sanitize_filename("DOCUMENT.DOCX").endswith(".docx")


def test_sanitize_empty_stem():
    """If stripping leaves nothing, should still produce a valid name."""
    result = _sanitize_filename("(()).pdf")
    assert result.endswith(".pdf")
    assert len(result) > 4  # more than just ".pdf"


# ---------------------------------------------------------------------------
# _keyword_score
# ---------------------------------------------------------------------------


def test_keyword_score_full_match():
    score = _keyword_score("fence height", "The fence height must be under 6 feet")
    assert score == 1.0


def test_keyword_score_partial_match():
    score = _keyword_score("fence height rules", "The fence must be under 6 feet")
    assert 0 < score < 1.0


def test_keyword_score_no_match():
    score = _keyword_score("swimming pool", "The fence must be under 6 feet")
    assert score == 0.0


def test_keyword_score_ignores_stop_words():
    """Stop words like 'the', 'is', 'my' shouldn't count as matches."""
    score = _keyword_score("the is my", "the cat is on my mat")
    assert score == 0.0  # all tokens are stop words, so no real tokens


def test_keyword_score_empty_query():
    assert _keyword_score("", "some content") == 0.0


def test_keyword_score_case_insensitive():
    score = _keyword_score("HOA Rules", "hoa rules and regulations")
    assert score == 1.0


# ---------------------------------------------------------------------------
# run_search - fallback mode (when OpenSearch is down)
# ---------------------------------------------------------------------------


def _make_mock_store():
    """Create a mock PgStore with some test documents and chunks."""
    store = MagicMock()
    doc = DocumentResponse(
        document_id="doc_1",
        title="HOA Rules.pdf",
        source_type="uploaded_file",
        source_url="/tmp/hoa.pdf",
        document_type="hoa",
        category="HOA Governance",
        tags=["hoa"],
        status="indexed",
    )
    chunks = [
        ChunkRecord(
            chunk_id="doc_1_chunk_1",
            document_id="doc_1",
            section_heading="Body",
            content="All fences must be under 6 feet tall. Sheds require approval.",
            source_type="uploaded_file",
            document_type="hoa",
            tags=["hoa"],
        ),
        ChunkRecord(
            chunk_id="doc_1_chunk_2",
            document_id="doc_1",
            section_heading="Body",
            content="The annual HOA meeting is held in January each year.",
            source_type="uploaded_file",
            document_type="hoa",
            tags=["hoa"],
        ),
    ]
    store.all_chunks.return_value = [(doc, c) for c in chunks]
    store.get_chunks.return_value = chunks
    return store


@patch("app.services.os_search")
def test_run_search_fallback(mock_os):
    """When OpenSearch is down, search should fall back to keyword scoring."""
    mock_os.search_chunks.side_effect = Exception("OpenSearch unavailable")
    store = _make_mock_store()

    result = run_search(store, SearchRequest(query="fence height"))
    assert isinstance(result, SearchResponse)
    assert result.total > 0
    assert result.results[0].title == "HOA Rules.pdf"
    assert "fence" in result.results[0].snippet.lower()


@patch("app.services.os_search")
def test_run_search_no_results(mock_os):
    """Query that matches nothing should return empty results."""
    mock_os.search_chunks.side_effect = Exception("down")
    store = _make_mock_store()

    result = run_search(store, SearchRequest(query="swimming pool"))
    assert result.total == 0
    assert result.results == []


@patch("app.services.os_search")
def test_run_search_pagination(mock_os):
    """Pagination should limit results per page."""
    mock_os.search_chunks.side_effect = Exception("down")
    store = _make_mock_store()

    result = run_search(store, SearchRequest(query="hoa", page=1, page_size=1))
    assert len(result.results) == 1
    assert result.total >= 1


@patch("app.services.os_search")
def test_run_search_facets(mock_os):
    """Facets should count document types across all results."""
    mock_os.search_chunks.side_effect = Exception("down")
    store = _make_mock_store()

    result = run_search(store, SearchRequest(query="hoa"))
    assert "hoa" in result.facets["document_type"]


# ---------------------------------------------------------------------------
# run_ask - with mocked Bedrock
# ---------------------------------------------------------------------------


@patch("app.services._get_bedrock")
@patch("app.services.os_search")
def test_run_ask_returns_answer(mock_os, mock_bedrock_fn):
    """Ask should return an answer from Bedrock with citations."""
    mock_os.search_chunks.side_effect = Exception("down")
    store = _make_mock_store()

    # Mock Bedrock converse response
    mock_client = MagicMock()
    mock_bedrock_fn.return_value = mock_client
    mock_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "Fences must be under 6 feet."}]}},
        "usage": {"inputTokens": 100, "outputTokens": 20},
    }

    result = run_ask(store, AskRequest(question="What are the fence rules?"))
    assert "6 feet" in result.answer
    assert len(result.citations) > 0


@patch("app.services._get_bedrock")
@patch("app.services.os_search")
def test_run_ask_no_results(mock_os, mock_bedrock_fn):
    """Ask with no matching chunks should say it couldn't find anything."""
    mock_os.search_chunks.side_effect = Exception("down")
    store = MagicMock()
    store.all_chunks.return_value = []

    result = run_ask(store, AskRequest(question="What about the swimming pool?"))
    assert "could not find" in result.answer.lower()
    assert result.citations == []


@patch("app.services._get_bedrock")
@patch("app.services.os_search")
def test_run_ask_bedrock_failure(mock_os, mock_bedrock_fn):
    """If Bedrock fails, should still return citations with a fallback message."""
    mock_os.search_chunks.side_effect = Exception("down")
    store = _make_mock_store()

    mock_client = MagicMock()
    mock_bedrock_fn.return_value = mock_client
    mock_client.converse.side_effect = Exception("Bedrock timeout")

    result = run_ask(store, AskRequest(question="fence rules"))
    assert "could not generate" in result.answer.lower()
    assert len(result.citations) > 0  # citations should still be there


# ---------------------------------------------------------------------------
# ingest_file_to_store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.os_search")
@patch("app.services.extract_text", return_value=("HOA rules about fences and sheds.", ["Extracted text from page 1"]))
@patch("app.services.chunk_text", return_value=["HOA rules about fences and sheds."])
@patch("app.services.classify_document", return_value=("HOA Governance", "hoa", ["hoa"], "HOA Rules Document", "2026-01-15"))
async def test_ingest_stores_document(mock_classify, mock_chunk, mock_extract, mock_os):
    """Ingestion should save the file, create a document, and store chunks."""
    store = MagicMock()
    store.new_id.return_value = "doc_test123"
    store.new_job_id.return_value = "ingest_test123"
    store.upload_dir = "/tmp"
    store.find_by_hash.return_value = None

    file = MagicMock()
    file.filename = "test_rules.txt"
    file.read = AsyncMock(return_value=b"HOA rules about fences and sheds.")

    result = await ingest_file_to_store(store, file)
    assert result.document_id == "doc_test123"
    store.add_document.assert_called_once()
    store.set_chunks.assert_called_once()
    store.update_job_status.assert_called_once_with("ingest_test123", "completed")


@pytest.mark.asyncio
async def test_ingest_rejects_unsupported_type():
    """Should raise ValueError for unsupported file types."""
    store = MagicMock()
    file = MagicMock()
    file.filename = "archive.zip"

    with pytest.raises(ValueError, match="Unsupported"):
        await ingest_file_to_store(store, file)


# ---------------------------------------------------------------------------
# Hybrid search: embedding integration
# ---------------------------------------------------------------------------


@patch("app.search._get_bedrock_runtime")
def test_get_embedding_calls_bedrock(mock_runtime):
    """get_embedding should call Bedrock Titan with the input text."""
    import json

    from app.search import get_embedding

    mock_client = MagicMock()
    mock_runtime.return_value = mock_client
    mock_body = MagicMock()
    mock_body.read.return_value = json.dumps({"embedding": [0.1] * 1024}).encode()
    mock_client.invoke_model.return_value = {"body": mock_body}

    result = get_embedding("test text")
    assert len(result) == 1024
    mock_client.invoke_model.assert_called_once()
    call_args = mock_client.invoke_model.call_args
    assert "inputText" in call_args[1]["body"]


@patch("app.search.helpers.bulk")
@patch("app.search.get_embedding")
@patch("app.search.get_client")
def test_index_chunks_embeds_content(mock_client_fn, mock_embed, mock_bulk):
    """index_chunks should generate embeddings for each chunk."""
    from app.search import index_chunks

    mock_embed.return_value = [0.0] * 1024
    mock_client = MagicMock()
    mock_client_fn.return_value = mock_client

    chunks = [
        {"chunk_id": "c1", "content": "fence rules"},
        {"chunk_id": "c2", "content": "roof condition"},
    ]
    index_chunks("doc1", "Test Doc", chunks)

    assert mock_embed.call_count == 2
    mock_embed.assert_any_call("fence rules")
    mock_embed.assert_any_call("roof condition")
    mock_bulk.assert_called_once()
    # Verify embeddings are in the actions
    actions = mock_bulk.call_args[0][1]
    assert actions[0]["_source"]["embedding"] == [0.0] * 1024


@patch("app.search.helpers.bulk")
@patch("app.search.get_embedding")
@patch("app.search.get_client")
def test_index_chunks_survives_embedding_failure(mock_client_fn, mock_embed, mock_bulk):
    """If embedding fails for a chunk, it should still be indexed without the vector."""
    from app.search import index_chunks

    mock_embed.side_effect = Exception("Bedrock timeout")
    mock_client = MagicMock()
    mock_client_fn.return_value = mock_client

    chunks = [{"chunk_id": "c1", "content": "some text"}]
    # Should not raise
    index_chunks("doc1", "Test Doc", chunks)
    mock_bulk.assert_called_once()
    actions = mock_bulk.call_args[0][1]
    assert "embedding" not in actions[0]["_source"]
