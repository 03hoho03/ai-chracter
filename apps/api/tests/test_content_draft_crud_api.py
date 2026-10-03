import asyncio
import io
import unicodedata
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone, UTC
from typing import Any

import boto3
import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import ORMExecuteState
from sqlalchemy.pool import NullPool

from api.core.config import settings
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.auth import User
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.moderation import AdminActionLog, ModerationAction, Notification
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    KeywordNote,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.session import get_db_session, get_session_factory
from api.main import app
from factories import (
    _add_media_book_cell,
    _count_queries,
    _create_admin,
    _get_genre,
    _login_as,
    _login_as_admin,
    _make_asset,
    _make_user,
)


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


def _draft_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "아리아",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "intro": "안녕하세요",
        "exampleDialogues": [{"id": "d1", "userLine": "안녕", "characterLine": "반가워"}],
        "characterPrompt": "너는 아리아다.",
        "playguide": None,
        "situationalImages": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def _story_draft_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "잃어버린 도시",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


_CONTENT_DRAFT_REQUIRES_LOGIN_CASES = [
    pytest.param("post", "/contents", {"type": "character"}, id="create"),
    pytest.param("get", f"/contents/{uuid.uuid4()}/draft", None, id="get"),
    pytest.param("patch", f"/contents/{uuid.uuid4()}/draft", _draft_payload(), id="patch"),
    pytest.param("delete", f"/contents/{uuid.uuid4()}/draft", None, id="delete"),
]


@pytest.mark.parametrize(("method", "path", "json"), _CONTENT_DRAFT_REQUIRES_LOGIN_CASES)
async def test_content_draft_requires_login(
    db_client: httpx.AsyncClient, method: str, path: str, json: dict[str, object] | None
) -> None:
    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401


async def test_create_content_draft_creates_empty_character_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/contents", json={"type": "character"})
    assert resp.status_code == 201
    content_id = uuid.UUID(resp.json()["contentId"])

    content = await db_session.get(Content, content_id)
    assert content is not None
    assert content.type == ContentType.CHARACTER
    assert content.creator_user_id == user.id
    assert content.genre_id is None
    assert content.target is None
    assert content.hashtags == []
    assert content.visibility == ContentVisibility.PRIVATE
    assert content.moderation_status == ModerationStatus.NORMAL
    assert content.current_published_version_id is None

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content_id)
        )
    ).scalar_one()
    assert version.published_at is None
    assert version.version_number is None
    assert version.detail_description == ""

    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    assert detail.name == ""
    assert detail.one_liner == ""
    assert detail.thumbnail_asset_id is None
    assert detail.intro == ""
    assert detail.example_dialogues == []
    assert detail.character_prompt == ""
    assert detail.playguide is None


async def test_create_content_draft_creates_empty_story_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/contents", json={"type": "story"})
    assert resp.status_code == 201
    content_id = uuid.UUID(resp.json()["contentId"])

    content = await db_session.get(Content, content_id)
    assert content is not None
    assert content.type == ContentType.STORY
    assert content.creator_user_id == user.id
    assert content.genre_id is None

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content_id)
        )
    ).scalar_one()
    assert version.published_at is None

    detail = await db_session.get(StoryVersionDetail, version.id)
    assert detail is not None
    assert detail.name == ""
    assert detail.one_liner == ""
    assert detail.thumbnail_asset_id is None
    assert detail.prompt_template == StoryPromptTemplate.BASIC
    assert detail.setting_text is None
    assert detail.development_example is None
    assert detail.custom_prompt is None
    assert detail.development_examples == []
    assert detail.user_goal is None
    assert detail.rules is None


async def test_get_content_draft_returns_404_for_missing_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.get(f"/contents/{uuid.uuid4()}/draft")
    assert resp.status_code == 404


_CONTENT_DRAFT_NON_OWNER_CASES = [
    pytest.param("get", None, id="get"),
    pytest.param("patch", _draft_payload(), id="patch"),
]


@pytest.mark.parametrize(("method", "json"), _CONTENT_DRAFT_NON_OWNER_CASES)
async def test_content_draft_returns_403_for_non_owner(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    json: dict[str, object] | None,
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.request(method.upper(), f"/contents/{content.id}/draft", json=json)
    assert resp.status_code == 403


async def test_get_content_draft_returns_newly_created_empty_story_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    create_resp = await db_client.post("/contents", json={"type": "story"})
    content_id = create_resp.json()["contentId"]

    resp = await db_client.get(f"/contents/{content_id}/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == content_id
    assert body["type"] == "story"
    assert body["name"] == ""
    assert body["oneLiner"] == ""
    assert body["thumbnailAssetId"] is None
    assert body["thumbnailUrl"] is None
    assert body["promptTemplate"] == "basic"
    assert body["settingText"] is None
    assert body["developmentExample"] is None
    assert body["customPrompt"] is None
    assert body["developmentExamples"] == []
    assert body["userGoal"] is None
    assert body["rules"] is None
    assert body["startingSetups"] == []
    assert body["keywordNotes"] == []
    assert body["shortcuts"] == []
    assert body["description"] == ""
    assert body["genreId"] is None
    assert body["target"] is None
    assert body["hashtags"] == []
    assert body["visibility"] == "private"


async def test_get_content_draft_returns_newly_created_empty_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    create_resp = await db_client.post("/contents", json={"type": "character"})
    content_id = create_resp.json()["contentId"]

    resp = await db_client.get(f"/contents/{content_id}/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == content_id
    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == uuid.UUID(content_id))
        )
    ).scalar_one()
    assert body["contentVersionId"] == str(version.id)
    assert body["type"] == "character"
    assert body["name"] == ""
    assert body["oneLiner"] == ""
    assert body["thumbnailAssetId"] is None
    assert body["thumbnailUrl"] is None
    assert body["intro"] == ""
    assert body["exampleDialogues"] == []
    assert body["characterPrompt"] == ""
    assert body["playguide"] is None
    assert body["situationalImages"] == []
    assert body["description"] == ""
    assert body["genreId"] is None
    assert body["target"] is None
    assert body["hashtags"] == []
    assert body["visibility"] == "private"


async def test_get_content_draft_returns_thumbnail_url_for_character(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Draft GET resolves a renderable URL for thumbnailAssetId
    via the same `_resolve_thumbnail_url` path DraftSummary already uses."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    thumbnail = await _make_asset(db_session, user.id)
    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    detail.thumbnail_asset_id = thumbnail.id
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.get(f"/contents/{content.id}/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["thumbnailAssetId"] == str(thumbnail.id)
    assert body["thumbnailUrl"]


async def test_get_content_draft_returns_thumbnail_url_for_story(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Same as the character case, story side."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    thumbnail = await _make_asset(db_session, user.id)
    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    detail = await db_session.get(StoryVersionDetail, version.id)
    assert detail is not None
    detail.thumbnail_asset_id = thumbnail.id
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.get(f"/contents/{content.id}/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["thumbnailAssetId"] == str(thumbnail.id)
    assert body["thumbnailUrl"]


async def test_patch_content_draft_updates_fields_without_validation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """AC: PATCH accepts the payload as-is, no min-length/required-ness checks."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(name="", characterPrompt=""),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == ""
    assert body["characterPrompt"] == ""
    assert body["thumbnailUrl"] is None
    assert body["exampleDialogues"] == [
        {"id": "d1", "userLine": "안녕", "characterLine": "반가워"}
    ]

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    assert detail.intro == "안녕하세요"
    assert detail.example_dialogues == [
        {"id": "d1", "userLine": "안녕", "characterLine": "반가워"}
    ]


async def test_patch_content_draft_updates_registration_fields(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """registration-tab fields live on Content/ContentVersion, not character_version_details
    (shared across versions, not per-version snapshot data) — publish validation depends on these
    being settable so a draft can ever pass it."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            description="상세 설명입니다",
            genreId=str(genre.id),
            target="female",
            hashtags=["힐링", "일상"],
            visibility="public",
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "상세 설명입니다"
    assert body["genreId"] == str(genre.id)
    assert body["target"] == "female"
    assert body["hashtags"] == ["힐링", "일상"]
    assert body["visibility"] == "public"

    await db_session.refresh(content)
    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    assert version.detail_description == "상세 설명입니다"
    assert content.genre_id == genre.id
    assert content.target == ContentTarget.FEMALE
    assert content.hashtags == ["힐링", "일상"]
    assert content.visibility == ContentVisibility.PUBLIC


async def test_patch_content_draft_upserts_inserts_updates_deletes_and_reorders_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    keep_id = str(uuid.uuid4())
    drop_id = str(uuid.uuid4())
    first_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            situationalImages=[
                {"id": keep_id, "triggerCondition": "첫 조건"},
                {"id": drop_id, "triggerCondition": "삭제될 조건"},
            ]
        ),
    )
    assert first_resp.status_code == 200
    assert [item["id"] for item in first_resp.json()["situationalImages"]] == [keep_id, drop_id]

    new_id = str(uuid.uuid4())
    second_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            situationalImages=[
                {"id": new_id, "triggerCondition": "새 조건"},
                {"id": keep_id, "triggerCondition": "수정된 조건"},
            ]
        ),
    )
    assert second_resp.status_code == 200
    body = second_resp.json()
    assert [item["id"] for item in body["situationalImages"]] == [new_id, keep_id]
    assert body["situationalImages"][1]["triggerCondition"] == "수정된 조건"

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    rows = (
        (
            await db_session.execute(
                sa.select(SituationalImage)
                .where(SituationalImage.content_version_id == version.id)
                .order_by(SituationalImage.order)
            )
        )
        .scalars()
        .all()
    )
    assert [str(row.entity_id) for row in rows] == [new_id, keep_id]
    assert [row.order for row in rows] == [0, 1]
    assert rows[1].trigger_condition == "수정된 조건"


async def test_patch_content_draft_preserves_image_asset_id_set_by_register_endpoint(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """The image fields are exclusively owned by `/assets/{id}/register-situational-image`
    — this endpoint must not null them out when it updates trigger_condition/order
    for an entity_id that already has an image attached."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()

    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color=(200, 40, 40)).save(buffer, format="PNG")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=buffer.getvalue())
    await db_session.commit()
    await _login_as(db_client, user.id)

    entity_id = uuid.uuid4()
    register_resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(entity_id),
            "contentVersionId": str(version.id),
            "triggerCondition": "원래 조건",
            "order": 0,
        },
    )
    assert register_resp.status_code == 200
    blurred_asset_id = register_resp.json()["blurredAssetId"]

    patch_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(
            situationalImages=[{"id": str(entity_id), "triggerCondition": "수정된 조건"}]
        ),
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["situationalImages"] == [
        {"id": str(entity_id), "imageAssetId": str(asset.id), "triggerCondition": "수정된 조건"}
    ]

    row = await db_session.scalar(
        sa.select(SituationalImage).where(SituationalImage.entity_id == entity_id)
    )
    assert row is not None
    assert row.image_asset_id == asset.id
    assert str(row.blurred_asset_id) == blurred_asset_id
    assert row.trigger_condition == "수정된 조건"


async def test_register_after_patch_for_same_new_entity_keeps_one_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    """The builder autosaves a freshly added row (no image yet) and then registers its image
    under the same entity_id. The registration must land on that row, not add a second one —
    a second row would never be tracked by later PATCHes and would be copied into every
    published version."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    version = (
        await db_session.execute(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    ).scalar_one()
    asset = await _make_asset(
        db_session, user.id, storage_key_prefix="assets/situational-image/", status=AssetStatus.READY
    )
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color=(200, 40, 40)).save(buffer, format="PNG")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url)
    s3.put_object(Bucket=settings.s3_bucket_name, Key=asset.storage_key, Body=buffer.getvalue())
    await db_session.commit()
    await _login_as(db_client, user.id)

    entity_id = uuid.uuid4()
    patch_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(situationalImages=[{"id": str(entity_id), "triggerCondition": "자동저장 조건"}]),
    )
    assert patch_resp.status_code == 200
    register_resp = await db_client.post(
        f"/assets/{asset.id}/register-situational-image",
        json={
            "entityId": str(entity_id),
            "contentVersionId": str(version.id),
            "triggerCondition": "등록 조건",
            "order": 0,
        },
    )
    assert register_resp.status_code == 200

    rows = (
        await db_session.scalars(
            sa.select(SituationalImage).where(SituationalImage.content_version_id == version.id)
        )
    ).all()
    [row] = rows
    assert row.entity_id == entity_id
    assert row.image_asset_id == asset.id
    assert str(row.blurred_asset_id) == register_resp.json()["blurredAssetId"]
    assert row.trigger_condition == "등록 조건"


