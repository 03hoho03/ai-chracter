"""방 기억 API — 사용자 노트와 현재 요약을 읽고 고친다.

깨지는 시나리오: 요약 편집이 그사이 새로 접힌 요약(또는 되감긴 요약)을 조용히 덮는다, 되돌리기가
한 단계를 넘어 반복된다, 거절한 요청이 버전만 올려 둬 멀쩡한 다음 편집까지 409가 된다, 노트 저장이
요약 버전을 올려 열린 요약 편집을 409로 만든다. 단언은 전부 컬럼 `select()`로 DB를 본다 — 앱과
테스트가 세션을 공유해 ORM 객체로는 커밋 여부를 알 수 없다.
"""

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoom, ChatRoomMemorySnapshot
from factories import (
    Room,
    SnapshotRow,
    _login_as,
    _make_user,
    _memory_version,
    _open_room,
    _plant_snapshot,
    _snapshots,
)


async def _note(db_session: AsyncSession, room: Room) -> str | None:
    note: str | None = await db_session.scalar(sa.select(ChatRoom.memory_note).where(ChatRoom.id == room.room_id))
    return note


async def _plant_user_edited_snapshot(db_session: AsyncSession, room: Room, *, turn: int) -> None:
    assistant = room.turns[turn][1]
    db_session.add(
        ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=assistant.created_at,
            cursor_message_id=assistant.id,
            summary_text="사용자가 고친 요약",
            previous_text="AI가 접은 요약",
            previous_source="auto",
            source="user",
        )
    )
    await db_session.commit()


async def test_new_room_has_an_empty_note_and_no_summary(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=0)

    resp = await db_client.get(f"/chat-rooms/{room.room_id}/memory")

    assert resp.status_code == 200
    assert resp.json() == {
        "note": "",
        "summary": None,
        "version": 0,
        "rolledBackAt": None,
        "limits": {"noteMaxLength": 1000, "summaryMaxLength": 1500},
    }


async def test_memory_shows_the_summary_with_the_latest_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    await _plant_snapshot(db_session, room, turn=10, text="앞 요약")
    await _plant_user_edited_snapshot(db_session, room, turn=20)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_version=7))
    await db_session.commit()

    body = (await db_client.get(f"/chat-rooms/{room.room_id}/memory")).json()

    assert body["summary"]["text"] == "사용자가 고친 요약"
    assert body["summary"]["source"] == "user"
    assert body["summary"]["canRevert"] is True
    assert body["version"] == 7


# ---- 노트 ----


async def test_note_is_trimmed_and_does_not_touch_the_summary_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=0)

    resp = await db_client.put(f"/chat-rooms/{room.room_id}/memory/note", json={"note": "  주인공은 고양이를 무서워한다\n"})

    assert resp.status_code == 200
    assert resp.json()["note"] == "주인공은 고양이를 무서워한다"
    assert await _note(db_session, room) == "주인공은 고양이를 무서워한다"
    assert await _memory_version(db_session, room) == 0


async def test_whitespace_only_note_is_saved_as_empty(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=0)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_note="예전 메모"))
    await db_session.commit()

    resp = await db_client.put(f"/chat-rooms/{room.room_id}/memory/note", json={"note": "  \n "})

    assert resp.status_code == 200
    assert await _note(db_session, room) == ""


async def test_note_length_limit_counts_after_trimming(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=0)

    at_limit = await db_client.put(f"/chat-rooms/{room.room_id}/memory/note", json={"note": f" {'가' * 1000} "})
    over_limit = await db_client.put(f"/chat-rooms/{room.room_id}/memory/note", json={"note": "가" * 1001})

    assert at_limit.status_code == 200
    assert over_limit.status_code == 422
    assert await _note(db_session, room) == "가" * 1000


async def test_clearing_the_note_returns_the_whole_memory(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=0)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_note="지울 메모"))
    await db_session.commit()

    resp = await db_client.delete(f"/chat-rooms/{room.room_id}/memory/note")

    assert resp.status_code == 200
    assert resp.json()["note"] == ""
    assert await _note(db_session, room) == ""
    assert await _memory_version(db_session, room) == 0


