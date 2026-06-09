"""Gambit: Package Archive Structure Test

Runs the Tasks workflow end-to-end, exports a ZIP package, then restructures it
into a human-readable archive where:

- The writeup is at the top level
- Each source document is numbered and renamed by its relevance to the prompt
- A subdirectory per document contains the original file + a relevance summary

Archive structure:
  2026-06-08-14-33-28/
    writeup.txt
    sources/
      01_AHC_Flat_Roof_Replacement_Proposal/
        original.pdf
        relevance.txt   (why this doc was pulled, which chunks matched)
      02_Jacob_Estes_Email_Roof_Details/
        original.txt
        relevance.txt
      ...
"""

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

API = "https://api.localhost"
VERIFY = False
TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"

PROMPT = "Fill out the description of proposed modification for the exterior modification form using American Home Contractors GAF LIBERTY SBS system"
DOC_IDS = ["doc_aaee35593d06", "doc_6b883a64a4d0", "doc_b866994701d3", "doc_ece84354cbb5", "doc_38cebc657b28"]


def get_doc_info(doc_id: str) -> dict:
    r = requests.get(f"{API}/documents/{doc_id}", verify=VERIFY)
    return r.json() if r.status_code == 200 else {}


def get_relevant_chunks(prompt: str, doc_id: str) -> list[dict]:
    """Search for chunks in this specific document that relate to the prompt."""
    r = requests.post(f"{API}/search", json={
        "query": prompt, "mode": "hybrid", "page": 1, "page_size": 5,
    }, verify=VERIFY)
    results = r.json().get("results", [])
    return [r for r in results if r["document_id"] == doc_id]


def generate_writeup(prompt: str, doc_ids: list[str]) -> str:
    """Run tasks/generate and return the markdown content."""
    r = requests.post(f"{API}/tasks/generate", json={
        "prompt": prompt, "document_ids": doc_ids,
        "history": [], "format": "md", "skip_auto_search": True,
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
    return result


def build_relevance_name(doc_info: dict, chunks: list[dict]) -> str:
    """Create a descriptive name for the document based on what it contributes."""
    title = doc_info.get("title", "Unknown")
    # Shorten to a clean filesystem-safe name
    name = re.sub(r"[^\w\s-]", "", title)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:60]


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    archive_dir = TMP_DIR / timestamp
    sources_dir = archive_dir / "sources"

    print(f"Archive: {archive_dir}")
    print(f"Prompt: {PROMPT}")
    print(f"Documents: {len(DOC_IDS)}")
    print()

    # Step 1: Generate the writeup
    print("[1] Generating writeup...")
    writeup = generate_writeup(PROMPT, DOC_IDS)
    if not writeup:
        print("  ERROR: No writeup generated")
        return
    print(f"  Done: {len(writeup)} chars")

    # Step 2: Build the archive structure
    print("[2] Building archive...")
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)

    # Write the main writeup
    writeup_path = archive_dir / "writeup.txt"
    citations = ["Source Documents:", ""]
    
    for idx, doc_id in enumerate(DOC_IDS, 1):
        doc_info = get_doc_info(doc_id)
        if not doc_info:
            continue

        # Get relevance info
        chunks = get_relevant_chunks(PROMPT, doc_id)
        relevance_name = build_relevance_name(doc_info, chunks)
        dir_name = f"{idx:02d}_{relevance_name}"
        doc_dir = sources_dir / dir_name
        doc_dir.mkdir(parents=True, exist_ok=True)

        # Copy original file
        source_url = doc_info.get("source_url", "")
        file_path = Path(source_url.replace("/app/", ""))
        if not file_path.exists():
            file_path = Path("data/uploads") / file_path.name
        
        original_filename = doc_info.get("original_filename", "unknown")
        if file_path.exists():
            dest = doc_dir / original_filename
            shutil.copy2(file_path, dest)
            print(f"  [{idx}] {dir_name}/ → {original_filename}")
        else:
            print(f"  [{idx}] {dir_name}/ → FILE NOT FOUND ({file_path})")

        # Write relevance summary
        relevance_text = [
            f"Document: {doc_info.get('title', 'Unknown')}",
            f"Original filename: {original_filename}",
            f"Type: {doc_info.get('document_type', 'unknown')}",
            f"Category: {doc_info.get('category', 'unknown')}",
            f"",
            f"Why this document was included:",
            f"",
        ]
        if chunks:
            for i, chunk in enumerate(chunks, 1):
                snippet = chunk.get("snippet", "").replace("<em>", "").replace("</em>", "")
                relevance_text.append(f"  Match {i} (score {chunk.get('score', 0):.1f}):")
                relevance_text.append(f"    {snippet[:300]}")
                relevance_text.append("")
        else:
            relevance_text.append("  Included via entity name match or form auto-detection.")

        (doc_dir / "relevance.txt").write_text("\n".join(relevance_text))

        # Add to citations in writeup
        citations.append(f"  {idx}. {dir_name}/ — {doc_info.get('title', '')}")

    # Append citations to writeup
    full_writeup = writeup + "\n\n" + "\n".join(citations) + "\n"
    writeup_path.write_text(full_writeup)

    # Step 3: Summary
    print(f"\n[3] Archive complete: {archive_dir}")
    print(f"  writeup.txt ({len(full_writeup)} chars)")
    for d in sorted(sources_dir.iterdir()):
        files = list(d.iterdir())
        print(f"  sources/{d.name}/ ({len(files)} files)")

    # Step 4: Verify and report
    print(f"\n[4] Verification:")
    total_files = sum(1 for _ in archive_dir.rglob("*") if _.is_file())
    print(f"  Total files: {total_files}")
    print(f"  Archive path: {archive_dir}")

    return archive_dir


if __name__ == "__main__":
    result_dir = main()
    if result_dir:
        print(f"\n✅ Done. Archive at: {result_dir}")
        # Clean up after inspection
        # shutil.rmtree(result_dir)
