"""소설 라우트 — 게이트·소유권·소설 만들기·목록·상세·삭제·설정 노트·주인공 이름.

장 경계 제안·장 생성·재생성·마지막 장 삭제는 `test_novelize_chapter_routes.py`, 장 읽기·직접 수정·되돌리기·AI 수정·
적용은 `test_novelize_edit_routes.py` 에 있다. 셋이 같은 준비 함수(`factories.py` 의 소설 라우트 절)를 쓴다."""

import uuid
from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa
from fastapi import routing as fastapi_routing
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.core.config import settings
from api.db.models import ChatRoom, Novel, NovelChapter, NovelChapterRevision, NovelJob, User, UserPersona
from api.main import app
from api.novelize import router as novelize_router
from api.novelize.access import require_novelize_access
from factories import (
    _add_chapter,
    _allow_novelize,
    _login_as,
    _make_published,
    _make_user,
    _novel_ledger,
    _novel_setup,
    _open_room,
    _queue_job,
    _room_messages,
)

_NOVEL_PATH_PREFIXES = ("/novels", "/chat-rooms/{room_id}/novel")


def _novel_routes() -> list[tuple[str, APIRoute]]:
    routes: list[tuple[str, APIRoute]] = []
    for context in fastapi_routing.iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute) and route.path.startswith(_NOVEL_PATH_PREFIXES):
            routes.extend((method, route) for method in sorted(route.methods or ()))
    return routes


# ── 게이트 ──────────────────────────────────────────────────────────────────
def test_every_novel_route_carries_the_novelize_gate() -> None:
    """읽기 라우트 하나를 빠뜨리는 것이 이 게이트의 실제 위험이라 라우트 테이블 전체를 본다."""
    routes = _novel_routes()
    # 라우트가 하나도 안 잡히면 이 검사는 아무것도 지키지 않는다 — 접두사가 바뀌었는지부터 본다.
    assert len(routes) >= 12, [f"{m} {r.path}" for m, r in routes]
    missing = [
        f"{method} {route.path}"
        for method, route in routes
        if require_novelize_access not in [dep.call for dep in route.dependant.dependencies]
    ]
    assert missing == []


_DUMMY_PATH_IDS = {
    name: str(uuid.uuid4()) for name in ("novel_id", "chapter_id", "revision_id", "job_id", "room_id")
}


async def test_without_access_every_novel_route_is_403_even_before_the_consent_gate(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """허용이 없는 사용자는 읽기까지 모두 같은 403 이다. 재동의도 필요한 상태로 두어, 기능 게이트가 재동의 게이트보다
    먼저 돈다는 순서도 함께 고정한다(재동의 403 이 나오면 허용 없는 사용자에게 기능의 쓰기 라우트가 드러난다)."""
    monkeypatch.setattr(settings, "novelize_enabled", True)
    user = _make_user(terms_version=None)
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await db_session.commit()
    await _login_as(db_client, user.id)

    results = {
        f"{method} {route.path}": await db_client.request(method, route.path.format(**_DUMMY_PATH_IDS), json={})
        for method, route in _novel_routes()
    }

    wrong = {
        key: (resp.status_code, resp.json().get("detail"))
        for key, resp in results.items()
        if resp.status_code != 403 or resp.json().get("detail") != {"code": "NOVELIZE_NOT_ALLOWED"}
    }
    assert wrong == {}


# ── 방의 소설 ───────────────────────────────────────────────────────────────
async def test_creating_a_room_novel_copies_the_work_and_prefills_the_profile_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, persona="서진")
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None

    again = await db_client.post(f"/chat-rooms/{room.room_id}/novel")
    fetched = await db_client.get(f"/chat-rooms/{room.room_id}/novel")

    assert again.status_code == 200, again.text
    assert again.json()["id"] == str(novel_id)
    assert fetched.status_code == 200 and fetched.json()["id"] == str(novel_id)
    body = fetched.json()
    assert (body["chatRoomId"], body["contentId"], body["contentType"]) == (
        str(room.room_id),
        str(chat_room.content_id),
        "character",
    )
    assert (body["contentTitle"], body["characterName"], body["protagonistName"]) == ("캐릭터", "캐릭터", "서진")
    assert (body["settingNotes"], body["chapters"], body["activeJob"]) == ("", [], None)
    rows = (await db_session.scalars(sa.select(Novel).where(Novel.chat_room_id == room.room_id))).all()
    assert len(rows) == 1
    assert await _novel_ledger(db_session, room.user_id) == []


async def test_room_novel_falls_back_to_the_work_default_name_then_to_none(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, persona=None, lane="story")
    story = (await db_client.get(f"/novels/{novel_id}")).json()

    assert (story["contentType"], story["characterName"], story["protagonistName"]) == ("story", None, None)

    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    await db_session.execute(
        sa.text("UPDATE story_version_details SET default_user_name = '나그네' WHERE content_version_id = :v"),
        {"v": chat_room.content_version_id},
    )
    await db_session.execute(sa.delete(Novel).where(Novel.id == novel_id))
    await db_session.commit()

    recreated = await db_client.post(f"/chat-rooms/{room.room_id}/novel")

    assert recreated.status_code == 201, recreated.text
    assert recreated.json()["protagonistName"] == "나그네"


