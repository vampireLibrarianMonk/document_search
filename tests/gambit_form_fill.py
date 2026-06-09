"""Gambit: Form Field Generation — Multi-model + Multi-document-set test.

Tests which combination of (model × document set × prompt complexity) produces
the best "Description of Proposed Modification" writeup for the HOA exterior
modification application.

Ground truth: tmp/ahc_hoa_submission/description_of_proposed_modification.txt

Scoring (automated via judge model):
  - Factual accuracy /25 (correct price, dimensions, timeline vs ground truth)
  - Hallucination rate /25 (penalize mentions of things not in source docs)
  - Format compliance /25 (flowing paragraphs, first person, no headers/bullets)
  - Completeness /25 (all required fields from form directions present)

Also checks for specific required facts:
  $7,200 | 750 sq ft | black | 1 day | VA #2705190396 | LIBERTY SBS
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import boto3
import requests
import urllib3

urllib3.disable_warnings()

API = "https://api.localhost"
VERIFY = False
REGION = os.getenv("AWS_REGION", "us-east-1")
OUTPUT_DIR = Path(__file__).resolve().parent / "results" / "form_fill_gambit"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ground truth
GROUND_TRUTH = (Path(__file__).resolve().parent.parent / "tmp" / "ahc_hoa_submission" / "description_of_proposed_modification.txt").read_text()

# Required facts (must appear in output)
REQUIRED_FACTS = {
    "price_7200": r"\$?7[,.]?200",
    "area_750": r"750\s*(sq|square)",
    "color_black": r"(?i)\bblack\b",
    "timeline_1_day": r"(?i)(one\s+day|1\s+day|8\s+hour)",
    "license_va": r"2705190396",
    "liberty_sbs": r"(?i)LIBERTY.*SBS",
}

# Models to test
MODELS = [
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "mistral.magistral-small-2509",
    "meta.llama3-70b-instruct-v1:0",
    "qwen.qwen3-32b-v1:0",
    "deepseek.v3.2",
    "nvidia.nemotron-super-3-120b",
]

# Document sets to test
DOC_SETS = {
    "focused_5": {
        "description": "Only AHC docs + form (5 docs, no noise)",
        "doc_ids": ["doc_aaee35593d06", "doc_6b883a64a4d0", "doc_b866994701d3", "doc_ece84354cbb5", "doc_38cebc657b28"],
    },
    "focused_no_form": {
        "description": "AHC docs only, no form (4 docs — tests if model still formats correctly)",
        "doc_ids": ["doc_aaee35593d06", "doc_6b883a64a4d0", "doc_b866994701d3", "doc_ece84354cbb5"],
    },
    "with_arb_standards": {
        "description": "AHC docs + form + ARB Standards (6 docs — tests noise resistance)",
        "doc_ids": ["doc_aaee35593d06", "doc_6b883a64a4d0", "doc_b866994701d3", "doc_ece84354cbb5", "doc_38cebc657b28", "doc_26da506329b6"],
    },
    "kitchen_sink": {
        "description": "All roof-related docs (tests signal extraction from noise)",
        "doc_ids": ["doc_aaee35593d06", "doc_6b883a64a4d0", "doc_b866994701d3", "doc_ece84354cbb5", "doc_38cebc657b28", "doc_26da506329b6", "doc_80126e445665", "doc_183edbcecb4e", "doc_6f864ae384d9"],
    },
}

# Prompts to test (minimal → detailed)
PROMPTS = {
    "minimal": "Fill out the description of proposed modification for the exterior modification form using American Home Contractors",
    "medium": "Write the description of proposed modification section for the HOA exterior modification application using American Home Contractors GAF LIBERTY SBS system. Plain paragraphs, first person.",
    "detailed": (
        "Look at the exterior modification application form directions section. "
        "Using only the American Home Contractors documents, write 2-3 plain paragraphs for the "
        "\"Description of Proposed Modification\" box. Use the GAF LIBERTY SBS Self-Adhered 2-Ply option ($7,200). "
        "State facts only: what they will do, materials, 750 sq ft roof area, black color, 1 day install, "
        "2 weeks lead time, contractor license VA #2705190396. First person, like a homeowner explaining to a review board."
    ),
}

JUDGE_MODEL = "amazon.nova-pro-v1:0"


def get_context(doc_ids: list[str]) -> str:
    """Get concatenated document content."""
    parts = []
    for doc_id in doc_ids:
        r = requests.get(f"{API}/documents/{doc_id}/chunks", verify=VERIFY)
        if r.status_code == 200:
            data = r.json()
            chunks = data.get("chunks", [])
            text = "\n".join(c["content"] for c in chunks)
            # Get title
            r2 = requests.get(f"{API}/documents/{doc_id}", verify=VERIFY)
            title = r2.json().get("title", doc_id) if r2.status_code == 200 else doc_id
            parts.append(f"[{title}]\n{text}")
    return "\n\n---\n\n".join(parts)


def generate(model_id: str, prompt: str, context: str) -> tuple[str, float]:
    """Call Bedrock to generate the form field content. Returns (text, seconds)."""
    client = boto3.client("bedrock-runtime", region_name=REGION)

    system = (
        "You are helping a homeowner fill out an HOA Exterior Modification Application form. "
        "Write ONLY the content that goes in the form field. No headers, no markdown formatting, "
        "no bullet points. Just flowing paragraphs in first person. Use only facts from the provided documents."
    )

    user_msg = f"{prompt}\n\n--- SOURCE DOCUMENTS ---\n{context[:80000]}"

    t0 = time.time()
    try:
        resolved = model_id
        try:
            resp = client.converse(
                modelId=resolved,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user_msg}]}],
                inferenceConfig={"maxTokens": 1500},
            )
        except Exception:
            resolved = f"us.{model_id}"
            resp = client.converse(
                modelId=resolved,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user_msg}]}],
                inferenceConfig={"maxTokens": 1500},
            )
        elapsed = time.time() - t0
        return resp["output"]["message"]["content"][0]["text"], elapsed
    except Exception as e:
        return f"ERROR: {e}", time.time() - t0


def check_facts(text: str) -> dict[str, bool]:
    """Check which required facts are present."""
    return {name: bool(re.search(pattern, text)) for name, pattern in REQUIRED_FACTS.items()}


def judge_output(output: str, ground_truth: str) -> dict:
    """Use a judge model to score the output against ground truth."""
    client = boto3.client("bedrock-runtime", region_name=REGION)

    prompt = f"""Score this HOA form field writeup against the reference. Rate each criterion 0-25.

