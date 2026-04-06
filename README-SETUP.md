# Setup Guide

This covers everything you need to get the app running on your machine. There are three options: run locally without containers, run with Docker Compose over HTTP, or run with Docker Compose over HTTPS.

## Prerequisites

You will need the following installed before you start:

- Python 3.10 or newer
- Node.js 20 or newer (with npm)
- Docker and Docker Compose (only needed if you want to run with containers)
- mkcert (only needed if you want local HTTPS)

## Option 1: Run Locally (No Containers)

This is the quickest way to get up and running for development.

### 1. Clone the repo and enter the directory

```bash
git clone <your-repo-url>
cd document_search
```

### 2. Set up the Python virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install backend dependencies

```bash
pip install -r backend/requirements-dev.txt
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 5. Start both services

You can start them together:

```bash
source .venv/bin/activate
make dev-all
```

Or start them separately in two terminals:

Terminal 1 (backend):
```bash
source .venv/bin/activate
make dev-backend
```

Terminal 2 (frontend):
```bash
make dev-frontend
```

### 6. Open the app

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Option 2: Run with Docker Compose (HTTP)

This starts the full stack including OpenSearch, Postgres, and MinIO alongside the app.

### 1. Build and start everything

```bash
make up
```

That is it. Docker Compose will build the images and start all six services:

- Frontend (port 5173)
- Backend API (port 8000)
- Background worker
- OpenSearch (port 9200)
- Postgres (port 5432)
- MinIO object storage (port 9000, console on 9001)

### 2. Check that everything is running

```bash
make ps
```

You should see all services listed as healthy or running.

### 3. Open the app

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs

### 4. View logs

```bash
make logs
```

### 5. Stop everything

```bash
make down
```

## Option 3: Run with Docker Compose (HTTPS)

This adds a Caddy reverse proxy in front of the app so everything runs over HTTPS with trusted local certificates. It includes all the same services from Option 2 plus the reverse proxy.

### 1. Install mkcert

Ubuntu/Debian:
```bash
sudo apt install mkcert
```

macOS:
```bash
brew install mkcert
```

### 2. Generate local certificates

```bash
make certs
```

This creates trusted certificates for `app.localhost` and `api.localhost` in `infra/docker/certs/`. You only need to do this once.

### 3. Build and start everything with HTTPS

```bash
make up-https
```

This starts all the same services as Option 2 plus a Caddy reverse proxy that handles TLS termination.

### 4. Open the app

- Frontend: https://app.localhost
- Backend API docs: https://api.localhost/docs
- Health check: https://api.localhost/health

HTTP requests to `http://app.localhost` and `http://api.localhost` automatically redirect to HTTPS.

### 5. Stop everything

```bash
make down
```

## Environment Variables

The backend reads from environment variables. A template is provided at `backend/.env.example`:

```
APP_ENV=dev
APP_HOST=0.0.0.0
APP_PORT=8000
DATA_DIR=data
```

When running with Docker Compose, the container environment is configured through `infra/docker/compose/local.env` and you should not need to change anything for local development.

## Quick Verification

Once the app is running (any option), you can verify it works with a quick curl. Swap the URLs for `https://api.localhost` if you are using Option 3.

```bash
# Check the API is up
curl http://localhost:8000/health

# Upload a test file
echo "HOA rules say fences must be under 6 feet." > /tmp/test.txt
curl -F "file=@/tmp/test.txt" http://localhost:8000/ingest/upload

# Search for it
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "fence height", "mode": "hybrid", "filters": {}, "page": 1, "page_size": 10}'
```

## Project Structure

```
document_search/
  backend/
    app/
      __init__.py        # Package init
      main.py            # FastAPI routes
      schemas.py         # Request/response models
      services.py        # Ingestion, search, and ask logic
      storage.py         # In-memory document store
      worker.py          # Background worker (placeholder)
    .env.example
    requirements-dev.txt
    Dockerfile
  frontend/
    src/
      main.ts            # Vue app (search, upload, results UI)
    index.html
    package.json
    tsconfig.json
    vite.config.ts
    Dockerfile
    nginx.conf
  infra/
    docker/
      caddy/
        Caddyfile        # Reverse proxy config for HTTPS
      certs/
        generate.sh      # Certificate generation script
      compose/
        docker-compose.yml
        local.env
  Makefile
  README.md
  README-SETUP.md
```
