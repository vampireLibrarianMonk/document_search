# Docker Compose - Infrastructure Setup

How to build and stand up the Docker Compose stack from scratch.

## Prerequisites

| Tool            | Version | Install                                              |
| --------------- | ------- | ---------------------------------------------------- |
| Docker          | 24+     | https://docs.docker.com/get-docker/                  |
| Docker Compose  | v2+     | Included with Docker Desktop                         |
| mkcert          | any     | `sudo apt install mkcert libnss3-tools` (HTTPS only) |
| AWS credentials | -       | `~/.aws/credentials` with Bedrock access             |

## Initial Setup

### 1. Clone and enter the repo

```bash
git clone <repo-url>
cd document_search
```

### 2. Build the Docker images

```bash
make build
```

This builds:

- `document-search-api` (Python 3.10 + FastAPI + Pandoc + Playwright + Chromium)
- `document-search-frontend` (Node build + Nginx)

### 3. Start the stack (HTTP)

```bash
make up
```

Services started:

- Frontend (port 5173)
- Backend API (port 8000)
- Background worker
- OpenSearch (port 9200)
- Postgres (port 5432)
- MinIO (port 9000/9001)
- BookStack (port 6875)
- BookStack MySQL

### 4. Verify

```bash
make ps                              # all services healthy
curl http://localhost:8000/health     # API responds
```

## HTTPS Setup (Optional)

### 1. Install mkcert and generate certs

```bash
sudo apt install mkcert libnss3-tools
mkcert -install
make certs
```

This generates trusted local certificates for `app.localhost` and `api.localhost`.

### 2. Start with HTTPS

```bash
make up-https
```

This adds a Caddy reverse proxy that terminates TLS on ports 80/443.

### 3. Trust the certs in your browser

If you see certificate warnings, restart your browser after `mkcert -install`.

## Configuration

Edit `deployment/docker/local.env`:

```bash
# Models (change to upgrade quality)
BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
BEDROCK_GENERATE_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
BEDROCK_VISION_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# AWS
AWS_REGION=us-east-1

# BookStack (fill in after creating API token in BookStack UI)
BOOKSTACK_TOKEN_ID=
BOOKSTACK_TOKEN_SECRET=
```

After editing, recreate the API container:

```bash
docker compose -f deployment/docker/docker-compose.yml up -d api --force-recreate
```

## Rebuilding After Code Changes

```bash
make build    # rebuild images
make up       # restart with new images
```

Or rebuild a single service:

```bash
docker compose -f deployment/docker/docker-compose.yml up --build -d api
```

## Data Persistence

Data is stored in Docker named volumes:

- `postgres_data` - document metadata, chunks, usage
- `opensearch_data` - search index
- `api_data` - uploaded files
- `minio_data` - object storage
- `bookstack_data` / `bookstack_db_data` - wiki content

These survive `make down` and `make up`. To wipe everything:

```bash
make down
docker volume rm $(docker volume ls -q | grep compose_)
```

## Troubleshooting

| Problem                     | Fix                                                                                                       |
| --------------------------- | --------------------------------------------------------------------------------------------------------- |
| Port already in use         | Stop other services on 5173/8000/9200/5432/6875                                                           |
| API can't reach Postgres    | Wait 10s after `make up`, Postgres needs to initialize                                                    |
| HTTPS cert not trusted      | Run `mkcert -install` and restart browser                                                                 |
| BookStack shows 500         | Delete bookstack volumes and restart: `docker volume rm compose_bookstack_data compose_bookstack_db_data` |
| Upload fails with NUL error | Fixed in code, rebuild API image                                                                          |