REFERENCE (ground truth):
{ground_truth}

OUTPUT TO SCORE:
{output}

CRITERIA:
1. Factual Accuracy (0-25): Are the facts correct? Price, dimensions, timeline, materials, license, color.
2. Hallucination Rate (0-25): 25 = no hallucinations. Deduct for any info not in source docs (wrong colors, wrong materials, made-up details).
3. Format Compliance (0-25): 25 = flowing paragraphs, first person, no markdown headers/bullets/tables. Deduct for structured output.
4. Completeness (0-25): Does it cover dimensions, materials, color, timeline, cost, contractor info?

Respond ONLY with JSON: {{"factual": N, "hallucination": N, "format": N, "completeness": N, "notes": "brief explanation"}}"""

    try:
        resp = client.converse(
            modelId=JUDGE_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 300},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        # Extract JSON
        match = re.search(r"\{[^}]+\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        return {"factual": 0, "hallucination": 0, "format": 0, "completeness": 0, "notes": f"Judge error: {e}"}
    return {"factual": 0, "hallucination": 0, "format": 0, "completeness": 0, "notes": "Parse error"}


def main():
    print("=" * 70)
    print("FORM FILL GAMBIT — Multi-Model × Multi-DocSet × Multi-Prompt")
    print("=" * 70)

    # Pre-load document contexts
    print("\n[1] Loading document sets...")
    contexts = {}
    for name, ds in DOC_SETS.items():
        ctx = get_context(ds["doc_ids"])
        contexts[name] = ctx
        print(f"  {name}: {len(ctx)//1000}k chars from {len(ds['doc_ids'])} docs")

    # Run the gambit
    results = []
    total_combos = len(MODELS) * len(DOC_SETS) * len(PROMPTS)
    combo_num = 0

    print(f"\n[2] Running {total_combos} combinations...")

    for model_id in MODELS:
        model_short = model_id.split(".")[1].split("-")[0] if "." in model_id else model_id[:20]
        for doc_set_name in DOC_SETS:
            for prompt_name, prompt_text in PROMPTS.items():
                combo_num += 1
                label = f"{model_short}/{doc_set_name}/{prompt_name}"
                print(f"\n  [{combo_num}/{total_combos}] {label}")

                output, elapsed = generate(model_id, prompt_text, contexts[doc_set_name])

                if output.startswith("ERROR:"):
                    print(f"    ✗ {output[:80]}")
                    results.append({
                        "model": model_id, "doc_set": doc_set_name, "prompt": prompt_name,
                        "output": output, "time_s": elapsed, "facts": {},
                        "scores": {"factual": 0, "hallucination": 0, "format": 0, "completeness": 0},
                        "total": 0, "error": True,
                    })
                    continue

                # Check facts
                facts = check_facts(output)
                facts_hit = sum(facts.values())
                print(f"    Facts: {facts_hit}/{len(REQUIRED_FACTS)} | {elapsed:.1f}s | {len(output)} chars")

                # Judge
                scores = judge_output(output, GROUND_TRUTH)
                total = scores.get("factual", 0) + scores.get("hallucination", 0) + scores.get("format", 0) + scores.get("completeness", 0)
                print(f"    Score: {total}/100 (F:{scores.get('factual',0)} H:{scores.get('hallucination',0)} Fmt:{scores.get('format',0)} C:{scores.get('completeness',0)})")

                results.append({
                    "model": model_id, "doc_set": doc_set_name, "prompt": prompt_name,
                    "output": output, "time_s": round(elapsed, 2),
                    "facts": facts, "facts_hit": facts_hit,
                    "scores": scores, "total": total, "error": False,
                })

                # Save individual output
                out_file = OUTPUT_DIR / f"{model_short}_{doc_set_name}_{prompt_name}.txt"
                with open(out_file, "w") as f:
                    f.write(output)

    # Save all results
    json_path = OUTPUT_DIR / "all_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    # Generate summary
    print(f"\n{'=' * 70}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 70}")

    # Best by total score
    valid = [r for r in results if not r.get("error")]
    valid.sort(key=lambda r: r["total"], reverse=True)

    summary_lines = [
        "# Form Fill Gambit Results",
        f"\nDate: {time.strftime('%Y-%m-%d %H:%M')}",
        f"Combinations tested: {total_combos}",
        f"Successful: {len(valid)}/{total_combos}",
        f"\n## Ground Truth",
        f"Source: tmp/ahc_hoa_submission/description_of_proposed_modification.txt",
        f"Required facts: {', '.join(REQUIRED_FACTS.keys())}",
        f"\n## Top 10 Combinations (by total score /100)\n",
        "| Rank | Model | Doc Set | Prompt | Score | Facts | Time |",
        "|------|-------|---------|--------|-------|-------|------|",
    ]

    for i, r in enumerate(valid[:10], 1):
        model_short = r["model"].split(".")[1].split("-")[0] if "." in r["model"] else r["model"][:15]
        summary_lines.append(
            f"| {i} | {model_short} | {r['doc_set']} | {r['prompt']} | {r['total']}/100 | {r['facts_hit']}/6 | {r['time_s']:.1f}s |"
        )
        print(f"  #{i}: {model_short}/{r['doc_set']}/{r['prompt']} → {r['total']}/100 ({r['facts_hit']}/6 facts) {r['time_s']:.1f}s")

    # Best per axis
    summary_lines.append(f"\n## Best Model (averaged across all doc sets and prompts)\n")
    model_avgs = {}
    for r in valid:
        model_avgs.setdefault(r["model"], []).append(r["total"])
    model_avgs_sorted = sorted(model_avgs.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True)
    summary_lines.append("| Model | Avg Score | Runs |")
    summary_lines.append("|-------|-----------|------|")
    for model, scores in model_avgs_sorted:
        avg = sum(scores) / len(scores)
        short = model.split(".")[1].split("-")[0] if "." in model else model[:15]
        summary_lines.append(f"| {short} | {avg:.1f}/100 | {len(scores)} |")

    summary_lines.append(f"\n## Best Document Set (averaged across all models and prompts)\n")
    ds_avgs = {}
    for r in valid:
        ds_avgs.setdefault(r["doc_set"], []).append(r["total"])
    ds_avgs_sorted = sorted(ds_avgs.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True)
    summary_lines.append("| Doc Set | Avg Score | Description |")
    summary_lines.append("|---------|-----------|-------------|")
    for ds, scores in ds_avgs_sorted:
        avg = sum(scores) / len(scores)
        desc = DOC_SETS[ds]["description"]
        summary_lines.append(f"| {ds} | {avg:.1f}/100 | {desc} |")

    summary_lines.append(f"\n## Best Prompt Level (averaged across all models and doc sets)\n")
    prompt_avgs = {}
    for r in valid:
        prompt_avgs.setdefault(r["prompt"], []).append(r["total"])
    prompt_avgs_sorted = sorted(prompt_avgs.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True)
    summary_lines.append("| Prompt | Avg Score | Text |")
    summary_lines.append("|--------|-----------|------|")
    for p, scores in prompt_avgs_sorted:
        avg = sum(scores) / len(scores)
        summary_lines.append(f"| {p} | {avg:.1f}/100 | {PROMPTS[p][:80]}... |")

    summary_lines.append(f"\n## Recommendations\n")
    if valid:
        best = valid[0]
        summary_lines.append(f"- **Best overall**: {best['model']} + {best['doc_set']} + {best['prompt']} ({best['total']}/100)")
        fastest = min(valid, key=lambda r: r["time_s"])
        summary_lines.append(f"- **Fastest**: {fastest['model']} ({fastest['time_s']:.1f}s, {fastest['total']}/100)")
        best_minimal = max((r for r in valid if r["prompt"] == "minimal"), key=lambda r: r["total"], default=None)
        if best_minimal:
            summary_lines.append(f"- **Best with minimal prompt**: {best_minimal['model']} + {best_minimal['doc_set']} ({best_minimal['total']}/100)")

    summary_text = "\n".join(summary_lines)
    summary_path = OUTPUT_DIR / "summary.md"
    with open(summary_path, "w") as f:
        f.write(summary_text)
    print(f"\n  Summary: {summary_path}")
    print(f"  Raw data: {json_path}")


if __name__ == "__main__":
    main()