# ---- 요약 편집 ----


async def test_editing_the_summary_keeps_the_previous_text_for_one_revert(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    await _plant_snapshot(db_session, room, turn=10, text="앞 요약")
    await _plant_snapshot(db_session, room, turn=20, text="AI가 접은 요약")

    resp = await db_client.put(
        f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "  고친 요약 ", "version": 0}
    )

    assert resp.status_code == 200
    assert resp.json()["summary"]["canRevert"] is True
    assert resp.json()["version"] == 1
    front, current = await _snapshots(db_session, room)
    assert (front.summary_text, front.previous_text, front.source) == ("앞 요약", None, "auto")
    assert (current.summary_text, current.previous_text, current.source) == ("고친 요약", "AI가 접은 요약", "user")
    assert await _memory_version(db_session, room) == 1


async def test_editing_with_a_stale_version_is_rejected_without_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_snapshot(db_session, room, turn=10, text="AI가 접은 요약")
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_version=3))
    await db_session.commit()
    before = await _snapshots(db_session, room)

    resp = await db_client.put(
        f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "고친 요약", "version": 2}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MEMORY_VERSION_CONFLICT"
    assert await _snapshots(db_session, room) == before
    assert await _memory_version(db_session, room) == 3


async def test_editing_before_the_first_summary_is_rejected_without_bumping_the_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=5)

    resp = await db_client.put(
        f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "미리 적은 요약", "version": 0}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MEMORY_SUMMARY_NOT_READY"
    assert await _snapshots(db_session, room) == []
    assert await _memory_version(db_session, room) == 0


async def test_summary_longer_than_the_limit_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_snapshot(db_session, room, turn=10, text="AI가 접은 요약")

    resp = await db_client.put(
        f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "가" * 1501, "version": 0}
    )

    assert resp.status_code == 422


async def test_an_empty_summary_can_be_saved(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_snapshot(db_session, room, turn=10, text="AI가 접은 요약")

    resp = await db_client.put(f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "   ", "version": 0})

    assert resp.status_code == 200
    assert resp.json()["summary"]["text"] == ""
    assert resp.json()["summary"]["canRevert"] is True
    assert [row.summary_text for row in await _snapshots(db_session, room)] == [""]


# ---- 되돌리기 ----


async def test_revert_restores_the_text_once_and_then_has_nothing_left(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_snapshot(db_session, room, turn=10, text="AI가 접은 요약")
    edited = await db_client.put(
        f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "고친 요약", "version": 0}
    )
    assert edited.status_code == 200

    first = await db_client.post(f"/chat-rooms/{room.room_id}/memory/summary/revert", json={"version": 1})
    after_first = await _snapshots(db_session, room)
    second = await db_client.post(f"/chat-rooms/{room.room_id}/memory/summary/revert", json={"version": 2})

    assert first.status_code == 200
    assert first.json()["summary"]["text"] == "AI가 접은 요약"
    assert first.json()["summary"]["canRevert"] is False
    assert first.json()["version"] == 2
    assert [(row.summary_text, row.previous_text) for row in after_first] == [("AI가 접은 요약", None)]
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "MEMORY_NOTHING_TO_REVERT"
    assert await _snapshots(db_session, room) == after_first
    assert await _memory_version(db_session, room) == 2


async def _revert_buffer(db_session: AsyncSession, room: Room) -> list[tuple[str, str, str | None, str | None]]:
    rows = (
        await db_session.execute(
            sa.select(
                ChatRoomMemorySnapshot.summary_text,
                ChatRoomMemorySnapshot.source,
                ChatRoomMemorySnapshot.previous_text,
                ChatRoomMemorySnapshot.previous_source,
            ).where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
        )
    ).all()
    return [tuple(row) for row in rows]


