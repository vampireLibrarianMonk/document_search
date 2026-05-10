# Template Extraction from Uploaded Documents

## Overview

Allow users to upload an existing document (PDF, DOCX, PPTX, MD, or image) and have the app extract its structure/format as a reusable template. The user can then use that template to generate new documents with different content but the same layout.

## User Flow

1. User clicks "Import Template" in the Create tab
2. Selects a file (PDF, DOCX, PPTX, MD, or image of a form)
3. App analyzes the document structure:
   - Headings hierarchy
   - Section layout
   - Field labels and blanks (for forms)
   - Table structures
   - Bullet/numbered list patterns
   - Signature lines
   - Logos/headers/footers (noted but not reproduced)
4. App presents the extracted template structure for review
5. User saves the template with a name
6. When creating a new document, user can select a saved template
7. The generation prompt includes the template structure so Bedrock follows it

## What Gets Extracted Per Format

| Format | What we extract |
|--------|----------------|
| PDF | Text structure via pypdf, form fields if present, section headings, tables |
| DOCX | Heading styles, paragraph structure, table layouts, form fields (content controls) |
| PPTX | Slide count, slide titles, bullet structure per slide, layout pattern |
| MD | Heading hierarchy, section names, list patterns, table structure |
| Image | Send to vision LLM with prompt: "Describe the layout and structure of this form/document" |

## Architecture

```
User uploads template file
    → extract structure (not content, just layout)
    → store template in Postgres (name, format, structure JSON)
    → when generating, inject template structure into Bedrock prompt:
        "Follow this exact structure: [template JSON]"
    → Bedrock generates content matching the template layout
    → convert to requested output format
```

## Data Model

```sql
CREATE TABLE templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_format TEXT NOT NULL,
    structure JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

Structure JSON example (for a form):
```json
{
  "type": "form",
  "title": "Exterior Modification Application",
  "sections": [
    {
      "heading": "Homeowner Information",
      "fields": ["Name", "Address", "Phone", "Email"]
    },
    {
      "heading": "Proposed Modification",
      "fields": ["Description", "Materials", "Color"],
      "type": "textarea"
    },
    {
      "heading": "Neighbor Acknowledgments",
      "repeating": true,
      "fields": ["Signature", "Date"]
    }
  ],
  "submission_info": "Mail to: [address]"
}
```

## API Endpoints

```
POST /templates/extract    - Upload a file, extract its structure as a template
GET  /templates            - List saved templates
GET  /templates/{id}       - Get a template's structure
DELETE /templates/{id}     - Delete a template
POST /generate             - (updated) Accept optional template_id parameter
```

## Frontend Changes

- Add "Import Template" button in Create tab
- Template selector dropdown (alongside document selector)
- Template preview showing the extracted structure
- Template management (list, delete)

## Implementation Steps

1. Add `templates` table to Postgres schema
2. Create `template_extractor.py` module with per-format extraction logic
3. Add API endpoints for template CRUD
4. Update `/generate` to accept `template_id` and inject structure into prompt
5. Update frontend Create tab with template selector and import button
6. Test with the HOA exterior modification form as the primary test case

## Test Scenarios

### PDF Form Template
**Input:** Appendix 02 Architectural Guidelines PDF (the exterior modification form)
**Expected:** Extracts section headings, field labels, checkbox items, signature lines, submission address

### PPTX Template
**Input:** A generated PowerPoint from the Create tab
**Expected:** Extracts slide count, title patterns, bullet structure per slide

### DOCX Template
**Input:** A generated Word document
**Expected:** Extracts heading hierarchy, paragraph/bullet patterns, table structures

### Image Template
**Input:** Photo of a paper form
**Expected:** Vision LLM describes the layout: "This is a form with sections for X, Y, Z with blank lines for..."
