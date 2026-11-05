"""어드민 Claude 자격 목록 API — 조회, 추가, 메타 수정, 키 교체, 순서 저장, 켜기, 끄기, 삭제, 확인 호출, 목록 사용 켜기·끄기.

이 판은 저장과 관리만 한다 — 호출 경로는 아직 이 목록을 읽지 않는다. 조회는 캐시가 아니라 DB 를 읽는다.

- **키를 받는 일**(추가·키 교체·확인 호출)과 목록 사용 켜기는 저장소 설정(암호화 키·허용 계정)이 있어야 한다(없으면 503).
  메타 수정·끄기·삭제·순서 저장·목록 사용 끄기는 설정 없이도 된다 — 끄기·삭제는 되돌리기 경로라 막으면 안 된다.
- **조직 대조**: 추가·키 교체는 트랜잭션 밖에서 토큰 세기를 불러 응답의 조직 헤더를 허용 목록과 견준다(한 행 잠금을 쥔 채 최대
  10초를 기다리면 그동안 다른 목록 변경이 줄 선다). 헤더가 없으면 조직 미확인으로 저장하고, 확인 호출이 헤더로 채울 때까지 켤
  수 없다. 키 교체가 헤더 없이 오면 옛 조직 표지를 지운다 — 남기면 다른 조직의 키로 바꾼 항목이 확인된 것으로 보인다.
- **켜기**는 지금 키 지문의 최신 확인 회차가 지금 판(`state_version`)에서 시작했고 통과한 축이 있고 조직 오류가 없을 때만
  된다(`llm/credentials.py` 의 `enable_blocker`). 확인 호출은 시작할 때의 판·지문을 기록에 남기므로, 호출을 기다리는 동안
  끄기·소진·키 교체가 있었으면 그 회차는 세지 않는다. 목록 사용 켜기는 모든 축이 지금 모델 id 로 확인된 켜진 항목으로 덮일
  것을 요구한다 — 모델 id 설정을 바꾼 뒤 항목마다 다시 확인하게 강제하는 자리다.
- **목록 판**: 추가·삭제·순서 저장은 한 행 표의 판 번호를 먼저 올린다. 그 행의 잠금이 세 변경을 줄 세우고, 순서 저장만 화면이
  본 판을 요구한다(한 문장 조건부 UPDATE — 낡은 판과 경쟁을 함께 409 로). 순서는 모두를 같은 양수만큼 민 뒤 최종값을 매긴다
  (위치는 즉시 검사하는 유일 칸이라 바로 최종값을 매기면 도중에 겹친다).
- **비밀이 나가는 길**: 요청 검증 오류는 입력값·문맥을 지운다(`_NoInputEchoRoute`). 모든 쓰기 구간은 첫 변경부터 커밋까지
  `credential_write` 로 감싼다 — DB 오류의 파라미터와 드라이버 DETAIL(위반한 행 전체)이 암호문을 싣는다. 응답·감사 로그·알림에는
  키 원문·암호문·암호화 키 id 를 싣지 않고, 감사 로그·알림에는 끝 4자리와 조직 id 도 싣지 않는다.
- **감사·알림**: 성공한 변경마다 감사 한 행(대상 칸 없음 — 회원 상세가 읽지 않는다)과 커밋 뒤 알림 한 건이다. 바뀐 것이 없는
  요청(이미 켜진 항목 켜기 등)은 둘 다 남기지 않는다. 보안 신호(허용 목록 밖 조직의 키 저장 시도, 확인 응답의 조직 불일치·허용
  밖, 저장·확인 둘 다 조직 헤더 없음)는 변경이 거부돼도 따로 알린다.
"""

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
    AdminLlmCredentialUpdateRequest,
)
from api.core.config import settings
from api.core.field_crypto import FieldDecryptError
from api.core.rate_limit import check_rate_limit
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
from api.llm.credential_probe import (
    CheckCallResult,
    CredentialProbe,
    CredentialProbeError,
    get_anthropic_credential_probe,
)
from api.llm.credentials import (
    CLAUDE_AXES,
    CheckGroup,
    EnableBlocker,
    SecretFormatError,
    account_in_allowlist,
    allowed_accounts,
    check_groups,
    credential_keyring,
    credential_write,
    current_model_ids,
    decrypt_secret,
    enable_blocker,
    latest_checks_per_axis,
    new_credential,
    replace_secret,
    same_as_env_key,
    store_configured,
    uncovered_axes,
    validate_api_key_format,
)

Notifier = Callable[[str], None]

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
    "organization-mismatch": "마지막 확인에서 응답의 조직이 어긋난 축이 있어 켤 수 없습니다.",
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


def _usd(micro: int | None) -> Decimal | None:
    return None if micro is None else (Decimal(micro) / _MICRO_PER_USD).quantize(Decimal("0.01"))


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


def _after_commit(notify: Notifier, *messages: str) -> None:
    """커밋된 변경의 알림."""
    for message in messages:
        notify(message)


def _check_out(
    credential: LlmCredential, check: LlmCredentialCheck, model_ids: dict[ClaudeModelAxis, str]
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
    )


def _credential_out(
    credential: LlmCredential, checks: Sequence[LlmCredentialCheck], model_ids: dict[ClaudeModelAxis, str]
) -> AdminLlmCredential:
    latest = latest_checks_per_axis(checks)
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
        checks=[_check_out(credential, latest[axis], model_ids) for axis in CLAUDE_AXES if axis in latest],
        enable_blocker=enable_blocker(credential, checks, allowed_accounts()),
    )


