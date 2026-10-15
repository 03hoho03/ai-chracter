"""측정 서버의 프롬프트 덤프에 백그라운드 작업(요약 접기·장면 기억 추출·사실 기억 추출)의 호출 프롬프트를 남긴다.

생성·판정 줄은 `turn_engine.py` 가 같은 파일에 쓴다. 이 함수를 거기 두지 않은 것은 기억 모듈들이 덤프 한 줄을 쓰려고 턴
엔진 전체(정산·판정·생성 스트림)에 의존하게 되지 않게 하려는 것이다 — 지금 기억 모듈은 턴 엔진을 import 하지 않는다."""

import json
import logging
import uuid

from api.core.config import settings
from api.llm.chat_models import configured_call_site_model
from api.llm.client import LLMCallSite, structured_model
from api.llm.routing import resolve_backend


def dump_background_prompt(
    *,
    room_id: uuid.UUID,
    call_site: LLMCallSite,
    schema: str,
    prompt: str,
    log: logging.Logger,
    turn: int | None = None,
    cursor_message_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
) -> None:
    """백그라운드 구조화 호출 하나의 프롬프트를 덤프 파일에 한 줄로 남긴다. 덤프 경로가 없으면(운영) 아무것도 하지 않는다 —
    파일을 열지 않고 모델 해석도 하지 않는다. 부르는 쪽은 호출 **앞**에서 부른다 — 실패한 호출의 입력도 남아야 다시 보내 볼 수 있다.

    `kind` 는 `background` 다. 생성 줄만 읽는 리플레이(`scripts/replay/logs.py` 의 `dump_record`)가 이 줄을 생성 줄로 세지
    않게 하려는 것이고, 어느 작업인지는 판정 줄처럼 `callSite` 로 가른다. 모델은 실제로 보낸 id 로, 판정 줄과 같은 해석이다.
    이 호출들은 지시문을 따로 보내지 않아 `systemInstruction` 칸이 없다.

    무엇을 다뤘는지는 그 작업이 아는 식별자로 적는다. 접기는 그때 읽은 방 턴 수(`turn`, 그 턴의 생성 줄과 짝지을 수 있다)와
    접는 마지막 메시지(`cursorMessageId`, 새 스냅샷의 커서)를, 추출은 추출하는 스냅샷(`snapshotId`)을 적는다. 추출은 어느 턴
    뒤에 도는지 모르므로 `turn` 칸을 두지 않는다.

    쓰기 실패는 경고만 남기고 삼킨다 — 덤프는 측정용 부가 기록이라 접기·추출의 결과를 바꾸면 안 된다(생성·판정 덤프와 같다).
    쓰기는 그 둘처럼 한 줄을 한 번의 `write` 로 추가한다."""
    if settings.prompt_dump_path is None:
        return
    try:
        backend, sent = resolve_backend(call_site, configured_call_site_model(call_site))
        record: dict[str, str | int] = {"roomId": str(room_id)}
        if turn is not None:
            record["turn"] = turn
        record |= {
            "kind": "background",
            "callSite": call_site,
            "model": structured_model(call_site, sent) if backend == "gemini" else sent,
            "schema": schema,
            "prompt": prompt,
        }
        if cursor_message_id is not None:
            record["cursorMessageId"] = str(cursor_message_id)
        if snapshot_id is not None:
            record["snapshotId"] = str(snapshot_id)
        with open(settings.prompt_dump_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        log.warning("백그라운드 프롬프트 덤프 실패 (room=%s, call_site=%s)", room_id, call_site, exc_info=True)
