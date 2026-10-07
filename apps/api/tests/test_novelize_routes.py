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
from api.db.models import (
    Asset,
    AssetKind,
    AssetStatus,
    ChatRoom,
    Content,
    ModerationStatus,
    Novel,
    NovelChapter,
    NovelChapterRevision,
    NovelJob,
    User,
    UserFeatureGrant,
    UserPersona,
)
from api.db.models.novel import NovelReadingPosition
from api.main import app
from api.novelize import router as novelize_router
from api.novelize.access import require_novelize_access
from factories import (
    _add_batch,
    _add_chapter,
    _allow_novel_premium,
    _allow_novelize,
    _make_asset,
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
# 게이트 밖에 두는 라우트. 소설 삭제는 자기 데이터를 지울 권리라 기능 허용과 무관하다 — 허용을 거두거나 기능을
# 끄면 게이트가 닫히는데, 그때도 이용자가 자기 소설을 지울 수 있어야 한다(로그인·소유권만 본다).
_GATE_EXEMPT_ROUTES = {"DELETE /novels/{novel_id}"}


def _novel_routes() -> list[tuple[str, APIRoute]]:
    routes: list[tuple[str, APIRoute]] = []
    for context in fastapi_routing.iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute) and route.path.startswith(_NOVEL_PATH_PREFIXES):
            routes.extend((method, route) for method in sorted(route.methods or ()))
    return routes


# ── 게이트 ──────────────────────────────────────────────────────────────────
def test_every_novel_route_carries_the_novelize_gate() -> None:
    """읽기 라우트 하나를 빠뜨리는 것이 이 게이트의 실제 위험이라 라우트 테이블 전체를 본다. 예외 목록의 라우트는
    반대로 게이트가 **없어야** 한다 — 실수로 다시 게이트 뒤로 들어가면 회수된 이용자가 자기 소설을 못 지운다."""
    routes = _novel_routes()
    # 라우트가 하나도 안 잡히면 이 검사는 아무것도 지키지 않는다 — 접두사가 바뀌었는지부터 본다.
    assert len(routes) >= 19, [f"{m} {r.path}" for m, r in routes]
    gated = {
        f"{method} {route.path}": require_novelize_access in [dep.call for dep in route.dependant.dependencies]
        for method, route in routes
    }
    assert {key for key, has_gate in gated.items() if not has_gate} == _GATE_EXEMPT_ROUTES


_DUMMY_PATH_IDS = {
    name: str(uuid.uuid4())
    for name in ("novel_id", "chapter_id", "revision_id", "job_id", "room_id", "batch_id", "character_id", "snapshot_id")
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
        if f"{method} {route.path}" not in _GATE_EXEMPT_ROUTES
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
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST", 31)
    monkeypatch.setattr(clover, "NOVELIZE_AI_EDIT_COST", 7)

    resp = await db_client.get(f"/novels/{novel_id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [
        (c["id"], c["ordinal"], c["assistantMessageCount"], c["currentRevisionNo"], c["currentRevisionSource"])
        for c in body["chapters"]
    ] == [(str(first.id), 1, 2, 2, "manual_edit"), (str(second.id), 2, 2, 1, "generate")]
    assert body["prices"] == {"chapterGenerate": 31, "chapterRegenerate": 31, "aiEdit": 7}
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
        "batchId": None,
        "completedBatches": None,
        "plannedBatches": None,
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
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -40), ("novelize_refund", 40)]


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
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -40), ("novelize_refund", 40)]


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
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -40), ("novelize_refund", 40)]
    assert await db_session.get(ChatRoom, room.room_id) is not None
    assert (await db_client.get(f"/chat-rooms/{room.room_id}/novel")).status_code == 404


