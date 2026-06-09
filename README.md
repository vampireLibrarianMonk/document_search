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
- **Task History**: set how many previous task prompts/results to keep (default: 5)

### How Documents Are Processed

![Ingestion Pipeline](docs/diagrams/ingestion.png)

When you upload a PDF, the app handles each page individually:

- Pages with text are read directly using pypdf (free, instant)
- Scanned pages with no text layer are sent to the selected Vision OCR model via Bedrock Converse API (costs about $0.002 per page)
- Mixed pages with both text and images get both extracted and merged so nothing is missed

### How Search and Ask Work

![Search and Ask Flow](docs/diagrams/search_ask.png)

Search uses a **hybrid approach** combining BM25 lexical matching with kNN vector similarity. Each chunk is embedded at indexing time using Amazon Titan Embeddings v2, and at search time both the keyword score and semantic similarity score are combined to rank results. This means you get exact-match precision *and* semantic recall — a query like "how tall can my fence be" will match a chunk about "perimeter barriers shall not exceed six feet" even though the words don't overlap.

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
| Email/Text (.txt)  | Plain text email ready to copy-paste or send                                       |

### How It Works

- The app searches your indexed documents for relevant content
- Sends that content plus your request to the selected generation model (configurable in Settings)
- Bedrock writes the document grounded in your actual documents
- The markdown is converted to your chosen format locally (no additional API calls)
- Form requests are auto-detected and generate proper form fields with blanks, checkboxes, and signature lines

### Model Selection

Six separate models can be configured in Settings:

- **Ask AI Model** — For quick Q&A answers (default: Qwen3 32B — fastest high-accuracy model, 0.58s)
- **Create Document Model** — For document/template generation (default: Amazon Nova Pro — highest quality 59/60, fast)
- **Task Model** — For the Tasks tab guided generation (default: NVIDIA Nemotron Super — 100/100 gambit score, 2.7s)
- **Template Extraction Model** — For analyzing template structure on import (default: Mistral Magistral Small — best field/section detection)
- **Vision OCR Model** — For reading scanned pages and images (default: Mistral Ministral 3B — perfect accuracy, fastest at 0.49s)
- **Format Detection Model** — For detecting output format from prompts (default: Llama 3 8B — fastest at 194ms, perfect cleanliness)
- **Embedding Model** — For generating vector embeddings at index and search time (default: Amazon Titan Embed Text v2 — 1024 dimensions, ~$0.0001/chunk)

Models from 11+ families are supported: Anthropic, Amazon, NVIDIA, Mistral, DeepSeek, Meta, Google, AI21, Qwen, Z.AI, and OpenAI (GPT-OSS). Each model in Settings shows descriptive tags like `[$ cheapest · fast]` or `[$$ balanced · best for document generation]`.

## Tasks

Click the "🧠 Tasks" tab for the guided document generation workflow.

### How It Works

1. **Type your prompt** — describe what you need (e.g., "Fill out the description of proposed modification for the exterior modification form using American Home Contractors GAF LIBERTY SBS system")
2. **Prompt quality meter** — as you type, a live meter shows how well your prompt connects to indexed documents (uses embedding search to score in real time)
3. **Click "Find Documents"** — the app searches using hybrid BM25+kNN, extracts entity names, searches abbreviations, then refines results with Cohere Rerank and prompt decomposition
4. **Review documents** — see what was found with relevance snippets. Check/uncheck to curate your source set
5. **Generate** — produces content using only the selected documents (chunk-level retrieval for precision, no bloat)
6. **Refine** — type follow-up instructions to iterate on the output
7. **Export** — download as PDF, DOCX, Markdown, or ZIP package (includes source PDFs)

### Document Discovery Pipeline

The "Find Documents" step uses a multi-phase approach:

1. **Hybrid search** — BM25 keyword + kNN vector similarity on the full prompt
2. **Entity extraction** — detects capitalized names (e.g., "American Home Contractors") and searches specifically for those
3. **Abbreviation search** — generates initials (e.g., "AHC") and searches for correspondence
4. **Prompt decomposition** — a fast model (Nova Micro) extracts structured intent: vendor, product, subject, target document
5. **Cohere Rerank** — rescores all candidates using the content-subject (not the administrative action) as the query
6. **Score cutoff** — removes low-relevance noise (below 8% of top score)
7. **Auto-include forms** — if the prompt implies a form but none was found, application-type documents are added automatically

### Form Detection

When a document with type "application" or "form" is in the selected set, the system automatically:
- Switches to plain-paragraph output (no markdown headers, bullets, or tables)
- Requests all key facts: cost, materials, dimensions, timeline, contractor info, colors
- Post-processes with a topic-transition model to split into natural paragraphs

### Task Model

Default: NVIDIA Nemotron Super (selected via gambit testing — 100/100 quality, 2.7s, all facts correct)

### Task History

Previous tasks are saved automatically (localStorage) so you can return to them later:
- Click "📋 History" to see your past prompts and results
- Click any entry to reload it and continue refining
- Delete individual entries with "×" or clear all at once
- Set how many to keep in Settings (default: 5)

### Export Package

The "📦 Package (ZIP)" export produces a structured archive:

