"""Core services: file ingestion, OpenSearch-powered search, and Bedrock Q&A."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from docx import Document as DocxDocument
from fastapi import UploadFile
from pypdf import PdfReader

from .schemas import (
    AskRequest,
    AskResponse,
    ChunkRecord,
    Citation,
    DocumentResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UploadResponse,
)
from .pg_store import PgStore as LocalStore
from . import search as os_search
from .classifier import classify_document

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# Thread pool for CPU-bound work (PDF parsing, etc.)
_pool = ThreadPoolExecutor(max_workers=4)

# Lazy-init so the module still imports if AWS creds aren't configured
_bedrock = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    return _bedrock


# ---------------------------------------------------------------------------
# Text extraction (per-page, with vision LLM fallback for empty pages)
# ---------------------------------------------------------------------------

# Minimum chars to consider a page as having usable text
_MIN_PAGE_TEXT = 20


def _extract_page_image(page, page_num: int, path: str) -> str:
    """Render a PDF page to an image and send it to Claude vision for OCR."""
    try:
        from pdf2image import convert_from_path
        import base64
        from io import BytesIO

        # Render just this one page to a JPEG (150 DPI keeps it small and cheap)
        images = convert_from_path(path, first_page=page_num, last_page=page_num, dpi=150, fmt="jpeg")
        if not images:
            return ""

        buf = BytesIO()
        images[0].save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        resp = _get_bedrock().invoke_model(
            modelId=os.getenv("BEDROCK_VISION_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"),
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                        },
                        {
                            "type": "text",
                            "text": "Extract all text from this document page. Return only the text content, no commentary.",
                        },
                    ],
                }],
            }),
        )
        body = json.loads(resp["body"].read())
        text = body["content"][0]["text"]
        logger.info("Vision OCR extracted %d chars from page %d of %s", len(text), page_num, Path(path).name)
        return text
    except Exception as e:
        logger.warning("Vision OCR failed for page %d of %s: %s", page_num, Path(path).name, e)
        return ""


def _page_has_images(page) -> bool:
    """Check if a PDF page contains embedded images."""
    try:
        return len(page.images) > 0
    except Exception:
        # Fallback: check for image XObjects in resources
        try:
            resources = page.get("/Resources", {})
            xobjects = resources.get("/XObject", {})
            return any(
                xobjects[key].get("/Subtype") == "/Image"
                for key in xobjects
            )
        except Exception:
            return False


def _extract_text(path: str) -> str:
    """Pull plain text out of a PDF, DOCX, or text file.

    For PDFs, works per-page:
      - Text-only page: use extracted text
      - Image-only page (no text): send to vision LLM
      - Mixed page (text + images): use extracted text AND vision LLM, merge both
    """
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        reader = PdfReader(path)
        pages_text = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            has_text = len(text) >= _MIN_PAGE_TEXT
            has_images = _page_has_images(page)

            if has_text and not has_images:
                # Text-only page, no need for vision
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


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping windows. Tries to break on sentence boundaries."""
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


# ---------------------------------------------------------------------------
# Document type inference
# ---------------------------------------------------------------------------

_DOC_TYPE_RULES = {
    "inspection": "inspection",
    "hoa": "hoa",
    "architectural": "hoa",
    "escrow": "escrow",
    "closing": "closing",
    "insurance": "insurance",
    "mortgage": "loan_mortgage",
    "loan": "loan_mortgage",
    "appraisal": "appraisal",
    "title": "title",
    "deed": "deed",
    "disclosure": "disclosure",
}


def _infer_document_type(filename: str, text: str) -> str:
    """Guess the document category from filename and first chunk of text."""
    probe = f"{filename} {text[:500]}".lower()
    for needle, doc_type in _DOC_TYPE_RULES.items():
        if needle in probe:
            return doc_type
    return "general"


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _sanitize_filename(name: str) -> str:
    """Strip characters that cause issues in filenames and curl."""
    import re
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    clean = re.sub(r"[^\w\s\-.]", "", stem).strip().replace(" ", "_")
    return f"{clean}{ext}" if clean else f"file{ext}"


