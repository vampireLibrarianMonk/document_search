# Document Generation Strategy

## Overview

Add a "Create" tab to the app that lets users describe a document they need, then generates it using their indexed house documents as source material. The app searches for relevant content, sends it to Bedrock with the user's request, and produces a downloadable document in the chosen format.

This is RAG-powered document creation: the AI writes grounded in your actual documents, not from general knowledge.

## User Flow

1. User clicks the "Create" tab
2. Types a prompt: "Write a summary of all HOA fence and shed rules"
3. Selects output format (Markdown, DOCX, PDF, Image, PPTX)
4. Clicks "Generate"
5. App searches indexed documents for relevant chunks
6. Bedrock receives: system prompt + retrieved chunks + user request
7. Bedrock generates document content grounded in the source material
8. Content is converted to the requested format
9. User downloads the file

## Architecture

```
User prompt
    → search OpenSearch for relevant chunks (reuse existing search)
    → build context from top chunks + neighbors (reuse run_ask pattern)
    → send to Bedrock via Converse API:
        system: "You are a document writer. Use ONLY the provided excerpts."
        user: retrieved chunks + user's generation request
    → Bedrock returns Markdown content
    → convert to requested format:
        .md   → serve directly
        .docx → Pandoc with reference template
        .pdf  → Pandoc via weasyprint (or CairoSVG for templated)
        .png  → Markdown → styled HTML → Playwright screenshot
        .pptx → Pandoc slide-per-heading
        .svg  → SVG template + ElementTree substitution → CairoSVG
```

## Generation Paths

| Output             | Primary Path                                                   | Fallback                                             | Dependencies         |
| ------------------ | -------------------------------------------------------------- | ---------------------------------------------------- | -------------------- |
| Markdown (.md)     | Bedrock returns MD directly                                    | -                                                    | None                 |
| Word (.docx)       | python-docx with styled headings, bullets, form fields         | Pandoc fallback                                      | python-docx          |
| PDF (.pdf)         | Pandoc via weasyprint                                          | CairoSVG from SVG template, or Playwright screenshot | pandoc, weasyprint   |
| Image (.png)       | MD → styled HTML + CSS → Playwright screenshot                 | CairoSVG from SVG template                           | playwright, markdown |
| PowerPoint (.pptx) | python-pptx with navy/white theme, title slide, content slides | Pandoc fallback                                      | python-pptx          |
| SVG (templated)    | SVG template with stable IDs + string substitution             | -                                                    | cairosvg, xml.etree  |

## Dependencies

### Python Packages

| Package       | Role                                    | Already Installed |
| ------------- | --------------------------------------- | ----------------- |
| `python-docx` | Programmatic DOCX creation/manipulation | Yes               |
| `markdown`    | Markdown to HTML conversion             | No                |
| `playwright`  | Headless Chromium for HTML to PNG       | No                |
| `cairosvg`    | SVG to PNG/PDF rasterization            | No                |
| `weasyprint`  | HTML to PDF without LaTeX               | No                |
| `odfpy`       | ODT generation (fallback)               | No                |

### System Packages

| Tool     | Role                              | Install                       |
| -------- | --------------------------------- | ----------------------------- |
| Pandoc   | Universal document converter      | `sudo apt install pandoc`     |
| Chromium | Rendering engine (via Playwright) | `playwright install chromium` |

## Design Patterns (from Reference Document)

### 1. Pandoc with Reference Template

For DOCX and PPTX output with consistent branding:

```bash
pandoc content.md -o output.docx --reference-doc=templates/house_report.docx --toc
```

The reference template defines styles (fonts, colors, heading formats). Pandoc applies them to the generated content. Template is version-controlled in the repo.

### 2. CSS-Styled HTML Intermediate (for Images)

For PNG output with visual styling:

