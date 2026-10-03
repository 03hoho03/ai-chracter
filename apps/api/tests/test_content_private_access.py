"""처음 보는 사람에게 닫힌 작품(비공개·이용제한·삭제·미발행·작가 탈퇴)에는 작가가 아닌 사람이 새 대화방을 만들 수
없고, 상세 응답도 본문(소개·시작설정)을 주지 않는다. 링크 공개는 열려 있다.

이미 그 작품에 대화방이 있는 사람도 비공개가 된 뒤에는 새 방을 못 연다 — 새 방을 만드는 시작설정 변경도 막히고,
상세의 본문·시작설정도 받지 않는다. 기존 방에서 대화를 잇는 경로는 이 판정을 보지 않는다(이용제한·삭제는 다른 테스트
파일이 다루는 대로 기존 방에서도 막힌다)."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.db.models import ChatRoom, Content, ContentChatParticipant, ContentVisibility, ModerationStatus, StartingSetup
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_published_story,
    _make_user,
    _make_user_with_clover_lot,
    _override_llm_client,
)


async def _author_and_reader(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    author, reader = _make_user(), _make_user()
    db_session.add_all([author, reader])
    await db_session.flush()
    return author.id, reader.id


async def _character(db_session: AsyncSession, author_id: uuid.UUID) -> Content:
    genre = await _get_genre(db_session)
    return await _make_published_character(db_session, creator_user_id=author_id, genre_id=genre.id)


async def _story_with_two_setups(db_session: AsyncSession, author_id: uuid.UUID) -> tuple[Content, list[StartingSetup]]:
    genre = await _get_genre(db_session)
    story = await _make_published_story(db_session, creator_user_id=author_id, genre_id=genre.id)
    assert story.current_published_version_id is not None
    setups = [
        StartingSetup(
            entity_id=uuid.uuid4(),
            content_version_id=story.current_published_version_id,
            name=name,
            prologue=f"{name} 프롤로그",
            opening_message="안녕",
            order=order,
        )
        for order, name in enumerate(["첫 만남", "재회"], start=1)
    ]
    db_session.add_all(setups)
    await db_session.flush()
    return story, setups


async def _start(client: httpx.AsyncClient, content_id: uuid.UUID) -> httpx.Response:
    return await client.post("/chat-rooms", json={"contentId": str(content_id), "contentType": "character"})


_Close = Callable[[httpx.AsyncClient, AsyncSession, Content], Awaitable[None]]


async def _make_private(_client: httpx.AsyncClient, db_session: AsyncSession, content: Content) -> None:
    content.visibility = ContentVisibility.PRIVATE
    await db_session.commit()


async def _withdraw_author(client: httpx.AsyncClient, db_session: AsyncSession, content: Content) -> None:
    await _login_as(client, content.creator_user_id)
    assert (await client.delete("/me")).status_code == 204


async def _restrict(_client: httpx.AsyncClient, db_session: AsyncSession, content: Content) -> None:
    content.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()


async def _delete(_client: httpx.AsyncClient, db_session: AsyncSession, content: Content) -> None:
    content.moderation_status = ModerationStatus.DELETED
    await db_session.commit()


async def _unpublish(_client: httpx.AsyncClient, db_session: AsyncSession, content: Content) -> None:
    content.current_published_version_id = None
    await db_session.commit()


@pytest.mark.parametrize(
    ("close", "status_code", "detail"),
    [
        pytest.param(_make_private, 403, {"code": "CONTENT_PRIVATE"}, id="private"),
        pytest.param(_withdraw_author, 403, {"code": "CONTENT_PRIVATE"}, id="author-withdrawn"),
        pytest.param(_restrict, 403, {"code": "CONTENT_RESTRICTED"}, id="restricted"),
        pytest.param(_delete, 403, {"code": "CONTENT_RESTRICTED"}, id="deleted"),
        pytest.param(_unpublish, 404, "Content not found", id="unpublished"),
    ],
)
async def test_a_stranger_cannot_open_a_new_room_on_a_closed_content(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    close: _Close,
    status_code: int,
    detail: object,
) -> None:
    """거부는 방을 만들기 전에 난다 — 방도, 대화 상대 기록도, 대화수도 생기지 않는다."""
    author_id, reader_id = await _author_and_reader(db_session)
    content = await _character(db_session, author_id)
    await db_session.commit()
    await close(db_client, db_session, content)

    await _login_as(db_client, reader_id)
    resp = await _start(db_client, content.id)

    assert resp.status_code == status_code
    assert resp.json() == {"detail": detail}
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.user_id == reader_id)) == 0
    assert await db_session.scalar(
        sa.select(sa.func.count()).select_from(ContentChatParticipant).where(ContentChatParticipant.content_id == content.id)
    ) == 0
    assert await db_session.scalar(sa.select(Content.chat_count).where(Content.id == content.id)) == 0


async def test_the_author_can_open_a_new_room_on_own_private_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    author_id, _reader_id = await _author_and_reader(db_session)
    content = await _character(db_session, author_id)
    content.visibility = ContentVisibility.PRIVATE
    await db_session.commit()

    await _login_as(db_client, author_id)
    assert (await _start(db_client, content.id)).status_code == 201


@pytest.mark.parametrize(
    "visibility",
    [pytest.param(ContentVisibility.PUBLIC, id="public"), pytest.param(ContentVisibility.LINK, id="link")],
)
async def test_public_and_link_contents_are_open_to_new_readers(
    db_client: httpx.AsyncClient, db_session: AsyncSession, visibility: ContentVisibility
) -> None:
    """링크 공개는 목록에 실리지 않을 뿐 주소를 받은 사람이 대화를 시작하라고 있는 공개 범위다."""
    author_id, reader_id = await _author_and_reader(db_session)
    content = await _character(db_session, author_id)
    content.visibility = visibility
    await db_session.commit()

    await _login_as(db_client, reader_id)
    assert (await _start(db_client, content.id)).status_code == 201
    assert await db_session.scalar(sa.select(Content.chat_count).where(Content.id == content.id)) == 1


async def test_only_the_author_can_change_the_starting_setup_after_the_story_goes_private(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """시작설정 변경은 기존 방에서 부르지만 새 방을 만든다. 비공개 작품에서는 새 방 생성과 같이 작가 본인만 된다."""
    author_id, reader_id = await _author_and_reader(db_session)
    story, setups = await _story_with_two_setups(db_session, author_id)
    await db_session.commit()

    room_ids: dict[uuid.UUID, str] = {}
    for user_id in (author_id, reader_id):
        await _login_as(db_client, user_id)
        created = await db_client.post(
            "/chat-rooms", json={"contentId": str(story.id), "contentType": "story", "startingSetupId": str(setups[0].id)}
        )
        assert created.status_code == 201
        room_ids[user_id] = created.json()["id"]
    story.visibility = ContentVisibility.PRIVATE
    await db_session.commit()

    async def change_as(user_id: uuid.UUID) -> httpx.Response:
        await _login_as(db_client, user_id)
        return await db_client.post(
            f"/chat-rooms/{room_ids[user_id]}/change-starting-setup", json={"startingSetupId": str(setups[1].id)}
        )

    refused = await change_as(reader_id)
    assert refused.status_code == 403
    assert refused.json() == {"detail": {"code": "CONTENT_PRIVATE"}}
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(ChatRoom).where(ChatRoom.user_id == reader_id)) == 1
    assert (await change_as(author_id)).status_code == 201


async def test_detail_of_a_private_story_shows_its_body_only_to_the_author(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상세는 비공개 작품에도 200 으로 "볼 수 없음" 판정을 내준다. 그 응답에 소개·시작설정·프롤로그가 실리면 화면이
    가려도 주소만 알면 읽힌다. 그 작품에 방이 있는 독자도 받지 않는다 — 시작설정 목록을 쓰는 변경 창이 비공개 작품
    에서는 어차피 막힌다."""
    author_id, reader_id = await _author_and_reader(db_session)
    stranger = _make_user()
    db_session.add(stranger)
    story, setups = await _story_with_two_setups(db_session, author_id)
    await db_session.commit()
    await _login_as(db_client, reader_id)
    created = await db_client.post(
        "/chat-rooms", json={"contentId": str(story.id), "contentType": "story", "startingSetupId": str(setups[0].id)}
    )
    assert created.status_code == 201
    story.visibility = ContentVisibility.PRIVATE
    await db_session.commit()

    async def detail_as(user_id: uuid.UUID | None) -> dict[str, Any]:
        db_client.cookies.clear()
        if user_id is not None:
            await _login_as(db_client, user_id)
        resp = await db_client.get(f"/contents/{story.id}")
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        return body

    for hidden_from in (reader_id, stranger.id, None):
        body = await detail_as(hidden_from)
        assert body["detailDescription"] == ""
        assert body["startingSetups"] == []
        assert body["accessStatus"] == {"kind": "accessible", "visibility": "private"}

    body = await detail_as(author_id)
    assert body["detailDescription"] == "설명"
    assert [setup["name"] for setup in body["startingSetups"]] == ["첫 만남", "재회"]


async def test_a_reader_with_a_room_can_keep_chatting_after_the_content_goes_private(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """비공개 작품에서 막히는 것은 새 방(새 대화·시작설정 변경)뿐이다. 이미 대화한 독자는 자기 방에서 대화를 잇는다.
    전송·재생성·편집은 같은 방 의존성을 거치므로 전송 하나로 본다.

    빨개지는 조건: 그 방 의존성에 비공개 판정(작가만 허용)을 더하면 독자의 전송이 403 이 된다."""
    author = _make_user()
    db_session.add(author)
    reader = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    content = await _character(db_session, author.id)
    await db_session.commit()
    await _login_as(db_client, reader.id)
    created = await _start(db_client, content.id)
    assert created.status_code == 201
    content.visibility = ContentVisibility.PRIVATE
    await db_session.commit()

    _override_llm_client(_FakeLLMClient(tokens=["응"]))
    try:
        resp = await db_client.post(f"/chat-rooms/{created.json()['id']}/messages", json={"content": "계속하자"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
