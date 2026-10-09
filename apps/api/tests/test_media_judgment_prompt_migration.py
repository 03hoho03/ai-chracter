"""story 레인에 미디어 북 칸 판정 channel(`image_judgment` 3행)을 넣는 데이터 마이그레이션 `2519dde454e0`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_memory_prompt_slot_migration.py`와 같은 방식). 세션 스코프
스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 published 분기는 "마이그레이션 뒤 DB 상태"를
단언하고, 순수 함수·`_patch_draft`·`_delete_draft_rows`는 직접 부른다(뒤 둘은 테스트마다 롤백되는
`db_session`의 커넥션에 `run_sync`로).

character 레인에도 같은 channel(캐릭터 상황별 이미지 판정)이 있다 — 이 리비전의 어떤 쿼리도 그 행을
건드리지 않아야 한다."""

import importlib.util
import uuid
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, load_active_prompt_set, render_prompt_channel
from api.db.models.prompt import PromptSection, PromptSet

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("2519dde454e0")
# 이 리비전이 복사한 원본(이전 story 활성 세트)과, 손대지 않아야 하는 character 활성 세트 — 테스트 DB에서는
# 둘 다 채팅방 기억 행을 넣은 리비전의 세트다.
_PREVIOUS_SET_IDS: dict[str, uuid.UUID] = _load("c328445d4c2d").NEW_SET_IDS
# 이 리비전 뒤에 story 레인 generation 에 상황 노트 행을 더하는 리비전 — 초안 게시 검사가 head 코드 표를 쓰므로
# 함께 거친다.
_NEXT_STORY_MIGRATION = _load("2417f5829bb1")
# 그 뒤 두 레인에 사용자 이름 한 줄 행을 더하는 리비전 — 같은 이유로 초안은 이것도 거친다.
_USER_NAME_MIGRATION = _load("8e895c898730")
# 그 뒤 두 레인에 소설화 채널 행을 더하는 리비전 — 같은 이유로 초안은 이것도 거친다.
_NOVELIZE_MIGRATION = _load("3bb2cc159b6d")
# story 레인 Gemini 체인에 스탯 규칙 판정 채널을 더하는 리비전 — 초안 게시 검사가 head 코드 표를 쓰므로 story 초안은
# 이것도 거친다.
_STAT_RULE_MIGRATION = _load("d9768bc0cfee")

