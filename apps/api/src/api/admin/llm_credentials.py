"""어드민 Claude 자격 목록 API — 조회, 추가, 메타 수정, 키 교체, 순서 저장, 켜기, 끄기, 삭제, 확인 호출, 목록 사용 켜기·끄기.

조회는 캐시가 아니라 DB 를 읽는다. 호출 경로는 이 목록을 Redis 스냅숏과 세대 번호로 읽으므로(`llm/credential_pool.py`) 커밋된
변경마다 커밋 뒤에 그 세대를 올린다 — 끈 항목·바꾼 순서가 다음 호출부터 보인다. 무효화가 실패해도 변경은 이미 커밋됐으니 응답은
그대로이고 경고만 남긴다(옛 스냅숏은 캐시 수명 안에서 저절로 맞춰진다).

- **키를 받는 일**(추가·키 교체·확인 호출)과 목록 사용 켜기는 저장소 설정(암호화 키·허용 계정)이 있어야 한다(없으면 503).
  메타 수정·끄기·삭제·순서 저장·목록 사용 끄기는 설정 없이도 된다 — 끄기·삭제는 되돌리기 경로라 막으면 안 된다.
- **조직 대조**: 추가·키 교체는 트랜잭션 밖에서 토큰 세기를 불러 응답의 조직 헤더를 허용 목록과 견준다(한 행 잠금을 쥔 채 최대
  10초를 기다리면 그동안 다른 목록 변경이 줄 선다). 헤더가 없으면 조직 미확인으로 저장하고, 확인 호출이 헤더로 채울 때까지 켤
  수 없다. 키 교체가 헤더 없이 오면 옛 조직 표지를 지운다 — 남기면 다른 조직의 키로 바꾼 항목이 확인된 것으로 보인다. 같은
  키(같은 지문)를 다시 넣는 교체는 같은 조직이라 토큰 세기를 부르지 않고 표지를 그대로 둔다.
- **켜기**는 지금 키 지문의 최신 확인 회차가 지금 판(`state_version`)에서 시작했고 통과한 축이 있고 풀리지 않은 조직 불일치가
  없을 때만 된다(`llm/credentials.py` 의 `enable_blocker` — 조직 신호는 런타임과 같다). 확인 호출은 시작할 때의 판·지문을 기록에 남기므로, 호출을 기다리는 동안
  끄기·소진·키 교체가 있었으면 그 회차는 세지 않는다. 목록 사용 켜기는 모든 축이 지금 모델 id 로 확인된 켜진 항목으로 덮일
  것을 요구한다 — 모델 id 설정을 바꾼 뒤 항목마다 다시 확인하게 강제하는 자리다.
- **추정 사용액**: 조회 응답은 충전액이 있는 항목마다 그 기준 이후의 추정 사용액을 싣는다(`llm/credential_usage.py`). 확인
  호출의 원가도 그 항목에 쌓는다 — 호출 경로 스위치와 무관하게 계정은 실제로 썼다.
- **목록 판**: 추가·삭제·순서 저장은 한 행 표의 판 번호를 먼저 올린다. 그 행의 잠금이 세 변경을 줄 세우고, 순서 저장만 화면이
  본 판을 요구한다(한 문장 조건부 UPDATE — 낡은 판과 경쟁을 함께 409 로). 순서는 모두를 같은 양수만큼 민 뒤 최종값을 매긴다
  (위치는 즉시 검사하는 유일 칸이라 바로 최종값을 매기면 도중에 겹친다).
- **비밀이 나가는 길**: 요청 검증 오류는 입력값·문맥을 지운다(`_NoInputEchoRoute`). 모든 쓰기 구간은 첫 변경부터 커밋까지
  `credential_write` 로 감싼다 — DB 오류의 파라미터와 드라이버 DETAIL(위반한 행 전체)이 암호문을 싣는다. 응답·감사 로그·알림에는
  키 원문·암호문·암호화 키 id 를 싣지 않고, 감사 로그·알림에는 끝 4자리와 조직 id 도 싣지 않는다.
- **감사·알림**: 성공한 변경마다 감사 한 행(대상 칸 없음 — 회원 상세가 읽지 않는다)과 커밋 뒤 알림 한 건이다. 바뀐 것이 없는
  요청(이미 켜진 항목 켜기 등)은 둘 다 남기지 않고 캐시도 무효화하지 않는다. 보안 신호(허용 목록 밖 조직의 키 저장 시도, 확인
  응답의 조직 불일치·허용 밖, 저장·확인 둘 다 조직 헤더 없음)는 변경이 거부돼도 따로 알린다.
"""

import logging
import uuid
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminLlmCredential,
    AdminLlmCredentialCheckItem,
    AdminLlmCredentialCheckResponse,
    AdminLlmCredentialCreateRequest,
    AdminLlmCredentialListResponse,
    AdminLlmCredentialOrderRequest,
    AdminLlmCredentialPoolRequest,
    AdminLlmCredentialSecretRequest,
    AdminLlmCredentialSpend,
    AdminLlmCredentialUpdateRequest,
)
from api.core.config import settings
from api.core.field_crypto import FieldDecryptError
from api.core.rate_limit import check_rate_limit
from api.core.sentry import capture_dependency_failure
from api.db.models.llm_credential import (
    CheckErrorKind,
    ClaudeModelAxis,
    CredentialProvider,
    CredentialState,
    CredentialStateReason,
    LlmCredential,
    LlmCredentialCheck,
    LlmCredentialSettings,
)
from api.db.session import get_db_session
from api.llm import credentials
from api.llm.credential_notify import get_credential_notifier
from api.llm.credential_pool import invalidate_pool_snapshot
from api.llm.credential_probe import (
    CheckCallResult,
    CredentialProbe,
    CredentialProbeError,
    get_anthropic_credential_probe,
)
from api.llm.credential_usage import (
    CredentialSpend,
    SpendTarget,
    below_alert,
    read_credential_spend,
    record_credential_spend,
)
from api.llm.credentials import (
    CLAUDE_AXES,
    TRANSIENT_CHECK_ERROR,
    CheckGroup,
    EnableBlocker,
    SecretFormatError,
    account_in_allowlist,
    allowed_accounts,
    check_groups,
    conclusive_checks_per_axis,
    credential_keyring,
    credential_write,
    current_model_ids,
    decrypt_secret,
    enable_blocker,
    latest_checks_per_axis,
    new_credential,
    passed_axes,
    replace_secret,
    same_as_env_key,
    secret_fingerprint,
    store_configured,
    uncovered_axes,
    validate_api_key_format,
)

