"""chat-longrun-goal-prompt.md LB-9·LB-14·LB-27: 턴 계측 trace 의 **호출부 층**(`_stream_new_turn`)만
단언한다. 클라이언트 층(`GeminiLLMClient` 의 `usage`)은 가짜 클라이언트로는 한 줄도 돌지 않으므로
여기서 보지 않는다(LB-27).

두 경로는 `tmp_path` 로 monkeypatch 한다(chat-longrun-goal-prompt.md LB-28) — `.env` 나 셸에서 들어온
값이 있어도 보존 원본에 가짜 방 레코드가 섞이지 않게 하는 두 번째 방어선이다.
"""

import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    PromptRenderError,
    StatChangeJudgment,
    StatJudgmentResult,
)
from api.core.config import settings
from api.db.models import (
    ChatRoom,
    ChatRoomStat,
    Content,
    Ending,
    EndingRule,
    EndingRuleOperator,
    StartingSetup,
    StatDef,
)
from api.llm.client import LLMClient, LLMClientError, LLMPolicyViolationError, LLMRateLimitError
from factories import (
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_published_story,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
)


class _QueueLLMClient(LLMClient):
    """`generate` 는 `generate_errors` 를 호출 순서대로 소비해 예외면 첫 토큰 전에 raise 하고,
    `generate_structured` 는 `structured_results` 를 호출 순서대로 소비한다(예외면 raise)."""

    def __init__(self, structured_results: list[Any], generate_errors: list[Exception | None] | None = None) -> None:
        self._structured_results = list(structured_results)
        self._generate_errors = list(generate_errors or [])

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
    ) -> AsyncIterator[str]:
        error = self._generate_errors.pop(0) if self._generate_errors else None
        if error is not None:
            raise error
        yield "장면이 움직인다."

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None) -> Any:
        result = self._structured_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def _story_with_setup(db_session: AsyncSession) -> tuple[uuid.UUID, Content, StartingSetup]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="첫 만남",
        prologue="낯선 마을에 도착했다.",
        opening_message="어서 와요.",
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    return user.id, content, setup


async def _add_stat(db_session: AsyncSession, setup: StartingSetup, **overrides: object) -> StatDef:
    fields: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": setup.id,
        "icon": "heart",
        "color": "#ff0000",
        "min_value": 0,
        "max_value": 100,
        "unit": None,
        "description": "스탯",
    }
    fields.update(overrides)
    stat_def = StatDef(**fields)
    db_session.add(stat_def)
    await db_session.flush()
    return stat_def


async def _add_ending_with_rule(
    db_session: AsyncSession, setup: StartingSetup, *, name: str, order: int, rule: EndingRule | None
) -> Ending:
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name=name,
        turn_count_gate=10,
        judgment_prompt=f"{name} 에 이르렀는가?",
        epilogue="끝.",
        order=order,
    )
    db_session.add(ending)
    await db_session.flush()
    if rule is not None:
        rule.ending_id = ending.id
        db_session.add(rule)
        await db_session.flush()
    return ending


def _rule(stat_def: StatDef, operator: EndingRuleOperator, threshold: int) -> EndingRule:
    return EndingRule(
        entity_id=uuid.uuid4(),
        stat_def_entity_id=stat_def.entity_id,
        operator=operator,
        threshold=threshold,
        next_op=None,
        order=1,
    )


async def _open_room(client: httpx.AsyncClient, user_id: uuid.UUID, content: Content, setup: StartingSetup) -> str:
    await _login_as(client, user_id)
    resp = await client.post(
        "/chat-rooms",
        json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)},
    )
    assert resp.status_code == 201
    room_id: str = resp.json()["id"]
    return room_id


def _read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def trace_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(settings, "longrun_trace_path", str(path))
    monkeypatch.setattr(settings, "prompt_dump_path", str(tmp_path / "prompt-dump.jsonl"))
    return path