_NEW_KEYS = {
    ("image_judgment", "story", "image_list_intro", ""),
    ("image_judgment", "story", "turn_context", ""),
    ("image_judgment", "story", "judgment_instruction", ""),
}


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[tuple[str, str, str, str], tuple[str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


# ---- 문안 성질 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "placeholders"),
    [
        pytest.param(_M.IMAGE_LIST_INTRO_BODY, ["image_lines"], id="intro"),
        pytest.param(_M.TURN_CONTEXT_BODY, ["turn_lines"], id="turns"),
        pytest.param(_M.JUDGMENT_INSTRUCTION_BODY, [], id="instruction"),
    ],
)
def test_media_judgment_bodies_use_exactly_the_allowed_placeholders(body: str, placeholders: list[str]) -> None:
    """렌더 `values`에 없는 이름이 body 에 있으면 그 턴의 판정 렌더가 실패한다."""
    assert [name for _, name, _, _ in Formatter().parse(body) if name] == placeholders


# ---- 가드 ----------------------------------------------------------------------------------------


def test_assert_layout_accepts_story_rows_without_the_channel() -> None:
    _M._assert_layout(["system", "generation", "stat_judgment", "ending_judgment", "memory_summary"])


def test_assert_layout_raises_when_the_channel_is_already_there() -> None:
    with pytest.raises(RuntimeError, match="image_judgment channel 행이 이미 1개"):
        _M._assert_layout(["generation", "image_judgment"])


# ---- 마이그레이션 뒤 DB 상태 — published 분기 ----------------------------------------------------


async def test_active_story_set_is_this_revisions_set_with_media_judgment_rows(db_session: AsyncSession) -> None:
    """회귀 방지 — `published_at`이 원본보다 과거가 되면 새 세트가 활성이 되지 못한다. 그래서 활성 세트를 id·게시
    시각으로 직접 단언한다 — 이 리비전의 세트이거나, 뒤 리비전이 이 세트를 복사해 만든 더 나중 세트다(상황 노트
    섹션 리비전이 그렇다). 이 리비전의 세트의 다른 행은 원본과 바이트까지 같다."""
    latest, _ = await load_active_prompt_set(db_session, lane="story")
    active = await db_session.get(PromptSet, _M.NEW_SET_ID)
    assert active is not None
    assert latest.published_at is not None and active.published_at is not None
    assert latest.id == active.id or latest.published_at > active.published_at
    assert active.note == _M._NOTE
    assert active.version == "6"

    source_set = await db_session.get(PromptSet, _PREVIOUS_SET_IDS["story"])
    assert source_set is not None
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(active, a) for a in labels] == [getattr(source_set, a) for a in labels]

    new = _keyed(await _sections_of(db_session, _M.NEW_SET_ID))
    old = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS["story"]))
    assert {key: new.pop(key) for key in _NEW_KEYS} == {
        ("image_judgment", "story", "image_list_intro", ""): (_M.IMAGE_LIST_INTRO_BODY, False, 1),
        ("image_judgment", "story", "turn_context", ""): (_M.TURN_CONTEXT_BODY, False, 2),
        ("image_judgment", "story", "judgment_instruction", ""): (_M.JUDGMENT_INSTRUCTION_BODY, False, 3),
    }
    assert new == old


async def test_character_lane_keeps_its_active_set(db_session: AsyncSession) -> None:
    """이 리비전은 character 레인에 새 세트를 만들지 않는다 — 활성은 이전 세트이거나, 뒤 리비전(사용자 이름 한 줄·
    소설화 채널)이 두 레인에 만든 세트다."""
    active, _ = await load_active_prompt_set(db_session, lane="character")
    assert active.id in (
        _PREVIOUS_SET_IDS["character"],
        _USER_NAME_MIGRATION.NEW_SET_IDS["character"],
        _NOVELIZE_MIGRATION.NEW_SET_IDS["character"],
    )


async def test_story_media_judgment_renders_from_the_new_set(db_session: AsyncSession) -> None:
    _, sections = await load_active_prompt_set(db_session, lane="story")

    rendered = render_prompt_channel(
        sections, channel="image_judgment", scope="story", values={"image_lines": "<칸>", "turn_lines": "<대화>"}
    )

    assert rendered == "\n\n".join(
        [
            _M.IMAGE_LIST_INTRO_BODY.format(image_lines="<칸>"),
            _M.TURN_CONTEXT_BODY.format(turn_lines="<대화>"),
            _M.JUDGMENT_INSTRUCTION_BODY,
        ]
    )


def test_build_published_rows_copies_source_and_adds_three_rows() -> None:
    source = [
        ("generation", "story", "history", "", "body:history", True, 7),
        ("system", "both", "rule_rating", "", "body:rating", False, 3),
    ]
    set_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    built = _M._build_published_rows(source, set_id)

    assert all(row["prompt_set_id"] == set_id for row in built)
    assert len({row["id"] for row in built}) == len(built)
    assert [
        (r["channel"], r["scope"], r["slot"], r["variant"], r["body"], r["conditional"], r["order"]) for r in built
    ] == [*source, *_M.NEW_ROWS]


# ---- `_patch_draft` ------------------------------------------------------------------------


