import asyncio
import io
import logging
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import boto3
import httpx
import pytest
import sqlalchemy as sa
from botocore.exceptions import ClientError
from PIL import Image
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets import blur as blur_module
from api.assets.image_processing import IMAGE_WORK_CONCURRENCY, generate_blurred_image
from api.content import publish_filter_memo
from api.content.publish import PublishFilterResult, validate_story_publish
from api.content import router as content_router
from api.content.router import _MEDIA_BOOK_S3_CONCURRENCY
from api.core import rate_limit_gate
from api.core.config import settings
from api.core.redis import redis_client
from api.core.s3 import build_thumbnail_key, build_variant_keys, download_object
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
from api.db.models.prompt import PromptSection, PromptSet
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
    SituationNote,
    StartingSetup,
    StatChangeDirection,
    StatDef,
    StatRule,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError, LLMRateLimitError
from factories import (
    _add_media_book_cell,
    _add_named_media_cell,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_user,
    _noting_open_transactions,
    _open_transaction_probe,
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
            default_user_name="여행자",
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
            default_user_name="모험가",
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
        self.calls = 0

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
        self.calls += 1
        self.received_prompt = prompt
        self.received_images = images
        return self.result


def _image_label_lines(prompt: str) -> list[str]:
    """심사 프롬프트의 이미지 목록 줄(`1. 대표 이미지` 꼴)만 순서대로 뽑는다."""
    return [line for line in prompt.splitlines() if re.match(r"\d+\. ", line)]


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


async def test_publish_passes_thumbnail_original_and_situational_thumbnails_in_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """대표 이미지는 원본, 상황 이미지는 축소본(`_thumb.webp`)을 싣는다. 상황 이미지는 `order` 순, 같으면
    `entity_id` 순이다 — 행을 그 반대로 넣어도 순서가 같아야 같은 그림의 재발행이 지난 통과를 쓰고, 라벨
    "상황 이미지 k" 가 k 번째 그림을 가리킨다. 축소본 색을 그림마다 달리 해 어느 그림이 어느 자리에 실렸는지 가린다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, thumbnail, last = await _make_publishable_character_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    last.order = 3
    await db_session.flush()
    last_asset = await db_session.get(Asset, last.image_asset_id)
    assert last_asset is not None
    expected_thumbnails = {last.entity_id: _upload_test_thumbnail(last_asset.storage_key, color=(200, 0, 0))}
    # 넣는 순서는 기대 순서의 역순이다. 동률(order=1) 두 행도 entity_id 가 큰 쪽을 먼저 넣는다.
    rows = [
        (2, uuid.uuid4(), (0, 200, 0)),
        (1, uuid.UUID("ffffffff-ffff-4fff-bfff-ffffffffffff"), (0, 0, 200)),
        (1, uuid.UUID("00000000-0000-4000-8000-000000000000"), (200, 200, 0)),
        (0, uuid.uuid4(), (0, 200, 200)),
    ]
    for order, entity_id, color in rows:
        asset = await _make_ready_asset(db_session, owner_user_id=user.id)
        expected_thumbnails[entity_id] = _upload_test_thumbnail(asset.storage_key, color=color)
        db_session.add(
            SituationalImage(
                entity_id=entity_id,
                content_version_id=version.id,
                image_asset_id=asset.id,
                trigger_condition="비가 내릴 때",
                order=order,
            )
        )
        await db_session.flush()
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    expected_order = [rows[3][1], rows[2][1], rows[1][1], rows[0][1], last.entity_id]
    assert fake.received_images == [
        (_object_bytes(thumbnail.storage_key), "image/png"),
        *((expected_thumbnails[entity_id], "image/webp") for entity_id in expected_order),
    ]
    assert fake.received_prompt is not None
    assert _image_label_lines(fake.received_prompt) == [
        "1. 대표 이미지",
        *(f"{n + 2}. 상황 이미지 {n + 1}" for n in range(len(expected_order))),
    ]


async def test_publish_screens_situational_original_when_its_thumbnail_is_missing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """READY 그림은 축소본을 갖는 것이 원칙이지만 옛 데이터엔 없을 수 있다. 없으면 원본으로 심사해 발행을 막지
    않는다 — 원본도 같은 그림이라 심사가 빠지는 그림은 없다."""
    content, _, _, image = await _publishable_character(db_session, db_client)
    asset = await db_session.get(Asset, image.image_asset_id)
    assert asset is not None
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.delete_object(Bucket=settings.s3_bucket_name, Key=build_thumbnail_key(asset.storage_key))

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_images is not None
    assert fake.received_images[1] == (_object_bytes(asset.storage_key), "image/png")


async def test_publish_does_not_fall_back_when_situational_thumbnail_read_fails_otherwise(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """원본으로 대신하는 것은 축소본이 **없을** 때뿐이다. 권한·저장소 장애 같은 다른 오류는 원본 읽기도 같이
    실패할 수 있는 상황이라 그대로 올려 발행을 멈춘다 — 심사는 불리지 않는다."""
    content, version, _, _ = await _publishable_character(db_session, db_client)

    def failing_download(key: str) -> bytes:
        if key.endswith("_thumb.webp"):
            raise ClientError({"Error": {"Code": "InternalError", "Message": "boom"}}, "GetObject")
        return _object_bytes(key)

    monkeypatch.setattr("api.content.router.download_object", failing_download)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        with pytest.raises(ClientError):
            await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert fake.received_prompt is None
    await db_session.refresh(version)
    assert version.published_at is None


async def _use_extensionless_key(db_session: AsyncSession, asset_id: uuid.UUID | None) -> bytes:
    """그림을 운영과 같은 확장자 없는 키(`assets/<용도>/<id>`)로 옮기고 원본 바이트를 돌려준다. 운영은 MIME 표에
    `image/webp` 가 없어 업로드 키에 확장자가 안 붙는다 — 키로 형식을 짐작하면 그림이 형식 없는 바이트로 간다."""
    asset = await db_session.get(Asset, asset_id)
    assert asset is not None
    data = _object_bytes(asset.storage_key)
    asset.storage_key = f"assets/situational-image/{uuid.uuid4()}"
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=data)
    await db_session.commit()
    return data


async def test_publish_character_sends_original_type_read_from_bytes_not_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """원본을 싣는 두 자리(대표 이미지, 축소본이 없는 상황 이미지)는 키 확장자가 아니라 바이트의 형식을 MIME
    으로 보낸다."""
    content, _, thumbnail, image = await _publishable_character(db_session, db_client)
    thumbnail_bytes = await _use_extensionless_key(db_session, thumbnail.id)
    situational_bytes = await _use_extensionless_key(db_session, image.image_asset_id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_images == [(thumbnail_bytes, "image/png"), (situational_bytes, "image/png")]


async def test_publish_character_rejects_with_fixed_reason_when_gemini_blocks_an_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """Gemini 가 자체 안전 기준으로 응답을 막으면 판정이 없다. 그래도 작가 입장에선 그림 때문에 발행이 거부된
    것이라 오류(500) 대신 이의제기할 수 있는 거부(400 `reason`)로 돌려준다. 막힌 범주는 알리지 않는다. 통과가
    아니므로 기억하지 않아 다음 발행은 다시 심사한다."""
    content, version, _, _ = await _publishable_character(db_session, db_client)
    blocking = _BlockedFilterLLMClient(PublishFilterResult(passed=True, reason=None))
    passing = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    try:
        _override_llm_client(blocking)
        blocked = await db_client.post(f"/contents/{content.id}/publish")
        await db_session.refresh(version)
        published_after_block = version.published_at
        _override_llm_client(passing)
        retried = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert blocked.status_code == 400
    assert blocked.json()["detail"] == {"reason": "첨부한 이미지 중 안전 기준에 걸리는 그림이 있어 발행할 수 없어요."}
    assert published_after_block is None
    assert retried.status_code == 200
    assert passing.calls == 1


async def test_publish_character_filter_prompt_carries_no_creator_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """발행 심사는 그림만 본다 — 작가가 쓴 글(이름·소개·예시 대화·프롬프트·상세 설명·상황 이미지 조건)은
    프롬프트에 하나도 실리지 않는다. 글은 공개 뒤 신고로만 걸러진다."""
    content, _, _, _ = await _publishable_character(db_session, db_client)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None
    for creator_text in ("아리아", "한 줄 소개", "안녕하세요", "반가워", "너는 아리아다.", "상세 설명", "사용자가 인사할 때"):
        assert creator_text not in fake.received_prompt


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
    assert new_detail.default_user_name == "여행자"

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


async def test_publish_story_rejects_ending_rules_on_stat_missing_from_their_setup_before_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """초안 저장이 막기 전에 저장된 초안이나 API 직접 호출도 발행에서 막는다. 규칙 몇 개가 어긋나도 키는 한 번만
    알리고(어느 규칙인지는 초안 저장이 경로로 알린다) 심사 모델은 부르지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _setup, _ending, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    # 맨 위 규칙과 그룹 안 규칙이 모두 이 스탯을 가리킨다.
    await db_session.delete(stat_def)
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["endings.statRules"]}
    assert fake.received_prompt is None


