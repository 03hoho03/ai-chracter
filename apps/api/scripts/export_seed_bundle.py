"""운영 작품을 비공개 시드 묶음(`seed_content/private/`)으로 읽기 전용으로 내보낸다.

운영 api 활성 컨테이너 안에서 돈다(앱 코드·DB·저장소 접근은 그 컨테이너의 env):

    python -u scripts/export_seed_bundle.py --map /tmp/map.txt --out /tmp/seed-bundle.tar.gz

`--map` 은 한 줄에 `<콘텐츠 uuid> <시드 slug>` 이고 빈 줄과 `#` 로 시작하는 줄은 건너뛴다. 조감독·민유나는 측정 도구가
기본값으로 쓰는 튜토리얼 slug(`tutorial-filmclub`·`tutorial-filmclub-yuna`)를 이어받는다.

묶음은 로더(`seed_content/loader.py`)가 읽는 꼴 그대로다 — `stories/{slug}.json`·`characters/{slug}.json`(빌더 초안
응답을 시드 입력 모델이 받는 camelCase 로, 발행본이 없으면 초안을 담고 최상위 `seedPublished: false`), `images/`(대표
이미지·미디어 북 칸·상황별 이미지 원본 바이트), `manifest.json`(작품 slug 별로 어느 파일이 어느 그림인지와 원래 종류·형식·
프레임 수·크롭). tar.gz 안에는 최상위 폴더가 없어 로컬에서 `tar -xzf … -C apps/api/scripts/seed_content/private/` 로 푼다.

DB 는 읽기 전용 트랜잭션으로만 읽는다 — 실수로 쓰기가 섞여도 DB 가 거부한다. 표준 출력에는 작품 수·이미지 수·바이트·
sha256 만 남긴다. 작품 이름이나 본문은 컨테이너 로그에 남기지 않는다.
"""

import argparse
import asyncio
import gzip
import hashlib
import io
import json
import sys
import tarfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.image_processing import read_frame_count, read_image_content_type

# 작품 하나를 직렬화하는 경로다. 테스트가 이 이름 자리를 감싸 직렬화 시점의 트랜잭션 상태를 본다.
from api.content.router import _character_draft_response, _story_draft_response
from api.core.s3 import download_object
from api.db.models.content import Content, ContentType, ContentVersion
from api.db.models.media import Asset

# 안전장치가 묶음 만들기를 거부했을 때의 종료 코드 — 묶음 파일은 만들지 않는다.
EXIT_REFUSED = 2

# 초안 응답에서 묶음에 담지 않는 칸 — 운영 작품·버전 id 와 운영 버킷을 서명한 주소. 시드 입력 모델은 모르는 키를
# 무시하므로 남겨도 읽히지만, 서명 주소를 로컬 파일에 퍼뜨릴 이유가 없다.
_DROPPED_TOP_KEYS = ("id", "contentVersionId", "thumbnailUrl")
_DROPPED_IMAGE_KEYS = ("imageUrl",)


class ExportRefusedError(Exception):
    """맵이나 출력 자리가 안전장치에 걸렸다. 메시지에는 작품 이름·본문을 넣지 않는다."""


@dataclass(frozen=True)
class MapEntry:
    content_id: uuid.UUID
    slug: str


@dataclass(frozen=True)
class ExportSummary:
    works: int
    images: int
    size_bytes: int
    sha256: str


def read_map(path: Path) -> list[MapEntry]:
    """`<콘텐츠 uuid> <slug>` 줄을 읽는다. 빈 줄과 `#` 줄은 건너뛴다."""
    entries = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ExportRefusedError(f"맵 {number}번째 줄이 `<콘텐츠 uuid> <slug>` 꼴이 아니다")
        try:
            content_id = uuid.UUID(parts[0])
        except ValueError as exc:
            raise ExportRefusedError(f"맵 {number}번째 줄의 콘텐츠 id 가 uuid 가 아니다") from exc
        entries.append(MapEntry(content_id=content_id, slug=parts[1]))
    return entries


