"""어드민 기능 스위치 API — 목록(버튼 대상·읽기 전용·이 판이 모르는 덮어쓰기), 덮어쓰기 바꾸기·지우기, 변경 이력.

목록과 저장 응답의 실효 값은 이 프로세스의 맵이 아니라 DB·저장 결과로 계산한다(같은 요청은 시작 때 맵을 고정해 저장 전 값을
보고, 다른 프로세스의 저장은 맵에 늦게 닿는다). 저장은 화면이 본 덮어쓰기와 지금 덮어쓰기가 같을 때만 한 문장으로 쓰고(비교-후-쓰기),
켜는 쪽으로 가면 선행 조건을 본 뒤 이력과 함께 커밋한다. 알림은 커밋 뒤 쏘고 잊는다."""

import asyncio
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import feature_switches as admin_feature_switches
from api.core.config import settings
from api.core.feature_switch_notify import get_feature_switch_notifier
from api.core.feature_switches import FEATURE_SWITCH_NAMES, READ_ONLY_SWITCH_REASONS, switch_on
from api.db.models import AdminUser, FeatureSwitchChange, FeatureSwitchOverride, PaymentCancellation, PromptSet
from api.db.session import engine
from api.main import app
from api.payments.config import payments_active
from factories import _create_admin, _eventually, _login_as, _login_as_admin, _make_payment, _make_user, _patch_httpx

_BASE = "/admin/feature-switches"
_PAYMENT_KEYS = (
    "portone_store_id",
    "portone_payment_channel_key",
    "portone_identity_channel_key",
    "portone_api_secret",
    "portone_webhook_secret",
    "identity_ci_hmac_key",
)


