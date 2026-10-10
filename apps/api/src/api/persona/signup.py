"""가입하면서 받은 이름으로 첫 대화 프로필을 만든다 — 이메일 가입과 구글·카카오 온보딩이 쓴다.

`users.default_persona_id` ↔ `user_personas.user_id` 가 순환 FK 라 순서가 정해져 있다: 사용자 행이 먼저 flush 돼 있어야
프로필을 넣을 수 있고, 프로필이 flush 된 뒤에야 기본으로 가리킬 수 있다. 그래서 세 함수 모두 사용자 행을 flush 한
**뒤에** 부른다(소셜 온보딩은 `_flush_social_signup` 뒤 — 그 전에 쓰기가 나가면 UNIQUE 충돌이 409 가 아니라 500 이 된다).
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.persona import UserPersona
from api.persona.router import count_personas, lock_user_default_persona


async def create_signup_persona(db: AsyncSession, user: User, name: str | None) -> None:
    """새로 만든 사용자에게 받은 이름으로 프로필을 만들고 기본으로 둔다. 이름이 없으면 아무것도 하지 않는다."""
    if name is None:
        return
    persona = UserPersona(user_id=user.id, name=name)
    db.add(persona)
    await db.flush()
    user.default_persona_id = persona.id


async def replace_signup_personas(db: AsyncSession, user: User, name: str | None) -> None:
    """방치된 미인증 가입 행을 새 가입이 덮어쓸 때. 그 행은 남이 같은 이메일로 해 둔 가입일 수 있어, 남아 있던 프로필을
    지우고 이번에 받은 이름으로 다시 만든다(없으면 0개로 둔다). 그 행은 로그인할 수 없었으므로 프로필을 쓰는 방이 없다."""
    user.default_persona_id = None
    await db.flush()
    await db.execute(delete(UserPersona).where(UserPersona.user_id == user.id))
    await create_signup_persona(db, user, name)


async def ensure_signup_persona(db: AsyncSession, user: User, name: str | None) -> None:
    """이미 가입된 사용자로 이어지는 소셜 온보딩(두 탭에서 같은 가입을 낸 경우 등). 쓰던 프로필이 있으면 건드리지 않고,
    하나도 없을 때만 만든다. 유저 행을 잠그고 세야 두 탭이 동시에 첫 프로필을 둘 만들지 않는다."""
    if name is None:
        return
    await lock_user_default_persona(db, user.id)
    if await count_personas(db, user.id) == 0:
        await create_signup_persona(db, user, name)
