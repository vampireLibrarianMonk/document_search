# Document Generation Requirements

## 1. Current Capability (from `llm-integration` branch)

### Overview

The existing tool (`documentation/test/images/export_markdown_to_png.py`) aggregates all test specification markdown files, renders them as styled PNG screenshots, assembles them into a single OpenDocument Text (`.odt`) file with a table of contents, and relies on LibreOffice for final `.docx` conversion.

### Pipeline

```
Markdown files (.md)
    → inline base64 images
    → convert to styled HTML (via python-markdown + custom CSS)
    → render to PNG (via Playwright/Chromium headless)
    → assemble PNGs into .odt (via odfpy)
    → convert .odt to .docx (via LibreOffice headless CLI)
```

### Source Files

| File | Purpose |
|------|---------|
| `documentation/test/images/export_markdown_to_png.py` | Main script: MD→PNG→ODT pipeline |
| `documentation/test/images/export_format_rest.css` | CSS for test spec rendering (dark mode) |
| `documentation/test/images/export_format_tm.css` | CSS for traceability matrix rendering |
| `pandoc.css` | General pandoc dark-mode stylesheet |

### Current Dependencies

| Package | Role |
|---------|------|
| `markdown` | Markdown → HTML conversion |
| `odfpy` | Build OpenDocument Text programmatically |
| `Pillow` | Image manipulation (split traceability matrix PNG) |
| `playwright` | Headless Chromium for HTML → PNG screenshot |

### External Tools Required

| Tool | Role |
|------|------|
| LibreOffice (headless) | `.odt` → `.docx` conversion |
| Chromium (via Playwright) | HTML rendering engine |

### Features

- Categorizes markdown by prefix (UT-, MAT-, UAT-, ST-, TRACEABILITY_MATRIX)
- Applies category-specific CSS styling
- Inlines supporting images as base64 data URIs
- Generates a table of contents with GitHub links and internal bookmarks
- Handles oversized content (splits traceability matrix across two pages)
- Ordered output by category (MAT → ST → UT → UAT → Traceability Matrix)

### Limitations

- Output is image-based (PNGs embedded in ODT) — text is not selectable/searchable in the final document
- Requires LibreOffice installed for `.docx` conversion
- No direct Markdown → DOCX path (lossy intermediate steps)
- Hardcoded to dark-mode styling only
- Tightly coupled to the test documentation directory structure
- No CLI arguments or configuration file — behavior is entirely hardcoded

---

## 2. Recommended Augmentation: Direct Markdown → Document Pipeline

### Additional Tools

| Package / Tool | Role | Install |
|----------------|------|---------|
| **Pandoc** | Universal document converter (MD → DOCX, PDF, HTML, EPUB) | `sudo apt install pandoc` or [pandoc.org](https://pandoc.org/installing.html) |
| **python-docx** | Programmatic DOCX creation/manipulation in Python | `pip install python-docx` |
| **Sphinx** | Documentation generator with cross-referencing, TOC trees, and multi-format output (HTML, PDF, EPUB, man pages) | `pip install sphinx` |
| **MyST-Parser** | Sphinx extension enabling Markdown (instead of RST) as source | `pip install myst-parser` |
| **sphinx-rtd-theme** | Read the Docs theme for professional HTML output | `pip install sphinx-rtd-theme` |

### Pandoc-Based Approach (Simplest)

Replaces the PNG-screenshot pipeline with a direct text-preserving conversion:

```bash
# Single markdown → docx
pandoc input.md -o output.docx --reference-doc=template.docx

# Aggregate multiple markdowns → single docx (ordered)
pandoc \
  documentation/test/acceptance/MAT-*.md \
  documentation/test/system/ST-*.md \
  documentation/test/unit/UT-*.md \
  documentation/test/traceability_matrix.md \
  -o all_tests.docx \
  --toc \
  --reference-doc=template.docx
```

**Advantages over current approach:**
- Searchable, selectable text in output
- Native Word styles, headings, and TOC
- Custom styling via `--reference-doc` template
- Supports PDF output via LaTeX (`pandoc ... -o output.pdf`)
- No Playwright/Chromium dependency

### python-docx Approach (Programmatic Control)

For cases requiring fine-grained control over document structure:

```python
from docx import Document
from docx.shared import Inches

doc = Document()
doc.add_heading('Test Report', level=0)
# Programmatically add sections, tables, images
doc.save('report.docx')
```

**Use when:** you need dynamic content assembly, conditional sections, or integration with Django models.

### Sphinx + MyST Approach (Full Documentation Site + Export)

For maintaining a living documentation site that also exports to Word/PDF:

```
docs/
├── conf.py          # Sphinx configuration
├── index.md         # TOC tree root
├── test/
│   ├── acceptance/
│   ├── unit/
│   └── system/
└── _build/          # Output (HTML, PDF, DOCX)
```

**Advantages:**
- Cross-references between documents
- Auto-generated index and search
- Multi-format output from single source
- Integrates with GitHub Pages / Read the Docs hosting
- Extensible via plugins (diagrams, API docs, etc.)

---

## 3. Recommended Strategy

| Goal | Recommended Tool |
|------|-----------------|
| Quick single-document export (MD → DOCX) | Pandoc |
| Aggregated test report with TOC (current use case) | Pandoc with `--toc` and `--reference-doc` |
| Programmatic report generation from Django data | python-docx |
| Full project documentation site + multi-format export | Sphinx + MyST-Parser |
| Retain current PNG-based visual fidelity | Keep existing Playwright pipeline |

### Migration Path

1. **Immediate improvement:** Replace the ODT/LibreOffice step with Pandoc for direct `.docx` output with searchable text.
2. **Medium-term:** Add a `docs/` Sphinx site using MyST-Parser to unify all project documentation (guides + test specs) under one build system.
3. **Keep existing tool** for visual-fidelity PNG exports where exact rendered appearance matters (e.g., embedding screenshots in presentations).
