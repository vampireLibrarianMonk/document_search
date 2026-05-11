"""FastAPI routes for the House Document Search API."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import search as os_search
from .bookstack import BookStackClient
from .confluence import ConfluenceClient
from .pg_store import PgStore
from .schemas import (
    AskRequest,
    AskResponse,
    BulkUploadResponse,
    ChunkListResponse,
    ConfluenceSyncRequest,
    DocumentResponse,
    JobResponse,
    SearchRequest,
    SearchResponse,
    UploadResponse,
)
from .services import ingest_file_to_store, run_ask, run_search


@asynccontextmanager
async def lifespan(app):
    """Initialize OpenSearch index on startup."""
    try:
        os_search.ensure_index()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("OpenSearch init failed: %s", e)
    yield


app = FastAPI(title="House Document Search API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://app.localhost",
        "https://api.localhost",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = PgStore()
_logger = logging.getLogger(__name__)


# -- Health / root --


@app.get("/")
def root():
    return {"message": "House Document Search API", "docs": "/docs"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


_confluence = ConfluenceClient()
_bookstack = BookStackClient()


# -- Ingestion --


@app.post("/ingest/upload", response_model=UploadResponse)
async def ingest_upload(file: UploadFile = File(...)) -> UploadResponse:
    """Upload and index a single document."""
    try:
        return await ingest_file_to_store(store, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/ingest/upload-bulk", response_model=BulkUploadResponse)
async def ingest_upload_bulk(files: list[UploadFile] = File(...)) -> BulkUploadResponse:
    """Upload and index multiple documents concurrently."""
    import asyncio

    async def _ingest_one(file: UploadFile) -> tuple[UploadResponse | None, str | None]:
        try:
            return await ingest_file_to_store(store, file), None
        except Exception as exc:
            return None, f"{file.filename}: {exc}"

    results = await asyncio.gather(*[_ingest_one(f) for f in files])
    uploaded = [r for r, _ in results if r]
    errors = [e for _, e in results if e]
    return BulkUploadResponse(uploaded=uploaded, errors=errors)


@app.post("/ingest/upload-queue")
async def ingest_upload_queue(files: list[UploadFile] = File(...)):
    """Save files to disk and queue them for background processing. Returns immediately."""
    import uuid
    from pathlib import Path

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    queued = []

    from .db import get_conn
    from .services import SUPPORTED_EXTENSIONS, _sanitize_filename

    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        content = await f.read()
        filename = f.filename or f"file{ext}"
        safe_name = _sanitize_filename(filename)
        job_id = store.new_id("job")
        dest = os.path.join(store.upload_dir, f"{job_id}_{safe_name}")
        with open(dest, "wb") as fh:
            fh.write(content)

        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (job_id, status, batch_id, file_path, filename) VALUES (%s, %s, %s, %s, %s)",
                (job_id, "queued", batch_id, dest, filename),
            )
        conn.close()
        queued.append({"job_id": job_id, "filename": filename})

    return {"batch_id": batch_id, "queued": len(queued), "jobs": queued}


@app.get("/ingest/upload-status/{batch_id}")
async def ingest_upload_status(batch_id: str):
    """SSE stream that emits progress as jobs in a batch complete."""
    import asyncio
    import json as _json

    from starlette.responses import StreamingResponse

    from .db import get_conn

    async def _stream():
        seen_done: set = set()
        while True:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT job_id, status, filename, category, document_type, document_id FROM jobs WHERE batch_id = %s",
                    (batch_id,),
                )
                rows = cur.fetchall()
            conn.close()

            total = len(rows)
            if total == 0:
                yield f"data: {_json.dumps({'type': 'error', 'error': 'Batch not found'})}\n\n"
                return

            for job_id, status, filename, category, doc_type, doc_id in rows:
                if job_id in seen_done:
                    continue
                if status == "completed":
                    seen_done.add(job_id)
                    yield f"data: {_json.dumps({'type': 'done', 'file': filename, 'category': category or 'Uncategorized', 'document_type': doc_type or 'general', 'document_id': doc_id, 'current': len(seen_done), 'total': total})}\n\n"
                elif status.startswith("failed"):
                    seen_done.add(job_id)
                    yield f"data: {_json.dumps({'type': 'error', 'file': filename, 'error': status, 'current': len(seen_done), 'total': total})}\n\n"
                elif status == "cancelled":
                    seen_done.add(job_id)

            done_count = len(seen_done)
            if done_count >= total:
                ok = sum(1 for _, s, *_ in rows if s == "completed")
                fail = sum(1 for _, s, *_ in rows if s.startswith("failed"))
                yield f"data: {_json.dumps({'type': 'complete', 'uploaded': ok, 'errors': fail, 'total': total})}\n\n"
                return

            await asyncio.sleep(1)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/ingest/upload-stream")
async def ingest_upload_stream(files: list[UploadFile] = File(...)):
    """Upload multiple files with SSE progress updates per file."""
    import json as _json
    from io import BytesIO

    from starlette.datastructures import UploadFile as StarletteUpload
    from starlette.responses import StreamingResponse

    # Read file metadata upfront (names + raw bytes in batches to limit memory)
    # We must read all content before the response starts because the request
    # body becomes unavailable once streaming begins.
    BATCH_SIZE = 10
    file_batches: list[list[tuple[str, bytes]]] = []
    current_batch: list[tuple[str, bytes]] = []

    for f in files:
        content = await f.read()
        current_batch.append((f.filename or "unknown", content))
        if len(current_batch) >= BATCH_SIZE:
            file_batches.append(current_batch)
            current_batch = []
    if current_batch:
        file_batches.append(current_batch)

    total = sum(len(b) for b in file_batches)

    # Create a job ID for this batch so it can be cancelled
    batch_job_id = store.new_job_id("upload_batch")

    # Create a job ID for this batch so it can be cancelled
    batch_job_id = store.new_job_id("upload_batch")

    async def _stream():
        ok, fail = 0, 0
        file_num = 0
        for batch in file_batches:
            for name, content in batch:
                file_num += 1

                # Check for cancellation
                from .db import get_conn as _get_conn

                _conn = _get_conn()
                with _conn.cursor() as _cur:
                    _cur.execute(
                        "SELECT status FROM jobs WHERE job_id = %s",
                        (batch_job_id,),
                    )
                    _row = _cur.fetchone()
                _conn.close()
                if _row and _row[0] == "cancelled":
                    yield f"data: {_json.dumps({'type': 'complete', 'uploaded': ok, 'errors': fail, 'total': total, 'cancelled': True})}\n\n"
                    return

                yield f"data: {_json.dumps({'type': 'progress', 'file': name, 'step': 'uploading', 'current': file_num, 'total': total})}\n\n"
                try:
                    fake_file = StarletteUpload(filename=name, file=BytesIO(content))
                    result = await ingest_file_to_store(store, fake_file)
                    ok += 1
                    doc = store.get_document(result.document_id)
                    cat = doc.category if doc else "Uncategorized"
                    dtype = doc.document_type if doc else "general"
                    msg = {
                        "type": "done",
                        "file": name,
                        "current": file_num,
                        "total": total,
                        "document_id": result.document_id,
                        "category": cat,
                        "document_type": dtype,
                        "log": result.processing_log,
                    }
                    yield f"data: {_json.dumps(msg)}\n\n"
                except Exception as exc:
                    fail += 1
                    yield f"data: {_json.dumps({'type': 'error', 'file': name, 'current': file_num, 'total': total, 'error': str(exc)})}\n\n"

        store.update_job_status(batch_job_id, "completed")
        yield f"data: {_json.dumps({'type': 'complete', 'uploaded': ok, 'errors': fail, 'total': total})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# -- Search / Ask --


@app.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest) -> SearchResponse:
    return run_search(store, payload)


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    return run_ask(store, payload)


# -- Documents --


@app.get("/documents", response_model=list[DocumentResponse])
def list_documents() -> list[DocumentResponse]:
    return store.list_documents()


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str) -> DocumentResponse:
    doc = store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.get("/documents/{document_id}/file")
def get_document_file(document_id: str):
    """Download the original uploaded file."""
    from fastapi.responses import FileResponse

    doc = store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not os.path.isfile(doc.source_url):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        doc.source_url,
        filename=doc.title,
        media_type="application/octet-stream",
    )


@app.get("/documents/{document_id}/chunks", response_model=ChunkListResponse)
def get_document_chunks(document_id: str) -> ChunkListResponse:
    if not store.get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return ChunkListResponse(document_id=document_id, chunks=store.get_chunks(document_id))


# -- Confluence (placeholder) --


@app.post("/sources/confluence/sync", response_model=BulkUploadResponse)
async def confluence_sync(req: ConfluenceSyncRequest) -> BulkUploadResponse:
    """Pull PDF attachments from Confluence pages and ingest them."""
    if not _confluence.configured:
        raise HTTPException(status_code=400, detail="Confluence credentials not configured")

    uploaded: list[UploadResponse] = []
    errors: list[str] = []

    for space_key in req.space_keys or ["HOUSE"]:
        try:
            pages = _confluence.get_pages_in_space(space_key)
        except Exception as e:
            errors.append(f"Failed to list pages in {space_key}: {e}")
            continue

        for page in pages:
            try:
                attachments = _confluence.get_attachments(page["id"])
                for att in attachments:
                    title = att.get("title", "")
                    if not title.lower().endswith(".pdf"):
                        continue
                    download_path = att.get("_links", {}).get("download", "")
                    if not download_path:
                        continue

                    # Download the PDF
                    pdf_bytes = _confluence.download_attachment(download_path)

                    # Wrap as an UploadFile so we can reuse the ingest pipeline
                    from starlette.datastructures import UploadFile as StarletteUpload

                    fake_file = StarletteUpload(filename=title, file=pdf_bytes)
                    result = await ingest_file_to_store(store, fake_file)
                    uploaded.append(result)
            except Exception as e:
                errors.append(f"{page.get('title', '?')}: {e}")

    return BulkUploadResponse(uploaded=uploaded, errors=errors)


# -- BookStack sync --


@app.post("/sources/bookstack/sync", response_model=BulkUploadResponse)
async def bookstack_sync() -> BulkUploadResponse:
    """Pull all PDF attachments from BookStack and ingest them."""
    if not _bookstack.configured:
        raise HTTPException(status_code=400, detail="BookStack credentials not configured. Set BOOKSTACK_TOKEN_ID and BOOKSTACK_TOKEN_SECRET.")

    uploaded: list[UploadResponse] = []
    errors: list[str] = []

    try:
        pdf_attachments = _bookstack.get_all_pdf_attachments()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to BookStack: {e}") from e

    for att in pdf_attachments:
        try:
            name, content = _bookstack.download_attachment(att["id"])
            from starlette.datastructures import UploadFile as StarletteUpload

            fake_file = StarletteUpload(filename=name, file=content)
            result = await ingest_file_to_store(store, fake_file)
            uploaded.append(result)
        except Exception as e:
            errors.append(f"{att.get('name', '?')}: {e}")

    return BulkUploadResponse(uploaded=uploaded, errors=errors)


# -- Document Generation --


@app.post("/generate")
def generate_document(body: dict):
    """Generate a document from a user prompt, grounded in indexed documents."""

    from .generator import generate_markdown

    prompt = body.get("prompt", "").strip()
    fmt = body.get("format", "md").lower()
    top_k = body.get("top_k", 15)
    filters = body.get("filters", {})
    document_ids = body.get("document_ids")  # optional: specific docs to use

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")
    if fmt not in ("md", "docx", "pdf", "png", "pptx"):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    context_parts = []

    if document_ids:
        # User selected specific documents: use all their chunks as context
        for doc_id in document_ids:
            doc = store.get_document(doc_id)
            if not doc:
                continue
            chunks = store.get_chunks(doc_id)
            if chunks:
                text = "\n".join(c.content for c in chunks)
                context_parts.append(f"[{doc.title}]\n{text}")
    else:
        # Auto-search: retrieve relevant chunks (same as Ask AI)
        search_result = run_search(
            store,
            SearchRequest(
                query=prompt,
                mode="hybrid",
                filters=filters,
                page=1,
                page_size=top_k * 5,
            ),
        )

        seen: dict[str, list] = {}
        for r in search_result.results:
            seen.setdefault(r.document_id, []).append(r)
        top = [chunks[0] for chunks in seen.values()]
        top.sort(key=lambda r: r.score, reverse=True)
        top = top[:top_k]

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

    context = "\n\n---\n\n".join(context_parts)

    if not context.strip():
        raise HTTPException(
            status_code=404,
            detail="No relevant documents found. Upload documents first.",
        )

    # Generate markdown content via Bedrock
    markdown_content = generate_markdown(prompt, context, manual_mode=bool(document_ids), fmt=fmt)

    return {"markdown": markdown_content, "format": fmt}


@app.post("/generate/detect-format")
def generate_detect_format(body: dict):
    """Use a cheap LLM call to detect the best output format for a prompt."""
    import boto3

    prompt = body.get("prompt", "").strip()
    if not prompt:
        return {"format": "md", "reason": "no prompt"}

    model_id = os.getenv(
        "BEDROCK_DETECT_MODEL_ID",
        os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"),
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )

    try:
        resp = client.converse(
            modelId=model_id,
            system=[
                {
                    "text": (
                        "You detect the best output format for a document request. "
                        "Reply with EXACTLY this format: FORMAT|REASON\n"
                        "FORMAT must be one of: md, docx, pdf, png, pptx\n"
                        "REASON is 2-4 words explaining why.\n\n"
                        "Examples:\n"
                        "- 'Write a letter to my HOA' → docx|formal letter\n"
                        "- 'Create a presentation about rules' → pptx|slide deck\n"
                        "- 'Fill out the modification form' → docx|fillable form\n"
                        "- 'Make a quick reference card' → png|visual reference\n"
                        "- 'Generate a report with all fees' → pdf|formal report\n"
                        "- 'Summarize the bylaws' → md|text summary"
                    ),
                },
            ],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 20},
        )
        result = resp["output"]["message"]["content"][0]["text"].strip()
        parts = result.split("|", 1)
        fmt = parts[0].strip().lower()
        reason = parts[1].strip() if len(parts) > 1 else "detected"

        if fmt not in ("md", "docx", "pdf", "png", "pptx"):
            fmt = "md"
            reason = "general content"

        return {"format": fmt, "reason": reason}
    except Exception:
        return {"format": "md", "reason": "detection unavailable"}


@app.post("/generate/convert")
def generate_convert(body: dict):
    """Convert previously generated markdown to a different format (no Bedrock call)."""
    import base64

    from .generator import (
        convert_to_docx,
        convert_to_pdf,
        convert_to_png,
        convert_to_pptx,
    )

    markdown = body.get("markdown", "")
    fmt = body.get("format", "md")

    if not markdown:
        raise HTTPException(status_code=400, detail="No markdown content provided")

    if fmt == "docx":
        file_bytes = convert_to_docx(markdown)
        filename = "generated.docx"
    elif fmt == "pdf":
        file_bytes = convert_to_pdf(markdown)
        filename = "generated.pdf"
    elif fmt == "png":
        file_bytes = convert_to_png(markdown)
        filename = "generated.png"
    elif fmt == "pptx":
        file_bytes = convert_to_pptx(markdown)
        filename = "generated.pptx"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    return {"file_b64": base64.b64encode(file_bytes).decode(), "filename": filename}


# -- Admin --


@app.delete("/documents/{document_id}")
def delete_document(document_id: str):
    """Delete a single document and its chunks from all stores."""
    doc = store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        os_search.get_client().delete_by_query(
            index=os_search.INDEX_NAME,
            body={"query": {"term": {"document_id": document_id}}},
            ignore=[404],
        )
    except Exception as e:
        _logger.warning("OpenSearch cleanup failed for %s: %s", document_id, e)

    try:
        if _bookstack.configured:
            _bookstack.delete_attachment_by_name(doc.title)
    except Exception as e:
        _logger.warning("BookStack cleanup failed for %s: %s", doc.title, e)

    store.delete_document(document_id)
    return {"deleted": document_id}


@app.delete("/documents")
def delete_all_documents():
    """Delete all documents and chunks from all stores, including files on disk."""
    try:
        os_search.get_client().delete_by_query(
            index=os_search.INDEX_NAME,
            body={"query": {"match_all": {}}},
            ignore=[404],
        )
    except Exception as e:
        _logger.warning("OpenSearch bulk cleanup failed: %s", e)

    try:
        if _bookstack.configured:
            _bookstack.delete_all_attachments()
            _bookstack.delete_empty_pages_and_books()
    except Exception as e:
        _logger.warning("BookStack bulk cleanup failed: %s", e)

    # Cancel any in-progress jobs
    from .db import get_conn
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET status = 'cancelled' WHERE status IN ('queued', 'processing')")
        cur.execute("DELETE FROM jobs")
    conn.close()

    # Clean up files on disk
    upload_dir = store.upload_dir
    if os.path.isdir(upload_dir):
        for f in os.listdir(upload_dir):
            filepath = os.path.join(upload_dir, f)
            try:
                os.unlink(filepath)
            except Exception:
                pass  # nosec B110

    count = store.delete_all_documents()
    return {"deleted": count}


@app.get("/admin/jobs", response_model=list[JobResponse])
def admin_jobs() -> list[JobResponse]:
    return store.get_jobs()


@app.post("/admin/reindex")
def admin_reindex():
    """Rebuild the OpenSearch index from Postgres."""
    os_search.ensure_index()
    docs = store.list_documents()
    indexed = 0
    for doc in docs:
        chunks = store.get_chunks(doc.document_id)
        if chunks:
            os_search.index_chunks(
                doc.document_id,
                doc.title,
                [
                    {
                        "chunk_id": c.chunk_id,
                        "content": c.content,
                        "source_type": c.source_type,
                        "document_type": c.document_type,
                        "tags": c.tags,
                    }
                    for c in chunks
                ],
            )
            indexed += 1
    return {"status": "completed", "indexed": indexed, "total": len(docs)}


@app.get("/admin/usage")
def admin_usage():
    """Get token usage summary with cost estimates."""
    return store.get_usage_summary()


@app.get("/admin/pricing")
def admin_pricing():
    """Get current Bedrock pricing for the configured region."""
    from .pricing import US_REGIONS, fetch_pricing

    region = os.getenv("AWS_REGION", "us-east-1")
    prices = fetch_pricing(region)
    return {"region": region, "available_regions": US_REGIONS, "models": prices}


@app.put("/admin/pricing")
def admin_pricing_manual(body: dict):
    """Load pricing from a manually provided JSON string."""
    from .pricing import load_pricing_from_json

    raw = body.get("json", "")
    region = body.get("region", os.getenv("AWS_REGION", "us-east-1"))
    prices = load_pricing_from_json(raw, region)
    return {"region": region, "models_loaded": len(prices)}


@app.get("/admin/health-check")
def admin_health_check():
    """Check connectivity to all services and return status with versions."""
    checks: dict = {}
    errors: list[str] = []

    # AWS
    try:
        import boto3

        sts = boto3.client("sts", region_name=os.getenv("AWS_REGION", "us-east-1"))
        identity = sts.get_caller_identity()
        arn = identity.get("Arn", "")
        username = arn.split("/")[-1] if "/" in arn else arn
        checks["aws"] = {
            "status": "ok",
            "username": username,
            "account": identity.get("Account", ""),
            "region": os.getenv("AWS_REGION", "us-east-1"),
            "version": f"boto3 {boto3.__version__}",
        }
    except Exception as e:
        checks["aws"] = {"status": "error"}
        errors.append(f"AWS: {e}")

    # Postgres
    try:
        from .db import get_conn

        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            pg_version = cur.fetchone()[0].split(",")[0]  # e.g. "PostgreSQL 16.2"
        conn.close()
        checks["postgres"] = {"status": "ok", "version": pg_version}
    except Exception as e:
        checks["postgres"] = {"status": "error"}
        errors.append(f"Postgres: {e}")

    # OpenSearch
    try:
        info = os_search.get_client().info()
        checks["opensearch"] = {
            "status": "ok",
            "version": f"OpenSearch {info.get('version', {}).get('number', 'unknown')}",
        }
    except Exception as e:
        checks["opensearch"] = {"status": "error"}
        errors.append(f"OpenSearch: {e}")

    # BookStack
    try:
        if _bookstack.configured:
            import requests as _req

            resp = _req.get(
                f"{_bookstack.base_url}/login",
                timeout=5,
            )
            # Extract version from the CSS link: ?version=v26.03.3
            import re

            ver_match = re.search(r"\?version=(v[\d.]+)", resp.text)
            bs_version = ver_match.group(1) if ver_match else "unknown"
            checks["bookstack"] = {
                "status": "ok",
                "version": f"BookStack {bs_version}",
            }
        else:
            checks["bookstack"] = {"status": "not configured"}
    except Exception as e:
        checks["bookstack"] = {"status": "error"}
        errors.append(f"BookStack: {e}")

    # Confluence
    if _confluence.configured:
        checks["confluence"] = {
            "status": "ok",
            "version": f"Cloud @ {_confluence.base_url}",
        }
    else:
        checks["confluence"] = {"status": "not configured"}

    # Index sync check
    try:
        doc_count = len(store.list_documents())
        os_count_resp = os_search.get_client().count(index=os_search.INDEX_NAME)
        # Count unique document_ids in OpenSearch
        agg_resp = os_search.get_client().search(
            index=os_search.INDEX_NAME,
            body={"size": 0, "aggs": {"docs": {"cardinality": {"field": "document_id"}}}},
        )
        os_unique_docs = agg_resp["aggregations"]["docs"]["value"]
        in_sync = os_unique_docs >= doc_count
        checks["search_index"] = {
            "status": "ok" if in_sync else "out of sync",
            "postgres_docs": doc_count,
            "opensearch_docs": os_unique_docs,
            "version": f"{os_count_resp['count']} chunks indexed",
        }
        if not in_sync:
            errors.append(
                f"Search index out of sync: {doc_count} docs in database, " f"{os_unique_docs} in search index. Click Reindex to fix.",
            )
    except Exception as e:
        checks["search_index"] = {"status": "error", "version": "unavailable"}
        errors.append(f"Search index check failed: {e}")

    return {"checks": checks, "errors": errors}


@app.get("/admin/models")
def admin_list_models():
    """List available Bedrock models for Q&A and vision, pulled live from AWS."""
    try:
        import boto3

        client = boto3.client(
            "bedrock",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        models = client.list_foundation_models()["modelSummaries"]

        # Only include active chat/text-generation models (not embedding, not image-gen)
        skip_prefixes = (
            "stability.",
            "cohere.embed",
            "cohere.rerank",
            "amazon.titan-embed",
            "amazon.titan-tg1",
            "twelvelabs.",
            "openai.gpt-oss-safeguard",
        )

        qa_models = []
        vision_models = []

        for m in models:
            mid = m["modelId"]
            mods_in = set(m.get("inputModalities", []))
            mods_out = set(m.get("outputModalities", []))
            status = m.get("modelLifecycle", {}).get("status", "")

            # Skip inactive, embedding-only, image-generation, and size variants
            if status not in ("ACTIVE", "LEGACY"):
                continue
            if any(mid.startswith(p) for p in skip_prefixes):
                continue
            if mods_out == {"EMBEDDING"} or mods_out == {"IMAGE"}:
                continue
            if any(x in mid for x in [":48k", ":200k", ":28k", ":24k", ":300k", ":128k", ":256k", ":512", ":20k", ":1000k", ":mm"]):
                continue
            if "TEXT" not in mods_in:
                continue
            if "TEXT" not in mods_out:
                continue

            provider = m.get("providerName", "")

            # Add descriptive tags so users know what they're picking
            tags = _model_tags(mid, provider)
            if status == "LEGACY":
                tags = f"legacy · {tags}" if tags else "legacy"
            label = f"{provider} / {mid.split(':')[0]}"
            if tags:
                label += f"  [{tags}]"

            qa_models.append({"id": mid, "label": label})
            if "IMAGE" in mods_in:
                vision_models.append({"id": mid, "label": label})

        # Deduplicate by label (keep first occurrence)
        def _dedup(models: list) -> list:
            seen: set = set()
            out = []
            for m in models:
                if m["label"] not in seen:
                    seen.add(m["label"])
                    out.append(m)
            return out

        qa_models = _dedup(sorted(qa_models, key=lambda x: x["label"]))
        vision_models = _dedup(sorted(vision_models, key=lambda x: x["label"]))
        return {"qa": qa_models, "vision": vision_models}
    except Exception as e:
        return {"qa": [], "vision": [], "error": str(e)}


def _model_tags(model_id: str, provider: str) -> str:
    """Return descriptive tags for a model to help users choose."""
    mid = model_id.lower()
    tags = []

    # Cost tier ($ cheapest, $$ balanced, $$$ premium)
    cheap = [
        "haiku",
        "nova-lite",
        "nova-micro",
        "nova-2-lite",
        "llama3-8b",
        "llama3-1-8b",
        "llama3-2-1b",
        "llama3-2-3b",
        "mistral-7b",
        "mixtral",
        "ministral-3-3b",
        "ministral-3-8b",
        "gemma-3-4b",
        "voxtral-mini",
        "jamba-1-5-mini",
        "nemotron-nano-9b",
        "glm-4.7-flash",
        "gpt-oss-20b",
    ]
    mid_tier = [
        "sonnet",
        "nova-pro",
        "nova-2-pro",
        "llama3-70b",
        "llama3-1-70b",
        "llama3-3-70b",
        "llama4-scout",
        "mistral-small",
        "mistral-large",
        "magistral",
        "pixtral",
        "ministral-3-14b",
        "devstral",
        "gemma-3-12b",
        "gemma-3-27b",
        "jamba-1-5-large",
        "nemotron-nano-12b",
        "nemotron-nano-3-30b",
        "deepseek",
        "qwen3-32b",
        "qwen3-coder",
        "qwen3-next",
        "palmyra-x4",
        "palmyra-x5",
        "palmyra-vision",
        "glm-4.7",
        "glm-5",
        "gpt-oss-120b",
        "minimax",
        "kimi",
        "voxtral-small",
    ]
    expensive = [
        "opus",
        "nova-premier",
        "llama4-maverick",
        "nemotron-super",
        "qwen3-vl-235b",
    ]

    if any(x in mid for x in cheap):
        tags.append("$ cheapest")
    elif any(x in mid for x in expensive):
        tags.append("$$$ premium")
    elif any(x in mid for x in mid_tier):
        tags.append("$$ balanced")

    # Speed
    fast = [
        "haiku",
        "nova-micro",
        "nova-lite",
        "nova-2-lite",
        "ministral-3-3b",
        "ministral-3-8b",
        "llama3-8b",
        "llama3-1-8b",
        "gemma-3-4b",
        "voxtral-mini",
        "glm-4.7-flash",
        "nemotron-nano-9b",
        "jamba-1-5-mini",
        "gpt-oss-20b",
    ]
    slow = ["opus", "nova-premier", "llama4-maverick", "nemotron-super", "qwen3-vl-235b"]

    if any(x in mid for x in fast):
        tags.append("fast")
    elif any(x in mid for x in slow):
        tags.append("slow")

    # Recommended
    if "claude-3-haiku-2024" in mid:
        tags.append("recommended default")
    elif "claude-sonnet-4-2025" in mid or "claude-3-7-sonnet" in mid:
        tags.append("best quality")
    elif "claude-haiku-4-5" in mid:
        tags.append("recommended upgrade")

    return " · ".join(tags)


@app.post("/admin/cancel-upload")
def admin_cancel_upload():
    """Cancel all queued/processing upload jobs and clean up their files."""
    from .db import get_conn

    conn = get_conn()
    with conn.cursor() as cur:
        # Get file paths before cancelling so we can clean up
        cur.execute(
            "SELECT file_path FROM jobs WHERE status IN ('queued', 'processing') AND file_path IS NOT NULL",
        )
        paths = [row[0] for row in cur.fetchall()]
        cur.execute(
            "UPDATE jobs SET status = 'cancelled' WHERE status IN ('queued', 'processing')",
        )
        count = cur.rowcount
        cur.execute("DELETE FROM jobs WHERE status = 'cancelled'")
    conn.close()

    # Remove queued files from disk
    for p in paths:
        try:
            if os.path.isfile(p):
                os.unlink(p)
        except Exception:
            pass

    return {"cancelled": count}


@app.get("/admin/k8s-health")
def admin_k8s_health():
    """Get Kubernetes pod status and resource usage for the Health tab."""
    from .k8s_health import get_cluster_health

    return get_cluster_health()


@app.get("/admin/config")
def admin_get_config():
    """Return current configuration (secrets are masked)."""
    qa_model = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
    vision_model = os.getenv("BEDROCK_VISION_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
    gen_model = os.getenv("BEDROCK_GENERATE_MODEL_ID", qa_model)
    detect_model = os.getenv("BEDROCK_DETECT_MODEL_ID", qa_model)
    return {
        "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
        "BEDROCK_MODEL_ID": qa_model,
        "BEDROCK_GENERATE_MODEL_ID": gen_model,
        "BEDROCK_DETECT_MODEL_ID": detect_model,
        "BEDROCK_VISION_MODEL_ID": vision_model,
        "OPENSEARCH_HOST": os.getenv("OPENSEARCH_HOST", "localhost"),
        "OPENSEARCH_PORT": os.getenv("OPENSEARCH_PORT", "9200"),
        "BOOKSTACK_URL": os.getenv("BOOKSTACK_URL", ""),
        "BOOKSTACK_TOKEN_ID": os.getenv("BOOKSTACK_TOKEN_ID", ""),
        "BOOKSTACK_TOKEN_SECRET": os.getenv("BOOKSTACK_TOKEN_SECRET", ""),
        "CONFLUENCE_URL": os.getenv("CONFLUENCE_URL", ""),
        "CONFLUENCE_EMAIL": os.getenv("CONFLUENCE_EMAIL", ""),
        "CONFLUENCE_API_TOKEN": os.getenv("CONFLUENCE_API_TOKEN", ""),
        "TRACK_USAGE": os.getenv("TRACK_USAGE", "true"),
        "WORKER_CONCURRENCY": os.getenv("WORKER_CONCURRENCY", "3"),
    }


@app.put("/admin/config")
def admin_update_config(updates: dict):
    """Update environment variables at runtime (non-persistent)."""
    allowed = {
        "AWS_REGION",
        "BEDROCK_MODEL_ID",
        "BEDROCK_GENERATE_MODEL_ID",
        "BEDROCK_DETECT_MODEL_ID",
        "BEDROCK_VISION_MODEL_ID",
        "BOOKSTACK_URL",
        "BOOKSTACK_TOKEN_ID",
        "BOOKSTACK_TOKEN_SECRET",
        "CONFLUENCE_URL",
        "CONFLUENCE_EMAIL",
        "CONFLUENCE_API_TOKEN",
        "TRACK_USAGE",
    }

    applied = {}
    for key, val in updates.items():
        if key in allowed:
            os.environ[key] = val
            applied[key] = val if "SECRET" not in key and "TOKEN" not in key else "***"
    # Reinitialize clients with new env vars
    global _bookstack, _confluence
    _bookstack = BookStackClient()
    _confluence = ConfluenceClient()
    return {"applied": applied}
