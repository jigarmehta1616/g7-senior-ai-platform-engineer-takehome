"""The demo CLI's argument parsing, including what Command Prompt does to inline JSON."""

from __future__ import annotations

import pytest

from support_copilot.cli_args import ArgumentError, parse_tool_arguments

SEARCH_SCHEMA = {
    "properties": {
        "priority": {"anyOf": [{"type": "array", "items": {"enum": ["P1", "P2", "P3"], "type": "string"}},
                               {"type": "null"}]},
        "support_tier": {"anyOf": [{"enum": ["Platinum", "Gold"], "type": "string"}, {"type": "null"}]},
        "min_open_hours": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "limit": {"type": "integer"},
    }
}


def test_key_value_pairs_are_coerced_using_the_schema():
    args = ["priority=P1,P2", "support_tier=Platinum", "min_open_hours=48", "limit=5"]
    assert parse_tool_arguments(args, SEARCH_SCHEMA) == {
        "priority": ["P1", "P2"], "support_tier": "Platinum", "min_open_hours": 48, "limit": 5}


def test_inline_json_still_works():
    assert parse_tool_arguments(['{"case_id": "CS-10280"}']) == {"case_id": "CS-10280"}


def test_json_file(tmp_path):
    f = tmp_path / "args.json"
    f.write_text('{"priority": ["P1"]}', encoding="utf-8")
    assert parse_tool_arguments([f"@{f}"]) == {"priority": ["P1"]}


def test_command_prompt_mangled_json_gets_a_helpful_message():
    # What cmd.exe actually delivers for '{"priority":["P1"]}'
    with pytest.raises(ArgumentError, match="Command Prompt"):
        parse_tool_arguments(["'{priority:[P1]}'"])


@pytest.mark.parametrize(("args", "message"), [
    (["min_open_hours=soon"], "must be an integer"),
    (["colour=blue"], "Unknown argument 'colour'"),
    (["@does-not-exist.json"], "not found"),
    (["justaword", "another"], "Expected key=value"),
])
def test_bad_arguments_explain_themselves(args, message):
    with pytest.raises(ArgumentError, match=message):
        parse_tool_arguments(args, SEARCH_SCHEMA)


def test_no_arguments_is_an_empty_object():
    assert parse_tool_arguments([]) == {}
