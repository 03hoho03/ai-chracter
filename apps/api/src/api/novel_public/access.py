"""노벨 공개 스위치 게이트와 원작 판정.

**원작 판정은 둘로 갈린다.** 새로 공개하는 것(처음 공개·다음 화 이어 붙이기)은 원작이 지금 공개 목록에 실리고(발행됨 ∧
공개 ∧ 이용제한 없음 — 작품 목록과 같은 조건) 원작자가 소설 공개를 허락했을 때만 된다. 게시자가 원작자 본인이면 허락은
따지지 않는다(자기 작품을 자기가 소설로 공개하는 데 허락이 필요 없다) — 공개 목록 조건은 본인도 따른다. 이미 공개한 것(공개한
화의 수정본·소설 제목·소개 다시 공개, 거뒀던 공개 다시 열기)은 원작이 이용제한·삭제만 아니면 된다 — 원작자가 허락을 낮추거나
원작을 비공개로 돌려도 이미 공개된 소설은 유지하고, 그 고친 내용을 다시 내는 것도 막지 않는다. 원작이 이용제한·삭제되면 그
원작의 공개 소설은 독자에게 보이지 않으므로 고쳐 다시 내는 것도 막는다.

정책 스위치가 켜졌고 소설이 연재권 잠금(한 번 독자에게 보임, `novel_public/serial_lock.py`)을 가졌으면 새로 공개하는 것도
허락은 따지지 않는다 — 원작자가 소설화 허락을 거둬도 그 소설의 다음 화는 이어 공개한다. 면제는 허락뿐이고 공개 목록 조건은
그대로 본다(원작자가 작품 자체를 비공개로 돌리거나 내리면 다음 화도 막힌다).

원작 행이 없으면(소설은 원작 id 를 FK 없는 사본으로 들고 있다) 이용제한과 같이 본다 — 풀어 줄 근거가 없다."""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Select, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from api.content.access import publicly_listed_conditions
from api.core.config import settings
from api.db.models.auth import User
from api.db.models.content import Content, ModerationStatus
from api.db.models.novel import Novel, NovelChapterPublication, NovelPublication
from api.db.session import get_db_session
from api.session.dependencies import get_current_user_id, get_current_user_id_optional

_any_chapter = aliased(NovelChapterPublication)

# 새로 공개할 수 없는 이유. 앞의 것이 먼저다 — 이용제한은 모든 공개를 막고, 허락은 원작자가 바꿔야 풀리고, 목록 조건은
# 원작자가 다시 공개하면 풀린다.
NewPublishBlock = Literal["source_unavailable", "source_permission", "source_not_listed"]
# 이미 공개한 것을 다시 낼 수 없는 이유. `restricted` 는 운영자가 이 공개 소설을 내린 상태다.
RepublishBlock = Literal["source_unavailable", "restricted"]


def novel_public_open_to(user_id: uuid.UUID | None) -> bool:
    """노벨이 이 사람에게 열려 있는가. 스위치(`novel_public_enabled`)가 꺼져 있으면 아무에게도 아니고, 미리보기 명단
    (`novel_public_preview_allowlist`)이 비어 있지 않으면 그 명단의 회원에게만이다. `user_id` 가 None 이면 비로그인이거나,
    인증 없는 공개 응답처럼 누가 보는지 모르는 경우다 — 명단이 있는 동안은 닫힘이다.

    독자·게시 게이트, 작품 정보·화 읽기의 직접 판정, 가격 응답과 `GET /me` 의 켜짐 표시가 모두 이 함수를 부른다 — 따로
    판정하면 화면에 보이는 탭이 404 를 받거나, 열린 사람에게 탭이 숨는다."""
    if not settings.novel_public_enabled:
        return False
    allowlist = settings.novel_public_preview_allowlist
    return not allowlist or (user_id is not None and user_id in allowlist)


def require_novel_public_enabled(user_id: uuid.UUID = Depends(get_current_user_id)) -> None:
    """노벨이 이 게시자에게 닫혀 있으면(`novel_public_open_to`) 403 `NOVEL_PUBLIC_DISABLED`. 공개·다시 공개·게시자 공개
    상태 조회 라우터 수준 게이트다. 공개 거두기는 이 게이트 밖이다(자기 글을 내리는 일이라)."""
    if not novel_public_open_to(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "NOVEL_PUBLIC_DISABLED"})


