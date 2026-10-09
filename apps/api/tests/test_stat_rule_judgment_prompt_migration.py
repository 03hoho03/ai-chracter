"""story 레인 Gemini 체인에 스탯 규칙 판정 채널(`stat_rule_judgment` 4행)을 넣는 데이터 마이그레이션 `d9768bc0cfee`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_media_judgment_prompt_migration.py`와 같은 방식). 세션 스코프
스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 published 분기는 "마이그레이션 뒤 DB 상태"를 단언하고,
`seed_published_set`·`_patch_draft`·`delete_seeded_rows`는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로
직접 부른다(되돌리기 → 다시 올리기 왕복)."""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path
from string import Formatter
from types import ModuleType

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import (
    ALLOWED_PLACEHOLDERS,
    PromptLane,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import ChatModelId
from factories import _create_admin, _login_as_admin

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("d9768bc0cfee")
# 이 리비전이 복사한 원본 — 테스트 DB에서는 소설화 채널 리비전의 story Gemini 세트다(그 뒤 리비전들은 story Gemini 세트를
# 만들지 않았다).
_SOURCE_SET_ID: uuid.UUID = _load("3bb2cc159b6d").NEW_SET_IDS["story"]
# 손대지 않아야 하는 story Claude 체인 세트.
_CLAUDE_MODELS: tuple[ChatModelId, ...] = ("sonnet", "opus")
_CLAUDE_SET_IDS: dict[ChatModelId, uuid.UUID] = {
    model: _load("e6aa289fea62").NEW_SET_IDS[("story", model)] for model in _CLAUDE_MODELS
}

_NEW_KEYS = {(row[0], row[1], row[2], row[3]) for row in _M.NEW_ROWS}

Key = tuple[str, str, str, str]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[Key, tuple[str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


async def _active_id(db_session: AsyncSession, model: ChatModelId = "gemini") -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane="story", model=model))[0].id


# ---- 문안 성질 --------------------------------------------------------------------------------


@pytest.mark.parametrize(("channel", "_scope", "slot", "_variant", "body", "_conditional", "_order"), _M.NEW_ROWS)
def test_new_bodies_use_only_allowed_placeholders(
    channel: str, _scope: str, slot: str, _variant: str, body: str, _conditional: bool, _order: int
) -> None:
    """렌더 `values`에 없는 이름이 body 에 있으면 그 턴의 판정 렌더가 실패한다 — 어드민 게시 검증이 쓰는 표와 맞대 본다."""
    names = {name for _, name, _, _ in Formatter().parse(body) if name}
    assert names == ALLOWED_PLACEHOLDERS[(channel, slot)]


def test_instruction_names_the_real_response_key() -> None:
    """구조화 출력은 필드 이름을 그대로 키로 쓴다 — 지시문이 부르는 키가 스키마 키와 다르면 모델이 어느 쪽을 따를지
    모른다."""
    (key,) = StatRuleJudgmentResult.model_json_schema()["properties"]
    assert key in _M.JUDGMENT_INSTRUCTION_BODY


# ---- 가드 ----------------------------------------------------------------------------------------


def test_assert_layout_accepts_story_rows_without_the_channel() -> None:
    _M._assert_layout(["system", "generation", "stat_judgment", "ending_judgment"])


def test_assert_layout_raises_when_the_channel_is_already_there() -> None:
    with pytest.raises(RuntimeError, match="stat_rule_judgment channel 행이 이미 1개"):
        _M._assert_layout(["stat_judgment", "stat_rule_judgment"])


# ---- 마이그레이션 뒤 DB 상태 --------------------------------------------------------------------


async def test_active_story_gemini_set_is_the_source_plus_four_rows(db_session: AsyncSession) -> None:
    """활성 story Gemini 세트가 이 리비전의 세트이고, 원본보다 나중 게시이며, 새 4행 말고는 원본과 바이트까지 같다.
    `published_at`이 원본보다 과거가 되면 새 세트가 활성이 되지 못하므로 활성 id 를 직접 단언한다."""
    assert await _active_id(db_session) == _M.NEW_SET_ID
    active = await db_session.get(PromptSet, _M.NEW_SET_ID)
    source = await db_session.get(PromptSet, _SOURCE_SET_ID)
    assert active is not None and source is not None
    assert active.published_at is not None and source.published_at is not None
    assert active.published_at > source.published_at
    assert (active.model, active.note) == ("gemini", _M._NOTE)
    # 이전 published 최대는 소설 레인 opus 세트의 "21"이다.
    assert active.version == "22"
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(active, a) for a in labels] == [getattr(source, a) for a in labels]

    new = _keyed(await _sections_of(db_session, _M.NEW_SET_ID))
    old = _keyed(await _sections_of(db_session, _SOURCE_SET_ID))
    assert {key: new.pop(key) for key in _NEW_KEYS} == {
        (c, s, slot, v): (body, cond, order) for c, s, slot, v, body, cond, order in _M.NEW_ROWS
    }
    assert new == old


