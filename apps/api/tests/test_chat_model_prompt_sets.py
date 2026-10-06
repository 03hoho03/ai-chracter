"""한 턴이 읽는 두 프롬프트 세트 — 생성은 값을 낸 모델의 세트, 판정·요약은 Gemini 세트.

시드 마이그레이션이 Claude 세트를 Gemini 세트의 사본으로 심으므로, 그대로 두면 어느 세트가 쓰였는지 결과로 구분되지
않는다. 그래서 테스트 안에서 Sonnet 세트의 바닥 지시문·생성 문안에 표지 문장을 붙이고 사용자 라벨을 바꾼다.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat.prompt_builder import StatJudgmentResult, load_active_prompt_set
from api.chat.prompt_set_cache import get_cached_active_prompt_set
from api.core import clover
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.chat import ChatRoom
from api.db.models.clover import CloverLedger
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _allow_chat_premium,
    _clear_llm_override,
    _make_user_with_clover_lot,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
)

_MARK = "소넷 세트 표지 문장"
_SONNET_LABEL = "소넷독자"


class _RecordingLLM(LLMClient):
    def __init__(self) -> None:
        self.generate_calls: list[tuple[str, str | None, list[str] | None, LLMCallContext]] = []
        self.structured_prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.generate_calls.append((prompt, system_instruction, stop_sequences, usage))
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.structured_prompts.append(prompt)
        return StatJudgmentResult(stat_changes=[])


async def _sonnet_story_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, uuid.UUID]:
    """Sonnet 을 고른 스토리 방(스탯 하나라 새 턴마다 스탯 판정이 구조화 호출로 나간다)과 그 주인."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    await db_session.commit()
    await _allow_chat_premium(db_session, monkeypatch, user.id)
    room = await _open_room(db_client, db_session, turns=1, lane="story", user=user)
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model="sonnet"))
    await db_session.commit()
    return room.room_id, user.id


async def _sonnet_set_id(db_session: AsyncSession) -> uuid.UUID:
    set_id = await db_session.scalar(
        select(PromptSet.id).where(PromptSet.lane == "story", PromptSet.model == "sonnet", PromptSet.status == "published")
    )
    assert set_id is not None
    return set_id


async def _mark_sonnet_set(db_session: AsyncSession) -> None:
    set_id = await _sonnet_set_id(db_session)
    await db_session.execute(
        update(PromptSection)
        .where(PromptSection.prompt_set_id == set_id, PromptSection.channel.in_(["system", "generation"]))
        .values(body=PromptSection.body + "\n" + _MARK)
    )
    await db_session.execute(update(PromptSet).where(PromptSet.id == set_id).values(user_label=_SONNET_LABEL))
    await db_session.commit()


async def _post(db_client: httpx.AsyncClient, fake: LLMClient, method: str, path: str, **kwargs: Any) -> httpx.Response:
    _override_llm_client(fake)
    try:
        return await db_client.request(method, path, **kwargs)
    finally:
        _clear_llm_override()


def _generation(fake: _RecordingLLM) -> tuple[str, str | None, list[str] | None, LLMCallContext]:
    calls = [call for call in fake.generate_calls if call[3].call_site == "chat_generate"]
    assert len(calls) == 1
    return calls[0]


async def test_premium_turn_generates_from_its_model_set_and_judges_from_the_gemini_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, _ = await _sonnet_story_room(db_client, db_session, monkeypatch)
    await _mark_sonnet_set(db_session)
    fake = _RecordingLLM()

    resp = await _post(db_client, fake, "POST", f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)][-1] == "done"
    prompt, system_instruction, stop_sequences, usage = _generation(fake)
    assert usage.model == "sonnet"
    assert system_instruction is not None and _MARK in system_instruction
    assert _MARK in prompt
    assert stop_sequences == [f"\n{_SONNET_LABEL}:"]
    # 스탯 판정은 Gemini 세트로 렌더됐다 — Claude 세트에는 판정 채널이 없어 그 세트로 렌더하면 판정 문안이 비어 스탯
    # 정의조차 실리지 않는다.
    assert len(fake.structured_prompts) == 1
    assert "[STAT]신뢰" in fake.structured_prompts[0]
    assert _MARK not in fake.structured_prompts[0]


