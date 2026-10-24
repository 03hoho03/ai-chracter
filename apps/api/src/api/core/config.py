import json
import uuid
from typing import Annotated, Literal, get_args

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from api.core.field_crypto import FieldKeyring

# 둘 다 `settings` 를 찾지 않는 모듈이다(`backends` 는 `call_policy` 만, `call_policy` 는 아무 `api` 모듈도 import 하지 않는다) — 아래 `settings = Settings()` 가 이 모듈을 import 하는 도중에 돌므로,
# 기동 검증이 읽는 표는 `settings` 를 찾지 않는 모듈에 있어야 한다.
from api.llm import backends
from api.llm.backends import PromptSetModelId
from api.llm.call_policy import BackendId, LLMCallSite

# Anthropic API 의 사고 깊이(`output_config.effort`). API 가 받는 값만 둔다 — 오타가 첫 호출의 거부가 아니라 기동 거부가 되게.
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
# 기억 사용 범위(`memory_model_scope`)가 받는 레인 — 기억 기능이 있는 대화 레인 둘뿐이다.
MemoryScopeLane = Literal["story", "character"]


class Settings(BaseSettings):
    # 설정 검증 오류 메시지에 입력값을 싣지 않는다 — 비밀 설정(키·토큰)이 형식 오류로 기동 로그에 찍히지 않게.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    # 비밀 필드는 `Field(repr=False)`로 repr에서 뺀다. 어떤 필드가 비밀인지는 이 파일에서
    # `repr=False` 를 찾으면 나온다 — 개수·목록을 여기 적어 두면 필드를 더할 때 이 주석만 낡는다.
    # repr에서 빼는 이유는 `monkeypatch.setattr(settings, "오타", ...)`가 내는
    # `AttributeError(f"{target!r} has no attribute ...")` 메시지에 전 필드 repr이 실려 비밀이
    # 평문으로 찍히기 때문이다. 값이 traceback이 아니라 **예외 메시지 자체**에 있어 pytest
    # `--tb` 옵션으로는 못 막는다. 타입은 `str` 그대로다(`SecretStr` 전환은 별건).
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_character_chat",
        repr=False,
    )
    redis_url: str = "redis://localhost:6379/0"

    # 워커(프로세스)마다 풀이 따로 생긴다. 워커를 늘리면 워커 수 × (`db_pool_size` + `db_max_overflow`)
    # 가 Postgres 연결 상한(`max_connections`)을 넘지 않게 줄인다 — 크론·백업·관리 접속 몫을 남겨야 한다.
    # 기본값은 이 설정이 생기기 전에 앱이 쓰던 SQLAlchemy 기본값과 같다. `db_pool_size` 가 0 이면
    # SQLAlchemy 는 상한 없음으로 읽으므로 1 이상만 받는다.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    # 풀이 다 찼을 때 연결을 기다리는 초. 넘기면 그 요청이 500 이다.
    db_pool_timeout: float = Field(default=30, gt=0)
    # 이미지 디코드·블러·변형 생성을 한 워커(프로세스)에서 동시에 몇 건까지 돌릴지. 픽셀 상한 그림은 RGBA 한 장만
    # 약 36MB 이고 블러·축소 복사본이 더 붙으므로, 워커 수 × 이 값 × 건당 최대 메모리가 VM 가용 메모리의 절반을
    # 넘지 않게 정한다. 기본값은 이 설정이 생기기 전 상수로 박혀 있던 값과 같다. 0 이면 세마포어가 아무도 들여보내지
    # 않아 업로드가 영원히 기다리므로 1 이상만 받는다.
    image_decode_concurrency: int = Field(default=3, ge=1)

    # 프로덕션은 스키마 전수 노출을 막는다 — 안전한
    # 기본값(닫힘)이어야 env 설정 없이 배포해도 닫힌 채로 뜬다. 로컬 개발만 True로 켠다.
    expose_api_docs: bool = False

    session_cookie_name: str = "session_id"
    session_ttl_seconds: int = 60 * 60 * 24 * 7
    # Secure requires HTTPS; browsers drop the cookie on local http dev servers, so
    # this defaults to False and must be overridden to True in any deployed env.
    session_cookie_secure: bool = False
    # Default "lax" keeps local dev (same-site) working. A cross-site deploy where the
    # API and the SPA live on different registrable domains (e.g. *.run.app vs
    # *.pages.dev) must set this to "none" (with session_cookie_secure=True) or the
    # browser won't attach the session cookie to the SPA's cross-site XHR at all.
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Admin sessions use a separate cookie name (and,
    # in api/admin/session.py, a separate Redis key prefix) so they never collide
    # with a regular user's session cookie.
    admin_session_cookie_name: str = "admin_session_id"

    # env 에서는 쉼표 구분(`https://a,https://b`)과 JSON 배열(`["https://a","https://b"]`) 둘 다 받는다.
    # 쉼표 구분이 기본 표기다 — env 파일은 따옴표 없는 값만 쓰는데(DEPLOY.md 의 env 파일 형식 절), JSON 배열은
    # 큰따옴표가 필요하고 `uv run --env-file` 이 그 따옴표를 벗겨 JSON 이 깨진다. JSON 배열은 예전 운영 값과의
    # 호환으로만 남긴다. `NoDecode` 는 pydantic-settings 가 list 필드를 JSON 으로 먼저 디코드하는 단계를 끄고
    # 아래 검증기가 문자열을 직접 받게 한다.
    cors_allow_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:5174"]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """env 문자열을 리스트로 바꾼다. `[` 로 시작하면 JSON 배열, 아니면 쉼표 구분이다. 항목 앞뒤 공백은 지우고
        빈 항목은 버린다. 남는 항목이 없으면 오류다 — 빈 값으로 기동하면 운영 FE 요청이 전부 CORS 로 막힌다."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        origins = [item.strip() for item in text.split(",") if item.strip()]
        if not origins:
            raise ValueError("CORS_ALLOW_ORIGINS 가 비어 있다 — 쉼표로 구분한 오리진을 하나 이상 넣는다")
        return origins

    aws_region: str = "ap-northeast-2"
    s3_bucket_name: str = "ai-character-chat-assets-dev"
    s3_presigned_url_expires_seconds: int = 900
    # Required in every environment: the Cloudflare R2 endpoint in production, moto
    # (e.g. `uv run moto_server`) for local dev/tests. `generate_presigned_get_url`
    # signs path-style URLs against it and raises when it is unset.
    s3_endpoint_url: str | None = None

    # No requirement fixes this TTL (only the 60s resend cooldown was specified) —
    # a reasonable default for how long an issued email verification code stays usable.
    email_verification_code_ttl_seconds: int = 60 * 15
    email_verification_resend_cooldown_seconds: int = 60

    # 탈퇴 시 users.email이 자리표시자로 바뀌므로,
    # 재가입 차단은 이 키로 만든 HMAC-SHA256(withdrawn_emails.email_hmac)을 조회해서 한다.
    # 키를 잃거나(배포 환경마다 값이 달라지는 등) 바꾸면 과거에 적립한 해시와 새 조회의 해시가
    # 어긋나 재가입 차단이 조용히 멈춘다(모든 조회가 미스) — DEPLOY.md에 남긴다.
    withdrawn_email_hmac_key: str = Field(default="", repr=False)
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    # Used to build the redirect_uri sent to Google and the /auth/google/callback
    # Location header target after a successful/pending login.
    api_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"
    google_oauth_state_ttl_seconds: int = 60 * 10
    # Same TTL rationale as email_verification_code_ttl_seconds: how long a new
    # Google user has to finish POST /auth/onboarding/google before retrying.
    google_pending_signup_ttl_seconds: int = 60 * 15
    # 카카오 로그인. REST API 키는 인가 URL 에 그대로 실리는 공개 식별자라 비밀이 아니고,
    # 클라이언트 시크릿(토큰 교환에 필수)과 어드민 키(연결 끊기 API 호출과 연결 해제 웹훅의
    # 인증 헤더 대조)는 비밀이다. REST API 키나 시크릿이 비면 로그인 시작이 카카오로 가지 않고
    # 로그인 화면 오류로 돌아온다(로컬·CI 처럼 키가 없는 환경에서 카카오 오류 화면에 갇히지 않게).
    kakao_rest_api_key: str = ""
    kakao_client_secret: str = Field(default="", repr=False)
    kakao_admin_key: str = Field(default="", repr=False)
    # 구글과 같은 값이고 이유도 같다(인가 왕복 시간, 온보딩 작성 시간).
    kakao_oauth_state_ttl_seconds: int = 60 * 10
    kakao_pending_signup_ttl_seconds: int = 60 * 15

    # 포트원(결제·휴대폰 본인인증). 상점 id 와 두 채널키는 브라우저 SDK 에도 실리는 공개 식별자라 비밀이 아니다 — 웹은
    # 이 값을 따로 갖지 않고 주문·인증 시작 응답으로 받는다. API 비밀(조회·취소 호출)과 웹훅 비밀(서명 검증)은 비밀이다.
    # 값이 비면 기동을 막지 않고 그 기능이 꺼진다(`payments/config.py` 의 판정 함수들).
    portone_store_id: str = ""
    portone_payment_channel_key: str = ""
    portone_identity_channel_key: str = ""
    portone_api_secret: str = Field(default="", repr=False)
    portone_webhook_secret: str = Field(default="", repr=False)
    # 본인인증 CI 를 HMAC 으로 바꿔 저장할 때 쓰는 키. 탈퇴 이메일 키와 따로 둔다 — 이 해시는 살아 있는 계정끼리 같은
    # 사람인지를 인증 때마다 대조하는 데 쓰여, 키가 바뀌면 기존 인증자 전원과 대조가 어긋나 같은 사람의 중복 인증이
    # 열린다. 이메일 키를 (유출 등으로) 바꿀 때 그 사고가 이쪽으로 번지지 않게 가른다. **한번 정하면 바꾸지 않는다.**
    identity_ci_hmac_key: str = Field(default="", repr=False)
    # 결제와 본인인증 게이트의 스위치. 코드 기본값이 닫힘이라 env 없이 배포하면 닫힌 채 뜬다.
    payments_enabled: bool = False
    identity_gate_enabled: bool = False
    # 결제·환불 완료를 알리는 디스코드 웹훅 주소. 비면 알림을 건너뛴다. 주소 자체가 그 채널에 글을 쓸 권한이라 비밀이다.
    payment_discord_webhook_url: str = Field(default="", repr=False)

    # 크리에이터 정산 스위치. 켜도 본인인증 설정이 없으면 꺼진 것으로 본다(`creator_payout/config.py`) — 신청 자격이 본인인증과
    # 만 19세라 인증할 수 없는 환경에서는 아무도 신청할 수 없다. 어드민 신청 처리는 이 값과 무관하게 열려 있다.
    creator_payout_enabled: bool = False
    # 크리에이터 정산. 비율은 다른 회원이 작품에서 쓴 유료 클로버의 공급가 중 작가 몫(bps, 500 = 5%)이고, 확정할 때마다
    # 확정 행에 그 값을 남긴다. 소급 일수는 첫 승인 때 거슬러 세는 기간이다 — 0 이면 소급 구간이 비어 확정 행의 구간 CHECK
    # 에 걸리므로 1 이상만 받는다. 범위 밖이면 기동하지 않는다(잘못된 비율로 돈을 계산하는 것보다 뜨지 않는 편이 낫다).
    creator_payout_rate_bps: int = Field(default=500, ge=1, le=10_000)
    creator_payout_retro_days: int = Field(default=90, ge=1)
    # 지급을 신청할 수 있는 최소 확정 잔액(원). 탈퇴하려는 회원은 이보다 적어도 신청할 수 있다.
    creator_payout_minimum_krw: int = Field(default=10_000, ge=1)
    # 크리에이터 지급 정보(실명·주민등록번호·계좌번호) 암호화 키 목록 `kid:base64url(32바이트)[,kid:…]`. 맨 앞 키로
    # 암호화하고 모든 키로 복호화한다(`core/field_crypto.py`). 비면 정산이 꺼진다. 키를 잃으면 지급 정보를 되살릴 수
    # 없다 — 보관·회전 절차는 DEPLOY.md. 형식이 틀리면 기동하지 않는다.
    creator_payout_encryption_keys: str = Field(default="", repr=False)

    @field_validator(
        "creator_payout_enabled",
        "creator_payout_rate_bps",
        "creator_payout_retro_days",
        "creator_payout_minimum_krw",
        mode="before",
    )
    @classmethod
    def _empty_creator_payout_value_is_default(cls, value: object, info: ValidationInfo) -> object:
        """env 에 값만 비운 줄(`KEY=`)이 남아도 기동하게 빈 값은 코드 기본값으로 읽는다 — 정수·불리언 파싱은 빈
        문자열에서 실패한다."""
        if isinstance(value, str) and not value.strip():
            assert info.field_name is not None
            return cls.model_fields[info.field_name].default
        return value

    @field_validator("creator_payout_encryption_keys")
    @classmethod
    def _creator_payout_encryption_keys_are_well_formed(cls, value: str) -> str:
        if value:
            FieldKeyring.parse(value)
        return value

    # Password reset tokens expire 1 hour after issuance.
    password_reset_token_ttl_seconds: int = 60 * 60

    # Gemini 2.5 LLMClient 구현체.
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model_name: str = "gemini-2.5-flash"
    # ⚠️ 아래 실측은 전부 **현행 기본 모델이 아닌 모델**(gemini-3.5-flash·flash-lite)에서 나왔다
    # — 현행 기본값은 바로 위 `gemini_model_name`(gemini-2.5-flash)이다. 근거로는 쓰되 현행
    # 모델에서 재현된 값은 아니다.
    # generate()(채팅 생성)의 출력 상한 — 폭주 방지용이지 길이 연출 수단이 아니다. 주의:
    # 이 상한은 응답만이 아니라 **사고(thinking) 토큰과 응답이 나눠 쓰는 예산**이다.
    # 옛 기본값 2048의 근거였던 "실측 90턴 최대 응답 1635자"는 사고를 안 하는 flash-lite
    # 계열 실측이라 사고형 모델에는 성립하지 않는다 — gemini-3.5-flash 는 같은 프롬프트에
    # 사고가 1185토큰을 먼저 쓰고 응답이 859토큰째에 MAX_TOKENS 로 잘렸고(실측 8턴 중 5턴),
    # 8192에서는 절단이 0이 됐다.
    # 값을 올려도 응답이 길어지지는 않는다 — 상한은 목표가 아니라 천장이라, flash-lite 로
    # 2048~65536 을 훑어도 전부 STOP 이고 길이는 453~922토큰 사이를 무작위로 오갈 뿐
    # 상한과 상관이 없었다(2026-08-14 실측). 그래서 올리는 쪽의 비용은 사실상 없다.
    # 무제한으로 두지 않는 이유는 하나뿐이다 — 모델이 루프에 빠지면 그 토큰만큼 실제로
    # 과금되므로, 모델 자체 한도(65,536)보다 한참 낮은 값이 폭주 방지선 역할을 해야 한다.
    gemini_max_output_tokens: int = 8192
    # 사고(thinking) 예산: None = thinking_config 를 아예 넘기지 않음(모델 기본 사고 동작),
    # 0 = 사고 끔, 양수 = 그 토큰까지 허용. 세 상태가 서로 다른 동작이라 bool 로 합치지
    # 않는다. ⚠️ gemini-3.5-flash-lite 는 0 을 400 으로 거부했다(2026-10-02, 구조화 호출 실측) — 그 모델에
    # 0 을 주면 생성이 실패할 수 있다.
    gemini_thinking_budget: int | None = None
    # 구조화 호출 중 판정(스탯·엔딩·그림 매칭)과 발행 심사만 다른 모델로 돌리는 스위치. 판정은 종류마다 따로
    # 옮길 수 있게 셋으로 나눈다. 어느 호출이 어느 종류인지는 `llm/call_policy.py` 의 호출 정책 표가 정한다.
    # None(또는 빈 문자열)이면 `gemini_model_name` 을 그대로 쓴다 — 넷 다 기본값이면 지금 동작과 같고, 되돌리려면
    # env 줄을 지우고 재기동한다. 사고 설정은 이 호출들에 넘기지 않는다(`llm/gemini.py` 의 `generate_structured`).
    gemini_stat_judgment_model_name: str | None = None
    gemini_ending_judgment_model_name: str | None = None
    gemini_image_judgment_model_name: str | None = None
    gemini_publish_filter_model_name: str | None = None
    # Gemini 호출 하나를 기다리는 상한(ms). 호출마다 그 종류에 맞는 값을 요청에 싣는다(`llm/client.py` 의
    # `request_timeout_ms`). SDK 의 httpx 경로에서는 연결·읽기·쓰기 단계마다의 상한이고 같은 값이 서버 기한 헤더로도
    # 나간다 — 비스트리밍인 판정·요약·발행 심사는 응답이 끝나야 바이트가 오므로 사실상 호출 전체의 상한이고, 스트리밍
    # 생성은 "다음 청크까지"의 상한이다. 재시도는 하지 않는다 — 판정은 실패를 흡수하도록 짜여 있고 재시도는 턴 길이를
    # 곱으로 늘린다. 시간 초과는 다른 네트워크 실패와 같은 `LLMClientError` 로 올라가 기존 실패 경로를 탄다.
    # 생성: 운영에서 잰 가장 긴 턴(약 21초)의 두 배쯤.
    gemini_generate_timeout_ms: int = 45_000
    # 판정(스탯·엔딩·그림 매칭, 미리보기 포함): 출력이 수십 토큰이라 정상 지연이 1~2초다. 판정 하나가 멈춰도 그 턴이
    # 생성 상한 + 이 값 근처에서 끝나게 짧게 끊는다. 판정 윈도우를 끄면 긴 방의 판정 입력이 대화 전체로 커져 이 값에
    # 걸릴 수 있다.
    gemini_judgment_timeout_ms: int = 20_000
    # 기억 요약 접기: 턴이 끝난 뒤 background 로 돌아 사용자가 기다리지 않고, 실패는 백오프 뒤 다음 턴에 다시 한다.
    gemini_memory_summary_timeout_ms: int = 60_000
    # 발행 심사: 작가가 기다리는 멀티모달 호출이라 이미지 수만큼 길어진다. 시간 초과는 거부가 아니라 "잠시 뒤 다시
    # 발행"(503)으로 돌아가지만, 시간당 심사 횟수는 호출 앞에서 세므로 그 한 번을 쓴다.
    gemini_publish_filter_timeout_ms: int = 60_000
    # 클라이언트 기본값 — 요청 단위 값 없이 나가는 호출이 생겨도 무제한으로 기다리지 않게 하는 안전망.
    gemini_client_timeout_ms: int = 60_000

    # 소설화(대화를 장편 소설의 장으로 옮겨 쓰기). 장 생성과 문단 수정만 이 모델·출력 상한·사고 설정을 쓰고, 장 경계
    # 제안은 턴 번호 몇 개를 고르는 판정이라 `gemini_model_name` 으로 간다 — 어느 호출이 어느 쪽인지는 `llm/call_policy.py`
    # 의 호출 정책 표가 정한다. 모델명이 비면 `gemini_model_name` 으로 돈다.
    # 기본 모델은 같은 장을 세 후보 모델로 써 본 비교에서 골랐다. 모델 이름을 가리고 매긴 1위 횟수는 가장 많이 받은
    # 후보와 비슷했고(장만 보면 2 대 2, 문단 AI 수정까지 8건이면 3 대 4), 장당 원가는 다음으로 싼 후보의 약 절반,
    # 지연도 가장 짧았으며, 원문 응답 끝의 상태 표를 장 본문에 옮겨 적은 일이 없었다. 시험한 장이 다섯 개뿐이라
    # 원가는 운영에서 다시 본다.
    gemini_novelize_model_name: str = "gemini-3.8-flash"
    # 사고 토큰과 본문이 나눠 쓰는 예산이다(위 `gemini_max_output_tokens` 주석). 장 하나는 수천 자에 사고 토큰이 본문보다
    # 많이 붙어 채팅 상한으로는 잘린다. 여기서 잘린 장은 실패로 끝나고 환불되므로 낮게 잡으면 원가만 버린다.
    # 시험에서 기본 모델이 한 장에 쓴 출력·사고 토큰 합은 보고된 값으로 많아야 약 7천이었고(원문 21턴 장), 비교한 다른
    # 모델은 약 2만 3천까지 썼다. 장이 길어지거나 사고가 길게 붙는 날에도 잘리지 않게 그 몇 배인 이 값을 그대로 둔다.
    gemini_novelize_max_output_tokens: int = 32_768
    # 사고 설정. 둘 다 None 이면 thinking_config 를 넘기지 않는다(모델 기본 사고 동작). 정한 것만 넘긴다 — 예산은
    # 위 `gemini_thinking_budget` 과 같은 뜻이고, 수준은 사고형 모델이 받는 단계 이름이다. 기본 모델의 품질·원가는
    # 사고 설정 없이(모델 기본) 잰 것이라 기본값도 정하지 않음으로 둔다. 이 모델은 가장 낮은 사고 수준(MINIMAL)을 받지
    # 않는다.
    gemini_novelize_thinking_budget: int | None = None
    gemini_novelize_thinking_level: Literal["MINIMAL", "LOW", "MEDIUM", "HIGH"] | None = None
    # 소설화 호출 상한(ms). 백그라운드 작업이라 Cloudflare 응답 상한(100초)과 무관하다. 장 생성은 스트리밍이라 "다음
    # 청크까지"의 상한이고, 문단 수정·경계 제안은 비스트리밍이라 호출 전체의 상한이다. 경계 제안은 사용자가 화면에서
    # 기다리므로 짧게 끊는다. 시험에서 기본 모델은 장 하나를 길어야 31초, 문단 수정을 11초 안에 끝냈다. 이 값들은 호출이
    # 멈췄을 때만 걸리는 상한이라 줄여도 정상 호출은 빨라지지 않고, 느린 날의 정상 호출을 실패·환불로 바꿀 위험만 늘어
    # 그대로 둔다.
    gemini_novelize_chapter_timeout_ms: int = 300_000
    gemini_novelize_revise_timeout_ms: int = 120_000
    gemini_novelize_boundary_timeout_ms: int = 30_000
    # 여러 문단 수정의 묶음 재검사. 경계 제안처럼 사용자가 화면에서 기다리는 짧은 판정이라 같은 값으로 짧게 끊는다.
    gemini_novelize_recheck_timeout_ms: int = 30_000

    # 상위 모델(AWS Bedrock 의 Claude). 채팅 턴 생성(측정용 리플레이 포함)과 소설 장 생성만 이 모델로 갈 수 있고 나머지 호출은 Gemini 다.
    # 🔴 env 이름을 `AWS_` 로 시작하지 않는다 — 그 이름들은 R2 용이고 boto3 가 프로세스 env 에서 직접 읽는다. 자격은 Bedrock
    # 호출만 허용한 전용 IAM 사용자 키를 여기서 SDK 에 명시로 넘긴다(`llm/bedrock.py`). 키나 리전이 빈 채로 SDK 에 가면 기본
    # 자격 체인이 R2 키로 서명하거나 R2 리전(`auto`)으로 엔드포인트를 만들어서, 아래 스위치가 켜져 있으면 셋이 다 있어야 기동한다.
    bedrock_access_key_id: str = Field(default="", repr=False)
    bedrock_secret_access_key: str = Field(default="", repr=False)
    bedrock_region: str = "ap-northeast-2"
    # 실제 모델 id. 서울 출발 호출은 global 교차 리전 프로필만 열려 있다. 새 버전으로 옮길 때 이 값만 바꾸면 방·작업에 저장된
    # 모델 값(`sonnet`·`opus`)은 그대로다 — 단가표(`llm/pricing.py`)에 없는 id 면 어드민 원가가 "단가 없음"이 된다.
    bedrock_sonnet_model_id: str = "global.anthropic.claude-sonnet-4-6"
    bedrock_opus_model_id: str = "global.anthropic.claude-opus-4-6-v1"
    # 판정 전용 모델(Claude Haiku 4.5). 판정·요약 모델 설정이 `haiku` 일 때만 쓰인다.
    bedrock_haiku_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    # 요청 타임아웃(ms). SDK 가 httpx 계열이라 스트리밍에서는 Gemini 와 같이 "다음 청크까지"의 상한이고 호출 전체의 상한이
    # 아니다. 채팅은 Gemini 생성 상한과 같은 값, 장은 Gemini 장 생성 상한과 같은 값이다. 재시도는 하지 않는다.
    bedrock_chat_timeout_ms: int = 45_000
    bedrock_chapter_timeout_ms: int = 300_000
    # 출력 상한. 사고를 끄므로 응답만 쓰는 예산이다. 채팅은 같은 방의 같은 입력으로 Sonnet 을 돌려 본 비교에서 쓴 값이고,
    # 장은 Gemini 소설화 상한과 같은 값이다. Bedrock 은 요청마다 입력 + 이 출력 상한 전체를 분당 토큰 쿼터에서 먼저 잡고
    # (출력 토큰은 모델에 따라 몇 배로 센다), 무작정 올리면 동시 요청이 스로틀된다. 장 상한이 채팅의 8배라 장 하나가 채팅
    # 턴 여럿만큼 쿼터를 잡는다. 상위 모델을 켜기 전에 Service Quotas 의 교차 리전 TPM 과 그 모델의 출력 배수로 동시 장
    # 몇 개가 들어가는지 계산해 본다.
    bedrock_chat_max_tokens: int = 4096
    bedrock_chapter_max_tokens: int = 32_768
    # 상위 모델을 Anthropic API 로 직접 보낼 때의 설정(`llm/anthropic_api.py`). 아래 배정(`LLM_CALL_SITE_BACKENDS`)이 호출을
    # 이 구현으로 옮길 때만 쓰이고, 배정이 없으면 상위 모델은 위 Bedrock 으로 간다. 키의 env 이름을 SDK 가 스스로 읽는
    # `ANTHROPIC_API_KEY` 와 나눈다(Bedrock 키가 `AWS_*` 를 피한 것과 같은 이유) — 배정이 경로를 옮기는데 키가 비면 기동하지
    # 않는다(`llm/backends.py` 의 `assignment_errors`).
    anthropic_direct_api_key: str = Field(default="", repr=False)
    # 실제 모델 id. 같은 `opus`·`sonnet` 이라도 Bedrock 쪽 id 와 버전이 다르다. 화면의 모델 이름(`llm/chat_models.py`)은
    # 운영이 실제로 부르는 쪽을 따르고, 운영은 배정으로 상위 모델을 이 구현에 보내므로 지금은 이 쪽 버전이다.
    anthropic_sonnet_model_id: str = "claude-sonnet-5-5"
    anthropic_opus_model_id: str = "claude-opus-5-5"
    # 판정 전용 모델(Claude Haiku 5.5). 판정·요약 모델 설정이 `haiku` 이고 배정이 그 호출을 이 구현으로 옮길 때만 쓰인다.
    # 위 Bedrock 쪽은 Haiku 4.5 그대로다 — 같은 `haiku` 라도 구현에 따라 버전이 다르다. 판정 요청의 사고·깊이 규칙은 이
    # 값(실제 모델 id)으로 가른다(`llm/anthropic_api.py`).
    anthropic_haiku_model_id: str = "claude-haiku-5-5"
    # 요청 타임아웃(ms). Bedrock 과 같은 값이고 같은 뜻("다음 청크까지")이다.
    anthropic_chat_timeout_ms: int = 45_000
    anthropic_chapter_timeout_ms: int = 300_000
    # 출력 상한. 이 경로의 모델은 사고를 끌 수 없고 사고 토큰이 이 상한 안에 들어, Bedrock 상한(사고 끔)을 그대로 쓰면 사고가
    # 상한을 다 써 본문 없이 끝날 수 있다. 상한이지 과금량이 아니다 — 쓰지 않은 몫은 과금되지 않는다.
    anthropic_chat_max_tokens: int = 16_000
    anthropic_chapter_max_tokens: int = 64_000
    # 사고 깊이. 채팅 턴(다시 생성 포함) / 소설 장. 모델의 기본값에 맡기지 않고 늘 보낸다.
    anthropic_chat_effort: ClaudeEffort = "low"
    anthropic_chapter_effort: ClaudeEffort = "medium"
    # 판정·요약(구조화 호출)의 사고 깊이. 채팅 생성 깊이와 나눈다 — 함께 쓰면 채팅 깊이를 xhigh 로 올리는 순간, 사고를 끈
    # Haiku 5.x 판정(사고를 끈 요청은 깊이를 high 까지만 받는다)이 전부 거부된다. 기본값이 채팅 기본값과 같아 두 깊이
    # env(ANTHROPIC_CHAT_EFFORT·ANTHROPIC_STRUCTURED_EFFORT)를 모두 두지 않으면 Opus·Sonnet 판정 요청은 이전과 같다.
    anthropic_structured_effort: ClaudeEffort = "low"
    # 상위 모델 스위치 — 채팅과 소설화에 하나씩(기본 닫힘). 채팅은 이 스위치 하나로 로그인 회원 전원에게 열린다. 소설은
    # 허용 가능 계정 명단도 두며 뜻은 소설화 스위치·명단과 같다(명단에서 빼고 재기동하면 허용 행이 있어도 막힘). 소설 장의
    # 상위 모델은 소설화 자체 허용도 함께 있어야 쓸 수 있다.
    chat_premium_models_enabled: bool = False
    novelize_premium_models_enabled: bool = False
    novelize_premium_model_allowlist: Annotated[list[uuid.UUID], NoDecode] = []
    # 호출 위치마다 공급자 구현을 배정한다(`call_site:backend` 를 쉼표로 이은 목록, 따옴표 없이). 비면 배정 없음 — 모델의
    # 기본 구현으로 간다. 배정은 그 구현이 그 모델을 서비스할 때만 따르고(`llm/backends.py` 의 `pick_backend`), 따를 수 없는
    # 배정은 아래 기동 검증이 거부한다. 호출 위치·구현 이름은 대소문자까지 정확해야 한다.
    llm_call_site_backends: Annotated[dict[LLMCallSite, BackendId], NoDecode] = {}
    # 판정 종류(스탯·엔딩·그림 매칭)와 기억 요약마다 쓰는 모델 — 값은 문안 체인의 모델 id(`gemini`·`sonnet`·`opus`·판정 전용
    # `haiku`)이고, 판정은 그 모델의 활성 프롬프트 세트로 렌더된다. 방의 모델과 무관하다. 기본값 `gemini` 면 지금 동작 그대로이고,
    # 그때 실제 Gemini 모델은 위 `gemini_*_judgment_model_name` 이 고른다. 그 모델을 어느 구현이 서비스할지는 위 배정이 정하고,
    # 배정이 없으면 모델의 기본 구현이다(`haiku`·`sonnet`·`opus` → Bedrock). 배정이 그 모델을 서비스하지 않거나 가는 구현의
    # 자격이 비면 기동하지 않는다. 되돌리려면 env 줄을 지우고 재기동한다.
    stat_judgment_model: PromptSetModelId = "gemini"
    ending_judgment_model: PromptSetModelId = "gemini"
    image_judgment_model: PromptSetModelId = "gemini"
    memory_summary_model: PromptSetModelId = "gemini"
    # 요약 접기 뒤 장면 기억 추출(`chat/memory_episodes.py`)의 모델. 위 판정·요약 모델과 같은 규칙이다.
    memory_episode_model: PromptSetModelId = "gemini"
    # 요약 접기 뒤 관계·사실 기억 추출(`chat/memory_facts.py`)의 모델. 위 판정·요약 모델과 같은 규칙이다.
    memory_fact_model: PromptSetModelId = "gemini"
    # 요약 접기 뒤 인상 생성(`chat/memory_impressions.py`)의 모델. 위 판정·요약 모델과 같은 규칙이다.
    memory_impression_model: PromptSetModelId = "gemini"

    @field_validator("llm_call_site_backends", mode="before")
    @classmethod
    def _split_call_site_backends(cls, value: object) -> object:
        """env 문자열을 `{call_site: backend}` 로 나눈다. 항목은 쉼표로 나누고 앞뒤 공백은 지우며 빈 항목은 버린다 — 허용
        명단처럼 남는 항목이 없으면 빈 값(배정 없음)이다. 항목마다 콜론이 정확히 하나이고 양쪽이 비지 않아야 한다. 같은
        호출 위치가 두 번 나오면 거부한다 — 사전으로 바로 만들면 뒤의 값이 조용히 이기는데 어느 쪽이 의도였는지 모른다.
        모르는 호출 위치·구현 이름은 pydantic 이 거부한다."""
        if not isinstance(value, str):
            return value
        assignments: dict[str, str] = {}
        for item in value.split(","):
            if not item.strip():
                continue
            parts = [part.strip() for part in item.split(":")]
            if len(parts) != 2 or not all(parts):
                raise ValueError(f"LLM_CALL_SITE_BACKENDS 의 항목 {item.strip()!r} 은 call_site:backend 모양이 아니다")
            call_site, backend = parts
            if call_site in assignments:
                raise ValueError(f"LLM_CALL_SITE_BACKENDS 에 {call_site} 가 두 번 있다")
            assignments[call_site] = backend
        return assignments

    @field_validator(
        "bedrock_sonnet_model_id",
        "bedrock_opus_model_id",
        "bedrock_haiku_model_id",
        "bedrock_chat_timeout_ms",
        "bedrock_chapter_timeout_ms",
        "bedrock_chat_max_tokens",
        "bedrock_chapter_max_tokens",
        "anthropic_sonnet_model_id",
        "anthropic_opus_model_id",
        "anthropic_haiku_model_id",
        "anthropic_chat_timeout_ms",
        "anthropic_chapter_timeout_ms",
        "anthropic_chat_max_tokens",
        "anthropic_chapter_max_tokens",
        "anthropic_chat_effort",
        "anthropic_chapter_effort",
        "anthropic_structured_effort",
        "chat_premium_models_enabled",
        "novelize_premium_models_enabled",
        "stat_judgment_model",
        "ending_judgment_model",
        "image_judgment_model",
        "memory_summary_model",
        "memory_episode_model",
        "memory_fact_model",
        "memory_impression_model",
        mode="before",
    )
    @classmethod
    def _empty_bedrock_value_is_default(cls, value: object, info: ValidationInfo) -> object:
        """env 에 값만 비운 줄(`KEY=`)이 남아도 기동하게 빈 값은 코드 기본값으로 읽는다 — 숫자·불리언 파싱은 빈 문자열에서
        실패하고, 빈 모델 id 는 어떤 모델도 가리키지 않는다. 키·리전은 여기 넣지 않는다(빈 값이 곧 "없음"이고 아래 기동
        검사가 본다)."""
        if isinstance(value, str) and not value.strip():
            assert info.field_name is not None
            return cls.model_fields[info.field_name].default
        return value

    @model_validator(mode="after")
    def _premium_models_need_backend_credentials(self) -> "Settings":
        """켜진 스위치가 여는 호출(채팅: 턴 생성과 측정용 다시 생성, 소설: 장 생성과 구성안 두 호출)이 상위 모델로 실제로 갈 구현마다 그
        자격이 모두 있어야 한다. 배정이 없으면 그 구현은 Bedrock 이라 키·비밀 키·리전 셋을 본다. 켜진 채 빈 값으로 뜨면 첫
        상위 모델 호출에서야 실패하고(그 턴은 환불된다), Bedrock 은 클라이언트가 막지 못한 경로가 생기면 R2 자격으로 서명된다."""
        call_sites: list[LLMCallSite] = []
        if self.chat_premium_models_enabled:
            call_sites += ["chat_generate", "replay_generate"]
        if self.novelize_premium_models_enabled:
            call_sites += ["novelize_chapter", "novelize_outline", "novelize_episode_outline"]
        # 글쓰기 모델만 본다 — 구현 등록부의 모델 표에는 판정 전용 id 도 있어, 그 표로 고르면 스위치가 열지 않는 경로의
        # 자격까지 요구한다.
        premium_models = [model for model in get_args(backends.ChatModelId) if model != backends.DEFAULT_CHAT_MODEL]
        resolved = {
            backends.pick_backend(call_site, model, self.llm_call_site_backends)[1]
            for call_site in call_sites
            for model in premium_models
        }
        missing = [
            env_name
            for backend in sorted(resolved)
            for env_name, attr in backends.BACKENDS[backend].credential_env
            if not str(getattr(self, attr)).strip()
        ]
        if missing:
            raise ValueError(f"상위 모델 스위치가 켜져 있는데 {', '.join(missing)} 가 비어 있다")
        return self

    @field_validator("memory_model_scope", mode="before")
    @classmethod
    def _split_memory_model_scope(cls, value: object) -> object:
        """env 문자열을 `(레인, 모델)` 목록으로 편다. 항목은 쉼표로 나누고 앞뒤 공백은 지우며 빈 항목은 버린다. `모델` 만 쓴
        항목은 두 레인 모두로, `레인:모델` 은 그 레인 하나로 편다. 콜론이 둘 이상이거나 한쪽이 비면 거부하고, 모르는 레인·모델
        이름(판정 전용 `haiku` 포함)은 pydantic 이 거부한다 — 오타가 조용히 "어떤 방도 범위에 없음"이 되면 켠 스위치가 아무
        데서도 동작하지 않는데 기동은 성공한다."""
        if not isinstance(value, str):
            return value
        pairs: list[tuple[str, str]] = []
        for item in value.split(","):
            if not item.strip():
                continue
            parts = [part.strip() for part in item.split(":")]
            if len(parts) == 1:
                pairs += [(lane, parts[0]) for lane in get_args(MemoryScopeLane)]
            elif len(parts) == 2 and all(parts):
                pairs.append((parts[0], parts[1]))
            else:
                raise ValueError(f"MEMORY_MODEL_SCOPE 의 항목 {item.strip()!r} 은 모델 또는 레인:모델 모양이 아니다")
        return pairs

    @model_validator(mode="after")
    def _embedding_needs_a_voyage_key(self) -> "Settings":
        """키 없이 켜진 채우기는 채울 때마다 실패할 뿐이라 켠 것이 성공한 것처럼 보인다 — 배포 단계에서 드러나게 기동을 막는다.
        임베딩 회상도 같다(키 없이 켜면 매 턴 질의 임베딩이 실패해 조용히 명사 단독으로 돈다). 꺼져 있으면 키를 보지 않는다."""
        if self.memory_embed_write and not self.voyage_api_key.strip():
            raise ValueError("MEMORY_EMBED_WRITE 가 켜져 있는데 VOYAGE_API_KEY 가 비어 있다")
        if self.memory_embed_recall and not self.voyage_api_key.strip():
            raise ValueError("MEMORY_EMBED_RECALL 이 켜져 있는데 VOYAGE_API_KEY 가 비어 있다")
        return self

    @model_validator(mode="after")
    def _call_site_backends_can_be_followed(self) -> "Settings":
        """배정이나 판정·요약 모델이 틀린 채 뜨면 그 호출이 첫 호출에서야 실패하거나 배정이 조용히 무시된다. 규칙은 등록부
        쪽에 있다(`llm/backends.py` 의 `assignment_errors`) — 구현 행이 늘어도 여기는 그대로다."""
        errors = backends.assignment_errors(self.llm_call_site_backends, lambda name: str(getattr(self, name)))
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @field_validator(
        "gemini_thinking_budget", "gemini_novelize_thinking_budget", "gemini_novelize_thinking_level", mode="before"
    )
    @classmethod
    def _empty_thinking_budget_is_unset(cls, value: object) -> object:
        """env 에 값을 비운 줄(`KEY=`)이 남으면 빈 문자열이 들어와 정수 파싱이 실패하고 api 가 기동하지 못한다.
        빈 값은 "정하지 않음"이므로 None(사고 설정을 넘기지 않음)으로 읽는다 — 빈 모델명이 기본 모델로 도는
        것과 같다. `0`(사고 끔)은 빈 값이 아니라 그대로 0 이다."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _novelize_thinking_is_budget_or_level(self) -> "Settings":
        """Gemini 3 계열은 사고 예산과 사고 수준을 한 요청에 함께 받으면 요청을 거부할 수 있다. 둘 다 둔 채로 뜨면
        장 생성·문단 수정이 매번 실패하고 환불로 끝나므로, 둘 중 하나만 정하도록 기동에서 막는다."""
        if self.gemini_novelize_thinking_budget is not None and self.gemini_novelize_thinking_level is not None:
            raise ValueError("gemini_novelize_thinking_budget 과 gemini_novelize_thinking_level 은 둘 중 하나만 정한다")
        return self

    # 회차 재현성을 위한 결정적 시드. None = seed 를 아예 안
    # 넘김(현재와 동일한 매 회차 난수 동작). generate()에만 붙인다 — generate_structured()
    # (판단 호출)는 회차 재현 측정 대상이 아니다.
    gemini_seed: int | None = None
    # 조립된 프롬프트를 회차 재현용으로 JSONL에
    # 남길 파일 경로. None = 아무 일도 안 함(프로덕션 기본값이자 방어) — 프롬프트에는
    # 창작자의 비공개 설정이 들어 있어 기본으로 켜지면 안 된다.
    prompt_dump_path: str | None = None
    # 생성 잡 Redis 레코드 TTL(확정값 1시간).
    image_generation_job_ttl_seconds: int = 60 * 60

    # 집 PC 자가 호스팅 이미지 생성
    # 서버. 호스트명에 모델 힌트를 넣지 않는다 — DNS 레코드와 CT 로그는 공개다.
    local_image_base_url: str = ""
    # Cloudflare Access 서비스 토큰.
    local_image_access_client_id: str = ""
    local_image_access_client_secret: str = Field(default="", repr=False)
    # DEPLOY.md "이미지 생성" 절 실측(집 PC 계약 v4): 워밍업 뒤 생성은 참조 포함 약 17초 이하, 최악은
    # 서버 재기동 직후 첫 요청의 약 38초이고, 참조를 실은 요청은 안 실은 요청보다 약 2초 느리다.
    # 8,000,000자에 가까운 큰 참조는 VM→집 PC 전송 시간이 따로 붙는데 그건 아직 재지 않았다 — 90초는
    # 그 여유까지 둔 값이다. 참조 요청과 참조 없는 요청이 이 값 하나를 쓰므로 참조 요청만 짧아지는 일은 없다. 상한 쪽
    # 제약은 그대로 살아 있다: VM은 Cloudflare Tunnel로 집 PC에 도달하므로(DEPLOY.md "이미지 생성" 절)
    # edge 타임아웃(무료 플랜 100초로 알려짐, 아직 실측 없음) 미만이어야 한다.
    local_image_timeout_seconds: int = 90
    # 잠정값 — 복구 감지 속도와 프로브 빈도의 타협(콜드/만료 시에만 프로브).
    local_image_capabilities_ttl_seconds: int = 30
    # 잠정값. 모든 워커를 합친 값이다(대기열이 Redis 에 있다). 잡 하나는 최대 2장(count<=2)이고
    # `llm/local_image.py` 의 생성 락이 집 PC 호출을 워커를 가리지 않고 한 장씩 직렬로 보낸다. 장당
    # 최악을 DEPLOY.md "이미지 생성" 절의 약 38초(서버 재기동 직후 첫 요청 — 보통은 워밍업 뒤 약 17초
    # 이하)로 잡으면 잡당 약 76초, 네 번째로 받아들인 잡이 끝나기까지
    # 약 5분이다. 큰 참조 이미지의 전송 시간(미측정)과 응답 없이 타임아웃까지 매달리는 실패는 이
    # 추정에 들어 있지 않다.
    local_image_queue_limit: int = 4
    # 공개 id(FE 노출, `v1`)와 홈PC의 실제
    # 체크포인트 id(와이어 id)가 다를 수 있다. 원 요구가 "코드상이나 endpoint나
    # payload로 모델을 유추할 수 없게"이므로 실제 와이어 값을 이 소스에 박으면 그 요구를
    # 어긴다 — 실제 값은 VM `.env`에만 두고 이 저장소엔 없다.
    # 기본값을 공개 id와 같게 두어 env 없이 테스트·로컬 개발이 그대로 동작한다.
    #
    # style 축은 이 분리를 두지 않는다 — 공개 id와
    # 와이어 id가 같아 `local_image.py`가 `style.value`를 그대로 싣는다. model 축만
    # 분리를 유지하는 이유: model 축은 실제로 다른 와이어 값을 가렸지만
    # style 축은 지금까지 아무것도 보호한 적이 없다.
    # 실제 값이 드러나면 안 되므로 다른 비밀 필드처럼 repr 에서도 뺀다.
    local_image_model_wire_id: str = Field(default="v1", repr=False)
    # 본인 생성 이미지를 참조로 집 PC 에 싣는 기능의 공개 스위치. 기본값이 닫힘이라 env 없이
    # 배포해도 닫힌 채로 뜬다. 참조 필드를 모르는 서버는 이 필드를 조용히 무시하고 참조 없이 200 을
    # 주므로, 서버 반영을 통지받은 뒤에만 켠다. `/images/models` 가 이 값을 FE 에 알리고
    # `POST /images/generate` 는 요청마다 다시 본다.
    local_image_reference_enabled: bool = False

    # 빌더 미리보기 세션(Redis 전용, Postgres 미기록)의
    # 마지막 활동 기준 TTL — 확정값 24시간.
    preview_session_ttl_seconds: int = 60 * 60 * 24

    # 조회수 중복 제거용 게스트 뷰어 쿠키. 쿠키 수명은
    # 중복 제거 TTL보다 반드시 길어야 한다(짧으면 쿠키 재발급 = 새 뷰어로 잡혀
    # TTL 창 안에서 같은 사람이 두 번 세어진다).
    guest_viewer_cookie_name: str = "guest_viewer_id"
    guest_viewer_cookie_max_age_seconds: int = 60 * 60 * 24 * 365
    content_view_dedup_ttl_seconds: int = 60 * 60 * 24

    # 프로바이더는 env 스위치, 기본값은 콘솔 — 로컬 개발/pytest가
    # 실수로 실제 메일을 쏘는 사고를 원천 차단한다.
    email_provider: Literal["console", "resend"] = "console"
    # Resend REST API(https://api.resend.com/emails) 인증 토큰.
    resend_api_key: str = Field(default="", repr=False)
    # 발신 주소. ddona.site 도메인이 Resend에서 검증돼야 이 주소로
    # 실제 발신이 나간다.
    email_from: str = "noreply@ddona.site"

    # 활성 프롬프트 세트 캐시(`prompt_set:active`)의 TTL.
    # `invalidate_active_prompt_set()`의 명시적 DEL이 무효화의 정공법이라 이 값은 주 수단이
    # 아니라 그 DEL이 누락되는 경로가 생겼을 때의 상한이다. 게시는 드문 관리자 작업이라 짧을
    # 이유가 없고, 반대로 DEL이 어떤 이유로든 안 불리면 옛 문안이 그만큼 오래 남으므로 무한정
    # 길게 둘 수도 없다 — 5분이면 무효화가 깨져도 운영자가 재게시 확인을 오래 기다리지 않는다.
    prompt_set_cache_ttl_seconds: int = 60 * 5

    # 긴 방의 생성 프롬프트에서 요약이 덮은 메시지를 빼는 히스토리 윈도우를 켠다. 끄면 요약
    # 스냅샷이 있어도 전체 히스토리를 싣는다(스냅샷은 남고 무시될 뿐 지워지지 않는다) — 요약
    # 품질 사고 때 코드 배포 없이 `.env` 수정과 재기동만으로 예전 동작으로 돌아가는 스위치다.
    memory_window_generation: bool = True
    # 판정 호출에도 윈도우를 씌울지 호출별로 정한다. 기본으로 켜 둔다 — 끄면 판정이 대화 전체를 실어, 미디어 북 칸
    # 판정처럼 매 턴 도는 판정의 입력이 턴 수에 비례해 끝없이 자라고 원가·지연이 함께 늘어 긴 대화를 감당하지 못한다.
    # 켜면 생성 프롬프트와 같은 요약 커서로 원문을 자른다. 엔딩은 누적 판단이라 현재 요약도
    # 함께 싣고, 그림 매칭(캐릭터 상황 이미지·스토리 미디어 북 칸)은 장면 매칭이라 최근 원문만 싣는다.
    # 판정 품질 사고 때는 `.env` 에 `MEMORY_WINDOW_ENDING_JUDGMENT=false`·`MEMORY_WINDOW_IMAGE_JUDGMENT=false` 를 넣고
    # 재기동하면 윈도우 도입 전과 같은 프롬프트로 돌아간다. 위 생성 윈도우 스위치를 끄면 이 둘이 켜져 있어도 판정까지
    # 전체 히스토리로 돌아간다 — 되돌리기 스위치 하나로 전부 돌아가게.
    memory_window_ending_judgment: bool = True
    memory_window_image_judgment: bool = True
    # 요약 접기가 접은 대화 구간을 장면 기억(`chat_memory_episodes`)으로 뽑는 백그라운드 추출을 켠다. 기본은 꺼짐 — 꺼져
    # 있으면 접기 뒤에 아무것도 예약하지 않아 턴의 호출·트랜잭션이 이 스위치가 생기기 전과 같다. 위 생성 윈도우 스위치가
    # 꺼져 있으면 접기 자체가 없어 이 값과 무관하게 추출도 없다. 끄면(줄 삭제 + 재기동) 이미 뽑은 장면은 남고 새로 뽑지 않는다.
    memory_episodes_extract: bool = False
    # 요약 접기가 접은 대화 구간을 관계·사실 기억(`chat_memory_facts`)으로 뽑는 백그라운드 추출을 켠다. 기본은 꺼짐이고 장면
    # 추출 스위치와 따로다 — 켜면 장면 추출 예약 뒤에 따로 예약한다. 생성 윈도우 스위치가 꺼져 있으면 접기가 없어 추출도 없다.
    # 끄면(줄 삭제 + 재기동) 이미 뽑은 사실은 남고 새로 뽑지 않는다.
    memory_facts_extract: bool = False
    # 매 턴 방의 장면 기억에서 이번 턴과 이어질 장면을 골라 생성 프롬프트의 회상 섹션(대화 기록 뒤)에 싣는다. 인물이 대사로만
    # 말한 장면은 싣지 않고, 장면 행 자신의 아는 사람 칸이나 방 사실 행의 아는 사람 정보로 이번 장면에 아는 사람이 없는 비밀
    # 장면을 가린다(`chat/memory_recall.py`) — 그래서 켜면 사실 주입이 꺼져 있어도 매 턴 방 사실 행을 읽고, 이 가림만 따로 끌 수는 없다.
    # 기본은 꺼짐 — 꺼져 있으면 장면도 사실도 읽지 않아 생성 프롬프트·SQL 이 이 스위치가 생기기 전과 같다. 위 생성 윈도우
    # 스위치가 꺼져 있으면 요약 커서가 없어 이 값과 무관하게 회상도 없다. 끄면(줄 삭제 + 재기동) 다음 턴부터 섹션이 빠지고
    # 장면은 남는다.
    memory_episodes_recall: bool = False
    # 매 턴 방의 관계·사실 기억을 키마다 지금 값으로 줄여 생성 프롬프트의 사실 섹션(대화 기록 뒤, 회상 앞)에 싣는다. 키의 지금
    # 값이 인물·서술이 말로만 전한 확인되지 않은 주장이면 그 키는 싣지 않는다(사용자 주장은 싣는다). 기본은
    # 꺼짐 — 꺼져 있으면 사실을 읽지도 않아 생성 프롬프트·SQL 이 이 스위치가 생기기 전과 같다. 회상과 같은 이유로 생성 윈도우
    # 스위치가 꺼져 있으면 이 값과 무관하게 싣지 않는다(원문이 전체로 실리면 같은 사실이 두 번 들어간다). 끄면(줄 삭제 +
    # 재기동) 다음 턴부터 섹션이 빠지고 사실 행은 남는다.
    memory_facts_inject: bool = False
    # 사실 섹션을 고르기 전에, 아는 사람이 정해진 사실 중 그 사람이 이번 장면(이번 사용자 메시지·직전 응답에 이름이 나온
    # 인물, 사용자 제외)에 없는 행을 뺀다(`chat/memory_knowledge.py`) — 비밀을 모르는 인물만 있는 장면에서 그 비밀이 새지 않게.
    # 기본은 꺼짐 — 꺼져 있으면 이름 출처를 읽지도 않아 생성 프롬프트·SQL 이 이 스위치가 생기기 전과 같다. 거름은 사실 섹션 안에서만
    # 걸린다. 회상 줄의 같은 가림은 이 스위치가 아니라 회상 스위치에 묶여 있다. 켜면 사실 섹션과 회상의 가림 모두 직전 응답의
    # 대사 따옴표 안에만 나온 이름을 장면 인물로 세지 않는다(두 섹션이 같은 장면 인물을 써야 사실 섹션이 뺀 비밀이 회상 줄로
    # 새지 않는다) — 그래서 사실 주입과 회상이 둘 다 꺼져 있을 때만 이 값과 무관하게 아무것도 바뀌지 않는다. 끄면(줄 삭제 +
    # 재기동) 다음 턴부터 사실 섹션에서 걸러 내지 않고 대사 안 이름도 다시 센다.
    memory_knowledge_filter: bool = False
    # 요약 접기 프롬프트의 지시문 바로 뒤에 비밀 표기 슬롯(비밀에 아는 사람 표기를 붙이고 그 내용을 표기 없이 다시 쓰지 않게 하는
    # 지시와 그 방의 인물 이름 목록)을 싣는다(`chat/memory_fold.py`). 기본은 꺼짐 — 꺼져 있으면 이름 출처를 읽지도 않고 슬롯의 값이
    # 비어 conditional 로 섹션째 빠져, 요약 프롬프트가 이 스위치가 생기기 전과 바이트까지 같다. 생성 윈도우 스위치가 꺼져 있으면
    # 접기가 없어 이 값과 무관하다. 끄면(줄 삭제 + 재기동) 다음 접기부터 슬롯이 빠지고, 이미 쓴 요약은 그대로 남는다.
    memory_summary_secret_marking: bool = False
    # 위 기억 사용 스위치(회상·사실 주입·지식 범위 필터·요약 비밀 표기)와 아래 임베딩 회상이 실제로 동작하는 방의 범위 — 그 턴의
    # 레인과 글쓰기 모델이 이 목록에 있어야 켜진 스위치가 동작하고, 없으면 그 턴은 스위치를 다 끈 것과 프롬프트·SQL 이 같다.
    # 기억 품질은 Opus 방에서만 재 보았고 다른 모델 방에서 켜면 측정하지 않은 동작이 나가므로 기본은 Opus 방뿐이다. 값은 쉼표로
    # 나눈 목록이고 원소는 `모델`(두 레인 모두) 또는 `레인:모델`이다 — 레인은 `story`·`character`, 모델은 글쓰기 모델 id
    # (`gemini`·`sonnet`·`opus`, 판정 전용 `haiku` 는 아니다). 모르는 레인·모델이면 기동하지 않는다. 어떤 방에서도
    # 기억을 쓰지 않으려면 이 값을 비우지 말고 기억 스위치를 끈다 — 운영 env 형식 검사가 빈 값을 거부해 배포가 멈춘다.
    # 추출(장면·사실)과 임베딩 쓰기는 이 범위와 무관하다 — 쌓아 두는 일이라 어느 방에서 켜도 그 방 대화가 바뀌지 않는다.
    memory_model_scope: Annotated[list[tuple[MemoryScopeLane, backends.ChatModelId]], NoDecode] = [
        ("story", "opus"),
        ("character", "opus"),
    ]
    # 요약 접기 뒤 장면·사실 기억 행을 Voyage 로 임베딩해 `chat_memory_embeddings` 에 채우는 백그라운드 작업을 켠다
    # (`chat/memory_embeddings.py`). 기본은 꺼짐 — 꺼져 있으면 예약하지 않아 Voyage 를 부르지도 임베딩 표를 읽지도 않고, 턴의
    # 호출·트랜잭션이 이 스위치가 생기기 전과 같다. 생성 윈도우 스위치가 꺼져 있으면 접기가 없어 이 값과 무관하게 채우지 않는다.
    # 켜면 Voyage 키(`voyage_api_key`)가 있어야 기동한다. 끄면(줄 삭제 + 재기동) 이미 채운 행은 남고 새로 채우지 않는다.
    memory_embed_write: bool = False
    # 임베딩 모델 id 와 출력 차원. 임베딩 표는 행마다 모델·차원을 적고 읽는 쪽이 늘 지금 값으로 거르므로, 바꾸면 그 모델·차원의
    # 행이 없는 장면·사실을 처음부터 다시 채운다(옛 행은 남는다). 기본값은 회상 품질 측정(Voyage 4 계열 모델 × 출력 차원 비교)이
    # 고른 값이라 스위치만 켜도 측정한 설정으로 돈다. 두 임베딩 스위치가 꺼져 있으면 이 값을 읽는 호출이 없다.
    memory_embed_model: str = "voyage-4-large"
    memory_embed_dims: int = 1024
    voyage_api_key: str = Field(default="", repr=False)
    # 매 턴 질의 임베딩을 한 번 받아(이번 사용자 메시지 + 직전 응답) 장면 회상과 사실 섹션의 관련 몫을 명사 순위와 벡터 거리
    # 순위의 RRF 로 고른다(`chat/memory_vector.py`). 기본은 꺼짐 — 꺼져 있으면 Voyage 를 부르지도 임베딩 표를 읽지도 않아 생성
    # 프롬프트·SQL·턴 기록이 이 스위치가 생기기 전과 같다. 회상(`memory_episodes_recall`)이나 사실 주입(`memory_facts_inject`)이
    # 켜져 있어야 효과가 있다. 질의 임베딩이 시간 상한을 넘기거나 실패하거나 방에 지금 모델·차원의 임베딩이 없으면 그 턴은 명사
    # 단독과 바이트까지 같다. 켜면 Voyage 키가 있어야 기동한다. 끄면(줄 삭제 + 재기동) 다음 턴부터 명사 단독이다.
    memory_embed_recall: bool = False
    # 질의 임베딩의 시간 상한(밀리초). 생성 앞에서 기다리므로 첫 글자 지연이 이만큼까지 는다 — 넘기면 기다리지 않고 명사 단독이다.
    # 기본값은 운영 VM 에서 잰 Voyage 왕복(키 없이 401 을 받는 왕복, 다시 쓰는 연결 p50 약 130ms·p95 약 480ms)에 임베딩 계산
    # 시간의 여유를 둔 값이다(로컬 맥에서 실제 키로 다시 쓰는 연결은 p50 340~430ms). 켠 뒤 턴 기록의 시간 초과 비율로 다시 본다.
    memory_embed_recall_timeout_ms: int = 1000
    # 아래는 벡터 쪽이 비지 않은 턴에만 쓰는 값이다(비면 명사 단독의 모듈 상수 그대로라 이 값과 무관하게 바이트가 같다). 기본값은
    # 회상 품질 측정의 격자가 고른 값이다 — 명사 단독과 같은 주입 상한(보통 턴 1·회상 단서 턴 3), RRF k = 20, 거리로 거르지 않음
    # (코사인 거리의 최댓값 2), 흔한 명사의 절대 상한 없음(비율 기준만). 회상의 벡터 순위는 거리 순 앞 `vector_limit`
    # 개까지다. k 와 거리 상한은 사실 섹션 관련 몫에도 쓴다(사실 쪽 벡터 순위는 지식 범위 필터를 지난 행 전부라 길이 상한이 없다).
    memory_embed_recall_rrf_k: int = 20
    memory_embed_recall_max_plain: int = 1
    memory_embed_recall_max_cue: int = 3
    memory_embed_recall_max_distance: float = 2.0
    memory_embed_recall_vector_limit: int = 10
    memory_embed_recall_df_max: int | None = None
    # 방 주인에게 그 방의 장면·사실 기억 목록을 보여 주는 API(`GET /chat-rooms/{id}/memory/items`)를 연다. 기본은 꺼짐 — 꺼져
    # 있으면 라우트는 등록된 채 404 `MEMORY_ITEMS_DISABLED` 이고(그래서 OpenAPI 스펙은 이 값과 무관하다), 기억 응답의 기능 칸이
    # 꺼짐을 알려 화면이 "목록 없음"과 가른다. 목록은 읽기만 해서 생성·요약·추출과 무관하다. 처리방침에 기억 열람 항목을 게시한
    # 뒤 켠다. 끄면(줄 삭제 + 재기동) 다음 요청부터 다시 404 다.
    memory_items_visible: bool = False
    # 턴 기록에 스탯 판정 이벤트(스탯마다 발동한 규칙·적용한 규칙·폭·잘림, 카운터의 한 칸 — 규칙은 id 로만)를 남긴다. 기본은
    # 꺼짐 — 꺼져 있으면 칸(`chat_turns.stat_events`)을 INSERT 에 싣지 않아 DB 기본값 `[]` 이 들어가고 턴 기록 INSERT 의 칸
    # 목록이 이 칸이 생기기 전과 같다(서버 기본값이 있는 칸이라 RETURNING 에는 이 칸이 더해진다). 켜도 꺼도 판정·생성 프롬프트와 스탯 값은 같다(기록만 더한다). 방 범위와 무관하게 모든 방에 쓴다 — 판정이
    # 모든 방에서 돌고 이 칸은 기억 기능이 아니다. 처리방침 턴 기록 항목에 판정 규칙 식별자를 게시한 뒤 켠다. 끄면(줄 삭제 +
    # 재기동) 다음 턴부터 다시 `[]` 이고 이미 쌓인 칸은 남는다.
    stat_event_log: bool = False
    # 요약 접기 몇 번마다 방 하나에 인상(그 접기들에서 뽑힌 장면·사실 기억을 읽고 인물 사이 감정·태도의 흐름을 적은 짧은 글) 한
    # 행을 `chat_memory_impressions` 에 쌓는 백그라운드 작업을 켠다(`chat/memory_impressions.py`). 저장만 한다 — 생성 프롬프트에
    # 싣지 않고 화면에도 보이지 않는다. 기본은 꺼짐 — 꺼져 있으면 예약하지 않아 호출도 인상 표 SELECT·INSERT 도 없고 턴의
    # 호출·트랜잭션이 이 스위치가 생기기 전과 같다. 켜져 있어도 기억 사용 범위(`memory_model_scope`) 밖 방에서는 돌지 않고, 덮는
    # 스냅샷들의 장면·사실 추출이 모두 끝나야 돈다 — 그래서 두 추출 스위치가 꺼져 있으면 아무것도 쌓이지 않는다. 생성 윈도우
    # 스위치가 꺼져 있으면 접기가 없어 이 값과 무관하게 돌지 않는다. 처리방침에 인상 항목을 게시한 뒤 켠다. 끄면(줄 삭제 +
    # 재기동) 이미 쌓인 행은 남고 새로 쌓지 않는다.
    memory_impressions_write: bool = False
    # 인상 하나가 덮는 요약 스냅샷 수(접기 횟수). 방의 스냅샷 수가 이 값의 배수가 된 접기 뒤에 가장 새 스냅샷까지의 이만큼을 묶어
    # 인상 하나를 만든다. 접기는 대략 10턴마다라 기본값 3 이면 약 30턴마다 한 번이다 — 개발 측정에서 다시 정한다.
    memory_impression_every_n_folds: int = Field(default=3, ge=1)

    # 소설화 전역 스위치. 꺼져 있으면 허용 행이 있어도 아무도 못 쓴다 — 코드 기본값이 닫힘이어야 env 설정 없이
    # 배포해도 닫힌 채로 뜬다. 끄면 다음 요청부터 막히고(재기동 필요), 허용 행은 남아 다시 켜면 그대로 돌아온다.
    novelize_enabled: bool = False
    # 소설화를 허용할 수 있는 계정 id 명단(쉼표 구분, 따옴표 없이). 어드민이 허용을 줄 때와 사용자가 접근할 때 둘 다
    # 본다 — 명단에서 지우고 재기동하면 허용 행을 지우지 않아도 그 계정은 곧바로 막힌다. 비어 있으면 아무에게도 줄 수
    # 없다. `NoDecode` 는 위 CORS 명단과 같은 이유로 JSON 디코드 단계를 끈다.
    novelize_grant_allowlist: Annotated[list[uuid.UUID], NoDecode] = []
    # 같은 장(같은 시작 메시지)을 하루(KST)에 몇 번까지 만들 수 있는지 — 장 생성과 재생성을 함께 세고, 진행 중·성공만
    # 센다(환불된 실패는 세지 않는다). 매번 과금되지만 같은 구간을 끝없이 다시 돌리는 것을 막는 상한이다. 소설화 본
    # 시험에서 같은 장을 여러 번 돌려야 하므로 격리 환경에서 올릴 수 있게 설정으로 둔다. 기본값은 시험 뒤 확정하는 임시값.
    novelize_chapter_daily_limit: int = 5
    # 소설화 작업이 살아 있다는 표시(`novel_jobs.heartbeat_at`)를 몇 초마다 갱신하는지, 몇 초 갱신이 없으면 죽은 작업으로
    # 보고 실패·환불하는지. 만료는 주기보다 넉넉히 길어야 한다 — 짧으면 DB 가 잠깐 느린 것만으로 살아 있는 작업이
    # 환불되고, 그 작업의 결과는 버려진다. 비교는 DB 시계로 한다. 둘 다 시험 뒤 확정하는 임시값.
    novelize_heartbeat_interval_seconds: float = 10
    novelize_heartbeat_expiry_seconds: int = 60
    # 소설화 작업 하나의 전체 상한(초). heartbeat 가 살아 있어도 작업이 무한히 늘어지지 않게 한다. 지금 SDK 경로(httpx)
    # 에서 장 생성 호출의 타임아웃(Gemini `gemini_novelize_chapter_timeout_ms`, 상위 모델은 Bedrock 이면
    # `bedrock_chapter_timeout_ms`, Anthropic API 로 직접 보내면 `anthropic_chapter_timeout_ms`)은 스트리밍의 청크 사이 읽기
    # 상한이라, 꾸준히 흘러나오는 긴 장의 전체 시간을 끊는 것은 이 작업 상한 하나뿐이다. 그 호출
    # 타임아웃은 첫 청크 전(또는 청크 사이)에 오래 멈춘 경우에만 먼저 난다. 넘기면 실패·환불하고(상위 모델도 그 모델 값
    # 그대로 환불), 취소된 호출의 토큰 사용량은 기록되지 않는다 — 원가는 나갔는데 집계에 안 잡힌다. 상위 모델, 특히 Opus
    # 의 긴 장이 이 상한 안에 드는지는 아직 재지 않았다. 상위 모델을 켜기 전에 가장 긴 장(턴 상한 끝까지)을 Opus 로 한 번
    # 돌려 걸린 시간을 보고, 넘으면 이 값을 올린다. Anthropic API 직접 경로의 모델은 사고를 끌 수 없어 본문 앞에 사고가
    # 붙으므로, 장을 그 경로로 보낼 때는 그 경로로 따로 잰다. 임시값.
    novelize_job_timeout_seconds: float = 360
    # 장 본문이 이보다 짧으면(글자 수, 앞뒤 공백 제외) 정상 종료였어도 실패·환불한다. 출력 토큰 1개로 끝난 장이 실제로
    # 나왔다. 200자는 측정으로 정한 값이 아니라 그런 몇 글자짜리 장을 거르려고 넉넉히 낮게 잡은 임시 하한이다 — 짧은
    # 응답 한 턴만 담은 정상 장이 이 아래로 나올 수도 있어서, 본 시험에서 정상 장의 최단 길이를 보고 다시 정한다.
    novelize_min_chapter_chars: int = 200
    # 다음 장 생성에 싣는 직전 장 끝 발췌의 목표 길이(글자). 문단 단위로 잘라 이 길이에 가장 가까운 만큼 싣는다.
    # 앞 장을 되풀이하지 않고 이어 쓰게 하려는 것이다. 임시값.
    novelize_previous_excerpt_chars: int = 1000
    # 생성 한 번(묶음)이 담을 수 있는 원문 턴(AI 응답) 수의 상한 — 모델마다 따로다. 경계 제안은 이 수만큼의 후보 턴을
    # 보여 주고, 생성은 끝 메시지가 이 범위 밖이면 거절한다. 원문은 빠짐없이 옮기므로 묶음의 출력 길이를 정하는 것은 화
    # 수가 아니라 이 턴 수다. Gemini 는 화 여러 개를 한 번에 쓰므로 길게 두고, Claude 는 짧은 연결 시험에서 잰 Opus
    # 출력 속도(초당 약 48토큰)로 보면 45턴 묶음이 작업 전체 상한(`novelize_job_timeout_seconds`)에 닿거나 넘고 20턴이면
    # 원문이 길게 옮겨지는 경우에도 그 70% 안에 든다 — Sonnet 은 따로 재지 않고 Opus 와 같은 값을 쓴다. 모두 임시값이고,
    # Gemini 키 이름은 한 모델뿐이던 때의 것을 그대로 둔다(운영 `.env` 에 같은 키가 있으면 그 값이 이긴다).
    novelize_chapter_max_turns: int = Field(default=45, ge=1)
    novelize_chapter_max_turns_sonnet: int = Field(default=20, ge=1)
    novelize_chapter_max_turns_opus: int = Field(default=20, ge=1)
    # 묶음 하나가 나뉘는 화 수의 상한(모델별). 화 수는 원문 분량으로 정하고 이 값에서 자른다(`novelize/episodes.py`).
    # Gemini 는 출력 상한(`gemini_novelize_max_output_tokens`)에서 사고 토큰 최악치를 뺀 몫을 화 하나의 출력 토큰으로
    # 나눈 값(약 4)에서, 형식이 어긋나면 묶음 전체를 환불하므로 한 칸 여유를 둔 값이다. Claude 는 위 Opus 속도로 화 둘을
    # 쓰면 작업 상한의 70% 를 넘을 수 있어 하나다. 임시값.
    novelize_k_max_gemini: int = Field(default=3, ge=1)
    novelize_k_max_sonnet: int = Field(default=1, ge=1)
    novelize_k_max_opus: int = Field(default=1, ge=1)
    # 화 하나의 목표 길이(공백 포함 글자)와, 원문 글자 수를 본문 글자 수로 바꾸는 비율. 화 수 = 원문 글자 × 비율 ÷ 목표
    # 길이를 반올림한 값이다. 비율은 지난 장들의 본문/원문 글자 비의 중앙값 근처다. 임시값.
    novelize_episode_target_chars: int = Field(default=5000, ge=1)
    novelize_source_ratio: float = Field(default=0.8, gt=0)
    # 다음 묶음 생성에 싣는 지난 화 요약 전부의 글자 상한. 넘으면 오래된 화부터 뺀다 — 가까운 화가 이어 쓰기에 더 쓸모
    # 있다. 요약은 화마다 두세 문장이라 이 값이면 수십 화를 싣는다. 임시값.
    novelize_previous_summaries_max_chars: int = Field(default=8000, ge=1)
    # 장 경계 제안(무과금 모델 호출)을 한 사용자가 한 시간에 몇 번까지 부를 수 있는지. 과금이 없어 남용을 막는 것이
    # 이 상한뿐이다. 면제 계정도 똑같이 센다. 임시값.
    novelize_proposal_hourly_limit: int = 30
    # "남은 대화 한 번에"(연쇄 생성)가 한 번에 만드는 묶음 수의 상한. 금액을 묶음마다 화 수 상한만큼 미리 받으므로 이
    # 값이 한 번에 묶이는 클로버의 상한이기도 하다 — 남은 대화가 더 있으면 다시 누른다. 임시값.
    novelize_chain_max_batches: int = Field(default=5, ge=1)
    # 연쇄 부모 작업의 전체 시간 상한 = 계획한 묶음 수 × (작업 하나의 상한 `novelize_job_timeout_seconds` + 경계 제안
    # 타임아웃 `gemini_novelize_boundary_timeout_ms`) + 이 여유(초). 묶음마다 경계 제안 한 번과 자식 작업 하나가 돌므로 둘은
    # 묶음 수에 비례해 곱하고, 여유는 묶음 수와 무관한 몫(부모 시작·끝의 DB 일)만 담는다. heartbeat 가 살아 있어도 이
    # 상한을 넘으면 실패·남은 몫 환불이다 — 걸린 부모가 소설을 영영 진행 중으로 잠그지 않게. 임시값.
    novelize_chain_timeout_margin_seconds: float = Field(default=60, gt=0)
    # 소설 하나의 스냅샷 개수 상한. 닿으면 가장 오래된 복원 직전 자동 스냅샷부터 지우고, 이름 붙인 것만 남았으면 새 저장을
    # 거절한다. 복원 직전 자동 스냅샷은 복원이 막히지 않게 이 상한을 넘어 한 장 더 둘 수 있다. 임시값.
    novelize_snapshot_limit: int = Field(default=50, ge=1)
    # 노벨(공개 소설) 스위치. 꺼져 있으면 아무도 소설을 공개하거나 다시 공개할 수 없고 게시자의 공개 상태 조회도 403 이다 —
    # 코드 기본값이 닫힘이라 env 설정 없이 배포하면 닫힌 채 뜬다(바꾸면 재기동해야 반영된다). 소설화 스위치·허용과 별개로 이
    # 스위치도 켜져 있어야 한다. 끄는 동안에도 공개 상태 행은 남아 다시 켜면 그대로 돌아오고, 게시자의 공개 거두기는 막지
    # 않는다(자기 글을 내리는 일이라).
    novel_public_enabled: bool = False
    # 노벨 미리보기 명단 — 계정 id, 쉼표 구분(따옴표 없이). 비어 있으면(기본값) 스위치가 켜졌을 때 모두에게 열린다. 비어
    # 있지 않으면 스위치가 켜져 있어도 이 명단의 로그인 회원에게만 열리고, 나머지(비로그인 포함)에게는 스위치를 끈 것과 같다
    # — 약관이 시행되기 전에 운영자만 운영 환경에서 시험해 보고, 시행일에 명단을 비워 모두에게 연다. 판정은
    # `novel_public/access.py` 의 `novel_public_open_to` 하나다. UUID 가 아닌 항목이 있으면 api 가 기동하지 못한다.
    novel_public_preview_allowlist: Annotated[list[uuid.UUID], NoDecode] = []
    # 노벨 공개 정책 스위치. 꺼져 있으면(기본값) 지금 약관대로다 — 첫 공개는 자동 글 심사를 통과하면 바로 독자에게 열리고,
    # 원작자가 소설화 허락을 거두면 다음 화 공개가 막힌다. 켜면 아직 독자에게 보인 적 없는 소설의 첫 공개가 운영자 승인을
    # 기다리고, 한 번 독자에게 보인 소설은 원작자가 허락을 거둬도 다음 화를 이어 공개한다. 6화부터 화마다 무료·유료를
    # 고르고 유료 화를 무료로 바꾸는 것도 켜졌을 때만 된다. 개정 약관이 시행된 뒤에 켠다.
    novel_public_policy_v2_enabled: bool = False
    # 소설 화 삽화 스위치. 꺼져 있으면(기본값) 작가의 삽화 붙이기·옮기기·바꾸기·떼기와 원작 그림 후보가 404 이고, 삽화 용도
    # 업로드를 받지 않으며, 화 응답에 그림을 싣지 않고, 소설 표지는 생성 이미지 삭제를 막지 않는다(지금 약관대로). 개정에 이미
    # 붙은 배치는 꺼져 있어도 새 개정으로 이어지고 그 그림 파일을 지우지 못하게 지킨다. 개정 처리방침 게시 뒤에 켠다.
    novel_illustrations_enabled: bool = False
    # 소설 구성 흐름 스위치 — 작가가 소설로 옮길 대화 구간을 고르고(뺄 구간은 모델에 보내지 않는다) 구성안을 거쳐 화를 만드는
    # 흐름. 꺼져 있으면(기본값) 지금의 이어 쓰기 흐름(경계 제안·묶음 생성·연쇄)만 있다. 지금은 가격 응답의 같은 이름 칸만 이 값을
    # 따르고, 구간 선택·구성안 라우트를 더할 때 이 스위치 뒤에 둔다. 개정 처리방침 게시 뒤에 켠다.
    novelize_outline_flow_enabled: bool = False
    # 전체 구성안 한 판의 화 수 상한. 모델이 낸 화 수가 1 이상 이 값 이하가 아니면 실패·환불이고, 사용자가 고친 판도 이 안이어야
    # 한다. 프롬프트의 화 수 안내값(원문 분량 산식)도 이 값에서 자른다. 묶음 하나의 화 수 상한(`novelize_k_max_*`)과 다른 값이다 —
    # 구성안은 고른 대화 전체를 나누므로 묶음 하나보다 훨씬 많은 화가 된다. 구성안 원가·분포를 재기 전의 임시값.
    novelize_outline_max_episodes: int = Field(default=30, ge=1)
    # 전체 구성안 호출 한 번의 입력 견적 상한(토큰). 견적은 고른 원문 줄(include·맥락)의 글자 수를 토큰 수로 그대로 친 값이다 —
    # 글자당 토큰 비율을 아직 재지 않았다. 넘으면 모델을 부르기 전·차감 전에 "구간을 줄여 달라"로 거절한다(조용히 잘라 보내지
    # 않는다). 구성안 원가·입력 분포를 잰 뒤 견적 규칙과 함께 정하는 임시값.
    novelize_outline_max_input_tokens: int = Field(default=150_000, ge=1)
    # 여러 문단 수정 스위치 — 작가가 떨어진 문단 여럿(같은 장면 안)을 골라 한 번에 AI 수정을 맡기고 문단마다 수정안을 받는 흐름.
    # 꺼져 있으면(기본값) 새 요청이 404 이고 지금의 연속 범위 수정만 있다. 이미 만든 수정안의 목록은 꺼져 있어도 보인다. 개정
    # 처리방침 게시 뒤, 수정안 적용·버리기 라우트까지 배포한 뒤에 켠다.
    novelize_multi_block_edit_enabled: bool = False
    # 여러 문단 수정 한 번의 입력 견적 상한(글자). 견적은 모델에 보낼 문맥 문단(장면 있는 화는 그 장면, 없으면 화 전체)·작품 설정·
    # 설정 노트·지시의 글자 수 합이다. 넘으면 모델을 부르기 전·차감 전에 거절한다(조용히 잘라 보내지 않는다). 옛 연속 범위 수정이
    # 받는 화(직접 수정 본문 상한 10만 자)를 막지 않는 값으로 둔 임시값이고, 지연·원가를 잰 뒤 다시 정한다.
    novelize_block_edit_max_input_chars: int = Field(default=120_000, ge=1)
    # 여러 문단 수정 묶음 재검사(무과금 모델 호출)를 한 사용자가 한 시간에 몇 번까지 부를 수 있는지. 따로 적용할 수 없다는 판정을
    # 받은 묶음은 다시 물을 수 있어 이 상한이 유일한 제동이다. 면제 계정도 똑같이 센다. 재검사 원가를 재기 전의 임시값.
    novelize_recheck_hourly_limit: int = Field(default=10, ge=1)

    @field_validator(
        "novelize_grant_allowlist",
        "novelize_premium_model_allowlist",
        "novel_public_preview_allowlist",
        mode="before",
    )
    @classmethod
    def _split_novelize_grant_allowlist(cls, value: object) -> object:
        """env 문자열을 쉼표로 나눈다. 항목 앞뒤 공백은 지우고 빈 항목은 버린다. CORS 명단과 달리 남는 항목이
        없어도 오류가 아니다 — 빈 명단은 "아무에게도 허용하지 않음"이라는 정상 값이고 기본값이다. UUID 가 아닌
        항목은 pydantic 이 기동에서 거부한다."""
        if not isinstance(value, str):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    # 자가호스팅 Bugsink DSN. 비어 있으면 그 자체로 비활성이라
    # 별도 활성 플래그를 두지 않는다(플래그와 DSN 유무가 어긋나는 상태만 늘어나고 얻는 것이
    # 없다). `apps/api/.env`는 `.worktreeinclude`로 전 워크트리에 복사되므로 여기 실제 DSN을
    # 넣으면 dev·모든 워크트리가 같은 프로덕션 Bugsink로 이벤트를 쏜다 — 기본값은 항상
    # 빈 문자열로 둘 것(배포 환경에서만 값을 채운다).
    sentry_dsn: str = Field(default="", repr=False)
    # 프로덕션·dev를 가르는 값(DEPLOY.md: 스테이징 환경 없음).
    # 기본값 "development"는 DSN이 실수로 채워져도 이벤트가 dev로 표시되게 하는 안전장치다.
    sentry_environment: Literal["development", "production"] = "development"


settings = Settings()
