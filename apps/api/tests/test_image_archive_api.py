import uuid
from datetime import date, datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.character import SituationalImage
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


async def _make_asset(db_session: AsyncSession, *, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(owner_user_id=owner_user_id, storage_key=f"assets/test/{uuid.uuid4()}", kind=AssetKind.ORIGINAL)
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

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _add_situational_image(
    db_session: AsyncSession, content: Content, *, owner_user_id: uuid.UUID, **overrides: object
) -> SituationalImage:
    assert content.current_published_version_id is not None
    image_asset = await _make_asset(db_session, owner_user_id=owner_user_id)
    blurred_asset = await _make_asset(db_session, owner_user_id=owner_user_id)
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
