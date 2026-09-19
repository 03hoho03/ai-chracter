"""monitoring-techspec.md MT-5: 자가호스팅 Bugsink에는 서버측 스크러빙이 없다(§0-1-3) —
SDK 옵션이 유일한 방어선이다. 실제 `sentry_sdk.init()` 호출과 DSN 등 배포별 설정은 MT-4
(`main.py`/`core/config.py`)다. 이 모듈의 옵션 빌더는 `init()`을 직접 부르지 않는다 — 그래야
테스트가 전역 SDK 상태를 건드리지 않고 `sentry_sdk.Client(**build_sentry_options())`로
프로덕션과 같은 옵션을 재현해 검증할 수 있다(옵션이 테스트와 프로덕션에서 갈리면 테스트가
아무것도 보증하지 못한다).

`capture_dependency_failure`(MT-6)는 흡수된 장애(`logger.warning`)를 Bugsink 이벤트로도
승격하는 공통 지점이다 — 승격 대상 13곳이 같은 두 줄(로그는 유지 + 호출 한 줄)을 반복해서
헬퍼로 뺐다. 전역 `sentry_sdk.capture_exception`을 그대로 호출하므로 `init()`을 부르지 않고,
DSN이 비어 `init()`이 안 불린 환경(dev·테스트, MT-4)에서는 활성 클라이언트가 없어 no-op이다.
"""

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.google_genai import GoogleGenAIIntegration
from sentry_sdk.types import Event, Hint


def _strip_query_string(event: Event, hint: Hint) -> Event | None:
    """`send_default_pii=False`는 쿼리스트링을 지우지 않는다 — ASGI 통합의
    `_get_request_data()`는 `request.query_string`을 PII 게이트 없이 무조건 채운다(sentry-sdk
    2.69.1 `integrations/_asgi_common.py` 확인, `request.url`도 SDK/통합에 따라 물음표 뒤를
    포함할 수 있어 같이 자른다). 파라미터 이름으로 골라내지 않고 쿼리스트링 자체를 통째로
    버린다 — 어떤 파라미터가 민감한지 화이트리스트로 미리 다 알 수 없다. 그래서 이름과
    무관하게, 이 경로로 남는 민감 파라미터가 늘어도 코드 변경 없이 계속 덮인다 — 현재 걸리는
    지점은 최소 둘이다: `GET /auth/password-reset/validate?token=...`의 재설정 토큰(§0-1-9)과
    `GET /auth/google/callback?code=...&state=...`의 OAuth 인가 코드·state(`auth/router.py`
    `google_callback`/`get_google_profile`)."""
    request = event.get("request")
    if not isinstance(request, dict):
        return event
    url = request.get("url")
    if isinstance(url, str) and "?" in url:
        request["url"] = url.split("?", 1)[0]
    request.pop("query_string", None)
    return event


def build_sentry_options() -> dict[str, Any]:
    """`sentry_sdk.init(**build_sentry_options())`(MT-4) / 테스트의 `sentry_sdk.Client(**...)`가
    함께 쓰는 스크러빙 옵션(monitoring-techspec.md MT-5).

    - `max_request_body_size="never"`: JSON 요청 본문(채팅 메시지 원문)은 `send_default_pii`와
      무관하게 첨부된다 — 크기 게이트만 탄다(§0-1-4). `"never"`가 그 게이트를 항상 닫는 유일한
      값이다.
    - `include_local_variables=False`: 채팅 프롬프트·히스토리·비밀번호 재설정 링크·인증 코드가
      스택 프레임 지역변수로 산다(§0-1-7) — 임의 문자열이라 키 이름 매칭 스크럽으로는 원리적으로
      못 잡는다.
    - `send_default_pii=False`: IP(`x_forwarded_for`·`x_real_ip`·`ip_address`·`remote_addr`)·
      쿠키를 SDK `DEFAULT_PII_DENYLIST`로 거른다. **User-Agent와 요청 경로(`request.url`)는 이
      플래그와 무관하게 항상 붙는다** — ASGI 통합의 `_get_request_data()`가 헤더 딕셔너리를
      `_filter_headers()`로 거르는데, 그 차단 목록(`integrations/_wsgi_common.py`의
      `SENSITIVE_HEADERS`)에 User-Agent가 없고, `request.url`은 아예 게이트 없이 항상
      채워진다(sentry-sdk 2.69.1 소스로 확인).
    - `disabled_integrations=[GoogleGenAIIntegration]`: `google-genai`가 의존성에 있어 이 통합이
      auto-enabling 이고 `include_prompts` 기본값이 True라 프롬프트가 span에 실린다(§0-1-8).
      지금은 트레이싱이 꺼져 있어(`traces_sample_rate=0`) 전송되지 않지만, 그 안전은 "트레이싱을
      켜지 않는다"는 별도 결정에 기대는 간접 보증이라 명시적으로도 막는다.
    - `traces_sample_rate=0`: Bugsink가 트레이싱을 지원하지 않아 어차피 권장 설정이고, 위
      GenAI 통합 방어의 두 번째 축이다.
      ⚠️ 트레이싱을 켜려면(`traces_sample_rate>0`) **`before_send_transaction`을 먼저 만들어야
      한다** — `before_send`는 트랜잭션을 보지 않는다(이 저장소는 아직 트랜잭션을 만들지 않아
      지금은 걸지 않는다).
    - `before_send=_strip_query_string`: 위 옵션들이 못 막는 유일한 경로 — 비밀번호 재설정
      토큰이 쿼리스트링에 있다(§0-1-9).
    """
    return {
        "max_request_body_size": "never",
        "include_local_variables": False,
        "send_default_pii": False,
        "disabled_integrations": [GoogleGenAIIntegration],
        "traces_sample_rate": 0,
        "before_send": _strip_query_string,
    }


def capture_dependency_failure(exc: BaseException | None = None, *, dependency: str) -> None:
    """monitoring-techspec.md MT-6: 흡수(사용자 응답 유지 + `logger.warning`)는 그대로 두고
    Bugsink 이벤트로도 승격한다. `dependency` 태그(`clover`/`db`/`email`/`gemini`/
    `gemini_rate_limit`/`local_image`/`prompt_render`/`redis`/`s3`)로만 Bugsink에서 묶어 본다 —
    **태그·컨텍스트에는 이 리터럴 문자열 외에 아무것도 싣지 않는다.** 사용자 입력·프롬프트·
    이메일 주소는 호출부가 절대 넘기지 말 것(MT-6 설계 제약 1, PII 금지).

    이 목록은 호출부 실사용과 대조해 다시 썼다(clover-techspec.md CT-14). ⚠️ 리터럴
    `dependency="..."`만 grep하면 **`gemini`/`gemini_rate_limit`/`prompt_render` 셋을 놓친다** —
    그 셋은 `chat/router.py`의 `_llm_dependency_tag(exc)`가 계산해서 넘기므로 호출부 9곳에
    문자열로 나타나지 않는다.

    `exc`를 생략하면 `sentry_sdk.capture_exception`이 `sys.exc_info()`를 쓴다 — 호출부의
    `except` 절이 예외를 `as exc`로 바인딩하지 않은 경우(`prompt_set_cache.py`·
    `admin/prompts.py`)를 위한 것이다."""
    sentry_sdk.capture_exception(exc, tags={"dependency": dependency})