async def test_patch_racing_register_for_same_new_entity_keeps_one_row_and_its_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The race the sequential case can't show: an image registration commits the row
    *after* this PATCH has read the version's rows (so the PATCH thinks the entity is new)
    but *before* it writes. The PATCH must update that row's text and order, keep its image,
    and not fail or add a second row."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    version = (
        await db_session.execute(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    ).scalar_one()
    image = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    blurred = await _make_asset(db_session, user.id, kind=AssetKind.BLURRED, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)

    entity_id = uuid.uuid4()
    raced = False

    def _register_lands_right_after_patch_reads(orm_execute_state: ORMExecuteState) -> Result[Any] | None:
        nonlocal raced
        statement = orm_execute_state.statement
        if raced or not isinstance(statement, sa.Select):
            return None
        if SituationalImage.__table__ not in statement.get_final_froms():
            return None
        raced = True
        # 읽기 결과를 먼저 다 받아 두고, 그 뒤에 경쟁 쓰기를 끼워 넣는다.
        frozen = orm_execute_state.invoke_statement().freeze()
        orm_execute_state.session.connection().execute(
            sa.insert(SituationalImage).values(
                id=uuid.uuid4(),
                entity_id=entity_id,
                content_version_id=version.id,
                image_asset_id=image.id,
                blurred_asset_id=blurred.id,
                trigger_condition="등록 조건",
                order=0,
            )
        )
        return frozen()

    sa.event.listen(db_session.sync_session, "do_orm_execute", _register_lands_right_after_patch_reads)
    try:
        resp = await db_client.patch(
            f"/contents/{content.id}/draft",
            json=_draft_payload(
                situationalImages=[
                    {"id": str(uuid.uuid4()), "triggerCondition": "앞 항목"},
                    {"id": str(entity_id), "triggerCondition": "자동저장 조건"},
                ]
            ),
        )
    finally:
        sa.event.remove(db_session.sync_session, "do_orm_execute", _register_lands_right_after_patch_reads)
    assert raced
    assert resp.status_code == 200

    rows = (
        await db_session.scalars(
            sa.select(SituationalImage)
            .where(SituationalImage.content_version_id == version.id, SituationalImage.entity_id == entity_id)
            .execution_options(populate_existing=True)
        )
    ).all()
    [row] = rows
    assert row.image_asset_id == image.id
    assert row.blurred_asset_id == blurred.id
    assert row.trigger_condition == "자동저장 조건"
    assert row.order == 1


