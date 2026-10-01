import uuid
from datetime import timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    AssetKind,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Ending,
    EndingRule,
    EndingRuleGroup,
    EndingRuleOperator,
    Genre,
    KeywordNote,
    LogicalOp,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    ModerationStatus,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from factories import _make_user


async def _make_story_draft(db_session: AsyncSession) -> ContentVersion:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    genre_result = await db_session.execute(sa.select(Genre).limit(1))
    genre = genre_result.scalar_one()

    content = Content(
        type=ContentType.STORY,
        creator_user_id=user.id,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    draft = ContentVersion(content_id=content.id, detail_description="초안 설명")
    db_session.add(draft)
    await db_session.flush()

    return draft


async def _make_starting_setup(db_session: AsyncSession, draft: ContentVersion, **overrides: object) -> StartingSetup:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "content_version_id": draft.id,
        "name": "시작 설정 1",
        "prologue": "이야기가 시작된다.",
        "order": 1,
    }
    defaults.update(overrides)
    setup = StartingSetup(**defaults)
    db_session.add(setup)
    await db_session.flush()
    return setup


async def test_story_version_detail_attaches_to_draft(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    draft = await _make_story_draft(db_session)

    thumbnail = Asset(owner_user_id=user.id, storage_key=f"uploads/{uuid.uuid4()}.png", kind=AssetKind.ORIGINAL)
    db_session.add(thumbnail)
    await db_session.flush()

    detail = StoryVersionDetail(
        content_version_id=draft.id,
        name="달빛 아래",
        one_liner="한 줄 소개",
        thumbnail_asset_id=thumbnail.id,
        prompt_template=StoryPromptTemplate.BASIC,
    )
    db_session.add(detail)
    await db_session.flush()

    assert detail.setting_text is None
    assert detail.prompt_template == StoryPromptTemplate.BASIC


async def test_starting_setup_keeps_entity_id_stable_and_orders_list(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    entity_id = uuid.uuid4()

    setup = await _make_starting_setup(db_session, draft, entity_id=entity_id, order=2)

    assert setup.id is not None
    assert setup.id != entity_id
    assert setup.entity_id == entity_id
    assert setup.order == 2


async def test_stat_def_is_independent_per_starting_setup(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    setup_a = await _make_starting_setup(db_session, draft, order=1)
    setup_b = await _make_starting_setup(db_session, draft, order=2)

    stat_a = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup_a.id,
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        description="호감도 스탯",
        order=1,
    )
    stat_b = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup_b.id,
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        description="호감도 스탯",
        order=1,
    )
    db_session.add_all([stat_a, stat_b])
    await db_session.flush()

    assert stat_a.starting_setup_id == setup_a.id
    assert stat_b.starting_setup_id == setup_b.id
    assert stat_a.id != stat_b.id


async def test_keyword_note_can_apply_to_whole_story_or_one_starting_setup(
    db_session: AsyncSession,
) -> None:
    draft = await _make_story_draft(db_session)
    setup = await _make_starting_setup(db_session, draft)

    story_wide = KeywordNote(
        entity_id=uuid.uuid4(),
        content_version_id=draft.id,
        info_text="이 세계관에서는 마법이 금지되어 있다.",
        trigger_keywords=["마법", "금지"],
    )
    scoped = KeywordNote(
        entity_id=uuid.uuid4(),
        content_version_id=draft.id,
        starting_setup_id=setup.id,
        info_text="이 시작 설정에서는 주인공이 이미 마법사다.",
        trigger_keywords=["마법사"],
    )
    db_session.add_all([story_wide, scoped])
    await db_session.flush()

    assert story_wide.starting_setup_id is None
    assert scoped.starting_setup_id == setup.id


async def test_shortcut_attaches_to_content_version(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)

    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=draft.id,
        name="자기소개",
        description="캐릭터가 자기소개를 하도록 유도",
        prompt="당신의 이름과 목적을 소개해주세요.",
    )
    db_session.add(shortcut)
    await db_session.flush()

    assert shortcut.content_version_id == draft.id