Notifier = Callable[[str], None]

logger = logging.getLogger(__name__)

# 확인 호출은 항목마다 분당 한 번이다(호출마다 실제 비용이 든다). 정책값이라 기구(`core/rate_limit.py`)가 아니라 여기 둔다.
CHECK_LIMIT = 1
CHECK_WINDOW_SECONDS = 60

_MICRO_PER_USD = 1_000_000
_NOT_FOUND = "해당 자격을 찾을 수 없습니다."
_OUTSIDE_ALLOWLIST_ALERT = "[Claude 자격] 허용 목록 밖 조직의 키를 넣으려 했다 — 저장하지 않았다"
_BLOCKER_MESSAGES: dict[EnableBlocker, str] = {
    "organization-unverified": "조직이 확인되지 않아 켤 수 없습니다. 확인 호출로 조직을 다시 대조해 주세요.",
    "account-not-allowed": "이 항목의 조직이 지금 허용 목록에 없어 켤 수 없습니다.",
    "check-required": "지금 키로 한 확인 호출이 지금 상태에서 통과해야 켤 수 있습니다. 확인 호출을 먼저 해 주세요.",
    "organization-mismatch": "응답의 조직이 어긋났던 축이 아직 다시 통과하지 않아 켤 수 없습니다. 그 축이 확인 호출에서 통과해야 "
    "합니다.",
}


