"""편집 보드 배치와 읽은 위치 라우트.

보드 배치는 통째 저장이고 크기 상한만 서버가 본다. 읽을 때는 지금 없는 화·인물의 자리를 뺀다. 읽은 위치는 화면을 떠날 때
응답을 기다리지 않는 요청으로도 오므로 멱등이어야 하고, 한 번 다 읽은 화는 다 읽은 화로 남는다. 삭제와 겹치는 경쟁은
`test_novelize_edit_races.py` 에 있다."""

import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import NovelCharacter, NovelReadingPosition
from api.novelize.schemas import BOARD_LAYOUT_MAX_BYTES
from factories import (
    _NeverCalledLLMClient,
    _add_batch,
    _clear_llm_override,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)


@pytest.fixture(autouse=True)
def _no_model() -> Iterator[None]:
    _override_llm_client(_NeverCalledLLMClient())
    yield
    _clear_llm_override()


# ── 보드 배치 ───────────────────────────────────────────────────────────────
async def test_board_layout_round_trips_and_drops_places_of_episodes_and_cards_that_are_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """묶음 삭제·인물 합치기는 저장된 배치를 고치지 않는다 — 읽을 때 지금 없는 대상의 자리를 빼야 화면이 받은 키만 다시
    보내 저절로 정리된다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    (chapter,) = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1])
    card = NovelCharacter(novel_id=novel_id, name="도윤")
    db_session.add(card)
    await db_session.commit()
    gone_chapter, gone_card = uuid.uuid4(), uuid.uuid4()
    layout = {
        "version": 1,
        "positions": {
            f"episode:{chapter.id}": {"x": 0, "y": 120.5},
            f"episode:{gone_chapter}": {"x": 0, "y": 240},
            f"character:{card.id}": {"x": 400, "y": -10},
            f"character:{gone_card}": {"x": 400, "y": 90},
            "notes": {"x": -300, "y": 0},
        },
        "viewport": {"x": 10, "y": 20, "zoom": 0.75},
    }

    empty = await db_client.get(f"/novels/{novel_id}/board-layout")
    saved = await db_client.put(f"/novels/{novel_id}/board-layout", json=layout)
    read = await db_client.get(f"/novels/{novel_id}/board-layout")

    assert empty.json() == {"layout": None}
    assert saved.status_code == 204, saved.text
    assert read.json()["layout"] == {
        "version": 1,
        "positions": {
            f"episode:{chapter.id}": {"x": 0, "y": 120.5},
            f"character:{card.id}": {"x": 400, "y": -10},
            "notes": {"x": -300, "y": 0},
        },
        "viewport": {"x": 10, "y": 20, "zoom": 0.75},
    }


async def test_board_layout_over_the_size_cap_is_422_and_keeps_the_saved_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    small = {"version": 1, "positions": {"notes": {"x": 1, "y": 2}}, "viewport": None}
    await db_client.put(f"/novels/{novel_id}/board-layout", json=small)
    # 키 하나가 약 70바이트라 상한 / 60 개면 넘는다. 키는 형식만 맞으면 된다(없는 대상은 읽을 때 빠진다).
    huge = {
        "version": 1,
        "positions": {f"episode:{uuid.uuid4()}": {"x": 1.5, "y": 2.5} for _ in range(BOARD_LAYOUT_MAX_BYTES // 60)},
        "viewport": None,
    }

    resp = await db_client.put(f"/novels/{novel_id}/board-layout", json=huge)

    assert (resp.status_code, resp.json()["detail"]) == (422, {"code": "NOVEL_BOARD_LAYOUT_TOO_LARGE"})
    assert (await db_client.get(f"/novels/{novel_id}/board-layout")).json()["layout"] == small


async def test_board_layout_just_under_the_cap_is_saved(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한은 화면이 받은 값과 같은 바이트 수다 — 서버가 더 작게 자르면 화면이 보낼 수 있다고 본 배치가 422 가 된다."""
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    positions: dict[str, object] = {}
    layout: dict[str, object] = {"version": 1, "positions": positions, "viewport": None}
    while len(json.dumps(layout, separators=(",", ":")).encode()) <= BOARD_LAYOUT_MAX_BYTES - 80:
        positions[f"character:{uuid.uuid4()}"] = {"x": 1.0, "y": 2.0}

    resp = await db_client.put(f"/novels/{novel_id}/board-layout", json=layout)

    assert resp.status_code == 204, resp.text


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param({"version": 1, "positions": {"chapter:x": {"x": 0, "y": 0}}, "viewport": None}, id="unknown-key"),
        pytest.param({"version": 2, "positions": {}, "viewport": None}, id="unknown-version"),
        pytest.param({"version": 1, "positions": {}, "viewport": {"x": 0, "y": 0, "zoom": 0}}, id="zero-zoom"),
    ],
)
async def test_board_layout_of_an_unknown_shape_is_422(
    layout: dict[str, object], db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    resp = await db_client.put(f"/novels/{novel_id}/board-layout", json=layout)

    assert resp.status_code == 422


# ── 읽은 위치 ───────────────────────────────────────────────────────────────
async def _positions(db: AsyncSession, novel_id: uuid.UUID) -> list[tuple[uuid.UUID, int, int, bool]]:
    rows = await db.scalars(
        sa.select(NovelReadingPosition)
        .where(NovelReadingPosition.novel_id == novel_id)
        .execution_options(populate_existing=True)
    )
    return [(p.chapter_id, p.paragraph_index, p.paragraph_count, p.finished_at is not None) for p in rows.all()]


async def test_reading_position_is_an_idempotent_upsert_and_finishing_never_reverts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first, second = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], episodes=2)
    revision = uuid.uuid4()
    url = f"/novels/{novel_id}/chapters/{first.id}/reading-position"

    started = await db_client.put(
        url, json={"paragraphIndex": 1, "paragraphCount": 3, "revisionId": str(revision), "finished": False}
    )
    repeated = await db_client.put(
        url, json={"paragraphIndex": 1, "paragraphCount": 3, "revisionId": str(revision), "finished": False}
    )
    assert (started.status_code, repeated.status_code) == (204, 204)
    assert await _positions(db_session, novel_id) == [(first.id, 1, 3, False)]

    await db_client.put(
        url, json={"paragraphIndex": 2, "paragraphCount": 3, "revisionId": str(revision), "finished": True}
    )
    reread = await db_client.put(
        url, json={"paragraphIndex": 0, "paragraphCount": 4, "revisionId": str(revision), "finished": False}
    )

    assert reread.status_code == 204
    assert await _positions(db_session, novel_id) == [(first.id, 0, 4, True)]
    detail = (await db_client.get(f"/novels/{novel_id}")).json()
    assert [c["finishedReading"] for c in detail["chapters"]] == [True, False]
    assert (detail["lastRead"]["chapterId"], detail["lastRead"]["paragraphIndex"]) == (str(first.id), 0)
    assert second.id not in [row[0] for row in await _positions(db_session, novel_id)]


