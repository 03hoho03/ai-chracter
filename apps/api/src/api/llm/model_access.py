"""상위 글쓰기 모델(Gemini 밖의 모델) 허용 판정과, 저장된 모델을 지금 쓸 모델로 읽는 규칙.

채팅과 소설에 한 벌씩이다. 둘 다 세 조건이 모두 참이어야 한다 — 기능별 전역 스위치(`chat_premium_models_enabled`·
`novelize_premium_models_enabled`)가 켜져 있고, 계정이 그 기능의 env 허용 명단에 있고, 어드민이 준 허용 행
(`user_feature_grants`)이 있다. 소설은 소설화 자체 허용(`novelize/access.py`)까지 참이어야 한다 — 소설화를 못 쓰는
계정에게 소설 장 모델 선택만 열 수는 없다. 명단을 접근할 때마다 보는 이유는 소설화 판정과 같다(env 에서 지우고
재기동하면 허용 행을 그대로 둔 채 막힌다).

스위치와 명단은 메모리 값이라 먼저 보고, 둘 다 통과할 때만 허용 행을 조회한다 — 꺼져 있는 동안 방 응답·`/me`·턴
게이트가 쿼리를 더 쓰지 않는다.

`GET /me` 의 허용 기능 목록, 모델 목록·지정 라우트, 턴 과금 게이트가 같은 함수를 쓴다. 따로 판정하면 화면이 고를 수
있게 보여 준 모델을 게이트가 막는 어긋남이 생긴다.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.feature_grant import FeatureName, UserFeatureGrant
from api.llm.chat_models import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_CHAT_ROOM_MODEL,
    ChatModelId,
    ChatRoomModelId,
    is_chat_room_model,
    parse_chat_model_id,
)
from api.novelize.access import has_novelize_access


async def _has_grant(db: AsyncSession, user_id: uuid.UUID, feature: FeatureName) -> bool:
    grant_id = await db.scalar(
        select(UserFeatureGrant.id).where(UserFeatureGrant.user_id == user_id, UserFeatureGrant.feature == feature)
    )
    return grant_id is not None


async def has_chat_premium_access(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """이 계정이 채팅방에 상위 모델을 고르고 그 모델로 턴을 돌릴 수 있는가."""
    if not settings.chat_premium_models_enabled or user_id not in settings.chat_premium_model_allowlist:
        return False
    return await _has_grant(db, user_id, "chat_premium_models")


async def has_novel_premium_access(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """이 계정이 소설 장 생성·재생성에 상위 모델을 고를 수 있는가. 소설화 자체 허용은 상위 모델 허용 행까지 확인한 뒤에
    본다 — 상위 모델 쪽이 꺼져 있으면 소설화 판정의 쿼리도 내지 않는다."""
    if not settings.novelize_premium_models_enabled or user_id not in settings.novelize_premium_model_allowlist:
        return False
    if not await _has_grant(db, user_id, "novelize_premium_models"):
        return False
    return await has_novelize_access(db, user_id)


def effective_model(stored: str | None, *, allowed: bool) -> ChatModelId:
    """저장된 모델 값을 지금 쓸 모델로 읽는다. 비었거나, 레지스트리에서 내린 모델이거나, 상위 모델인데 허용이 없으면(스위치
    꺼짐·허용 회수) 기본 모델이다 — 그 턴은 기본 모델로, 기본 모델 가격으로 돈다. 스위치를 끄는 것이 1차 롤백이라 그때
    상위 모델 방이 턴 불가가 되면 롤백이 장애가 된다. 값을 내고 다른 모델의 글을 받는 일은 없다 — 가격도 이 값에서 정한다."""
    model = parse_chat_model_id(stored) if stored is not None else None
    if model is None or model == DEFAULT_CHAT_MODEL:
        return DEFAULT_CHAT_MODEL
    return model if allowed else DEFAULT_CHAT_MODEL


async def effective_room_model(db: AsyncSession, user_id: uuid.UUID, stored: str | None) -> ChatRoomModelId:
    """방에 저장된 모델(`chat_rooms.chat_model`)을 그 방 주인이 지금 쓸 모델로 읽는다. 기본 모델 방은 허용을 보지 않는다 —
    턴마다 부르는 값이라 대부분의 방에서 쿼리를 더하지 않는다. 채팅에서 고를 수 없는 모델(채팅에서 내리기 전에 저장된
    Sonnet)도 허용과 무관하게 기본 모델이다 — 화면이 고를 수 없는 모델로 턴이 돌면 안 된다."""
    model = effective_model(stored, allowed=True)
    if not is_chat_room_model(model) or model == DEFAULT_CHAT_ROOM_MODEL:
        return DEFAULT_CHAT_ROOM_MODEL
    return model if await has_chat_premium_access(db, user_id) else DEFAULT_CHAT_ROOM_MODEL
