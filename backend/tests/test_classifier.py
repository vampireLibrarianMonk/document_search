"""Tests for the LLM-based document classifier.

Mocks Bedrock calls to verify the classification logic without API costs.
"""

import os
from unittest.mock import patch, MagicMock

from app.classifier import classify_document

# Ensure a model ID is set for tests that mock Bedrock
_TEST_ENV = {"BEDROCK_MODEL_ID": "test-model"}


def _mock_bedrock_response(category: str, doc_type: str, tags: list[str], title: str = "", document_date: str = ""):
    """Create a mock Bedrock converse response."""
    import json
    return {
        "output": {"message": {"content": [{"text": json.dumps({
            "category": category,
            "document_type": doc_type,
            "tags": tags,
            "title": title,
            "document_date": document_date or None,
        })}]}},
        "usage": {"inputTokens": 100, "outputTokens": 50},
    }


@patch.dict("os.environ", _TEST_ENV)
@patch("app.classifier._get_existing_categories", return_value=[])
@patch("app.classifier._get_bedrock")
def test_classifies_document(mock_bedrock, mock_cats):
    mock_bedrock.return_value.converse.return_value = _mock_bedrock_response(
        "Vehicle Maintenance", "invoice", ["oil-change", "toyota"], "Oil Change Invoice - Toyota Dealership"
    )
    cat, dtype, tags, title, doc_date = classify_document("oil_change_receipt.pdf", "Oil change service performed on 2024 Toyota")
    assert cat == "Vehicle Maintenance"
    assert dtype == "invoice"
    assert "oil-change" in tags
    assert title == "Oil Change Invoice - Toyota Dealership"


@patch.dict("os.environ", _TEST_ENV)
@patch("app.classifier._get_existing_categories", return_value=["Vehicle Maintenance", "Insurance"])
@patch("app.classifier._get_bedrock")
def test_existing_categories_passed_to_prompt(mock_bedrock, mock_cats):
    mock_bedrock.return_value.converse.return_value = _mock_bedrock_response(
        "Insurance", "insurance_policy", ["auto"], "Auto Insurance Policy - State Farm"
    )
    classify_document("policy.pdf", "Auto insurance policy coverage")
    call_args = mock_bedrock.return_value.converse.call_args
    prompt_text = call_args[1]["messages"][0]["content"][0]["text"]
    assert "Vehicle Maintenance" in prompt_text
    assert "Insurance" in prompt_text


@patch.dict("os.environ", _TEST_ENV)
@patch("app.classifier._get_existing_categories", return_value=[])
@patch("app.classifier._get_bedrock")
def test_falls_back_on_error(mock_bedrock, mock_cats):
    mock_bedrock.return_value.converse.side_effect = Exception("API error")
    cat, dtype, tags, title, doc_date = classify_document("test.pdf", "some text")
    assert cat == "Uncategorized"
    assert dtype == "general"
    assert title == ""


@patch.dict("os.environ", {"BEDROCK_MODEL_ID": ""}, clear=False)
@patch.dict("os.environ", {"BEDROCK_CLASSIFY_MODEL_ID": ""}, clear=False)
def test_falls_back_when_no_model_configured():
    cat, dtype, tags, title, doc_date = classify_document("test.pdf", "some text")
    assert cat == "Uncategorized"
    assert dtype == "general"
    assert title == ""


@patch.dict("os.environ", _TEST_ENV)
@patch("app.classifier._get_existing_categories", return_value=[])
@patch("app.classifier._get_bedrock")
def test_handles_markdown_wrapped_json(mock_bedrock, mock_cats):
    mock_bedrock.return_value.converse.return_value = {
        "output": {"message": {"content": [{"text": '```json\n{"category": "Medical", "document_type": "lab_results", "tags": ["blood-work"], "title": "Complete Blood Count Results"}\n```'}]}},
        "usage": {"inputTokens": 100, "outputTokens": 50},
    }
    cat, dtype, tags, title, doc_date = classify_document("labs.pdf", "Complete blood count results")
    assert cat == "Medical"
    assert dtype == "lab_results"
    assert title == "Complete Blood Count Results"


@patch.dict("os.environ", _TEST_ENV)
@patch("app.classifier._get_existing_categories", return_value=[])
@patch("app.classifier._get_bedrock")
def test_normalizes_document_type(mock_bedrock, mock_cats):
    mock_bedrock.return_value.converse.return_value = _mock_bedrock_response(
        "Tax & Legal", "Tax Return 2024", ["taxes"], "2024 Federal Tax Return"
    )
    cat, dtype, tags, title, doc_date = classify_document("1040.pdf", "Form 1040 tax return")
    assert cat == "Tax & Legal"
    assert dtype == "tax_return_2024"  # normalized to snake_case


@patch.dict("os.environ", _TEST_ENV)
@patch("app.classifier._get_existing_categories", return_value=[])
@patch("app.classifier._get_bedrock")
def test_limits_tags_to_five(mock_bedrock, mock_cats):
    mock_bedrock.return_value.converse.return_value = _mock_bedrock_response(
        "General", "report", ["a", "b", "c", "d", "e", "f", "g"], "Some Report"
    )
    _, _, tags, _, _ = classify_document("report.pdf", "some report")
    assert len(tags) <= 5
