"""Template extraction from uploaded documents.

Analyzes a document's structure (not content) and returns a JSON
representation that can be used to generate new documents with the
same layout but different content.
"""

from __future__ import annotations

import json
import logging
import os
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_template(file_bytes: bytes, filename: str) -> dict:
    """Extract structure from a document file.

    Returns a dict describing the document's layout:
    {
        "type": "form" | "report" | "presentation" | "document",
        "title": str,
        "sections": [...],
        "source_format": str,
    }
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return _extract_pdf_template(file_bytes)
    elif ext in (".docx", ".doc"):
        return _extract_docx_template(file_bytes)
    elif ext == ".pptx":
        return _extract_pptx_template(file_bytes)
    elif ext == ".md":
        return _extract_md_template(file_bytes.decode("utf-8", errors="ignore"))
    elif ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif"):
        return _extract_image_template(file_bytes, ext)
    else:
        raise ValueError(f"Unsupported template format: {ext}")


def _extract_pdf_template(file_bytes: bytes) -> dict:
    """Extract structure from a PDF."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(file_bytes))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)

    # Use Bedrock to analyze the structure
    structure = _ask_bedrock_for_structure(text, "PDF")
    structure["source_format"] = "pdf"
    structure["page_count"] = len(reader.pages)
    return structure


def _extract_docx_template(file_bytes: bytes) -> dict:
    """Extract structure from a DOCX by walking the document tree."""
    from docx import Document

    doc = Document(BytesIO(file_bytes))
    sections = []
    current_section = {"heading": "", "elements": []}

    for para in doc.paragraphs:
        style = para.style.name if para.style else ""

        if "Heading" in style:
            # Start a new section
            if current_section["heading"] or current_section["elements"]:
                sections.append(current_section)
            level = int(style.replace("Heading ", "")) if style.replace("Heading ", "").isdigit() else 1
            current_section = {"heading": para.text, "level": level, "elements": []}
        elif para.text.strip():
            # Detect element type
            text = para.text.strip()
            if "___" in text or "____" in text:
                # Form field with blank
                label = text.split("___")[0].strip().rstrip(":")
                current_section["elements"].append({"type": "field", "label": label})
            elif text.startswith("☐") or text.startswith("□"):
                current_section["elements"].append({"type": "checkbox", "label": text[1:].strip()})
            elif style == "List Bullet" or text.startswith("•") or text.startswith("-"):
                current_section["elements"].append({"type": "bullet", "text": text.lstrip("•-").strip()})
            elif "signature" in text.lower():
                current_section["elements"].append({"type": "signature_line"})
            else:
                current_section["elements"].append({"type": "paragraph", "text": text[:100]})

    if current_section["heading"] or current_section["elements"]:
        sections.append(current_section)

    # Determine document type
    has_fields = any(
        e["type"] == "field" for s in sections for e in s.get("elements", [])
    )
    doc_type = "form" if has_fields else "document"

    title = sections[0]["heading"] if sections and sections[0].get("heading") else "Untitled"

    return {
        "type": doc_type,
        "title": title,
        "sections": sections,
        "source_format": "docx",
    }


def _extract_pptx_template(file_bytes: bytes) -> dict:
    """Extract structure from a PPTX."""
    from pptx import Presentation

    prs = Presentation(BytesIO(file_bytes))
    slides = []

    for slide in prs.slides:
        slide_data = {"title": "", "bullets": [], "has_image": False}

        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if not text:
                        continue
                    if not slide_data["title"]:
                        slide_data["title"] = text
                    else:
                        slide_data["bullets"].append(text)
            if shape.shape_type == 13:  # Picture
                slide_data["has_image"] = True

        slides.append(slide_data)

    return {
        "type": "presentation",
        "title": slides[0]["title"] if slides else "Untitled",
        "slide_count": len(slides),
        "slides": [
            {
                "title": s["title"],
                "bullet_count": len(s["bullets"]),
                "has_image": s["has_image"],
            }
            for s in slides
        ],
        "source_format": "pptx",
    }


