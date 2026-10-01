import io
import threading
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timezone
from decimal import Decimal
from typing import Any

import boto3
import httpx
import pytest
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.image_processing import generate_blurred_image
from api.content.publish import PublishFilterResult, validate_story_publish
from api.content.router import _MEDIA_BOOK_S3_CONCURRENCY
from api.core.config import settings
from api.core.s3 import build_thumbnail_key
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    EndingRuleOperator,
    KeywordNote,
    LogicalOp,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from factories import (
    _add_media_book_cell,
    _add_named_media_cell,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_user,
    _override_llm_client,
)


def _upload_test_image(storage_key: str, size: tuple[int, int] = (16, 16)) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buffer, format="PNG")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=buffer.getvalue())


def _upload_test_thumbnail(storage_key: str, color: tuple[int, int, int] = (40, 50, 60)) -> bytes:
    """원본 `storage_key` 옆 `_thumb.webp` 자리에 축소본을 올리고 그 바이트를 돌려준다. 색을 달리 주면 축소본마다
    바이트가 달라 어느 칸의 축소본이 실렸는지 가릴 수 있다."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buffer, format="WEBP")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=build_thumbnail_key(storage_key), Body=buffer.getvalue())
    return buffer.getvalue()


def _object_bytes(storage_key: str) -> bytes:
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    body: bytes = s3.get_object(Bucket=settings.s3_bucket_name, Key=storage_key)["Body"].read()
    return body


async def _make_ready_asset(db_session: AsyncSession, *, owner_user_id: uuid.UUID) -> Asset:
    """READY 자산은 언제나 원본과 `_thumb.webp` 축소본을 함께 갖는다(업로드 완료·생성이 둘을 같이 올린다)."""
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/profile-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    _upload_test_image(asset.storage_key)
    _upload_test_thumbnail(asset.storage_key)
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


async def _make_empty_story_draft(db_session: AsyncSession, *, creator_user_id: uuid.UUID) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
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
        StoryVersionDetail(
            content_version_id=version.id,
            name="",
            one_liner="",
            prompt_template=StoryPromptTemplate.BASIC,
        )
    )
    await db_session.flush()
    return content


async def _make_publishable_story_draft(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID
) -> tuple[Content, ContentVersion, Asset, StartingSetup, Ending, StatDef]:
    """A story draft with every field `validate_story_publish` requires filled in, plus one
    starting setup carrying a stat, an ending with a turnCountGate=10 rule tree (top-level rule +
    one nested group), a keyword note scoped to that setup, and a shortcut — deep enough to
    exercise the full publish-transaction clone."""
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=["판타지"],
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
        StoryVersionDetail(
            content_version_id=version.id,
            name="잃어버린 도시",
            one_liner="한 줄 소개",
            thumbnail_asset_id=thumbnail.id,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text="세계관 설명",
            development_examples=[{"userLine": "안녕", "assistantLine": "어서오세요"}],
            user_goal="용을 물리친다",
            rules="폭력 묘사는 암시로만 한다",
        )
    )
    await db_session.flush()

    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=version.id,
        name="시작설정1",
        prologue="프롤로그",
        order=0,
    )
    db_session.add(setup)
    await db_session.flush()

    stat_def = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="체력",
        icon="heart",
        color="rose",
        min_value=0,
        max_value=100,
        initial_value=50,
        description="체력 스탯",
        order=0,
    )
    db_session.add(stat_def)
    await db_session.flush()

    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="해피엔딩",
        turn_count_gate=10,
        judgment_prompt="판정 프롬프트",
        epilogue="에필로그",
        order=0,
    )
    db_session.add(ending)
    await db_session.flush()

    top_rule = EndingRule(
        entity_id=uuid.uuid4(),
        ending_id=ending.id,
        stat_def_entity_id=stat_def.entity_id,
        operator=EndingRuleOperator.GTE,
        threshold=Decimal(50),
        next_op=LogicalOp.AND,
        order=0,
    )
    db_session.add(top_rule)

    group = EndingRuleGroup(entity_id=uuid.uuid4(), ending_id=ending.id, next_op=None, order=1)
    db_session.add(group)
    await db_session.flush()

    nested_rule = EndingRule(
        entity_id=uuid.uuid4(),
        rule_group_id=group.id,
        stat_def_entity_id=stat_def.entity_id,
        operator=EndingRuleOperator.LT,
        threshold=Decimal(10),
        order=0,
    )
    db_session.add(nested_rule)

    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=version.id,
            starting_setup_id=setup.id,
            info_text="키워드 노트",
            trigger_keywords=["단서"],
        )
    )
    db_session.add(
        Shortcut(
            entity_id=uuid.uuid4(),
            content_version_id=version.id,
            name="단축어1",
            description="설명",
            prompt="프롬프트",
        )
    )
    await db_session.flush()

    return content, version, thumbnail, setup, ending, stat_def


class _FakeLLMClient(LLMClient):
    def __init__(self, result: PublishFilterResult) -> None:
        self.result = result
        self.received_prompt: str | None = None
        self.received_images: list[tuple[bytes, str]] | None = None

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover - unreachable, keeps this an async generator

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.received_prompt = prompt
        self.received_images = images
        return self.result


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


async def test_publish_character_rejects_situational_image_without_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """The builder autosaves a situational-image row before its image is uploaded. Publishing
    with such a row would ship a slot the chat can never show, so publish names it as missing
    instead — before the moderation call, and without touching the draft."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _thumbnail, _image = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    db_session.add(
        SituationalImage(
            entity_id=uuid.uuid4(),
            content_version_id=version.id,
            trigger_condition="이미지를 아직 안 올린 상황",
            order=1,
        )
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["situationalImages"]}
    assert fake.received_prompt is None
    await db_session.refresh(version)
    assert version.published_at is None


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


