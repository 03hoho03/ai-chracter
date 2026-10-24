"""장면 헤더 판정 지시문(`scene_judgment`/`instruction`)을 새 판으로 바꾸는 데이터 마이그레이션 `0f82ea9f9fa5`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 판정·요약 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가
이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·
`delete_seeded_rows`·`_delete_draft_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행에서 장면 판정 지시문만 새 상수) — 마이그레이션의 행 조립 함수로 기대값을 만들면
그 함수가 틀려도 테스트가 같이 틀린다. 문안 원문은 적지 않고 지문(sha256)으로 고정한다."""

import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptNames, build_scene_judgment_prompt, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import PromptSetModelId

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("0f82ea9f9fa5")
# 이 리비전 뒤에 채팅 두 레인 여덟 체인에 인상 생성 문안 채널을 더한 세트를 게시하는 리비전 — head 활성이라 "이 리비전 직후
# 상태"를 보는 테스트는 이것부터 되돌린다(실제 downgrade 순서).
_IMPRESSION = _load("6558ab4d3dbc")
# 소설 레인 세 체인에 구성안 문안을 심은 리비전의 세트 — 다른 레인과 무관하지만 전역 버전 번호를 이 리비전 뒤에서 이어
# 쓰므로 버전 차례를 보는 시험에서 뺀다.
_NOVEL_OUTLINE_SET_IDS: list[uuid.UUID] = list(_load("b389c2317149").NEW_SET_IDS.values()) + list(
    _load("174f78b92e5c").NEW_SET_IDS.values()  # 그 뒤 여러 문단 수정 문안을 심은 소설 레인 Gemini 세트도 같은 이유로 뺀다.
)
# 장면 판정 채널을 심은 리비전 — 옛 지시문의 출처다.
_SCENE_JUDGMENT = _load("0346abdbcc92")
# 바로 앞 프롬프트 리비전 — 여덟 체인에 요약 비밀 표기 슬롯 본문만 바꾼 세트를 게시했고, 그 story 네 세트가 이 리비전 직전
# 활성 세트다(그 사이의 리비전은 프롬프트를 게시하지 않는다). 장면 판정 행은 장면 판정 채널을 심은 리비전의 것이 바이트 그대로
# 옮겨져 왔다.
_SOURCE_MARKING = _load("0c1a85bc5c2f")
_PREVIOUS_SET_IDS: dict[tuple[str, str], uuid.UUID] = _SOURCE_MARKING.NEW_SET_IDS

_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus", "haiku")

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_INSTRUCTION_KEY: Key = ("scene_judgment", "story", "instruction", "")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 새 지시문(사람이 검수한 측정에서 고른 판)과 옛 지시문의 지문 — 글자 하나가 바뀌어도 여기서 깨진다.
_NEW_INSTRUCTION_SHA256 = "390ad0d3e75f86e49d3d82e6be6eb233d4978528e0a2a1b11140f009437b1ae5"
_OLD_INSTRUCTION_MD5 = "03b352bae2560b1394d9aadf8cd349ce"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


def _expected_after(before: dict[Key, Value]) -> dict[Key, Value]:
    """이전 행 그대로, 장면 판정 지시문만 새 상수."""
    _old_body, conditional, order = before[_INSTRUCTION_KEY]
    return {**before, _INSTRUCTION_KEY: (_M.INSTRUCTION_BODY, conditional, order)}


async def _active_id(db_session: AsyncSession, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane="story", model=model))[0].id


async def _lane_only_active_id(db_session: AsyncSession) -> uuid.UUID:
    connection = await db_session.connection()
    chosen: uuid.UUID = (await connection.execute(_M._LANE_ONLY_ACTIVE_SET_SQL, {"lane": "story"})).one().id
    return chosen


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


async def _undo_later_revisions(db_session: AsyncSession) -> None:
    await (await db_session.connection()).run_sync(_IMPRESSION.delete_seeded_rows)


def _published(*, model: str, published_at: datetime) -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version="9001",
        status="published",
        lane="story",
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
        published_at=published_at,
    )


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_old_instruction_this_revision_expects_is_the_one_the_seed_revision_planted() -> None:
    """운영 본문이 이 상수와 같을 때만 바꾼다 — 상수가 앞 리비전 문안과 한 글자라도 다르면 모든 체인에서 멈춘다."""
    assert _M.OLD_INSTRUCTION_BODY == _SCENE_JUDGMENT.INSTRUCTION_BODY
    assert hashlib.md5(_M.OLD_INSTRUCTION_BODY.encode()).hexdigest() == _OLD_INSTRUCTION_MD5


