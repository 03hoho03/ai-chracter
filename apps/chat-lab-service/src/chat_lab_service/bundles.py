"""올린 묶음 읽기(크기 상한·압축 풀기·sha·JSON·모양 검사)와 판 쓰기·조회·지우기.

판 키는 압축 푼 JSON 바이트의 sha256 이다. 서비스는 JSON 을 다시 직렬화하지 않고, 올린 gzip 바이트를 그대로 저장해 그대로
내준다.
"""

import hashlib
import json
import math
import re
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Row, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request

from chat_lab_service.errors import ServiceHTTPError
from chat_lab_service.models import bundle_versions
from chat_lab_service.schemas import Provenance, RunItem, SourceCommit, UploadHeader, Version

MIB = 1024 * 1024
# 상한과 같은 크기는 받는다.
COMPRESSED_LIMIT = 8 * MIB
UNCOMPRESSED_LIMIT = 32 * MIB
# 같은 런의 올리기를 줄 세우는 advisory 잠금의 첫 키(두 키 꼴) — 둘째 키는 runId 의 해시다. 해시가 겹친 두 런은 함께 줄을 설
# 뿐이라 결과는 같다.
_RUN_LOCK_CLASS = 0x1AB0
# 계약 판 칸(integer)에 들어가는 가장 큰 값 — 넘는 값을 받으면 쓰기에서 DB 오류(503)가 된다.
_INT4_MAX = 2**31 - 1
# 풀 때 한 번에 넣는 압축 바이트와 한 번에 꺼내는 푼 바이트. 꺼내는 쪽에도 상한을 둬야 압축 폭탄의 작은 입력 하나가 상한만큼의
# 출력을 한꺼번에 만들지 않는다.
_INFLATE_INPUT = 64 * 1024
_INFLATE_OUTPUT = 1 * MIB

_GZIP_MAGIC = b"\x1f\x8b"
_FORMATS = ("current", "preMessageId")
# JSON 으로는 읽히지만 JSONB 가 받지 못하는 글자 — NUL 과 짝 없는 서로게이트(짝을 이룬 이스케이프는 읽을 때 한 글자로 합쳐진다).
_UNSTORABLE_CHARACTER = re.compile("[\x00\ud800-\udfff]")


class _BrokenGzipError(Exception):
    pass


def inflate(compressed: bytes) -> Iterator[bytes]:
    """gzip 멤버 하나를 풀어 조각으로 낸다. 잘렸거나 뒤에 다른 바이트(다른 멤버 포함)가 붙었으면 `_BrokenGzipError`, 깨졌으면
    `zlib.error`."""
    decompressor = zlib.decompressobj(wbits=31)
    view = memoryview(compressed)
    position = 0
    while not decompressor.eof:
        if decompressor.unconsumed_tail:
            feed: bytes | memoryview = decompressor.unconsumed_tail
        else:
            feed = view[position : position + _INFLATE_INPUT]
            position += len(feed)
        piece = decompressor.decompress(feed, _INFLATE_OUTPUT)
        if not piece and not feed:
            raise _BrokenGzipError("gzip 이 끝나기 전에 잘렸다")
        if piece:
            yield piece
    if decompressor.unused_data or position < len(view):
        # 뒤에 붙은 바이트는 sha 를 잰 내용 밖이라, 저장하면 꺼낼 때 다른 묶음이 된다.
        raise _BrokenGzipError("gzip 뒤에 다른 바이트가 붙어 있다")


@dataclass(frozen=True)
class ParsedBundle:
    sha256: str
    uncompressed_size: int
    contract_version: int
    raw: bool
    run_item: dict[str, Any]


def _reject_constant(name: str) -> Any:
    # 웹의 `JSON.parse` 가 읽지 못하는 값이다.
    raise ValueError(f"JSON 이 아닌 수 {name}")


def parse_bundle(compressed: bytes, run_id: str) -> ParsedBundle:
    """압축을 풀며 sha 를 재고 JSON 으로 읽어 묶음 모양을 본다. 큰 묶음에서 오래 걸려 스레드에서 부른다."""
    if compressed[:2] != _GZIP_MAGIC:
        raise ServiceHTTPError(422, "notGzip", "본문이 gzip 이 아니다")
    digest = hashlib.sha256()
    plain = bytearray()
    try:
        for piece in inflate(compressed):
            if len(plain) + len(piece) > UNCOMPRESSED_LIMIT:
                raise ServiceHTTPError(413, "tooLarge", f"푼 묶음이 {UNCOMPRESSED_LIMIT // MIB}MiB 를 넘는다")
            digest.update(piece)
            plain += piece
    except (zlib.error, _BrokenGzipError) as error:
        raise ServiceHTTPError(422, "notGzip", f"gzip 을 풀지 못했다: {error}") from None
    size = len(plain)
    try:
        # UTF-8 만 받는다 — BOM·UTF-16 은 웹이 읽지 못한다. 바이트 버퍼는 문자열을 만든 뒤 바로 놓아 정점에 둘이 오래 함께
        # 남지 않게 한다.
        text = plain.decode("utf-8")
        del plain
        document = json.loads(text, parse_constant=_reject_constant)
        del text
    except (ValueError, RecursionError):
        raise ServiceHTTPError(422, "notJsonObject", "묶음이 JSON 으로 읽히지 않는다") from None
    if not isinstance(document, dict):
        raise ServiceHTTPError(422, "notJsonObject", "묶음 꼭대기가 JSON 객체가 아니다")
    return _check_bundle(document, run_id, digest.hexdigest(), size)


