"""스탯 규칙 판정이 실채팅·빌더 미리보기의 한 턴에 붙는지 — 판정 스탯 전부에 규칙이 있는 시작설정에서 판정 LLM 이 규칙
id 를 내면 그 규칙의 폭만큼 `statChange` 가 나가고 엔딩 판정이 이어진다. 판정 실패는 현행처럼 그 턴의 스탯·엔딩 판정을
건너뛴다. 규칙 판정 채널이 없는 세트(배포 직후 캐시)는 현행 판정으로 돈다."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.preview_session import get_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    StatJudgmentResult,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat.prompt_set_cache import set_cached_active_prompt_set
from api.db.models import (
    ChatRoom,
    ChatRoomStat,
    Content,
    ContentVersion,
    Ending,
    EndingRule,
    EndingRuleOperator,
    StartingSetup,
    StatDef,
)
from api.db.models.story import StatRule
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from factories import _clear_llm_override, _login_as, _override_llm_client, _parse_sse_events, _story_with_setup


class _FakeLLMClient(LLMClient):
    """구조화 응답을 호출 순서대로 내는 큐(`test_chat_ending_pipeline_api.py` 의 것과 같은 모양)."""

    def __init__(self, structured_results: list[Any]) -> None:
        self._structured_results = list(structured_results)
        self.schemas: list[Any] = []
        self.prompts: list[str] = []
        self.call_sites: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.call_sites.append(usage.call_site)
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.call_sites.append(usage.call_site)
        self.schemas.append(response_schema)
        self.prompts.append(prompt)
        result = self._structured_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _stat(setup: StartingSetup, name: str, order: int, *, entity_id: uuid.UUID | None = None) -> StatDef:
    return StatDef(
        entity_id=entity_id or uuid.uuid4(),
        starting_setup_id=setup.id,
        name=name,
        icon="heart",
        color="rose",
        min_value=0,
        max_value=100,
        initial_value=37,
        description=f"{name} 설명",
        order=order,
    )


async def _add_rules(db_session: AsyncSession, stat: StatDef, *rules: tuple[str, int]) -> None:
    for order, (condition, delta) in enumerate(rules):
        db_session.add(
            StatRule(entity_id=uuid.uuid4(), stat_def_id=stat.id, condition=condition, delta=delta, order=order)
        )


async def _story_room_with_rules(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[uuid.UUID, StatDef, StatDef, Ending]:
    """판정 스탯 둘(둘 다 규칙 있음)과 「호감 ≥ 40」 규칙의 엔딩 하나가 있는 방. 같은 작품의 초안 버전에는 같은 entity_id
    스탯에 다른 규칙이 달려 있다 — 방은 고정한 버전의 규칙만 읽어야 한다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와")
    affection, trust = _stat(setup, "호감", 0), _stat(setup, "신뢰", 1)
    db_session.add_all([affection, trust])
    await db_session.flush()
    await _add_rules(db_session, affection, ("감싸 준다", 3), ("목숨을 구한다", 8), ("모른 척한다", -8))
    await _add_rules(db_session, trust, ("약속을 지킨다", 2))
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="엔딩",
        turn_count_gate=1,
        judgment_prompt="둘이 가까워졌는가?",
        epilogue="끝",
        order=1,
    )
    db_session.add(ending)
    await db_session.flush()
    db_session.add(
        EndingRule(
            entity_id=uuid.uuid4(),
            ending_id=ending.id,
            stat_def_entity_id=affection.entity_id,
            operator=EndingRuleOperator.GTE,
            threshold=40,
            next_op=None,
            order=1,
        )
    )
    await _add_draft_version_rules(db_session, content, setup, affection, trust)
    await db_session.commit()

    await _login_as(db_client, user_id)
    created = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert created.status_code in (200, 201)
    return uuid.UUID(created.json()["id"]), affection, trust, ending


