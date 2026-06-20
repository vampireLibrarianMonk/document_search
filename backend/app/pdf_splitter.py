"""PDF splitting for multi-document scans.

OCRs each page, detects document boundaries using an LLM, then writes
individual PDFs for each detected document.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig
from pypdf import PdfReader, PdfWriter

from .extraction import _extract_page_image

logger = logging.getLogger(__name__)

_BOUNDARY_PROMPT = """You are splitting a multi-page scanned PDF into individual documents. Given two consecutive pages, decide if they belong to the SAME document or if Page B starts a NEW document.

SAME indicators: same file/case/reference number, "Page 2 of X", same form title continues, same company and same transaction
NEW indicators: completely different title/form, different company, different subject, Page 1 or fresh start, an invoice/receipt vs a report

Page A:
{page_a}

Page B:
{page_b}

Does Page B start a NEW document or is it the SAME document as Page A? Answer exactly: NEW or SAME"""


_CROSS_FILE_PROMPT = """These pages come from DIFFERENT physical scan files. They should ONLY be considered the SAME document if there is VERY strong evidence of continuity.

SAME (merge) ONLY if ALL of these are true:
- The EXACT same document title/form name appears on both pages
- The EXACT same file number, loan number, or case number appears on both pages
- Page B explicitly shows a continuation (e.g. "Page 2 of 3", "continued from previous page")

NEW (do not merge) if ANY of these are true:
- Different document titles or form names
- "Page 1 of X" or "Page 1" on Page B
- Different subject matter, even if same parties are involved
- One page ends with a signature/notary and the next starts with a new heading
- You are not 100% certain they are the same document

Page A (end of previous scan file):
{page_a}

Page B (start of next scan file):
{page_b}

Are these the SAME document split across scan files? Answer exactly: NEW or SAME"""


def _get_split_model() -> str:
    return os.getenv("BEDROCK_SCAN_SPLIT_MODEL_ID", "mistral.mistral-small-2402-v1:0")


def _get_client():
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=BotoConfig(read_timeout=30, connect_timeout=5),
    )


def _detect_boundary(client, page_a_text: str, page_b_text: str, cross_file: bool = False) -> bool:
    """Returns True if page_b starts a new document."""
    # Give context: first 800 + last 400 of page A, first 800 of page B
    a_context = page_a_text[:800] + ("\n...\n" + page_a_text[-400:] if len(page_a_text) > 1200 else "")
    b_context = page_b_text[:800]

    if cross_file:
        prompt = _CROSS_FILE_PROMPT.format(page_a=a_context, page_b=b_context)
    else:
        prompt = _BOUNDARY_PROMPT.format(page_a=a_context, page_b=b_context)
    try:
        resp = client.converse(
            modelId=_get_split_model(),
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 10, "temperature": 0},
        )
        answer = resp["output"]["message"]["content"][0]["text"].strip().upper()
        return "NEW" in answer
    except Exception as e:
        logger.warning("Boundary detection failed: %s", e)
        # Default to NEW for cross-file (conservative), SAME for within-file
        return cross_file


def split_pdf(pdf_path: str, progress_callback=None) -> list[dict]:
    """Split a multi-document PDF into individual PDFs.

    Args:
        pdf_path: Path to the source PDF
        progress_callback: Optional callable(step, detail) for progress updates

    Returns:
        List of dicts: [{"path": "/path/to/split.pdf", "pages": [0,1,2], "text": "combined text"}]
    """
    reader = PdfReader(pdf_path)
    num_pages = len(reader.pages)

    if num_pages <= 1:
        # Single page — no splitting needed
        text = _extract_page_image(reader.pages[0], 1, pdf_path) or ""
        return [{"path": pdf_path, "pages": [0], "text": text}]

    # OCR all pages
    page_texts = []
    for i in range(num_pages):
        if progress_callback:
            progress_callback("ocr_page", f"OCR page {i + 1}/{num_pages}")
        text = _extract_page_image(reader.pages[i], i + 1, pdf_path) or ""
        page_texts.append(text)

    # Detect boundaries
    client = _get_client()
    boundaries = [0]  # First page always starts a document
    for i in range(num_pages - 1):
        if progress_callback:
            progress_callback("boundary", f"Checking boundary {i + 1}→{i + 2}")
        if not page_texts[i].strip() or not page_texts[i + 1].strip():
            continue  # Skip blank pages
        is_new = _detect_boundary(client, page_texts[i], page_texts[i + 1])
        if is_new:
            boundaries.append(i + 1)

    if progress_callback:
        progress_callback("splitting", f"Found {len(boundaries)} documents in {num_pages} pages")

    # Split into individual PDFs
    output_dir = Path(pdf_path).parent
    base_name = Path(pdf_path).stem
    results = []

    for doc_idx, start_page in enumerate(boundaries):
        end_page = boundaries[doc_idx + 1] if doc_idx + 1 < len(boundaries) else num_pages

        # Write split PDF
        writer = PdfWriter()
        for p in range(start_page, end_page):
            writer.add_page(reader.pages[p])

        split_path = str(output_dir / f"{base_name}_doc{doc_idx + 1:02d}_p{start_page + 1}-{end_page}.pdf")
        with open(split_path, "wb") as f:
            writer.write(f)

        # Combine text for this document
        combined_text = "\n".join(page_texts[start_page:end_page])

        results.append({
            "path": split_path,
            "pages": list(range(start_page, end_page)),
            "text": combined_text,
        })

    return results


def merge_across_files(split_results: list[list[dict]], progress_callback=None) -> list[dict]:
    """Check boundaries between the last doc of file N and first doc of file N+1.

    If they're the same document, merge their PDFs and text into one entry.

    Args:
        split_results: List of per-file split results (each is a list of doc dicts from split_pdf)
        progress_callback: Optional callable(step, detail)

    Returns:
        Flat list of doc dicts with cross-file merges applied.
    """
    if not split_results:
        return []

    # Flatten into a single list, tracking file boundaries
    flat: list[dict] = []
    for file_docs in split_results:
        flat.extend(file_docs)

    if len(split_results) <= 1:
        return flat

    # Check each file boundary
    client = _get_client()
    merge_indices: set[int] = set()  # indices in flat[] that should merge with previous

    offset = 0
    for file_idx in range(len(split_results) - 1):
        offset += len(split_results[file_idx])
        # offset is now the index of the first doc in file_idx+1

        last_doc = flat[offset - 1]
        first_doc = flat[offset]

        if not last_doc["text"].strip() or not first_doc["text"].strip():
            continue

        if progress_callback:
            progress_callback("cross_check", f"Checking boundary between file {file_idx + 1} and {file_idx + 2}")

        is_new = _detect_boundary(client, last_doc["text"], first_doc["text"], cross_file=True)
        if not is_new:
            merge_indices.add(offset)

    if not merge_indices:
        return flat

    # Build merged list
    merged: list[dict] = []
    i = 0
    while i < len(flat):
        doc = flat[i]
        # Absorb subsequent docs that should merge
        while i + 1 < len(flat) and (i + 1) in merge_indices:
            next_doc = flat[i + 1]
            # Merge PDFs
            writer = PdfWriter()
            for src_path in [doc["path"], next_doc["path"]]:
                reader = PdfReader(src_path)
                for page in reader.pages:
                    writer.add_page(page)
            # Write merged PDF over the first doc's path
            merged_path = doc["path"].replace(".pdf", "_merged.pdf")
            with open(merged_path, "wb") as f:
                writer.write(f)
            # Clean up individual split files
            if os.path.exists(doc["path"]) and doc["path"] != merged_path:
                os.remove(doc["path"])
            if os.path.exists(next_doc["path"]):
                os.remove(next_doc["path"])

            doc = {
                "path": merged_path,
                "pages": doc["pages"] + next_doc["pages"],
                "text": doc["text"] + "\n" + next_doc["text"],
            }
            i += 1
        merged.append(doc)
        i += 1

    if progress_callback:
        progress_callback("merge_done", f"Merged {len(merge_indices)} cross-file documents, {len(merged)} total")

    return merged


_VALIDATE_PROMPT = """You are reviewing a document that was automatically extracted from a scanned PDF package. Your job is to check if the splitting was done correctly.

