"""판정 입력을 설정별로 반복 호출하고 한 호출을 JSONL 한 줄로 남긴다.

모델·사고 예산은 서버와 같은 경로로 바꾼다 — 판정·발행 심사 call_site 는 `structured_model_and_thinking` 이
`settings.gemini_judgment_*`·`gemini_publish_filter_*` 를 호출마다 읽으므로, 설정 하나를 다 돌 때까지 그 값을 세워 두고
다음 설정으로 넘어간다(설정을 섞어 동시에 돌리면 서로의 값을 덮는다). 동시 실행은 한 설정 안에서만 한다.

토큰·실제로 보낸 모델·사고 설정은 `generate_structured` 가 돌려주지 않아, Gemini SDK 의 `generate_content` 를 감싸
호출 태스크의 컨텍스트 변수에 담는다(`install_usage_capture`). 그 래퍼는 응답·예외를 그대로 통과시킨다.
"""

import asyncio
import contextvars
import hashlib
import io
import mimetypes
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel

from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    StatJudgmentResult,
)
from api.chat.stats import StatChange, apply_stat_changes
from api.content.publish import PublishFilterResult
from api.core.config import settings
from api.db.models.story import StatDef
from api.llm.client import (
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
)
from api.llm.gemini import GeminiLLMClient

from .scenes import JudgmentKind, ReplayInput


@dataclass(frozen=True)
class ReplayConfig:
    name: str
    model: str
    # None 이면 사고 설정을 보내지 않는다(모델 기본), 0 이면 끈다.
    thinking_budget: int | None


CONFIGS: dict[str, ReplayConfig] = {
    config.name: config
    for config in (
        ReplayConfig("3.5-default", "gemini-3.5-flash-lite", None),
        ReplayConfig("3.5-off", "gemini-3.5-flash-lite", 0),
        ReplayConfig("3.1-default", "gemini-3.1-flash-lite", None),
        ReplayConfig("3.1-off", "gemini-3.1-flash-lite", 0),
    )
}
# 비교 기준 — 지금 운영 판정이 도는 설정.
BASELINE_CONFIG = "3.5-default"

Sink = Callable[[dict[str, Any]], None]


def apply_settings(config: ReplayConfig) -> None:
    settings.gemini_judgment_model_name = config.model
    settings.gemini_judgment_thinking_budget = config.thinking_budget
    settings.gemini_publish_filter_model_name = config.model
    settings.gemini_publish_filter_thinking_budget = config.thinking_budget