async def test_ending_attaches_to_starting_setup_and_orders_list(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    setup = await _make_starting_setup(db_session, draft)

    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="해피엔딩",
        turn_count_gate=10,
        judgment_prompt="호감도가 80 이상이면 해피엔딩",
        order=1,
    )
    db_session.add(ending)
    await db_session.flush()

    assert ending.epilogue is None
    assert ending.starting_setup_id == setup.id


async def test_ending_rule_top_level_is_valid(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    setup = await _make_starting_setup(db_session, draft)
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="해피엔딩",
        turn_count_gate=10,
        judgment_prompt="호감도가 80 이상이면 해피엔딩",
        order=1,
    )
    db_session.add(ending)
    await db_session.flush()

    rule = EndingRule(
        entity_id=uuid.uuid4(),
        ending_id=ending.id,
        stat_def_entity_id=uuid.uuid4(),
        operator=EndingRuleOperator.GTE,
        threshold=80,
        order=1,
    )
    db_session.add(rule)
    await db_session.flush()

    assert rule.ending_id == ending.id
    assert rule.rule_group_id is None


async def test_ending_rule_inside_group_is_valid(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    setup = await _make_starting_setup(db_session, draft)
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="해피엔딩",
        turn_count_gate=10,
        judgment_prompt="호감도가 80 이상이면 해피엔딩",
        order=1,
    )
    db_session.add(ending)
    await db_session.flush()

    group = EndingRuleGroup(
        entity_id=uuid.uuid4(),
        ending_id=ending.id,
        next_op=LogicalOp.OR,
        order=1,
    )
    db_session.add(group)
    await db_session.flush()

    rule = EndingRule(
        entity_id=uuid.uuid4(),
        rule_group_id=group.id,
        stat_def_entity_id=uuid.uuid4(),
        operator=EndingRuleOperator.LT,
        threshold=20,
        order=1,
    )
    db_session.add(rule)
    await db_session.flush()

    assert rule.rule_group_id == group.id
    assert rule.ending_id is None


# `alembic check` 는 기존 테이블의 CHECK 제약을 비교하지 않는다(alembic 1.18.5 의
# autogenerate/compare 에 CheckConstraint 비교자가 없다) — `ck_ending_rules_exactly_one_parent`
# 는 이 테스트에서만 검증된다.
async def test_ending_rule_rejects_both_ending_and_group_set(db_session: AsyncSession) -> None:
    draft = await _make_story_draft(db_session)
    setup = await _make_starting_setup(db_session, draft)
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="해피엔딩",
        turn_count_gate=10,
        judgment_prompt="호감도가 80 이상이면 해피엔딩",
        order=1,
    )
    db_session.add(ending)
    await db_session.flush()

    group = EndingRuleGroup(entity_id=uuid.uuid4(), ending_id=ending.id, order=1)
    db_session.add(group)
    await db_session.flush()

    rule = EndingRule(
        entity_id=uuid.uuid4(),
        ending_id=ending.id,
        rule_group_id=group.id,
        stat_def_entity_id=uuid.uuid4(),
        operator=EndingRuleOperator.EQ,
        threshold=50,
        order=1,
    )
    db_session.add(rule)

    with pytest.raises(IntegrityError):
        await db_session.flush()


# `alembic check` 는 기존 테이블의 CHECK 제약을 비교하지 않는다(alembic 1.18.5 의
# autogenerate/compare 에 CheckConstraint 비교자가 없다) — `ck_ending_rules_exactly_one_parent`
# 는 이 테스트에서만 검증된다.
async def test_ending_rule_rejects_neither_ending_nor_group_set(db_session: AsyncSession) -> None:
    rule = EndingRule(
        entity_id=uuid.uuid4(),
        stat_def_entity_id=uuid.uuid4(),
        operator=EndingRuleOperator.EQ,
        threshold=50,
        order=1,
    )
    db_session.add(rule)

    with pytest.raises(IntegrityError):
        await db_session.flush()


