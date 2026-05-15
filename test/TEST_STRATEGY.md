# Comprehensive Test Suite

## Scope

Tests cover the full application: document ingestion, search, AI features, template system, document generation, and infrastructure. Tests are organized by layer and dependency.

## Test Fixtures

Template files in `test/`:
- `template_1.docx` — Academic thesis (10 pages, 124 SDTs, background image, bibliography table, index table)
- `template_1.pdf` — Same document rendered as PDF
- `template_2.docx` — Business Startup Checklist (3 pages, 49 checkboxes in tables)
- `template_2.pdf` — Same as PDF
- `template_3.docx` — Statement of Work (4 pages, 12 tables, mostly empty placeholders)
- `template_3.pdf` — Same as PDF

---

## Test Categories

### 1. Unit Tests (no external dependencies)

| Test File | Module Under Test | What it covers |
|-----------|-------------------|---------------|
| `test_template_extractor.py` | `template_extractor.py` | DOCX/PDF structure extraction, SDT detection, font/layout parsing, pattern detection |
| `test_template_fill_engine.py` | `template_fill_engine.py` | SDT replacement, MACROBUTTON removal, table filling, font scaling, structure preservation |
| `test_template_content_generator.py` | `template_content_generator.py` | Content formatting, HTML stripping, validation logic, split algorithms |
| `test_document_preview.py` | `main.py` (preview endpoint) | Preview routing, MIME types, caching |
| `test_generator.py` | `generator.py` | Markdown generation, DOCX/PDF/PNG/PPTX/TXT conversion |
| `test_pricing.py` | `pricing.py` | Pricing JSON parsing, cost estimation, model matching |
| `test_pg_store.py` | `pg_store.py` | Template CRUD, document CRUD, chunk storage (mocked DB) |
| `test_worker.py` | `worker.py` | Concurrency config, job processing logic |

### 2. Integration Tests (require Bedrock/AWS)

| Test File | What it covers |
|-----------|---------------|
| `test_model_capabilities.py` | Each configured model responds correctly per its assigned task |
| `test_template_fill_e2e.py` | Full pipeline: import → generate → apply → verify (all 3 templates) |
| `test_search_and_ask.py` | Search relevance, Ask AI accuracy with citations |
| `test_template_extraction_bedrock.py` | Bedrock-enhanced extraction vs local-only quality |

### 3. Functional Tests (require running cluster)

| Test File | What it covers |
|-----------|---------------|
| `test_api_endpoints.py` | All REST endpoints: status codes, response shapes, error handling |
| `test_template_workflow.py` | Full UI workflow: import → list → preview → fill → download → delete |
| `test_diagnostic_tab.py` | Diagnostic endpoint returns all 3 panels correctly |
| `test_upload_workflow.py` | Single/bulk/streaming upload, duplicate detection, cancellation |
| `test_bookstack_sync.py` | BookStack push on upload, sync endpoint |
| `test_admin_endpoints.py` | Config get/set, model listing, usage tracking, health check |

---

## Test Details

### 1.1 `test_template_extractor.py`

**Using template_1.docx:**
```
- test_extract_docx_finds_all_sdts: 124 placeholder SDTs detected
- test_extract_docx_detects_fonts: heading=Franklin Gothic Demi, body=Franklin Gothic Book
- test_extract_docx_detects_page_layout: size=8.5x11, margins T=0.75 B=0.44 L=1.5 R=1.5
- test_extract_docx_detects_fill_in_fields: fill_in_count > 0, type="form"
- test_extract_docx_detects_toc: formatting.has_table_of_contents = True
- test_extract_docx_bibliography_pattern: ". . , ." replaced with field description
- test_extract_docx_index_pattern: 3-column index with letter headers detected
- test_extract_docx_sections_count: ≥ 10 sections extracted
- test_extract_docx_title_derived: title contains "Universe" or meaningful text
```

**Using template_2.docx (Business Checklist):**
```
- test_extract_checklist_detects_checkboxes: ≥ 40 checkboxes found
- test_extract_checklist_type_is_form: type="form"
- test_extract_checklist_title: "BUSINESS STARTUP CHECKLIST"
- test_extract_checklist_tables: 7 tables detected
```

**Using template_3.docx (Statement of Work):**
```
- test_extract_sow_tables: 12 tables detected
- test_extract_sow_empty_cells: detects high percentage of empty cells (placeholder form)
```

**Using template_1.pdf:**
```
- test_extract_pdf_gets_fonts: FranklinGothic-Book/Demi from embedded fonts
- test_extract_pdf_no_bedrock_fallback: local extraction works without model configured
- test_extract_pdf_page_count: 10 pages detected
- test_extract_pdf_sections: headings include TABLE OF CONTENTS, GLOSSARY, etc.
```

### 1.2 `test_template_fill_engine.py`

```
- test_analyze_returns_slots: analyze(template_1.docx) returns > 100 slots
- test_analyze_detects_macrobuttons: macrobutton count > 0
- test_analyze_detects_bib_table: bib_table entry present
- test_apply_preserves_page_breaks: output has ≥ 7 page breaks (same as input)
- test_apply_preserves_title_table_rows: 14 rows maintained (empty spacers kept)
- test_apply_removes_macrobuttons: 0 MACROBUTTON instrText in output
- test_apply_fills_bibliography_table: no ". . , ." in output
- test_apply_fills_index_table: no "Aristotle" or "Geocentric" in output
- test_apply_clears_unused_sdts: SDTs 47-90 have empty text
- test_apply_static_text_replaced: no "Professor Janessa", no "Supervisory Committee"
- test_font_scaling_shrinks_long_text: text > original chars gets smaller w:sz value
- test_font_scaling_no_change_short_text: text ≤ original chars has no w:sz added
- test_sdt_multirun_replacement: 3-run SDT gets 3-element array correctly
- test_apply_preserves_images: output ZIP contains word/media/image1.png
```

### 1.3 `test_template_content_generator.py`

```
- test_title_split_short: "HOA" → ["HOA", "", ""]
- test_title_split_two_words: "HOA Governance" → ["HOA", "", "Governance"]
- test_title_split_long: "HOA Governance Analysis Report" → ["HOA Governance", "", "Analysis Report"]
- test_description_split_at_preposition: splits at " of " near char 70
- test_description_split_at_comma: splits at ", " if no preposition
- test_description_short_no_split: text < 70 chars returns [text, ""]
- test_institution_split: "Centerpointe Community" → ["Centerpointe", " ", "Community"]
- test_institution_single_word: "Centerpointe" → ["Centerpointe", " ", ""]
- test_html_stripping: "<em>text</em>" → "text"
- test_html_nested: "<b><i>text</i></b>" → "text"
- test_glossary_validation_minimum: returns ≥ 6 terms always
- test_chapter_validation_body_length: each section body ≥ 100 chars
- test_acknowledgments_3_parts: always returns part1, name, part3
- test_toc_deterministic_from_chapter: TOC entries match chapter headings
- test_bibliography_deduplicates: no duplicate entries
- test_index_deterministic: returns 32 entries
- test_content_to_fill_data_mapping: maps title_runs→title, author_runs→author, glossary list passes through
- test_content_to_fill_data_abstract_title_fallback: uses title_page title if abstract has no title
```

