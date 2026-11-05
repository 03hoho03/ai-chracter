"""Claude 자격 목록의 런타임 읽기 — 호출마다 목록 스냅숏을 읽어 그 모델 축의 후보를 위치 순으로 고르고, 후보의 키를 프로세스
안에서 복호화한다. 목록을 쓸지(스위치), 후보마다 요청을 보내고 거절을 다루는 일은 부르는 쪽(`llm/anthropic_api.py`)이 한다.

- **스냅숏**은 설정 행(목록 사용 칸)·항목 전부·항목마다 받을 수 있는 축이다. Redis 키 하나에 JSON 으로 두고 세대 번호 키와
  함께 한 번(MGET)에 읽는다. 히트면 왕복 한 번, 미스면 MGET + DB(설정 행·항목·확인 기록) + SET 이다.
- **무효화는 세대 번호(INCR)**다. 미스는 DB 를 읽기 **전에** 읽은 세대를 스냅숏에 적고, 읽을 때 지금 세대와 다르면 버린다 — 키를
  지우는 무효화로는 "미스가 옛 DB 를 읽는 동안 무효화가 지나간 뒤 옛 값을 SET"하는 경합에서 낡은 스냅숏이 캐시 수명 동안 남고,
  운영자가 키 유출로 끈 항목이 그동안 쓰인다. 무효화는 반드시 커밋 뒤에 부른다(어드민 쓰기·재암호화 실행기·런타임 소진 표시).
- **Redis 장애**(오류·0.1초 초과)면 DB 를 바로 읽는다 — env 키 경로로 떨어지면 목록 맨 아래(env 키와 같은 계정)가 장애마다
  조용히 쓰이고, 그 계정이 소진이면 다른 계정에 크레딧이 있어도 실패한다. 세대 없이 읽은 값은 캐시에 쓰지 않는다. DB 도 읽지
  못하면 원인을 단 `LLMClientError`(환불 경로)다. 공용 Redis 클라이언트에 소켓 시간 초과가 없어 상한을 따로 건다.
- **비밀은 스냅숏에 없다** — 키 원문·끝 4자리를 싣지 않고, 암호문(base64)·키 id 만 실어 프로세스 안에서 복호화한다. 원문은 그
  프로세스의 SDK 클라이언트 안에만 산다(Redis 의 디스크 기록에 남지 않게). 나머지 칸(라벨·위치·상태 판·지문·조직 id·받는 축·
  충전액)은 후보 판정·소진 표시 조건·알림·사용액에 호출마다 필요한 비밀이 아닌 값이다.
- 세션은 부를 때마다 팩토리로 짧게 열고 닫는다 — 요청 세션에 기대지 않아 소설화 워커·SSE 제너레이터 안에서도 같다. 기본 풀은
  api 와 같은 세션 팩토리·Redis 를 써서 워커도 같은 스냅숏·세대를 본다.
- **소진 표시**는 조건부 UPDATE(아직 켜짐 + 그 요청이 쓴 키의 지문 + 그 요청이 본 상태 판)라 같은 거절이 여러 요청·프로세스에서
  와도 한 번만 바뀌고, 바꾼 쪽만 세대를 올리고 알린다. 키를 바꾸거나 끄고 다시 켠 뒤 도착한 늦은 거절은 0행이다. 표시·무효화·
  알림은 참조를 쥔 태스크 하나로 돌고 부르는 쪽은 방패 너머로 상한까지만 기다린다.
- **알림**은 쏘고 잊는다(`llm/credential_notify.py`). 후보 없음은 그 요청의 소진 표시가 끝난 뒤의 세대·축으로, 읽을 수 없는 키는
  (항목, 지문, 키 id)로 Redis 표지를 세워 같은 상태가 이어지는 동안 한 번만 보낸다.
"""