async def test_patch_content_draft_returns_422_for_mismatched_payload_type(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(f"/contents/{content.id}/draft", json=_draft_payload())
    assert resp.status_code == 422


async def test_patch_content_draft_updates_story_fields_without_validation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """AC: PATCH accepts the payload as-is, no min-length/required-ness checks."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            name="",
            promptTemplate="custom",
            customPrompt="",
            description="상세 설명입니다",
            genreId=str(genre.id),
            target="all",
            hashtags=["판타지"],
            visibility="public",
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "story"
    assert body["name"] == ""
    assert body["promptTemplate"] == "custom"
    assert body["customPrompt"] == ""
    assert body["thumbnailUrl"] is None
    assert body["description"] == "상세 설명입니다"
    assert body["genreId"] == str(genre.id)
    assert body["target"] == "all"
    assert body["hashtags"] == ["판타지"]
    assert body["visibility"] == "public"

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    detail = await db_session.get(StoryVersionDetail, version.id)
    assert detail is not None
    assert detail.setting_text == "세계관 설명"


async def test_patch_content_draft_returns_thumbnail_url_for_character(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """PATCH response resolves thumbnailUrl the same way GET does."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    thumbnail = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(thumbnailAssetId=str(thumbnail.id)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["thumbnailAssetId"] == str(thumbnail.id)
    assert body["thumbnailUrl"]


async def test_patch_content_draft_returns_thumbnail_url_for_story(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Story side of the same PATCH behavior."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    thumbnail = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(thumbnailAssetId=str(thumbnail.id)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["thumbnailAssetId"] == str(thumbnail.id)
    assert body["thumbnailUrl"]


async def test_patch_content_draft_round_trips_rules_user_goal_and_development_examples(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """새 필드 셋이 PATCH -> GET 왕복에서
    손실 없이 돈다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    development_examples = [
        {"userLine": "안녕", "assistantLine": "어서오세요"},
        {"userLine": "잘 지내?", "assistantLine": "그럭저럭요"},
    ]
    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            rules="폭력 묘사는 암시로만 한다",
            userGoal="용을 물리친다",
            developmentExamples=development_examples,
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rules"] == "폭력 묘사는 암시로만 한다"
    assert body["userGoal"] == "용을 물리친다"
    assert body["developmentExamples"] == development_examples

    get_resp = await db_client.get(f"/contents/{content.id}/draft")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["rules"] == "폭력 묘사는 암시로만 한다"
    assert get_body["userGoal"] == "용을 물리친다"
    assert get_body["developmentExamples"] == development_examples


async def test_patch_content_draft_preserves_development_example_when_key_omitted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """구 컬럼 `developmentExample`은 마이그레이션 리비전②(구 컬럼 드롭)
    전까지 롤백 안전망으로 살아 있어야 한다. FE는 이 필드를 더 이상 폼에서 관리하지 않아 PATCH에
    아예 안 보내므로, "안 보냄"을 서버가 명시적 `null`과 구분하지 못하면 창작자가 다른 필드만
    고쳐도 원본 값이 조용히 지워진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    detail = await db_session.get(StoryVersionDetail, version.id)
    assert detail is not None
    detail.development_example = "사용자: 안녕\n서술자: 어서오세요"
    await db_session.commit()

    payload = _story_draft_payload(name="새 이름")
    del payload["developmentExample"]

    resp = await db_client.patch(f"/contents/{content.id}/draft", json=payload)
    assert resp.status_code == 200
    assert resp.json()["name"] == "새 이름"

    await db_session.refresh(detail)
    assert detail.development_example == "사용자: 안녕\n서술자: 어서오세요"


async def test_patch_content_draft_clears_development_example_when_sent_explicit_null(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """위 테스트의 반대쪽 방어: 명시적 `null`은 여전히 지워야 한다 — "안 보냄"과 뭉치면 위 보존
    동작 자체가 필드를 영영 못 지우는 결함으로 뒤집힌다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    version = (
        await db_session.execute(
            sa.select(ContentVersion).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()
    detail = await db_session.get(StoryVersionDetail, version.id)
    assert detail is not None
    detail.development_example = "사용자: 안녕\n서술자: 어서오세요"
    await db_session.commit()

    resp = await db_client.patch(
        f"/contents/{content.id}/draft", json=_story_draft_payload(developmentExample=None)
    )
    assert resp.status_code == 200

    await db_session.refresh(detail)
    assert detail.development_example is None


def _starting_setup_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "name": "시작설정1",
        "prologue": "프롤로그",
        "openingMessage": None,
        "playguide": None,
        "suggestedReplies": [],
        "statDefs": [],
        "endings": [],
    }
    item.update(overrides)
    return item


async def test_patch_content_draft_upserts_starting_setup_tree(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    setup_id = str(uuid.uuid4())
    stat_id = str(uuid.uuid4())
    ending_id = str(uuid.uuid4())
    top_rule_id = str(uuid.uuid4())
    group_id = str(uuid.uuid4())
    nested_rule_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())
    shortcut_id = str(uuid.uuid4())

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=[
                {
                    "id": setup_id,
                    "name": "시작설정1",
                    "prologue": "프롤로그",
                    "openingMessage": "오프닝 메시지",
                    "playguide": None,
                    "suggestedReplies": ["응답1"],
                    "statDefs": [
                        {
                            "id": stat_id,
                            "name": "체력",
                            "icon": "heart",
                            "color": "rose",
                            "minValue": 0,
                            "maxValue": 100,
                            "initialValue": 50,
                            "unit": None,
                            "description": "체력 스탯",
                        }
                    ],
                    "endings": [
                        {
                            "id": ending_id,
                            "name": "해피엔딩",
                            "turnCountGate": 10,
                            "judgmentPrompt": "판정 프롬프트",
                            "epilogue": "에필로그",
                            "hint": None,
                            "statRules": [
                                {
                                    "kind": "rule",
                                    "id": top_rule_id,
                                    "statId": stat_id,
                                    "operator": "gte",
                                    "threshold": 50,
                                    "nextOp": "and",
                                },
                                {
                                    "kind": "group",
                                    "id": group_id,
                                    "nextOp": None,
                                    "rules": [
                                        {
                                            "kind": "rule",
                                            "id": nested_rule_id,
                                            "statId": stat_id,
                                            "operator": "lt",
                                            "threshold": 10,
                                            "nextOp": None,
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
            keywordNotes=[
                {
                    "id": note_id,
                    "infoText": "키워드 노트",
                    "triggerKeywords": ["단서"],
                    "startingSetupId": setup_id,
                }
            ],
            shortcuts=[
                {"id": shortcut_id, "name": "단축어1", "description": "설명", "prompt": "프롬프트"}
            ],
        ),
    )
    assert resp.status_code == 200
    body = resp.json()

    assert [s["id"] for s in body["startingSetups"]] == [setup_id]
    setup_body = body["startingSetups"][0]
    assert setup_body["openingMessage"] == "오프닝 메시지"
    assert [sd["id"] for sd in setup_body["statDefs"]] == [stat_id]
    assert setup_body["endings"][0]["id"] == ending_id
    stat_rules = setup_body["endings"][0]["statRules"]
    assert stat_rules[0] == {
        "kind": "rule",
        "id": top_rule_id,
        "statId": stat_id,
        "operator": "gte",
        "threshold": 50.0,
        "nextOp": "and",
    }
    assert stat_rules[1]["kind"] == "group"
    assert stat_rules[1]["id"] == group_id
    assert stat_rules[1]["rules"][0]["id"] == nested_rule_id
    assert body["keywordNotes"] == [
        {
            "id": note_id,
            "infoText": "키워드 노트",
            "triggerKeywords": ["단서"],
            "startingSetupId": setup_id,
            "name": "",
            "excludeKeywords": [],
            "stickyTurns": 0,
            "alwaysOn": False,
        }
    ]
    assert body["shortcuts"] == [
        {"id": shortcut_id, "name": "단축어1", "description": "설명", "prompt": "프롬프트"}
    ]

    # keyword_notes.starting_setup_id is a physical FK, not the entity_id used in the API.
    setup_row = await db_session.scalar(
        sa.select(StartingSetup).where(StartingSetup.entity_id == uuid.UUID(setup_id))
    )
    assert setup_row is not None
    note_row = await db_session.scalar(
        sa.select(KeywordNote).where(KeywordNote.entity_id == uuid.UUID(note_id))
    )
    assert note_row is not None
    assert note_row.starting_setup_id == setup_row.id
    assert note_row.starting_setup_id != uuid.UUID(setup_id)

    # GET returns the same tree (startingSetups(entity_id, order) + descendants).
    get_resp = await db_client.get(f"/contents/{content.id}/draft")
    assert get_resp.status_code == 200
    assert get_resp.json() == body

    setup_physical_id = setup_row.id

    # Second PATCH: reorder two setups, update a stat value, drop nothing yet — physical
    # ids must be stable (real upsert, not delete+reinsert).
    second_setup_id = str(uuid.uuid4())
    second_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=[
                _starting_setup_item(id=second_setup_id, name="시작설정2"),
                {
                    "id": setup_id,
                    "name": "시작설정1",
                    "prologue": "프롤로그",
                    "openingMessage": "오프닝 메시지",
                    "playguide": None,
                    "suggestedReplies": ["응답1"],
                    "statDefs": [
                        {
                            "id": stat_id,
                            "name": "체력",
                            "icon": "heart",
                            "color": "rose",
                            "minValue": 0,
                            "maxValue": 100,
                            "initialValue": 80,
                            "unit": None,
                            "description": "체력 스탯",
                        }
                    ],
                    "endings": [],
                },
            ],
            keywordNotes=[],
            shortcuts=[],
        ),
    )
    assert second_resp.status_code == 200
    second_body = second_resp.json()
    assert [s["id"] for s in second_body["startingSetups"]] == [second_setup_id, setup_id]
    assert second_body["startingSetups"][1]["statDefs"][0]["initialValue"] == 80
    # ending removed from the incoming payload -> its rule tree must be gone too.
    assert second_body["startingSetups"][1]["endings"] == []

    await db_session.refresh(setup_row)
    assert setup_row.id == setup_physical_id
    assert setup_row.order == 1

    remaining_ending = await db_session.scalar(
        sa.select(Ending).where(Ending.entity_id == uuid.UUID(ending_id))
    )
    assert remaining_ending is None
    remaining_group = await db_session.scalar(
        sa.select(EndingRuleGroup).where(EndingRuleGroup.entity_id == uuid.UUID(group_id))
    )
    assert remaining_group is None
    remaining_rules = (
        await db_session.execute(
            sa.select(EndingRule).where(
                EndingRule.entity_id.in_([uuid.UUID(top_rule_id), uuid.UUID(nested_rule_id)])
            )
        )
    ).scalars().all()
    assert remaining_rules == []
    # keyword note dropped from the payload -> deleted.
    remaining_note = await db_session.scalar(
        sa.select(KeywordNote).where(KeywordNote.entity_id == uuid.UUID(note_id))
    )
    assert remaining_note is None


async def test_patch_content_draft_deletes_removed_starting_setup_subtree(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    setup_id = str(uuid.uuid4())
    stat_id = str(uuid.uuid4())
    ending_id = str(uuid.uuid4())
    rule_id = str(uuid.uuid4())

    first_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=[
                {
                    "id": setup_id,
                    "name": "시작설정1",
                    "prologue": "프롤로그",
                    "openingMessage": None,
                    "playguide": None,
                    "suggestedReplies": [],
                    "statDefs": [
                        {
                            "id": stat_id,
                            "name": "체력",
                            "icon": "heart",
                            "color": "rose",
                            "minValue": 0,
                            "maxValue": 100,
                            "initialValue": 50,
                            "unit": None,
                            "description": "체력 스탯",
                        }
                    ],
                    "endings": [
                        {
                            "id": ending_id,
                            "name": "엔딩",
                            "turnCountGate": 10,
                            "judgmentPrompt": "판정",
                            "epilogue": None,
                            "hint": None,
                            "statRules": [
                                {
                                    "kind": "rule",
                                    "id": rule_id,
                                    "statId": stat_id,
                                    "operator": "eq",
                                    "threshold": 1,
                                    "nextOp": None,
                                }
                            ],
                        }
                    ],
                }
            ],
        ),
    )
    assert first_resp.status_code == 200

    # Removing the starting setup entirely must cascade-delete stat_defs/endings/rules —
    # these FKs have no ON DELETE CASCADE, so a naive delete would raise an IntegrityError.
    second_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(startingSetups=[]),
    )
    assert second_resp.status_code == 200
    assert second_resp.json()["startingSetups"] == []

    assert (
        await db_session.scalar(sa.select(StartingSetup).where(StartingSetup.entity_id == uuid.UUID(setup_id)))
    ) is None
    assert (
        await db_session.scalar(sa.select(StatDef).where(StatDef.entity_id == uuid.UUID(stat_id)))
    ) is None
    assert (
        await db_session.scalar(sa.select(Ending).where(Ending.entity_id == uuid.UUID(ending_id)))
    ) is None
    assert (
        await db_session.scalar(sa.select(EndingRule).where(EndingRule.entity_id == uuid.UUID(rule_id)))
    ) is None


async def _mark_published(db_session: AsyncSession, content: Content) -> ContentVersion:
    """Reproduces the state `_publish_character_content`/`_publish_story_content` leave
    behind: a published version the content points at, *alongside* the draft version publish
    auto-clones. Without `current_published_version_id` set, a test would sail through the
    409 guard while pretending to be published."""
    published = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(UTC),
        detail_description="발행본",
    )
    db_session.add(published)
    await db_session.flush()
    content.current_published_version_id = published.id
    await db_session.flush()
    return published


async def test_delete_content_draft_returns_403_for_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.delete(f"/contents/{content.id}/draft")
    assert resp.status_code == 403

    assert (
        await db_session.scalar(sa.select(Content).where(Content.id == content.id))
    ) is not None


async def test_delete_content_draft_removes_character_draft_with_its_images(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    image_id = str(uuid.uuid4())
    patch_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_draft_payload(situationalImages=[{"id": image_id, "triggerCondition": "조건"}]),
    )
    assert patch_resp.status_code == 200
    version_id = uuid.UUID(patch_resp.json()["contentVersionId"])

    resp = await db_client.delete(f"/contents/{content.id}/draft")
    assert resp.status_code == 204

    assert (await db_session.scalar(sa.select(Content).where(Content.id == content.id))) is None
    assert (
        await db_session.scalar(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    ) is None
    assert (
        await db_session.scalar(
            sa.select(CharacterVersionDetail).where(
                CharacterVersionDetail.content_version_id == version_id
            )
        )
    ) is None
    assert (
        await db_session.scalar(
            sa.select(SituationalImage).where(SituationalImage.entity_id == uuid.UUID(image_id))
        )
    ) is None


async def test_delete_content_draft_removes_story_draft_with_its_whole_setup_tree(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """keyword_notes are the interesting part: they hang off the version but carry a physical
    FK to starting_setups, so deleting setups first would raise an IntegrityError."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    setup_id = str(uuid.uuid4())
    stat_id = str(uuid.uuid4())
    ending_id = str(uuid.uuid4())
    top_rule_id = str(uuid.uuid4())
    group_id = str(uuid.uuid4())
    nested_rule_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())
    shortcut_id = str(uuid.uuid4())

    patch_resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=[
                {
                    "id": setup_id,
                    "name": "시작설정1",
                    "prologue": "프롤로그",
                    "openingMessage": None,
                    "playguide": None,
                    "suggestedReplies": [],
                    "statDefs": [
                        {
                            "id": stat_id,
                            "name": "체력",
                            "icon": "heart",
                            "color": "rose",
                            "minValue": 0,
                            "maxValue": 100,
                            "initialValue": 50,
                            "unit": None,
                            "description": "체력 스탯",
                        }
                    ],
                    "endings": [
                        {
                            "id": ending_id,
                            "name": "엔딩",
                            "turnCountGate": 10,
                            "judgmentPrompt": "판정",
                            "epilogue": None,
                            "hint": None,
                            "statRules": [
                                {
                                    "kind": "rule",
                                    "id": top_rule_id,
                                    "statId": stat_id,
                                    "operator": "gte",
                                    "threshold": 50,
                                    "nextOp": "and",
                                },
                                {
                                    "kind": "group",
                                    "id": group_id,
                                    "nextOp": None,
                                    "rules": [
                                        {
                                            "kind": "rule",
                                            "id": nested_rule_id,
                                            "statId": stat_id,
                                            "operator": "lt",
                                            "threshold": 10,
                                            "nextOp": None,
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
            keywordNotes=[
                {
                    "id": note_id,
                    "infoText": "키워드 노트",
                    "triggerKeywords": ["단서"],
                    "startingSetupId": setup_id,
                }
            ],
            shortcuts=[
                {"id": shortcut_id, "name": "단축어1", "description": "설명", "prompt": "프롬프트"}
            ],
        ),
    )
    assert patch_resp.status_code == 200
    # StoryDraftResponse has no contentVersionId (only CharacterDraftResponse does).
    version_id = (
        await db_session.execute(
            sa.select(ContentVersion.id).where(ContentVersion.content_id == content.id)
        )
    ).scalar_one()

    resp = await db_client.delete(f"/contents/{content.id}/draft")
    assert resp.status_code == 204

    assert (await db_session.scalar(sa.select(Content).where(Content.id == content.id))) is None
    assert (
        await db_session.scalar(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    ) is None
    assert (
        await db_session.scalar(
            sa.select(StoryVersionDetail).where(StoryVersionDetail.content_version_id == version_id)
        )
    ) is None
    assert (
        await db_session.scalar(sa.select(KeywordNote).where(KeywordNote.entity_id == uuid.UUID(note_id)))
    ) is None
    assert (
        await db_session.scalar(sa.select(Shortcut).where(Shortcut.entity_id == uuid.UUID(shortcut_id)))
    ) is None
    assert (
        await db_session.scalar(
            sa.select(StartingSetup).where(StartingSetup.entity_id == uuid.UUID(setup_id))
        )
    ) is None
    assert (
        await db_session.scalar(sa.select(StatDef).where(StatDef.entity_id == uuid.UUID(stat_id)))
    ) is None
    assert (
        await db_session.scalar(sa.select(Ending).where(Ending.entity_id == uuid.UUID(ending_id)))
    ) is None
    assert (
        await db_session.scalar(
            sa.select(EndingRuleGroup).where(EndingRuleGroup.entity_id == uuid.UUID(group_id))
        )
    ) is None
    assert (
        await db_session.scalar(
            sa.select(EndingRule).where(
                EndingRule.entity_id.in_([uuid.UUID(top_rule_id), uuid.UUID(nested_rule_id)])
            )
        )
    ) is None


async def test_delete_content_draft_returns_409_for_content_with_publish_history(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Publishing auto-clones a draft version, so a published work always has one — deleting
    it would take the published work down with it. 편집 취소(`POST /contents/{id}/draft/reset`)가
    그 경우의 출구다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    published = await _mark_published(db_session, content)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.delete(f"/contents/{content.id}/draft")
    assert resp.status_code == 409

    assert (await db_session.scalar(sa.select(Content).where(Content.id == content.id))) is not None
    assert (
        await db_session.scalar(sa.select(ContentVersion).where(ContentVersion.id == published.id))
    ) is not None


async def _restrict_draft_as_admin_then_login_as_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[uuid.UUID, Content]:
    """관리자 작품 목록은 초안만 있는 작품도 나열하고 조치는 발행 여부를 보지 않는다 — 그래서
    초안에도 조치 행·감사 로그·알림이 생긴다. 소유자 id와 초안을 돌려준다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    admin_payload = await _create_admin(db_session)
    await db_session.commit()

    await _login_as_admin(db_client, admin_payload)
    action_resp = await db_client.post(
        f"/admin/contents/{content.id}/action",
        json={"action": "restrict", "reasonCategory": "hate", "adminComment": "초안 조치"},
    )
    assert action_resp.status_code == 200
    await _login_as(db_client, user.id)
    return user.id, content


async def test_delete_content_draft_keeps_admin_action_records_with_the_content_link_cleared(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """관리자가 조치한 초안도 소유자가 지울 수 있어야 한다. 조치 행·감사 로그·소유자 알림은
    기록이라 남기고 사라진 작품을 가리키던 칸만 비운다."""
    user_id, content = await _restrict_draft_as_admin_then_login_as_owner(db_client, db_session)

    resp = await db_client.delete(f"/contents/{content.id}/draft")
    assert resp.status_code == 204

    assert (await db_session.scalar(sa.select(Content.id).where(Content.id == content.id))) is None
    action_rows = (await db_session.execute(sa.select(ModerationAction.id, ModerationAction.content_id))).all()
    assert len(action_rows) == 1
    assert action_rows[0].content_id is None
    log_rows = (
        await db_session.execute(sa.select(AdminActionLog.action_type, AdminActionLog.target_content_id))
    ).all()
    assert [tuple(row) for row in log_rows] == [("content-restrict", None)]
    notification_rows = (
        await db_session.execute(
            sa.select(Notification.content_id, Notification.action_id).where(Notification.user_id == user_id)
        )
    ).all()
    assert [tuple(row) for row in notification_rows] == [(None, action_rows[0].id)]


async def test_accepting_an_appeal_on_an_action_whose_draft_was_deleted_resolves_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작품이 사라진 조치에 이의제기가 수용되면 되돌릴 작품 상태가 없다 — 500이 아니라
    이의제기만 처리된다."""
    _, content = await _restrict_draft_as_admin_then_login_as_owner(db_client, db_session)
    action_id = await db_session.scalar(sa.select(ModerationAction.id))
    assert action_id is not None
    appeal_resp = await db_client.post(
        "/appeals",
        json={"targetKind": "moderation-action", "targetId": str(action_id), "reasonText": "이의 있음"},
    )
    assert appeal_resp.status_code == 201
    assert (await db_client.delete(f"/contents/{content.id}/draft")).status_code == 204

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    resp = await db_client.post(
        f"/admin/appeals/{appeal_resp.json()['appealId']}/resolve", json={"verdict": "accepted"}
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["verdict"] == "accepted"


# --- 미디어 북 -----------------------------------------------------------------------------------


def _axis(entity_id: uuid.UUID, name: str) -> dict[str, object]:
    return {"id": str(entity_id), "name": name}


def _media_cell(
    cell_id: uuid.UUID, person_id: uuid.UUID, scene_id: uuid.UUID, asset_id: uuid.UUID, **overrides: object
) -> dict[str, object]:
    cell: dict[str, object] = {
        "id": str(cell_id),
        "personId": str(person_id),
        "sceneId": str(scene_id),
        "imageAssetId": str(asset_id),
        "situationDescription": "",
        "unlockHint": "",
        "excludeFromChat": False,
    }
    cell.update(overrides)
    return cell


def _media_book(
    people: list[dict[str, object]], scenes: list[dict[str, object]], cells: list[dict[str, object]]
) -> dict[str, object]:
    return {"people": people, "scenes": scenes, "cells": cells}


async def _logged_in_story_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[User, Content, ContentVersion, Asset]:
    """로그인한 작성자의 빈 스토리 초안과 그가 가진 READY 원본 자산 하나."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    version = (
        await db_session.execute(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    ).scalar_one()
    asset = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user, content, version, asset


async def _media_rows(
    db_session: AsyncSession, version_id: uuid.UUID
) -> tuple[list[MediaBookPerson], list[MediaBookScene], list[MediaBookCell]]:
    people = (
        await db_session.scalars(
            sa.select(MediaBookPerson)
            .where(MediaBookPerson.content_version_id == version_id)
            .order_by(MediaBookPerson.order)
            .execution_options(populate_existing=True)
        )
    ).all()
    scenes = (
        await db_session.scalars(
            sa.select(MediaBookScene)
            .where(MediaBookScene.content_version_id == version_id)
            .order_by(MediaBookScene.order)
            .execution_options(populate_existing=True)
        )
    ).all()
    cells = (
        await db_session.scalars(
            sa.select(MediaBookCell)
            .where(MediaBookCell.content_version_id == version_id)
            .execution_options(populate_existing=True)
        )
    ).all()
    return list(people), list(scenes), list(cells)


async def test_patch_story_draft_upserts_media_book_by_entity_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 번째 저장은 같은 entity_id 의 행을 고친다 — 지우고 새로 넣으면 물리 id 가 바뀐다.
    생성 이미지(GENERATED)도 칸에 걸 수 있다."""
    user, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    generated = await _make_asset(db_session, user.id, kind=AssetKind.GENERATED, status=AssetStatus.READY)
    await db_session.commit()
    person_a, person_b, scene_a, scene_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cell_a, cell_b = uuid.uuid4(), uuid.uuid4()

    first = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(person_a, "민아"), _axis(person_b, "준")],
                [_axis(scene_a, "교실")],
                [_media_cell(cell_a, person_a, scene_a, asset.id, situationDescription="웃는다", unlockHint="첫 만남")],
            )
        ),
    )
    assert first.status_code == 200
    _, _, [first_cell] = await _media_rows(db_session, version.id)
    first_cell_physical_id = first_cell.id

    second = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(person_b, "준"), _axis(person_a, "민아 언니")],
                [_axis(scene_a, "교실"), _axis(scene_b, "옥상")],
                [
                    _media_cell(cell_a, person_a, scene_a, asset.id, situationDescription="운다", excludeFromChat=True),
                    _media_cell(cell_b, person_b, scene_b, generated.id),
                ],
            )
        ),
    )
    assert second.status_code == 200

    people, scenes, cells = await _media_rows(db_session, version.id)
    assert [(p.entity_id, p.name, p.order) for p in people] == [(person_b, "준", 0), (person_a, "민아 언니", 1)]
    assert [(s.entity_id, s.name) for s in scenes] == [(scene_a, "교실"), (scene_b, "옥상")]
    cells_by_entity = {cell.entity_id: cell for cell in cells}
    assert set(cells_by_entity) == {cell_a, cell_b}
    updated = cells_by_entity[cell_a]
    assert updated.id == first_cell_physical_id
    assert (updated.situation_description, updated.unlock_hint, updated.exclude_from_chat) == ("운다", "", True)
    inserted = cells_by_entity[cell_b]
    assert (inserted.person_entity_id, inserted.scene_entity_id, inserted.image_asset_id) == (
        person_b,
        scene_b,
        generated.id,
    )

    body = second.json()["mediaBook"]
    assert [p["id"] for p in body["people"]] == [str(person_b), str(person_a)]
    assert {c["id"]: c["excludeFromChat"] for c in body["cells"]} == {str(cell_a): True, str(cell_b): False}


async def test_get_story_draft_returns_media_cells_with_thumbnail_url_and_dimensions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """칸 응답은 썸네일 서명 URL 과 자산의 너비·높이를 싣는다. 크기를 모르는 자산은 null 이다."""
    user, content, _, sized = await _logged_in_story_draft(db_client, db_session)
    sized.width, sized.height = 600, 800
    unsized = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    await db_session.commit()
    person, scene_a, scene_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sized_cell, unsized_cell = uuid.uuid4(), uuid.uuid4()
    patch = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(person, "민아")],
                [_axis(scene_a, "교실"), _axis(scene_b, "옥상")],
                [
                    _media_cell(sized_cell, person, scene_a, sized.id),
                    _media_cell(unsized_cell, person, scene_b, unsized.id),
                ],
            )
        ),
    )
    assert patch.status_code == 200

    resp = await db_client.get(f"/contents/{content.id}/draft")

    assert resp.status_code == 200
    cells = {cell["id"]: cell for cell in resp.json()["mediaBook"]["cells"]}
    assert (cells[str(sized_cell)]["imageWidth"], cells[str(sized_cell)]["imageHeight"]) == (600, 800)
    assert (cells[str(unsized_cell)]["imageWidth"], cells[str(unsized_cell)]["imageHeight"]) == (None, None)
    assert f"{sized.storage_key}_thumb.webp" in cells[str(sized_cell)]["imageUrl"]
    assert cells[str(sized_cell)]["imageAssetId"] == str(sized.id)


