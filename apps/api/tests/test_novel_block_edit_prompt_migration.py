"""소설 레인 Gemini 체인에 여러 문단 수정 문안 채널 둘(`novelize_revise_blocks`·`novelize_revise_recheck`)을 심는 데이터 마이그레이션
`174f78b92e5c` 의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마가 이미 `upgrade head` 를 했으므로
시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows` 는 테스트마다 롤백되는
`db_session` 의 커넥션에 `run_sync` 로 직접 부른다. 기대 행은 이 파일이 직접 적는다. 문안 원문은 적지 않고 지문(md5)과 자리표시자로
고정한다."""

import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import ALLOWED_PLACEHOLDERS, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import PromptSetModelId
from api.novelize.prompts import build_novelize_revise_prompt

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("174f78b92e5c")
# 이 리비전 직전 소설 레인 세 체인의 활성 세트 — 구성안 문안 리비전이 심은 세트다.
_PREVIOUS_SET_IDS: dict[str, uuid.UUID] = dict(_load("b389c2317149").NEW_SET_IDS)
_CLAUDE_MODELS: tuple[PromptSetModelId, ...] = ("sonnet", "opus")

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
_NEW_CHANNELS = ("novelize_revise_blocks", "novelize_revise_recheck")


def _md5(body: str) -> str:
    return hashlib.md5(body.encode()).hexdigest()


def _fields(body: str) -> list[str]:
    return sorted({name for _, name, _, _ in Formatter().parse(body) if name})


# 시드 문안의 지문 — 글자 하나가 바뀌어도 여기서 깨진다.
_BODY_MD5: dict[tuple[str, str], str] = {
    ("novelize_revise_blocks", "instruction"): "20dedb9fe83ed8c5034b5aab56e3f21c",
    ("novelize_revise_blocks", "work_setting"): "2a1f3eca23f67ebe8553706d621b933d",
    ("novelize_revise_blocks", "setting_notes"): "91c4d2824c8c7faea706cbc27f0d82b9",
    ("novelize_revise_blocks", "paragraphs"): "01bdbe08799043dd0aaa7f431d445379",
    ("novelize_revise_blocks", "target_blocks"): "d4d202c7b3e502576808370c8a0a7a27",
    ("novelize_revise_blocks", "user_request"): "5df0ccaca40f2b2f24223a9f9a377bca",
    ("novelize_revise_recheck", "instruction"): "4142031c3daa179e2ad92507f1087f43",
    ("novelize_revise_recheck", "context"): "1fa35a078c1322cb25cb50f44ff08439",
    ("novelize_revise_recheck", "edited_paragraphs"): "80553ea04473dce6fe57aca7942773d3",
    ("novelize_revise_recheck", "pending_patches"): "9a39a7a4560a7d08bc08f645db5fb53d",
}

_BLOCKS_LAYOUT: dict[str, tuple[bool, int]] = {
    "instruction": (False, 0),
    "work_setting": (False, 1),
    "setting_notes": (True, 2),
    "paragraphs": (False, 3),
    "target_blocks": (False, 4),
    "user_request": (False, 5),
}
_RECHECK_LAYOUT: dict[str, tuple[bool, int]] = {
    "instruction": (False, 0),
    "context": (True, 1),
    "edited_paragraphs": (False, 2),
    "pending_patches": (False, 3),
}


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    rows = (await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all()
    return [
        PromptSection(
            channel=s.channel,
            scope=s.scope,
            slot=s.slot,
            variant=s.variant,
            body=s.body,
            conditional=s.conditional,
            order=s.order,
        )
        for s in rows
    ]


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


async def _active_id(db_session: AsyncSession, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane="novel", model=model))[0].id


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


async def _copy_set(
    db_session: AsyncSession, source_id: uuid.UUID, *, status: str, published_at: datetime | None, edit: str = ""
) -> uuid.UUID:
    """`source_id` 세트를 복제한다. `edit` 가 있으면 옛 문단 수정 지시문 끝에 붙인다(어드민이 고친 문안 흉내)."""
    source = await _get_set(db_session, source_id)
    copy = PromptSet(
        version="9001" if status == "published" else None,
        status=status,
        lane="novel",
        model=source.model,
        **{label: getattr(source, label) for label in _LABELS},
        published_at=published_at,
    )
    db_session.add(copy)
    await db_session.flush()
    copy_id = copy.id
    for s in await _sections_of(db_session, source_id):
        body = s.body + edit if (s.channel, s.slot) == ("novelize_revise", "instruction") else s.body
        db_session.add(
            PromptSection(
                prompt_set_id=copy_id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=body,
                conditional=s.conditional,
                order=s.order,
            )
        )
    await db_session.flush()
    return copy_id


async def _undo(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)


async def _seed(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.seed_published_sets)


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_seed_bodies_use_only_the_placeholders_the_renderer_allows() -> None:
    for channel, _scope, slot, _variant, body, _conditional, _order in _M.NEW_CHANNEL_ROWS:
        assert _fields(body) == sorted(ALLOWED_PLACEHOLDERS[(channel, slot)]), (channel, slot)
    assert {(row[0], row[2]): _md5(row[4]) for row in _M.NEW_CHANNEL_ROWS} == _BODY_MD5


