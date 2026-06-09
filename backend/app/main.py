"""FastAPI routes for the Document Search API."""

import logging
import os
from pathlib import Path
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
    GapEmailRequest,
    GapEmailResponse,
    GapEmailResult,
    JobResponse,
    SearchRequest,
    SearchResponse,
    UploadResponse,
)
from .services import ingest_file_to_store, run_ask, run_search, _get_bedrock


@asynccontextmanager
async def lifespan(app):
    """Initialize OpenSearch index on startup."""
    try:
        os_search.ensure_index()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("OpenSearch init failed: %s", e)
    yield


app = FastAPI(title="Document Search API", version="0.1.0", lifespan=lifespan)

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
    return {"message": "Document Search API", "docs": "/docs"}


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


@app.get("/documents/{document_id}/preview")
def get_document_preview(document_id: str):
    """Return a previewable version: PDF for office docs, original for PDF/images."""
    import subprocess

    from fastapi.responses import FileResponse

    doc = store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not os.path.isfile(doc.source_url):
        raise HTTPException(status_code=404, detail="File not found on disk")

    ext = os.path.splitext(doc.source_url)[1].lower()

    if ext == ".pdf":
        return FileResponse(doc.source_url, media_type="application/pdf")
    if ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif"):
        mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "tiff": "image/tiff", "tif": "image/tiff"}
        return FileResponse(doc.source_url, media_type=mime_map.get(ext.lstrip("."), "image/png"))

    # PPTX/DOCX → convert to PDF via LibreOffice (cached)
    pdf_path = doc.source_url + ".preview.pdf"
    if not os.path.isfile(pdf_path):
        out_dir = os.path.dirname(doc.source_url)
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, doc.source_url],
            capture_output=True, timeout=60,
        )
        generated = os.path.splitext(doc.source_url)[0] + ".pdf"
        if os.path.isfile(generated):
            os.rename(generated, pdf_path)
        elif result.returncode != 0:
            raise HTTPException(status_code=500, detail="Preview conversion failed")

    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=500, detail="Preview conversion failed")
    return FileResponse(pdf_path, media_type="application/pdf")


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
    template_id = body.get("template_id")  # optional: template to follow

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")
    if fmt not in ("md", "docx", "pdf", "png", "pptx", "txt"):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    # If a template is specified, inject its structure into the prompt
    template_instruction = ""
    if template_id:
        tmpl = store.get_template(template_id)
        if tmpl:
            import json as _json
            template_instruction = (
                f"\n\nIMPORTANT: Follow this document structure as a template. "
                f"Create the same sections and field types, but fill them with appropriate content "
                f"based on the user's request. Do NOT output the JSON structure itself. "
                f"Output a properly formatted Markdown document that matches this layout:\n"
                f"{_json.dumps(tmpl['structure'], indent=2)}\n"
            )

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
    full_prompt = prompt + template_instruction
    markdown_content = generate_markdown(full_prompt, context, manual_mode=bool(document_ids), fmt=fmt)

    # Resolve effective format (email keywords → txt)
    effective_fmt = fmt
    email_keywords = ["email", "e-mail"]
    if any(kw in prompt.lower() for kw in email_keywords):
        effective_fmt = "txt"

    return {"markdown": markdown_content, "format": effective_fmt}


# -- Gap-to-Email Pipeline --


@app.post("/search/refine")
def search_refine(body: dict):
    """Refine a list of candidate documents using reranking and LLM classification."""
    from .search import refine_document_selection

    query = body.get("query", "").strip()
    candidates = body.get("candidates", [])
    top_k = body.get("top_k", 10)

    if not query or not candidates:
        return {"results": candidates}

    refined = refine_document_selection(query, candidates, top_k=top_k)
    return {"results": refined}