def test_new_instruction_is_the_reviewed_wording_without_placeholders() -> None:
    """새 판은 측정에서 고른 문안 그대로이고 자리표시자가 없다 — 옛 이미지가 이 판을 렌더해도 넘길 값이 없어 깨지지 않는다."""
    assert _sha256(_M.INSTRUCTION_BODY) == _NEW_INSTRUCTION_SHA256
    assert "{" not in _M.INSTRUCTION_BODY and "}" not in _M.INSTRUCTION_BODY
    assert _M.INSTRUCTION_BODY != _M.OLD_INSTRUCTION_BODY


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


@pytest.mark.parametrize("model", _MODELS)
async def test_each_story_chain_is_active_at_its_seeded_set_with_the_new_instruction(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    await _undo_later_revisions(db_session)
    assert await _active_id(db_session, model) == _M.NEW_SET_IDS[("story", model)]
    _prompt_set, sections = await load_active_prompt_set(db_session, lane="story", model=model)
    (instruction,) = [s for s in sections if (s.channel, s.slot) == ("scene_judgment", "instruction")]
    assert _sha256(instruction.body) == _NEW_INSTRUCTION_SHA256


async def test_the_lane_only_select_picks_the_new_gemini_set_and_character_is_untouched(
    db_session: AsyncSession,
) -> None:
    await _undo_later_revisions(db_session)
    assert await _lane_only_active_id(db_session) == _M.NEW_SET_IDS[("story", "gemini")]
    _set, sections = await load_active_prompt_set(db_session, lane="character", model="gemini")
    assert not any(s.channel == "scene_judgment" for s in sections)


@pytest.mark.parametrize("model", _MODELS)
async def test_new_set_is_the_previous_active_set_with_only_the_instruction_changed(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """이전 활성 세트의 행이 바이트 그대로 옮겨지고(장면 판정 지시문만 다르다 — 직전 장면·이번 턴 행도 그대로), 더하거나 빠진
    행이 없다. 라벨도 이전 활성 세트 것이다."""
    new_sections = await _sections_of(db_session, _M.NEW_SET_IDS[("story", model)])
    new = _keyed(new_sections)
    # 다음 `_sections_of` 가 `expire_all` 로 이 객체들을 만료시키므로 그 전에 읽어 둔다.
    ids = {s.id: (s.channel, s.scope, s.slot, s.variant) for s in new_sections}
    before = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[("story", model)]))

    assert before[_INSTRUCTION_KEY][0] == _M.OLD_INSTRUCTION_BODY
    assert new == _expected_after(before)
    assert all(section_id == _M._section_id("story", model, *key) for section_id, key in ids.items())

    this_set = await _get_set(db_session, _M.NEW_SET_IDS[("story", model)])
    old_set = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", model)])
    assert (this_set.lane, this_set.model, this_set.status) == ("story", model, "published")
    assert [getattr(this_set, a) for a in _LABELS] == [getattr(old_set, a) for a in _LABELS]


async def test_new_sets_are_published_in_the_window_of_both_active_rules(db_session: AsyncSession) -> None:
    """새 Gemini 세트는 원본보다 나중, 나머지 세 체인의 새 세트는 (그 체인 이전 활성, 새 Gemini) 의 중간값."""
    gemini_old = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    gemini_new = await _get_set(db_session, _M.NEW_SET_IDS[("story", "gemini")])
    assert gemini_old.published_at is not None and gemini_new.published_at is not None
    assert gemini_new.published_at >= gemini_old.published_at + timedelta(seconds=1)
    for model in ("sonnet", "opus", "haiku"):
        old = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", model)])
        new = await _get_set(db_session, _M.NEW_SET_IDS[("story", model)])
        assert old.published_at is not None and new.published_at is not None
        assert old.published_at < new.published_at < gemini_new.published_at
        assert new.published_at == old.published_at + (gemini_new.published_at - old.published_at) / 2


async def test_versions_continue_the_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    """전 레인·전 모델 published 최대 + 1 을 gemini·sonnet·opus·haiku 순서로. 테스트 DB에 이 리비전 뒤에 게시한 세트는 소설
    레인 문안 리비전과 인상 생성 문안 리비전의 것뿐이라 그 둘을 뺀다."""
    order = [_M.NEW_SET_IDS[("story", model)] for model in _MODELS]
    versions = [int((await _get_set(db_session, set_id)).version or "0") for set_id in order]
    others = (
        await db_session.scalars(
            sa.select(sa.cast(PromptSet.version, sa.Integer)).where(
                PromptSet.status == "published",
                PromptSet.id.not_in(order),
                PromptSet.id.not_in(_NOVEL_OUTLINE_SET_IDS),
                PromptSet.id.not_in(list(_IMPRESSION.NEW_SET_IDS.values())),
            )
        )
    ).all()
    assert versions == list(range(max(others) + 1, max(others) + 1 + len(order)))


