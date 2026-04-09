"""FastAPI routes for the House Document Search API."""

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    SearchRequest,
    SearchResponse,
    AskRequest,
    AskResponse,
    UploadResponse,
    BulkUploadResponse,
    DocumentResponse,
    ChunkListResponse,
    ConfluenceSyncRequest,
    JobResponse,
)
from .storage import LocalStore
from .pg_store import PgStore
from .services import ingest_file_to_store, run_search, run_ask

app = FastAPI(title="House Document Search API", version="0.1.0")

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


# -- Health / root --

@app.get("/")
def root():
    return {"message": "House Document Search API", "docs": "/docs"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


from .confluence import ConfluenceClient
from .bookstack import BookStackClient
from . import search as os_search

_confluence = ConfluenceClient()
_bookstack = BookStackClient()


@app.on_event("startup")
def _startup():
    """Initialize OpenSearch index on startup."""
    try:
        os_search.ensure_index()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("OpenSearch init failed: %s", e)


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


@app.post("/ingest/upload-stream")
async def ingest_upload_stream(files: list[UploadFile] = File(...)):
    """Upload multiple files with SSE progress updates per file."""
    from starlette.responses import StreamingResponse
    from starlette.datastructures import UploadFile as StarletteUpload
    import json as _json
    from io import BytesIO

    # Read all file contents upfront before streaming begins
    file_data = []
    for f in files:
        content = await f.read()
        file_data.append((f.filename or "unknown", content))

    async def _stream():
        total = len(file_data)
        ok, fail = 0, 0
        for i, (name, content) in enumerate(file_data, start=1):
            yield f"data: {_json.dumps({'type': 'progress', 'file': name, 'step': 'uploading', 'current': i, 'total': total})}\n\n"
            try:
                fake_file = StarletteUpload(filename=name, file=BytesIO(content))
                result = await ingest_file_to_store(store, fake_file)
                ok += 1
                doc = store.get_document(result.document_id)
                cat = doc.category if doc else "Uncategorized"
                dtype = doc.document_type if doc else "general"
                yield f"data: {_json.dumps({'type': 'done', 'file': name, 'current': i, 'total': total, 'document_id': result.document_id, 'category': cat, 'document_type': dtype})}\n\n"
            except Exception as exc:
                fail += 1
                yield f"data: {_json.dumps({'type': 'error', 'file': name, 'current': i, 'total': total, 'error': str(exc)})}\n\n"
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

    for space_key in (req.space_keys or ["HOUSE"]):
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


# -- Admin --

@app.delete("/documents/{document_id}")
def delete_document(document_id: str):
    """Delete a single document and its chunks from all stores."""
    # Get the title before deleting so we can clean up BookStack
    doc = store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove from OpenSearch
    try:
        os_search.get_client().delete_by_query(
            index=os_search.INDEX_NAME,
            body={"query": {"term": {"document_id": document_id}}},
            ignore=[404],
        )
    except Exception:
        pass

    # Remove from BookStack
    try:
        if _bookstack.configured:
            _bookstack.delete_attachment_by_name(doc.title)
    except Exception:
        pass

    store.delete_document(document_id)
    return {"deleted": document_id}


@app.delete("/documents")
def delete_all_documents():
    """Delete all documents and chunks from all stores."""
    # Remove from OpenSearch
    try:
        os_search.get_client().delete_by_query(
            index=os_search.INDEX_NAME,
            body={"query": {"match_all": {}}},
            ignore=[404],
        )
    except Exception:
        pass

    # Remove from BookStack
    try:
        if _bookstack.configured:
            _bookstack.delete_all_attachments()
            _bookstack.delete_empty_pages_and_books()
    except Exception:
        pass

    count = store.delete_all_documents()
    return {"deleted": count}

@app.get("/admin/jobs", response_model=list[JobResponse])
def admin_jobs() -> list[JobResponse]:
    return store.get_jobs()


@app.post("/admin/reindex", response_model=JobResponse)
def admin_reindex() -> JobResponse:
    return JobResponse(job_id=store.new_job_id("reindex"), status="queued")