async def test_publish_removes_content_from_my_drafts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """`/me/drafts`가 거르는 상태를 실제 발행 경로로 만들어 확인한다 — 발행이 남기는
    자동 복제 초안이 목록에 다시 새어 나오지 않아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _image = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    before = await db_client.get("/me/drafts")
    assert before.status_code == 200
    assert [draft["id"] for draft in before.json()["items"]] == [str(content.id)]

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    after = await db_client.get("/me/drafts")
    assert after.status_code == 200
    assert after.json()["items"] == []


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


async def test_publish_story_rejects_incomplete_draft_with_missing_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
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
            "settingText",
            "startingSetups",
            "description",
            "genreId",
            "target",
        ]
    }


async def test_publish_story_rejects_ending_with_low_turn_count_gate(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _setup, ending, _stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    ending.turn_count_gate = 5
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["startingSetups[0].endings[0].turnCountGate"]}


async def test_publish_story_rejects_when_filter_fails_and_leaves_draft_unchanged(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _thumbnail, _setup, _ending, _stat_def = await _make_publishable_story_draft(
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
        (
            await db_session.execute(
                sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_versions) == 1


async def test_publish_story_passes_thumbnail_to_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _setup, _ending, _stat_def = await _make_publishable_story_draft(
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
    assert len(fake.received_images) == 1
    _data, mime_type = fake.received_images[0]
    assert mime_type == "image/png"
    assert fake.received_prompt is not None
    assert "잃어버린 도시" in fake.received_prompt
    assert "세계관 설명" in fake.received_prompt


async def test_publish_story_confirms_transaction_and_clones_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, thumbnail, setup, ending, stat_def = await _make_publishable_story_draft(
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

    new_detail = await db_session.get(StoryVersionDetail, new_version.id)
    assert new_detail is not None
    assert new_detail.name == "잃어버린 도시"
    assert new_detail.thumbnail_asset_id == thumbnail.id
    assert new_detail.setting_text == "세계관 설명"
    assert new_detail.development_examples == [{"userLine": "안녕", "assistantLine": "어서오세요"}]
    assert new_detail.user_goal == "용을 물리친다"
    assert new_detail.rules == "폭력 묘사는 암시로만 한다"

    new_setup = await db_session.scalar(
        sa.select(StartingSetup).where(
            StartingSetup.content_version_id == new_version.id, StartingSetup.entity_id == setup.entity_id
        )
    )
    assert new_setup is not None
    assert new_setup.id != setup.id
    assert new_setup.name == "시작설정1"
    assert new_setup.prologue == "프롤로그"

    new_stat_def = await db_session.scalar(
        sa.select(StatDef).where(
            StatDef.starting_setup_id == new_setup.id, StatDef.entity_id == stat_def.entity_id
        )
    )
    assert new_stat_def is not None
    assert new_stat_def.id != stat_def.id

    new_ending = await db_session.scalar(
        sa.select(Ending).where(
            Ending.starting_setup_id == new_setup.id, Ending.entity_id == ending.entity_id
        )
    )
    assert new_ending is not None
    assert new_ending.id != ending.id
    assert new_ending.turn_count_gate == 10

    new_top_rules = (
        (await db_session.execute(sa.select(EndingRule).where(EndingRule.ending_id == new_ending.id)))
        .scalars()
        .all()
    )
    assert len(new_top_rules) == 1
    assert new_top_rules[0].stat_def_entity_id == stat_def.entity_id
    assert new_top_rules[0].operator == EndingRuleOperator.GTE

    new_groups = (
        (
            await db_session.execute(
                sa.select(EndingRuleGroup).where(EndingRuleGroup.ending_id == new_ending.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(new_groups) == 1
    new_nested_rules = (
        (await db_session.execute(sa.select(EndingRule).where(EndingRule.rule_group_id == new_groups[0].id)))
        .scalars()
        .all()
    )
    assert len(new_nested_rules) == 1
    assert new_nested_rules[0].stat_def_entity_id == stat_def.entity_id
    assert new_nested_rules[0].operator == EndingRuleOperator.LT

    new_keyword_note = await db_session.scalar(
        sa.select(KeywordNote).where(KeywordNote.content_version_id == new_version.id)
    )
    assert new_keyword_note is not None
    # keyword_notes.starting_setup_id is a physical FK — must be remapped to the *new* setup's
    # physical id, not left pointing at the old (now-published) setup row.
    assert new_keyword_note.starting_setup_id == new_setup.id

    new_shortcut = await db_session.scalar(
        sa.select(Shortcut).where(Shortcut.content_version_id == new_version.id)
    )
    assert new_shortcut is not None
    assert new_shortcut.name == "단축어1"

    # the original (now-published) version's tree is untouched
    old_setup_still_exists = await db_session.get(StartingSetup, setup.id)
    assert old_setup_still_exists is not None
    old_ending_still_exists = await db_session.get(Ending, ending.id)
    assert old_ending_still_exists is not None


async def test_reset_draft_after_real_publish_restores_character_edits(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """End to end on the state a real publish leaves behind — the auto-cloned draft is
    edited through the real autosave endpoint, then 편집 취소 puts the published content back."""
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
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert publish_resp.status_code == 200

    patch_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json={
            "name": "고쳐 쓴 이름",
            "oneLiner": "고쳐 쓴 한 줄",
            "thumbnailAssetId": None,
            "intro": "고쳐 쓴 인트로",
            "exampleDialogues": [],
            "characterPrompt": "고쳐 쓴 프롬프트",
            "playguide": None,
            "situationalImages": [],
            "description": "고쳐 쓴 설명",
            "genreId": str(genre.id),
            "target": "all",
            "hashtags": ["힐링"],
            "visibility": "private",
        },
    )
    assert patch_resp.status_code == 200
    draft_version_id = uuid.UUID(patch_resp.json()["contentVersionId"])

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 204

    draft_version = await db_session.get(ContentVersion, draft_version_id)
    assert draft_version is not None
    assert draft_version.detail_description == "상세 설명"

    draft_detail = await db_session.get(CharacterVersionDetail, draft_version_id)
    assert draft_detail is not None
    assert draft_detail.name == "아리아"
    assert draft_detail.thumbnail_asset_id == thumbnail.id
    assert draft_detail.character_prompt == "너는 아리아다."

    draft_images = (
        (
            await db_session.execute(
                sa.select(SituationalImage).where(
                    SituationalImage.content_version_id == draft_version_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [i.entity_id for i in draft_images] == [image.entity_id]
    assert draft_images[0].image_asset_id == image.image_asset_id

    # the draft row itself survived, so editing still works after the reset
    reedit_resp = await db_client.get(f"/contents/{content.id}/draft")
    assert reedit_resp.status_code == 200
    assert reedit_resp.json()["name"] == "아리아"

    await db_session.refresh(content)
    assert content.current_published_version_id == version.id


async def test_reset_draft_after_real_publish_restores_story_edits(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _thumbnail, setup, ending, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert publish_resp.status_code == 200

    draft_version_id = await db_session.scalar(
        sa.select(ContentVersion.id).where(
            ContentVersion.content_id == content.id, ContentVersion.published_at.is_(None)
        )
    )
    assert draft_version_id is not None
    pre_reset_note = await db_session.scalar(
        sa.select(KeywordNote).where(KeywordNote.content_version_id == draft_version_id)
    )
    assert pre_reset_note is not None

    # the editor renames the setup and throws away its stats, endings and the shortcut.
    patch_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json={
            "name": "고쳐 쓴 제목",
            "oneLiner": "고쳐 쓴 한 줄",
            "thumbnailAssetId": None,
            "promptTemplate": "basic",
            "settingText": "고쳐 쓴 세계관",
            "developmentExample": None,
            "customPrompt": None,
            "startingSetups": [
                {
                    "id": str(setup.entity_id),
                    "name": "고쳐 쓴 시작설정",
                    "prologue": "고쳐 쓴 프롤로그",
                    "openingMessage": None,
                    "playguide": None,
                    "suggestedReplies": [],
                    "statDefs": [],
                    "endings": [],
                }
            ],
            "keywordNotes": [
                {
                    "id": str(pre_reset_note.entity_id),
                    "infoText": "고쳐 쓴 노트",
                    "triggerKeywords": ["고침"],
                    "startingSetupId": str(setup.entity_id),
                }
            ],
            "shortcuts": [],
            "description": "고쳐 쓴 설명",
            "genreId": str(genre.id),
            "target": "all",
            "hashtags": ["판타지"],
            "visibility": "private",
        },
    )
    assert patch_resp.status_code == 200

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 204

    draft_detail = await db_session.get(StoryVersionDetail, draft_version_id)
    assert draft_detail is not None
    assert draft_detail.name == "잃어버린 도시"
    assert draft_detail.setting_text == "세계관 설명"

    draft_setup = await db_session.scalar(
        sa.select(StartingSetup).where(StartingSetup.content_version_id == draft_version_id)
    )
    assert draft_setup is not None
    assert draft_setup.entity_id == setup.entity_id
    assert draft_setup.id != setup.id
    assert draft_setup.name == "시작설정1"
    assert draft_setup.prologue == "프롤로그"

    draft_stat = await db_session.scalar(
        sa.select(StatDef).where(StatDef.starting_setup_id == draft_setup.id)
    )
    assert draft_stat is not None
    assert draft_stat.entity_id == stat_def.entity_id

    draft_ending = await db_session.scalar(
        sa.select(Ending).where(Ending.starting_setup_id == draft_setup.id)
    )
    assert draft_ending is not None
    assert draft_ending.entity_id == ending.entity_id

    draft_top_rules = (
        (await db_session.execute(sa.select(EndingRule).where(EndingRule.ending_id == draft_ending.id)))
        .scalars()
        .all()
    )
    assert len(draft_top_rules) == 1
    assert draft_top_rules[0].stat_def_entity_id == stat_def.entity_id

    draft_groups = (
        (
            await db_session.execute(
                sa.select(EndingRuleGroup).where(EndingRuleGroup.ending_id == draft_ending.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(draft_groups) == 1

    draft_note = await db_session.scalar(
        sa.select(KeywordNote).where(KeywordNote.content_version_id == draft_version_id)
    )
    assert draft_note is not None
    assert draft_note.info_text == "키워드 노트"
    assert draft_note.trigger_keywords == ["단서"]
    assert draft_note.starting_setup_id == draft_setup.id

    draft_shortcut = await db_session.scalar(
        sa.select(Shortcut).where(Shortcut.content_version_id == draft_version_id)
    )
    assert draft_shortcut is not None
    assert draft_shortcut.name == "단축어1"

    await db_session.refresh(content)
    assert content.current_published_version_id == version.id


async def _summary_has_unpublished_changes(
    client: httpx.AsyncClient, *, creator_user_id: uuid.UUID
) -> bool:
    """`ContentSummary.hasUnpublishedChanges`를 `/users/{id}/contents`에서 읽어 온다 — 플래그를
    세팅하는 코드와 그것을 노출하는 스키마를 한 번에 본다."""
    resp = await client.get(f"/users/{creator_user_id}/contents", params={"type": "character"})
    assert resp.status_code == 200
    [item] = resp.json()["items"]
    assert isinstance(item["hasUnpublishedChanges"], bool)
    return bool(item["hasUnpublishedChanges"])


async def test_has_unpublished_changes_follows_draft_lifecycle(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """발행 직후 false → 자동저장 후 true → 편집 취소 후 false → 자동저장 후 재발행하면
    다시 false. `ContentVersion`에는 `updated_at`이 없고 발행이 다음 편집용 초안을 자동 복제하므로
    이 네 상태는 명시적 플래그로만 구분된다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, thumbnail, _image = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    def _edit_payload(name: str) -> dict[str, object]:
        """발행 가능한 상태를 유지하는 자동저장 페이로드 — 재발행까지 이어가야 하므로 필수 필드를
        비우지 않는다."""
        return {
            "name": name,
            "oneLiner": "고쳐 쓴 한 줄",
            "thumbnailAssetId": str(thumbnail.id),
            "intro": "고쳐 쓴 인트로",
            "exampleDialogues": [],
            "characterPrompt": "너는 아리아다.",
            "playguide": None,
            "situationalImages": [],
            "description": "상세 설명",
            "genreId": str(genre.id),
            "target": "all",
            "hashtags": ["힐링"],
            "visibility": "private",
        }

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
        assert publish_resp.status_code == 200
        assert await _summary_has_unpublished_changes(db_client, creator_user_id=user.id) is False

        patch_resp = await db_client.patch(
            f"/contents/{content.id}/draft", json=_edit_payload("고쳐 쓴 이름")
        )
        assert patch_resp.status_code == 200
        assert await _summary_has_unpublished_changes(db_client, creator_user_id=user.id) is True

        reset_resp = await db_client.post(f"/contents/{content.id}/draft/reset")
        assert reset_resp.status_code == 204
        assert await _summary_has_unpublished_changes(db_client, creator_user_id=user.id) is False

        rewrite_resp = await db_client.patch(
            f"/contents/{content.id}/draft", json=_edit_payload("다시 고쳐 쓴 이름")
        )
        assert rewrite_resp.status_code == 200
        assert await _summary_has_unpublished_changes(db_client, creator_user_id=user.id) is True

        republish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert republish_resp.status_code == 200
    assert await _summary_has_unpublished_changes(db_client, creator_user_id=user.id) is False


