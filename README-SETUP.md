# Setup Guide

This covers everything you need to get the app running on your machine. There are three options: run locally without containers, run with Docker Compose over HTTP, or run with Docker Compose over HTTPS.

## Prerequisites

You will need the following installed before you start:

- Python 3.10 or newer
- Node.js 20 or newer (with npm)
- Docker and Docker Compose (only needed if you want to run with containers)
- mkcert (only needed if you want local HTTPS)
- AWS credentials configured (`~/.aws/credentials`) with access to Amazon Bedrock (needed for AI answers)

## Option 1: Run Locally (No Containers)

This is the quickest way to get up and running for development. Note that OpenSearch, Postgres, and BookStack will not be available in this mode. The app will use in-memory storage and keyword search as a fallback.

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

This starts the full stack including OpenSearch, Postgres, BookStack, and MinIO alongside the app.

### 1. Build and start everything

```bash
make up
```

Docker Compose will build the images and start all services:

- Frontend (port 5173)
- Backend API (port 8000)
- Background worker
- OpenSearch (port 9200) for full-text search
- Postgres (port 5432) for persistent document storage
- MinIO (port 9000, console on 9001) for object storage
- BookStack (port 6875) for local document wiki
- BookStack MySQL database

### 2. Check that everything is running

```bash
make ps
```

You should see all services listed as healthy or running.

### 3. Open the app

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs
- BookStack: http://localhost:6875 (login: `admin@admin.com` / `password`)

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
sudo apt install mkcert libnss3-tools
mkcert -install
```

macOS:
```bash
brew install mkcert
mkcert -install
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

### 4. Open the app

- Frontend: https://app.localhost
- Backend API docs: https://api.localhost/docs
- BookStack: http://localhost:6875

HTTP requests to `http://app.localhost` and `http://api.localhost` automatically redirect to HTTPS.

### 5. Stop everything

```bash
make down
```

## Setting Up BookStack

BookStack is a local wiki that runs alongside the app. You can organize your documents there and sync them into the search system.

### 1. Log in

Open http://localhost:6875 and log in with `admin@admin.com` / `password`.

### 2. Create an API token

Go to your profile (top right) > "API Tokens" > "Create Token". Copy the Token ID and Token Secret.

### 3. Add the token to the environment

Edit `infra/docker/compose/local.env` and fill in:

```
BOOKSTACK_TOKEN_ID=your-token-id
BOOKSTACK_TOKEN_SECRET=your-token-secret
```

Then restart the API: `docker compose -f infra/docker/compose/docker-compose.yml restart api`

### 4. Organize your documents

Create books and pages in BookStack, then attach your PDFs to the pages.

### 5. Sync

```bash
curl -X POST http://localhost:8000/sources/bookstack/sync
```

This pulls all PDF attachments from BookStack and ingests them into the search system.

## Setting Up Confluence Cloud (Optional)

The Confluence connector is ready for when you want to move to Confluence Cloud.

### 1. Sign up

Go to https://www.atlassian.com/software/confluence and sign up for the free tier.

### 2. Create a space and upload documents

Create a space (e.g., key: `HOUSE`), create pages, and attach your PDFs.

### 3. Generate an API token

Go to https://id.atlassian.com/manage-profile/security/api-tokens and create a token.

### 4. Add credentials to the environment

Edit `infra/docker/compose/local.env`:

```
CONFLUENCE_URL=https://yoursite.atlassian.net
CONFLUENCE_EMAIL=your@email.com
CONFLUENCE_API_TOKEN=your-api-token
```

Restart the API, then sync:

```bash
curl -X POST http://localhost:8000/sources/confluence/sync \
  -H 'Content-Type: application/json' \
  -d '{"space_keys": ["HOUSE"]}'
```

## Environment Variables

The backend reads from environment variables. When running with Docker Compose, these are configured through `infra/docker/compose/local.env`:

```
# App
APP_ENV=container-local
DATA_DIR=data

# Postgres
POSTGRES_USER=docsearch
POSTGRES_PASSWORD=docsearch_local
POSTGRES_DB=docsearch

# OpenSearch
OPENSEARCH_HOST=opensearch
OPENSEARCH_PORT=9200

# BookStack
BOOKSTACK_URL=http://bookstack:80
BOOKSTACK_TOKEN_ID=
BOOKSTACK_TOKEN_SECRET=

# Confluence (optional, for cloud)
CONFLUENCE_URL=
CONFLUENCE_EMAIL=
CONFLUENCE_API_TOKEN=
```

## Quick Verification

Once the app is running (any option), you can verify it works:

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

# Ask a question (requires AWS Bedrock access)
curl -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What are the rules about fences?"}'
```

## Project Structure

```
document_search/
  backend/
    app/
      __init__.py          # Package init
      main.py              # FastAPI routes
      schemas.py           # Request/response models
      services.py          # Ingestion, search, and ask logic
      classifier.py        # Auto-categorization of documents
      db.py                # Postgres connection and schema
      pg_store.py          # Postgres-backed document store
      storage.py           # In-memory store (fallback)
      search.py            # OpenSearch integration
      bookstack.py         # BookStack API client
      confluence.py        # Confluence Cloud API client
      worker.py            # Background worker (placeholder)
    .env.example
    requirements-dev.txt
    Dockerfile
  frontend/
    src/
      main.ts              # Vue app (search, upload, results UI)
    index.html
    package.json
    tsconfig.json
    vite.config.ts
    Dockerfile
    nginx.conf
  infra/
    docker/
      caddy/
        Caddyfile          # Reverse proxy config for HTTPS
      certs/
        generate.sh        # Certificate generation script
      compose/
        docker-compose.yml # Full stack: app, OpenSearch, Postgres, BookStack, etc.
        local.env          # Environment variables for all services
  Makefile
  README.md
  README-SETUP.md
```