@pytest.fixture(autouse=True)
def _no_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬 `.env` 에 운영 채널 주소가 있어도 시험이 그리로 보내지 않게 비워 둔다. 보내는 길을 보는 시험은 다시 채운다."""
    monkeypatch.setattr(settings, "discord_webhook_url", "")


@pytest.fixture
def notes() -> Iterator[list[str]]:
    sent: list[str] = []
    app.dependency_overrides[get_feature_switch_notifier] = lambda: sent.append
    yield sent
    app.dependency_overrides.pop(get_feature_switch_notifier, None)


@pytest.fixture
async def admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> dict[str, object]:
    payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, payload)
    return payload


def _keys_present(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _PAYMENT_KEYS:
        monkeypatch.setattr(settings, key, f"{key}-test")


async def _override(db_session: AsyncSession, name: str, value: bool, admin_id: object) -> None:
    db_session.add(FeatureSwitchOverride(name=name, value=value, admin_id=admin_id))
    await db_session.flush()


async def _overrides(db_session: AsyncSession) -> dict[str, bool]:
    rows = (await db_session.execute(sa.select(FeatureSwitchOverride.name, FeatureSwitchOverride.value))).all()
    return {name: value for name, value in rows}


async def _changes(db_session: AsyncSession) -> list[tuple[str, bool | None, bool | None, bool | None, str]]:
    rows = (
        await db_session.execute(
            sa.select(
                FeatureSwitchChange.name,
                FeatureSwitchChange.before_override,
                FeatureSwitchChange.after_override,
                FeatureSwitchChange.env_value,
                FeatureSwitchChange.reason,
            ).order_by(FeatureSwitchChange.created_at, FeatureSwitchChange.reason)
        )
    ).all()
    return [tuple(row) for row in rows]


async def _requested_refund(db_session: AsyncSession) -> PaymentCancellation:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    payment = await _make_payment(db_session, user_id=user.id, status="paid")
    cancellation = PaymentCancellation(payment_id=payment.id, source="console", status="requested", amount_krw=9_900)
    db_session.add(cancellation)
    await db_session.flush()
    return cancellation


# ── 권한 ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("GET", _BASE, None, id="list"),
        pytest.param("GET", f"{_BASE}/changes", None, id="changes"),
        pytest.param(
            "PUT", f"{_BASE}/payments_enabled", {"value": True, "reason": "x", "expectedOverride": None}, id="set"
        ),
        pytest.param(
            "DELETE", f"{_BASE}/payments_enabled/override", {"reason": "x", "expectedOverride": True}, id="clear"
        ),
    ],
)
async def test_every_route_needs_an_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession, method: str, path: str, body: dict[str, object] | None
) -> None:
    """회원 세션으로는 어드민 세션이 되지 않는다. 깨지는 시나리오: 라우트 하나가 어드민 의존성을 빠뜨려 아무나 결제·클로버
    정지를 켜고 끈다."""
    assert (await db_client.request(method, path, json=body)).status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    assert (await db_client.request(method, path, json=body)).status_code == 401
    assert await _overrides(db_session) == {}


# ── 목록 ─────────────────────────────────────────────────────────────────────


async def test_the_list_reads_values_from_the_table_and_names_missing_payment_settings(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """목록은 이 요청에서 표를 읽어 덮어쓰기·실효 값을 낸다 — 이 프로세스 맵에 아직 닿지 않은 저장도 보인다. 결제·본인인증은
    키 설정까지 본 실제 상태와 비어 있는 설정의 env 키 이름(값 없이)을 싣는다. 깨지는 시나리오: 목록이 고정된 맵(`switch_on`)으로
    실효 값을 내 다른 프로세스가 방금 켠 클로버 정지가 꺼진 것으로 보이거나, 결제를 켰는데 키가 비어 닫힌 사실이 안 보인다."""
    _keys_present(monkeypatch)
    monkeypatch.setattr(settings, "portone_webhook_secret", "")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "")
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "identity_gate_enabled", True)
    monkeypatch.setattr(settings, "novelize_enabled", True)
    monkeypatch.setattr(settings, "clover_ledger_paused", False)
    monkeypatch.setattr(settings, "novel_bible_enabled", False)
    for name in ("payments_enabled", "novelize_enabled"):
        await _override(db_session, name, name == "payments_enabled", admin["id"])
    await _override(db_session, "novel_bible_enabled", True, admin["id"])
    await _override(db_session, "retired_switch", False, admin["id"])

    resp = await db_client.get(_BASE)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = {row["name"]: row for row in body["adjustable"]}
    assert [row["name"] for row in body["adjustable"]] == list(FEATURE_SWITCH_NAMES)
    payments = rows["payments_enabled"]
    assert (payments["envValue"], payments["override"]["value"], payments["effectiveValue"]) == (False, True, True)
    assert (payments["override"]["adminId"], payments["override"]["adminEmail"]) == (str(admin["id"]), admin["email"])
    assert payments["effectiveState"] == {
        "open": False,
        "missingSettings": ["PORTONE_WEBHOOK_SECRET", "IDENTITY_CI_HMAC_KEY"],
    }
    gate = rows["identity_gate_enabled"]
    assert (gate["envValue"], gate["override"], gate["effectiveValue"]) == (True, None, True)
    assert gate["effectiveState"] == {"open": False, "missingSettings": ["IDENTITY_CI_HMAC_KEY"]}
    novelize = rows["novelize_enabled"]
    assert (novelize["envValue"], novelize["override"]["value"], novelize["effectiveValue"]) == (True, False, False)
    assert novelize["effectiveState"] is None
    clover = rows["clover_ledger_paused"]
    assert (clover["envValue"], clover["override"], clover["effectiveValue"]) == (False, None, False)

    assert {row["name"]: row["reason"] for row in body["readOnly"]} == READ_ONLY_SWITCH_REASONS
    assert {row["name"]: row["value"] for row in body["readOnly"]}["novel_bible_enabled"] is False
    assert {(row["name"], row["value"], row["adminEmail"]) for row in body["unknownOverrides"]} == {
        ("novel_bible_enabled", True, admin["email"]),
        ("retired_switch", False, admin["email"]),
    }
    assert body["refreshIntervalSeconds"] == 2.0
    # 이 프로세스 맵은 아직 표를 다시 읽지 않았다 — 위 값은 맵이 아니라 표에서 왔다.
    assert switch_on("payments_enabled") is False


# ── 바꾸기 · 지우기 ───────────────────────────────────────────────────────────


async def test_setting_an_override_saves_it_with_history_and_this_process_follows_at_once(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """덮어쓰기와 이력 한 행이 함께 남고, 응답의 실효 값·실제 상태는 저장 결과로 계산하며, 저장한 프로세스는 응답 전에 새 값을
    본다. 알림은 스위치·실효 전→후·사유만 싣는다. 깨지는 시나리오: 응답이 요청 시작 때 고정된 값(저장 전 값)을 실어 화면이
    반대로 그려지거나, 이 프로세스가 주기 갱신까지 옛 값으로 돌거나, 알림에 운영자 이메일이 실린다."""
    _keys_present(monkeypatch)
    monkeypatch.setattr(settings, "payments_enabled", False)

    resp = await db_client.put(
        f"{_BASE}/payments_enabled", json={"value": True, "reason": "  결제 시행  ", "expectedOverride": None}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"] == []
    assert (body["switch"]["envValue"], body["switch"]["effectiveValue"]) == (False, True)
    assert body["switch"]["override"]["value"] is True
    assert body["switch"]["override"]["adminEmail"] == admin["email"]
    assert body["switch"]["effectiveState"] == {"open": True, "missingSettings": []}
    change = body["change"]
    assert (change["name"], change["beforeOverride"], change["afterOverride"], change["envValue"]) == (
        "payments_enabled",
        None,
        True,
        False,
    )
    assert (change["reason"], change["adminId"], change["adminEmail"]) == ("결제 시행", str(admin["id"]), admin["email"])
    assert await _overrides(db_session) == {"payments_enabled": True}
    assert await _changes(db_session) == [("payments_enabled", None, True, False, "결제 시행")]
    assert switch_on("payments_enabled") is True
    assert payments_active() is True

    resp = await db_client.put(
        f"{_BASE}/payments_enabled", json={"value": False, "reason": "점검", "expectedOverride": True}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["switch"]["effectiveValue"] is False
    assert resp.json()["switch"]["effectiveState"] == {"open": False, "missingSettings": []}
    assert await _overrides(db_session) == {"payments_enabled": False}
    assert switch_on("payments_enabled") is False
    assert notes == [
        "[기능 스위치] payments_enabled — 꺼짐 → 켜짐 (어드민 덮어쓰기)\n사유: 결제 시행",
        "[기능 스위치] payments_enabled — 켜짐 → 꺼짐 (어드민 덮어쓰기)\n사유: 점검",
    ]
    assert not any(str(admin["email"]) in note or str(admin["id"]) in note for note in notes)


async def test_clearing_an_override_returns_to_the_env_value(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """지우면 행이 사라지고 이력에 그 순간의 `.env` 값이 남으며, 이 프로세스는 바로 `.env` 값으로 돈다. 깨지는 시나리오:
    지운 뒤에도 이 프로세스가 옛 덮어쓰기로 돌거나, 이력의 `.env` 값이 비어 그때의 실효 값을 알 수 없다."""
    monkeypatch.setattr(settings, "memory_items_visible", True)
    await _override(db_session, "memory_items_visible", False, admin["id"])

    resp = await db_client.request(
        "DELETE", f"{_BASE}/memory_items_visible/override", json={"reason": "되돌림", "expectedOverride": False}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["switch"]["override"], body["switch"]["effectiveValue"]) == (None, True)
    assert (body["change"]["beforeOverride"], body["change"]["afterOverride"], body["change"]["envValue"]) == (
        False,
        None,
        True,
    )
    assert await _overrides(db_session) == {}
    assert switch_on("memory_items_visible") is True
    assert notes == ["[기능 스위치] memory_items_visible — 꺼짐 → 켜짐 (덮어쓰기를 지워 .env 값)\n사유: 되돌림"]


@pytest.mark.parametrize(
    ("name", "env_value"),
    [pytest.param("retired_switch", None, id="no-settings-field"), pytest.param("novel_bible_enabled", True, id="read-only")],
)
async def test_clearing_an_override_this_version_does_not_handle(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    env_value: bool | None,
) -> None:
    """버튼 대상이 아닌 이름도 덮어쓰기 행이 있으면 지울 수 있다. 이 판에 그 이름의 참/거짓 `.env` 칸이 없으면 이력의 `.env`
    값은 비운다. 깨지는 시나리오: 새 판이 더한 스위치를 덮어쓴 뒤 그 이름을 모르는 판으로 롤백했을 때 남은 행을 지우려다
    `.env` 칸을 못 찾아 500 이 나, 다시 새 판을 올리는 순간 그 덮어쓰기가 되살아난다."""
    monkeypatch.setattr(settings, "novel_bible_enabled", True)
    await _override(db_session, name, False, admin["id"])

    resp = await db_client.request(
        "DELETE", f"{_BASE}/{name}/override", json={"reason": "옛 덮어쓰기 정리", "expectedOverride": False}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["switch"] is None
    assert resp.json()["change"]["envValue"] is env_value
    assert await _overrides(db_session) == {}
    assert await _changes(db_session) == [(name, False, None, env_value, "옛 덮어쓰기 정리")]
    assert notes == [f"[기능 스위치] {name} — 이 판이 다루지 않는 이름의 덮어쓰기를 지웠다(실효 값 그대로)\n사유: 옛 덮어쓰기 정리"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("PUT", "novel_bible_enabled", {"value": True}, id="read-only"),
        pytest.param("PUT", "no_such_switch", {"value": True}, id="unknown"),
        pytest.param("DELETE", "no_such_switch/override", {"expectedOverride": True}, id="clear-without-row"),
        pytest.param("DELETE", "novel_bible_enabled/override", {"expectedOverride": True}, id="clear-read-only"),
    ],
)
async def test_a_switch_without_a_button_is_refused(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    method: str,
    path: str,
    body: dict[str, object],
) -> None:
    """기동 검증·워커·크론과 엮인 스위치와 모르는 이름은 바꿀 수 없고, 버튼 대상이 아닌 이름은 덮어쓰기 행이 있을 때만 지울 수
    있다. 깨지는 시나리오: 덮어쓰기로 소설 정본 기억을 켜 기동 검증을 건너뛰거나, 아무 이름이나 표에 쌓인다."""
    resp = await db_client.request(
        method, f"{_BASE}/{path}", json={"reason": "시험", "expectedOverride": None, **body}
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "FEATURE_SWITCH_READ_ONLY"
    assert (await _overrides(db_session), await _changes(db_session), notes) == ({}, [], [])


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="ascii-spaces"),
        pytest.param("　 \t\n", id="ideographic-and-no-break-spaces"),
        pytest.param("﻿ ", id="byte-order-mark-and-em-space"),
    ],
)
async def test_a_blank_reason_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin: dict[str, object], notes: list[str], reason: str
) -> None:
    """사유는 앞뒤 공백을 걷은 뒤 비면 거절한다 — 유니코드 공백까지(화면의 `trim` 과 같은 범위). 깨지는 시나리오: 전각 공백만
    친 사유가 DB 의 공백 검사(ASCII 공백만 깎는다)를 지나 누가 왜 바꿨는지 모르는 이력이 남는다."""
    resp = await db_client.put(
        f"{_BASE}/payments_enabled", json={"value": True, "reason": reason, "expectedOverride": None}
    )
    cleared = await db_client.request(
        "DELETE", f"{_BASE}/payments_enabled/override", json={"reason": reason, "expectedOverride": True}
    )

    assert [resp.status_code, cleared.status_code] == [422, 422]
    assert [resp.json()["detail"]["code"], cleared.json()["detail"]["code"]] == ["FEATURE_SWITCH_REASON_REQUIRED"] * 2
    assert (await _overrides(db_session), await _changes(db_session), notes) == ({}, [], [])


async def test_the_reason_limit_counts_after_trimming(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin: dict[str, object], notes: list[str]
) -> None:
    """사유 상한(1,000자)은 앞뒤 공백을 걷은 글로 센다 — 화면과 같은 규칙이라 화면이 통과시킨 사유를 서버가 다르게 거절하지
    않는다. 깨지는 시나리오: 상한을 걷기 전 길이로 세 화면에서 통과한 사유가 이름 없는 422 로 떨어지거나, 상한이 없어 알림이
    디스코드 2,000자 상한을 넘어 버려진다."""
    too_long = await db_client.put(
        f"{_BASE}/payments_enabled", json={"value": True, "reason": "가" * 1001, "expectedOverride": None}
    )
    padded = await db_client.put(
        f"{_BASE}/payments_enabled",
        json={"value": True, "reason": f"  {'가' * 1000}　", "expectedOverride": None},
    )

    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["detail"] == {
        "code": "FEATURE_SWITCH_REASON_TOO_LONG",
        "message": "사유는 1,000자까지 쓸 수 있습니다.",
        "maxLength": 1000,
    }
    assert padded.status_code == 200, padded.text
    assert padded.json()["change"]["reason"] == "가" * 1000


async def test_a_second_save_from_the_same_screen_is_stale(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin: dict[str, object], notes: list[str]
) -> None:
    """화면이 본 덮어쓰기와 지금 덮어쓰기가 다르면 409 `FEATURE_SWITCH_STALE` 이다 — 행이 없다고 본 두 번째 저장, 행이 있다고 본
    두 번째 저장·지우기 모두. 두 번 누름도 여기로 떨어진다. 깨지는 시나리오: 두 운영자가 같은 화면에서 저장해 둘 다 "전 = 없음"
    이력이 남거나, 다른 운영자가 방금 바꾼 값을 모른 채 덮어쓴다."""
    first = {"value": True, "reason": "첫 저장", "expectedOverride": None}
    assert (await db_client.put(f"{_BASE}/novelize_enabled", json=first)).status_code == 200
    absent = await db_client.put(f"{_BASE}/novelize_enabled", json={**first, "reason": "같은 화면"})

    flip = {"value": False, "reason": "끄기", "expectedOverride": True}
    assert (await db_client.put(f"{_BASE}/novelize_enabled", json=flip)).status_code == 200
    present = await db_client.put(f"{_BASE}/novelize_enabled", json={**flip, "reason": "같은 화면"})
    cleared = await db_client.request(
        "DELETE", f"{_BASE}/novelize_enabled/override", json={"reason": "같은 화면", "expectedOverride": True}
    )

    assert [absent.status_code, present.status_code, cleared.status_code] == [409, 409, 409]
    assert {r.json()["detail"]["code"] for r in (absent, present, cleared)} == {"FEATURE_SWITCH_STALE"}
    assert await _overrides(db_session) == {"novelize_enabled": False}
    assert [change[4] for change in await _changes(db_session)] == ["끄기", "첫 저장"]
    assert len(notes) == 2


async def test_saving_the_current_override_again_is_unchanged(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin: dict[str, object], notes: list[str]
) -> None:
    """화면이 본 값이 맞는데 같은 값을 보내면 409 `FEATURE_SWITCH_UNCHANGED` 이고 빈 이력을 남기지 않는다. 깨지는 시나리오:
    아무것도 바뀌지 않은 저장이 이력·알림을 남겨 채널에 바뀐 것처럼 보인다."""
    await _override(db_session, "novelize_enabled", True, admin["id"])

    resp = await db_client.put(
        f"{_BASE}/novelize_enabled", json={"value": True, "reason": "다시", "expectedOverride": True}
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "FEATURE_SWITCH_UNCHANGED"
    assert (await _changes(db_session), notes) == ([], [])


async def _commit_admin() -> uuid.UUID:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = AdminUser(email=f"admin-{uuid.uuid4()}@example.com", password_hash="unused")
        db.add(admin)
        await db.commit()
        return admin.id


async def _waiting_on_a_lock() -> bool:
    async with engine.connect() as conn:
        waiting = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )
    return bool(waiting)


@pytest.mark.parametrize(
    ("existing", "expected", "value"),
    [pytest.param(None, None, True, id="no-row-yet"), pytest.param(True, True, False, id="row-present")],
)
async def test_of_two_racing_saves_from_the_same_screen_only_one_writes(
    existing: bool | None, expected: bool | None, value: bool
) -> None:
    """두 트랜잭션이 같은 기대값으로 동시에 쓰면 먼저 커밋한 쪽만 쓰고 나머지는 STALE 이다. 행이 없을 때는 잠글 행이 없어
    "먼저 읽고 비교"로는 막을 수 없다 — 쓰기 한 문장이 비교를 겸해야 한다. 깨지는 시나리오: 둘 다 "덮어쓰기 없음"을 읽고 둘 다
    써서 이력 두 행의 "전" 이 모두 없음이 되고 뒤에 쓴 값이 말없이 이긴다(실제 커밋하는 두 연결로 본다)."""
    admin_id = await _commit_admin()
    name = "local_image_reference_enabled"
    try:
        if existing is not None:
            async with AsyncSession(engine) as db:
                db.add(FeatureSwitchOverride(name=name, value=existing, admin_id=admin_id))
                await db.commit()
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await admin_feature_switches._write_override(first, name, value, expected, admin_id)
            racing = asyncio.create_task(admin_feature_switches._write_override(second, name, value, expected, admin_id))
            await _eventually(_waiting_on_a_lock)
            await first.commit()
            with pytest.raises(HTTPException) as refused:
                await racing
            await second.rollback()
        assert refused.value.status_code == 409
        assert isinstance(refused.value.detail, dict)
        assert refused.value.detail["code"] == "FEATURE_SWITCH_STALE"
    finally:
        async with AsyncSession(engine) as db:
            await db.execute(sa.delete(FeatureSwitchOverride).where(FeatureSwitchOverride.name == name))
            await db.execute(sa.delete(AdminUser).where(AdminUser.id == admin_id))
            await db.commit()


# ── 켜기 선행 조건 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("by_clearing", [pytest.param(False, id="override-on"), pytest.param(True, id="clear-to-env-on")])
async def test_turning_on_the_clover_pause_waits_for_refunds_in_progress(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    committing_request_session: None,
    monkeypatch: pytest.MonkeyPatch,
    by_clearing: bool,
) -> None:
    """진행 중 환불이 있으면 클로버 정지를 켜는 저장(덮어쓰기로 켬, 또는 지워서 `.env` 의 켬으로 감)을 거절하고 아무것도 남기지
    않는다. 환불이 끝나면 같은 저장이 된다. 깨지는 시나리오: 정지가 켜져 그 환불을 마무리하는 라우트까지 막혀, 회수한 클로버와
    포트원 취소가 어긋난 채 묶인다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", by_clearing)
    if by_clearing:
        await _override(db_session, "clover_ledger_paused", False, admin["id"])
    cancellation = await _requested_refund(db_session)
    await db_session.commit()

    async def turn_on() -> httpx.Response:
        if by_clearing:
            return await db_client.request(
                "DELETE", f"{_BASE}/clover_ledger_paused/override", json={"reason": "전환", "expectedOverride": False}
            )
        return await db_client.put(
            f"{_BASE}/clover_ledger_paused", json={"value": True, "reason": "전환", "expectedOverride": None}
        )

    refused = await turn_on()

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "CLOVER_PAUSE_REFUNDS_IN_PROGRESS"
    assert refused.json()["detail"]["requestedCount"] == 1
    assert await _overrides(db_session) == ({"clover_ledger_paused": False} if by_clearing else {})
    assert (await _changes(db_session), notes) == ([], [])

    cancellation.status = "succeeded"
    await db_session.commit()
    resp = await turn_on()

    assert resp.status_code == 200, resp.text
    assert resp.json()["switch"]["effectiveValue"] is True
    assert resp.json()["warnings"] == []