async def test_publish_story_clears_has_unpublished_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """스토리 발행도 플래그를 내린다 — 캐릭터와 같은 한 곳(`publish_content`)이 두 경로를
    덮는지 확인한다. 여기서 플래그를 자동저장이 아니라 직접 세우는 이유는 스토리 자동저장
    페이로드가 시작설정 트리를 통째로 다시 보내야 해서(빈 배열이면 발행 검증에서 막힌다)다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _setup, _ending, _stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    content.has_unpublished_changes = True
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    await db_session.refresh(content)
    assert content.has_unpublished_changes is False


async def test_publish_clones_media_book_with_stable_entity_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """발행은 초안이 발행본이 되고 다음 편집용 새 초안에 칸·축을 복제한다. entity_id·이미지·블러본·글·
    스위치가 그대로 가야 다음 발행이 블러본을 다시 만들지 않고 노출 기록도 같은 칸을 가리킨다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    image = await _make_ready_asset(db_session, owner_user_id=user.id)
    blurred = await _make_ready_asset(db_session, owner_user_id=user.id)
    cell = await _add_media_book_cell(db_session, version.id, image.id, blurred.id)
    # 축이 둘 이상이어야 복제가 순서까지 옮기는지 드러난다(빌더 배치표의 열 순서).
    second_person = MediaBookPerson(entity_id=uuid.uuid4(), content_version_id=version.id, name="준", order=1)
    second_scene = MediaBookScene(entity_id=uuid.uuid4(), content_version_id=version.id, name="옥상", order=1)
    db_session.add_all([second_person, second_scene])
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    new_version_id = await db_session.scalar(
        sa.select(ContentVersion.id).where(
            ContentVersion.content_id == content.id, ContentVersion.published_at.is_(None)
        )
    )
    assert new_version_id is not None and new_version_id != version.id
    for version_id in (version.id, new_version_id):
        people = (
            await db_session.scalars(
                sa.select(MediaBookPerson)
                .where(MediaBookPerson.content_version_id == version_id)
                .order_by(MediaBookPerson.order)
            )
        ).all()
        scenes = (
            await db_session.scalars(
                sa.select(MediaBookScene)
                .where(MediaBookScene.content_version_id == version_id)
                .order_by(MediaBookScene.order)
            )
        ).all()
        [copied] = (
            await db_session.scalars(sa.select(MediaBookCell).where(MediaBookCell.content_version_id == version_id))
        ).all()
        assert [(p.entity_id, p.name, p.order) for p in people] == [
            (cell.person_entity_id, "민아", 0),
            (second_person.entity_id, "준", 1),
        ]
        assert [(s.entity_id, s.name, s.order) for s in scenes] == [
            (cell.scene_entity_id, "교실", 0),
            (second_scene.entity_id, "옥상", 1),
        ]
        assert (
            copied.entity_id,
            copied.person_entity_id,
            copied.scene_entity_id,
            copied.image_asset_id,
            copied.blurred_asset_id,
            copied.situation_description,
            copied.unlock_hint,
            copied.exclude_from_chat,
        ) == (
            cell.entity_id,
            cell.person_entity_id,
            cell.scene_entity_id,
            image.id,
            blurred.id,
            "창가에서 웃는다",
            "첫 만남",
            True,
        )


