"""Turn command-line tool arguments into a JSON object, whatever shell they came from.

Three accepted forms, so nobody has to fight their shell's quoting rules:

    key=value pairs     priority=P1 support_tier=Platinum min_open_hours=48
    a JSON file         @mcp/demo/examples/sample_question.json   (or @- for stdin)
    inline JSON         '{"priority":["P1"]}'   (bash / PowerShell 7 only)

key=value values are converted using the tool's input schema: integers become numbers, arrays
are comma-separated (priority=P1,P2), booleans accept true/false.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FORMS_HELP = (
    "Pass tool arguments in one of these forms:\n"
    "  key=value pairs   priority=P1 support_tier=Platinum min_open_hours=48 renewal_within_days=90\n"
    "  a JSON file       @mcp/demo/examples/sample_question.json\n"
    "  inline JSON       '{\"priority\":[\"P1\"]}'   (works in bash and PowerShell 7, not in Command Prompt)"
)


class ArgumentError(ValueError):
    """Bad command-line arguments; the message is meant to be shown to the user as-is."""


def _effective_schema(prop: dict[str, Any]) -> dict[str, Any]:
    """Unwrap Optional[...] (``anyOf: [X, {type: null}]``) to X."""
    for option in prop.get("anyOf", []):
        if isinstance(option, dict) and option.get("type") != "null":
            return option
    return prop


def _coerce_scalar(key: str, value: str, schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
    except ValueError as exc:
        article = "an" if kind == "integer" else "a"
        raise ArgumentError(f"'{key}' must be {article} {kind}, got '{value}'.") from exc
    if kind == "boolean":
        lowered = value.lower()
        if lowered not in ("true", "false"):
            raise ArgumentError(f"'{key}' must be true or false, got '{value}'.")
        return lowered == "true"
    return value


def _coerce(key: str, value: str, prop: dict[str, Any] | None) -> Any:
    if prop is None:  # no schema available: best effort
        try:
            return json.loads(value)
        except ValueError:
            return value
    schema = _effective_schema(prop)
    if schema.get("type") == "array":
        items = schema.get("items", {})
        return [_coerce_scalar(key, part.strip(), items) for part in value.split(",") if part.strip()]
    return _coerce_scalar(key, value, schema)


def _load_json(text: str, source: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        hint = ""
        if text.startswith("'") or (text.startswith("{") and '"' not in text):
            hint = ("\nYour shell seems to have removed the double quotes (Command Prompt does this). "
                    "Use key=value pairs or an @file instead.")
        raise ArgumentError(
            f"Couldn't read {source} as JSON: {exc.msg}.\nReceived: {text}{hint}\n\n{FORMS_HELP}"
        ) from exc
    if not isinstance(data, dict):
        raise ArgumentError(f"{source} must be a JSON object like {{\"case_id\": \"CS-10231\"}}.")
    return data


def parse_tool_arguments(raw: list[str], input_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse the words after the tool name. ``input_schema`` is the tool's JSON schema, if known."""
    if not raw:
        return {}
    if len(raw) == 1 and raw[0].startswith("@"):
        target = raw[0][1:]
        if target == "-":
            return _load_json(sys.stdin.read(), "standard input")
        path = Path(target)
        if not path.is_file():
            raise ArgumentError(f"Arguments file not found: {path}")
        return _load_json(path.read_text(encoding="utf-8"), str(path))
    if len(raw) == 1 and "=" not in raw[0].split(":", 1)[0]:
        return _load_json(raw[0].strip(), "the arguments")

    properties: dict[str, Any] = (input_schema or {}).get("properties", {})
    parsed: dict[str, Any] = {}
    for item in raw:
        key, sep, value = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise ArgumentError(f"Expected key=value, got '{item}'.\n\n{FORMS_HELP}")
        if properties and key not in properties:
            raise ArgumentError(f"Unknown argument '{key}'. This tool accepts: {', '.join(sorted(properties))}.")
        parsed[key] = _coerce(key, value, properties.get(key) if properties else None)
    return parsed