async def test_patch_story_draft_without_media_book_keeps_existing_cells(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """미디어 북을 모르는 옛 화면의 자동저장은 키를 안 보낸다 — 그 저장이 칸을 지우면 안 된다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    cell = await _add_media_book_cell(db_session, version.id, asset.id)
    await db_session.commit()

    resp = await db_client.patch(f"/contents/{content.id}/draft", json=_story_draft_payload(name="바뀐 이름"))

    assert resp.status_code == 200
    people, scenes, cells = await _media_rows(db_session, version.id)
    assert (len(people), len(scenes)) == (1, 1)
    assert [c.entity_id for c in cells] == [cell.entity_id]
    assert [c["id"] for c in resp.json()["mediaBook"]["cells"]] == [str(cell.entity_id)]


async def test_patch_story_draft_with_empty_media_book_deletes_everything(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    await _add_media_book_cell(db_session, version.id, asset.id)
    await db_session.commit()

    resp = await db_client.patch(
        f"/contents/{content.id}/draft", json=_story_draft_payload(mediaBook=_media_book([], [], []))
    )

    assert resp.status_code == 200
    assert await _media_rows(db_session, version.id) == ([], [], [])


async def _foreign_asset(db_session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    return (await _make_asset(db_session, other.id, kind=AssetKind.GENERATED, status=AssetStatus.READY)).id


async def _pending_asset(db_session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    return (await _make_asset(db_session, owner_id)).id


async def _blurred_asset(db_session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    return (await _make_asset(db_session, owner_id, kind=AssetKind.BLURRED, status=AssetStatus.READY)).id


async def _missing_asset(db_session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.parametrize(
    "make_asset_id",
    [
        pytest.param(_foreign_asset, id="owned-by-other-user"),
        pytest.param(_pending_asset, id="pending"),
        pytest.param(_blurred_asset, id="blurred-kind"),
        pytest.param(_missing_asset, id="missing"),
    ],
)
async def test_patch_story_draft_rejects_unusable_media_cell_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession, make_asset_id: Any
) -> None:
    """칸 이미지는 요청자 소유의 READY 원본·생성 이미지만 — 남의 생성 이미지를 고르면 그 사람의
    삭제가 막히고, 블러본을 고르면 해금 전 이미지가 원본 자리에 나간다."""
    user, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    asset_id = await make_asset_id(db_session, user.id)
    await db_session.commit()
    person, scene = uuid.uuid4(), uuid.uuid4()

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(person, "민아")], [_axis(scene, "교실")], [_media_cell(uuid.uuid4(), person, scene, asset_id)]
            )
        ),
    )

    assert resp.status_code == 422
    assert (await _media_rows(db_session, version.id))[2] == []


async def test_patch_story_draft_checks_media_cell_assets_in_one_query(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """자동저장마다 칸 50개가 돈다 — 자산 확인도 쓰기도 칸 수만큼 따로 묻지 않는다."""
    _, content, _, asset = await _logged_in_story_draft(db_client, db_session)
    person = uuid.uuid4()

    async def _patch_with(cell_count: int) -> int:
        scenes = [uuid.uuid4() for _ in range(cell_count)]
        with _count_queries() as count:
            resp = await db_client.patch(
                f"/contents/{content.id}/draft",
                json=_story_draft_payload(
                    mediaBook=_media_book(
                        [_axis(person, "민아")],
                        [_axis(scene, f"장면{i}") for i, scene in enumerate(scenes)],
                        [_media_cell(uuid.uuid4(), person, scene, asset.id) for scene in scenes],
                    )
                ),
            )
        assert resp.status_code == 200
        return count()

    # 같은 모양의 저장(칸 n 개 → 새 칸 n 개로 교체)을 두 크기에서 재서 칸 수만큼 늘어나는 쿼리가 없는지 본다.
    await _patch_with(2)
    small = await _patch_with(2)
    await _patch_with(10)
    large = await _patch_with(10)
    assert large == small


async def _thumbnail_kind_asset(db_session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    return (await _make_asset(db_session, owner_id, kind=AssetKind.THUMBNAIL, status=AssetStatus.READY)).id


@pytest.mark.parametrize(
    "make_asset_id",
    [
        pytest.param(_foreign_asset, id="owned-by-other-user"),
        pytest.param(_pending_asset, id="pending"),
        pytest.param(_blurred_asset, id="blurred-kind"),
        pytest.param(_thumbnail_kind_asset, id="thumbnail-kind"),
        pytest.param(_missing_asset, id="missing"),
    ],
)
async def test_patch_character_draft_rejects_unusable_new_thumbnail_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession, make_asset_id: Any
) -> None:
    """새로 거는 대표 이미지는 작가 본인의 업로드 완료 원본이나 생성 이미지여야 한다. 남의 이미지를 걸면 그
    사람이 자기 이미지를 못 지우고, 업로드가 끝나지 않은 자산은 최종 키에 객체가 없다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    asset_id = await make_asset_id(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft", json=_draft_payload(name="바뀐 이름", thumbnailAssetId=str(asset_id))
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Thumbnail must be the creator's own ready upload or generated image"
    version = (
        await db_session.execute(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    ).scalar_one()
    detail = await db_session.get(CharacterVersionDetail, version.id)
    assert detail is not None
    await db_session.refresh(detail)
    assert (detail.name, detail.thumbnail_asset_id) == ("", None)


async def test_patch_story_draft_rejects_another_users_thumbnail_asset(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, _version, _asset = await _logged_in_story_draft(db_client, db_session)
    foreign_asset_id = await _foreign_asset(db_session, user.id)
    await db_session.commit()

    resp = await db_client.patch(
        f"/contents/{content.id}/draft", json=_story_draft_payload(thumbnailAssetId=str(foreign_asset_id))
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Thumbnail must be the creator's own ready upload or generated image"


async def test_patch_character_draft_accepts_own_generated_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """갤러리에서 고른 생성 이미지 — 업로드 원본과 함께 정상 화면이 거는 두 종류 중 하나다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    generated = await _make_asset(db_session, user.id, kind=AssetKind.GENERATED, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft", json=_draft_payload(thumbnailAssetId=str(generated.id))
    )

    assert resp.status_code == 200
    assert resp.json()["thumbnailAssetId"] == str(generated.id)


@pytest.mark.parametrize(
    ("content_type", "detail_model"),
    [
        pytest.param(ContentType.CHARACTER, CharacterVersionDetail, id="character"),
        pytest.param(ContentType.STORY, StoryVersionDetail, id="story"),
    ],
)
async def test_patch_draft_keeps_saving_an_unchanged_seed_thumbnail(
    db_client: httpx.AsyncClient, db_session: AsyncSession, content_type: ContentType, detail_model: Any
) -> None:
    """시드 작품의 대표 이미지는 시드 스크립트가 THUMBNAIL 종류로 직접 넣었다. 빌더 자동저장은 그 값을 그대로
    다시 보내므로, 값이 그대로면 검사하지 않아야 시드 작품을 계속 고칠 수 있다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    if content_type == ContentType.CHARACTER:
        content = await _make_empty_character_draft(db_session, creator_user_id=user.id)
    else:
        content = await _make_empty_story_draft(db_session, creator_user_id=user.id)
    version = (
        await db_session.execute(sa.select(ContentVersion).where(ContentVersion.content_id == content.id))
    ).scalar_one()
    detail = await db_session.get(detail_model, version.id)
    assert detail is not None
    seed_thumbnail_id = await _thumbnail_kind_asset(db_session, user.id)
    detail.thumbnail_asset_id = seed_thumbnail_id
    await db_session.commit()
    await _login_as(db_client, user.id)
    payload_fn = _draft_payload if content_type == ContentType.CHARACTER else _story_draft_payload

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=payload_fn(name="고친 이름", thumbnailAssetId=str(seed_thumbnail_id)),
    )

    assert resp.status_code == 200
    assert resp.json()["name"] == "고친 이름"
    assert resp.json()["thumbnailAssetId"] == str(seed_thumbnail_id)


async def test_patch_story_draft_rejects_fifty_first_media_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person = uuid.uuid4()
    scenes = [uuid.uuid4() for _ in range(51)]

    def _payload(cell_count: int) -> dict[str, object]:
        return _story_draft_payload(
            mediaBook=_media_book(
                [_axis(person, "민아")],
                [_axis(scene, f"장면{i}") for i, scene in enumerate(scenes)],
                [_media_cell(uuid.uuid4(), person, scene, asset.id) for scene in scenes[:cell_count]],
            )
        )

    rejected = await db_client.patch(f"/contents/{content.id}/draft", json=_payload(51))
    assert rejected.status_code == 422
    assert (await _media_rows(db_session, version.id))[2] == []

    accepted = await db_client.patch(f"/contents/{content.id}/draft", json=_payload(50))
    assert accepted.status_code == 200
    assert len((await _media_rows(db_session, version.id))[2]) == 50


@pytest.mark.parametrize(
    ("people", "scenes"),
    [
        pytest.param(["민아", " 민아 "], ["교실"], id="person-after-trim"),
        # 맥 파일명은 한글을 자모로 풀어(NFD) 보낼 수 있다 — 화면에선 같은 이름이다.
        pytest.param(["민아", unicodedata.normalize("NFD", "민아")], ["교실"], id="person-after-nfc"),
        pytest.param(["민아"], ["교실", "교실\t"], id="scene-after-trim"),
    ],
)
async def test_patch_story_draft_rejects_duplicate_axis_name_after_normalizing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, people: list[str], scenes: list[str]
) -> None:
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(uuid.uuid4(), name) for name in people], [_axis(uuid.uuid4(), name) for name in scenes], []
            )
        ),
    )

    assert resp.status_code == 422
    assert await _media_rows(db_session, version.id) == ([], [], [])


