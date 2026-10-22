"""노벨 화 읽기(독자·어드민)에 싣는 삽화 — 얼린 판의 그림을 문단 번호로.

**언제 싣나**: 삽화 스위치가 켜졌고 그 판(화 공개본·판 행)이 삽화를 심사했을 때만이다(`screened_for`). 스위치가 꺼진 동안이나
이 칸을 모르는 코드가 얼린 판에는 심사받지 않은 그림이 승계돼 있을 수 있다. 잠긴 화(소장하지 않은 유료 화)는 글처럼 그림도 싣지
않는다 — 호출부가 정한다.

**어디에**: 노벨·어드민 응답은 블록 id 를 싣지 않으므로 앵커 문단의 번호(본문 문단 배열의 인덱스)와 앞뒤, 같은 자리 안의 순위로
싣는다. 위치 확인 필요인 그림은 싣지 않는다.

**자리만 남기는 그림**(주소 없이 사유만):
- 운영자가 내린 그림(`taken_down`) — 자산 행에 적힌 바이트 sha 로 내림 표를 잇는다(`takedown_reasons`). 같은 파일을 담은 다른
  자산도 걸린다. 사유는 운영자가 적은 독자용 문장이다. 모든 판에 걸린다.
- 운영자가 원작 작품을 이용제한·삭제한 동안의 원작 그림(`original_restricted`) — 원작 행이 정상 상태가 아니면 그 원작에서 온
  그림만 비운다. 원작자 계정 정지로 걸린 일괄 제한은 빼고 본다 — 원작자 탈퇴와 같이 그림을 그대로 보인다(소장자 열람 조건이
  정지 제한을 정상과 같이 보는 것과 같은 판단). 글과 다른 그림은 그대로다. 원작자의 탈퇴·비공개도 그림을 빼지 않는다(연재권이
  고정된 소설의 이용은 이어진다).
환급은 없다 — 그림 자리만 비우고 판은 그대로다.

**작가 화면**: 작가 자신의 화·개정 응답도 같은 두 까닭으로 자리만 남긴다(`owner_withholdings`). 그 개정의 그림 전부에 건다."""

import asyncio
import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.core.config import settings
from api.core.s3 import build_display_key, generate_presigned_get_url
from api.core.sentry import capture_dependency_failure
from api.db.models.content import Content, ModerationStatus
from api.db.models.media import Asset
from api.db.models.novel import (
    NovelChapterIllustration,
    NovelChapterRevision,
    NovelIllustrationPlacement,
    NovelIllustrationSource,
    NovelIllustrationTakedown,
    NovelIllustrationWithheld,
)
from api.novel_public.illustration_screening import download_display, sha256_of
from api.novel_public.schemas import PublicNovelIllustration
from api.novelize.illustrations import placements_of

logger = logging.getLogger(__name__)


async def _original_restricted(db: AsyncSession, content_id: uuid.UUID) -> bool:
    """운영자가 원작을 이용제한·삭제한 동안인가(모듈 docstring 의 원작 그림 규칙)."""
    source = (
        await db.execute(
            select(Content.moderation_status, Content.restricted_by_suspension).where(Content.id == content_id)
        )
    ).one_or_none()
    # 원작 행이 없으면 운영 제한과 같이 본다(풀어 줄 근거가 없다). 원작자 정지로 걸린 일괄 제한은 빼고 본다.
    return source is None or (source[0] != ModerationStatus.NORMAL and not source[1])