async def test_reverting_an_edited_ai_summary_shows_it_as_the_ai_summary_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_snapshot(db_session, room, turn=10, text="AI가 접은 요약")
    edited = await db_client.put(
        f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": "고친 요약", "version": 0}
    )
    after_edit = await _revert_buffer(db_session, room)

    reverted = await db_client.post(f"/chat-rooms/{room.room_id}/memory/summary/revert", json={"version": 1})

    assert edited.status_code == 200
    assert after_edit == [("고친 요약", "user", "AI가 접은 요약", "auto")]
    assert reverted.status_code == 200
    assert reverted.json()["summary"]["source"] == "auto"
    assert await _revert_buffer(db_session, room) == [("AI가 접은 요약", "auto", None, None)]


async def test_reverting_a_second_edit_returns_to_the_users_first_edit(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_snapshot(db_session, room, turn=10, text="AI가 접은 요약")
    for version, text in [(0, "처음 고친 요약"), (1, "다시 고친 요약")]:
        resp = await db_client.put(
            f"/chat-rooms/{room.room_id}/memory/summary", json={"summary": text, "version": version}
        )
        assert resp.status_code == 200

    reverted = await db_client.post(f"/chat-rooms/{room.room_id}/memory/summary/revert", json={"version": 2})

    assert reverted.status_code == 200
    assert reverted.json()["summary"]["source"] == "user"
    assert await _revert_buffer(db_session, room) == [("처음 고친 요약", "user", None, None)]


async def test_a_summary_the_ai_folded_cannot_be_reverted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_snapshot(db_session, room, turn=10, text="AI가 접은 요약")

    resp = await db_client.post(f"/chat-rooms/{room.room_id}/memory/summary/revert", json={"version": 0})

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MEMORY_NOTHING_TO_REVERT"
    assert await _memory_version(db_session, room) == 0


async def test_revert_with_a_stale_version_is_rejected(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=20)
    await _plant_user_edited_snapshot(db_session, room, turn=20)
    before = await _snapshots(db_session, room)

    resp = await db_client.post(f"/chat-rooms/{room.room_id}/memory/summary/revert", json={"version": 5})

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MEMORY_VERSION_CONFLICT"
    assert await _snapshots(db_session, room) == before
    assert before == [
        SnapshotRow(
            cursor_created_at=room.turns[20][1].created_at,
            cursor_message_id=room.turns[20][1].id,
            summary_text="사용자가 고친 요약",
            previous_text="AI가 접은 요약",
            source="user",
        )
    ]


# ---- 소유권 ----


_MEMORY_REQUESTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/chat-rooms/{room_id}/memory", None),
    ("PUT", "/chat-rooms/{room_id}/memory/note", {"note": "남의 방"}),
    ("DELETE", "/chat-rooms/{room_id}/memory/note", None),
    ("PUT", "/chat-rooms/{room_id}/memory/summary", {"summary": "남의 방", "version": 0}),
    ("POST", "/chat-rooms/{room_id}/memory/summary/revert", {"version": 0}),
]


@pytest.mark.parametrize(
    ("method", "path", "body"), _MEMORY_REQUESTS, ids=[f"{method} {path}" for method, path, _ in _MEMORY_REQUESTS]
)
async def test_someone_elses_room_is_refused_and_a_missing_room_is_not_found(
    db_client: httpx.AsyncClient, db_session: AsyncSession, method: str, path: str, body: dict[str, object] | None
) -> None:
    room = await _open_room(db_client, db_session, turns=10)
    await _plant_user_edited_snapshot(db_session, room, turn=10)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(memory_note="주인 메모"))
    await db_session.commit()
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.commit()
    await _login_as(db_client, stranger.id)

    foreign = await db_client.request(method, path.format(room_id=room.room_id), json=body)
    missing = await db_client.request(method, path.format(room_id=uuid.uuid4()), json=body)

    assert foreign.status_code == 403
    assert missing.status_code == 404
    assert await _note(db_session, room) == "주인 메모"
    assert [row.summary_text for row in await _snapshots(db_session, room)] == ["사용자가 고친 요약"]
