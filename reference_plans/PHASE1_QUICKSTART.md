# Phase 1 Quickstart (Local HTTP)

This bootstraps the first working slice of the implementation plan:

- Upload documents (PDF/DOCX/TXT/MD)
- Local ingestion + chunking
- Search endpoint
- Ask endpoint with citations
- Minimal Vue UI

## 1) Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
make dev-backend
```

Backend runs at: `http://localhost:8000`
Docs: `http://localhost:8000/docs`

## 2) Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Frontend runs at: `http://localhost:5173`

## 3) Manual API checks (optional)

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"inspection","mode":"hybrid","filters":{},"page":1,"page_size":10}'
```

## Notes

- Current search is in-memory scoring for Phase 1 kickoff.
- OpenSearch + Bedrock wiring is the next step.
- Confluence sync endpoint is scaffolded and currently returns queued jobs.