async def _credential_response(db: AsyncSession, credential_id: uuid.UUID) -> AdminLlmCredential:
    """커밋 뒤 다시 읽은 항목 — 서버가 채운 칸(만든 시각 등)까지."""
    credential = await _get(db, credential_id)
    checks = await _checks_of(db, [credential.id])
    return _credential_out(credential, checks[credential.id], current_model_ids())


async def _list_response(db: AsyncSession) -> AdminLlmCredentialListResponse:
    row = await db.scalar(
        select(LlmCredentialSettings)
        .where(LlmCredentialSettings.id == 1)
        .execution_options(populate_existing=True)
    )
    rows = await _ordered(db)
    checks = await _checks_of(db, [credential.id for credential in rows])
    model_ids = current_model_ids()
    return AdminLlmCredentialListResponse(
        store_configured=store_configured(),
        notifications_configured=bool(settings.llm_credential_discord_webhook_url),
        pool_enabled=row.pool_enabled if row is not None else False,
        list_revision=row.list_revision if row is not None else 0,
        model_ids=model_ids,
        credentials=[_credential_out(credential, checks[credential.id], model_ids) for credential in rows],
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
    _after_commit(notify, message)
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
    _after_commit(notify, f"[Claude 자격] 순서 — {order}")
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
                latest = {credential_id: latest_checks_per_axis(items) for credential_id, items in checks.items()}
                axes = uncovered_axes(rows, latest, current_model_ids(), allowed_accounts())
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
        _after_commit(notify, f"[Claude 자격] 목록 사용 {'켬' if body.enabled else '끔'}")
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
    """라벨·충전액·임계만 고친다. 충전액이 바뀌면 그 기준 시각을 지금으로 다시 잡는다(사용액 누적이 그 시각부터 다시 센다)."""
    changes: list[str] = []
    async with credential_write(db):
        credential = await _get(db, credential_id, lock=True)
        if body.label is not None and body.label != credential.label:
            changes.append(f"라벨 {credential.label} → {body.label}")
            credential.label = body.label
        if "credit_usd" in body.model_fields_set:
            micro = _micro(body.credit_usd)
            if micro != credential.credit_micro_usd:
                changes.append(f"충전액 {_usd_text(credential.credit_micro_usd)} → {_usd_text(micro)} 달러")
                credential.credit_micro_usd = micro
                credential.credit_since = None if micro is None else datetime.now(UTC)
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
        _after_commit(notify, f"[Claude 자격] 수정 — {_subject(credential)} · {', '.join(changes)}")
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
    있어 교체만으로 그 기록이 지금 키의 확인이 아니게 된다. 같은 키를 다시 붙여넣으면(암호화 키를 잃어 저장한 키를 읽을 수
    없을 때 살리는 길) 지문이 같아 옛 확인 기록이 그대로 지금 키의 확인으로 센다 — 암호문만 지금 키로 다시 쓴다."""
    _require_store()
    api_key = _api_key(body.api_key)
    header = await _organization(probe, api_key)
    keyring = credential_keyring()
    async with credential_write(db):
        credential = await _get(db, credential_id, lock=True)
        if credential.provider != "anthropic":
            raise _rule(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "provider-not-available", "이 공급자의 키 교체는 아직 없습니다."
            )
        old_fingerprint = credential.secret_fingerprint
        old_is_env_key = same_as_env_key(credential)
        cleared = False
        if header is None:
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
        same_key = credential.secret_fingerprint == old_fingerprint
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
        message += " · 확인 호출 전까지 미확인" + _env_key_line(old_is_env_key)
        if same_as_env_key(credential):
            message += "\n새 키는 env 롤백 키와 같다"
    if cleared:
        message += "\n조직 미확인으로 돌아감"
    _after_commit(notify, message)
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
        _after_commit(notify, f"[Claude 자격] 켬 — {_subject(credential)}")
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
        _after_commit(notify, f"[Claude 자격] 끔 — {_subject(credential)}")
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
    _after_commit(notify, message)


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


def _axis_results(outcomes: Sequence[_Outcome]) -> list[str]:
    kinds = {axis: kind for group, kind, _ in outcomes for axis in group.axes}
    return [f"{axis} 통과" if kinds[axis] is None else f"{axis} 실패({kinds[axis]})" for axis in CLAUDE_AXES if axis in kinds]


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
    다시 시도할 일(과부하·시간 초과 등)로 실패한 축도 그 종류로 남는다 — 분당 한 번이라 1분 뒤 다시 누른다."""
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
    # 보인 조직은 그대로다. 아래 쓰기가 바꾸는 결과는 통과를 `account-already-listed` 로 돌리는 것뿐이라 신호가 달라지지 않는다.
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
        axis_results = _axis_results(outcomes)
        await record_admin_action(
            db,
            admin_id=admin_id,
            action_type="llm-credential-check",
            reason_text=f"{subject} · {', '.join(axis_results)}",
        )
        await db.flush()
        await db.commit()

    _after_commit(
        notify, f"[Claude 자격] 확인 — {subject} · {' · '.join(axis_results)}" + ("\n조직 확인됨" if fill else "")
    )
    return AdminLlmCredentialCheckResponse(
        credential=await _credential_response(db, credential_id), calls=len(groups)
    )