async def export_seed_bundle(session: AsyncSession, entries: Sequence[MapEntry], out: Path) -> ExportSummary:
    """`entries` 의 작품을 묶음으로 만들어 `out` 에 tar.gz 로 쓴다.

    첫 문장으로 트랜잭션을 읽기 전용으로 바꾸고, 세션의 트랜잭션을 끝내지 않는다(커밋·닫기는 호출부 몫). 맵의 id 가
    DB 에 없거나, 작가가 맵 전체에서 한 명이 아니거나, slug 가 겹치거나, `out` 이 이미 있으면 아무것도 쓰지 않고
    `ExportRefusedError` 를 던진다."""
    await session.execute(text("SET TRANSACTION READ ONLY"))
    if out.exists():  # noqa: ASYNC240 — 운영자가 한 번 돌리는 CLI 라 이벤트 루프를 막아도 기다릴 다른 일이 없다
        raise ExportRefusedError(f"{out} 이 이미 있다 — 앞선 묶음을 덮지 않는다")
    slugs = [entry.slug for entry in entries]
    duplicated = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if duplicated:
        raise ExportRefusedError(f"slug 가 겹친다: {', '.join(duplicated)}")
    ids = [entry.content_id for entry in entries]
    contents = {
        content.id: content for content in (await session.scalars(select(Content).where(Content.id.in_(ids)))).all()
    }
    missing = [str(content_id) for content_id in ids if content_id not in contents]
    if missing:
        raise ExportRefusedError(f"DB 에 없는 콘텐츠 id: {', '.join(missing)}")
    authors = {content.creator_user_id for content in contents.values()}
    if len(authors) != 1:
        raise ExportRefusedError(
            f"맵의 작품 작가가 한 명이 아니다({len(authors)}명) — 묶음은 시드 작가 한 명의 작품이 된다"
        )

    files: dict[str, bytes] = {}
    manifest: dict[str, dict[str, Any]] = {"stories": {}, "characters": {}}
    for entry in entries:
        content = contents[entry.content_id]
        version, published = await _export_version(session, content)
        if content.type == ContentType.STORY:
            work = _bundle_json(await _story_draft_response(session, content, version), published)
            cells = (work.get("mediaBook") or {}).get("cells", [])
            manifest["stories"][entry.slug] = {
                "thumbnail": await _image(session, files, work.get("thumbnailAssetId"), f"{entry.slug}-thumb"),
                "mediaBookCells": {
                    cell["id"]: await _image(session, files, cell["imageAssetId"], f"{entry.slug}-cell-{cell['id']}")
                    for cell in cells
                },
            }
            folder = "stories"
        else:
            work = _bundle_json(await _character_draft_response(session, content, version), published)
            manifest["characters"][entry.slug] = {
                "thumbnail": await _image(session, files, work.get("thumbnailAssetId"), f"{entry.slug}-thumb"),
                "situationalImages": {
                    image["id"]: await _image(
                        session, files, image["imageAssetId"], f"{entry.slug}-scene-{image['id']}"
                    )
                    for image in work.get("situationalImages", [])
                    if image.get("imageAssetId") is not None
                },
            }
            folder = "characters"
        files[f"{folder}/{entry.slug}.json"] = _json_bytes(work)
    files["manifest.json"] = _json_bytes(manifest)

    archive = _tar_gz(files)
    with out.open("xb") as handle:
        handle.write(archive)
    return ExportSummary(
        works=len(entries),
        images=sum(1 for name in files if name.startswith("images/")),
        size_bytes=len(archive),
        sha256=hashlib.sha256(archive).hexdigest(),
    )


async def _export_version(session: AsyncSession, content: Content) -> tuple[ContentVersion, bool]:
    """담을 버전과 그것이 발행본인지. 발행본이 있으면 그것(발행 뒤 고친 초안은 아직 독자가 보지 못한 글이라 담지
    않는다), 없으면 빌더가 여는 초안 — 미발행 버전 중 가장 최근 것."""
    if content.current_published_version_id is not None:
        published = await session.get(ContentVersion, content.current_published_version_id)
        assert published is not None
        return published, True
    draft = await session.scalar(
        select(ContentVersion)
        .where(ContentVersion.content_id == content.id, ContentVersion.published_at.is_(None))
        .order_by(ContentVersion.created_at.desc())
        .limit(1)
    )
    if draft is None:
        raise ExportRefusedError(f"콘텐츠 {content.id} 에 발행본도 초안도 없다")
    return draft, False


def _bundle_json(response: Any, published: bool) -> dict[str, Any]:
    work: dict[str, Any] = response.model_dump(by_alias=True, mode="json")
    for key in _DROPPED_TOP_KEYS:
        work.pop(key, None)
    images = [*(work.get("mediaBook") or {}).get("cells", []), *work.get("situationalImages", [])]
    for image in images:
        for key in _DROPPED_IMAGE_KEYS:
            image.pop(key, None)
    if not published:
        work["seedPublished"] = False
    return work


async def _image(
    session: AsyncSession, files: dict[str, bytes], asset_id: str | None, stem: str
) -> dict[str, Any] | None:
    """자산 원본 바이트를 `images/` 에 담고 매니페스트 항목을 돌려준다. 그림이 없는 자리는 None."""
    if asset_id is None:
        return None
    asset = await session.get(Asset, uuid.UUID(asset_id))
    assert asset is not None
    data = await asyncio.to_thread(download_object, asset.storage_key)
    content_type = read_image_content_type(data)
    extension = content_type.removeprefix("image/") if content_type else "bin"
    name = f"{stem}.{extension}"
    files[f"images/{name}"] = data
    return {
        "file": name,
        "kind": asset.kind.value,
        "contentType": content_type,
        "frameCount": read_frame_count(data),
        "crop": asset.crop,
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _tar_gz(files: dict[str, bytes]) -> bytes:
    """이름순·고정 시각·고정 소유자로 묶는다 — 같은 내용이면 같은 바이트(같은 sha256)가 나온다."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    gz_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buffer, mode="wb", mtime=0) as compressed:
        compressed.write(tar_buffer.getvalue())
    return gz_buffer.getvalue()


async def run(session: AsyncSession, map_path: Path, out: Path) -> int:
    """맵을 읽어 내보내고 요약 한 줄을 찍은 뒤 종료 코드를 돌려준다 — 성공 0, 안전장치 거부 `EXIT_REFUSED`."""
    try:
        summary = await export_seed_bundle(session, read_map(map_path), out)
    except ExportRefusedError as refused:
        print(f"거부했다 — 묶음을 만들지 않았다: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"작품 {summary.works}편 · 이미지 {summary.images}장 · {summary.size_bytes} 바이트 · sha256 {summary.sha256}")
    return 0


async def _run(args: argparse.Namespace) -> int:
    from api.db.session import async_session_factory

    async with async_session_factory() as session:
        try:
            return await run(session, args.map, args.out)
        finally:
            await session.rollback()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="운영 작품을 비공개 시드 묶음으로 읽기 전용 내보내기")
    parser.add_argument("--map", type=Path, required=True, help="한 줄에 `<콘텐츠 uuid> <시드 slug>`")
    parser.add_argument("--out", type=Path, required=True, help="만들 tar.gz — 이미 있으면 거부한다")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