@dataclass(frozen=True)
class SourceGate:
    new_publish_block: NewPublishBlock | None
    source_available: bool


async def judge_source(
    db: AsyncSession, content_id: uuid.UUID, publisher_id: uuid.UUID, *, permission_locked: bool
) -> SourceGate:
    """공개 목록 조건은 작품 목록과 같은 식(`publicly_listed_conditions`)을 SQL 로 다시 물어 판정한다 — 조건을 여기 따로
    적으면 목록 조건이 바뀔 때 한쪽만 고쳐진다. `permission_locked` 가 참이면(연재권 잠금이 효력 있음) 허락 판정을 건너뛰고
    목록 조건까지 본다."""
    source = await db.get(Content, content_id, populate_existing=True)
    if source is None or source.moderation_status != ModerationStatus.NORMAL:
        return SourceGate(new_publish_block="source_unavailable", source_available=False)
    if not permission_locked and source.creator_user_id != publisher_id and source.novel_permission != "public":
        return SourceGate(new_publish_block="source_permission", source_available=True)
    listed = await db.scalar(select(Content.id).where(Content.id == content_id, *publicly_listed_conditions()))
    return SourceGate(new_publish_block=None if listed is not None else "source_not_listed", source_available=True)


async def require_novel_public_readable(request: Request, db: AsyncSession = Depends(get_db_session)) -> None:
    """노벨 읽기 라우트의 스위치 게이트. 노벨이 이 사람에게 닫혀 있으면(`novel_public_open_to`) 404 `NOVEL_PUBLIC_DISABLED`
    다 — 독자에게는 노벨이 없는 것과 같고(켜짐 표시로 화면이 탭을 숨긴다), 게시자 쪽 403 과 달리 무엇이 막혔는지 알릴 상대가
    아니다. 화 읽기는 이 게이트를 걸지 않고 직접 판정한다(소장한 사람에게는 "잠시 쉬는 중"을 알려야 해서).

    누구인지는 로그인 필수 의존성이 아니라 선택 의존성으로 본다 — 명단이 있는 동안 비로그인도 로그인 요구(401)가 아니라 꺼진
    노벨의 404 를 받아야 한다. 명단이 비어 있으면 누구인지 볼 필요가 없어 세션을 읽지 않는다."""
    viewer = await get_current_user_id_optional(request, db) if settings.novel_public_preview_allowlist else None
    if not novel_public_open_to(viewer):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOVEL_PUBLIC_DISABLED"})


def readable_publication_conditions() -> tuple[ColumnElement[bool], ...]:
    """독자가 지금 이 공개 소설을 읽을 수 있는가 — SQL 조건. 공개 중(거두지 않음) ∧ 첫 공개가 운영자 승인을 기다리거나
    반려되지 않음 ∧ 운영자 이용제한 없음 ∧ 작가가 숨기지 않음 ∧ 게시자가 탈퇴·정지
    되지 않음 ∧ 원작이 이용제한·삭제되지 않음 ∧ 공개 화가 하나 이상(마지막 묶음을 지워 공개 화가 모두 사라진 공개 상태 행은
    소설 제목·소개만 남아 읽을 것이 없다). 호출부가 `NovelPublication`·`Novel`·게시자 `User`(`User.id ==
    Novel.user_id`)·원작 `Content`(`Content.id == Novel.content_id`)를 조인한다.

    정지·원작 상태는 표식 칸을 두지 않고 조회 때 조인으로 본다 — 정지가 풀리거나 원작이 복구되면 표식을 되돌리지 않아도 다시
    보인다. 구매·열람·목록이 이 조건 하나를 함께 써야 "목록엔 없는데 구매는 되는" 틈이 생기지 않는다."""
    return (
        NovelPublication.visibility == "public",
        # 대기·반려 행은 공개 범위도 `withdrawn` 이라 위 조건으로 이미 빠진다. 심사 칸을 함께 보는 것은 그 약속이 어느 쓰기
        # 경로에서 깨져도 승인 전 글이 나가지 않게 하려는 것이다.
        or_(NovelPublication.review_status.is_(None), NovelPublication.review_status == "approved"),
        NovelPublication.moderation_status == "normal",
        # 숨긴 소설(노벨로 팔린 뒤 작가가 지운 소설)은 공개를 거둔 채 숨기므로 위 공개 범위 조건으로 이미 빠진다. 숨김을 따로
        # 보는 것은 그 약속이 깨져도(숨김을 모르는 옛 이미지로 되돌린 동안 작가가 다시 공개) 지운 소설이 독자 목록·구매에
        # 나가지 않게 하려는 것이다.
        Novel.hidden_at.is_(None),
        User.deleted_at.is_(None),
        User.suspended_at.is_(None),
        Content.moderation_status == ModerationStatus.NORMAL,
        # 별칭을 쓰는 것은 화 공개본을 이미 FROM 에 둔 쿼리(화 하나를 고르는 쿼리)에서도 이 하위 쿼리가 그 행에 묶이지 않고
        # 소설의 공개 화 전체를 보게 하려는 것이다.
        exists().where(_any_chapter.novel_id == NovelPublication.novel_id).correlate_except(_any_chapter),
    )