async def takedown_reasons(db: AsyncSession, asset_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """내린 그림인 자산 → 운영자 사유. 내림 표를 자산 행에 적힌 바이트 sha 로 잇는다 — 같은 파일을 담은 다른 자산도 내린
    그림이다. 그 자산 자신이 내린 자산이면 자산 id 로도 잇는다(바이트 sha 가 아직 적히지 않은 자산 — 이 칸이 생기기 전에 내린
    자산이나 그 칸을 모르는 코드가 내린 자산). 둘 다 걸리면 자산 id 로 내린 기록의 사유가 먼저다."""
    wanted = set(asset_ids)
    if not wanted:
        return {}
    rows = await db.execute(
        select(Asset.id, NovelIllustrationTakedown.reason)
        .join(
            NovelIllustrationTakedown,
            or_(
                NovelIllustrationTakedown.asset_id == Asset.id,
                NovelIllustrationTakedown.content_sha256 == Asset.display_sha256,
            ),
        )
        .where(Asset.id.in_(wanted))
        .order_by(NovelIllustrationTakedown.asset_id != Asset.id)
    )
    found: dict[uuid.UUID, str] = {}
    for asset_id, reason in rows.tuples():
        found.setdefault(asset_id, reason)
    return found


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
    takedowns = await takedown_reasons(db, asset_ids)
    original_restricted = await _original_restricted(db, content_id)
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


# ── 작가 화면 ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Withholding:
    withheld: NovelIllustrationWithheld
    reason: str | None


async def owner_withholdings(
    db: AsyncSession,
    rows: Sequence[NovelChapterIllustration],
    assets: Mapping[uuid.UUID, Asset],
    *,
    content_id: uuid.UUID,
) -> dict[uuid.UUID, Withholding]:
    """작가 자신의 화·개정 응답에서 자리만 남길 그림(배치 id → 까닭). 독자와 같은 두 까닭이고 사유도 같다 — 작가가 독자가 보는
    빈 자리를 알고, 다시 공개 전에 바꾸거나 뗄 그림을 안다. 판·심사와 무관하게 그 개정의 모든 배치(위치 확인 필요 포함)에 건다.

    내림은 다시 공개가 거부하는 기준과 같게 그림의 바이트(정지 변형의 sha)로 본다 — 같은 파일을 새 자산으로 다시 올린 그림도
    내림으로 보인다. `assets` 는 `rows` 의 자산이다."""
    takedowns = await _owner_takedowns(db, assets)
    restricted = any(row.source == "original" for row in rows) and await _original_restricted(db, content_id)
    withheld: dict[uuid.UUID, Withholding] = {}
    for row in rows:
        if row.asset_id in takedowns:
            withheld[row.id] = Withholding("taken_down", takedowns[row.asset_id])
        elif row.source == "original" and restricted:
            withheld[row.id] = Withholding("original_restricted", None)
    return withheld


async def _owner_takedowns(db: AsyncSession, assets: Mapping[uuid.UUID, Asset]) -> dict[uuid.UUID, str]:
    """내린 그림인 자산 → 운영자 사유. 독자와 같이 자산 행의 바이트 sha 로 잇고(`takedown_reasons`), 바이트 sha 가 아직 적히지
    않은 자산(공개 심사를 거친 적 없는 그림 — 작가가 다시 올린 파일이 여기 든다)만 내려받아 대조한다. 다시 공개가 바이트로
    막으므로 작가 화면도 바이트로 봐야 하는데, 그런 자산은 행에 값이 없다. 내림이 하나도 없으면 아무것도 보지 않는다. 내려받기가
    실패하면 응답을 실패시키지 않고(편집 결과를 돌려주는 자리다) 이어진 것만 돌려준다. 읽기라 내려받은 sha 를 행에 적지는 않는다."""
    if not assets or await db.scalar(select(NovelIllustrationTakedown.content_sha256).limit(1)) is None:
        return {}
    found = await takedown_reasons(db, assets)
    unknown = [asset_id for asset_id, asset in assets.items() if asset.display_sha256 is None and asset_id not in found]
    if not unknown:
        return found
    try:
        data = await asyncio.gather(*(run_in_threadpool(download_display, assets[i].storage_key) for i in unknown))
    except (BotoCoreError, ClientError) as exc:
        logger.warning("novel_owner_illustration_download_failed: %s", type(exc).__name__)
        capture_dependency_failure(exc, dependency="s3")
        return found
    shas = {asset_id: sha256_of(item) for asset_id, item in zip(unknown, data, strict=True)}
    by_sha = dict(
        (
            await db.execute(
                select(NovelIllustrationTakedown.content_sha256, NovelIllustrationTakedown.reason).where(
                    NovelIllustrationTakedown.content_sha256.in_(set(shas.values()))
                )
            )
        )
        .tuples()
        .all()
    )
    return {**found, **{asset_id: by_sha[sha] for asset_id, sha in shas.items() if sha in by_sha}}
