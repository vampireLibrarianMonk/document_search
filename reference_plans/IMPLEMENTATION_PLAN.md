# House Document Search — Full Implementation Plan

## 1) Goal and Delivery Sequence

Convert the requirements in `raw_input.md` into an executable implementation roadmap delivered in this exact order:

1. **Locally hosted (HTTP) MVP**
2. **Containerized locally (Docker Compose)**
3. **Upgraded to local HTTPS**

This plan is structured so each stage is production-aligned, testable, and builds directly on the previous stage.

---

## 2) Scope Summary from Raw Input

### Product Objective
Build a house-document search system that supports:

- Upload + Confluence ingest
- Keyword + semantic + hybrid search
- Q&A over retrieved chunks with citations
- Secure, ACL-aware retrieval and document access

### Core Tech Choices

- **Frontend:** Vue 3 + Router + Composition API
- **Backend:** Python (FastAPI recommended)
- **Search:** OpenSearch (vector + BM25 hybrid)
- **LLM/Embeddings:** Amazon Bedrock
- **Source:** Confluence Cloud REST/CQL + uploaded files

### Delivery Strategy

- **MVP (Phase 1):** Upload + Confluence pages + chunk/index + search + cited Q&A
- **Phase 2:** ACL-aware retrieval, attachments, incremental sync, admin improvements
- **Phase 3:** OCR, advanced automation, assistant workflows

---

## 3) Target Local Architecture (All Three Stages)

### Services

1. `frontend` (Vue app)
2. `api` (FastAPI)
3. `worker` (ingestion/sync pipeline jobs)
4. `opensearch` (local search engine)
5. `postgres` (document registry/job state) or DynamoDB-local equivalent
6. `localstack` (optional for S3/SQS emulation) **or** MinIO + Redis alternative
7. `reverse-proxy` (Nginx/Caddy; introduced in HTTPS stage)

### Data Flow

1. Upload file / sync Confluence page
2. Parse + normalize + chunk + metadata enrich
3. Generate embeddings (Bedrock or local mock in dev)
4. Index chunks/documents into OpenSearch
5. `/search` and `/ask` execute hybrid retrieval + Bedrock answer generation
6. Return answer + citations + source links

---

## 4) Repository Layout

```text
house-doc-search/
  frontend/
  backend/
    app/
      api/
      services/
      workers/
      ingestion/
        parsers/
        chunkers/
        embeddings/
        indexers/
      rag/
      auth/
      settings/
  infra/
    docker/
      compose/
      nginx/
      certs/
  docs/
    requirements/
    api/
    runbooks/
```

---

## 5) Stage 1 — Locally Hosted (HTTP-first)

## Objective
Run frontend + backend locally on developer machine, integrated with local OpenSearch, with core APIs and MVP workflows functional.

## Deliverables

- Vue search UI with:
  - search bar
  - mode selector (keyword/semantic/hybrid/ask)
  - filters and results list
- FastAPI endpoints:
  - `POST /search`
  - `POST /ask`
  - `POST /ingest/upload`
  - `POST /sources/confluence/sync`
  - `GET /documents/{id}` + chunks
- Ingestion pipeline:
  - PDF/DOCX parsing
  - chunking
  - metadata enrichment
  - embedding generation adapter
  - OpenSearch indexing
- Basic auth skeleton + audit log hooks

## Implementation Tasks

### A. Project bootstrap

- Initialize `frontend` with Vue 3 + Router + TypeScript
- Initialize `backend` with FastAPI + Pydantic + Alembic
- Add shared `.env.example` files for both

### B. Backend domain + APIs

- Define models:
  - Document
  - Chunk
  - SourceSyncJob
  - IngestionJob
- Implement API contracts from raw input
- Add OpenAPI docs and request/response validation

### C. Ingestion pipeline

- Upload endpoint writes source file to local object storage path
- Parsers:
  - PDF text extraction
  - DOCX extraction
- Normalize + section heuristics + chunker
- Metadata mapper (document_type, source_type, tags, ACL placeholders)

