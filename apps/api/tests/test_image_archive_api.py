import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import ImageMatchJudgmentResult
from api.core.s3 import build_thumbnail_key
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.chat import CharacterImageExposure
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.main import app


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(timezone.utc),
        "privacy_agreed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _get_genre(db_session: AsyncSession) -> Genre:
    result = await db_session.execute(sa.select(Genre).limit(1))
    return result.scalars().one()


async def _make_asset(
    db_session: AsyncSession, *, owner_user_id: uuid.UUID, kind: AssetKind = AssetKind.ORIGINAL
) -> Asset:
    asset = Asset(owner_user_id=owner_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=kind)
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_published_character(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(timezone.utc), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_asset(db_session, owner_user_id=creator_user_id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _add_situational_image(
    db_session: AsyncSession, content: Content, *, owner_user_id: uuid.UUID, **overrides: object
) -> SituationalImage:
    assert content.current_published_version_id is not None
    image_asset = await _make_asset(db_session, owner_user_id=owner_user_id, kind=AssetKind.ORIGINAL)
    blurred_asset = await _make_asset(db_session, owner_user_id=owner_user_id, kind=AssetKind.BLURRED)
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "content_version_id": content.current_published_version_id,
        "image_asset_id": image_asset.id,
        "blurred_asset_id": blurred_asset.id,
        "trigger_condition": "문을 열었을 때",
        "order": 1,
    }
    defaults.update(overrides)
    image = SituationalImage(**defaults)
    db_session.add(image)
    await db_session.flush()
    return image


class _ImageMatchingLLMClient(LLMClient):
    """상황별 이미지 매칭만 흉내내는 최소 페이크 — `test_chat_message_send_api.py`의 페이크와
    달리 판정 결과를 고정해, 이 파일이 검증하려는 "매칭 발동 → 보관함" 경로에만 집중한다."""

    def __init__(self, matched_entity_id: uuid.UUID) -> None:
        self.matched_entity_id = matched_entity_id

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        yield "그럼요."

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None) -> Any:
        return ImageMatchJudgmentResult(matched_image_entity_id=str(self.matched_entity_id))


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    events = []
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


async def test_image_archive_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/characters/{uuid.uuid4()}/image-archive")
    assert resp.status_code == 401


async def test_image_archive_unknown_character_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/characters/{uuid.uuid4()}/image-archive")
    assert resp.status_code == 404


async def test_image_archive_unpublished_character_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = Content(
        creator_user_id=user.id,
        type=ContentType.CHARACTER,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/characters/{content.id}/image-archive")
    assert resp.status_code == 404


async def test_image_archive_returns_empty_list_when_no_images_registered(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/characters/{content.id}/image-archive")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_image_archive_marks_exposed_image_with_original_and_unexposed_with_blurred(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    exposed_image = await _add_situational_image(db_session, content, owner_user_id=user.id, order=1)
    unexposed_image = await _add_situational_image(db_session, content, owner_user_id=user.id, order=2)
    db_session.add(
        CharacterImageExposure(
            user_id=user.id, content_id=content.id, image_entity_id=exposed_image.entity_id
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/characters/{content.id}/image-archive")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == [str(exposed_image.entity_id), str(unexposed_image.entity_id)]

    exposed_item, unexposed_item = body
    assert exposed_item["exposed"] is True
    assert unexposed_item["exposed"] is False
    assert exposed_item["imageUrl"] != unexposed_item["imageUrl"]


async def test_image_archive_exposed_url_signs_original_asset_and_unexposed_signs_blurred(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """URL이 서로 다르다는 것만으로는 원본/블러가 뒤바뀐 경우를 잡지 못한다 — 실제로 어느
    자산의 storage_key가 서명됐는지까지 본다(해금 이미지가 흐리게 보인다는 신고의 후보 원인 중
    "자산 페어링 오류"를 고정하는 회귀 테스트)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    exposed_image = await _add_situational_image(db_session, content, owner_user_id=user.id, order=1)
    unexposed_image = await _add_situational_image(db_session, content, owner_user_id=user.id, order=2)
    db_session.add(
        CharacterImageExposure(
            user_id=user.id, content_id=content.id, image_entity_id=exposed_image.entity_id
        )
    )
    await db_session.commit()

    original = await db_session.get(Asset, exposed_image.image_asset_id)
    blurred = await db_session.get(Asset, unexposed_image.blurred_asset_id)
    assert original is not None and original.kind is AssetKind.ORIGINAL
    assert blurred is not None and blurred.kind is AssetKind.BLURRED

    await _login_as(db_client, user.id)
    exposed_item, unexposed_item = (
        await db_client.get(f"/characters/{content.id}/image-archive")
    ).json()

    assert build_thumbnail_key(original.storage_key) in exposed_item["imageUrl"]
    assert build_thumbnail_key(blurred.storage_key) in unexposed_item["imageUrl"]


async def test_image_archive_marks_image_exposed_right_after_chat_match(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """대화 중 매칭이 발동한 직후 보관함을 다시 조회하면 그 이미지가 해금(원본 자산)으로 보여야
    한다 — 노출 기록(`_match_situational_image`)과 보관함 조회를 잇는 유일한 종단 경로다.
    보관함은 방이 고정한 버전이 아니라 콘텐츠의 현재 발행 버전을 나열하므로, 이 테스트는 두
    조회가 같은 이미지 집합을 보는지(entity_id 기준 대조)까지 함께 고정한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    image = await _add_situational_image(db_session, content, owner_user_id=user.id, order=1)
    other = await _add_situational_image(db_session, content, owner_user_id=user.id, order=2)
    await db_session.commit()

    await _login_as(db_client, user.id)
    before = (await db_client.get(f"/characters/{content.id}/image-archive")).json()
    assert [item["exposed"] for item in before] == [False, False]

    room_id = (
        await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    ).json()["id"]

    app.dependency_overrides[get_llm_client] = lambda: _ImageMatchingLLMClient(image.entity_id)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "사연 읽어주세요"})
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    final_message = _parse_sse_events(resp.text)[-1]["finalMessage"]
    assert final_message["imageId"] == str(image.entity_id)

    after = (await db_client.get(f"/characters/{content.id}/image-archive")).json()
    exposed_item, unexposed_item = after
    assert exposed_item["id"] == str(image.entity_id)
    assert exposed_item["exposed"] is True
    assert unexposed_item["id"] == str(other.entity_id)
    assert unexposed_item["exposed"] is False

    original = await db_session.get(Asset, image.image_asset_id)
    assert original is not None
    # 채팅 인라인 imageUrl은 원본 화질을 유지하고, 보관함 그리드만 썸네일 변형을 서명한다.
    assert original.storage_key in final_message["imageUrl"]
    assert "_thumb.webp" not in final_message["imageUrl"]
    assert build_thumbnail_key(original.storage_key) in exposed_item["imageUrl"]


async def test_image_archive_exposure_accumulates_across_chat_rooms_not_scoped_to_one_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """AC3: 노출 기록은 방 단위가 아니라 사용자+캐릭터 단위로 누적된다 — 어떤 대화방에서
    기록됐는지와 무관하게 (user_id, content_id, image_entity_id) 존재만으로 판정해야 하므로,
    특정 chat_room을 전혀 참조하지 않고도 exposed=True가 나와야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    image = await _add_situational_image(db_session, content, owner_user_id=user.id)
    db_session.add(CharacterImageExposure(user_id=user.id, content_id=content.id, image_entity_id=image.entity_id))
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/characters/{content.id}/image-archive")
    assert resp.status_code == 200
    assert resp.json()[0]["exposed"] is True