```
task_package_2026-06-08-15-26.zip
├── writeup.txt              (prompt + generated content + source citations)
└── sources/
    ├── 01_Document_Title/
    │   ├── original_file.pdf
    │   └── relevance.txt    (why this doc was pulled, matched chunks + scores)
    ├── 02_Another_Document/
    │   ├── original_file.txt
    │   └── relevance.txt
    └── ...
```

## Gap-to-Email

Click the "📧 Gap-to-Email" tab to analyze forms against vendor documents and generate follow-up emails.

### How It Works

![Gap-to-Email Pipeline](docs/diagrams/gap_to_email.png)

1. Select a **form document** (e.g., an HOA application) that defines what's required
2. Optionally add **context documents** (e.g., architectural standards, guidelines) for compliance checking
3. Add **vendors** — each with a name, contact info, and their relevant documents
4. Optionally paste an **example email** to match tone and structure
5. Click "Analyze Gaps & Generate Emails"
6. For each vendor, the system:
   - Reads the form requirements
   - Compares against what the vendor already provided in their documents
   - Identifies specific gaps (missing items)
   - Generates a tailored follow-up email requesting only what's missing

### Use Cases

- HOA applications: gather contractor documentation for architectural review board submissions
- Insurance claims: identify missing documentation from adjusters or repair vendors
- Closing paperwork: track which parties still owe documents for settlement
- Any workflow where a form requires inputs from multiple vendors

## Document Preview

Click the 📄 icon next to any document to open an in-browser preview:

- **PDF files** — rendered directly in an iframe
- **Images (PNG, JPEG)** — displayed inline
- **DOCX files** — rendered client-side via docx-preview (no server conversion needed)
- **PPTX files** — converted to PDF server-side via LibreOffice, then displayed

## Templates

Click the "📋 Templates" tab to manage document templates.

### Importing Templates

1. Click "+ Import Template" and select a DOCX or PDF file
2. The system extracts the template's structure: fonts, page layout, sections, fill-in fields
3. The template is stored with its original file bytes for later filling

### Filling Templates

1. Go to the "✏ Create" tab and select a template from the dropdown
2. Write a prompt describing what content you want (e.g., "Write a thesis about HOA governance")
3. Click "📄 Fill Template"
4. The system searches your indexed documents for relevant content, generates text for each section, and produces a filled DOCX that preserves the original formatting, fonts, images, and page layout

### How Template Fill Works

![Template Fill Pipeline](docs/diagrams/template_fill.png)

The fill engine uses a three-phase approach:

1. **Generate** — Section-by-section content generation via Bedrock (title, abstract, glossary, chapter, bibliography, index). Each section gets its own focused context from the search index.
2. **Apply** — Clones the original DOCX and replaces placeholder text (SDTs, MACROBUTTON fields, table cells) while preserving all XML formatting, run properties, and page structure.
3. **Post-process** — Removes artifacts, scales fonts for overflow, preserves page breaks.

### Template Diagnostic

The "🔬 Diagnostic" tab shows a three-panel view for debugging template fills:
- **Original Template** — extracted structure (sections, fonts, layout)
- **Fill Schema** — the analyzed fill map (every fillable slot cataloged)
- **Filled Result** — the generated output with download button

### Supported Template Types

| Template Type | Example | Fill Method |
|--------------|---------|-------------|
| Academic thesis | Title page, TOC, chapters, bibliography, index | Full SDT replacement |
| Business checklist | Checkbox tables with task descriptions | Table content fill |
| Statement of work | Contract tables with scope/deliverables | Table content fill |

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

## Kubernetes Services

![Kubernetes Services](docs/diagrams/kubernetes.png)

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
- `POST /generate/export-package` - Export writeup + source PDFs as a ZIP
- `POST /gap-to-email` - Analyze form requirements vs vendor docs, generate follow-up emails
- `POST /search/refine` - Refine search candidates via prompt decomposition + Cohere Rerank
- `GET /documents` - List all documents
- `GET /documents/{id}` - Get a single document
- `GET /documents/{id}/chunks` - Get a document's text chunks
- `GET /documents/{id}/file` - Download the original uploaded file
- `GET /documents/{id}/preview` - Preview document (PDF/image direct, DOCX/PPTX converted)
- `DELETE /documents/{id}` - Delete a document
- `DELETE /documents` - Delete all documents
- `POST /templates/extract` - Import a template (extract structure + store file)
- `GET /templates` - List all templates
- `GET /templates/{id}` - Get template structure
- `POST /templates/{id}/analyze` - Get fill schema (all fillable slots)
- `POST /templates/{id}/fill` - Fill template with AI-generated content
- `GET /templates/{id}/export` - Export template as JSON or XML
- `DELETE /templates/{id}` - Delete a template
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

## Diagrams

Architecture diagrams are maintained as PlantUML source files in `docs/diagrams/`. To regenerate the PNGs after editing a `.puml` file:

```bash
make diagrams
```

Requires Java (headless) and the PlantUML JAR at `~/.local/lib/plantuml.jar`. Install with:

```bash
sudo apt-get install -y default-jre-headless
wget -O ~/.local/lib/plantuml.jar \
  "https://github.com/plantuml/plantuml/releases/download/v1.2024.8/plantuml-1.2024.8.jar"
```

See [docs/PLANTUML_GUIDE.md](docs/PLANTUML_GUIDE.md) for the full methodology including CI integration and generating diagrams from repo context via Bedrock.