def select_readable_publications(*columns: Any) -> Select[Any]:
    """독자가 지금 읽을 수 있는 공개 소설만 남기는 select(`readable_publication_conditions` 와 그 조인). 고를 열은 호출부가
    정하고, 정렬·추가 조건·조인은 돌려받은 select 에 더 얹는다. 노벨 목록·작품 정보·화·좋아요·홈 노벨·어드민 지정 판정이
    이것 하나를 쓴다 — 조건이 갈리면 "목록엔 없는데 열리는" 틈이 생긴다."""
    return (
        select(*columns)
        .select_from(NovelPublication)
        .join(Novel, Novel.id == NovelPublication.novel_id)
        .join(User, User.id == Novel.user_id)
        .join(Content, Content.id == Novel.content_id)
        .where(*readable_publication_conditions())
    )


def owner_readable_publication_conditions() -> tuple[ColumnElement[bool], ...]:
    """정책 스위치가 켜졌을 때, 아직 환급되지 않은 구매를 가진 사람(소장자)이 이 공개 소설을 계속 읽을 수 있는가 — SQL 조건.
    운영자 이용제한 없음 ∧ 첫 공개 승인 대기·반려 아님 ∧ 게시자 미탈퇴 ∧ 원작이 정상이거나 원작자 정지로만 일괄 제한됨 ∧ 공개
    화가 하나 이상. 조인은 `readable_publication_conditions` 와 같다.

    공개 범위(게시자의 거둠·판매된 소설 삭제의 숨김)와 게시자 정지는 보지 않는다 — 게시자 쪽 사정이라 산 사람의 소장을 끝내지
    않는다(새로 보이거나 팔리지 않는 것은 목록·구매가 쓰는 `readable_publication_conditions` 가 맡는다). 여기서 빠지는 경우
    (노벨 이용제한·원작 자체 이용제한·원작 삭제·게시자 탈퇴)는 그 쓰기마다 구매를 환급한다(`purchases.py` 모듈 docstring) —
    두 목록이 어긋나면 환급 없이 닫히는 소장이 생긴다."""
    return (
        or_(NovelPublication.review_status.is_(None), NovelPublication.review_status == "approved"),
        NovelPublication.moderation_status == "normal",
        User.deleted_at.is_(None),
        or_(Content.moderation_status == ModerationStatus.NORMAL, Content.restricted_by_suspension.is_(True)),
        exists().where(_any_chapter.novel_id == NovelPublication.novel_id).correlate_except(_any_chapter),
    )


def select_owner_readable_publications(*columns: Any) -> Select[Any]:
    """`select_readable_publications` 의 소장자 판(`owner_readable_publication_conditions`). 이 사람이 그 소설의 소장자인지는
    호출자가 먼저 본다."""
    return (
        select(*columns)
        .select_from(NovelPublication)
        .join(Novel, Novel.id == NovelPublication.novel_id)
        .join(User, User.id == Novel.user_id)
        .join(Content, Content.id == Novel.content_id)
        .where(*owner_readable_publication_conditions())
    )
