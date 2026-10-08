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
    _count_queries,
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


async def test_reading_position_beyond_any_body_length_is_422_not_an_integer_overflow(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    (chapter,) = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1])
    url = f"/novels/{novel_id}/chapters/{chapter.id}/reading-position"

    resp = await db_client.put(
        url, json={"paragraphIndex": 0, "paragraphCount": 2**31, "revisionId": str(uuid.uuid4()), "finished": False}
    )

    assert resp.status_code == 422
    assert await _positions(db_session, novel_id) == []


def _place(paragraph_index: int, paragraph_count: int, revision_id: uuid.UUID, *, finished: bool) -> dict[str, object]:
    return {
        "paragraphIndex": paragraph_index,
        "paragraphCount": paragraph_count,
        "revisionId": str(revision_id),
        "finished": finished,
    }


async def test_detail_carries_each_episodes_own_reading_position_and_null_for_unread_ones(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """마지막으로 읽은 화가 아닌 화도 다시 열면 읽던 자리로 돌아가야 하므로, 목차의 화마다 그 화의 자리를 싣는다.
    다 읽은 표시는 한 번 참이면 앞부분을 다시 저장해도 참이고, 옛 칸(`finishedReading`·`lastRead`)도 그대로 나온다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first, second, third = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], episodes=3)
    before = (await db_client.get(f"/novels/{novel_id}")).json()
    first_revision, second_revision = uuid.uuid4(), uuid.uuid4()

    await db_client.put(
        f"/novels/{novel_id}/chapters/{first.id}/reading-position", json=_place(2, 3, first_revision, finished=True)
    )
    await db_client.put(
        f"/novels/{novel_id}/chapters/{first.id}/reading-position", json=_place(0, 3, first_revision, finished=False)
    )
    saved = await db_client.put(
        f"/novels/{novel_id}/chapters/{second.id}/reading-position",
        json=_place(1, 4, second_revision, finished=False),
    )
    after = (await db_client.get(f"/novels/{novel_id}")).json()

    assert saved.status_code == 204, saved.text
    assert [c["readingPosition"] for c in before["chapters"]] == [None, None, None]
    assert [c["id"] for c in after["chapters"]] == [str(first.id), str(second.id), str(third.id)]
    assert [c["readingPosition"] for c in after["chapters"]] == [
        _place(0, 3, first_revision, finished=True),
        _place(1, 4, second_revision, finished=False),
        None,
    ]
    assert [c["finishedReading"] for c in after["chapters"]] == [True, False, False]
    assert after["lastRead"]["chapterId"] in {str(first.id), str(second.id)}


async def test_deleting_the_last_batch_drops_its_episodes_and_keeps_the_positions_of_the_rest(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    (first,) = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1])
    (last,) = await _add_batch(db_session, novel_id, room, room.turns[2][0], room.turns[3][1])
    revision = uuid.uuid4()
    for chapter in (first, last):
        await db_client.put(
            f"/novels/{novel_id}/chapters/{chapter.id}/reading-position", json=_place(1, 3, revision, finished=False)
        )

    deleted = await db_client.delete(f"/novels/{novel_id}/batches/{last.batch_id}")
    detail = (await db_client.get(f"/novels/{novel_id}")).json()

    assert deleted.status_code == 204, deleted.text
    assert [(c["id"], c["readingPosition"]) for c in detail["chapters"]] == [
        (str(first.id), _place(1, 3, revision, finished=False))
    ]


async def _detail_query_count(db_client: httpx.AsyncClient, novel_id: uuid.UUID) -> int:
    # 첫 조회는 묶음 채우기 같은 한 번뿐인 일을 할 수 있어 한 번 읽어 둔 뒤 센다.
    assert (await db_client.get(f"/novels/{novel_id}")).status_code == 200
    with _count_queries() as count:
        resp = await db_client.get(f"/novels/{novel_id}")
    assert resp.status_code == 200
    return count()


async def test_detail_reads_reading_positions_without_a_query_per_episode(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화 수가 늘어도 상세의 쿼리 수는 같다 — 읽은 위치는 소설 단위로 한 번에 읽는다."""
    counts: list[int] = []
    for episodes in (1, 3):
        room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
        messages = await _room_messages(db_session, room.room_id)
        chapters = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], episodes=episodes)
        for chapter in chapters:
            await db_client.put(
                f"/novels/{novel_id}/chapters/{chapter.id}/reading-position",
                json=_place(0, 3, uuid.uuid4(), finished=False),
            )
        detail = (await db_client.get(f"/novels/{novel_id}")).json()
        assert sum(c["readingPosition"] is not None for c in detail["chapters"]) == episodes
        counts.append(await _detail_query_count(db_client, novel_id))

    assert counts[0] == counts[1]
