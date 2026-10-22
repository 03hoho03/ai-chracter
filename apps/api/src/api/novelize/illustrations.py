"""소설 화 삽화 — 개정을 넣으며 배치를 잇는 단 한 곳, 배치 읽기, 작가가 쓸 수 있는 그림 판정, 업로드 삽화 파일 정리.

**배치 승계**: 개정 행은 `add_revision` 하나로만 세션에 넣는다(테스트가 구조로 검사한다). 그 자리에서 새 개정의 배치를 쓴다.
- 되돌리기·스냅숏 복원(`reverted_from_revision_id` 가 찬 개정): 원본 개정의 배치를 그대로 복사한다. 블록 id 도 원본 것을 복제하므로
  모든 앵커가 살아 있다.
- 배치 변경(붙이기·옮기기·바꾸기·떼기): 호출자가 계산한 배치를 그대로 쓴다.
- 그 밖(직접 수정·AI 수정 적용·다시 만들기): 앞 개정에서 앵커 문단 블록 id 가 새 개정에도 있는 배치는 자리 그대로 잇고, 사라진
  배치는 "위치 확인 필요"(앵커·앞뒤 없음)로 잇는다 — 다른 문단으로 옮기지 않는다. 이미 위치 확인 필요인 배치도 그대로 잇는다.
- 생성: 앞 개정이 없어 배치도 없다.
순서(`sort_order`)는 쓸 때마다 자리(앵커·앞뒤)마다, 그리고 위치 확인 필요끼리 0부터 빈틈없이 다시 매긴다 — 화면이 같은 두 개정의
배치가 저장값까지 같도록.

배치 행은 쓰고 지울 뿐 고치지 않는다(공개본이 얼린 개정의 그림이 나중에 바뀌지 않는다는 전제, 테스트가 구조로 검사한다).

**쓸 수 있는 그림**: 내가 올린 삽화 용도 업로드(준비된 것), 내가 만든 이미지(준비된 것), 원작 그림 후보(`original_candidates`).
원작 그림 후보는 원작의 지금 발행본에서 고른다 — 대표 이미지는 늘, 상황 이미지·미디어 북 칸은 작가가 그 작품에서 본 것(사용자+작품
노출 기록)만. 작가가 원작자 본인이면 지금 발행본의 그림 전부다. 원작을 그 작가에게 열 수 없으면(이용제한·남의 비공개 등) 후보가 없다.

**삽화 파일 정리**: 업로드 삽화(와 소유자가 탈퇴한 생성 이미지)는 어느 개정도 쓰지 않게 되면 소설 삭제·묶음 삭제·탈퇴·숨긴 소설
파기 때 자산 행과 저장소 파일(원본·변형)을 함께 지운다. 떼기만으로는 지우지 않는다(앞 개정이 여전히 쓴다)."""

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import ColumnElement, Select, SQLColumnExpression, and_, delete, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from starlette.concurrency import run_in_threadpool

from api.assets.router import collect_asset_usages
from api.assets.schemas import AssetPurpose
from api.content.access import is_open_to_participant
from api.core.s3 import build_display_key, build_variant_keys, delete_object, generate_presigned_get_url
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.chat import CharacterImageExposure, StoryMediaExposure
from api.db.models.content import Content, ContentType
from api.db.models.inquiry import Inquiry
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.novel import (
    Novel,
    NovelChapterIllustration,
    NovelChapterRevision,
    NovelIllustrationPlacement,
    NovelIllustrationSource,
)
from api.db.models.story import MediaBookCell, StoryVersionDetail

logger = logging.getLogger(__name__)

# 업로드 삽화 자산의 저장 키 접두. 자산 행에 용도 칸이 없어 키 경로로 용도를 가린다(`assets/router.py` 의 `_upload_purpose`).
UPLOAD_KEY_PREFIX = f"assets/{AssetPurpose.NOVEL_ILLUSTRATION.value}/"

