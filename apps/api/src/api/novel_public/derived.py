"""원작 상세의 공개 소설 목록 — 이 작품을 원작으로 한, 지금 독자가 읽을 수 있는 노벨.

경로는 원작 아래(`/contents/{id}/derived-novels`)지만 코드는 노벨 쪽에 둔다. 무엇이 나가는지는 노벨 목록과 같은
`select_readable_publications` 하나가 정하고(공개 중 ∧ 심사 대기·반려 아님 ∧ 운영 이용제한·판매 중단 없음 ∧ 숨기지 않음 ∧
게시자 탈퇴·정지 아님 ∧ 원작 이용제한·삭제 아님 ∧ 공개 화 하나 이상), 항목 모양·원작 표기도 노벨 목록의 것을 그대로 쓴다.
`/novels` 접두에 두지 않는 것은 그 라우터 전체에 소설화 허용 게이트가 걸려 일반 독자가 403 을 받기 때문이다.

**노벨 스위치는 따로 본다.** 위 조건은 스위치·미리보기 명단을 보지 않는다. 노벨이 읽는 사람에게 닫혀 있으면
(`novel_public_open_to`) 노벨 목록처럼 404 를 내지 않고 빈 목록을 준다 — 원작 상세는 노벨 화면이 아니라, 목록이 비면 그
영역을 그리지 않으면 되고 원작 상세 자체가 오류로 보일 까닭이 없다. 로그인은 필요하다(노벨 목록·작품 정보가 로그인
회원에게만 열려 있어, 비로그인에게 노벨 제목·표지를 새로 내보이지 않는다).

**원작자의 숨김**(`contents.derived_novels_visible`)은 표시만 줄인다. 거짓이면 원작자가 아닌 사람에게 빈 목록이고, 원작자
본인에게는 숨긴 동안에도 무엇이 걸려 있는지 보이게 항목을 그대로 준다."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.content import Content
from api.db.models.novel import Novel, NovelPublication
from api.db.session import get_db_session
from api.novel_public.access import novel_public_open_to, select_readable_publications
from api.novel_public.no_store import NoStoreRoute
from api.novel_public.reading import (
    _chapter_count,
    _decode_latest_cursor,
    _encode_cursor,
    _publisher_withdrawn,
    _sources,
    _title,
)
from api.novel_public.schemas import DerivedNovelListResponse, PublicNovelListItem
from api.session.dependencies import get_current_user_id

DERIVED_NOVEL_PAGE_SIZE = 20

derived_router = APIRouter(tags=["webnovels"], route_class=NoStoreRoute)


@derived_router.get("/contents/{content_id}/derived-novels")
async def list_derived_novels(
    content_id: uuid.UUID,
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> DerivedNovelListResponse:
    """이 작품을 원작으로 한 공개 소설, 공개 화면 글이 마지막으로 바뀐 시각 순으로 한 번에 20편. 다음 페이지는
    `nextCursor` 를 그대로 `cursor` 로 넘긴다. 작품이 없으면 404 다(원작이 삭제됐으면 행은 남아 빈 목록)."""
    content = await db.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found")
    visible = content.derived_novels_visible
    if not novel_public_open_to(user_id) or (not visible and user_id != content.creator_user_id):
        return DerivedNovelListResponse(visible=visible, items=[], next_cursor=None)

    query = (
        select_readable_publications(NovelPublication, Novel, User.nickname, _publisher_withdrawn(), _chapter_count())
        .where(Novel.content_id == content_id)
        .order_by(NovelPublication.published_at.desc(), NovelPublication.novel_id.desc())
    )
    if cursor is not None:
        query = query.where(
            tuple_(NovelPublication.published_at, NovelPublication.novel_id) < _decode_latest_cursor(cursor)
        )
    rows = (await db.execute(query.limit(DERIVED_NOVEL_PAGE_SIZE + 1))).all()
    page = rows[:DERIVED_NOVEL_PAGE_SIZE]
    sources = await _sources(db, [novel for _, novel, _, _, _ in page])
    items = [
        PublicNovelListItem(
            id=novel.id,
            title=_title(publication, novel),
            synopsis=publication.synopsis,
            source=sources[novel.id],
            publisher_nickname=nickname,
            publisher_withdrawn=withdrawn,
            chapter_count=count,
            like_count=publication.like_count,
            view_count=publication.view_count,
            published_at=publication.published_at,
        )
        for publication, novel, nickname, withdrawn, count in page
    ]
    next_cursor: str | None = None
    if len(rows) > DERIVED_NOVEL_PAGE_SIZE and page:
        last: NovelPublication = page[-1][0]
        next_cursor = _encode_cursor([last.published_at.isoformat(), str(last.novel_id)])
    return DerivedNovelListResponse(visible=visible, items=items, next_cursor=next_cursor)
