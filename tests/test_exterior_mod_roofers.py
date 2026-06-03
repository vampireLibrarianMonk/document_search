"""Test: Gather HOA Exterior Modification Application + each roofer's documents,
then craft a writeup per roofer to insert into the application form.

Roofers identified (alpha order):
  A - All Day Roofing & More LLC
  B - American Home Contractors (AHC)
  C - Brax Roofing
  D - Virginia Roofing Corporation

Uses the live app API at https://api.localhost.
"""

import json
import sys
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API = "https://api.localhost"
VERIFY = False

# Document IDs found via search
EXTERIOR_MOD_APP = "doc_38cebc657b28"

ROOFERS = {
    "All Day Roofing & More LLC": {
        "doc_ids": ["doc_183edbcecb4e"],
        "search_hint": "All Day Roofing flat roof replacement proposal",
        "estimates": [
            {"name": "Option 1 - TPO 60mil (15-20yr warranty)", "price": "$12,800"},
            {"name": "Option 2 - EPDM 75mil (20-30yr warranty)", "price": "~$16,000"},
            {"name": "Option 3 - RubberGard 90mil (30-50yr warranty)", "price": "$20,996 + $1,500 forklift + $3,450 balcony = $25,946"},
        ],
    },
    "American Home Contractors": {
        "doc_ids": ["doc_80126e445665", "doc_aaee35593d06"],
        "search_hint": "American Home Contractors roofing flat roof replacement",
        "estimates": [
            {"name": "Roof repairs only", "price": "$2,850"},
            {"name": "GAF LIBERTY SBS 2-ply self-adhered system (15yr warranty)", "price": "$7,200"},
            {"name": "GAF RUBEROID Torch granule membrane system", "price": "$9,600"},
            {"name": "GAF Everguard TPO system", "price": "$17,400"},
        ],
    },
    "Brax Roofing": {
        "doc_ids": ["doc_6f864ae384d9", "doc_707cc5dde5df", "doc_e8344600ec2c"],
        "search_hint": "Brax Roofing roof replacement quote proposal email",
        "estimates": [
            {"name": "TPO roof replacement (no parapet walls)", "price": "$10,595"},
            {"name": "TPO roof + parapet walls (recommended)", "price": "$14,220"},
            {"name": "Full 3-home roof replacement", "price": "$24,350"},
        ],
    },
    "Virginia Roofing Corporation": {
        "doc_ids": ["doc_57d1c14cee79", "doc_7541b3323728"],
        "search_hint": "Virginia Roofing Corporation roof recovery repair proposal",
        "estimates": [
            {"name": "Full EPDM roof recovery (main roof)", "price": "$15,704"},
            {"name": "Roof repairs only (caulking, flashing, patches)", "price": "$2,289"},
        ],
    },
}

OUTPUT_DIR = Path(__file__).resolve().parent / "exterior_mod_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_document_chunks(doc_id: str) -> str:
    """Fetch all chunk text for a document."""
    resp = requests.get(f"{API}/documents/{doc_id}/chunks", verify=VERIFY)
    resp.raise_for_status()
    data = resp.json()
    chunks = data.get("chunks", [])
    return "\n".join(c.get("content", "") for c in chunks)


def search_docs(query: str, limit: int = 5) -> list[dict]:
    """Search the index."""
    resp = requests.post(f"{API}/search", json={"query": query, "limit": limit}, verify=VERIFY)
    resp.raise_for_status()
    return resp.json().get("results", resp.json())


def ask_ai(question: str, doc_ids: list[str] | None = None) -> dict:
    """Ask AI with optional document filter."""
    payload = {"question": question}
    if doc_ids:
        payload["document_ids"] = doc_ids
    resp = requests.post(f"{API}/ask", json=payload, verify=VERIFY)
    resp.raise_for_status()
    return resp.json()


def generate_doc(prompt: str, doc_ids: list[str] | None = None) -> dict:
    """Generate content via the generate endpoint."""
    payload = {"prompt": prompt}
    if doc_ids:
        payload["document_ids"] = doc_ids
    resp = requests.post(f"{API}/generate", json=payload, verify=VERIFY)
    resp.raise_for_status()
    return resp.json()