async def test_room_novel_lookup_is_404_before_creation_and_403_for_someone_elses_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign_room = await _open_room(db_client, db_session, turns=1)
    room = await _open_room(db_client, db_session, turns=1)
    await _allow_novelize(db_session, monkeypatch, room.user_id)

    missing = await db_client.get(f"/chat-rooms/{room.room_id}/novel")
    foreign_get = await db_client.get(f"/chat-rooms/{foreign_room.room_id}/novel")
    foreign_post = await db_client.post(f"/chat-rooms/{foreign_room.room_id}/novel")
    no_room = await db_client.post(f"/chat-rooms/{uuid.uuid4()}/novel")

    assert missing.status_code == 404 and missing.json()["detail"] == {"code": "NOVEL_NOT_FOUND"}
    assert [foreign_get.status_code, foreign_post.status_code, no_room.status_code] == [403, 403, 404]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(Novel)) == 0


# ── 소유권 ──────────────────────────────────────────────────────────────────
async def test_someone_elses_novel_is_403_and_a_missing_one_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, foreign_id = await _novel_setup(db_client, db_session, monkeypatch)
    _own_room, own_id = await _novel_setup(db_client, db_session, monkeypatch)

    foreign = await db_client.get(f"/novels/{foreign_id}")
    foreign_delete = await db_client.delete(f"/novels/{foreign_id}")
    missing = await db_client.get(f"/novels/{uuid.uuid4()}")
    own = await db_client.get(f"/novels/{own_id}")

    assert foreign.status_code == 403 and foreign.json()["detail"] == {"code": "NOVEL_FORBIDDEN"}
    assert foreign_delete.status_code == 403
    assert missing.status_code == 404 and missing.json()["detail"] == {"code": "NOVEL_NOT_FOUND"}
    assert own.status_code == 200
    assert await db_session.get(Novel, foreign_id) is not None


# ── 목록 ────────────────────────────────────────────────────────────────────
async def test_list_shows_my_novels_newest_first_including_ones_whose_room_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(novelize_router, "NOVEL_PAGE_SIZE", 2)
    room, first = await _novel_setup(db_client, db_session, monkeypatch)
    user_id = room.user_id
    owner = await db_session.get_one(User, user_id)
    second_room = await _open_room(db_client, db_session, turns=1, user=owner)
    third_room = await _open_room(db_client, db_session, turns=1, user=owner)
    second = uuid.UUID((await db_client.post(f"/chat-rooms/{second_room.room_id}/novel")).json()["id"])
    third = uuid.UUID((await db_client.post(f"/chat-rooms/{third_room.room_id}/novel")).json()["id"])
    base = (await db_session.get_one(Novel, first)).created_at
    for offset, novel_id in enumerate((first, second, third)):
        await db_session.execute(
            sa.update(Novel).where(Novel.id == novel_id).values(updated_at=base + timedelta(minutes=offset))
        )
    await _add_chapter(db_session, first, room, (await _room_messages(db_session, room.room_id))[0], room.turns[1][1])
    await db_session.commit()
    assert (await db_client.delete(f"/chat-rooms/{room.room_id}")).status_code == 204
    _other_room, _other = await _novel_setup(db_client, db_session, monkeypatch)
    await _login_as(db_client, user_id)

    page1 = await db_client.get("/novels")
    page2 = await db_client.get("/novels", params={"cursor": page1.json()["nextCursor"]})

    assert page1.status_code == 200, page1.text
    assert [item["id"] for item in page1.json()["items"]] == [str(third), str(second)]
    assert page2.json()["nextCursor"] is None
    (last,) = page2.json()["items"]
    assert (last["id"], last["chatRoomId"], last["chapterCount"]) == (str(first), None, 1)


