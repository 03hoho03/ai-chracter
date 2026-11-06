"""측정 서버 스키마와 서비스가 읽는 묶음 칸의 대조.

서비스는 측정 서버 코드를 import 하지 않는다. 측정 서버가 떨군 `apps/chat-lab/openapi.json` 을 JSON 으로 읽어, 서비스가
읽는 칸이 그 스키마에 그대로 있는지와 테스트의 합성 묶음·올리기 머리가 그 스키마를 따르는지를 본다. 측정 서버가 칸 이름이나
형식 값을 바꾸면 이 대조가 먼저 깨진다.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import pytest

from bundles import PROVENANCE_FIELDS, make_bundle, to_json, upload_bundle, upload_header
from harness import MEASUREMENT_OPENAPI, Lab


@cache
def schemas() -> dict[str, Any]:
    document = json.loads(MEASUREMENT_OPENAPI.read_text(encoding="utf-8"))
    components: dict[str, Any] = document["components"]["schemas"]
    return components


def resolve(schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    prefix = "#/components/schemas/"
    assert ref.startswith(prefix), ref
    return resolve(schemas()[ref.removeprefix(prefix)])


def property_of(name: str, field: str) -> dict[str, Any]:
    schema = schemas()[name]
    assert field in schema["properties"], f"{name}.{field} 가 측정 서버 스키마에 없다"
    return resolve(schema["properties"][field])


def types_of(schema: dict[str, Any]) -> set[str]:
    schema = resolve(schema)
    if "anyOf" in schema:
        return set().union(*(types_of(option) for option in schema["anyOf"]))
    if "type" in schema:
        return {schema["type"]}
    return {"object"} if "properties" in schema else set()


def is_required(name: str, field: str) -> bool:
    return field in schemas()[name].get("required", [])


# 서비스가 올리기 때 읽고 검사하는 칸 — (스키마, 칸, 받아들이는 JSON 타입, 필수인가).
FIELDS_THE_SERVICE_READS = [
    ("RunBundle", "contractVersion", {"integer"}, True),
    ("RunBundle", "raw", {"boolean"}, True),
    ("RunBundle", "detail", {"object"}, True),
    ("RunDetail", "run", {"object"}, True),
    ("RunListItem", "runId", {"string"}, True),
    ("RunListItem", "format", {"string"}, True),
    ("UploadHeader", "sourceCommit", {"object"}, True),
    ("UploadHeader", "provenance", {"object"}, True),
    ("SourceCommit", "commit", {"string"}, True),
    ("SourceCommit", "dirty", {"boolean"}, True),
    ("Provenance", "passed", {"boolean"}, True),
    ("Provenance", "baseLocal", {"boolean", "null"}, True),
    ("Provenance", "roomFound", {"boolean"}, True),
    ("Provenance", "ownerInExampleDomain", {"boolean"}, True),
    ("Provenance", "outsideUsers", {"integer"}, True),
    ("Provenance", "exemptedUsers", {"integer"}, True),
    ("Provenance", "authorInExampleDomain", {"boolean", "null"}, True),
]


@pytest.mark.parametrize(("name", "field", "json_types", "required"), FIELDS_THE_SERVICE_READS)
def test_fields_the_service_reads_exist_in_measurement_schema(
    name: str, field: str, json_types: set[str], required: bool
) -> None:
    assert types_of(property_of(name, field)) == json_types
    assert is_required(name, field) is required


def test_schema_links_bundle_to_run_list_item() -> None:
    assert schemas()["RunBundle"]["properties"]["detail"] == {"$ref": "#/components/schemas/RunDetail"}
    assert schemas()["RunDetail"]["properties"]["run"] == {"$ref": "#/components/schemas/RunListItem"}
    assert schemas()["UploadHeader"]["properties"]["sourceCommit"] == {"$ref": "#/components/schemas/SourceCommit"}
    assert schemas()["UploadHeader"]["properties"]["provenance"] == {"$ref": "#/components/schemas/Provenance"}


def test_provenance_fields_match_measurement_schema() -> None:
    # 서비스는 알려진 출처 칸만 저장한다 — 그 목록이 측정 서버의 칸 목록과 같아야 칸이 조용히 빠지지 않는다.
    assert set(schemas()["Provenance"]["properties"]) == set(PROVENANCE_FIELDS)


def test_measurement_formats_are_the_ones_the_service_decides_on() -> None:
    # 서비스는 `current`·`preMessageId` 를 받고 `legacy` 를 거부한다. 측정 서버가 형식을 더하면 서비스의 판정을 정해야 한다.
    assert set(property_of("RunListItem", "format")["enum"]) == {"current", "preMessageId", "legacy"}


def check(value: Any, schema: dict[str, Any], where: str) -> list[str]:
    """측정 서버 스키마가 쓰는 꼴(`$ref`·`anyOf`·`type`·`enum`·`const`·`properties`·`required`·`items`)만 보는 작은 대조."""
    schema = resolve(schema)
    if "anyOf" in schema:
        failures = [check(value, option, where) for option in schema["anyOf"]]
        return [] if any(not failure for failure in failures) else [f"{where}: anyOf 어느 것에도 맞지 않는다"]
    problems: list[str] = []
    if "const" in schema and value != schema["const"]:
        problems.append(f"{where}: const {schema['const']!r} 가 아니다")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} 가 enum 밖이다")
    expected = schema.get("type")
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if expected is not None and not matches[expected]:
        return [*problems, f"{where}: {expected} 가 아니다"]
    if isinstance(value, dict):
        for field in schema.get("required", []):
            if field not in value:
                problems.append(f"{where}.{field}: 필수 칸이 없다")
        for field, sub in schema.get("properties", {}).items():
            if field in value:
                problems += check(value[field], sub, f"{where}.{field}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problems += check(item, schema["items"], f"{where}[{index}]")
    return problems


@pytest.mark.parametrize("raw", [True, False], ids=["raw", "redacted"])
def test_synthetic_bundle_follows_measurement_schema(raw: bool) -> None:
    bundle = make_bundle("run-shape", raw=raw)
    assert check(bundle, schemas()["RunBundle"], "RunBundle") == []
    # 합성 묶음도 직렬화한 바이트 그대로가 판 키이므로 JSON 으로 다시 읽어도 같은 값이어야 한다.
    assert json.loads(to_json(bundle)) == bundle


def test_synthetic_upload_header_follows_measurement_schema() -> None:
    assert check(upload_header(), schemas()["UploadHeader"], "UploadHeader") == []


@pytest.mark.parametrize("fmt", ["current", "preMessageId"])
async def test_every_non_legacy_format_in_schema_is_accepted(lab: Lab, fmt: str) -> None:
    assert fmt in property_of("RunListItem", "format")["enum"]
    response, _, _ = await upload_bundle(lab.client, make_bundle(f"run-{fmt}", fmt=fmt))
    assert response.status_code == 201, response.text
