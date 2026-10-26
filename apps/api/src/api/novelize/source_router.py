"""소설로 만들 수 있는 내 채팅 목록. 소설 라우트와 같은 소설화 접근 게이트를 라우터 수준에 건다(허용이 없으면 같은 403).

`/novels` 아래가 아니라 `/me` 아래에 두는 이유: `/novels/{novel_id}` 보다 먼저 등록해야 하는 순서 의존이 생기지 않는다."""

import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.router import my_chat_room_rows, my_chat_room_sort_key, sign_room_thumbnails
from api.db.models.novel import Novel
from api.db.session import get_db_session
from api.novelize.access import require_novelize_access
from api.novelize.schemas import NovelSourceListResponse, NovelSourceRoom
from api.novelize.writing_lock import novel_creation_blocked_rooms
from api.session.dependencies import get_current_user_id

source_router = APIRouter(prefix="/me", tags=["novels"], dependencies=[Depends(require_novelize_access)])

# 한 페이지의 방 개수. 테스트가 바꿔 끼울 수 있게 부를 때 모듈 전역으로 읽는다.
NOVEL_SOURCE_PAGE_SIZE = 20


def _encode_cursor(key: tuple[datetime, datetime, uuid.UUID]) -> str:
    activity_at, created_at, room_id = key
    return base64.urlsafe_b64encode(
        json.dumps([activity_at.isoformat(), created_at.isoformat(), str(room_id)]).encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, datetime, uuid.UUID]:
    invalid = HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "NOVEL_SOURCE_CURSOR_INVALID"}
    )
    try:
        activity_at, created_at, room_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        key = datetime.fromisoformat(activity_at), datetime.fromisoformat(created_at), uuid.UUID(room_id)
    except (ValueError, TypeError) as exc:
        raise invalid from exc
    # 방의 정렬 키는 시간대 있는 시각이라, 오프셋 없는 시각과 비교하면 TypeError 로 500 이 난다.
    if key[0].tzinfo is None or key[1].tzinfo is None:
        raise invalid
    return key


@source_router.get("/novel-sources")
async def list_novel_sources(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSourceListResponse:
    """내 채팅방을 내 채팅 목록과 같은 순서·같은 방 칸으로, 방마다 그 방의 소설 id 와 새 소설 만들기 막힘 여부를 붙여 한
    페이지씩. 원작이 이용제한된 방도 싣는다 — 소설은 만들 수 있고 생성 경로가 막는다. 커서는 정렬 키 전체(활동 시각·생성
    시각·방 id)라 동점 방이 페이지 경계에 걸려도 겹치거나 빠지지 않는다. "대화 N" 번호는 자르기 전 전체 방으로 센다."""
    rows, contents = await my_chat_room_rows(db, user_id)
    if cursor is not None:
        after = _decode_cursor(cursor)
        rows = [row for row in rows if my_chat_room_sort_key(row[0]) < after]
    page_size = NOVEL_SOURCE_PAGE_SIZE
    page = rows[:page_size]
    next_cursor = _encode_cursor(my_chat_room_sort_key(page[-1][0])) if len(rows) > page_size else None

    room_ids = [item.id for item, _key in page]
    # 숨긴 소설은 방 칸이 비어 여기서 잡히지 않는다 — 그 방은 새 소설을 만들 수 있는 방으로 보인다.
    novel_ids = dict(
        (await db.execute(select(Novel.chat_room_id, Novel.id).where(Novel.chat_room_id.in_(room_ids)))).tuples().all()
    )
    blocked = await novel_creation_blocked_rooms(
        db, user_id, [(item.id, contents[item.content_id]) for item, _key in page]
    )
    sources = [
        (
            NovelSourceRoom(
                **dict(item),
                novel_id=novel_ids.get(item.id),
                novel_creation_blocked=item.id in blocked,
            ),
            key,
        )
        for item, key in page
    ]
    return NovelSourceListResponse(items=await sign_room_thumbnails(sources), next_cursor=next_cursor)
