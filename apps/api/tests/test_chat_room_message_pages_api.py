"""긴 방을 꼬리부터 나눠 읽는 방 조회 — `GET /chat-rooms/{id}?messageLimit=` 의 꼬리 창과
`GET /chat-rooms/{id}/messages?before=` 의 위로 불러오기.

천 턴짜리 방도 진입할 때 메시지 전부를 받으면 응답이 수 MB 가 된다. 화면은 최근 몇십 개만 받고 위로 올라갈 때
그 앞을 이어 받는다. 이어 붙인 결과가 전량 조회와 한 메시지도 다르지 않아야 하므로, 페이지 경계는 메시지 정렬과
같은 `(created_at, id)` 로 자른다 — `created_at` 이 같은 메시지가 경계에 걸려도 빠지거나 겹치지 않는다."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatMessage, ChatMessageRole, Content, SituationalImage, StartingSetup
from factories import (
    _add_named_media_cell,
    _get_genre,
    _login_as,
    _make_asset,
    _make_published_character,
    _make_user,
    _story_with_setup,
)

# 시험 방 길이와 창 크기. 120 = 꼬리 창 50 두 번 + 나머지 20 이라 마지막 페이지가 창보다 짧다.
_MESSAGE_COUNT = 120
_WINDOW = 50


async def _create_story_room(client: httpx.AsyncClient, content: Content, setup: StartingSetup) -> uuid.UUID:
    resp = await client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _create_character_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[uuid.UUID, uuid.UUID, Content]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    assert resp.status_code == 201, resp.text
    return user.id, uuid.UUID(resp.json()["id"]), content


async def _add_turns(
    db_session: AsyncSession,
    room_id: uuid.UUID,
    count: int,
    *,
    same_time: bool = False,
    image_ids: dict[int, uuid.UUID] | None = None,
) -> list[str]:
    """오프닝 뒤에 사용자·모델 메시지를 번갈아 `count` 개 넣고 넣은 순서대로 id 를 돌려준다. `same_time` 이면
    전부 같은 `created_at` 이라 순서는 id 로만 갈린다. `image_ids` 는 {넣는 순번: 그 메시지의 image_id}."""
    base = datetime.now(UTC) + timedelta(minutes=1)
    rows = [
        ChatMessage(
            id=uuid.uuid4(),
            chat_room_id=room_id,
            role=ChatMessageRole.USER if index % 2 == 0 else ChatMessageRole.ASSISTANT,
            content=f"메시지 {index}",
            created_at=base if same_time else base + timedelta(seconds=index),
            image_id=(image_ids or {}).get(index),
        )
        for index in range(count)
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return [str(row.id) for row in rows]


def _ids(messages: list[dict[str, Any]]) -> list[str]:
    return [message["id"] for message in messages]


async def _all_message_ids(client: httpx.AsyncClient, room_id: uuid.UUID) -> list[str]:
    resp = await client.get(f"/chat-rooms/{room_id}")
    assert resp.status_code == 200, resp.text
    return _ids(resp.json()["messages"])


async def test_room_with_message_limit_returns_only_newest_messages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, room_id, _ = await _create_character_room(db_client, db_session)
    added = await _add_turns(db_session, room_id, _MESSAGE_COUNT)

    resp = await db_client.get(f"/chat-rooms/{room_id}", params={"messageLimit": _WINDOW})

    assert resp.status_code == 200
    body = resp.json()
    # 최신 50개를 오래된 것부터 — 전량 조회와 같은 방향이라 화면이 그대로 이어 그린다.
    assert _ids(body["messages"]) == added[-_WINDOW:]
    assert body["hasMoreMessagesBefore"] is True


async def test_room_without_message_limit_returns_every_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """파라미터를 모르는 옛 화면이 받는 응답은 지금과 같아야 한다 — 서버와 화면을 어느 순서로 배포해도 된다."""
    _, room_id, _ = await _create_character_room(db_client, db_session)
    added = await _add_turns(db_session, room_id, _MESSAGE_COUNT)

    resp = await db_client.get(f"/chat-rooms/{room_id}")

    body = resp.json()
    assert len(body["messages"]) == _MESSAGE_COUNT + 1  # 오프닝 포함
    assert _ids(body["messages"])[1:] == added
    assert body["hasMoreMessagesBefore"] is False


async def test_room_with_message_limit_covering_the_room_reports_nothing_before(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """창이 방 전체와 딱 맞으면 앞에 더 없다 — 하나 더 읽어 보고 판단하는 경계."""
    _, room_id, _ = await _create_character_room(db_client, db_session)
    await _add_turns(db_session, room_id, _WINDOW - 1)  # 오프닝 포함 정확히 50개

    body = (await db_client.get(f"/chat-rooms/{room_id}", params={"messageLimit": _WINDOW})).json()

    assert len(body["messages"]) == _WINDOW
    assert body["hasMoreMessagesBefore"] is False


async def test_message_pages_before_cursor_walk_back_to_the_opening(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, room_id, _ = await _create_character_room(db_client, db_session)
    await _add_turns(db_session, room_id, _MESSAGE_COUNT)
    everything = await _all_message_ids(db_client, room_id)
    tail = (await db_client.get(f"/chat-rooms/{room_id}", params={"messageLimit": _WINDOW})).json()["messages"]

    first = await db_client.get(
        f"/chat-rooms/{room_id}/messages", params={"before": tail[0]["id"], "limit": _WINDOW}
    )

    assert first.status_code == 200
    page = first.json()
    assert _ids(page["messages"]) == everything[-2 * _WINDOW : -_WINDOW]
    assert page["hasMoreBefore"] is True

    last = (
        await db_client.get(
            f"/chat-rooms/{room_id}/messages", params={"before": page["messages"][0]["id"], "limit": _WINDOW}
        )
    ).json()
    # 남은 21개(오프닝 + 20)가 한 페이지에 다 오고 그 앞은 없다.
    assert _ids(last["messages"]) == everything[: -2 * _WINDOW]
    assert last["hasMoreBefore"] is False


async def test_message_pages_split_messages_sharing_a_timestamp_without_gaps_or_repeats(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """한 트랜잭션에 넣은 메시지처럼 `created_at` 이 같으면 순서는 id 가 정한다. 페이지 경계가 그 한가운데를
    지나도 이어 붙인 결과가 전량 조회와 같아야 한다 — 정렬에서 id 가 빠지면 같은 시각 메시지 중 무엇이 창에
    드는지가 매번 달라져 빠지거나 두 번 나온다."""
    _, room_id, _ = await _create_character_room(db_client, db_session)
    added = await _add_turns(db_session, room_id, _MESSAGE_COUNT, same_time=True)
    everything = await _all_message_ids(db_client, room_id)
    # 전량 조회도 같은 시각 메시지를 id 순으로 둔다(오프닝은 그보다 이르다).
    assert everything[1:] == sorted(added, key=uuid.UUID)

    body = (await db_client.get(f"/chat-rooms/{room_id}", params={"messageLimit": _WINDOW})).json()
    collected = _ids(body["messages"])
    has_more = body["hasMoreMessagesBefore"]
    while has_more:
        page = (
            await db_client.get(
                f"/chat-rooms/{room_id}/messages", params={"before": collected[0], "limit": _WINDOW}
            )
        ).json()
        collected = _ids(page["messages"]) + collected
        has_more = page["hasMoreBefore"]

    assert collected == everything


async def test_message_pages_of_someone_elses_room_are_forbidden(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, room_id, _ = await _create_character_room(db_client, db_session)
    added = await _add_turns(db_session, room_id, 3)
    stranger = _make_user()
    db_session.add(stranger)
    await db_session.commit()
    await _login_as(db_client, stranger.id)

    resp = await db_client.get(f"/chat-rooms/{room_id}/messages", params={"before": added[-1], "limit": _WINDOW})

    assert resp.status_code == 403


async def test_message_pages_reject_a_cursor_from_another_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """다른 방(내 방이어도)의 메시지 id 를 커서로 주면 그 시각으로 이 방을 자르지 않고 404 다."""
    _, room_id, content = await _create_character_room(db_client, db_session)
    await _add_turns(db_session, room_id, 3)
    other = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    other_room_id = uuid.UUID(other.json()["id"])
    other_ids = await _add_turns(db_session, other_room_id, 3)

    foreign = await db_client.get(
        f"/chat-rooms/{room_id}/messages", params={"before": other_ids[-1], "limit": _WINDOW}
    )
    missing = await db_client.get(
        f"/chat-rooms/{room_id}/messages", params={"before": str(uuid.uuid4()), "limit": _WINDOW}
    )

    assert foreign.status_code == 404
    assert missing.status_code == 404


async def test_story_room_tail_window_keeps_opening_media_tag_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오프닝 그림 맵은 꼬리 창이 아니라 방의 첫 메시지로 계산한다 — 긴 방에서 창에 오프닝이 없어도, 위로
    불러와 오프닝에 닿았을 때 그림이 그려져야 한다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    cell, asset = await _add_named_media_cell(
        db_session, content.current_published_version_id, user_id, "민아", "교실", size=(640, 480)
    )
    await db_session.commit()
    await _login_as(db_client, user_id)
    room_id = await _create_story_room(db_client, content, setup)
    await _add_turns(db_session, room_id, _MESSAGE_COUNT)

    full = (await db_client.get(f"/chat-rooms/{room_id}")).json()
    windowed = (await db_client.get(f"/chat-rooms/{room_id}", params={"messageLimit": _WINDOW})).json()

    assert list(full["mediaTagImages"]) == [str(cell.entity_id)]
    assert asset.storage_key in full["mediaTagImages"][str(cell.entity_id)]["url"]
    assert windowed["mediaTagImages"] == full["mediaTagImages"]


async def test_message_pages_sign_media_book_cell_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """위로 불러온 메시지의 칸 그림도 진입 응답과 같은 URL·크기로 온다 — 안 그러면 위쪽 그림이 전부 빈다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    cell, asset = await _add_named_media_cell(
        db_session, content.current_published_version_id, user_id, "민아", "교실", size=(640, 480)
    )
    await db_session.commit()
    await _login_as(db_client, user_id)
    room_id = await _create_story_room(db_client, content, setup)
    added = await _add_turns(db_session, room_id, _MESSAGE_COUNT, image_ids={1: cell.entity_id})

    page = (
        await db_client.get(f"/chat-rooms/{room_id}/messages", params={"before": added[10], "limit": _WINDOW})
    ).json()

    with_image = next(message for message in page["messages"] if message["id"] == added[1])
    assert with_image["imageId"] == str(cell.entity_id)
    assert asset.storage_key in with_image["imageUrl"]
    assert (with_image["imageWidth"], with_image["imageHeight"]) == (640, 480)


