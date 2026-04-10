Here’s a solid requirements draft for that stack.

Objective

Build a document search and retrieval system for house-related records so a user can type questions like:

“Show me the closing disclosure”
“Find HOA rules about sheds”
“What does the inspection say about the roof?”
“Which documents mention escrow shortages?”

The system should ingest and organize documents from Confluence and uploaded files, index them in OpenSearch, and use Amazon Bedrock for semantic search and answer generation. OpenSearch supports vector search plus traditional search/filtering, and Bedrock Knowledge Bases can work with supported vector stores including Amazon OpenSearch options.

Proposed stack

Frontend:

Vue 3
Vue Router
Composition API with <script setup>, which Vue recommends for Composition API SFC usage.

Backend:

Python API service
Document ingestion workers
Search orchestration service
LLM/RAG service

Search + retrieval:

Amazon OpenSearch Service or OpenSearch Serverless vector search
Hybrid retrieval: keyword + metadata filters + vector similarity
OpenSearch knn_vector / k-NN search for semantic retrieval.

Content source:

Confluence Cloud via REST API and CQL-backed search endpoints.

LLM layer:

Amazon Bedrock for embeddings + response generation
Optional Bedrock Knowledge Bases if you want managed chunking/embedding/retrieval instead of a fully custom RAG pipeline.
Core product requirements

1. Content intake

The system must support:

PDF upload
DOCX upload
Image-based house documents if OCR is later added
Confluence page sync
Confluence attachment sync
Manual metadata tagging

Each document should be classified into one or more categories:

Closing
Loan / mortgage
Escrow
Title
HOA / condo docs
Inspection
Appraisal
Insurance
Repair / contractor
Utility / property records
Personal notes 2. Search modes

The system must support:

Exact keyword search
Semantic search
Hybrid search
Filtered search by metadata
Natural language question answering over retrieved documents

Example queries:

“Find the termite inspection”
“What fees increased before closing?”
“Which docs mention flood risk?”
“Show only HOA documents from 2026” 3. Answering behavior

When the user asks a question, the system should:

Retrieve relevant chunks from OpenSearch
Send retrieved chunks to Bedrock
Return:
direct answer
cited source chunks
links to full documents / Confluence pages
confidence / relevance indicators

The answer should never appear without source citations.

4. Document access

The user must be able to:

Open the original Confluence page
Open the original uploaded file
Jump to matching sections/chunks
Preview extracted text and metadata
Download original files when authorized 5. Continuous sync

The system should support:

scheduled sync from Confluence
manual re-sync
incremental updates
deleted/archived content handling
version-aware reindexing
Functional requirements
Frontend requirements

The Vue frontend should provide:

Search page
single search bar
mode selector: keyword / semantic / hybrid / ask a question
filter drawer
results list with snippets
document type badges
source badge: Confluence or uploaded file
sort options: relevance, newest, document type
Result detail page
title
source link
metadata panel
matched chunks
extracted summary
“ask follow-up” box
Admin / power-user pages
ingestion status
sync history
failed docs
reindex controls
model configuration
access control mapping
chunk preview / index inspection
Backend requirements

The Python backend should expose APIs for:

Search
/search
/ask
/documents
/documents/{id}
/documents/{id}/chunks
/sources/confluence/sync
/admin/reindex
/admin/jobs
Ingestion
file upload endpoint
Confluence crawler/sync worker
text extraction pipeline
chunking pipeline
metadata enrichment pipeline
embedding generation pipeline
indexing pipeline
Authorization
user authentication
per-document authorization
source-level authorization
audit logging
Data pipeline requirements

1. Confluence connector

The system should use Confluence REST APIs to:

enumerate spaces/pages
retrieve page content
retrieve attachments
retrieve metadata
run content searches via CQL-backed endpoints where helpful.

Store for each item:

source_type
space_key
page_id
page_title
page_url
attachment_id
attachment_name
version
last_modified
author
permissions snapshot if available 2. Parsing and normalization

The system should:

extract text from PDF and DOCX
normalize whitespace
preserve headings when possible
identify sections
split into chunks
attach chunk metadata

Recommended chunk metadata:

document_id
chunk_id
section_heading
page_number if available
source_type
document_type
closing_stage
property_address
loan_number redacted if needed
created_at
updated_at
tags
acl 3. Embeddings

The system should create embeddings for each chunk using a Bedrock-supported embedding model. Bedrock Knowledge Bases documentation lists supported embedding models and regions, so final model choice should be pinned to the deployment region you pick.

4. Indexing

OpenSearch index should store:

raw chunk text
embedding vector
metadata fields
normalized title
boosted fields for exact search

Because OpenSearch supports vector search together with filters, aggregations, and traditional search, it fits a hybrid retrieval design well.

Recommended OpenSearch schema

Use two indexes at minimum:

house_documents

Document-level record:

