"""정본 기억 작업의 모델 호출 기록(`novel_bible_jobs.llm_calls`). 원소 꼴은 소설 작업의 호출 기록(`novelize/call_records.py`)과
같다 — 사용량 칸(`callSite`·`model`·토큰 다섯)에 `backend`·`durationMs`·`promptSetId`·`stage`·`routeSource`·`failure` 를 덧붙인다.
그래서 같은 원가 함수로 칠 수 있다(소설 작업 원가 보고 스크립트는 소설 작업 행만 읽어 이 칸을 세지 않는다). `stage` 는 연산
이름(`facts.extract` 따위)이고, 배정 표를 읽지 않으므로 `routeSource` 는 늘 null 이다.

소설 작업의 함수(`recorded_call`)를 넓히지 않고 따로 둔다 — 넓히려면 그 함수의 단계 이름 타입에 정본 기억 연산을 더해야 해서 소설
생성 경로 모듈이 정본 기억에 묶인다. 대신 그 모듈의 공개 함수(구현·모델 해석과 실패 사유 가르기)를 그대로 쓴다. 두 함수의 원소 키가
같은지는 테스트가 본다."""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

from api.llm.client import CallUsage, LLMCallContext
from api.novel_bible.ids import OperationKey
from api.novelize.call_records import CallFailure, call_failure, sent_model


@contextmanager
def recorded_bible_call(
    records: list[dict[str, Any]], usage: LLMCallContext, *, stage: OperationKey, prompt_set_id: uuid.UUID
) -> Iterator[LLMCallContext]:
    """모델 호출 하나를 감싸 끝날 때(성공·실패·취소 모두) `records` 에 원소를 더한다. 감싼 구간에는 사용량을 모을 목록을 실은
    호출 문맥을 내준다. 공급자가 사용량을 남기기 전에 끝난 호출은 토큰 칸 없이 `callSite`·`model` 만 갖는다. 예외는 그대로 다시
    올린다."""
    backend, model = sent_model(usage)
    sink: list[CallUsage] = []
    started = time.monotonic()
    failure: CallFailure | None = None
    try:
        yield replace(usage, usage_sink=sink)
    except BaseException as exc:
        failure = call_failure(exc, reported=bool(sink))
        raise
    finally:
        added = {
            "backend": backend,
            "durationMs": round((time.monotonic() - started) * 1000),
            "promptSetId": str(prompt_set_id),
            "stage": stage,
            "routeSource": None,
            "failure": failure,
        }
        bases = [reported.as_record() for reported in sink] or [{"callSite": usage.call_site, "model": model}]
        records.extend(base | added for base in bases)
