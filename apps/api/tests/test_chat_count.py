"""작품의 대화수(`contents.chat_count`) — (작품, 사용자) 쌍당 한 번, 작가 본인 제외.

방을 만드는 두 경로(`POST /chat-rooms`, `POST /chat-rooms/{id}/change-starting-setup`)를 실제 API 로 부른다.
값은 언제나 컬럼 단위 `select` 로 읽는다 — `db_session.get(Content, …)` 는 셋업 때 올린 객체(값 0)를 identity map
에서 그대로 돌려줄 수 있어, 증가가 일어났는지와 무관하게 같은 값을 보여 줄 수 있다."""

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoom, Content, ContentChatParticipant, StartingSetup
from factories import (
    _get_genre,
    _login_as,
    _make_published_character,
    _make_published_story,
    _make_user,
)


async def _users(db_session: AsyncSession, count: int) -> list[uuid.UUID]:
    users = [_make_user() for _ in range(count)]
    db_session.add_all(users)
    await db_session.flush()
    return [user.id for user in users]


async def _character(db_session: AsyncSession, creator_user_id: uuid.UUID) -> Content:
    genre = await _get_genre(db_session)
    return await _make_published_character(db_session, creator_user_id=creator_user_id, genre_id=genre.id)


async def _chat_count(db_session: AsyncSession, content_id: uuid.UUID) -> int | None:
    value: int | None = await db_session.scalar(sa.select(Content.chat_count).where(Content.id == content_id))
    return value


