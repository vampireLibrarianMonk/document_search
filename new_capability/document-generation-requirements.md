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

| File                                                  | Purpose                                 |
| ----------------------------------------------------- | --------------------------------------- |
| `documentation/test/images/export_markdown_to_png.py` | Main script: MD→PNG→ODT pipeline        |
| `documentation/test/images/export_format_rest.css`    | CSS for test spec rendering (dark mode) |
| `documentation/test/images/export_format_tm.css`      | CSS for traceability matrix rendering   |
| `pandoc.css`                                          | General pandoc dark-mode stylesheet     |

### Current Dependencies

| Package      | Role                                               |
| ------------ | -------------------------------------------------- |
| `markdown`   | Markdown → HTML conversion                         |
| `odfpy`      | Build OpenDocument Text programmatically           |
| `Pillow`     | Image manipulation (split traceability matrix PNG) |
| `playwright` | Headless Chromium for HTML → PNG screenshot        |

### External Tools Required

| Tool                      | Role                        |
| ------------------------- | --------------------------- |
| LibreOffice (headless)    | `.odt` → `.docx` conversion |
| Chromium (via Playwright) | HTML rendering engine       |

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

| Package / Tool       | Role                                                                                                            | Install                                                                       |
| -------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **Pandoc**           | Universal document converter (MD → DOCX, PDF, HTML, EPUB)                                                       | `sudo apt install pandoc` or [pandoc.org](https://pandoc.org/installing.html) |
| **python-docx**      | Programmatic DOCX creation/manipulation in Python                                                               | `pip install python-docx`                                                     |
| **Sphinx**           | Documentation generator with cross-referencing, TOC trees, and multi-format output (HTML, PDF, EPUB, man pages) | `pip install sphinx`                                                          |
| **MyST-Parser**      | Sphinx extension enabling Markdown (instead of RST) as source                                                   | `pip install myst-parser`                                                     |
| **sphinx-rtd-theme** | Read the Docs theme for professional HTML output                                                                | `pip install sphinx-rtd-theme`                                                |

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

| Goal                                                  | Recommended Tool                          |
| ----------------------------------------------------- | ----------------------------------------- |
| Quick single-document export (MD → DOCX)              | Pandoc                                    |
| Aggregated test report with TOC (current use case)    | Pandoc with `--toc` and `--reference-doc` |
| Programmatic report generation from Django data       | python-docx                               |
| Full project documentation site + multi-format export | Sphinx + MyST-Parser                      |
| Retain current PNG-based visual fidelity              | Keep existing Playwright pipeline         |

### Migration Path

1. **Immediate improvement:** Replace the ODT/LibreOffice step with Pandoc for direct `.docx` output with searchable text.
2. **Medium-term:** Add a `docs/` Sphinx site using MyST-Parser to unify all project documentation (guides + test specs) under one build system.
3. **Keep existing tool** for visual-fidelity PNG exports where exact rendered appearance matters (e.g., embedding screenshots in presentations).

---

## 4. Reference Implementation: SVG Template → Document Pipeline (ORRG Project)

The **Open Range Ring Generator** (`range_ring_2016_05_12`) implements a production SVG-to-document generation pipeline that converts geospatial analysis outputs into professional IC-style PNG and PDF products via an SVG template intermediary.

### Pipeline

```
RangeRingOutput / Trajectory Data
    → render map image (matplotlib + GeoServer WMS basemap)
    → encode map as base64 PNG
    → load SVG template (app/templates/output-template.svg)
    → substitute title, classification, legend, coordinates, attribution, map image
    → dynamically build multi-item legend via ElementTree
    → output final SVG string
    → CairoSVG converts SVG → PNG (cairosvg.svg2png)
    → CairoSVG converts SVG → PDF (cairosvg.svg2pdf)
```

### Source Files

| File                                                                              | Purpose                                                                   |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `app/exports/png.py` → `render_svg_with_template()`                               | Main SVG rendering engine for range-ring tools (~340 lines)               |
| `app/exports/pdf.py` → `export_to_pdf_bytes()`                                    | SVG → PDF conversion via CairoSVG (with reportlab fallback)               |
| `app/templates/output-template.svg`                                               | IC-style product layout template (1400×900px, header/map/legend/metadata) |
| `app/ui/tools/shared.py` → `_cached_svg_export()`                                 | Streamlit-cached SVG generation for reuse by PNG and PDF exports          |
| `app/ui/tools/launch_trajectory/ui.py` → `_render_trajectory_svg_with_template()` | Trajectory-specific SVG rendering variant                                 |
| `app/ui/command/shared_command_utils.py`                                          | Command Center SVG→PNG/PDF export path                                    |

### SVG Template Structure (`output-template.svg`)

The template is a 1400×900 SVG with stable element IDs for programmatic substitution:

| Element ID                                   | Content                                                  |
| -------------------------------------------- | -------------------------------------------------------- |
| `product_title_line1` / `line2`              | Dynamic title and subtitle                               |
| `classification_top_right` / `bottom_left`   | Classification banners                                   |
| `created_by`, `source_line1`, `source_line2` | Attribution metadata                                     |
| `map_image`                                  | Base64-encoded map PNG (main content area: 1336×676px)   |
| `legend_items_container`                     | Dynamically generated multi-item legend (expands upward) |
| `coordinate_line1` / `line2`                 | Projection and datum info                                |
| `attribution_text`                           | Data source attribution                                  |

### Dependencies

| Package     | Version | Role                                            |
| ----------- | ------- | ----------------------------------------------- |
| `CairoSVG`  | 2.8.2   | SVG → PNG and SVG → PDF rasterization           |
| `cairocffi` | 1.7.1   | Cairo bindings (CairoSVG backend)               |
| `reportlab` | 4.4.9   | Fallback PDF generation if CairoSVG unavailable |
| `simplekml` | 1.3.6   | KMZ export (parallel export path)               |

### Key Design Patterns

- **Single SVG, multiple outputs:** One `render_svg_with_template()` call produces the SVG; the same bytes feed both `svg2png` and `svg2pdf` — no redundant rendering.
- **Streamlit caching:** `@st.cache_data` decorators on `_cached_svg_export`, `_cached_png_export`, `_cached_pdf_export` prevent re-rendering on UI interactions.
- **Dynamic legend via ElementTree:** Legend items are built programmatically from output layers (polygons → rect swatches, points → circles, lines → line elements), with the legend box expanding upward from a fixed bottom edge.
- **Template rationale:** Deterministic, version-controlled SVG layout replaces proprietary ArcGIS MXD workflows — transparent, scriptable, and analyst-owned.
- **Graceful fallback:** If CairoSVG is not installed, PDF export falls back to reportlab-based generation (no SVG template, simpler layout).

### Applicability to This Project

| ORRG Pattern                                       | Potential Reuse                                                                    |
| -------------------------------------------------- | ---------------------------------------------------------------------------------- |
| SVG template with stable IDs + string substitution | Any report needing branded/structured layout with dynamic content                  |
| CairoSVG for SVG → PNG/PDF                         | Lightweight alternative to Playwright for vector-to-raster conversion              |
| Base64 image embedding in SVG                      | Embedding charts, maps, or screenshots in templated documents                      |
| ElementTree for dynamic SVG manipulation           | Programmatic legend/table/diagram generation                                       |
| Cached export pipeline                             | Streamlit or web apps needing on-demand document generation without re-computation |