@pytest.mark.parametrize("model", _MODELS)
async def test_seeded_sets_pass_publish_validation(db_session: AsyncSession, model: PromptSetModelId) -> None:
    """행 집합·자리표시자가 앞 리비전과 같다. 지금 코드 표는 뒤 리비전(인상 생성 채널)까지 기준이라 이 세트는 그 채널 "누락"으로만
    막히고, 그 채널을 더한 head 활성 세트는 통과한다."""
    sections = await _sections_of(db_session, _M.NEW_SET_IDS[("story", model)])
    prompt_set = await _get_set(db_session, _M.NEW_SET_IDS[("story", model)])
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(prompt_set, sections, lane="story", model=model)
    later_set, later_sections = await load_active_prompt_set(db_session, lane="story", model=model)
    assert later_set.id == _IMPRESSION.NEW_SET_IDS[("story", model)]
    _validate_prompt_draft_for_publish(later_set, later_sections, lane="story", model=model)


@pytest.mark.parametrize("model", _MODELS)
async def test_the_rendered_judgment_prompt_carries_the_new_instruction_and_the_same_tail(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """렌더된 판정 프롬프트는 새 지시문으로 시작하고, 그 뒤(직전 장면·이번 턴)는 이전 세트로 렌더한 것과 바이트까지 같다."""
    names = PromptNames(persona_name=None, char_name=None)

    async def render(set_id: uuid.UUID) -> str:
        sections = await _sections_of(db_session, set_id)
        prompt_set = await _get_set(db_session, set_id)  # 섹션을 읽으며 세션이 만료시킨 뒤에 읽는다
        return build_scene_judgment_prompt(
            prompt_set=prompt_set,
            sections=sections,
            previous_place="교실",
            previous_time="방과 후",
            user_message="옥상으로 올라가자",
            assistant_message="둘은 계단을 올라 옥상 문을 열었다.",
            names=names,
        )

    new = await render(_M.NEW_SET_IDS[("story", model)])
    old = await render(_PREVIOUS_SET_IDS[("story", model)])
    assert new.startswith(_M.INSTRUCTION_BODY) and old.startswith(_M.OLD_INSTRUCTION_BODY)
    assert new.removeprefix(_M.INSTRUCTION_BODY) == old.removeprefix(_M.OLD_INSTRUCTION_BODY)


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_every_chain_back_and_forth(db_session: AsyncSession) -> None:
    """되돌리면 네 체인 활성이 이전 세트(처음부터 옛 지시문)로, 레인만 보는 조회가 이전 Gemini 세트로 돌아가고, 다시 올리면 같은
    리터럴 세트가 활성이 된다."""
    connection = await db_session.connection()

    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    for model in _MODELS:
        assert await _active_id(db_session, model) == _PREVIOUS_SET_IDS[("story", model)]
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None
        _set, sections = await load_active_prompt_set(db_session, lane="story", model=model)
        (instruction,) = [s for s in sections if (s.channel, s.slot) == ("scene_judgment", "instruction")]
        assert instruction.body == _SCENE_JUDGMENT.INSTRUCTION_BODY
    assert await _lane_only_active_id(db_session) == _PREVIOUS_SET_IDS[("story", "gemini")]
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.body == _M.INSTRUCTION_BODY)
    )
    assert remaining == 0

    await connection.run_sync(_M.seed_published_sets)

    for model in _MODELS:
        assert await _active_id(db_session, model) == _M.NEW_SET_IDS[("story", model)]


@pytest.mark.parametrize("model", _MODELS)
async def test_upgrade_refuses_to_overwrite_an_instruction_the_admin_edited(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """활성 지시문이 앞 리비전 문안과 한 글자라도 다르면 어드민이 고친 운영 문안이다 — 조용히 덮어쓰지 않고, 네 체인 어디에도
    세트를 넣지 않은 채 멈춘다. 고친 본문도 그대로다."""
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    edited = _SCENE_JUDGMENT.INSTRUCTION_BODY + " "
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("story", model)],
            PromptSection.channel == "scene_judgment",
            PromptSection.slot == "instruction",
        )
        .values(body=edited)
    )

    with pytest.raises(RuntimeError, match=f"story/{model}") as caught:
        await connection.run_sync(_M.seed_published_sets)
    assert "scene_judgment 채널의 instruction 본문이 앞 리비전이 심은 문안과 다르다" in str(caught.value)
    for other in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", other)]) is None
    after = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[("story", model)]))
    assert after[_INSTRUCTION_KEY][0] == edited