async def test_publish_story_rejects_stat_with_initial_value_outside_its_range_before_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """초안 저장은 범위가 모순된 스탯도 받아 주므로(자동저장이 멈추면 안 된다) 발행이 막는다. 라우터가 그 버전의
    스탯을 검증에 넘기는지 본다 — 심사 모델은 부르지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _setup, _ending, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    stat_def.initial_value = stat_def.max_value + 1
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["stats.range"]}
    assert fake.received_prompt is None


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
    content, version, _thumbnail, _setup, _ending, _stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    detail = await db_session.get(StoryVersionDetail, version.id)
    assert detail is not None
    detail.custom_prompt = "커스텀 지시문"
    detail.development_example = "옛 전개 예시"
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
    assert _image_label_lines(fake.received_prompt) == ["1. 대표 이미지"]
    for creator_text in (
        "잃어버린 도시",
        "한 줄 소개",
        "세계관 설명",
        "커스텀 지시문",
        "옛 전개 예시",
        "어서오세요",
        "용을 물리친다",
        "폭력 묘사는 암시로만 한다",
        "시작설정1",
        "프롤로그",
        "상세 설명",
    ):
        assert creator_text not in fake.received_prompt


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
    assert new_detail.default_user_name == "모험가"

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
            "defaultUserName": "고쳐 쓴 이름",
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
    assert draft_detail.default_user_name == "여행자"

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
            "defaultUserName": "고쳐 쓴 이름",
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
    assert draft_detail.default_user_name == "모험가"

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
    assert _bucket_keys() - keys_before == {blurred.storage_key, *build_variant_keys(blurred.storage_key)}
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


async def test_publish_story_reports_cell_whose_image_exceeds_the_pixel_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """칸 원본이 픽셀 상한을 넘으면(화면을 거치지 않고 올린 큰 그림) 블러를 만들지 않고, 이름 없는 500 이 아니라
    그 칸을 다시 올리라는 응답으로 발행을 멈춘다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    cell, image = await _add_named_media_cell(db_session, version.id, user.id, "민아", "교실", size=None)
    _upload_test_image(image.storage_key, size=(20, 30))
    _upload_test_thumbnail(image.storage_key)
    await db_session.commit()
    await _login_as(db_client, user.id)
    monkeypatch.setattr("api.assets.image_processing.MAX_DECODE_PIXELS", 20 * 30 - 1)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 502
    assert (resp.json()["detail"]["code"], resp.json()["detail"]["cellId"]) == (
        "MEDIA_BOOK_IMAGE_UNAVAILABLE",
        str(cell.entity_id),
    )
    await db_session.refresh(cell)
    assert cell.blurred_asset_id is None


async def test_publish_story_blurs_cells_concurrently_within_s3_connection_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """칸 블러본은 동시에 만든다 — 운영 저장소 왕복이 칸마다 붙어 50칸을 줄 세우면 발행이 1분을 넘긴다. 다만
    공유 저장소 클라이언트의 연결 수를 넘지 않게 한 번에 정해진 칸 수까지만 돌리고, 그 안에서 그림을 푸는 블러
    단계는 프로세스 전역 이미지 작업 한도까지만 겹친다(그림 한 장 디코드가 수백 MB 를 쓴다). 칸 수가 두 한도를
    넘어도 전부 끝나야 하고, 동시에 돌아도 칸마다 자기 그림의 블러본과 그 크기를 받아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    limit = min(_MEDIA_BOOK_S3_CONCURRENCY, IMAGE_WORK_CONCURRENCY)
    sized_cells: list[tuple[MediaBookCell, tuple[int, int]]] = []
    for index in range(_MEDIA_BOOK_S3_CONCURRENCY + 4):
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
        blurred_keys |= {blurred.storage_key, *build_variant_keys(blurred.storage_key)}
    assert _bucket_keys() - keys_before == blurred_keys
    assert len(blurred_keys) == 3 * len(sized_cells)


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


async def test_publish_story_filter_prompt_labels_media_book_cells_by_name_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """칸 그림은 프롬프트의 이미지 목록에서 인물·장면 이름 라벨로 가리킨다. 라벨은 실린 그림과 같은 축 순서이고
    줄 수도 그림 수와 같다. 칸의 상황 설명·해금 힌트는 싣지 않는다. 대화 노출 제외 칸(준/교실)의 라벨도 있다."""
    content, _, _, _ = await _story_with_media_cells(db_session, db_client)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_prompt is not None and fake.received_images is not None
    labels = _image_label_lines(fake.received_prompt)
    assert labels == ["1. 대표 이미지", "2. 미디어 북 민아·교실", "3. 미디어 북 민아·옥상", "4. 미디어 북 준·교실"]
    assert len(labels) == len(fake.received_images)
    for cell_text in ("창가에서 웃는다", "첫 만남", "난간에 기대 선다", "비 오는 날"):
        assert cell_text not in fake.received_prompt


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
    만들지 않는다. 이름 없는 500 이 아니라 다시 시도하라는 503 으로 알리고, 거부(`reason`)의 모양이 아니어야 화면이
    이의제기로 안내하지 않는다."""
    content, version, _, cells = await _story_with_media_cells(db_session, db_client)
    keys_before = _bucket_keys()

    fake = _FailingFilterLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "PUBLISH_SCREENING_UNAVAILABLE"
    assert "reason" not in resp.json()["detail"]
    assert fake.received_images is not None and len(fake.received_images) == 1 + len(cells)
    await db_session.refresh(version)
    assert version.published_at is None
    assert _bucket_keys() == keys_before


class _BlockedFilterLLMClient(_FakeLLMClient):
    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.received_images = images
        raise LLMPolicyViolationError("Gemini 가 안전 기준으로 응답을 막았다")


async def test_publish_story_rejects_with_fixed_reason_when_gemini_blocks_an_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """스토리도 같은 거부로 돌려주고, 거부된 발행이므로 칸 블러를 만들지 않는다."""
    content, version, _, _ = await _story_with_media_cells(db_session, db_client)
    keys_before = _bucket_keys()

    _override_llm_client(_BlockedFilterLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"reason": "첨부한 이미지 중 안전 기준에 걸리는 그림이 있어 발행할 수 없어요."}
    await db_session.refresh(version)
    assert version.published_at is None
    assert _bucket_keys() == keys_before


async def test_publish_story_sends_thumbnail_type_read_from_bytes_not_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """스토리 대표 이미지(원본)도 키가 아니라 바이트로 형식을 정한다. 칸 축소본은 늘 WebP 다."""
    content, _, thumbnail, cells = await _story_with_media_cells(db_session, db_client)
    thumbnail_bytes = await _use_extensionless_key(db_session, thumbnail.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.received_images is not None
    assert fake.received_images[0] == (thumbnail_bytes, "image/png")
    assert [mime_type for _, mime_type in fake.received_images[1:]] == ["image/webp"] * len(cells)


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
        keyword_notes=[],
        dangling_stat_rule_paths=[],
        stat_rules=[],
        situation_notes=[],
        dangling_situation_note_paths=[],
        stat_defs=[],
    )

    assert missing == expected


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        pytest.param([(None, None, None)], [], id="unset"),
        pytest.param([(None, "decrease", 3), (None, "increase", 1)], [], id="judged-with-options"),
        pytest.param([(-1, None, None), (-1, "both", None)], [], id="counter-without-options"),
        pytest.param([(-1, "decrease", None)], ["stats.changeLimitWithCounter"], id="counter-with-direction"),
        pytest.param([(-1, "both", 3)], ["stats.changeLimitWithCounter"], id="counter-with-step"),
        pytest.param([(None, "both", 0)], ["stats.maxChangePerTurn"], id="zero-step"),
        pytest.param([(None, "both", -2), (None, "both", 0)], ["stats.maxChangePerTurn"], id="several-reported-once"),
        pytest.param(
            [(2, "increase", 0)], ["stats.changeLimitWithCounter", "stats.maxChangePerTurn"], id="both-problems"
        ),
    ],
)
def test_validate_story_publish_stat_change_options(
    options: list[tuple[int | None, StatChangeDirection | None, int | None]], expected: list[str]
) -> None:
    """턴당 변화가 있는 스탯은 판정을 받지 않아 방향·폭이 아무 일도 하지 않는다 — 걸려 있으면 발행이 막는다. 폭은 양의
    정수만(빈 값이 제한 없음). 어긋난 스탯이 몇 개든 키는 한 번만 알린다."""
    content, version, detail, setups = _valid_story_rows()

    missing = validate_story_publish(
        content,
        version,
        detail,
        setups,
        {},
        media_book_people=[],
        media_book_scenes=[],
        media_book_cells=[],
        keyword_notes=[],
        dangling_stat_rule_paths=[],
        stat_rules=[],
        situation_notes=[],
        dangling_situation_note_paths=[],
        stat_defs=[
            StatDef(
                min_value=0,
                max_value=10,
                initial_value=5,
                per_turn_delta=delta,
                change_direction=direction,
                max_change_per_turn=step,
            )
            for delta, direction, step in options
        ],
    )

    assert missing == expected


