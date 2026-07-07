import uuid
from datetime import date, datetime, timezone

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
    ModerationStatus,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
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


async def test_story_version_detail_rejects_unknown_version(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    thumbnail = Asset(owner_user_id=user.id, storage_key=f"uploads/{uuid.uuid4()}.png", kind=AssetKind.ORIGINAL)
    db_session.add(thumbnail)
    await db_session.flush()

    detail = StoryVersionDetail(
        content_version_id=uuid.uuid4(),
        name="달빛 아래",
        one_liner="한 줄 소개",
        thumbnail_asset_id=thumbnail.id,
        prompt_template=StoryPromptTemplate.BASIC,
    )
    db_session.add(detail)

    with pytest.raises(IntegrityError):
        await db_session.flush()


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


async def test_stat_def_rejects_unknown_starting_setup(db_session: AsyncSession) -> None:
    stat = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=uuid.uuid4(),
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        description="호감도 스탯",
        order=1,
    )
    db_session.add(stat)

    with pytest.raises(IntegrityError):
        await db_session.flush()


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