class CallBudget:
    """프로세스 전체의 실호출 상한. `take` 와 그 앞의 검사 사이에 await 가 없어 동시 워커끼리도 넘지 않는다."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


_capture: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "judgment_replay_capture", default=None
)

_TOKEN_FIELDS = {
    "prompt": "prompt_token_count",
    "cached": "cached_content_token_count",
    "candidates": "candidates_token_count",
    "thoughts": "thoughts_token_count",
    "total": "total_token_count",
}


def install_usage_capture(client: GeminiLLMClient) -> None:
    models = client._client.aio.models
    original = models.generate_content

    async def generate_content(**kwargs: Any) -> Any:
        response = await original(**kwargs)
        slot = _capture.get()
        if slot is not None:
            usage = getattr(response, "usage_metadata", None)
            thinking = getattr(kwargs.get("config"), "thinking_config", None)
            slot["sent_model"] = kwargs.get("model")
            slot["thinking_config_sent"] = thinking is not None
            slot["sent_thinking_budget"] = getattr(thinking, "thinking_budget", None)
            slot["tokens"] = {key: getattr(usage, attr, None) for key, attr in _TOKEN_FIELDS.items()}
            try:
                slot["raw_text"] = response.text
            except Exception:
                slot["raw_text"] = None
        return response

    setattr(models, "generate_content", generate_content)  # noqa: B010 — 메서드 대입은 mypy 가 막는다


def derive(item: ReplayInput, parsed: BaseModel) -> dict[str, Any]:
    """응답을 서버와 같은 후처리로 해석한다 — 스탯은 `apply_stat_changes`(범위 자르기·카운터 무시) 뒤의 방향, 그림은
    후보 id 와 정확히 같을 때만 매칭."""
    if isinstance(parsed, StatJudgmentResult):
        defs: list[StatDef] = item.context["stat_defs"]
        current: dict[str, float] = item.context["current"]
        changes = [StatChange(stat_id=c.stat_id, new_value=c.new_value) for c in parsed.stat_changes]
        updated = apply_stat_changes(current, changes, defs)
        known = {str(d.entity_id) for d in defs}
        counters = {str(d.entity_id) for d in defs if d.per_turn_delta is not None}
        directions = {}
        for stat_def in defs:
            stat_id = str(stat_def.entity_id)
            if stat_id in counters:
                continue
            delta = updated[stat_id] - current[stat_id]
            directions[stat_def.name] = "+" if delta > 0 else "-" if delta < 0 else "0"
        return {
            "directions": directions,
            "deltas": {d.name: updated[str(d.entity_id)] - current[str(d.entity_id)] for d in defs},
            "unknown_stat_ids": sum(c.stat_id not in known for c in parsed.stat_changes),
            "counter_included": any(c.stat_id in counters for c in parsed.stat_changes),
        }
    if isinstance(parsed, ImageMatchJudgmentResult):
        candidates: dict[str, str] = item.context["candidates"]
        matched = parsed.matched_image_entity_id
        return {
            "matched": candidates.get(matched) if matched is not None else None,
            "out_of_candidates": matched is not None and matched not in candidates,
        }
    if isinstance(parsed, EndingJudgmentResult):
        return {"triggered": parsed.triggered}
    if isinstance(parsed, PublishFilterResult):
        return {"passed": parsed.passed, "reason": parsed.reason}
    raise TypeError(f"모르는 응답 스키마: {type(parsed).__name__}")


def _error_type(exc: Exception) -> str:
    if isinstance(exc, LLMRateLimitError):
        return "rate_limit"
    if isinstance(exc, LLMPolicyViolationError):
        return "policy"
    if isinstance(exc, LLMClientError):
        return "parse" if "could not be parsed" in str(exc) else "api"
    return "unexpected"


def _load_images(paths: Sequence[Path]) -> list[tuple[bytes, str]]:
    return [(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream") for path in paths]


async def _call(
    client: LLMClient,
    *,
    prompt: str,
    schema: type[BaseModel],
    call_site: LLMCallSite,
    images: list[tuple[bytes, str]] | None,
) -> tuple[BaseModel | None, Exception | None, dict[str, Any], float]:
    slot: dict[str, Any] = {}
    token = _capture.set(slot)
    started = time.perf_counter()
    try:
        parsed = await client.generate_structured(
            prompt, schema, images=images, usage=LLMCallContext(call_site=call_site, user_id=None, room_id=None)
        )
        return parsed, None, slot, (time.perf_counter() - started) * 1000
    except Exception as exc:
        return None, exc, slot, (time.perf_counter() - started) * 1000
    finally:
        _capture.reset(token)


async def _replay_once(
    client: LLMClient, item: ReplayInput, config: ReplayConfig, rep: int, run_id: str
) -> dict[str, Any]:
    images = _load_images(item.image_paths) if item.image_paths else None
    parsed, exc, slot, latency_ms = await _call(
        client, prompt=item.prompt, schema=item.schema, call_site=item.call_site, images=images
    )
    record: dict[str, Any] = {
        "run_id": run_id,
        "at": datetime.now(UTC).isoformat(),
        "input_id": item.input_id,
        "kind": item.kind,
        "call_site": item.call_site,
        "config": config.name,
        "model": config.model,
        "thinking_budget": config.thinking_budget,
        "rep": rep,
        "ok": exc is None,
        "error_type": None if exc is None else _error_type(exc),
        "error": None if exc is None else str(exc)[:500],
        "output": parsed.model_dump() if parsed is not None else None,
        "derived": derive(item, parsed) if parsed is not None else None,
        "expected": item.expected,
        "tokens": slot.get("tokens"),
        "sent_model": slot.get("sent_model"),
        "sent_thinking_budget": slot.get("sent_thinking_budget"),
        "thinking_config_sent": slot.get("thinking_config_sent"),
        "latency_ms": round(latency_ms, 1),
        "prompt_chars": len(item.prompt),
        "prompt_sha256": hashlib.sha256(item.prompt.encode()).hexdigest()[:16],
        "images": len(item.image_paths),
        "meta": item.context.get("meta", {}),
    }
    if exc is not None:
        record["raw_text"] = slot.get("raw_text")
    return record


@dataclass(frozen=True)
class RunResult:
    calls: int
    stopped_by_limit: bool


async def run_replay(
    client: LLMClient,
    inputs: Sequence[ReplayInput],
    configs: Sequence[ReplayConfig],
    *,
    reps: dict[JudgmentKind, int],
    budget: CallBudget,
    concurrency: int,
    sink: Sink,
    apply_config: Callable[[ReplayConfig], None] = apply_settings,
    run_id: str = "",
) -> RunResult:
    """설정 순서대로, 설정 안에서는 회차 순서대로(회차 0 의 전 입력 → 회차 1 …) 부른다 — 상한에 걸려 멈춰도 앞 설정·앞
    회차가 온전히 남는다. 상한을 넘는 호출은 보내지 않고 멈춘다. 실패한 호출도 한 줄로 남기고 계속한다."""
    stopped = False
    calls = 0
    for config in configs:
        if stopped:
            break
        apply_config(config)
        jobs = deque(
            (item, rep)
            for rep in range(max(reps.values(), default=0))
            for item in inputs
            if rep < reps.get(item.kind, 0)
        )

        async def worker(config: ReplayConfig = config, jobs: deque[tuple[ReplayInput, int]] = jobs) -> None:
            nonlocal stopped, calls
            while jobs and not stopped:
                item, rep = jobs.popleft()
                if not budget.take():
                    stopped = True
                    return
                calls += 1
                sink(await _replay_once(client, item, config, rep, run_id))

        await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    return RunResult(calls=calls, stopped_by_limit=stopped)


def _probe_image() -> tuple[bytes, str]:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (128, 128, 128)).save(buffer, format="PNG")
    return buffer.getvalue(), "image/png"


async def probe_thinking(
    client: LLMClient, models: Sequence[str], *, budget: CallBudget, sink: Sink, run_id: str = ""
) -> RunResult:
    """모델마다 사고 기본·끔(thinking_budget=0) 텍스트 호출 하나씩과, 끔 설정의 이미지 첨부 호출 하나 — 사고 끔이
    받아들여지는지, 사고 토큰이 0 이 되는지, 구조화 출력·이미지 입력이 되는지만 본다."""
    text_prompt = "다음 문장이 비가 왔다는 내용인지 판단하라.\n[문장]\n오늘은 하루 종일 비가 내렸다."
    image_prompt = "첨부한 이미지에 선정성·폭력성 등 부적절한 내용이 있는지 판단해 passed 와 reason 으로 답하라."
    plan: list[tuple[str, int | None, bool]] = [
        (model, thinking, with_image)
        for model in models
        for thinking, with_image in ((None, False), (0, False), (0, True))
    ]
    calls = 0
    for model, thinking, with_image in plan:
        if not budget.take():
            return RunResult(calls=calls, stopped_by_limit=True)
        calls += 1
        config = ReplayConfig(f"probe:{model}:{thinking}", model, thinking)
        apply_settings(config)
        schema: type[BaseModel] = PublishFilterResult if with_image else EndingJudgmentResult
        call_site: LLMCallSite = "publish_filter_character" if with_image else "chat_ending_judgment"
        parsed, exc, slot, latency_ms = await _call(
            client,
            prompt=image_prompt if with_image else text_prompt,
            schema=schema,
            call_site=call_site,
            images=[_probe_image()] if with_image else None,
        )
        sink(
            {
                "run_id": run_id,
                "kind": "probe",
                "config": config.name,
                "model": model,
                "thinking_budget": thinking,
                "with_image": with_image,
                "ok": exc is None,
                "error_type": None if exc is None else _error_type(exc),
                "error": None if exc is None else str(exc)[:500],
                "output": parsed.model_dump() if parsed is not None else None,
                "tokens": slot.get("tokens"),
                "sent_model": slot.get("sent_model"),
                "sent_thinking_budget": slot.get("sent_thinking_budget"),
                "thinking_config_sent": slot.get("thinking_config_sent"),
                "latency_ms": round(latency_ms, 1),
            }
        )
    return RunResult(calls=calls, stopped_by_limit=False)
