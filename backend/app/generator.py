"""Document generation from user prompts + indexed document context.

Uses RAG (retrieval-augmented generation) to create documents grounded
in the user's actual house documents. Supports multiple output formats:
  - Markdown (.md) - direct from Bedrock
  - Word (.docx) - via Pandoc with optional reference template
  - PDF (.pdf) - via Pandoc + weasyprint
  - Image (.png) - Markdown to styled HTML, screenshot via Playwright
  - PowerPoint (.pptx) - via Pandoc slide-per-heading
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_RULES = (
    "- Use only information from the provided source documents\n"
    "- Include specific details, numbers, addresses, and names from the source material\n"
    "- If the source material doesn't contain enough information, say so clearly\n"
    "- Write in plain English that a homeowner would understand"
)

_FORMAT_INSTRUCTIONS = {
    "md": (
        "Structure the output as clean Markdown with proper headings (# ## ###), "
        "bullet points, and paragraphs. Use bold for key terms."
    ),
    "docx": (
        "Structure the output as a formal document with:\n"
        "- A clear title as a level-1 heading\n"
        "- Sections with level-2 headings\n"
        "- Proper paragraphs (not just bullet points)\n"
        "- Tables where data comparison is useful\n"
        "- A professional, complete tone suitable for a Word document"
    ),
    "pdf": (
        "Structure the output as a formal report with:\n"
        "- A title and subtitle\n"
        "- Sections with clear headings\n"
        "- Detailed paragraphs with supporting data\n"
        "- Tables for structured information\n"
        "- A conclusion or summary section"
    ),
    "png": (
        "Structure the output as a concise, single-page reference card:\n"
        "- Keep it brief and scannable\n"
        "- Use short bullet points, not long paragraphs\n"
        "- Organize into 2-4 clear sections\n"
        "- Include only the most important facts\n"
        "- Aim for no more than 30 lines total"
    ),
    "pptx": (
        "Structure the output as a presentation with EXACTLY this format:\n"
        "- First level-1 heading (# Title) becomes the title slide\n"
        "- Each level-2 heading (## Slide Title) becomes a new slide\n"
        "- Under each slide heading, use bullet points (- item)\n"
        "- Keep each slide to 4-6 bullet points maximum\n"
        "- Keep bullet points short (one line each)\n"
        "- Include a final slide with summary or contact info\n"
        "- Aim for 5-8 slides total"
    ),
    "form": (
        "Structure the output as a fillable form with:\n"
        "- A form title as level-1 heading\n"
        "- Sections with level-2 headings\n"
        "- Field labels followed by blanks: **Field Name:** _______________\n"
        "- Checkbox items: ☐ Option text\n"
        "- Signature lines: **Signature:** ___________________________ **Date:** ___________\n"
        "- Pre-fill any fields where the information is available in the source documents\n"
        "- Include all addresses, phone numbers, and submission instructions from the source"
    ),
}


def generate_markdown(prompt: str, context: str, manual_mode: bool = False, fmt: str = "md") -> str:
    """Ask Bedrock to generate a markdown document from context and prompt."""
    import boto3

    model_id = os.getenv("BEDROCK_GENERATE_MODEL_ID", "") or os.getenv("BEDROCK_MODEL_ID", "")
    if not model_id:
        raise ValueError("No Ask AI model configured. Set it in Settings.")

    client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )

    # Detect if this is a form request
    effective_fmt = fmt
    form_keywords = ["form", "application", "fill out", "fill in", "request form"]
    if any(kw in prompt.lower() for kw in form_keywords):
        effective_fmt = "form"

    format_instruction = _FORMAT_INSTRUCTIONS.get(effective_fmt, _FORMAT_INSTRUCTIONS["md"])

    mode_intro = (
        "The user has selected specific documents as source material. "
        "Their prompt describes WHAT to create, not what to search for."
        if manual_mode
        else "Your job is to create well-structured documents using ONLY the provided source material."
    )

    system_prompt = (
        f"You are a professional document writer. {mode_intro}\n\n"
        f"Output format instructions:\n{format_instruction}\n\n"
        f"Rules:\n{_BASE_RULES}"
    )

    user_msg = (
        f"Source documents:\n{context}\n\n"
        f"Request: {prompt}\n\n"
        "Generate the document in Markdown format following the format instructions above."
    )

    resp = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_msg}]}],
        inferenceConfig={"maxTokens": 4096},
    )

    content = resp["output"]["message"]["content"][0]["text"]

    # Track usage
    if os.getenv("TRACK_USAGE", "true").lower() == "true":
        usage = resp.get("usage", {})
        try:
            from .pricing import estimate_cost
            from .db import get_conn

            cost = estimate_cost(
                model_id,
                usage.get("inputTokens", 0),
                usage.get("outputTokens", 0),
                os.getenv("AWS_REGION", "us-east-1"),
            )
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO token_usage
                       (model_id, operation, input_tokens, output_tokens, estimated_cost_usd)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (model_id, "generate", usage.get("inputTokens", 0),
                     usage.get("outputTokens", 0), cost),
                )
            conn.close()
        except Exception:
            pass

    return content


def convert_to_docx(markdown_content: str) -> bytes:
    """Convert markdown to DOCX using Pandoc."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as md_file:
        md_file.write(markdown_content)
        md_path = md_file.name

    out_path = md_path.replace(".md", ".docx")
    try:
        subprocess.run(
            ["pandoc", md_path, "-o", out_path, "--toc"],
            check=True, capture_output=True,
        )
        return Path(out_path).read_bytes()
    finally:
        os.unlink(md_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def convert_to_pdf(markdown_content: str) -> bytes:
    """Convert markdown to PDF using Pandoc + weasyprint or HTML intermediate."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as md_file:
        md_file.write(markdown_content)
        md_path = md_file.name

    out_path = md_path.replace(".md", ".pdf")
    try:
        # Try pandoc with weasyprint first
        result = subprocess.run(
            ["pandoc", md_path, "-o", out_path, "--pdf-engine=weasyprint"],
            capture_output=True,
        )
        if result.returncode == 0:
            return Path(out_path).read_bytes()

        # Fallback: convert to HTML then use weasyprint directly
        import markdown as md_lib
        from weasyprint import HTML

        html = md_lib.markdown(markdown_content, extensions=["tables", "fenced_code"])
        styled = f"""<html><head><style>
            body {{ font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; }}
            h1 {{ color: #1a1a2e; }} h2 {{ color: #374151; }}
            table {{ border-collapse: collapse; width: 100%; }}
            td, th {{ border: 1px solid #ddd; padding: 8px; }}
        </style></head><body>{html}</body></html>"""

        pdf_bytes = HTML(string=styled).write_pdf()
        return pdf_bytes
    finally:
        os.unlink(md_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def convert_to_png(markdown_content: str) -> bytes:
    """Convert markdown to a styled PNG image using Playwright."""
    import markdown as md_lib
    from playwright.sync_api import sync_playwright

    html = md_lib.markdown(markdown_content, extensions=["tables", "fenced_code"])
    styled = f"""<html><head><style>
        body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 0 auto;
               padding: 40px; line-height: 1.6; color: #1a1a2e; background: #fff; }}
        h1 {{ font-size: 1.8rem; color: #1a1a2e; border-bottom: 2px solid #6366f1; padding-bottom: 8px; }}
        h2 {{ font-size: 1.3rem; color: #374151; margin-top: 24px; }}
        ul, ol {{ padding-left: 24px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
        td, th {{ border: 1px solid #e5e7eb; padding: 8px 12px; font-size: 0.9rem; }}
        th {{ background: #f3f4f6; font-weight: 600; }}
        blockquote {{ border-left: 3px solid #6366f1; padding-left: 12px; color: #6b7280; }}
        code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }}
    </style></head><body>{html}</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 600})
        page.set_content(styled)
        page.wait_for_load_state("networkidle")
        png_bytes = page.screenshot(full_page=True)
        browser.close()

    return png_bytes


def convert_to_pptx(markdown_content: str) -> bytes:
    """Convert markdown to PPTX using Pandoc (slide per heading)."""
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as md_file:
        md_file.write(markdown_content)
        md_path = md_file.name

    out_path = md_path.replace(".md", ".pptx")
    try:
        subprocess.run(
            ["pandoc", md_path, "-o", out_path],
            check=True, capture_output=True,
        )
        return Path(out_path).read_bytes()
    finally:
        os.unlink(md_path)
        if os.path.exists(out_path):
            os.unlink(out_path)
