"""합성 런 묶음·gzip·올리기 머리 도우미.

공개 저장소라 실측 묶음을 쓰지 않는다. 묶음 모양은 측정 서버 스키마(`apps/chat-lab/openapi.json` 의
`RunBundle`)의 필수 칸을 따르고, `test_bundle_contract_shape.py` 가 그 스키마로 이 모양을 다시 대조한다. 대화·프롬프트
원문은 없다 — 원문 자리에는 합성 자리 표시 문자열만 넣는다.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import struct
import zlib
from collections.abc import AsyncIterator
from functools import cache
from typing import Any

import httpx

from keys import TOKEN_HEADER, UPLOADER_ID, service_token

UPLOAD_HEADER = "X-Lab-Upload-Header"
COMMIT_A = "0123456789abcdef0123456789abcdef01234567"
COMMIT_B = "89abcdef0123456789abcdef0123456789abcdef"
COMMIT_SHA256 = "fedcba9876543210" * 4
SYNTHETIC_ROOM_ID = "00000000-0000-4000-8000-000000000001"

PROVENANCE_FIELDS = (
    "passed",
    "baseLocal",
    "roomFound",
    "ownerInExampleDomain",
    "outsideUsers",
    "exemptedUsers",
    "authorInExampleDomain",
)


def run_item(run_id: str, *, fmt: str = "current") -> dict[str, Any]:
    """`RunListItem` 꼴 — 올리는 묶음은 열린 묶음이라 `supported` 는 참, `openError` 는 비어 있다."""
    return {
        "runId": run_id,
        "path": f"synthetic/{run_id}/chat.jsonl",
        "group": "synthetic",
        "format": fmt,
        "supported": True,
        "roomId": SYNTHETIC_ROOM_ID,
        "storyName": "합성 이야기",
        "turnCount": 1,
        "startedAt": "2026-11-01T00:00:00+00:00",
        "endedAt": "2026-11-01T00:10:00+00:00",
        "sentChatModels": ["synthetic-model"],
        "sentChatModelsFrom": "dump",
        "configuredChatModels": ["synthetic-model"],
        "costUsd": 0.0125,
        "unpricedCalls": 0,
        "costIsLowerBound": False,
        "hasSnapshots": False,
        "hasDump": True,
        "hasChatTurns": False,
        "mismatchCount": 0,
        "cautionCount": 0,
        "openError": None,
    }


def _turn_detail(raw: bool) -> dict[str, Any]:
    dump: dict[str, Any] = {"callSite": "synthetic"}
    if raw:
        dump["prompt"] = "합성 프롬프트 자리 표시"
        dump["systemInstruction"] = "합성 지시문 자리 표시"
    return {
        "turn": 1,
        "supplemented": False,
        "replaced": False,
        "attempts": [],
        "earlierGenerationDumps": [dump],
        "judgmentDumps": [],
        "backgroundDumps": [],
        "replacements": [],
        "memorySnapshot": None,
        "memorySnapshotChangedHere": False,
        "metrics": None,
        "mismatches": [],
        "cautions": [],
        "recordLimits": [],
    }


def _metrics(variant: int) -> dict[str, Any]:
    return {
        "scored": 1,
        "lost": 0,
        "truncated": 0,
        "selfCopy": 0,
        "solicit": 0,
        "ignored": 0,
        "sceneOpen": 0,
        "labelLeak": 0,
        "userTurn": 0,
        "broken": 0,
        "brackets": variant,
        "medianLength": 120.0,
        "medianSentences": 3.0,
        "lengthNonIncreasing": None,
        "turns": [],
    }


def make_bundle(
    run_id: str,
    *,
    raw: bool = False,
    contract_version: Any = 1,
    fmt: str = "current",
    variant: int = 0,
    pad: str = "",
) -> dict[str, Any]:
    """합성 `RunBundle`. `variant` 를 바꾸면 내용(따라서 sha)이 바뀌고, `pad` 는 묶음 크기를 키운다."""
    return {
        "contractVersion": contract_version,
        "raw": raw,
        "detail": {
            "run": run_item(run_id, fmt=fmt),
            "meta": {"synthetic": True, "variant": variant, "pad": pad},
            "roomStatic": {"synthetic": "합성 방 스냅숏 자리 표시"} if raw else None,
            "turns": [],
            "series": [],
            "markers": [],
            "statComparisons": 0,
            "cost": None,
            "unmatchedRows": [],
            "mismatches": [],
            "cautions": [],
        },
        "metrics": _metrics(variant),
        "turns": [_turn_detail(raw)],
    }


def to_json(bundle: Any, *, indent: int | None = None) -> bytes:
    return json.dumps(bundle, ensure_ascii=False, indent=indent, allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gz(data: bytes, *, level: int = 6, mtime: int = 0) -> bytes:
    return gzip.compress(data, compresslevel=level, mtime=mtime)


def gzip_of_exact_size(data: bytes, total_size: int) -> bytes:
    """압축 바이트 길이가 정확히 `total_size` 인 gzip.

    본문은 저장 블록(level 0)으로 넣고 남는 길이를 gzip 머리의 주석 칸(FCOMMENT)으로 채운다 — 주석은 풀어도 나오지 않으므로
    푼 바이트는 `data` 그대로다.
    """
    compressor = zlib.compressobj(0, zlib.DEFLATED, -15)
    deflated = compressor.compress(data) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF)
    header = bytes([0x1F, 0x8B, 0x08, 0x10, 0, 0, 0, 0, 0, 0xFF])
    pad = total_size - (len(header) + 1 + len(deflated) + len(trailer))
    if pad < 0:
        raise ValueError("data is too large for the requested gzip size")
    result = header + b"c" * pad + b"\x00" + deflated + trailer
    assert len(result) == total_size
    return result


def bundle_json_of_size(run_id: str, size: int, *, incompressible: bool = False, **kwargs: Any) -> bytes:
    """JSON 바이트 길이가 정확히 `size` 인 합성 묶음. 채움은 ASCII 라 한 글자가 한 바이트다."""
    base = to_json(make_bundle(run_id, **kwargs))
    need = size - len(base)
    if need < 0:
        raise ValueError("size is smaller than the empty bundle")
    if incompressible:
        filler = base64.b64encode(random.Random(need).randbytes(need)).decode("ascii")[:need]
    else:
        filler = "a" * need
    data = to_json(make_bundle(run_id, pad=filler, **kwargs))
    assert len(data) == size
    return data


@cache
def gzip_bomb(uncompressed_size: int) -> bytes:
    """풀면 `uncompressed_size` 바이트의 올바른 JSON 객체가 되는 작은 gzip — 다 풀기만 하면 받아질 꼴이라, 거부는 크기
    상한에서만 나온다."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    head = b'{"pad":"'
    tail = b'"}'
    parts = [compressor.compress(head)]
    remaining = uncompressed_size - len(head) - len(tail)
    chunk = b"a" * (1024 * 1024)
    while remaining > 0:
        piece = chunk[: min(remaining, len(chunk))]
        parts.append(compressor.compress(piece))
        remaining -= len(piece)
    parts.append(compressor.compress(tail))
    parts.append(compressor.flush())
    return b"".join(parts)


