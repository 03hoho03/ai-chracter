"""작품을 누구에게 열지 정하는 판정. 라우터를 import 하지 않아 어느 라우터에서 불러도 순환이 생기지 않는다.

판정은 셋이고 서로 다르다.

- 공개 목록에 실리는가(`publicly_listed_conditions`): 발행됐고, 공개(`PUBLIC`)이고, 이용제한·삭제가 아니다. 홈 목록이
  이 조건으로 거른다. 링크 공개(`LINK`)는 주소를 아는 사람에게만 열려 목록에는 실리지 않는다.
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

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.chat import ChatRoom
from api.db.models.content import Content, ContentVisibility, ModerationStatus


def publicly_listed_conditions() -> tuple[ColumnElement[bool], ...]:
    """공개 목록에 실리는 작품의 WHERE 조건들. 목록을 만드는 쿼리가 `.where(*publicly_listed_conditions())` 로 쓴다."""
    return (
        Content.current_published_version_id.is_not(None),
        Content.visibility == ContentVisibility.PUBLIC,
        Content.moderation_status == ModerationStatus.NORMAL,
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
