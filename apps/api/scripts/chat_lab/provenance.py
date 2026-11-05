"""출처 칸 — 묶음 하나와 로컬 DB 하나로 계산한다. 판정과 칸의 뜻은 `apps/chat-lab/README.md` 「묶음 계약 판과 출처 칸」 절.

쿼리는 판정에 쓰는 칸만 이름으로 고른다 — 엔티티를 통째로 고르면 지금 모델보다 칸이 적은 옛 DB 에서 없는 칸 오류가 난다. 사용자
수는 DB 가 세고, DB 밖으로 꺼내는 이메일은 방 주인·작가 두 사람 것뿐이며 판정에만 쓴다."""

import uuid
from collections.abc import Collection
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.db.models import ChatRoom, Content, User
from chat_lab.schemas import Provenance
from replay.local_db import LOCAL_DB_HOSTS

EXAMPLE_DOMAIN = "@example.com"


def base_is_local(meta: dict[str, Any] | None) -> bool | None:
    """meta 줄 주소의 호스트가 루프백인가. meta 줄이 없으면 None."""
    if meta is None:
        return None
    base = meta.get("base")
    if not isinstance(base, str):
        return False
    try:
        host = urlsplit(base).hostname
    except ValueError:
        return False
    return host in LOCAL_DB_HOSTS


def in_example_domain(email: str) -> bool:
    return email.lower().endswith(EXAMPLE_DOMAIN)


async def _room_emails(session: AsyncSession, room_id: str) -> tuple[str, str] | None:
    """(방 주인 이메일, 작품 작가 이메일). 이 DB 에 방이 없으면 None. 방 id 가 uuid 가 아닌 묶음은 묶음을 열 때 결합이 먼저
    거부한다(지원 안 함)."""
    room = uuid.UUID(room_id)
    owner, author = aliased(User), aliased(User)
    row = (
        await session.execute(
            select(owner.email, author.email)
            .select_from(ChatRoom)
            .join(owner, owner.id == ChatRoom.user_id)
            .join(Content, Content.id == ChatRoom.content_id)
            .join(author, author.id == Content.creator_user_id)
            .where(ChatRoom.id == room)
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def _outside_users(session: AsyncSession, exempt: set[str]) -> tuple[int, int]:
    """(탈퇴하지 않은 테스트 계정 밖 사용자 가운데 예외가 아닌 수, 예외로 뺀 수). `exempt` 는 앞뒤 공백을 뗀 소문자다."""
    email = func.lower(User.email)
    exempted = email.in_(sorted(exempt))
    row = (
        await session.execute(
            select(func.count().filter(~exempted), func.count().filter(exempted))
            .select_from(User)
            .where(User.deleted_at.is_(None), ~email.endswith(EXAMPLE_DOMAIN))
        )
    ).one()
    return int(row[0]), int(row[1])


async def check_provenance(
    session: AsyncSession, *, meta: dict[str, Any] | None, room_id: str, exempt_emails: Collection[str]
) -> Provenance:
    base_local = base_is_local(meta)
    emails = await _room_emails(session, room_id)
    outside, exempted = await _outside_users(session, {email.strip().lower() for email in exempt_emails})
    owner_ok = emails is not None and in_example_domain(emails[0])
    return Provenance(
        # 방 주인 판정은 방이 없으면 거짓이라 방 판정을 따로 넣지 않는다.
        passed=base_local is not False and owner_ok and outside == 0,
        base_local=base_local,
        room_found=emails is not None,
        owner_in_example_domain=owner_ok,
        outside_users=outside,
        exempted_users=exempted,
        author_in_example_domain=None if emails is None else in_example_domain(emails[1]),
    )