def _bad_bundle(detail: str) -> ServiceHTTPError:
    return ServiceHTTPError(422, "badBundle", detail)


def _check_bundle(document: dict[str, Any], run_id: str, sha256: str, size: int) -> ParsedBundle:
    if "contractVersion" not in document:
        raise ServiceHTTPError(422, "noContractVersion", "묶음에 계약 판(contractVersion)이 없다")
    version = document["contractVersion"]
    # 판 숫자는 저장만 하고 해석은 웹이 한다. 불은 정수의 하위 타입이라 따로 거른다.
    if type(version) is not int or not 1 <= version <= _INT4_MAX:
        raise ServiceHTTPError(422, "unsupportedContract", "계약 판은 1 이상의 정수여야 한다")
    raw = document.get("raw")
    if not isinstance(raw, bool):
        raise _bad_bundle("raw 가 불이 아니다")
    detail = document.get("detail")
    run = detail.get("run") if isinstance(detail, dict) else None
    if not isinstance(run, dict):
        raise _bad_bundle("detail.run 이 객체가 아니다")
    if not isinstance(run.get("runId"), str):
        raise _bad_bundle("detail.run.runId 가 문자열이 아니다")
    fmt = run.get("format")
    if fmt == "legacy":
        raise ServiceHTTPError(422, "legacyFormat", "옛 형식 묶음은 받지 않는다")
    if fmt not in _FORMATS:
        raise _bad_bundle("detail.run.format 이 알려진 형식이 아니다")
    if not _storable(run):
        raise _bad_bundle("detail.run 에 저장할 수 없는 값(NUL·짝 없는 서로게이트·무한대로 읽히는 수)이 있다")
    if run["runId"] != run_id:
        raise ServiceHTTPError(422, "runIdMismatch", "묶음의 runId 가 경로와 다르다")
    return ParsedBundle(sha256=sha256, uncompressed_size=size, contract_version=version, raw=raw, run_item=run)


def _storable(value: Any) -> bool:
    """런 칸을 JSONB 로 저장할 수 있는가 — 못 하면 쓰기가 DB 오류(503)로 끝나 다시 올려도 같은 실패를 되풀이한다."""
    if isinstance(value, str):
        return _UNSTORABLE_CHARACTER.search(value) is None
    if isinstance(value, float):
        # 배정밀도를 넘는 수는 무한대로 읽힌다.
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_storable(key) and _storable(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_storable(item) for item in value)
    return True


async def read_limited(request: Request, limit: int) -> bytes | None:
    """본문을 실제로 읽은 바이트로 센다. `limit` 을 넘는 조각에서 멈추고 None — 나머지는 읽지 않는다. 길이 머리가 없거나
    거짓이어도 같다."""
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > limit:
            return None
        buffer += chunk
    return bytes(buffer)


def _version_columns() -> list[Any]:
    bv = bundle_versions.c
    return [
        bv.id,
        bv.run_id,
        bv.sha256,
        bv.uploaded_at,
        bv.uploaded_by,
        bv.raw,
        bv.contract_version,
        bv.source_commit,
        bv.source_dirty,
        bv.provenance,
        bv.compressed_size,
        bv.uncompressed_size,
        bv.run_item,
        bv.deleted_at,
        func.row_number().over(partition_by=bv.run_id, order_by=bv.id).label("version_number"),
    ]


def _version(row: Row[Any]) -> Version:
    return Version(
        sha256=row.sha256,
        version_number=row.version_number,
        uploaded_at=row.uploaded_at,
        uploaded_by=row.uploaded_by,
        raw=row.raw,
        contract_version=row.contract_version,
        source_commit=SourceCommit(commit=row.source_commit, dirty=row.source_dirty),
        provenance=Provenance.model_validate(row.provenance),
        compressed_size=row.compressed_size,
        uncompressed_size=row.uncompressed_size,
    )


async def list_runs(engine: AsyncEngine) -> list[RunItem]:
    """런마다 최신 판 하나 — 지우지 않은 판 가운데 처음 들어온 순서로 가장 늦은 판. 최신 판을 올린 때의 내림차순."""
    # 판 번호는 지운 판까지 넣어 매긴 뒤 지운 판을 거른다. 본문은 고르지 않는다(판마다 수 MiB).
    numbered = select(*_version_columns()).subquery()
    live = (
        select(
            numbered,
            func.count().over(partition_by=numbered.c.run_id).label("version_count"),
            func.row_number().over(partition_by=numbered.c.run_id, order_by=numbered.c.id.desc()).label("newest"),
        )
        .where(numbered.c.deleted_at.is_(None))
        .subquery()
    )
    query = select(live).where(live.c.newest == 1).order_by(live.c.uploaded_at.desc(), live.c.id.desc())
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    return [
        RunItem(run_id=row.run_id, latest=_version(row), version_count=row.version_count, run=row.run_item)
        for row in rows
    ]