OriginalKind = Literal["thumbnail", "situationalImage", "mediaBook"]

# 한 화(개정 하나)에 둘 수 있는 삽화 수. 위치 확인 필요인 그림도 센다 — 다시 놓으면 화에 나가는 그림이다. 붙이기가 이 수에서
# 막고, 공개도 문단에 붙은 그림이 이 수를 넘으면 막는다(이 상한 전에 쌓인 개정이 있어도 넘는 화가 나가지 않게). 심사 원가와 한
# 화의 쪽 수를 묶는 정책값이다.
NOVEL_ILLUSTRATION_LIMIT = 10


@dataclass(frozen=True)
class PlacementSpec:
    """새 개정에 쓸 배치 한 장. 앵커·앞뒤가 둘 다 None 이면 위치 확인 필요다. 순서 칸은 없다 — 같은 자리 안의 목록 순서가 순서다."""

    anchor_block_id: uuid.UUID | None
    placement: NovelIllustrationPlacement | None
    asset_id: uuid.UUID
    source: NovelIllustrationSource


@dataclass(frozen=True)
class OriginalCandidate:
    asset: Asset
    kind: OriginalKind


# ── 배치 읽기·쓰기 ──────────────────────────────────────────────────────────
async def placements_of(db: AsyncSession, revision: NovelChapterRevision) -> list[NovelChapterIllustration]:
    """개정의 배치를 읽는 순서로 — 위치 있는 것은 앵커 문단 순서·앞 먼저·자리 안 순서, 그 뒤에 위치 확인 필요(순서)."""
    rows = list(
        (
            await db.scalars(
                select(NovelChapterIllustration).where(NovelChapterIllustration.revision_id == revision.id)
            )
        ).all()
    )
    position = {block_id: index for index, block_id in enumerate(revision.block_ids)}

    def key(row: NovelChapterIllustration) -> tuple[int, int, int, int]:
        if row.anchor_block_id is None:
            return (1, 0, 0, row.sort_order)
        return (0, position.get(row.anchor_block_id, len(position)), 0 if row.placement == "before" else 1, row.sort_order)

    return sorted(rows, key=key)


def placement_fingerprint(revision_id: SQLColumnExpression[uuid.UUID] | uuid.UUID) -> ColumnElement[str | None]:
    """개정 `revision_id` 의 삽화가 독자 화면에 놓이는 모양 — SQL 스칼라(문단에 붙은 그림이 없으면 NULL). 두 개정의 값이 같으면
    (본문이 같을 때) 독자 화면의 그림이 같다. 공개 변경 판정이 공개본 개정과 지금 개정을 이 값으로 비교한다.

    한 그림은 (앵커 문단의 번호, 앞뒤, 그림, 출처)이고 (문단 번호, 앞뒤, 순서 값) 순으로 잇는다. 블록 id 가 아니라 문단 번호인
    것은 같은 글로 문단을 다시 쓰거나 승계 규칙으로 앵커 id 가 바뀐 뒤 같은 자리에 다시 붙인 화가 화면이 같은데 "바뀜"이 되지
    않게 하려는 것이다. 순서 값을 싣지 않고 잇는 순서로만 쓰는 것은 같은 자리 안의 순위만 화면에 보이기 때문이다(저장값이 듬성해도
    같다). 출처는 "원작 이미지" 표시를 바꾸므로 싣는다. 위치 확인 필요인 그림은 독자에게 안 나가 뺀다."""
    owner = aliased(NovelChapterRevision)
    row = aliased(NovelChapterIllustration)
    paragraph = func.array_position(owner.block_ids, row.anchor_block_id)
    entry = func.concat_ws(literal_column("':'"), paragraph, row.placement, row.asset_id, row.source)
    return (
        select(func.string_agg(entry, aggregate_order_by(literal_column("','"), paragraph, row.placement, row.sort_order)))
        .select_from(row)
        .join(owner, owner.id == row.revision_id)
        .where(row.revision_id == revision_id, row.anchor_block_id.is_not(None))
        .correlate_except(row, owner)
        .scalar_subquery()
    )


