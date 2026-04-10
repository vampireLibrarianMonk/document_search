"""Tests for the document classifier.

Makes sure documents get sorted into the right categories based on
their filename and content. No API calls needed, runs instantly.
"""

from app.classifier import classify_document


def test_closing_disclosure():
    cat, dtype, _ = classify_document(
        "Closing Disclosure.pdf",
        "closing disclosure projected payments loan terms",
    )
    assert cat == "Closing Documents"
    assert dtype == "closing_disclosure"


def test_deed_of_trust():
    cat, dtype, _ = classify_document(
        "3047 VA Deed of Trust 2021.pdf",
        "deed of trust grantor grantee trustee",
    )
    assert cat == "Closing Documents"
    assert dtype == "deed"


def test_bylaws():
    cat, dtype, _ = classify_document(
        "Appendix 02Bylaws.pdf",
        "bylaws board of directors annual meeting of members",
    )
    assert cat == "HOA Governance"
    assert dtype == "bylaws"


def test_architectural_guidelines():
    cat, dtype, _ = classify_document(
        "Appendix 02Architectural Guidelines.pdf",
        "architectural review board exterior modification application",
    )
    assert cat == "HOA Governance"
    assert dtype == "architectural_guidelines"


def test_appraisal():
    cat, dtype, _ = classify_document(
        "APPRAISAL-1.pdf",
        "uniform residential appraisal report market value comparable sale",
    )
    assert cat == "Appraisal"
    assert dtype == "appraisal"


def test_insurance():
    cat, dtype, _ = classify_document(
        "Insurance Dec Page.pdf",
        "insurance dec page policy number coverage info replacement cost",
    )
    assert cat == "Insurance"
    assert dtype == "insurance_policy"


def test_tax_document():
    cat, dtype, _ = classify_document(
        "W-9 Taxpayer ID.pdf",
        "w-9 taxpayer identification number",
    )
    assert cat == "Tax & Legal"
    assert dtype == "tax"


def test_wire_transfer():
    cat, dtype, _ = classify_document(
        "Wire Fraud Education.pdf",
        "wire fraud wire transfer wire instruction",
    )
    assert cat == "Payments & Transfers"
    assert dtype == "wire"


def test_resale_certificate():
    cat, dtype, _ = classify_document(
        "Resale Certificate.pdf",
        "resale certificate managing agent disclosure",
    )
    assert cat == "HOA Financial"
    assert dtype == "resale_certificate"


def test_unknown_document_falls_back_to_general():
    cat, dtype, _ = classify_document(
        "random_notes.pdf",
        "nothing special here just some random text about lunch",
    )
    assert cat == "Uncategorized"
    assert dtype == "general"


def test_filename_hint_works_when_text_has_no_match():
    """If the text doesn't match any rules, the filename should still catch it."""
    cat, dtype, _ = classify_document(
        "APPRAISAL-2.pdf",
        "some generic text with no keywords",
    )
    assert cat == "Appraisal"
    assert dtype == "appraisal"


def test_tags_include_document_type():
    _, dtype, tags = classify_document(
        "Bylaws.pdf",
        "bylaws board of directors",
    )
    assert dtype in tags


def test_tags_detect_va_loan():
    _, _, tags = classify_document(
        "VA Fixed Rate Note.pdf",
        "va fixed rate note monthly payment",
    )
    assert "va-loan" in tags