def _bucket_keys() -> set[str]:
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    keys: set[str] = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket_name):
        keys |= {item["Key"] for item in page.get("Contents", [])}
    return keys


async def test_publish_story_creates_blur_only_for_cells_without_blur(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """보관함의 잠긴 칸은 발행이 만든 블러본만 보여 준다. 블러본은 칸마다 한 번 — 앞 발행에서 만들어 복제된
    블러본이 있는 칸은 건너뛰고, 없는 칸만 원본으로 블러본(PNG 와 `_thumb.webp`)을 만들어 원본과 같은 크기를
    적는다. 다음 편집용 초안에는 새 블러본 id 가 복제돼야 다음 발행이 다시 만들지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    kept_image = await _make_ready_asset(db_session, owner_user_id=user.id)
    kept_blur = await _make_ready_asset(db_session, owner_user_id=user.id)
    kept = await _add_media_book_cell(db_session, version.id, kept_image.id, kept_blur.id)
    fresh_image = await _make_ready_asset(db_session, owner_user_id=user.id)
    _upload_test_image(fresh_image.storage_key, size=(20, 30))
    fresh = await _add_media_book_cell(db_session, version.id, fresh_image.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    keys_before = _bucket_keys()

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    await db_session.refresh(kept)
    await db_session.refresh(fresh)
    assert kept.blurred_asset_id == kept_blur.id
    assert fresh.blurred_asset_id is not None
    blurred = await db_session.get(Asset, fresh.blurred_asset_id)
    assert blurred is not None
    assert (blurred.kind, blurred.status, blurred.owner_user_id, blurred.width, blurred.height) == (
        AssetKind.BLURRED,
        AssetStatus.READY,
        user.id,
        20,
        30,
    )
    assert _bucket_keys() - keys_before == {blurred.storage_key, build_thumbnail_key(blurred.storage_key)}
    copied_blur_id = await db_session.scalar(
        sa.select(MediaBookCell.blurred_asset_id).where(
            MediaBookCell.entity_id == fresh.entity_id, MediaBookCell.content_version_id != version.id
        )
    )
    assert copied_blur_id == blurred.id


async def test_publish_story_rejected_by_filter_creates_no_blur(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """블러본은 심사를 통과한 뒤에 만든다 — 탈락한 발행이 S3 에 블러본을 올리면 가리키는 행 없이 남는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    image = await _make_ready_asset(db_session, owner_user_id=user.id)
    cell = await _add_media_book_cell(db_session, version.id, image.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    keys_before = _bucket_keys()

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=False, reason="부적절")))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 400
    await db_session.refresh(cell)
    assert cell.blurred_asset_id is None
    assert _bucket_keys() == keys_before
    # 탈락한 발행은 초안을 그대로 둔다 — 칸은 여전히 그 초안 버전에 있고 버전은 발행되지 않았다.
    await db_session.refresh(version)
    assert (version.published_at, version.version_number, cell.content_version_id) == (None, None, version.id)


