"""chat-longrun-goal-prompt.md LB-9·LB-27: 긴 턴 측정용 턴 계측 trace(실험 브랜치 한정, main 병합 안 함).

두 층이 같은 JSONL 파일에 한 줄 한 레코드 `{ts, roomId, turn, kind, …}` 를 남긴다. 호출부 층
(`chat/router.py:_stream_new_turn`)이 턴 문맥을 ContextVar 에 세팅하고, 클라이언트 층
(`llm/gemini.py`)은 그 문맥을 읽어 `usage` 레코드를 같은 키로 남긴다 — `LLMClient` 인터페이스가
usage 를 돌려주지 않아 인자로 넘길 길이 없다(LB-27). 서버 요청은 요청마다 태스크가 따로라
ContextVar 가 요청 사이로 새지 않는다.

`settings.longrun_trace_path` 가 None 이면 두 함수 모두 아무것도 하지 않는다. 기록 실패는 절대
밖으로 내지 않는다 — 호출부가 SSE 제너레이터 본문이라 예외가 새면 무관한 요청까지 500 이 된다
(apps/api/CLAUDE.md §SSE 스트리밍, `_stream_generated_tokens` 의 덤프 가드와 같은 이유).
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from api.core.config import settings

logger = logging.getLogger(__name__)

_turn_context: ContextVar[dict[str, Any] | None] = ContextVar("longrun_turn_context", default=None)


def trace_enabled() -> bool:
    return settings.longrun_trace_path is not None


def set_trace_context(*, reset: bool = False, **fields: Any) -> None:
    """턴 문맥에 `fields` 를 덧붙인다. `reset=True` 면 이전 문맥을 버리고 새로 시작한다(턴 진입)."""
    if not trace_enabled():
        return
    base = {} if reset else (_turn_context.get() or {})
    _turn_context.set({**base, **fields})


def trace_context() -> dict[str, Any]:
    return _turn_context.get() or {}


def write_trace(kind: str, **fields: Any) -> None:
    path = settings.longrun_trace_path
    if path is None:
        return
    try:
        context = trace_context()
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "roomId": context.get("roomId"),
            "turn": context.get("turn"),
            "kind": kind,
            **fields,
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("longrun trace 기록 실패 (kind=%s)", kind, exc_info=True)


def write_usage(
    *, call: str, usage_metadata: Any, model_version: str | None, elapsed_ms: int, finish_reason: Any = None
) -> None:
    """클라이언트 층 `usage` 레코드. 엔딩 판정이면 호출부가 세팅한 `order` 를 붙여 호출부 레코드와
    (roomId, turn, call, order)로 잇는다."""
    if not trace_enabled():
        return
    try:
        fields: dict[str, Any] = {
            name: getattr(usage_metadata, name, None)
            for name in (
                "prompt_token_count",
                "candidates_token_count",
                "thoughts_token_count",
                "cached_content_token_count",
                "total_token_count",
            )
        }
        fields.update(modelVersion=model_version, elapsedMs=elapsed_ms)
        if finish_reason is not None:
            fields["finishReason"] = getattr(finish_reason, "name", str(finish_reason))
        context = trace_context()
        if context.get("call") == "ending":
            fields["order"] = context.get("order")
        write_trace("usage", call=call, **fields)
    except Exception:
        logger.warning("longrun usage 기록 실패 (call=%s)", call, exc_info=True)
