"""작품의 소설화 허락 바꾸기 — 발행 뒤 설정(`PUT /contents/{id}/novel-permission`)과 상세 응답.

빌더 자동저장 쪽(초안 PATCH 의 선택 칸)은 `test_content_draft_crud_api.py` 에 있다."""

import uuid
from datetime import UTC, datetime

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Content, ModerationStatus, User
from api.db.models.content import NovelPermission
from factories import _get_genre, _login_as, _make_published_character, _make_user


async def _work(db_session: AsyncSession, **creator_overrides: object) -> tuple[User, Content]:
    creator = _make_user(**creator_overrides)
    db_session.add(creator)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await db_session.commit()
    return creator, content


async def _stored(db_session: AsyncSession, content_id: uuid.UUID) -> NovelPermission | None:
    permission: NovelPermission | None = await db_session.scalar(
        sa.select(Content.novel_permission).where(Content.id == content_id)
    )
    return permission


async def test_creator_changes_the_permission_and_the_detail_shows_it_to_anyone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator, content = await _work(db_session)
    viewer = _make_user()
    db_session.add(viewer)
    await db_session.commit()
    await _login_as(db_client, creator.id)

    resp = await db_client.put(f"/contents/{content.id}/novel-permission", json={"novelPermission": "forbidden"})

    assert resp.status_code == 204
    assert await _stored(db_session, content.id) == "forbidden"
    await _login_as(db_client, viewer.id)
    detail = await db_client.get(f"/contents/{content.id}")
    assert detail.status_code == 200 and detail.json()["novelPermission"] == "forbidden"


async def test_someone_else_cannot_change_it_and_a_missing_work_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, content = await _work(db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.commit()
    await _login_as(db_client, other.id)

    forbidden = await db_client.put(f"/contents/{content.id}/novel-permission", json={"novelPermission": "forbidden"})
    missing = await db_client.put(f"/contents/{uuid.uuid4()}/novel-permission", json={"novelPermission": "forbidden"})

    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "Not the content owner")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Content not found")
    assert await _stored(db_session, content.id) == "private"


async def test_a_suspended_creator_cannot_change_it(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """세션 검사(Redis 정지 표식)를 지난 뒤에도 회원 행의 정지를 다시 본다 — 표식 없이 DB 만 정지인 상태로 만든다."""
    creator, content = await _work(db_session, suspended_at=datetime.now(UTC))
    await _login_as(db_client, creator.id)

    resp = await db_client.put(f"/contents/{content.id}/novel-permission", json={"novelPermission": "forbidden"})

    assert (resp.status_code, resp.json()["detail"]) == (403, "Account suspended")
    assert await _stored(db_session, content.id) == "private"


async def test_a_restricted_work_can_still_change_it(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """허락을 낮추는 것은 작가 보호 쪽이라 이용제한 중에도 막지 않는다."""
    creator, content = await _work(db_session)
    await db_session.execute(
        sa.update(Content).where(Content.id == content.id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db_session.commit()
    await _login_as(db_client, creator.id)

    resp = await db_client.put(f"/contents/{content.id}/novel-permission", json={"novelPermission": "forbidden"})

    assert resp.status_code == 204
    assert await _stored(db_session, content.id) == "forbidden"