async def test_pinning_a_clover_pause_that_is_already_on_is_not_held_by_refunds(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """선행 조건은 실효 값이 꺼짐에서 켜짐으로 바뀔 때만 본다 — `.env` 로 이미 정지한 상태를 덮어쓰기로 붙잡아 두는 저장은
    막지 않는다(실효 값이 그대로라 그 환불은 이미 막혀 있고, 거절해도 달라지는 것이 없다). 깨지는 시나리오: 이미 켜진 정지를
    덮어쓰기로 남기려는데 진행 중 환불 때문에 거절된다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", True)
    await _requested_refund(db_session)

    resp = await db_client.put(
        f"{_BASE}/clover_ledger_paused", json={"value": True, "reason": "붙잡기", "expectedOverride": None}
    )

    assert resp.status_code == 200, resp.text


async def test_a_refund_started_while_turning_on_the_pause_is_warned(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """확인과 커밋 사이에 환불이 시작되면 저장은 그대로 두고 응답에 경고를 싣는다(커밋 뒤 다시 센다). 깨지는 시나리오: 정지가
    켜진 채 마무리할 수 없는 환불이 생긴 것을 운영자가 모른다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", False)
    counts = iter([0, 1])

    async def requested_refunds(_db: AsyncSession) -> int:
        return next(counts)

    monkeypatch.setattr(admin_feature_switches, "_requested_refunds", requested_refunds)

    resp = await db_client.put(
        f"{_BASE}/clover_ledger_paused", json={"value": True, "reason": "전환", "expectedOverride": None}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["warnings"] == ["refund-started-during-pause"]
    assert await _overrides(db_session) == {"clover_ledger_paused": True}


@pytest.mark.parametrize("by_clearing", [pytest.param(False, id="override-on"), pytest.param(True, id="clear-to-env-on")])
async def test_turning_on_illustrations_needs_an_active_review_prompt_set(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
    by_clearing: bool,
) -> None:
    """삽화 심사 레인에 활성 세트가 없으면 삽화를 켜는 저장을 거절한다(지워서 `.env` 의 켬으로 가는 경우도). 깨지는 시나리오:
    삽화가 켜져 그림이 있는 노벨 공개가 전부 503 이 된다."""
    monkeypatch.setattr(settings, "novel_illustrations_enabled", by_clearing)
    if by_clearing:
        await _override(db_session, "novel_illustrations_enabled", False, admin["id"])
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.lane == "publish_filter").values(status="archived")
    )

    if by_clearing:
        resp = await db_client.request(
            "DELETE", f"{_BASE}/novel_illustrations_enabled/override", json={"reason": "켜기", "expectedOverride": False}
        )
    else:
        resp = await db_client.put(
            f"{_BASE}/novel_illustrations_enabled", json={"value": True, "reason": "켜기", "expectedOverride": None}
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "NOVEL_ILLUSTRATIONS_REVIEW_LANE_MISSING"
    assert notes == []


async def test_turning_on_illustrations_with_a_review_prompt_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin: dict[str, object], notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "novel_illustrations_enabled", False)

    resp = await db_client.put(
        f"{_BASE}/novel_illustrations_enabled", json={"value": True, "reason": "켜기", "expectedOverride": None}
    )

    assert resp.status_code == 200, resp.text