def specs_of(rows: Sequence[NovelChapterIllustration]) -> list[PlacementSpec]:
    return [PlacementSpec(row.anchor_block_id, row.placement, row.asset_id, row.source) for row in rows]


def _inherited(rows: Sequence[NovelChapterIllustration], block_ids: Sequence[uuid.UUID]) -> list[PlacementSpec]:
    survivors = set(block_ids)
    placed: list[PlacementSpec] = []
    unplaced: list[PlacementSpec] = []
    for spec in specs_of(rows):
        if spec.anchor_block_id is not None and spec.anchor_block_id in survivors:
            placed.append(spec)
        else:
            unplaced.append(PlacementSpec(None, None, spec.asset_id, spec.source))
    return [*placed, *unplaced]


def _write(db: AsyncSession, revision_id: uuid.UUID, specs: Sequence[PlacementSpec]) -> None:
    next_order: dict[tuple[uuid.UUID | None, str | None], int] = {}
    for spec in specs:
        slot = (spec.anchor_block_id, spec.placement)
        order = next_order.get(slot, 0)
        next_order[slot] = order + 1
        db.add(
            NovelChapterIllustration(
                revision_id=revision_id,
                anchor_block_id=spec.anchor_block_id,
                placement=spec.placement,
                sort_order=order,
                asset_id=spec.asset_id,
                source=spec.source,
            )
        )


async def add_revision(
    db: AsyncSession,
    revision: NovelChapterRevision,
    *,
    previous: NovelChapterRevision | None,
    placements: Sequence[PlacementSpec] | None = None,
) -> NovelChapterRevision:
    """개정 행을 세션에 넣고(flush) 그 배치를 쓴다(모듈 docstring 의 승계 규칙). `previous` 는 같은 화의 바로 앞 개정(생성이면
    None), `placements` 는 배치 변경이 계산한 새 배치다. 커밋은 호출자."""
    db.add(revision)
    await db.flush()
    if placements is not None:
        specs = list(placements)
    elif revision.reverted_from_revision_id is not None:
        origin = await db.get_one(NovelChapterRevision, revision.reverted_from_revision_id)
        specs = specs_of(await placements_of(db, origin))
    elif previous is not None:
        specs = _inherited(await placements_of(db, previous), revision.block_ids)
    else:
        specs = []
    _write(db, revision.id, specs)
    if specs:
        await db.flush()
    return revision


@dataclass(frozen=True)
class PlacementView:
    row: NovelChapterIllustration
    url: str
    width: int | None
    height: int | None


async def placement_views(db: AsyncSession, revision: NovelChapterRevision) -> list[PlacementView]:
    """개정의 배치와 그림 주소(크게 그리는 정지 변형)·크기. 읽는 순서다."""
    rows = await placements_of(db, revision)
    if not rows:
        return []
    assets = {
        asset.id: asset
        for asset in (await db.scalars(select(Asset).where(Asset.id.in_({row.asset_id for row in rows})))).all()
    }
    return [
        PlacementView(
            row=row,
            url=generate_presigned_get_url(build_display_key(assets[row.asset_id].storage_key)),
            width=assets[row.asset_id].width,
            height=assets[row.asset_id].height,
        )
        for row in rows
    ]