def _stat_def_fields(stat_def: StatDef) -> tuple[object, ...]:
    return (
        stat_def.name,
        stat_def.icon,
        stat_def.color,
        stat_def.min_value,
        stat_def.max_value,
        stat_def.initial_value,
        stat_def.unit,
        stat_def.description,
        stat_def.per_turn_delta,
        stat_def.change_direction,
        stat_def.max_change_per_turn,
        stat_def.order,
    )


async def test_publish_and_reset_clone_every_stat_def_field(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """발행과 편집 취소는 스탯을 생성자에 필드를 하나씩 나열해 복사한다. 하나를 빠뜨리면 그 필드가 조용히 기본값으로
    돌아가므로(방향은 양방향, 폭·턴당 변화는 없음으로), 모든 필드를 기본값이 아닌 값으로 채워 두고 복사본과 맞춰 본다.
    턴당 변화와 방향·폭은 발행에서 함께 쓸 수 없으므로 스탯 둘로 나눠 싣는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, setup, _, judged = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    judged.unit = "일"
    judged.change_direction = "decrease"
    judged.max_change_per_turn = 7
    counter = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="산소",
        icon="wind",
        color="sky",
        min_value=-5,
        max_value=95,
        initial_value=90,
        unit="%",
        description="매 턴 준다",
        per_turn_delta=-3,
        order=1,
    )
    db_session.add(counter)
    await db_session.flush()
    expected = {stat.entity_id: _stat_def_fields(stat) for stat in (judged, counter)}
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert publish_resp.status_code == 200

    content_id = content.id

    async def _draft_copies() -> dict[uuid.UUID, tuple[object, ...]]:
        copies = (
            await db_session.scalars(
                sa.select(StatDef)
                .join(StartingSetup, StartingSetup.id == StatDef.starting_setup_id)
                .join(ContentVersion, ContentVersion.id == StartingSetup.content_version_id)
                .where(ContentVersion.content_id == content_id, ContentVersion.published_at.is_(None))
                .execution_options(populate_existing=True)
            )
        ).all()
        return {stat.entity_id: _stat_def_fields(stat) for stat in copies}

    assert await _draft_copies() == expected

    reset_resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert reset_resp.status_code == 204
    assert await _draft_copies() == expected


async def test_publish_and_reset_clone_stat_rules_onto_the_new_stat(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """스탯 규칙은 스탯을 물리 FK 로 가리킨다. 발행과 편집 취소는 규칙을 entity_id·조건·폭·순서 그대로 옮기되 새 초안의
    스탯 행에 달아야 한다 — 옛 스탯 id 를 그대로 쓰면 초안 규칙이 발행본 스탯에 붙고, 빠뜨리면 다음 초안에서 규칙이
    사라진다. 판정 스탯에 단 규칙은 발행을 막지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, _, _, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    rules = [
        StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def.id, condition="감싸 준다", delta=5, order=1),
        StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def.id, condition="거짓말이 들킨다", delta=-3, order=0),
    ]
    db_session.add_all(rules)
    expected = sorted((rule.entity_id, rule.condition, rule.delta, rule.order) for rule in rules)
    stat_entity_id = stat_def.entity_id
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert publish_resp.status_code == 200

    content_id = content.id

    async def _rules_by_version() -> dict[bool, list[tuple[object, ...]]]:
        rows = (
            await db_session.execute(
                sa.select(ContentVersion.published_at.is_not(None), StatDef.entity_id, StatRule)
                .join(StatDef, StatDef.id == StatRule.stat_def_id)
                .join(StartingSetup, StartingSetup.id == StatDef.starting_setup_id)
                .join(ContentVersion, ContentVersion.id == StartingSetup.content_version_id)
                .where(ContentVersion.content_id == content_id)
                .execution_options(populate_existing=True)
            )
        ).all()
        result: dict[bool, list[tuple[object, ...]]] = {}
        for published, owner_entity_id, rule in rows:
            assert owner_entity_id == stat_entity_id
            result.setdefault(published, []).append((rule.entity_id, rule.condition, rule.delta, rule.order))
        return {published: sorted(items) for published, items in result.items()}

    assert await _rules_by_version() == {True: expected, False: expected}

    reset_resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert reset_resp.status_code == 204
    assert await _rules_by_version() == {True: expected, False: expected}