async def _add_draft_version_rules(
    db_session: AsyncSession, content: Content, setup: StartingSetup, *stats: StatDef
) -> None:
    draft = ContentVersion(content_id=content.id, version_number=2, published_at=None, detail_description="초안")
    db_session.add(draft)
    await db_session.flush()
    draft_setup = StartingSetup(
        entity_id=setup.entity_id, content_version_id=draft.id, name="첫 만남", prologue="프롤로그", order=1
    )
    db_session.add(draft_setup)
    await db_session.flush()
    for order, stat in enumerate(stats):
        draft_stat = _stat(draft_setup, stat.name, order, entity_id=stat.entity_id)
        db_session.add(draft_stat)
        await db_session.flush()
        await _add_rules(db_session, draft_stat, ("초안에만 있는 규칙", 50))


async def _send(db_client: httpx.AsyncClient, room_id: uuid.UUID, fake: _FakeLLMClient) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "구해 준다"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200
    return _parse_sse_events(resp.text)


async def _room_stat(db_session: AsyncSession, room_id: uuid.UUID, stat: StatDef) -> float:
    row = await db_session.get(ChatRoomStat, (room_id, stat.entity_id), populate_existing=True)
    assert row is not None
    return float(row.current_value)


async def test_room_turn_applies_fired_rules_and_judges_the_ending(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """호감은 발동한 셋 중 |폭| 최대(+8, 동점 -8 보다 순서가 앞선다)만 더하고, 신뢰는 +2. 바뀐 값으로 엔딩 규칙(≥ 40)을
    통과해 엔딩 판정이 이어진다. 판정 프롬프트에는 방이 고정한 버전의 규칙만 실리고 현재값(37)은 실리지 않는다. 규칙
    판정도 스탯 판정 call_site 로 간다(판정 모델 스위치)."""
    room_id, affection, trust, ending = await _story_room_with_rules(db_client, db_session)
    fake = _FakeLLMClient(
        [StatRuleJudgmentResult(fired_rule_ids=["a1", "a3", "a2", "b1"]), EndingJudgmentResult(triggered=True)]
    )

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events] == ["token", "statChange", "statChange", "endingReached", "done"]
    assert {e["statId"]: e["newValue"] for e in events if e["type"] == "statChange"} == {
        str(affection.entity_id): 45,
        str(trust.entity_id): 39,
    }
    assert events[3]["endingId"] == str(ending.entity_id)
    assert fake.schemas == [StatRuleJudgmentResult, EndingJudgmentResult]
    assert fake.call_sites == ["chat_generate", "chat_stat_judgment", "chat_ending_judgment"]
    judgment_prompt = fake.prompts[0]
    assert "- a2: 목숨을 구한다" in judgment_prompt and "- b1: 약속을 지킨다" in judgment_prompt
    assert "초안에만 있는 규칙" not in judgment_prompt
    assert "37" not in judgment_prompt

    assert await _room_stat(db_session, room_id, affection) == 45
    assert await _room_stat(db_session, room_id, trust) == 39
    room = await db_session.get(ChatRoom, room_id, populate_existing=True)
    assert room is not None and room.ending_reached is True


async def test_room_turn_skips_stats_and_endings_when_rule_judgment_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room_id, affection, _, _ = await _story_room_with_rules(db_client, db_session)
    fake = _FakeLLMClient([LLMClientError("429 RESOURCE_EXHAUSTED")])

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.schemas == [StatRuleJudgmentResult]
    assert await _room_stat(db_session, room_id, affection) == 37


async def test_room_turn_uses_current_judgment_while_the_cached_set_lacks_the_channel(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """배포 직후 캐시에 남은 옛 세트에는 규칙 판정 채널이 없다 — 렌더가 비어 현행 절대값 판정으로 돈다."""
    room_id, affection, _, _ = await _story_room_with_rules(db_client, db_session)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    old_sections = [section for section in sections if section.channel != "stat_rule_judgment"]
    await set_cached_active_prompt_set("story", prompt_set, old_sections, model="gemini")
    fake = _FakeLLMClient([StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=False)])

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.schemas[0] is StatJudgmentResult
    assert await _room_stat(db_session, room_id, affection) == 37


