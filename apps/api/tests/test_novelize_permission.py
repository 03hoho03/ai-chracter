"""작가의 소설화 허락(`contents.novel_permission`)이 소설 라우트와 방 응답에 미치는 것.

허용 안 함이 막는 것은 하나뿐이다 — 작가가 아닌 사람이 소설이 아직 없는 방에서 소설을 새로 만드는 것. 이미 만든 소설은
허락을 낮춘 뒤에도 열리고(방의 소설 만들기가 그 소설을 돌려준다) 다음 화·연쇄·다시 만들기·AI 수정·읽기가 그대로다. 그래서
아래 매트릭스는 허락을 소설을 만든 **뒤에** 바꾼다.

작업을 띄우는 함수는 기록 없이 버리는 페이크로 바꿔 끼운다 — 여기서는 라우트가 받아들이는지(2xx)만 본다."""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.db.models import ChatRoom, Content, Novel, NovelChapterRevision
from api.novelize import router as novelize_router
from factories import (
    Room,
    _NeverCalledLLMClient,
    _add_chapter,
    _allow_novelize,
    _clear_llm_override,
    _make_user,
    _novel_setup,
    _open_room,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_PERMISSIONS = ("forbidden", "private", "public")
_ACTORS = ("owner", "other")


@pytest.fixture(autouse=True)
def _jobs_not_run(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """작업은 띄우지 않고, LLM 은 불리면 실패한다(라우트는 작업을 넣기만 한다)."""

    async def drop(_factory: Any, _llm: Any, _job_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(novelize_router, "enqueue_job", drop)
    monkeypatch.setattr(novelize_router, "enqueue_chain_job", drop)
    _override_llm_client(_NeverCalledLLMClient())
    yield
    _clear_llm_override()


async def _set_work(db_session: AsyncSession, room_id: uuid.UUID, *, actor: str, permission: str) -> None:
    """방의 원작에 허락을 걸고, `actor` 가 "other" 면 원작의 작가를 다른 회원으로 바꾼다(방 주인은 그대로)."""
    content_id = await db_session.scalar(sa.select(ChatRoom.content_id).where(ChatRoom.id == room_id))
    values: dict[str, object] = {"novel_permission": permission}
    if actor == "other":
        creator = _make_user()
        db_session.add(creator)
        await db_session.flush()
        values["creator_user_id"] = creator.id
    await db_session.execute(sa.update(Content).where(Content.id == content_id).values(**values))
    await db_session.commit()


async def _room_without_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, actor: str, permission: str
) -> Room:
    room = await _open_room(db_client, db_session, turns=1)
    await _allow_novelize(db_session, monkeypatch, room.user_id)
    await _set_work(db_session, room.room_id, actor=actor, permission=permission)
    return room


async def _novel_with_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, actor: str, permission: str
) -> tuple[Room, uuid.UUID, uuid.UUID]:
    """3턴 방의 소설(첫 화 하나)을 만든 **뒤** 허락을 건다. 잔액은 연쇄 한 번을 낼 만큼 넉넉하다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    await clover.grant(db_session, user_id=room.user_id, amount=2000, kind="admin_grant")
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    await _set_work(db_session, room.room_id, actor=actor, permission=permission)
    return room, novel_id, chapter.id


async def _existing_novel_request(
    action: str, db_client: httpx.AsyncClient, db_session: AsyncSession, room: Room, novel_id: uuid.UUID, chapter_id: uuid.UUID
) -> httpx.Response:
    if action == "open_existing":
        return await db_client.post(f"/chat-rooms/{room.room_id}/novel")
    if action == "next_chapter":
        return await db_client.post(
            f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[2][1].id), "expectedCost": 40}
        )
    if action == "chain":
        return await db_client.post(
            f"/novels/{novel_id}/chain", json={"model": "gemini", "expectedCost": 120, "maxBatches": 1}
        )
    if action == "regenerate":
        return await db_client.post(f"/novels/{novel_id}/chapters/{chapter_id}/regenerate", json={"expectedCost": 40})
    if action == "ai_edit":
        revision_id = await db_session.scalar(
            sa.select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id == chapter_id)
        )
        return await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter_id}/ai-edits",
            json={
                "baseRevisionId": str(revision_id),
                "paragraphStart": 0,
                "paragraphEnd": 0,
                "instruction": "더 쓸쓸하게",
                "expectedCost": 20,
            },
        )
    assert action == "read"
    return await db_client.get(f"/novels/{novel_id}")


_EXISTING_NOVEL_ACTIONS = {
    "open_existing": 200,
    "next_chapter": 202,
    "chain": 202,
    "regenerate": 202,
    "ai_edit": 202,
    "read": 200,
}


@pytest.mark.parametrize("actor", _ACTORS)
@pytest.mark.parametrize("permission", _PERMISSIONS)
async def test_new_novel_is_refused_only_to_someone_else_when_the_creator_forbids_it(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    permission: str,
    actor: str,
) -> None:
    """작가 본인은 허락과 무관하게 자기 작품의 대화를 소설로 만든다. 403 은 "허용 안 함 × 다른 회원"뿐이고 소설 행을
    남기지 않는다."""
    room = await _room_without_novel(db_client, db_session, monkeypatch, actor=actor, permission=permission)

    resp = await db_client.post(f"/chat-rooms/{room.room_id}/novel")

    novels = await db_session.scalar(sa.select(sa.func.count()).select_from(Novel).where(Novel.chat_room_id == room.room_id))
    if (permission, actor) == ("forbidden", "other"):
        assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "CONTENT_NOVELIZE_FORBIDDEN"})
        assert novels == 0
    else:
        assert resp.status_code == 201, resp.text
        assert novels == 1


@pytest.mark.parametrize("action", list(_EXISTING_NOVEL_ACTIONS))
@pytest.mark.parametrize("actor", _ACTORS)
@pytest.mark.parametrize("permission", _PERMISSIONS)
async def test_an_existing_novel_keeps_working_whatever_the_permission_becomes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    permission: str,
    actor: str,
    action: str,
) -> None:
    """허락을 낮춰도 이미 만든 소설은 그대로다 — 방에서 다시 열기·다음 화·연쇄·다시 만들기·AI 수정·읽기 모두."""
    room, novel_id, chapter_id = await _novel_with_chapter(
        db_client, db_session, monkeypatch, actor=actor, permission=permission
    )

    resp = await _existing_novel_request(action, db_client, db_session, room, novel_id, chapter_id)

    assert resp.status_code == _EXISTING_NOVEL_ACTIONS[action], resp.text


@pytest.mark.parametrize(
    ("permission", "actor", "has_novel", "blocked"),
    [
        pytest.param("forbidden", "other", False, True, id="forbidden-other-no-novel"),
        pytest.param("private", "other", False, False, id="allowed"),
        pytest.param("forbidden", "owner", False, False, id="creator-themself"),
        pytest.param("forbidden", "other", True, False, id="novel-already-made"),
    ],
)
async def test_room_response_says_whether_a_new_novel_is_blocked(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    permission: str,
    actor: str,
    has_novel: bool,
    blocked: bool,
) -> None:
    """세 조건(허용 안 함 · 작가가 아님 · 이 방에 소설 없음)이 모두일 때만 참이다 — 하나씩 뒤집으면 거짓."""
    if has_novel:
        room, _ = await _novel_setup(db_client, db_session, monkeypatch, turns=1)
        await _set_work(db_session, room.room_id, actor=actor, permission=permission)
    else:
        room = await _room_without_novel(db_client, db_session, monkeypatch, actor=actor, permission=permission)

    resp = await db_client.get(f"/chat-rooms/{room.room_id}")

    assert resp.status_code == 200
    assert resp.json()["novelCreationBlocked"] is blocked
