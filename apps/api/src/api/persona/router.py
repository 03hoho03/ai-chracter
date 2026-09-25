"""대화 프로필의 `/me` 라우트.

방 선택(`PUT /chat-rooms/{id}/persona`)과 방 생성 두 경로의 `persona_id`는 `chat/router.py`에
있고, 여기의 `lock_user_default_persona`·`get_owned_persona`를 같이 쓴다.

🔴 **쓰기 경로의 소유권 검사가 이 기능의 유일한 방어선이다.** 읽기 경로(`_build_prompt`,
`_preview_persona_dependency`)는 프로필 소유자를 다시 보지 않는다. 그래서 프로필 id를
`users.default_persona_id`나 `chat_rooms.persona_id`에 싣는 모든 경로는 `get_owned_persona`를
거친다. 예외는 `change_starting_setup`의 승계뿐이다 — 같은 유저의 방에서 복사한다.

**동시성**: 프로필을 참조하거나 바꾸는 쓰기는 먼저 유저 행을 잠근다(락 순서 users →
user_personas → chat_rooms). 락 뒤의 값은 `with_for_update()`를 건 컬럼 select로 읽는다 —
`db.get(User)`는 락을 걸지 않는다. 엔티티 select 대신 컬럼 select인 이유는, 같은 세션에 살아 있는
`User` 인스턴스가 있으면 엔티티 select는 `populate_existing` 없이 옛 속성을 유지하기 때문이다
(identity map은 약참조라 보통은 앞 의존성이 읽은 `User`가 이미 수거돼 있다 —
`session/dependencies.py`의 `_is_active_user` 참고).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.chat import ChatRoom
from api.db.models.persona import UserPersona
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.persona.schemas import (
    PERSONA_MAX_COUNT,
    PersonaCreateRequest,
    PersonaListResponse,
    PersonaResponse,
    PersonaSelectRequest,
    PersonaUpsertRequest,
)
from api.session.dependencies import get_current_user_id

me_router = APIRouter(prefix="/me", tags=["persona"])

_PERSONA_LIMIT_MESSAGE = f"대화 프로필은 최대 {PERSONA_MAX_COUNT}개까지 만들 수 있어요."


async def lock_user_default_persona(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """유저 행을 잠그면서 `default_persona_id`를 DB에서 새로 읽는다."""
    return await db.scalar(select(User.default_persona_id).where(User.id == user_id).with_for_update())


async def get_owned_persona(db: AsyncSession, persona_id: uuid.UUID, user_id: uuid.UUID) -> UserPersona:
    persona = await db.get(UserPersona, persona_id)
    if persona is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    if persona.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the persona owner")
    return persona


def _to_response(persona: UserPersona) -> PersonaResponse:
    return PersonaResponse.model_validate(persona, from_attributes=True)


@me_router.get("/personas")
async def list_personas(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PersonaListResponse:
    personas = (
        await db.scalars(
            select(UserPersona)
            .where(UserPersona.user_id == user_id)
            .order_by(UserPersona.created_at.asc(), UserPersona.id.asc())
        )
    ).all()
    default_persona_id = await db.scalar(select(User.default_persona_id).where(User.id == user_id))
    return PersonaListResponse(
        items=[_to_response(persona) for persona in personas],
        default_persona_id=default_persona_id,
        max_count=PERSONA_MAX_COUNT,
    )


@me_router.post(  # 재동의 게이트
    "/personas", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def create_persona(
    payload: PersonaCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PersonaResponse:
    # 락 뒤에 세야 두 요청이 동시에 10번째를 넘기지 못한다.
    await lock_user_default_persona(db, user_id)
    count = await db.scalar(select(func.count()).select_from(UserPersona).where(UserPersona.user_id == user_id))
    if count is not None and count >= PERSONA_MAX_COUNT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_PERSONA_LIMIT_MESSAGE)

    persona = UserPersona(
        user_id=user_id, name=payload.name, gender=payload.gender, description=payload.description
    )
    db.add(persona)
    await db.flush()
    # 받은 값만 따른다(기본 유무로 추론하지 않는다).
    if payload.set_as_default:
        await db.execute(update(User).where(User.id == user_id).values(default_persona_id=persona.id))
    await db.commit()
    return _to_response(persona)


@me_router.put(  # 재동의 게이트
    "/personas/{persona_id}", dependencies=[Depends(require_legal_consent)]
)
async def update_persona(
    persona_id: uuid.UUID,
    payload: PersonaUpsertRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> PersonaResponse:
    await lock_user_default_persona(db, user_id)
    persona = await get_owned_persona(db, persona_id, user_id)
    persona.name = payload.name
    persona.gender = payload.gender
    persona.description = payload.description
    # 파이썬 값으로 넣는다 — SQL `func.now()`는 커밋 뒤 expire돼 응답을 만들 때 재조회가
    # 그린렛 밖에서 일어난다(`admin/notices.py` `_to_detail` 주석의 실측).
    persona.updated_at = datetime.now(UTC)
    await db.commit()
    return _to_response(persona)


@me_router.delete(  # 자기 데이터 삭제라 재동의 게이트를 걸지 않는다
    "/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_persona(
    persona_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """지우면 참조하던 방은 "선택 없음", 기본이었으면 기본도 없음.
    FK에 `ondelete`가 없으므로 참조를 먼저 끊고 flush한 뒤 지운다."""
    default_persona_id = await lock_user_default_persona(db, user_id)
    persona = await get_owned_persona(db, persona_id, user_id)

    await db.execute(update(ChatRoom).where(ChatRoom.persona_id == persona.id).values(persona_id=None))
    if default_persona_id == persona.id:
        await db.execute(update(User).where(User.id == user_id).values(default_persona_id=None))
    await db.flush()
    await db.delete(persona)
    await db.commit()


@me_router.put(  # 재동의 게이트
    "/default-persona", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_legal_consent)]
)
async def set_default_persona(
    payload: PersonaSelectRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """`/me/personas/default`가 아닌 이유: `/me/personas/{persona_id}`와 모양이 같아
    `"default"`를 UUID로 파싱하다 422가 난다."""
    await lock_user_default_persona(db, user_id)
    if payload.persona_id is not None:
        await get_owned_persona(db, payload.persona_id, user_id)
    await db.execute(update(User).where(User.id == user_id).values(default_persona_id=payload.persona_id))
    await db.commit()