def main():
    print("=" * 70)
    print("EXTERIOR MODIFICATION APPLICATION - ROOFER WRITEUP GENERATOR")
    print("=" * 70)

    # Step 1: Fetch the application form content
    print("\n[1] Fetching Exterior Modification Application form...")
    form_text = get_document_chunks(EXTERIOR_MOD_APP)
    print(f"    Form loaded: {len(form_text)} chars, from doc {EXTERIOR_MOD_APP}")

    # Step 2: Loop through roofers alphabetically, then each estimate option
    results = {}
    for roofer_name, info in sorted(ROOFERS.items()):
        print(f"\n{'─' * 70}")
        print(f"[ROOFER] {roofer_name} ({len(info['estimates'])} estimate(s))")
        print(f"{'─' * 70}")

        # Gather roofer's document content
        print(f"  Gathering documents: {info['doc_ids']}")
        roofer_content = ""
        for doc_id in info["doc_ids"]:
            chunk_text = get_document_chunks(doc_id)
            roofer_content += f"\n--- {doc_id} ---\n{chunk_text}\n"
            print(f"    {doc_id}: {len(chunk_text)} chars")

        # Also do a search to catch anything we might have missed
        print(f"  Searching: {info['search_hint']}")
        search_results = search_docs(info["search_hint"])
        print(f"    Found {len(search_results)} search hits")

        # Print estimates summary
        for i, est in enumerate(info["estimates"], 1):
            print(f"  Estimate {i}: {est['name']} — {est['price']}")

        # Generate a writeup for EACH estimate option
        roofer_results = []
        safe_name = roofer_name.replace(" ", "_").replace("&", "and").replace(".", "")

        for i, est in enumerate(info["estimates"], 1):
            prompt = (
                f"I need to fill out an HOA Exterior Modification Application for a roof project. "
                f"The contractor is {roofer_name}. I am choosing this specific option from their proposal:\n"
                f"  \"{est['name']}\" at {est['price']}\n\n"
                f"Using the contractor's documents below, write the 'Description of Proposed Modification' "
                f"section for the application form. Include: what work will be done, materials, "
                f"contractor license/contact info, cost for THIS option, and timeline. "
                f"Be factual and concise. Only describe this specific option.\n\n"
                f"--- CONTRACTOR DOCUMENTS ---\n{roofer_content[:8000]}\n\n"
                f"--- APPLICATION FORM REFERENCE ---\n{form_text[:2000]}"
            )

            print(f"\n  [{i}/{len(info['estimates'])}] Generating: {est['name']}...")
            t0 = time.time()
            gen_result = generate_doc(prompt, info["doc_ids"])
            elapsed = time.time() - t0

            writeup = gen_result.get("content", gen_result.get("markdown", gen_result.get("text", "")))
            print(f"    Generated in {elapsed:.1f}s, {len(writeup)} chars")
            print(f"    Preview: {writeup[:150]}...")

            roofer_results.append({
                "estimate_name": est["name"],
                "estimate_price": est["price"],
                "writeup": writeup,
                "generation_time_s": round(elapsed, 2),
            })

        results[roofer_name] = {
            "doc_ids": info["doc_ids"],
            "estimates": roofer_results,
            "search_hits": len(search_results),
        }

        # Save combined writeup for this roofer (all options)
        output_path = OUTPUT_DIR / f"{safe_name}_writeup.md"
        with open(output_path, "w") as f:
            f.write(f"# Exterior Modification Application Writeups\n")
            f.write(f"## Contractor: {roofer_name}\n\n")
            f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for r in roofer_results:
                f.write(f"---\n\n### Option: {r['estimate_name']}\n")
                f.write(f"**Price: {r['estimate_price']}**\n\n")
                f.write(f"#### Description of Proposed Modification\n\n")
                f.write(r["writeup"])
                f.write(f"\n\n")
            f.write(f"---\n*Source documents: {', '.join(info['doc_ids'])}*\n")
        print(f"\n  Saved: {output_path.name}")

    # Step 3: Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"Form document: {EXTERIOR_MOD_APP}")
    print(f"Roofers processed: {len(results)}")
    total_writeups = 0
    for name, r in sorted(results.items()):
        print(f"\n  {name} ({len(r['estimates'])} options):")
        for est in r["estimates"]:
            print(f"    • {est['estimate_name']}: {est['estimate_price']} ({len(est['writeup'])} chars, {est['generation_time_s']}s)")
            total_writeups += 1
    print(f"\nTotal writeups generated: {total_writeups}")

    # Save combined JSON
    summary_path = OUTPUT_DIR / "all_roofer_writeups.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Full results: {summary_path}")


if __name__ == "__main__":
    main()