async def test_premium_regenerate_generates_from_its_model_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, _ = await _sonnet_story_room(db_client, db_session, monkeypatch)
    await _mark_sonnet_set(db_session)
    fake = _RecordingLLM()

    resp = await _post(db_client, fake, "POST", f"/chat-rooms/{room_id}/regenerate")

    assert resp.status_code == 200
    prompt, system_instruction, stop_sequences, usage = _generation(fake)
    assert usage.model == "sonnet"
    assert system_instruction is not None and _MARK in system_instruction
    assert _MARK in prompt
    assert stop_sequences == [f"\n{_SONNET_LABEL}:"]


@pytest.mark.parametrize("surface", ["send", "regenerate"])
async def test_missing_model_set_is_an_error_event_with_a_refund(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    """(레인, 모델)에 게시본이 없으면 Gemini 세트로 조용히 대신 쓰지 않는다 — 렌더 실패와 같은 오류 이벤트와 환불이다.
    세트는 차감 뒤에야 알 수 있어(모델이 영수증에서 온다) 의존성 단계의 404·500 이 아니다."""
    room_id, user_id = await _sonnet_story_room(db_client, db_session, monkeypatch)
    set_id = await _sonnet_set_id(db_session)
    await db_session.execute(delete(PromptSection).where(PromptSection.prompt_set_id == set_id))
    await db_session.execute(delete(PromptSet).where(PromptSet.id == set_id))
    await db_session.commit()
    fake = _RecordingLLM()

    if surface == "send":
        resp = await _post(db_client, fake, "POST", f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    else:
        resp = await _post(db_client, fake, "POST", f"/chat-rooms/{room_id}/regenerate")

    assert resp.status_code == 200
    assert [e["type"] for e in _parse_sse_events(resp.text)] == ["error"]
    assert fake.generate_calls == []
    ledger = sorted(
        (row.kind, row.amount)
        for row in (await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    )
    assert ledger == [("chat_refund", clover.CHAT_TURN_COST_SONNET), ("chat_spend", -clover.CHAT_TURN_COST_SONNET)]


async def test_memory_fold_gets_the_gemini_set_in_a_premium_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """요약은 구조가 정해진 Gemini 호출이라 Gemini 세트를 받는다(Claude 세트에는 요약 채널이 없다)."""
    room_id, _ = await _sonnet_story_room(db_client, db_session, monkeypatch)
    folded_with: list[str] = []

    async def _recording_fold(*_args: Any, **kwargs: Any) -> None:
        folded_with.append(kwargs["prompt_set"].model)

    monkeypatch.setattr(chat_router, "fold_memory", _recording_fold)

    resp = await _post(db_client, _RecordingLLM(), "POST", f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})

    assert resp.status_code == 200
    assert folded_with == ["gemini"]


async def test_gemini_room_does_not_read_any_model_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini 방은 받은 Gemini 세트를 그대로 쓴다 — 모델별 세트 조회가 없다(세트 조회는 판정용 Gemini 세트 한 번뿐)."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=0)
    await db_session.commit()
    room = await _open_room(db_client, db_session, turns=1, lane="story", user=user)
    looked_up: list[str] = []
    real_cached, real_load = get_cached_active_prompt_set, load_active_prompt_set

    async def _cached(lane: Any, *, model: str) -> Any:
        looked_up.append(model)
        return await real_cached(lane, model=model)  # type: ignore[arg-type]

    async def _load(db: Any, *, lane: Any, model: str = "gemini") -> Any:
        looked_up.append(model)
        return await real_load(db, lane=lane, model=model)  # type: ignore[arg-type]

    monkeypatch.setattr(chat_router, "get_cached_active_prompt_set", _cached)
    monkeypatch.setattr(chat_router, "load_active_prompt_set", _load)
    fake = _RecordingLLM()

    resp = await _post(db_client, fake, "POST", f"/chat-rooms/{room.room_id}/messages", json={"content": "안녕"})

    assert resp.status_code == 200
    assert _generation(fake)[3].model == "gemini"
    assert set(looked_up) == {"gemini"}
