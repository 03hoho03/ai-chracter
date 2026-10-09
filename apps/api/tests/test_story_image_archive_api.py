"""스토리 미디어 북 보관함 — 해금 기록(첫 메시지·에필로그)과 보관함 목록.

보관함은 현재 발행본의 칸 중 사용자가 채팅에서 볼 수 있는 길이 있는 칸만 싣는다. 본 칸(해금 기록이 있는
칸)은 원본 썸네일, 아직 못 본 칸은 블러본 썸네일과 해금 힌트다 — 못 본 칸의 원본 키는 서명하지 않는다.
판정 노출의 기록은 `test_chat_media_judgment_api.py` 가 다룬다."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.core.s3 import build_thumbnail_key
from api.db.models import (
    Asset,
    AssetKind,
    AssetStatus,
    ChatRoom,
    Content,
    ContentVersion,
    ContentVisibility,
    MediaBookCell,
    ModerationStatus,
    StartingSetup,
    StoryMediaExposure,
)
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _add_epilogue_ending,
    _add_named_media_cell,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
    _story_with_setup,
)


async def _unlocked_cells(db_session: AsyncSession, user_id: uuid.UUID, content: Content) -> list[uuid.UUID]:
    return list(
        await db_session.scalars(
            select(StoryMediaExposure.cell_entity_id).where(
                StoryMediaExposure.user_id == user_id, StoryMediaExposure.content_id == content.id
            )
        )
    )


async def _create_room(client: httpx.AsyncClient, content: Content, setup: StartingSetup) -> dict[str, Any]:
    resp = await client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _add_blurred_cell(
    db_session: AsyncSession,
    version_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    person: str,
    scene: str,
    *,
    exclude_from_chat: bool = False,
    unlock_hint: str = "",
) -> tuple[MediaBookCell, Asset, Asset]:
    """발행이 블러본을 채운 칸 — 원본과 블러본 자산을 함께 돌려준다."""
    cell, original = await _add_named_media_cell(
        db_session, version_id, owner_user_id, person, scene, exclude_from_chat=exclude_from_chat
    )
    blurred = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/situational-image-blurred/{uuid.uuid4()}.png",
        kind=AssetKind.BLURRED,
        status=AssetStatus.READY,
        width=original.width,
        height=original.height,
    )
    db_session.add(blurred)
    await db_session.flush()
    cell.blurred_asset_id = blurred.id
    cell.unlock_hint = unlock_hint
    await db_session.flush()
    return cell, original, blurred


class _EndingLLMClient(LLMClient):
    """엔딩에 도달하는 한 턴 — 스탯 판정은 변화 없음, 엔딩 판정은 충족, 칸 판정은 고른 칸 없음."""

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "떠났다"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        results: dict[Any, Any] = {
            StatRuleJudgmentResult: StatRuleJudgmentResult(fired_rule_ids=[]),
            EndingJudgmentResult: EndingJudgmentResult(triggered=True),
            ImageMatchJudgmentResult: ImageMatchJudgmentResult(matched_image_entity_id=None),
        }
        return results[response_schema]


# ---- 해금 기록 -------------------------------------------------------------------------------------------


async def test_opening_media_tags_unlock_cells(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """첫 메시지에 나온 칸은 방을 만든 순간 본 것이다. 첫 메시지에 없는 칸은 해금되지 않는다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await db_session.commit()
    await _login_as(db_client, user_id)

    await _create_room(db_client, content, setup)

    assert await _unlocked_cells(db_session, user_id, content) == [cell.entity_id]