def _extract_md_template(text: str) -> dict:
    """Extract structure from Markdown text."""
    sections = []
    current_section = {"heading": "", "level": 0, "elements": []}

    for line in text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("#"):
            if current_section["heading"] or current_section["elements"]:
                sections.append(current_section)
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped.lstrip("#").strip()
            current_section = {"heading": heading, "level": level, "elements": []}
        elif stripped.startswith("- ") or stripped.startswith("* "):
            current_section["elements"].append({"type": "bullet", "text": stripped[2:][:80]})
        elif stripped.startswith("|"):
            current_section["elements"].append({"type": "table_row"})
        elif "___" in stripped:
            label = stripped.split("___")[0].strip().rstrip(":")
            current_section["elements"].append({"type": "field", "label": label})
        elif stripped:
            current_section["elements"].append({"type": "paragraph", "text": stripped[:80]})

    if current_section["heading"] or current_section["elements"]:
        sections.append(current_section)

    has_fields = any(
        e["type"] == "field" for s in sections for e in s.get("elements", [])
    )

    return {
        "type": "form" if has_fields else "document",
        "title": sections[0]["heading"] if sections else "Untitled",
        "sections": sections,
        "source_format": "md",
    }


def _extract_image_template(file_bytes: bytes, ext: str) -> dict:
    """Send image to vision LLM to describe the document structure."""
    import boto3

    model_id = os.getenv("BEDROCK_VISION_MODEL_ID", "")
    if not model_id:
        raise ValueError("No Vision OCR model configured")

    fmt_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".tiff": "tiff", ".tif": "tiff"}
    fmt = fmt_map.get(ext, "jpeg")

    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

    resp = client.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [
                {"image": {"format": fmt, "source": {"bytes": file_bytes}}},
                {"text": (
                    "Analyze this document/form image and describe its STRUCTURE only (not content). "
                    "Return a JSON object with: "
                    '{"type": "form"|"document"|"report", "title": "...", "sections": [{"heading": "...", "elements": [{"type": "field"|"checkbox"|"paragraph"|"signature_line"|"table", "label": "..."}]}]}'
                    " Be precise about field labels, section headings, and element types."
                )},
            ],
        }],
        inferenceConfig={"maxTokens": 2048},
    )

    text = resp["output"]["message"]["content"][0]["text"]

    # Try to parse as JSON
    try:
        # Find JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            structure = json.loads(text[start:end])
            structure["source_format"] = "image"
            return structure
    except json.JSONDecodeError:
        pass

    # Fallback: return raw description
    return {
        "type": "document",
        "title": "Extracted from image",
        "description": text,
        "sections": [],
        "source_format": "image",
    }


def _ask_bedrock_for_structure(text: str, source_type: str) -> dict:
    """Ask Bedrock to analyze document text and return structure JSON."""
    import boto3

    model_id = os.getenv("BEDROCK_MODEL_ID", "")
    if not model_id:
        raise ValueError("No model configured")

    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

    resp = client.converse(
        modelId=model_id,
        system=[{"text": (
            "You analyze document structure. Return ONLY a JSON object describing the layout. "
            "Do not include the actual content, just the structure pattern."
        )}],
        messages=[{
            "role": "user",
            "content": [{"text": (
                f"Analyze this {source_type} document and describe its structure as JSON:\n\n"
                f"{text[:3000]}\n\n"
                "Return: {\"type\": \"form\"|\"document\"|\"report\", \"title\": \"...\", "
                "\"sections\": [{\"heading\": \"...\", \"elements\": [{\"type\": \"field\"|\"checkbox\"|\"paragraph\"|\"signature_line\"|\"table\", \"label\": \"...\"}]}]}"
            )}],
        }],
        inferenceConfig={"maxTokens": 2048},
    )

    text_resp = resp["output"]["message"]["content"][0]["text"]

    try:
        start = text_resp.find("{")
        end = text_resp.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text_resp[start:end])
    except json.JSONDecodeError:
        pass

    return {"type": "document", "title": "Untitled", "sections": []}