# ── 상세 ────────────────────────────────────────────────────────────────────
async def test_detail_lists_chapters_with_their_current_revision_and_the_prices_of_the_moment(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    second = await _add_chapter(db_session, novel_id, room, room.turns[2][0], room.turns[3][1])
    db_session.add(NovelChapterRevision(chapter_id=first.id, revision_no=2, body="고친 본문", source="manual_edit"))
    await db_session.commit()
    monkeypatch.setattr(clover, "NOVELIZE_CHAPTER_GENERATE_COST", 31)
    monkeypatch.setattr(clover, "NOVELIZE_CHAPTER_REGENERATE_COST", 32)
    monkeypatch.setattr(clover, "NOVELIZE_AI_EDIT_COST", 7)

    resp = await db_client.get(f"/novels/{novel_id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [
        (c["id"], c["ordinal"], c["assistantMessageCount"], c["currentRevisionNo"], c["currentRevisionSource"])
        for c in body["chapters"]
    ] == [(str(first.id), 1, 2, 2, "manual_edit"), (str(second.id), 2, 2, 1, "generate")]
    assert body["prices"] == {"chapterGenerate": 31, "chapterRegenerate": 32, "aiEdit": 7}
    assert body["limits"]["settingNotesMaxLength"] == 2000
    assert body["activeJob"] is None


async def test_detail_shows_the_running_job_and_expires_a_dead_one_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    job = await _queue_job(db_session, novel_id, messages[0], room.turns[1][1])

    alive = await db_client.get(f"/novels/{novel_id}")

    assert alive.json()["activeJob"] == {
        "id": str(job.id),
        "kind": "chapter_generate",
        "status": "queued",
        "chapterId": None,
    }

    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == job.id).values(heartbeat_at=sa.func.now() - timedelta(hours=1))
    )
    await db_session.commit()

    dead = await db_client.get(f"/novels/{novel_id}")
    via_room = await db_client.get(f"/chat-rooms/{room.room_id}/novel")

    assert dead.json()["activeJob"] is None and via_room.json()["activeJob"] is None
    stored = await db_session.scalar(
        sa.select(NovelJob).where(NovelJob.id == job.id).execution_options(populate_existing=True)
    )
    assert stored is not None and (stored.status, stored.failure_code) == ("failed", "expired")
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -20), ("novelize_refund", 20)]


async def test_room_novel_lookup_also_expires_a_dead_job(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    job = await _queue_job(db_session, novel_id, messages[0], room.turns[1][1])
    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == job.id).values(heartbeat_at=sa.func.now() - timedelta(hours=1))
    )
    await db_session.commit()

    resp = await db_client.get(f"/chat-rooms/{room.room_id}/novel")

    assert resp.json()["activeJob"] is None
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -20), ("novelize_refund", 20)]


# ── 설정 노트·주인공 이름 ───────────────────────────────────────────────────
async def test_setting_notes_are_saved_trimmed_and_capped(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    saved = await db_client.put(f"/novels/{novel_id}/notes", json={"settingNotes": "  서진은 왼손잡이다.  "})
    too_long = await db_client.put(f"/novels/{novel_id}/notes", json={"settingNotes": "가" * 2001})

    assert saved.status_code == 200, saved.text
    assert saved.json()["settingNotes"] == "서진은 왼손잡이다."
    assert too_long.status_code == 422
    stored = await db_session.scalar(
        sa.select(Novel.setting_notes).where(Novel.id == novel_id).execution_options(populate_existing=True)
    )
    assert stored == "서진은 왼손잡이다."


async def test_protagonist_name_can_be_set_and_is_checked_like_a_profile_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, persona=None)

    saved = await db_client.put(f"/novels/{novel_id}/protagonist-name", json={"protagonistName": " 한서진 "})
    with_colon = await db_client.put(f"/novels/{novel_id}/protagonist-name", json={"protagonistName": "서진:"})
    blank = await db_client.put(f"/novels/{novel_id}/protagonist-name", json={"protagonistName": "  "})

    assert saved.status_code == 200, saved.text
    assert saved.json()["protagonistName"] == "한서진"
    assert [with_colon.status_code, blank.status_code] == [422, 422]


# ── 삭제 ────────────────────────────────────────────────────────────────────
async def test_deleting_a_novel_refunds_its_running_job_and_removes_every_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    job = await _queue_job(db_session, novel_id, room.turns[2][0], room.turns[3][1])

    resp = await db_client.delete(f"/novels/{novel_id}")

    assert resp.status_code == 204, resp.text
    for model, column, value in (
        (Novel, Novel.id, novel_id),
        (NovelChapter, NovelChapter.id, chapter.id),
        (NovelChapterRevision, NovelChapterRevision.chapter_id, chapter.id),
        (NovelJob, NovelJob.id, job.id),
    ):
        assert await db_session.scalar(sa.select(sa.func.count()).select_from(model).where(column == value)) == 0
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -20), ("novelize_refund", 20)]
    assert await db_session.get(ChatRoom, room.room_id) is not None
    assert (await db_client.get(f"/chat-rooms/{room.room_id}/novel")).status_code == 404


async def test_room_persona_name_is_read_from_the_room_not_the_default_profile(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _open_room(db_client, db_session, turns=1)
    await _allow_novelize(db_session, monkeypatch, room.user_id)
    persona = UserPersona(user_id=room.user_id, name="방 프로필")
    db_session.add(persona)
    await db_session.flush()
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(persona_id=persona.id))
    await db_session.commit()

    resp = await db_client.post(f"/chat-rooms/{room.room_id}/novel")

    assert resp.status_code == 201, resp.text
    assert resp.json()["protagonistName"] == "방 프로필"
