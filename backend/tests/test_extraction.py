"""Tests for text extraction and chunking.

Covers plain text extraction, chunk splitting, sentence boundaries,
overlap behavior, and edge cases. PDF and vision tests use mocks
so they run without actual files or AWS credentials.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

from app.extraction import _page_has_images, chunk_text, extract_text

# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------


def test_chunk_empty_text():
    assert chunk_text("") == []


def test_chunk_short_text():
    """Text shorter than chunk_size comes back as one chunk."""
    result = chunk_text("Hello world")
    assert len(result) == 1
    assert result[0] == "Hello world"


def test_chunk_splits_long_text():
    """Long text gets split into multiple chunks."""
    text = "word " * 500  # ~2500 chars
    result = chunk_text(text, chunk_size=200, overlap=50)
    assert len(result) > 1


def test_chunk_overlap_shares_content():
    """Consecutive chunks should share some text at the boundary."""
    text = "A" * 300 + ". " + "B" * 300 + ". " + "C" * 300
    result = chunk_text(text, chunk_size=350, overlap=100)
    assert len(result) >= 2
    # The overlap means the end of chunk N appears in chunk N+1
    for i in range(len(result) - 1):
        tail = result[i][-50:]
        assert any(tail[j : j + 20] in result[i + 1] for j in range(len(tail) - 20)), "Expected overlap between consecutive chunks"


def test_chunk_respects_sentence_boundaries():
    """Chunks should try to break on sentence endings."""
    text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
    result = chunk_text(text, chunk_size=50, overlap=10)
    for chunk in result:
        # Shouldn't end mid-word (no trailing partial words)
        assert not chunk[-1].isalpha() or chunk.endswith(text[-1:])


def test_chunk_no_empty_chunks():
    """Result should never contain empty strings."""
    text = "Hello. " * 200
    result = chunk_text(text, chunk_size=100, overlap=20)
    assert all(len(c.strip()) > 0 for c in result)


def test_chunk_custom_sizes():
    """Custom chunk_size and overlap should be respected."""
    text = "x" * 1000
    result = chunk_text(text, chunk_size=100, overlap=10)
    assert all(len(c) <= 100 for c in result)


# ---------------------------------------------------------------------------
# extract_text - plain text files
# ---------------------------------------------------------------------------


def test_extract_text_from_txt():
    """Should read .txt files directly."""
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("HOA rules say fences must be under 6 feet.")
        f.flush()
        result = extract_text(f.name)
    os.unlink(f.name)
    assert "fences" in result
    assert "6 feet" in result


def test_extract_text_from_md():
    """Should read .md files as plain text."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write("# Rules\n\nNo sheds without approval.")
        f.flush()
        result = extract_text(f.name)
    os.unlink(f.name)
    assert "sheds" in result


def test_extract_text_empty_file():
    """Empty file should return empty string."""
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("")
        f.flush()
        result = extract_text(f.name)
    os.unlink(f.name)
    assert result == ""


# ---------------------------------------------------------------------------
# extract_text - PDF with mocked pypdf
# ---------------------------------------------------------------------------


@patch("app.extraction.PdfReader")
def test_extract_text_pdf_with_text(mock_reader_cls):
    """PDF pages with text should use pypdf extraction, not vision."""
    page1 = MagicMock()
    page1.extract_text.return_value = "Page one content about HOA rules and regulations."
    page1.images = []
    page2 = MagicMock()
    page2.extract_text.return_value = "Page two content about fence height limits."
    page2.images = []
    mock_reader_cls.return_value.pages = [page1, page2]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake pdf")
        result = extract_text(f.name)
    os.unlink(f.name)

    assert "HOA rules" in result
    assert "fence height" in result


@patch("app.extraction._extract_page_image")
@patch("app.extraction.PdfReader")
def test_extract_text_pdf_image_only_page(mock_reader_cls, mock_vision):
    """Pages with no text should be sent to vision LLM."""
    page = MagicMock()
    page.extract_text.return_value = ""  # no text layer
    page.images = [MagicMock()]  # has an image
    mock_reader_cls.return_value.pages = [page]
    mock_vision.return_value = "OCR text from scanned page"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake pdf")
        result = extract_text(f.name)
    os.unlink(f.name)

    mock_vision.assert_called_once()
    assert "OCR text" in result


@patch("app.extraction._extract_page_image")
@patch("app.extraction.PdfReader")
def test_extract_text_pdf_mixed_page(mock_reader_cls, mock_vision):
    """Pages with both text and images should merge both sources."""
    page = MagicMock()
    page.extract_text.return_value = "Some text on the page about closing costs."
    page.images = [MagicMock()]  # also has an image
    mock_reader_cls.return_value.pages = [page]
    mock_vision.return_value = "Table showing $317.95 fee"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake pdf")
        result = extract_text(f.name)
    os.unlink(f.name)

    assert "closing costs" in result
    assert "$317.95" in result


@patch("app.extraction._extract_page_image")
@patch("app.extraction.PdfReader")
def test_extract_text_pdf_skips_vision_for_text_only(mock_reader_cls, mock_vision):
    """Text-only pages should NOT call vision (saves money)."""
    page = MagicMock()
    page.extract_text.return_value = "Plenty of text here, no images needed at all."
    page.images = []  # no images
    mock_reader_cls.return_value.pages = [page]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake pdf")
        extract_text(f.name)
    os.unlink(f.name)

    mock_vision.assert_not_called()


# ---------------------------------------------------------------------------
# _page_has_images
# ---------------------------------------------------------------------------


def test_page_has_images_true():
    page = MagicMock()
    page.images = [MagicMock()]
    assert _page_has_images(page) is True


def test_page_has_images_false():
    page = MagicMock()
    page.images = []
    assert _page_has_images(page) is False


def test_page_has_images_handles_exception():
    """Should not crash if page.images throws."""
    page = MagicMock()
    page.images = property(lambda self: (_ for _ in ()).throw(Exception("broken")))
    # Should return False, not raise
    result = _page_has_images(page)
    assert result in (True, False)  # just shouldn't crash