async def test_message_pages_sign_character_situational_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, room_id, content = await _create_character_room(db_client, db_session)
    assert content.current_published_version_id is not None
    image_asset = await _make_asset(db_session, owner_user_id=user_id)
    image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        image_asset_id=image_asset.id,
        trigger_condition="조건",
        order=0,
    )
    db_session.add(image)
    await db_session.commit()
    added = await _add_turns(db_session, room_id, _MESSAGE_COUNT, image_ids={1: image.entity_id})

    page = (
        await db_client.get(f"/chat-rooms/{room_id}/messages", params={"before": added[10], "limit": _WINDOW})
    ).json()

    with_image = next(message for message in page["messages"] if message["id"] == added[1])
    assert with_image["imageId"] == str(image.entity_id)
    assert image_asset.storage_key in with_image["imageUrl"]


async def test_pin_latest_version_keeps_the_depth_the_screen_asked_for(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """버전 고정 응답은 화면 캐시를 통째로 바꾼다. 화면이 위로 불러 둔 깊이를 넘기면 그만큼 돌려줘야 불러 둔
    메시지가 응답으로 잘리지 않는다."""
    _, room_id, _ = await _create_character_room(db_client, db_session)
    added = await _add_turns(db_session, room_id, _MESSAGE_COUNT)

    resp = await db_client.post(f"/chat-rooms/{room_id}/pin-latest-version", params={"messageLimit": 70})

    assert resp.status_code == 200
    body = resp.json()
    assert _ids(body["messages"]) == added[-70:]
    assert body["hasMoreMessagesBefore"] is True
