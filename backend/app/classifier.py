"""Auto-classify documents using LLM.

Sends document text to Bedrock and asks it to pick or create a category.
Learns from existing categories in the database so the taxonomy grows organically.
Falls back to "Uncategorized" if Bedrock is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_bedrock = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        import boto3
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    return _bedrock


def _get_existing_categories() -> list[str]:
    """Pull distinct categories from the database."""
    try:
        from .db import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT category FROM documents WHERE category IS NOT NULL AND category != 'Uncategorized' ORDER BY category")
                return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


def classify_document(filename: str, text: str) -> tuple[str, str, list[str], str]:
    """Classify a document and return (category, document_type, tags, suggested_title).

    Uses Bedrock to determine category and type based on content.
    Falls back to Uncategorized if the LLM call fails.
    """
    model_id = os.getenv("BEDROCK_CLASSIFY_MODEL_ID", "") or os.getenv("BEDROCK_MODEL_ID", "")
    if not model_id:
        return "Uncategorized", "general", ["general"], ""

    existing = _get_existing_categories()
    probe_text = text[:2000]

    categories_hint = ""
    if existing:
        categories_hint = f"\n\nExisting categories in this collection: {json.dumps(existing)}\nUse one of these if the document clearly fits. Create a new category if none are a good match. Be precise — do not lump unrelated services together (e.g. HVAC repair is not Vehicle Maintenance)."

    prompt = (
        f"Classify this document. Return ONLY a JSON object with these fields:\n"
        f"- \"category\": a short human-readable group name that describes the domain (e.g. \"Home Maintenance\", \"Medical Records\", \"Tax & Legal\", \"Vehicle Maintenance\"). Choose based on the actual subject matter of the document, not just the document format.\n"
        f"- \"document_type\": a snake_case type (e.g. \"invoice\", \"estimate\", \"proposal\", \"inspection_report\", \"insurance_policy\")\n"
        f"- \"tags\": a list of 1-3 relevant keyword tags\n"
        f"- \"title\": a clear, descriptive title for this document (e.g. \"HVAC Ductwork Repair Estimate - Reddick & Sons\" or \"Q1 2024 HOA Budget Report\"). Make it specific enough to distinguish from similar documents.\n"
        f"\nImportant distinctions:\n"
        f"- \"Appraisal\" means a professional property valuation (market value, comparable sales). Do NOT use it for contractor estimates, proposals, or quotes.\n"
        f"- Contractor estimates, proposals, and quotes for future work belong in \"Home Maintenance\" or a similar service category, with document_type like \"estimate\" or \"proposal\".\n"
        f"{categories_hint}\n\n"
        f"Filename: {filename}\n\n"
        f"Document text (first 2000 chars):\n{probe_text}"
    )

    try:
        resp = _get_bedrock().converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 256},
        )
        raw = resp["output"]["message"]["content"][0]["text"]

        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if not json_match:
            return "Uncategorized", "general", ["general"]

        result = json.loads(json_match.group())
        category = result.get("category", "Uncategorized")
        doc_type = result.get("document_type", "general")
        tags = result.get("tags", [doc_type])
        title = result.get("title", "")

        # Normalize
        if not category or category.lower() == "uncategorized":
            category = "Uncategorized"
        doc_type = re.sub(r"[^a-z0-9_]", "_", doc_type.lower().strip())
        tags = [str(t).lower().strip() for t in tags if t][:5]

        # Track usage
        if os.getenv("TRACK_USAGE", "true").lower() == "true":
            try:
                from .pg_store import PgStore
                from .pricing import estimate_cost
                usage = resp.get("usage", {})
                store = PgStore()
                store.log_usage(
                    model_id=model_id,
                    operation="classify",
                    input_tokens=usage.get("inputTokens", 0),
                    output_tokens=usage.get("outputTokens", 0),
                    cost=estimate_cost(model_id, usage.get("inputTokens", 0), usage.get("outputTokens", 0), os.getenv("AWS_REGION", "us-east-1")),
                )
            except Exception:
                pass

        return category, doc_type, tags, title

    except Exception as e:
        logger.warning("LLM classification failed, falling back to Uncategorized: %s", e)
        return "Uncategorized", "general", ["general"], ""