def provenance(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "passed": True,
        "baseLocal": True,
        "roomFound": True,
        "ownerInExampleDomain": True,
        "outsideUsers": 0,
        "exemptedUsers": 0,
        "authorInExampleDomain": True,
    }
    values.update(overrides)
    return values


def upload_header(
    *, commit: str = COMMIT_A, dirty: bool = False, prov: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    """측정 서버 `upload-header` 응답 꼴 `{"sourceCommit": {…}, "provenance": {…}}`."""
    return {"sourceCommit": {"commit": commit, "dirty": dirty}, "provenance": prov or provenance(), **extra}


def header_value(header: dict[str, Any]) -> str:
    return json.dumps(header, separators=(",", ":"))


class TrackedBody:
    """요청 본문을 조각으로 내며 몇 조각을 꺼내 갔는지 센다 — 서비스가 본문을 읽지 않았는지(또는 어디서 멈췄는지)를 본다."""

    def __init__(self, head: bytes, *, chunk_size: int, chunk_count: int) -> None:
        self.head = head
        self.chunk_size = chunk_size
        self.chunk_count = chunk_count
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index in range(self.chunk_count):
            self.pulled += 1
            if index == 0:
                yield self.head + bytes(self.chunk_size - len(self.head))
            else:
                yield bytes(self.chunk_size)


async def post_upload(
    client: httpx.AsyncClient,
    run_id: str,
    body: bytes | TrackedBody,
    *,
    token: str | None = None,
    header: dict[str, Any] | str | None = None,
    send_header: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    """`POST /api/runs/{runId}/versions` — 본문은 gzip 바이트, 머리는 `X-Lab-Upload-Header` 의 JSON."""
    headers: dict[str, str] = {
        TOKEN_HEADER: token if token is not None else service_token(UPLOADER_ID),
        "Content-Type": "application/gzip",
    }
    if send_header:
        value = header if isinstance(header, str) else header_value(header or upload_header())
        headers[UPLOAD_HEADER] = value
    headers.update(extra_headers or {})
    return await client.post(f"/api/runs/{run_id}/versions", content=body, headers=headers)


async def upload_bundle(
    client: httpx.AsyncClient, bundle: dict[str, Any], **kwargs: Any
) -> tuple[httpx.Response, bytes, bytes]:
    """묶음을 JSON·gzip 으로 만들어 올린다. (응답, JSON 바이트, gzip 바이트)를 돌려준다."""
    data = to_json(bundle)
    compressed = gz(data)
    response = await post_upload(client, bundle["detail"]["run"]["runId"], compressed, **kwargs)
    return response, data, compressed
