"""Auto-classify documents by reading their content.

Uses a tiered approach:
  1. Structural patterns (phrases that only appear in specific doc types)
  2. Filename hints
  3. Keyword density scoring across the full text

No API calls, no cost. Runs locally and instantly.
"""

from __future__ import annotations

import re

# Each rule: (category, document_type, patterns_in_text, filename_hints)
# Patterns are checked against the first 3000 chars of extracted text.
# More specific patterns go first so they match before generic ones.

_RULES: list[tuple[str, str, list[str], list[str]]] = [
    # -- Closing Documents --
    ("Closing Documents", "closing_disclosure",
     ["closing disclosure", "loan estimate", "projected payments"],
     ["closing disclosure"]),

    ("Closing Documents", "deed",
     ["deed of trust", "deed of conveyance", "grantor", "grantee", "trustee"],
     ["deed"]),

    ("Closing Documents", "note",
     ["promissory note", "fixed rate note", "interest rate", "monthly payment", "note holder"],
     ["note 2021", "fixed rate note"]),

    ("Closing Documents", "loan_application",
     ["uniform residential loan application", "1003"],
     ["1003", "loan application"]),

    ("Closing Documents", "loan_analysis",
     ["va loan analysis", "loan summary sheet", "loan disbursement"],
     ["loan analysis", "loan summary", "disbursement"]),

    ("Closing Documents", "escrow",
     ["escrow account", "escrow disclosure", "escrow analysis"],
     ["escrow"]),

    ("Closing Documents", "amortization",
     ["amortization schedule", "payment schedule", "principal", "interest", "balance"],
     ["amortization"]),

    ("Closing Documents", "title",
     ["title insurance", "title commitment", "title company"],
     ["title"]),

    ("Closing Documents", "closing_instructions",
     ["closing instructions", "settlement statement", "closing agent"],
     ["closing instruction"]),

    ("Closing Documents", "closing_misc",
     ["compliance agreement", "servicing transfer", "first payment letter",
      "patriot act", "occupancy statement", "e-close", "hybrid eclose",
      "signature-name affidavit", "nearest living relative",
      "lender loan quality", "taxpayer consent"],
     ["compliance", "servicing transfer", "first payment", "patriot act",
      "occupancy", "eclose", "affidavit", "nearest living",
      "loan quality", "taxpayer consent", "fact act"]),

    # -- HOA / Governance --
    ("HOA Governance", "bylaws",
     ["bylaws", "by-laws", "board of directors shall", "annual meeting of members"],
     ["bylaws", "by-laws"]),

    ("HOA Governance", "ccrs",
     ["declaration of covenants", "covenants, conditions", "cc&r", "declaration of protective"],
     ["declaration", "cc&r", "covenants"]),

    ("HOA Governance", "rules_and_regulations",
     ["rules and regulations", "community rules", "violation notice"],
     ["rules and regulations", "rules_and_regulations"]),

    ("HOA Governance", "architectural_guidelines",
     ["architectural review", "exterior modification", "architectural guidelines",
      "architectural review board", "arb"],
     ["architectural"]),

    ("HOA Governance", "articles_of_incorporation",
     ["articles of incorporation", "certificate of incorporation"],
     ["articles of incorporation"]),

    ("HOA Governance", "resolutions",
     ["resolution", "board resolution", "adopted by the board"],
     ["resolution"]),

    ("HOA Governance", "meeting_minutes",
     ["meeting minutes", "board meeting", "association meeting", "minutes of"],
     ["meeting minutes", "board meeting", "association meeting"]),

    ("HOA Governance", "hoa_misc",
     ["homeowners association", "homeowner association", "hoa",
      "community association", "annual registration"],
     ["hoa", "annual registration", "new owner forms"]),

    # -- Financial --
    ("HOA Financial", "budget",
     ["annual budget", "operating budget", "budget summary"],
     ["budget"]),

    ("HOA Financial", "financial_statement",
     ["balance sheet", "income statement", "expense statement", "financial statement"],
     ["balance sheet", "income", "expense"]),

    ("HOA Financial", "reserve_study",
     ["reserve study", "reserve fund", "replacement reserve"],
     ["reserve study"]),

    ("HOA Financial", "audit",
     ["audited financial", "independent auditor", "audit report"],
     ["audit"]),

    ("HOA Financial", "assessment",
     ["special assessment", "assessment notice", "assessment schedule"],
     ["assessment"]),

    ("HOA Financial", "resale_certificate",
     ["resale certificate", "resale disclosure"],
     ["resale certificate"]),

    # -- Insurance --
    ("Insurance", "insurance_policy",
     ["insurance dec page", "insurance policy", "coverage info", "policy number",
      "replacement cost", "hazard insurance", "homeowner and fire"],
     ["insurance", "coverage", "hazard", "replacement cost"]),

    # -- Inspection --
    ("Inspection", "inspection_report",
     ["inspection report", "property inspection", "wdi", "wood destroying",
      "termite", "pest inspection", "compliance inspection"],
     ["inspection", "wdi"]),

    # -- Appraisal --
    ("Appraisal", "appraisal",
     ["appraisal report", "uniform residential appraisal", "appraised value",
      "market value", "comparable sale"],
     ["appraisal"]),

    # -- Tax --
    ("Tax & Legal", "tax",
     ["tax return", "tax information", "w-9", "8821", "taxpayer identification",
      "tax authorization", "credit score disclosure"],
     ["tax", "w-9", "8821", "credit score"]),

    ("Tax & Legal", "va_document",
     ["va amendment", "va rider", "va loan", "department of veterans"],
     ["va amendment", "va rider", "va loan"]),

    # -- Wire / Payment --
    ("Payments & Transfers", "wire",
     ["wire transfer", "wire fraud", "wire instruction", "wire detail"],
     ["wire"]),

    ("Payments & Transfers", "payment",
     ["payment confirmation", "payment receipt", "direct pay"],
     ["receipt", "payment"]),

    # -- Mortgage --
    ("Mortgage", "mortgage_statement",
     ["mortgagee statement", "mortgage statement", "loan servicer"],
     ["mortgagee", "mortgage statement"]),

    ("Mortgage", "pud_rider",
     ["pud rider", "planned unit development"],
     ["pud rider"]),
]