async def _clone_as_draft(db_session: AsyncSession, set_id: uuid.UUID, lane: PromptLane) -> uuid.UUID:
    source = await db_session.get(PromptSet, set_id)
    assert source is not None
    draft = PromptSet(
        version=None,
        status="draft",
        lane=lane,
        user_label=source.user_label,
        story_assistant_label=source.story_assistant_label,
        story_example_label=source.story_example_label,
        character_assistant_label=source.character_assistant_label,
    )
    db_session.add(draft)
    await db_session.flush()
    draft_id = draft.id
    for s in await _sections_of(db_session, set_id):
        db_session.add(
            PromptSection(
                prompt_set_id=draft_id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=s.body,
                conditional=s.conditional,
                order=s.order,
            )
        )
    await db_session.flush()
    return draft_id


async def test_patch_draft_adds_rows_in_place_and_draft_then_publishes(db_session: AsyncSession) -> None:
    """운영 story 레인에는 초안이 있다 — 이 분기가 실제로 탄다. 이 리비전 이전 배치의 초안(이전 활성 세트
    복제)에 3행이 더해지고 다른 행은 그대로이며, 게시 게이트 전체(head 코드 표)를 통과한다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS["story"], "story")
    before = _keyed(await _sections_of(db_session, draft_id))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is True

    sections = await _sections_of(db_session, draft_id)
    after = _keyed(sections)
    assert {key: after.pop(key) for key in _NEW_KEYS} == {
        (c, s, slot, v): (body, cond, order) for c, s, slot, v, body, cond, order in _M.NEW_ROWS
    }
    assert after == before

    # 코드 표는 지금 head 기준이라, 체인이 실제로 하듯 뒤 리비전(상황 노트 행)의 초안 패치도 거친 뒤 검사한다.
    assert await connection.run_sync(_NEXT_STORY_MIGRATION._patch_draft) is True
    assert await connection.run_sync(_USER_NAME_MIGRATION._patch_draft, "story") is True
    assert await connection.run_sync(_NOVELIZE_MIGRATION._patch_draft, "story") is True
    assert await connection.run_sync(_STAT_RULE_MIGRATION._patch_draft) is True
    sections = await _sections_of(db_session, draft_id)
    draft = await db_session.get(PromptSet, draft_id)
    assert draft is not None
    _validate_prompt_draft_for_publish(draft, sections, lane="story")


async def test_patch_draft_leaves_character_draft_alone(db_session: AsyncSession) -> None:
    """character 초안만 있으면 story 패치는 할 일이 없다 — 레인 조건이 빠지면 character 초안에 행이 들어간다."""
    character_draft = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS["character"], "character")
    before = _keyed(await _sections_of(db_session, character_draft))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is False

    assert _keyed(await _sections_of(db_session, character_draft)) == before


async def test_patch_draft_raises_when_story_draft_already_has_the_channel(db_session: AsyncSession) -> None:
    await _clone_as_draft(db_session, _M.NEW_SET_ID, "story")

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="image_judgment channel 행이 이미 3개"):
        await connection.run_sync(_M._patch_draft)


# ---- 되돌리기 ------------------------------------------------------------------------------


async def test_delete_draft_rows_removes_only_story_draft_rows(db_session: AsyncSession) -> None:
    """되돌리기는 story 초안의 칸 판정 행만 지운다 — character 초안의 상황별 이미지 판정 행과 published
    세트의 행은 남는다."""
    story_draft = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS["story"], "story")
    character_draft = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS["character"], "character")
    connection = await db_session.connection()
    await connection.run_sync(_M._patch_draft)
    story_before = _keyed(await _sections_of(db_session, story_draft))
    character_before = _keyed(await _sections_of(db_session, character_draft))
    published_before = _keyed(await _sections_of(db_session, _M.NEW_SET_ID))
    assert {key for key in character_before if key[0] == "image_judgment"}  # 지워질 수 있는 행이 실제로 있다

    await connection.run_sync(_M._delete_draft_rows)

    assert _keyed(await _sections_of(db_session, story_draft)) == {
        key: value for key, value in story_before.items() if key not in _NEW_KEYS
    }
    assert _keyed(await _sections_of(db_session, character_draft)) == character_before
    assert _keyed(await _sections_of(db_session, _M.NEW_SET_ID)) == published_before