@app.post("/gap-to-email", response_model=GapEmailResponse)
def gap_to_email(payload: GapEmailRequest):
    """Analyze a form's requirements against vendor documents and generate follow-up emails."""

    # 1. Get the form content to understand requirements
    form_doc = store.get_document(payload.form_document_id)
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form document not found")
    form_chunks = store.get_chunks(payload.form_document_id)
    form_text = "\n".join(c.content for c in form_chunks)

    # 2. Get additional context (e.g., ARB standards) - auto-discover if not provided
    context_text = ""
    if payload.context_document_ids:
        for ctx_id in payload.context_document_ids:
            ctx_chunks = store.get_chunks(ctx_id)
            if ctx_chunks:
                context_text += "\n".join(c.content for c in ctx_chunks) + "\n"
    else:
        # Auto-search for relevant standards/guidelines based on form content
        context_search = run_search(
            store,
            SearchRequest(
                query=f"standards guidelines requirements rules specifications {form_text[:200]}",
                mode="hybrid",
                filters={},
                page=1,
                page_size=30,
            ),
        )
        # Grab top context docs that aren't the form itself or vendor docs
        all_vendor_doc_ids = set()
        for v in payload.vendor_groups:
            all_vendor_doc_ids.update(v.get("doc_ids", []))
        seen_ctx = set()
        for r in context_search.results:
            if r.document_id == payload.form_document_id:
                continue
            if r.document_id in all_vendor_doc_ids:
                continue
            if r.document_id in seen_ctx:
                continue
            seen_ctx.add(r.document_id)
            ctx_chunks = store.get_chunks(r.document_id)
            if ctx_chunks:
                context_text += "\n".join(c.content for c in ctx_chunks) + "\n"
            if len(seen_ctx) >= 3:
                break

    # 3. Process each vendor
    client = _get_bedrock()
    model_id = os.getenv("BEDROCK_GENERATE_MODEL_ID", "amazon.nova-pro-v1:0")

    results = []
    for vendor in sorted(payload.vendor_groups, key=lambda v: v.get("name", "")):
        name = vendor.get("name", "Unknown")
        contact = vendor.get("contact", "")
        doc_ids = vendor.get("doc_ids", [])
        already_have = vendor.get("already_have", [])
        notes = vendor.get("notes", "")

        # Gather vendor document content
        vendor_content = ""
        for doc_id in doc_ids:
            chunks = store.get_chunks(doc_id)
            if chunks:
                doc = store.get_document(doc_id)
                title = doc.title if doc else doc_id
                vendor_content += f"[{title}]\n" + "\n".join(c.content for c in chunks) + "\n\n"

        # Build the prompt for gap analysis + email generation
        example_section = ""
        if payload.example_email:
            example_section = f"\nEXAMPLE EMAIL (match this tone and structure):\n{payload.example_email}\n"

        already_have_text = "\n".join(f"  - {item}" for item in already_have) if already_have else "  (nothing specified)"

        prompt = f"""You are helping someone prepare follow-up emails to vendors/contractors.

TASK: Analyze what a form/application requires, compare against what this vendor has already provided,
identify the gaps, and write a follow-up email requesting the missing items.

FORM/APPLICATION REQUIREMENTS:
{form_text[:4000]}

ADDITIONAL STANDARDS/CONTEXT:
{context_text[:3000]}

VENDOR: {name}
CONTACT: {contact}
NOTES: {notes}

WHAT WE ALREADY HAVE FROM THIS VENDOR:
{already_have_text}

VENDOR'S DOCUMENTS (excerpts):
{vendor_content[:6000]}
{example_section}
INSTRUCTIONS:
1. First, identify what the form requires for submission
2. Compare against what this vendor has already provided (from their documents above)
3. List the specific GAPS (items still needed)
4. Write a follow-up email that:
   - Sounds like a continuation of an existing relationship (not a cold intro)
   - Acknowledges what they already provided
   - Only asks for what's actually missing
   - Is friendly, direct, and concise
   - Signs off with the applicant's name and address (infer from documents if available)

OUTPUT FORMAT (respond with EXACTLY this structure):
GAPS:
- gap 1
- gap 2
- ...

EMAIL:
Subject: ...
(full email text)"""

        system = [{"text": "You produce gap analyses and professional follow-up emails."}]
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        resolved = model_id
        try:
            resp = client.converse(
                modelId=resolved, system=system, messages=messages,
                inferenceConfig={"maxTokens": 2000},
            )
        except BaseException:
            if not resolved.startswith("us."):
                resolved = f"us.{model_id}"
                resp = client.converse(
                    modelId=resolved, system=system, messages=messages,
                    inferenceConfig={"maxTokens": 2000},
                )
            else:
                raise

        output = resp["output"]["message"]["content"][0]["text"]

        # Parse gaps and email from output
        gaps = []
        email = output
        if "GAPS:" in output and "EMAIL:" in output:
            parts = output.split("EMAIL:", 1)
            gaps_section = parts[0].split("GAPS:", 1)[1].strip()
            gaps = [line.strip().lstrip("- ") for line in gaps_section.split("\n") if line.strip().startswith("-")]
            email = parts[1].strip()

        results.append(GapEmailResult(
            vendor_name=name,
            contact=contact,
            gaps=gaps,
            email=email,
        ))

    return GapEmailResponse(results=results)


# ---------------------------------------------------------------------------
# Tasks: iterative document generation with conversation history
# ---------------------------------------------------------------------------

# =========================================================================
# MODEL INVOCATION HELPERS
#
# AWS Bedrock has two ways to call models:
# 1. On-demand: use the model ID directly (e.g., "amazon.nova-pro-v1:0")
# 2. Inference profile: prefix with "us." (e.g., "us.anthropic.claude-sonnet-4-6")
#
# Some models only work one way. Instead of maintaining a hardcoded list,
# we try on-demand first and automatically retry with "us." if it fails.
# Results are cached so we only fail once per model.
# =========================================================================

_profile_models: set = set()   # models that need "us." prefix
_ondemand_models: set = set()  # models that work without prefix


def _resolve_model_id(model_id: str) -> str:
    """Check if a model needs the 'us.' inference profile prefix.
    First call for an unknown model returns it as-is (caller handles fallback).
    After that, cached result is used.
    """
    if model_id.startswith("us.") or model_id.startswith("global."):
        return model_id
    if model_id in _profile_models:
        return f"us.{model_id}"
    if model_id in _ondemand_models:
        return model_id
    return model_id


def _call_bedrock_stream(client, model_id: str, system: list, messages: list, max_tokens: int = 4096):
    """Call any Bedrock model and return the text response.
    
    Handles two quirks automatically:
    1. If the model needs an inference profile ("us." prefix), retries with it
    2. If the model is a "reasoning" model (OpenAI GPT-OSS, DeepSeek R1), 
       it returns both thinking tokens and answer tokens — we only keep the answer
    """
    resolved = _resolve_model_id(model_id)
    try:
        resp = client.converse_stream(
            modelId=resolved, system=system, messages=messages,
            inferenceConfig={"maxTokens": max_tokens},
        )
        _ondemand_models.add(model_id)
    except BaseException as e:
        if not resolved.startswith("us."):
            # Model doesn't work on-demand — try with inference profile
            resolved = f"us.{model_id}"
            _profile_models.add(model_id)
            resp = client.converse_stream(
                modelId=resolved, system=system, messages=messages,
                inferenceConfig={"maxTokens": max_tokens},
            )
        else:
            raise

    # Collect only "text" deltas (skip "reasoningContent" from thinking models)
    # Also capture usage metadata from the final stream event
    chunks = []
    usage = {}
    for event in resp["stream"]:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"]["delta"]
            if "text" in delta:
                chunks.append(delta["text"])
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
    return "".join(chunks), usage