def test_the_new_channels_have_the_intended_layout() -> None:
    """두 채널의 슬롯·conditional·order 를 고정한다. 깨지는 시나리오: 설정 노트·주변 본문이 conditional 이 아니어서 값이 없는
    호출에 빈 머리글이 나가거나, 필수 슬롯이 conditional 이어서 대상 문단 번호가 조용히 빠진다."""
    layout = {channel: {row[2]: (row[5], row[6]) for row in _M.NEW_CHANNEL_ROWS if row[0] == channel} for channel in _NEW_CHANNELS}
    assert layout == {"novelize_revise_blocks": _BLOCKS_LAYOUT, "novelize_revise_recheck": _RECHECK_LAYOUT}
    assert {row[1] for row in _M.NEW_CHANNEL_ROWS} == {"both"} and {row[3] for row in _M.NEW_CHANNEL_ROWS} == {""}


# ---- 시드 결과(head 상태) --------------------------------------------------------------------


async def test_the_gemini_chain_is_active_at_its_seed_which_is_the_previous_set_plus_the_new_rows(
    db_session: AsyncSession,
) -> None:
    """Gemini 체인은 새 세트가 활성이고, 그 세트는 이전 활성 세트의 행 전부(본문·conditional·order 그대로) + 새 두 채널 열 행이다.
    라벨도 그대로다. Claude 두 체인은 건드리지 않는다(여러 문단 수정은 Gemini 고정). 깨지는 시나리오: 사본이 이전 행을 하나라도
    잃어 옛 흐름 렌더가 바뀌거나, Claude 체인에 새 채널이 들어가 그 체인 게시가 "잉여"로 막힌다."""
    assert await _active_id(db_session, "gemini") == _M.NEW_SET_IDS["gemini"]
    previous = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS["gemini"]))
    seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS["gemini"]))

    assert {key: value for key, value in seeded.items() if key in previous} == previous
    added = {key: (cond, order) for key, (_body, cond, order) in seeded.items() if key not in previous}
    assert added == {
        **{("novelize_revise_blocks", "both", slot, ""): value for slot, value in _BLOCKS_LAYOUT.items()},
        **{("novelize_revise_recheck", "both", slot, ""): value for slot, value in _RECHECK_LAYOUT.items()},
    }
    previous_set = await _get_set(db_session, _PREVIOUS_SET_IDS["gemini"])
    seeded_set = await _get_set(db_session, _M.NEW_SET_IDS["gemini"])
    assert [getattr(seeded_set, label) for label in _LABELS] == [getattr(previous_set, label) for label in _LABELS]
    assert seeded_set.published_at is not None and previous_set.published_at is not None
    assert seeded_set.published_at > previous_set.published_at
    for model in _CLAUDE_MODELS:
        assert await _active_id(db_session, model) == _PREVIOUS_SET_IDS[model]


async def test_the_seeded_set_passes_publish_validation_and_the_previous_one_no_longer_does(db_session: AsyncSession) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="novel", model="gemini")
    _validate_prompt_draft_for_publish(prompt_set, sections, lane="novel", model="gemini")
    for model in _CLAUDE_MODELS:
        claude_set, claude_sections = await load_active_prompt_set(db_session, lane="novel", model=model)
        _validate_prompt_draft_for_publish(claude_set, claude_sections, lane="novel", model=model)

    previous = await _get_set(db_session, _PREVIOUS_SET_IDS["gemini"])
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(
            previous, await _sections_of(db_session, _PREVIOUS_SET_IDS["gemini"]), lane="novel", model="gemini"
        )


async def test_the_old_range_edit_prompt_renders_byte_for_byte_the_same_from_the_seed(db_session: AsyncSession) -> None:
    """옛 문단 수정(`novelize_revise`)의 렌더가 이전 세트와 새 세트에서 바이트까지 같다 — 옛 채널은 한 글자도 바뀌지 않는다.
    깨지는 시나리오: 마이그레이션 직후 옛 연속 범위 수정의 프롬프트가 바뀌어 같은 요청이 다른 글을 낸다."""
    previous_sections = await _sections_of(db_session, _PREVIOUS_SET_IDS["gemini"])
    seeded_sections = await _sections_of(db_session, _M.NEW_SET_IDS["gemini"])
    _chat_set, chat_sections = await load_active_prompt_set(db_session, lane="story", model="gemini")

    def render(sections: list[PromptSection]) -> str:
        built = build_novelize_revise_prompt(
            chat_sections=chat_sections,
            sections=sections,
            is_story_chat=True,
            work_setting="작품 설정",
            setting_notes="노트",
            paragraphs=["가.", "나.", "다."],
            first_index=1,
            last_index=1,
            user_request="더 쓸쓸하게",
        )
        return f"{built.system_instruction}\n---\n{built.prompt}"

    assert render(seeded_sections) == render(previous_sections)


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_the_gemini_chain_back_and_forth(db_session: AsyncSession) -> None:
    await _undo(db_session)

    assert await _active_id(db_session, "gemini") == _PREVIOUS_SET_IDS["gemini"]
    assert await db_session.get(PromptSet, _M.NEW_SET_IDS["gemini"]) is None
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.channel.in_(_NEW_CHANNELS))
    )
    assert remaining == 0

    await _seed(db_session)

    assert await _active_id(db_session, "gemini") == _M.NEW_SET_IDS["gemini"]


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    with pytest.raises(RuntimeError, match="이미 있다"):
        await _seed(db_session)


