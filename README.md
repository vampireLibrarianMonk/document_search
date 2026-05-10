# House Document Search

This is a tool that helps you search through house-related documents like HOA rules, inspection reports, closing paperwork, insurance policies, and anything else that comes with buying or owning a home. Instead of digging through a pile of PDFs and Word docs trying to find that one paragraph about fence height limits or what the inspector said about the roof, you can upload your files and just search or ask questions in plain English. The app breaks your documents into smaller pieces, scores them for relevance, and gives you back the most useful snippets along with where they came from. Think of it like having a personal assistant who has actually read all your paperwork.

When you upload a document, the app automatically reads the content (including scanned pages using AI vision), figures out what kind of document it is (closing disclosure, HOA bylaws, appraisal, etc.), and files it into the right category. Documents are also pushed to BookStack (a local wiki) so you can browse and manage them there. You can also sync documents from Confluence Cloud when you are ready to move to the cloud.

## Architecture

![Architecture](docs/diagrams/architecture.png)

## How to Use It

### Uploading Documents

1. Open the app in your browser at `http://localhost:5173` (or `https://app.localhost` if running with HTTPS)
2. Pick individual files or select an entire folder using the two file pickers
3. Click "Upload" and watch the live progress log as each file is extracted, classified, and indexed
4. Documents are automatically categorized (Closing Documents, HOA Governance, Insurance, etc.) and appear in the list at the bottom
5. Each document is also pushed to BookStack, organized by category

You can select multiple folders before uploading. Each selection accumulates, so pick folder A, then folder B, then hit Upload to process everything in one batch.

During upload, a red "Cancel" button appears next to the progress indicator. Click it to stop processing remaining files (already-processed files are kept).

### Managing Documents

- Click any document title to open or download the original file
- Click the 👁 icon to view the full extracted text inline (scrollable, collapsible)
- Click the "x" button next to any document to delete it (removes from search index, database, and BookStack)
- Click "Clear All" to wipe everything and start fresh
- Documents are grouped by category with collapsible sections

### Searching

1. Make sure the "Search" toggle is selected (it is by default)
2. Type what you are looking for in the search bar, something like "rules about sheds" or "roof condition"
3. Hit Enter or click the Search button
4. Results show up below with the document name, type, relevance score, and a snippet of the matching text

### Asking Questions

1. Click the "Ask AI" toggle next to the search bar
2. Type a question like "What is the email address for my HOA?"
3. Hit Enter or click Ask
4. You will get a plain English answer powered by Amazon Bedrock along with citations showing exactly which documents the answer came from

### Settings

Click the "Settings" tab to access:

- **Service Health**: connectivity status and version info for all services (AWS, Postgres, OpenSearch, BookStack, Confluence)
- **Configuration**: select your Ask AI, Create Document, and Vision OCR models (with cost/speed labels), set AWS region, configure BookStack and Confluence credentials, toggle usage tracking, set upload concurrency
- **Token Usage & Cost**: track API calls, token counts, and estimated costs per model and per day. Pricing is pulled live from the AWS bulk pricing JSON

### How Documents Are Processed

![Ingestion Pipeline](docs/diagrams/ingestion.png)

When you upload a PDF, the app handles each page individually:

- Pages with text are read directly using pypdf (free, instant)
- Scanned pages with no text layer are sent to the selected Vision OCR model via Bedrock Converse API (costs about $0.002 per page)
- Mixed pages with both text and images get both extracted and merged so nothing is missed

### How Search and Ask Work

![Search and Ask Flow](docs/diagrams/search_ask.png)

### Syncing from BookStack

BookStack is a local wiki that runs alongside the app. When you upload through the app, documents are automatically organized in BookStack by category. You can also manage documents directly in BookStack and sync them back.

1. Open BookStack at `http://localhost:6875` (default login: `admin@admin.com` / `password`)
2. Create a book, add pages, and attach your PDFs
3. Generate an API token in your BookStack profile settings
4. Add the token to Settings > Configuration (or `deployment/docker/local.env`)
5. Sync: `curl -X POST http://localhost:8000/sources/bookstack/sync`

### Syncing from Confluence Cloud

When you are ready to move to Confluence Cloud, the connector is built and ready.

1. Sign up at https://www.atlassian.com/software/confluence (free tier works)
2. Create a space, upload your PDFs as page attachments
3. Generate an API token at https://id.atlassian.com/manage-profile/security/api-tokens
4. Add your site URL, email, and token to Settings > Configuration
5. Sync: `curl -X POST http://localhost:8000/sources/confluence/sync -H 'Content-Type: application/json' -d '{"space_keys":["YOUR_SPACE"]}'`

### Supported File Types