### 1.4 `test_document_preview.py`

```
- test_preview_pdf_serves_directly: returns application/pdf, no conversion
- test_preview_image_png: returns image/png for .png files
- test_preview_image_jpg: returns image/jpeg for .jpg files
- test_preview_docx_converts: returns application/pdf (converted)
- test_preview_pptx_converts: returns application/pdf (converted)
- test_preview_caches_conversion: .preview.pdf file created on first call
- test_preview_404_missing_doc: returns 404 for nonexistent document
- test_preview_404_missing_file: returns 404 if file deleted from disk
```

### 1.5 `test_generator.py`

```
- test_generate_markdown_returns_string: non-empty markdown from prompt
- test_convert_to_docx_valid_zip: output is valid ZIP with word/document.xml
- test_convert_to_pdf_valid: output starts with %PDF
- test_convert_to_png_valid: output is valid PNG (magic bytes)
- test_convert_to_pptx_valid_zip: output is valid ZIP with ppt/presentation.xml
- test_convert_to_txt_plain: output is plain text, no markup
```

### 1.6 `test_pricing.py`

```
- test_estimate_cost_known_model: returns non-zero cost for haiku
- test_estimate_cost_unknown_model: returns 0 or raises gracefully
- test_parse_pricing_json: parses AWS bulk pricing format
- test_fuzzy_match_model: matches "claude-3-haiku" variants
```

### 2.1 `test_model_capabilities.py`

Tests every available on-demand model per family on the 3 core tasks (JSON, content, Q&A).

**Models tested (all on-demand Converse API compatible):**

| Family | Models |
|--------|--------|
| Anthropic | claude-3-haiku, claude-3-sonnet |
| Amazon | nova-pro, nova-2-lite |
| NVIDIA | nemotron-super-3-120b, nemotron-nano-3-30b, nemotron-nano-12b, nemotron-nano-9b |
| Mistral | mistral-large-3-675b, ministral-3-14b, ministral-3-8b |
| DeepSeek | deepseek-v3.2, deepseek-r1 |
| Meta | llama3-8b (if on-demand available) |
| AI21 | jamba-1-5-large, jamba-1-5-mini |
| Cohere | command-r, command-r-plus |
| Google | gemma-3-27b, gemma-3-12b, gemma-3-4b |
| Qwen | qwen3-32b |
| MiniMax | minimax-m2.5 |
| Writer | palmyra-x5 |
| Z.AI | glm-5, glm-4.7 |
| Moonshot | kimi-k2.5 |

**Per model, 3 tests:**
```
- test_{family}_{model}_json: returns valid JSON with expected keys (pass/fail + time)
- test_{family}_{model}_content: produces 100-400 char paragraph about HOA (pass/fail + time)
- test_{family}_{model}_qa: answers "how long does ARB review take?" with "30 days" (pass/fail + time)
```

**Parametrized test structure:**
```python
@pytest.mark.parametrize("model_id", ALL_AVAILABLE_MODELS)
def test_json_generation(model_id):
    ...

@pytest.mark.parametrize("model_id", ALL_AVAILABLE_MODELS)
def test_content_generation(model_id):
    ...

@pytest.mark.parametrize("model_id", ALL_AVAILABLE_MODELS)
def test_qa_accuracy(model_id):
    ...
```

**Output:** Results table saved to `test/results/model_capabilities.json` with per-model scores.

### 2.2 `test_template_fill_e2e.py`

Tests the full fill pipeline with every generation-capable model.

**Models tested for template fill:**
```
- anthropic.claude-3-haiku-20240307-v1:0
- anthropic.claude-3-sonnet-20240229-v1:0
- amazon.nova-pro-v1:0
- nvidia.nemotron-super-3-120b
- nvidia.nemotron-nano-3-30b
- mistral.mistral-large-3-675b-instruct
- deepseek.v3.2
```

**Per model × per template:**
```
- test_fill_{model}_{template}_score: overall score ≥ threshold
- test_fill_{model}_{template}_artifacts: 17/17 cleared
- test_fill_{model}_{template}_content: 12/12 present
- test_fill_{model}_{template}_structure: page breaks, no macros, title rows
```

**Thresholds by model tier:**
```
- Sonnet/Nemotron-Super: ≥ 95%
- Haiku/Nova/Mistral/Nemotron-Nano: ≥ 90%
- DeepSeek: ≥ 85% (slower, may truncate)
```

**Templates tested:**
```
- template_1.docx (thesis, 10 pages, complex)
- template_2.docx (checklist, 3 pages, checkboxes)
- template_3.docx (SOW, 4 pages, tables)
```

**Output:** Filled documents saved to `test/results/filled/` for manual review.

### 2.3 `test_search_and_ask.py`

```
- test_search_hoa_returns_results: "HOA rules" returns > 0 results
- test_search_relevance_top_result: top result title contains HOA-related term
- test_search_pagination: page=2 returns different results than page=1
- test_search_facets: response includes document_type facets
- test_ask_returns_answer: non-empty answer string
- test_ask_has_citations: citations list is non-empty
- test_ask_answer_references_docs: answer contains terms from indexed documents
- test_ask_handles_no_results: graceful response for unrelated question
```

### 3.1 `test_api_endpoints.py`

```
- test_health: GET /health → 200
- test_root: GET / → 200
- test_documents_list: GET /documents → 200, array
- test_documents_get_404: GET /documents/fake → 404
- test_documents_chunks: GET /documents/{id}/chunks → 200, has chunks array
- test_documents_file_download: GET /documents/{id}/file → 200, binary content
- test_templates_list: GET /templates → 200, array
- test_template_import: POST /templates/extract + file → 200, has template_id
- test_template_get: GET /templates/{id} → 200, has structure
- test_template_analyze: POST /templates/{id}/analyze → 200, returns array (not dict)
- test_template_fill: POST /templates/{id}/fill + prompt → 200, docx bytes
- test_template_export_json: GET /templates/{id}/export?format=json → 200
- test_template_export_xml: GET /templates/{id}/export?format=xml → 200
- test_template_delete: DELETE /templates/{id} → 200
- test_search: POST /search + query → 200, has results array
- test_ask: POST /ask + question → 200, has answer
- test_generate: POST /generate + prompt → 200, has markdown
- test_generate_convert: POST /generate/convert + markdown + format → 200
- test_generate_detect_format: POST /generate/detect-format + prompt → 200, has format
- test_preview: GET /documents/{id}/preview → 200 or 404
- test_admin_config_get: GET /admin/config → 200, has all 5 model IDs
- test_admin_config_update: PUT /admin/config → 200, applied
- test_admin_models: GET /admin/models → 200, has qa array (non-empty)
- test_admin_health: GET /admin/health-check → 200
- test_admin_usage: GET /admin/usage → 200
- test_admin_pricing: GET /admin/pricing → 200
- test_admin_jobs: GET /admin/jobs → 200, array
- test_admin_reindex: POST /admin/reindex → 200
- test_admin_k8s_health: GET /admin/k8s-health → 200 or error
- test_admin_cancel_upload: POST /admin/cancel-upload → 200
- test_upload_single: POST /ingest/upload + file → 200, has document_id
- test_upload_bulk: POST /ingest/upload-bulk + files → 200, array of results
- test_upload_stream: POST /ingest/upload-stream + files → 200, SSE events
- test_upload_duplicate: POST same file twice → 400 (duplicate hash)
- test_upload_unsupported: POST .exe file → 400
- test_delete_document: DELETE /documents/{id} → 200
- test_delete_all: DELETE /documents → 200
- test_bookstack_sync: POST /sources/bookstack/sync → 200 or error
- test_confluence_sync: POST /sources/confluence/sync → 200 or error
```

