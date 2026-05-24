"""Round 3 gambit - run with updated local code directly."""

import json
import os
import sys
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

API = "https://api.localhost"
OUT = Path(__file__).resolve().parent / "gambit_output" / "round3"
OUT.mkdir(parents=True, exist_ok=True)

# Get rich context from indexed docs
resp = requests.post(
    API + "/search",
    json={
        "query": "roof replacement contractors quotes TPO EPDM warranty Brax All Day Roofing parapet Firestone",
        "mode": "hybrid",
        "page_size": 20,
    },
    verify=False,
    timeout=30,
)
search_results = resp.json().get("results", [])

context_parts = []
seen_docs = set()
for r in search_results:
    doc_id = r["document_id"]
    if doc_id not in seen_docs and len(seen_docs) < 8:
        seen_docs.add(doc_id)
        chunks_resp = requests.get(API + "/documents/" + doc_id + "/chunks", verify=False, timeout=10)
        if chunks_resp.status_code == 200:
            data = chunks_resp.json()
            chunks = data.get("chunks", data) if isinstance(data, dict) else data
            if isinstance(chunks, list):
                first_five = chunks[:5]
                text = "\n".join(c["content"] for c in first_five if isinstance(c, dict) and "content" in c)
            else:
                text = str(chunks)[:2000]
            title = r.get("title", "Unknown")
            context_parts.append(f"[{title}]\n{text}")

context = "\n\n---\n\n".join(context_parts)
print(f"Context: {len(context)} chars from {len(context_parts)} docs")

from app.generator import generate_markdown
from app.plantuml import render_puml_to_png
from app.pptx_builder import build_pptx, parse_enhanced_markdown

PROMPT = (
    "Create a presentation about my roof replacement options. "
    "Include the different contractors who provided quotes, their prices, "
    "materials proposed (TPO, Firestone, etc.), warranty terms, and a timeline. "
    "Include a workflow diagram showing the decision process from getting quotes "
    "to selecting a contractor to scheduling work."
)

MODELS = [
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
    "deepseek.v3.2",
    "mistral.mistral-large-2402-v1:0",
    "mistral.mistral-large-3-675b-instruct",
    "qwen.qwen3-32b-v1:0",
    "nvidia.nemotron-super-3-120b",
    "amazon.nova-micro-v1:0",
]

print("\nROUND 3 FULL GAMBIT - Updated code with mandatory diagram/notes")
print("=" * 80)

results_list = []
for model_id in MODELS:
    short = model_id.split(".")[1] if "." in model_id else model_id
    print(f"  {short:<38}", end=" ", flush=True)

    os.environ["BEDROCK_GENERATE_MODEL_ID"] = model_id

    start = time.time()
    try:
        md = generate_markdown(PROMPT, context, manual_mode=False, fmt="pptx")
        dur = time.time() - start
    except Exception as e:
        dur = time.time() - start
        print(f"ERROR ({dur:.1f}s): {e!s:.60}")
        results_list.append({"model": model_id, "error": str(e)[:100], "duration": dur})
        continue

    (OUT / f"{short}_r3.md").write_text(md)

    slides = parse_enhanced_markdown(md)
    diagrams = [s for s in slides if s.get("diagram")]
    notes_slides = [s for s in slides if s.get("notes")]
    rendered = sum(1 for s in diagrams if render_puml_to_png(s["diagram"]))

    pptx_bytes = build_pptx(slides)
    (OUT / f"{short}_r3.pptx").write_bytes(pptx_bytes)

    r = {
        "model": model_id,
        "duration": round(dur, 1),
        "slides": len(slides),
        "diagrams": len(diagrams),
        "rendered": rendered,
        "notes": len(notes_slides),
        "pptx_kb": len(pptx_bytes) // 1024,
    }

    # Score: diagrams(30) + notes coverage(30) + slide count(20) + speed(20)
    diag_score = 30 if rendered > 0 else (15 if len(diagrams) > 0 else 0)
    notes_score = int(30 * (len(notes_slides) / max(len(slides), 1)))
    slide_score = 20 if 5 <= len(slides) <= 8 else (10 if 3 <= len(slides) <= 10 else 0)
    speed_score = 20 if dur < 5 else (15 if dur < 10 else (10 if dur < 20 else 5))
    r["score"] = diag_score + notes_score + slide_score + speed_score
    results_list.append(r)

    diag_str = f"{rendered}/{len(diagrams)}"
    print(f"OK ({dur:>5.1f}s) slides:{len(slides):>2} diag:{diag_str:>3} notes:{len(notes_slides):>2} score:{r['score']:>3} {r['pptx_kb']}KB")

# Rankings
print("\n" + "=" * 80)
print("FINAL RANKINGS")
print("=" * 80)
ranked = sorted(
    [r for r in results_list if not r.get("error")],
    key=lambda x: (x["score"], -x["duration"]),
    reverse=True,
)
print(f"  {'Model':<38} {'Score':>5} {'Time':>6} {'Slides':>6} {'Diag':>5} {'Notes':>5}")
print("  " + "-" * 72)
for r in ranked:
    short = r["model"].split(".")[1]
    print(f"  {short:<38} {r['score']:>5} {r['duration']:>5.1f}s {r['slides']:>6} {r['rendered']}/{r['diagrams']:>3} {r['notes']:>5}")

(OUT / "final_results.json").write_text(json.dumps(ranked, indent=2))
print(f"\nPPTXs saved to: {OUT}/")
if ranked:
    print(f"\n🏆 BEST: {ranked[0]['model']} (score {ranked[0]['score']}, {ranked[0]['duration']}s)")