async def test_patch_story_draft_stores_media_axis_names_trimmed_and_nfc(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 이름이 다른 바이트로 저장되면 태그 `{{img::인물/장면}}` 의 이름 대조가 갈라진다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    twenty = "가" * 20

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(uuid.uuid4(), "  " + unicodedata.normalize("NFD", "민아") + " ")],
                [_axis(uuid.uuid4(), twenty)],
                [],
            )
        ),
    )

    assert resp.status_code == 200
    people, scenes, _ = await _media_rows(db_session, version.id)
    assert [p.name for p in people] == ["민아"]
    assert [s.name for s in scenes] == [twenty]


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("   ", id="blank"),
        pytest.param("가" * 21, id="over-20"),
        pytest.param("민/아", id="slash"),
        pytest.param("민{아", id="open-brace"),
        pytest.param("민}아", id="close-brace"),
        pytest.param("민:아", id="colon"),
    ],
)
async def test_patch_story_draft_rejects_invalid_media_axis_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession, name: str
) -> None:
    """`/`·`{`·`}`·`:` 는 태그 `{{img::인물/장면}}` 의 구분자라 이름에 들어가면 태그를 못 가른다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(mediaBook=_media_book([], [_axis(uuid.uuid4(), name)], [])),
    )

    assert resp.status_code == 422
    assert await _media_rows(db_session, version.id) == ([], [], [])


async def test_patch_story_draft_rejects_media_cell_pointing_outside_payload_axes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """축 참조에 FK 가 없어 DB 는 고아 칸을 못 막는다 — 요청 검증이 막는다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene = uuid.uuid4(), uuid.uuid4()

    for cell in (
        _media_cell(uuid.uuid4(), uuid.uuid4(), scene, asset.id),
        _media_cell(uuid.uuid4(), person, uuid.uuid4(), asset.id),
    ):
        resp = await db_client.patch(
            f"/contents/{content.id}/draft",
            json=_story_draft_payload(mediaBook=_media_book([_axis(person, "민아")], [_axis(scene, "교실")], [cell])),
        )
        assert resp.status_code == 422

    assert await _media_rows(db_session, version.id) == ([], [], [])


async def test_patch_story_draft_rejects_two_media_cells_at_same_position(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene = uuid.uuid4(), uuid.uuid4()

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(person, "민아")],
                [_axis(scene, "교실")],
                [_media_cell(uuid.uuid4(), person, scene, asset.id), _media_cell(uuid.uuid4(), person, scene, asset.id)],
            )
        ),
    )

    assert resp.status_code == 422
    assert await _media_rows(db_session, version.id) == ([], [], [])


