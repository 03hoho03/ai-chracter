"""스토리 채팅의 미디어 북 이미지 태그 — 첫 메시지 저장 형태, 화면 응답의 URL 맵, 모델로 가는 사본의 태그 제거.

빌더 글(시작상황·프롤로그·에필로그·등록 설명)의 태그는 이름 형태 `{{img::인물/장면}}` 이다. 첫 메시지는 방에
복사될 때 버전이 바뀌어도 유지되는 칸 id 형태로 저장돼, 방이 새 버전으로 옮겨 가면 새 버전의 같은 칸으로
해석된다. 화면 응답은 id 형태 글 + `{칸 id: {url, width, height}}` 맵을 싣고, 모델로 가는 프롬프트에는 두 형태
모두 실리지 않는다(모델이 태그를 흉내 내거나 이름이 문맥을 오염시킨다)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatJudgmentResult
from api.db.models import (
    Asset,
    AssetKind,
    AssetStatus,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentVersion,
    ContentVisibility,
    Ending,
    ModerationStatus,
    SituationalImage,
    StartingSetup,
    StoryEndingUnlock,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _add_epilogue_ending,
    _add_named_media_cell,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_published_story,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
    _story_with_setup,
)


def _id_tag(cell_id: uuid.UUID | str) -> str:
    return "{{img::" + str(cell_id) + "}}"


async def _publish_next_version(db_session: AsyncSession, content: Content, setup: StartingSetup) -> ContentVersion:
    """같은 시작설정(entity_id)을 담은 새 발행 버전을 현재 발행본으로 만든다. 미디어 북은 비어 있다."""
    version = ContentVersion(
        content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()
    # 실제 발행본은 언제나 버전 상세 행을 갖는다 — 방 응답이 그 행에서 작품명·작품 기본 이름을 읽는다.
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id, name="스토리", one_liner="한줄소개", prompt_template=StoryPromptTemplate.BASIC
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
    return version


async def _create_room(client: httpx.AsyncClient, content: Content, setup: StartingSetup) -> dict[str, Any]:
    resp = await client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _stored_messages(db_session: AsyncSession, room_id: str) -> list[str]:
    return list(
        await db_session.scalars(
            select(ChatMessage.content)
            .where(ChatMessage.chat_room_id == uuid.UUID(room_id))
            .order_by(ChatMessage.created_at)
        )
    )


class _RecordingLLMClient(LLMClient):
    """생성·판정 프롬프트를 모두 기록하고, 구조화 응답은 요청한 스키마의 것을 큐에서 순서대로 꺼낸다. 미디어
    북 칸이 있는 스토리 방은 스탯 판정과 칸 판정을 동시에 부르므로 호출 순서로 꺼내면 결과가 엇갈린다 — 칸
    판정은 큐에 없으면 "고른 칸 없음"으로 답한다. `judgment_prompts` 는 스키마별로 남는다."""

    def __init__(self, tokens: list[str], structured_results: list[Any] | None = None) -> None:
        self.tokens = tokens
        self._structured_results = list(structured_results or [])
        self.generation_prompts: list[str] = []
        self.judgment_prompts: list[str] = []
        self.judgment_prompts_by_schema: dict[Any, list[str]] = {}

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.generation_prompts.append(prompt)
        for token in self.tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.judgment_prompts.append(prompt)
        self.judgment_prompts_by_schema.setdefault(response_schema, []).append(prompt)
        for index, result in enumerate(self._structured_results):
            if isinstance(result, response_schema):
                return self._structured_results.pop(index)
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        raise AssertionError(f"큐에 {response_schema.__name__} 응답이 없다")


# ---- 첫 메시지 저장 형태 ---------------------------------------------------------------------------


async def test_opening_message_stores_media_tags_as_cell_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(
        db_session, opening_message="문이 열린다.\n\n{{img::민아/교실}}\n\n{{img::수아/교실}}\n\n민아가 웃는다."
    )
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)

    room = await _create_room(db_client, content, setup)

    # 없는 이름(수아)의 태그는 지운다 — 그 자리에 빈 줄이 겹쳐 쌓이지 않는다.
    expected = f"문이 열린다.\n\n{_id_tag(cell.entity_id)}\n\n민아가 웃는다."
    assert await _stored_messages(db_session, room["id"]) == [expected]
    assert room["messages"][0]["content"] == expected


async def test_opening_message_falls_back_to_prologue_tags_as_cell_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(
        db_session, opening_message=None, prologue="{{img::민아/교실}}\n프롤로그"
    )
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)

    room = await _create_room(db_client, content, setup)

    assert await _stored_messages(db_session, room["id"]) == [f"{_id_tag(cell.entity_id)}\n프롤로그"]


async def test_change_starting_setup_stores_opening_media_tags_as_cell_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="태그 없는 시작")
    assert content.current_published_version_id is not None
    other_setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="두 번째 만남",
        prologue="프롤로그",
        opening_message="{{img::민아/옥상}} 다시 만났다.",
        order=2,
    )
    db_session.add(other_setup)
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    resp = await db_client.post(
        f"/chat-rooms/{room['id']}/change-starting-setup", json={"startingSetupId": str(other_setup.id)}
    )

    assert resp.status_code == 201
    assert await _stored_messages(db_session, resp.json()["id"]) == [f"{_id_tag(cell.entity_id)} 다시 만났다."]


async def test_reset_chat_room_stores_opening_media_tags_as_cell_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    db_session.add(ChatMessage(chat_room_id=uuid.UUID(room["id"]), role=ChatMessageRole.USER, content="안녕"))
    await db_session.commit()

    resp = await db_client.post(f"/chat-rooms/{room['id']}/reset")

    assert resp.status_code == 200
    assert await _stored_messages(db_session, room["id"]) == [f"{_id_tag(cell.entity_id)} 시작"]
    assert set(resp.json()["mediaTagImages"]) == {str(cell.entity_id)}


# ---- 방 응답의 URL 맵 ---------------------------------------------------------------------------------


async def test_room_response_resolves_opening_media_tags_for_pinned_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    cell, asset = await _add_named_media_cell(
        db_session, content.current_published_version_id, user_id, "민아", "교실", size=(640, 480)
    )
    # 같은 버전의 다른 칸은 첫 메시지가 가리키지 않으므로 맵에 없다.
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    resp = await db_client.get(f"/chat-rooms/{room['id']}")

    assert resp.status_code == 200
    images = resp.json()["mediaTagImages"]
    assert list(images) == [str(cell.entity_id)]
    assert asset.storage_key in images[str(cell.entity_id)]["url"]
    assert (images[str(cell.entity_id)]["width"], images[str(cell.entity_id)]["height"]) == (640, 480)
    # 방을 만든 응답도 같은 맵을 싣는다.
    assert list(room["mediaTagImages"]) == [str(cell.entity_id)]


async def test_room_response_carries_null_size_for_asset_without_dimensions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}}")
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실", size=None)
    await db_session.commit()
    await _login_as(db_client, user_id)

    room = await _create_room(db_client, content, setup)

    image = room["mediaTagImages"][str(cell.entity_id)]
    assert (image["width"], image["height"]) == (None, None)


async def test_room_response_ignores_media_tags_typed_in_user_messages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """사용자가 칸 id 를 쳐 넣어도 그 칸의 원본 URL 을 받지 못한다 — 맵은 첫 메시지(작성자 글)만 본다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="태그 없는 시작")
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    db_session.add(
        ChatMessage(chat_room_id=uuid.UUID(room["id"]), role=ChatMessageRole.USER, content=_id_tag(cell.entity_id))
    )
    await db_session.commit()

    resp = await db_client.get(f"/chat-rooms/{room['id']}")

    assert resp.json()["mediaTagImages"] == {}


