"""스탯 규칙 판정이 실채팅·빌더 미리보기의 한 턴에 붙는지 — 판정 LLM 이 규칙 id 를 내면 그 규칙의 폭만큼 `statChange` 가
나가고 엔딩 판정이 이어진다. 판정 실패는 그 턴의 스탯·엔딩 판정을 건너뛴다. 규칙 없는 판정 스탯은 판정에 싣지 않아 값이
그대로이고, 규칙 있는 판정 스탯이 하나도 없거나 규칙 판정 채널이 렌더되지 않으면 판정 LLM 을 부르지 않고 엔딩 판정으로
넘어간다."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.preview_session import get_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
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


async def test_room_turn_letters_stats_in_author_order_not_insertion_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """규칙 글자는 작가가 정한 스탯 순서(`order`)를 따른다. 신뢰(order 1)를 호감(order 0)보다 먼저 넣어, 정렬 없이 읽으면
    행이 놓인 순서대로 신뢰가 a 가 되게 만든다 — 그 순서는 앞선 쓰기·롤백이 남긴 빈자리에 따라 실행마다 달라진다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와")
    trust = _stat(setup, "신뢰", 1)
    db_session.add(trust)
    await db_session.flush()
    affection = _stat(setup, "호감", 0)
    db_session.add(affection)
    await db_session.flush()
    await _add_rules(db_session, affection, ("감싸 준다", 3))
    await _add_rules(db_session, trust, ("약속을 지킨다", 2))
    await db_session.commit()
    await _login_as(db_client, user_id)
    created = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    fake = _FakeLLMClient([StatRuleJudgmentResult(fired_rule_ids=["a1"])])

    events = await _send(db_client, uuid.UUID(created.json()["id"]), fake)

    assert "- a1: 감싸 준다" in fake.prompts[0] and "- b1: 약속을 지킨다" in fake.prompts[0]
    assert [(e["statId"], e["newValue"]) for e in events if e["type"] == "statChange"] == [
        (str(affection.entity_id), 40)
    ]


async def test_room_turn_skips_stats_and_endings_when_rule_judgment_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room_id, affection, _, _ = await _story_room_with_rules(db_client, db_session)
    fake = _FakeLLMClient([LLMClientError("429 RESOURCE_EXHAUSTED")])

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events] == ["token", "done"]
    assert fake.schemas == [StatRuleJudgmentResult]
    assert await _room_stat(db_session, room_id, affection) == 37


async def _lower_ending_threshold(db_session: AsyncSession, ending: Ending) -> None:
    """엔딩 규칙(호감 ≥ 40)을 초기값(37)으로도 통과하게 낮춘다 — 스탯이 움직이지 않는 턴에도 엔딩 판정이 도는지 보려고."""
    await db_session.execute(sa.update(EndingRule).where(EndingRule.ending_id == ending.id).values(threshold=0))
    await db_session.commit()


async def test_room_turn_skips_the_stat_call_but_judges_endings_while_the_set_lacks_the_channel(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """활성 세트에 규칙 판정 채널이 없으면 렌더가 비어 판정 LLM 을 부르지 않는다. 실패가 아니라 "변화 없음"이라 엔딩 판정은
    그대로 이어진다."""
    room_id, affection, _, ending = await _story_room_with_rules(db_client, db_session)
    await _lower_ending_threshold(db_session, ending)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    old_sections = [section for section in sections if section.channel != "stat_rule_judgment"]
    await set_cached_active_prompt_set("story", prompt_set, old_sections, model="gemini")
    fake = _FakeLLMClient([EndingJudgmentResult(triggered=True)])

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events] == ["token", "endingReached", "done"]
    assert fake.schemas == [EndingJudgmentResult]
    assert await _room_stat(db_session, room_id, affection) == 37