async def versions_of(engine: AsyncEngine, run_id: str) -> list[Version]:
    """지우지 않은 판, 최신 먼저."""
    numbered = select(*_version_columns()).where(bundle_versions.c.run_id == run_id).subquery()
    query = select(numbered).where(numbered.c.deleted_at.is_(None)).order_by(numbered.c.id.desc())
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    return [_version(row) for row in rows]


@dataclass(frozen=True)
class StoredBody:
    body: bytes
    raw: bool
    uncompressed_size: int


async def stored_body(engine: AsyncEngine, run_id: str, sha256: str) -> StoredBody | None:
    bv = bundle_versions.c
    query = select(bv.body, bv.raw, bv.uncompressed_size).where(
        bv.run_id == run_id, bv.sha256 == sha256, bv.deleted_at.is_(None)
    )
    async with engine.connect() as conn:
        row = (await conn.execute(query)).one_or_none()
    if row is None:
        return None
    return StoredBody(body=row.body, raw=row.raw, uncompressed_size=row.uncompressed_size)


UploadStatus = Literal["created", "exists", "restored"]


async def store_version(
    engine: AsyncEngine,
    *,
    run_id: str,
    compressed: bytes,
    parsed: ParsedBundle,
    header: UploadHeader,
    uploader: str,
    now: datetime,
) -> tuple[UploadStatus, int]:
    """판을 쓰고 (상태, 판 번호)를 돌려준다.

    같은 내용이 살아 있으면 `exists` — 저장된 커밋·출처·올린 이는 처음 것 그대로 둔다. 지운 판이면 `restored` — 되살림은 새로
    올린 것과 같아 본문·올린 이·때·커밋·출처를 이번 값으로 바꾼다.

    판 번호는 커밋 전에 "내 id 까지의 행 수"로 센다. 그래서 같은 런의 올리기는 트랜잭션 첫머리의 런 잠금으로 줄을 세운다 — 없으면
    서로의 커밋 안 된 행이 보이지 않아 다른 내용을 동시에 올린 둘이 같은 번호를 받는다. 줄을 서면 런 안의 id 순서가 커밋 순서와
    같아 목록이 읽을 때 매기는 번호와도 같다.
    """
    bv = bundle_versions.c
    this_upload = {
        "body": compressed,
        "compressed_size": len(compressed),
        "source_commit": header.source_commit.commit,
        "source_dirty": header.source_commit.dirty,
        "provenance": header.provenance.model_dump(by_alias=True),
        "uploaded_by": uploader,
        "uploaded_at": now,
    }
    same_content = (bv.run_id == run_id, bv.sha256 == parsed.sha256)
    status: UploadStatus = "created"
    async with engine.begin() as conn:
        await conn.execute(select(func.pg_advisory_xact_lock(_RUN_LOCK_CLASS, func.hashtext(run_id))))
        version_id = (
            await conn.execute(
                insert(bundle_versions)
                .values(
                    run_id=run_id,
                    sha256=parsed.sha256,
                    uncompressed_size=parsed.uncompressed_size,
                    contract_version=parsed.contract_version,
                    raw=parsed.raw,
                    run_item=parsed.run_item,
                    **this_upload,
                )
                .on_conflict_do_nothing(index_elements=[bv.run_id, bv.sha256])
                .returning(bv.id)
            )
        ).scalar_one_or_none()
        if version_id is None:
            # 행을 잠그고 본다 — 지우기가 진행 중이면 끝나기를 기다려 지운 판으로 보고 되살린다. 잠그지 않으면 그 사이에 지워진
            # 판을 `exists` 로 알린다.
            existing = (await conn.execute(select(bv.id, bv.deleted_at).where(*same_content).with_for_update())).one()
            version_id = existing.id
            status = "exists"
            if existing.deleted_at is not None:
                status = "restored"
                await conn.execute(
                    update(bundle_versions)
                    .where(bv.id == version_id)
                    .values(deleted_by=None, deleted_at=None, **this_upload)
                )
        number = (
            await conn.execute(
                select(func.count()).select_from(bundle_versions).where(bv.run_id == run_id, bv.id <= version_id)
            )
        ).scalar_one()
    return status, number


async def delete_run(engine: AsyncEngine, run_id: str, *, deleted_by: str, now: datetime) -> int:
    """그 런의 살아 있는 판을 모두 지우고(본문을 비우고 지운 이·때를 남긴다) 지운 수를 돌려준다."""
    bv = bundle_versions.c
    async with engine.begin() as conn:
        result = await conn.execute(
            update(bundle_versions)
            .where(bv.run_id == run_id, bv.deleted_at.is_(None))
            .values(body=None, deleted_by=deleted_by, deleted_at=now)
        )
    return result.rowcount