async def test_patch_story_draft_rejects_repeated_media_entity_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """한 목록에 같은 id 가 두 번이면 한 버전에 같은 entity_id 행이 둘이 되려다 500 이 난다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene_a, scene_b, cell = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    for media_book in (
        _media_book([_axis(person, "민아"), _axis(person, "준")], [], []),
        _media_book([], [_axis(scene_a, "교실"), _axis(scene_a, "옥상")], []),
        _media_book(
            [_axis(person, "민아")],
            [_axis(scene_a, "교실"), _axis(scene_b, "옥상")],
            [_media_cell(cell, person, scene_a, asset.id), _media_cell(cell, person, scene_b, asset.id)],
        ),
    ):
        resp = await db_client.patch(f"/contents/{content.id}/draft", json=_story_draft_payload(mediaBook=media_book))
        assert resp.status_code == 422

    assert await _media_rows(db_session, version.id) == ([], [], [])


@pytest.mark.parametrize(
    ("field", "accepted", "rejected"),
    [
        pytest.param("situationDescription", "가" * 100, "가" * 101, id="situation-description"),
        pytest.param("unlockHint", "가" * 20, "가" * 21, id="unlock-hint"),
    ],
)
async def test_patch_story_draft_limits_media_cell_text_length(
    db_client: httpx.AsyncClient, db_session: AsyncSession, field: str, accepted: str, rejected: str
) -> None:
    _, content, _, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene, cell = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def _payload(text: str) -> dict[str, object]:
        return _story_draft_payload(
            mediaBook=_media_book(
                [_axis(person, "민아")], [_axis(scene, "교실")], [_media_cell(cell, person, scene, asset.id, **{field: text})]
            )
        )

    assert (await db_client.patch(f"/contents/{content.id}/draft", json=_payload(rejected))).status_code == 422
    assert (await db_client.patch(f"/contents/{content.id}/draft", json=_payload(accepted))).status_code == 200


async def test_patch_story_draft_clears_blur_when_cell_image_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """블러본은 발행 때 칸 이미지에서 만든다 — 이미지가 바뀌면 옛 블러본은 다른 그림의 블러다."""
    user, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    blurred = await _make_asset(db_session, user.id, kind=AssetKind.BLURRED, status=AssetStatus.READY)
    replacement = await _make_asset(db_session, user.id, status=AssetStatus.READY)
    cell = await _add_media_book_cell(db_session, version.id, asset.id, blurred.id)
    await db_session.commit()

    def _payload(image_id: uuid.UUID) -> dict[str, object]:
        return _story_draft_payload(
            mediaBook=_media_book(
                [_axis(cell.person_entity_id, "민아")],
                [_axis(cell.scene_entity_id, "교실")],
                [_media_cell(cell.entity_id, cell.person_entity_id, cell.scene_entity_id, image_id)],
            )
        )

    same = await db_client.patch(f"/contents/{content.id}/draft", json=_payload(asset.id))
    assert same.status_code == 200
    [kept] = (await _media_rows(db_session, version.id))[2]
    assert kept.blurred_asset_id == blurred.id

    changed = await db_client.patch(f"/contents/{content.id}/draft", json=_payload(replacement.id))
    assert changed.status_code == 200
    [cleared] = (await _media_rows(db_session, version.id))[2]
    assert (cleared.entity_id, cleared.image_asset_id, cleared.blurred_asset_id) == (
        cell.entity_id,
        replacement.id,
        None,
    )


async def test_patch_story_draft_replaces_deleted_cell_with_new_cell_at_same_position(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """칸 하나 자리 UNIQUE 는 즉시 검사라, 새 칸 insert 가 옛 칸 delete 보다 먼저 나가면 500 이다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    old = await _add_media_book_cell(db_session, version.id, asset.id)
    await db_session.commit()
    new_cell = uuid.uuid4()

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                [_axis(old.person_entity_id, "민아")],
                [_axis(old.scene_entity_id, "교실")],
                [_media_cell(new_cell, old.person_entity_id, old.scene_entity_id, asset.id)],
            )
        ),
    )

    assert resp.status_code == 200
    assert [c.entity_id for c in (await _media_rows(db_session, version.id))[2]] == [new_cell]


async def test_patch_story_draft_repeated_new_cell_keeps_one_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene, cell = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    payload = _story_draft_payload(
        mediaBook=_media_book(
            [_axis(person, "민아")], [_axis(scene, "교실")], [_media_cell(cell, person, scene, asset.id)]
        )
    )

    assert (await db_client.patch(f"/contents/{content.id}/draft", json=payload)).status_code == 200
    assert (await db_client.patch(f"/contents/{content.id}/draft", json=payload)).status_code == 200

    people, scenes, cells = await _media_rows(db_session, version.id)
    assert (len(people), len(scenes), [c.entity_id for c in cells]) == (1, 1, [cell])


def _insert_competing_cell_after_patch_reads_cells(
    db_session: AsyncSession, values: dict[str, object]
) -> tuple[Any, list[bool]]:
    """PATCH 가 칸 행을 읽은 직후·쓰기 전에 다른 저장(두 번째 탭)이 칸 하나를 커밋한 순서를 결정적으로
    재현한다. 읽기 결과를 먼저 다 받아 두고 그 뒤에 경쟁 행을 넣는다."""
    raced: list[bool] = []

    def _hook(orm_execute_state: ORMExecuteState) -> Result[Any] | None:
        statement = orm_execute_state.statement
        if raced or not isinstance(statement, sa.Select):
            return None
        if MediaBookCell.__table__ not in statement.get_final_froms():
            return None
        raced.append(True)
        frozen = orm_execute_state.invoke_statement().freeze()
        orm_execute_state.session.connection().execute(sa.insert(MediaBookCell).values(id=uuid.uuid4(), **values))
        return frozen()

    return _hook, raced


async def test_patch_racing_same_new_media_cell_keeps_one_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """겹친 두 저장이 같은 새 칸을 담으면 뒤의 insert 가 앞의 행을 고친다(500 이 아니다)."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene, cell = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    hook, raced = _insert_competing_cell_after_patch_reads_cells(
        db_session,
        {
            "entity_id": cell,
            "content_version_id": version.id,
            "person_entity_id": person,
            "scene_entity_id": scene,
            "image_asset_id": asset.id,
            "situation_description": "먼저 저장된 글",
        },
    )

    sa.event.listen(db_session.sync_session, "do_orm_execute", hook)
    try:
        resp = await db_client.patch(
            f"/contents/{content.id}/draft",
            json=_story_draft_payload(
                mediaBook=_media_book(
                    [_axis(person, "민아")],
                    [_axis(scene, "교실")],
                    [_media_cell(cell, person, scene, asset.id, situationDescription="나중 저장의 글")],
                )
            ),
        )
    finally:
        sa.event.remove(db_session.sync_session, "do_orm_execute", hook)

    assert raced
    assert resp.status_code == 200
    [row] = (await _media_rows(db_session, version.id))[2]
    assert (row.entity_id, row.situation_description) == (cell, "나중 저장의 글")


async def test_patch_racing_other_new_media_cell_at_same_position_returns_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 탭이 서로 다른 새 칸으로 같은 빈 자리를 채우면 둘 중 하나만 남을 수 있다 — 뒤의 저장은
    500 이 아니라 409 와 code 로 거절되고(화면은 새로고침을 안내한다), 앞의 칸은 그대로다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene, winner, loser = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    hook, raced = _insert_competing_cell_after_patch_reads_cells(
        db_session,
        {
            "entity_id": winner,
            "content_version_id": version.id,
            "person_entity_id": person,
            "scene_entity_id": scene,
            "image_asset_id": asset.id,
        },
    )

    sa.event.listen(db_session.sync_session, "do_orm_execute", hook)
    try:
        resp = await db_client.patch(
            f"/contents/{content.id}/draft",
            json=_story_draft_payload(
                mediaBook=_media_book(
                    [_axis(person, "민아")], [_axis(scene, "교실")], [_media_cell(loser, person, scene, asset.id)]
                )
            ),
        )
    finally:
        sa.event.remove(db_session.sync_session, "do_orm_execute", hook)

    assert raced
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "MEDIA_BOOK_CELL_POSITION_TAKEN"}
    assert [c.entity_id for c in (await _media_rows(db_session, version.id))[2]] == [winner]


async def test_get_story_draft_skips_media_cell_whose_axis_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """축이 사라진 칸 하나가 초안 전체를 500 으로 잠그면 빌더가 열리지 않아 화면에서 고칠 길이 없다.
    응답은 그 칸을 빼고 만들고, 다음 미디어 북 저장이 페이로드에 없는 그 칸을 지운다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    kept = await _add_media_book_cell(db_session, version.id, asset.id)
    orphan = MediaBookCell(
        entity_id=uuid.uuid4(),
        content_version_id=version.id,
        person_entity_id=kept.person_entity_id,
        scene_entity_id=uuid.uuid4(),
        image_asset_id=asset.id,
    )
    db_session.add(orphan)
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}/draft")

    assert resp.status_code == 200
    assert [cell["id"] for cell in resp.json()["mediaBook"]["cells"]] == [str(kept.entity_id)]


# --- 겹친 미디어 북 저장의 직렬화 -----------------------------------------------------------------
#
# 아래 테스트는 `db_session`(롤백되는 한 커넥션)을 쓰지 않는다. 행 잠금 대기는 한 트랜잭션 안에서는
# 드러나지 않는다. 여기서 쓴 행은 커밋되므로 픽스처가 표지 도메인으로 골라 지운다.

_MEDIA_BOOK_RACE_DOMAIN = "media-book-race.test"


@pytest_asyncio.fixture
async def committed_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """테스트 DB 에 붙는 별도 엔진. 잠금을 기다리다 영영 멈추지 않게 모든 커넥션에 `lock_timeout` 을
    건다(공용 엔진의 풀 커넥션에 세션 설정을 남기지 않으려고 풀 없는 엔진을 따로 만든다)."""
    committed = create_async_engine(
        db_engine.url.render_as_string(hide_password=False),
        poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "5s"}},
    )
    yield committed
    async with async_sessionmaker(committed, expire_on_commit=False)() as cleanup:
        user_ids = (
            await cleanup.scalars(sa.select(User.id).where(User.email.like(f"%@{_MEDIA_BOOK_RACE_DOMAIN}")))
        ).all()
        if user_ids:
            content_ids = (
                await cleanup.scalars(sa.select(Content.id).where(Content.creator_user_id.in_(user_ids)))
            ).all()
            version_ids = (
                await cleanup.scalars(sa.select(ContentVersion.id).where(ContentVersion.content_id.in_(content_ids)))
            ).all()
            for model in (MediaBookCell, MediaBookPerson, MediaBookScene, StoryVersionDetail):
                await cleanup.execute(sa.delete(model).where(model.content_version_id.in_(version_ids)))
            await cleanup.execute(sa.delete(ContentVersion).where(ContentVersion.id.in_(version_ids)))
            await cleanup.execute(sa.delete(Content).where(Content.id.in_(content_ids)))
            await cleanup.execute(sa.delete(Asset).where(Asset.owner_user_id.in_(user_ids)))
            await cleanup.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()
    await committed.dispose()