import asyncio
import base64
import logging
import uuid
from collections.abc import Callable, Coroutine, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.field_crypto import FieldDecryptError
from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure
from api.db.models.llm_credential import ClaudeModelAxis, LlmCredential, LlmCredentialCheck, LlmCredentialSettings
from api.llm.claude_messages import claude_error
from api.llm.client import LLMClientError
from api.llm.credential_accounts import AccountProvider
from api.llm.credential_notify import spawn_credential_notification, spawn_credential_notification_once
from api.llm.credential_usage import SpendTarget
from api.llm.credentials import (
    CLAUDE_AXES,
    CREDENTIAL_KEY_PREFIX,
    CredentialStoreError,
    RejectionKind,
    account_in_allowlist,
    classify_anthropic_rejection,
    allowed_accounts,
    credential_keyring,
    credential_write,
    decrypt_stored_secret,
    is_env_key,
    passed_axes,
)
from api.llm.usage_store import RECORD_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = f"{CREDENTIAL_KEY_PREFIX}pool:snapshot"
GENERATION_KEY = f"{CREDENTIAL_KEY_PREFIX}pool:generation"
# Redis 왕복 하나의 상한. 사용량 기록과 같은 근거(같은 VM 의 도커 네트워크라 정상 왕복은 1ms 안팎)·같은 값이다.
REDIS_TIMEOUT_SECONDS = RECORD_TIMEOUT_SECONDS

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# 소진 표시를 부르는 쪽이 기다리는 상한. DB 가 느려도 다음 항목으로 다시 보내는 일이 이만큼보다 밀리지 않는다. 보통은 이 안에
# 끝나 요청이 끝날 때 DB·세대가 이미 바뀌어 있다(다른 프로세스가 결정적으로 본다). 표시 자체는 상한과 무관하게 끝까지 돈다.
MARK_TIMEOUT_SECONDS = 1.0
# 후보 없음·읽을 수 없는 키 알림의 중복 억제 수명 — 같은 상태가 하루 넘게 이어지면 하루에 한 번 다시 알린다.
_STATE_ALERT_SECONDS = 24 * 60 * 60
_ALERT_KEY_PREFIX = f"{CREDENTIAL_KEY_PREFIX}alert:"
# 소진 사유마다 (알림의 사유, 운영자가 할 일).
_EXHAUSTION_REASONS: dict[RejectionKind, tuple[str, str]] = {
    "credit": ("크레딧 부족", "충전한 뒤 확인 호출 → 켜기"),
    "auth": ("키 무효 또는 조직 비활성", "키를 교체하거나 지운다"),
    "limit": ("사용 한도 도달", "한도가 풀린 뒤(월 상한은 다음 달 1일 00:00 UTC) 확인 호출 → 켜기"),
}
# 쏘고 잊은 표시·알림 태스크의 참조(알림 모듈과 같은 꼴) — 참조가 없으면 끝나기 전에 사라질 수 있다.
_pending: set[asyncio.Task[None]] = set()


