"""어드민 기능 스위치 API — 목록, 덮어쓰기 바꾸기·지우기, 변경 이력.

값은 덮어쓰기가 있으면 그 값, 없으면 `.env` 값이다(읽는 쪽 `core/feature_switches.py`). 이 라우터는 늘 DB 를 읽어 답한다 — 이
요청은 시작 순간의 프로세스 맵에 고정돼 저장 전 값을 보고, 다른 프로세스의 저장은 맵에 한 간격 늦게 닿는다. 그래서 목록의
덮어쓰기·실효 값과 저장 응답의 실효 값·실제 상태는 접근자(`switch_on`)나 `payments_active()` 가 아니라 표와 저장 결과로 계산한다.
`.env` 값은 이 서버가 기동 때 읽은 `settings` 칸이다(파일을 고쳐도 교체 전에는 바뀌지 않는다).

**저장**(바꾸기·지우기) 검사 순서: 이름 → 사유 → 동시 저장(STALE) → 같은 값(UNCHANGED) → 켜기 선행 조건 → 이력 → 커밋.
동시 저장 판정은 쓰기 한 문장이 겸한다 — 화면이 본 덮어쓰기가 없으면 `INSERT … ON CONFLICT DO NOTHING`, 있으면
`UPDATE/DELETE … WHERE value = 기대값` 이고, 0행이면 다른 저장이 먼저 커밋한 것이다. 행이 없을 때는 잠글 행이 없어, 먼저 읽고
비교하면 같은 화면에서 낸 두 저장이 함께 지나가 둘 다 "전 = 없음" 이력을 남긴다. 비교 대상이 보낼 값이 아니라 화면이 본 값이라,
같은 화면에서 두 번 누른 저장도 같은 값(UNCHANGED)이 아니라 STALE 로 떨어진다. STALE 을 선행 조건보다 먼저 보는 것은, 이미 다른
운영자가 바꾼 상태에서 선행 조건 거절을 보이면 운영자가 낡은 화면 기준으로 원인을 찾기 때문이다. 거절은 커밋 전이라 쓴 행은
세션이 닫히며 되돌아간다.

**켜기 선행 조건**은 실효 값이 꺼짐에서 켜짐으로 바뀔 때만 본다(덮어쓰기로 켜거나, 지워서 `.env` 의 켬으로 가거나). 이미 켜진
값을 덮어쓰기로 붙잡아 두는 저장은 막지 않는다 — 실효 값이 그대로라, 막아도 선행 조건이 피하려던 상태(정지로 막힌 환불, 그림
있는 공개의 503)는 이미 그대로다.
- 클로버 정지: 진행 중 환불이 있으면 거절한다 — 정지 중에는 그 환불을 마무리하는 라우트도 막힌다. 확인과 커밋 사이에 시작된
  환불은 막지 못하므로 커밋 뒤 다시 세어 경고한다.
- 소설 화 삽화: 삽화 심사 레인에 활성 세트가 없으면 거절한다 — 켜면 그림이 있는 노벨 공개가 503 이 된다. 공개 라우트와 같은
  함수로 활성 세트를 찾는다.
- 나머지는 서버가 막지 않는다. 삽화는 켜는 순간 노벨 공개가 다른 레인(발행 심사)에 새로 기대게 되지만, 소설 구성 흐름·여러 문단
  수정이 읽는 문안은 소설화가 이미 쓰는 소설 레인 세트의 채널이고 어드민 게시 검증이 그 채널 없는 세트의 게시를 막는다 — 켜서 새로
  생기는 빈칸이 없다. 그런 세트로 돌더라도 구성안·여러 문단 수정 작업은 모델을 부르기 전에 실패해 환불된다.

**커밋 뒤**: 이 프로세스 맵을 바로 다시 읽고(실패하면 경고 — 주기 갱신이 따라온다), 운영 알림 채널에 쏘고 잊는다(실패는 저장과
무관). 문구는 스위치 이름·실효 전→후·사유만 싣는다. 커밋 뒤의 일은 서로 막지 않는다 — 하나가 실패해도 이미 커밋한 저장은 200 과
알림으로 끝난다.

사유는 앞뒤 공백을 유니코드 공백까지 걷고 1~1,000자다 — DB 의 CHECK(`btrim`)는 스페이스(U+0020)만 깎아 탭·줄바꿈·전각 공백만
있는 사유를 막지 못하고, 화면의 `trim` 은 유니코드 공백과 BOM 까지 걷는다. 1,000자는 이름·전→후와 함께 디스코드 글 상한(2,000자) 안에 든다.
"""