@pytest.mark.parametrize("model", ["sonnet", "opus"])
async def test_claude_story_sets_are_untouched(db_session: AsyncSession, model: ChatModelId) -> None:
    """Claude 체인 기대 집합은 system·generation 뿐이라 이 채널이 들어가면 그 체인 게시가 막힌다."""
    assert await _active_id(db_session, model) == _CLAUDE_SET_IDS[model]
    assert all(s.channel != _M._CHANNEL for s in await _sections_of(db_session, _CLAUDE_SET_IDS[model]))


async def test_downgrade_then_upgrade_swaps_the_active_set_and_back(db_session: AsyncSession) -> None:
    """되돌리면 활성 story Gemini 세트가 원본으로 돌아가고 이 채널 행이 어디에도 남지 않는다. 다시 올리면 같은 리터럴
    세트가 활성이 된다. Claude 체인 활성 세트는 내내 그대로다."""
    connection = await db_session.connection()
    claude_before = {model: await _active_id(db_session, model) for model in _CLAUDE_SET_IDS}

    await connection.run_sync(_M.delete_seeded_rows)

    assert await _active_id(db_session) == _SOURCE_SET_ID
    assert await db_session.get(PromptSet, _M.NEW_SET_ID) is None
    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSection).where(PromptSection.channel == _M._CHANNEL)
    )
    assert remaining == 0
    assert {model: await _active_id(db_session, model) for model in _CLAUDE_SET_IDS} == claude_before

    await connection.run_sync(_M.seed_published_set, datetime.now(UTC))

    assert await _active_id(db_session) == _M.NEW_SET_ID
    assert {model: await _active_id(db_session, model) for model in _CLAUDE_SET_IDS} == claude_before


async def test_seed_refuses_to_run_twice(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 4개"):
        await connection.run_sync(_M.seed_published_set, datetime.now(UTC))


# ---- `_patch_draft` ------------------------------------------------------------------------


async def _clone_as_draft(db_session: AsyncSession, set_id: uuid.UUID, lane: PromptLane, model: str) -> uuid.UUID:
    source = await db_session.get(PromptSet, set_id)
    assert source is not None
    draft = PromptSet(
        version=None,
        status="draft",
        lane=lane,
        model=model,
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


async def test_patch_draft_adds_rows_in_place_and_the_draft_publishes_then_downgrade_removes_them(
    db_session: AsyncSession,
) -> None:
    """운영 story 레인에는 Gemini 초안이 있다 — 이 리비전 이전 배치의 초안(원본 복제)에 4행이 더해지고 다른 행은
    그대로이며, 게시 게이트 전체(head 코드 표)를 통과한다. 되돌리기는 초안의 이 채널 행만 지운다."""
    draft_id = await _clone_as_draft(db_session, _SOURCE_SET_ID, "story", "gemini")
    before = _keyed(await _sections_of(db_session, draft_id))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is True

    sections = await _sections_of(db_session, draft_id)
    after = _keyed(sections)
    assert {key: after.pop(key) for key in _NEW_KEYS} == {
        (c, s, slot, v): (body, cond, order) for c, s, slot, v, body, cond, order in _M.NEW_ROWS
    }
    assert after == before
    draft = await db_session.get(PromptSet, draft_id)
    assert draft is not None
    _validate_prompt_draft_for_publish(draft, sections, lane="story")

    await connection.run_sync(_M._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_draft_leaves_claude_drafts_alone(db_session: AsyncSession) -> None:
    """story Claude 초안만 있으면 할 일이 없다 — 모델 조건이 빠지면 Claude 초안에 판정 행이 들어가 그 체인 게시가 막힌다."""
    draft_id = await _clone_as_draft(db_session, _CLAUDE_SET_IDS["sonnet"], "story", "sonnet")
    before = _keyed(await _sections_of(db_session, draft_id))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is False

    assert _keyed(await _sections_of(db_session, draft_id)) == before


async def test_patch_draft_raises_when_the_draft_already_has_the_channel(db_session: AsyncSession) -> None:
    await _clone_as_draft(db_session, _M.NEW_SET_ID, "story", "gemini")

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="이미 4개"):
        await connection.run_sync(_M._patch_draft)


# ---- 어드민 게시 ---------------------------------------------------------------------------------


async def test_admin_publishes_a_story_draft_carrying_the_channel(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """활성 세트를 그대로 초안으로 옮겨 게시하면 통과하고, 게시본에 이 채널 4행이 실린다 — 코드 표(기대 행·허용
    플레이스홀더)가 이 마이그레이션의 행과 같이 갔다."""
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)
    cloned = (await db_client.get("/admin/prompt-sets/story/draft")).json()
    put = await db_client.put(
        "/admin/prompt-sets/story/draft", json={"labels": cloned["labels"], "sections": cloned["sections"]}
    )
    assert put.status_code == 200

    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "규칙 판정 채널 포함"})

    assert resp.status_code == 200
    published = {
        (s["channel"], s["scope"], s["slot"], s["variant"]): s["body"]
        for s in resp.json()["sections"]
        if s["channel"] == _M._CHANNEL
    }
    assert published == {(c, s, slot, v): body for c, s, slot, v, body, _, _ in _M.NEW_ROWS}