async def test_change_starting_setup_unlocks_new_opening_cells(
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
    assert await _unlocked_cells(db_session, user_id, content) == []

    resp = await db_client.post(
        f"/chat-rooms/{room['id']}/change-starting-setup", json={"startingSetupId": str(other_setup.id)}
    )

    assert resp.status_code == 201
    assert await _unlocked_cells(db_session, user_id, content) == [cell.entity_id]


async def test_reset_chat_room_keeps_opening_unlock_idempotent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초기화도 첫 메시지를 다시 넣으므로 해금을 기록한다. 이미 있는 기록과 겹쳐도 실패하지 않고 한 행이다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{img::민아/교실}} 시작")
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)
    await db_session.execute(delete(StoryMediaExposure).where(StoryMediaExposure.user_id == user_id))
    await db_session.commit()

    first = await db_client.post(f"/chat-rooms/{room['id']}/reset")
    assert first.status_code == 200
    assert await _unlocked_cells(db_session, user_id, content) == [cell.entity_id]

    second = await db_client.post(f"/chat-rooms/{room['id']}/reset")
    assert second.status_code == 200
    assert await _unlocked_cells(db_session, user_id, content) == [cell.entity_id]


async def test_epilogue_media_tags_unlock_cells_on_ending_reached(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """도달한 엔딩의 에필로그에 나온 칸만 해금한다 — 다른 엔딩의 에필로그 칸은 그대로 잠겨 있다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    rooftop, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "옥상")
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await _add_epilogue_ending(db_session, setup, "끝났다.\n\n{{img::민아/옥상}}", order=1)
    await _add_epilogue_ending(db_session, setup, "{{img::민아/교실}} 다른 끝.", order=2)
    await db_session.commit()
    await _login_as(db_client, user_id)
    room = await _create_room(db_client, content, setup)

    _override_llm_client(_EndingLLMClient())
    try:
        resp = await db_client.post(f"/chat-rooms/{room['id']}/messages", json={"content": "떠난다"})
    finally:
        _clear_llm_override()

    assert any(event["type"] == "endingReached" for event in _parse_sse_events(resp.text))
    assert await _unlocked_cells(db_session, user_id, content) == [rooftop.entity_id]


async def test_story_detail_view_does_not_unlock_cells(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상세 페이지의 프롤로그 그림은 해금이 아니다 — 보관함은 채팅에서 본 것만 연다."""
    user_id, content, _ = await _story_with_setup(db_session, opening_message=None, prologue="{{img::민아/교실}}")
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    viewer = _make_user()
    db_session.add(viewer)
    await db_session.commit()
    await _login_as(db_client, viewer.id)

    resp = await db_client.get(f"/contents/{content.id}")

    assert resp.status_code == 200
    assert resp.json()["mediaTagImages"] != {}
    assert await _unlocked_cells(db_session, viewer.id, content) == []


# ---- 보관함 목록 -----------------------------------------------------------------------------------------


async def test_story_image_archive_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/stories/{uuid.uuid4()}/image-archive")
    assert resp.status_code == 401


async def test_story_image_archive_unknown_or_unpublished_story_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, _ = await _story_with_setup(db_session, opening_message="시작")
    content.current_published_version_id = None
    await db_session.commit()
    await _login_as(db_client, user_id)

    assert (await db_client.get(f"/stories/{uuid.uuid4()}/image-archive")).status_code == 404
    assert (await db_client.get(f"/stories/{content.id}/image-archive")).status_code == 404


async def test_story_image_archive_never_signs_original_key_for_locked_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """본 칸은 원본 썸네일, 못 본 칸은 블러본 썸네일과 힌트. 못 본 칸의 응답에는 원본 키가 어디에도 없다.
    항목은 축 순서(인물 → 장면)이고, 이름과 크기를 함께 싣는다."""
    user_id, content, _ = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    version_id = content.current_published_version_id
    seen, seen_original, _ = await _add_blurred_cell(db_session, version_id, user_id, "민아", "교실", unlock_hint="교실")
    locked, locked_original, locked_blur = await _add_blurred_cell(
        db_session, version_id, user_id, "민아", "옥상", unlock_hint="옥상에 올라가 보자"
    )
    db_session.add(StoryMediaExposure(user_id=user_id, content_id=content.id, cell_entity_id=seen.entity_id))
    await db_session.commit()
    await _login_as(db_client, user_id)

    resp = await db_client.get(f"/stories/{content.id}/image-archive")

    assert resp.status_code == 200
    seen_item, locked_item = resp.json()
    assert seen_item["id"] == str(seen.entity_id)
    assert seen_item["exposed"] is True
    assert build_thumbnail_key(seen_original.storage_key) in seen_item["imageUrl"]
    assert seen_item["unlockHint"] == ""
    assert locked_item["id"] == str(locked.entity_id)
    assert locked_item["exposed"] is False
    assert build_thumbnail_key(locked_blur.storage_key) in locked_item["imageUrl"]
    assert locked_original.storage_key.rsplit(".", 1)[0] not in resp.text
    assert locked_item["unlockHint"] == "옥상에 올라가 보자"
    # 못 본 칸은 인물 이름만 — 장면 이름은 무엇이 그려졌는지 미리 알려 주므로 해금 전까지 비운다.
    assert (seen_item["personName"], seen_item["sceneName"]) == ("민아", "교실")
    assert (locked_item["personName"], locked_item["sceneName"]) == ("민아", "")
    assert (locked_item["width"], locked_item["height"]) == (300, 400)


async def test_story_image_archive_uses_current_published_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """칸 목록과 그림은 지금 발행본의 것이다 — 해금 기록은 칸 entity_id 로 버전을 건너 이어진다."""
    user_id, content, _ = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    old_cell, _, _ = await _add_blurred_cell(db_session, content.current_published_version_id, user_id, "민아", "교실")
    await _add_blurred_cell(db_session, content.current_published_version_id, user_id, "민아", "복도")
    new_version = ContentVersion(
        content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(new_version)
    await db_session.flush()
    content.current_published_version_id = new_version.id
    kept, kept_original, _ = await _add_blurred_cell(db_session, new_version.id, user_id, "민아", "교실")
    kept.entity_id = old_cell.entity_id
    added, _, _ = await _add_blurred_cell(db_session, new_version.id, user_id, "민아", "옥상")
    db_session.add(StoryMediaExposure(user_id=user_id, content_id=content.id, cell_entity_id=old_cell.entity_id))
    await db_session.commit()
    await _login_as(db_client, user_id)

    resp = await db_client.get(f"/stories/{content.id}/image-archive")

    assert resp.status_code == 200
    items = resp.json()
    assert [item["id"] for item in items] == [str(old_cell.entity_id), str(added.entity_id)]
    assert build_thumbnail_key(kept_original.storage_key) in items[0]["imageUrl"]


async def test_story_image_archive_omits_cells_without_unlock_path(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """대화 중 판정에서 빠진 칸은 첫 메시지나 엔딩 에필로그에 나올 때만 볼 길이 있다. 시작상황이 있는 시작설정의
    프롤로그는 첫 메시지가 아니라서 길이 아니다. 길 없는 칸은 영원히 잠긴 자물쇠라 목록에서 뺀다."""
    user_id, content, setup = await _story_with_setup(
        db_session, opening_message="시작", prologue="{{img::민아/프롤로그}}"
    )
    assert content.current_published_version_id is not None
    version_id = content.current_published_version_id
    db_session.add(
        StartingSetup(
            entity_id=uuid.uuid4(),
            content_version_id=version_id,
            name="두 번째",
            prologue="{{img::민아/시작상황없음}}",
            opening_message=None,
            order=2,
        )
    )
    db_session.add(
        StartingSetup(
            entity_id=uuid.uuid4(),
            content_version_id=version_id,
            name="세 번째",
            prologue="프롤로그",
            opening_message="{{img::민아/시작상황}}",
            order=3,
        )
    )
    await _add_epilogue_ending(db_session, setup, "{{img::민아/에필로그}}")
    judged, _, _ = await _add_blurred_cell(db_session, version_id, user_id, "민아", "판정")
    await _add_blurred_cell(db_session, version_id, user_id, "민아", "길없음", exclude_from_chat=True)
    await _add_blurred_cell(db_session, version_id, user_id, "민아", "프롤로그", exclude_from_chat=True)
    no_opening, _, _ = await _add_blurred_cell(db_session, version_id, user_id, "민아", "시작상황없음", exclude_from_chat=True)
    opening, _, _ = await _add_blurred_cell(db_session, version_id, user_id, "민아", "시작상황", exclude_from_chat=True)
    epilogue, _, _ = await _add_blurred_cell(db_session, version_id, user_id, "민아", "에필로그", exclude_from_chat=True)
    await db_session.commit()
    await _login_as(db_client, user_id)

    resp = await db_client.get(f"/stories/{content.id}/image-archive")

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [
        str(judged.entity_id),
        str(no_opening.entity_id),
        str(opening.entity_id),
        str(epilogue.entity_id),
    ]


async def test_story_image_archive_keeps_unlocked_cell_after_exclusion(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작가가 나중에 판정에서 뺀 칸이라도 이미 본 칸은 보관함에 남는다."""
    user_id, content, _ = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    cell, original, _ = await _add_blurred_cell(
        db_session, content.current_published_version_id, user_id, "민아", "교실", exclude_from_chat=True
    )
    db_session.add(StoryMediaExposure(user_id=user_id, content_id=content.id, cell_entity_id=cell.entity_id))
    await db_session.commit()
    await _login_as(db_client, user_id)

    resp = await db_client.get(f"/stories/{content.id}/image-archive")

    assert resp.status_code == 200
    [item] = resp.json()
    assert item["id"] == str(cell.entity_id)
    assert item["exposed"] is True
    assert build_thumbnail_key(original.storage_key) in item["imageUrl"]


async def _archive_status(client: httpx.AsyncClient, viewer_id: uuid.UUID, content: Content) -> int:
    await _login_as(client, viewer_id)
    return (await client.get(f"/stories/{content.id}/image-archive")).status_code


async def test_story_image_archive_blocks_sanctioned_story(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이용제한·삭제된 작품의 보관함은 작가에게도 열지 않는다(상세 화면이 본문을 그리지 않는 작품)."""
    user_id, content, _ = await _story_with_setup(db_session, opening_message="시작")
    content.moderation_status = ModerationStatus.RESTRICTED
    await db_session.commit()
    assert await _archive_status(db_client, user_id, content) == 404

    content.moderation_status = ModerationStatus.DELETED
    await db_session.commit()
    assert await _archive_status(db_client, user_id, content) == 404


async def test_story_image_archive_private_story_opens_only_to_creator_and_players(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """비공개 작품은 작가 본인과 그 작품에 대화방이 있는 사용자(공개였을 때 시작한 독자)만 볼 수 있다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="시작")
    assert content.current_published_version_id is not None
    content.visibility = ContentVisibility.PRIVATE
    player = _make_user()
    stranger = _make_user()
    db_session.add_all([player, stranger])
    await db_session.flush()
    db_session.add(
        ChatRoom(
            user_id=player.id,
            content_id=content.id,
            content_version_id=content.current_published_version_id,
            starting_setup_entity_id=setup.entity_id,
        )
    )
    await db_session.commit()

    assert await _archive_status(db_client, user_id, content) == 200
    assert await _archive_status(db_client, player.id, content) == 200
    assert await _archive_status(db_client, stranger.id, content) == 404


async def test_story_image_archive_rejects_character_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """스토리 보관함 주소에 캐릭터 id 를 넣으면 없는 스토리와 같은 404 다 — 캐릭터에는 미디어 북이 없어서, 빈
    목록으로 열어 주면 엉뚱한 작품의 빈 보관함이 정상처럼 보인다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    character = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    assert await _archive_status(db_client, user.id, character) == 404