import logging
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminAdjustableSwitch,
    AdminFeatureSwitchChangeItem,
    AdminFeatureSwitchChangeListResponse,
    AdminFeatureSwitchChangeResult,
    AdminFeatureSwitchClearRequest,
    AdminFeatureSwitchListResponse,
    AdminFeatureSwitchSetRequest,
    AdminReadOnlySwitch,
    AdminSwitchEffectiveState,
    AdminSwitchOverride,
    AdminUnknownOverride,
    FeatureSwitchWarning,
)
from api.chat.prompt_builder import PromptSetNotFoundError, load_active_prompt_set
from api.core.config import settings
from api.core.feature_switch_notify import get_feature_switch_notifier
from api.core.feature_switches import (
    FEATURE_SWITCH_NAMES,
    READ_ONLY_SWITCH_REASONS,
    REFRESH_INTERVAL_SECONDS,
    FeatureSwitchName,
    is_switch_name,
    refresh_switch_overrides,
)
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import AdminUser
from api.db.models.feature_switch import FeatureSwitchChange, FeatureSwitchOverride
from api.db.models.payment import PaymentCancellation
from api.db.session import get_db_session, get_session_factory
from api.novel_public.illustration_screening import NOVEL_ILLUSTRATION_SCREEN_LANE
from api.payments.config import missing_identity_settings, missing_payment_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

Notifier = Callable[[str], None]

ADMIN_FEATURE_SWITCH_CHANGE_PAGE_SIZE = 20
REASON_MAX_LENGTH = 1000
# 앞뒤에서 걷을 공백 — 파이썬 `\s`(유니코드 공백)에 화면의 `trim` 이 함께 걷는 BOM 을 더한다.
_EDGE_SPACE = re.compile(r"^[\s﻿]+|[\s﻿]+$")


def _refuse(status_code: int, code: str, message: str, **extra: object) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def _read_only() -> NoReturn:
    _refuse(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "FEATURE_SWITCH_READ_ONLY",
        "어드민에서 바꿀 수 없는 스위치입니다.",
    )


def _stale() -> NoReturn:
    _refuse(
        status.HTTP_409_CONFLICT,
        "FEATURE_SWITCH_STALE",
        "다른 저장이 먼저 반영됐습니다. 새로 불러온 뒤 다시 저장해 주세요.",
    )


def _clean_reason(raw: str) -> str:
    reason = _EDGE_SPACE.sub("", raw)
    if not reason:
        _refuse(status.HTTP_422_UNPROCESSABLE_CONTENT, "FEATURE_SWITCH_REASON_REQUIRED", "사유를 입력해 주세요.")
    if len(reason) > REASON_MAX_LENGTH:
        _refuse(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "FEATURE_SWITCH_REASON_TOO_LONG",
            "사유는 1,000자까지 쓸 수 있습니다.",
            maxLength=REASON_MAX_LENGTH,
        )
    return reason


def _env_value(name: str) -> bool | None:
    """이 판의 `.env` 값. 버튼 대상이 아닌 이름은 참/거짓 칸이 있을 때만 그 값이고, 없으면(이 판이 모르는 이름) None."""
    value = getattr(settings, name, None)
    return value if isinstance(value, bool) else None


def _effective_state(name: FeatureSwitchName, effective: bool) -> AdminSwitchEffectiveState | None:
    if name == "payments_enabled":
        missing = missing_payment_settings()
    elif name == "identity_gate_enabled":
        missing = missing_identity_settings()
    else:
        return None
    return AdminSwitchEffectiveState(open=effective and not missing, missing_settings=missing)


def _adjustable(name: FeatureSwitchName, override: AdminSwitchOverride | None) -> AdminAdjustableSwitch:
    env_value: bool = getattr(settings, name)
    effective = override.value if override is not None else env_value
    return AdminAdjustableSwitch(
        name=name,
        env_value=env_value,
        override=override,
        effective_value=effective,
        effective_state=_effective_state(name, effective),
    )