### 3.2 `test_template_workflow.py`

```
- test_import_stores_file_bytes: after import, DB has file_bytes populated
- test_import_generates_fill_map: structure contains fill_map array
- test_import_names_from_filename: name derived from filename, not content
- test_fill_returns_valid_docx: response is valid ZIP with word/document.xml
- test_fill_preserves_images: output ZIP contains word/media/image1.png
- test_fill_preserves_page_breaks: output has ≥ 7 page breaks
- test_fill_timeout_handling: long generation doesn't crash server
- test_delete_removes_template: after delete, GET returns 404
- test_reimport_overwrites: importing same file creates new template_id
```

### 3.3 `test_upload_workflow.py`

```
- test_upload_single_pdf: POST /ingest/upload + .pdf → indexed, chunks created
- test_upload_single_docx: POST /ingest/upload + .docx → indexed, chunks created
- test_upload_single_txt: POST /ingest/upload + .txt → indexed
- test_upload_single_image: POST /ingest/upload + .png → processed via vision OCR
- test_upload_bulk_multiple: POST /ingest/upload-bulk + 3 files → all indexed, array response
- test_upload_stream_sse_events: POST /ingest/upload-stream → SSE events with progress
- test_upload_stream_cancel: POST /admin/cancel-upload during stream → stops remaining
- test_upload_duplicate_rejected: same content hash → 400 error with message
- test_upload_classifies_category: uploaded HOA doc gets "HOA Governance" category
- test_upload_classifies_type: uploaded doc gets document_type assigned
- test_upload_pushes_bookstack: document appears in BookStack (if configured)
- test_upload_creates_chunks: GET /documents/{id}/chunks returns non-empty array
- test_upload_indexes_opensearch: search finds the uploaded document
- test_upload_unsupported_type: .exe → 400 with supported types message
- test_upload_empty_file: 0-byte file → appropriate error
```

---

## Scoring Criteria for Template Fill Tests

### Current (Text Presence) — necessary but insufficient:
```python
ARTIFACTS = [...]  # 17 patterns that must NOT appear
EXPECTED = [...]   # 12 terms that MUST appear
STRUCTURE = [...]  # 3 structural checks
# Score: 32 points max
```

### NEW: Three-Dimensional Evaluation

#### Dimension 1: Content Quality (25 points)

| Check | Points | Method |
|-------|--------|--------|
| Title is meaningful (not generic/truncated) | 3 | len > 5, no trailing "and", no cut words |
| Author is "Patrick Flanigan" | 2 | Exact match |
| Abstract is substantive | 3 | len ≥ 150 chars, contains HOA-specific terms |
| Glossary has ≥ 6 distinct terms with definitions | 3 | Count term/def pairs, each def > 30 chars |
| Chapter has ≥ 3 sections with body paragraphs | 5 | Each section: heading + body ≥ 100 chars |
| Chapter references source documents | 3 | Contains terms from indexed docs (ARB, CC&R, etc.) |
| Bibliography has ≥ 5 unique entries | 3 | No duplicates, proper citation format |
| Index has ≥ 10 entries with page numbers | 3 | Format "Term, N" where N is a digit |

#### Dimension 2: Format Fidelity (25 points)

| Check | Points | Method |
|-------|--------|--------|
| Title table has 14 rows | 2 | Count `<w:tr>` in first table |
| Title runs match expected count (3/2/2/3) | 3 | SDTs 1-4 have correct run counts |
| Background image preserved | 2 | `word/media/image1.png` exists in ZIP |
| Image is anchored behind text | 2 | `<wp:anchor behindDoc="1">` present |
| Fonts not overridden (no unexpected `<w:sz>`) | 3 | Only scaled runs have explicit size |
| No HTML tags in any `<w:t>` | 2 | Scan all text elements |
| MACROBUTTON fields removed | 3 | 0 instrText with MACROBUTTON |
| Static text replaced | 2 | No "Professor Janessa", no "Supervisory Committee" |
| Bibliography table cells fully cleared | 3 | No `. . , .` or `[Last, First` in any cell |
| Page breaks preserved from original | 3 | Count matches original (9 breaks) |

#### Dimension 3: Locational Accuracy (25 points)

| Check | Points | Method |
|-------|--------|--------|
| Page 1 contains ONLY title table + image | 4 | No abstract/glossary text on page 1 |
| Page 1 title fits (no overflow to page 2) | 3 | Title row text ≤ 15 chars per run |
| Page 2 starts with institution + "Abstract" | 3 | First text on page 2 is institution name |
| TOC is on page 3 (not page 2) | 2 | "Table of Contents" text on page 3 |
| Glossary terms are on glossary page | 3 | All glossary terms on same page |
| Chapter content is on chapter page | 3 | Chapter heading + body on page 7 |
| Bibliography is on bibliography page | 2 | "Bibliography" heading + entries on page 8+ |
| Index is on index page | 2 | "Index" heading + entries on last content page |
| No empty pages (page with 0 content chars) | 3 | Every page has ≥ 10 chars of text |

#### Total: 75 points

**Pass thresholds:**
- Premium models (Sonnet, Nemotron-Super): ≥ 68/75 (90%)
- Balanced models (Haiku, Nova, Mistral): ≥ 60/75 (80%)
- Budget models (DeepSeek, Nano): ≥ 52/75 (70%)

### Scoring Implementation

```python
def score_filled_document(filled_bytes: bytes, original_bytes: bytes) -> dict:
    """Three-dimensional scoring of a filled template document."""
    # Returns:
    # {
    #   "content": {"score": N, "max": 25, "details": [...]},
    #   "format": {"score": N, "max": 25, "details": [...]},
    #   "location": {"score": N, "max": 25, "details": [...]},
    #   "total": N,
    #   "max": 75,
    #   "pct": float,
    # }
```

### What the old scoring missed (examples):

| Scenario | Old Score | New Score | Why |
|----------|-----------|-----------|-----|
| Title "Centerpointe Governance and" (truncated) | 100% | -3 content, -3 location | Cut word, may overflow |
| Abstract is 50 chars (too short) | 100% | -3 content | Not substantive |
| Chapter has heading but no body | 100% | -5 content | Empty section |
| Content bleeds from page 1 to page 2 | 100% | -4 location | Title overflow |
| Font size changed on all runs | 100% | -3 format | Unnecessary scaling |
| Empty page between sections | 100% | -3 location | Structural gap |

