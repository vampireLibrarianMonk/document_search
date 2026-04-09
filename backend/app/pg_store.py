"""Persistent document and chunk store backed by Postgres.

Replaces the in-memory LocalStore so data survives container restarts.
"""

from __future__ import annotations

import os
import uuid

import psycopg2.extras

from .db import get_conn, init_db
from .schemas import ChunkRecord, DocumentResponse, JobResponse


class PgStore:
    def __init__(self) -> None:
        self.upload_dir = os.path.join(os.getenv("DATA_DIR", "data"), "uploads")
        os.makedirs(self.upload_dir, exist_ok=True)
        init_db()

    # -- ID helpers --

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def new_job_id(self, job_type: str) -> str:
        job_id = self.new_id(job_type)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO jobs (job_id, status) VALUES (%s, %s)", (job_id, "queued"))
        finally:
            conn.close()
        return job_id

    def update_job_status(self, job_id: str, status: str) -> None:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE jobs SET status = %s WHERE job_id = %s", (status, job_id))
        finally:
            conn.close()

    # -- Document CRUD --

    def add_document(self, doc: DocumentResponse) -> None:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO documents (document_id, title, source_type, source_url, document_type, category, tags, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (document_id) DO UPDATE SET
                         title=EXCLUDED.title, category=EXCLUDED.category, tags=EXCLUDED.tags, status=EXCLUDED.status""",
                    (doc.document_id, doc.title, doc.source_type, doc.source_url,
                     doc.document_type, doc.category, doc.tags, doc.status),
                )
        finally:
            conn.close()

    def get_document(self, document_id: str) -> DocumentResponse | None:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM documents WHERE document_id = %s", (document_id,))
                row = cur.fetchone()
                return DocumentResponse(**row) if row else None
        finally:
            conn.close()

    def list_documents(self) -> list[DocumentResponse]:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM documents ORDER BY document_id")
                return [DocumentResponse(**r) for r in cur.fetchall()]
        finally:
            conn.close()

    # -- Chunk CRUD --

    def set_chunks(self, document_id: str, chunks: list[ChunkRecord]) -> None:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # Clear old chunks for this doc, then insert new ones
                cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
                for c in chunks:
                    cur.execute(
                        """INSERT INTO chunks (chunk_id, document_id, section_heading, content,
                                              source_type, document_type, tags)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (c.chunk_id, c.document_id, c.section_heading, c.content,
                         c.source_type, c.document_type, c.tags),
                    )
        finally:
            conn.close()

    def get_chunks(self, document_id: str) -> list[ChunkRecord]:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM chunks WHERE document_id = %s ORDER BY chunk_id", (document_id,))
                return [ChunkRecord(**r) for r in cur.fetchall()]
        finally:
            conn.close()

    def all_chunks(self) -> list[tuple[DocumentResponse, ChunkRecord]]:
        """Return (document, chunk) pairs across all documents."""
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT d.document_id as d_document_id, d.title, d.source_type as d_source_type,
                           d.source_url, d.document_type as d_document_type, d.tags as d_tags, d.status,
                           c.chunk_id, c.document_id, c.section_heading, c.content,
                           c.source_type, c.document_type, c.tags
                    FROM chunks c JOIN documents d ON c.document_id = d.document_id
                """)
                results = []
                for r in cur.fetchall():
                    doc = DocumentResponse(
                        document_id=r["d_document_id"], title=r["title"],
                        source_type=r["d_source_type"], source_url=r["source_url"],
                        document_type=r["d_document_type"], tags=r["d_tags"], status=r["status"],
                    )
                    chunk = ChunkRecord(
                        chunk_id=r["chunk_id"], document_id=r["document_id"],
                        section_heading=r["section_heading"], content=r["content"],
                        source_type=r["source_type"], document_type=r["document_type"],
                        tags=r["tags"],
                    )
                    results.append((doc, chunk))
                return results
        finally:
            conn.close()

    def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks. Returns True if found."""
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE document_id = %s", (document_id,))
                return cur.rowcount > 0
        finally:
            conn.close()

    def delete_all_documents(self) -> int:
        """Delete all documents and chunks. Returns count deleted."""
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chunks")
                cur.execute("DELETE FROM documents")
                return cur.rowcount
        finally:
            conn.close()

    # -- Jobs --

    def get_jobs(self) -> list[JobResponse]:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT job_id, status FROM jobs ORDER BY created_at DESC LIMIT 100")
                return [JobResponse(**r) for r in cur.fetchall()]
        finally:
            conn.close()