def _on_off(value: bool) -> str:
    return "켜짐" if value else "꺼짐"


async def _admin_email(db: AsyncSession, admin_id: uuid.UUID) -> str:
    email: str = (await db.execute(select(AdminUser.email).where(AdminUser.id == admin_id))).scalar_one()
    return email


async def _requested_refunds(db: AsyncSession) -> int:
    """진행 중 환불(포트원 결과가 확정되지 않은 취소 시도) 수."""
    count: int = (
        await db.execute(select(func.count()).where(PaymentCancellation.status == "requested"))
    ).scalar_one()
    return count


async def _refuse_turning_on(db: AsyncSession, name: FeatureSwitchName) -> None:
    """실효 값이 꺼짐에서 켜짐으로 바뀌는 저장의 선행 조건(모듈 docstring)."""
    if name == "clover_ledger_paused":
        requested = await _requested_refunds(db)
        if requested:
            _refuse(
                status.HTTP_409_CONFLICT,
                "CLOVER_PAUSE_REFUNDS_IN_PROGRESS",
                "진행 중인 환불이 있어 클로버 정지를 켤 수 없습니다. 환불을 먼저 마무리해 주세요.",
                requestedCount=requested,
            )
    elif name == "novel_illustrations_enabled":
        try:
            await load_active_prompt_set(db, lane=NOVEL_ILLUSTRATION_SCREEN_LANE)
        except PromptSetNotFoundError:
            _refuse(
                status.HTTP_409_CONFLICT,
                "NOVEL_ILLUSTRATIONS_REVIEW_LANE_MISSING",
                "삽화를 심사할 프롬프트 세트가 없어 삽화를 켤 수 없습니다.",
            )


async def _write_override(
    db: AsyncSession, name: str, value: bool, expected: bool | None, admin_id: uuid.UUID
) -> datetime:
    """화면이 본 덮어쓰기(`expected`)가 지금과 같을 때만 `value` 로 쓰고 그 행의 시각을 돌려준다. 비교는 쓰기 문장이 겸한다(모듈
    docstring). 기대값이 맞는데 같은 값이면 409 `FEATURE_SWITCH_UNCHANGED` — 빈 이력을 남기지 않는다."""
    if expected is None:
        inserted = await db.execute(
            insert(FeatureSwitchOverride)
            .values(name=name, value=value, admin_id=admin_id)
            .on_conflict_do_nothing(index_elements=[FeatureSwitchOverride.name])
            .returning(FeatureSwitchOverride.updated_at)
        )
        written = inserted.scalar_one_or_none()
    elif value == expected:
        current = await db.scalar(select(FeatureSwitchOverride.value).where(FeatureSwitchOverride.name == name))
        if current != expected:
            _stale()
        _refuse(status.HTTP_409_CONFLICT, "FEATURE_SWITCH_UNCHANGED", "이미 그 값입니다.")
    else:
        updated = await db.execute(
            update(FeatureSwitchOverride)
            .where(FeatureSwitchOverride.name == name, FeatureSwitchOverride.value == expected)
            .values(value=value, admin_id=admin_id, updated_at=func.now())
            .returning(FeatureSwitchOverride.updated_at)
            .execution_options(synchronize_session=False)
        )
        written = updated.scalar_one_or_none()
    if written is None:
        _stale()
    return written


async def _record(
    db: AsyncSession,
    *,
    name: str,
    before: bool | None,
    after: bool | None,
    env_value: bool | None,
    reason: str,
    admin_id: uuid.UUID,
) -> AdminFeatureSwitchChangeItem:
    change = FeatureSwitchChange(
        name=name, before_override=before, after_override=after, env_value=env_value, reason=reason, admin_id=admin_id
    )
    db.add(change)
    await db.flush()
    await db.refresh(change, ["created_at"])
    return AdminFeatureSwitchChangeItem(
        id=change.id,
        name=name,
        before_override=before,
        after_override=after,
        env_value=env_value,
        reason=reason,
        admin_id=admin_id,
        admin_email=await _admin_email(db, admin_id),
        created_at=change.created_at,
    )


