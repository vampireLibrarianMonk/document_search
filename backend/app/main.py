from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    SearchRequest,
    SearchResponse,
    AskRequest,
    AskResponse,
    UploadResponse,
    DocumentResponse,
    ChunkListResponse,
    ConfluenceSyncRequest,
    JobResponse,
)
from .storage import LocalStore
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

store = LocalStore()


@app.get("/")
def root():
    return {"message": "House Document Search API", "docs": "/docs"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ingest/upload", response_model=UploadResponse)
async def ingest_upload(file: UploadFile = File(...)) -> UploadResponse:
    try:
        return await ingest_file_to_store(store, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest) -> SearchResponse:
    return run_search(store, payload)


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    return run_ask(store, payload)


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str) -> DocumentResponse:
    document = store.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@app.get("/documents", response_model=list[DocumentResponse])
def list_documents() -> list[DocumentResponse]:
    return store.list_documents()


@app.get("/documents/{document_id}/chunks", response_model=ChunkListResponse)
def get_document_chunks(document_id: str) -> ChunkListResponse:
    document = store.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return ChunkListResponse(document_id=document_id, chunks=store.get_chunks(document_id))


@app.post("/sources/confluence/sync", response_model=JobResponse)
def confluence_sync(_: ConfluenceSyncRequest) -> JobResponse:
    # Placeholder for Phase 1: connector comes next.
    return JobResponse(job_id=store.new_job_id("confluence_sync"), status="queued")


@app.get("/admin/jobs", response_model=list[JobResponse])
def admin_jobs() -> list[JobResponse]:
    return store.get_jobs()


@app.post("/admin/reindex", response_model=JobResponse)
def admin_reindex() -> JobResponse:
    return JobResponse(job_id=store.new_job_id("reindex"), status="queued")
