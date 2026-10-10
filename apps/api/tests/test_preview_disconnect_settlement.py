"""빌더 미리보기 턴이 이벤트 하나를 내보낸 직후 끊길 때, 그 자리마다 차감을 되돌리는지와 세션을 저장하는지를 지금 동작
그대로 고정한다.

미리보기는 DB 에 응답을 남기지 않아 `done` 을 내보내는 순간이 응답 확정이다 — 그 앞(토큰·`statChange`·`endingReached`)에서
끊기면 되돌리고, `done` 에 멈춘 뒤 끊기면 되돌리지 않는다. 실패 매트릭스의 끊김은 LLM 을 기다리는 중(`CancelledError`)이거나
`done` 뒤 저장 중뿐이라, 제너레이터가 `yield` 에 멈춘 채 닫히는(`GeneratorExit`) 이 자리들을 보지 않는다. 그래서 정산 표시를
세우는 자리가 `statChange` 앞으로 옮겨 가도(실채팅처럼 응답을 "쓴" 직후에 세우면 그렇게 된다) 다른 테스트는 초록이다.

끊김의 수거 시점에 흔들리지 않도록 서버를 띄우지 않고 라우트 함수를 직접 몬다 — 의존성 값을 인자로 넘기고, 이벤트 k 개를
받은 뒤 `aclose()` 한다. 환급 래퍼와 세션 저장은 호출만 세는 대역이다.

기대값은 지금 동작을 기록한 것이다(`fixtures/preview_disconnect_settlement.json`). 다시 뜨는 법은
`factories._assert_characterization`.
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import api.chat.router as chat_router
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat.schemas import ChatMessageCreateRequest, ChatStreamEvent, PreviewSessionState
from api.content.schemas import MediaTagImage, StoryDraftPayload
from api.core import clover
from api.core.rate_limit_gate import ChatCharge
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.client import LLMCallContext, LLMClient
from factories import _assert_characterization, _preview_story_payload

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "preview_disconnect_settlement.json"

_COST = 10


class _PreviewLLM(LLMClient):
    """생성은 토큰 하나, 스탯 판정은 규칙 a1 발동, 칸 판정은 그 칸, 엔딩 판정은 발동 — 스토리 미리보기 한 턴이 토큰·
    `statChange`·`endingReached`·`done` 을 모두 내보내게 한다."""

    def __init__(self, cell_id: uuid.UUID) -> None:
        self._cell_id = cell_id

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "모두가 행복해졌다."

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=["a1"])
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=str(self._cell_id))
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=True)
        raise AssertionError(f"예상하지 못한 응답 스키마: {response_schema}")


class _RequestSession:
    """라우트가 본문 첫머리에서 반납 커밋만 하는 요청 세션의 대역."""

    async def commit(self) -> None:
        return None


class _Calls:
    def __init__(self) -> None:
        self.refunds = 0
        self.saves = 0


def _install_doubles(monkeypatch: pytest.MonkeyPatch, calls: _Calls) -> None:
    async def refund(
        session_factory: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID,
        spend_ledger_id: uuid.UUID | None,
        amount: int,
        kind: str,
    ) -> None:
        calls.refunds += 1

    async def save(session_id: str, state: PreviewSessionState) -> None:
        calls.saves += 1

    monkeypatch.setattr(clover, "refund_spend_in_new_transaction", refund)
    # 저장은 라우트가 정산 가드 밖에서 부르는 자리다 — 그 자리에 닿았는지만 센다.
    monkeypatch.setattr(chat_router, "update_preview_session", save)


async def _drive(
    payload: dict[str, object],
    cell_id: uuid.UUID,
    prompt_set_data: tuple[PromptSet, list[PromptSection]],
    *,
    stop_after: int | None,
) -> list[str]:
    """새 세션 상태로 미리보기 한 턴을 몬다. `stop_after` 가 있으면 그 번째(0부터) 이벤트를 받은 직후 닫고, 없으면 끝까지
    받는다. 받은 이벤트 종류를 돌려준다."""
    state = chat_router._build_preview_start_state(StoryDraftPayload.model_validate(payload))
    stream = cast(
        AsyncGenerator[ChatStreamEvent, None],
        chat_router.send_preview_message(
            id="preview-session",
            payload=ChatMessageCreateRequest(content="행복해지자"),
            _consent=None,
            db=cast(AsyncSession, _RequestSession()),
            session_factory=async_sessionmaker(),
            user_id=uuid.uuid4(),
            state=state,
            shortcut=None,
            llm_client=_PreviewLLM(cell_id),
            prompt_set_data=prompt_set_data,
            persona=None,
            media_images={cell_id: MediaTagImage(url="https://example.test/cell.png", width=10, height=20)},
            charge=ChatCharge(source="clover", clover_amount=_COST, spend_ledger_id=uuid.uuid4()),
        ),
    )
    received: list[str] = []
    if stop_after is None:
        async for event in stream:
            received.append(event.type)
        return received
    for _ in range(stop_after + 1):
        received.append((await anext(stream)).type)
    await stream.aclose()
    return received


async def test_preview_turn_refund_and_save_at_each_disconnect_point(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt_set_data = await load_active_prompt_set(db_session, lane="story")
    cell_id, payload = _preview_story_payload(uuid.uuid4())

    calls = _Calls()
    _install_doubles(monkeypatch, calls)
    whole = await _drive(payload, cell_id, prompt_set_data, stop_after=None)
    rows: list[dict[str, object]] = [
        {"closedAfter": "end", "events": whole, "refunds": calls.refunds, "saves": calls.saves}
    ]
    for index in range(len(whole)):
        calls = _Calls()
        _install_doubles(monkeypatch, calls)
        received = await _drive(payload, cell_id, prompt_set_data, stop_after=index)
        rows.append({"closedAfter": received[-1], "events": received, "refunds": calls.refunds, "saves": calls.saves})

    _assert_characterization(FIXTURE_PATH, "story-turn", rows)
