"""작품을 누구에게 열지 정하는 판정. 라우터를 import 하지 않아 어느 라우터에서 불러도 순환이 생기지 않는다.

판정은 셋이고 서로 다르다.

- 공개 목록에 실리는가(`select_publicly_listed`): 발행됐고, 공개(`PUBLIC`)이고, 이용제한·삭제가 아니다. 링크
  공개(`LINK`)는 주소를 아는 사람에게만 열려 목록에는 실리지 않는다. 조건(`publicly_listed_conditions`)만이 아니라
  발행본 상세·작가·장르와의 내부 조인도 판정의 일부다 — 장르가 빈 발행작은 조건을 통과해도 조인에서 빠진다. 홈 목록,
  홈 큐레이션 공개 조회, 어드민의 지정 허용·"홈에 보임" 표시가 이 select 하나를 같이 쓴다(조인이 갈리면 어드민이
  보인다고 말한 작품이 홈에는 없다).
- 상세 본문을 보이고 새 방을 열어도 되는가(`is_open_to`): 이용제한·삭제가 아니고, 비공개(`PRIVATE`)면 작가 본인만.
  새 방은 새 대화 시작과 시작설정 변경 둘 다다 — 그 작품에 방이 이미 있는 사람도 비공개 작품에서는 새 방을 못 연다.
  링크 공개는 열린다 — 그 주소로 들어와 상세를 보고 대화를 시작하라고 있는 공개 범위다. 웹 상세 화면의 같은 판정과
  규칙이 같다.
- 이미 대화한 사람이 본 것을 다시 볼 수 있는가(`is_open_to_participant`): 위에 더해 비공개 작품이라도 그 작품에
  대화방이 있는 사용자에게는 연다. 공개였을 때 대화를 시작한 독자가 작가가 비공개로 돌리거나 탈퇴(작품이 비공개가
  된다)해도 자기 방에서 이미 본 그림을 다시 볼 수 있게 하려는 것이다. 이용제한·삭제는 여기서도 닫힌다.

작가 탈퇴는 파기가 작품을 비공개로 돌리므로 비공개 규칙을 따른다. 발행본이 없는 작품은 호출부가 먼저 404 로 막는다.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatRoom
from api.db.models.content import Content, ContentType, ContentVisibility, Genre, ModerationStatus
from api.db.models.story import StoryVersionDetail


def publicly_listed_conditions() -> tuple[ColumnElement[bool], ...]:
    """공개 목록에 실리는 작품의 WHERE 조건들. 목록을 만드는 쿼리가 `.where(*publicly_listed_conditions())` 로 쓴다."""
    return (
        Content.current_published_version_id.is_not(None),
        Content.visibility == ContentVisibility.PUBLIC,
        Content.moderation_status == ModerationStatus.NORMAL,
    )


def detail_model_for(content_type: ContentType) -> type[CharacterVersionDetail] | type[StoryVersionDetail]:
    """유형별 버전 상세 테이블(이름·한 줄 소개·썸네일이 여기 있다)."""
    return CharacterVersionDetail if content_type == ContentType.CHARACTER else StoryVersionDetail


def select_publicly_listed(content_type: ContentType, *columns: Any) -> Select[Any]:
    """`content_type` 유형에서 공개 목록에 실리는 작품만 남기는 select. 고를 열은 호출부가 정하고(상세 열은
    `detail_model_for(content_type)` 로 집는다), 정렬·추가 조건·조인은 돌려받은 select 에 더 얹는다."""
    detail_model = detail_model_for(content_type)
    return (
        select(*columns)
        .select_from(Content)
        .join(detail_model, detail_model.content_version_id == Content.current_published_version_id)
        .join(User, User.id == Content.creator_user_id)
        # 고르는 열은 없어도 내부 조인이라 장르 없는 작품을 뺀다 — 지우면 걸러지는 대상이 바뀐다.
        .join(Genre, Genre.id == Content.genre_id)
        .where(Content.type == content_type, *publicly_listed_conditions())
    )


def is_open_to(content: Content, viewer_id: uuid.UUID | None) -> bool:
    """처음 보는 사람(`viewer_id`, 비로그인은 `None`)에게 이 작품의 상세 본문을 보이고 새 대화를 열어도 되는가."""
    if content.moderation_status != ModerationStatus.NORMAL:
        return False
    return content.visibility != ContentVisibility.PRIVATE or viewer_id == content.creator_user_id


async def is_open_to_participant(db: AsyncSession, content: Content, viewer_id: uuid.UUID | None) -> bool:
    """`is_open_to` 에 더해, 비공개 작품이라도 그 작품에 대화방이 있는 사용자에게는 연다."""
    if is_open_to(content, viewer_id):
        return True
    if viewer_id is None or content.moderation_status != ModerationStatus.NORMAL:
        return False
    room_id = await db.scalar(
        select(ChatRoom.id).where(ChatRoom.user_id == viewer_id, ChatRoom.content_id == content.id).limit(1)
    )
    return room_id is not None