```python
# Convert markdown to HTML
html = markdown.markdown(content, extensions=["tables", "fenced_code"])

# Wrap in styled HTML with custom CSS
full_html = f"<html><head><style>{css}</style></head><body>{html}</body></html>"

# Screenshot with Playwright
page.set_content(full_html)
page.screenshot(path="output.png", full_page=True)
```

### 3. SVG Template Approach (from ORRG Reference)

For branded/structured visual documents (report covers, one-pagers):

```python
# Load SVG template with stable element IDs
tree = ElementTree.parse("templates/report-template.svg")

# Substitute content
tree.find(".//*[@id='title']").text = generated_title
tree.find(".//*[@id='body_content']").text = generated_body

# Render to PNG/PDF
svg_bytes = ElementTree.tostring(tree.getroot())
cairosvg.svg2png(bytestring=svg_bytes, write_to="output.png")
cairosvg.svg2pdf(bytestring=svg_bytes, write_to="output.pdf")
```

### 4. python-docx for Dynamic Assembly

For documents needing programmatic structure (tables from search results, conditional sections):

```python
from docx import Document
from docx.shared import Inches

doc = Document()
doc.add_heading("HOA Rules Summary", level=0)
doc.add_paragraph(generated_intro)

# Add a table of relevant documents
table = doc.add_table(rows=1, cols=3)
for chunk in relevant_chunks:
    row = table.add_row().cells
    row[0].text = chunk.title
    row[1].text = chunk.document_type
    row[2].text = chunk.content[:200]

doc.save("output.docx")
```

## Backend Implementation

### New Endpoint

```
POST /generate
Body: {
    "prompt": "Write a summary of HOA fence rules",
    "format": "docx",  // md, docx, pdf, png, pptx
    "top_k": 15,
    "filters": {}
}
Response: File download (binary)
```

### New Module: `app/generator.py`

Responsibilities:

- Retrieve relevant chunks (reuse search logic from services.py)
- Build generation prompt with retrieved context
- Call Bedrock Converse API with document-writing system prompt
- Convert Bedrock's markdown output to requested format
- Return file bytes

## Frontend Implementation

### New "Create" Tab

- Text area for the generation prompt
- Format dropdown (Markdown, Word, PDF, Image, PowerPoint)
- "Generate" button with loading state
- Download link when generation completes
- Preview panel for Markdown output

## Rollout Order

Each step is independently testable:

1. **Markdown** - Backend endpoint + Bedrock call + frontend tab. Test: generate a fence rules summary as .md
2. **Image (PNG)** - Add Playwright rendering. Test: generate a styled one-page summary as .png
3. **PDF** - Add Pandoc/weasyprint. Test: generate a multi-page report as .pdf
4. **DOCX** - Add Pandoc with reference template. Test: generate a Word doc with TOC
5. **PPTX** - Add Pandoc slide format. Test: generate a presentation from HOA rules

## File Structure

```
backend/
  app/
    generator.py           # Document generation logic
  templates/
    house_report.docx      # Pandoc reference template for DOCX
    report.css             # CSS for HTML/PNG rendering
    report-template.svg    # SVG template for branded output (optional)
frontend/
  src/
    main.ts                # Add "Create" tab
```

## System Prompt for Document Generation

```
You are a professional document writer. Your job is to create well-structured
documents using ONLY the provided source material from the user's house documents.

Rules:
- Use only information from the provided document excerpts
- Structure the output as clean Markdown with proper headings
- Include specific details, numbers, and quotes from the source material
- Cite which document each piece of information comes from
- If the source material doesn't contain enough information, say so clearly
- Write in plain English that a homeowner would understand
```

## Cost Considerations

- Generation uses the same Ask AI model (configurable in Settings)
- Each generation is one Bedrock call (same cost as an Ask AI question)
- Image generation adds Playwright rendering (free, local)
- PDF/DOCX/PPTX conversion via Pandoc (free, local)
- Token usage is tracked in the same usage dashboard

## Test Scenarios

Use these prompts to verify each format works correctly after implementation:

### Markdown Test