- PDF (.pdf) including scanned documents
- Word documents (.docx, .doc) including inline images
- Images (.jpg, .jpeg, .png, .tiff, .tif) processed via vision OCR
- Plain text (.txt)
- Markdown (.md)

## Creating Documents

Click the "Create" tab to generate new documents from your indexed content.

1. Type what you want to create (e.g., "Fill out an exterior modification application for a roof replacement")
2. Optionally select specific source documents, or let the app auto-search for relevant content
3. Pick an output format and click Generate
4. Preview the content, then Download in your chosen format

### Output Formats

| Format             | What you get                                                                       |
| ------------------ | ---------------------------------------------------------------------------------- |
| Markdown (.md)     | Clean text with headings and bullets                                               |
| Word (.docx)       | Styled document with Calibri font, proper headings, bullet points, and form fields |
| PDF (.pdf)         | Formatted report suitable for printing or sharing                                  |
| Image (.png)       | Single-page visual reference card                                                  |
| PowerPoint (.pptx) | Presentation with navy/white theme, title slide, content slides with bullets       |

### How It Works

- The app searches your indexed documents for relevant content
- Sends that content plus your request to the selected generation model (configurable in Settings)
- Bedrock writes the document grounded in your actual house documents
- The markdown is converted to your chosen format locally (no additional API calls)
- Form requests are auto-detected and generate proper form fields with blanks, checkboxes, and signature lines

### Model Selection

Three separate models can be configured in Settings:

- **Ask AI Model** - For quick Q&A answers (use a cheap/fast model)
- **Create Document Model** - For document generation (use a balanced/quality model for better output)
- **Vision OCR Model** - For reading scanned pages

## Running the App

There are three ways to run it: locally without containers, with Docker Compose over HTTP, or with Docker Compose over HTTPS. See [README-SETUP.md](README-SETUP.md) for full setup instructions.

Quick start with Docker:

```bash
make up
```

Or with HTTPS (adds a Caddy reverse proxy for TLS termination):

```bash
make certs
make up-https
```

If you previously started local dev with `make dev-all`, stop that first before switching to HTTPS so port `5173` is free for Docker.

Or locally without containers:

```bash
source .venv/bin/activate
make dev-all
```

Or with Kubernetes (k3s + Helm):

```bash
make k3s-install    # one time
make k3s-up         # deploy
make k3s-status     # check pods
```

See [deployment/kubernetes/helm/README-SETUP.md](deployment/kubernetes/helm/README-SETUP.md) for full k8s setup.

## Docker Services

![Docker Services](docs/diagrams/containers.png)

## Data Model

![Data Model](docs/diagrams/data_model.png)

## API

The backend has a full REST API. Once running, visit `http://localhost:8000/docs` (or `https://api.localhost/docs` with HTTPS) for the interactive documentation.

Key endpoints:

- `POST /ingest/upload` - Upload a single document
- `POST /ingest/upload-bulk` - Upload multiple documents at once
- `POST /ingest/upload-stream` - Upload multiple files with live progress (SSE)
- `POST /search` - Search documents
- `POST /ask` - Ask a question and get an AI answer with citations
- `POST /generate` - Generate a document from a prompt (returns markdown)
- `POST /generate/convert` - Convert markdown to DOCX, PDF, PNG, or PPTX
- `GET /documents` - List all documents
- `GET /documents/{id}` - Get a single document
- `GET /documents/{id}/chunks` - Get a document's text chunks
- `GET /documents/{id}/file` - Download the original uploaded file
- `DELETE /documents/{id}` - Delete a document
- `DELETE /documents` - Delete all documents
- `POST /sources/bookstack/sync` - Sync from BookStack
- `POST /sources/confluence/sync` - Sync from Confluence Cloud
- `GET /admin/health-check` - Service health with versions
- `GET /admin/config` - Current configuration
- `PUT /admin/config` - Update configuration at runtime
- `GET /admin/models` - Available Bedrock models with labels
- `GET /admin/usage` - Token usage and cost summary
- `GET /admin/pricing` - Current Bedrock pricing for the region
- `PUT /admin/pricing` - Manually load pricing JSON
- `POST /admin/cancel-upload` - Cancel in-progress uploads
- `GET /admin/k8s-health` - Kubernetes pod status and metrics
- `GET /admin/jobs` - Background job status
- `POST /admin/reindex` - Trigger a reindex

## Testing

```bash
make test              # unit tests (no containers needed)
make test-integration  # integration tests (needs running containers)
make test-all          # everything
make test-coverage     # with coverage report
```

119 tests across 8 test files covering classification, extraction, schemas, services, API routes, BookStack client, Confluence client, and full HTTP/HTTPS integration.
