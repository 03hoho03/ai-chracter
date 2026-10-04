"""방 화면이 작가 글의 `{{user}}`·`{{char}}` 를 바꿀 이름(방 응답)과, 서버가 직접 바꿔 내보내는 방 목록 미리보기.

이름은 방이 고른 대화 프로필 → 방이 고정한 버전의 작품 기본 이름 → "당신" 순서로 고른다. 작품 쪽 값은 최신 발행본이
아니라 방이 고정한 버전에서 읽어야 모델이 부른 이름과 화면의 이름이 갈리지 않는다.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    Content,
    ContentVersion,
    StartingSetup,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
    UserPersona,
)
from factories import _get_genre, _login_as, _make_published_character, _make_user, _story_with_setup


async def _set_default_user_name(db_session: AsyncSession, content: Content, name: str) -> None:
    assert content.current_published_version_id is not None
    detail = await db_session.get(StoryVersionDetail, content.current_published_version_id)
    assert detail is not None
    detail.default_user_name = name


async def _publish_renamed_version(db_session: AsyncSession, content: Content, setup: StartingSetup) -> None:
    """작품명·작품 기본 이름을 바꾼 새 발행본을 현재 발행본으로 만든다. 이미 있는 방은 옛 버전에 남는다."""
    version = ContentVersion(
        content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name="새 작품명",
            one_liner="한줄소개",
            prompt_template=StoryPromptTemplate.BASIC,
            default_user_name="용사",
        )
    )
    db_session.add(
        StartingSetup(
            entity_id=setup.entity_id,
            content_version_id=version.id,
            name=setup.name,
            prologue=setup.prologue,
            opening_message=setup.opening_message,
            order=setup.order,
        )
    )
    content.current_published_version_id = version.id
    await db_session.flush()


async def _make_default_persona(db_session: AsyncSession, user_id: uuid.UUID, name: str) -> UserPersona:
    persona = UserPersona(user_id=user_id, name=name)
    db_session.add(persona)
    await db_session.flush()
    user = await db_session.get(User, user_id)
    assert user is not None
    user.default_persona_id = persona.id
    return persona


async def _create_room(client: httpx.AsyncClient, content: Content, setup: StartingSetup | None) -> dict[str, Any]:
    body: dict[str, Any] = {"contentId": str(content.id), "contentType": "story" if setup else "character"}
    if setup is not None:
        body["startingSetupId"] = str(setup.id)
    resp = await client.post("/chat-rooms", json=body)
    assert resp.status_code == 201, resp.text
    room: dict[str, Any] = resp.json()
    return room


async def _previews(client: httpx.AsyncClient, content: Content) -> dict[str, tuple[str, str]]:
    """방 id → (작품 방 목록의 미리보기, 내 채팅목록의 미리보기)."""
    content_rooms = (await client.get("/chat-rooms", params={"contentId": str(content.id)})).json()
    my_rooms = {room["id"]: room["lastMessagePreview"] for room in (await client.get("/me/chat-rooms")).json()}
    return {room["id"]: (room["lastMessagePreview"], my_rooms[room["id"]]) for room in content_rooms}


async def test_room_response_names_come_from_room_persona_and_pinned_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    await _set_default_user_name(db_session, content, "모험가")
    await _make_default_persona(db_session, user_id, "지훈")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    await _publish_renamed_version(db_session, content, setup)
    await db_session.commit()

    resp = await db_client.get(f"/chat-rooms/{room['id']}")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["personaName"], body["defaultUserName"], body["contentName"]) == ("지훈", "모험가", "스토리")
    assert body["latestVersionAvailable"] is True


async def test_room_response_follows_persona_rename_and_delete(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필 이름은 방에 복사하지 않고 읽을 때 조인한다 — 고치거나 지우면 다음 조회부터 바뀐다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    persona = await _make_default_persona(db_session, user_id, "지훈")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    renamed = await db_client.put(f"/me/personas/{persona.id}", json={"name": "민수", "gender": None, "description": ""})
    after_rename = (await db_client.get(f"/chat-rooms/{room['id']}")).json()
    deleted = await db_client.delete(f"/me/personas/{persona.id}")
    after_delete = (await db_client.get(f"/chat-rooms/{room['id']}")).json()

    assert (renamed.status_code, deleted.status_code) == (200, 204)
    assert after_rename["personaName"] == "민수"
    assert (after_delete["personaId"], after_delete["personaName"]) == (None, None)


async def test_story_room_preview_uses_each_rooms_name_and_leaves_char_as_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방마다 프로필이 달라 목록 화면은 이름을 모른다 — 서버가 방마다 바꾼다. 프로필이 없으면 방이 고정한 버전의 작품
    기본 이름(새 발행본의 "용사" 가 아니다), 그것도 없으면 "당신". 스토리에는 `{{char}}` 가 가리킬 한 사람이 없어
    글자 그대로 둔다."""
    user_id, content, setup = await _story_with_setup(
        db_session, opening_message="{{user}}는 문을 연다. {{char}}가 있다."
    )
    await _make_default_persona(db_session, user_id, "지훈")
    await db_session.commit()
    await _login_as(db_client, user_id)
    with_persona = await _create_room(db_client, content, setup)
    without_persona = await _create_room(db_client, content, setup)
    cleared = await db_client.put(f"/chat-rooms/{without_persona['id']}/persona", json={"personaId": None})
    assert cleared.status_code == 200
    previews_without_default_name = await _previews(db_client, content)

    await _set_default_user_name(db_session, content, "모험가")
    await _publish_renamed_version(db_session, content, setup)
    await db_session.commit()
    previews = await _previews(db_client, content)

    assert previews_without_default_name[without_persona["id"]] == ("당신은 문을 연다. {{char}}가 있다.",) * 2
    assert previews[with_persona["id"]] == ("지훈은 문을 연다. {{char}}가 있다.",) * 2
    assert previews[without_persona["id"]] == ("모험가는 문을 연다. {{char}}가 있다.",) * 2


async def test_character_room_preview_replaces_char_with_character_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=genre.id, intro="{{char}}가 {{user}}를 반긴다."
    )
    assert content.current_published_version_id is not None
    detail = await db_session.get(CharacterVersionDetail, content.current_published_version_id)
    assert detail is not None
    detail.name = "하늘"
    await db_session.commit()
    await _login_as(db_client, user.id)
    room = await _create_room(db_client, content, None)

    previews = await _previews(db_client, content)
    room_body = (await db_client.get(f"/chat-rooms/{room['id']}")).json()

    assert previews[room["id"]] == ("하늘이 당신을 반긴다.",) * 2
    assert (room_body["personaName"], room_body["defaultUserName"], room_body["contentName"]) == (None, "", "하늘")


async def test_room_preview_leaves_user_message_as_sent(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """사용자 메시지는 화면이 보내기 전에 이름을 바꿔 저장한다. 그 뒤에 남은 `{{user}}` 는 사용자가 쓴 글자다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    await _make_default_persona(db_session, user_id, "지훈")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    db_session.add(
        ChatMessage(chat_room_id=uuid.UUID(room["id"]), role=ChatMessageRole.USER, content="{{user}}라고 쳤다")
    )
    await db_session.commit()

    previews = await _previews(db_client, content)

    assert previews[room["id"]] == ("{{user}}라고 쳤다",) * 2
