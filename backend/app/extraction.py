"""Text extraction from PDFs, Word docs, and plain text files.

Handles three types of PDF pages:
  - Text pages: extracted directly with pypdf (free, instant)
  - Image-only pages: sent to vision LLM via Bedrock Converse API (~$0.002/page)
  - Mixed pages: text extracted AND image sent to vision, results merged

Uses the Bedrock Converse API so any supported model works (Claude, Nova, Llama, etc).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# If a page has fewer chars than this, we treat it as "no usable text"
MIN_PAGE_TEXT = 20

# Lazy-init so the module imports even without AWS creds
_bedrock = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        import boto3

        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    return _bedrock


def _page_has_images(page) -> bool:
    """Check if a PDF page contains embedded images."""
    try:
        return len(page.images) > 0
    except Exception:
        try:
            resources = page.get("/Resources", {})
            xobjects = resources.get("/XObject", {})
            return any(xobjects[key].get("/Subtype") == "/Image" for key in xobjects)
        except Exception:
            return False


def _extract_page_image(page, page_num: int, path: str) -> str:
    """Render a PDF page to an image and send it to a vision LLM for OCR."""
    try:
        from io import BytesIO

        from pdf2image import convert_from_path

        # Render just this one page to JPEG (150 DPI keeps it small and cheap)
        images = convert_from_path(
            path,
            first_page=page_num,
            last_page=page_num,
            dpi=150,
            fmt="jpeg",
        )
        if not images:
            return ""

        buf = BytesIO()
        images[0].save(buf, format="JPEG", quality=80)

        model_id = os.getenv("BEDROCK_VISION_MODEL_ID", "")
        resp = _get_bedrock().converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": "jpeg",
                                "source": {"bytes": buf.getvalue()},
                            },
                        },
                        {
                            "text": "Extract all text from this document page. Return only the text content, no commentary.",
                        },
                    ],
                },
            ],
            inferenceConfig={"maxTokens": 4096},
        )
        text = resp["output"]["message"]["content"][0]["text"]

        # Track usage if enabled
        if os.getenv("TRACK_USAGE", "true").lower() == "true":
            usage = resp.get("usage", {})
            from .pricing import estimate_cost
            from .db import get_conn

            try:
                cost = estimate_cost(
                    model_id,
                    usage.get("inputTokens", 0),
                    usage.get("outputTokens", 0),
                    os.getenv("AWS_REGION", "us-east-1"),
                )
                conn = get_conn()
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO token_usage
                           (model_id, operation, input_tokens, output_tokens, estimated_cost_usd)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (model_id, "vision", usage.get("inputTokens", 0),
                         usage.get("outputTokens", 0), cost),
                    )
                conn.close()
            except Exception:
                pass  # non-fatal

        logger.info(
            "Vision OCR extracted %d chars from page %d of %s",
            len(text),
            page_num,
            Path(path).name,
        )
        return text
    except Exception as e:
        logger.warning("Vision OCR failed for page %d of %s: %s", page_num, Path(path).name, e)
        return ""


def extract_text(path: str) -> str:
    """Pull plain text out of a PDF, DOCX, or text file.

    For PDFs, works per-page:
      - Text-only page: use extracted text
      - Image-only page (no text): send to vision LLM
      - Mixed page (text + images): extract text AND send to vision, merge both
    """
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        reader = PdfReader(path)
        pages_text = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            has_text = len(text) >= MIN_PAGE_TEXT
            has_images = _page_has_images(page)

            if has_text and not has_images:
                pages_text.append(text)
            elif has_text and has_images:
                # Mixed page: get vision description of images, combine with text
                ocr_text = _extract_page_image(page, i, path)
                if ocr_text and ocr_text.strip() != text.strip():
                    pages_text.append(f"{text}\n\n[Image content]\n{ocr_text}")
                else:
                    pages_text.append(text)
            else:
                # No text, send whole page to vision
                ocr_text = _extract_page_image(page, i, path)
                if ocr_text:
                    pages_text.append(ocr_text)
        return "\n".join(pages_text).strip()

    if ext == ".docx":
        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs).strip()

    # .txt, .md, or anything else
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping windows, breaking on sentence boundaries.

    Each chunk is roughly chunk_size characters with overlap characters
    shared between consecutive chunks so context isn't lost at boundaries.
    """
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        # Try to break on a sentence boundary instead of mid-word
        if end < len(text):
            for sep in (". ", ".\n", "\n\n", "\n", " "):
                boundary = text.rfind(sep, start + chunk_size // 2, end)
                if boundary != -1:
                    end = boundary + len(sep)
                    break
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [c for c in chunks if c]
