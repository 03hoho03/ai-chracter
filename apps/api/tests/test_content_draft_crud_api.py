import io
import uuid
from datetime import date, datetime, timezone

import boto3
import httpx
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

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
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    KeywordNote,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
)


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


async def test_create_content_draft_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/contents", json={"type": "character"})
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


async def test_get_content_draft_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(f"/contents/{uuid.uuid4()}/draft")
    assert resp.status_code == 401


async def test_get_content_draft_returns_404_for_missing_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)

    resp = await db_client.get(f"/contents/{uuid.uuid4()}/draft")
    assert resp.status_code == 404


async def test_get_content_draft_returns_403_for_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.get(f"/contents/{content.id}/draft")
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
    assert body["promptTemplate"] == "basic"
    assert body["settingText"] is None
    assert body["developmentExample"] is None
    assert body["customPrompt"] is None
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
    assert body["type"] == "character"
    assert body["name"] == ""
    assert body["oneLiner"] == ""
    assert body["thumbnailAssetId"] is None
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


async def test_patch_content_draft_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.patch(f"/contents/{uuid.uuid4()}/draft", json=_draft_payload())
    assert resp.status_code == 401


async def test_patch_content_draft_returns_403_for_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_empty_character_draft(db_session, creator_user_id=owner.id)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.patch(f"/contents/{content.id}/draft", json=_draft_payload())
    assert resp.status_code == 403


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
    (shared across versions, not per-version snapshot data) — US-083 depends on these being
    settable so a draft can ever pass publish validation."""
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
    (US-071) — this endpoint must not null them out when it updates trigger_condition/order
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

    # GET returns the same tree (AC1: startingSetups(entity_id, order) + descendants).
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