# `alembic check` 는 모델과 마이그레이션의 UNIQUE 가 일치하는지만 본다. 제약이 실제로 무엇을 막고 무엇을
# 허용하는지(같은 버전만 막고 다른 버전·같은 이름은 허용)는 아래 테스트들이 고정하고, 이 부류는 src 를
# 실행하지 않아 지워도 커버리지가 떨어지지 않는다.
@pytest.mark.parametrize(
    "axis_model",
    [pytest.param(MediaBookPerson, id="person"), pytest.param(MediaBookScene, id="scene")],
)
async def test_media_book_axis_rejects_second_row_for_same_entity_in_one_version(
    db_session: AsyncSession, axis_model: type[MediaBookPerson] | type[MediaBookScene]
) -> None:
    """Cells point at an axis row by entity_id, so one version may hold that entity_id once.
    The same entity_id in another version is how a row survives publish, and a repeated name
    is left to request validation (a name swap inside one save would trip a DB constraint)."""
    draft = await _make_story_draft(db_session)
    other_version = ContentVersion(content_id=draft.content_id, detail_description="다른 버전")
    db_session.add(other_version)
    await db_session.flush()

    entity_id = uuid.uuid4()
    db_session.add_all(
        [
            axis_model(entity_id=entity_id, content_version_id=draft.id, name="하나", order=0),
            axis_model(entity_id=entity_id, content_version_id=other_version.id, name="하나", order=0),
            axis_model(entity_id=uuid.uuid4(), content_version_id=draft.id, name="하나", order=1),
        ]
    )
    await db_session.flush()

    db_session.add(axis_model(entity_id=entity_id, content_version_id=draft.id, name="둘", order=2))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def _make_cell_image(db_session: AsyncSession, draft: ContentVersion) -> Asset:
    content = await db_session.get(Content, draft.content_id)
    assert content is not None
    image = Asset(
        owner_user_id=content.creator_user_id, storage_key=f"uploads/{uuid.uuid4()}.webp", kind=AssetKind.ORIGINAL
    )
    db_session.add(image)
    await db_session.flush()
    return image


async def test_media_book_cell_rejects_second_row_for_same_entity_in_one_version(
    db_session: AsyncSession,
) -> None:
    """The duplicate sits on a different person × scene spot, so only the entity_id
    constraint can refuse it."""
    draft = await _make_story_draft(db_session)
    other_version = ContentVersion(content_id=draft.content_id, detail_description="다른 버전")
    db_session.add(other_version)
    await db_session.flush()
    image = await _make_cell_image(db_session, draft)

    entity_id = uuid.uuid4()
    person, scene = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            MediaBookCell(
                entity_id=entity_id,
                content_version_id=draft.id,
                person_entity_id=person,
                scene_entity_id=scene,
                image_asset_id=image.id,
            ),
            MediaBookCell(
                entity_id=entity_id,
                content_version_id=other_version.id,
                person_entity_id=person,
                scene_entity_id=scene,
                image_asset_id=image.id,
            ),
        ]
    )
    await db_session.flush()

    db_session.add(
        MediaBookCell(
            entity_id=entity_id,
            content_version_id=draft.id,
            person_entity_id=person,
            scene_entity_id=uuid.uuid4(),
            image_asset_id=image.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_media_book_cell_rejects_second_image_in_same_person_scene(db_session: AsyncSession) -> None:
    """One person × scene spot holds one image per version. The same spot in another version
    and the same person in another scene are separate spots."""
    draft = await _make_story_draft(db_session)
    other_version = ContentVersion(content_id=draft.content_id, detail_description="다른 버전")
    db_session.add(other_version)
    await db_session.flush()
    image = await _make_cell_image(db_session, draft)

    person, scene = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            MediaBookCell(
                entity_id=uuid.uuid4(),
                content_version_id=draft.id,
                person_entity_id=person,
                scene_entity_id=scene,
                image_asset_id=image.id,
            ),
            MediaBookCell(
                entity_id=uuid.uuid4(),
                content_version_id=other_version.id,
                person_entity_id=person,
                scene_entity_id=scene,
                image_asset_id=image.id,
            ),
            MediaBookCell(
                entity_id=uuid.uuid4(),
                content_version_id=draft.id,
                person_entity_id=person,
                scene_entity_id=uuid.uuid4(),
                image_asset_id=image.id,
            ),
        ]
    )
    await db_session.flush()

    db_session.add(
        MediaBookCell(
            entity_id=uuid.uuid4(),
            content_version_id=draft.id,
            person_entity_id=person,
            scene_entity_id=scene,
            image_asset_id=image.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
