"""Template Fill Engine v2 - Section-by-section generation with full cleanup.

Implements the spec in new_capability/api/template_fill_spec.md.
Three phases: analyze → generate → apply.
"""

from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from io import BytesIO

from lxml import etree

logger = logging.getLogger(__name__)

WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _trunc(text: str, max_chars: int) -> str:
    """Truncate text at a word boundary without exceeding max_chars."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    # Find last space to avoid cutting mid-word
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.5:
        return truncated[:last_space].rstrip()
    return truncated.rstrip()


def analyze(docx_bytes: bytes) -> list[dict]:
    """Catalog all fillable slots in the template."""
    slots = []
    with zipfile.ZipFile(BytesIO(docx_bytes)) as z:
        root = etree.fromstring(z.read("word/document.xml"))

        # Count SDT placeholders
        sdt_count = 0
        for sdt in root.findall(f".//{WNS}sdt"):
            sdt_pr = sdt.find(f"{WNS}sdtPr")
            if sdt_pr is not None and sdt_pr.find(f"{WNS}showingPlcHdr") is not None:
                sdt_count += 1
                texts = sdt.findall(f".//{WNS}t")
                content = "".join(t.text or "" for t in texts)
                runs = sdt.findall(f".//{WNS}r")
                non_empty_runs = sum(1 for r in runs if "".join(t.text or "" for t in r.findall(f"{WNS}t")).strip())
                slots.append({
                    "slot_id": f"sdt_{sdt_count}",
                    "type": "sdt",
                    "text": content[:100],
                    "char_count": len(content),
                    "run_count": non_empty_runs,
                })

        # Count MACROBUTTON fields
        macro_count = sum(1 for i in root.findall(f".//{WNS}instrText")
                         if i.text and "MACROBUTTON" in i.text)
        if macro_count:
            slots.append({"type": "macrobutton", "count": macro_count})

        # Count bibliography table cells with ". . , ."
        body = root.find(f"{WNS}body")
        tables = body.findall(f"{WNS}tbl")
        for ti, tbl in enumerate(tables):
            cell_count = sum(1 for t in tbl.findall(f".//{WNS}t")
                            if t.text and ". . , ." in t.text)
            if cell_count:
                slots.append({"type": "bib_table", "table_index": ti, "cells": cell_count})

    return slots


def generate_sectioned(prompt: str, context: str, doc_titles: list[str]) -> dict:
    """Generate content per section using multiple Bedrock calls.

    Returns a dict with all replacement data organized by section.
    """
    import boto3

    model_id = os.getenv("BEDROCK_GENERATE_MODEL_ID", os.getenv("BEDROCK_MODEL_ID", ""))
    if not model_id:
        raise ValueError("No generation model configured")

    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

    def ask(p):
        resp = client.converse(modelId=model_id,
                               messages=[{"role": "user", "content": [{"text": p}]}],
                               inferenceConfig={"maxTokens": 2048})
        return resp["output"]["message"]["content"][0]["text"]

    def parse(text):
        s = text.find("{")
        e = text.rfind("}") + 1
        if s >= 0 and e > s:
            raw = json.loads(text[s:e])
            # Strip HTML tags from all string values
            return _strip_html(raw)
        return {}

    def _strip_html(obj):
        if isinstance(obj, str):
            return re.sub(r'<[^>]+>', '', obj)
        if isinstance(obj, list):
            return [_strip_html(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _strip_html(v) for k, v in obj.items()}
        return obj

    # --- Title Page ---
    # --- Title Page (generate all values, then format to fit) ---
    title_data = parse(ask(f"""Fill a thesis title page. The topic is: {prompt}
The author is Patrick Flanigan. The community is Centerpointe.

Return JSON with these fields:
- "title": a short thesis title (2-4 words max)
- "author": "Patrick Flanigan"
- "description": one sentence describing the document's purpose (~100 chars)
- "institution": "Centerpointe Community"
- "year": "2026"
- "committee": approving body name (~30 chars)
- "program": program or department name (~20 chars)
- "date": "May 2026"