async def _participants(db_session: AsyncSession, content_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db_session.scalars(
        sa.select(ContentChatParticipant.user_id).where(ContentChatParticipant.content_id == content_id)
    )
    return set(rows.all())


async def _start_character_chat(client: httpx.AsyncClient, user_id: uuid.UUID, content_id: uuid.UUID) -> str:
    await _login_as(client, user_id)
    resp = await client.post("/chat-rooms", json={"contentId": str(content_id), "contentType": "character"})
    assert resp.status_code == 201
    room_id: str = resp.json()["id"]
    return room_id


async def test_another_users_first_room_counts_once(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    author_id, reader_id = await _users(db_session, 2)
    content = await _character(db_session, author_id)
    await db_session.commit()

    await _start_character_chat(db_client, reader_id, content.id)

    assert await _chat_count(db_session, content.id) == 1
    assert await _participants(db_session, content.id) == {reader_id}


async def test_the_same_users_second_room_does_not_count_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """플레이는 누를 때마다 새 방이다 — 방 수가 아니라 사람 수를 센다."""
    author_id, reader_id = await _users(db_session, 2)
    content = await _character(db_session, author_id)
    await db_session.commit()

    await _start_character_chat(db_client, reader_id, content.id)
    await _start_character_chat(db_client, reader_id, content.id)

    assert await _chat_count(db_session, content.id) == 1


async def test_two_different_users_count_twice(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    author_id, first_id, second_id = await _users(db_session, 3)
    content = await _character(db_session, author_id)
    await db_session.commit()

    await _start_character_chat(db_client, first_id, content.id)
    await _start_character_chat(db_client, second_id, content.id)

    assert await _chat_count(db_session, content.id) == 2
    assert await _participants(db_session, content.id) == {first_id, second_id}


async def test_the_authors_own_room_is_not_counted(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    (author_id,) = await _users(db_session, 1)
    content = await _character(db_session, author_id)
    await db_session.commit()

    await _start_character_chat(db_client, author_id, content.id)

    assert await _chat_count(db_session, content.id) == 0
    assert await _participants(db_session, content.id) == set()


async def test_changing_the_starting_setup_does_not_count_the_same_user_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """시작설정 변경도 새 방을 만든다(같은 생성 함수). 이미 대화를 시작한 사람이므로 수는 그대로다."""
    author_id, reader_id = await _users(db_session, 2)
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=author_id, genre_id=genre.id)
    assert story.current_published_version_id is not None
    setups = [
        StartingSetup(
            entity_id=uuid.uuid4(),
            content_version_id=story.current_published_version_id,
            name=name,
            prologue="프롤로그",
            opening_message="안녕",
            order=order,
        )
        for order, name in enumerate(["첫 만남", "재회"], start=1)
    ]
    db_session.add_all(setups)
    await db_session.commit()

    await _login_as(db_client, reader_id)
    created = await db_client.post(
        "/chat-rooms",
        json={"contentId": str(story.id), "contentType": "story", "startingSetupId": str(setups[0].id)},
    )
    assert created.status_code == 201
    changed = await db_client.post(
        f"/chat-rooms/{created.json()['id']}/change-starting-setup", json={"startingSetupId": str(setups[1].id)}
    )
    assert changed.status_code == 201
    assert changed.json()["id"] != created.json()["id"]

    assert await _chat_count(db_session, story.id) == 1


async def test_changing_the_starting_setup_counts_a_user_who_was_not_yet_recorded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """시작설정 변경도 방을 만드는 경로라 처음 기록되는 사용자면 센다. 기록 없는 기존 방은 마이그레이션 적용과 새
    서버 기동 사이에 옛 코드가 만든 방에서 생길 수 있다 — 여기서는 생성자로 직접 넣어 그 상태를 만든다.

    빨개지는 조건: 증가 호출을 공용 방 생성 함수에서 `POST /chat-rooms` 쪽으로만 옮기면 이 경로는 0 으로 남는다."""
    author_id, reader_id = await _users(db_session, 2)
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=author_id, genre_id=genre.id)
    assert story.current_published_version_id is not None
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=story.current_published_version_id,
        name="첫 만남",
        prologue="프롤로그",
        opening_message="안녕",
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    unrecorded_room = ChatRoom(
        user_id=reader_id,
        content_id=story.id,
        content_version_id=story.current_published_version_id,
        starting_setup_entity_id=setup.entity_id,
    )
    db_session.add(unrecorded_room)
    await db_session.commit()

    await _login_as(db_client, reader_id)
    changed = await db_client.post(
        f"/chat-rooms/{unrecorded_room.id}/change-starting-setup", json={"startingSetupId": str(setup.id)}
    )
    assert changed.status_code == 201

    assert await _chat_count(db_session, story.id) == 1
    assert await _participants(db_session, story.id) == {reader_id}


async def test_deleting_the_room_keeps_the_count_and_recreating_does_not_add(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방은 하드 삭제다. 방으로 "이미 셌는가" 를 판정하면 지우고 다시 만들 때 또 오른다."""
    author_id, reader_id = await _users(db_session, 2)
    content = await _character(db_session, author_id)
    await db_session.commit()

    room_id = await _start_character_chat(db_client, reader_id, content.id)
    assert (await db_client.delete(f"/chat-rooms/{room_id}")).status_code == 204

    assert await _chat_count(db_session, content.id) == 1
    assert await _participants(db_session, content.id) == {reader_id}

    await _start_character_chat(db_client, reader_id, content.id)

    assert await _chat_count(db_session, content.id) == 1


async def test_withdrawal_erases_the_users_participation_but_keeps_the_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴 파기는 "이 사람이 이 작품과 대화했다" 는 기록을 지운다. 수는 이미 공개된 집계라 내리지 않는다."""
    author_id, reader_id, other_id = await _users(db_session, 3)
    content = await _character(db_session, author_id)
    await db_session.commit()

    await _start_character_chat(db_client, reader_id, content.id)
    await _start_character_chat(db_client, other_id, content.id)
    await _login_as(db_client, reader_id)
    assert (await db_client.delete("/me")).status_code == 204

    assert await _participants(db_session, content.id) == {other_id}
    assert await _chat_count(db_session, content.id) == 2


async def test_content_detail_reports_the_count(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    author_id, reader_id = await _users(db_session, 2)
    content = await _character(db_session, author_id)
    await db_session.commit()

    await _start_character_chat(db_client, reader_id, content.id)

    resp = await db_client.get(f"/contents/{content.id}")
    assert resp.status_code == 200
    assert resp.json()["chatCount"] == 1


async def test_popular_sort_ranks_a_content_up_once_someone_chats_with_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """인기순은 대화수를 첫 키로 쓴다. 대화가 없을 때 좋아요가 앞서던 작품을 대화 한 번이 뒤집어야 한다."""
    author_id, reader_id = await _users(db_session, 2)
    liked = await _character(db_session, author_id)
    liked.like_count = 10
    chatted = await _character(db_session, author_id)
    await db_session.commit()

    async def popular_ids() -> list[str]:
        resp = await db_client.get("/contents", params={"type": "character", "sort": "popular"})
        assert resp.status_code == 200
        return [item["id"] for item in resp.json()["items"] if item["id"] in {str(liked.id), str(chatted.id)}]

    assert await popular_ids() == [str(liked.id), str(chatted.id)]

    await _start_character_chat(db_client, reader_id, chatted.id)

    assert await popular_ids() == [str(chatted.id), str(liked.id)]


async def test_a_pair_can_be_recorded_only_once(db_session: AsyncSession) -> None:
    """복합 PK 가 "쌍당 한 번" 의 마지막 방어선이다(삽입은 충돌을 무시하는 형태). `alembic check` 는 복합 PK 구성을
    비교하지 않으므로 행위 테스트가 지킨다 — PK 가 사라지면 이 테스트가, `content_id` 한 칸으로 줄면 같은 쌍은 여전히
    충돌해 이 테스트는 통과하고 다른 사용자 둘을 세는 테스트가 잡는다."""
    author_id, reader_id = await _users(db_session, 2)
    content = await _character(db_session, author_id)
    db_session.add(ContentChatParticipant(content_id=content.id, user_id=reader_id))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(ContentChatParticipant(content_id=content.id, user_id=reader_id))
            await db_session.flush()