async def test_upgrade_stops_when_the_instruction_row_is_not_exactly_one(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    await db_session.execute(
        sa.delete(PromptSection).where(
            PromptSection.prompt_set_id == _PREVIOUS_SET_IDS[("story", "haiku")],
            PromptSection.channel == "scene_judgment",
            PromptSection.slot == "instruction",
        )
    )

    with pytest.raises(
        RuntimeError, match=r"story/haiku\] scene_judgment 채널의 instruction 행이 정확히 하나가 아니다\(0개"
    ):
        await connection.run_sync(_M.seed_published_sets)
    for model in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 있다"):
        await connection.run_sync(_M.seed_published_sets)


async def test_upgrade_stops_when_the_lane_only_select_does_not_pick_gemini(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_IMPRESSION.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)
    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[("story", "gemini")])
    assert previous.published_at is not None
    db_session.add(_published(model="sonnet", published_at=previous.published_at + timedelta(seconds=1)))
    await db_session.flush()

    with pytest.raises(RuntimeError, match=r"\[story\] 레인만 보는"):
        await connection.run_sync(_M.seed_published_sets)
    for model in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", model)]) is None


@pytest.mark.parametrize("model", _MODELS)
async def test_downgrade_stops_when_the_admin_published_after_the_seed(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """시드 뒤에 어드민이 네 체인 중 하나라도 새 버전을 게시했으면 아무것도 지우지 않고 멈춘다."""
    await _undo_later_revisions(db_session)
    seeded = await _get_set(db_session, _M.NEW_SET_IDS[("story", model)])
    assert seeded.published_at is not None
    db_session.add(_published(model=model, published_at=seeded.published_at + timedelta(seconds=1)))
    await db_session.flush()
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match=f"story/{model}"):
        await connection.run_sync(_M.delete_seeded_rows)

    for other in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[("story", other)]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


async def _clone_as_draft(
    db_session: AsyncSession, set_id: uuid.UUID, model: str, *, edit: dict[Key, str] | None = None
) -> uuid.UUID:
    """`set_id` 세트를 초안으로 복제한다. `edit` 는 그 키의 body 를 바꾼다."""
    source = await _get_set(db_session, set_id)
    copy = PromptSet(
        version=None,
        status="draft",
        lane="story",
        model=model,
        user_label=source.user_label,
        story_assistant_label=source.story_assistant_label,
        story_example_label=source.story_example_label,
        character_assistant_label=source.character_assistant_label,
        published_at=None,
    )
    db_session.add(copy)
    await db_session.flush()
    copy_id = copy.id
    for s in await _sections_of(db_session, set_id):
        key = (s.channel, s.scope, s.slot, s.variant)
        db_session.add(
            PromptSection(
                prompt_set_id=copy_id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=(edit or {}).get(key, s.body),
                conditional=s.conditional,
                order=s.order,
            )
        )
    await db_session.flush()
    return copy_id


@pytest.mark.parametrize("model", _MODELS)
async def test_patch_drafts_swaps_the_instruction_in_place_and_the_draft_publishes(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """이 리비전 이전에 저장한 초안(이전 활성 세트 복제)이 새 세트와 같은 행이 되고 그 체인의 게시 게이트를 통과한다.
    되돌리기는 지시문을 옛 문안으로 돌린다."""
    draft_id = await _clone_as_draft(db_session, _PREVIOUS_SET_IDS[("story", model)], model)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == [("story", model)]

    sections = await _sections_of(db_session, draft_id)
    assert _keyed(sections) == _expected_after(before)
    await connection.run_sync(_IMPRESSION._patch_drafts)
    sections = await _sections_of(db_session, draft_id)
    _validate_prompt_draft_for_publish(await _get_set(db_session, draft_id), sections, lane="story", model=model)

    await connection.run_sync(_IMPRESSION._delete_draft_rows)
    assert await connection.run_sync(_M._delete_draft_rows) == [("story", model)]
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_drafts_keeps_an_instruction_edited_in_the_draft(db_session: AsyncSession) -> None:
    """초안에서 고치던 지시문은 그대로 둔다(배포를 멈추지도 않는다). 되돌리기도 고친 본문을 건드리지 않는다."""
    draft_id = await _clone_as_draft(
        db_session,
        _PREVIOUS_SET_IDS[("story", "opus")],
        "opus",
        edit={_INSTRUCTION_KEY: "운영자가 고치던 장면 판정 지시문"},
    )
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    assert await connection.run_sync(_M._patch_drafts) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before

    assert await connection.run_sync(_M._delete_draft_rows) == []
    assert _keyed(await _sections_of(db_session, draft_id)) == before