Use context: {context[:500]}
Return ONLY valid JSON. No HTML tags."""))
    
    # Format title into 3-run structure: split at natural midpoint
    raw_title = title_data.get("title", "HOA Governance")
    if isinstance(raw_title, list):
        raw_title = " ".join(str(x) for x in raw_title if x)
    words = raw_title.split()
    if len(words) <= 2:
        title_data["title"] = [words[0] if words else "HOA", "", words[1] if len(words) > 1 else ""]
    else:
        mid = len(words) // 2
        title_data["title"] = [" ".join(words[:mid]), "", " ".join(words[mid:])]
    
    # Format author into 2-run structure
    raw_author = title_data.get("author", "Patrick Flanigan")
    if isinstance(raw_author, str):
        name = raw_author.replace("by ", "").replace("By ", "").strip()
        title_data["author"] = ["by", name]
    
    # Format description into 2-run structure
    raw_desc = title_data.get("description", "A comprehensive guide")
    if isinstance(raw_desc, str):
        # Split at last comma or preposition before char 70
        if len(raw_desc) > 70:
            # Find a good split point
            split_at = raw_desc.rfind(" of ", 0, 75)
            if split_at < 0: split_at = raw_desc.rfind(", ", 0, 75)
            if split_at < 0: split_at = raw_desc.rfind(" ", 0, 70)
            if split_at > 0:
                title_data["description"] = [raw_desc[:split_at + 3].strip(), raw_desc[split_at + 3:].strip()]
            else:
                title_data["description"] = [raw_desc[:70], raw_desc[70:]]
        else:
            title_data["description"] = [raw_desc, ""]
    elif isinstance(raw_desc, list) and len(raw_desc) == 1:
        title_data["description"] = [raw_desc[0], ""]
    
    # Format institution into 3-run structure
    raw_inst = title_data.get("institution", "Centerpointe Community")
    if isinstance(raw_inst, str):
        parts = raw_inst.split()
        if len(parts) >= 2:
            title_data["institution"] = [parts[0], " ", " ".join(parts[1:])]
        else:
            title_data["institution"] = [raw_inst, " ", ""]
    
    # Ensure simple string fields
    for key in ("year", "committee", "program", "date"):
        v = title_data.get(key, "")
        if isinstance(v, list):
            title_data[key] = " ".join(str(x) for x in v)
    
    title_data.setdefault("institution2", title_data.get("institution", ["", " ", ""])[0] + " " + title_data.get("institution", ["", " ", ""])[2] if isinstance(title_data.get("institution"), list) else str(title_data.get("institution", "")))

    # --- Abstract ---
    abstract_data = parse(ask(f"""Write a thesis abstract about HOA governance (~220 chars).
Return JSON: {{"title": "HOA Governance", "author": "By Patrick Flanigan", "body": "220 char paragraph about HOA governance, architectural guidelines, and compliance."}}
Use: {context[:500]}
Return ONLY JSON."""))

    # --- Acknowledgments ---
    ack_data = parse(ask("""Write acknowledgments for an HOA governance report (3 parts):
Return JSON: {{"part1": "~190 chars thanking HOA board and ARB for guidance...", "name": "Sarah Johnson", "part3": "~175 chars about their ARB leadership role and thanks to community members..."}}
Return ONLY JSON."""))

    # --- Glossary ---
    glossary_data = parse(ask(f"""Write 8 HOA glossary terms. Return JSON:
{{"terms": [{{"term": "ARB.", "def": "Architectural Review Board..."}}, ...]}}
Include: ARB, Assessment, CC&Rs, Common Area, Compliance, Exterior Modification, Governance, Variance.
Use: {context[:500]}
Return ONLY JSON."""))

    # --- Chapter ---
    chapter_data = parse(ask(f"""Write chapter content for HOA governance thesis.