async def test_longrun_trace_records_ten_turns_and_rules_pass_for_every_judged_ending(
    db_client: httpx.AsyncClient, db_session: AsyncSession, trace_path: Path
) -> None:
    """10턴 — 턴마다 generation·stat_judgment·stat_outcome 이 이 순서로 남고, 판정 턴(10)에는 엔딩
    셋 모두의 ending_judgment·ending_check 가 남는다. `triggered=false` 엔딩에도 rulesPass 가 실제
    규칙 평가값으로 남는다(LB-14) — A 는 거짓, B 는 참이라 상수로는 둘 다 맞출 수 없다."""
    user_id, content, setup = await _story_with_setup(db_session)
    affinity = await _add_stat(db_session, setup, name="호감도", initial_value=50, order=1)
    days = await _add_stat(
        db_session, setup, name="남은 날", initial_value=30, min_value=0, max_value=30, per_turn_delta=-1, order=2
    )
    await _add_ending_with_rule(
        db_session, setup, name="A", order=1, rule=_rule(affinity, EndingRuleOperator.GTE, 80)
    )
    await _add_ending_with_rule(db_session, setup, name="B", order=2, rule=_rule(days, EndingRuleOperator.LTE, 25))
    await _add_ending_with_rule(
        db_session, setup, name="C", order=3, rule=_rule(affinity, EndingRuleOperator.GTE, 80)
    )
    await db_session.commit()
    room_id = await _open_room(db_client, user_id, content, setup)

    aff, day = str(affinity.entity_id), str(days.entity_id)
    structured: list[Any] = [
        StatJudgmentResult(stat_changes=[StatChangeJudgment(stat_id=aff, new_value=60)]),
        *[StatJudgmentResult(stat_changes=[]) for _ in range(9)],
        EndingJudgmentResult(triggered=False),
        EndingJudgmentResult(triggered=False),
        EndingJudgmentResult(triggered=True),
    ]
    _override_llm_client(_QueueLLMClient(structured))
    try:
        for turn in range(1, 11):
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": f"발화 {turn}"})
            assert resp.status_code == 200
            assert [e["type"] for e in _parse_sse_events(resp.text)][-1] == "done"
    finally:
        _clear_llm_override()

    records = _read_trace(trace_path)
    assert {r["roomId"] for r in records} == {room_id}
    assert all(isinstance(r["ts"], str) for r in records)
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        by_turn.setdefault(record["turn"], []).append(record)
    assert sorted(by_turn) == list(range(1, 11))

    for turn in range(1, 10):
        assert [r["kind"] for r in by_turn[turn]] == ["generation", "stat_judgment", "stat_outcome"]
    assert [r["kind"] for r in by_turn[10]] == [
        "generation",
        "stat_judgment",
        "stat_outcome",
        *["ending_judgment", "ending_check"] * 3,
    ]
    for turn_records in by_turn.values():
        generation, stat_judgment = turn_records[0], turn_records[1]
        assert generation["ok"] is True
        assert "errorType" not in generation
        assert generation["promptChars"] > 0
        assert generation["systemChars"] >= 0
        assert stat_judgment["promptChars"] > 0

    first_outcome = by_turn[1][2]
    assert first_outcome["before"] == {aff: 50.0, day: 30.0}
    assert first_outcome["changes"] == [{"statId": aff, "newValue": 60.0}]
    assert first_outcome["after"] == {aff: 60.0, day: 29.0}
    assert first_outcome["counterApplied"] is True
    tenth_after = by_turn[10][2]["after"]
    assert tenth_after == {aff: 60.0, day: 20.0}

    judgments = [r for r in by_turn[10] if r["kind"] == "ending_judgment"]
    assert [(r["name"], r["order"]) for r in judgments] == [("A", 1), ("B", 2), ("C", 3)]
    assert all(r["promptChars"] > 0 for r in judgments)
    checks = [r for r in by_turn[10] if r["kind"] == "ending_check"]
    assert [(r["name"], r["order"], r["gate"], r["triggered"], r["rulesPass"]) for r in checks] == [
        ("A", 1, 10, False, False),
        ("B", 2, 10, False, True),
        ("C", 3, 10, True, False),
    ]
    assert all(r["statsAtCheck"] == tenth_after for r in checks)

    room = await db_session.get(ChatRoom, uuid.UUID(room_id))
    assert room is not None
    assert room.turn_count == 10
    assert room.ending_reached is False


async def test_longrun_trace_ending_rate_limit_records_judgment_failed_and_keeps_the_counter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, trace_path: Path
) -> None:
    """엔딩 판정 호출의 429 는 `judgment_failed{stage=ending, order, errorType}` 로 남고, 이미 적용된
    스탯 변화(카운터 포함)는 그 턴에 커밋된다 — E5·LB-29 의 전제."""
    user_id, content, setup = await _story_with_setup(db_session)
    affinity = await _add_stat(db_session, setup, name="호감도", initial_value=50, order=1)
    days = await _add_stat(
        db_session, setup, name="남은 날", initial_value=30, min_value=0, max_value=30, per_turn_delta=-1, order=2
    )
    ending = await _add_ending_with_rule(db_session, setup, name="A", order=1, rule=None)
    ending.turn_count_gate = 1
    await db_session.commit()
    room_id = await _open_room(db_client, user_id, content, setup)

    _override_llm_client(
        _QueueLLMClient(
            [
                StatJudgmentResult(stat_changes=[StatChangeJudgment(stat_id=str(affinity.entity_id), new_value=70)]),
                LLMRateLimitError("429 RESOURCE_EXHAUSTED"),
            ]
        )
    )
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "발화"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    records = _read_trace(trace_path)
    assert [r["kind"] for r in records] == ["generation", "stat_judgment", "stat_outcome", "judgment_failed"]
    failed = records[-1]
    assert (failed["roomId"], failed["turn"], failed["stage"], failed["order"], failed["errorType"]) == (
        room_id,
        1,
        "ending",
        1,
        "LLMRateLimitError",
    )
    assert failed["message"] == "429 RESOURCE_EXHAUSTED"

    affinity_row = await db_session.get(ChatRoomStat, (uuid.UUID(room_id), affinity.entity_id))
    days_row = await db_session.get(ChatRoomStat, (uuid.UUID(room_id), days.entity_id))
    assert affinity_row is not None and days_row is not None
    assert (float(affinity_row.current_value), float(days_row.current_value)) == (70.0, 29.0)