@app.post("/tasks/generate")
async def task_generate(body: dict):
    """Generate or refine a document with conversation history.
    Returns SSE stream with status updates, then final result as JSON event.
    """
    from starlette.responses import StreamingResponse
    import json as _json
    import asyncio

    prompt = body.get("prompt", "").strip()
    document_ids = body.get("document_ids", [])
    history = body.get("history", [])
    fmt = body.get("format", "md")
    skip_auto_search = body.get("skip_auto_search", False)

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    async def generate_stream():
        from .schemas import SearchRequest

        yield f"data: {_json.dumps({'status': 'Gathering source documents...'})}\n\n"
        await asyncio.sleep(0)  # flush

        # Detect if any selected document is a form/application (adjusts generation style)
        is_form_task = False
        form_doc_titles = []
        for doc_id in document_ids:
            doc = store.get_document(doc_id)
            if doc:
                dtype = getattr(doc, 'document_type', '') or ''
                title = getattr(doc, 'title', '') or ''
                if dtype in ('application', 'form') or 'application' in title.lower() or 'form' in title.lower():
                    is_form_task = True
                    form_doc_titles.append(title)

        # Build context from selected documents
        context_parts = []
        manual_count = 0
        seen_ids = set(document_ids)

        if skip_auto_search and document_ids:
            # User curated their doc list — use chunk-level retrieval for precision
            # Instead of loading entire documents, search for the most relevant chunks
            yield f"data: {_json.dumps({'status': 'Retrieving relevant sections from selected documents...'})}\n\n"
            await asyncio.sleep(0)

            # Search within the selected documents for chunks relevant to the prompt
            from .search import search_chunks_grouped
            chunk_results = search_chunks_grouped(prompt, document_ids=document_ids, top_k=30)
            for doc_id, chunks_text in chunk_results.items():
                doc = store.get_document(doc_id)
                title = doc.title if doc else doc_id
                context_parts.append(f"[{title}]\n{chunks_text}")
                manual_count += 1

            # If chunk search returned nothing, fall back to full doc load
            if not context_parts:
                for doc_id in document_ids:
                    doc = store.get_document(doc_id)
                    if not doc:
                        continue
                    chunks = store.get_chunks(doc_id)
                    if chunks:
                        text = "\n".join(c.content for c in chunks)
                        context_parts.append(f"[{doc.title}]\n{text}")
                        manual_count += 1
        else:
            # Original behavior: load full documents
            for doc_id in document_ids:
                doc = store.get_document(doc_id)
                if not doc:
                    continue
                chunks = store.get_chunks(doc_id)
                if chunks:
                    text = "\n".join(c.content for c in chunks)
                    context_parts.append(f"[{doc.title}]\n{text}")
                    manual_count += 1

        # Auto-search for additional relevant documents
        auto_parts = []
        if not history and not skip_auto_search:
            yield f"data: {_json.dumps({'status': 'Searching for relevant documents...'})}\n\n"
            await asyncio.sleep(0)
            search_result = run_search(
                store,
                SearchRequest(query=prompt, mode="hybrid", page=1, page_size=30),
            )
            auto_count = 0
            for r in search_result.results:
                if r.document_id not in seen_ids:
                    seen_ids.add(r.document_id)
                    doc = store.get_document(r.document_id)
                    if doc:
                        chunks = store.get_chunks(r.document_id)
                        if chunks:
                            text = "\n".join(c.content for c in chunks)
                            auto_parts.append(f"[{doc.title}]\n{text}")
                            auto_count += 1
            yield f"data: {_json.dumps({'status': f'Found {manual_count + auto_count} relevant documents ({manual_count} selected, {auto_count} auto-discovered)'})}\n\n"
            await asyncio.sleep(0)

        # Map-reduce: only extract from AUTO-DISCOVERED large docs, never from manually selected
        MAX_CONTEXT = 150000
        manual_len = sum(len(p) for p in context_parts)
        auto_len = sum(len(p) for p in auto_parts)
        total_len = manual_len + auto_len

        if auto_len > (MAX_CONTEXT - manual_len) and len(auto_parts) > 0:
            yield f"data: {_json.dumps({'status': f'Extracting relevant info from {len(auto_parts)} auto-discovered documents...'})}\n\n"
            await asyncio.sleep(0)
            yield f"data: {_json.dumps({'status': f'Context is {total_len//1000}k chars. Extracting relevant info from large documents...'})}\n\n"
            await asyncio.sleep(0)

            import boto3 as _boto3
            from botocore.config import Config as BotoConfig
            _bedrock_config = BotoConfig(read_timeout=300, connect_timeout=10)
            _map_client = _boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"), config=_bedrock_config)
            _map_model = _resolve_model_id(os.getenv("BEDROCK_TASK_MULTI_MODEL_ID", "") or "meta.llama3-3-70b-instruct-v1:0")

            extracted_parts = []
            for i, part in enumerate(auto_parts):
                if len(part) <= 8000:
                    extracted_parts.append(part)
                else:
                    yield f"data: {_json.dumps({'status': f'Extracting from document {i+1}/{len(auto_parts)}...'})}\n\n"
                    await asyncio.sleep(0)
                    try:
                        loop = asyncio.get_event_loop()
                        def _map_extract(p=part):
                            text, _ = _call_bedrock_stream(_map_client, _map_model, [],
                                [{"role": "user", "content": [{"text":
                                    f"Extract ONLY the information relevant to this task from the document below. "
                                    f"Include ALL specific details: company names, license numbers, contact info, prices, dates, addresses, warranty terms, scope of work, and conditions. "
                                    f"Even if some fields are blank or missing, still include the company and what IS provided. "
                                    f"Omit generic legal boilerplate and cancellation notices. Be thorough with relevant details.\n\n"
                                    f"Task: {prompt}\n\n"
                                    f"Document:\n{p[:80000]}"
                                }]}])
                            return text

                        future = loop.run_in_executor(None, _map_extract)
                        while not future.done():
                            done, _ = await asyncio.wait({future}, timeout=8)
                            if not done:
                                yield ": keepalive\n\n"
                        extracted = future.result()
                        doc_title = part.split("\n")[0]
                        extracted_parts.append(f"{doc_title}\n{extracted}")
                    except Exception as e:
                        extracted_parts.append(part[:8000] + "\n[... extraction failed, showing partial ...]")

            auto_parts = extracted_parts
            yield f"data: {_json.dumps({'status': 'Extraction complete. Generating final document...'})}\n\n"
            await asyncio.sleep(0)

        # Combine: manual docs (full) + auto docs (possibly extracted)
        all_context = context_parts + auto_parts
        total_context_chars = sum(len(p) for p in all_context)
        yield f"data: {_json.dumps({'status': f'Total context: {total_context_chars//1000}k chars from {len(all_context)} documents'})}\n\n"
        await asyncio.sleep(0)

        # =====================================================================
        # ADAPTIVE MODEL ROUTING
        # 
        # We use different AI models depending on how much text we need to process:
        #
        # SMALL context (fits in one shot):
        #   → Nova Pro in single-pass mode (score: 8.6/10, speed: ~80s)
        #   → Nova Pro has a 300k token window so it can read everything at once
        #   → Best at: getting all prices, fast turnaround
        #   → Weakness: sometimes doesn't rank options optimally
        #
        # LARGE context (too much for one shot):
        #   → Mistral Magistral in structured pipeline (score: 9.8/10, speed: ~280s)
        #   → Reads each document separately, fills a structured form (JSON)
        #   → Forms are merged with code (no AI = no information loss)
        #   → Then generates final document from the clean structured data
        #   → Best at: following instructions precisely, not missing details
        #   → Weakness: slower (has to process each document individually)
        #
        # WHY NOT USE THE SAME MODEL FOR BOTH?
        # Tested 17+ models. Fast models (Nova Pro, Llama) rush through structured
        # extraction and miss fields. Thorough models (Mistral Magistral) are too
        # slow for single-pass. Each model type excels at its assigned strategy.
        #
        # These sizes come from AWS docs (not available via API unfortunately):
        # =====================================================================
        MAX_BATCH_CHARS = 80000  # per-cycle batch size for structured pipeline

        _MODEL_CONTEXT_CHARS = {
            "amazon.nova-pro": 250000,       # 300k tokens
            "amazon.nova-lite": 250000,      # 300k tokens
            "amazon.nova-2-lite": 250000,    # 300k tokens
            "anthropic.claude-sonnet-4": 160000,  # 200k tokens
            "anthropic.claude-opus-4": 160000,
            "anthropic.claude-haiku-4": 160000,
            "mistral.mistral-large": 100000, # 128k tokens
            "meta.llama3-3": 100000,         # 128k tokens
            "meta.llama4": 100000,           # 128k tokens
            "deepseek": 100000,              # 128k tokens
            "qwen": 100000,                  # 128k tokens
        }

        single_model_id = os.getenv("BEDROCK_TASK_SINGLE_MODEL_ID", "") or "nvidia.nemotron-super-3-120b"
        # Look up how much text the single-pass model can handle
        single_pass_limit = 80000  # safe default if model not in table
        for prefix, limit in _MODEL_CONTEXT_CHARS.items():
            if single_model_id.startswith(prefix):
                single_pass_limit = limit
                break

        # ─── COMPLEXITY DETECTION ───
        # Some prompts require the structured pipeline regardless of context size.
        # Testing showed Nova Pro hallucates on complex multi-entity tasks even
        # when context fits in its window. Detect complexity from prompt signals:
        import re
        prompt_lower = prompt.lower()
        complexity_signals = (
            len(re.findall(r'section \d|## \d|step \d', prompt_lower)) >= 3  # multiple sections requested
            or ("rank" in prompt_lower and ("all" in prompt_lower or "every" in prompt_lower))  # exhaustive ranking
            or (prompt_lower.count("compare") + prompt_lower.count(" vs ") + prompt_lower.count("best to worst")) >= 1  # comparison task
            or (len(re.findall(r'\ball\b.*\b(contractor|compan|vendor|provider)', prompt_lower)) >= 1)  # exhaustive entity search
        )

        if complexity_signals and total_context_chars > 30000:
            # Complex task with substantial context — use structured pipeline
            strategy = "structured"
            model_id = _resolve_model_id(os.getenv("BEDROCK_TASK_MULTI_MODEL_ID", "") or "mistral.magistral-small-2509")
            yield f"data: {_json.dumps({'status': f'Strategy: structured (complex prompt detected) ({model_id})'})}\n\n"
        elif total_context_chars <= single_pass_limit:
            # Simple task or small context — use the fast single-pass model
            strategy = "single"
            model_id = _resolve_model_id(single_model_id)
            yield f"data: {_json.dumps({'status': f'Strategy: single-pass ({model_id})'})}\n\n"
        else:
            # Too much text for one shot — use structured pipeline with thorough model
            strategy = "structured"
            model_id = _resolve_model_id(os.getenv("BEDROCK_TASK_MULTI_MODEL_ID", "") or "mistral.magistral-small-2509")
            yield f"data: {_json.dumps({'status': f'Strategy: structured extract+generate ({model_id})'})}\n\n"
        await asyncio.sleep(0)

        if not model_id:
            yield f"data: {_json.dumps({'error': 'No generation model configured'})}\n\n"
            return

        system_prompt = (
            "You are a document analyst and writer. You create professional documents "
            "based on source material provided by the user. "
            "CRITICAL RULES: "
            "(1) Use ONLY information explicitly stated in the provided documents. "
            "NEVER invent company names, prices, license numbers, phone numbers, or any other facts. "
            "If information is not in the documents, say 'Not provided in documents' — do NOT fabricate it. "
            "(2) When ranking or comparing options, prioritize: "
            "solutions that solve the user's stated problems, "
            "practical feasibility (proposals executable independently rank higher than those requiring third-party coordination), "
            "and total value (price + warranty + scope together, not just one factor). "
            "(3) Do not penalize a proposal for missing details if it addresses the core problem better than alternatives. "
            "Output well-structured Markdown. Include EVERY company, price, and entity found in the source data — never omit any."
        )

        # Override system prompt for form-filling tasks
        if is_form_task:
            system_prompt = (
                "You are writing content for a form field on behalf of the user. "
                "Write in plain, simple English. Use complete sentences in flowing paragraphs. "
                "Break the content into 2-3 short paragraphs for readability. "
                "No bullet points, no headers, no tables, no numbered lists, no dashes, no markdown formatting. "
                "First person. State facts directly from the provided documents. "
                "Do NOT invent any facts. Do NOT use corporate or robotic language. "
                "Write like a real person explaining a project simply and clearly. "
                "ALWAYS include these details if they appear in the documents: "
                "cost/pricing, materials and products, dimensions/measurements, "
                "timeline (start date, completion time), contractor name and license number, "
                "color specifications, and scope of work (what will be done step by step)."
            )

        try:
            import boto3
            from botocore.config import Config as BotoConfig
            client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"), config=BotoConfig(read_timeout=300, connect_timeout=10))
            loop = asyncio.get_event_loop()

            # Multi-cycle rolling context: split docs into batches that fit ~80k chars each
            # Each cycle builds on the previous result
            MAX_BATCH_CHARS = 80000
            markdown_content = ""

            if history:
                # Refinement: no multi-cycle needed, just send the refinement
                messages = []
                for msg in history:
                    messages.append({"role": msg["role"], "content": [{"text": msg["content"]}]})
                messages.append({"role": "user", "content": [{"text": prompt}]})

                yield f"data: {_json.dumps({'status': 'Refining...'})}\n\n"
                await asyncio.sleep(0)

                def _stream_refine():
                    text, _ = _call_bedrock_stream(client, model_id, [{"text": system_prompt}], messages)
                    return text

                future = loop.run_in_executor(None, _stream_refine)
                while not future.done():
                    done, _ = await asyncio.wait({future}, timeout=8)
                    if not done:
                        yield ": keepalive\n\n"
                markdown_content = future.result()

            elif strategy == "single":
                # Single pass: everything fits in model's context window
                context = "\n\n---\n\n".join(all_context)
                yield f"data: {_json.dumps({'status': f'Generating document (single pass, {len(context)//1000}k chars)...'})}\n\n"
                await asyncio.sleep(0)

                def _stream_single():
                    user_msg = f"Source documents:\n{context}\n\n---\n\nTask: {prompt}"
                    if is_form_task:
                        user_msg += "\n\nREMINDER: Output 2-3 short paragraphs separated by blank lines. No headers, no bullets, no markdown."
                    text, _ = _call_bedrock_stream(client, model_id, [{"text": system_prompt}],
                        [{"role": "user", "content": [{"text": user_msg}]}])
                    return text

                future = loop.run_in_executor(None, _stream_single)
                while not future.done():
                    done, _ = await asyncio.wait({future}, timeout=8)
                    if not done:
                        yield ": keepalive\n\n"
                markdown_content = future.result()

                # Post-process: split wall-of-text into paragraphs for form tasks
                if is_form_task and "\n\n" not in markdown_content and len(markdown_content) > 500:
                    try:
                        def _split_paragraphs(text=markdown_content):
                            split_resp = client.converse(
                                modelId="amazon.nova-micro-v1:0",
                                messages=[{"role": "user", "content": [{"text":
                                    "Insert paragraph breaks (blank lines) into this text where the topic naturally shifts. "
                                    "Do not change any words. Return only the text with blank lines added.\n\n" + text
                                }]}],
                                inferenceConfig={"maxTokens": len(text) // 3},
                            )
                            return split_resp["output"]["message"]["content"][0]["text"]
                        future = loop.run_in_executor(None, _split_paragraphs)
                        done, _ = await asyncio.wait({future}, timeout=10)
                        if done:
                            result = future.result()
                            if "\n\n" in result and len(result) > len(markdown_content) * 0.8:
                                markdown_content = result
                    except Exception:
                        pass  # Keep original if splitting fails

            else:
                # Structured pipeline: schema → extract → merge → generate
                from .task_pipeline import generate_schema, extract_from_document, merge_extractions, generate_document

                # Step 1: Generate extraction schema from prompt
                yield f"data: {_json.dumps({'status': 'Step 1/4: Generating extraction schema from prompt...'})}\n\n"
                await asyncio.sleep(0)

                def _gen_schema():
                    return generate_schema(client, model_id, prompt)
                future = loop.run_in_executor(None, _gen_schema)
                while not future.done():
                    done, _ = await asyncio.wait({future}, timeout=8)
                    if not done:
                        yield ": keepalive\n\n"
                schema = future.result()

                if "_error" in schema:
                    err_msg = schema.get("_error", "unknown")
                    yield f"data: {_json.dumps({'error': f'Schema generation failed: {err_msg}'})}\n\n"
                    return

                yield f"data: {_json.dumps({'status': f'Schema ready: {len(schema)} categories'})}\n\n"
                await asyncio.sleep(0)

                # Step 2: Extract from each document using schema
                extractions = []
                for i, doc_text in enumerate(all_context):
                    yield f"data: {_json.dumps({'status': f'Step 2/4: Extracting from document {i+1}/{len(all_context)}...'})}\n\n"
                    await asyncio.sleep(0)

                    def _extract(dt=doc_text):
                        return extract_from_document(client, model_id, schema, dt)
                    future = loop.run_in_executor(None, _extract)
                    while not future.done():
                        done, _ = await asyncio.wait({future}, timeout=8)
                        if not done:
                            yield ": keepalive\n\n"
                    result = future.result()
                    if result:
                        extractions.append(result)

                # Step 3: Merge (pure code, instant)
                yield f"data: {_json.dumps({'status': f'Step 3/4: Merging {len(extractions)} extractions...'})}\n\n"
                await asyncio.sleep(0)
                merged = merge_extractions(extractions)

                # Step 4: Generate final document from structured data
                yield f"data: {_json.dumps({'status': 'Step 4/4: Generating final document from structured data...'})}\n\n"
                await asyncio.sleep(0)

                def _generate():
                    return generate_document(client, model_id, system_prompt, merged, prompt)
                future = loop.run_in_executor(None, _generate)
                while not future.done():
                    done, _ = await asyncio.wait({future}, timeout=8)
                    if not done:
                        yield ": keepalive\n\n"
                markdown_content = future.result()

            # Track usage (approximate - multi-cycle doesn't return per-call usage easily)
            if os.getenv("TRACK_USAGE", "true").lower() == "true":
                from .pricing import estimate_cost
                approx_input = total_context_chars // 4  # rough token estimate
                approx_output = len(markdown_content) // 4
                store.log_usage(
                    model_id=model_id,
                    operation="task_generate",
                    input_tokens=approx_input,
                    output_tokens=approx_output,
                    estimated_cost_usd=estimate_cost(model_id, approx_input, approx_output, os.getenv("AWS_REGION", "us-east-1")),
                )

            # Build updated history (store summary for refinement, not full context)
            new_history = list(history)
            if not history:
                new_history.append({"role": "user", "content": f"Task: {prompt}"})
            else:
                new_history.append({"role": "user", "content": prompt})
            new_history.append({"role": "assistant", "content": markdown_content})

            yield f"data: {_json.dumps({'status': 'Done'})}\n\n"
            yield f"data: {_json.dumps({'result': {'markdown': markdown_content, 'history': new_history, 'format': fmt}})}\n\n"

        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/generate/detect-format")
def generate_detect_format(body: dict):
    """Use a cheap LLM call to detect the best output format for a prompt."""
    import boto3

    prompt = body.get("prompt", "").strip()
    if not prompt:
        return {"format": "md", "reason": "no prompt"}

    model_id = os.getenv(
        "BEDROCK_DETECT_MODEL_ID",
        os.getenv("BEDROCK_MODEL_ID", "meta.llama3-8b-instruct-v1:0"),
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
                        "FORMAT must be one of: md, docx, pdf, png, pptx, txt\n"
                        "REASON is 2-4 words explaining why.\n\n"
                        "Examples:\n"
                        "- 'Write a letter to my HOA' → docx|formal letter\n"
                        "- 'Create a presentation about rules' → pptx|slide deck\n"
                        "- 'Fill out the modification form' → docx|fillable form\n"
                        "- 'Make a quick reference card' → png|visual reference\n"
                        "- 'Generate a report with all fees' → pdf|formal report\n"
                        "- 'Summarize the bylaws' → md|text summary\n"
                        "- 'Write an email to my roofer' → txt|email message\n"
                        "- 'Send an email asking about repairs' → txt|email message\n"
                        "- 'Draft an email to the contractor' → txt|email message"
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

        if fmt not in ("md", "docx", "pdf", "png", "pptx", "txt"):
            fmt = "md"
            reason = "general content"

        return {"format": fmt, "reason": reason}
    except Exception:
        return {"format": "md", "reason": "detection unavailable"}


@app.get("/generate/plantuml-status")
def plantuml_status():
    """Check if PlantUML rendering is available."""
    from .plantuml import find_plantuml_jar, is_available

    jar = find_plantuml_jar()
    return {
        "available": is_available(),
        "jar_path": str(jar) if jar else None,
    }


@app.post("/generate/convert")
def generate_convert(body: dict):
    """Convert previously generated markdown to a different format (no Bedrock call)."""
    import base64

    from .generator import (
        convert_to_docx,
        convert_to_pdf,
        convert_to_png,
        convert_to_pptx,
        convert_to_txt,
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
    elif fmt == "txt":
        file_bytes = convert_to_txt(markdown)
        filename = "generated.txt"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    return {"file_b64": base64.b64encode(file_bytes).decode(), "filename": filename}


@app.post("/generate/export-package")
def generate_export_package(body: dict):
    """Export a writeup + associated source document files as a structured archive ZIP."""
    import base64
    import io
    import re
    import zipfile
    from datetime import datetime

    markdown = body.get("markdown", "").strip()
    document_ids = body.get("document_ids", [])
    prompt = body.get("prompt", "")
    filename_prefix = body.get("filename_prefix", "submission")

    if not markdown:
        raise HTTPException(status_code=400, detail="No content to export")

    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    archive_name = f"{filename_prefix}_{timestamp}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write the main writeup with source citations
        citations = ["\n\nSource Documents:\n"]
        
        for idx, doc_id in enumerate(document_ids, 1):
            doc = store.get_document(doc_id)
            if not doc:
                continue

            title = doc.title or doc.original_filename or doc_id
            # Clean title for filesystem
            clean_name = re.sub(r"[^\w\s-]", "", title)
            clean_name = re.sub(r"\s+", "_", clean_name.strip())[:60]
            dir_name = f"{idx:02d}_{clean_name}"

            # Find the source file
            source_url = doc.source_url or ""
            file_path = Path(source_url.replace("/app/", ""))
            if not file_path.exists():
                file_path = Path("data/uploads") / file_path.name

            # Copy original file into the archive
            original_filename = doc.original_filename or file_path.name
            if file_path.exists():
                zf.write(file_path, f"sources/{dir_name}/{original_filename}")

            # Build relevance summary
            relevance_lines = [
                f"Document: {title}",
                f"Original filename: {original_filename}",
                f"Type: {doc.document_type or 'unknown'}",
                f"Category: {doc.category or 'unknown'}",
                "",
                "Why this document was included:",
                "",
            ]

            # Search for matching chunks if we have a prompt
            if prompt:
                from .search import search_chunks
                result = search_chunks(prompt, document_ids=[doc_id], page=1, page_size=3)
                for i, r in enumerate(result.get("results", []), 1):
                    snippet = r.get("snippet", "").replace("<em>", "").replace("</em>", "")
                    relevance_lines.append(f"  Match {i} (score {r.get('score', 0):.1f}):")
                    relevance_lines.append(f"    {snippet[:300]}")
                    relevance_lines.append("")
            if len(relevance_lines) == 7:  # No matches added
                relevance_lines.append("  Included via entity match or form auto-detection.")

            zf.writestr(f"sources/{dir_name}/relevance.txt", "\n".join(relevance_lines))
            citations.append(f"  {idx}. {dir_name}/ — {title}")

        # Write the writeup with prompt and citations appended
        full_writeup = f"Prompt:\n{prompt}\n\n{'='*60}\n\nGenerated Content:\n\n{markdown}" + "\n".join(citations) + "\n"
        zf.writestr("writeup.txt", full_writeup)

    buf.seek(0)
    return {"file_b64": base64.b64encode(buf.read()).decode(), "filename": f"{archive_name}.zip"}


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


# -- Templates --


@app.post("/templates/extract")
async def extract_template_endpoint(file: UploadFile = File(...), name: str = ""):
    """Upload a file and extract its structure as a reusable template."""
    from .template_extractor import extract_template

    content = await file.read()
    filename = file.filename or "unknown"

    structure = extract_template(content, filename)

    # Analyze fill map for DOCX templates
    ext = Path(filename).suffix.lower()
    if ext in (".docx", ".doc"):
        from .template_fill_engine import analyze
        structure["fill_map"] = analyze(content)

    # Derive template name from filename (clean it up)
    if not name:
        stem = Path(filename).stem
        name = stem.replace("_", " ").replace("-", " ").strip().title()

    template_id = store.new_id("tmpl")
    store.save_template(
        template_id=template_id,
        name=name,
        source_format=structure.get("source_format", "unknown"),
        structure=structure,
        file_bytes=content,
    )

    return {"template_id": template_id, "name": name, "structure": structure}


@app.get("/templates")
def list_templates():
    """List all saved templates."""
    return store.list_templates()


@app.get("/templates/{template_id}")
def get_template(template_id: str):
    """Get a template's structure."""
    tmpl = store.get_template(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    # Remove non-serializable fields
    tmpl.pop("file_bytes", None)
    return tmpl


@app.get("/templates/{template_id}/export")
def export_template(template_id: str, format: str = "json"):
    """Export a template as JSON or XML."""
    from fastapi.responses import Response

    tmpl = store.get_template(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    structure = tmpl.get("structure", {})
    name = tmpl.get("name", "template").replace(" ", "_")

    if format == "xml":
        xml = _structure_to_xml(structure)
        return Response(content=xml, media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{name}.template.xml"'})

    import json as json_mod
    content = json_mod.dumps(structure, indent=2)
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.template.json"'})


def _structure_to_xml(structure: dict) -> str:
    """Convert template structure dict to XML."""
    from xml.etree.ElementTree import Element, SubElement, tostring
    from xml.dom.minidom import parseString

    root = Element("template")
    root.set("type", structure.get("type", "document"))
    root.set("title", structure.get("title", ""))
    root.set("source_format", structure.get("source_format", ""))

    if structure.get("fonts"):
        fonts_el = SubElement(root, "fonts")
        for k, v in structure["fonts"].items():
            fonts_el.set(k, str(v))

    if structure.get("page_layout"):
        layout_el = SubElement(root, "page_layout")
        pl = structure["page_layout"]
        if pl.get("size"):
            layout_el.set("size", pl["size"])
        if pl.get("orientation"):
            layout_el.set("orientation", pl["orientation"])
        if pl.get("margins"):
            margins_el = SubElement(layout_el, "margins")
            for k, v in pl["margins"].items():
                margins_el.set(k, str(v))

    sections_el = SubElement(root, "sections")
    for section in structure.get("sections", []):
        sec_el = SubElement(sections_el, "section")
        if section.get("heading"):
            sec_el.set("heading", section["heading"])
        if section.get("style"):
            sec_el.set("style", section["style"])
        if section.get("row_count"):
            sec_el.set("row_count", str(section["row_count"]))
        for element in section.get("elements", []):
            el = SubElement(sec_el, element.get("type", "element"))
            for k, v in element.items():
                if k == "type":
                    continue
                if isinstance(v, list):
                    el.set(k, " | ".join(str(c) for c in v))
                elif isinstance(v, bool):
                    el.set(k, str(v).lower())
                else:
                    el.set(k, str(v))

    raw = tostring(root, encoding="unicode")
    return parseString(raw).toprettyxml(indent="  ")


@app.delete("/templates/{template_id}")
def delete_template(template_id: str):
    """Delete a template."""
    if not store.delete_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": template_id}


@app.post("/templates/{template_id}/analyze")
def analyze_template(template_id: str):
    """Return the fill schema for a template (intermediate representation)."""
    from .template_fill_engine import analyze

    file_bytes = _get_template_file_bytes(template_id)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Template has no stored file")
    return analyze(file_bytes)


@app.post("/templates/{template_id}/fill")
async def fill_template(template_id: str, request: dict):
    """Fill a template with AI-generated content based on a prompt and indexed documents.

    Uses the TemplateFillEngine: analyze → generate → apply.
    Request body: {"prompt": "Write a thesis about...", "document_ids": [...] (optional)}
    Returns the filled document as a downloadable file.
    """
    from fastapi.responses import Response
    from .template_fill_engine import analyze, generate_sectioned, apply_full
    from .template_content_generator import generate_content

    prompt = request.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    tmpl = store.get_template(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    file_bytes = _get_template_file_bytes(template_id)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Template has no stored file. Re-import the template.")

    source_format = tmpl.get("source_format", "docx")
    if source_format not in ("docx", "doc"):
        raise HTTPException(status_code=400, detail="Template fill only supports DOCX templates")

    # Search indexed documents for relevant content
    doc_ids = request.get("document_ids")
    from .schemas import SearchRequest
    search_payload = SearchRequest(query=prompt, filters={"document_ids": doc_ids} if doc_ids else {}, page=1, page_size=15)
    search_response = run_search(store, search_payload)
    context_chunks = "\n\n".join(f"[{r.title}]: {r.snippet}" for r in search_response.results)

    # Get document titles for bibliography
    all_docs = store.list_documents()
    doc_titles = [d.title for d in all_docs if any(x in (d.category or "").lower() for x in ["hoa", "governance"])
                  or any(x in (d.document_type or "").lower() for x in ["architectural", "rules", "bylaws", "ccrs", "meeting", "resolution", "hoa"])]

    # 1. GENERATE — section-by-section decision loop with validation
    content = generate_content(prompt, context_chunks, doc_titles)
    if not content:
        raise HTTPException(status_code=500, detail="Failed to generate content for template fields")

    # 2. APPLY — map content package to template structure
    # Convert content package to the format apply_full expects
    fill_data = _content_to_fill_data(content)
    filled_bytes = apply_full(file_bytes, fill_data)

    name = tmpl.get("name", "filled_template").replace(" ", "_")
    return Response(
        content=filled_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}_filled.docx"'},
    )


def _get_template_file_bytes(template_id: str) -> bytes | None:
    """Get the stored file bytes for a template."""
    from .db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_bytes FROM templates WHERE template_id = %s", (template_id,))
            row = cur.fetchone()
            if row and row[0]:
                return bytes(row[0])
    finally:
        conn.close()
    return None


def _content_to_fill_data(content: dict) -> dict:
    """Convert content generator output to the format apply_full expects."""
    tp = content.get("title_page", {})
    abstract = content.get("abstract", {})
    ack = content.get("acknowledgments", {})
    glossary = content.get("glossary", [])
    chapter = content.get("chapter", {})

    return {
        "title": {
            "title": tp.get("title_runs", ["HOA", "", "Governance"]),
            "author": tp.get("author_runs", ["by", "The Author"]),
            "description": tp.get("description_runs", ["A guide to HOA governance", ""]),
            "institution": tp.get("institution_runs", ["Centerpointe", " ", "Community"]),
            "year": tp.get("year", "2026"),
            "committee": tp.get("committee", "HOA Board of Directors"),
            "program": tp.get("program", "Community Governance"),
            "date": tp.get("date", "May 2026"),
            "institution2": tp.get("institution", "Centerpointe Community"),
        },
        "abstract": {
            "title": abstract.get("title", tp.get("title", "HOA Governance")),
            "author": f"By {tp.get('author', 'The Author')}",
            "body": abstract.get("body", ""),
        },
        "ack": ack,
        "glossary": glossary if isinstance(glossary, list) else glossary.get("terms", []),
        "chapter": chapter,
        "toc_entries": content.get("toc", []),
        "figure_entries": content.get("figures", []),
        "bib_entries": content.get("bibliography", []),
        "index_entries": content.get("index", []),
    }


@app.get("/admin/jobs", response_model=list[JobResponse])
def admin_jobs() -> list[JobResponse]:
    return store.get_jobs()


@app.post("/admin/reindex")
def admin_reindex():
    """Rebuild the OpenSearch index from Postgres (recreates index for mapping changes)."""
    client = os_search.get_client()
    if client.indices.exists(index=os_search.INDEX_NAME):
        client.indices.delete(index=os_search.INDEX_NAME)
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

    # App build metadata
    checks["app"] = {
        "status": "ok",
        "tag": os.getenv("IMAGE_TAG", "dev"),
        "build_date": os.getenv("BUILD_DATE", "unknown"),
        "git_hash": os.getenv("GIT_HASH", "unknown"),
    }

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

        # Embedding models (ranked by benchmark results)
        _embed_rankings = {
            "amazon.titan-embed-text-v2:0": "★ 93.3% acc · $0.00002/1K · 1024d · fastest value",
            "cohere.embed-multilingual-v3": "93.3% acc · $0.0001/1K · 1024d",
            "cohere.embed-v4:0": "93.3% acc · $0.0001/1K · 1536d · newest",
            "cohere.embed-english-v3": "93.3% acc · $0.0001/1K · 1024d",
            "amazon.titan-embed-g1-text-02": "86.7% acc · $0.0001/1K · 1536d",
            "amazon.titan-embed-text-v1": "86.7% acc · $0.0001/1K · 1536d",
            "amazon.titan-embed-image-v1": "80.0% acc · $0.0001/1K · 1024d · multimodal",
            "amazon.nova-2-multimodal-embeddings-v1:0": "multimodal · up to 3072d · unique schema",
        }
        embed_models = []
        seen_embed: set = set()
        for m in models:
            mid = m["modelId"]
            mods_out = set(m.get("outputModalities", []))
            status = m.get("modelLifecycle", {}).get("status", "")
            if status not in ("ACTIVE", "LEGACY"):
                continue
            if "EMBEDDING" not in mods_out:
                continue
            if "TEXT" not in set(m.get("inputModalities", [])):
                continue
            # Use the base model ID (strip size variants like :8k, :512)
            base_id = mid
            for suffix in (":8k", ":512", ":2:8k", ":0:8k", ":0:512"):
                if mid.endswith(suffix):
                    base_id = mid[: -len(suffix)]
                    break
            # Deduplicate by model family (e.g. "cohere.embed-english-v3" covers both bare and :0)
            family = base_id.rstrip(":0").rstrip(":")  # normalize trailing :0
            if family in seen_embed:
                continue
            seen_embed.add(family)
            # Prefer the :0 versioned ID for consistency
            if not base_id.endswith(":0") and ":" not in base_id.split(".")[-1]:
                # Check if a :0 version exists in rankings
                if base_id + ":0" in _embed_rankings:
                    base_id = base_id + ":0"
            provider = m.get("providerName", "")
            # Look up ranking tag
            tag = ""
            for key, val in _embed_rankings.items():
                if key in base_id or base_id.startswith(key.split(":")[0]):
                    tag = val
                    break
            label = f"{provider} / {base_id}"
            if tag:
                label += f"  [{tag}]"
            embed_models.append({"id": base_id, "label": label})
        embed_models.sort(key=lambda x: ("★" not in x["label"], x["label"]))

        return {"qa": qa_models, "vision": vision_models, "embedding": embed_models}
    except Exception as e:
        return {"qa": [], "vision": [], "embedding": [], "error": str(e)}


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

    # Task-specific recommendations based on testing
    if "nova-pro" in mid:
        tags.append("great for Q&A · fast JSON")
    elif "nemotron-super" in mid:
        tags.append("excellent all-rounder · fast")
    elif "nemotron-nano-3-30b" in mid or "nemotron-nano-12b" in mid:
        tags.append("good for Q&A · fast")
    elif "mistral-large-3" in mid or "magistral" in mid:
        tags.append("fastest · strong JSON · good for templates")
    elif "deepseek" in mid and "r1" not in mid:
        tags.append("strong reasoning · slower generation")
    elif "claude-3-sonnet-2024" in mid:
        tags.append("best for document generation")
    elif "gpt-oss-120b" in mid:
        tags.append("needs inference profile")
    elif "gpt-oss-20b" in mid:
        tags.append("needs inference profile")

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
    qa_model = os.getenv("BEDROCK_MODEL_ID", "qwen.qwen3-32b-v1:0")
    vision_model = os.getenv("BEDROCK_VISION_MODEL_ID", "mistral.ministral-3-3b-instruct")
    gen_model = os.getenv("BEDROCK_GENERATE_MODEL_ID", "amazon.nova-pro-v1:0")
    task_model = os.getenv("BEDROCK_TASK_MODEL_ID", "amazon.nova-pro-v1:0")
    task_single = os.getenv("BEDROCK_TASK_SINGLE_MODEL_ID", "nvidia.nemotron-super-3-120b")
    task_multi = os.getenv("BEDROCK_TASK_MULTI_MODEL_ID", "meta.llama3-3-70b-instruct-v1:0")
    detect_model = os.getenv("BEDROCK_DETECT_MODEL_ID", "meta.llama3-8b-instruct-v1:0")
    template_model = os.getenv("BEDROCK_TEMPLATE_MODEL_ID", "mistral.magistral-small-2509")
    embed_model = os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    return {
        "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
        "BEDROCK_MODEL_ID": qa_model,
        "BEDROCK_GENERATE_MODEL_ID": gen_model,
        "BEDROCK_TASK_MODEL_ID": task_model,
        "BEDROCK_TASK_SINGLE_MODEL_ID": task_single,
        "BEDROCK_TASK_MULTI_MODEL_ID": task_multi,
        "BEDROCK_DETECT_MODEL_ID": detect_model,
        "BEDROCK_TEMPLATE_MODEL_ID": template_model,
        "BEDROCK_VISION_MODEL_ID": vision_model,
        "BEDROCK_EMBED_MODEL_ID": embed_model,
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
        "BEDROCK_TASK_MODEL_ID",
        "BEDROCK_TASK_SINGLE_MODEL_ID",
        "BEDROCK_TASK_MULTI_MODEL_ID",
        "BEDROCK_DETECT_MODEL_ID",
        "BEDROCK_TEMPLATE_MODEL_ID",
        "BEDROCK_VISION_MODEL_ID",
        "BEDROCK_EMBED_MODEL_ID",
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
    # Reset embedding client so model change takes effect
    from . import search as _search_mod
    _search_mod._bedrock_runtime = None
    return {"applied": applied}