# ── 저장 뒤 ───────────────────────────────────────────────────────────────────


async def test_a_failed_self_refresh_is_a_warning_not_a_failure(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """커밋 뒤 이 프로세스 맵을 다시 읽지 못해도 저장은 성공이고 경고로 알린다(주기 갱신이 곧 따라온다). 깨지는 시나리오: 이미
    커밋한 저장을 실패로 보고해 운영자가 다시 누르고 STALE 을 받거나, 반영이 늦는 사실을 모른다."""

    async def unreadable(_factory: object) -> None:
        raise ConnectionRefusedError("DB 가 안 된다")

    monkeypatch.setattr(admin_feature_switches, "refresh_switch_overrides", unreadable)

    resp = await db_client.put(
        f"{_BASE}/novelize_enabled", json={"value": True, "reason": "켜기", "expectedOverride": None}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["warnings"] == ["self-refresh-failed"]
    assert await _overrides(db_session) == {"novelize_enabled": True}
    assert len(notes) == 1


async def test_a_failing_notification_does_not_fail_the_save(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """실제 알림 길에서 웹훅이 실패해도 저장은 남고 응답은 성공이다. 깨지는 시나리오: 디스코드 장애 동안 스위치를 바꿀 수 없거나,
    알림 실패가 커밋한 저장을 실패로 보고한다."""
    from api.core import feature_switch_notify

    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.invalid/api/webhooks/0/switch-hook")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    _patch_httpx(monkeypatch, handler, module="api.core.feature_switch_notify")
    caplog.set_level(logging.WARNING, logger="api.core.feature_switch_notify")

    resp = await db_client.put(
        f"{_BASE}/novelize_enabled", json={"value": True, "reason": "켜기", "expectedOverride": None}
    )
    await asyncio.gather(*feature_switch_notify._pending)

    assert resp.status_code == 200, resp.text
    assert await _overrides(db_session) == {"novelize_enabled": True}
    assert "feature switch notification failed: ConnectError" in caplog.text


async def test_an_empty_webhook_skips_the_notification(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """운영 채널 주소가 비면 보내지 않고 경고만 남긴다 — 저장은 막지 않는다. 깨지는 시나리오: 주소 없는 로컬·시험 환경에서
    스위치를 바꾸면 빈 주소로 요청하다 실패하거나 저장이 막힌다."""
    from api.core import feature_switch_notify

    caplog.set_level(logging.WARNING, logger="api.core.feature_switch_notify")

    resp = await db_client.put(
        f"{_BASE}/novelize_enabled", json={"value": True, "reason": "켜기", "expectedOverride": None}
    )

    assert resp.status_code == 200, resp.text
    assert feature_switch_notify._pending == set()
    assert "feature switch notification skipped: webhook not configured" in caplog.text


# ── 이력 ─────────────────────────────────────────────────────────────────────


async def test_change_history_pages_by_twenty_newest_first_and_filters_by_switch(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin: dict[str, object]
) -> None:
    """이력은 최신 먼저 20건씩이고, 스위치 이름으로 거른다(이 판이 모르는 옛 이름도). 깨지는 시나리오: 옛 기록이 앞에 와 방금
    바꾼 사람이 안 보이거나, 거르기가 무시돼 다른 스위치 기록이 섞인다."""
    start = datetime(2026, 11, 1, tzinfo=UTC)
    for minute in range(21):
        db_session.add(
            FeatureSwitchChange(
                name="payments_enabled",
                before_override=None,
                after_override=True,
                env_value=False,
                reason=f"결제 {minute}",
                admin_id=admin["id"],
                created_at=start + timedelta(minutes=minute),
            )
        )
    db_session.add(
        FeatureSwitchChange(
            name="retired_switch",
            before_override=True,
            after_override=None,
            env_value=None,
            reason="옛 이름",
            admin_id=admin["id"],
            created_at=start - timedelta(days=1),
        )
    )
    await db_session.flush()

    first = (await db_client.get(f"{_BASE}/changes")).json()
    second = (await db_client.get(f"{_BASE}/changes", params={"page": 2})).json()
    retired = (await db_client.get(f"{_BASE}/changes", params={"switch": "retired_switch"})).json()
    payments = (await db_client.get(f"{_BASE}/changes", params={"switch": "payments_enabled"})).json()

    assert (first["page"], first["totalPages"], first["totalCount"]) == (1, 2, 22)
    assert [item["reason"] for item in first["items"]] == [f"결제 {minute}" for minute in range(20, 0, -1)]
    assert first["items"][0]["adminEmail"] == admin["email"]
    assert [item["reason"] for item in second["items"]] == ["결제 0", "옛 이름"]
    assert [(item["name"], item["envValue"]) for item in retired["items"]] == [("retired_switch", None)]
    assert (payments["totalCount"], payments["totalPages"]) == (21, 2)
