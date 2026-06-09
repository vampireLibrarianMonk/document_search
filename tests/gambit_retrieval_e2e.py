"""Gambit: Retrieval + Generation End-to-End

Tests the full Tasks tab pipeline: given ONLY a prompt (no pre-selected docs),
does the app find the right documents via embedding search AND produce a good writeup?

This tests the entire chain:
  1. Hybrid search (BM25 + kNN embeddings) finds candidate docs
  2. Entity extraction + initials search expands coverage
  3. User "confirms all" (simulating clicking Generate with all found docs checked)
  4. Generation model produces the form field content

Measures:
  - Retrieval recall: did it find the required AHC documents?
  - Retrieval precision: what % of found docs are actually relevant?
  - Generation quality: same 100-point judged score as gambit_form_fill.py
  - End-to-end time: search + generate combined

Compares prompt variations to see which wording yields the best retrieval.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

API = "https://api.localhost"
VERIFY = False
OUTPUT_DIR = Path(__file__).resolve().parent / "results" / "retrieval_e2e_gambit"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Documents that MUST be found for a successful retrieval
REQUIRED_DOCS = {
    "doc_aaee35593d06": "AHC Flat Roof Replacement Proposal",
    "doc_6b883a64a4d0": "Jacob Estes Email 1 (dimensions, black, 2 weeks, 1 day)",
    "doc_b866994701d3": "Jacob Estes Email 2 (1 work day = 8 hours)",
    "doc_ece84354cbb5": "AHC Roof Dimensions (750 sq ft aerial report)",
    "doc_38cebc657b28": "Exterior Modification Application (the form)",
}

# Documents that are ACCEPTABLE but not required
ACCEPTABLE_DOCS = {
    "doc_80126e445665": "AHC Repair Estimate ($2,850 — separate scope)",
    "doc_26da506329b6": "ARB Standards (context, not vendor-specific)",
}

# Documents that should NOT appear (noise / wrong vendor)
NOISE_DOCS = {
    "doc_6f864ae384d9": "Brax Roofing quote (wrong vendor)",
    "doc_707cc5dde5df": "Brax email (wrong vendor)",
    "doc_183edbcecb4e": "All Day Roofing proposal (wrong vendor)",
    "doc_57d1c14cee79": "Virginia Roofing proposal (wrong vendor)",
}

# Prompts to test (simulating what a user would actually type)
PROMPTS = {
    "natural": "Fill out the description of proposed modification for the exterior modification form using American Home Contractors",
    "with_system": "Write the description of proposed modification for the HOA exterior modification application using American Home Contractors GAF LIBERTY SBS system",
    "conversational": "I need to fill out my HOA form for the roof replacement. The contractor is American Home Contractors and I'm going with the LIBERTY SBS option.",
    "minimal": "American Home Contractors roof replacement HOA application",
    "detailed": (
        "Look at the exterior modification application form. Using American Home Contractors "
        "documents (their proposal, emails from Jacob Estes, and roof dimensions), write the "
        "Description of Proposed Modification section using the GAF LIBERTY SBS Self-Adhered 2-Ply option."
    ),
}


def simulate_frontend_search(prompt: str) -> dict:
    """Simulate the Tasks tab 'Find Documents' step exactly as the frontend does it.
    
    Replicates: primary search + entity extraction + initials search.
    Returns found doc_ids, timing, and metadata.
    """
    t0 = time.time()
    seen = set()
    found = []

    # Step 1: Primary search on full prompt
    r = requests.post(f"{API}/search", json={"query": prompt, "mode": "hybrid", "page": 1, "page_size": 20}, verify=VERIFY)
    for res in r.json().get("results", []):
        if res["document_id"] not in seen:
            seen.add(res["document_id"])
            found.append({"document_id": res["document_id"], "title": res["title"], "score": res["score"]})

    # Step 2: Entity extraction (capitalized multi-word phrases)
    entities = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", prompt)
    searches = []
    for entity in entities:
        searches.append(entity)
        searches.append(f"{entity} email correspondence reply")
        initials = "".join(w[0] for w in entity.split())
        if len(initials) >= 2:
            searches.append(f"{initials} project")

    # Step 3: Follow-up searches
    for q in searches:
        r2 = requests.post(f"{API}/search", json={"query": q, "mode": "hybrid", "page": 1, "page_size": 15}, verify=VERIFY)
        for res in r2.json().get("results", []):
            if res["document_id"] not in seen:
                seen.add(res["document_id"])
                found.append({"document_id": res["document_id"], "title": res["title"], "score": res["score"]})

    elapsed = time.time() - t0
    return {"docs": found, "doc_ids": [d["document_id"] for d in found], "time_s": round(elapsed, 2)}


def score_retrieval(found_ids: list[str]) -> dict:
    """Score retrieval quality."""
    found_set = set(found_ids)

    required_found = {doc_id: doc_id in found_set for doc_id in REQUIRED_DOCS}
    noise_found = {doc_id: doc_id in found_set for doc_id in NOISE_DOCS}

    recall = sum(required_found.values()) / len(REQUIRED_DOCS)
    noise_count = sum(noise_found.values())
    precision_relevant = sum(1 for d in found_ids if d in REQUIRED_DOCS or d in ACCEPTABLE_DOCS)
    precision = precision_relevant / len(found_ids) if found_ids else 0

    return {
        "recall": round(recall, 2),
        "precision": round(precision, 2),
        "required_found": required_found,
        "required_hit": sum(required_found.values()),
        "required_total": len(REQUIRED_DOCS),
        "noise_found": noise_found,
        "noise_count": noise_count,
        "total_docs_returned": len(found_ids),
    }


def run_generation(prompt: str, doc_ids: list[str]) -> tuple[str, float]:
    """Run the tasks/generate endpoint with skip_auto_search."""
    t0 = time.time()
    r = requests.post(f"{API}/tasks/generate", json={
        "prompt": prompt,
        "document_ids": doc_ids,
        "history": [],
        "format": "md",
        "skip_auto_search": True,
    }, verify=VERIFY, stream=True, timeout=120)

    result = ""
    for line in r.iter_lines(decode_unicode=True):
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                if data.get("result"):
                    result = data["result"]["markdown"]
            except (json.JSONDecodeError, KeyError):
                pass

    return result, round(time.time() - t0, 2)


def check_facts(text: str) -> dict[str, bool]:
    """Check required facts in generated output."""
    facts = {
        "price_7200": bool(re.search(r"\$?7[,.]?200", text)),
        "area_750": bool(re.search(r"750\s*(sq|square)", text)),
        "color_black": bool(re.search(r"(?i)\bblack\b", text)),
        "timeline_1_day": bool(re.search(r"(?i)(one\s+day|1\s+day|8\s+hour)", text)),
        "license_va": bool(re.search(r"2705190396", text)),
        "liberty_sbs": bool(re.search(r"(?i)LIBERTY.*SBS", text)),
    }
    return facts


def main():
    print("=" * 70)
    print("RETRIEVAL + GENERATION END-TO-END GAMBIT")
    print("=" * 70)

    results = []

    for prompt_name, prompt_text in PROMPTS.items():
        print(f"\n{'─' * 70}")
        print(f"Prompt: [{prompt_name}]")
        print(f"  \"{prompt_text[:80]}...\"")

        # Step 1: Retrieval
        retrieval = simulate_frontend_search(prompt_text)
        retrieval_score = score_retrieval(retrieval["doc_ids"])
        print(f"  Retrieval: {retrieval_score['required_hit']}/{retrieval_score['required_total']} required docs, "
              f"{retrieval_score['noise_count']} noise, {retrieval['time_s']}s")
        for doc_id, found in retrieval_score["required_found"].items():
            status = "✅" if found else "❌"
            print(f"    {status} {REQUIRED_DOCS[doc_id]}")

        # Step 2: Generation (using only the found docs)
        gen_text, gen_time = run_generation(prompt_text, retrieval["doc_ids"])
        facts = check_facts(gen_text)
        facts_hit = sum(facts.values())
        print(f"  Generation: {facts_hit}/6 facts, {gen_time}s, {len(gen_text)} chars")

        results.append({
            "prompt_name": prompt_name,
            "prompt_text": prompt_text,
            "retrieval": {
                "docs_found": len(retrieval["doc_ids"]),
                "time_s": retrieval["time_s"],
                **retrieval_score,
            },
            "generation": {
                "text": gen_text,
                "time_s": gen_time,
                "facts": facts,
                "facts_hit": facts_hit,
                "chars": len(gen_text),
            },
            "total_time_s": round(retrieval["time_s"] + gen_time, 2),
        })

    # Save results
    json_path = OUTPUT_DIR / "all_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Summary
    summary_lines = [
        "# Retrieval + Generation End-to-End Results",
        f"\nDate: {time.strftime('%Y-%m-%d %H:%M')}",
        f"Model: NVIDIA Nemotron Super (default task model)",
        f"Embedding: Amazon Titan Embed Text v2 (hybrid BM25 + kNN)",
        "",
        "## What This Tests",
        "",
        "Given only a typed prompt (no manual document selection), does the app:",
        "1. Find the right contractor documents via search?",
        "2. Produce an accurate form-field writeup from those documents?",
        "",
        "## Results",
        "",
        "| Prompt | Recall | Noise | Facts | Retrieval | Generation | Total |",
        "|--------|--------|-------|-------|-----------|------------|-------|",
    ]

    for r in results:
        summary_lines.append(
            f"| {r['prompt_name']} | {r['retrieval']['required_hit']}/5 | "
            f"{r['retrieval']['noise_count']} | {r['generation']['facts_hit']}/6 | "
            f"{r['retrieval']['time_s']}s | {r['generation']['time_s']}s | {r['total_time_s']}s |"
        )

    best = max(results, key=lambda r: (r["retrieval"]["required_hit"], r["generation"]["facts_hit"]))
    fastest = min(results, key=lambda r: r["total_time_s"])

    summary_lines += [
        "",
        "## Key Findings",
        "",
        f"- **Best retrieval + generation**: [{best['prompt_name']}] — "
        f"{best['retrieval']['required_hit']}/5 docs, {best['generation']['facts_hit']}/6 facts",
        f"- **Fastest**: [{fastest['prompt_name']}] — {fastest['total_time_s']}s total",
        "",
        "## Retrieval Detail",
        "",
        "Required documents:",
    ]
    for doc_id, label in REQUIRED_DOCS.items():
        hit_count = sum(1 for r in results if r["retrieval"]["required_found"][doc_id])
        summary_lines.append(f"- {label}: found in {hit_count}/{len(PROMPTS)} prompts")

    summary_path = OUTPUT_DIR / "summary.md"
    with open(summary_path, "w") as f:
        f.write("\n".join(summary_lines))

    print(f"\n{'=' * 70}")
    print(f"Results: {json_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