Document text (may be truncated in the middle):
{text}

A document is VALID if:
- It is clearly ONE document (even if multi-page)
- Legal documents, forms, and letters that end with signatures are complete
- A document does NOT need a formal conclusion to be valid — signatures, notary seals, or the end of form content count as complete

A document is INVALID only if:
- It clearly contains TWO OR MORE completely unrelated documents (different titles, different parties, different subjects)
- There is an obvious mid-sentence cutoff at the very beginning (missing the first page of this specific form)

DO NOT flag as invalid:
- Documents that reference other documents
- Multi-section forms with different headings (that's normal for legal docs)
- Documents with riders or addenda attached (those belong together)

Respond with ONLY a JSON object:
{{"valid": true, "issue": "none", "action": "keep"}}
or
{{"valid": false, "issue": "brief description", "action": "split_at_page_N" or "incomplete_missing_start"}}"""


def validate_documents(docs: list[dict], progress_callback=None) -> list[dict]:
    """Validate split documents and flag issues. Returns docs with 'validation' key added.

    Does NOT modify the list — just annotates each doc with validation results
    so downstream can decide what to do.
    """
    client = _get_client()
    model_id = os.getenv("BEDROCK_SCAN_VALIDATE_MODEL_ID", "amazon.nova-pro-v1:0")

    for i, doc in enumerate(docs):
        if progress_callback:
            progress_callback("validate", f"Validating document {i + 1}/{len(docs)}")

        text = doc["text"]
        # For large docs, sample start + end
        if len(text) > 3000:
            sample = text[:1500] + "\n\n[...middle omitted...]\n\n" + text[-1500:]
        else:
            sample = text

        try:
            resp = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": _VALIDATE_PROMPT.format(text=sample)}]}],
                inferenceConfig={"maxTokens": 150, "temperature": 0},
            )
            answer = resp["output"]["message"]["content"][0]["text"].strip()
            # Parse JSON from response
            import re
            json_match = re.search(r'\{[^}]+\}', answer)
            if json_match:
                validation = json.loads(json_match.group())
            else:
                validation = {"valid": True, "issue": "none", "action": "keep"}
        except Exception as e:
            logger.warning("Validation failed for doc %d: %s", i, e)
            validation = {"valid": True, "issue": "validation_error", "action": "keep"}

        doc["validation"] = validation

    return docs
