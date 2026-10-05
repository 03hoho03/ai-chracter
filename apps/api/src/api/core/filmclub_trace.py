"""측정 브랜치 전용 계측 trace. 운영 코드로 병합하지 않는다.

두 종류의 레코드를 JSONL 한 줄씩 남긴다.
- `stat_outcome`: 스토리 턴의 스탯 판정 결과를 스탯마다 시작 값·판정이 요청한 값·실제 적용 값으로. 요청과 적용이
  다르면 방향·한 턴 최대 폭·범위 자르기가 일한 것이다. 판정 모델이 낸 변경 목록도 `judgmentOutput` 에 그대로
  남긴다 — 요청 값은 같은 스탯의 마지막 항목만 남기고 모르는 statId 를 버려, 판정이 다른 줄의 값을 읽었는지 같은
  오독을 가릴 수 없다.
- `llm_call`: LLM 호출 한 건의 call_site·모델·경과 ms·성공 여부. 실패한 호출(시간 초과 포함)도 남긴다.

`settings.filmclub_trace_path` 가 None 이면 아무것도 하지 않는다(기본값). 프롬프트 덤프처럼 `.env` 가 아니라 서버
기동 명령의 환경 변수로만 켠다 — `.env` 에 두면 pytest 가 같은 파일에 가짜 방 기록을 덧붙인다.
기록 실패는 밖으로 내지 않는다. 호출부가 SSE 제너레이터 본문이라 예외가 새면 그 턴을 넘어 무관한 요청까지 망가진다.

턴 번호는 `_stream_new_turn` 이 문맥 변수에 넣고, 클라이언트 층이 그 값을 읽는다(LLM 인터페이스에 턴 번호가 없다).
턴이 끝난 뒤 백그라운드로 도는 기억 요약 호출은 그 문맥 밖이라 턴 번호 없이 남는다.
"""

import json
import logging
import uuid
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from api.core.config import settings

logger = logging.getLogger(__name__)

_turn: ContextVar[int | None] = ContextVar("filmclub_trace_turn", default=None)


def set_turn(turn: int) -> None:
    if settings.filmclub_trace_path is not None:
        _turn.set(turn)


def current_turn() -> int | None:
    return _turn.get()


def write_trace(kind: str, **fields: Any) -> None:
    path = settings.filmclub_trace_path
    if path is None:
        return
    try:
        record = {"ts": datetime.now(UTC).isoformat(), "kind": kind, "turn": _turn.get(), **fields}
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("filmclub trace 기록 실패 (kind=%s)", kind, exc_info=True)


def trace_llm_call(
    *, call_site: str, model: str, room_id: uuid.UUID | None, elapsed_ms: int, error: BaseException | None
) -> None:
    if settings.filmclub_trace_path is None:
        return
    try:
        write_trace(
            "llm_call",
            callSite=call_site,
            model=model,
            roomId=str(room_id) if room_id is not None else None,
            elapsedMs=elapsed_ms,
            ok=error is None,
            errorType=type(error).__name__ if error is not None else None,
        )
    except Exception:
        logger.warning("filmclub trace llm_call 조립 실패", exc_info=True)


def trace_stat_outcome(
    *,
    room_id: uuid.UUID,
    stat_defs: Sequence[Any],
    current: dict[str, float],
    requested: dict[str, float],
    applied: dict[str, float],
    judgment_output: dict[str, Any] | None = None,
) -> None:
    """`requested` 는 판정이 스탯마다 낸 마지막 값(적용 함수와 같은 규칙), 없으면 그 스탯은 요청 없음(None).
    `judgment_output` 은 구조화 출력 전체(순서·중복·모르는 id 포함)."""
    if settings.filmclub_trace_path is None:
        return
    try:
        stats = []
        for stat_def in stat_defs:
            stat_id = str(stat_def.entity_id)
            start = current.get(stat_id, float(stat_def.initial_value))
            want = requested.get(stat_id)
            got = applied.get(stat_id, start)
            stats.append(
                {
                    "statId": stat_id,
                    "name": stat_def.name,
                    "start": float(start),
                    "requested": float(want) if want is not None else None,
                    "applied": float(got),
                    "maxChangePerTurn": stat_def.max_change_per_turn,
                    "changeDirection": stat_def.change_direction,
                    "clamped": want is not None and float(want) != float(got),
                }
            )
        write_trace("stat_outcome", roomId=str(room_id), stats=stats, judgmentOutput=judgment_output)
    except Exception:
        logger.warning("filmclub trace stat_outcome 조립 실패", exc_info=True)
