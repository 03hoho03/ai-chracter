"""어드민에서 켜고 끄는 기능 스위치 — 덮어쓰기가 있으면 그 값, 없으면 `.env`(`Settings`) 값.

덮어쓰기는 DB 표(`feature_switch_overrides`)가 소스다. 프로세스마다 그 표를 통째로 읽은 맵을 메모리에 두고 갱신 태스크가
`REFRESH_INTERVAL_SECONDS` 마다 갈아 끼운다 — 요청 경로에는 DB·Redis 왕복이 하나도 늘지 않는다. 다른 프로세스(api 의 다른
워커·다른 색·소설화 워커)의 저장은 길어야 약 그 간격 뒤에 보인다 — 갱신이 끝난 뒤 그 간격을 쉬므로 실제 간격은 여기에 한 번
읽는 시간과 이벤트 루프 지연이 더해진다. 저장한 프로세스는 커밋 직후 `refresh_switch_overrides` 를 불러 자기 맵을 바로 바꾼다.

**한 작업 안에서는 값이 섞이지 않는다.** 스위치는 한 요청·한 작업 안에서 여러 번 읽히고, 그 사이 맵이 바뀌어 앞뒤 값이 다르면
심사 비용을 쓴 뒤 거절하거나 환급을 빠뜨리는 식으로 깨진다. 그래서 HTTP 요청은 시작 순간의 맵을 `PinFeatureSwitches` 가,
소설화 워커 작업은 띄우는 순간의 맵을 `pinned_context` 가 컨텍스트 변수에 고정한다. 고정은 그 요청에서 이어지는 SSE
제너레이터·`BackgroundTasks`·스레드풀·`asyncio.create_task` 잡이 물려받는다 — 컨텍스트 복사로 전해지므로 제너레이터가 시작되기
**전에** 걸어야 한다(제너레이터 안에서 처음 걸면 그 값이 같은 요청의 `BackgroundTasks` 로 돌아가지 않는다).

**읽는 순서**(`switch_on`): 고정된 맵이 있으면 그 맵만 본다 → 없으면 프로세스 맵 → 맵에 이름이 없으면 그 순간의
`settings` 칸. `.env` 값은 맵에 복사하지 않고 호출 때마다 `settings` 에서 읽는다 — 테스트가 스위치를 바꾸는
`monkeypatch.setattr(settings, ...)` 가 덮어쓰기 없는 상태에서 그대로 먹게.

**갱신 실패**는 직전 맵을 그대로 쓰고 경고를 남긴다. `.env` 값으로 넘어가지 않는다 — 덮어쓰기로 켠 클로버 정지가 DB 장애 동안
조용히 풀리면 안 된다. 기동 때의 첫 적재 실패는 기동 실패다(api lifespan·워커 진입점이 이미 DB 를 요구한다).

**테스트**에서는 갱신 태스크가 돌지 않는다(api 테스트 클라이언트는 lifespan 을 보내지 않고, 워커 테스트는 루프를 직접 부른다)
— 그래서 맵은 비어 있고 모든 읽기가 `settings` 로 간다. `tests/conftest.py` 가 매 테스트 전에 맵과 고정을 비운다.
"""

import asyncio
import contextvars
import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, TypeGuard, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.feature_switch import FeatureSwitchOverride

logger = logging.getLogger(__name__)

