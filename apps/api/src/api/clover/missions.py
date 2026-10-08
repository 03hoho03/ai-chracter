"""미션 정의·달성 판정.

DB 테이블·어드민 관리 화면을 두지 않는다(3종 고정). 달성 여부는 저장하지 않고 매
조회·청구마다 EXISTS 쿼리로 다시 판정한다 — 그래야 청구 전에 달성 신호가 사라졌다
다시 생겨도(방·메시지 삭제 후 재대화 등) 다시 청구할 수 있다.
청구는 `clover/router.py`가 멱등키
`mission:{user_id}:{key}`로 지급한다 — 이 파일은 그 키 파생 하나만 갖고(GET의 "청구완료"
판정과 POST의 실제 청구가 같은 키를 써야 한다), 지급 자체는 `core/clover.py`의 `grant`에
맡긴다.
"""

import uuid
from datetime import datetime
from typing import Literal, assert_never

from sqlalchemy import any_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.constants import WITHDRAWN_IDENTITY_RETENTION_PERIOD
from api.db.models.auth import WithdrawnIdentity
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.clover import CloverLedger
from api.db.models.content import Content
from api.db.models.media import ImageGenerationRequest

MissionKey = Literal["first_publish", "first_message", "first_image"]

# 표시 순서 고정 — dict 순회 순서에 기대지 않는다.
MISSION_KEYS: tuple[MissionKey, ...] = ("first_publish", "first_message", "first_image")

# 확정값(첫 대화 100 · 첫 이미지 200 · 첫 발행 300).
MISSION_REWARDS: dict[MissionKey, int] = {
    "first_publish": 300,
    "first_message": 100,
    "first_image": 200,
}


def mission_idempotency_key(*, user_id: uuid.UUID, key: MissionKey) -> str:
    """`ux_clover_ledger_idempotency_key`가 이중 청구를 막는 유일한 수단이다 — GET의
    "청구완료" 판정(원장에 이 키가 있는지)과 POST의 실제 청구가 같은 파생식을 써야 하므로
    한 곳에 둔다."""
    return f"mission:{user_id}:{key}"


async def mission_achieved(db: AsyncSession, *, user_id: uuid.UUID, key: MissionKey) -> bool:
    """3종 판정을 EXISTS로 계산한다. 상태를 저장하지 않는다 — 그래서 청구 전에 달성 신호가
    사라졌다가 다시 생기면 다시 청구할 수 있다.

    판정에 쓰는 컬럼:
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


async def mission_claimed_before_withdrawal(
    db: AsyncSession, *, ci_hmac: str | None, key: MissionKey, now: datetime
) -> bool:
    """같은 사람(본인인증 CI 해시)이 탈퇴한 계정에서 이 미션 보상을 이미 받았는가. 1회성 보상은 사람 기준 한 번이라 새
    계정의 원장만 보면 탈퇴 → 재가입으로 다시 받을 수 있다. 살아 있는 계정 사이에서는 CI 가 유일해 이 기록이 필요 없다.

    탈퇴한 지 보관 기간(1년)이 지난 기록은 무시한다(크론이 아직 못 지운 행도 마찬가지). 인증하지 않은 회원은 대조할
    것이 없어 거짓이다."""
    if ci_hmac is None:
        return False
    condition = (
        select(WithdrawnIdentity.ci_hmac)
        .where(
            WithdrawnIdentity.ci_hmac == ci_hmac,
            WithdrawnIdentity.withdrawn_at > now - WITHDRAWN_IDENTITY_RETENTION_PERIOD,
            any_(WithdrawnIdentity.claimed_mission_keys) == key,
        )
        .exists()
    )
    return bool(await db.scalar(select(condition)))