# ── 쓸 수 있는 그림 ─────────────────────────────────────────────────────────
async def original_candidates(db: AsyncSession, novel: Novel) -> list[OriginalCandidate]:
    """원작 그림 후보(모듈 docstring). 대표 이미지 → 상황 이미지·미디어 북 칸 순서."""
    content = await db.get(Content, novel.content_id)
    if (
        content is None
        or content.current_published_version_id is None
        or not await is_open_to_participant(db, content, novel.user_id)
    ):
        return []
    version_id = content.current_published_version_id
    is_creator = content.creator_user_id == novel.user_id
    found: list[tuple[uuid.UUID, OriginalKind]] = []
    detail_model = CharacterVersionDetail if content.type == ContentType.CHARACTER else StoryVersionDetail
    thumbnail = await db.scalar(
        select(detail_model.thumbnail_asset_id).where(detail_model.content_version_id == version_id)
    )
    if thumbnail is not None:
        found.append((thumbnail, "thumbnail"))
    if content.type == ContentType.CHARACTER:
        images = select(SituationalImage.image_asset_id).where(
            SituationalImage.content_version_id == version_id, SituationalImage.image_asset_id.is_not(None)
        )
        if not is_creator:
            images = images.where(
                SituationalImage.entity_id.in_(
                    select(CharacterImageExposure.image_entity_id).where(
                        CharacterImageExposure.user_id == novel.user_id, CharacterImageExposure.content_id == content.id
                    )
                )
            )
        rows = (await db.scalars(images.order_by(SituationalImage.order))).all()
        found += [(asset_id, "situationalImage") for asset_id in rows if asset_id is not None]
    else:
        cells = select(MediaBookCell.image_asset_id).where(MediaBookCell.content_version_id == version_id)
        if not is_creator:
            cells = cells.where(
                MediaBookCell.entity_id.in_(
                    select(StoryMediaExposure.cell_entity_id).where(
                        StoryMediaExposure.user_id == novel.user_id, StoryMediaExposure.content_id == content.id
                    )
                )
            )
        found += [(asset_id, "mediaBook") for asset_id in (await db.scalars(cells)).all()]
    if not found:
        return []
    assets = {
        asset.id: asset
        for asset in (await db.scalars(select(Asset).where(Asset.id.in_({asset_id for asset_id, _ in found})))).all()
    }
    seen: set[uuid.UUID] = set()
    candidates: list[OriginalCandidate] = []
    for asset_id, kind in found:
        if asset_id in assets and asset_id not in seen:
            seen.add(asset_id)
            candidates.append(OriginalCandidate(assets[asset_id], kind))
    return candidates


async def usable_asset(
    db: AsyncSession, novel: Novel, asset_id: uuid.UUID, source: NovelIllustrationSource
) -> bool:
    """작가가 이 그림을 이 출처로 붙일 수 있는가. 자산 행을 키 공유 잠금으로 확인한다 — 확인과 배치 저장 사이에 그림 행이 먼저
    지워지면 저장이 FK 거부로 500 이 되는데, 잠금을 쥐면 행 DELETE 가 이 저장의 커밋을 기다린다. 기다린 DELETE 는 새 배치의 FK 에
    걸려 실패한다(생성 이미지 삭제가 사용처를 다시 본 뒤 행을 지우기까지의 틈 — 작품 그림에도 있는 드문 경합이다)."""
    query = select(Asset).where(Asset.id == asset_id).with_for_update(key_share=True, read=True)
    if source == "original":
        if asset_id not in {candidate.asset.id for candidate in await original_candidates(db, novel)}:
            return False
        return await db.scalar(query) is not None
    asset = await db.scalar(query)
    if asset is None or asset.owner_user_id != novel.user_id or asset.status != AssetStatus.READY:
        return False
    if source == "generated":
        return asset.kind == AssetKind.GENERATED
    return asset.kind == AssetKind.ORIGINAL and asset.storage_key.startswith(UPLOAD_KEY_PREFIX)


# ── 업로드 삽화 파일 정리 ───────────────────────────────────────────────────
def assets_used_by(revision_ids: Select[tuple[uuid.UUID]]) -> Select[tuple[uuid.UUID]]:
    """`revision_ids` 개정의 배치가 쓰는 그림 id(출처 무관)."""
    return select(NovelChapterIllustration.asset_id).where(NovelChapterIllustration.revision_id.in_(revision_ids))