**Prompt:** "Create a one-page summary of all HOA fence and shed rules including height limits, approval requirements, and who to contact."
**Expected:** A clean markdown file with headings, bullet points, and citations from the architectural guidelines and CC&Rs.

### Image (PNG) Test

**Prompt:** "Create a quick-reference card of the HOA architectural review board submission process, including what documents are needed and the timeline."
**Expected:** A styled, readable PNG image suitable for printing or sharing, with the ARB steps laid out clearly.

### PDF Test

**Prompt:** "Generate a multi-page report summarizing all closing costs and fees from my house purchase, organized by category with totals."
**Expected:** A PDF with a table of contents, sections for each fee category (title, escrow, recording, etc.), and dollar amounts pulled from the closing disclosure and TRID fee schedule.

### Word (DOCX) Test

**Prompt:** "Write a letter to my HOA requesting approval for a 5-foot privacy fence in my backyard. Include the relevant rules I need to reference and the submission address."
**Expected:** A properly formatted Word document with letterhead-style layout, the request body citing specific HOA rules, and the ARB mailing address from the architectural guidelines.

**Alpha Loop (style iteration):**

| Iteration     | What to check                                          | How to improve                                           |
| ------------- | ------------------------------------------------------ | -------------------------------------------------------- |
| 1. Structure  | Are headings, paragraphs, and bullets correct?         | Adjust markdown parsing in `convert_to_docx`             |
| 2. Typography | Are fonts, sizes, and colors professional?             | Tweak Pt sizes and RGBColor values in the style setup    |
| 3. Spacing    | Is there enough whitespace between sections?           | Adjust `space_before`/`space_after` on paragraph formats |
| 4. Bold/forms | Are form fields (\_\_\_) and bold (**text**) rendered? | Check `_add_rich_text` and signature line handling       |
| 5. PDF match  | Does the PDF look consistent with the DOCX?            | Align the weasyprint CSS with the python-docx styles     |

**Pipeline:** Markdown → python-docx (styled DOCX) → weasyprint (styled PDF with matching CSS)

### PowerPoint (PPTX) Test

**Prompt:** "Create a 5-slide presentation explaining the HOA rules and regulations for new homeowners, covering architectural changes, assessments, meeting schedule, and contact information."
**Expected:** A PPTX with title slide, one slide per topic, bullet points with key rules, and a final slide with contact info pulled from the resale certificate and bylaws.

**Alpha Loop (style iteration):**

| Iteration           | What to check                                            | How to improve                                                  |
| ------------------- | -------------------------------------------------------- | --------------------------------------------------------------- |
| 1. Plain output     | Does Pandoc produce valid slides with correct structure? | Verify heading-to-slide mapping works                           |
| 2. Content quality  | Are bullets concise (4-6 per slide)? Is data accurate?   | Adjust the PPTX format instructions in the system prompt        |
| 3. Template styling | Are colors, fonts, backgrounds applied?                  | Edit `backend/templates/presentation.pptx` master slides        |
| 4. Layout fit       | Does content overflow slides? Are titles truncated?      | Tighten the "keep bullets short" instruction, adjust max_tokens |
| 5. Final polish     | Does it look professional enough to present?             | Refine template: add logo placeholder, footer, slide numbers    |

**Template location:** `backend/templates/presentation.pptx`
**To iterate on style:** Open the template in PowerPoint/LibreOffice, modify the slide masters (colors, fonts, backgrounds), save, and regenerate. Pandoc applies the template's theme to all generated content.

### Form Generation Test

**Prompt:** "Fill out an exterior modification application for a roof replacement. Use my address and the HOA's architectural review board submission requirements. Include the neighbor signature section."
**Expected:** A document (DOCX or PDF) that resembles the Centerpointe Exterior Modification Application form, pre-filled with the property address (12133 Tribune St), the ARB mailing address (Select Community Services, 4840 Westfields Blvd, Suite 100, Chantilly, VA 20151), the modification description for a roof replacement, and the neighbor acknowledgment section ready for signatures.
