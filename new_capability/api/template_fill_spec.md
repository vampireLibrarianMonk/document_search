# Template Fill Specification

## Overview

This document governs how to fill a DOCX template with AI-generated content while preserving exact formatting, layout, fonts, and page structure. Uses `template_1.docx` (academic thesis) as the reference implementation.

## Template Anatomy

A DOCX template contains these fillable element types:

### 1. SDT Placeholders (`showingPlcHdr`)
- Content controls marked with `<w:showingPlcHdr/>` in their properties
- Contains sample text that should be replaced
- May have multiple `<w:r>` (runs) — each run is a separate line/formatting segment
- **Rule**: Replace text in runs, preserve run formatting (bold, italic, size, font)

### 2. MACROBUTTON Fields
- `<w:instrText>` containing `MACROBUTTON DoFieldClick [Label]`
- Renders as clickable placeholder text in Word (e.g., `[Last, First Name of Author]`)
- Surrounded by `<w:fldChar>` begin/separate/end markers
- **Rule**: Remove the entire field sequence (all runs from begin to end)

### 3. Table Cells with Patterns
- Bibliography: cells containing `. . , .` (dot-comma pattern = citation placeholder)
- Index: cells in multi-column tables with alphabetical entries
- **Rule**: Replace cell text content, remove empty rows after filling

### 4. Static Text
- Regular paragraphs or non-placeholder SDTs with sample content
- Examples: "Professor Janessa Bughatti", "Department of Science"
- **Rule**: Find-and-replace in `<w:t>` elements

## Page-by-Page Structure (template_1)

