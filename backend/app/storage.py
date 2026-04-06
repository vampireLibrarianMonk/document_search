from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

from .schemas import ChunkRecord, DocumentResponse, JobResponse


@dataclass
class LocalStore:
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))

    def __post_init__(self) -> None:
        self.documents: dict[str, DocumentResponse] = {}
        self.chunks_by_doc: dict[str, list[ChunkRecord]] = {}
        self.jobs: list[JobResponse] = []
        self.upload_dir = os.path.join(self.data_dir, "uploads")
        os.makedirs(self.upload_dir, exist_ok=True)

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def new_job_id(self, job_type: str) -> str:
        job_id = self.new_id(job_type)
        self.jobs.insert(0, JobResponse(job_id=job_id, status="queued"))
        return job_id

    def update_job_status(self, job_id: str, status: str) -> None:
        for i, job in enumerate(self.jobs):
            if job.job_id == job_id:
                self.jobs[i] = JobResponse(job_id=job.job_id, status=status)
                return

    def add_document(self, document: DocumentResponse) -> None:
        self.documents[document.document_id] = document

    def set_chunks(self, document_id: str, chunks: list[ChunkRecord]) -> None:
        self.chunks_by_doc[document_id] = chunks

    def get_document(self, document_id: str) -> DocumentResponse | None:
        return self.documents.get(document_id)

    def get_chunks(self, document_id: str) -> list[ChunkRecord]:
        return self.chunks_by_doc.get(document_id, [])

    def list_documents(self) -> list[DocumentResponse]:
        return list(self.documents.values())

    def get_jobs(self) -> list[JobResponse]:
        return self.jobs
