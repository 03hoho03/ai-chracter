import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
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


async def _make_asset(db_session: AsyncSession, *, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/original/{uuid.uuid4()}.png",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_content(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, content_type: ContentType
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def _add_version(
    db_session: AsyncSession, content: Content, *, detail_description: str, published: bool
) -> ContentVersion:
    """Adds one content_version. `published=True` also points `content` at it — publishing
    is what sets that pointer, and it's the only thing `reset_content_draft` branches on."""
    version = ContentVersion(content_id=content.id, detail_description=detail_description)
    if published:
        version.version_number = 1
        version.published_at = datetime.now(timezone.utc)
    db_session.add(version)
    await db_session.flush()
    if published:
        content.current_published_version_id = version.id
        await db_session.flush()
    return version


async def _add_character_version_rows(
    db_session: AsyncSession,
    version: ContentVersion,
    *,
    name: str,
    thumbnail_asset_id: uuid.UUID | None,
    image_entity_id: uuid.UUID,
    image_asset_id: uuid.UUID | None,
    blurred_asset_id: uuid.UUID | None,
    trigger_condition: str,
) -> None:
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner=f"{name} 한 줄",
            thumbnail_asset_id=thumbnail_asset_id,
            intro=f"{name} 인트로",
            example_dialogues=[{"id": "d1", "userLine": name, "characterLine": name}],
            character_prompt=f"너는 {name}이다.",
            playguide=f"{name} 플레이가이드",
        )
    )
    db_session.add(
        SituationalImage(
            entity_id=image_entity_id,
            content_version_id=version.id,
            image_asset_id=image_asset_id,
            blurred_asset_id=blurred_asset_id,
            trigger_condition=trigger_condition,
            order=0,
        )
    )
    await db_session.flush()


async def _add_story_version_rows(
    db_session: AsyncSession,
    version: ContentVersion,
    *,
    name: str,
    setup_entity_id: uuid.UUID,
    stat_entity_id: uuid.UUID,
    ending_entity_id: uuid.UUID,
    note_entity_id: uuid.UUID,
    shortcut_entity_id: uuid.UUID,
) -> StartingSetup:
    """One starting setup carrying a stat, an ending with a top-level rule plus a nested
    rule group, a keyword note scoped to that setup, and a shortcut — deep enough that a
    reset has to walk every tier and remap `keyword_notes.starting_setup_id`."""
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name=name,
            one_liner=f"{name} 한 줄",
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text=f"{name} 세계관",
            development_example=f"{name} 전개 예시",
        )
    )

    setup = StartingSetup(
        entity_id=setup_entity_id,
        content_version_id=version.id,
        name=f"{name} 시작설정",
        prologue=f"{name} 프롤로그",
        opening_message=f"{name} 오프닝",
        suggested_replies=[f"{name} 추천답변"],
        order=0,
    )
    db_session.add(setup)
    await db_session.flush()

    db_session.add(
        StatDef(
            entity_id=stat_entity_id,
            starting_setup_id=setup.id,
            name=f"{name} 스탯",
            icon="heart",
            color="rose",
            min_value=0,
            max_value=100,
            initial_value=50,
            description=f"{name} 스탯 설명",
            per_turn_delta=-1,
            order=0,
        )
    )

    ending = Ending(
        entity_id=ending_entity_id,
        starting_setup_id=setup.id,
        name=f"{name} 엔딩",
        turn_count_gate=10,
        judgment_prompt=f"{name} 판정",
        epilogue=f"{name} 에필로그",
        order=0,
    )
    db_session.add(ending)
    await db_session.flush()

    db_session.add(
        EndingRule(
            entity_id=uuid.uuid4(),
            ending_id=ending.id,
            stat_def_entity_id=stat_entity_id,
            operator=EndingRuleOperator.GTE,
            threshold=Decimal(50),
            next_op=LogicalOp.AND,
            order=0,
        )
    )
    group = EndingRuleGroup(entity_id=uuid.uuid4(), ending_id=ending.id, next_op=None, order=1)
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        EndingRule(
            entity_id=uuid.uuid4(),
            rule_group_id=group.id,
            stat_def_entity_id=stat_entity_id,
            operator=EndingRuleOperator.LT,
            threshold=Decimal(10),
            order=0,
        )
    )

    db_session.add(
        KeywordNote(
            entity_id=note_entity_id,
            content_version_id=version.id,
            starting_setup_id=setup.id,
            info_text=f"{name} 노트",
            trigger_keywords=[name],
        )
    )
    db_session.add(
        Shortcut(
            entity_id=shortcut_entity_id,
            content_version_id=version.id,
            name=f"{name} 단축어",
            description=f"{name} 설명",
            prompt=f"{name} 프롬프트",
        )
    )
    await db_session.flush()
    return setup


