"""리플레이 호출과 호출 기록.

호출은 앱의 라우팅 클라이언트(`get_llm_client` 가 돌려주는 것)로 call_site `replay_generate` 를 실어 보낸다. 고른 모델이
Claude 면 그 호출 위치의 배정대로 Bedrock 이나 Anthropic API 로 가고(배정이 없으면 Bedrock), 모델·출력 상한·사고 설정·
타임아웃이 실제 채팅 생성과 같다. 정지 시퀀스는 그 갈래 세트의 사용자 라벨로 만든다(서버와 같은 모양).

실제로 보낸 모델 id 와 토큰은 공급자 구현이 호출을 마치며 부르는 사용량 기록 함수(`record_usage`)를 감싸 잡는다. 모든
공급자가 이 이름을 같은 인자(call_site, 실제 모델 id, 사용량 메타데이터)로 부르므로 SDK 안쪽을 감쌀 필요가 없다. 중단·오류로
끝난 호출은 기록 함수가 불리지 않아 원가를 모르고(`costUsd` 가 None), 장부는 그 호출을 넉넉한 값으로 센다.
"""

import contextlib
import hashlib
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby
from typing import Any

from api.llm import anthropic_api, bedrock, gemini
from api.llm.client import LLMCallContext, LLMClient
from api.llm.pricing import estimate_cost_usd
from replay.assemble import REPLAY_CALL_SITE, GenerationInput
from replay.budget import CallBudget

# 기록 키 → 사용량 메타데이터 속성. Claude 사용량도 같은 속성 이름으로 옮겨 온다(캐시 쓰기는 Claude 에만 있다).
TOKEN_FIELDS = {
    "prompt": "prompt_token_count",
    "cached": "cached_content_token_count",
    "cacheWrite": "cache_write_token_count",
    "candidates": "candidates_token_count",
    "thoughts": "thoughts_token_count",
    "total": "total_token_count",
}


@dataclass(frozen=True)
class SentCall:
    call_site: str
    model: str
    usage_metadata: object | None


@contextlib.contextmanager
def capture_usage() -> Iterator[list[SentCall]]:
    """이 블록 안에서 공급자 구현 모듈마다의 사용량 기록을 감싸, 원래 기록을 그대로 한 뒤 보낸 값을 목록에 더한다. 블록을
    나가면 원래 함수로 되돌린다."""
    sent: list[SentCall] = []
    originals = [(module, module.record_usage) for module in (gemini, bedrock, anthropic_api)]

    def wrap(original: Callable[..., Any]) -> Callable[..., Any]:
        async def record_usage(call_site: str, model: str, usage_metadata: object | None, **kwargs: Any) -> None:
            await original(call_site, model, usage_metadata, **kwargs)
            sent.append(SentCall(call_site, model, usage_metadata))

        return record_usage

    try:
        for module, original in originals:
            setattr(module, "record_usage", wrap(original))  # noqa: B010 — 모듈 함수 대입은 mypy 가 막는다
        yield sent
    finally:
        for module, original in originals:
            setattr(module, "record_usage", original)  # noqa: B010


def _tokens(usage_metadata: object | None) -> dict[str, int | None] | None:
    if usage_metadata is None:
        return None
    return {key: getattr(usage_metadata, attr, None) for key, attr in TOKEN_FIELDS.items()}


def _cost(model: str | None, tokens: dict[str, int | None] | None) -> float | None:
    if model is None or tokens is None:
        return None
    return estimate_cost_usd(
        model,
        input_tokens=tokens["prompt"] or 0,
        cached_tokens=tokens["cached"] or 0,
        output_tokens=tokens["candidates"] or 0,
        thoughts_tokens=tokens["thoughts"] or 0,
        cache_write_tokens=tokens["cacheWrite"] or 0,
    )


async def run_calls(
    client: LLMClient,
    sent: list[SentCall],
    inputs: list[GenerationInput],
    *,
    reps: int,
    budget: CallBudget,
    user_id: uuid.UUID,
    room_id: uuid.UUID,
    sink: Callable[[dict[str, Any]], None],
) -> None:
    """턴마다, 반복마다 그 턴의 갈래를 차례로 부른다 — 상한에 걸려 멈춰도 이미 부른 반복은 갈래가 짝을 이룬다. `sent` 는
    `capture_usage` 가 채우는 목록이다. 상한에 닿으면 `budgetExhausted` 기록을 남기고 멈춘다."""
    for _turn, group in groupby(inputs, key=lambda item: item.turn):
        items = list(group)
        for rep in range(reps):
            for item in items:
                if not budget.take():
                    sink(
                        {**budget.exhausted(), "turn": item.turn, "variant": item.variant, "arm": item.arm, "rep": rep}
                    )
                    return
                sink(await _call(client, sent, item, rep, budget, user_id=user_id, room_id=room_id))


async def _call(
    client: LLMClient,
    sent: list[SentCall],
    item: GenerationInput,
    rep: int,
    budget: CallBudget,
    *,
    user_id: uuid.UUID,
    room_id: uuid.UUID,
) -> dict[str, Any]:
    sent.clear()
    started = time.perf_counter()
    chunks: list[str] = []
    error: str | None = None
    try:
        async for delta in client.generate(
            item.prompt,
            item.system_instruction,
            stop_sequences=[f"\n{item.user_label}:"],
            usage=LLMCallContext(call_site=REPLAY_CALL_SITE, user_id=user_id, room_id=room_id, model=item.chat_model),
        ):
            chunks.append(delta)
    except Exception as exc:  # 기록하고 다음 호출로 — 실패(정책 차단 등)도 결과다
        error = f"{type(exc).__name__}: {str(exc)[:500]}"
    last = sent[-1] if sent else None
    tokens = _tokens(last.usage_metadata) if last is not None else None
    sent_model = last.model if last is not None else None
    record: dict[str, Any] = {
        "kind": "call",
        "at": datetime.now(UTC).isoformat(),
        "turn": item.turn,
        "variant": item.variant,
        "arm": item.arm,
        "swapLabel": item.swap_label,
        "rep": rep,
        "callSite": last.call_site if last is not None else REPLAY_CALL_SITE,
        "chatModel": item.chat_model,
        "sentModel": sent_model,
        "tokens": tokens,
        "costUsd": _cost(sent_model, tokens),
        "costCeilingUsd": item.cost_ceiling_usd(),
        "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        "historyMessages": item.history_messages,
        "promptChars": len(item.prompt),
        "promptSha256": hashlib.sha256(item.prompt.encode()).hexdigest(),
        "reply": "".join(chunks),
        "error": error,
    }
    budget.charge(record)
    record["cumulativeChargedUsd"] = round(budget.spent_usd, 6)
    return record