### D. Search/RAG

- OpenSearch index templates:
  - `house_documents`
  - `house_document_chunks`
- Hybrid retrieval routine:
  - BM25 query
  - vector query
  - merge/rerank
  - metadata filter support
- `/ask` flow:
  - top-k retrieval
  - Bedrock prompt assembly
  - answer + citations structure

### E. Confluence connector

- REST client for pages and metadata
- CQL search endpoint support
- Manual sync trigger endpoint

### F. Frontend MVP pages

- Search page
- Result detail page
- Lightweight admin page for job status/sync trigger

### G. Local run scripts

- `make dev-backend`
- `make dev-frontend`
- `make dev-all`

## Example Local Commands (Stage 1)

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Stage 1 Exit Criteria

- Can upload PDF/DOCX and see ingestion job complete
- `POST /search` returns hybrid results with facets/filter behavior
- `POST /ask` returns answer + citations only from retrieved chunks
- UI can open source links and show snippet/chunk context

---

## 6) Stage 2 — Containerized Locally (Docker)

## Objective
Package all local services in Docker and run with one command, preserving Stage 1 behavior.

## Deliverables

- Dockerfiles for frontend and backend/worker
- `docker-compose.yml` for complete local stack
- Health checks + startup ordering
- Volume strategy for data persistence

## Implementation Tasks

### A. Dockerfiles

- `frontend/Dockerfile`
  - multi-stage Node build + static serving
- `backend/Dockerfile`
  - python slim base, dependencies, app startup
- `backend/worker.Dockerfile` (or shared image + different command)

### B. Compose orchestration

Services:

- `frontend`
- `api`
- `worker`
- `opensearch`
- `postgres`
- `minio` (or localstack)
- `redis` (if used for background queue)

Add:

- service healthchecks (`/health`, ping checks)
- dependency order with `depends_on` + health conditions
- named volumes:
  - `opensearch_data`
  - `postgres_data`
  - `minio_data`

### C. Runtime configuration

- Create `env/local.env`
- Ensure container-to-container hostnames are used (e.g., `http://api:8000`)
- Add profile-based settings for `dev`, `container-local`

### D. Developer ergonomics

- `make up`, `make down`, `make logs`, `make ps`
- Seed script for sample documents and sample Confluence payload

## Example Local Commands (Stage 2)

```bash
docker compose -f infra/docker/compose/docker-compose.yml up --build -d
docker compose -f infra/docker/compose/docker-compose.yml ps
docker compose -f infra/docker/compose/docker-compose.yml logs -f api
```

## Stage 2 Exit Criteria

- Full stack starts with one compose command
- Frontend can call backend via container network
- Upload/sync/search/ask work end-to-end in containers
- Data persists across container restarts

---

## 7) Stage 3 — Upgrade to Local HTTPS

## Objective
Serve frontend and API securely over HTTPS in local development to mirror production security posture.

## Deliverables

- Local CA + trusted certs (recommended: `mkcert`)
- TLS termination via reverse proxy (Nginx or Caddy)
- HTTPS routing for UI + API
- Redirect HTTP -> HTTPS

## Implementation Tasks

### A. Certificate strategy

Preferred:

- Install `mkcert`
- Generate local cert for domains such as:
  - `app.localhost`
  - `api.localhost`

Artifacts:

- `infra/docker/certs/local-dev.pem`
- `infra/docker/certs/local-dev-key.pem`

### B. Reverse proxy container

- Add `reverse-proxy` service to compose
- Bind ports:
  - `80:80`
  - `443:443`
- Route:
  - `https://app.localhost` -> frontend
  - `https://api.localhost` -> backend API

### C. App config updates

- Set frontend API base URL to `https://api.localhost`
- Enable CORS/Cookie/SameSite settings for HTTPS local domains
- If auth tokens are cookie-based, mark `Secure` and `HttpOnly`

### D. Security hardening checks

- Enforce TLS 1.2+
- Add secure headers (HSTS optional for local)
- Validate no mixed-content requests

