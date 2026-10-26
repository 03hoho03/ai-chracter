"""소설로 만들 수 있는 내 채팅 목록(`GET /me/novel-sources`)과 작가용 소설 응답의 권리 칸.

목록은 내 방만 싣고, 방마다 그 방의 소설 id 와 새 소설 만들기 막힘 여부를 붙인다. 막힘 여부는 채팅방 단건 응답과 같은 판정이라
여기서는 한 계정의 방 여럿을 한 번에 불러도 방마다 단건 응답과 같은 값인지를 본다(방 하나짜리 경우의 갈래는
`test_novelize_permission.py` 가 단건과 목록을 짝으로 본다)."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import ChatMessage, ChatRoom, Content, Novel, User
from api.db.models.content import ModerationStatus
from api.novelize import source_router
from factories import Room, _allow_novelize, _lock_novel, _make_user, _novel_setup, _open_room

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")


async def _sources(db_client: httpx.AsyncClient, cursor: str | None = None) -> dict[str, object]:
    resp = await db_client.get("/me/novel-sources", params={} if cursor is None else {"cursor": cursor})
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


async def _items(db_client: httpx.AsyncClient) -> list[dict[str, object]]:
    items = (await _sources(db_client))["items"]
    assert isinstance(items, list)
    return items


async def _set_work(
    db_session: AsyncSession, room_id: uuid.UUID, *, permission: str, other_creator: bool, restricted: bool = False
) -> None:
    """방의 원작 허락을 바꾸고, `other_creator` 면 원작의 작가를 다른 회원으로 바꾼다(방 주인은 그대로)."""
    content_id = await db_session.scalar(sa.select(ChatRoom.content_id).where(ChatRoom.id == room_id))
    values: dict[str, object] = {"novel_permission": permission}
    if other_creator:
        creator = _make_user()
        db_session.add(creator)
        await db_session.flush()
        values["creator_user_id"] = creator.id
    if restricted:
        values["moderation_status"] = ModerationStatus.RESTRICTED
    await db_session.execute(sa.update(Content).where(Content.id == content_id).values(**values))
    await db_session.commit()


async def _single_blocked(db_client: httpx.AsyncClient, room_id: uuid.UUID) -> bool:
    resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert resp.status_code == 200, resp.text
    blocked = resp.json()["novelCreationBlocked"]
    assert isinstance(blocked, bool)
    return blocked


def _at(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


async def _more_rooms(db_client: httpx.AsyncClient, db_session: AsyncSession, first: Room, count: int) -> list[Room]:
    owner = await db_session.get_one(User, first.user_id)
    return [await _open_room(db_client, db_session, turns=1, user=owner) for _ in range(count)]


async def test_only_my_own_rooms_are_listed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남의 방은 싣지 않는다. 깨지는 시나리오: 사용자 조건이 빠져 남의 대화가 내 소설 재료로 보인다."""
    stranger = await _open_room(db_client, db_session, turns=1)
    await _allow_novelize(db_session, monkeypatch, stranger.user_id)
    mine = await _open_room(db_client, db_session, turns=1)
    await _allow_novelize(db_session, monkeypatch, mine.user_id)

    items = await _items(db_client)

    assert [item["id"] for item in items] == [str(mine.room_id)]
    assert items[0]["novelId"] is None
    assert items[0]["novelCreationBlocked"] is False


