"""노벨 공개 스위치 게이트와 원작 판정.

**원작 판정은 둘로 갈린다.** 새로 공개하는 것(처음 공개·다음 화 이어 붙이기)은 원작이 지금 공개 목록에 실리고(발행됨 ∧
공개 ∧ 이용제한 없음 — 작품 목록과 같은 조건) 원작자가 소설 공개를 허락했을 때만 된다. 게시자가 원작자 본인이면 허락은
따지지 않는다(자기 작품을 자기가 소설로 공개하는 데 허락이 필요 없다) — 공개 목록 조건은 본인도 따른다. 이미 공개한 것(공개한
화의 수정본·소설 제목·소개 다시 공개, 거뒀던 공개 다시 열기)은 원작이 이용제한·삭제만 아니면 된다 — 원작자가 허락을 낮추거나
원작을 비공개로 돌려도 이미 공개된 소설은 유지하고, 그 고친 내용을 다시 내는 것도 막지 않는다. 원작이 이용제한·삭제되면 그
원작의 공개 소설은 독자에게 보이지 않으므로 고쳐 다시 내는 것도 막는다.

원작 행이 없으면(소설은 원작 id 를 FK 없는 사본으로 들고 있다) 이용제한과 같이 본다 — 풀어 줄 근거가 없다."""

import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.content.access import publicly_listed_conditions
from api.core.config import settings
from api.db.models.auth import User
from api.db.models.content import Content, ModerationStatus
from api.db.models.novel import NovelPublication

# 새로 공개할 수 없는 이유. 앞의 것이 먼저다 — 이용제한은 모든 공개를 막고, 허락은 원작자가 바꿔야 풀리고, 목록 조건은
# 원작자가 다시 공개하면 풀린다.
NewPublishBlock = Literal["source_unavailable", "source_permission", "source_not_listed"]
# 이미 공개한 것을 다시 낼 수 없는 이유. `restricted` 는 운영자가 이 공개 소설을 내린 상태다.
RepublishBlock = Literal["source_unavailable", "restricted"]


def require_novel_public_enabled() -> None:
    """노벨 스위치(`novel_public_enabled`)가 꺼져 있으면 403 `NOVEL_PUBLIC_DISABLED`. 공개·다시 공개·게시자 공개 상태 조회
    라우터 수준 게이트다. 공개 거두기는 이 게이트 밖이다(자기 글을 내리는 일이라)."""
    if not settings.novel_public_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "NOVEL_PUBLIC_DISABLED"})


@dataclass(frozen=True)
class SourceGate:
    new_publish_block: NewPublishBlock | None
    source_available: bool


async def judge_source(db: AsyncSession, content_id: uuid.UUID, publisher_id: uuid.UUID) -> SourceGate:
    """공개 목록 조건은 작품 목록과 같은 식(`publicly_listed_conditions`)을 SQL 로 다시 물어 판정한다 — 조건을 여기 따로
    적으면 목록 조건이 바뀔 때 한쪽만 고쳐진다."""
    source = await db.get(Content, content_id, populate_existing=True)
    if source is None or source.moderation_status != ModerationStatus.NORMAL:
        return SourceGate(new_publish_block="source_unavailable", source_available=False)
    if source.creator_user_id != publisher_id and source.novel_permission != "public":
        return SourceGate(new_publish_block="source_permission", source_available=True)
    listed = await db.scalar(select(Content.id).where(Content.id == content_id, *publicly_listed_conditions()))
    return SourceGate(new_publish_block=None if listed is not None else "source_not_listed", source_available=True)


def readable_publication_conditions() -> tuple[ColumnElement[bool], ...]:
    """독자가 지금 이 공개 소설을 읽을 수 있는가 — SQL 조건. 공개 중(거두지 않음) ∧ 운영자 이용제한 없음 ∧ 게시자가 탈퇴·정지
    되지 않음 ∧ 원작이 이용제한·삭제되지 않음. 호출부가 `NovelPublication`·`Novel`·게시자 `User`(`User.id ==
    Novel.user_id`)·원작 `Content`(`Content.id == Novel.content_id`)를 조인한다.

    정지·원작 상태는 표식 칸을 두지 않고 조회 때 조인으로 본다 — 정지가 풀리거나 원작이 복구되면 표식을 되돌리지 않아도 다시
    보인다. 구매·열람·목록이 이 조건 하나를 함께 써야 "목록엔 없는데 구매는 되는" 틈이 생기지 않는다."""
    return (
        NovelPublication.visibility == "public",
        NovelPublication.moderation_status == "normal",
        User.deleted_at.is_(None),
        User.suspended_at.is_(None),
        Content.moderation_status == ModerationStatus.NORMAL,
    )