async def test_reset_content_draft_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(f"/contents/{uuid.uuid4()}/draft/reset")
    assert resp.status_code == 401


async def test_reset_content_draft_returns_404_for_missing_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{uuid.uuid4()}/draft/reset")
    assert resp.status_code == 404


async def test_reset_content_draft_returns_403_for_non_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    content = await _make_content(
        db_session, creator_user_id=owner.id, content_type=ContentType.CHARACTER
    )
    published = await _add_version(db_session, content, detail_description="발행본", published=True)
    await _add_character_version_rows(
        db_session,
        published,
        name="발행본",
        thumbnail_asset_id=None,
        image_entity_id=uuid.uuid4(),
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="발행 조건",
    )
    draft = await _add_version(db_session, content, detail_description="편집중", published=False)
    await _add_character_version_rows(
        db_session,
        draft,
        name="편집중",
        thumbnail_asset_id=None,
        image_entity_id=uuid.uuid4(),
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="편집 조건",
    )
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 403

    draft_detail = await db_session.get(CharacterVersionDetail, draft.id)
    assert draft_detail is not None
    assert draft_detail.name == "편집중"


async def test_reset_content_draft_returns_400_for_never_published_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """No published version means there is nothing to reset *to* — the exit for this case is
    `DELETE /contents/{id}/draft` (US-003), which is exactly the set this 400 complements."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(
        db_session, creator_user_id=user.id, content_type=ContentType.CHARACTER
    )
    draft = await _add_version(db_session, content, detail_description="편집중", published=False)
    await _add_character_version_rows(
        db_session,
        draft,
        name="편집중",
        thumbnail_asset_id=None,
        image_entity_id=uuid.uuid4(),
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="편집 조건",
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 400

    draft_detail = await db_session.get(CharacterVersionDetail, draft.id)
    assert draft_detail is not None
    assert draft_detail.name == "편집중"


async def test_reset_content_draft_restores_character_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    published_thumbnail = await _make_asset(db_session, owner_user_id=user.id)
    published_image = await _make_asset(db_session, owner_user_id=user.id)
    published_blurred = await _make_asset(db_session, owner_user_id=user.id)
    draft_thumbnail = await _make_asset(db_session, owner_user_id=user.id)

    content = await _make_content(
        db_session, creator_user_id=user.id, content_type=ContentType.CHARACTER
    )
    published_image_entity_id = uuid.uuid4()
    draft_image_entity_id = uuid.uuid4()

    published = await _add_version(db_session, content, detail_description="발행본 설명", published=True)
    await _add_character_version_rows(
        db_session,
        published,
        name="발행본",
        thumbnail_asset_id=published_thumbnail.id,
        image_entity_id=published_image_entity_id,
        image_asset_id=published_image.id,
        blurred_asset_id=published_blurred.id,
        trigger_condition="발행 조건",
    )
    draft = await _add_version(db_session, content, detail_description="편집중 설명", published=False)
    await _add_character_version_rows(
        db_session,
        draft,
        name="편집중",
        thumbnail_asset_id=draft_thumbnail.id,
        image_entity_id=draft_image_entity_id,
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="편집 조건",
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 204

    draft_version = await db_session.get(ContentVersion, draft.id)
    assert draft_version is not None, "the draft row must survive — PATCH .../draft targets it"
    assert draft_version.detail_description == "발행본 설명"

    draft_detail = await db_session.get(CharacterVersionDetail, draft.id)
    assert draft_detail is not None
    assert draft_detail.name == "발행본"
    assert draft_detail.one_liner == "발행본 한 줄"
    assert draft_detail.thumbnail_asset_id == published_thumbnail.id
    assert draft_detail.intro == "발행본 인트로"
    assert draft_detail.example_dialogues == [
        {"id": "d1", "userLine": "발행본", "characterLine": "발행본"}
    ]
    assert draft_detail.character_prompt == "너는 발행본이다."
    assert draft_detail.playguide == "발행본 플레이가이드"

    draft_images = (
        await db_session.scalars(
            sa.select(SituationalImage).where(SituationalImage.content_version_id == draft.id)
        )
    ).all()
    assert [image.entity_id for image in draft_images] == [published_image_entity_id]
    assert draft_images[0].image_asset_id == published_image.id
    assert draft_images[0].blurred_asset_id == published_blurred.id
    assert draft_images[0].trigger_condition == "발행 조건"

    assert (
        await db_session.scalar(
            sa.select(SituationalImage).where(SituationalImage.entity_id == draft_image_entity_id)
        )
    ) is None


async def test_reset_content_draft_leaves_published_character_version_intact(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(
        db_session, creator_user_id=user.id, content_type=ContentType.CHARACTER
    )
    published_image_entity_id = uuid.uuid4()
    published = await _add_version(db_session, content, detail_description="발행본 설명", published=True)
    await _add_character_version_rows(
        db_session,
        published,
        name="발행본",
        thumbnail_asset_id=None,
        image_entity_id=published_image_entity_id,
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="발행 조건",
    )
    draft = await _add_version(db_session, content, detail_description="편집중 설명", published=False)
    await _add_character_version_rows(
        db_session,
        draft,
        name="편집중",
        thumbnail_asset_id=None,
        image_entity_id=uuid.uuid4(),
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="편집 조건",
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 204

    published_version = await db_session.get(ContentVersion, published.id)
    assert published_version is not None
    assert published_version.version_number == 1
    assert published_version.published_at is not None
    assert published_version.detail_description == "발행본 설명"

    refreshed_content = await db_session.get(Content, content.id)
    assert refreshed_content is not None
    assert refreshed_content.current_published_version_id == published.id

    published_images = (
        await db_session.scalars(
            sa.select(SituationalImage).where(SituationalImage.content_version_id == published.id)
        )
    ).all()
    assert [image.entity_id for image in published_images] == [published_image_entity_id]


async def test_reset_content_draft_succeeds_when_draft_already_matches_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """No dirty check: the endpoint rewrites identical rows and still answers 204."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(
        db_session, creator_user_id=user.id, content_type=ContentType.CHARACTER
    )
    image_entity_id = uuid.uuid4()
    published = await _add_version(db_session, content, detail_description="발행본 설명", published=True)
    await _add_character_version_rows(
        db_session,
        published,
        name="발행본",
        thumbnail_asset_id=None,
        image_entity_id=image_entity_id,
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="발행 조건",
    )
    draft = await _add_version(db_session, content, detail_description="발행본 설명", published=False)
    await _add_character_version_rows(
        db_session,
        draft,
        name="발행본",
        thumbnail_asset_id=None,
        image_entity_id=image_entity_id,
        image_asset_id=None,
        blurred_asset_id=None,
        trigger_condition="발행 조건",
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 204

    draft_images = (
        await db_session.scalars(
            sa.select(SituationalImage).where(SituationalImage.content_version_id == draft.id)
        )
    ).all()
    assert [image.entity_id for image in draft_images] == [image_entity_id]


async def test_reset_content_draft_restores_story_draft_with_remapped_children(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, content_type=ContentType.STORY)

    published_setup_entity_id = uuid.uuid4()
    published_stat_entity_id = uuid.uuid4()
    published_ending_entity_id = uuid.uuid4()
    published_note_entity_id = uuid.uuid4()
    published_shortcut_entity_id = uuid.uuid4()
    draft_setup_entity_id = uuid.uuid4()
    draft_note_entity_id = uuid.uuid4()

    published = await _add_version(db_session, content, detail_description="발행본 설명", published=True)
    published_setup = await _add_story_version_rows(
        db_session,
        published,
        name="발행본",
        setup_entity_id=published_setup_entity_id,
        stat_entity_id=published_stat_entity_id,
        ending_entity_id=published_ending_entity_id,
        note_entity_id=published_note_entity_id,
        shortcut_entity_id=published_shortcut_entity_id,
    )
    draft = await _add_version(db_session, content, detail_description="편집중 설명", published=False)
    await _add_story_version_rows(
        db_session,
        draft,
        name="편집중",
        setup_entity_id=draft_setup_entity_id,
        stat_entity_id=uuid.uuid4(),
        ending_entity_id=uuid.uuid4(),
        note_entity_id=draft_note_entity_id,
        shortcut_entity_id=uuid.uuid4(),
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 204

    draft_version = await db_session.get(ContentVersion, draft.id)
    assert draft_version is not None
    assert draft_version.detail_description == "발행본 설명"

    draft_detail = await db_session.get(StoryVersionDetail, draft.id)
    assert draft_detail is not None
    assert draft_detail.name == "발행본"
    assert draft_detail.setting_text == "발행본 세계관"
    assert draft_detail.development_example == "발행본 전개 예시"

    draft_setups = (
        await db_session.scalars(
            sa.select(StartingSetup).where(StartingSetup.content_version_id == draft.id)
        )
    ).all()
    assert [setup.entity_id for setup in draft_setups] == [published_setup_entity_id]
    draft_setup = draft_setups[0]
    assert draft_setup.id != published_setup.id, "a clone gets a fresh physical id"
    assert draft_setup.name == "발행본 시작설정"
    assert draft_setup.opening_message == "발행본 오프닝"
    assert draft_setup.suggested_replies == ["발행본 추천답변"]

    draft_stats = (
        await db_session.scalars(
            sa.select(StatDef).where(StatDef.starting_setup_id == draft_setup.id)
        )
    ).all()
    assert [stat.entity_id for stat in draft_stats] == [published_stat_entity_id]
    assert draft_stats[0].per_turn_delta == -1

    draft_endings = (
        await db_session.scalars(sa.select(Ending).where(Ending.starting_setup_id == draft_setup.id))
    ).all()
    assert [ending.entity_id for ending in draft_endings] == [published_ending_entity_id]
    draft_ending = draft_endings[0]
    assert draft_ending.epilogue == "발행본 에필로그"

    top_rules = (
        await db_session.scalars(sa.select(EndingRule).where(EndingRule.ending_id == draft_ending.id))
    ).all()
    assert len(top_rules) == 1
    assert top_rules[0].stat_def_entity_id == published_stat_entity_id
    assert top_rules[0].operator == EndingRuleOperator.GTE
    assert top_rules[0].next_op == LogicalOp.AND

    draft_groups = (
        await db_session.scalars(
            sa.select(EndingRuleGroup).where(EndingRuleGroup.ending_id == draft_ending.id)
        )
    ).all()
    assert len(draft_groups) == 1
    nested_rules = (
        await db_session.scalars(
            sa.select(EndingRule).where(EndingRule.rule_group_id == draft_groups[0].id)
        )
    ).all()
    assert len(nested_rules) == 1
    assert nested_rules[0].stat_def_entity_id == published_stat_entity_id
    assert nested_rules[0].operator == EndingRuleOperator.LT

    draft_notes = (
        await db_session.scalars(
            sa.select(KeywordNote).where(KeywordNote.content_version_id == draft.id)
        )
    ).all()
    assert [note.entity_id for note in draft_notes] == [published_note_entity_id]
    assert draft_notes[0].starting_setup_id == draft_setup.id, (
        "keyword_notes.starting_setup_id is a physical FK — it must be remapped onto the "
        "draft's own cloned setup, not left pointing at the published one"
    )

    draft_shortcuts = (
        await db_session.scalars(sa.select(Shortcut).where(Shortcut.content_version_id == draft.id))
    ).all()
    assert [shortcut.entity_id for shortcut in draft_shortcuts] == [published_shortcut_entity_id]
    assert draft_shortcuts[0].prompt == "발행본 프롬프트"

    assert (
        await db_session.scalar(
            sa.select(StartingSetup).where(StartingSetup.entity_id == draft_setup_entity_id)
        )
    ) is None
    assert (
        await db_session.scalar(
            sa.select(KeywordNote).where(KeywordNote.entity_id == draft_note_entity_id)
        )
    ) is None


async def test_reset_content_draft_leaves_published_story_version_intact(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_content(db_session, creator_user_id=user.id, content_type=ContentType.STORY)

    published_setup_entity_id = uuid.uuid4()
    published_note_entity_id = uuid.uuid4()
    published = await _add_version(db_session, content, detail_description="발행본 설명", published=True)
    published_setup = await _add_story_version_rows(
        db_session,
        published,
        name="발행본",
        setup_entity_id=published_setup_entity_id,
        stat_entity_id=uuid.uuid4(),
        ending_entity_id=uuid.uuid4(),
        note_entity_id=published_note_entity_id,
        shortcut_entity_id=uuid.uuid4(),
    )
    draft = await _add_version(db_session, content, detail_description="편집중 설명", published=False)
    await _add_story_version_rows(
        db_session,
        draft,
        name="편집중",
        setup_entity_id=uuid.uuid4(),
        stat_entity_id=uuid.uuid4(),
        ending_entity_id=uuid.uuid4(),
        note_entity_id=uuid.uuid4(),
        shortcut_entity_id=uuid.uuid4(),
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")
    assert resp.status_code == 204

    published_detail = await db_session.get(StoryVersionDetail, published.id)
    assert published_detail is not None
    assert published_detail.name == "발행본"

    published_setups = (
        await db_session.scalars(
            sa.select(StartingSetup).where(StartingSetup.content_version_id == published.id)
        )
    ).all()
    assert [setup.id for setup in published_setups] == [published_setup.id]

    published_notes = (
        await db_session.scalars(
            sa.select(KeywordNote).where(KeywordNote.content_version_id == published.id)
        )
    ).all()
    assert [note.entity_id for note in published_notes] == [published_note_entity_id]
    assert published_notes[0].starting_setup_id == published_setup.id
