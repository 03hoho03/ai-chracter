"""미디어 북 태그를 한 버전의 칸으로 해석하는 DB 조회. 태그 문법 자체는 `media_tags.py`(순수 함수)에 있다.

방 응답·엔딩·상세처럼 화면으로 글을 내보내는 곳이 같은 두 단계를 지난다 — 이름 형태를 그 버전의 칸 id 로
바꾸고(`normalize_texts`), 글이 가리키는 칸의 그림을 서명한다(`resolve_media_tag_images`). 둘을 한 번에
하는 것이 `normalize_texts_for_display` 다.
칸은 늘 "그 글이 속한 버전"에서 찾는다 — 방이면 방이 고정한 버전, 상세면 현재 발행본이다."""

import uuid
from collections.abc import Iterable

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.content.media_tags import normalize_media_tags
from api.content.schemas import MediaTagImage
from api.core.s3 import generate_presigned_get_url
from api.db.models.media import Asset
from api.db.models.story import MediaBookCell, MediaBookPerson, MediaBookScene


async def load_media_cells_by_name(db: AsyncSession, version_id: uuid.UUID) -> dict[tuple[str, str], uuid.UUID]:
    """버전의 칸을 (인물 이름, 장면 이름) → 칸 entity_id 로 읽는다. 축이 사라진 칸은 이름이 없어 빠진다."""
    rows = await db.execute(
        select(MediaBookPerson.name, MediaBookScene.name, MediaBookCell.entity_id)
        .select_from(MediaBookCell)
        .join(
            MediaBookPerson,
            and_(
                MediaBookPerson.content_version_id == MediaBookCell.content_version_id,
                MediaBookPerson.entity_id == MediaBookCell.person_entity_id,
            ),
        )
        .join(
            MediaBookScene,
            and_(
                MediaBookScene.content_version_id == MediaBookCell.content_version_id,
                MediaBookScene.entity_id == MediaBookCell.scene_entity_id,
            ),
        )
        .where(MediaBookCell.content_version_id == version_id)
    )
    return {(person, scene): cell_id for person, scene, cell_id in rows.tuples()}


def _sign_original_urls(storage_keys: list[str]) -> list[str]:
    return [generate_presigned_get_url(key) for key in storage_keys]


async def resolve_media_tag_images(
    db: AsyncSession, version_id: uuid.UUID, cell_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, MediaTagImage]:
    """칸 id 들을 그 버전의 칸 그림으로 해석한다. 버전에 없는 칸은 맵에서 빠진다(화면은 빈칸)."""
    wanted = set(cell_ids)
    if not wanted:
        return {}
    pairs = (
        await db.execute(
            select(MediaBookCell.entity_id, Asset)
            .join(Asset, Asset.id == MediaBookCell.image_asset_id)
            .where(MediaBookCell.content_version_id == version_id, MediaBookCell.entity_id.in_(wanted))
        )
    ).tuples().all()
    urls = await run_in_threadpool(_sign_original_urls, [asset.storage_key for _, asset in pairs])
    return {
        cell_id: MediaTagImage(url=url, width=asset.width, height=asset.height)
        for (cell_id, asset), url in zip(pairs, urls, strict=True)
    }


async def normalize_texts(
    db: AsyncSession, version_id: uuid.UUID, texts: list[str]
) -> tuple[list[str], set[uuid.UUID]]:
    """이름 형태 태그가 든 작성자 글들을 그 버전의 칸 id 형태로 바꾸고, 글들이 가리키는 칸 id 합집합을
    돌려준다. 태그가 하나도 없으면 칸을 읽지 않는다 — 미디어 북을 안 쓰는 작품은 쿼리 수가 그대로다."""
    if not any("{{img::" in text for text in texts):
        return texts, set()
    cells_by_name = await load_media_cells_by_name(db, version_id)
    normalized: list[str] = []
    referenced: set[uuid.UUID] = set()
    for text in texts:
        id_text, refs = normalize_media_tags(text, cells_by_name)
        normalized.append(id_text)
        referenced |= refs
    return normalized, referenced


async def normalize_texts_for_display(
    db: AsyncSession, version_id: uuid.UUID, texts: list[str]
) -> tuple[list[str], dict[uuid.UUID, MediaTagImage]]:
    """`normalize_texts` 에 더해 글들이 가리키는 칸 그림 맵을 함께 돌려준다."""
    normalized, referenced = await normalize_texts(db, version_id, texts)
    return normalized, await resolve_media_tag_images(db, version_id, referenced)