### Page 1: Title Page
- **Container**: Table (14 rows × 2-4 cols) — DO NOT remove empty rows (they're spacers)
- **Background**: Anchored image (2.10×11.00 in, behind text, offset H=-1371600 V=-685800 EMU)
- **SDTs 1-10**: Title page fields

| SDT | Runs | Role | Original | Constraint |
|-----|------|------|----------|------------|
| 1 | 3 | title | "The" / "" / "Universe" | Array of 3, each ≤12 chars |
| 2 | 2 | author | "by" / "Diert Maage" | Array: ["by", "Name"] |
| 3 | 2 | description | "A thesis submitted..." / "Doctoral Degree..." | Array: [~70 chars, ~30 chars] |
| 4 | 3 | institution | "Glenwood" / " " / "University" | Array: [word, " ", word] |
| 5 | 1 | year | "20XX" | ≤4 chars |
| 6 | 1 | label | "Approved by" | Keep as-is |
| 7 | 1 | committee | "Chairperson of Supervisory Committee" | ≤36 chars |
| 8 | 1 | program | "Program to Offer Degree" | ≤23 chars |
| 9 | 1 | label | "Authorized" | Keep as-is |
| 10 | 1 | date | "Date" | ≤15 chars |

### Page 2: Abstract
- **Page break**: Required before this section
- **SDTs 11-15**:

| SDT | Role | Original | Notes |
|-----|------|----------|-------|
| 11 | institution_repeat | "Glenwood University" | Same as page 1 institution |
| 12 | heading | "Abstract" | Keep as-is |
| 13 | title_repeat | "The Universe" | Same as page 1 title |
| 14 | author_repeat | "By Diert Maage" | Same as page 1 author |
| 15 | abstract_body | "A thesis presented on..." (2 runs, 224 chars) | [body text, " "] |

- **Static text** (non-SDT, must be find-replaced):
  - "Chairperson of the Supervisory Committee:" → role title
  - "Professor Janessa " + "Bughatti" → name (split across 2 `<w:t>`)
  - "Department of Science" → department/board name

### Page 3: Table of Contents
- **SDT 16**: Heading "Table of Contents"
- **SDT 17**: TOC entries (69 runs, 17 non-empty) — alternating [title, page_number]
- **Rule**: Replace only non-empty runs in order

### Page 4: List of Figures
- **SDT 18**: Heading "List of figures"
- **SDT 19**: Column headers "Number" / "Page" — keep as-is
- **SDT 20**: Figure entries (30 runs, 20 non-empty) — alternating [name, page_number]

### Page 5: Acknowledgments
- **SDT 21**: Heading "Acknowledgments"
- **SDT 22**: Body (3 runs) — [opening thanks ~190 chars, person name ~15 chars, closing ~175 chars]

### Page 6: Glossary
- **SDT 23**: Heading "Glossary"
- **SDTs 24-39**: Alternating term/definition pairs (8 pairs = 16 SDTs)
- **Rule**: Fill all pairs; if fewer terms needed, set remaining to ""

### Pages 7-8: Chapter
- **SDT 39**: "Chapter 1" (or chapter number)
- **SDT 40**: Chapter title heading
- **SDTs 41-90**: Chapter body — subheadings and paragraphs
  - Subheadings: short text, no period
  - Body paragraphs: 1-3 sentences
- **Rule**: Fill used slots, set unused to "" (they collapse)

### Page 9: Bibliography
- **SDT 91**: Heading "Bibliography"
- **Table 2** (17 rows × 3 cols): Bibliography entries
  - Col 0: entry text, Col 1: spacer (empty), Col 2: entry text
  - Each row holds 2 entries side by side
  - **MACROBUTTON fields** inside cells: `[Last, First Name of Author]`, `[Title]`, `[Publisher]`, `[year of publication]`
- **Rule**: Replace ALL `<w:t>` in each cell (not just first), remove empty rows after

### Page 10: Index
- **SDT 92**: Heading "Index"
- **Table 3** (12 rows × 5 cols): Index entries
  - Cols 0,2,4: content; Cols 1,3: spacers
  - Single letters = section headers; "Term, page" = entries
- **SDTs 93-124**: Individual index cells
- **Rule**: Replace all SDTs; table cells also need direct replacement

### Endnotes
- **SDT 124**: Endnote text

## Font & Layout Data to Preserve

| Property | Value | Source |
|----------|-------|--------|
| Heading font | Franklin Gothic Demi | Theme (word/theme/theme11.xml) |
| Body font | Franklin Gothic Book | Theme |
| Default size | 12pt | styles2.xml docDefaults |
| Heading 1 size | 16pt | Style definition |
| Page size | 8.5 × 11.0 in | sectPr/pgSz |
| Margins | T=0.75 B=0.44 L=1.50 R=1.50 in | sectPr/pgMar |
| Orientation | Portrait | pgSz w < h |

## Apply Phase Rules

1. **SDT replacement**: Match run count. If replacement is array, fill runs 1:1. If string, put in first run, clear rest.
2. **MACROBUTTON removal**: Find all `<w:instrText>` with "MACROBUTTON", walk up to `<w:p>`, remove all runs containing `<w:fldChar>`, `<w:instrText>`, or bracket text `[...]`.
3. **Table cell replacement**: Set first `<w:t>` to new text, set ALL remaining `<w:t>` in same cell to "".
4. **Static text**: Direct find-replace on `<w:t>` elements (handle split across elements).
5. **Empty row removal**: Remove rows from bibliography/index tables ONLY (not title page table).
6. **Empty paragraph removal**: Remove `<w:p>` with no text, no drawing, no page break. Only at body level (not inside tables).
7. **Page breaks**: Insert `<w:br w:type="page"/>` before each section heading.
8. **Bookmark cleanup**: Remove orphaned `<w:bookmarkStart>` / `<w:bookmarkEnd>` at body level.

## Generation Strategy

Generate content **per section** (not one massive call):

| Section | Method | Bedrock? |
|---------|--------|----------|
| Title page | One call, constrained by char limits | Yes |
| Abstract | One call | Yes |
| Acknowledgments | One call | Yes |
| Glossary | One call | Yes |
| Chapter | One call with subheadings | Yes |
| TOC | Deterministic from chapter headings | No |
| Figures | Deterministic | No |
| Bibliography | From actual indexed document titles | No |
| Index | Deterministic from content terms | No |

## Scoring Criteria (95% target)

| Category | Checks | Weight |
|----------|--------|--------|
| Artifacts cleared | 17 patterns must not appear | 53% |
| Expected content | 12 terms must appear | 38% |
| Structure | MACROBUTTONs=0, no empty bib rows, page breaks≥5 | 9% |

**Formula**: `score = (artifacts_cleared + content_found + structure_checks) / 32`


## Chapter Fill Strategy (Discovered via Analysis)

The chapter section (SDTs 40-90) contains 51 SDTs that in the original template form:
- 4 subheadings (single SDTs with short text, no period)
- 5 body paragraphs (each split across 5-15 SDTs for inline bold formatting)

**Problem**: The SDTs are individual XML elements — not grouped by paragraph in the tree. Word renders them inline because they lack paragraph breaks between them, but structurally they're siblings.

**Solution**: Treat the chapter as a **sequential fill**:
1. SDT 40 = chapter title
2. SDT 41 = first subheading
3. SDT 42 = first body paragraph (full text in one SDT)
4. SDT 43 = second subheading  
5. SDT 44 = second body paragraph
6. SDT 45 = third subheading
7. SDT 46 = third body paragraph
8. SDTs 47-90 = set to "" (they collapse, original inline fragments no longer needed)

The bold keywords from the original (like "Save As", "File", "Insert") are lost — but that's acceptable because the new content has different keywords. The paragraph formatting (font, size, spacing) is inherited from the SDT's style.

## Glossary Fill Strategy

SDTs alternate: term (short, ≤30 chars) → definition (longer). 
- Terms inherit bold formatting from the paragraph style
- Definitions inherit normal formatting
- Fill pairs sequentially: SDT 24=term1, 25=def1, 26=term2, 27=def2...
- Unused pairs (if fewer than 8 terms): set to ""

## Intermediate Process Summary

```
ORIGINAL DOCX
     │
     ▼
[1. ANALYZE] → Fill Schema JSON
     │         • SDT inventory with formatting per run
     │         • Paragraph grouping (which SDTs form one logical unit)
     │         • Role assignment (heading, term, definition, paragraph, label)
     │         • Character budgets per slot
     │         • Table structure (rows, cols, fill pattern)
     │         • Static text locations
     │         • MACROBUTTON field locations
     │
     ▼
[2. GENERATE] → Replacement Content (per section, multiple Bedrock calls)
     │         • Title page: constrained by run structure and char limits
     │         • Abstract: single paragraph ≤250 chars
     │         • Glossary: term/definition pairs
     │         • Chapter: sequential heading/paragraph fill
     │         • Bibliography: from actual indexed document titles
     │         • Index: from terms found in generated content + page numbers
     │         • TOC: deterministic from section headings
     │
     ▼
[3. APPLY] → Filled DOCX (single pass)
     │         • Replace SDT text (respecting multi-run structure)
     │         • Remove MACROBUTTON fields
     │         • Fill bibliography table cells (clear ALL w:t in each cell)
     │         • Fill index table cells
     │         • Replace static text
     │         • Remove empty rows (bib/index only, NOT title table)
     │         • Remove empty body-level paragraphs
     │         • Deduplicate page breaks
     │         • Remove orphaned bookmarks
     │
     ▼
[4. POST-PROCESS] → Final validation
     │         • Rebuild index from actual content + page numbers
     │         • Update TOC page numbers if content shifted
     │         • Verify no artifacts remain
     │         • Verify page count matches expected
```