async def ingest_file_to_store(store: LocalStore, file: UploadFile) -> UploadResponse:
    """Save an uploaded file, extract text, chunk it, and index it."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    document_id = store.new_id("doc")
    job_id = store.new_job_id("ingest")
    original_name = file.filename or f"{document_id}{ext}"
    safe_name = _sanitize_filename(original_name)
    destination = os.path.join(store.upload_dir, f"{document_id}_{safe_name}")

    # Save to disk
    content = await file.read()
    with open(destination, "wb") as f:
        f.write(content)

    # Extract and chunk in a thread so we don't block the event loop
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(_pool, _extract_text, destination)
    chunks = await loop.run_in_executor(_pool, _chunk_text, text)

    # Auto-classify based on content and filename
    category, document_type, tags = classify_document(original_name, text)

    # Store document metadata (keep original name as title for display)
    store.add_document(DocumentResponse(
        document_id=document_id,
        title=original_name,
        source_type="uploaded_file",
        source_url=destination,
        document_type=document_type,
        category=category,
        tags=tags,
        status="indexed" if chunks else "empty",
    ))

    # Store chunks
    store.set_chunks(document_id, [
        ChunkRecord(
            chunk_id=f"{document_id}_chunk_{i}",
            document_id=document_id,
            section_heading="Body",
            content=chunk,
            source_type="uploaded_file",
            document_type=document_type,
            tags=tags,
        )
        for i, chunk in enumerate(chunks, start=1)
    ])

    store.update_job_status(job_id, "completed")

    # Index into OpenSearch for fast search
    try:
        os_search.index_chunks(document_id, original_name, [
            {"chunk_id": f"{document_id}_chunk_{i}", "content": c,
             "source_type": "uploaded_file", "document_type": document_type,
             "tags": tags}
            for i, c in enumerate(chunks, start=1)
        ])
    except Exception as e:
        logger.warning("OpenSearch indexing failed (search will use fallback): %s", e)

    # Push to BookStack, organized by category
    try:
        from .bookstack import BookStackClient
        bs = BookStackClient()
        if bs.configured:
            book_id = bs.find_or_create_book(category)
            page_id = bs.find_or_create_page(book_id, document_type.replace("_", " ").title())
            with open(destination, "rb") as fh:
                bs.upload_attachment(page_id, original_name, fh.read())
            logger.info("Pushed %s to BookStack: %s / %s", original_name, category, document_type)
    except Exception as e:
        logger.warning("BookStack push failed (non-fatal): %s", e)

    return UploadResponse(document_id=document_id, job_id=job_id)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "between",
    "through", "after", "before", "above", "below", "and", "but", "or",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very",
    "just", "that", "this", "it", "its", "my", "your", "our", "their",
    "what", "which", "who", "whom", "how", "when", "where", "why",
    "all", "each", "every", "any", "some", "such", "only",
}


def _score_chunk(query: str, content: str) -> float:
    """Score a chunk against a query. Rewards term coverage and proximity."""
    tokens = list(dict.fromkeys(
        t.lower() for t in query.split() if len(t) > 1 and t.lower() not in _STOP_WORDS
    ))
    if not tokens:
        return 0.0
    lower = content.lower()

    # Expand common synonyms so "HOA email" also matches "managing agent email"
    synonyms = {
        "hoa": ["hoa", "homeowner", "association", "managing agent", "management company"],
        "email": ["email", "e-mail"],
        "phone": ["phone", "telephone", "fax"],
        "contact": ["contact", "address", "phone", "email", "managing agent"],
        "rules": ["rules", "regulations", "guidelines", "restrictions", "covenants"],
        "inspection": ["inspection", "report", "condition"],
        "fence": ["fence", "fencing"],
        "shed": ["shed", "outbuilding", "structure"],
    }

    # Build expanded token set
    expanded = []
    for t in tokens:
        expanded.append(t)
        if t in synonyms:
            expanded.extend(synonyms[t])
    expanded = list(dict.fromkeys(expanded))

    # Base: fraction of original query terms (or their synonyms) found
    hits = []
    for t in tokens:
        group = synonyms.get(t, [t])
        if any(g in lower for g in group):
            hits.append(t)
    if not hits:
        return 0.0
    coverage = len(hits) / len(tokens)

    # Bonus: reward chunks where hits appear close together
    positions = []
    for t in expanded:
        idx = lower.find(t)
        if idx >= 0:
            positions.append(idx)
    proximity = 0.0
    if len(positions) > 1:
        positions.sort()
        span = positions[-1] - positions[0]
        proximity = max(0, 0.3 * (1 - span / max(len(content), 1)))

    return coverage + proximity


def _passes_filters(chunk: ChunkRecord, filters: dict) -> bool:
    for key, val in filters.items():
        if key == "document_type" and chunk.document_type != val:
            return False
        if key == "source_type" and chunk.source_type != val:
            return False
        if key == "tag" and val not in chunk.tags:
            return False
    return True


def run_search(store: LocalStore, payload: SearchRequest) -> SearchResponse:
    """Search chunks via OpenSearch (BM25). Falls back to keyword scan if OpenSearch is down."""
    start = time.time()

    try:
        data = os_search.search_chunks(
            query=payload.query,
            filters=payload.filters,
            page=payload.page,
            page_size=payload.page_size,
        )
        results = [SearchResult(**r) for r in data["results"]]
        return SearchResponse(
            results=results,
            total=data["total"],
            facets=data["facets"],
            timing_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        logger.warning("OpenSearch search failed, using fallback: %s", e)

    # Fallback: scan Postgres chunks with keyword scoring
    scored: list[SearchResult] = []
    for doc, chunk in store.all_chunks():
        if not _passes_filters(chunk, payload.filters):
            continue
        score = _score_chunk(payload.query, chunk.content)
        if score <= 0:
            continue
        scored.append(SearchResult(
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            title=doc.title,
            snippet=chunk.content[:300],
            score=round(score, 4),
            source_type=chunk.source_type,
            document_type=chunk.document_type,
        ))

    scored.sort(key=lambda r: r.score, reverse=True)
    offset = max(0, (payload.page - 1) * payload.page_size)
    paged = scored[offset : offset + payload.page_size]

    facets: dict[str, dict[str, int]] = {"document_type": {}, "source_type": {}}
    for r in scored:
        facets["document_type"][r.document_type] = facets["document_type"].get(r.document_type, 0) + 1
        facets["source_type"][r.source_type] = facets["source_type"].get(r.source_type, 0) + 1

    return SearchResponse(
        results=paged,
        total=len(scored),
        facets=facets,
        timing_ms=int((time.time() - start) * 1000),
    )


# ---------------------------------------------------------------------------
# Ask (RAG with Bedrock)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions about house documents "
    "(HOA rules, inspection reports, closing paperwork, insurance, etc). "
    "Answer the question using ONLY the provided document excerpts. "
    "Give a clear, direct answer in plain English that a non-expert would understand. "
    "If the excerpts don't contain enough information to answer, say so honestly."
)


def run_ask(store: LocalStore, payload: AskRequest) -> AskResponse:
    """Retrieve relevant chunks then ask Bedrock for a plain-English answer."""
    search = run_search(store, SearchRequest(
        query=payload.question,
        mode="hybrid",
        filters=payload.filters,
        page=1,
        page_size=max(1, payload.top_k) * 5,
    ))

    # Smart dedup: spread across documents, but if few documents match,
    # allow multiple chunks from the same doc to fill the quota
    seen_docs: dict[str, list[SearchResult]] = {}
    for r in search.results:
        seen_docs.setdefault(r.document_id, []).append(r)

    top: list[SearchResult] = []
    # First pass: best chunk per document
    for doc_id, chunks in seen_docs.items():
        top.append(chunks[0])
    top.sort(key=lambda r: r.score, reverse=True)
    top = top[: payload.top_k]

    # Second pass: if we have room, fill with more chunks from top-scoring docs
    if len(top) < payload.top_k:
        used = {r.chunk_id for r in top}
        for r in search.results:
            if r.chunk_id not in used:
                top.append(r)
                used.add(r.chunk_id)
                if len(top) >= payload.top_k:
                    break

    citations = [
        Citation(
            document_id=r.document_id,
            chunk_id=r.chunk_id,
            title=r.title,
            snippet=r.snippet,
        )
        for r in top
    ]
    documents = sorted({c.document_id for c in citations})

    if not citations:
        return AskResponse(
            answer="I could not find relevant content in the indexed documents for this question.",
            citations=[],
            documents=[],
            suggested_queries=[],
        )

    # Build the prompt with FULL chunk content from Postgres (not the short snippet)
    # This gives Bedrock much more context to find the right answer
    context_parts = []
    for r in top:
        full_chunks = store.get_chunks(r.document_id)
        # Find the matching chunk and include it plus its neighbors for context
        for idx, ch in enumerate(full_chunks):
            if ch.chunk_id == r.chunk_id:
                parts = []
                if idx > 0:
                    parts.append(full_chunks[idx - 1].content)
                parts.append(ch.content)
                if idx < len(full_chunks) - 1:
                    parts.append(full_chunks[idx + 1].content)
                context_parts.append(f"[{r.title}]\n" + "\n".join(parts))
                break
        else:
            context_parts.append(f"[{r.title}]\n{r.snippet}")

    context = "\n\n---\n\n".join(context_parts)
    user_msg = f"Document excerpts:\n{context}\n\nQuestion: {payload.question}"

    try:
        resp = _get_bedrock().invoke_model(
            modelId=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"),
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            }),
        )
        answer = json.loads(resp["body"].read())["content"][0]["text"]
    except Exception as e:
        logger.warning("Bedrock call failed: %s", e)
        answer = (
            "I found relevant documents but could not generate an AI answer right now. "
            "See the citations below."
        )

    return AskResponse(
        answer=answer,
        citations=citations,
        documents=documents,
        suggested_queries=[],
    )