def classify_document(filename: str, text: str) -> tuple[str, str, list[str]]:
    """Classify a document and return (category, document_type, tags).

    Reads the filename and first 3000 chars of text to determine
    what kind of document this is and which category it belongs to.
    """
    probe_text = text[:3000].lower()
    probe_name = filename.lower()

    # Pass 1: check text patterns (most reliable)
    for category, doc_type, text_patterns, _ in _RULES:
        for pattern in text_patterns:
            if pattern in probe_text:
                tags = _extract_tags(probe_text, doc_type)
                return category, doc_type, tags

    # Pass 2: check filename hints
    for category, doc_type, _, name_hints in _RULES:
        for hint in name_hints:
            if hint in probe_name:
                tags = _extract_tags(probe_text, doc_type)
                return category, doc_type, tags

    # Pass 3: nothing matched
    tags = _extract_tags(probe_text, "general")
    return "Uncategorized", "general", tags


def _extract_tags(text: str, doc_type: str) -> list[str]:
    """Pull useful tags from the document text."""
    tags = [doc_type]

    # Look for common identifiers
    if "centerpointe" in text:
        tags.append("centerpointe")
    if "12133 tribune" in text:
        tags.append("12133-tribune-st")
    if re.search(r"va\s+(loan|fixed|rider|amendment)", text):
        tags.append("va-loan")
    if "zillow" in text or "zhl" in text:
        tags.append("zillow-home-loans")

    return list(dict.fromkeys(tags))  # dedupe preserving order