async def test_an_account_without_novelize_access_gets_the_novel_routes_403(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """소설화 허용이 없는 계정은 소설 라우트와 같은 403 이다. 깨지는 시나리오: 게이트가 빠져 허용 없는 계정이 소설화 진입
    화면의 재료를 받는다."""
    await _open_room(db_client, db_session, turns=1)
    monkeypatch.setattr(settings, "novelize_enabled", True)

    resp = await db_client.get("/me/novel-sources")
    novels = await db_client.get("/novels")

    assert novels.status_code == 403
    assert (resp.status_code, resp.json()) == (novels.status_code, novels.json())


async def test_a_room_with_a_novel_carries_its_id_and_a_hidden_novel_frees_the_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """방 하나에 소설 하나 — 소설이 있는 방은 그 id 를, 없는 방은 null 을 싣는다. 숨긴 소설은 방 칸이 비어 그 방이 다시
    null 이다. 깨지는 시나리오: 소설 id 가 다른 방에 붙거나, 숨긴 소설이 방을 계속 붙잡아 새 소설을 못 만드는 것처럼 보인다."""
    with_novel, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=1)
    [without_novel] = await _more_rooms(db_client, db_session, with_novel, 1)

    before = {item["id"]: item["novelId"] for item in await _items(db_client)}
    await db_session.execute(
        sa.update(Novel).where(Novel.id == novel_id).values(hidden_at=sa.func.now(), chat_room_id=None)
    )
    await db_session.commit()
    after = {item["id"]: item["novelId"] for item in await _items(db_client)}

    assert before == {str(with_novel.room_id): str(novel_id), str(without_novel.room_id): None}
    assert after == {str(with_novel.room_id): None, str(without_novel.room_id): None}


async def test_every_room_gets_the_same_blocked_flag_as_its_own_room_response(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """한 계정의 방 여럿을 한 번에 판정해도 방마다 단건 채팅방 응답과 같은 값이다 — 허락 셋, 내 원작과 남의 원작, 소설 없음·
    빈 소설·잠긴 소설, 이용제한 원작이 한 목록에 섞여 있다. 이용제한 원작의 방도 목록에 남는다(생성 경로가 막는다). 깨지는
    시나리오: 일괄 판정이 방끼리 원작·소설을 엇갈려 붙이거나, 단건과 다른 식으로 판정한다."""
    own_forbidden, _own_novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=1)
    locked_room, empty_room, other_forbidden, other_private, other_public, restricted = await _more_rooms(
        db_client, db_session, own_forbidden, 6
    )
    # 소설은 허락을 낮추기 전에 만든다(허용 안 함이면 만들 수 없다).
    created = await db_client.post(f"/chat-rooms/{locked_room.room_id}/novel")
    assert created.status_code == 201, created.text
    await _lock_novel(db_session, uuid.UUID(created.json()["id"]), permission="private")
    created = await db_client.post(f"/chat-rooms/{empty_room.room_id}/novel")
    assert created.status_code == 201, created.text

    await _set_work(db_session, own_forbidden.room_id, permission="forbidden", other_creator=False)
    await _set_work(db_session, locked_room.room_id, permission="forbidden", other_creator=True)
    await _set_work(db_session, empty_room.room_id, permission="forbidden", other_creator=True)
    await _set_work(db_session, other_forbidden.room_id, permission="forbidden", other_creator=True)
    await _set_work(db_session, other_private.room_id, permission="private", other_creator=True)
    await _set_work(db_session, other_public.room_id, permission="public", other_creator=True)
    await _set_work(db_session, restricted.room_id, permission="forbidden", other_creator=True, restricted=True)

    listed = {item["id"]: item["novelCreationBlocked"] for item in await _items(db_client)}
    rooms = [own_forbidden, locked_room, empty_room, other_forbidden, other_private, other_public, restricted]
    single = {str(room.room_id): await _single_blocked(db_client, room.room_id) for room in rooms}

    assert listed == single
    # 갈래가 실제로 양쪽 값을 다 낸다 — 한쪽 값만 나오면 위 비교가 아무것도 가르지 못한다.
    assert single == {
        str(own_forbidden.room_id): False,
        str(locked_room.room_id): False,
        str(empty_room.room_id): True,
        str(other_forbidden.room_id): True,
        str(other_private.room_id): False,
        str(other_public.room_id): False,
        str(restricted.room_id): True,
    }