## Example Local Commands (Stage 3)

```bash
# generate trusted local certs
mkcert -install
mkcert app.localhost api.localhost

# bring up stack including reverse proxy
docker compose -f infra/docker/compose/docker-compose.yml --profile https up -d --build
```

## Stage 3 Exit Criteria

- UI reachable via `https://app.localhost`
- API reachable via `https://api.localhost/docs`
- HTTP redirects to HTTPS
- Search and ask flows work fully over TLS

---

## 8) Detailed API Implementation Checklist

Implement and validate these endpoints in order:

1. `POST /ingest/upload`
2. `POST /search`
3. `POST /ask`
4. `GET /documents/{id}`
5. `GET /documents/{id}/chunks`
6. `POST /sources/confluence/sync`
7. `POST /admin/reindex`
8. `GET /admin/jobs`

For each endpoint:

- request schema validation
- auth guard (stub in MVP)
- structured error responses
- audit log event
- latency metric + trace ID

---

## 9) OpenSearch Design Implementation Plan

## Indexes

1. `house_documents`
2. `house_document_chunks`

## Mapping requirements

- `content_vector` as `knn_vector`
- keyword fields for exact filters (`document_type`, `source_type`, `tags`, `acl`)
- text fields with analyzers for BM25

## Query strategy

- Run keyword query + vector query in parallel
- Apply metadata and ACL filters at query time
- Merge by weighted score
- Group by `document_id` for UI display

## Validation

- relevance smoke tests with sample queries
- filter correctness tests (`HOA`, date ranges, source type)

---

## 10) Security Implementation Plan (Local-to-Prod Ready)

## MVP controls (must implement now)

- Auth middleware scaffold (JWT or session)
- Per-document ACL field propagated through ingestion
- Authorization filter injected into all retrieval queries
- Audit events for search/view/download/admin actions

## Next controls (phase 2+)

- Source-derived ACL propagation (Confluence permissions)
- PII redaction policy for previews and prompts
- prompt context guardrail (authorized chunks only)

---

## 11) Testing and Verification Plan

## Automated tests

- Unit tests:
  - parsers/chunker/metadata mapping
  - query builders
  - citation formatter
- Integration tests:
  - upload -> parse -> index -> search
  - ask flow with mocked Bedrock
- Contract tests:
  - endpoint schema verification

## Manual test scenarios

1. “Find HOA rules about sheds” (hybrid + filter)
2. “What does inspection say about roof?” (`/ask` with citations)
3. “Show only HOA docs from 2026” (metadata filter validation)
4. Unauthorized ACL simulation (result suppression)

---

## 12) Implementation Timeline (Practical)

## Week 1–2: Stage 1 (local hosted)

- API scaffolding, ingestion core, OpenSearch wiring, UI MVP

## Week 3: Stage 2 (containerization)

- Dockerfiles, compose, healthchecks, seed data, dev scripts

## Week 4: Stage 3 (local HTTPS)

- Cert generation, reverse proxy, secure config, TLS testing

## Week 5+: Phase 2 capabilities

- ACL propagation, Confluence attachments, incremental sync, admin depth

---

## 13) Risks and Mitigations

1. **Confluence API variability/rate limits**
   - Mitigation: incremental cursoring, retry/backoff, sync checkpoints

2. **Embedding/LLM cost and latency**
   - Mitigation: batching, caching, top-k caps, observability metrics

3. **Hybrid relevance quality**
   - Mitigation: tune score weights, rerank strategy, query analytics

4. **Local HTTPS complexity**
   - Mitigation: standardize on mkcert + checked-in proxy templates

---

## 14) Final Acceptance Criteria for This Plan

This implementation is complete when:

1. Team can run system on localhost over HTTP with full MVP workflow.
2. Team can run same workflow in local containers with one compose command.
3. Team can run same workflow over trusted local HTTPS with TLS termination and HTTP redirect.
4. Search/Q&A always return citations, and ACL filtering is enforceable in retrieval path.