Return JSON:
{{"title": "HOA Governance Structure",
"sub1_heading": "Architectural Guidelines", "sub1_body": "2-3 sentences ~200 chars about ARB and design standards",
"sub2_heading": "Exterior Modification Process", "sub2_body": "2-3 sentences ~200 chars about application process",
"sub3_heading": "Compliance and Enforcement", "sub3_body": "2-3 sentences ~200 chars about violations and fines"}}
Use REAL details from: {context[:1500]}
Return ONLY JSON."""))

    # --- Bibliography (deterministic) ---
    bib_entries = []
    for title in doc_titles[:14]:
        clean = title.split("/")[-1].replace(".pdf", "").replace(".docx", "")
        clean = re.sub(r"^Appendix \d+", "", clean).strip().replace("_", " ").replace(" - Master", "")
        if clean:
            bib_entries.append(f"Centerpointe Community Association. {clean}. Fairfax, VA: Centerpointe HOA, 2024.")
    bib_entries = list(dict.fromkeys(bib_entries))  # dedupe

    # --- Index (deterministic) ---
    index_entries = [
        "A", "M", "S", "Architectural Guidelines, 7", "Maintenance, 6", "Setbacks, 7",
        "ARB, 7", "Meetings, 5", "Signage, 8", "Assessments, 5", "Modifications, 7", "Trash, 8",
        "C", "O", "V", "CC&Rs, 6", "Outdoor Structures, 7", "Variances, 8",
        "Compliance, 7", "P", "Violations, 8", "Common Areas, 6", "Paint Colors, 7", "Voting, 5",
        "E", "Parking, 8", "Y", "Enforcement, 8", "R", "Yards, 7", "F", "Roofing, 7",
    ]

    # --- TOC (deterministic from chapter) ---
    toc_entries = [
        "Acknowledgments", "5", "Glossary", "6", "Chapter 1",
        f" {chapter_data.get('title', 'HOA Governance Structure')}", "7",
        chapter_data.get("sub1_heading", "Architectural Guidelines"), "7",
        chapter_data.get("sub2_heading", "Exterior Modification Process"), "8",
        chapter_data.get("sub3_heading", "Compliance and Enforcement"), "8",
        "Bibliography", "9", "Index", "10",
    ]

    figure_entries = [
        "Community Site Plan", "7", "Approved Materials", "8", "Fence Standards", "8",
        "Landscaping Guide", "8", "Color Palette", "9", "Modification Form", "9",
        "Review Process", "9", "Compliance Flow", "10", "Fee Schedule", "10", "Site Map", "10",
    ]

    return {
        "title": title_data,
        "abstract": abstract_data,
        "ack": ack_data,
        "glossary": glossary_data.get("terms", []),
        "chapter": chapter_data,
        "bib_entries": bib_entries,
        "index_entries": index_entries,
        "toc_entries": toc_entries,
        "figure_entries": figure_entries,
    }


def apply_full(docx_bytes: bytes, content: dict) -> bytes:
    """Apply all replacements to the DOCX in a single pass.

    Handles: SDTs, MACROBUTTON fields, bibliography table, index table,
    static text, empty cleanup, page breaks.
    """
    with zipfile.ZipFile(BytesIO(docx_bytes)) as z:
        doc_xml = z.read("word/document.xml")
        root = etree.fromstring(doc_xml)
        body = root.find(f"{WNS}body")

        title = content["title"]
        abstract = content["abstract"]
        ack = content["ack"]
        glossary = content["glossary"]
        chapter = content["chapter"]
        bib_entries = content["bib_entries"]
        index_entries = content["index_entries"]
        toc_entries = content["toc_entries"]
        figure_entries = content["figure_entries"]

        # === 1. REPLACE SDTs ===
        sdt_idx = 0
        for sdt in root.findall(f".//{WNS}sdt"):
            sdt_pr = sdt.find(f"{WNS}sdtPr")
            if sdt_pr is None or sdt_pr.find(f"{WNS}showingPlcHdr") is None:
                continue
            sdt_idx += 1
            runs = sdt.findall(f".//{WNS}r")

            # Determine replacement
            r = _get_sdt_replacement(sdt_idx, title, abstract, ack, glossary, chapter, index_entries, toc_entries, figure_entries, runs)

            if r == "__SKIP__":
                # Just remove placeholder flag
                _remove_plc_flag(sdt_pr)
                continue
            if r == "__TOC__":
                _fill_non_empty_runs(runs, toc_entries)
                _remove_plc_flag(sdt_pr)
                continue
            if r == "__FIGS__":
                _fill_non_empty_runs(runs, figure_entries)
                _remove_plc_flag(sdt_pr)
                continue
            if r is None:
                continue

            # For title page SDTs (1-10), apply font scaling if text is longer than original
            # Original sizes: SDT1=11chars, SDT2=13, SDT3=110, SDT4=19, SDT7=36, SDT8=23
            # Base font: 24 half-points (12pt) from document default
            orig_chars_map = {1: 11, 2: 13, 3: 110, 4: 19, 5: 4, 7: 36, 8: 23, 10: 4}
            orig_chars = orig_chars_map.get(sdt_idx, 0)
            _set_sdt_content(runs, r, original_chars=orig_chars, base_size_half_pts=24)
            _remove_plc_flag(sdt_pr)

        # === 2. REMOVE MACROBUTTON FIELDS ===
        for p in list(root.findall(f".//{WNS}p")):
            if any(i.text and "MACROBUTTON" in i.text for i in p.findall(f".//{WNS}instrText")):
                for run in list(p.findall(f"{WNS}r")):
                    if (run.find(f"{WNS}fldChar") is not None or
                            run.find(f"{WNS}instrText") is not None):
                        p.remove(run)
                    else:
                        t = run.find(f"{WNS}t")
                        if t is not None and t.text and t.text.startswith("[") and "]" in t.text:
                            p.remove(run)

        # === 3. FILL BIBLIOGRAPHY TABLE ===
        tables = body.findall(f"{WNS}tbl")
        if len(tables) >= 2:
            _fill_bib_table(tables[1], bib_entries)

        # === 4. FILL INDEX TABLE ===
        if len(tables) >= 3:
            _fill_index_table(tables[2], index_entries)

        # === 5. STATIC TEXT REPLACEMENT ===
        static_map = {
            "Professor Janessa ": "Jane Smith, ",
            "Bughatti": "ARB Chair",
            "Department of Science": "Architectural Review Board",
            "Chairperson of the Supervisory Committee:": "Chairperson of the Architectural Review Board:",
        }
        for t_el in root.findall(f".//{WNS}t"):
            if t_el.text:
                for old, new in static_map.items():
                    if old in t_el.text:
                        t_el.text = t_el.text.replace(old, new)

        # === 6. REMOVE EMPTY ROWS (bib/index tables only, NOT title table) ===
        for tbl in tables[1:]:  # Skip first table (title page)
            for row in list(tbl.findall(f".//{WNS}tr")):
                if not "".join(t.text or "" for t in row.findall(f".//{WNS}t")).strip():
                    tbl.remove(row)

        # === 7. PRESERVE ORIGINAL STRUCTURE ===
        # Do NOT remove empty paragraphs — they are structural spacers and page breaks
        # Do NOT insert new page breaks — the original template already has them
        # Only remove orphaned bookmarks at body level

        # === 8. BOOKMARK CLEANUP ===
        for el in list(body):
            if el.tag.split("}")[-1] in ("bookmarkStart", "bookmarkEnd"):
                body.remove(el)

        modified_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    # Rebuild ZIP
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(docx_bytes), "r") as zin:
        with zipfile.ZipFile(output, "w") as zout:
            for item in zin.infolist():
                if item.filename == "word/document.xml":
                    zout.writestr(item, modified_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))

    return output.getvalue()


def _get_sdt_replacement(idx, title, abstract, ack, glossary, chapter, index_entries, toc_entries, figure_entries, runs):
    """Map SDT index to its replacement value."""
    # Title page (1-10) — values are pre-constrained from generate step
    if idx == 1: return title.get("title", ["HOA", "", "Governance"])
    if idx == 2: return title.get("author", ["by", "Patrick Flanigan"])
    if idx == 3: return title.get("description", ["A guide to HOA governance", "Centerpointe Community"])
    if idx == 4: return title.get("institution", ["Centerpointe", " ", "Community"])
    if idx == 5: return title.get("year", "2026")
    if idx == 6: return "Approved by"
    if idx == 7: return title.get("committee", "HOA Board of Directors")
    if idx == 8: return title.get("program", "Community Governance")
    if idx == 9: return "Authorized"
    if idx == 10: return title.get("date", "May 2026")
    # Abstract (11-15)
    if idx == 11: return title.get("institution2", "Centerpointe Community")
    if idx == 12: return "Abstract"
    if idx == 13: return abstract.get("title", "HOA Governance")
    if idx == 14: return abstract.get("author", "By Patrick Flanigan")
    if idx == 15: return [abstract.get("body", "This report examines HOA governance."), " "]
    # TOC (16-17)
    if idx == 16: return "Table of Contents"
    if idx == 17: return "__TOC__"
    # Figures (18-20)
    if idx == 18: return "List of Figures"
    if idx == 19: return "__SKIP__"  # Number/Page headers
    if idx == 20: return "__FIGS__"
    # Acknowledgments (21-22)
    if idx == 21: return "Acknowledgments"
    if idx == 22: return [ack.get("part1", "Thanks "), ack.get("name", "Sarah Johnson"), ack.get("part3", " for contributions.")]
    # Glossary (23-39)
    if idx == 23: return "Glossary"
    if 24 <= idx <= 39:
        gi = (idx - 24) // 2
        if gi < len(glossary):
            return glossary[gi].get("term" if (idx - 24) % 2 == 0 else "def", "")
        return ""
    # Chapter (39-90) — use sections array from content generator
    if idx == 39: return "Chapter 1"
    if idx == 40:
        return chapter.get("title", "HOA Governance Structure")
    if 41 <= idx <= 90:
        sections = chapter.get("sections", [])
        # Map SDTs sequentially: heading, body, heading, body, heading, body...
        chapter_offset = idx - 41
        section_idx = chapter_offset // 2
        is_heading = chapter_offset % 2 == 0
        if section_idx < len(sections):
            s = sections[section_idx]
            return s.get("heading", "") if is_heading else s.get("body", "")
        return ""
    # Bibliography/Index headings
    if idx == 91: return "Bibliography"
    if idx == 92: return "Index"
    # Index entries (93-124)
    if 93 <= idx <= 124:
        ii = idx - 93
        return index_entries[ii] if ii < len(index_entries) else ""
    return None


def _set_sdt_content(runs, replacement, original_chars: int = 0, base_size_half_pts: int = 0):
    """Set SDT content from replacement (string or list).
    
    If original_chars and base_size_half_pts are provided, scales font size
    to fit: new_size = base_size * (original_chars / new_chars), clamped to 60%-100%.
    """
    if isinstance(replacement, list):
        for i, run in enumerate(runs):
            t_el = run.find(f"{WNS}t")
            if t_el is None:
                t_el = etree.SubElement(run, f"{WNS}t")
            new_text = replacement[i] if i < len(replacement) else ""
            t_el.text = new_text
            t_el.set(f"{WNS}space", "preserve")
            # Scale font if text is longer than original
            if original_chars and base_size_half_pts and new_text:
                _scale_run_font(run, len(new_text), original_chars, base_size_half_pts)
    else:
        if runs:
            t_el = runs[0].find(f"{WNS}t")
            if t_el is None:
                t_el = etree.SubElement(runs[0], f"{WNS}t")
            t_el.text = str(replacement)
            t_el.set(f"{WNS}space", "preserve")
            if original_chars and base_size_half_pts:
                _scale_run_font(runs[0], len(str(replacement)), original_chars, base_size_half_pts)
            for run in runs[1:]:
                for t in run.findall(f"{WNS}t"):
                    t.text = ""


def _scale_run_font(run, new_chars: int, original_chars: int, base_size_half_pts: int):
    """Scale a run's font size inversely proportional to text length.
    
    Formula: new_size = base_size * (original_chars / new_chars)
    Clamped: min 60% of base, max 100% of base.
    """
    if new_chars <= original_chars:
        return  # No scaling needed — text fits
    
    ratio = original_chars / new_chars
    ratio = max(0.6, min(1.0, ratio))  # Clamp 60%-100%
    new_size = int(base_size_half_pts * ratio)
    
    # Set or update <w:sz> in run properties
    rpr = run.find(f"{WNS}rPr")
    if rpr is None:
        rpr = etree.SubElement(run, f"{WNS}rPr")
        run.insert(0, rpr)  # rPr must be first child
    sz = rpr.find(f"{WNS}sz")
    if sz is None:
        sz = etree.SubElement(rpr, f"{WNS}sz")
    sz.set(f"{WNS}val", str(new_size))
    # Also set szCs (complex script size) to match
    szcs = rpr.find(f"{WNS}szCs")
    if szcs is None:
        szcs = etree.SubElement(rpr, f"{WNS}szCs")
    szcs.set(f"{WNS}val", str(new_size))


def _fill_non_empty_runs(runs, entries):
    """Fill only non-empty runs with entries in order."""
    ni = 0
    for run in runs:
        t_el = run.find(f"{WNS}t")
        if t_el is not None and t_el.text and t_el.text.strip():
            t_el.text = entries[ni] if ni < len(entries) else ""
            ni += 1


def _remove_plc_flag(sdt_pr):
    """Remove showingPlcHdr flag."""
    plc = sdt_pr.find(f"{WNS}showingPlcHdr")
    if plc is not None:
        sdt_pr.remove(plc)


def _fill_bib_table(table, entries):
    """Fill bibliography table, clearing all text in each cell."""
    rows = table.findall(f".//{WNS}tr")
    for ri, row in enumerate(rows):
        cells = row.findall(f"{WNS}tc")
        entry_idx = ri * 2
        for ci, cell in enumerate(cells):
            all_t = cell.findall(f".//{WNS}t")
            if ci == 0 and entry_idx < len(entries):
                for ti, t in enumerate(all_t):
                    t.text = entries[entry_idx] if ti == 0 else ""
            elif ci == 2 and entry_idx + 1 < len(entries):
                for ti, t in enumerate(all_t):
                    t.text = entries[entry_idx + 1] if ti == 0 else ""
            else:
                for t in all_t:
                    t.text = ""


def _fill_index_table(table, entries):
    """Fill index table cells with entries."""
    all_t = table.findall(f".//{WNS}t")
    ei = 0
    for t in all_t:
        if t.text and t.text.strip():
            t.text = entries[ei] if ei < len(entries) else ""
            ei += 1
