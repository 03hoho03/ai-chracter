"""소설 작업의 모델 호출 실패를 실패 사유 코드로 가르고, 경고 로그에 붙일 원인을 적는다.

소설 작업 실행(`novelize/runner.py`)의 호출 다섯 곳(장 생성 스트림, 문단 수정·여러 문단 수정·전체 구성안·장면 구성안 구조화
호출)이 같은 갈래로 실패를 가른다. 채팅 턴과 기억 추출은 이 파일을 쓰지 않는다 — 그쪽 실패 처리는 따로 정해져 있고, 소설 쪽
사유 코드를 고치는 변경이 채팅까지 움직이지 않게 한다(테스트가 고정한다). 로그는 이 모듈이 아니라 부르는 쪽 로거로 남긴다 —
운영 로그의 레코드 이름이 실행 모듈 그대로여야 한다."""

from typing import Literal

import anthropic
from google.genai import errors as genai_errors

from api.llm.client import LLMClientError, LLMEmptyResponseError, LLMPolicyViolationError, LLMTruncatedError

LLMFailureCode = Literal["truncated", "empty", "blocked", "llm_error"]


def classify_llm_failure(exc: LLMClientError) -> LLMFailureCode:
    """잘림·빈 본문·안전 차단은 제 사유, 나머지(쿼터 소진 포함)는 호출 실패. 셋 다 `LLMClientError` 의 하위라 보는 순서가 뜻을
    가진다 — 잘림 → 빈 본문 → 차단."""
    if isinstance(exc, LLMTruncatedError):
        return "truncated"
    if isinstance(exc, LLMEmptyResponseError):
        return "empty"
    if isinstance(exc, LLMPolicyViolationError):
        return "blocked"
    return "llm_error"


def describe_llm_failure(exc: LLMClientError) -> str:
    """실패한 모델 호출 경고에 붙일 원인 — 실패 예외 종류, 원인 예외 종류, HTTP 상태, 공급자 요청 id(알 수 있을 때, 없으면 "없음").
    과부하(529)·서버 오류·연결 실패·시간 초과를 로그로 가르고 공급자에 문의할 요청 id 를 남기려는 것이다. 예외 글은 넣지 않는다 —
    공급자 오류 글에는 오류 응답 본문이 통째로 실리고, 그 안에 요청 내용 일부가 섞일 수 있다.

    Claude 는 SDK 상태 오류가 상태 코드와 헤더를 들고 온다(직접 API 는 `request-id`, Bedrock 은 `x-amzn-requestid`). 스트림을 흘리던
    도중의 오류(장 생성의 과부하·스로틀)는 응답 상태가 이미 200 이라 상태 코드로는 가를 수 없어, 오류 본문의 오류 종류(직접 API 의
    `overloaded_error`, Bedrock 의 `ThrottlingException` 같은 고정 이름)도 남긴다 — 같은 본문의 메시지 글은 넣지 않는다. 여기서는 Gemini
    SDK 오류의 상태 코드만 읽고 요청 id 는 남기지 않는다."""
    cause = exc.__cause__
    status: int | None = None
    request_id: str | None = None
    kind: str | None = None
    if isinstance(cause, anthropic.APIStatusError):
        status = cause.status_code
        request_id = cause.request_id or cause.response.headers.get("x-amzn-requestid")
        body = cause.body
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict) and isinstance(error.get("type"), str):
            kind = error["type"][:64]
    elif isinstance(cause, genai_errors.APIError):
        status = cause.code
    cause_name = "없음" if cause is None else type(cause).__name__
    return (
        f"{type(exc).__name__} 원인={cause_name} 상태={'없음' if status is None else status} "
        f"종류={kind or '없음'} 요청={request_id or '없음'}"
    )