async def _wait_until_a_lock_is_awaited(engine: AsyncEngine) -> None:
    """어떤 트랜잭션이 잠금을 기다리기 시작할 때까지 기다린다(시간이 아니라 상태로 순서를 강제한다).
    행 잠금 대기는 상대 트랜잭션 id 를 기다리는 모양이라 `pg_locks` 로는 데이터베이스를 가릴 수 없어
    `pg_stat_activity` 의 대기 종류로 본다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    while True:
        async with factory() as probe:
            waiting = await probe.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.01)


async def test_patch_adding_a_cell_while_another_save_deletes_its_axis_leaves_no_orphan(
    committed_engine: AsyncEngine, db_client: httpx.AsyncClient
) -> None:
    """두 탭이 같은 초안을 저장한다. 탭 A 의 저장이 장면 하나를 지운 채 커밋 직전에 있을 때, 그 장면이
    아직 보이는 탭 B 가 그 자리에 새 칸을 담아 저장한다. B 가 A 의 커밋 전 상태를 읽고 칸만 넣으면 A 의
    커밋 뒤 축 없는 칸이 남아 그 초안의 GET 이 500 이 된다. 미디어 북 쓰기는 초안 단위로 줄을 서므로
    B 는 A 가 커밋할 때까지 기다렸다가 A 의 결과 위에 자기 페이로드(장면 포함)를 맞춰 넣는다."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    async with factory() as setup:
        user = _make_user(email=f"owner-{uuid.uuid4()}@{_MEDIA_BOOK_RACE_DOMAIN}")
        setup.add(user)
        await setup.flush()
        content = await _make_empty_story_draft(setup, creator_user_id=user.id)
        version_id = await setup.scalar(sa.select(ContentVersion.id).where(ContentVersion.content_id == content.id))
        asset = await _make_asset(setup, user.id, status=AssetStatus.READY)
        await setup.commit()
    assert version_id is not None
    person, hallway, new_cell = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    both_axes = ([_axis(person, "민아")], [_axis(hallway, "복도")])

    holding, release = asyncio.Event(), asyncio.Event()

    class _StoppingSession(AsyncSession):
        async def commit(self) -> None:
            await self.flush()
            holding.set()
            await release.wait()
            await super().commit()

    request_factories: list[async_sessionmaker[AsyncSession]] = []

    async def _request_session() -> AsyncGenerator[AsyncSession, None]:
        chosen = request_factories.pop(0) if request_factories else factory
        async with chosen() as session:
            yield session

    saved = {key: app.dependency_overrides[key] for key in (get_db_session, get_session_factory)}
    app.dependency_overrides[get_db_session] = _request_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    tab_a: asyncio.Task[httpx.Response] | None = None
    tab_b: asyncio.Task[httpx.Response] | None = None
    try:
        await _login_as(db_client, user.id)
        # 앞선 자동저장으로 장면 둘이 이미 저장돼 있다 — 두 탭의 나머지 필드는 같아 초안 상세 행에는
        # 쓰지 않는다(그 행의 UPDATE 잠금이 우연히 둘을 줄 세우지 않게).
        first = await db_client.patch(
            f"/contents/{content.id}/draft", json=_story_draft_payload(mediaBook=_media_book(*both_axes, []))
        )
        assert first.status_code == 200

        request_factories.append(async_sessionmaker(committed_engine, class_=_StoppingSession, expire_on_commit=False))
        tab_a = asyncio.create_task(
            db_client.patch(
                f"/contents/{content.id}/draft",
                json=_story_draft_payload(mediaBook=_media_book(both_axes[0], [], [])),
            )
        )
        await asyncio.wait_for(holding.wait(), 5)
        tab_b = asyncio.create_task(
            db_client.patch(
                f"/contents/{content.id}/draft",
                json=_story_draft_payload(
                    mediaBook=_media_book(*both_axes, [_media_cell(new_cell, person, hallway, asset.id)])
                ),
            )
        )
        lock_wait = asyncio.create_task(_wait_until_a_lock_is_awaited(committed_engine))
        done, _ = await asyncio.wait({tab_b, lock_wait}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        lock_wait.cancel()
        # B 가 A 를 기다리지 않고 먼저 끝났다면 겹친 저장이 줄을 서지 않은 것이다.
        b_waited_for_a = lock_wait in done and not tab_b.done()
        release.set()
        resp_a = await asyncio.wait_for(tab_a, 10)
        resp_b = await asyncio.wait_for(tab_b, 10)
        draft = await db_client.get(f"/contents/{content.id}/draft")
    finally:
        release.set()
        for task in (tab_a, tab_b):
            if task is not None and not task.done():
                await asyncio.wait_for(task, 10)
        app.dependency_overrides.update(saved)

    assert (resp_a.status_code, resp_b.status_code) == (200, 200)
    async with factory() as check:
        scene_ids = (
            await check.scalars(sa.select(MediaBookScene.entity_id).where(MediaBookScene.content_version_id == version_id))
        ).all()
        cells = (
            await check.execute(
                sa.select(MediaBookCell.entity_id, MediaBookCell.scene_entity_id).where(
                    MediaBookCell.content_version_id == version_id
                )
            )
        ).all()
    assert (scene_ids, [tuple(cell) for cell in cells]) == ([hallway], [(new_cell, hallway)])
    assert b_waited_for_a
    assert draft.status_code == 200
    assert [cell["id"] for cell in draft.json()["mediaBook"]["cells"]] == [str(new_cell)]


async def test_patch_story_draft_rejects_moving_existing_media_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """빌더에는 칸을 옮기는 동작이 없다. 기존 칸 둘의 자리를 맞바꾸면 행을 하나씩 고치는 도중 같은
    자리가 둘이 되어 500 이 나므로, 기존 칸의 자리 변경은 받지 않는다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    person, scene_a, scene_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cell_a, cell_b = uuid.uuid4(), uuid.uuid4()
    axes = ([_axis(person, "민아")], [_axis(scene_a, "교실"), _axis(scene_b, "옥상")])
    created = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(*axes, [_media_cell(cell_a, person, scene_a, asset.id)])
        ),
    )
    assert created.status_code == 200

    moved = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(mediaBook=_media_book(*axes, [_media_cell(cell_a, person, scene_b, asset.id)])),
    )
    assert moved.status_code == 422

    both = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                *axes,
                [_media_cell(cell_a, person, scene_a, asset.id), _media_cell(cell_b, person, scene_b, asset.id)],
            )
        ),
    )
    assert both.status_code == 200
    swapped = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            mediaBook=_media_book(
                *axes,
                [_media_cell(cell_a, person, scene_b, asset.id), _media_cell(cell_b, person, scene_a, asset.id)],
            )
        ),
    )
    assert swapped.status_code == 422

    cells = {c.entity_id: c.scene_entity_id for c in (await _media_rows(db_session, version.id))[2]}
    assert cells == {cell_a: scene_a, cell_b: scene_b}


async def test_patch_story_draft_swaps_media_axis_names(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이름 중복은 DB 가 아니라 요청 검증이 막는다 — 그래서 한 저장 안의 이름 맞바꾸기가 된다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    person_a, person_b = uuid.uuid4(), uuid.uuid4()
    first = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(mediaBook=_media_book([_axis(person_a, "민아"), _axis(person_b, "준")], [], [])),
    )
    assert first.status_code == 200

    swapped = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(mediaBook=_media_book([_axis(person_a, "준"), _axis(person_b, "민아")], [], [])),
    )

    assert swapped.status_code == 200
    people, _, _ = await _media_rows(db_session, version.id)
    assert [(p.entity_id, p.name) for p in people] == [(person_a, "준"), (person_b, "민아")]


async def test_delete_story_draft_with_media_book(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """칸·축은 버전에 물리 FK 로 매달려 있어 함께 지우지 않으면 초안 삭제가 FK 위반 500 이다."""
    _, content, version, asset = await _logged_in_story_draft(db_client, db_session)
    await _add_media_book_cell(db_session, version.id, asset.id)
    await db_session.commit()

    resp = await db_client.delete(f"/contents/{content.id}/draft")

    assert resp.status_code == 204
    assert await _media_rows(db_session, version.id) == ([], [], [])
    assert await db_session.get(Asset, asset.id) is not None


# --- 키워드북: 저장 검증 · 순서 · 옵션 · 시작설정 참조 ---


def _keyword_note_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "infoText": "정보",
        "triggerKeywords": ["단서"],
        "startingSetupId": None,
    }
    item.update(overrides)
    return item


async def _keyword_notes_by_order(db_session: AsyncSession, version_id: uuid.UUID) -> list[KeywordNote]:
    return list(
        (
            await db_session.scalars(
                sa.select(KeywordNote)
                .where(KeywordNote.content_version_id == version_id)
                .order_by(KeywordNote.order)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


@pytest.mark.parametrize("field", ["triggerKeywords", "excludeKeywords"])
async def test_patch_story_draft_rejects_blank_keyword(
    db_client: httpx.AsyncClient, db_session: AsyncSession, field: str
) -> None:
    """공백은 거의 모든 글에 들어 있어 공백뿐인 키워드는 키워드 구실을 못 한다 — 저장에서 막는다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(keywordNotes=[_keyword_note_item(**{field: ["단서", " \u3000"]})]),
    )

    assert resp.status_code == 422
    assert await _keyword_notes_by_order(db_session, version.id) == []


@pytest.mark.parametrize("field", ["triggerKeywords", "excludeKeywords"])
@pytest.mark.parametrize(
    "keywords",
    [
        pytest.param(["USB", "usb"], id="ascii-case"),
        pytest.param(["단서", unicodedata.normalize("NFD", "단서")], id="nfd"),
        # casefold 는 ß 를 ss 로 접는다 — 소문자화만 하면 둘을 다른 키워드로 본다.
        pytest.param(["strasse", "STRAßE"], id="casefold"),
    ],
)
async def test_patch_story_draft_rejects_case_insensitive_duplicate_keyword(
    db_client: httpx.AsyncClient, db_session: AsyncSession, field: str, keywords: list[str]
) -> None:
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(keywordNotes=[_keyword_note_item(**{field: keywords})]),
    )

    assert resp.status_code == 422
    assert await _keyword_notes_by_order(db_session, version.id) == []


async def test_patch_story_draft_measures_keyword_length_before_normalizing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """빌더는 보낼 글자 그대로의 코드 포인트 수로 20자를 막는다. NFC 로 바꾸면 길어지는 문자(U+0344 는 두 코드
    포인트가 된다)가 있어, 서버가 정규화한 뒤에 재면 빌더가 받아 준 키워드를 서버가 거절해 자동저장이 멈춘다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    # 앞 글자와 합쳐지지 않게 맨 앞에 둔다 — 뒤에 두면 앞의 a 와 합성돼 길이가 그대로다.
    keyword = "\u0344" + "a" * 19
    assert len(keyword) == 20 and len(unicodedata.normalize("NFC", keyword)) == 21

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(keywordNotes=[_keyword_note_item(triggerKeywords=[keyword])]),
    )

    assert resp.status_code == 200
    [note] = await _keyword_notes_by_order(db_session, version.id)
    assert note.trigger_keywords == [keyword]


async def test_patch_story_draft_rejects_fourth_always_on_note(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)

    def _payload(always_on_count: int) -> dict[str, object]:
        return _story_draft_payload(
            keywordNotes=[_keyword_note_item(alwaysOn=True) for _ in range(always_on_count)]
            + [_keyword_note_item(alwaysOn=False)]
        )

    rejected = await db_client.patch(f"/contents/{content.id}/draft", json=_payload(4))
    assert rejected.status_code == 422
    assert await _keyword_notes_by_order(db_session, version.id) == []

    accepted = await db_client.patch(f"/contents/{content.id}/draft", json=_payload(3))
    assert accepted.status_code == 200
    assert [n.always_on for n in await _keyword_notes_by_order(db_session, version.id)] == [True, True, True, False]


async def test_patch_story_draft_accepts_new_keyword_note_without_keywords(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """빌더의 "노트 추가" 직후 자동저장은 빈 정보·빈 키워드 노트를 그대로 보낸다. 키워드가 있어야 한다는 규칙은
    발행이 검사한다 — 저장에서 막으면 노트를 추가할 때마다 자동저장이 멈춘다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(keywordNotes=[_keyword_note_item(infoText="", triggerKeywords=[])]),
    )

    assert resp.status_code == 200
    [note] = await _keyword_notes_by_order(db_session, version.id)
    assert (note.info_text, note.trigger_keywords) == ("", [])


