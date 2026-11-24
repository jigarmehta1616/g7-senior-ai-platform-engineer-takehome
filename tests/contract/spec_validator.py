"""Validates live responses against openapi.yaml (OpenAPI 3.1 == JSON Schema 2020-12).

Small on purpose: resolve the operation by path template, pick the declared response for
the status code, check the media type, validate the body schema with $refs resolved
inside the spec document."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi.yaml"
SPEC_URI = "urn:support-platform:openapi"


@cache
def load_spec() -> dict[str, Any]:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


@cache
def _registry() -> Registry:
    return Registry().with_resource(SPEC_URI, Resource.from_contents(load_spec(), default_specification=DRAFT202012))


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _deref(node: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Follow a component $ref (responses etc.). Returns (node, json-pointer)."""
    spec = load_spec()
    pointer = ""
    while "$ref" in node:
        pointer = node["$ref"].lstrip("#")
        cur: Any = spec
        for part in pointer.strip("/").split("/"):
            cur = cur[part.replace("~1", "/").replace("~0", "~")]
        node = cur
    return node, pointer


def path_templates() -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for template in load_spec()["paths"]:
        regex = "^" + re.sub(r"\{[^/]+\}", "[^/]+", template) + "$"
        out.append((template, re.compile(regex)))
    return out


def find_template(path: str) -> str:
    matches = [t for t, rx in path_templates() if rx.match(path)]
    assert matches, f"{path} is not declared in openapi.yaml"
    return min(matches, key=lambda t: t.count("{"))   # prefer literal segments


class ContractViolation(AssertionError):
    pass


def validate_response(resp: httpx.Response) -> None:
    method = resp.request.method.lower()
    template = find_template(resp.request.url.path)
    op = load_spec()["paths"][template].get(method)
    if op is None:
        raise ContractViolation(f"{method.upper()} {template} not in spec")
    responses = op["responses"]
    code = str(resp.status_code)
    key = code if code in responses else f"{code[0]}XX" if f"{code[0]}XX" in responses else "default"
    if key not in responses:
        raise ContractViolation(f"{method.upper()} {template} -> undeclared status {code}: {resp.text[:300]}")
    response_obj, response_ptr = _deref(responses[key])
    if not response_ptr:
        response_ptr = f"/paths/{_escape(template)}/{method}/responses/{key}"
    content = response_obj.get("content")
    if not content:
        if resp.content and resp.status_code != 304:
            raise ContractViolation(f"{template} {code}: body returned but none declared")
        return
    media = resp.headers.get("content-type", "").split(";")[0].strip()
    if media not in content:
        raise ContractViolation(f"{template} {code}: media type {media!r} not in {list(content)}")
    schema_ptr = f"{response_ptr}/content/{_escape(media)}/schema"
    validator = Draft202012Validator({"$ref": f"{SPEC_URI}#{schema_ptr}"}, registry=_registry(),
                                     format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(resp.json()), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
        raise ContractViolation(f"{method.upper()} {template} {code} violates schema: {detail}")


def validate_event(event: dict[str, Any]) -> None:
    validator = Draft202012Validator({"$ref": f"{SPEC_URI}#/components/schemas/CaseEscalatedEvent"},
                                     registry=_registry())
    errors = list(validator.iter_errors(event))
    if errors:
        raise ContractViolation("; ".join(e.message for e in errors[:5]))
