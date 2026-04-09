"""Pydantic models for API requests and responses."""

from typing import Any

from pydantic import BaseModel, Field


# -- Search --

class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: str = Field(default="hybrid")
    filters: dict[str, Any] = Field(default_factory=dict)
    page: int = 1
    page_size: int = 10


class SearchResult(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    snippet: str
    score: float
    source_type: str
    document_type: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)
    timing_ms: int


# -- Ask (RAG) --

class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    top_k: int = 15


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    snippet: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    documents: list[str]
    suggested_queries: list[str]


# -- Ingestion --

class UploadResponse(BaseModel):
    document_id: str
    job_id: str


class BulkUploadResponse(BaseModel):
    uploaded: list[UploadResponse]
    errors: list[str]


# -- Documents --

class DocumentResponse(BaseModel):
    document_id: str
    title: str
    source_type: str
    source_url: str
    document_type: str
    category: str = "Uncategorized"
    tags: list[str] = []
    status: str


class ChunkRecord(BaseModel):
    chunk_id: str
    document_id: str
    section_heading: str
    content: str
    source_type: str
    document_type: str
    tags: list[str]


class ChunkListResponse(BaseModel):
    document_id: str
    chunks: list[ChunkRecord]


# -- Confluence --

class ConfluenceSyncRequest(BaseModel):
    space_keys: list[str] = Field(default_factory=list)
    full_sync: bool = False
    since: str | None = None


# -- Jobs --

class JobResponse(BaseModel):
    job_id: str
    status: str