async def test_room_response_ignores_cells_in_model_reply_left_first_after_opening_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오프닝을 지우면 모델 응답이 첫 자리에 올 수 있다. 사용자가 시킨 대로 모델이 칸 id 태그를 따라 썼어도,
    작성자의 첫 메시지가 가리키지 않는 칸은 서명하지 않는다 — 아직 보지 못한 칸의 원본이 새는 길이다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    classroom, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    rooftop, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    db_session.add(
        ChatMessage(
            chat_room_id=uuid.UUID(room["id"]),
            role=ChatMessageRole.ASSISTANT,
            content=f"{_id_tag(rooftop.entity_id)} {_id_tag(classroom.entity_id)} 따라 썼다",
        )
    )
    await db_session.commit()

    deleted = await db_client.delete(f"/chat-rooms/{room['id']}/messages/{room['messages'][0]['id']}")
    resp = await db_client.get(f"/chat-rooms/{room['id']}")

    assert deleted.status_code == 204
    assert resp.json()["messages"][0]["role"] == "assistant"
    # 작성자 첫 메시지가 가리키는 칸(교실)만 남고, 응답이 끌어온 칸(옥상)은 빠진다.
    assert list(resp.json()["mediaTagImages"]) == [str(classroom.entity_id)]


async def test_room_response_ignores_user_message_left_first_after_opening_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    classroom, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    db_session.add(
        ChatMessage(
            chat_room_id=uuid.UUID(room["id"]), role=ChatMessageRole.USER, content=_id_tag(classroom.entity_id)
        )
    )
    await db_session.commit()

    await db_client.delete(f"/chat-rooms/{room['id']}/messages/{room['messages'][0]['id']}")
    resp = await db_client.get(f"/chat-rooms/{room['id']}")

    assert resp.json()["messages"][0]["role"] == "user"
    assert resp.json()["mediaTagImages"] == {}


