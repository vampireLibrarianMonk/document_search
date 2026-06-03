"""Benchmark text generation models for Template Extraction task.

Tests each model's ability to produce valid, schema-compliant JSON describing
document structure (layout, sections, fonts, fillable fields).
"""

import json
import time
import sys
from pathlib import Path

import boto3

REGION = "us-east-1"
OUTPUT_PATH = Path(__file__).parent / "benchmark_results" / "template_extract_benchmark.txt"

MODELS = [
    "amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-pro-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "mistral.magistral-small-2509",
    "meta.llama3-70b-instruct-v1:0",
    "qwen.qwen3-32b-v1:0",
    "deepseek.v3.2",
    "nvidia.nemotron-super-3-120b",
    "zai.glm-5",
]

TEMPLATES = {
    "academic_thesis": (
        "TITLE PAGE\n[Title: _____________]\n[Author: _____________]\n"
        "[Date: _____________]\n\nTABLE OF CONTENTS\n1. Introduction\n"
        "2. Literature Review\n3. Methodology\n4. Results\n5. Conclusion\n\n"
        "BIBLIOGRAPHY\n[References listed in APA format]\n\n"
        "Font: Times New Roman 12pt. Margins: 1 inch all sides. Double-spaced."
    ),
    "hoa_modification_app": (
        "EXTERIOR MODIFICATION APPLICATION\n"
        "Homeowner Name: _____________\nAddress: _____________\n"
        "Date: _____________\n\n"
        "Modification Type: [ ] Fence [ ] Shed [ ] Paint [ ] Landscaping [ ] Other: ____\n\n"
        "Description of Proposed Change:\n"
        "_____________________________________________\n"
        "_____________________________________________\n\n"
        "Estimated Start Date: _____________\n"
        "Estimated Completion Date: _____________\n\n"
        "Owner Signature: _____________  Date: _____________\n\n"
        "FOR COMMITTEE USE ONLY\n"
        "Approved: [ ] Yes [ ] No\n"
        "Committee Member: _____________  Date: _____________\n"
        "Comments: _____________________________________________"
    ),
}

# Expected sections per template for scoring
EXPECTED_SECTIONS = {
    "academic_thesis": ["title page", "table of contents", "introduction", "literature review",
                        "methodology", "results", "conclusion", "bibliography"],
    "hoa_modification_app": ["exterior modification application", "modification type",
                             "description", "dates", "signature", "committee use"],
}

# Expected fillable fields per template
EXPECTED_FIELDS = {
    "academic_thesis": ["title", "author", "date"],
    "hoa_modification_app": ["homeowner name", "address", "date", "modification type",
                             "description", "start date", "completion date",
                             "owner signature", "approved", "committee member", "comments"],
}


def build_prompt(template_text: str) -> str:
    """Build the same prompt used in _bedrock_extract_structure."""
    return f"""Analyze this document and extract its COMPLETE structure including formatting, layout, and text placement.

The text below includes metadata markers in brackets like [THEME FONTS:...], [PAGE SIZE:...], [MARGINS:...], [DEFAULT SIZE:...], [FONTS USED:...], style names in [StyleName], and formatting in (size, bold, italic, font:name).

Return a JSON object with this exact schema:
{{
  "type": "form" | "report" | "presentation" | "document",
  "title": "document title",
  "fonts": {{
    "heading_font": "font family name for headings",
    "body_font": "font family name for body text",
    "default_size_pt": 12
  }},
  "page_layout": {{
    "size": "8.5x11" or "A4" etc,
    "margins": {{"top": 0.75, "bottom": 0.44, "left": 1.5, "right": 1.5}},
    "orientation": "portrait" | "landscape"
  }},
  "sections": [
    {{
      "heading": "section heading or empty string",
      "level": 1,
      "style": "style name if known",
      "elements": [
        {{"type": "paragraph", "text": "actual text content", "style": "normal|bold|italic|centered", "font_size_pt": 12}},
        {{"type": "heading", "text": "heading text", "level": 1, "font_size_pt": 16, "bold": true}},
        {{"type": "field", "label": "field label"}},
        {{"type": "checkbox", "label": "checkbox text"}},
        {{"type": "bullet", "text": "bullet point text"}},
        {{"type": "table_header", "columns": ["col1", "col2"]}},
        {{"type": "table_row", "cells": ["cell1", "cell2"]}},
        {{"type": "signature_line"}},
        {{"type": "page_break"}},
        {{"type": "note", "text": "footnote or annotation"}}
      ]
    }}
  ],
  "source_format": "txt",
  "page_count": null,
  "formatting": {{
    "has_headers_footers": true/false,
    "has_page_numbers": true/false,
    "has_table_of_contents": true/false,
    "layout": "single_column" | "two_column" | "mixed"
  }}
}}

Capture section headings and structure. For tables, show only column headers and row count. For long paragraphs, truncate to first 50 chars. Keep response under 3000 tokens.

Document content:
{template_text}"""