async def test_room_turn_leaves_a_judged_stat_without_rules_out_of_the_judgment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """규칙 없는 판정 스탯(신뢰)은 판정 프롬프트에 싣지 않고 값이 그대로다. 규칙 있는 스탯(호감)은 그대로 판정을 받는다 —
    실린 스탯만 글자를 받으므로 호감이 a 다."""
    room_id, affection, trust, _ = await _story_room_with_rules(db_client, db_session)
    await db_session.execute(sa.delete(StatRule).where(StatRule.stat_def_id == trust.id))
    await db_session.commit()
    fake = _FakeLLMClient([StatRuleJudgmentResult(fired_rule_ids=["a1", "b1"]), EndingJudgmentResult(triggered=False)])

    events = await _send(db_client, room_id, fake)

    assert [(e["statId"], e["newValue"]) for e in events if e["type"] == "statChange"] == [
        (str(affection.entity_id), 40)
    ]
    assert fake.schemas == [StatRuleJudgmentResult, EndingJudgmentResult]
    assert "신뢰" not in fake.prompts[0]
    assert await _room_stat(db_session, room_id, trust) == 37


async def test_room_turn_without_any_rules_skips_the_stat_call_and_judges_endings(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판정 스탯 어디에도 규칙이 없으면 판정 LLM 을 부르지 않고 스탯은 그대로다. 엔딩 판정은 스탯 반영 결과가 있을 때만
    돌기 때문에, 이 턴을 실패로 다루면 엔딩이 멈춘다 — 엔딩 판정이 그대로 이어져야 한다."""
    room_id, affection, trust, ending = await _story_room_with_rules(db_client, db_session)
    await db_session.execute(sa.delete(StatRule).where(StatRule.stat_def_id.in_([affection.id, trust.id])))
    await _lower_ending_threshold(db_session, ending)
    fake = _FakeLLMClient([EndingJudgmentResult(triggered=True)])

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events] == ["token", "endingReached", "done"]
    assert fake.schemas == [EndingJudgmentResult]
    assert fake.call_sites == ["chat_generate", "chat_ending_judgment"]
    assert await _room_stat(db_session, room_id, affection) == 37


# ---- 빌더 미리보기 ------------------------------------------------------------------------------


def _preview_payload(stat_id: str, ending_id: str, *, with_rules: bool = True) -> dict[str, object]:
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
        ]
        if with_rules
        else [],
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



async def test_preview_turn_without_rules_skips_the_stat_call_and_judges_endings(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안 스탯에 아직 규칙이 없으면(발행은 막지만 미리보기는 돈다) 판정 LLM 을 부르지 않고 값이 그대로다. 그래도 카운터는
    굴러가고 엔딩 판정은 이어진다."""
    user_id, _, _ = await _story_with_setup(db_session, opening_message=None)
    await db_session.commit()
    await _login_as(db_client, user_id)
    stat_id, counter_id = str(uuid.uuid4()), str(uuid.uuid4())
    payload = _preview_payload(stat_id, str(uuid.uuid4()), with_rules=False)
    setup = payload["startingSetups"][0]  # type: ignore[index]
    counter = {**setup["statDefs"][0], "id": counter_id, "name": "남은 날", "initialValue": 10, "perTurnDelta": -1}
    setup["statDefs"].append(counter)
    started = await db_client.post("/preview-sessions", json=payload)
    session_id = started.json()["previewSessionId"]
    fake = _FakeLLMClient([EndingJudgmentResult(triggered=True)])

    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "감싼다"})
    finally:
        _clear_llm_override()

    events = _parse_sse_events(resp.text)
    assert [e["type"] for e in events] == ["token", "statChange", "endingReached", "done"]
    assert (events[1]["statId"], events[1]["newValue"]) == (counter_id, 9)
    assert fake.call_sites == ["preview_generate", "preview_ending_judgment"]
    state = await get_preview_session(session_id)
    assert state is not None and state.stats == {stat_id: 95.0, counter_id: 9.0} and state.ending_reached is True
