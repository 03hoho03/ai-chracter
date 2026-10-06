"""프롬프트 세트에 모델 축을 더하고 Claude 세트 4개를 심는 마이그레이션 `e6aa289fea62`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_novelize_prompt_migration.py`와 같은 방식). 세션 스코프 스키마
(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, 순수 함수와
`_delete_non_gemini_sets`는 직접 부른다(뒤의 것은 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로).
왕복(upgrade/downgrade)은 세션 스키마의 teardown 이 `downgrade base` 로 탄다."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import ChatModelId

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("e6aa289fea62")
# 이 리비전이 복사한 원본 — 테스트 DB에서는 두 레인 모두 소설화 채널 리비전의 Gemini 세트다.
_SOURCE_SET_IDS: dict[str, uuid.UUID] = _load("3bb2cc159b6d").NEW_SET_IDS
_PAIRS: list[tuple[PromptLane, ChatModelId]] = [
    ("story", "sonnet"),
    ("story", "opus"),
    ("character", "sonnet"),
    ("character", "opus"),
]
_PAIR_IDS = [f"{lane}-{model}" for lane, model in _PAIRS]

Key = tuple[str, str, str, str]

# ---- 순수 함수 ---------------------------------------------------------------------------

_SOURCE_ROWS = [
    ("system", "both", "rule_rating", "", "등급", False, 2),
    ("generation", "both", "history", "", "{history}", True, 0),
    ("stat_judgment", "story", "turn_context", "", "판정", False, 0),
    ("memory_summary", "both", "instruction", "", "요약", False, 0),
    ("novelize_chapter", "both", "instruction", "", "장", False, 0),
]


def test_copied_rows_keep_only_system_and_generation_as_is() -> None:
    assert _M._copied_rows(_SOURCE_ROWS) == _SOURCE_ROWS[:2]


def test_assert_layout_accepts_a_fresh_pair_with_both_channels() -> None:
    _M._assert_layout(_SOURCE_ROWS, 0, lane="story", model="sonnet")


def test_assert_layout_raises_when_the_pair_already_has_a_set() -> None:
    with pytest.raises(RuntimeError, match="이미 세트가 1개"):
        _M._assert_layout(_SOURCE_ROWS, 1, lane="story", model="opus")


@pytest.mark.parametrize("channel", _M.CHANNELS)
def test_assert_layout_raises_when_the_source_lacks_a_copied_channel(channel: str) -> None:
    rows = [row for row in _SOURCE_ROWS if row[0] != channel]
    with pytest.raises(RuntimeError, match=f"누락 \\['{channel}'\\]"):
        _M._assert_layout(rows, 0, lane="character", model="sonnet")


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, tuple[str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_PAIR_IDS)
async def test_claude_set_is_the_sources_system_and_generation_rows_byte_for_byte(
    db_session: AsyncSession, lane: PromptLane, model: ChatModelId
) -> None:
    set_id = _M.NEW_SET_IDS[(lane, model)]
    new_sections = await _sections_of(db_session, set_id)
    new = _keyed(new_sections)
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    source = _keyed(await _sections_of(db_session, _SOURCE_SET_IDS[lane]))  # 위 객체들을 만료시키므로 값을 먼저 뽑았다

    assert {key[0] for key in new} == {"system", "generation"}
    assert new == {key: value for key, value in source.items() if key[0] in ("system", "generation")}
    assert all(section_id == _M._section_id(lane, model, *key) for section_id, key in ids.items())

    this_set = await db_session.get(PromptSet, set_id)
    source_set = await db_session.get(PromptSet, _SOURCE_SET_IDS[lane])
    assert this_set is not None and source_set is not None
    assert (this_set.lane, this_set.model, this_set.status) == (lane, model, "published")
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(this_set, a) for a in labels] == [getattr(source_set, a) for a in labels]
    assert this_set.note == _M._NOTES[model]


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_PAIR_IDS)
async def test_claude_set_is_one_second_older_than_its_source(
    db_session: AsyncSession, lane: PromptLane, model: ChatModelId
) -> None:
    """원본보다 1초 과거 — 모델 열을 모르는 코드(옛 이미지·옛 마이그레이션의 원시 SQL)가 레인만 보고 최신 게시본을
    고를 때 Claude 세트를 집지 않게 하는 장치다. 앞선 시드 리비전들처럼 원본 + 1초로 두면 이 테스트와 아래 레인만
    보는 활성 SELECT 테스트가 함께 깨진다."""
    this_set = await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, model)])
    source_set = await db_session.get(PromptSet, _SOURCE_SET_IDS[lane])
    assert this_set is not None and source_set is not None
    assert source_set.published_at is not None
    assert this_set.published_at == source_set.published_at - timedelta(seconds=1)


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_lane_only_active_select_still_picks_the_gemini_set(db_session: AsyncSession, lane: PromptLane) -> None:
    """옛 이미지의 `load_active_prompt_set`·옛 마이그레이션의 활성 SELECT 와 같은 규칙(레인만, 최신 published_at)."""
    connection = await db_session.connection()
    chosen = (await connection.execute(_M._LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane})).one().id
    gemini, _ = await load_active_prompt_set(db_session, lane=lane)
    assert chosen == gemini.id
    assert gemini.model == "gemini"


@pytest.mark.parametrize(("lane", "model"), _PAIRS, ids=_PAIR_IDS)
async def test_claude_set_is_active_for_its_lane_and_model(
    db_session: AsyncSession, lane: PromptLane, model: ChatModelId
) -> None:
    """이 리비전의 세트이거나, 뒤에 어드민·리비전이 그 체인에 게시한 더 나중 세트가 활성이다."""
    latest, _ = await load_active_prompt_set(db_session, lane=lane, model=model)
    this_set = await db_session.get(PromptSet, _M.NEW_SET_IDS[(lane, model)])
    assert this_set is not None and latest.published_at is not None and this_set.published_at is not None
    assert latest.model == model
    assert latest.id == this_set.id or latest.published_at > this_set.published_at


async def test_versions_follow_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    """전 레인·전 모델 published 최대 + 1 을 (story, character) × (sonnet, opus) 순서로. 테스트 DB의 이전 최대는 소설화
    채널 리비전의 "13"이다."""
    versions = {pair: await db_session.get(PromptSet, set_id) for pair, set_id in _M.NEW_SET_IDS.items()}
    assert {pair: s.version if s else None for pair, s in versions.items()} == {
        ("story", "sonnet"): "14",
        ("story", "opus"): "15",
        ("character", "sonnet"): "16",
        ("character", "opus"): "17",
    }


async def test_no_drafts_are_seeded(db_session: AsyncSession) -> None:
    """초안을 심으면 레인만 보고 초안을 한 행으로 읽는 옛 코드(옛 마이그레이션의 초안 보정·옛 어드민)가 깨진다."""
    drafts = (await db_session.scalars(sa.select(PromptSet.id).where(PromptSet.status == "draft"))).all()
    assert drafts == []


# ---- 되돌리기 ------------------------------------------------------------------------------


def _set(*, lane: str, model: str, status: str, version: str | None) -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version=version,
        status=status,
        lane=lane,
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
        published_at=datetime.now(UTC) if status == "published" else None,
    )


async def test_delete_non_gemini_sets_also_removes_admin_made_claude_rows(db_session: AsyncSession) -> None:
    """리터럴 id 만 지우면 어드민이 만든 Claude 초안·게시본이 남은 채 열이 사라진다 — 그 행이 레인의 초안 유니크를
    깨거나 레인의 최신 게시본이 된다. Gemini 세트와 섹션은 하나도 건드리지 않는다."""
    admin_made = [
        _set(lane="story", model="sonnet", status="draft", version=None),
        _set(lane="character", model="opus", status="published", version="9001"),
    ]
    db_session.add_all(admin_made)
    await db_session.flush()
    db_session.add_all(
        PromptSection(
            prompt_set_id=s.id, channel="system", scope="both", slot="rule_rating", body="등급", conditional=False, order=0
        )
        for s in admin_made
    )
    await db_session.flush()
    gemini_sets_before = (
        await db_session.scalars(sa.select(PromptSet.id).where(PromptSet.model == "gemini"))
    ).all()
    gemini_sections_before = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(PromptSection)
        .join(PromptSet, PromptSet.id == PromptSection.prompt_set_id)
        .where(PromptSet.model == "gemini")
    )

    connection = await db_session.connection()
    await connection.run_sync(_M._delete_non_gemini_sets)

    db_session.expire_all()
    remaining_models = (await db_session.scalars(sa.select(PromptSet.model).distinct())).all()
    assert remaining_models == ["gemini"]
    assert sorted((await db_session.scalars(sa.select(PromptSet.id))).all()) == sorted(gemini_sets_before)
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(PromptSection)) == gemini_sections_before