async def test_reading_position_outside_the_paragraphs_is_422_and_a_missing_chapter_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_room, other_novel = await _novel_setup(db_client, db_session, monkeypatch)
    other_messages = await _room_messages(db_session, other_room.room_id)
    (foreign,) = await _add_batch(db_session, other_novel, other_room, other_messages[0], other_room.turns[1][1])
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    (chapter,) = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1])
    body = {"paragraphIndex": 3, "paragraphCount": 3, "revisionId": str(uuid.uuid4()), "finished": False}

    beyond = await db_client.put(f"/novels/{novel_id}/chapters/{chapter.id}/reading-position", json=body)
    body["paragraphIndex"] = 0
    missing = await db_client.put(f"/novels/{novel_id}/chapters/{uuid.uuid4()}/reading-position", json=body)
    other_novels = await db_client.put(f"/novels/{novel_id}/chapters/{foreign.id}/reading-position", json=body)

    assert (beyond.status_code, beyond.json()["detail"]) == (422, {"code": "NOVEL_PARAGRAPH_RANGE_INVALID"})
    assert (missing.status_code, missing.json()["detail"]) == (404, {"code": "NOVEL_CHAPTER_NOT_FOUND"})
    assert other_novels.status_code == 404
    assert await _positions(db_session, novel_id) == []
    assert await _positions(db_session, other_novel) == []
