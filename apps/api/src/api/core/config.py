from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # secure-issue-goal-prompt.md SEC-9: 비밀 5종(`database_url`·`google_client_secret`·
    # `gemini_api_key`·`local_image_access_client_secret`·`resend_api_key`)은 `Field(repr=False)`로
    # repr에서 뺀다 — `monkeypatch.setattr(settings, "오타", ...)`가 내는
    # `AttributeError(f"{target!r} has no attribute ...")` 메시지에 전 필드 repr이 실려 비밀이
    # 평문으로 찍히기 때문이다. 값이 traceback이 아니라 **예외 메시지 자체**에 있어 pytest
    # `--tb` 옵션으로는 못 막는다. 타입은 `str` 그대로다(`SecretStr` 전환은 별건).
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_character_chat",
        repr=False,
    )
    redis_url: str = "redis://localhost:6379/0"

    # local-image-gen-goal-prompt.md LG-11: 프로덕션은 스키마 전수 노출을 막는다 — 안전한
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

    # techspec-backend-auth.md §2: admin sessions use a separate cookie name (and,
    # in api/admin/session.py, a separate Redis key prefix) so they never collide
    # with a regular user's session cookie.
    admin_session_cookie_name: str = "admin_session_id"

    cors_allow_origins: list[str] = ["http://localhost:5173", "http://localhost:5174"]

    aws_region: str = "ap-northeast-2"
    s3_bucket_name: str = "ai-character-chat-assets-dev"
    s3_presigned_url_expires_seconds: int = 900
    # Overridden for local dev/tests to point at a non-AWS S3-compatible endpoint
    # (e.g. `uv run moto_server`); left unset in real AWS environments.
    s3_endpoint_url: str | None = None

    # Not specified by techspec-backend-auth.md (only the 60s resend cooldown is) —
    # a reasonable default for how long an issued email verification code stays usable.
    email_verification_code_ttl_seconds: int = 60 * 15
    email_verification_resend_cooldown_seconds: int = 60

    # legal-revision-goal-prompt.md LR-8: 탈퇴 시 users.email이 자리표시자로 바뀌므로(LR-6),
    # 재가입 차단은 이 키로 만든 HMAC-SHA256(withdrawn_emails.email_hmac)을 조회해서 한다.
    # 키를 잃거나(배포 환경마다 값이 달라지는 등) 바꾸면 과거에 적립한 해시와 새 조회의 해시가
    # 어긋나 재가입 차단이 조용히 멈춘다(모든 조회가 미스) — DEPLOY.md에 남긴다.
    withdrawn_email_hmac_key: str = ""
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

    # techspec-backend-auth.md: password reset tokens expire 1 hour after issuance.
    password_reset_token_ttl_seconds: int = 60 * 60

    # techspec-overview-backend.md §5: Gemini 2.5 LLMClient 구현체 (US-050).
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model_name: str = "gemini-2.5-flash"
    # ⚠️ 아래 실측은 전부 **현행 기본 모델이 아닌 모델**(gemini-3.5-flash·flash-lite)에서 나왔다
    # — 현행 기본값은 바로 위 `gemini_model_name`(gemini-2.5-flash)이다. 근거로는 쓰되 현행
    # 모델에서 재현된 값은 아니다(secure-issue-goal-prompt.md SEC-8).
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
    # 않는다.
    gemini_thinking_budget: int | None = None
    # tasks/chat-techspec.md §3-1: 회차 재현성을 위한 결정적 시드. None = seed 를 아예 안
    # 넘김(현재와 동일한 매 회차 난수 동작). generate()에만 붙인다 — generate_structured()
    # (판단 호출)는 이 런의 측정 대상이 아니다.
    gemini_seed: int | None = None
    # tasks/chat-techspec.md §3-5(D-21·D-22): 조립된 프롬프트를 회차 재현용으로 JSONL에
    # 남길 파일 경로. None = 아무 일도 안 함(프로덕션 기본값이자 방어) — 프롬프트에는
    # 창작자의 비공개 설정이 들어 있어 기본으로 켜지면 안 된다.
    prompt_dump_path: str | None = None
    # tasks/archive/prd-image-generation.md §3/US-003: 생성 잡 Redis 레코드 TTL(확정값 1시간).
    image_generation_job_ttl_seconds: int = 60 * 60

    # local-image-gen-goal-prompt.md/techspec §5(LT-13): 집 PC 자가 호스팅 이미지 생성
    # 서버. 호스트명에 모델 힌트를 넣지 않는다(LC-14) — DNS 레코드와 CT 로그는 공개다.
    local_image_base_url: str = ""
    # local-image-gen-goal-prompt.md LG-5: Cloudflare Access 서비스 토큰.
    local_image_access_client_id: str = ""
    local_image_access_client_secret: str = Field(default="", repr=False)
    # DEPLOY.md §5 실측: 정상 생성은 17~20초지만 종횡비 버킷 전환 직후 첫 요청이 27~34초다
    # (`torch.backends.cudnn.benchmark`가 그 해상도의 커널을 처음 탐색·캐시하는 비용) — 45초가
    # 아니라 90초인 이유가 이 값이다. 상한 쪽 제약은 그대로 살아 있다: VM은 Cloudflare Tunnel로
    # 집 PC에 도달하므로(DEPLOY.md §5) edge 타임아웃(무료 플랜 100초로 알려짐, 아직 실측 없음)
    # 미만이어야 한다.
    local_image_timeout_seconds: int = 90
    # 잠정값 — 복구 감지 속도와 프로브 빈도의 타협(LG-18: 콜드/만료 시에만 프로브).
    local_image_capabilities_ttl_seconds: int = 30
    # 잠정값 — 잡당 최대 60초(count<=2, LG-7) 기준 최악 대기 약 4분(LT-3).
    local_image_queue_limit: int = 4
    # local-image-gen-goal-prompt.md LG-19: 공개 id(FE 노출, `v1`)와 홈PC의 실제
    # 체크포인트 id(와이어 id)가 다를 수 있다. 원 요구가 "코드상이나 endpoint나
    # payload로 모델을 유추할 수 없게"이므로 실제 와이어 값을 이 소스에 박으면 그 요구를
    # 어긴다 — 실제 값은 VM `.env`에만 두고 이 저장소엔 없다.
    # 기본값을 공개 id와 같게 두어 env 없이 테스트·로컬 개발이 그대로 동작한다.
    #
    # image-style-7-goal-prompt.md IS-2: style 축은 이 분리를 두지 않는다 — 공개 id와
    # 와이어 id가 같아 `local_image.py`가 `style.value`를 그대로 싣는다. model 축만
    # 분리를 유지하는 이유는 IS-2 참고(model 축은 실제로 다른 와이어 값을 가렸지만
    # style 축은 지금까지 아무것도 보호한 적이 없다).
    local_image_model_wire_id: str = "v1"

    # techspec-builder-common.md §3: 빌더 미리보기 세션(Redis 전용, Postgres 미기록)의
    # 마지막 활동 기준 TTL — 확정값 24시간.
    preview_session_ttl_seconds: int = 60 * 60 * 24

    # tasks/archive/prd-view-count.md: 조회수 중복 제거용 게스트 뷰어 쿠키. 쿠키 수명은
    # 중복 제거 TTL보다 반드시 길어야 한다(짧으면 쿠키 재발급 = 새 뷰어로 잡혀
    # TTL 창 안에서 같은 사람이 두 번 세어진다).
    guest_viewer_cookie_name: str = "guest_viewer_id"
    guest_viewer_cookie_max_age_seconds: int = 60 * 60 * 24 * 365
    content_view_dedup_ttl_seconds: int = 60 * 60 * 24

    # email-goal-prompt.md E-3: 프로바이더는 env 스위치, 기본값은 콘솔 — 로컬 개발/pytest가
    # 실수로 실제 메일을 쏘는 사고를 원천 차단한다.
    email_provider: Literal["console", "resend"] = "console"
    # email-goal-prompt.md E-1: Resend REST API(https://api.resend.com/emails) 인증 토큰.
    resend_api_key: str = Field(default="", repr=False)
    # email-goal-prompt.md E-4: 발신 주소. ddona.site 도메인이 Resend에서 검증돼야 이 주소로
    # 실제 발신이 나간다(§5의 사용자 액션).
    email_from: str = "noreply@ddona.site"

    # prompt-db-goal-prompt.md §8-1: 활성 프롬프트 세트 캐시(`prompt_set:active`)의 TTL.
    # `invalidate_active_prompt_set()`의 명시적 DEL이 무효화의 정공법이라 이 값은 주 수단이
    # 아니라 그 DEL이 누락되는 경로가 생겼을 때의 상한이다. 게시는 드문 관리자 작업이라 짧을
    # 이유가 없고, 반대로 DEL이 어떤 이유로든 안 불리면 옛 문안이 그만큼 오래 남으므로 무한정
    # 길게 둘 수도 없다 — 5분이면 무효화가 깨져도 운영자가 재게시 확인을 오래 기다리지 않는다.
    prompt_set_cache_ttl_seconds: int = 60 * 5

    # monitoring-techspec.md MT-4: 자가호스팅 Bugsink DSN. 비어 있으면 그 자체로 비활성이라
    # 별도 활성 플래그를 두지 않는다(플래그와 DSN 유무가 어긋나는 상태만 늘어나고 얻는 것이
    # 없다). `apps/api/.env`는 `.worktreeinclude`로 전 워크트리에 복사되므로 여기 실제 DSN을
    # 넣으면 dev·모든 워크트리가 같은 프로덕션 Bugsink로 이벤트를 쏜다 — 기본값은 항상
    # 빈 문자열로 둘 것(배포 환경에서만 값을 채운다).
    sentry_dsn: str = Field(default="", repr=False)
    # monitoring-techspec.md MT-4: 프로덕션·dev를 가르는 값(DEPLOY.md: 스테이징 환경 없음).
    # 기본값 "development"는 DSN이 실수로 채워져도 이벤트가 dev로 표시되게 하는 안전장치다.
    sentry_environment: Literal["development", "production"] = "development"


settings = Settings()