async def _after_commit(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    notify: Notifier,
    message: str,
    *,
    turned_on_clover_pause: bool,
) -> list[FeatureSwitchWarning]:
    """커밋이 끝난 저장의 뒷일 셋 — 서로 막지 않는다. 어느 하나가 실패해도 저장은 이미 커밋됐으니 200 으로 답하고 알림까지 보낸다.
    재집계가 실패하면 환불이 생겼는지 알 수 없어 경고를 달지 않고 서버 로그로만 남긴다."""
    warnings: list[FeatureSwitchWarning] = []
    if turned_on_clover_pause:
        try:
            if await _requested_refunds(db):
                warnings.append("refund-started-during-pause")
        except Exception as exc:
            logger.warning("클로버 정지를 켠 뒤 진행 중 환불을 다시 세지 못했다: %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="db")
    try:
        await refresh_switch_overrides(session_factory)
    except Exception as exc:
        logger.warning("기능 스위치 저장 뒤 이 프로세스의 덮어쓰기를 다시 읽지 못했다: %s", type(exc).__name__)
        capture_dependency_failure(exc, dependency="db")
        warnings.append("self-refresh-failed")
    notify(message)
    return warnings


@router.get("/admin/feature-switches")
async def list_feature_switches(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminFeatureSwitchListResponse:
    rows = (
        await db.execute(
            select(
                FeatureSwitchOverride.name,
                FeatureSwitchOverride.value,
                FeatureSwitchOverride.admin_id,
                AdminUser.email,
                FeatureSwitchOverride.updated_at,
            ).join(AdminUser, AdminUser.id == FeatureSwitchOverride.admin_id)
        )
    ).all()
    overrides = {
        name: AdminSwitchOverride(value=value, admin_id=admin_id, admin_email=email, updated_at=updated_at)
        for name, value, admin_id, email, updated_at in rows
    }
    return AdminFeatureSwitchListResponse(
        adjustable=[_adjustable(name, overrides.get(name)) for name in FEATURE_SWITCH_NAMES],
        read_only=[
            AdminReadOnlySwitch(name=name, value=getattr(settings, name), reason=reason)
            for name, reason in READ_ONLY_SWITCH_REASONS.items()
        ],
        unknown_overrides=[
            AdminUnknownOverride(name=name, **override.model_dump())
            for name, override in sorted(overrides.items())
            if not is_switch_name(name)
        ],
        refresh_interval_seconds=REFRESH_INTERVAL_SECONDS,
    )


@router.get("/admin/feature-switches/changes")
async def list_feature_switch_changes(
    page: int = Query(1, ge=1),
    switch_name: str | None = Query(None, alias="switch"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminFeatureSwitchChangeListResponse:
    """최신 먼저 20건씩. `switch` 로 거르면 이 판이 모르는 옛 이름도 거를 수 있다."""
    filters = [FeatureSwitchChange.name == switch_name] if switch_name is not None else []
    total_count = (await db.scalar(select(func.count()).select_from(FeatureSwitchChange).where(*filters))) or 0
    total_pages = -(-total_count // ADMIN_FEATURE_SWITCH_CHANGE_PAGE_SIZE) if total_count else 0
    rows = (
        await db.execute(
            select(FeatureSwitchChange, AdminUser.email)
            .join(AdminUser, AdminUser.id == FeatureSwitchChange.admin_id)
            .where(*filters)
            # 같은 시각의 행이 페이지 경계에서 흔들리지 않게 id 까지 정렬한다.
            .order_by(FeatureSwitchChange.created_at.desc(), FeatureSwitchChange.id)
            .offset((page - 1) * ADMIN_FEATURE_SWITCH_CHANGE_PAGE_SIZE)
            .limit(ADMIN_FEATURE_SWITCH_CHANGE_PAGE_SIZE)
        )
    ).all()
    return AdminFeatureSwitchChangeListResponse(
        items=[
            AdminFeatureSwitchChangeItem(
                id=change.id,
                name=change.name,
                before_override=change.before_override,
                after_override=change.after_override,
                env_value=change.env_value,
                reason=change.reason,
                admin_id=change.admin_id,
                admin_email=email,
                created_at=change.created_at,
            )
            for change, email in rows
        ],
        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )


@router.put("/admin/feature-switches/{name}")
async def set_feature_switch(
    name: str,
    body: AdminFeatureSwitchSetRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    notify: Notifier = Depends(get_feature_switch_notifier),
) -> AdminFeatureSwitchChangeResult:
    """덮어쓰기를 `value` 로 바꾼다. 경로의 이름은 문자열로 받아 버튼 대상이 아니면 422 `FEATURE_SWITCH_READ_ONLY` 로 거른다
    (이름 유니언으로 받으면 코드 없는 기본 422 가 나간다)."""
    if not is_switch_name(name):
        _read_only()
    reason = _clean_reason(body.reason)
    env_value: bool = getattr(settings, name)
    updated_at = await _write_override(db, name, body.value, body.expected_override, admin_id)
    before = body.expected_override if body.expected_override is not None else env_value
    turning_on = not before and body.value
    if turning_on:
        await _refuse_turning_on(db, name)
    change = await _record(
        db,
        name=name,
        before=body.expected_override,
        after=body.value,
        env_value=env_value,
        reason=reason,
        admin_id=admin_id,
    )
    await db.commit()

    message = f"[기능 스위치] {name} — {_on_off(before)} → {_on_off(body.value)} (어드민 덮어쓰기)\n사유: {reason}"
    warnings = await _after_commit(
        db, session_factory, notify, message, turned_on_clover_pause=turning_on and name == "clover_ledger_paused"
    )
    override = AdminSwitchOverride(
        value=body.value, admin_id=admin_id, admin_email=change.admin_email, updated_at=updated_at
    )
    return AdminFeatureSwitchChangeResult(switch=_adjustable(name, override), change=change, warnings=warnings)


@router.delete("/admin/feature-switches/{name}/override")
async def clear_feature_switch_override(
    name: str,
    body: AdminFeatureSwitchClearRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    notify: Notifier = Depends(get_feature_switch_notifier),
) -> AdminFeatureSwitchChangeResult:
    """덮어쓰기를 지워 `.env` 값으로 돌린다. 버튼 대상이 아니어도 덮어쓰기 행이 있는 이름(다른 판이 남긴 행)은 지울 수 있다 —
    그 판으로 되돌렸다가 다시 올라올 때 되살아나지 않게. 그런 이름은 응답의 `switch` 가 null 이다."""
    known: FeatureSwitchName | None = name if is_switch_name(name) else None
    if known is None:
        row = await db.scalar(select(FeatureSwitchOverride.name).where(FeatureSwitchOverride.name == name))
        if row is None:
            _read_only()
    reason = _clean_reason(body.reason)
    deleted = await db.execute(
        delete(FeatureSwitchOverride)
        .where(FeatureSwitchOverride.name == name, FeatureSwitchOverride.value == body.expected_override)
        .returning(FeatureSwitchOverride.name)
        .execution_options(synchronize_session=False)
    )
    if deleted.scalar_one_or_none() is None:
        _stale()
    env_value = _env_value(name)
    turning_on = known is not None and not body.expected_override and env_value is True
    if known is not None and turning_on:
        await _refuse_turning_on(db, known)
    change = await _record(
        db,
        name=name,
        before=body.expected_override,
        after=None,
        env_value=env_value,
        reason=reason,
        admin_id=admin_id,
    )
    await db.commit()

    if known is not None and env_value is not None:
        message = (
            f"[기능 스위치] {name} — {_on_off(body.expected_override)} → {_on_off(env_value)} (덮어쓰기를 지워 .env 값)"
            f"\n사유: {reason}"
        )
        switch: AdminAdjustableSwitch | None = _adjustable(known, None)
    else:
        message = f"[기능 스위치] {name} — 이 판이 다루지 않는 이름의 덮어쓰기를 지웠다(실효 값 그대로)\n사유: {reason}"
        switch = None
    warnings = await _after_commit(
        db, session_factory, notify, message, turned_on_clover_pause=turning_on and name == "clover_ledger_paused"
    )
    return AdminFeatureSwitchChangeResult(switch=switch, change=change, warnings=warnings)