@pytest.mark.parametrize("closed_by", ["kill_switch", "allowlist", "grant_row"])
async def test_deleting_a_novel_needs_only_login_and_ownership_even_after_access_is_withdrawn(
    closed_by: str, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기능을 끄거나 허용을 거둬도 자기 소설은 지울 수 있다. 남의 소설·없는 소설은 그대로 막힌다."""
    _foreign_room, foreign_id = await _novel_setup(db_client, db_session, monkeypatch)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    if closed_by == "kill_switch":
        monkeypatch.setattr(settings, "novelize_enabled", False)
    elif closed_by == "allowlist":
        monkeypatch.setattr(settings, "novelize_grant_allowlist", [])
    else:
        await db_session.execute(sa.delete(UserFeatureGrant).where(UserFeatureGrant.user_id == room.user_id))
        await db_session.commit()
    assert (await db_client.get(f"/novels/{novel_id}")).status_code == 403

    foreign = await db_client.delete(f"/novels/{foreign_id}")
    missing = await db_client.delete(f"/novels/{uuid.uuid4()}")
    own = await db_client.delete(f"/novels/{novel_id}")

    assert foreign.status_code == 403 and foreign.json()["detail"] == {"code": "NOVEL_FORBIDDEN"}
    assert missing.status_code == 404 and missing.json()["detail"] == {"code": "NOVEL_NOT_FOUND"}
    assert own.status_code == 204, own.text
    assert await db_session.get(Novel, novel_id, populate_existing=True) is None
    assert await db_session.get(Novel, foreign_id, populate_existing=True) is not None


async def test_deleting_a_novel_still_needs_a_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.delete(f"/novels/{uuid.uuid4()}")

    assert resp.status_code == 401


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


# ── 묶음·화·읽은 자리·표지 ──────────────────────────────────────────────────
async def test_detail_lists_batches_with_regenerate_prices_and_why_a_model_cannot_take_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다시 만들기 금액은 묶음의 화 수 × 모델 화 단가다. 화 수나 턴 수를 담지 못하는 모델은 목록에 남되 이유가 붙는다
    (화면은 그 모델을 비활성으로 보인다)."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await _allow_novel_premium(db_session, monkeypatch, room.user_id)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns_opus", 1)
    messages = await _room_messages(db_session, room.room_id)
    (single,) = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1])
    pair = await _add_batch(db_session, novel_id, room, room.turns[2][0], room.turns[2][1], episodes=2)

    body = (await db_client.get(f"/novels/{novel_id}")).json()

    assert [(b["id"], b["ordinal"], b["chapterIds"]) for b in body["batches"]] == [
        (str(single.batch_id), 1, [str(single.id)]),
        (str(pair[0].batch_id), 2, [str(c.id) for c in pair]),
    ]
    options = {
        b["ordinal"]: [(o["model"], o["cost"], o["eligible"], o["ineligibleReason"]) for o in b["regenerateOptions"]]
        for b in body["batches"]
    }
    assert options == {
        1: [("gemini", 40, True, None), ("sonnet", 105, True, None), ("opus", 170, False, "too_many_turns")],
        2: [("gemini", 80, True, None), ("sonnet", 210, False, "too_many_episodes"), ("opus", 340, False, "too_many_episodes")],
    }
    assert [(c["batchId"], c["episodeIndex"]) for c in body["chapters"]] == [
        (str(single.batch_id), 0),
        (str(pair[0].batch_id), 0),
        (str(pair[0].batch_id), 1),
    ]


async def test_detail_shows_episode_fields_finished_reading_and_the_last_read_place(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first, second = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], episodes=2, body="가나다")
    await db_session.execute(
        sa.update(NovelChapter).where(NovelChapter.id == first.id).values(title="첫 화", summary="만났다")
    )
    base = (await db_session.get_one(Novel, novel_id)).created_at
    revision_id = uuid.uuid4()
    db_session.add_all(
        [
            NovelReadingPosition(
                chapter_id=first.id,
                novel_id=novel_id,
                paragraph_index=4,
                paragraph_count=5,
                revision_id=uuid.uuid4(),
                finished_at=base,
                updated_at=base,
            ),
            NovelReadingPosition(
                chapter_id=second.id,
                novel_id=novel_id,
                paragraph_index=1,
                paragraph_count=6,
                revision_id=revision_id,
                updated_at=base + timedelta(minutes=1),
            ),
        ]
    )
    await db_session.commit()

    body = (await db_client.get(f"/novels/{novel_id}")).json()

    assert [
        (c["title"], c["summary"], c["authorNote"], c["charCount"], c["finishedReading"]) for c in body["chapters"]
    ] == [("첫 화", "만났다", "", 3, True), (None, None, "", 3, False)]
    assert body["lastRead"] is not None
    assert (body["lastRead"]["chapterId"], body["lastRead"]["paragraphIndex"], body["lastRead"]["paragraphCount"]) == (
        str(second.id),
        1,
        6,
    )
    assert body["lastRead"]["revisionId"] == str(revision_id)


async def test_detail_shows_the_chain_parent_as_the_active_job_with_its_progress(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """연쇄 중에는 부모와 자식이 함께 진행 중이다. 화면이 자식을 폴링하면 첫 묶음이 끝날 때 전체가 끝난 것으로 읽으므로
    상세는 부모를 고른다 — 자식을 먼저 만든 것처럼 시각을 앞에 두어도 그렇다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    base = (await db_session.get_one(Novel, novel_id)).created_at
    parent = NovelJob(
        novel_id=novel_id,
        user_id=room.user_id,
        kind="chain_generate",
        status="running",
        model="gemini",
        charged_amount=240,
        unit_price=40,
        planned_batches=2,
        batch_k_max=3,
        created_at=base + timedelta(minutes=1),
    )
    db_session.add(parent)
    await db_session.flush()
    for status, minute in (("succeeded", -2), ("running", -1)):
        db_session.add(
            NovelJob(
                novel_id=novel_id,
                user_id=room.user_id,
                kind="chapter_generate",
                status=status,
                model="gemini",
                charged_amount=0,
                parent_job_id=parent.id,
                created_at=base + timedelta(minutes=minute),
            )
        )
    await db_session.commit()

    active = (await db_client.get(f"/novels/{novel_id}")).json()["activeJob"]
    polled = (await db_client.get(f"/novels/{novel_id}/jobs/{parent.id}")).json()

    assert active is not None
    assert (active["id"], active["kind"], active["completedBatches"], active["plannedBatches"]) == (
        str(parent.id),
        "chain_generate",
        1,
        2,
    )
    assert (polled["completedBatches"], polled["plannedBatches"]) == (1, 2)


async def test_job_polling_reports_the_amount_actually_refunded(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """목표보다 적은 화를 낸 성공도 일부를 돌려받는다 — 화면은 `refunded` 가 아니라 금액으로 안내한다. 금액 칸을 모르는
    옛 코드가 환불한 실패는 낸 금액 전부다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    rows = {
        "partial": NovelJob(
            status="succeeded", charged_amount=120, episode_count_target=3, refunded_amount=40, refunded_at=sa.func.now()
        ),
        "legacy": NovelJob(status="failed", charged_amount=40, refunded_at=sa.func.now(), failure_code="llm_error"),
        "none": NovelJob(status="succeeded", charged_amount=40),
    }
    for job in rows.values():
        job.novel_id, job.user_id, job.kind = novel_id, room.user_id, "chapter_generate"
    db_session.add_all(rows.values())
    await db_session.commit()

    amounts = {
        name: (await db_client.get(f"/novels/{novel_id}/jobs/{job.id}")).json()["refundedAmount"]
        for name, job in rows.items()
    }

    assert amounts == {"partial": 40, "legacy": 40, "none": 0}


async def test_title_edit_takes_the_title_from_the_ai_and_synopsis_is_saved_trimmed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    synopsis_only = await db_client.patch(f"/novels/{novel_id}", json={"synopsis": "  두 사람의 여름.  "})
    titled = await db_client.patch(f"/novels/{novel_id}", json={"title": " 비 오는 저녁 "})
    blank = await db_client.patch(f"/novels/{novel_id}", json={"title": "   "})

    assert synopsis_only.status_code == 200, synopsis_only.text
    assert (synopsis_only.json()["synopsis"], synopsis_only.json()["titleEdited"]) == ("두 사람의 여름.", False)
    assert (titled.json()["title"], titled.json()["titleEdited"], titled.json()["synopsis"]) == (
        "비 오는 저녁",
        True,
        "두 사람의 여름.",
    )
    assert blank.status_code == 422


async def test_cover_must_be_my_ready_generated_image_and_falls_back_when_the_image_is_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남의 이미지·업로드 이미지·준비 중 이미지는 같은 422 다. 고른 이미지를 지우면 표지만 비고 원작 썸네일로 돌아간다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.flush()
    generated, ready = AssetKind.GENERATED, AssetStatus.READY
    foreign = await _make_asset(db_session, stranger.id, kind=generated, status=ready)
    uploaded = await _make_asset(db_session, room.user_id, kind=AssetKind.ORIGINAL, status=ready)
    pending = await _make_asset(db_session, room.user_id, kind=generated, status=AssetStatus.PENDING)
    mine = await _make_asset(db_session, room.user_id, kind=generated, status=ready)
    await db_session.commit()
    work_cover = (await db_client.get(f"/novels/{novel_id}")).json()["cover"]

    rejected = [
        await db_client.patch(f"/novels/{novel_id}", json={"coverAssetId": str(asset.id)})
        for asset in (foreign, uploaded, pending)
    ]
    chosen = await db_client.patch(f"/novels/{novel_id}", json={"coverAssetId": str(mine.id)})
    await db_session.execute(sa.delete(Asset).where(Asset.id == mine.id))
    await db_session.commit()
    after_delete = await db_client.get(f"/novels/{novel_id}")

    assert [(r.status_code, r.json()["detail"]) for r in rejected] == [(422, {"code": "NOVEL_COVER_INVALID"})] * 3
    assert (work_cover["source"], work_cover["assetId"]) == ("work", None)
    assert work_cover["url"] is not None
    assert chosen.status_code == 200, chosen.text
    assert (chosen.json()["cover"]["source"], chosen.json()["cover"]["assetId"]) == ("generated", str(mine.id))
    assert "_display.webp" in chosen.json()["cover"]["url"]
    assert after_delete.json()["cover"] == work_cover
    stored = await db_session.scalar(
        sa.select(Novel.cover_asset_id).where(Novel.id == novel_id).execution_options(populate_existing=True)
    )
    assert stored is None


async def test_clearing_the_cover_goes_back_to_the_work_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    mine = await _make_asset(db_session, room.user_id, kind=AssetKind.GENERATED, status=AssetStatus.READY)
    await db_session.commit()
    await db_client.patch(f"/novels/{novel_id}", json={"coverAssetId": str(mine.id)})

    untouched = await db_client.patch(f"/novels/{novel_id}", json={"synopsis": "소개"})
    cleared = await db_client.patch(f"/novels/{novel_id}", json={"coverAssetId": None})

    assert untouched.json()["cover"]["source"] == "generated"
    assert (cleared.json()["cover"]["source"], cleared.json()["cover"]["assetId"]) == ("work", None)


async def test_source_link_is_offered_only_while_the_work_is_viewable(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    content_id = (await db_session.get_one(Novel, novel_id)).content_id

    open_work = (await db_client.get(f"/novels/{novel_id}")).json()["source"]
    await db_session.execute(
        sa.update(Content).where(Content.id == content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db_session.commit()
    restricted = (await db_client.get(f"/novels/{novel_id}")).json()["source"]

    assert open_work["linkable"] is True and open_work["thumbnailUrl"] is not None
    assert restricted["linkable"] is False


async def test_chapter_title_and_author_note_can_be_edited_only_in_my_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_room, other_id = await _novel_setup(db_client, db_session, monkeypatch)
    other = await _add_chapter(
        db_session, other_id, other_room, (await _room_messages(db_session, other_room.room_id))[0], other_room.turns[1][1]
    )
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    chapter = await _add_chapter(
        db_session, novel_id, room, (await _room_messages(db_session, room.room_id))[0], room.turns[1][1]
    )

    note_only = await db_client.patch(f"/novels/{novel_id}/chapters/{chapter.id}", json={"authorNote": " 고마워요 "})
    titled = await db_client.patch(f"/novels/{novel_id}/chapters/{chapter.id}", json={"title": "새 제목"})
    note_again = await db_client.patch(f"/novels/{novel_id}/chapters/{chapter.id}", json={"authorNote": "또"})
    edited_at = (await db_session.get_one(NovelChapter, chapter.id, populate_existing=True)).title_edited_at
    cleared = await db_client.patch(f"/novels/{novel_id}/chapters/{chapter.id}", json={"title": None})
    foreign = await db_client.patch(f"/novels/{novel_id}/chapters/{other.id}", json={"title": "남의 화"})

    assert note_only.status_code == 200, note_only.text
    assert (note_only.json()["chapters"][0]["title"], note_only.json()["chapters"][0]["titleEdited"]) == (None, False)
    (summary,) = titled.json()["chapters"]
    assert (summary["title"], summary["titleEdited"], summary["authorNote"]) == ("새 제목", True, "고마워요")
    # 제목을 보내지 않은 수정은 제목도 고친 표시도 건드리지 않는다.
    assert (note_again.json()["chapters"][0]["title"], note_again.json()["chapters"][0]["titleEdited"]) == (
        "새 제목",
        True,
    )
    assert edited_at is not None
    # 제목을 비우면 고친 표시도 비워져 다음 다시 만들기가 AI 제목을 쓴다.
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["chapters"][0]["title"], cleared.json()["chapters"][0]["titleEdited"]) == (None, False)
    stored = await db_session.get_one(NovelChapter, chapter.id, populate_existing=True)
    assert (stored.title, stored.title_edited_at) == (None, None)
    assert foreign.status_code == 404 and foreign.json()["detail"] == {"code": "NOVEL_CHAPTER_NOT_FOUND"}


async def test_list_items_carry_the_novel_title_and_cover(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await db_client.patch(f"/novels/{novel_id}", json={"title": "여름"})

    (item,) = (await db_client.get("/novels")).json()["items"]

    assert (item["title"], item["cover"]["source"]) == ("여름", "work")
    assert item["cover"]["url"] is not None
