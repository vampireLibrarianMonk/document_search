"""Model gambit: run the same PPTX generation prompt across multiple models.

Evaluates each model on:
  1. Format compliance (correct markdown structure for slides)
  2. Diagram generation (valid PlantUML in ```plantuml blocks)
  3. Speaker notes (<!-- notes: ... --> present)
  4. Content quality (grounded in source documents)
  5. Slide count and bullet density

Outputs scored results and saves each PPTX for manual review.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

API_BASE = "https://api.localhost"
VERIFY_SSL = False
OUTPUT_DIR = Path(__file__).resolve().parent / "gambit_output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Models to test — broad sweep across families
CANDIDATE_MODELS = [
    # Tier 1: Expected best performers for structured output
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
    # Tier 2: Strong contenders
    "deepseek.v3.2",
    "mistral.mistral-large-3-675b-instruct",
    "mistral.mistral-large-2402-v1:0",
    # Tier 3: Mid-range / value
    "meta.llama3-70b-instruct-v1:0",
    "qwen.qwen3-32b-v1:0",
    "nvidia.nemotron-super-3-120b",
    # Tier 4: Smaller / cheaper
    "amazon.nova-micro-v1:0",
    "mistral.ministral-3-8b-instruct",
]

# The test prompt — asks for a presentation about roof replacement options
# grounded in the actual indexed documents
TEST_PROMPT = (
    "Create a presentation about my roof replacement options. "
    "Include the different contractors who provided quotes, their prices, "
    "materials proposed (TPO, Firestone, etc.), warranty terms, and a timeline. "
    "Include a workflow diagram showing the decision process from getting quotes "
    "to selecting a contractor to scheduling work."
)


def score_markdown(markdown: str, model_id: str) -> dict:
    """Score the generated markdown for PPTX quality."""
    from app.pptx_builder import parse_enhanced_markdown
    from app.plantuml import render_puml_to_png

    scores = {
        "model": model_id,
        "total_chars": len(markdown),
        "has_title_slide": markdown.strip().startswith("# "),
        "slide_count": 0,
        "has_diagrams": False,
        "diagram_count": 0,
        "diagrams_render": 0,
        "has_notes": False,
        "notes_count": 0,
        "bullet_count": 0,
        "format_score": 0,  # 0-100
        "content_score": 0,  # 0-100
        "errors": [],
    }

    # Parse
    try:
        slides = parse_enhanced_markdown(markdown)
        scores["slide_count"] = len(slides)
    except Exception as e:
        scores["errors"].append(f"Parse error: {e}")
        return scores

    # Count features
    for s in slides:
        if s.get("diagram"):
            scores["diagram_count"] += 1
        if s.get("notes"):
            scores["notes_count"] += 1
        scores["bullet_count"] += len(s.get("bullets", []))

    scores["has_diagrams"] = scores["diagram_count"] > 0
    scores["has_notes"] = scores["notes_count"] > 0

    # Test diagram rendering
    for s in slides:
        if s.get("diagram"):
            png = render_puml_to_png(s["diagram"])
            if png:
                scores["diagrams_render"] += 1

    # Format score (0-100)
    fmt = 0
    if scores["has_title_slide"]:
        fmt += 15
    if 4 <= scores["slide_count"] <= 10:
        fmt += 20
    elif scores["slide_count"] >= 3:
        fmt += 10
    if scores["has_diagrams"]:
        fmt += 25
    if scores["diagrams_render"] == scores["diagram_count"] and scores["diagram_count"] > 0:
        fmt += 15  # All diagrams render successfully
    elif scores["diagrams_render"] > 0:
        fmt += 8
    if scores["has_notes"]:
        fmt += 15
    if scores["notes_count"] >= scores["slide_count"] * 0.5:
        fmt += 10  # Notes on most slides
    scores["format_score"] = min(fmt, 100)

    # Content score (0-100) — check for grounding in actual documents
    content = 0
    md_lower = markdown.lower()
    # Check for contractor names from the indexed docs
    if "brax" in md_lower:
        content += 15
    if "all day roofing" in md_lower or "all day" in md_lower:
        content += 15
    if "reddick" in md_lower:
        content += 10
    # Check for materials
    if "tpo" in md_lower:
        content += 10
    if "firestone" in md_lower:
        content += 10
    # Check for pricing/numbers
    if "$" in markdown:
        content += 15
    # Check for warranty
    if "warranty" in md_lower:
        content += 10
    # Check for specific details
    if "parapet" in md_lower:
        content += 10
    if "tribune" in md_lower:
        content += 5
    scores["content_score"] = min(content, 100)

    return scores


def run_generation(model_id: str) -> tuple[str | None, float, str]:
    """Call the API to generate a PPTX-formatted markdown. Returns (markdown, duration, error)."""
    # First, update the model config
    try:
        requests.put(
            f"{API_BASE}/admin/config",
            json={"BEDROCK_GENERATE_MODEL_ID": model_id},
            verify=VERIFY_SSL,
            timeout=10,
        )
    except Exception as e:
        return None, 0, f"Config update failed: {e}"

    # Generate
    start = time.time()
    try:
        resp = requests.post(
            f"{API_BASE}/generate",
            json={
                "prompt": TEST_PROMPT,
                "format": "pptx",
                "top_k": 10,
            },
            verify=VERIFY_SSL,
            timeout=120,
        )
        duration = time.time() - start

        if resp.status_code != 200:
            return None, duration, f"HTTP {resp.status_code}: {resp.text[:200]}"

        data = resp.json()
        return data.get("markdown", ""), duration, ""
    except requests.Timeout:
        return None, time.time() - start, "Timeout (120s)"
    except Exception as e:
        return None, time.time() - start, str(e)


def run_gambit():
    """Run all models and produce comparison."""
    print("=" * 80)
    print("PPTX GENERATION MODEL GAMBIT")
    print(f"Prompt: {TEST_PROMPT[:80]}...")
    print(f"Models: {len(CANDIDATE_MODELS)}")
    print("=" * 80)
    print()

    results = []

    for i, model_id in enumerate(CANDIDATE_MODELS, 1):
        short_name = model_id.split(".")[1] if "." in model_id else model_id
        print(f"[{i}/{len(CANDIDATE_MODELS)}] {short_name}...", end=" ", flush=True)

        markdown, duration, error = run_generation(model_id)

        if error:
            print(f"FAILED ({duration:.1f}s) - {error}")
            results.append({
                "model": model_id,
                "error": error,
                "duration": duration,
                "format_score": 0,
                "content_score": 0,
            })
            continue

        # Score it
        scores = score_markdown(markdown, model_id)
        scores["duration"] = duration

        # Save markdown
        md_path = OUTPUT_DIR / f"{short_name}.md"
        md_path.write_text(markdown, encoding="utf-8")

        # Build PPTX
        try:
            from app.pptx_builder import build_pptx, parse_enhanced_markdown
            slides = parse_enhanced_markdown(markdown)
            pptx_bytes = build_pptx(slides)
            pptx_path = OUTPUT_DIR / f"{short_name}.pptx"
            pptx_path.write_bytes(pptx_bytes)
            scores["pptx_size"] = len(pptx_bytes)
        except Exception as e:
            scores["errors"].append(f"PPTX build failed: {e}")
            scores["pptx_size"] = 0

        results.append(scores)

        # Print summary
        total = scores["format_score"] + scores["content_score"]
        diag_status = f"{scores['diagrams_render']}/{scores['diagram_count']}" if scores["diagram_count"] > 0 else "none"
        print(
            f"OK ({duration:.1f}s) | "
            f"fmt:{scores['format_score']} content:{scores['content_score']} total:{total} | "
            f"slides:{scores['slide_count']} diagrams:{diag_status} notes:{scores['notes_count']}"
        )

    # Summary
    print()
    print("=" * 80)
    print("RESULTS RANKED BY TOTAL SCORE")
    print("=" * 80)
    print(f"{'Model':<45} {'Fmt':>4} {'Cnt':>4} {'Tot':>4} {'Time':>5} {'Slides':>6} {'Diag':>5} {'Notes':>5}")
    print("-" * 80)

    ranked = sorted(results, key=lambda r: r.get("format_score", 0) + r.get("content_score", 0), reverse=True)
    for r in ranked:
        model = r["model"].split(".")[1] if "." in r["model"] else r["model"]
        if r.get("error"):
            print(f"{model:<45} {'ERR':>4} {'ERR':>4} {'ERR':>4} {r['duration']:>4.1f}s  {r['error'][:30]}")
        else:
            total = r["format_score"] + r["content_score"]
            diag = f"{r.get('diagrams_render', 0)}/{r.get('diagram_count', 0)}"
            print(
                f"{model:<45} {r['format_score']:>4} {r['content_score']:>4} {total:>4} "
                f"{r['duration']:>4.1f}s {r.get('slide_count', 0):>6} {diag:>5} {r.get('notes_count', 0):>5}"
            )

    # Save full results
    results_path = OUTPUT_DIR / "gambit_results.json"
    results_path.write_text(json.dumps(ranked, indent=2, default=str), encoding="utf-8")
    print(f"\nFull results: {results_path}")
    print(f"PPTX files: {OUTPUT_DIR}/")

    # Identify winner
    if ranked and not ranked[0].get("error"):
        winner = ranked[0]
        print(f"\n🏆 WINNER: {winner['model']}")
        print(f"   Format: {winner['format_score']}/100, Content: {winner['content_score']}/100")
        print(f"   {winner.get('slide_count', 0)} slides, {winner.get('diagram_count', 0)} diagrams, {winner.get('notes_count', 0)} notes")


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    run_gambit()
