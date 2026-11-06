"""올리기 요청의 머리·계약 판·묶음 모양 검사와 크기 상한(압축 바이트·푼 크기·압축 폭탄).

거부된 올리기는 판을 남기지 않고, 응답의 `reason` 과 같은 이유가 접근 기록에 남는다.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

import httpx
import pytest

from bundles import (
    COMMIT_A,
    COMMIT_B,
    COMMIT_SHA256,
    PROVENANCE_FIELDS,
    UPLOAD_HEADER,
    TrackedBody,
    bundle_json_of_size,
    gz,
    gzip_bomb,
    gzip_of_exact_size,
    header_value,
    make_bundle,
    post_upload,
    provenance,
    sha256_hex,
    to_json,
    upload_header,
)
from chat_lab_service.bundles import _INFLATE_INPUT as INFLATE_WINDOW
from harness import (
    COMPRESSED_LIMIT,
    MIB,
    UNCOMPRESSED_LIMIT,
    Db,
    Lab,
    assert_error,
    measure_peak,
)
from keys import TOKEN_HEADER, auth, human_token, service_token

RUN = "run-upload"

# 받아지는 올리기 한 번의 정점 상한. 압축 버퍼(≤8MiB) + 푼 버퍼 + 그 바이트 사본 + 디코드한 문자열 + 파싱한 객체가
# 한꺼번에 살아 있어도 푼 상한의 4.25배이므로, 할당기 여유를 더해 5배로 둔다(160MiB — 512MiB 컨테이너 안에서 앱 기본
# 사용량을 더해도 남는 선). 이 선을 넘으면 푼 상한을 낮출지 컨테이너 메모리를 올릴지 정해야 한다.
ACCEPTED_PEAK_LIMIT = 5 * UNCOMPRESSED_LIMIT
# 압축 폭탄은 푼 누계가 상한을 넘는 순간 멈추고 디코드·파싱에 가지 않으므로 푼 버퍼 하나(상한 + 조각 하나)만 남는다.
# 버퍼 하나의 사본이 더 생기면 넘는 선이다.
BOMB_PEAK_LIMIT = 2 * UNCOMPRESSED_LIMIT


async def assert_upload_rejected(db: Db, response: httpx.Response, status: int, reason: str) -> None:
    assert_error(response, status, reason)
    row = await db.last_access_row()
    assert (row["status"], row["reason"], row["route"]) == (status, reason, "/api/runs/{runId}/versions")
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 0


async def upload_json(lab: Lab, data: bytes, **kwargs: Any) -> httpx.Response:
    return await post_upload(lab.client, RUN, gz(data), **kwargs)


def unread_body() -> TrackedBody:
    return TrackedBody(b"\x1f\x8b", chunk_size=MIB, chunk_count=9)


def report_peak(name: str, peak: int, limit: int) -> None:
    # `-s` 없이도 실패한 테스트의 캡처 출력에 남는다.
    print(f"{name}: 메모리 정점 {peak / MIB:.1f}MiB (상한 {limit / MIB:.0f}MiB)")


# --- 올리기 머리 -------------------------------------------------------------------------------------------------


async def test_missing_upload_header_is_422(lab: Lab, db: Db) -> None:
    # 머리는 본문보다 먼저 본다 — 선언 길이가 상한을 넘어도 413 이 아니라 422 이고, 본문은 한 조각도 읽지 않는다.
    body = unread_body()
    response = await post_upload(
        lab.client, RUN, body, send_header=False, extra_headers={"Content-Length": str(COMPRESSED_LIMIT + 1)}
    )
    await assert_upload_rejected(db, response, 422, "noUploadHeader")
    assert body.pulled == 0


@pytest.mark.parametrize(
    "header",
    [
        "not json",
        "[]",
        "{}",
        '{"sourceCommit": {"commit": "' + COMMIT_A + '"}, "provenance": {}}',
    ],
    ids=["not-json", "array", "empty-object", "missing-fields"],
)
async def test_upload_header_with_wrong_shape_is_422(lab: Lab, db: Db, header: str) -> None:
    body = unread_body()
    response = await post_upload(lab.client, RUN, body, header=header)
    await assert_upload_rejected(db, response, 422, "badUploadHeader")
    assert body.pulled == 0


@pytest.mark.parametrize(
    "commit",
    [COMMIT_A[:-1], COMMIT_A + "0", "g" * 40, COMMIT_SHA256[:-1], ""],
    ids=["39", "41", "not-hex", "63", "empty"],
)
async def test_upload_header_with_bad_commit_is_422(lab: Lab, db: Db, commit: str) -> None:
    response = await upload_json(lab, to_json(make_bundle(RUN)), header=upload_header(commit=commit))
    await assert_upload_rejected(db, response, 422, "badUploadHeader")


async def test_oversized_upload_header_is_422(lab: Lab, db: Db) -> None:
    # 머리는 불·수·hex 뿐이라 수백 바이트다 — 4KiB 를 넘는 머리는 받지 않는다.
    header = upload_header(note="x" * 5000)
    response = await upload_json(lab, to_json(make_bundle(RUN)), header=header)
    await assert_upload_rejected(db, response, 422, "badUploadHeader")


async def test_failed_provenance_is_422(lab: Lab, db: Db) -> None:
    header = upload_header(prov=provenance(passed=False, outsideUsers=3))
    response = await upload_json(lab, to_json(make_bundle(RUN)), header=header)
    await assert_upload_rejected(db, response, 422, "provenanceFailed")


@pytest.mark.parametrize(
    "overrides",
    [{"baseLocal": False}, {"roomFound": False}, {"ownerInExampleDomain": False}, {"outsideUsers": 1}],
    ids=["remote-base", "room-missing", "owner-outside", "outside-users"],
)
async def test_inconsistent_provenance_fields_is_422(lab: Lab, db: Db, overrides: dict[str, Any]) -> None:
    # `passed` 가 참이라고 적혀 있어도 서비스가 칸들로 다시 계산해 어긋나면 받지 않는다.
    header = upload_header(prov=provenance(passed=True, **overrides))
    response = await upload_json(lab, to_json(make_bundle(RUN)), header=header)
    await assert_upload_rejected(db, response, 422, "provenanceFailed")


@pytest.mark.parametrize(
    "overrides",
    [{"baseLocal": None}, {"authorInExampleDomain": False}, {"authorInExampleDomain": None}],
    ids=["base-unknown", "author-outside", "author-unknown"],
)
async def test_provenance_warnings_do_not_block_upload(lab: Lab, overrides: dict[str, Any]) -> None:
    header = upload_header(prov=provenance(**overrides))
    response = await upload_json(lab, to_json(make_bundle(RUN)), header=header)
    assert response.status_code == 201, response.text


async def test_unknown_header_fields_are_ignored_and_not_stored(lab: Lab, db: Db) -> None:
    prov = {**provenance(), "exemptEmails": ["someone@example.com"]}
    header = upload_header(prov=prov, note="ignored")
    response = await upload_json(lab, to_json(make_bundle(RUN)), header=header)
    assert response.status_code == 201, response.text
    stored = await db.scalar("SELECT provenance::text FROM bundle_versions")
    assert set(json.loads(stored)) == set(PROVENANCE_FIELDS)
    versions = await lab.client.get(f"/api/runs/{RUN}/versions", headers=auth(human_token()))
    assert set(versions.json()["versions"][0]["provenance"]) == set(PROVENANCE_FIELDS)


async def test_sha256_object_format_commit_is_accepted(lab: Lab) -> None:
    response = await upload_json(lab, to_json(make_bundle(RUN)), header=upload_header(commit=COMMIT_SHA256))
    assert response.status_code == 201, response.text


# --- 계약 판·묶음 모양 ---------------------------------------------------------------------------------------------


async def test_missing_contract_version_is_422(lab: Lab, db: Db) -> None:
    bundle = make_bundle(RUN)
    del bundle["contractVersion"]
    response = await upload_json(lab, to_json(bundle))
    await assert_upload_rejected(db, response, 422, "noContractVersion")


@pytest.mark.parametrize("version", [0, -1, True, "1", 1.0], ids=["zero", "negative", "bool", "string", "float"])
async def test_contract_version_must_be_positive_integer(lab: Lab, db: Db, version: Any) -> None:
    response = await upload_json(lab, to_json(make_bundle(RUN, contract_version=version)))
    await assert_upload_rejected(db, response, 422, "unsupportedContract")


async def test_newer_contract_version_is_accepted(lab: Lab) -> None:
    # 서비스는 판 숫자를 저장만 하고 해석은 웹이 한다 — 지금 판보다 새 판도 받는다.
    response = await upload_json(lab, to_json(make_bundle(RUN, contract_version=2)))
    assert response.status_code == 201, response.text
    versions = await lab.client.get(f"/api/runs/{RUN}/versions", headers=auth(human_token()))
    assert versions.json()["versions"][0]["contractVersion"] == 2


async def test_legacy_format_is_422(lab: Lab, db: Db) -> None:
    response = await upload_json(lab, to_json(make_bundle(RUN, fmt="legacy")))
    await assert_upload_rejected(db, response, 422, "legacyFormat")


@pytest.mark.parametrize("fmt", ["future", "", None], ids=["unknown", "empty", "null"])
async def test_unknown_format_is_422(lab: Lab, db: Db, fmt: Any) -> None:
    response = await upload_json(lab, to_json(make_bundle(RUN, fmt=fmt)))
    await assert_upload_rejected(db, response, 422, "badBundle")


def _without(path: tuple[str, ...]) -> dict[str, Any]:
    bundle = make_bundle(RUN)
    target: Any = bundle
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return bundle


def _with(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    bundle = make_bundle(RUN)
    target: Any = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return bundle


MALFORMED_BUNDLES = {
    "raw-not-bool": lambda: _with(("raw",), "yes"),
    "raw-missing": lambda: _without(("raw",)),
    "detail-missing": lambda: _without(("detail",)),
    "detail-not-object": lambda: _with(("detail",), []),
    "run-missing": lambda: _without(("detail", "run")),
    "run-not-object": lambda: _with(("detail", "run"), RUN),
    "format-missing": lambda: _without(("detail", "run", "format")),
}


@pytest.mark.parametrize("shape", sorted(MALFORMED_BUNDLES))
async def test_malformed_bundle_is_422(lab: Lab, db: Db, shape: str) -> None:
    response = await upload_json(lab, to_json(MALFORMED_BUNDLES[shape]()))
    await assert_upload_rejected(db, response, 422, "badBundle")


async def test_run_id_mismatch_is_422(lab: Lab, db: Db) -> None:
    response = await upload_json(lab, to_json(make_bundle("another-run")))
    await assert_upload_rejected(db, response, 422, "runIdMismatch")


# --- gzip·JSON 읽기 -------------------------------------------------------------------------------------------------


async def test_not_gzip_is_422(lab: Lab, db: Db) -> None:
    response = await post_upload(lab.client, RUN, to_json(make_bundle(RUN)))
    await assert_upload_rejected(db, response, 422, "notGzip")


async def test_gzip_detected_by_magic_bytes_not_content_type(lab: Lab) -> None:
    compressed = gz(to_json(make_bundle(RUN)))
    response = await post_upload(lab.client, RUN, compressed, extra_headers={"Content-Type": "application/json"})
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("cut", ["half", "trailer"])
async def test_truncated_gzip_is_422(lab: Lab, db: Db, cut: str) -> None:
    compressed = gz(to_json(make_bundle(RUN)))
    truncated = compressed[: len(compressed) // 2] if cut == "half" else compressed[:-4]
    response = await post_upload(lab.client, RUN, truncated)
    await assert_upload_rejected(db, response, 422, "notGzip")


@pytest.mark.parametrize("tail", ["garbage", "second-member"])
async def test_trailing_garbage_after_gzip_is_422(lab: Lab, db: Db, tail: str) -> None:
    # 뒤에 붙은 바이트는 sha 를 잰 내용 밖이라 저장하면 꺼낼 때 다른 묶음이 된다.
    data = to_json(make_bundle(RUN))
    extra = b"trailing bytes" if tail == "garbage" else gz(to_json(make_bundle(RUN, variant=1)))
    response = await post_upload(lab.client, RUN, gz(data) + extra)
    await assert_upload_rejected(db, response, 422, "notGzip")


async def test_corrupted_gzip_is_422(lab: Lab, db: Db) -> None:
    compressed = bytearray(gzip.compress(to_json(make_bundle(RUN)), compresslevel=0, mtime=0))
    compressed[len(compressed) // 2] ^= 0xFF
    response = await post_upload(lab.client, RUN, bytes(compressed))
    await assert_upload_rejected(db, response, 422, "notGzip")


async def test_json_array_is_422(lab: Lab, db: Db) -> None:
    response = await upload_json(lab, to_json([make_bundle(RUN)]))
    await assert_upload_rejected(db, response, 422, "notJsonObject")


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
async def test_nan_is_422(lab: Lab, db: Db, constant: bytes) -> None:
    # 웹의 `JSON.parse` 가 읽지 못하는 값이다.
    data = to_json(make_bundle(RUN))
    assert b'"medianLength": 120.0' in data
    response = await upload_json(lab, data.replace(b'"medianLength": 120.0', b'"medianLength": ' + constant))
    await assert_upload_rejected(db, response, 422, "notJsonObject")


@pytest.mark.parametrize("encoding", ["bom", "utf-16", "invalid-byte", "not-json"])
async def test_non_utf8_or_broken_json_is_422(lab: Lab, db: Db, encoding: str) -> None:
    text = to_json(make_bundle(RUN)).decode("utf-8")
    data = {
        "bom": b"\xef\xbb\xbf" + text.encode("utf-8"),
        "utf-16": text.encode("utf-16"),
        "invalid-byte": text.replace("합성 이야기", "\x00").encode("utf-8").replace(b"\x00", b"\xff"),
        "not-json": b"{not json",
    }[encoding]
    response = await upload_json(lab, data)
    await assert_upload_rejected(db, response, 422, "notJsonObject")


# --- 크기 상한 -----------------------------------------------------------------------------------------------------


async def test_compressed_over_limit_is_413(lab: Lab, db: Db) -> None:
    body = gzip_of_exact_size(to_json(make_bundle(RUN)), COMPRESSED_LIMIT + 1)
    response = await post_upload(lab.client, RUN, body)
    await assert_upload_rejected(db, response, 413, "tooLarge")


async def test_declared_length_over_limit_is_413_without_reading(lab: Lab, db: Db) -> None:
    body = unread_body()
    response = await post_upload(lab.client, RUN, body, extra_headers={"Content-Length": str(COMPRESSED_LIMIT + 1)})
    await assert_upload_rejected(db, response, 413, "tooLarge")
    assert body.pulled == 0


async def test_chunked_body_over_limit_is_413(lab: Lab, db: Db) -> None:
    # 길이 머리 없이 오는 본문도 실제로 읽은 바이트로 센다 — 상한을 넘는 조각에서 멈추고 나머지는 읽지 않는다.
    body = TrackedBody(b"\x1f\x8b", chunk_size=MIB, chunk_count=16)
    response = await post_upload(lab.client, RUN, body)
    await assert_upload_rejected(db, response, 413, "tooLarge")
    assert body.pulled <= COMPRESSED_LIMIT // MIB + 1


async def test_understated_length_is_still_cut_at_limit(lab: Lab, db: Db) -> None:
    body = TrackedBody(b"\x1f\x8b", chunk_size=MIB, chunk_count=16)
    response = await post_upload(lab.client, RUN, body, extra_headers={"Content-Length": "1024"})
    await assert_upload_rejected(db, response, 413, "tooLarge")
    assert body.pulled <= COMPRESSED_LIMIT // MIB + 1


async def test_uncompressed_over_limit_is_413(lab: Lab, db: Db) -> None:
    data = bundle_json_of_size(RUN, UNCOMPRESSED_LIMIT + 1)
    response = await upload_json(lab, data)
    await assert_upload_rejected(db, response, 413, "tooLarge")


async def test_gzip_bomb_is_413_and_memory_peak_stays_under_limit(lab: Lab, db: Db) -> None:
    bomb = gzip_bomb(256 * MIB)
    assert len(bomb) < COMPRESSED_LIMIT
    response, peak = await measure_peak(lambda: post_upload(lab.client, RUN, bomb))
    report_peak("압축 폭탄", peak, BOMB_PEAK_LIMIT)
    await assert_upload_rejected(db, response, 413, "tooLarge")
    assert peak < BOMB_PEAK_LIMIT, f"정점 {peak / MIB:.1f}MiB"


async def test_uncompressed_size_at_limit_succeeds(lab: Lab) -> None:
    data = bundle_json_of_size(RUN, UNCOMPRESSED_LIMIT)
    compressed = gz(data)
    response, peak = await measure_peak(lambda: post_upload(lab.client, RUN, compressed))
    report_peak("푼 크기 상한", peak, ACCEPTED_PEAK_LIMIT)
    assert response.status_code == 201, response.text
    assert response.json()["sha256"] == sha256_hex(data)
    assert peak < ACCEPTED_PEAK_LIMIT, f"정점 {peak / MIB:.1f}MiB"
    versions = await lab.client.get(f"/api/runs/{RUN}/versions", headers=auth(human_token()))
    latest = versions.json()["versions"][0]
    assert (latest["uncompressedSize"], latest["compressedSize"]) == (UNCOMPRESSED_LIMIT, len(compressed))


async def test_compressed_size_at_limit_succeeds(lab: Lab) -> None:
    # 저장 블록 gzip 이라 푼 크기도 압축 크기와 거의 같다 — 8MiB 를 실제로 풀고 파싱하고 저장하는 정점을 잰다.
    data = bundle_json_of_size(RUN, COMPRESSED_LIMIT - 64 * 1024, incompressible=True)
    body = gzip_of_exact_size(data, COMPRESSED_LIMIT)
    response, peak = await measure_peak(lambda: post_upload(lab.client, RUN, body))
    report_peak("압축 크기 상한", peak, ACCEPTED_PEAK_LIMIT)
    assert response.status_code == 201, response.text
    assert response.json()["sha256"] == sha256_hex(data)
    assert peak < ACCEPTED_PEAK_LIMIT, f"정점 {peak / MIB:.1f}MiB"
    plain = await lab.client.get(
        f"/api/runs/{RUN}/versions/{sha256_hex(data)}/bundle",
        headers={**auth(human_token()), "Accept-Encoding": "identity"},
    )
    assert plain.content == data


# --- 구현 뒤에 더한 경계: 머리 중복·읽을 수 없는 길이·계약 판 범위·runId 타입·깊은 중첩 ------------------------------------


async def upload_with_header_list(
    lab: Lab,
    body: bytes | TrackedBody,
    extra: list[tuple[bytes, bytes]],
    *,
    upload_headers: list[bytes] | None = None,
) -> httpx.Response:
    """머리를 (이름, 값) 목록으로 보낸다 — 같은 머리를 둘 싣거나 ASCII 밖 바이트를 그대로 싣기 위해서다."""
    headers: list[tuple[bytes, bytes]] = [
        (TOKEN_HEADER.encode(), service_token().encode()),
        (b"content-type", b"application/gzip"),
    ]
    for value in upload_headers if upload_headers is not None else [header_value(upload_header()).encode()]:
        headers.append((UPLOAD_HEADER.encode(), value))
    return await lab.client.post(f"/api/runs/{RUN}/versions", content=body, headers=headers + extra)


@pytest.mark.parametrize("variant", ["different", "identical"])
async def test_duplicate_upload_header_is_422(lab: Lab, db: Db, variant: str) -> None:
    # 머리가 둘이면 어느 쪽 출처를 믿을지 정할 수 없다 — 값이 같아도 하나만 받는다. 본문은 읽지 않는다.
    first = header_value(upload_header()).encode()
    second = first if variant == "identical" else header_value(upload_header(commit=COMMIT_B)).encode()
    body = unread_body()
    response = await upload_with_header_list(lab, body, [], upload_headers=[first, second])
    await assert_upload_rejected(db, response, 422, "badUploadHeader")
    assert body.pulled == 0


UNREADABLE_LENGTHS = {
    "abc": b"abc",
    "negative": b"-1",
    "double-minus": b"--5",
    "exponent": b"1e3",
    # latin-1 의 위 첨자 2 — 파이썬 `str.isdigit()` 은 참인데 `int()` 로는 읽히지 않는다.
    "superscript-two": b"\xb2",
}


@pytest.mark.parametrize("size", ["small", "over-limit"])
@pytest.mark.parametrize("declared", sorted(UNREADABLE_LENGTHS))
async def test_unreadable_declared_length_is_decided_by_actual_body(lab: Lab, db: Db, declared: str, size: str) -> None:
    # 선언 길이는 미리 거르는 데만 쓰고 판정은 실제로 읽은 바이트다 — 읽을 수 없는 선언 길이는 무시한다. 어느 쪽이든 500 이
    # 아니다. 운영의 uvicorn 은 이런 머리를 앱 앞에서 400 으로 막지만, 앱이 그것에 기대지 않는다.
    extra = [(b"content-length", UNREADABLE_LENGTHS[declared])]
    if size == "small":
        response = await upload_with_header_list(lab, gz(to_json(make_bundle(RUN))), extra)
        assert response.status_code == 201, response.text
        return
    body = TrackedBody(b"\x1f\x8b", chunk_size=MIB, chunk_count=16)
    response = await upload_with_header_list(lab, body, extra)
    await assert_upload_rejected(db, response, 413, "tooLarge")
    assert body.pulled <= COMPRESSED_LIMIT // MIB + 1


RUN_ID_NOT_STRING = {
    "number": lambda: _with(("detail", "run", "runId"), 7),
    "null": lambda: _with(("detail", "run", "runId"), None),
    "missing": lambda: _without(("detail", "run", "runId")),
}


@pytest.mark.parametrize("shape", sorted(RUN_ID_NOT_STRING))
async def test_run_id_that_is_not_a_string_is_422(lab: Lab, db: Db, shape: str) -> None:
    # 경로와 다른 값(runIdMismatch)이 아니라 묶음 모양이 틀린 것이다.
    response = await upload_json(lab, to_json(RUN_ID_NOT_STRING[shape]()))
    await assert_upload_rejected(db, response, 422, "badBundle")


@pytest.mark.parametrize("version", [2**31, 10**30], ids=["2^31", "10^30"])
async def test_contract_version_beyond_int4_is_422(lab: Lab, db: Db, version: int) -> None:
    # 판 칸은 integer 다 — 넘는 값을 받으면 쓰기에서 DB 오류(503)가 되어 다시 올려도 같은 실패를 되풀이한다.
    response = await upload_json(lab, to_json(make_bundle(RUN, contract_version=version)))
    await assert_upload_rejected(db, response, 422, "unsupportedContract")


async def test_largest_contract_version_is_accepted(lab: Lab) -> None:
    largest = 2**31 - 1
    response = await upload_json(lab, to_json(make_bundle(RUN, contract_version=largest)))
    assert response.status_code == 201, response.text
    versions = await lab.client.get(f"/api/runs/{RUN}/versions", headers=auth(human_token()))
    assert versions.json()["versions"][0]["contractVersion"] == largest


@pytest.mark.parametrize("container", ["array", "object"])
async def test_deeply_nested_json_is_422(lab: Lab, db: Db, container: str) -> None:
    # 파서의 재귀 한도를 넘는 중첩은 RecursionError 로 끝난다 — 이것도 "JSON 으로 읽히지 않는다"이고 처리 안 된 500 이 아니다.
    depth = 100_000
    data = b"[" * depth + b"]" * depth if container == "array" else b'{"a":' * depth + b"1" + b"}" * depth
    response = await upload_json(lab, data)
    await assert_upload_rejected(db, response, 422, "notJsonObject")


# 목록이 읽는 런 칸(`detail.run`)은 JSONB 로 저장한다. JSON 으로는 읽히지만 JSONB 가 받지 못하는 값 — 문자열의 NUL, 짝 없는 서로게이트,
# 배정밀도를 넘어 무한대로 읽히는 수 — 는 DB 장애(503)가 아니라 묶음 모양이 틀린 것이다. 다시 올려도 같은 실패를 되풀이한다.
_STORY_NAME = '"storyName": "합성 이야기"'.encode()
UNSTORABLE_RUN_VALUES = {
    "nul-in-value": (_STORY_NAME, b'"storyName": "a\\u0000b"'),
    "lone-surrogate": (_STORY_NAME, b'"storyName": "a\\ud800b"'),
    "nul-in-key": (b'"storyName":', b'"story\\u0000Name":'),
    "overflowing-number": (b'"costUsd": 0.0125', b'"costUsd": 1e400'),
}


@pytest.mark.parametrize("shape", sorted(UNSTORABLE_RUN_VALUES))
async def test_run_value_that_jsonb_cannot_store_is_422(lab: Lab, db: Db, shape: str) -> None:
    original, replacement = UNSTORABLE_RUN_VALUES[shape]
    data = to_json(make_bundle(RUN))
    assert data.count(original) == 1
    response = await upload_json(lab, data.replace(original, replacement))
    await assert_upload_rejected(db, response, 422, "badBundle")


async def test_escaped_surrogate_pair_in_run_is_accepted(lab: Lab) -> None:
    # 짝을 이룬 서로게이트 이스케이프는 문자 하나(이모지)로 읽혀 JSONB 에 들어간다 — 거르는 쪽이 이것까지 막으면 안 된다.
    data = to_json(make_bundle(RUN)).replace("합성 이야기".encode(), b"\\ud83d\\ude00")
    response = await upload_json(lab, data)
    assert response.status_code == 201, response.text
    listed = await lab.client.get("/api/runs", headers=auth(human_token()))
    assert listed.json()["items"][0]["run"]["storyName"] == "\U0001f600"


@pytest.mark.parametrize("delta", [-1, 0, 1], ids=["minus-one", "exact", "plus-one"])
async def test_gzip_ending_on_input_window_with_trailing_byte_is_422(lab: Lab, db: Db, delta: int) -> None:
    # 서비스는 압축 바이트를 고정 크기 창으로 나눠 푼다. gzip 이 창 끝에서 정확히 끝나면 뒤에 붙은 바이트는 풀기 객체에 들어가지
    # 않아 남은 바이트로 드러나지 않는다 — 그래도 거부해야 sha 를 잰 내용 밖의 바이트가 저장되지 않는다. 창 앞뒤 한 바이트는
    # 뒤 바이트가 같은 조각에 들어가는 대조군이다.
    body = gzip_of_exact_size(to_json(make_bundle(RUN)), INFLATE_WINDOW + delta) + b"x"
    response = await post_upload(lab.client, RUN, body)
    await assert_upload_rejected(db, response, 422, "notGzip")
