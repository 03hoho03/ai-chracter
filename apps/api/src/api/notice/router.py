import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.notice import Notice
from api.db.session import get_db_session
from api.notice.schemas import NoticeDetailResponse, NoticeListItem, NoticeListResponse

router = APIRouter(prefix="/notices", tags=["notice"])


@router.get("")
async def list_notices(db: AsyncSession = Depends(get_db_session)) -> NoticeListResponse:
    """공개 목록 — 인증 없음(techspec.md §4-1, D-5). `legal/router.py`의
    `GET /legal/{kind}`와 같은 취급.

    **페이징하지 않는다**(D-13) — 항목이 제목+날짜뿐이라 행당 수십 바이트라 커서
    인코딩·무한스크롤이 불필요하다. **전환 조건**: 게시된 공지가 200건을 넘으면 커서
    페이징으로 바꾼다. `content/router.py`의 `_encode_cursor`/`_decode_cursor`(:1693/
    :1697)를 그대로 쓰면 되고, 응답에 `nextCursor`를 더하는 것은 기존 소비처를 깨지
    않는 추가라 지금 미리 만들어 둘 이유가 없다.
    """
    notices = (
        await db.scalars(
            select(Notice)
            .where(Notice.published.is_(True))
            .order_by(Notice.published_at.desc(), Notice.id.desc())
        )
    ).all()

    items = []
    for notice in notices:
        assert notice.published_at is not None  # 게시 행은 publish 시 항상 채워진다
        items.append(NoticeListItem(id=notice.id, title=notice.title, published_at=notice.published_at))
    return NoticeListResponse(items=items)


@router.get("/{id}")
async def get_notice(id: uuid.UUID, db: AsyncSession = Depends(get_db_session)) -> NoticeDetailResponse:
    """미게시 공지는 404 — 403이 아니다. 403은 "여기 뭔가 있다"를 알려주지만, 이건
    URL 추측으로 미게시 초안의 존재 자체가 새면 안 된다는 것이 목적이다."""
    notice = await db.get(Notice, id)
    if notice is None or not notice.published:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found")

    assert notice.published_at is not None  # 게시 행은 publish 시 항상 채워진다
    return NoticeDetailResponse(
        id=notice.id,
        title=notice.title,
        body_markdown=notice.body_markdown,
        published_at=notice.published_at,
    )