document_id
title
source_type
source_url
document_type
property_address
created_at
updated_at
tags
acl
summary
status
house_document_chunks

Chunk-level record:

chunk_id
document_id
title
section_heading
content
content_vector
page_number
source_type
document_type
property_address
closing_stage
updated_at
tags
acl

Use chunk-level retrieval for accuracy, but display document-level grouping in the UI.

Retrieval requirements
Hybrid retrieval strategy

Search should combine:

BM25 / keyword retrieval
vector similarity retrieval
metadata filtering
reranking

OpenSearch supports filtered vector search, which is useful for cases like:

only escrow documents
only one property
only docs updated after a date
only user-authorized spaces/files
RAG answer generation

The /ask flow should:

classify user intent
run hybrid search
rerank top chunks
send top chunks to Bedrock
generate answer with citations
return answer + sources + suggested follow-up queries
Security requirements

This is important because closing docs contain sensitive financial data.

Must have:

SSO or Cognito-backed auth
role-based access control
per-document ACL propagation from source where feasible
encryption in transit
encryption at rest
audit logs for search, view, download, and admin actions
secret storage in AWS Secrets Manager or similar
PII redaction option for previews and LLM prompts
prompt-context limits so the LLM only sees retrieved authorized chunks

Nice to have:

field-level redaction
legal hold / retention settings
document watermarking in preview mode
Non-functional requirements

Performance targets:

keyword search under 2 seconds
semantic/hybrid search under 3 seconds
ask-a-question flow under 6 seconds for typical corpora
incremental sync latency under 15 minutes for changed Confluence pages

Scale targets:

thousands of documents initially
hundreds of thousands of chunks
multi-property support later

Reliability:

retry failed ingestion jobs
dead-letter queue for parse/index failures
idempotent sync jobs
versioned reindex support

Observability:

ingestion job metrics
index counts
chunking errors
Bedrock token/cost tracking
search latency dashboards
trace ID per request
Suggested AWS architecture
Vue frontend hosted on S3 + CloudFront
Python backend on ECS/Fargate or Lambda + API Gateway
SQS for ingestion jobs
OpenSearch Service / OpenSearch Serverless for search
Bedrock for embeddings + answer generation
DynamoDB or Postgres for job state and document registry
S3 for raw uploaded files and extracted artifacts
EventBridge for sync scheduling
CloudWatch for logs/metrics
Secrets Manager for Confluence/API credentials
API contract draft
POST /search

Input:

query
mode
filters
page
page_size

Output:

results[]
total
facets
timing_ms
POST /ask

Input:

question
filters
top_k

Output:

answer
citations[]
documents[]
suggested_queries[]
POST /ingest/upload

Input:

multipart file
metadata

Output:

document_id
job_id
POST /sources/confluence/sync

Input:

space_keys[]
full_sync
since

Output:

job_id
Bedrock integration options
Option A: fully custom RAG

Your Python backend handles:

chunking
embeddings
OpenSearch indexing
retrieval
prompt building

Best when you want full control.

Option B: Bedrock Knowledge Bases + OpenSearch-backed vector store

Bedrock handles more of:

chunking
embeddings
retrieval orchestration

This has become more attractive because Bedrock Knowledge Bases supports OpenSearch options, including managed cluster support announced in March 2025.

For your use case, I would start with Option A if you want strict control over document classes, metadata, ACL behavior, and custom UI. Use Option B if you want faster time-to-market and can live with more managed behavior.

MVP scope

Phase 1:

upload PDFs/DOCX
Confluence page ingest
text extraction
chunking
embeddings
OpenSearch hybrid search
Vue search UI
Bedrock Q&A with citations

Phase 2:

ACL-aware retrieval
Confluence attachment sync
incremental sync
answer feedback loop
reranking
admin dashboards
property-based tagging

Phase 3:

OCR
email ingestion
closing timeline assistant
auto-summarized document packets
proactive “missing document” detection
Acceptance criteria

The system is successful when a user can:

search by phrase and find exact house docs
ask a natural-language question and get a cited answer
filter to a specific property or document class
open the original source page/file from the result
trust that unauthorized documents are never surfaced
re-sync Confluence changes without full rebuild
Recommended folder structure
house-doc-search/
frontend/
src/
pages/
components/
composables/
services/
router/
backend/
app/
api/
services/
models/
repositories/
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
terraform_or_cdk/
docs/
requirements/
api/
My recommendation

Use this architecture:

Vue 3 frontend
Python FastAPI backend
OpenSearch for hybrid retrieval
Confluence as one source system
S3 for uploaded documents
Bedrock for embeddings + final answer generation
Custom RAG first, Bedrock Knowledge Bases only if you want to reduce custom ingestion logic later

That gives you the most control for closing-document workflows, where metadata, provenance, and permissions matter a lot.

I can turn this into a proper markdown requirements document with epics, user stories, API schemas, and an AWS deployment diagram.
