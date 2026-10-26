"""소설로 만들 수 있는 내 채팅 목록. 소설 라우트와 같은 소설화 접근 게이트를 라우터 수준에 건다."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.session import get_db_session
from api.novelize.schemas import NovelSourceListResponse
from api.session.dependencies import get_current_user_id

source_router = APIRouter(prefix="/me", tags=["novels"])

# 한 페이지의 방 개수. 테스트가 바꿔 끼울 수 있게 부를 때 모듈 전역으로 읽는다.
NOVEL_SOURCE_PAGE_SIZE = 20


@source_router.get("/novel-sources")
async def list_novel_sources(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSourceListResponse:
    return NovelSourceListResponse(items=[], next_cursor=None)