def call_model(client, model_id: str, prompt: str) -> tuple[str, float]:
    """Call a model and return (response_text, latency_seconds)."""
    max_tokens = 2048 if "llama" in model_id.lower() else 4096
    start = time.time()
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    latency = time.time() - start
    return resp["output"]["message"]["content"][0]["text"], latency


def check_json_valid(text: str) -> tuple[bool, dict | None]:
    """Try to extract and parse JSON from response text."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end])
            return True, obj
        except json.JSONDecodeError:
            pass
    return False, None


def check_schema(obj: dict) -> dict[str, bool]:
    """Check which top-level schema fields are present."""
    return {
        "sections": isinstance(obj.get("sections"), list) and len(obj["sections"]) > 0,
        "fonts": isinstance(obj.get("fonts"), dict),
        "page_layout": isinstance(obj.get("page_layout"), dict),
        "fillable_fields": (
            # Fields can be in sections as elements with type "field" or "checkbox"
            any(
                any(e.get("type") in ("field", "checkbox", "signature_line")
                    for e in s.get("elements", []))
                for s in obj.get("sections", [])
            )
            # Or as a top-level fillable_fields key
            or isinstance(obj.get("fillable_fields"), list)
        ),
    }


def score_sections(obj: dict, template_key: str) -> int:
    """Score section detection 0-5."""
    expected = EXPECTED_SECTIONS[template_key]
    found_headings = []
    for s in obj.get("sections", []):
        h = (s.get("heading") or s.get("title") or "").lower()
        found_headings.append(h)
        # Also check elements for heading-type entries
        for e in s.get("elements", []):
            if e.get("type") == "heading":
                found_headings.append((e.get("text") or "").lower())

    all_text = " ".join(found_headings)
    matches = sum(1 for exp in expected if any(exp in h for h in found_headings) or exp in all_text)
    ratio = matches / len(expected)
    return min(5, round(ratio * 5))


def score_fields(obj: dict, template_key: str) -> int:
    """Score field detection 0-5."""
    expected = EXPECTED_FIELDS[template_key]
    found_labels = []
    for s in obj.get("sections", []):
        for e in s.get("elements", []):
            if e.get("type") in ("field", "checkbox", "signature_line"):
                found_labels.append((e.get("label") or "").lower())
    # Also check top-level fillable_fields
    for f in obj.get("fillable_fields", []):
        found_labels.append((f.get("label") or f.get("name") or "").lower())

    all_labels = " ".join(found_labels)
    matches = sum(1 for exp in expected if any(exp in l for l in found_labels) or exp in all_labels)
    ratio = matches / len(expected)
    return min(5, round(ratio * 5))


def run_benchmark():
    client = boto3.client("bedrock-runtime", region_name=REGION)
    results = []

    for model_id in MODELS:
        model_results = {"model": model_id, "tests": []}
        print(f"\n{'='*60}")
        print(f"Testing: {model_id}")
        print(f"{'='*60}")

        for tpl_key, tpl_text in TEMPLATES.items():
            prompt = build_prompt(tpl_text)
            print(f"  Template: {tpl_key}...", end=" ", flush=True)

            try:
                resp_text, latency = call_model(client, model_id, prompt)
                json_valid, obj = check_json_valid(resp_text)

                if json_valid and obj:
                    schema = check_schema(obj)
                    sec_score = score_sections(obj, tpl_key)
                    field_score = score_fields(obj, tpl_key)
                else:
                    schema = {"sections": False, "fonts": False, "page_layout": False, "fillable_fields": False}
                    sec_score = 0
                    field_score = 0

                test_result = {
                    "template": tpl_key,
                    "json_valid": json_valid,
                    "schema": schema,
                    "section_score": sec_score,
                    "field_score": field_score,
                    "latency": latency,
                    "error": None,
                }
                print(f"JSON={'✓' if json_valid else '✗'} Sec={sec_score}/5 Fields={field_score}/5 {latency:.1f}s")

            except Exception as e:
                test_result = {
                    "template": tpl_key,
                    "json_valid": False,
                    "schema": {"sections": False, "fonts": False, "page_layout": False, "fillable_fields": False},
                    "section_score": 0,
                    "field_score": 0,
                    "latency": 0,
                    "error": str(e),
                }
                print(f"ERROR: {e}")

            model_results["tests"].append(test_result)

        results.append(model_results)

    return results


def compute_scores(results: list) -> list[dict]:
    """Compute aggregate scores per model."""
    scored = []
    for r in results:
        tests = r["tests"]
        n = len(tests)
        if n == 0:
            continue

        json_pass = sum(1 for t in tests if t["json_valid"])
        schema_pass = sum(
            sum(t["schema"].values()) for t in tests
        )
        max_schema = n * 4  # 4 schema checks per test
        sec_total = sum(t["section_score"] for t in tests)
        field_total = sum(t["field_score"] for t in tests)
        avg_latency = sum(t["latency"] for t in tests) / max(1, sum(1 for t in tests if t["latency"] > 0))
        errors = sum(1 for t in tests if t["error"])

        # Composite score: JSON validity (20%) + schema (20%) + sections (30%) + fields (30%)
        json_pct = json_pass / n
        schema_pct = schema_pass / max_schema
        sec_pct = sec_total / (n * 5)
        field_pct = field_total / (n * 5)
        composite = (json_pct * 20 + schema_pct * 20 + sec_pct * 30 + field_pct * 30)

        scored.append({
            "model": r["model"],
            "composite": composite,
            "json_pass": f"{json_pass}/{n}",
            "schema_pct": f"{schema_pct*100:.0f}%",
            "section_avg": f"{sec_total/n:.1f}/5",
            "field_avg": f"{field_total/n:.1f}/5",
            "avg_latency": avg_latency,
            "errors": errors,
            "tests": tests,
        })

    scored.sort(key=lambda x: x["composite"], reverse=True)
    return scored


def format_results(scored: list) -> str:
    """Format results as a readable text report."""
    lines = []
    lines.append("=" * 80)
    lines.append("TEMPLATE EXTRACTION MODEL BENCHMARK")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Task: Extract structured JSON from document templates")
    lines.append("Expected output: {page_layout, fonts, sections, fillable_fields}")
    lines.append(f"Models tested: {len(scored)}")
    lines.append(f"Templates: academic_thesis, hoa_modification_app")
    lines.append("")
    lines.append("-" * 80)
    lines.append(f"{'Rank':<5}{'Model':<42}{'Score':<8}{'JSON':<7}{'Schema':<9}{'Sec':<7}{'Fields':<9}{'Latency':<8}{'Err'}")
    lines.append("-" * 80)

    for i, s in enumerate(scored, 1):
        lines.append(
            f"{i:<5}{s['model']:<42}{s['composite']:<8.1f}{s['json_pass']:<7}"
            f"{s['schema_pct']:<9}{s['section_avg']:<7}{s['field_avg']:<9}"
            f"{s['avg_latency']:<8.1f}{s['errors']}"
        )

    lines.append("-" * 80)
    lines.append("")
    lines.append("Scoring breakdown:")
    lines.append("  Composite = JSON validity (20%) + Schema compliance (20%) + Section detection (30%) + Field detection (30%)")
    lines.append("  JSON: valid parseable JSON output (pass/fail per template)")
    lines.append("  Schema: has sections, fonts, page_layout, fillable_fields (4 checks per template)")
    lines.append("  Sections: correctly identified document sections (0-5 per template)")
    lines.append("  Fields: correctly identified fillable fields, checkboxes, signatures (0-5 per template)")
    lines.append("  Latency: average response time in seconds")
    lines.append("")

    # Detail per model
    lines.append("=" * 80)
    lines.append("DETAILED RESULTS")
    lines.append("=" * 80)

    for s in scored:
        lines.append("")
        lines.append(f"{'─'*60}")
        lines.append(f"Model: {s['model']}")
        lines.append(f"Composite Score: {s['composite']:.1f}/100")
        lines.append(f"{'─'*60}")
        for t in s["tests"]:
            lines.append(f"  Template: {t['template']}")
            if t["error"]:
                lines.append(f"    ERROR: {t['error']}")
            else:
                lines.append(f"    JSON Valid: {'Yes' if t['json_valid'] else 'No'}")
                lines.append(f"    Schema: sections={'✓' if t['schema']['sections'] else '✗'} "
                             f"fonts={'✓' if t['schema']['fonts'] else '✗'} "
                             f"page_layout={'✓' if t['schema']['page_layout'] else '✗'} "
                             f"fillable_fields={'✓' if t['schema']['fillable_fields'] else '✗'}")
                lines.append(f"    Section Score: {t['section_score']}/5")
                lines.append(f"    Field Score: {t['field_score']}/5")
                lines.append(f"    Latency: {t['latency']:.2f}s")

    lines.append("")
    lines.append("=" * 80)
    if scored:
        lines.append(f"RECOMMENDATION: {scored[0]['model']}")
        lines.append(f"  Best overall for template extraction with composite score {scored[0]['composite']:.1f}/100")
        if len(scored) > 1:
            # Find fastest among top scorers (within 10 points of best)
            top_tier = [s for s in scored if s["composite"] >= scored[0]["composite"] - 10]
            fastest = min(top_tier, key=lambda x: x["avg_latency"])
            if fastest["model"] != scored[0]["model"]:
                lines.append(f"  Fastest in top tier: {fastest['model']} ({fastest['avg_latency']:.1f}s, score {fastest['composite']:.1f})")
    lines.append("=" * 80)

    return "\n".join(lines)


if __name__ == "__main__":
    print("Starting Template Extraction Model Benchmark...")
    print(f"Region: {REGION}")
    print(f"Models: {len(MODELS)}")
    print()

    results = run_benchmark()
    scored = compute_scores(results)
    report = format_results(scored)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report)

    print("\n\n")
    print(report)
    print(f"\nResults saved to: {OUTPUT_PATH}")
