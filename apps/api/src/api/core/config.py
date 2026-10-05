import json
import uuid
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    # 옮길 수 있게 셋으로 나눈다. 어느 호출이 어느 종류인지는 `llm/client.py` 의 call_site 집합이 정한다.
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
    # 제안은 턴 번호 몇 개를 고르는 판정이라 `gemini_model_name` 으로 간다 — 어느 호출이 어느 쪽인지는 `llm/client.py`
    # 의 소설화 call_site 집합이 정한다. 모델명이 비면 `gemini_model_name` 으로 돈다.
    gemini_novelize_model_name: str = "gemini-3.5-flash"
    # 사고 토큰과 본문이 나눠 쓰는 예산이다(위 `gemini_max_output_tokens` 주석). 장 하나는 수천 자에 사고 토큰이 본문보다
    # 많이 붙어 채팅 상한으로는 잘린다. 여기서 잘린 장은 실패로 끝나고 환불되므로 낮게 잡으면 원가만 버린다.
    gemini_novelize_max_output_tokens: int = 32_768
    # 사고 설정. 둘 다 None 이면 thinking_config 를 넘기지 않는다(모델 기본 사고 동작). 정한 것만 넘긴다 — 예산은
    # 위 `gemini_thinking_budget` 과 같은 뜻이고, 수준은 사고형 모델이 받는 단계 이름이다.
    gemini_novelize_thinking_budget: int | None = None
    gemini_novelize_thinking_level: Literal["MINIMAL", "LOW", "MEDIUM", "HIGH"] | None = None
    # 소설화 호출 상한(ms). 백그라운드 작업이라 Cloudflare 응답 상한(100초)과 무관하다. 장 생성은 스트리밍이라 "다음
    # 청크까지"의 상한이고, 문단 수정·경계 제안은 비스트리밍이라 호출 전체의 상한이다. 경계 제안은 사용자가 화면에서
    # 기다리므로 짧게 끊는다.
    gemini_novelize_chapter_timeout_ms: int = 300_000
    gemini_novelize_revise_timeout_ms: int = 120_000
    gemini_novelize_boundary_timeout_ms: int = 30_000

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
    # 에서 장 생성 호출의 타임아웃(`gemini_novelize_chapter_timeout_ms`)은 스트리밍의 청크 사이 읽기 상한이라, 꾸준히
    # 흘러나오는 긴 장의 전체 시간을 끊는 것은 이 작업 상한 하나뿐이다. 그 호출 타임아웃은 첫 청크 전(또는 청크 사이)에
    # 오래 멈춘 경우에만 먼저 난다. 넘기면 실패·환불하고, 취소된 호출의 토큰 사용량은 기록되지 않는다. 임시값.
    novelize_job_timeout_seconds: float = 360
    # 장 본문이 이보다 짧으면(글자 수, 앞뒤 공백 제외) 정상 종료였어도 실패·환불한다. 출력 토큰 1개로 끝난 장이 실제로
    # 나왔다. 200자는 측정으로 정한 값이 아니라 그런 몇 글자짜리 장을 거르려고 넉넉히 낮게 잡은 임시 하한이다 — 짧은
    # 응답 한 턴만 담은 정상 장이 이 아래로 나올 수도 있어서, 본 시험에서 정상 장의 최단 길이를 보고 다시 정한다.
    novelize_min_chapter_chars: int = 200
    # 다음 장 생성에 싣는 직전 장 끝 발췌의 목표 길이(글자). 문단 단위로 잘라 이 길이에 가장 가까운 만큼 싣는다.
    # 앞 장을 되풀이하지 않고 이어 쓰게 하려는 것이다. 임시값.
    novelize_previous_excerpt_chars: int = 1000
    # 장 하나가 담을 수 있는 원문 턴(AI 응답) 수의 상한. 다음 장 경계 제안은 이 수만큼의 후보 턴을 보여 주고, 장 생성은
    # 끝 메시지가 이 범위 밖이면 거절한다. 장이 길수록 출력 상한·작업 상한에 가까워지므로 본 시험에서 다시 정하는 임시값
    # 이다(가능성 확인에서 쓴 후보 범위가 12턴이었다).
    novelize_chapter_max_turns: int = 12
    # 장 경계 제안(무과금 모델 호출)을 한 사용자가 한 시간에 몇 번까지 부를 수 있는지. 과금이 없어 남용을 막는 것이
    # 이 상한뿐이다. 면제 계정도 똑같이 센다. 임시값.
    novelize_proposal_hourly_limit: int = 30

    @field_validator("novelize_grant_allowlist", mode="before")
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
