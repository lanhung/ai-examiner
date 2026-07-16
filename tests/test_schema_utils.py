import pytest

from ai_examiner.providers.schema_utils import parse_json_object


def test_parse_json_object_accepts_valid_json():
    assert parse_json_object('{"cases": [{"id": "Q1"}]}') == {
        "cases": [{"id": "Q1"}]
    }


def test_parse_json_object_extracts_fenced_json():
    text = '```json\n{"cases": []}\n```'
    assert parse_json_object(text) == {"cases": []}


def test_parse_json_object_repairs_missing_comma_between_cases():
    text = """{
      "cases": [
        {"id": "Q1", "question": "First question"}
        {"id": "Q2", "question": "Second question"}
      ]
    }"""
    assert parse_json_object(text) == {
        "cases": [
            {"id": "Q1", "question": "First question"},
            {"id": "Q2", "question": "Second question"},
        ]
    }


def test_parse_json_object_rejects_non_object_response():
    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object("not JSON")
