"""노벨 화 읽기(독자·어드민)에 싣는 삽화 — 얼린 판의 그림을 문단 번호로.

**언제 싣나**: 삽화 스위치가 켜졌고 그 판(화 공개본·판 행)이 삽화를 심사했을 때만이다(`screened_for`). 스위치가 꺼진 동안이나
이 칸을 모르는 코드가 얼린 판에는 심사받지 않은 그림이 승계돼 있을 수 있다. 잠긴 화(소장하지 않은 유료 화)는 글처럼 그림도 싣지
않는다 — 호출부가 정한다.

**어디에**: 노벨·어드민 응답은 블록 id 를 싣지 않으므로 앵커 문단의 번호(본문 문단 배열의 인덱스)와 앞뒤, 같은 자리 안의 순위로
싣는다. 위치 확인 필요인 그림은 싣지 않는다.

**자리만 남기는 그림**(주소 없이 사유만):
- 운영자가 내린 그림(`taken_down`) — 내림 표의 자산 id 로 본다. 사유는 운영자가 적은 독자용 문장이다. 모든 판에 걸린다.
- 운영자가 원작을 이용제한·삭제한 동안의 원작 그림(`original_restricted`) — 원작 행이 정상 상태가 아니면(원작자 정지로 걸린
  일괄 제한도 운영자 조치라 포함한다) 그 원작에서 온 그림만
  비운다(글과 다른 그림은 그대로). 원작자의 탈퇴·비공개는 그림을 빼지 않는다(연재권이 고정된 소설의 이용은 이어진다).
환급은 없다 — 그림 자리만 비우고 판은 그대로다."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.s3 import build_display_key, generate_presigned_get_url
from api.db.models.content import Content, ModerationStatus
from api.db.models.media import Asset
from api.db.models.novel import (
    NovelChapterRevision,
    NovelIllustrationPlacement,
    NovelIllustrationSource,
    NovelIllustrationTakedown,
)
from api.novel_public.schemas import NovelIllustrationWithheld, PublicNovelIllustration
from api.novelize.illustrations import placements_of


@dataclass(frozen=True)
class FrozenIllustration:
    paragraph_index: int
    placement: NovelIllustrationPlacement
    order: int
    asset_id: uuid.UUID
    source: NovelIllustrationSource
    url: str | None
    width: int | None
    height: int | None
    withheld: NovelIllustrationWithheld | None
    withheld_reason: str | None


def screened_for(screened_at: datetime | None, published_at: datetime) -> bool:
    """그 판이 지금 얼린 개정의 삽화를 심사했는가 — 심사 시각이 그 판의 공개 시각과 같을 때만이다. 공개는 두 칸을 같은
    트랜잭션 시각으로 함께 쓴다. 심사 시각을 모르는 옛 코드가 화 공개본을 다시 내면(UPDATE) 개정과 공개 시각만 바꾸고 앞 판의
    심사 시각을 남기므로, 비어 있는지만 보면 옛 코드가 얼린 미심사 그림이 남은 시각 덕에 독자에게 나간다."""
    return screened_at is not None and screened_at == published_at


async def frozen_illustrations(
    db: AsyncSession,
    *,
    revision_id: uuid.UUID,
    screened_at: datetime | None,
    published_at: datetime,
    content_id: uuid.UUID,
) -> list[FrozenIllustration]:
    """판이 얼린 개정 `revision_id` 의 그림(모듈 docstring 의 조건). `screened_at`·`published_at` 은 그 판의 두 칸,
    `content_id` 는 그 소설의 원작이다."""
    if not settings.novel_illustrations_enabled or not screened_for(screened_at, published_at):
        return []
    revision = await db.get_one(NovelChapterRevision, revision_id)
    rows = [row for row in await placements_of(db, revision) if row.anchor_block_id is not None]
    if not rows:
        return []
    asset_ids = {row.asset_id for row in rows}
    assets = {asset.id: asset for asset in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()}
    takedowns = dict(
        (
            await db.execute(
                select(NovelIllustrationTakedown.asset_id, NovelIllustrationTakedown.reason).where(
                    NovelIllustrationTakedown.asset_id.in_(asset_ids)
                )
            )
        )
        .tuples()
        .all()
    )
    source_status = await db.scalar(select(Content.moderation_status).where(Content.id == content_id))
    original_restricted = source_status != ModerationStatus.NORMAL
    position = {block_id: index for index, block_id in enumerate(revision.block_ids)}
    rank: dict[tuple[int, str], int] = {}
    shown: list[FrozenIllustration] = []
    for row in rows:
        if row.anchor_block_id is None or row.placement is None:
            continue
        paragraph = position[row.anchor_block_id]
        order = rank.get((paragraph, row.placement), 0)
        rank[(paragraph, row.placement)] = order + 1
        withheld: NovelIllustrationWithheld | None = None
        if row.asset_id in takedowns:
            withheld = "taken_down"
        elif row.source == "original" and original_restricted:
            withheld = "original_restricted"
        asset = assets[row.asset_id]
        shown.append(
            FrozenIllustration(
                paragraph_index=paragraph,
                placement=row.placement,
                order=order,
                asset_id=row.asset_id,
                source=row.source,
                url=generate_presigned_get_url(build_display_key(asset.storage_key)) if withheld is None else None,
                width=asset.width,
                height=asset.height,
                withheld=withheld,
                withheld_reason=takedowns[row.asset_id] if withheld == "taken_down" else None,
            )
        )
    return shown


def public_illustrations(illustrations: list[FrozenIllustration]) -> list[PublicNovelIllustration]:
    return [
        PublicNovelIllustration(
            paragraph_index=item.paragraph_index,
            placement=item.placement,
            order=item.order,
            source=item.source,
            url=item.url,
            width=item.width,
            height=item.height,
            withheld=item.withheld,
            withheld_reason=item.withheld_reason,
        )
        for item in illustrations
    ]