async def test_publish_story_rejects_stat_rules_on_counter_stat_before_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """턴당 변화가 있는 스탯은 판정을 받지 않아 규칙이 발동할 일이 없는데 작가는 걸었다고 믿게 된다. 초안 저장은 받아
    주므로 발행이 막는다 — 라우터가 그 버전의 규칙 행을 검증에 넘기는지 본다. 심사 모델은 부르지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, _, _, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    stat_def.per_turn_delta = -1
    db_session.add(StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def.id, condition="쉰다", delta=1, order=0))
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["stats.rulesWithCounter"]}
    assert fake.received_prompt is None


async def test_publish_and_reset_clone_ending_priority_stat(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """발행과 편집 취소는 엔딩을 생성자에 필드를 하나씩 나열해 복사한다. 우선 스탯을 빠뜨리면 새 초안에서 조용히 비워져
    다음 발행부터 루트 비교가 사라진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, _, ending, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    ending.priority_stat_def_entity_id = stat_def.entity_id
    ending_entity_id, stat_entity_id = ending.entity_id, stat_def.entity_id
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert publish_resp.status_code == 200

    content_id = content.id

    async def _draft_priority_stats() -> list[uuid.UUID | None]:
        copies = (
            await db_session.scalars(
                sa.select(Ending)
                .join(StartingSetup, StartingSetup.id == Ending.starting_setup_id)
                .join(ContentVersion, ContentVersion.id == StartingSetup.content_version_id)
                .where(
                    ContentVersion.content_id == content_id,
                    ContentVersion.published_at.is_(None),
                    Ending.entity_id == ending_entity_id,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        return [copy.priority_stat_def_entity_id for copy in copies]

    assert await _draft_priority_stats() == [stat_entity_id]

    reset_resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert reset_resp.status_code == 204
    assert await _draft_priority_stats() == [stat_entity_id]


async def test_publish_story_rejects_ending_priority_stat_missing_from_its_setup_before_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """옛 번들은 우선 스탯을 보내지 않아 저장이 기존 값을 그대로 두므로, 그 화면에서 스탯을 지우면 지운 스탯을 가리키는
    우선 스탯이 저장 검사를 지나 남는다. 발행이 엔딩 규칙과 같은 키로 막고 심사 모델은 부르지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, _, ending, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    ending.priority_stat_def_entity_id = uuid.uuid4()
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": ["endings.statRules"]}
    assert fake.received_prompt is None


@pytest.mark.parametrize(
    ("per_turn_delta", "change_direction", "max_change_per_turn", "expected"),
    [
        pytest.param(-1, "decrease", None, ["stats.changeLimitWithCounter"], id="counter-with-direction"),
        pytest.param(None, "both", 0, ["stats.maxChangePerTurn"], id="zero-step"),
    ],
)
async def test_publish_story_rejects_stat_change_options_before_filter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    s3_bucket: None,
    per_turn_delta: int | None,
    change_direction: StatChangeDirection,
    max_change_per_turn: int | None,
    expected: list[str],
) -> None:
    """초안 저장은 방향·폭이 어긋난 스탯도 받아 주므로(자동저장이 멈추면 안 된다) 발행이 막는다. 라우터가 그 버전의
    스탯 행(새 컬럼 포함)을 검증에 넘기는지 본다 — 심사 모델은 부르지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, _setup, _ending, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    stat_def.per_turn_delta = per_turn_delta
    stat_def.change_direction = change_direction
    stat_def.max_change_per_turn = max_change_per_turn
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert resp.status_code == 400
    assert resp.json()["detail"] == {"missingFields": expected}
    assert fake.received_prompt is None


def _json_rule(stat_id: uuid.UUID, *, operator: str = "lte", threshold: float = 7) -> dict[str, object]:
    return {
        "kind": "rule",
        "id": str(uuid.uuid4()),
        "stat_id": str(stat_id),
        "operator": operator,
        "threshold": threshold,
        "next_op": None,
    }


def _situation_note_fields(note: SituationNote) -> tuple[object, ...]:
    return (note.name, note.info_text, note.order, note.condition_rules)


async def test_publish_and_reset_clone_every_situation_note_field(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """발행과 편집 취소는 상황 노트를 생성자에 필드를 하나씩 나열해 복사한다. 하나를 빠뜨리면 그 필드가 조용히 기본값으로
    돌아가므로(이름은 빈 글, 순서는 0, 조건은 빈 목록) 모든 필드를 기본값이 아닌 값으로 채워 두고 복사본과 맞춰 본다.
    노트는 복사본 시작설정 밑에 붙어야 하고, 조건의 스탯 참조는 entity_id 라 값 그대로다. 편집 취소는 노트가 든 초안을
    지우고 다시 복제하므로 노트를 시작설정보다 먼저 지우는 경로도 함께 지난다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, setup, _, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    group = {
        "kind": "group",
        "id": str(uuid.uuid4()),
        "next_op": None,
        "rules": [_json_rule(stat_def.entity_id, operator="gte", threshold=3)],
    }
    notes = [
        SituationNote(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name=f"노트{order}",
            info_text=f"상황 {order}",
            order=order,
            condition_rules=[{**_json_rule(stat_def.entity_id), "next_op": "or"}, group],
        )
        for order in (1, 2)
    ]
    db_session.add_all(notes)
    await db_session.flush()
    expected = {note.entity_id: (setup.entity_id, _situation_note_fields(note)) for note in notes}
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert publish_resp.status_code == 200

    content_id = content.id

    async def _draft_copies() -> dict[uuid.UUID, tuple[object, ...]]:
        rows = (
            await db_session.execute(
                sa.select(StartingSetup.entity_id, SituationNote)
                .join(StartingSetup, StartingSetup.id == SituationNote.starting_setup_id)
                .join(ContentVersion, ContentVersion.id == StartingSetup.content_version_id)
                .where(ContentVersion.content_id == content_id, ContentVersion.published_at.is_(None))
                .execution_options(populate_existing=True)
            )
        ).all()
        return {note.entity_id: (setup_entity_id, _situation_note_fields(note)) for setup_entity_id, note in rows}

    assert await _draft_copies() == expected

    reset_resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert reset_resp.status_code == 204
    assert await _draft_copies() == expected


@pytest.mark.parametrize(
    ("notes", "dangling", "expected"),
    [
        pytest.param([("본문", 1)], [], [], id="valid"),
        pytest.param([("본문", 0)], [], ["situationNotes.emptyConditionRules"], id="no-rules"),
        pytest.param([("본문", -1)], [], ["situationNotes.emptyConditionRules"], id="only-an-empty-group"),
        pytest.param([("  \n", 1)], [], ["situationNotes.infoText"], id="blank-text"),
        pytest.param(
            [("본문", 1)],
            ["startingSetups[0].situationNotes[0].conditionRules[0].statId"],
            ["situationNotes.conditionRules"],
            id="dangling-stat",
        ),
        pytest.param(
            [("", 0), (" ", 0), ("본문", 1)],
            ["a", "b"],
            ["situationNotes.emptyConditionRules", "situationNotes.infoText", "situationNotes.conditionRules"],
            id="each-reported-once",
        ),
    ],
)
def test_validate_story_publish_situation_notes(
    notes: list[tuple[str, int]], dangling: list[str], expected: list[str]
) -> None:
    """조건 규칙이 없는 노트(빈 그룹만 있는 노트 포함)는 상시 지시가 되므로 막는다 — 그 자리는 스토리 설정이다. 본문이
    공백뿐인 노트는 실려도 빈 줄이다. 없는 스탯을 가리키는 조건은 영영 참이 될 수 없다. 어긋난 노트가 몇 개든 키는 한
    번씩이고, 엔딩의 키(`endings.statRules`)와는 따로다."""
    content, version, detail, setups = _valid_story_rows()
    stat_id = uuid.uuid4()

    def rules(count: int) -> list[dict[str, object]]:
        if count < 0:
            return [{"kind": "group", "id": str(uuid.uuid4()), "next_op": None, "rules": []}]
        return [_json_rule(stat_id) for _ in range(count)]

    missing = validate_story_publish(
        content,
        version,
        detail,
        setups,
        {},
        media_book_people=[],
        media_book_scenes=[],
        media_book_cells=[],
        keyword_notes=[],
        dangling_stat_rule_paths=[],
        stat_defs=[],
        stat_rules=[],
        situation_notes=[SituationNote(info_text=text, condition_rules=rules(count)) for text, count in notes],
        dangling_situation_note_paths=dangling,
    )

    assert missing == expected


async def test_publish_story_rejects_situation_notes_before_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """초안 저장은 조건 없는 노트·빈 본문을 받아 주고(자동저장이 멈추면 안 된다), 스탯을 지운 뒤 남은 조건은 옛 화면의
    저장으로도 생길 수 있으므로 발행이 막는다. 라우터가 그 버전의 시작설정마다 노트를 읽어 검증에 넘기는지 본다 — 엔딩
    키는 나오지 않고 심사 모델은 부르지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _version, _thumbnail, setup, _ending, stat_def = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    db_session.add_all(
        [
            SituationNote(entity_id=uuid.uuid4(), starting_setup_id=setup.id, info_text="조건 없음", order=0),
            SituationNote(
                entity_id=uuid.uuid4(),
                starting_setup_id=setup.id,
                info_text=" ",
                order=1,
                condition_rules=[_json_rule(stat_def.entity_id)],
            ),
            SituationNote(
                entity_id=uuid.uuid4(),
                starting_setup_id=setup.id,
                info_text="지워진 스탯",
                order=2,
                condition_rules=[_json_rule(uuid.uuid4())],
            ),
        ]
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
    assert resp.json()["detail"] == {
        "missingFields": [
            "situationNotes.emptyConditionRules",
            "situationNotes.infoText",
            "situationNotes.conditionRules",
        ]
    }
    assert fake.received_prompt is None


def _keyword_note_fields(note: KeywordNote) -> tuple[object, ...]:
    return (note.info_text, note.trigger_keywords, note.name, note.order, note.exclude_keywords, note.sticky_turns, note.always_on)


async def test_publish_and_reset_clone_every_keyword_note_field(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """발행과 편집 취소는 노트를 생성자에 필드를 하나씩 나열해 복사한다. 하나를 빠뜨리면 그 필드가 조용히 기본값으로
    돌아가므로, 모든 필드를 기본값이 아닌 값으로 채워 두고 복사본과 맞춰 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    note = KeywordNote(
        entity_id=uuid.uuid4(),
        content_version_id=version.id,
        info_text="상시 정보",
        trigger_keywords=["열쇠"],
        name="목록 이름",
        order=3,
        exclude_keywords=["회상"],
        sticky_turns=2,
        always_on=True,
    )
    db_session.add(note)
    await db_session.flush()
    expected = _keyword_note_fields(note)
    await db_session.commit()
    await _login_as(db_client, user.id)

    _override_llm_client(_FakeLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        publish_resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert publish_resp.status_code == 200

    content_id, note_entity_id = content.id, note.entity_id

    async def _draft_copy() -> KeywordNote:
        copy = await db_session.scalar(
            sa.select(KeywordNote)
            .join(ContentVersion, ContentVersion.id == KeywordNote.content_version_id)
            .where(
                ContentVersion.content_id == content_id,
                ContentVersion.published_at.is_(None),
                KeywordNote.entity_id == note_entity_id,
            )
            .execution_options(populate_existing=True)
        )
        assert copy is not None
        return copy

    assert _keyword_note_fields(await _draft_copy()) == expected

    reset_resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert reset_resp.status_code == 204
    assert _keyword_note_fields(await _draft_copy()) == expected


async def test_publish_rejects_keyword_note_without_keywords_unless_always_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """자동저장은 키워드 없는 노트를 받아 준다(노트 추가 직후의 빈 노트). 키워드가 없으면 상시가 아닌 노트는 열릴 길이
    없으니 발행이 막는다 — 심사(LLM 호출)까지 가지 않는다. 상시 노트는 키워드 없이 매 턴 실리므로 통과한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, version, _, _, _, _ = await _make_publishable_story_draft(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(), content_version_id=version.id, info_text="상시", trigger_keywords=[], always_on=True
        )
    )
    keywordless = KeywordNote(
        entity_id=uuid.uuid4(), content_version_id=version.id, info_text="키워드 없음", trigger_keywords=[]
    )
    db_session.add(keywordless)
    await db_session.commit()
    await _login_as(db_client, user.id)

    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    _override_llm_client(fake)
    try:
        rejected = await db_client.post(f"/contents/{content.id}/publish")
        assert rejected.status_code == 400
        assert rejected.json()["detail"] == {"missingFields": ["keywordNotes.triggerKeywords"]}
        assert fake.received_prompt is None

        await db_session.delete(keywordless)
        await db_session.commit()
        accepted = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()
    assert accepted.status_code == 200


@pytest.mark.parametrize(
    ("notes", "expected"),
    [
        pytest.param([], [], id="no-notes"),
        pytest.param([("정보", ["단서"], False)], [], id="complete"),
        pytest.param([("정보", [], True)], [], id="always-on-without-keywords"),
        pytest.param([("정보", [], False)], ["keywordNotes.triggerKeywords"], id="no-keywords"),
        # 저장 검증이 생기기 전에 저장된 공백 키워드는 키워드 구실을 못 하므로 없는 것과 같이 본다.
        pytest.param([("정보", [" "], False)], ["keywordNotes.triggerKeywords"], id="blank-keywords-only"),
        pytest.param([(" \n", ["단서"], False)], ["keywordNotes.infoText"], id="blank-info"),
        pytest.param([(" ", [], True)], ["keywordNotes.infoText"], id="always-on-blank-info"),
        pytest.param(
            [("", [], False), ("", [], False)],
            ["keywordNotes.triggerKeywords", "keywordNotes.infoText"],
            id="several-notes-reported-once-each",
        ),
    ],
)
def test_validate_story_publish_keyword_notes(
    notes: list[tuple[str, list[str], bool]], expected: list[str]
) -> None:
    """노트 하나하나가 아니라 키 하나씩만 알린다 — 어느 노트인지는 빌더 폼 검증이 노트 자리에서 먼저 보여 준다."""
    content, version, detail, setups = _valid_story_rows()

    missing = validate_story_publish(
        content,
        version,
        detail,
        setups,
        {},
        media_book_people=[],
        media_book_scenes=[],
        media_book_cells=[],
        keyword_notes=[
            KeywordNote(info_text=info, trigger_keywords=keywords, always_on=always_on)
            for info, keywords, always_on in notes
        ],
        dangling_stat_rule_paths=[],
        stat_rules=[],
        situation_notes=[],
        dangling_situation_note_paths=[],
        stat_defs=[],
    )

    assert missing == expected


@pytest.mark.parametrize(
    ("ranges", "expected"),
    [
        pytest.param([(0, 100, 50)], [], id="inside"),
        pytest.param([(0, 100, 0), (0, 100, 100)], [], id="initial-on-both-bounds"),
        pytest.param([(-10, -1, -5)], [], id="negative-range"),
        pytest.param([(50, 50, 50)], ["stats.range"], id="min-equals-max"),
        pytest.param([(100, 0, 50)], ["stats.range"], id="min-above-max"),
        pytest.param([(0, 100, 101)], ["stats.range"], id="initial-above-max"),
        pytest.param([(0, 100, -1)], ["stats.range"], id="initial-below-min"),
        pytest.param([(0, 100, 101), (100, 0, 500), (0, 10, 5)], ["stats.range"], id="several-reported-once"),
    ],
)
def test_validate_story_publish_stat_ranges(ranges: list[tuple[int, int, int]], expected: list[str]) -> None:
    """최소 < 최대, 최소 ≤ 초기 ≤ 최대. 경계(초기값이 최소·최대와 같음)는 통과하고, 어긋난 스탯이 몇 개든 키는 한 번만
    알린다 — 어느 칸인지는 빌더 폼 검증이 그 칸에서 먼저 보여 준다."""
    content, version, detail, setups = _valid_story_rows()

    missing = validate_story_publish(
        content,
        version,
        detail,
        setups,
        {},
        media_book_people=[],
        media_book_scenes=[],
        media_book_cells=[],
        keyword_notes=[],
        dangling_stat_rule_paths=[],
        stat_rules=[],
        situation_notes=[],
        dangling_situation_note_paths=[],
        stat_defs=[
            StatDef(min_value=low, max_value=high, initial_value=initial) for low, high, initial in ranges
        ],
    )

    assert missing == expected


# --- 무변경 재발행의 심사 생략 ---
#
# 심사 LLM 은 발행마다 부르면 같은 입력에 같은 값을 다시 내는 호출이 된다. 직전에 통과한 심사와 입력(콘텐츠·활성
# 심사 세트·실제 모델·렌더된 심사 문장·이미지 바이트와 형식의 순서)이 전부 같을 때만 건너뛴다. 하나라도 다르거나
# 기억을 확인할 수 없으면 심사한다 — 생략이 틀리면 심사 안 된 콘텐츠가 공개된다.


async def _draft_detail(db_session: AsyncSession, content: Content) -> CharacterVersionDetail:
    """발행이 열어 둔 다음 편집용 초안의 캐릭터 상세."""
    detail = await db_session.scalar(
        sa.select(CharacterVersionDetail)
        .join(ContentVersion, ContentVersion.id == CharacterVersionDetail.content_version_id)
        .where(ContentVersion.content_id == content.id, ContentVersion.published_at.is_(None))
    )
    assert detail is not None
    return detail


async def _publish_twice(
    db_client: httpx.AsyncClient, content: Content, fake: _FakeLLMClient, between: Any = None
) -> httpx.Response:
    """첫 발행이 통과한 것을 확인하고, `between` 을 돌린 뒤 다시 발행한 응답을 돌려준다."""
    _override_llm_client(fake)
    try:
        first = await db_client.post(f"/contents/{content.id}/publish")
        assert first.status_code == 200
        if between is not None:
            await between()
        return await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()


async def _publishable_character(
    db_session: AsyncSession, db_client: httpx.AsyncClient
) -> tuple[Content, ContentVersion, Asset, SituationalImage]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    drafted = await _make_publishable_character_draft(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return drafted


async def test_republish_unchanged_character_skips_filter_and_still_publishes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, caplog: pytest.LogCaptureFixture
) -> None:
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    with caplog.at_level(logging.WARNING, logger="api.content.router"):
        resp = await _publish_twice(db_client, content, fake)

    assert resp.status_code == 200
    assert resp.json()["versionNumber"] == 2
    assert fake.calls == 1
    skipped = [record.getMessage() for record in caplog.records if "publish_filter_skipped" in record.getMessage()]
    assert len(skipped) == 1
    assert str(content.id) not in skipped[0] and str(content.creator_user_id) not in skipped[0]
    await db_session.refresh(content)
    published = await db_session.get(ContentVersion, content.current_published_version_id)
    assert published is not None and published.version_number == 2


async def test_republish_character_with_only_text_changed_skips_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """심사는 그림만 보므로 글만 고친 재발행은 렌더된 심사 입력이 같아 지난 통과를 그대로 쓴다."""
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def change_one_letter() -> None:
        detail = await _draft_detail(db_session, content)
        detail.character_prompt = "너는 아리아야."
        await db_session.commit()

    resp = await _publish_twice(db_client, content, fake, change_one_letter)

    assert resp.status_code == 200
    assert resp.json()["versionNumber"] == 2
    assert fake.calls == 1


@pytest.mark.parametrize("slot", ["thumbnail-original", "situational-thumbnail"])
async def test_republish_character_with_replaced_image_bytes_rescreens(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, slot: str
) -> None:
    """저장 위치는 그대로 두고 심사가 보는 그 자리의 그림만 바뀌어도(시드 이미지 교체 등) 다시 심사한다. 심사가
    보는 것은 대표 이미지의 원본과 상황 이미지의 축소본이라 각각 그 객체를 바꾼다."""
    content, _, thumbnail, image = await _publishable_character(db_session, db_client)
    situational_asset = await db_session.get(Asset, image.image_asset_id)
    assert situational_asset is not None
    thumbnail_key, situational_key = thumbnail.storage_key, situational_asset.storage_key
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def replace_bytes() -> None:
        if slot == "thumbnail-original":
            _upload_test_image(thumbnail_key, size=(24, 24))
        else:
            _upload_test_thumbnail(situational_key, color=(1, 2, 3))

    resp = await _publish_twice(db_client, content, fake, replace_bytes)

    assert resp.status_code == 200
    assert fake.calls == 2


async def test_republish_character_with_swapped_image_roles_rescreens(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """대표 이미지와 상황 이미지의 그림을 맞바꾸면 대표 자리는 다른 그림의 원본을, 상황 자리는 다른 그림의
    축소본을 보게 되므로 다시 심사한다. 두 그림의 원본·축소본을 모두 서로 다르게 둬 두 자리 모두에서 차이가 난다."""
    content, _, thumbnail, image = await _publishable_character(db_session, db_client)
    situational_asset = await db_session.get(Asset, image.image_asset_id)
    assert situational_asset is not None
    _upload_test_image(situational_asset.storage_key, size=(24, 24))
    _upload_test_thumbnail(situational_asset.storage_key, color=(1, 2, 3))
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def swap() -> None:
        detail = await _draft_detail(db_session, content)
        draft_image = await db_session.scalar(
            sa.select(SituationalImage).where(SituationalImage.content_version_id == detail.content_version_id)
        )
        assert draft_image is not None
        detail.thumbnail_asset_id, draft_image.image_asset_id = situational_asset.id, thumbnail.id
        await db_session.commit()

    resp = await _publish_twice(db_client, content, fake, swap)

    assert resp.status_code == 200
    assert fake.calls == 2


async def test_republish_character_after_publish_filter_set_change_rescreens(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """문안이 같아도 심사 세트를 새로 게시하면 다시 심사한다 — 게시는 운영자가 심사 기준을 다시 세운 일이다."""
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def republish_same_set() -> None:
        active = await db_session.scalar(
            sa.select(PromptSet)
            .where(PromptSet.status == "published", PromptSet.lane == "publish_filter")
            .order_by(PromptSet.published_at.desc())
            .limit(1)
        )
        assert active is not None
        copy = PromptSet(
            version=f"copy-{uuid.uuid4()}",
            status="published",
            lane="publish_filter",
            user_label=active.user_label,
            story_assistant_label=active.story_assistant_label,
            story_example_label=active.story_example_label,
            character_assistant_label=active.character_assistant_label,
            published_at=sa.func.now(),
        )
        db_session.add(copy)
        await db_session.flush()
        sections = (
            await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == active.id))
        ).all()
        db_session.add_all(
            PromptSection(
                prompt_set_id=copy.id,
                channel=section.channel,
                scope=section.scope,
                slot=section.slot,
                variant=section.variant,
                body=section.body,
                conditional=section.conditional,
                order=section.order,
            )
            for section in sections
        )
        await db_session.commit()

    first_prompt: list[str | None] = []

    async def remember_prompt_then_republish_set() -> None:
        first_prompt.append(fake.received_prompt)
        await republish_same_set()

    resp = await _publish_twice(db_client, content, fake, remember_prompt_then_republish_set)

    assert resp.status_code == 200
    assert fake.calls == 2
    assert fake.received_prompt == first_prompt[0]


@pytest.mark.parametrize(
    "setting",
    [
        pytest.param("gemini_publish_filter_model_name", id="publish-filter-model"),
        pytest.param("gemini_model_name", id="default-model"),
    ],
)
async def test_republish_character_after_model_setting_change_rescreens(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    s3_bucket: None,
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
) -> None:
    """심사를 실제로 맡는 모델이 바뀌면 옛 모델의 통과로 건너뛰지 않는다. 심사 전용 설정이 비어 있으면 기본
    모델이 심사를 맡으므로 기본 모델 설정이 바뀌어도 다시 심사한다."""
    monkeypatch.setattr(settings, "gemini_publish_filter_model_name", None)
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def change_model() -> None:
        monkeypatch.setattr(settings, setting, "gemini-other-model")

    resp = await _publish_twice(db_client, content, fake, change_model)

    assert resp.status_code == 200
    assert fake.calls == 2


async def test_republish_character_with_unrelated_model_setting_change_still_skips(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """심사 전용 모델이 정해져 있으면 기본 모델이 바뀌어도 심사 모델은 그대로라 건너뛴다 — 키가 설정값이 아니라
    실제로 쓸 모델을 본다는 확인이다."""
    monkeypatch.setattr(settings, "gemini_publish_filter_model_name", "gemini-filter-model")
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def change_default_model() -> None:
        monkeypatch.setattr(settings, "gemini_model_name", "gemini-other-model")

    resp = await _publish_twice(db_client, content, fake, change_default_model)

    assert resp.status_code == 200
    assert fake.calls == 1


async def test_identical_character_drafts_do_not_share_a_pass(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """같은 사람이 같은 글·그림으로 작품을 둘 만들어도 각자 심사한다 — 통과는 작품 하나에 묶인다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    first, _, _, _ = await _make_publishable_character_draft(db_session, creator_user_id=user.id, genre_id=genre.id)
    second, _, _, _ = await _make_publishable_character_draft(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    _override_llm_client(fake)
    try:
        first_resp = await db_client.post(f"/contents/{first.id}/publish")
        first_prompt, first_images = fake.received_prompt, fake.received_images
        second_resp = await db_client.post(f"/contents/{second.id}/publish")
    finally:
        _clear_llm_override()

    assert (first_resp.status_code, second_resp.status_code) == (200, 200)
    assert (fake.received_prompt, fake.received_images) == (first_prompt, first_images)
    assert fake.calls == 2


async def test_rejected_publish_is_not_remembered(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    content, _, _, _ = await _publishable_character(db_session, db_client)
    rejecting = _FakeLLMClient(PublishFilterResult(passed=False, reason="부적절"))
    passing = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    try:
        _override_llm_client(rejecting)
        rejected = await db_client.post(f"/contents/{content.id}/publish")
        _override_llm_client(passing)
        retried = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert (rejected.status_code, retried.status_code) == (400, 200)
    assert passing.calls == 1


async def test_failed_filter_call_is_not_remembered(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    content, _, _, _ = await _publishable_character(db_session, db_client)
    passing = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    try:
        _override_llm_client(_FailingFilterLLMClient(PublishFilterResult(passed=True, reason=None)))
        failed = await db_client.post(f"/contents/{content.id}/publish")
        _override_llm_client(passing)
        retried = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert failed.status_code == 503
    assert retried.status_code == 200
    assert passing.calls == 1


async def _raise_redis_error(*_args: object, **_kwargs: object) -> object:
    raise RedisError("connection refused")


async def _hang(*_args: object, **_kwargs: object) -> object:
    await asyncio.sleep(30)
    raise AssertionError("unreachable")  # pragma: no cover - the timeout cancels the sleep


@pytest.mark.parametrize(
    "failure", [pytest.param(_raise_redis_error, id="redis-error"), pytest.param(_hang, id="hang")]
)
async def test_republish_screens_when_pass_cannot_be_read(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    s3_bucket: None,
    monkeypatch: pytest.MonkeyPatch,
    failure: Any,
) -> None:
    """통과 기억을 읽지 못하면 없는 것으로 보고 심사한다 — 생략은 통과를 확인했을 때만이다."""
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def break_reads() -> None:
        monkeypatch.setattr(publish_filter_memo, "redis_client", SimpleNamespace(exists=failure, set=redis_client.set))

    resp = await _publish_twice(db_client, content, fake, break_reads)

    assert resp.status_code == 200
    assert fake.calls == 2


@pytest.mark.parametrize(
    "failure", [pytest.param(_raise_redis_error, id="redis-error"), pytest.param(_hang, id="hang")]
)
async def test_publish_succeeds_when_pass_cannot_be_written(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    s3_bucket: None,
    monkeypatch: pytest.MonkeyPatch,
    failure: Any,
) -> None:
    """기억을 남기지 못해도 이번 발행은 그대로 성공하고, 다음 발행은 다시 심사한다."""
    monkeypatch.setattr(publish_filter_memo, "redis_client", SimpleNamespace(exists=redis_client.exists, set=failure))
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    resp = await _publish_twice(db_client, content, fake)

    assert resp.status_code == 200
    assert fake.calls == 2


async def test_republish_unchanged_story_skips_filter_and_still_blurs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """통과 뒤 칸 블러본을 만들지 못해 멈춘 발행을 다시 시도하면 심사는 건너뛰고 블러·발행은 끝까지 간다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, _, _, _ = await _make_publishable_story_draft(db_session, creator_user_id=user.id, genre_id=genre.id)
    version = await db_session.scalar(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    assert version is not None
    late = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(late)
    await db_session.flush()
    _upload_test_thumbnail(late.storage_key)
    cell = await _add_media_book_cell(db_session, version.id, late.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    _override_llm_client(fake)
    try:
        stalled = await db_client.post(f"/contents/{content.id}/publish")
        _upload_test_image(late.storage_key)
        retried = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert (stalled.status_code, retried.status_code) == (502, 200)
    assert fake.calls == 1
    await db_session.refresh(cell)
    await db_session.refresh(version)
    assert cell.blurred_asset_id is not None
    assert version.version_number == 1


async def test_republish_story_with_only_text_changed_skips_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """심사는 그림만 보므로 글만 고친 재발행은 렌더된 심사 입력이 같아 지난 통과를 그대로 쓴다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, _, _, _ = await _make_publishable_story_draft(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def change_one_letter() -> None:
        detail = await db_session.scalar(
            sa.select(StoryVersionDetail)
            .join(ContentVersion, ContentVersion.id == StoryVersionDetail.content_version_id)
            .where(ContentVersion.content_id == content.id, ContentVersion.published_at.is_(None))
        )
        assert detail is not None
        detail.rules = "폭력 묘사는 암시로만 한다!"
        await db_session.commit()

    resp = await _publish_twice(db_client, content, fake, change_one_letter)

    assert resp.status_code == 200
    assert resp.json()["versionNumber"] == 2
    assert fake.calls == 1


async def test_republish_story_with_media_book_name_changed_rescreens(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """칸 라벨에는 인물·장면 이름이 들어가므로, 그림이 같아도 이름을 바꾸면 심사 입력이 달라져 다시 심사한다."""
    content, _, _, _ = await _story_with_media_cells(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    async def rename_person() -> None:
        person = await db_session.scalar(
            sa.select(MediaBookPerson)
            .join(ContentVersion, ContentVersion.id == MediaBookPerson.content_version_id)
            .where(
                ContentVersion.content_id == content.id,
                ContentVersion.published_at.is_(None),
                MediaBookPerson.name == "준",
            )
        )
        assert person is not None
        person.name = "준호"
        await db_session.commit()

    resp = await _publish_twice(db_client, content, fake, rename_person)

    assert resp.status_code == 200
    assert fake.calls == 2
    assert fake.received_prompt is not None and "4. 미디어 북 준호·교실" in fake.received_prompt


class _QuotaExhaustedFilterLLMClient(_FakeLLMClient):
    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise LLMRateLimitError("RESOURCE_EXHAUSTED")


async def test_publish_screening_rate_limited_by_gemini_returns_503_and_reports_rate_limit_tag(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini 쿼터 소진(429)도 503 으로 알린다. 승격 태그를 갈라야 쿼터 소진이 다른 호출 실패와 섞이지 않는다."""
    content, _, _, _ = await _publishable_character(db_session, db_client)
    reported: list[str] = []
    monkeypatch.setattr(
        "api.content.router.capture_dependency_failure",
        lambda _exc=None, *, dependency: reported.append(dependency),
    )

    _override_llm_client(_QuotaExhaustedFilterLLMClient(PublishFilterResult(passed=True, reason=None)))
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 503
    assert resp.json()["detail"] == {
        "code": "PUBLISH_SCREENING_UNAVAILABLE",
        "message": "발행 심사를 지금 진행하지 못했어요. 잠시 뒤 다시 발행해 주세요.",
    }
    assert reported == ["gemini_rate_limit"]


async def test_publish_screening_returns_429_with_publish_window_after_hourly_limit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """심사 LLM 호출은 작가당 시간당 상한이 있다. 넘으면 LLM 을 부르지 않고 429 를 주며, 다른 429 와 같은 모양에
    `window` 로 기능을 가른다."""
    monkeypatch.setattr(rate_limit_gate, "PUBLISH_SCREEN_LIMIT", 1)
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=False, reason="부적절"))

    _override_llm_client(fake)
    try:
        first = await db_client.post(f"/contents/{content.id}/publish")
        second = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert first.status_code == 400
    assert second.status_code == 429
    detail = second.json()["detail"]
    assert (detail["code"], detail["window"]) == ("USER_LIMIT", "publish")
    assert 0 < detail["retryAfterSeconds"] <= rate_limit_gate.HOURLY_WINDOW_SECONDS
    assert fake.calls == 1
    await db_session.refresh(content)
    assert content.current_published_version_id is None


async def test_publish_screening_limit_does_not_count_validation_failures_or_remembered_passes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한은 LLM 을 실제로 부를 때만 센다 — 필수 항목 누락이나 통과 기억 적중은 비용이 없어 작가의 몫을 깎지 않는다.
    상한 1 에서 검증 실패, 심사 발행, 기억 적중 재발행이 모두 지나가야 한다."""
    monkeypatch.setattr(rate_limit_gate, "PUBLISH_SCREEN_LIMIT", 1)
    content, version, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))
    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    name = detail.name
    detail.name = ""
    await db_session.commit()

    _override_llm_client(fake)
    try:
        incomplete = await db_client.post(f"/contents/{content.id}/publish")
        detail.name = name
        await db_session.commit()
        published = await db_client.post(f"/contents/{content.id}/publish")
        republished = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert (incomplete.status_code, published.status_code, republished.status_code) == (400, 200, 200)
    assert "missingFields" in incomplete.json()["detail"]
    assert fake.calls == 1


async def test_publish_screening_limit_skips_exempt_users(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """예외 계정(시드 작가 등)은 채팅·이미지와 같은 판정으로 발행 상한도 건너뛴다."""
    monkeypatch.setattr(rate_limit_gate, "PUBLISH_SCREEN_LIMIT", 0)
    user = _make_user(rate_limit_exempt=True)
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content, _, _, _ = await _make_publishable_character_draft(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.calls == 1


async def test_publish_screening_limit_fails_open_when_redis_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한을 세는 장치가 죽어도 발행은 막지 않는다(채팅·이미지와 같은 fail-open). 장애는 승격한다."""
    monkeypatch.setattr(rate_limit_gate, "PUBLISH_SCREEN_LIMIT", 0)
    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", _raise_redis_error)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)
    reported: list[str] = []
    monkeypatch.setattr(
        rate_limit_gate, "capture_dependency_failure", lambda _exc=None, *, dependency: reported.append(dependency)
    )
    content, _, _, _ = await _publishable_character(db_session, db_client)
    fake = _FakeLLMClient(PublishFilterResult(passed=True, reason=None))

    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/contents/{content.id}/publish")
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    assert fake.calls == 1
    assert reported == ["redis"]


# ── 발행이 저장소·심사를 기다리는 동안 DB 트랜잭션을 쥐지 않는다 ──────────────────────────────
#
# 발행은 대표 이미지·칸 축소본 내려받기(최대 50장), Gemini 심사, 칸 블러본 올리기를 기다린다. 그동안 요청 세션이
# 트랜잭션을 열어 두면 커넥션 하나를 통째로 쥐어 다른 요청이 풀을 기다린다. 그래서 읽기를 끝내면 커밋으로 반납하고,
# 외부 호출이 다 끝난 뒤 짧은 트랜잭션에서 초안을 잠가 그사이 바뀌지 않았는지 다시 보고 쓴다. 측정은 채팅 턴과 같은
# 세션 이벤트 프로브다(`_open_transaction_probe` 의 docstring).


class _NotingFilterLLMClient(_FakeLLMClient):
    """심사를 부르는 순간 열린 루트 트랜잭션 수를 `seen` 에 적는다."""

    def __init__(self, open_sessions: set[int], seen: list[tuple[str, int]]) -> None:
        super().__init__(PublishFilterResult(passed=True, reason=None))
        self._open_sessions = open_sessions
        self._seen = seen

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self._seen.append(("screen", len(self._open_sessions)))
        return await super().generate_structured(prompt, response_schema, images, usage=usage)


async def test_publish_character_holds_no_transaction_while_downloading_or_screening(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    content, _, _, _ = await _publishable_character(db_session, db_client)
    seen: list[tuple[str, int]] = []
    with _open_transaction_probe() as open_sessions:
        monkeypatch.setattr(
            "api.content.router.download_object",
            _noting_open_transactions(open_sessions, seen, "download", download_object),
        )
        _override_llm_client(_NotingFilterLLMClient(open_sessions, seen))
        try:
            resp = await db_client.post(f"/contents/{content.id}/publish")
        finally:
            _clear_llm_override()

    assert resp.status_code == 200, resp.text
    # 대표 원본 1 + 상황 이미지 축소본 1, 그다음 심사 1.
    assert seen == [("download", 0), ("download", 0), ("screen", 0)]


async def test_publish_story_holds_no_transaction_while_downloading_screening_or_blurring(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    content, _, _, cells = await _story_with_media_cells(db_session, db_client)
    seen: list[tuple[str, int]] = []
    with _open_transaction_probe() as open_sessions:
        for module, attr, name in (
            (content_router, "download_object", "screening download"),
            (blur_module, "download_object", "blur download"),
            (blur_module, "upload_object", "blur upload"),
        ):
            real = getattr(module, attr)
            monkeypatch.setattr(module, attr, _noting_open_transactions(open_sessions, seen, name, real))
        _override_llm_client(_NotingFilterLLMClient(open_sessions, seen))
        try:
            resp = await db_client.post(f"/contents/{content.id}/publish")
        finally:
            _clear_llm_override()

    assert resp.status_code == 200, resp.text
    counts = {name: [count for seen_name, count in seen if seen_name == name] for name, _ in seen}
    # 대표 원본 1 + 칸 축소본 셋 · 심사 1 · 블러가 필요한 칸 셋(원본 받기 1 + 블러본·변형 올리기 3).
    assert {name: len(values) for name, values in counts.items()} == {
        "screening download": 1 + len(cells),
        "screen": 1,
        "blur download": len(cells),
        "blur upload": 3 * len(cells),
    }
    assert [(name, count) for name, count in seen if count != 0] == []


class _PausingFilterLLMClient(_FakeLLMClient):
    """첫 심사 호출만 `release` 가 열릴 때까지 붙잡는다(호출에 들어온 순간 `entered` 를 연다). 두 번째 호출부터는 바로
    통과를 돌려준다 — 발행 하나가 심사를 기다리는 사이 다른 일이 끝나는 순서를 만든다."""

    def __init__(self) -> None:
        super().__init__(PublishFilterResult(passed=True, reason=None))
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        first = self.calls == 0
        result = await super().generate_structured(prompt, response_schema, images, usage=usage)
        if first:
            self.entered.set()
            await asyncio.wait_for(self.release.wait(), 10)
        return result


async def _publish_while_first_screening_waits(
    db_client: httpx.AsyncClient, content_id: uuid.UUID, during: Any
) -> tuple[httpx.Response, Any]:
    """발행 하나를 심사 호출 안에 붙잡아 둔 채 `during()` 을 돌리고, 풀어 준 뒤 그 발행의 응답과 `during()` 의 값을
    돌려준다."""
    fake = _PausingFilterLLMClient()
    _override_llm_client(fake)
    try:
        first = asyncio.create_task(db_client.post(f"/contents/{content_id}/publish"))
        await asyncio.wait_for(fake.entered.wait(), 10)
        try:
            during_result = await during()
        finally:
            fake.release.set()
        return await first, during_result
    finally:
        _clear_llm_override()


async def _versions(db_session: AsyncSession, content_id: uuid.UUID) -> list[tuple[int | None, bool]]:
    """작품의 버전 번호와 발행 여부를 번호 순으로(초안은 뒤로)."""
    rows = (
        await db_session.execute(
            sa.select(ContentVersion.version_number, ContentVersion.published_at.is_not(None))
            .where(ContentVersion.content_id == content_id)
            .order_by(ContentVersion.version_number.asc().nulls_last())
        )
    ).tuples()
    return [(number, published) for number, published in rows]


@pytest.mark.usefixtures("committing_request_session")
async def test_overlapping_publishes_of_one_draft_publish_once_and_refuse_the_other(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 같은 초안에 발행 둘이 겹쳐(다른 창·두 번 누름) 한쪽이 심사를 기다리는 사이
    다른 쪽이 끝나면, 늦은 쪽은 409 `PUBLISH_CONFLICT` 이고 작품에는 발행본 1(번호 1)과 초안 하나만 남아야 한다.
    늦은 쪽도 200 이거나, 초안이 둘이거나, 번호 1 이 비면(건너뜀) 실패다.

    요청마다 같은 커넥션 위의 SAVEPOINT 세션이라 진짜 행 잠금 경쟁은 아니다 — 늦은 쪽이 "읽은 뒤 남이 바꾼 초안"에
    쓰는 순서를 정확히 만든다. 잠금 자체는 `test_publish_lock_makes_a_second_publish_wait_and_then_refuse` 가 본다."""
    content, _, _, _ = await _publishable_character(db_session, db_client)

    async def publish_again() -> httpx.Response:
        return await db_client.post(f"/contents/{content.id}/publish")

    late, early = await _publish_while_first_screening_waits(db_client, content.id, publish_again)

    assert early.status_code == 200, early.text
    assert early.json()["versionNumber"] == 1
    assert late.status_code == 409, late.text
    assert late.json() == {"detail": {"code": "PUBLISH_CONFLICT"}}
    assert await _versions(db_session, content.id) == [(1, True), (None, False)]


@pytest.mark.usefixtures("committing_request_session")
async def test_publish_is_refused_when_an_image_changes_while_it_is_being_screened(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """판정 기준: 심사하는 동안 상황 이미지가 다른 그림으로 바뀌면 그 발행은 409 `PUBLISH_CONFLICT` 이고 아무것도
    발행되지 않는다(초안 그대로, 미발행 변경 표시도 그대로). 200 이면 심사하지 않은 그림이 발행된 것이다."""
    content, _, _, situational_image = await _publishable_character(db_session, db_client)
    replacement = await _make_ready_asset(db_session, owner_user_id=content.creator_user_id)
    content.has_unpublished_changes = True
    await db_session.commit()

    async def swap_image() -> None:
        await db_session.execute(
            sa.update(SituationalImage)
            .where(SituationalImage.id == situational_image.id)
            .values(image_asset_id=replacement.id)
        )
        await db_session.commit()

    resp, _ = await _publish_while_first_screening_waits(db_client, content.id, swap_image)

    assert resp.status_code == 409, resp.text
    assert resp.json() == {"detail": {"code": "PUBLISH_CONFLICT"}}
    assert await _versions(db_session, content.id) == [(None, False)]
    await db_session.refresh(content)
    assert content.has_unpublished_changes is True
    assert content.current_published_version_id is None


@pytest.mark.usefixtures("committing_request_session")
async def test_publish_story_is_refused_when_a_cell_image_changes_while_it_is_being_screened(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """판정 기준: 심사하는 동안 칸 그림이 바뀌면 409 이고 발행본·블러 자산 행이 하나도 생기지 않는다(올린 블러본
    객체는 가리키는 행 없이 남는 것을 감수한다)."""
    content, version, _, cells = await _story_with_media_cells(db_session, db_client)
    replacement = await _make_ready_asset(db_session, owner_user_id=content.creator_user_id)
    await db_session.commit()

    async def swap_cell_image() -> None:
        await db_session.execute(
            sa.update(MediaBookCell).where(MediaBookCell.id == cells[0][0].id).values(image_asset_id=replacement.id)
        )
        await db_session.commit()

    resp, _ = await _publish_while_first_screening_waits(db_client, content.id, swap_cell_image)

    assert resp.status_code == 409, resp.text
    assert resp.json() == {"detail": {"code": "PUBLISH_CONFLICT"}}
    assert await _versions(db_session, content.id) == [(None, False)]
    blurred_rows = await db_session.scalar(
        sa.select(sa.func.count()).select_from(Asset).where(
            Asset.owner_user_id == content.creator_user_id, Asset.kind == AssetKind.BLURRED
        )
    )
    assert blurred_rows == 0
    cell_blurs = (
        await db_session.scalars(
            sa.select(MediaBookCell.blurred_asset_id).where(MediaBookCell.content_version_id == version.id)
        )
    ).all()
    assert set(cell_blurs) == {None}


@pytest.mark.usefixtures("committing_request_session")
async def test_publish_story_is_refused_when_a_cell_loses_its_blur_while_it_is_being_screened(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """판정 기준(결과를 보기 전에 적었다): 심사하는 동안 자동저장이 블러본이 있던 칸의 그림을 A→B→A 로 바꾸면 심사한
    그림은 같지만 블러본은 비워져, 이 발행이 올리지 않은 칸이 블러 대상이 된다. 그 발행은 409 `PUBLISH_CONFLICT` 이고
    아무것도 발행되지 않아야 한다. 500 이면 블러 대상 비교 없이 올리지 않은 블러본을 찾다 터진 것이다."""
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
    other_image = await _make_ready_asset(db_session, owner_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    async def swap_away_and_back() -> None:
        # 그림을 바꾸면 자동저장이 블러본을 비운다. 되돌려도 블러본은 돌아오지 않는다.
        for image_id in (other_image.id, kept_image.id):
            await db_session.execute(
                sa.update(MediaBookCell)
                .where(MediaBookCell.id == kept.id)
                .values(image_asset_id=image_id, blurred_asset_id=None)
            )
            await db_session.commit()

    resp, _ = await _publish_while_first_screening_waits(db_client, content.id, swap_away_and_back)

    assert resp.status_code == 409, resp.text
    assert resp.json() == {"detail": {"code": "PUBLISH_CONFLICT"}}
    assert await _versions(db_session, content.id) == [(None, False)]
    await db_session.refresh(kept)
    assert (kept.image_asset_id, kept.blurred_asset_id) == (kept_image.id, None)


@pytest.mark.usefixtures("committing_request_session")
async def test_publish_still_succeeds_when_only_text_changes_while_it_is_being_screened(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """심사는 그림만 본다 — 그사이 글만 바뀐 자동저장은 충돌이 아니다. 발행본에는 발행 시점의 글이 실린다."""
    content, version, _, _ = await _publishable_character(db_session, db_client)

    async def edit_text() -> None:
        await db_session.execute(
            sa.update(CharacterVersionDetail)
            .where(CharacterVersionDetail.content_version_id == version.id)
            .values(one_liner="바뀐 한 줄 소개")
        )
        await db_session.commit()

    resp, _ = await _publish_while_first_screening_waits(db_client, content.id, edit_text)

    assert resp.status_code == 200, resp.text
    assert await _versions(db_session, content.id) == [(1, True), (None, False)]
    published_one_liner = await db_session.scalar(
        sa.select(CharacterVersionDetail.one_liner).where(CharacterVersionDetail.content_version_id == version.id)
    )
    assert published_one_liner == "바뀐 한 줄 소개"
