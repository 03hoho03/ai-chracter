import io
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Any

import boto3
import httpx
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from api.content.publish import PublishFilterResult
from api.core.config import settings
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus
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


def _upload_test_image(storage_key: str) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color=(10, 20, 30)).save(buffer, format="PNG")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=buffer.getvalue())


async def _make_ready_asset(db_session: AsyncSession, *, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/profile-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    _upload_test_image(asset.storage_key)
    return asset


async def _make_empty_character_draft(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(content_id=content.id, detail_description="")
    db_session.add(version)
    await db_session.flush()

    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="",
            one_liner="",
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    )
    await db_session.flush()
    return content


async def _make_publishable_character_draft(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID
) -> tuple[Content, ContentVersion, Asset, SituationalImage]:
    """A draft with every field `validate_character_publish` requires filled in, plus one
    situational image (with an uploaded image) so the multimodal filter has something to see."""
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=["힐링"],
        visibility=ContentVisibility.PRIVATE,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(content_id=content.id, detail_description="상세 설명")
    db_session.add(version)
    await db_session.flush()

    thumbnail = await _make_ready_asset(db_session, owner_user_id=creator_user_id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="아리아",
            one_liner="한 줄 소개",
            thumbnail_asset_id=thumbnail.id,
            intro="안녕하세요",
            example_dialogues=[{"id": "d1", "userLine": "안녕", "characterLine": "반가워"}],
            character_prompt="너는 아리아다.",
        )
    )
    await db_session.flush()

    situational_image_asset = await _make_ready_asset(db_session, owner_user_id=creator_user_id)
    situational_image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=version.id,
        image_asset_id=situational_image_asset.id,
        trigger_condition="사용자가 인사할 때",
        order=0,
    )
    db_session.add(situational_image)
    await db_session.flush()

    return content, version, thumbnail, situational_image


class _FakeLLMClient(LLMClient):
    def __init__(self, result: PublishFilterResult) -> None:
        self.result = result
        self.received_prompt: str | None = None
        self.received_images: list[tuple[bytes, str]] | None = None

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover - unreachable, keeps this an async generator

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None
    ) -> Any:
        self.received_prompt = prompt
        self.received_images = images
        return self.result


def _override_llm_client(fake: _FakeLLMClient) -> None:
    app.dependency_overrides[get_llm_client] = lambda: fake


def _clear_llm_override() -> None:
    app.dependency_overrides.pop(get_llm_client, None)


async def test_publish_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(f"/contents/{uuid.uuid4()}/publish")
    assert resp.status_code == 401


async def test_publish_returns_404_for_missing_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)

    # FastAPI resolves every Depends() (including get_llm_client) before the route
    # body runs, even though this request never reaches the LLM call.
    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{uuid.uuid4()}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 404


async def test_publish_returns_403_for_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 403


async def test_publish_rejects_incomplete_draft_with_missing_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400
    assert resp.json()["detail"] == {
        "missingFields": [
            "name",
            "oneLiner",
            "thumbnailAssetId",
            "intro",
            "characterPrompt",
            "description",
            "genreId",
            "target",
        ]
    }


async def test_publish_rejects_when_filter_fails_and_leaves_draft_unchanged(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _thumbnail, _image = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=False, reason="부적절한 표현이 포함되어 있어요"))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"reason": "부적절한 표현이 포함되어 있어요"}

    await db_session.refresh(version)
    await db_session.refresh(content)
    assert version.published_at is None
    assert version.version_number is None
    assert content.current_published_version_id is None

    remaining_versions = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalars().all()
    assert len(remaining_versions) == 1


async def test_publish_passes_thumbnail_and_situational_images_to_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _image = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_images is not None
    assert len(fake.received_images) == 2
    for _data, mime_type in fake.received_images:
        assert mime_type == "image/png"
    assert fake.received_prompt is not None
    assert "아리아" in fake.received_prompt
    assert "너는 아리아다." in fake.received_prompt


async def test_publish_confirms_transaction_and_clones_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, thumbnail, image = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    body = resp.json()
    assert body["contentId"] == str(content.id)
    assert body["versionNumber"] == 1

    await db_session.refresh(version)
    await db_session.refresh(content)
    assert version.published_at is not None
    assert version.version_number == 1
    assert content.current_published_version_id == version.id

    versions = (
        (
            await db_session.execute(
                sa.select(ContentVersion)
                .where(ContentVersion.content_id == content.id)
                .order_by(ContentVersion.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert len(versions) == 2
    new_version = next(v for v in versions if v.id != version.id)
    assert new_version.published_at is None
    assert new_version.version_number is None
    assert new_version.detail_description == "상세 설명"

    new_detail = await db_session.get(CharacterVersionDetail, new_version.id)
    assert new_detail is not None
    assert new_detail.name == "아리아"
    assert new_detail.one_liner == "한 줄 소개"
    assert new_detail.thumbnail_asset_id == thumbnail.id
    assert new_detail.intro == "안녕하세요"
    assert new_detail.character_prompt == "너는 아리아다."

    new_images = (
        (
            await db_session.execute(
                sa.select(SituationalImage).where(SituationalImage.content_version_id == new_version.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(new_images) == 1
    assert new_images[0].id != image.id
    assert new_images[0].entity_id == image.entity_id
    assert new_images[0].image_asset_id == image.image_asset_id
    assert new_images[0].trigger_condition == image.trigger_condition
    assert new_images[0].order == image.order

    # the original (now-published) version's situational image row is untouched
    old_images = (
        (
            await db_session.execute(
                sa.select(SituationalImage).where(SituationalImage.content_version_id == version.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(old_images) == 1
    assert old_images[0].id == image.id


async def test_republish_increments_version_number(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _image = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        first_resp = await db_client.post(f"/contents/{content.id}/publish")
        assert first_resp.status_code == 200
        second_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert second_resp.status_code == 200
    assert second_resp.json()["versionNumber"] == 2
