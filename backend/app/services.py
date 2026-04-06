from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import boto3
from docx import Document as DocxDocument
from fastapi import UploadFile
from pypdf import PdfReader

logger = logging.getLogger(__name__)

_bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

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
from .storage import LocalStore


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(path)
        return "\n".join([(page.extract_text() or "") for page in reader.pages]).strip()
    if ext == ".docx":
        doc = DocxDocument(path)
        return "\n".join([p.text for p in doc.paragraphs]).strip()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


def _chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


async def ingest_file_to_store(store: LocalStore, file: UploadFile) -> UploadResponse:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    document_id = store.new_id("doc")
    job_id = store.new_job_id("ingest")

    filename = file.filename or f"{document_id}{ext}"
    destination = os.path.join(store.upload_dir, f"{document_id}_{filename}")

    content = await file.read()
    with open(destination, "wb") as f:
        f.write(content)

    text = _extract_text(destination)
    chunks = _chunk_text(text)

    document_type = _infer_document_type(filename, text)
    source_type = "uploaded_file"

    document = DocumentResponse(
        document_id=document_id,
        title=filename,
        source_type=source_type,
        source_url=destination,
        document_type=document_type,
        tags=[document_type],
        status="indexed" if chunks else "empty",
    )
    store.add_document(document)

    chunk_records: list[ChunkRecord] = []
    for i, chunk in enumerate(chunks, start=1):
        chunk_records.append(
            ChunkRecord(
                chunk_id=f"{document_id}_chunk_{i}",
                document_id=document_id,
                section_heading="Body",
                content=chunk,
                source_type=source_type,
                document_type=document_type,
                tags=[document_type],
            )
        )
    store.set_chunks(document_id, chunk_records)
    store.update_job_status(job_id, "completed")

    return UploadResponse(document_id=document_id, job_id=job_id)


def _infer_document_type(filename: str, text: str) -> str:
    probe = f"{filename} {text[:400].lower()}"
    rules = {
        "inspection": "inspection",
        "hoa": "hoa",
        "escrow": "escrow",
        "closing": "closing",
        "insurance": "insurance",
        "mortgage": "loan_mortgage",
        "loan": "loan_mortgage",
        "title": "title",
    }
    for needle, doc_type in rules.items():
        if needle in probe:
            return doc_type
    return "general"


def _score_chunk(query: str, content: str) -> float:
    q_tokens = [t.strip().lower() for t in query.split() if t.strip()]
    c = content.lower()
    if not q_tokens:
        return 0.0
    hits = sum(1 for t in q_tokens if t in c)
    return hits / len(q_tokens)


def _passes_filters(chunk: ChunkRecord, filters: dict) -> bool:
    if not filters:
        return True
    for k, v in filters.items():
        if k == "document_type" and chunk.document_type != v:
            return False
        if k == "source_type" and chunk.source_type != v:
            return False
        if k == "tag" and v not in chunk.tags:
            return False
    return True


def run_search(store: LocalStore, payload: SearchRequest) -> SearchResponse:
    start = time.time()
    scored: list[SearchResult] = []
    for doc in store.list_documents():
        chunks = store.get_chunks(doc.document_id)
        for chunk in chunks:
            if not _passes_filters(chunk, payload.filters):
                continue
            score = _score_chunk(payload.query, chunk.content)
            if score <= 0:
                continue
            scored.append(
                SearchResult(
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    title=doc.title,
                    snippet=chunk.content[:220],
                    score=round(score, 4),
                    source_type=chunk.source_type,
                    document_type=chunk.document_type,
                )
            )

    scored.sort(key=lambda r: r.score, reverse=True)
    total = len(scored)
    start_idx = max(0, (payload.page - 1) * payload.page_size)
    end_idx = start_idx + payload.page_size
    paged = scored[start_idx:end_idx]

    facets: dict[str, dict[str, int]] = {"document_type": {}, "source_type": {}}
    for r in scored:
        facets["document_type"][r.document_type] = facets["document_type"].get(r.document_type, 0) + 1
        facets["source_type"][r.source_type] = facets["source_type"].get(r.source_type, 0) + 1

    return SearchResponse(
        results=paged,
        total=total,
        facets=facets,
        timing_ms=int((time.time() - start) * 1000),
    )


def run_ask(store: LocalStore, payload: AskRequest) -> AskResponse:
    search = run_search(
        store,
        SearchRequest(
            query=payload.question,
            mode="hybrid",
            filters=payload.filters,
            page=1,
            page_size=max(1, payload.top_k),
        ),
    )

    citations = [
        Citation(
            document_id=r.document_id,
            chunk_id=r.chunk_id,
            title=r.title,
            snippet=r.snippet,
        )
        for r in search.results
    ]

    documents = sorted({c.document_id for c in citations})

    # Build context from chunks and ask Bedrock for a plain-English answer
    if citations:
        context = "\n\n".join(
            f"[{c.title}]\n{c.snippet}" for c in citations
        )
        prompt = (
            "You are a helpful assistant that answers questions about house documents "
            "(HOA rules, inspection reports, closing paperwork, etc). "
            "Answer the question below using ONLY the provided document excerpts. "
            "Give a clear, direct answer in plain English. "
            "If the excerpts don't contain enough information, say so.\n\n"
            f"Document excerpts:\n{context}\n\n"
            f"Question: {payload.question}"
        )
        try:
            resp = _bedrock.invoke_model(
                modelId=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"),
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )
            body = json.loads(resp["body"].read())
            answer = body["content"][0]["text"]
        except Exception as e:
            logger.warning("Bedrock call failed: %s", e)
            answer = "I found relevant documents but could not generate an AI answer right now. See the citations below."
    else:
        answer = "I could not find relevant content in the indexed documents for this question."

    suggested = [
        "Show me only inspection documents",
        "Filter results to HOA documents",
        "What changed in closing-related documents?",
    ]

    return AskResponse(
        answer=answer,
        citations=citations,
        documents=documents,
        suggested_queries=suggested,
    )