class _NoInputEchoRoute(APIRoute):
    """이 라우터의 요청 검증 오류에서 입력값을 지운다. FastAPI 기본 처리기는 오류마다 `input`(칸이 빠지면 본문 전체)을
    되돌려 실어, 키를 붙여넣은 요청이 형식 오류로 거부되면 그 키가 응답으로 돌아간다. `ctx` 도 지운다. 라우터 전체에 건다 —
    라우트마다 고르면 새 라우트에서 빠진다."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        "detail": [
                            {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
                            for error in exc.errors()
                        ]
                    },
                )

        return handle


router = APIRouter(tags=["admin"], route_class=_NoInputEchoRoute)


def _rule(status_code: int, rule: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"rule": rule, "message": message, **extra})


def _require_store() -> None:
    if not store_configured():
        raise _rule(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "store-not-configured",
            "자격 저장소 설정(암호화 키·허용 계정)이 없습니다.",
        )


def _refuse_other_providers(credential: LlmCredential) -> None:
    """키 교체는 Anthropic 항목만 받는다 — 확인 호출과 같은 규칙·같은 응답 꼴."""
    if credential.provider != "anthropic":
        raise _rule(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "provider-not-available", "이 공급자의 키 교체는 아직 없습니다."
        )


def _api_key(raw: SecretStr) -> str:
    try:
        return validate_api_key_format(raw.get_secret_value())
    except SecretFormatError:
        raise _rule(status.HTTP_422_UNPROCESSABLE_CONTENT, "secret-format", "키 형식이 아닙니다.") from None


async def _organization(probe: CredentialProbe, api_key: str) -> str | None:
    """붙여넣은 키의 조직(토큰 세기 응답 헤더). 거절은 422 와 그 종류, 닿지 못하면 503 이다."""
    try:
        return await probe.organization_of(api_key)
    except CredentialProbeError as exc:
        if exc.kind == "unavailable":
            raise _rule(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "upstream-unavailable",
                "Anthropic 에 닿지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
            ) from None
        raise _rule(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "credential-rejected",
            "Anthropic 이 이 키를 받아들이지 않아 저장하지 않았습니다.",
            reason=exc.kind,
        ) from None


def _allowed(provider: CredentialProvider, account_ref: str) -> bool:
    return account_in_allowlist(provider, account_ref, allowed_accounts())


async def _organization_listed(
    db: AsyncSession, provider: CredentialProvider, account_ref: str, *, exclude_id: uuid.UUID | None
) -> bool:
    """그 조직의 항목이 이미 목록에 있는가. 유일 인덱스가 마지막 안전망이고, 이 검사가 사유 있는 409 를 낸다."""
    stmt = select(LlmCredential.id).where(LlmCredential.provider == provider, LlmCredential.account_ref == account_ref)
    if exclude_id is not None:
        stmt = stmt.where(LlmCredential.id != exclude_id)
    return await db.scalar(stmt.limit(1)) is not None


async def _bump_list_revision(db: AsyncSession, *, base: int | None = None) -> int | None:
    """목록 판을 올리고 새 판을 돌려준다(이 행의 잠금이 목록 변경을 줄 세운다). `base` 를 주면 지금 판이 그 값일 때만 올리고,
    아니면 None 이다. 마이그레이션이 심은 행이 없으면(사람이 지움) 오류로 멈춘다."""
    stmt = update(LlmCredentialSettings).where(LlmCredentialSettings.id == 1)
    if base is not None:
        stmt = stmt.where(LlmCredentialSettings.list_revision == base)
    revision = await db.scalar(
        stmt.values(list_revision=LlmCredentialSettings.list_revision + 1, updated_at=datetime.now(UTC))
        .returning(LlmCredentialSettings.list_revision)
        .execution_options(synchronize_session=False)
    )
    if revision is None and await db.scalar(select(LlmCredentialSettings.id).where(LlmCredentialSettings.id == 1)) is None:
        raise RuntimeError("llm_credential_settings row is missing")
    return revision


async def _get(db: AsyncSession, credential_id: uuid.UUID, *, lock: bool = False) -> LlmCredential:
    stmt = select(LlmCredential).where(LlmCredential.id == credential_id).execution_options(populate_existing=True)
    credential = await db.scalar(stmt.with_for_update() if lock else stmt)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return credential


async def _checks_of(db: AsyncSession, credential_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[LlmCredentialCheck]]:
    grouped: dict[uuid.UUID, list[LlmCredentialCheck]] = {credential_id: [] for credential_id in credential_ids}
    if not credential_ids:
        return grouped
    rows = await db.scalars(
        select(LlmCredentialCheck)
        .where(LlmCredentialCheck.credential_id.in_(credential_ids))
        .execution_options(populate_existing=True)
    )
    for row in rows:
        grouped[row.credential_id].append(row)
    return grouped


async def _ordered(db: AsyncSession) -> list[LlmCredential]:
    rows = await db.scalars(
        select(LlmCredential).order_by(LlmCredential.position).execution_options(populate_existing=True)
    )
    return list(rows)


def _micro(usd: Decimal | None) -> int | None:
    return None if usd is None else int(usd * _MICRO_PER_USD)


def _dollars(micro: int) -> Decimal:
    return (Decimal(micro) / _MICRO_PER_USD).quantize(Decimal("0.01"))


def _usd(micro: int | None) -> Decimal | None:
    return None if micro is None else _dollars(micro)


def _usd_text(micro: int | None) -> str:
    usd = _usd(micro)
    return "없음" if usd is None else f"{usd}"


def _subject(credential: LlmCredential, fingerprint: str | None = None) -> str:
    """감사·알림 문구의 앞머리 — 공급자·라벨·지문만."""
    return f"{credential.provider} · {credential.label} · 지문 {fingerprint or credential.secret_fingerprint}"


def _env_key_line(same: bool) -> str:
    """지우거나 바꾼 옛 키가 env 롤백 키와 같은지에 따른 안내."""
    if same:
        return "\nenv 롤백 키와 같은 키다 — 콘솔에서 폐기하지 마라(env 되돌리기 경로가 같은 키를 쓴다)"
    return "\n쓰지 않을 키면 콘솔에서 폐기한다"


async def _invalidate_pool_snapshot() -> None:
    """런타임 목록 캐시의 세대를 올린다. 실패는 삼킨다 — 변경은 이미 커밋됐고, 옛 스냅숏이 나가는 시간은 캐시 수명이 상한이다."""
    try:
        await invalidate_pool_snapshot()
    except (RedisError, TimeoutError):
        logger.warning("Claude 자격 목록 변경 뒤 캐시 무효화 실패 — 캐시 수명 동안 옛 목록이 나간다", exc_info=True)
        capture_dependency_failure(dependency="redis")


async def _after_commit(notify: Notifier, *messages: str) -> None:
    """커밋된 변경의 캐시 무효화와 알림. 무효화가 먼저다 — 알림을 받은 운영자가 바로 본 런타임이 옛 목록이면 안 된다."""
    await _invalidate_pool_snapshot()
    for message in messages:
        notify(message)


def _check_out(
    credential: LlmCredential,
    check: LlmCredentialCheck,
    model_ids: dict[ClaudeModelAxis, str],
    *,
    is_runtime_basis: bool,
) -> AdminLlmCredentialCheckItem:
    return AdminLlmCredentialCheckItem(
        run=check.run,
        model_axis=check.model_axis,
        sent_model_id=check.sent_model_id,
        passed=check.passed,
        error_kind=check.error_kind,
        checked_at=check.checked_at,
        is_current_secret=check.secret_fingerprint == credential.secret_fingerprint,
        is_current_model_id=check.sent_model_id == model_ids.get(check.model_axis),
        is_current_state_version=check.state_version == credential.state_version,
        is_runtime_basis=is_runtime_basis,
    )


def _checks_out(
    credential: LlmCredential, checks: Sequence[LlmCredentialCheck], model_ids: dict[ClaudeModelAxis, str]
) -> list[AdminLlmCredentialCheckItem]:
    """축 순서로, 축마다 회차가 가장 큰 기록과 — 그것이 런타임이 그 축에 쓰는 기록이 아니면 — 런타임이 쓰는 기록을 하나 더.
    화면이 런타임과 같은 답(`credentials.passed_axes`)을 내려면 일시 오류 아래의 결론이 응답에 있어야 한다."""
    latest = latest_checks_per_axis(checks)
    basis = conclusive_checks_per_axis(credential.secret_fingerprint, checks)
    items: list[AdminLlmCredentialCheckItem] = []
    for axis in CLAUDE_AXES:
        newest, used = latest.get(axis), basis.get(axis)
        if newest is not None:
            items.append(_check_out(credential, newest, model_ids, is_runtime_basis=newest is used))
        if used is not None and used is not newest:
            items.append(_check_out(credential, used, model_ids, is_runtime_basis=True))
    return items


def _spend_out(credential: LlmCredential, spend: CredentialSpend | None) -> AdminLlmCredentialSpend | None:
    if spend is None or credential.credit_micro_usd is None:
        return None
    remaining = credential.credit_micro_usd - spend.spent_micro_usd
    return AdminLlmCredentialSpend(
        spent_usd=_dollars(spend.spent_micro_usd),
        remaining_usd=_dollars(remaining),
        below_alert=below_alert(credential.credit_micro_usd, spend.spent_micro_usd, credential.alert_pct),
        calls=spend.calls,
        unpriced_calls=spend.unpriced_calls,
        unpriced_model=spend.unpriced_model,
    )


def _credential_out(
    credential: LlmCredential,
    checks: Sequence[LlmCredentialCheck],
    model_ids: dict[ClaudeModelAxis, str],
    spend: CredentialSpend | None,
) -> AdminLlmCredential:
    return AdminLlmCredential(
        id=credential.id,
        provider=credential.provider,
        label=credential.label,
        position=credential.position,
        state=credential.state,
        state_reason=credential.state_reason,
        state_version=credential.state_version,
        state_changed_at=credential.state_changed_at,
        account_ref=credential.account_ref,
        organization_verified=credential.account_ref is not None,
        secret_last4=credential.secret_last4,
        secret_fingerprint=credential.secret_fingerprint,
        same_as_env_key=same_as_env_key(credential),
        credit_usd=_usd(credential.credit_micro_usd),
        credit_since=credential.credit_since,
        alert_pct=credential.alert_pct,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
        checks=_checks_out(credential, checks, model_ids),
        runtime_axes=[axis for axis in CLAUDE_AXES if axis in passed_axes(credential, checks)],
        enable_blocker=enable_blocker(credential, checks, allowed_accounts()),
        spend=_spend_out(credential, spend),
    )


async def _credential_response(db: AsyncSession, credential_id: uuid.UUID) -> AdminLlmCredential:
    """커밋 뒤 다시 읽은 항목 — 서버가 채운 칸(만든 시각 등)까지."""
    credential = await _get(db, credential_id)
    checks = await _checks_of(db, [credential.id])
    spends = await read_credential_spend([SpendTarget.of_row(credential)])
    return _credential_out(credential, checks[credential.id], current_model_ids(), spends[credential.id])


async def _list_response(db: AsyncSession) -> AdminLlmCredentialListResponse:
    row = await db.scalar(
        select(LlmCredentialSettings)
        .where(LlmCredentialSettings.id == 1)
        .execution_options(populate_existing=True)
    )
    rows = await _ordered(db)
    checks = await _checks_of(db, [credential.id for credential in rows])
    spends = await read_credential_spend([SpendTarget.of_row(credential) for credential in rows])
    model_ids = current_model_ids()
    return AdminLlmCredentialListResponse(
        store_configured=store_configured(),
        notifications_configured=bool(settings.llm_credential_discord_webhook_url),
        pool_enabled=row.pool_enabled if row is not None else False,
        list_revision=row.list_revision if row is not None else 0,
        model_ids=model_ids,
        credentials=[
            _credential_out(credential, checks[credential.id], model_ids, spends[credential.id]) for credential in rows
        ],
    )


# ── 조회·추가 ─────────────────────────────────────────────────────────────────────
@router.get("/admin/llm-credentials")
async def list_llm_credentials(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminLlmCredentialListResponse:
    return await _list_response(db)


@router.post("/admin/llm-credentials", status_code=status.HTTP_201_CREATED)
async def create_llm_credential(
    body: AdminLlmCredentialCreateRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    probe: CredentialProbe = Depends(get_anthropic_credential_probe),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredential:
    """목록 끝에 꺼진 채 더한다. 크레딧·한도로 거절된 키도 저장하지 않는다(충전한 뒤 다시 넣는다)."""
    _require_store()
    api_key = _api_key(body.api_key)
    account_ref = await _organization(probe, api_key)
    if account_ref is not None and not _allowed("anthropic", account_ref):
        notify(_OUTSIDE_ALLOWLIST_ALERT)
        raise _rule(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "account-not-allowed", "허용 목록 밖 조직의 키라 저장하지 않았습니다."
        )
    keyring = credential_keyring()
    async with credential_write(db):
        await _bump_list_revision(db)
        if account_ref is not None and await _organization_listed(db, "anthropic", account_ref, exclude_id=None):
            raise _rule(status.HTTP_409_CONFLICT, "account-already-listed", "이 조직의 키가 이미 목록에 있습니다.")
        position: int = (
            await db.execute(select(func.coalesce(func.max(LlmCredential.position), 0) + 1))
        ).scalar_one()
        credential = new_credential(
            keyring,
            provider="anthropic",
            label=body.label,
            secret=api_key,
            account_ref=account_ref,
            position=position,
            credit_micro_usd=_micro(body.credit_usd),
            alert_pct=body.alert_pct,
        )
        db.add(credential)
        organization = "조직 확인됨" if account_ref is not None else "조직 미확인"
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="llm-credential-add",
            reason_text=f"{_subject(credential)} · {position}번째 · {organization}",
        )
        await db.flush()
        await db.commit()
    message = f"[Claude 자격] 추가 — {_subject(credential)} · {position}번째 · 꺼진 채(확인 호출 뒤 켜기)"
    if account_ref is None:
        message += "\n조직 헤더가 없어 조직 미확인 — 확인 호출에서 다시 대조한다"
    if same_as_env_key(credential):
        message += "\nenv 롤백 키와 같은 키다 — 이 항목을 지우거나 교체해도 콘솔에서 폐기하지 마라"
    await _after_commit(notify, message)
    return await _credential_response(db, credential.id)


# ── 목록 단위 변경 (`/{id}` 보다 먼저 선언한다) ─────────────────────────────────────────
@router.put("/admin/llm-credentials/order")
async def reorder_llm_credentials(
    body: AdminLlmCredentialOrderRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredentialListResponse:
    async with credential_write(db):
        revision = await _bump_list_revision(db, base=body.base_list_revision)
        if revision is None:
            raise _rule(
                status.HTTP_409_CONFLICT,
                "stale-list-revision",
                "다른 변경이 먼저 반영됐습니다. 새로 고친 뒤 다시 저장해 주세요.",
            )
        rows = {credential.id: credential for credential in await _ordered(db)}
        if len(body.ids) != len(set(body.ids)) or set(body.ids) != set(rows):
            raise _rule(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "order-mismatch",
                "순서에는 지금 목록의 항목을 하나씩 모두 담아야 합니다.",
            )
        if rows:
            # 판 행 잠금 아래라 그 사이 위치가 바뀌지 않는다. 모두를 지금 최대만큼 밀면(최솟값이 최대 + 1 이 된다) 아직 밀지 않은
            # 값과도, 다음에 매길 최종값(1..n ≤ 최대)과도 겹치지 않는다.
            shift = max(credential.position for credential in rows.values())
            await db.execute(
                update(LlmCredential)
                .values(position=LlmCredential.position + shift)
                .execution_options(synchronize_session=False)
            )
            for position, credential_id in enumerate(body.ids, start=1):
                await db.execute(
                    update(LlmCredential)
                    .where(LlmCredential.id == credential_id)
                    .values(position=position)
                    .execution_options(synchronize_session=False)
                )
        order = " → ".join(rows[credential_id].label for credential_id in body.ids)
        await record_admin_action(
            db, admin_id=admin_id, action_type="llm-credential-reorder", reason_text=f"순서: {order} (판 {revision})"
        )
        await db.flush()
        await db.commit()
    await _after_commit(notify, f"[Claude 자격] 순서 — {order}")
    return await _list_response(db)


@router.put("/admin/llm-credentials/pool")
async def set_llm_credential_pool(
    body: AdminLlmCredentialPoolRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredentialListResponse:
    """목록 사용 켜기·끄기. 끄기는 늘 된다(되돌리기 첫 단계). 켜기는 축마다 켜진 항목 하나 이상이 지금 키·지금 모델 id 로 확인
    통과했을 때만 된다. 목록 판은 올리지 않는다."""
    if body.enabled:
        _require_store()
    changed = False
    async with credential_write(db):
        row = await db.scalar(
            select(LlmCredentialSettings)
            .where(LlmCredentialSettings.id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("llm_credential_settings row is missing")
        if row.pool_enabled != body.enabled:
            if body.enabled:
                rows = await _ordered(db)
                checks = await _checks_of(db, [credential.id for credential in rows])
                axes = uncovered_axes(rows, checks, current_model_ids(), allowed_accounts())
                if axes:
                    raise _rule(
                        status.HTTP_409_CONFLICT,
                        "pool-uncovered",
                        "모든 모델 축이 지금 모델 id 로 확인한 켜진 항목으로 덮여야 켤 수 있습니다.",
                        axes=axes,
                    )
            row.pool_enabled = body.enabled
            row.updated_at = datetime.now(UTC)
            await record_admin_action(
                db,
                admin_id=admin_id,
                action_type="llm-credential-pool-on" if body.enabled else "llm-credential-pool-off",
                reason_text="목록 사용 켬" if body.enabled else "목록 사용 끔",
            )
            await db.flush()
            await db.commit()
            changed = True
    if changed:
        await _after_commit(notify, f"[Claude 자격] 목록 사용 {'켬' if body.enabled else '끔'}")
    return await _list_response(db)


# ── 항목 단위 변경 ─────────────────────────────────────────────────────────────────
@router.patch("/admin/llm-credentials/{credential_id}")
async def update_llm_credential(
    credential_id: uuid.UUID,
    body: AdminLlmCredentialUpdateRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredential:
    """라벨·충전액·임계만 고친다. 충전액이 바뀌면 그 기준 시각을 지금으로 다시 잡는다(사용액 누적이 그 시각부터 다시 센다).
    `resetCreditBasis` 면 충전액이 같아도 다시 잡고, 다시 잡을 충전액이 없으면(원래 없거나 같은 요청이 지우면) 아무것도 바꾸지
    않고 409 다."""
    changes: list[str] = []
    async with credential_write(db):
        credential = await _get(db, credential_id, lock=True)
        credit = _micro(body.credit_usd) if "credit_usd" in body.model_fields_set else credential.credit_micro_usd
        if body.reset_credit_basis and credit is None:
            raise _rule(status.HTTP_409_CONFLICT, "credit-basis-missing", "충전액이 없어 기준을 다시 잡을 수 없습니다.")
        if body.label is not None and body.label != credential.label:
            changes.append(f"라벨 {credential.label} → {body.label}")
            credential.label = body.label
        if credit != credential.credit_micro_usd:
            changes.append(f"충전액 {_usd_text(credential.credit_micro_usd)} → {_usd_text(credit)} 달러")
            credential.credit_micro_usd = credit
            credential.credit_since = None if credit is None else datetime.now(UTC)
        elif body.reset_credit_basis:
            changes.append(f"사용액 기준 다시 잡음(충전액 {_usd_text(credit)} 달러)")
            credential.credit_since = datetime.now(UTC)
        if body.alert_pct is not None and body.alert_pct != credential.alert_pct:
            changes.append(f"임계 {credential.alert_pct} → {body.alert_pct}%")
            credential.alert_pct = body.alert_pct
        if changes:
            credential.updated_at = datetime.now(UTC)
            await record_admin_action(
                db,
                admin_id=admin_id,
                action_type="llm-credential-update",
                reason_text=f"{_subject(credential)} · {', '.join(changes)}",
            )
            await db.flush()
            await db.commit()
    if changes:
        await _after_commit(notify, f"[Claude 자격] 수정 — {_subject(credential)} · {', '.join(changes)}")
    return await _credential_response(db, credential_id)


@router.put("/admin/llm-credentials/{credential_id}/secret")
async def replace_llm_credential_secret(
    credential_id: uuid.UUID,
    body: AdminLlmCredentialSecretRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    probe: CredentialProbe = Depends(get_anthropic_credential_probe),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredential:
    """키만 바꾼다(한 항목 = 한 계정 — 다른 조직의 키로는 바꾸지 않는다). 상태·판은 그대로이고, 확인 기록이 옛 지문에 묶여
    있어 교체만으로 그 기록이 지금 키의 확인이 아니게 된다. 예전에 쓰던 키로 되돌리면 그 키로 한 예전 확인이 다시 지금 키의
    확인으로 센다(런타임도 바로 그 결론을 쓴다) — 알림이 그렇게 말한다. 같은 키를 다시 붙여넣으면(암호화 키를 잃어 저장한 키를 읽을 수
    없을 때 살리는 길) 지문이 같아 옛 확인 기록이 그대로 지금 키의 확인으로 센다 — 암호문만 지금 키로 다시 쓰고, 같은 키는
    같은 조직이라 조직 조회를 부르지 않고 조직 표지도 그대로 둔다."""
    _require_store()
    api_key = _api_key(body.api_key)
    fingerprint = secret_fingerprint(api_key)
    # 외부 호출 전에 잠그지 않고 읽는다 — 다른 공급자는 조회 없이 거부하고, 같은 키면 조회를 건너뛴다. 읽기만 한 트랜잭션은
    # 호출 전에 닫는다(호출을 기다리는 동안 연결·스냅샷을 쥐지 않는다).
    credential = await _get(db, credential_id)
    _refuse_other_providers(credential)
    lookup = credential.secret_fingerprint != fingerprint
    await db.commit()
    header = await _organization(probe, api_key) if lookup else None
    keyring = credential_keyring()
    async with credential_write(db):
        credential = await _get(db, credential_id, lock=True)
        # 지금 라우트로는 공급자가 바뀌지 않는다(추가는 anthropic 으로 고정하고 수정은 공급자를 받지 않는다). 나중에 행의
        # 공급자를 바꾸는 경로가 생겨도 조회를 기다리는 사이 바뀐 행의 비밀을 Anthropic 키로 덮지 않게 잠근 행으로 다시 본다.
        _refuse_other_providers(credential)
        old_fingerprint = credential.secret_fingerprint
        old_is_env_key = same_as_env_key(credential)
        same_key = old_fingerprint == fingerprint
        # 예전에 쓰던 키로 되돌리는가 — 그 키로 한 결론 기록이 있으면 교체 즉시 그 기록이 다시 지금 키의 확인이 된다.
        counts_again = not same_key and bool(
            conclusive_checks_per_axis(fingerprint, (await _checks_of(db, [credential.id]))[credential.id])
        )
        cleared = False
        if same_key:
            pass  # 같은 키는 같은 조직이다 — 조직 표지를 그대로 둔다.
        elif header is None:
            # 조회를 건너뛰었는데 그 사이 다른 키로 바뀐 행도 여기로 온다 — 붙여넣은 키의 조직을 모르니 헤더 없음과 같다.
            cleared = credential.account_ref is not None
            credential.account_ref = None
        elif header != credential.account_ref:
            outside = not _allowed(credential.provider, header)
            if outside:
                notify(_OUTSIDE_ALLOWLIST_ALERT)
            if credential.account_ref is not None:
                raise _rule(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "account-mismatch",
                    "다른 조직의 키로는 바꿀 수 없습니다. 지우고 새로 추가해 주세요.",
                )
            if outside:
                raise _rule(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "account-not-allowed",
                    "허용 목록 밖 조직의 키라 저장하지 않았습니다.",
                )
            if await _organization_listed(db, credential.provider, header, exclude_id=credential.id):
                raise _rule(status.HTTP_409_CONFLICT, "account-already-listed", "이 조직의 키가 이미 목록에 있습니다.")
            credential.account_ref = header
        replace_secret(keyring, credential, api_key)
        credential.updated_at = datetime.now(UTC)
        if same_key:
            fingerprints = f"지문 {old_fingerprint} · 같은 키 — 암호문만 다시 씀"
        else:
            fingerprints = f"지문 {old_fingerprint} → {credential.secret_fingerprint}"
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="llm-credential-secret-replace",
            reason_text=f"{credential.provider} · {credential.label} · {fingerprints}"
            + (" · 조직 미확인으로 돌아감" if cleared else ""),
        )
        await db.flush()
        await db.commit()
    message = f"[Claude 자격] 키 교체 — {credential.provider} · {credential.label} · {fingerprints}"
    # 같은 키면 옛 키가 곧 지금 키라 확인 기록이 그대로 세고 폐기할 옛 키도 없다.
    if not same_key:
        message += (" · 이 키로 한 이전 확인이 다시 센다" if counts_again else " · 확인 호출 전까지 미확인") + _env_key_line(
            old_is_env_key
        )
        if same_as_env_key(credential):
            message += "\n새 키는 env 롤백 키와 같다"
    if cleared:
        message += "\n조직 미확인으로 돌아감"
    await _after_commit(notify, message)
    return await _credential_response(db, credential_id)


@router.post("/admin/llm-credentials/{credential_id}/enable")
async def enable_llm_credential(
    credential_id: uuid.UUID,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredential:
    """켠다(소진된 항목의 해제도 이것이다). 조건은 `enable_blocker` — 막히면 409 와 그 이유. 이미 켜져 있으면 그대로 200."""
    changed = False
    async with credential_write(db):
        credential = await _get(db, credential_id, lock=True)
        if credential.state != "active":
            checks = await _checks_of(db, [credential.id])
            blocker = enable_blocker(credential, checks[credential.id], allowed_accounts())
            if blocker is not None:
                raise _rule(status.HTTP_409_CONFLICT, blocker, _BLOCKER_MESSAGES[blocker])
            _change_state(credential, "active", None)
            await record_admin_action(
                db, admin_id=admin_id, action_type="llm-credential-enable", reason_text=_subject(credential)
            )
            await db.flush()
            await db.commit()
            changed = True
    if changed:
        await _after_commit(notify, f"[Claude 자격] 켬 — {_subject(credential)}")
    return await _credential_response(db, credential_id)


@router.post("/admin/llm-credentials/{credential_id}/disable")
async def disable_llm_credential(
    credential_id: uuid.UUID,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredential:
    """운영자가 끈다. 판이 올라 그 전의 확인은 켜기에 세지 않는다. 이미 꺼져 있으면 그대로 200."""
    changed = False
    async with credential_write(db):
        credential = await _get(db, credential_id, lock=True)
        if credential.state != "disabled":
            # 부르는 때 모듈 속성으로 읽는다 — 새 항목과 같은 값을 쓰고, 테스트가 CHECK 밖 값으로 바꿔 쓰기 실패를 낸다.
            _change_state(credential, "disabled", credentials.ADMIN_DISABLED_REASON)
            await record_admin_action(
                db, admin_id=admin_id, action_type="llm-credential-disable", reason_text=_subject(credential)
            )
            await db.flush()
            await db.commit()
            changed = True
    if changed:
        await _after_commit(notify, f"[Claude 자격] 끔 — {_subject(credential)}")
    return await _credential_response(db, credential_id)


def _change_state(credential: LlmCredential, state: CredentialState, reason: CredentialStateReason | None) -> None:
    """상태를 바꾸고 판을 올린다(행 잠금 아래에서 부른다)."""
    now = datetime.now(UTC)
    credential.state = state
    credential.state_reason = reason
    credential.state_version = credential.state_version + 1
    credential.state_changed_at = now
    credential.updated_at = now


@router.delete("/admin/llm-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_credential(
    credential_id: uuid.UUID,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    notify: Notifier = Depends(get_credential_notifier),
) -> None:
    """행을 지운다(확인 기록도 함께) — 남는 행에 암호문이 남지 않게. 행이 사라지므로 감사 로그가 유일한 흔적이다."""
    async with credential_write(db):
        await _bump_list_revision(db)
        credential = await _get(db, credential_id, lock=True)
        subject = _subject(credential)
        was_env_key = same_as_env_key(credential)
        await record_admin_action(db, admin_id=admin_id, action_type="llm-credential-delete", reason_text=subject)
        await db.execute(
            delete(LlmCredential).where(LlmCredential.id == credential_id).execution_options(synchronize_session=False)
        )
        remaining = await db.scalar(select(func.count()).select_from(LlmCredential))
        await db.commit()
    message = f"[Claude 자격] 삭제 — {subject}" + _env_key_line(was_env_key)
    if not remaining:
        message += "\n목록이 비었다 — 런타임은 env 키 경로로 돈다"
    await _after_commit(notify, message)


# ── 확인 호출 ─────────────────────────────────────────────────────────────────────
_Outcome = tuple[CheckGroup, CheckErrorKind | None, str | None]


def _reconcile(
    results: Sequence[tuple[CheckGroup, CheckCallResult]], account_ref: str | None
) -> tuple[list[_Outcome], str | None]:
    """응답마다 조직 헤더를 대조해 묶음마다 (실패 종류, 헤더)를 정하고, 채울 조직(미확인 항목의 첫 허용 헤더)을 돌려준다.

    저장된 조직이 있으면 다른 헤더만 실패다(헤더가 없으면 저장 때 확인됐으므로 통과). 미확인이면 허용 목록 밖 헤더는 실패이고,
    첫 허용 헤더가 이 확인의 기준이 되어 그 뒤 다른 헤더는 불일치다. 헤더가 없으면 모델 접근만 통과로 남는다(여전히 미확인)."""
    reference = account_ref
    fill: str | None = None
    outcomes: list[_Outcome] = []
    for group, result in results:
        kind: CheckErrorKind | None = result.error_kind
        header = result.organization
        if kind is None and header is not None:
            if reference is not None:
                if header != reference:
                    kind = "organization-mismatch"
            elif not _allowed("anthropic", header):
                kind = "account-not-allowed"
            else:
                fill = reference = header
        outcomes.append((group, kind, header))
    return outcomes, fill


def _axis_result(axis: ClaudeModelAxis, kind: CheckErrorKind | None, *, concluded_before: bool) -> str:
    """감사·알림의 축 하나. 일시 오류는 실패가 아니라 이전 결과로 적는다 — 런타임이 그 축의 이전 결론을 그대로 쓴다
    (`credentials.passed_axes`). 이 키로 한 이전 결론이 없으면(키를 막 바꾼 뒤의 첫 확인 등) 옛 키의 통과가 이어지는 것처럼
    읽히지 않게 그 축을 아직 쓰지 않는다고 적는다."""
    if kind is None:
        return f"{axis} 통과"
    if kind == TRANSIENT_CHECK_ERROR:
        if concluded_before:
            return f"{axis} 일시 오류(이전 결과 유지)"
        return f"{axis} 일시 오류(이 키로 한 이전 결과 없음 — 이 모델은 아직 쓰지 않는다)"
    return f"{axis} 실패({kind})"


def _axis_results(outcomes: Sequence[_Outcome], concluded_before: set[ClaudeModelAxis]) -> list[str]:
    kinds = {axis: kind for group, kind, _ in outcomes for axis in group.axes}
    return [
        _axis_result(axis, kinds[axis], concluded_before=axis in concluded_before) for axis in CLAUDE_AXES if axis in kinds
    ]


@router.post("/admin/llm-credentials/{credential_id}/check")
async def check_llm_credential(
    credential_id: uuid.UUID,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    probe: CredentialProbe = Depends(get_anthropic_credential_probe),
    notify: Notifier = Depends(get_credential_notifier),
) -> AdminLlmCredentialCheckResponse:
    """모델 축마다 지금 설정의 실제 id 로 확인 호출을 하고 축마다 한 행을 같은 회차로 남긴다(같은 id 는 한 번, 차례로).
    기록에는 확인을 시작할 때 읽은 판·지문을 남긴다 — 호출을 기다리는 동안 상태나 키가 바뀌면 그 회차는 켜기에 세지 않는다.
    다시 시도할 일(429·과부하·시간 초과 등)로 실패한 축도 그 종류(`unavailable`)로 남지만 그 축의 이전 결과를 덮지 않는다 —
    런타임은 그 축의 이전 결론을 그대로 쓰고, 켜기·목록 사용 켜기에는 세지 않는다(분당 한 번이라 1분 뒤 다시 누른다)."""
    # DB 조회보다 먼저 센다 — 그 항목이 있든 없든 카운터가 오른다.
    retry_after = await check_rate_limit(
        "llm_credential_check", str(credential_id), CHECK_LIMIT, window_seconds=CHECK_WINDOW_SECONDS
    )
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "LLM_CREDENTIAL_CHECK_LIMIT", "retryAfterSeconds": retry_after, "window": "llm-credential-check"},
        )
    credential = await _get(db, credential_id)
    if credential.provider != "anthropic":
        raise _rule(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "provider-not-available", "이 공급자의 확인 호출은 아직 없습니다."
        )
    _require_store()
    started_version = credential.state_version
    started_fingerprint = credential.secret_fingerprint
    started_account = credential.account_ref
    label = credential.label
    try:
        api_key = decrypt_secret(credential_keyring(), credential)
    except FieldDecryptError:
        raise _rule(
            status.HTTP_409_CONFLICT, "secret-unreadable", "저장한 키를 읽을 수 없습니다. 키를 다시 붙여넣어 주세요."
        ) from None
    # 읽기만 한 트랜잭션을 닫고 부른다 — 호출을 기다리는 동안 연결·스냅샷을 쥐지 않는다.
    await db.commit()

    groups = check_groups(current_model_ids())
    results = [(group, await probe.check(api_key, group, credential_id=credential_id)) for group in groups]
    outcomes, fill = _reconcile(results, started_account)
    # 보안 신호는 기록을 쓰기 전에 보낸다 — 호출을 기다리는 동안 항목이 지워져(404) 기록이 남지 않거나 쓰기가 실패해도, 응답이
    # 보인 조직은 그대로다. 아래 쓰기는 `fill` 을 비우고(그새 키가 바뀌었거나 조직이 채워졌거나 이미 목록에 있는 조직) 그 헤더로
    # 통과한 축을 `account-already-listed` 로 돌릴 수 있지만, 그래도 신호는 같다. 조직 불일치·허용 밖 축은 건드리지 않고, 헤더
    # 없음 신호는 모든 응답에 헤더가 없을 때만인데 `fill` 은 헤더에서만 채워지므로 그때 `fill` 은 처음부터 비어 있고 돌릴 축도 없다.
    kinds = {kind for _, kind, _ in outcomes}
    if "organization-mismatch" in kinds:
        notify(f"[Claude 자격] 확인 응답의 조직이 저장된 조직과 다르다 — {label}")
    if "account-not-allowed" in kinds:
        notify(f"[Claude 자격] 확인 응답의 조직이 허용 목록 밖이다 — {label}")
    no_header = all(header is None for _, _, header in outcomes)
    if started_account is None and fill is None and no_header and None in kinds:
        notify(f"[Claude 자격] 저장·확인 둘 다 조직 헤더가 없다 — {label} 은 켤 수 없다")

    async with credential_write(db):
        current = await db.scalar(
            select(LlmCredential)
            .where(LlmCredential.id == credential_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
        if fill is not None and (current.secret_fingerprint != started_fingerprint or current.account_ref is not None):
            fill = None
        if fill is not None and await _organization_listed(db, current.provider, fill, exclude_id=current.id):
            # 채우지 않는다. 그 헤더로 통과한 축은 이미 목록에 있는 조직으로 남긴다.
            outcomes = [
                (group, "account-already-listed" if kind is None and header == fill else kind, header)
                for group, kind, header in outcomes
            ]
            fill = None
        # 이번 회차를 쓰기 전의 기록 — 일시 오류 축의 문구가 이 키로 한 이전 결론이 있는지에 따라 갈린다.
        earlier = await _checks_of(db, [credential_id])
        concluded_before = set(conclusive_checks_per_axis(started_fingerprint, earlier[credential_id]))
        run: int = (
            await db.execute(
                select(func.coalesce(func.max(LlmCredentialCheck.run), 0) + 1).where(
                    LlmCredentialCheck.credential_id == credential_id
                )
            )
        ).scalar_one()
        for group, kind, header in outcomes:
            for axis in group.axes:
                db.add(
                    LlmCredentialCheck(
                        credential_id=credential_id,
                        run=run,
                        state_version=started_version,
                        model_axis=axis,
                        sent_model_id=group.model_id,
                        secret_fingerprint=started_fingerprint,
                        passed=kind is None,
                        error_kind=kind,
                        organization_header=header,
                    )
                )
        if fill is not None:
            current.account_ref = fill
            current.updated_at = datetime.now(UTC)
        subject = _subject(current, started_fingerprint)
        axis_results = _axis_results(outcomes, concluded_before)
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="llm-credential-check",
            reason_text=f"{subject} · {', '.join(axis_results)}",
        )
        await db.flush()
        await db.commit()

    # 받아들여진 호출마다 원가를 그 항목의 지금 기준에 쌓는다 — 기록을 쓴 행의 기준이라 그 사이 충전액을 바꿨으면 새 기준이다.
    spend_target = SpendTarget.of_row(current)
    for group, result in results:
        if result.usage is not None:
            await record_credential_spend(spend_target, group.model_id, result.usage)
    await _after_commit(
        notify, f"[Claude 자격] 확인 — {subject} · {' · '.join(axis_results)}" + ("\n조직 확인됨" if fill else "")
    )
    return AdminLlmCredentialCheckResponse(
        credential=await _credential_response(db, credential_id), calls=len(groups)
    )