---

## Execution Order

1. Unit tests first (fast, no dependencies)
2. Integration tests (require AWS credentials)
3. Functional tests (require running cluster)

## Infrastructure Requirements

### `test/conftest.py` (REQUIRED)
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
```
This allows `from app.template_extractor import extract_template` etc.

### Environment Variables for Unit Tests
Unit tests that touch `template_extractor.py` MUST unset `BEDROCK_TEMPLATE_MODEL_ID` to prevent Bedrock calls:
```python
@pytest.fixture(autouse=True)
def no_bedrock(monkeypatch):
    monkeypatch.delenv("BEDROCK_TEMPLATE_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
```

### Mocking Strategy
- `test_template_content_generator.py` tests the **formatting/validation logic only** (title split, HTML strip, etc.) — NOT the Bedrock calls. The `_gen_*` functions that call Bedrock are tested in integration tests.
- `test_template_fill_engine.py` tests `apply_full()` which is pure XML manipulation — no mocking needed.
- `test_template_extractor.py` tests local extraction (Bedrock disabled via env var).

### Relationship to Existing Tests
The new `test/` directory contains **new functionality tests** (templates, preview, generator, pricing). It does NOT duplicate `backend/tests/` which covers core functionality (classifier, extraction, schemas, services, API basics, BookStack, Confluence). The functional `test_api_endpoints.py` extends coverage to NEW endpoints not in `backend/tests/test_api.py`.

## Scalable Generation Architecture

The content generator must never send more than **~2000 tokens of prompt + context** per Bedrock call. Large documents are divided into independent generation units that can be processed sequentially or in parallel.

### Generation Units (each is one Bedrock call)

| Unit | Input Size | Output Size | Dependencies |
|------|-----------|-------------|--------------|
| Title page | ~500 chars prompt | ~200 chars JSON | None |
| Abstract | ~800 chars (prompt + context excerpt) | ~300 chars | Title (for consistency) |
| Acknowledgments | ~200 chars prompt | ~400 chars | None |
| Glossary (batch 1: terms 1-4) | ~600 chars (prompt + context) | ~500 chars | None |
| Glossary (batch 2: terms 5-8) | ~600 chars | ~500 chars | None |
| Chapter section 1 | ~1500 chars (prompt + relevant context) | ~400 chars | None |
| Chapter section 2 | ~1500 chars (prompt + different context) | ~400 chars | None |
| Chapter section 3 | ~1500 chars (prompt + different context) | ~400 chars | None |
| TOC | Deterministic | N/A | Chapter headings |
| Figures | Deterministic | N/A | None |
| Bibliography | Deterministic (from doc titles) | N/A | None |
| Index | Deterministic (from content) | N/A | All content |

### Scaling Rules

1. **Context windowing**: Each generation call gets ONLY the search chunks relevant to its section, not the full 5000-char context blob.
   ```python
   # Instead of:
   context = all_chunks[:5000]
   
   # Do:
   section_context = search(section_specific_query, top_k=3)
   ```

2. **Glossary batching**: If > 8 terms needed, split into batches of 4. Each batch is a separate call.
   ```python
   for batch in chunk_list(terms_to_generate, batch_size=4):
       result = ask(glossary_prompt_for_batch(batch))
   ```

3. **Chapter sectioning**: Each subheading + body is a separate call with its own focused context.
   ```python
   for section in chapter_outline:
       section_context = search(section["heading"], top_k=3)
       section["body"] = ask(body_prompt(section["heading"], section_context))
   ```

4. **Token budget per call**: 
   - Prompt template: ~200 tokens
   - Context: ~500 tokens (3 chunks × ~170 tokens each)
   - Output: ~300 tokens
   - **Total per call: ~1000 tokens** (well within any model's limit)

5. **Parallelization**: Independent units (glossary batches, chapter sections) can run concurrently:
   ```python
   import asyncio
   results = await asyncio.gather(
       gen_section_1(context_1),
       gen_section_2(context_2),
       gen_section_3(context_3),
   )
   ```

6. **Large templates (20+ pages)**: Break into page groups. Each group generates independently, then assembles:
   ```
   Group 1: Title + Abstract (pages 1-2)
   Group 2: Front matter (TOC, Figures, Acknowledgments)
   Group 3: Chapter 1 (sections 1-3)
   Group 4: Chapter 2 (sections 4-6)  [if template has multiple chapters]
   Group 5: Back matter (Bibliography, Index, Appendices)
   ```

### Test Coverage for Scalability

```
# In test_template_content_generator.py:
- test_context_per_section_under_2000_chars: each call's prompt+context < 2000 chars
- test_glossary_batching_4_terms_per_call: 8 terms = 2 calls, not 1
- test_chapter_sections_independent: each section generated with own context
- test_large_template_page_groups: 20-page template splits into ≤ 5 generation groups
- test_no_single_call_exceeds_4096_output: output request never exceeds model limit

# In test_template_fill_e2e.py:
- test_fill_scales_to_20_pages: synthetic large template fills without timeout
- test_fill_parallel_sections: concurrent generation doesn't corrupt output
```

## Edge Case Tests (added to relevant files)

```
# In test_template_fill_engine.py:
- test_fill_empty_prompt_returns_400
- test_fill_no_file_bytes_returns_400
- test_fill_pdf_template_returns_400

# In test_template_extractor.py:
- test_extract_corrupt_docx_graceful_error
- test_extract_empty_file_graceful_error

# In test_api_endpoints.py:
- test_search_empty_query
- test_ask_empty_question
- test_preview_deleted_file_404
- test_upload_oversized_file

# In test_template_workflow.py:
- test_concurrent_fills_no_race_condition
```

## Dependencies

- `pytest` (already installed)
- Template files in `test/` directory (committed)
- Running k3s cluster with indexed HOA documents (functional tests)
- AWS credentials with Bedrock access (integration tests)


## Test Results Output

All test results are written to `test/results/` with the following structure:

```
test/results/
├── unit/
│   ├── template_extractor.json        # Per-template extraction results
│   ├── template_fill_engine.json      # Apply function verification
│   ├── content_generator.json         # Formatting/validation logic results
│   ├── document_preview.json          # Preview routing results
│   ├── generator.json                 # Format conversion results
│   └── pricing.json                   # Cost estimation results
│
├── integration/
│   ├── model_capabilities.json        # Per-model × per-task scores
│   ├── model_capabilities_summary.md  # Human-readable comparison table
│   ├── template_fill_e2e.json         # Per-model × per-template scores (75-pt system)
│   ├── template_fill_e2e_summary.md   # Human-readable fill comparison
│   ├── search_and_ask.json            # Search relevance + Ask accuracy
│   └── template_extraction_bedrock.json
│
├── functional/
│   ├── api_endpoints.json             # Per-endpoint status/timing
│   ├── template_workflow.json         # Workflow step results
│   ├── upload_workflow.json           # Upload pipeline results
│   └── admin_endpoints.json           # Admin API results
│
├── filled/                            # Actual filled documents for manual review
│   ├── template_1_haiku3.docx
│   ├── template_1_sonnet3.docx
│   ├── template_1_nova_pro.docx
│   ├── template_1_nemotron_super.docx
│   ├── template_1_mistral_large.docx
│   ├── template_1_deepseek_v3.docx
│   ├── template_2_sonnet3.docx
│   ├── template_2_nova_pro.docx
│   ├── template_3_sonnet3.docx
│   ├── template_3_nova_pro.docx
│   └── ...
│
├── scores/                            # 3-dimensional scoring breakdowns
│   ├── template_1_haiku3_score.json
│   ├── template_1_sonnet3_score.json
│   ├── template_1_nova_pro_score.json
│   └── ...
│
└── summary.md                         # Overall test run summary
```

### Result File Formats

#### `model_capabilities.json`
```json
{
  "run_date": "2026-05-15T07:00:00Z",
  "models_tested": 30,
  "results": [
    {
      "model_id": "amazon.nova-pro-v1:0",
      "family": "Amazon",
      "json_valid": true,
      "json_time_s": 0.4,
      "content_quality": true,
      "content_time_s": 0.7,
      "content_length": 330,
      "qa_correct": true,
      "qa_time_s": 0.4,
      "total_time_s": 1.5,
      "overall_pass": true,
      "error": null
    }
  ]
}
```

#### `template_fill_e2e.json`
```json
{
  "run_date": "2026-05-15T07:00:00Z",
  "results": [
    {
      "model_id": "anthropic.claude-3-sonnet-20240229-v1:0",
      "template": "template_1.docx",
      "generation_time_s": 33.1,
      "apply_time_s": 0.2,
      "scores": {
        "content": {"score": 23, "max": 25, "details": ["..."]},
        "format": {"score": 24, "max": 25, "details": ["..."]},
        "location": {"score": 22, "max": 25, "details": ["..."]},
        "total": 69,
        "max": 75,
        "pct": 92.0
      },
      "output_file": "filled/template_1_sonnet3.docx",
      "pass": true,
      "threshold": 90
    }
  ]
}
```

#### `scores/template_1_sonnet3_score.json`
```json
{
  "model": "anthropic.claude-3-sonnet-20240229-v1:0",
  "template": "template_1.docx",
  "content": {
    "score": 23,
    "max": 25,
    "checks": [
      {"name": "title_meaningful", "points": 3, "earned": 3, "detail": "HOA Governance (14 chars)"},
      {"name": "author_correct", "points": 2, "earned": 2, "detail": "Patrick Flanigan"},
      {"name": "abstract_substantive", "points": 3, "earned": 3, "detail": "589 chars"},
      {"name": "glossary_terms", "points": 3, "earned": 3, "detail": "8 terms"},
      {"name": "chapter_sections", "points": 5, "earned": 4, "detail": "3 sections, 1 short"},
      {"name": "chapter_grounded", "points": 3, "earned": 3, "detail": "references ARB, CC&Rs"},
      {"name": "bibliography_entries", "points": 3, "earned": 3, "detail": "12 unique"},
      {"name": "index_entries", "points": 3, "earned": 2, "detail": "32 entries, 5 missing page"}
    ]
  },
  "format": {
    "score": 24,
    "max": 25,
    "checks": [
      {"name": "title_table_rows", "points": 2, "earned": 2},
      {"name": "title_run_counts", "points": 3, "earned": 3},
      {"name": "image_present", "points": 2, "earned": 2},
      {"name": "image_anchored", "points": 2, "earned": 2},
      {"name": "fonts_preserved", "points": 3, "earned": 2, "detail": "2 unexpected w:sz"},
      {"name": "no_html", "points": 2, "earned": 2},
      {"name": "macrobuttons_removed", "points": 3, "earned": 3},
      {"name": "static_replaced", "points": 2, "earned": 2},
      {"name": "bib_cells_clean", "points": 3, "earned": 3},
      {"name": "page_breaks", "points": 3, "earned": 3}
    ]
  },
  "location": {
    "score": 22,
    "max": 25,
    "checks": [
      {"name": "page1_title_only", "points": 4, "earned": 4},
      {"name": "page1_no_overflow", "points": 3, "earned": 3},
      {"name": "page2_starts_abstract", "points": 3, "earned": 3},
      {"name": "toc_on_page3", "points": 2, "earned": 2},
      {"name": "glossary_same_page", "points": 3, "earned": 3},
      {"name": "chapter_on_page", "points": 3, "earned": 2, "detail": "body split to next page"},
      {"name": "bibliography_page", "points": 2, "earned": 2},
      {"name": "index_page", "points": 2, "earned": 2},
      {"name": "no_empty_pages", "points": 3, "earned": 1, "detail": "page 10 only 10 chars"}
    ]
  }
}
```

#### `summary.md` (auto-generated after full run)
```markdown
# Test Run Summary — 2026-05-15

## Unit Tests: 48/48 passed (100%)
## Integration Tests: 42/45 passed (93%)
## Functional Tests: 38/38 passed (100%)

## Model Comparison (Template Fill — 75-point scale)

| Model | T1 Content | T1 Format | T1 Location | T1 Total | Time |
|-------|-----------|-----------|-------------|----------|------|
| Sonnet 3 | 23/25 | 24/25 | 22/25 | 69/75 (92%) | 33s |
| Nova Pro | 21/25 | 23/25 | 20/25 | 64/75 (85%) | 12s |
| Haiku 3 | 20/25 | 23/25 | 19/25 | 62/75 (83%) | 11s |

## Recommendations
- Best quality: Sonnet 3 (92% avg)
- Best value: Nova Pro (85% avg, 3x faster)
- Fastest: Haiku 3 (83% avg, cheapest)
```

### Results Directory Creation

Tests auto-create the results directory structure on first run:
```python
@pytest.fixture(scope="session", autouse=True)
def results_dirs():
    for d in ["results/unit", "results/integration", "results/functional", 
              "results/filled", "results/scores"]:
        Path(d).mkdir(parents=True, exist_ok=True)
```


## Extraction Ground Truth Baselines

Each template has a **researched ground truth** — the definitive list of what the extraction MUST capture. Tests compare extraction output against this baseline. The baseline is established by manual inspection of the raw DOCX XML and PDF rendering.

### Template 1: Academic Thesis (`template_1.docx`)

| Property | Ground Truth Value | Source |
|----------|-------------------|--------|
| **Heading font** | Franklin Gothic Demi | `word/theme/theme11.xml` → `<a:majorFont><a:latin typeface="...">` |
| **Body font** | Franklin Gothic Book | `word/theme/theme11.xml` → `<a:minorFont><a:latin typeface="...">` |
| **Default size** | 12pt (24 half-points) | `word/styles2.xml` → `<w:docDefaults><w:sz w:val="24">` |
| **Page size** | 8.5 × 11.0 in | `<w:pgSz w:w="12240" w:h="15840">` (twips ÷ 1440) |
| **Margins** | T=0.75, B=0.44, L=1.50, R=1.50 in | `<w:pgMar>` values ÷ 1440 |
| **Placeholder SDTs** | 124 | Count of `<w:sdt>` with `<w:showingPlcHdr/>` |
| **MACROBUTTON fields** | 136 | Count of `<w:instrText>` containing "MACROBUTTON" |
| **Tables** | 3 (title=14×2, bibliography=17×3, index=12×5) | `<w:tbl>` count and row/col counts |
| **Background image** | 1 (2.10×11.00 in, behind text) | `<wp:anchor behindDoc="1">` with extent |
| **Type** | form (all SDTs are placeholders) | `<w:showingPlcHdr/>` on all 124 SDTs |
| **Fill-in count** | ≥ 40 (SDT placeholders + blank table cells) | SDTs + empty `<w:tc>` in tables |
| **Has TOC** | Yes | SDT with style "TOC1" present |
| **Sections (headings)** | Table of Contents, List of figures, Acknowledgments, Glossary, The Solar System, To Customize This Thesis, To Create a Document from the Template, How to Insert a Picture or Caption, Bibliography, Index | SDTs with heading styles |
| **Page count** | 10 | 9 page break paragraphs + 1 |

### Template 2: Business Startup Checklist (`template_2.docx`)

| Property | Ground Truth Value | Source |
|----------|-------------------|--------|
| **Title** | BUSINESS STARTUP CHECKLIST | First non-empty paragraph text |
| **Type** | form (checkboxes) | Checkbox characters in table cells |
| **Checkbox count** | 49 | Count of "☐" in `<w:t>` elements |
| **Tables** | 7 | `<w:tbl>` count |
| **Table structure** | 2 columns each (☐ + description) | First col = checkbox, second = text |
| **Sections** | 7 numbered sections (Assessing, Committing, Setting Up, Ensuring Funds, Planning, Marketing, Launching) | Table groupings with header rows |
| **Page count** | 3 | PDF page count |
| **Fonts** | Default (Calibri or theme) | No explicit theme override |
| **Fill-in pattern** | Checkboxes are actionable items | Each row = one task to complete |

### Template 3: Statement of Work (`template_3.docx`)

| Property | Ground Truth Value | Source |
|----------|-------------------|--------|
| **Title** | Statement of Work | PDF page 1 header text |
| **Type** | document (mostly empty placeholders) | 97% empty table cells |
| **Tables** | 12 | `<w:tbl>` count |
| **Empty cell percentage** | 97% (75 of 77 cells empty) | Count empty `<w:tc>` |
| **Paragraphs with content** | 3 | Non-empty `<w:p>` outside tables |
| **Page count** | 4 | PDF page count |
| **Key fields** | Date, Services Performed By, Services Performed For, Scope of Work, Deliverables, Period of Performance, Bill To Address | PDF text extraction |
| **Fill-in pattern** | Empty cells = user fills with project details | Table cells are form fields |

### Template 1 PDF: (`template_1.pdf`)

| Property | Ground Truth Value | Source |
|----------|-------------------|--------|
| **Embedded fonts** | FranklinGothic-Book, FranklinGothic-Demi, ArialMT | `/Resources/Font` in page 1 |
| **Page count** | 10 | `len(reader.pages)` |
| **Has bibliography text** | Yes — "[Last, First Name of Author]. [Title]. [Publisher], [year]." on page 8 | `reader.pages[7].extract_text()` |
| **Has index** | Yes — alphabetical 3-column layout on page 9 | `reader.pages[8].extract_text()` |
| **Sections detected** | ≥ 7 headings (TABLE OF CONTENTS, LIST OF FIGURES, ACKNOWLEDGMENTS, GLOSSARY, THE SOLAR SYSTEM, Bibliography, Index) | Uppercase/title-case lines |

### Extraction Scoring (per template)

```python
def score_extraction(result: dict, ground_truth: dict) -> dict:
    """Score extraction against ground truth baseline."""
    checks = []
    
    # Font detection
    if ground_truth.get("heading_font"):
        checks.append({
            "name": "heading_font",
            "expected": ground_truth["heading_font"],
            "actual": result.get("fonts", {}).get("heading_font"),
            "pass": ground_truth["heading_font"] in str(result.get("fonts", {}).get("heading_font", "")),
        })
    
    # Page layout
    if ground_truth.get("page_size"):
        checks.append({
            "name": "page_size",
            "expected": ground_truth["page_size"],
            "actual": result.get("page_layout", {}).get("size"),
            "pass": ground_truth["page_size"] in str(result.get("page_layout", {}).get("size", "")),
        })
    
    # Type detection
    checks.append({
        "name": "type",
        "expected": ground_truth["type"],
        "actual": result.get("type"),
        "pass": result.get("type") == ground_truth["type"],
    })
    
    # Section count
    expected_sections = ground_truth.get("min_sections", 5)
    actual_sections = len(result.get("sections", []))
    checks.append({
        "name": "sections",
        "expected": f"≥ {expected_sections}",
        "actual": actual_sections,
        "pass": actual_sections >= expected_sections,
    })
    
    # Fill-in detection
    if ground_truth.get("has_fill_ins"):
        fill_count = result.get("fill_in_count", 0)
        checks.append({
            "name": "fill_in_detection",
            "expected": "> 0",
            "actual": fill_count,
            "pass": fill_count > 0,
        })
    
    passed = sum(1 for c in checks if c["pass"])
    return {
        "template": ground_truth["name"],
        "passed": passed,
        "total": len(checks),
        "pct": passed / len(checks) * 100 if checks else 0,
        "checks": checks,
    }
```

### Ground Truth Test File: `test_extraction_ground_truth.py`

```python
GROUND_TRUTHS = {
    "template_1.docx": {
        "name": "template_1.docx",
        "heading_font": "Franklin Gothic Demi",
        "body_font": "Franklin Gothic Book",
        "default_size_pt": 12.0,
        "page_size": "8.5x11",
        "margins": {"top": 0.75, "bottom": 0.44, "left": 1.5, "right": 1.5},
        "type": "form",
        "sdt_count": 124,
        "macrobutton_count": 136,
        "table_count": 3,
        "has_fill_ins": True,
        "has_toc": True,
        "min_sections": 10,
        "has_image": True,
    },
    "template_2.docx": {
        "name": "template_2.docx",
        "type": "form",
        "checkbox_count_min": 40,
        "table_count": 7,
        "title": "BUSINESS STARTUP CHECKLIST",
        "min_sections": 1,
        "has_fill_ins": True,
    },
    "template_3.docx": {
        "name": "template_3.docx",
        "type": "document",
        "table_count": 12,
        "empty_cell_pct_min": 90,
        "min_sections": 1,
        "has_fill_ins": False,
    },
    "template_1.pdf": {
        "name": "template_1.pdf",
        "page_count": 10,
        "has_fonts": True,
        "font_contains": "FranklinGothic",
        "min_sections": 7,
        "type": "document",
        "has_fill_ins": False,
    },
    "template_2.pdf": {
        "name": "template_2.pdf",
        "page_count": 3,
        "has_fonts": True,
        "fonts": ["Calibri", "Calibri-Bold", "MS-Gothic"],
        "font_contains": "Calibri",
        "type": "form",
        "checkbox_count": 49,
        "has_fill_ins": True,
        "min_sections": 7,
        "section_headings": [
            "BUSINESS STARTUP CHECKLIST",
            "1. ASSESSING YOUR OPPORTUNITY (WHAT DO YOU WANT?)",
            "2. COMMITING TO YOUR BUSINESS",
            "3. SETTING UP YOUR BUSINESS",
            "4. ENSURING SUFFICIENT FUNDS ARE AVAILABLE",
            "5. PLANNING FOR YOUR BUSINESS",
            "6. SETTING UP TO OPERATE",
            "7. MARKETING AND LAUNCHING YOUR BUSINESS",
        ],
        "title": "BUSINESS STARTUP CHECKLIST",
    },
    "template_3.pdf": {
        "name": "template_3.pdf",
        "page_count": 4,
        "has_fonts": True,
        "fonts": ["Garamond", "Garamond-Italic", "CenturyGothic-Bold", "CenturyGothic", "TimesNewRomanPSMT"],
        "font_contains": "Garamond",
        "type": "document",
        "has_fill_ins": False,
        "min_sections": 3,
        "title_contains": "Statement of Work",
        "key_fields": ["DATE", "SERVICES PERFORMED BY", "SERVICES PERFORMED FOR",
                       "ITEM DESCRIPTION", "NUMBER OF RESOURCES", "HOURLY RATE",
                       "BILL TO ADDRESS", "CLIENT PROJECT MANAGER"],
    },
}
```

Results written to `test/results/integration/extraction_ground_truth.json`.


## Test Prompts

### Template 1 (Academic Thesis) — HOA-Specific Prompts

These use the indexed HOA documents as source material:

```python
TEMPLATE_1_HOA_PROMPTS = [
    # Primary test prompt (used throughout development)
    "Write a thesis about homeowner association governance covering HOA rules, architectural guidelines, exterior modifications, CC&Rs, compliance enforcement, and community management based on my house documents",
    
    # Focused on architectural standards
    "Write a thesis analyzing the architectural review process at Centerpointe Community, covering the ARB's role, modification application procedures, approved materials, and design standards",
    
    # Focused on compliance/enforcement
    "Write a thesis examining HOA compliance enforcement mechanisms including violation notices, fine schedules, hearing procedures, and homeowner appeal rights at Centerpointe",
    
    # Focused on financial governance
    "Write a thesis about HOA financial governance covering assessments, reserve studies, budgets, special assessments, and audited financial statements for Centerpointe Community",
    
    # Focused on community management
    "Write a thesis about community association management covering board meetings, annual registrations, new owner onboarding, and governance structure at Centerpointe",
]
```

### Template 1 (Academic Thesis) — Theme-Appropriate Prompts (Non-HOA)

These test the template with content unrelated to the indexed docs (tests generation without source grounding):

```python
TEMPLATE_1_GENERAL_PROMPTS = [
    # Technology
    "Write a thesis about the impact of artificial intelligence on software development practices, covering code generation, testing automation, and developer productivity",
    
    # Environmental
    "Write a thesis about sustainable urban planning covering green infrastructure, renewable energy integration, and community resilience to climate change",
    
    # Education
    "Write a thesis about remote learning effectiveness in higher education, covering student engagement, assessment methods, and technology accessibility",
    
    # Healthcare
    "Write a thesis about telemedicine adoption in rural communities, covering access barriers, patient outcomes, and regulatory frameworks",
    
    # Business
    "Write a thesis about small business resilience during economic disruption, covering financial planning, digital transformation, and supply chain adaptation",
]
```

### Template 2 (Business Startup Checklist) — HOA-Specific Prompts

```python
TEMPLATE_2_HOA_PROMPTS = [
    # HOA startup/formation
    "Create a checklist for establishing a new homeowner association covering incorporation, CC&R drafting, board formation, and initial assessments",
    
    # Modification application process
    "Create a checklist for submitting an exterior modification application covering documentation requirements, ARB review steps, and approval conditions",
    
    # New homeowner onboarding
    "Create a checklist for new homeowners joining Centerpointe Community covering registration, document review, fee setup, and community orientation",
]
```

### Template 2 (Business Startup Checklist) — Theme-Appropriate Prompts

```python
TEMPLATE_2_GENERAL_PROMPTS = [
    # Actual business startup
    "Create a business startup checklist for launching a mobile app company covering market research, funding, development, and go-to-market strategy",
    
    # Event planning
    "Create a checklist for organizing a community fundraising event covering venue, permits, marketing, volunteers, and day-of logistics",
    
    # Home renovation
    "Create a checklist for a kitchen renovation project covering design, permits, contractor selection, materials, and inspection milestones",
    
    # Career transition
    "Create a checklist for transitioning to a new career covering skills assessment, education, networking, resume updates, and interview preparation",
]
```

### Template 3 (Statement of Work) — HOA-Specific Prompts

```python
TEMPLATE_3_HOA_PROMPTS = [
    # Landscaping contract
    "Write a statement of work for a landscaping maintenance contract with Centerpointe Community HOA covering scope, schedule, deliverables, and payment terms",
    
    # Roof replacement
    "Write a statement of work for a community roof replacement project covering inspection, materials, timeline, warranty, and homeowner coordination",
    
    # HOA management company
    "Write a statement of work for an HOA management company engagement covering financial management, maintenance coordination, compliance enforcement, and reporting",
]
```

### Template 3 (Statement of Work) — Theme-Appropriate Prompts

```python
TEMPLATE_3_GENERAL_PROMPTS = [
    # Software development
    "Write a statement of work for a custom web application development project covering requirements, milestones, deliverables, acceptance criteria, and payment schedule",
    
    # Consulting engagement
    "Write a statement of work for a business process improvement consulting engagement covering assessment, recommendations, implementation support, and success metrics",
    
    # Construction
    "Write a statement of work for a commercial office buildout covering demolition, electrical, HVAC, finishing, and inspection phases",
]
```

### Prompt Selection for Tests

```python
# E2E fill tests use one prompt per category:
TEST_PROMPTS = {
    "template_1_hoa": TEMPLATE_1_HOA_PROMPTS[0],      # Primary HOA thesis
    "template_1_general": TEMPLATE_1_GENERAL_PROMPTS[0],  # AI thesis (no source docs)
    "template_2_hoa": TEMPLATE_2_HOA_PROMPTS[0],      # HOA formation checklist
    "template_2_general": TEMPLATE_2_GENERAL_PROMPTS[0],  # App startup checklist
    "template_3_hoa": TEMPLATE_3_HOA_PROMPTS[0],      # Landscaping SOW
    "template_3_general": TEMPLATE_3_GENERAL_PROMPTS[0],  # Web app SOW
}

# Model comparison tests use only the primary HOA prompt per template
# (consistent baseline for fair comparison)

# Stress tests cycle through ALL prompts to verify robustness
```

### What Each Prompt Category Tests

| Category | Tests |
|----------|-------|
| HOA-specific | Content grounding in source docs, citation accuracy, domain terminology |
| General (theme-matched) | Template structure works for any topic, not just HOA |
| Focused (narrow topic) | Model handles specific vs broad prompts |
| No-source (general) | Graceful handling when search returns no relevant chunks |


### Template Theme Stress Tests (Non-HOA, Diverse Domains)

These test whether the template fill engine adapts the template's structure to completely unrelated topics while maintaining format integrity.

#### Template 1 (Academic Thesis) — Diverse Thesis Topics

```python
TEMPLATE_1_THEME_TESTS = [
    # Sciences
    ("biology", "Write a thesis about CRISPR gene editing applications in agriculture covering crop resistance, yield improvement, and regulatory challenges"),
    ("physics", "Write a thesis about quantum computing error correction covering qubit decoherence, surface codes, and fault-tolerant architectures"),
    ("chemistry", "Write a thesis about biodegradable polymer development covering synthesis methods, degradation rates, and environmental impact"),
    
    # Humanities
    ("history", "Write a thesis about the economic impact of the Silk Road on medieval European trade covering spice routes, banking systems, and cultural exchange"),
    ("philosophy", "Write a thesis about the ethics of autonomous weapons systems covering just war theory, accountability gaps, and international law"),
    ("literature", "Write a thesis about unreliable narration in postmodern fiction covering Nabokov, Ishiguro, and narrative trust"),
    
    # Social Sciences
    ("economics", "Write a thesis about cryptocurrency regulation frameworks covering decentralized finance, consumer protection, and monetary policy implications"),
    ("psychology", "Write a thesis about cognitive load theory in UX design covering working memory limits, information architecture, and user testing methods"),
    ("sociology", "Write a thesis about remote work's impact on urban migration patterns covering housing markets, community formation, and infrastructure demand"),
    
    # Applied/Professional
    ("engineering", "Write a thesis about bridge structural health monitoring using IoT sensors covering vibration analysis, corrosion detection, and predictive maintenance"),
    ("medicine", "Write a thesis about antibiotic resistance mechanisms in hospital-acquired infections covering biofilm formation, horizontal gene transfer, and stewardship programs"),
    ("law", "Write a thesis about data privacy legislation harmonization covering GDPR, CCPA, and cross-border data transfer frameworks"),
]
```

#### Template 2 (Business Startup Checklist) — Diverse Checklist Topics

```python
TEMPLATE_2_THEME_TESTS = [
    # Personal life events
    ("wedding", "Create a checklist for planning a destination wedding covering venue selection, travel logistics, vendor coordination, and guest management"),
    ("relocation", "Create a checklist for relocating to a new country covering visa applications, housing search, banking setup, and cultural integration"),
    ("retirement", "Create a checklist for retirement preparation covering financial planning, healthcare transitions, estate planning, and lifestyle adjustments"),
    
    # Professional projects
    ("product_launch", "Create a checklist for launching a SaaS product covering beta testing, pricing strategy, marketing campaigns, and customer support setup"),
    ("audit", "Create a checklist for preparing for a financial audit covering document gathering, internal controls review, staff preparation, and timeline management"),
    ("certification", "Create a checklist for achieving ISO 27001 certification covering gap analysis, policy development, risk assessment, and surveillance audits"),
    
    # Technical operations
    ("deployment", "Create a checklist for deploying a production Kubernetes cluster covering node provisioning, networking, security policies, and monitoring setup"),
    ("disaster_recovery", "Create a checklist for disaster recovery planning covering backup verification, failover testing, communication protocols, and recovery time objectives"),
    ("security_incident", "Create a checklist for responding to a cybersecurity incident covering containment, evidence preservation, stakeholder notification, and post-mortem"),
]
```

#### Template 3 (Statement of Work) — Diverse Contract Topics

```python
TEMPLATE_3_THEME_TESTS = [
    # Creative services
    ("branding", "Write a statement of work for a corporate rebranding project covering brand audit, visual identity design, style guide creation, and rollout plan"),
    ("video_production", "Write a statement of work for a product video series covering scripting, filming, editing, and distribution across 6 episodes"),
    ("photography", "Write a statement of work for commercial real estate photography covering property visits, aerial drone shots, virtual tours, and delivery formats"),
    
    # Technical services
    ("data_migration", "Write a statement of work for migrating a legacy database to cloud infrastructure covering schema mapping, data validation, cutover planning, and rollback procedures"),
    ("penetration_testing", "Write a statement of work for a network penetration testing engagement covering scope definition, testing methodology, vulnerability reporting, and remediation verification"),
    ("ml_model", "Write a statement of work for developing a machine learning recommendation engine covering data pipeline, model training, A/B testing, and production deployment"),
    
    # Facilities/Physical
    ("hvac", "Write a statement of work for a commercial HVAC system replacement covering equipment specification, installation phases, testing, and warranty terms"),
    ("landscaping", "Write a statement of work for a corporate campus landscaping redesign covering site survey, design approval, planting schedule, and maintenance handoff"),
    ("electrical", "Write a statement of work for an electrical panel upgrade in a multi-tenant building covering load analysis, permit acquisition, installation, and inspection"),
]
```

### Theme Test Evaluation Criteria

For theme stress tests, scoring adjusts:

| Check | Standard (HOA) | Theme Test |
|-------|---------------|------------|
| Content grounded in source docs | Required | NOT required (no relevant docs) |
| Domain terminology present | HOA terms | Topic-specific terms |
| Author = "Patrick Flanigan" | Required | Required (from prompt) |
| Community = "Centerpointe" | Required | NOT required |
| Structure matches template | Required | Required |
| Format preserved | Required | Required |
| Location correct | Required | Required |

```python
def score_theme_test(filled_bytes, prompt, template_type):
    """Adjusted scoring for non-HOA theme tests."""
    # Content: check for topic-specific terms extracted from prompt
    topic_terms = extract_key_terms(prompt)  # e.g. "CRISPR", "gene editing", "agriculture"
    
    # Format + Location: same as standard scoring
    # Content: replace HOA-specific checks with topic relevance
    
    content_score = {
        "topic_terms_present": count_terms_in_doc(filled_bytes, topic_terms) >= 3,
        "title_relates_to_topic": any(t in get_title(filled_bytes) for t in topic_terms[:3]),
        "abstract_mentions_topic": any(t in get_abstract(filled_bytes) for t in topic_terms),
        "chapter_has_substance": get_chapter_chars(filled_bytes) >= 500,
        "no_hoa_bleed": "Centerpointe" not in get_full_text(filled_bytes),  # Shouldn't mention HOA
    }
```

### Test Matrix

| Template | HOA Prompts | General Prompts | Theme Stress | Total |
|----------|-------------|-----------------|--------------|-------|
| Template 1 | 5 | 5 | 12 | 22 |
| Template 2 | 3 | 4 | 9 | 16 |
| Template 3 | 3 | 3 | 9 | 15 |
| **Total** | **11** | **12** | **30** | **53 prompts** |

Full test matrix: 53 prompts × 7 models = **371 fill operations** (run as nightly/weekly, not on every commit).