# 어드민에서 켜고 끌 수 있는 스위치. 기동 때 한 번만 읽히거나, 켜는 데 키·워커 프로세스·크론 설치가 함께 필요한 스위치는
# 여기 없다(그것들은 `.env` 로만 바꾼다). 이름은 `Settings` 의 참/거짓 칸 이름 그대로다.
FeatureSwitchName = Literal[
    "memory_window_generation",
    "memory_window_ending_judgment",
    "memory_window_image_judgment",
    "memory_episodes_extract",
    "memory_facts_extract",
    "memory_episodes_recall",
    "memory_facts_inject",
    "memory_knowledge_filter",
    "memory_summary_secret_marking",
    "memory_items_visible",
    "stat_event_log",
    "memory_impressions_write",
    "memory_impressions_visible",
    "novelize_enabled",
    "novel_public_enabled",
    "novel_public_policy_v2_enabled",
    "novel_illustrations_enabled",
    "novelize_outline_flow_enabled",
    "novelize_multi_block_edit_enabled",
    "local_image_reference_enabled",
    "clover_ledger_paused",
    "payments_enabled",
    "identity_gate_enabled",
]
FEATURE_SWITCH_NAMES: tuple[FeatureSwitchName, ...] = get_args(FeatureSwitchName)

# 어드민 현황판이 값만 보이는 나머지 참/거짓 칸과, 버튼을 두지 않는 이유. 이유 문장은 화면이 코드별로 갖는다.
# - startup-check: 켤 때만 도는 기동 검증(자격·키)이 있어, 덮어쓰기로 켜면 그 검증을 건너뛴다.
# - worker-startup: 소설화 워커가 기동 때 한 번 읽어, 바꾸려면 워커 재기동과 기동 검증이 필요하다.
# - deploy-starts-worker: 교체 스크립트가 이 값을 보고 워커 컨테이너를 띄운다 — 워커 없이 켜면 작업이 만료 환불로 끝난다.
# - separate-cron-process: 월 확정 크론이 따로 뜬 프로세스에서 읽어 덮어쓰기를 보지 못하고, 켤 때 크론 설치가 함께 필요하다.
# - app-creation: 앱을 만들 때 한 번만 읽는다.
# - infrastructure: 기능이 아니라 쿠키 보안 인프라 설정이다.
ReadOnlySwitchReason = Literal[
    "startup-check",
    "worker-startup",
    "deploy-starts-worker",
    "separate-cron-process",
    "app-creation",
    "infrastructure",
]
ReadOnlyFeatureSwitchName = Literal[
    "chat_premium_models_enabled",
    "novelize_premium_models_enabled",
    "memory_embed_write",
    "memory_embed_recall",
    "llm_credential_pool_enabled",
    "novel_bible_enabled",
    "novelize_worker_enabled",
    "creator_payout_enabled",
    "expose_api_docs",
    "session_cookie_secure",
]
READ_ONLY_SWITCH_REASONS: Mapping[ReadOnlyFeatureSwitchName, ReadOnlySwitchReason] = MappingProxyType(
    {
        "chat_premium_models_enabled": "startup-check",
        "novelize_premium_models_enabled": "startup-check",
        "memory_embed_write": "startup-check",
        "memory_embed_recall": "startup-check",
        "llm_credential_pool_enabled": "startup-check",
        "novel_bible_enabled": "worker-startup",
        "novelize_worker_enabled": "deploy-starts-worker",
        "creator_payout_enabled": "separate-cron-process",
        "expose_api_docs": "app-creation",
        "session_cookie_secure": "infrastructure",
    }
)

# 갱신 사이에 쉬는 시간 — 다른 프로세스의 저장은 길어야 약 이만큼 뒤에 이 프로세스에 보인다(한 번 읽는 시간이 더해져 정확한
# 상한은 아니다). 소설화 워커의 폴링 기본 간격과 같다. 설정 칸으로 두지 않는다 — 운영에서 바꿀 일이 없고, 칸이 생기면 env 키
# 목록과 그 문서가 같이 늘어난다.
REFRESH_INTERVAL_SECONDS = 2.0

_NO_OVERRIDES: Mapping[FeatureSwitchName, bool] = MappingProxyType({})

# 이 프로세스의 덮어쓰기 맵. 고치지 않고 통째로 갈아 끼우므로, 고정해 둔 참조는 그 뒤의 갱신과 무관하게 그대로다.
_process_overrides: Mapping[FeatureSwitchName, bool] = _NO_OVERRIDES