async def test_pages_walk_every_room_once_in_the_chat_list_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """커서로 끝까지 넘기면 모든 방이 한 번씩, 내 채팅 목록과 같은 순서로 나온다. 활동 시각과 생성 시각이 모두 같은 방들이
    페이지 경계에 걸쳐도 id 로 갈라 겹치거나 빠지지 않는다. 깨지는 시나리오: 커서가 정렬 키 일부만 담아 동점 방이 두 페이지에
    걸리면 한 방이 두 번 나오거나 사라진다."""
    monkeypatch.setattr(source_router, "NOVEL_SOURCE_PAGE_SIZE", 2)
    first = await _open_room(db_client, db_session, turns=1)
    rooms = [first, *await _more_rooms(db_client, db_session, first, 4)]
    await _allow_novelize(db_session, monkeypatch, first.user_id)
    same = datetime.now(UTC) - timedelta(hours=1)
    room_ids = [room.room_id for room in rooms]
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id.in_(room_ids)).values(created_at=same))
    await db_session.execute(
        sa.update(ChatMessage).where(ChatMessage.chat_room_id.in_(room_ids)).values(created_at=same)
    )
    await db_session.commit()

    expected = [item["id"] for item in (await db_client.get("/me/chat-rooms")).json()]
    seen: list[object] = []
    cursor: str | None = None
    for _ in range(len(rooms) + 1):
        page = await _sources(db_client, cursor)
        items = page["items"]
        assert isinstance(items, list) and len(items) <= 2
        seen += [item["id"] for item in items]
        next_cursor = page["nextCursor"]
        assert next_cursor is None or isinstance(next_cursor, str)
        cursor = next_cursor
        if cursor is None:
            break

    assert len(expected) == len(rooms)
    assert seen == expected


def _forged_cursor(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode()


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param("@@@not-base64@@@", id="broken_base64"),
        pytest.param(
            _forged_cursor(json.dumps(["2026-01-01T00:00:00+00:00", str(uuid.uuid4())]).encode()),
            id="wrong_element_count",
        ),
        pytest.param(
            _forged_cursor(json.dumps(["2026-01-01T00:00:00", "2026-01-01T00:00:00", str(uuid.uuid4())]).encode()),
            id="time_without_offset",
        ),
    ],
)
async def test_a_forged_cursor_is_rejected_with_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, cursor: str
) -> None:
    """서버가 내준 적 없는 커서는 모양이 어떻게 틀렸든 같은 422 와 커서 오류 코드다. 방이 하나 있어야 커서를 방의 정렬 키와
    비교하는 데까지 간다. 깨지는 시나리오: 오프셋 없는 시각은 해석은 되지만 DB 의 시간대 있는 시각과 비교하다 터져 500 이
    나간다."""
    room = await _open_room(db_client, db_session, turns=1)
    await _allow_novelize(db_session, monkeypatch, room.user_id)

    resp = await db_client.get("/me/novel-sources", params={"cursor": cursor})

    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "NOVEL_SOURCE_CURSOR_INVALID")


async def test_owner_novel_response_carries_the_rights_lock_columns(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """작가용 소설 응답의 권리 칸 넷은 소설 행의 값이다 — 잠기기 전에는 모두 null, 잠근 뒤에는 행에 적힌 시각·허락 사본.
    깨지는 시나리오: 칸이 다른 칸(집필권·연재권)을 엇갈려 읽거나 늘 null 이라 화면이 권리 상태를 잘못 그린다."""
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=1)
    fields = ("writingLockedAt", "writingLockPermission", "serialLockedAt", "serialLockPermission")

    before = (await db_client.get(f"/novels/{novel_id}")).json()
    writing_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    serial_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    await _lock_novel(db_session, novel_id, permission="private", locked_at=writing_at)
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id == novel_id)
        .values(serial_locked_at=serial_at, serial_lock_permission="public", serial_lock_source="first_publish")
    )
    await db_session.commit()
    after = (await db_client.get(f"/novels/{novel_id}")).json()

    assert {field: before[field] for field in fields} == dict.fromkeys(fields)
    assert (
        _at(after["writingLockedAt"]),
        after["writingLockPermission"],
        _at(after["serialLockedAt"]),
        after["serialLockPermission"],
    ) == (writing_at, "private", serial_at, "public")