async def test_longrun_trace_records_generation_and_stat_stage_failures(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    trace_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """생성 실패 세 갈래(정책·429·일반)와 프롬프트 렌더 실패는 `generation{ok=false, errorType}` 로,
    스탯 판정 실패는 `judgment_failed{stage=stat}` 로 남는다. 성공한 턴이 없으니 turn 은 계속 1 이다."""
    user_id, content, setup = await _story_with_setup(db_session)
    await _add_stat(db_session, setup, name="호감도", initial_value=50, order=1)
    await db_session.commit()
    room_id = await _open_room(db_client, user_id, content, setup)

    async def _broken_build_prompt(*args: object, **kwargs: object) -> tuple[str, str]:
        raise PromptRenderError("섹션 렌더 실패")

    with monkeypatch.context() as patch:
        patch.setattr(chat_router, "_build_prompt", _broken_build_prompt)
        _override_llm_client(_QueueLLMClient([]))
        try:
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "발화"})
        finally:
            _clear_llm_override()
        assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]

    _override_llm_client(
        _QueueLLMClient(
            [LLMRateLimitError("429 RESOURCE_EXHAUSTED")],
            generate_errors=[
                LLMPolicyViolationError("blocked"),
                LLMRateLimitError("429"),
                LLMClientError("boom"),
                None,
            ],
        )
    )
    try:
        for _ in range(4):
            resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "발화"})
            assert resp.status_code == 200
    finally:
        _clear_llm_override()

    records = _read_trace(trace_path)
    assert {(r["roomId"], r["turn"]) for r in records} == {(room_id, 1)}
    generations = [r for r in records if r["kind"] == "generation"]
    assert [(g["ok"], g.get("errorType")) for g in generations] == [
        (False, "PromptRenderError"),
        (False, "LLMPolicyViolationError"),
        (False, "LLMRateLimitError"),
        (False, "LLMClientError"),
        (True, None),
    ]
    assert generations[0]["promptChars"] is None
    assert all(g["promptChars"] > 0 for g in generations[1:])
    assert [r["kind"] for r in records[len(generations) :]] == ["judgment_failed"]
    failed = records[-1]
    assert (failed["stage"], failed["order"], failed["errorType"]) == ("stat", None, "LLMRateLimitError")


async def test_longrun_trace_off_writes_nothing_and_skips_the_extra_rule_lookup(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """꺼짐(`longrun_trace_path=None`)이면 파일이 하나도 안 생기고, `triggered=false` 엔딩의 규칙을
    따로 조회하지도 않는다 — 꺼진 상태는 쿼리까지 기존과 같다(progress IV-4 에 따른 LB-14 조건)."""
    monkeypatch.setattr(settings, "longrun_trace_path", None)
    monkeypatch.setattr(settings, "prompt_dump_path", None)
    monkeypatch.chdir(tmp_path)
    user_id, content, setup = await _story_with_setup(db_session)
    affinity = await _add_stat(db_session, setup, name="호감도", initial_value=50, order=1)
    ending = await _add_ending_with_rule(
        db_session, setup, name="A", order=1, rule=_rule(affinity, EndingRuleOperator.GTE, 80)
    )
    ending.turn_count_gate = 1
    await db_session.commit()
    room_id = await _open_room(db_client, user_id, content, setup)

    # 방 생성 응답의 contentSnapshot 도 `_ending_rule_items` 를 부르므로, 세는 것은 방을 연 뒤부터다.
    rule_lookups: list[uuid.UUID] = []
    original_rule_items = chat_router._ending_rule_items

    async def _counting_rule_items(db: AsyncSession, ending: Ending) -> Any:
        rule_lookups.append(ending.id)
        return await original_rule_items(db, ending)

    monkeypatch.setattr(chat_router, "_ending_rule_items", _counting_rule_items)
    _override_llm_client(_QueueLLMClient([StatJudgmentResult(stat_changes=[]), EndingJudgmentResult(triggered=False)]))
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "발화"})
    finally:
        _clear_llm_override()

    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["token", "done"]
    assert rule_lookups == []
    assert os.listdir(tmp_path) == []