async def test_patch_story_draft_accepts_exclude_keywords_on_always_on_note(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상시 노트도 금지 키워드가 나온 턴에는 빠진다 — 상시 노트의 금지 키워드는 버리는 값이 아니다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            keywordNotes=[_keyword_note_item(triggerKeywords=[], alwaysOn=True, excludeKeywords=["회상"])]
        ),
    )

    assert resp.status_code == 200
    [note] = await _keyword_notes_by_order(db_session, version.id)
    assert (note.always_on, note.exclude_keywords) == (True, ["회상"])
    assert resp.json()["keywordNotes"][0]["excludeKeywords"] == ["회상"]


async def test_patch_story_draft_rejects_keyword_note_pointing_to_unknown_starting_setup(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """지금까지는 모르는 시작설정을 조용히 "스토리 전체"로 바꿔 저장했다 — 작가가 고른 범위가 말없이 넓어진다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    setup_id = str(uuid.uuid4())

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=[_starting_setup_item(id=setup_id)],
            keywordNotes=[
                _keyword_note_item(startingSetupId=setup_id),
                _keyword_note_item(name="", triggerKeywords=["잃어버린 열쇠"], startingSetupId=str(uuid.uuid4())),
            ],
        ),
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "KEYWORD_NOTE_STARTING_SETUP_NOT_FOUND"
    assert (detail["index"], detail["label"]) == (1, "잃어버린 열쇠")
    assert await _keyword_notes_by_order(db_session, version.id) == []


async def test_patch_story_draft_rejects_ending_rule_pointing_to_stat_missing_from_its_setup(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """스탯을 지우고 규칙을 남긴 초안을 그대로 받으면 그 엔딩 조건은 영영 참이 될 수 없다. 다른 시작설정의 스탯도
    같은 시작설정에 없으면 없는 스탯이다. 그룹 안 규칙까지 경로로 알리고 아무것도 저장하지 않는다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    own_stat, other_setup_stat = str(uuid.uuid4()), str(uuid.uuid4())

    def rule(stat_id: str) -> dict[str, object]:
        return {"kind": "rule", "id": str(uuid.uuid4()), "statId": stat_id, "operator": "gte", "threshold": 1, "nextOp": "and"}

    ending = {
        "id": str(uuid.uuid4()),
        "name": "엔딩",
        "turnCountGate": 10,
        "judgmentPrompt": "판정",
        "epilogue": None,
        "hint": None,
        "statRules": [
            rule(own_stat),
            rule(other_setup_stat),
            {"kind": "group", "id": str(uuid.uuid4()), "nextOp": None, "rules": [rule(own_stat), rule(str(uuid.uuid4()))]},
        ],
    }
    stat_item = {
        "name": "체력",
        "icon": "heart",
        "color": "rose",
        "minValue": 0,
        "maxValue": 100,
        "initialValue": 50,
        "unit": None,
        "description": "체력",
    }

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=[
                _starting_setup_item(statDefs=[{**stat_item, "id": own_stat}], endings=[ending]),
                _starting_setup_item(statDefs=[{**stat_item, "id": other_setup_stat}]),
            ]
        ),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == {
        "code": "ENDING_RULE_STAT_NOT_FOUND",
        "paths": [
            "startingSetups[0].endings[0].statRules[1].statId",
            "startingSetups[0].endings[0].statRules[2].rules[1].statId",
        ],
    }
    saved_setups = (
        await db_session.scalars(sa.select(StartingSetup).where(StartingSetup.content_version_id == version.id))
    ).all()
    assert saved_setups == []


async def test_patch_story_draft_keeps_accepting_stat_whose_range_is_contradictory(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """범위가 모순된 스탯(최소 > 최대, 범위 밖 초기값)도 초안 저장은 받아 저장한다. 이 검사는 발행만 한다 — 이미 그렇게
    저장된 초안이 있어서, 저장에서 막으면 그 초안의 자동저장이 편집마다 실패한다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    stat_item = {
        "id": str(uuid.uuid4()),
        "name": "체력",
        "icon": "heart",
        "color": "rose",
        "minValue": 100,
        "maxValue": 0,
        "initialValue": 500,
        "unit": None,
        "description": "체력",
    }

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(startingSetups=[_starting_setup_item(statDefs=[stat_item])]),
    )

    assert resp.status_code == 200
    saved = (
        await db_session.scalars(
            sa.select(StatDef)
            .join(StartingSetup, StatDef.starting_setup_id == StartingSetup.id)
            .where(StartingSetup.content_version_id == version.id)
        )
    ).all()
    assert [(s.min_value, s.max_value, s.initial_value) for s in saved] == [(100, 0, 500)]


async def test_patch_story_draft_persists_keyword_note_order_from_array_position(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    items = [_keyword_note_item(triggerKeywords=[f"키{i}"]) for i in range(3)]

    first = await db_client.patch(f"/contents/{content.id}/draft", json=_story_draft_payload(keywordNotes=items))
    assert first.status_code == 200
    reordered = [items[2], items[0], items[1]]
    second = await db_client.patch(
        f"/contents/{content.id}/draft", json=_story_draft_payload(keywordNotes=reordered)
    )

    assert second.status_code == 200
    notes = await _keyword_notes_by_order(db_session, version.id)
    assert [(str(n.entity_id), n.order) for n in notes] == [(item["id"], i) for i, item in enumerate(reordered)]
    assert [n["id"] for n in second.json()["keywordNotes"]] == [item["id"] for item in reordered]


async def test_get_story_draft_returns_notes_in_saved_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`order` 와 거꾸로 삽입해 힙 순서와 `order` 를 엇갈리게 둔다 — 같게 두면 ORDER BY 가 없어도 통과한다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    entity_ids = [uuid.uuid4() for _ in range(5)]
    for order in reversed(range(5)):
        db_session.add(
            KeywordNote(
                entity_id=entity_ids[order],
                content_version_id=version.id,
                info_text=f"정보{order}",
                trigger_keywords=[f"키{order}"],
                order=order,
            )
        )
        await db_session.flush()
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}/draft")

    assert resp.status_code == 200
    assert [n["id"] for n in resp.json()["keywordNotes"]] == [str(e) for e in entity_ids]


async def test_patch_story_draft_keeps_keyword_note_options_when_fields_omitted(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """옵션을 모르는 화면(배포 전부터 열려 있던 탭의 옛 번들)의 자동저장이 작가가 켠 상시·유지·금지·이름을 기본값으로
    되돌리면 안 된다. 새 노트는 기본값으로 들어간다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    kept_id = uuid.uuid4()
    db_session.add(
        KeywordNote(
            entity_id=kept_id,
            content_version_id=version.id,
            info_text="정보",
            trigger_keywords=["단서"],
            name="이름",
            exclude_keywords=["금지"],
            sticky_turns=3,
            always_on=True,
        )
    )
    await db_session.commit()
    new_id = str(uuid.uuid4())

    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            keywordNotes=[
                {"id": str(kept_id), "infoText": "고친 정보", "triggerKeywords": ["단서"], "startingSetupId": None},
                {"id": new_id, "infoText": "새 정보", "triggerKeywords": ["새"], "startingSetupId": None},
            ]
        ),
    )

    assert resp.status_code == 200
    kept, new = await _keyword_notes_by_order(db_session, version.id)
    assert (kept.info_text, kept.name, kept.exclude_keywords, kept.sticky_turns, kept.always_on) == (
        "고친 정보",
        "이름",
        ["금지"],
        3,
        True,
    )
    assert (new.name, new.exclude_keywords, new.sticky_turns, new.always_on) == ("", [], 0, False)

    cleared = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            keywordNotes=[
                _keyword_note_item(
                    id=str(kept_id), name="", excludeKeywords=[], stickyTurns=0, alwaysOn=False
                )
            ]
        ),
    )
    assert cleared.status_code == 200
    [kept] = await _keyword_notes_by_order(db_session, version.id)
    assert (kept.name, kept.exclude_keywords, kept.sticky_turns, kept.always_on) == ("", [], 0, False)


async def test_get_story_draft_returns_keyword_notes_over_save_limits(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """저장 상한은 요청에만 건다. 상한이 생기기 전에 저장된 행이나 서버를 이전 버전으로 되돌린 사이 저장된 행이
    상한을 넘어도 초안을 열 수 있어야 한다 — 응답 직렬화에서 검증하면 그 초안의 GET 이 500 이다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    for index in range(51):
        db_session.add(
            KeywordNote(
                entity_id=uuid.uuid4(),
                content_version_id=version.id,
                info_text="가" * 900,
                trigger_keywords=["열쇠" * 11] * 11 + ["USB", "usb", " "],
                name="이" * 30,
                exclude_keywords=["금" * 21] * 11,
                sticky_turns=9,
                always_on=index < 4,
                order=index,
            )
        )
    await db_session.commit()

    resp = await db_client.get(f"/contents/{content.id}/draft")

    assert resp.status_code == 200
    notes = resp.json()["keywordNotes"]
    assert len(notes) == 51
    assert (len(notes[0]["infoText"]), notes[0]["stickyTurns"], notes[0]["name"]) == (900, 9, "이" * 30)


@pytest.mark.parametrize("keep_other_setup", [True, False], ids=["other-setup-kept", "last-setup-removed"])
async def test_patch_removing_setup_referenced_by_note_succeeds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, keep_other_setup: bool
) -> None:
    """빌더에서 노트가 가리키는 시작설정을 지우면, 빌더는 그 노트를 스토리 전체로 돌린 값과 시작설정이 빠진 목록을
    보낸다. 삭제 직후 자동저장 대기 시간 안에 다른 편집이 이어지면 둘이 한 저장에 실려 온다 — 아래 페이로드가 그
    모양이고, 남은 시작설정의 플레이가이드 변경이 "이어진 다른 편집"이다. DB 의 노트는 아직 지울 시작설정을 가리키고
    있으므로 시작설정을 먼저 지우면 물리 FK 위반이다."""
    _, content, version, _ = await _logged_in_story_draft(db_client, db_session)
    kept_setup_id, removed_setup_id, note_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    kept_item = _starting_setup_item(id=kept_setup_id, name="남는 설정")
    removed_item = _starting_setup_item(id=removed_setup_id, name="지울 설정")
    setups_before = [kept_item, removed_item] if keep_other_setup else [removed_item]
    created = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=setups_before,
            keywordNotes=[_keyword_note_item(id=note_id, startingSetupId=removed_setup_id)],
        ),
    )
    assert created.status_code == 200

    setups_after = [{**kept_item, "playguide": "이어서 친 글"}] if keep_other_setup else []
    resp = await db_client.patch(
        f"/contents/{content.id}/draft",
        json=_story_draft_payload(
            startingSetups=setups_after,
            keywordNotes=[_keyword_note_item(id=note_id, startingSetupId=None)],
        ),
    )

    assert resp.status_code == 200
    remaining = (
        await db_session.scalars(
            sa.select(StartingSetup)
            .where(StartingSetup.content_version_id == version.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    assert [str(s.entity_id) for s in remaining] == ([kept_setup_id] if keep_other_setup else [])
    [note] = await _keyword_notes_by_order(db_session, version.id)
    assert note.starting_setup_id is None
    if keep_other_setup:
        assert remaining[0].playguide == "이어서 친 글"