async def test_pin_latest_version_resolves_opening_tag_to_new_version_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    cell, old_asset = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    # 새 발행본은 같은 칸(entity_id)의 그림을 바꿨다.
    new_version = await _publish_next_version(db_session, content, setup)
    _, new_asset = await _add_named_media_cell(
        db_session, new_version.id, user_id, "민아", "교실", entity_id=cell.entity_id, size=(100, 200)
    )
    await db_session.commit()

    before = (await db_client.get(f"/chat-rooms/{room['id']}")).json()["mediaTagImages"][str(cell.entity_id)]
    resp = await db_client.post(f"/chat-rooms/{room['id']}/pin-latest-version")

    assert resp.status_code == 200
    assert old_asset.storage_key in before["url"]
    after = resp.json()["mediaTagImages"][str(cell.entity_id)]
    assert new_asset.storage_key in after["url"]
    assert (after["width"], after["height"]) == (100, 200)


async def test_deleted_cell_tag_resolves_to_nothing(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    # 새 발행본에서 그 칸이 지워졌다.
    await _publish_next_version(db_session, content, setup)
    await db_session.commit()

    resp = await db_client.post(f"/chat-rooms/{room['id']}/pin-latest-version")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mediaTagImages"] == {}
    # 저장된 첫 메시지는 그대로다 — 화면이 그 자리를 빈칸으로 둔다.
    assert body["messages"][0]["content"] == f"{_id_tag(cell.entity_id)} 시작"


async def test_character_room_message_image_carries_no_dimensions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """캐릭터 상황별 이미지는 지금처럼 고정 비율 칸으로 그린다 — 크기 필드를 싣지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
        width=300,
        height=400,
    )
    db_session.add(asset)
    await db_session.flush()
    image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        image_asset_id=asset.id,
        trigger_condition="웃을 때",
        order=0,
    )
    db_session.add(image)
    await db_session.commit()
    await _login_as(db_client, user.id)
    room_resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    room_id = uuid.UUID(room_resp.json()["id"])
    db_session.add(
        ChatMessage(chat_room_id=room_id, role=ChatMessageRole.ASSISTANT, content="웃는다", image_id=image.entity_id)
    )
    await db_session.commit()

    resp = await db_client.get(f"/chat-rooms/{room_id}")

    message = resp.json()["messages"][-1]
    assert message["imageUrl"] is not None
    assert message.get("imageWidth") is None
    assert message.get("imageHeight") is None
    assert resp.json().get("mediaTagImages", {}) == {}


# ---- 엔딩 에필로그 -------------------------------------------------------------------------------------


async def test_room_snapshot_epilogue_strips_media_tags_without_url_map(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """스냅숏에는 아직 도달하지 않은 엔딩도 실린다 — 그 에필로그의 칸을 서명하면 미해금 원본이 샌다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="태그 없는 시작")
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await _add_epilogue_ending(db_session, setup, "끝났다.\n\n{{img::민아/옥상}}\n\n안녕.")
    await db_session.commit()
    await _login_as(db_client, user_id)

    room = await _create_room(db_client, content, setup)

    assert room["contentSnapshot"]["endings"][0]["epilogue"] == "끝났다.\n\n안녕."
    assert room["mediaTagImages"] == {}