async def test_upgrade_stops_when_the_active_set_already_has_a_new_row(db_session: AsyncSession) -> None:
    await _undo(db_session)
    latest = (await _get_set(db_session, _PREVIOUS_SET_IDS["gemini"])).published_at
    assert latest is not None
    edited = await _copy_set(
        db_session, _PREVIOUS_SET_IDS["gemini"], status="published", published_at=latest + timedelta(seconds=5)
    )
    db_session.add(
        PromptSection(
            prompt_set_id=edited,
            channel="novelize_revise_recheck",
            scope="both",
            slot="instruction",
            variant="",
            body="x",
            conditional=False,
            order=99,
        )
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="novel/gemini"):
        await _seed(db_session)

    assert await db_session.get(PromptSet, _M.NEW_SET_IDS["gemini"]) is None


async def test_upgrade_copies_an_admin_edited_set_published_later_than_now(db_session: AsyncSession) -> None:
    """운영 꼴 — 어드민이 고쳐 게시한 Gemini 세트(지금보다 뒤 시각)를 바이트째 옮겨 새 세트가 활성이 된다. 깨지는 시나리오: 시드
    원문으로 덮어 운영자가 고친 옛 문단 수정 문안이 사라지거나, 새 세트 시각이 활성보다 앞이라 옛 세트가 계속 뽑힌다."""
    await _undo(db_session)
    previous_at = (await _get_set(db_session, _PREVIOUS_SET_IDS["gemini"])).published_at
    assert previous_at is not None
    edited = await _copy_set(
        db_session,
        _PREVIOUS_SET_IDS["gemini"],
        status="published",
        published_at=max(previous_at, datetime.now(previous_at.tzinfo)) + timedelta(hours=1),
        edit="\n(운영 수정)",
    )

    await _seed(db_session)

    assert await _active_id(db_session, "gemini") == _M.NEW_SET_IDS["gemini"]
    source = _keyed(await _sections_of(db_session, edited))
    seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS["gemini"]))
    assert {key: value for key, value in seeded.items() if key in source} == source
    assert seeded[("novelize_revise", "both", "instruction", "")][0].endswith("(운영 수정)")


async def test_downgrade_stops_when_the_admin_published_after_the_seed(db_session: AsyncSession) -> None:
    seeded = await _get_set(db_session, _M.NEW_SET_IDS["gemini"])
    assert seeded.published_at is not None
    await _copy_set(
        db_session, _M.NEW_SET_IDS["gemini"], status="published", published_at=seeded.published_at + timedelta(seconds=1)
    )

    with pytest.raises(RuntimeError, match="novel/gemini"):
        await _undo(db_session)

    assert await db_session.get(PromptSet, _M.NEW_SET_IDS["gemini"]) is not None


async def test_patch_drafts_adds_the_rows_in_place_the_draft_publishes_and_downgrade_removes_them(
    db_session: AsyncSession,
) -> None:
    """새 행이 없는 Gemini 초안(배포 전 이전 활성본에서 만든 초안)에 같은 새 행을 넣어 게시 검증을 통과하게 하고, 되돌리면 그
    행만 지운다. 이미 다 있는 초안·Claude 체인 초안은 건드리지 않는다."""
    draft_id = await _copy_set(db_session, _PREVIOUS_SET_IDS["gemini"], status="draft", published_at=None)
    claude_draft_id = await _copy_set(db_session, _PREVIOUS_SET_IDS["sonnet"], status="draft", published_at=None)
    before = _keyed(await _sections_of(db_session, draft_id))
    claude_before = _keyed(await _sections_of(db_session, claude_draft_id))
    connection = await db_session.connection()

    patched_what = await connection.run_sync(_M._patch_drafts)
    patched = _keyed(await _sections_of(db_session, draft_id))
    assert sorted(patched_what) == [("gemini", "novelize_revise_blocks"), ("gemini", "novelize_revise_recheck")]
    assert {key: value for key, value in patched.items() if key in before} == before
    seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS["gemini"]))
    assert {key: value for key, value in patched.items() if key not in before} == {
        key: value for key, value in seeded.items() if key not in before
    }
    assert _keyed(await _sections_of(db_session, claude_draft_id)) == claude_before
    draft = await _get_set(db_session, draft_id)
    _validate_prompt_draft_for_publish(draft, await _sections_of(db_session, draft_id), lane="novel", model="gemini")

    assert await connection.run_sync(_M._patch_drafts) == []

    await connection.run_sync(_M._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before
