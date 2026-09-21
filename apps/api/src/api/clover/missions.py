"""clover-page-goal-prompt.md CE-13~CE-18 — 미션 정의·달성 판정.

DB 테이블·어드민 관리 화면을 두지 않는다(CE-15, 3종 고정). 달성 여부는 저장하지 않고 매
조회·청구마다 EXISTS 쿼리로 다시 판정한다(CE-13) — 그래야 청구 전에 달성 신호가 사라졌다
다시 생겨도(방·메시지 삭제 후 재대화 등) 다시 청구할 수 있다(clover-page-goal-prompt.md
"멱등키가 보장하지 않는 것" 콜아웃, T-13). 청구는 `clover/router.py`가 멱등키
`mission:{user_id}:{key}`로 지급한다 — 이 파일은 그 키 파생 하나만 갖고(GET의 "청구완료"
판정과 POST의 실제 청구가 같은 키를 써야 한다), 지급 자체는 `core/clover.py`의 `grant`에
맡긴다.
"""

import uuid
from typing import Literal, assert_never

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.clover import CloverLedger
from api.db.models.content import Content
from api.db.models.media import ImageGenerationRequest

MissionKey = Literal["first_publish", "first_message", "first_image"]

# clover-page-goal-prompt.md CE-14. 표시 순서 고정 — dict 순회 순서에 기대지 않는다.
MISSION_KEYS: tuple[MissionKey, ...] = ("first_publish", "first_message", "first_image")

# clover-page-goal-prompt.md CE-16. 확정값(첫 대화 100 · 첫 이미지 200 · 첫 발행 300).
MISSION_REWARDS: dict[MissionKey, int] = {
    "first_publish": 300,
    "first_message": 100,
    "first_image": 200,
}


def mission_idempotency_key(*, user_id: uuid.UUID, key: MissionKey) -> str:
    """`ux_clover_ledger_idempotency_key`가 이중 청구를 막는 유일한 수단이다(CE-13) — GET의
    "청구완료" 판정(원장에 이 키가 있는지)과 POST의 실제 청구가 같은 파생식을 써야 하므로
    한 곳에 둔다."""
    return f"mission:{user_id}:{key}"


async def mission_achieved(db: AsyncSession, *, user_id: uuid.UUID, key: MissionKey) -> bool:
    """3종 판정을 EXISTS로 계산한다. 상태를 저장하지 않는다(CE-13) — 그래서 T-13이 성립한다.

    clover-page-goal-prompt.md 사전 점검 PA-6:
    - `first_publish`: 발행 판정 컬럼은 `Content.current_published_version_id`, 소유는
      `creator_user_id`.
    - `first_message`: `chat_messages`에 `user_id`가 없어 `chat_rooms`를 거쳐 소유를 잇는다.
      🔴 `role = USER` 필터 필수 — `POST /chat-rooms`만으로 메시지 0개인 방이 생기므로, 방
      존재만 보면 "방만 만들고 유저 메시지는 0개"를 오판한다.
    - `first_image`: 🔴 `status = 'succeeded'` 필터 필수 — 실패·차단 요청도 행이 생긴다.
    """
    match key:
        case "first_publish":
            condition = (
                select(Content.id)
                .where(
                    Content.creator_user_id == user_id,
                    Content.current_published_version_id.is_not(None),
                )
                .exists()
            )
        case "first_message":
            condition = (
                select(ChatMessage.id)
                .join(ChatRoom, ChatRoom.id == ChatMessage.chat_room_id)
                .where(ChatRoom.user_id == user_id, ChatMessage.role == ChatMessageRole.USER)
                .exists()
            )
        case "first_image":
            condition = (
                select(ImageGenerationRequest.id)
                .where(
                    ImageGenerationRequest.owner_user_id == user_id,
                    ImageGenerationRequest.status == "succeeded",
                )
                .exists()
            )
        case _:
            assert_never(key)
    return bool(await db.scalar(select(condition)))


async def mission_claimed(db: AsyncSession, *, user_id: uuid.UUID, key: MissionKey) -> bool:
    """원장에 이 미션의 멱등키가 이미 있는가 — "청구완료" 표시용. 달성 판정(위)과 달리 이건
    실제로 지급된 사실을 보는 것이라 EXISTS 대상이 원장이다."""
    condition = (
        select(CloverLedger.id)
        .where(CloverLedger.idempotency_key == mission_idempotency_key(user_id=user_id, key=key))
        .exists()
    )
    return bool(await db.scalar(select(condition)))