async def test_publish_story_reports_cell_whose_image_cannot_be_blurred(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """칸 그림의 블러본을 만들지 못하면(원본이 저장소에 없음 등) 이름 없는 500 이 아니라 어느 칸 때문인지
    알리는 응답으로 발행을 멈춘다. 심사 거부(`reason`)와는 다른 모양이어야 화면이 이의제기로 안내하지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    missing = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(missing)
    await db_session.flush()
    # 심사는 축소본만 읽으므로 축소본은 두어 심사를 지나 블러 단계에서 원본이 없음을 만나게 한다.
    _upload_test_thumbnail(missing.storage_key)
    cell = await _add_media_book_cell(db_session, version.id, missing.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["code"] == "MEDIA_BOOK_IMAGE_UNAVAILABLE"
    assert detail["cellId"] == str(cell.entity_id)
    assert "reason" not in detail
    await db_session.refresh(version)
    assert version.published_at is None


async def test_publish_story_blurs_cells_concurrently_within_s3_connection_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """칸 블러본은 동시에 만든다 — 운영 저장소 왕복이 칸마다 붙어 50칸을 줄 세우면 발행이 1분을 넘긴다. 다만
    공유 저장소 클라이언트의 연결 수를 넘지 않게 한 번에 정해진 칸 수까지만 돌린다. 동시에 돌아도 칸마다 자기
    그림의 블러본과 그 크기를 받아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    limit = _MEDIA_BOOK_S3_CONCURRENCY
    sized_cells: list[tuple[MediaBookCell, tuple[int, int]]] = []
    for index in range(limit + 4):
        cell, image = await _add_named_media_cell(db_session, version.id, user.id, f"인물{index}", "교실", size=None)
        # 칸마다 크기를 달리 둬 블러본이 다른 칸의 것과 뒤바뀌면 크기로 드러나게 한다.
        size = (10 + index, 40 - index)
        _upload_test_image(image.storage_key, size=size)
        _upload_test_thumbnail(image.storage_key)
        sized_cells.append((cell, size))
    await db_session.commit()
    await _login_as(db_client, user.id)
    keys_before = _bucket_keys()

    lock = threading.Lock()
    counts = {"running": 0, "peak": 0}
    limit_reached = threading.Event()

    def counting_blur(image_bytes: bytes) -> bytes:
        with lock:
            counts["running"] += 1
            counts["peak"] = max(counts["peak"], counts["running"])
            if counts["running"] >= limit:
                limit_reached.set()
        try:
            # 한도만큼 모일 때까지 붙잡아 둔다 — 한 칸씩 돌면 아무도 이 문을 열지 못해 시간이 지나서야 넘어간다.
            # 연 뒤에도 잠깐 머물러, 한도가 없다면 남은 칸이 그사이 들어와 최댓값을 한도 위로 올리게 한다.
            limit_reached.wait(timeout=1)
            time.sleep(0.2)
            return generate_blurred_image(image_bytes)
        finally:
            with lock:
                counts["running"] -= 1

    monkeypatch.setattr("api.assets.blur.generate_blurred_image", counting_blur)
    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert counts["peak"] == limit
    blurred_keys: set[str] = set()
    for cell, size in sized_cells:
        await db_session.refresh(cell)
        assert cell.blurred_asset_id is not None
        blurred = await db_session.get(Asset, cell.blurred_asset_id)
        assert blurred is not None
        assert (blurred.kind, blurred.status, blurred.owner_user_id, (blurred.width, blurred.height)) == (
            AssetKind.BLURRED,
            AssetStatus.READY,
            user.id,
            size,
        )
        assert Image.open(io.BytesIO(_object_bytes(blurred.storage_key))).size == size
        blurred_keys |= {blurred.storage_key, build_thumbnail_key(blurred.storage_key)}
    assert _bucket_keys() - keys_before == blurred_keys
    assert len(blurred_keys) == 2 * len(sized_cells)


async def test_publish_story_blur_failure_reports_first_cell_in_axis_order_after_all_blurs_finish(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """블러본을 동시에 만들다 여러 칸이 실패하면, 화면의 배치표 순서(인물 → 장면)로 가장 앞 칸을 알린다 — 한 칸씩
    돌던 때 멈췄을 그 칸이고, 실행마다 바뀌지 않는다. 응답은 아직 돌고 있는 다른 칸이 끝난 뒤에 나간다(응답
    뒤에 저장소 작업이 남아 돌지 않는다). 발행되지 않고 블러 자산 행도 칸의 블러 id 도 남지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    # 넣는 순서(민아/교실 → 준/교실 → 민아/옥상)와 배치표 순서(민아/교실 → 민아/옥상 → 준/교실)를 어긋나게 둔다.
    readable, readable_image = await _add_named_media_cell(db_session, version.id, user.id, "민아", "교실")
    later_missing, later_image = await _add_named_media_cell(db_session, version.id, user.id, "준", "교실")
    first_missing, first_image = await _add_named_media_cell(db_session, version.id, user.id, "민아", "옥상")
    _upload_test_image(readable_image.storage_key)
    # 심사는 축소본만 읽으므로 원본 없는 칸도 축소본은 두어 블러 단계까지 가게 한다.
    for image in (readable_image, later_image, first_image):
        _upload_test_thumbnail(image.storage_key)
    await db_session.commit()
    await _login_as(db_client, user.id)

    lock = threading.Lock()
    counts = {"running": 0, "finished": 0}

    def slow_blur(image_bytes: bytes) -> bytes:
        with lock:
            counts["running"] += 1
        try:
            # 읽히는 칸은 원본이 없는 칸들이 실패한 뒤에도 한동안 돈다.
            time.sleep(0.5)
            return generate_blurred_image(image_bytes)
        finally:
            with lock:
                counts["running"] -= 1
                counts["finished"] += 1

    monkeypatch.setattr("api.assets.blur.generate_blurred_image", slow_blur)
    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert (detail["code"], detail["cellId"]) == ("MEDIA_BOOK_IMAGE_UNAVAILABLE", str(first_missing.entity_id))
    assert counts == {"running": 0, "finished": 1}
    await db_session.refresh(version)
    assert version.published_at is None
    for cell in (readable, later_missing, first_missing):
        await db_session.refresh(cell)
        assert cell.blurred_asset_id is None
    blurred_rows = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(Asset)
        .where(Asset.owner_user_id == user.id, Asset.kind == AssetKind.BLURRED)
    )
    assert blurred_rows == 0


async def _story_with_media_cells(
    db_session: AsyncSession, db_client: httpx.AsyncClient
) -> tuple[Content, ContentVersion, Asset, list[tuple[MediaBookCell, bytes]]]:
    """발행할 수 있는 스토리 초안에 칸 셋을 넣는다. 칸을 넣는 순서(민아/교실 → 준/교실 → 민아/옥상)와 축 순서
    (민아/교실 → 민아/옥상 → 준/교실)를 일부러 어긋나게 둬, 심사가 행 순서가 아니라 축 순서로 싣는지 드러나게 한다.
    칸 줄의 세 모양(상황 설명·해금 힌트 둘 다 / 설명만 / 힌트만)을 하나씩 두고, 준/교실은 대화 노출 제외 칸이다 —
    노출 제외 칸도 첫 메시지·에필로그 태그와 보관함으로 보일 수 있어 심사에서 빼면 안 된다.
    칸마다 원본과 색이 다른 축소본을 올려 축소본 바이트(축 순서)를 함께 돌려준다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, thumbnail, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    added: dict[tuple[str, str], tuple[MediaBookCell, bytes]] = {}
    for index, (person, scene, description, hint, excluded) in enumerate(
        [
            ("민아", "교실", "창가에서 웃는다", "첫 만남", False),
            ("준", "교실", "", "비 오는 날", True),
            ("민아", "옥상", "난간에 기대 선다", "", False),
        ]
    ):
        cell, asset = await _add_named_media_cell(
            db_session, version.id, user.id, person, scene, situation_description=description, exclude_from_chat=excluded
        )
        cell.unlock_hint = hint
        _upload_test_image(asset.storage_key)
        added[(person, scene)] = (cell, _upload_test_thumbnail(asset.storage_key, color=(index * 60, 10, 200)))
    await db_session.commit()
    await _login_as(db_client, user.id)
    return content, version, thumbnail, [added[("민아", "교실")], added[("민아", "옥상")], added[("준", "교실")]]


async def test_publish_story_sends_media_cell_thumbnails_to_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """심사에는 대표 이미지 뒤에 칸마다 512px 축소본(`_thumb.webp`)이 실린다 — 원본(장당 수 MB)을 50장 싣지
    않는다. 순서는 심사 프롬프트의 칸 줄과 같은 축 순서(인물 → 장면)라 그림과 줄이 짝을 이룬다. 대화 노출 제외 칸
    (준/교실)도 싣는다."""
    content, _, thumbnail, cells = await _story_with_media_cells(db_session, db_client)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_images == [
        (_object_bytes(thumbnail.storage_key), "image/png"),
        *[(thumb, "image/webp") for _, thumb in cells],
    ]


async def test_publish_story_filter_prompt_includes_media_book_names_and_descriptions(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """칸의 인물·장면 이름·상황 설명·해금 힌트도 작성자가 쓴 글이라 심사 대상이다 — 힌트는 보관함에서 다른
    플레이어에게 보인다. 빈 부분은 줄에서 빠진다. 대화 노출 제외 칸(준/교실)의 줄도 있다."""
    content, _, _, _ = await _story_with_media_cells(db_session, db_client)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    lines = fake.received_prompt.splitlines()
    cell_lines = [line for line in lines if line.startswith("- 민아/") or line.startswith("- 준/")]
    assert cell_lines == [
        "- 민아/교실: 창가에서 웃는다 (해금 힌트: 첫 만남)",
        "- 민아/옥상: 난간에 기대 선다",
        "- 준/교실 (해금 힌트: 비 오는 날)",
    ]


async def test_publish_story_fails_closed_when_media_cell_thumbnail_is_missing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """칸 축소본을 저장소에서 읽지 못하면 그 칸을 심사하지 못한 것이다 — 빼고 심사하면 안 본 그림이 발행된다.
    심사를 부르지 않고 어느 칸인지 알려 발행을 멈춘다(심사 거부 `reason` 모양이 아니다)."""
    content, version, _, cells = await _story_with_media_cells(db_session, db_client)
    unreadable, _ = cells[1]
    asset = await db_session.get(Asset, unreadable.image_asset_id)
    assert asset is not None
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.delete_object(Bucket=settings.s3_bucket_name, Key=build_thumbnail_key(asset.storage_key))

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert (detail["code"], detail["cellId"]) == ("MEDIA_BOOK_IMAGE_UNAVAILABLE", str(unreadable.entity_id))
    assert "reason" not in detail
    assert fake.received_prompt is None
    await db_session.refresh(version)
    assert version.published_at is None


async def test_publish_story_does_not_publish_when_thumbnail_download_raises_unexpectedly(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """저장소 오류가 아닌 예외(동시 다운로드 중 무엇이든)는 칸 안내 없이 그대로 올라가지만, 심사를 부르지 않고
    발행되지 않는 것은 같다 — 예외를 삼켜 그 칸을 빼고 심사하면 안 된다."""
    content, version, _, _ = await _story_with_media_cells(db_session, db_client)

    def failing_download(key: str) -> bytes:
        if key.endswith("_thumb.webp"):
            raise RuntimeError("축소본 읽기 중 예상 밖 오류")
        return _object_bytes(key)

    monkeypatch.setattr("api.content.router.download_object", failing_download)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        with pytest.raises(RuntimeError, match="예상 밖 오류"):
            await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert fake.received_prompt is None
    await db_session.refresh(version)
    assert version.published_at is None


class _FailingFilterLLMClient(_FakeLLMClient):
    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.received_images = images
        raise LLMClientError("심사 호출 실패(쿼터·요청 크기 초과 등)")


async def test_publish_story_does_not_publish_when_filter_call_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """심사 호출 자체가 실패하면(쿼터 소진, 요청 크기 초과로 거부 등) 판정이 없으므로 발행하지 않는다 — 블러도
    만들지 않는다. 지금은 처리기 없이 500 으로 나간다."""
    content, version, _, cells = await _story_with_media_cells(db_session, db_client)
    keys_before = _bucket_keys()

    fake = _FailingFilterLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        with pytest.raises(LLMClientError):
            await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert fake.received_images is not None and len(fake.received_images) == 1 + len(cells)
    await db_session.refresh(version)
    assert version.published_at is None
    assert _bucket_keys() == keys_before


async def test_publish_story_rejects_more_than_fifty_media_cells(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """자동저장이 51번째 칸을 막지만 발행이 마지막 관문이다 — 심사(51장 이상 요청)까지 가지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    for index in range(51):
        await _add_named_media_cell(db_session, version.id, user.id, f"인물{index}", "교실")
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["mediaBook.cells"]}
    assert fake.received_prompt is None


async def test_publish_story_rejects_media_cell_whose_axis_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """칸의 인물·장면 참조에는 FK 가 없다. 가리키는 축이 없는 칸은 이름도 자리도 없어 심사 줄을 만들 수 없고
    대화에서도 부를 수 없다 — 발행을 막는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    cell, _ = await _add_named_media_cell(db_session, version.id, user.id, "민아", "교실")
    cell.scene_entity_id = uuid.uuid4()
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["mediaBook.orphanCells"]}
    assert fake.received_prompt is None


def _valid_story_rows() -> tuple[Content, ContentVersion, StoryVersionDetail, list[StartingSetup]]:
    content = Content(genre_id=uuid.uuid4(), target=ContentTarget.ALL)
    version = ContentVersion(detail_description="상세 설명")
    detail = StoryVersionDetail(
        name="이름",
        one_liner="한 줄",
        thumbnail_asset_id=uuid.uuid4(),
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="설정",
    )
    return content, version, detail, [StartingSetup(id=uuid.uuid4(), name="시작", prologue="프롤로그")]


def _media_book_rows(
    cell_count: int, *, orphan_person: bool = False, orphan_scene: bool = False
) -> tuple[list[MediaBookPerson], list[MediaBookScene], list[MediaBookCell]]:
    people = [MediaBookPerson(entity_id=uuid.uuid4(), name=f"인물{i}", order=i) for i in range(cell_count)]
    scene = MediaBookScene(entity_id=uuid.uuid4(), name="교실", order=0)
    cells = [
        MediaBookCell(entity_id=uuid.uuid4(), person_entity_id=person.entity_id, scene_entity_id=scene.entity_id)
        for person in people
    ]
    if orphan_person:
        cells[0].person_entity_id = uuid.uuid4()
    if orphan_scene:
        cells[-1].scene_entity_id = uuid.uuid4()
    return people, [scene], cells


@pytest.mark.parametrize(
    ("cell_count", "orphan_person", "orphan_scene", "expected"),
    [
        pytest.param(0, False, False, [], id="no-media-book"),
        pytest.param(50, False, False, [], id="fifty-cells"),
        pytest.param(51, False, False, ["mediaBook.cells"], id="fifty-one-cells"),
        pytest.param(2, True, False, ["mediaBook.orphanCells"], id="person-gone"),
        pytest.param(2, False, True, ["mediaBook.orphanCells"], id="scene-gone"),
        pytest.param(2, True, True, ["mediaBook.orphanCells"], id="both-gone-reported-once"),
    ],
)
def test_validate_story_publish_media_book(
    cell_count: int, orphan_person: bool, orphan_scene: bool, expected: list[str]
) -> None:
    """칸 수의 경계(50 통과·51 거부)와 축 참조 — 인물만·장면만 사라진 칸을 각각 잡고, 여러 칸이 고아여도 한 번만
    알린다(화면은 칸 하나하나가 아니라 미디어 북 전체를 다시 저장해 고친다)."""
    people, scenes, cells = _media_book_rows(
        cell_count, orphan_person=orphan_person, orphan_scene=orphan_scene
    )
    content, version, detail, setups = _valid_story_rows()

    missing = validate_story_publish(
        content,
        version,
        detail,
        setups,
        {},
        media_book_people=people,
        media_book_scenes=scenes,
        media_book_cells=cells,
    )

    assert missing == expected