# 지금 요청·작업에 고정된 맵. None 은 고정 없음 — 빈 맵을 고정한 것(시작 순간 덮어쓰기가 없었음)과 다르다.
_pinned: contextvars.ContextVar[Mapping[FeatureSwitchName, bool] | None] = contextvars.ContextVar(
    "feature_switch_overrides", default=None
)


def switch_on(name: FeatureSwitchName) -> bool:
    """스위치의 실효 값 — 고정된 맵이 있으면 그 맵만, 없으면 프로세스 맵, 어느 맵에도 이름이 없으면 지금의 `settings` 값."""
    overrides = _pinned.get()
    if overrides is None:
        overrides = _process_overrides
    override = overrides.get(name)
    if override is not None:
        return override
    value: bool = getattr(settings, name)
    return value


def is_switch_name(name: str) -> TypeGuard[FeatureSwitchName]:
    """어드민에서 켜고 끌 수 있는 스위치 이름인가."""
    return name in FEATURE_SWITCH_NAMES


async def refresh_switch_overrides(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """덮어쓰기 표를 통째로 읽어 프로세스 맵을 갈아 끼운다. 지운 행은 맵에서도 사라진다. 읽기가 실패하면 예외를 그대로 올리고
    맵은 그대로다(갈아 끼우기는 읽기가 끝난 뒤 한 번).

    이 코드가 모르는 이름의 행(다음 이미지에서 버튼 대상에서 빠진 스위치가 남긴 행)은 건너뛴다 — 그 스위치는 `.env` 값으로
    돈다. 주기 갱신과 저장 직후 갱신이 겹치면 늦게 끝난 쪽이 이기므로, 저장한 프로세스도 한 간격 동안 옛 맵을 볼 수 있다 —
    다른 프로세스와 같은 지연이다."""
    global _process_overrides
    async with session_factory() as db:
        rows = (await db.execute(select(FeatureSwitchOverride.name, FeatureSwitchOverride.value))).all()
    _process_overrides = MappingProxyType({name: value for name, value in rows if is_switch_name(name)})


async def keep_switch_overrides_fresh(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """`REFRESH_INTERVAL_SECONDS` 마다 프로세스 맵을 다시 읽는다. 첫 적재는 부르는 쪽이 이 태스크를 띄우기 전에 끝내므로 먼저
    기다린다. 실패해도 멈추지 않고 직전 맵으로 다음 간격을 기다린다. 취소로만 끝난다."""
    while True:
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        try:
            await refresh_switch_overrides(session_factory)
        except Exception as exc:
            logger.warning("기능 스위치 덮어쓰기를 다시 읽지 못했다 — 직전 값으로 계속한다: %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="db")


def pinned_context() -> contextvars.Context:
    """지금 컨텍스트를 복사해 이 순간의 프로세스 맵을 고정한 컨텍스트. 루프가 작업 태스크를 띄울 때
    `asyncio.create_task(..., context=pinned_context())` 로 넘기면 그 작업은 끝날 때까지 이 맵을 본다. 띄우는 쪽(루프)의
    컨텍스트는 바꾸지 않는다."""
    context = contextvars.copy_context()
    context.run(_pinned.set, _process_overrides)
    return context


class PinFeatureSwitches:
    """HTTP 요청마다 시작 순간의 프로세스 맵을 고정하고 요청이 끝나면 푼다. 응답 본문(SSE)과 `BackgroundTasks` 도 이 호출
    안에서 돌아 같은 고정을 본다. 순수 ASGI 미들웨어다 — `BaseHTTPMiddleware` 는 안쪽 앱을 별도 태스크에서 돌리고 응답 본문을
    자기 스트림으로 옮겨 실어 SSE 응답 사이에 층을 하나 더 끼우는데, 값 하나를 고정했다 푸는 데는 그 층이 필요 없다. I/O 가
    없어 헬스체크도 그대로 지난다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _pinned.set(_process_overrides)
        try:
            await self.app(scope, receive, send)
        finally:
            _pinned.reset(token)
