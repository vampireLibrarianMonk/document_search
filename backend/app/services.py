"""Core services: ingestion, search, and Bedrock-powered Q&A.

This is the main business logic layer. It ties together:
  - extraction.py for reading document content
  - classifier.py for auto-categorizing documents
  - search.py for OpenSearch indexing and retrieval
  - pg_store.py for persistent storage
  - Bedrock Claude for answering questions
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import UploadFile

from . import search as os_search
from .classifier import classify_document
from .extraction import chunk_text, extract_text
from .pg_store import PgStore
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

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# Thread pool for CPU-bound work (PDF parsing, image rendering)
_pool = ThreadPoolExecutor(max_workers=4)

# Lazy-init Bedrock client
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


# ---------------------------------------------------------------------------
# Ingestion: upload -> extract -> chunk -> classify -> store -> index
# ---------------------------------------------------------------------------


def _sanitize_filename(name: str) -> str:
    """Strip characters that cause issues in filenames."""
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    clean = re.sub(r"[^\w\s\-.]", "", stem).strip().replace(" ", "_")
    return f"{clean}{ext}" if clean else f"file{ext}"


async def ingest_file_to_store(store: PgStore, file: UploadFile) -> UploadResponse:
    """Save an uploaded file, extract text, chunk it, classify it, and index it.

    This is the main ingestion pipeline. It:
      1. Saves the raw file to disk
      2. Extracts text (with vision LLM fallback for scanned pages)
      3. Splits text into overlapping chunks
      4. Auto-classifies the document by category and type
      5. Stores metadata in Postgres and chunks in Postgres + OpenSearch
      6. Pushes the file to BookStack organized by category
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    document_id = store.new_id("doc")
    job_id = store.new_job_id("ingest")
    original_name = file.filename or f"{document_id}{ext}"
    safe_name = _sanitize_filename(original_name)
    destination = os.path.join(store.upload_dir, f"{document_id}_{safe_name}")

    # Save the raw file
    content = await file.read()
    with open(destination, "wb") as f:
        f.write(content)

    # Extract text and chunk it (in a thread so we don't block the event loop)
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(_pool, extract_text, destination)
    chunks = await loop.run_in_executor(_pool, chunk_text, text)

    # Figure out what kind of document this is
    category, document_type, tags = classify_document(original_name, text)

    # Save to Postgres
    store.add_document(
        DocumentResponse(
            document_id=document_id,
            title=original_name,
            source_type="uploaded_file",
            source_url=destination,
            document_type=document_type,
            category=category,
            tags=tags,
            status="indexed" if chunks else "empty",
        ),
    )

    store.set_chunks(
        document_id,
        [
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
        ],
    )

    store.update_job_status(job_id, "completed")

    # Index into OpenSearch for fast search
    try:
        os_search.index_chunks(
            document_id,
            original_name,
            [
                {
                    "chunk_id": f"{document_id}_chunk_{i}",
                    "content": c,
                    "source_type": "uploaded_file",
                    "document_type": document_type,
                    "tags": tags,
                }
                for i, c in enumerate(chunks, start=1)
            ],
        )
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
# Search: OpenSearch BM25 with Postgres keyword fallback
# ---------------------------------------------------------------------------


def run_search(store: PgStore, payload: SearchRequest) -> SearchResponse:
    """Search chunks via OpenSearch BM25. Falls back to keyword scan if OpenSearch is down."""
    import time

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

    # Fallback: scan all chunks from Postgres with simple keyword scoring
    scored: list[SearchResult] = []
    for doc, chunk in store.all_chunks():
        score = _keyword_score(payload.query, chunk.content)
        if score <= 0:
            continue
        scored.append(
            SearchResult(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                title=doc.title,
                snippet=chunk.content[:300],
                score=round(score, 4),
                source_type=chunk.source_type,
                document_type=chunk.document_type,
            ),
        )

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


def _keyword_score(query: str, content: str) -> float:
    """Simple keyword overlap score used as a fallback when OpenSearch is down."""
    stop = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "and",
        "but",
        "or",
        "not",
        "my",
        "your",
        "what",
        "how",
    }
    tokens = [t.lower() for t in query.split() if len(t) > 1 and t.lower() not in stop]
    if not tokens:
        return 0.0
    lower = content.lower()
    hits = sum(1 for t in tokens if t in lower)
    return hits / len(tokens) if hits else 0.0


# ---------------------------------------------------------------------------
# Ask: retrieve chunks, send to Bedrock, get a plain-English answer
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions about house documents "
    "(HOA rules, inspection reports, closing paperwork, insurance, etc). "
    "Answer the question using ONLY the provided document excerpts. "
    "Give a clear, direct answer in plain English that a non-expert would understand. "
    "If the excerpts don't contain enough information to answer, say so honestly."
)


def run_ask(store: PgStore, payload: AskRequest) -> AskResponse:
    """Retrieve relevant chunks then ask Bedrock for a plain-English answer.

    The flow:
      1. Search for chunks matching the question
      2. Deduplicate: spread across documents, but fill remaining slots from top docs
      3. For each matched chunk, pull the full content plus neighbors from Postgres
      4. Send all that context to Bedrock Claude
      5. Return the answer with citations
    """
    # Step 1: search
    search = run_search(
        store,
        SearchRequest(
            query=payload.question,
            mode="hybrid",
            filters=payload.filters,
            page=1,
            page_size=max(1, payload.top_k) * 5,
        ),
    )

    # Step 2: smart dedup - spread across documents first, then fill gaps
    seen_docs: dict[str, list[SearchResult]] = {}
    for r in search.results:
        seen_docs.setdefault(r.document_id, []).append(r)

    top: list[SearchResult] = []
    for doc_id, chunks in seen_docs.items():
        top.append(chunks[0])
    top.sort(key=lambda r: r.score, reverse=True)
    top = top[: payload.top_k]

    if len(top) < payload.top_k:
        used = {r.chunk_id for r in top}
        for r in search.results:
            if r.chunk_id not in used:
                top.append(r)
                used.add(r.chunk_id)
                if len(top) >= payload.top_k:
                    break

    # Build citations from the top results
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

    # Step 3: pull full chunk content plus neighbors for richer context
    context_parts = []
    for r in top:
        full_chunks = store.get_chunks(r.document_id)
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

    # Step 4: ask Bedrock
    context = "\n\n---\n\n".join(context_parts)
    user_msg = f"Document excerpts:\n{context}\n\nQuestion: {payload.question}"

    try:
        model_id = os.getenv("BEDROCK_MODEL_ID", "")
        resp = _get_bedrock().converse(
            modelId=model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_msg}]}],
            inferenceConfig={"maxTokens": 1024},
        )
        answer = resp["output"]["message"]["content"][0]["text"]

        # Track usage if enabled
        if os.getenv("TRACK_USAGE", "true").lower() == "true":
            usage = resp.get("usage", {})
            from .pricing import estimate_cost

            cost = estimate_cost(
                model_id,
                usage.get("inputTokens", 0),
                usage.get("outputTokens", 0),
                os.getenv("AWS_REGION", "us-east-1"),
            )
            store.log_usage(
                model_id=model_id,
                operation="ask",
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                estimated_cost_usd=cost,
            )
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