def _spawn(coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    task = asyncio.create_task(coroutine)
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


class PoolCredential(BaseModel):
    """스냅숏의 항목 하나. 값을 Literal 로 좁히지 않는다 — 지금 코드가 모르는 공급자·상태가 한 행에 있다고 역직렬화가 통째로
    터지면 안 된다(그런 행은 후보 판정이 거른다)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    provider: str
    label: str
    position: int
    state: str
    # 소진 표시의 조건부 UPDATE 가 "그 요청이 본 상태"로 쓴다.
    state_version: int
    # 소진 표시 조건(그 요청이 쓴 키)이자 프로세스 안 SDK 클라이언트 캐시 키.
    secret_fingerprint: str
    key_id: str
    # 암호문 바이트의 표준 base64.
    ciphertext: str
    account_ref: str | None
    # 그 항목이 받을 수 있는 축(축 순서). 스냅숏을 만들 때 확인 기록으로 계산한다(`credentials.passed_axes`).
    passed_axes: tuple[str, ...]
    credit_micro_usd: int | None
    credit_since: datetime | None
    alert_pct: int

    @property
    def client_key(self) -> tuple[uuid.UUID, str]:
        """프로세스 안 SDK 클라이언트 캐시 키. 키를 바꾸면 지문이 바뀌어 새 클라이언트를 만들고, 키링 회전은 값이 같아 지문도
        같으므로 같은 클라이언트를 계속 쓴다."""
        return (self.id, self.secret_fingerprint)

    @property
    def subject(self) -> str:
        """알림 문구의 앞머리 — 공급자·라벨·지문만(키·끝 4자리·조직 id 는 싣지 않는다)."""
        return f"{self.provider} · {self.label} · 지문 {self.secret_fingerprint}"

    @property
    def spend_target(self) -> SpendTarget:
        return SpendTarget(
            id=self.id,
            label=self.label,
            fingerprint=self.secret_fingerprint,
            credit_micro_usd=self.credit_micro_usd,
            credit_since=self.credit_since,
            alert_pct=self.alert_pct,
        )


class PoolSnapshot(BaseModel):
    """목록 스냅숏. `generation` 은 DB 를 읽기 전에 읽은 세대이고, Redis 를 읽지 못해 DB 를 바로 읽었으면 None 이다(캐시에 쓰지
    않는다)."""

    generation: int | None
    pool_enabled: bool
    credentials: list[PoolCredential]


@dataclass(frozen=True)
class PoolPlan:
    """호출 한 번의 계획 — 그 축의 후보(위치 순)와, 프로세스 안 SDK 클라이언트 캐시에 남겨도 되는 키(스냅숏의 켜진 Anthropic
    항목). 끄기·소진·삭제·키 교체가 다음 호출의 계획에서 그 항목의 클라이언트를 버리게 한다."""

    candidates: list[PoolCredential]
    live_keys: frozenset[tuple[uuid.UUID, str]]


# ── 후보 판정 ───────────────────────────────────────────────────────────────────
def to_pool_credential(row: LlmCredential, checks: Sequence[LlmCredentialCheck]) -> PoolCredential:
    """DB 행과 그 항목의 확인 기록 전부를 스냅숏 항목으로 옮긴다."""
    axes = passed_axes(row, checks)
    return PoolCredential(
        id=row.id,
        provider=row.provider,
        label=row.label,
        position=row.position,
        state=row.state,
        state_version=row.state_version,
        secret_fingerprint=row.secret_fingerprint,
        key_id=row.key_id,
        ciphertext=base64.b64encode(row.secret_ciphertext).decode(),
        account_ref=row.account_ref,
        passed_axes=tuple(axis for axis in CLAUDE_AXES if axis in axes),
        credit_micro_usd=row.credit_micro_usd,
        credit_since=row.credit_since,
        alert_pct=row.alert_pct,
    )


def pool_candidates(
    credentials: Iterable[PoolCredential],
    axis: ClaudeModelAxis,
    allowed: frozenset[tuple[AccountProvider, str]],
) -> list[PoolCredential]:
    """그 축으로 보낼 수 있는 항목(위치 순): Anthropic 이고, 켜져 있고, 조직이 확인돼 지금 프로세스의 허용 목록 안이고, 그 축을
    받는다. 허용 목록은 부르는 쪽이 지금 env 로 넘긴다 — 허용 목록에서 조직을 빼고 재기동하면 그 항목은 바로 빠진다. 켜진 뒤
    확인 때의 상태 판은 보지 않는다(받는 축 계산이 이미 그렇게 정했다)."""
    return sorted(
        (
            credential
            for credential in credentials
            if credential.provider == "anthropic"
            and credential.state == "active"
            and credential.account_ref is not None
            and account_in_allowlist("anthropic", credential.account_ref, allowed)
            and axis in credential.passed_axes
        ),
        key=lambda credential: credential.position,
    )


# ── 스냅숏 캐시 ──────────────────────────────────────────────────────────────────
async def _read_from_db(session_factory: SessionFactory, *, generation: int | None) -> PoolSnapshot:
    """설정 행(없으면 꺼짐)·항목 전부(위치 순)·그 항목들의 확인 기록 전부를 짧은 세션 하나로 읽는다. 확인 기록을 전부 읽는 것은
    "축마다 최신"을 켜기 조건과 같은 함수로 고르기 위해서다(확인은 항목마다 분당 한 번이라 행이 적고, 스냅숏은 무효화·캐시 수명
    때만 다시 만든다). 읽지 못하면 원인을 단 `LLMClientError`."""
    try:
        async with session_factory() as db:
            pool_enabled = await db.scalar(
                select(LlmCredentialSettings.pool_enabled).where(LlmCredentialSettings.id == 1)
            )
            rows = list(await db.scalars(select(LlmCredential).order_by(LlmCredential.position)))
            checks: dict[uuid.UUID, list[LlmCredentialCheck]] = {row.id: [] for row in rows}
            if rows:
                for check in await db.scalars(
                    select(LlmCredentialCheck).where(LlmCredentialCheck.credential_id.in_(list(checks)))
                ):
                    checks[check.credential_id].append(check)
    except Exception as exc:
        raise claude_error(LLMClientError, "Claude 자격 목록을 읽지 못했다", "anthropic") from exc
    return PoolSnapshot(
        generation=generation,
        pool_enabled=bool(pool_enabled),
        credentials=[to_pool_credential(row, checks[row.id]) for row in rows],
    )


def _parse(raw: str | bytes | None) -> PoolSnapshot | None:
    if raw is None:
        return None
    try:
        return PoolSnapshot.model_validate_json(raw)
    except ValidationError:
        # 미스로 본다 — 값의 형식을 바꾼 배포가 겹치는 동안 옛 형식 값 때문에 호출이 실패하지 않고 한 번 다시 읽어 갈아 쓴다.
        logger.warning("Claude 자격 목록 캐시 값의 형식이 다르다 — DB 에서 다시 읽어 갈아 쓴다")
        return None


async def _store(redis: Redis, snapshot: PoolSnapshot) -> None:
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            # 캐시 수명은 배정 표 캐시와 같은 설정이다 — 무효화가 정공법이고 수명은 무효화가 빠진 경로의 안전망이다.
            await redis.set(SNAPSHOT_KEY, snapshot.model_dump_json(), ex=settings.prompt_set_cache_ttl_seconds)
    except Exception as exc:
        logger.warning("Claude 자격 목록 캐시 저장 실패 — 이번 호출은 이미 읽은 값으로 계속한다", exc_info=True)
        capture_dependency_failure(exc, dependency="redis")


async def load_pool_snapshot(session_factory: SessionFactory, redis: Redis) -> PoolSnapshot:
    """스냅숏 하나. 히트면 MGET 한 번, 미스면 MGET + DB + SET. Redis 가 실패하거나 상한 안에 답하지 않으면 DB 를 바로 읽는다."""
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            raw, raw_generation = await redis.mget(SNAPSHOT_KEY, GENERATION_KEY)
        generation = int(raw_generation or 0)
    except Exception as exc:
        logger.warning("Claude 자격 목록 캐시 조회 실패 — DB 를 바로 읽는다", exc_info=True)
        capture_dependency_failure(exc, dependency="redis")
        return await _read_from_db(session_factory, generation=None)
    cached = _parse(raw)
    if cached is not None and cached.generation == generation:
        return cached
    snapshot = await _read_from_db(session_factory, generation=generation)
    await _store(redis, snapshot)
    return snapshot


async def invalidate_pool_snapshot(redis: Redis | None = None) -> None:
    """세대를 올려 이미 저장된 스냅숏을 버리게 한다. 반드시 **커밋 뒤**에 부른다. Redis 오류·상한 초과(`TimeoutError`)는 삼키지
    않는다 — 옛 스냅숏이 캐시 수명만큼 나가는 것을 감수할지는 부르는 쪽이 정한다."""
    async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
        await (redis if redis is not None else redis_client).incr(GENERATION_KEY)


# ── 풀 ──────────────────────────────────────────────────────────────────────────
class CredentialPool:
    """호출 경로가 쓰는 목록 읽기. 프로세스마다(구현 인스턴스마다) 하나를 두고, 복호화하지 못한 항목을 경고했는지를 기억한다.
    세션 팩토리·Redis 를 주지 않으면 api 와 같은 모듈 전역을 쓴다 — 세션 팩토리는 처음 쓸 때 가져온다(구현 모듈을 import 하는
    스크립트가 import 만으로 DB 엔진을 만들지 않게)."""

    def __init__(self, *, session_factory: SessionFactory | None = None, redis: Redis | None = None) -> None:
        self._session_factory = session_factory
        self.redis: Redis = redis if redis is not None else redis_client
        self._unreadable: set[tuple[uuid.UUID, str, str]] = set()

    @property
    def session_factory(self) -> SessionFactory:
        if self._session_factory is None:
            from api.db.session import async_session_factory

            self._session_factory = async_session_factory
        return self._session_factory

    async def plan(self, axis: ClaudeModelAxis) -> PoolPlan | None:
        """그 축으로 보낼 계획. 목록 사용이 꺼져 있거나 목록에 행이 하나도 없으면(공급자·상태 무관) None — 부르는 쪽은 env 키
        경로로 간다. 행이 있으면 후보가 0 이어도 계획이다(env 키 경로로 떨어지지 않는다). 목록을 읽지 못하면 `LLMClientError`."""
        snapshot = await load_pool_snapshot(self.session_factory, self.redis)
        if not snapshot.pool_enabled or not snapshot.credentials:
            return None
        return PoolPlan(
            candidates=pool_candidates(snapshot.credentials, axis, allowed_accounts()),
            live_keys=frozenset(
                credential.client_key
                for credential in snapshot.credentials
                if credential.provider == "anthropic" and credential.state == "active"
            ),
        )

    def secret_of(self, credential: PoolCredential) -> str | None:
        """그 항목의 키 원문. 읽을 수 없으면(키링이 비었거나 그 키 id 가 없거나 암호문이 그 항목의 것이 아니면) None 이고 예외는
        밖으로 나가지 않는다 — 부르는 쪽은 그 항목을 건너뛴다. 같은 (항목, 지문, 키 id)는 프로세스에서 한 번만 경고한다."""
        try:
            return decrypt_stored_secret(
                credential_keyring(),
                credential_id=credential.id,
                key_id=credential.key_id,
                ciphertext=base64.b64decode(credential.ciphertext),
            )
        except (FieldDecryptError, ValueError):
            unreadable = (credential.id, credential.secret_fingerprint, credential.key_id)
            if unreadable not in self._unreadable:
                self._unreadable.add(unreadable)
                logger.warning(
                    "Claude 자격 목록 항목의 키를 읽을 수 없어 건너뛴다 — credential_id=%s 지문 %s 키 id %s",
                    credential.id,
                    credential.secret_fingerprint,
                    credential.key_id,
                )
                # 프로세스마다 한 번 쏘고, 프로세스 사이의 중복은 표지가 막는다.
                spawn_credential_notification_once(
                    f"{_ALERT_KEY_PREFIX}unreadable:{credential.id}:{credential.secret_fingerprint}:{credential.key_id}",
                    f"[Claude 자격] 저장한 키를 읽을 수 없어 건너뛴다 — {credential.subject} · 암호화 키 목록을 확인하거나 키를 "
                    "다시 붙여넣는다",
                    ttl_seconds=_STATE_ALERT_SECONDS,
                )
            return None

    # ── 소진 표시·알림 ──────────────────────────────────────────────────────────
    async def mark_exhausted(self, credential: PoolCredential, kind: RejectionKind) -> asyncio.Task[None]:
        """그 항목을 소진으로 표시한다. 표시(UPDATE·커밋)와 그 뒤 캐시 무효화·알림은 참조를 쥔 태스크 하나로 돌고, 부르는 쪽은
        방패 너머로 상한까지만 기다린다 — 커밋이 서버에 닿은 뒤 부르는 쪽이 취소되거나 상한에 걸려도 태스크가 무효화·알림까지
        끝낸다(부르는 코루틴 안에서 바로 커밋을 기다리면 그 둘이 사라지고, 뒤 요청은 0행이라 아무도 다시 알리지 않는다). 절대
        raise 하지 않는다(부르는 쪽의 취소는 그대로 올라간다). 돌려준 태스크는 후보 없음 알림이 기다린다."""
        task = _spawn(self._exhaust(credential, kind))
        try:
            async with asyncio.timeout(MARK_TIMEOUT_SECONDS):
                await asyncio.shield(task)
        except TimeoutError:
            logger.warning("Claude 자격 소진 표시가 상한 안에 끝나지 않아 기다리지 않고 다음 항목으로 간다")
        return task

    async def mark_if_rejected_mid_stream(self, credential: PoolCredential, exc: BaseException) -> None:
        """스트림이 열린 뒤 온 오류. 재시도는 하지 않는다(글이 이미 나갔을 수 있고, 끊어도 과금된다). 다만 그 오류가 소진으로 볼
        거절이면(상태 200 에서 분류가 값을 내는 갈래는 결제 오류 종류뿐이다) 그 항목을 소진으로 표시해 다음 요청이 다음 항목으로
        가게 한다 — 소진이 스트림 오류로만 온다면 생성이 매 턴 실패하는데 판정은 생성 실패로 돌지 않아 아무도 표시하지 않는다."""
        kind = classify_anthropic_rejection(exc)
        if kind is not None:
            await self.mark_exhausted(credential, kind)

    async def _exhaust(self, credential: PoolCredential, kind: RejectionKind) -> None:
        """그 요청이 쓴 키(지문)·그 요청이 본 상태 판이 그대로이고 아직 켜져 있을 때만 바꾼다 — 다른 프로세스가 먼저 표시했거나 그
        사이 키를 바꾸거나 끄고 다시 켰으면 0행이라 아무것도 하지 않는다. 판을 올리는 것은 어드민 상태 변경과 같은 뜻이다(그 전의
        확인은 다시 켜기에 세지 않는다). 1행을 바꿨을 때만 커밋 뒤에 세대를 올리고 알린다. 절대 raise 하지 않는다."""
        statement = (
            update(LlmCredential)
            .where(
                LlmCredential.id == credential.id,
                LlmCredential.state == "active",
                LlmCredential.secret_fingerprint == credential.secret_fingerprint,
                LlmCredential.state_version == credential.state_version,
            )
            .values(
                state="exhausted",
                state_reason=kind,
                state_version=LlmCredential.state_version + 1,
                state_changed_at=func.now(),
                updated_at=func.now(),
            )
            .returning(LlmCredential.id)
            .execution_options(synchronize_session=False)
        )
        try:
            async with self.session_factory() as db:
                # 이 표에 쓰는 문장의 DB 오류는 그 행 전체(암호문)를 싣는다 — 클래스 이름·SQLSTATE 만 남는 오류로 바꾼다.
                async with credential_write(db):
                    changed = (await db.execute(statement)).scalar_one_or_none() is not None
                    await db.commit()
        except Exception as exc:
            # 거절은 사실이라 부르는 쪽은 다음 항목으로 간다. 남기는 것은 클래스 이름(자격 표 쓰기 실패면 SQLSTATE 까지)뿐이다.
            logger.warning(
                "Claude 자격 소진 표시 실패: %s", exc if isinstance(exc, CredentialStoreError) else type(exc).__name__
            )
            capture_dependency_failure(exc, dependency="db")
            return
        if not changed:
            return
        try:
            await invalidate_pool_snapshot(self.redis)
        except Exception as exc:
            logger.warning(
                "Claude 자격 소진 표시 뒤 캐시 무효화 실패 — 캐시 수명 동안 다른 프로세스가 그 항목에 먼저 보낸다: %s",
                type(exc).__name__,
            )
            capture_dependency_failure(exc, dependency="redis")
        spawn_credential_notification(_exhaustion_message(credential, kind))

    def alert_no_candidate(self, axis: ClaudeModelAxis, *, after: Sequence[asyncio.Task[None]]) -> None:
        """그 축으로 보낼 항목이 없다고 알린다 — 쏘고 잊는다(부르는 쪽은 Redis 도 기다리지 않는다). 표지는 그 요청의 소진 표시
        (`after`)가 끝난 뒤의 세대다: 계획을 만들 때의 세대를 쓰면 같은 요청의 표시가 세대를 올려, 다음 호출이 새 세대로 표지를 또
        세워 두 번 알린다. 세대는 소진·어드민 변경마다 오르므로 그 상태가 이어지는 동안 축마다 한 번이다."""
        _spawn(self._alert_no_candidate(axis, list(after)))

    async def _alert_no_candidate(self, axis: ClaudeModelAxis, after: list[asyncio.Task[None]]) -> None:
        if after:
            await asyncio.wait(after)
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
                raw_generation = await self.redis.get(GENERATION_KEY)
        except Exception as exc:
            # 표지 없이 보내면 실패한 호출마다 알린다.
            logger.warning("Claude 자격 목록 세대를 읽지 못해 후보 없음 알림을 보내지 않는다: %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="redis")
            return
        spawn_credential_notification_once(
            f"{_ALERT_KEY_PREFIX}no-candidate:{int(raw_generation or 0)}:{axis}",
            f"[Claude 자격] {axis} 모델을 보낼 항목이 없다 — 그 모델 호출이 실패·환불된다. 항목을 충전·확인·켜거나, 목록 사용을 "
            "끄면 env 키 경로로 돈다",
            ttl_seconds=_STATE_ALERT_SECONDS,
        )


def _exhaustion_message(credential: PoolCredential, kind: RejectionKind) -> str:
    reason, action = _EXHAUSTION_REASONS[kind]
    message = f"[Claude 자격] 소진 — {credential.subject} · {reason} · 이 항목을 건너뛴다\n{action}"
    if is_env_key(credential.provider, credential.secret_fingerprint):
        message += "\nenv 롤백 키와 같은 키다 — 목록 사용을 끄면 env 경로도 같은 거절을 받는다"
    return message
