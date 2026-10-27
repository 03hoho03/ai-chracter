"""소설 작업의 모델 호출 기록(`novel_jobs.llm_calls`) — 작업이 부른 호출마다 원소 하나를 메모리 목록에 모으고, 작업을 끝내는 전이가 그
목록을 같은 트랜잭션에서 작업 행에 쓴다. 원가 분석용이라 응답·API 스키마에 싣지 않는다.

**원소 꼴**: 공급자 구현이 남기는 사용량 칸(`CallUsage.as_record` — `callSite`·`model`·`promptTokens`·`cachedTokens`·
`cacheWriteTokens`·`outputTokens`·`thoughtsTokens`)에 이 모듈이 바깥에서 칸을 덧붙인다: `backend`(호출이 간 구현), `durationMs`(호출을
감싼 구간의 걸린 시간, 스트림은 다 받을 때까지), `promptSetId`(문안을 읽은 소설 세트 id), `stage`(작업 갈래, 경계 제안은 `boundary`,
묶음 재검사는 `recheck`), `routeSource`(배정 표를 읽는 단계만 — 그 해석의 출처, 나머지는 null), `failure`(호출 단위의 실패 사유, 정상
종료면 null). 사용량 칸 모양은 채팅 턴 기록과 같게 두어 같은 원가 함수로 친다 — 그래서 `llm/client.py` 의 세 이름은 고치지 않고
덧붙이기만 한다. 공급자가 사용량을 남기기 전에 끝난 호출(안전 차단·전송 오류·쿼터 소진·시간 상한 취소)은 토큰 칸 없이 `callSite`·
`model` 만 갖고, `model` 은 요청에 실은 id 다(라우터와 같은 해석에 Gemini 는 클라이언트가 고르는 소설화 모델, `sent_model`). 세트의 판
번호는 싣지 않는다 — 서빙 경로는 판 표를 읽지 않으므로(`tests/test_prompt_semver_boundary.py`), 판은 세트 id 로 판 표와 이어 읽는다.

`failure` 는 호출 단위만 담는다 — 잘림·빈 본문·차단·호출 실패·쿼터 소진·취소. 호출은 정상 종료했는데 소설 쪽 판정(거절문·형식·
최소 길이·구성안 검증·저장 때 낡음)이 실패한 것은 작업 행의 실패 사유가 이미 담으므로 원소에서는 비운다.

**쓰는 자리**: 성공은 각 저장 함수의 성공 전이(`transition_job`)와 같은 트랜잭션, 실패는 환불 함수(`billing.refund_job`)의 실패 전이와
같은 트랜잭션이다. 전이가 행을 받지 못하면(다른 경로가 먼저 끝냈거나 작업이 지워졌으면) 기록도 쓰이지 않는다. 묶음 재검사(동기
라우트)는 판정을 쓰는 트랜잭션에서 이미 끝난 작업 행에 덧붙인다. 만료 정리와 소설 삭제 환불은 호출 목록을 모르는 다른
프로세스·요청이라 칸을 건드리지 않는다(`[]` 그대로).

**받아들인 손실** — 아래 경우의 호출은 공급자에게 과금됐어도 작업 행에 남지 않아, 이 칸의 합계는 실제 원가보다 낮게 나온다.
- 작업을 돌리던 프로세스가 죽으면 메모리 목록이 함께 사라지고, 작업은 만료 정리가 `[]` 그대로 실패·환불한다.
- 연쇄 부모의 전체 시간 상한이 돌던 자식을 취소하면 자식의 목록은 쓰이지 않고 버려진다 — 자식 행은 부모 환불이 함께 실패로 끝내며
  칸은 `[]` 로 남는다. 부모 행에는 부모가 직접 부른 경계 제안만 남는다(자식 호출을 부모 목록에 모으지 않는다).
- 묶음 재검사는 판정을 쓰는 트랜잭션에서만 기록한다 — 호출 실패(503)와, 부르는 동안 글이나 묶음이 바뀐 갈래(409)는 작업 행을 쓰지
  않으므로 그 호출은 남지 않는다.
- 작업 행이 없는 호출(경계 모달의 제안, 노벨 심사)은 이 칸의 대상이 아니다."""

import asyncio
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Literal

from api.chat.prompt_routing import RouteSource
from api.llm.call_failures import classify_llm_failure
from api.llm.call_policy import BackendId
from api.llm.client import CallUsage, LLMCallContext, LLMClientError, LLMRateLimitError, structured_model
from api.llm.routing import resolve_backend
from api.novelize.job_variants import JobVariant

# 원소의 `stage` — 작업 갈래 하나에 호출 하나이고, 작업 갈래가 아닌 호출 둘은 따로 이름을 둔다.
CallStage = JobVariant | Literal["boundary", "recheck"]
CallFailure = Literal["truncated", "empty", "blocked", "llm_error", "rate_limited", "cancelled", "internal"]


def sent_model(usage: LLMCallContext) -> tuple[BackendId, str]:
    """그 호출이 가는 구현과 요청에 싣는 모델 id — 라우터와 같은 해석(`resolve_backend`)에, Gemini 는 클라이언트가 호출 위치마다 고르는
    모델(`structured_model`, 소설화 호출은 소설화 모델 설정)이다. 측정 덤프의 `callModel` 도 이 값이다."""
    backend, sent = resolve_backend(usage.call_site, usage.model, usage.call_model)
    return backend, structured_model(usage.call_site, sent) if backend == "gemini" else sent


def call_failure(exc: BaseException, *, reported: bool) -> CallFailure | None:
    """감싼 구간에서 나온 예외를 호출 단위 실패 사유로 가른다. 소설 실행 경로는 공급자 예외를 작업 실패 예외로 감싸 올리므로(`from
    exc`) 원인까지 본다. 취소는 작업 시간 상한이 진행 중 호출을 끊은 것이다. 공급자 예외가 아닌데 사용량이 남았으면 호출은 정상
    종료했고 그 뒤 판정이 실패한 것이라 비우고, 사용량도 없으면 호출 자체가 예상하지 못한 오류로 끝난 것이다."""
    if isinstance(exc, asyncio.CancelledError | TimeoutError):
        return "cancelled"
    cause = exc if isinstance(exc, LLMClientError) else exc.__cause__
    if isinstance(cause, LLMRateLimitError):
        return "rate_limited"
    if isinstance(cause, LLMClientError):
        return classify_llm_failure(cause)
    return None if reported else "internal"


@contextmanager
def recorded_call(
    records: list[dict[str, Any]],
    usage: LLMCallContext,
    *,
    stage: CallStage,
    prompt_set_id: uuid.UUID | None,
    route_source: RouteSource | None,
) -> Iterator[LLMCallContext]:
    """모델 호출 하나를 감싸 끝날 때(성공·실패·취소 모두) `records` 에 원소를 더한다. 감싼 구간에는 사용량을 모을 목록을 실은 호출
    문맥을 내준다 — 그 문맥으로 불러야 공급자 구현이 사용량을 남긴다. 목록은 비교·해시에서 빠지는 칸이라 호출 문맥의 동등성은 그대로다.
    구간 안에서 호출이 사용량을 여럿 남기면 원소도 여럿이다. 예외는 그대로 다시 올린다."""
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
            "promptSetId": str(prompt_set_id) if prompt_set_id is not None else None,
            "stage": stage,
            "routeSource": route_source,
            "failure": failure,
        }
        bases = [reported.as_record() for reported in sink] or [{"callSite": usage.call_site, "model": model}]
        records.extend(base | added for base in bases)