async def test_room_turn_without_rules_on_every_judged_stat_stays_on_current_judgment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판정 스탯 하나라도 규칙이 없으면 그 시작설정은 통째로 현행 판정이다."""
    room_id, _, trust, _ = await _story_room_with_rules(db_client, db_session)
    await db_session.execute(sa.delete(StatRule).where(StatRule.stat_def_id == trust.id))
    await db_session.commit()
    fake = _FakeLLMClient([StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=False)])

    await _send(db_client, room_id, fake)

    assert fake.schemas[0] is StatJudgmentResult


# ---- 빌더 미리보기 ------------------------------------------------------------------------------


def _preview_payload(stat_id: str, ending_id: str) -> dict[str, object]:
    stat = {
        "id": stat_id,
        "name": "호감",
        "icon": "heart",
        "color": "rose",
        "minValue": 0,
        "maxValue": 100,
        "initialValue": 95,
        "unit": None,
        "description": "호감 설명",
        "rules": [
            {"id": str(uuid.uuid4()), "condition": "감싸 준다", "delta": 10},
            {"id": str(uuid.uuid4()), "condition": "모른 척한다", "delta": -3},
        ],
    }
    ending = {
        "id": ending_id,
        "name": "엔딩",
        "turnCountGate": 1,
        "judgmentPrompt": "가까워졌는가",
        "epilogue": "끝",
        "hint": None,
        "statRules": [],
    }
    setup = {
        "id": str(uuid.uuid4()),
        "name": "시작",
        "prologue": "프롤로그",
        "openingMessage": None,
        "playguide": None,
        "suggestedReplies": [],
        "statDefs": [stat],
        "endings": [ending],
    }
    return {
        "name": "스토리",
        "oneLiner": "한 줄",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "설정",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [setup],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }


async def test_preview_turn_applies_fired_rules_from_the_draft_payload(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """미리보기는 초안 페이로드의 규칙으로 판정한다. 95 + 10 은 최대 100 으로 잘리고, 엔딩 판정이 이어진다."""
    user_id, _, _ = await _story_with_setup(db_session, opening_message=None)
    await db_session.commit()
    await _login_as(db_client, user_id)
    stat_id, ending_id = str(uuid.uuid4()), str(uuid.uuid4())
    started = await db_client.post("/preview-sessions", json=_preview_payload(stat_id, ending_id))
    assert started.status_code == 201
    session_id = started.json()["previewSessionId"]
    fake = _FakeLLMClient(
        [StatRuleJudgmentResult(fired_rule_ids=["a2", "a1"]), EndingJudgmentResult(triggered=True)]
    )

    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "감싼다"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "statChange", "endingReached", "done"]
    assert (events[1]["statId"], events[1]["newValue"]) == (stat_id, 100)
    assert fake.schemas == [StatRuleJudgmentResult, EndingJudgmentResult]
    assert fake.call_sites == ["preview_generate", "preview_stat_judgment", "preview_ending_judgment"]
    assert "- a1: 감싸 준다\n- a2: 모른 척한다" in fake.prompts[0]
    state = await get_preview_session(session_id)
    assert state is not None and state.stats == {stat_id: 100.0}


async def test_preview_turn_skips_stats_and_endings_when_rule_judgment_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, _, _ = await _story_with_setup(db_session, opening_message=None)
    await db_session.commit()
    await _login_as(db_client, user_id)
    stat_id = str(uuid.uuid4())
    started = await db_client.post("/preview-sessions", json=_preview_payload(stat_id, str(uuid.uuid4())))
    session_id = started.json()["previewSessionId"]
    fake = _FakeLLMClient([LLMClientError("429 RESOURCE_EXHAUSTED")])

    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "감싼다"})
    finally:
        _clear_llm_override()

    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["token", "done"]
    assert fake.schemas == [StatRuleJudgmentResult]
    state = await get_preview_session(session_id)
    assert state is not None and state.stats == {stat_id: 95.0} and state.ending_reached is False