async def test_ending_reached_event_carries_cell_id_epilogue_and_url_map(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    cell, asset = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await _add_epilogue_ending(db_session, setup, "끝났다.\n\n{{img::민아/옥상}}\n\n{{img::수아/옥상}}")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    fake = _RecordingLLMClient(
        tokens=["떠났다"],
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=True)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room['id']}/messages", json={"content": "떠난다"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    ending_event = next(event for event in events if event["type"] == "endingReached")
    assert ending_event["epilogue"] == f"끝났다.\n\n{_id_tag(cell.entity_id)}"
    assert list(ending_event["mediaTagImages"]) == [str(cell.entity_id)]
    assert asset.storage_key in ending_event["mediaTagImages"][str(cell.entity_id)]["url"]


async def test_ending_collection_carries_cell_id_epilogue_and_url_map_only_for_reached_endings(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    rooftop, asset = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    reached = await _add_epilogue_ending(db_session, setup, "{{img::민아/옥상}}\n끝.", order=1)
    await _add_epilogue_ending(db_session, setup, "{{img::민아/교실}}\n다른 끝.", order=2)
    db_session.add(
        StoryEndingUnlock(user_id=user_id, starting_setup_entity_id=setup.entity_id, ending_entity_id=reached.entity_id)
    )
    await db_session.commit()
    await _login_as(db_client, user_id)

    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")

    assert resp.status_code == 200
    first, second = resp.json()
    assert first["epilogue"] == f"{_id_tag(rooftop.entity_id)}\n끝."
    assert list(first["mediaTagImages"]) == [str(rooftop.entity_id)]
    assert asset.storage_key in first["mediaTagImages"][str(rooftop.entity_id)]["url"]
    # 도달하지 않은 엔딩은 에필로그도 맵도 없다.
    assert second["epilogue"] is None
    assert second.get("mediaTagImages", {}) == {}


# ---- 상세 응답 -----------------------------------------------------------------------------------------


async def test_content_detail_resolves_prologue_and_description_media_tags(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, _ = await _story_with_setup(
        db_session, opening_message=None, prologue="{{img::민아/교실}}\n교실에서 시작한다."
    )
    assert content.current_published_version_id is not None
    version = await db_session.get(ContentVersion, content.current_published_version_id)
    assert version is not None
    version.detail_description = "소개\n\n{{img::민아/옥상}}\n\n{{img::없는/칸}}"
    classroom, _ = await _add_named_media_cell(db_session, version.id, user_id, "민아", "교실")
    rooftop, rooftop_asset = await _add_named_media_cell(db_session, version.id, user_id, "민아", "옥상", size=(500, 700))
    await _add_named_media_cell(db_session, version.id, user_id, "민아", "복도")
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["detailDescription"] == f"소개\n\n{_id_tag(rooftop.entity_id)}"
    assert body["startingSetups"][0]["prologue"] == f"{_id_tag(classroom.entity_id)}\n교실에서 시작한다."
    assert set(body["mediaTagImages"]) == {str(classroom.entity_id), str(rooftop.entity_id)}
    rooftop_image = body["mediaTagImages"][str(rooftop.entity_id)]
    assert rooftop_asset.storage_key in rooftop_image["url"]
    assert (rooftop_image["width"], rooftop_image["height"]) == (500, 700)


async def test_content_detail_signs_media_tags_only_for_viewers_who_can_see_the_detail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상세 응답은 볼 수 없는 작품에도 나간다(화면이 "볼 수 없음"을 그린다). 그림 원본은 상세 본문을 그리는
    사람에게만 서명한다 — 비공개 작품은 작성자에게만, 이용제한 작품은 아무에게도."""
    user_id, content, _ = await _story_with_setup(db_session, opening_message=None, prologue="{{img::민아/교실}}")
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    content.visibility = ContentVisibility.PRIVATE
    other = _make_user()
    db_session.add(other)
    await db_session.commit()

    await _login_as(db_client, other.id)
    as_other = (await db_client.get(f"/contents/{content.id}")).json()
    await _login_as(db_client, user_id)
    as_owner = (await db_client.get(f"/contents/{content.id}")).json()
    content.visibility = ContentVisibility.PUBLIC
    content.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()
    restricted = (await db_client.get(f"/contents/{content.id}")).json()

    assert as_other["mediaTagImages"] == {}
    assert list(as_owner["mediaTagImages"]) == [str(cell.entity_id)]
    assert restricted["mediaTagImages"] == {}
    # 글은 칸 id 형태로 바뀐 채 나간다. 볼 수 없는 사람에게는 시작설정 자체가 나가지 않으므로 작성자 응답으로 본다.
    assert as_owner["startingSetups"][0]["prologue"] == _id_tag(cell.entity_id)


# ---- 모델로 가는 사본# ---- 모델로 가는 사본 ------------------------------------------------------------------------------------


async def test_story_generation_prompt_excludes_media_tags_from_prologue_and_history(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(
        db_session,
        opening_message="{{img::민아/교실}}\n민아가 손을 흔든다.",
        prologue="프롤로그 {{img::민아/옥상}}끝",
    )
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    fake = _RecordingLLMClient(tokens=["응답"], structured_results=[StatJudgmentResult(stat_changes=[])])
    _override_llm_client(fake)
    try:
        # 이번 턴 사용자 입력은 사용자 글이라 원문 그대로 모델에 간다.
        resp = await db_client.post(f"/chat-rooms/{room['id']}/messages", json={"content": "{{img::민아/교실}} 봐"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    [prompt] = fake.generation_prompts
    assert "프롤로그 끝" in prompt
    assert "민아가 손을 흔든다." in prompt
    assert prompt.count("{{img::") == 1
    assert "{{img::민아/교실}} 봐" in prompt


async def test_ending_judgment_turn_lines_exclude_media_tags(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}}\n시작한다.")
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await _add_epilogue_ending(db_session, setup, "끝")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    fake = _RecordingLLMClient(
        tokens=["응답"],
        structured_results=[StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=False)],
    )
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room['id']}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    (ending_prompt,) = fake.judgment_prompts_by_schema[EndingJudgmentResult]
    assert "시작한다." in ending_prompt
    assert "{{img::" not in ending_prompt


async def test_preview_prompt_excludes_name_form_media_tags(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    payload: dict[str, Any] = {
        "name": "이야기",
        "oneLiner": "한 줄",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [
            {
                "id": str(uuid.uuid4()),
                "name": "시작",
                "prologue": "프롤로그\n\n{{img::민아/옥상}}\n\n이어진다.",
                "openingMessage": "{{img::민아/교실}}\n민아가 손을 흔든다.",
                "playguide": None,
                "suggestedReplies": [],
                "statDefs": [],
                "endings": [],
            }
        ],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    session_resp = await db_client.post("/preview-sessions", json=payload)
    session_id = session_resp.json()["previewSessionId"]

    fake = _RecordingLLMClient(tokens=["응답"], structured_results=[StatJudgmentResult(stat_changes=[])])
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "안녕"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    [prompt] = fake.generation_prompts
    assert "프롤로그\n\n이어진다." in prompt
    assert "민아가 손을 흔든다." in prompt
    assert "{{img::" not in prompt


async def test_last_message_preview_excludes_media_tags(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}}\n시작한다.")
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)
    await _create_room(db_client, content, setup)

    content_rooms = await db_client.get("/chat-rooms", params={"contentId": str(content.id)})
    my_rooms = await db_client.get("/me/chat-rooms")

    assert [room["lastMessagePreview"] for room in content_rooms.json()] == ["시작한다."]
    assert [room["lastMessagePreview"] for room in my_rooms.json()] == ["시작한다."]