async def drop_placements(db: AsyncSession, revision_ids: Select[tuple[uuid.UUID]]) -> set[uuid.UUID]:
    """`revision_ids` 개정의 배치를 지우고, 그 배치가 쓰던 그림 id 를 돌려준다(정리 후보). 개정을 지우기 전에 부른다."""
    used = set((await db.scalars(assets_used_by(revision_ids))).all())
    await db.execute(delete(NovelChapterIllustration).where(NovelChapterIllustration.revision_id.in_(revision_ids)))
    return used


async def delete_unused_illustration_assets(db: AsyncSession, asset_ids: Iterable[uuid.UUID]) -> list[str]:
    """`asset_ids` 중 이제 아무도 쓰지 않는 삽화 파일의 자산 행을 지우고, 지울 저장소 키(원본·변형)를 돌려준다. 저장소는 호출자가
    커밋 뒤에 지운다. 지우는 것은 둘이다 — 업로드 삽화, 그리고 소유자가 탈퇴한 생성 이미지(탈퇴 때 숨겨 남긴 팔린 소설의 판이 써서
    남겼던 것 — 그 소설이 파기되면 지울 사람이 없다). 원작 그림·살아 있는 회원의 생성 이미지는 그 사람의 것이라 남긴다.

    배치뿐 아니라 다른 자리(작품 그림·문의 첨부·프로필·소설 표지)가 가리키는 것도 남긴다 — 업로드 API 는 용도와 무관하게 내 자산을
    받는 자리가 있어서다. 후보 자산 행을 먼저 잠근다(`FOR UPDATE`) — 붙이기는 그림 행을 키 공유 잠금으로 확인하므로, 같은 그림을
    다른 소설에 붙이는 중이면 그 커밋을 기다렸다가 새 배치를 사용처로 본다(잠그지 않으면 행 DELETE 가 그 배치 FK 에 걸려 500)."""
    ids = set(asset_ids)
    if not ids:
        return []
    withdrawn_owner = select(User.id).where(User.id == Asset.owner_user_id, User.deleted_at.is_not(None)).exists()
    assets = list(
        (
            await db.scalars(
                select(Asset)
                .where(
                    Asset.id.in_(ids),
                    or_(
                        and_(Asset.kind == AssetKind.ORIGINAL, Asset.storage_key.startswith(UPLOAD_KEY_PREFIX)),
                        and_(Asset.kind == AssetKind.GENERATED, withdrawn_owner),
                    ),
                )
                .order_by(Asset.id)
                .with_for_update()
            )
        ).all()
    )
    if not assets:
        return []
    candidate_ids = [asset.id for asset in assets]
    referenced: set[uuid.UUID | None] = set((await collect_asset_usages(db, candidate_ids)).keys())
    for column in (
        NovelChapterIllustration.asset_id,
        Inquiry.attachment_asset_id,
        User.profile_image_asset_id,
        Novel.cover_asset_id,
    ):
        referenced |= set((await db.scalars(select(column).where(column.in_(candidate_ids)))).all())
    keys: list[str] = []
    for asset in assets:
        if asset.id in referenced:
            continue
        keys += [asset.storage_key, *build_variant_keys(asset.storage_key)]
        await db.delete(asset)
    await db.flush()
    return keys


async def delete_storage_objects(keys: Sequence[str]) -> None:
    """커밋 뒤에 업로드 삽화 파일을 저장소에서 지운다. 행은 이미 사라져 다시 시도할 길이 없으므로 하나가 실패해도 나머지를 지우고,
    실패는 남긴다(고아 파일)."""
    for key in keys:
        try:
            await run_in_threadpool(delete_object, key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("소설 삽화 업로드 파일 %s 를 지우지 못했다: %s", key, type(exc).__name__)
            capture_dependency_failure(exc, dependency="s3")
