"""크리에이터 지급: 지급 정보 입력(검증·암호화·판 갈기), 지급 신청(잔액 전액·최소액·탈퇴 전 예외·원천징수 스냅숏), 어드민
지급 처리(목록·상세·원문 열람·이체 기록·반려, 탈퇴한 회원 건의 보류·수취 정보 교체), 탈퇴 뒤 보존, 키 회전·분실, 어드민 회원
상세의 정산 섹션.

잔액은 확정 행을 직접 넣어 만든다(확정 계산은 정산 테스트 몫이다). 회원은 2000-01-01생 본인인증 성인이고, 그 사람의
주민등록번호는 `RRN`(2000년대 출생 여성, 7번째 자리 4)이다.
"""

import asyncio
import base64
import importlib.util
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Literal

import httpx
import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.admin.creator_payout import return_creator_payout
from api.admin.schemas import AdminCreatorPayoutReturnRequest
from api.auth.withdrawal import erase_account
from api.comments.access import lock_active_user
from api.core import config
from api.core.config import settings
from api.core.field_crypto import FieldDecryptError, FieldKeyring
from api.core.rate_limit import KST
from api.core.security import hash_withdrawn_email
from api.creator_payout.payout_info import (
    EncryptedColumn,
    PayoutInfo,
    decrypt_field,
    mask_name,
    new_profile,
    parse_payout_info,
)
from api.creator_payout.monthly import run_monthly
from api.creator_payout.reencrypt import reencrypt_profiles
from api.creator_payout.router import balance_krw, member_payout_status, payout_requested_message
from api.creator_payout.tax import withholding
from api.db.models.auth import AdminUser, User, WithdrawnEmail
from api.db.models.creator_payout import (
    CreatorPayout,
    CreatorPayoutApplication,
    CreatorPayoutConfirmation,
    CreatorPayoutProfile,
    CreatorPayoutStatus,
)
from api.db.models.moderation import AdminActionLog
from api.legal.dependencies import _latest_published_legal_version
from api.main import app
from api.payments.notify import get_payment_notifier
from factories import (
    CREATOR_PAYOUT_TEST_KEYS,
    _application,
    _assert_blocked,
    _create_admin,
    _login_as,
    _login_as_admin,
    _make_user,
)

RRN = "0001014123456"
ACCOUNT = "110123456789"
PLAINTEXTS: tuple[tuple[EncryptedColumn, str], ...] = (("legal_name", "홍길동"), ("rrn", RRN), ("account_number", ACCOUNT))
OTHER_KEYS = "k9:" + base64.urlsafe_b64encode(bytes(range(100, 132))).decode()


# ── 셋업 ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _creator_payout_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """정산은 스위치와 본인인증 설정, 지급 정보 암호화 키가 모두 있어야 켜진다. 로컬 `.env` 의 값이 아니라 테스트가 정한다."""
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "creator_payout_encryption_keys", CREATOR_PAYOUT_TEST_KEYS)
    monkeypatch.setattr(settings, "creator_payout_enabled", True)
    monkeypatch.setattr(settings, "creator_payout_minimum_krw", 10_000)


@pytest.fixture(autouse=True)
def notifications() -> Iterator[list[str]]:
    sent: list[str] = []

    async def record(message: str) -> None:
        sent.append(message)

    app.dependency_overrides[get_payment_notifier] = lambda: record
    yield sent
    app.dependency_overrides.pop(get_payment_notifier, None)


async def _member(db: AsyncSession, status: Literal["approved", "revoked", "pending"] | None = "approved") -> User:
    """본인인증한 성인(2000-01-01생)과 그 정산 신청 행."""
    user = _make_user(
        identity_ci_hmac=uuid.uuid4().hex, identity_verified_at=datetime.now(UTC), birth_date=date(2000, 1, 1)
    )
    db.add(user)
    await db.flush()
    start = datetime(2026, 9, 1, tzinfo=UTC)
    if status == "pending":
        db.add(
            CreatorPayoutApplication(
                user_id=user.id, status="pending", consented_at=start, privacy_version="2026-10-01"
            )
        )
        await db.flush()
    elif status is not None:
        revoked_at = start + timedelta(days=1) if status == "revoked" else None
        await _application(db, user.id, accrual_start_at=start, revoked_at=revoked_at)
    return user


async def _confirm(db: AsyncSession, user: User, amount_krw: int, *, month: int = 10) -> None:
    """그 달(2026년, KST) 월 확정 행 하나. 잔액은 이 행들의 합에서 지급을 뺀 값이다."""
    start = datetime(2026, month, 1, tzinfo=KST)
    db.add(
        CreatorPayoutConfirmation(
            user_id=user.id,
            kind="monthly",
            period_month=start.date(),
            window_start=start,
            window_end=start + timedelta(days=28),
            gross_units=0,
            refunded_units=0,
            rate_bps=500,
            exact_krw=Decimal(amount_krw),
            amount_krw=amount_krw,
        )
    )
    await db.flush()


def _info(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "legalName": "홍길동",
        "rrn": RRN,
        "bankCode": "088",
        "accountNumber": ACCOUNT,
        "agreed": True,
    }
    body.update(overrides)
    return body


async def _register(client: httpx.AsyncClient, **overrides: object) -> None:
    resp = await client.put("/me/creator-payout/payout-info", json=_info(**overrides))
    assert resp.status_code == 204, resp.text


async def _request(client: httpx.AsyncClient, *, for_withdrawal: bool = False) -> httpx.Response:
    return await client.post("/me/creator-payout/payouts", json={"forWithdrawal": for_withdrawal})


async def _ready(client: httpx.AsyncClient, db: AsyncSession, amount_krw: int) -> User:
    """지급 정보를 등록하고 잔액 `amount_krw` 를 가진 로그인한 회원."""
    user = await _member(db)
    await _confirm(db, user, amount_krw)
    await _login_as(client, user.id)
    await _register(client)
    return user


async def _payouts(db: AsyncSession, user: User) -> list[CreatorPayout]:
    rows = await db.scalars(
        select(CreatorPayout)
        .where(CreatorPayout.user_id == user.id)
        .order_by(CreatorPayout.requested_at, CreatorPayout.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _profiles(db: AsyncSession, user: User) -> list[CreatorPayoutProfile]:
    rows = await db.scalars(
        select(CreatorPayoutProfile)
        .where(CreatorPayoutProfile.user_id == user.id)
        .order_by(CreatorPayoutProfile.created_at, CreatorPayoutProfile.superseded_at.nulls_last())
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _balance(client: httpx.AsyncClient) -> int:
    resp = await client.get("/me/creator-payout")
    assert resp.status_code == 200, resp.text
    balance = resp.json()["balanceKrw"]
    assert isinstance(balance, int)
    return balance


async def _as_admin(client: httpx.AsyncClient, db: AsyncSession) -> uuid.UUID:
    admin = await _create_admin(db)
    await _login_as_admin(client, admin)
    admin_id = admin["id"]
    assert isinstance(admin_id, uuid.UUID)
    return admin_id


async def _audit(db: AsyncSession, action_type: str) -> list[AdminActionLog]:
    rows = await db.scalars(select(AdminActionLog).where(AdminActionLog.action_type == action_type))
    return list(rows)


def _keyring() -> FieldKeyring:
    return FieldKeyring.parse(CREATOR_PAYOUT_TEST_KEYS)


# ── 원천징수 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("amount", "income_tax", "local_tax", "net"),
    [
        pytest.param(12_345, 370, 30, 11_945, id="both-taxes-drop-under-10-won"),
        pytest.param(10_000, 300, 30, 9_670, id="minimum-payout"),
        pytest.param(10_304, 300, 30, 9_974, id="two-cuts-not-one-330bps-cut"),
        pytest.param(33_333, 990, 90, 32_253, id="income-tax-under-1000-still-withheld"),
        pytest.param(5_000, 150, 10, 4_840, id="below-minimum-before-withdrawal"),
        pytest.param(200_000, 6_000, 600, 193_400, id="exactly-3.3-percent"),
    ],
)
def test_withholding_is_business_income_with_each_tax_cut_to_10_won(
    amount: int, income_tax: int, local_tax: int, net: int
) -> None:
    tax = withholding(amount)
    assert (tax.income_tax_rate_bps, tax.income_tax_krw, tax.local_tax_krw, tax.net_amount_krw) == (
        300,
        income_tax,
        local_tax,
        net,
    )


# ── 암호화 ─────────────────────────────────────────────────────────────────
def _profile_for(user_id: uuid.UUID, keyring: FieldKeyring | None = None) -> CreatorPayoutProfile:
    info = PayoutInfo(legal_name="홍길동", rrn=RRN, bank_code="088", account_number=ACCOUNT)
    return new_profile(
        keyring or _keyring(),
        info,
        user_id=user_id,
        consented_at=datetime.now(UTC),
        privacy_version="2026-10-01",
    )


def test_ciphertext_moved_to_another_row_or_column_does_not_decrypt() -> None:
    """연관 데이터가 행과 칸을 묶는다 — 다른 사람 행이나 다른 칸에 붙은 암호문은 그 사람의 값처럼 읽히지 않고 실패한다."""
    keyring = _keyring()
    mine = _profile_for(uuid.uuid4())
    theirs = _profile_for(uuid.uuid4())
    assert decrypt_field(keyring, mine, "rrn") == RRN

    theirs.rrn_ciphertext = mine.rrn_ciphertext
    with pytest.raises(FieldDecryptError):
        decrypt_field(keyring, theirs, "rrn")
    mine.legal_name_ciphertext = mine.rrn_ciphertext
    with pytest.raises(FieldDecryptError):
        decrypt_field(keyring, mine, "legal_name")


def test_ciphertext_does_not_carry_the_plaintext() -> None:
    profile = _profile_for(uuid.uuid4())
    blobs = (profile.legal_name_ciphertext, profile.rrn_ciphertext, profile.account_number_ciphertext)
    for plaintext in ("홍길동".encode(), RRN.encode(), ACCOUNT.encode()):
        assert all(plaintext not in blob for blob in blobs)
    assert (profile.key_id, profile.account_last4) == ("k1", "6789")


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("k1:" + base64.urlsafe_b64encode(bytes(16)).decode(), id="short-key"),
        pytest.param("k1" + base64.urlsafe_b64encode(bytes(32)).decode(), id="no-kid-separator"),
        pytest.param("k 1:" + base64.urlsafe_b64encode(bytes(32)).decode(), id="space-in-kid"),
        pytest.param("k1:!!!!", id="not-base64"),
        pytest.param(f"{CREATOR_PAYOUT_TEST_KEYS},{CREATOR_PAYOUT_TEST_KEYS}", id="duplicated-kid"),
    ],
)
def test_malformed_encryption_keys_stop_startup_without_echoing_the_key(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("CREATOR_PAYOUT_ENCRYPTION_KEYS", raw)
    with pytest.raises(ValueError) as caught:
        config.Settings()
    assert raw.rsplit(":", 1)[-1] not in str(caught.value)


def test_empty_minimum_payout_reads_as_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_PAYOUT_MINIMUM_KRW", "")
    assert config.Settings().creator_payout_minimum_krw == 10_000


def test_mask_name_keeps_first_and_last_letters() -> None:
    assert [mask_name(name) for name in ("홍길동", "홍길", "남궁민수", "홍")] == ["홍*동", "홍*", "남**수", "*"]


@pytest.mark.parametrize(
    ("rrn", "expected"),
    [
        pytest.param("0001011123456", "rrn_mismatch", id="same-date-1900s-digit"),
        pytest.param("0001024123456", "rrn_mismatch", id="other-day"),
        pytest.param("0001010123456", "rrn_mismatch", id="1800s-digit"),
        pytest.param("0013324123456", "rrn_mismatch", id="impossible-date"),
        pytest.param("0001015123456", "foreigner", id="foreigner-5"),
        pytest.param("0001018123456", "foreigner", id="foreigner-8"),
    ],
)
def test_rrn_must_match_the_verified_birth_date(rrn: str, expected: str) -> None:
    assert (
        parse_payout_info(
            legal_name="홍길동", rrn=rrn, bank_code="088", account_number=ACCOUNT, birth_date=date(2000, 1, 1)
        )
        == expected
    )


def test_rrn_of_a_1900s_birth_matches() -> None:
    parsed = parse_payout_info(
        legal_name=" 홍길동 ", rrn="9005171123456", bank_code="004", account_number=ACCOUNT, birth_date=date(1990, 5, 17)
    )
    assert isinstance(parsed, PayoutInfo)
    assert (parsed.legal_name, parsed.bank_code) == ("홍길동", "004")
    assert RRN not in repr(parsed) and "9005171123456" not in repr(parsed)


# ── 지급 정보 입력 ─────────────────────────────────────────────────────────────
async def test_payout_info_gates_refuse_in_order(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """승인된 적 없음 → 형식 → 외국인등록번호 → 생년월일 대조 → 처리 중인 지급. 각 단계의 요청은 뒤 게이트에도 걸린다."""
    user = await _member(db_session, status="pending")
    await _login_as(db_client, user.id)

    async def put(**overrides: object) -> tuple[int, object]:
        resp = await db_client.put("/me/creator-payout/payout-info", json=_info(**overrides))
        return resp.status_code, resp.json()["detail"] if resp.status_code != 204 else None

    assert await put(rrn="0001015123456") == (403, {"code": "CREATOR_PAYOUT_NOT_APPROVED"})
    db_session.add(
        CreatorPayoutApplication(
            user_id=user.id,
            status="revoked",
            consented_at=datetime(2026, 9, 1, tzinfo=UTC),
            privacy_version="2026-10-01",
            decided_at=datetime(2026, 9, 1, tzinfo=UTC),
            accrual_start_at=datetime(2026, 9, 1, tzinfo=UTC),
            monthly_from_at=datetime(2026, 9, 1, tzinfo=UTC),
            revoked_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
    )
    await db_session.flush()
    invalid = {"code": "CREATOR_PAYOUT_INFO_INVALID"}
    for overrides in (
        {"legalName": "   ", "rrn": "0001015123456"},
        {"legalName": "가" * 41},
        {"rrn": "000101412345"},
        {"rrn": "000101-4123456"},
        {"bankCode": "999"},
        {"accountNumber": "12345"},
        {"accountNumber": "110-123-456789"},
    ):
        assert await put(**overrides) == (422, invalid), overrides
    assert await put(rrn="0001015123456", accountNumber="12345") == (422, invalid)
    assert await put(rrn="0001015123456") == (422, {"code": "CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED"})
    assert await put(rrn="0102034123456") == (422, {"code": "CREATOR_PAYOUT_RRN_MISMATCH"})
    assert await put() == (204, None)

    await _confirm(db_session, user, 10_000)
    assert (await _request(db_client)).status_code == 201
    assert await put(bankCode="004") == (409, {"code": "CREATOR_PAYOUT_IN_PROGRESS"})
    assert [profile.bank_code for profile in await _profiles(db_session, user)] == ["088"]


async def test_unverified_member_cannot_touch_payouts(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """지급 정보 입력·지급 신청도 정산 신청과 같은 회원 판정을 지난다 — 본인인증이 없으면 생년월일을 믿을 수 없다."""
    user = await _member(db_session)
    user.identity_ci_hmac, user.identity_verified_at = None, None
    await db_session.flush()
    await _login_as(db_client, user.id)

    put = await db_client.put("/me/creator-payout/payout-info", json=_info())
    post = await _request(db_client)

    for resp in (put, post):
        assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})


async def test_payout_info_is_stored_encrypted_with_its_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _member(db_session)
    await _login_as(db_client, user.id)

    await _register(db_client, legalName="  홍길동 ")

    [profile] = await _profiles(db_session, user)
    assert (profile.key_id, profile.bank_code, profile.account_last4, profile.superseded_at) == (
        "k1",
        "088",
        "6789",
        None,
    )
    assert profile.privacy_version == await _latest_published_legal_version(db_session, "privacy")
    assert profile.consented_at is not None
    for column, plaintext in PLAINTEXTS:
        blob = getattr(profile, f"{column}_ciphertext")
        assert plaintext.encode() not in blob
        assert decrypt_field(_keyring(), profile, column) == plaintext
    shown = (await db_client.get("/me/creator-payout")).json()["payoutInfo"]
    assert shown == {"maskedName": "홍*동", "bankCode": "088", "accountLast4": "6789"}


async def test_payout_info_requires_agreement(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _member(db_session)
    await _login_as(db_client, user.id)

    resp = await db_client.put("/me/creator-payout/payout-info", json=_info(agreed=False))

    assert resp.status_code == 422
    assert await _profiles(db_session, user) == []


async def test_reentering_payout_info_adds_a_version(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """새로 입력하면 새 판을 넣고 이전 판을 내린다. 이전 판은 그대로 남아 그 판으로 신청한 지급의 수취인이 바뀌지 않는다."""
    user = await _member(db_session)
    await _confirm(db_session, user, 10_000)
    await _login_as(db_client, user.id)
    await _register(db_client)
    assert (await _request(db_client)).status_code == 201
    await _as_admin(db_client, db_session)
    [payout] = await _payouts(db_session, user)
    transferred = await db_client.post(
        f"/admin/creator-payout/payouts/{payout.id}/transfer",
        json={"transferredOn": datetime.now(KST).date().isoformat(), "payeeProfileId": str(payout.profile_id)},
    )
    assert transferred.status_code == 204

    await _register(db_client, bankCode="004", accountNumber="9876543210")

    first, second = await _profiles(db_session, user)
    assert (first.bank_code, first.superseded_at is not None) == ("088", True)
    assert (second.bank_code, second.account_last4, second.superseded_at) == ("004", "3210", None)
    assert (await _payouts(db_session, user))[0].profile_id == first.id
    shown = (await db_client.get("/me/creator-payout")).json()["payoutInfo"]
    assert shown == {"maskedName": "홍*동", "bankCode": "004", "accountLast4": "3210"}


async def test_suspended_member_cannot_touch_payouts(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """정지는 Redis 표시 없이 DB 에만 있어 세션 확인을 지나고 회원 행 잠금이 막는다."""
    user = await _ready(db_client, db_session, 10_000)
    user.suspended_at = datetime.now(UTC)
    await db_session.flush()

    put = await db_client.put("/me/creator-payout/payout-info", json=_info())
    post = await _request(db_client)

    assert (put.status_code, put.json()["detail"]) == (403, "Account suspended")
    assert (post.status_code, post.json()["detail"]) == (403, "Account suspended")
    assert await _payouts(db_session, user) == []


async def test_payout_routes_are_closed_while_switched_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _member(db_session)
    await _login_as(db_client, user.id)
    monkeypatch.setattr(settings, "creator_payout_enabled", False)

    for resp in (
        await db_client.put("/me/creator-payout/payout-info", json=_info()),
        await _request(db_client),
        await db_client.get("/me/creator-payout/payouts"),
        await db_client.get("/me/creator-payout"),
    ):
        assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "CREATOR_PAYOUT_UNAVAILABLE"})


async def test_without_encryption_keys_only_payouts_close(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """키가 없으면 지급 정보 입력과 지급 신청만 닫힌다. 정산 조회·신청·내역·지급 내역, `/me` 진입점, 본인인증 시작, 월
    확정 배치는 키와 무관하게 돈다 — 이미 켠 정산이 키 하나 때문에 꺼지지 않는다."""
    user = await _member(db_session)
    await _confirm(db_session, user, 10_000)
    await _login_as(db_client, user.id)
    monkeypatch.setattr(settings, "creator_payout_encryption_keys", "")
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "identity_gate_enabled", False)

    for resp in (await db_client.put("/me/creator-payout/payout-info", json=_info()), await _request(db_client)):
        assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "CREATOR_PAYOUT_UNAVAILABLE"})
    overview = await db_client.get("/me/creator-payout")
    assert overview.status_code == 200
    assert (overview.json()["payoutAvailable"], overview.json()["balanceKrw"]) == (False, 10_000)
    assert (await db_client.get("/me/creator-payout/statements")).status_code == 200
    assert (await db_client.get("/me/creator-payout/payouts")).json() == {"items": []}
    applied = await db_client.post("/me/creator-payout/application", json={"agreed": True})
    # 스위치를 지나 회원 판정까지 간다(이 회원은 발행 작품이 없다).
    assert (applied.status_code, applied.json()["detail"]) == (422, {"code": "CREATOR_PAYOUT_NO_PUBLISHED_WORK"})
    assert "creator_payout" in (await db_client.get("/me")).json()["enabledFeatures"]
    identity = await db_client.post("/me/identity-verifications")
    assert identity.json()["detail"] == {"code": "IDENTITY_ALREADY_VERIFIED"}
    assert await run_monthly(async_sessionmaker(bind=db_session.bind, expire_on_commit=False), now=datetime.now(UTC)) != "off"


async def test_overview_says_payouts_are_available_with_keys(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _member(db_session)
    await _login_as(db_client, user.id)

    assert (await db_client.get("/me/creator-payout")).json()["payoutAvailable"] is True


# ── 지급 신청 ─────────────────────────────────────────────────────────────────
async def test_never_approved_member_cannot_request(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    for status in ("pending", None):
        user = await _member(db_session, status=status)
        await _confirm(db_session, user, 10_000)
        await _login_as(db_client, user.id)

        resp = await _request(db_client)

        assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "CREATOR_PAYOUT_NOT_APPROVED"})


async def test_revoked_member_can_register_and_request(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """승인이 취소돼도 이미 확정된 적립금은 받을 수 있다."""
    user = await _member(db_session, status="revoked")
    await _confirm(db_session, user, 10_000)
    await _login_as(db_client, user.id)

    put = await db_client.put("/me/creator-payout/payout-info", json=_info())
    post = await _request(db_client)

    assert (put.status_code, post.status_code) == (204, 201)


async def test_request_gates_refuse_in_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession, notifications: list[str]
) -> None:
    """지급 정보 없음 → 잔액 0 이하 → 최소액 미만 → 성공 → 처리 중 중복."""
    user = await _member(db_session)
    await _login_as(db_client, user.id)

    async def post() -> tuple[int, object]:
        resp = await _request(db_client)
        return resp.status_code, resp.json()["detail"] if resp.status_code != 201 else resp.json()

    assert await post() == (409, {"code": "CREATOR_PAYOUT_INFO_REQUIRED"})
    await _register(db_client)
    assert await post() == (422, {"code": "CREATOR_PAYOUT_NOTHING_TO_PAY"})
    await _confirm(db_session, user, -5, month=9)
    assert await post() == (422, {"code": "CREATOR_PAYOUT_NOTHING_TO_PAY"})
    await _confirm(db_session, user, 10_004, month=10)
    assert await post() == (
        422,
        {"code": "CREATOR_PAYOUT_BELOW_MINIMUM", "minimumKrw": 10_000, "balanceKrw": 9_999},
    )
    await _confirm(db_session, user, 1, month=11)
    assert await post() == (
        201,
        {"amountKrw": 10_000, "incomeTaxKrw": 300, "localTaxKrw": 30, "netAmountKrw": 9_670},
    )
    assert await post() == (409, {"code": "CREATOR_PAYOUT_IN_PROGRESS"})

    [payout] = await _payouts(db_session, user)
    assert (payout.status, payout.amount_krw, payout.for_withdrawal) == ("requested", 10_000, False)
    assert notifications == [payout_requested_message(10_000)] == ["크리에이터 지급 신청 10,000원 접수"]
    assert str(user.id) not in notifications[0]


async def test_request_takes_the_whole_balance_and_snapshots_withholding(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """금액은 고르지 않는다 — 요청에 금액을 실어도 잔액 전액이다. 세율·세액은 신청 때 값으로 남는다."""
    user = await _ready(db_client, db_session, 12_345)

    resp = await db_client.post("/me/creator-payout/payouts", json={"forWithdrawal": False, "amountKrw": 100})

    assert resp.json() == {"amountKrw": 12_345, "incomeTaxKrw": 370, "localTaxKrw": 30, "netAmountKrw": 11_945}
    [payout] = await _payouts(db_session, user)
    assert (
        payout.amount_krw,
        payout.income_tax_rate_bps,
        payout.income_tax_krw,
        payout.local_tax_krw,
        payout.net_amount_krw,
    ) == (12_345, 300, 370, 30, 11_945)
    assert await _balance(db_client) == 0
    progress = (await db_client.get("/me/creator-payout")).json()["inProgressPayout"]
    assert progress["amountKrw"] == 12_345


@pytest.mark.parametrize(
    ("balance", "for_withdrawal", "status", "stored_for_withdrawal"),
    [
        pytest.param(9_999, True, 201, True, id="below-minimum-before-withdrawal"),
        pytest.param(10_000, True, 201, False, id="at-minimum-is-ordinary"),
        pytest.param(9_999, False, 422, None, id="below-minimum-without-withdrawal"),
    ],
)
async def test_withdrawal_exception_only_below_the_minimum(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    balance: int,
    for_withdrawal: bool,
    status: int,
    stored_for_withdrawal: bool | None,
) -> None:
    user = await _ready(db_client, db_session, balance)

    resp = await _request(db_client, for_withdrawal=for_withdrawal)

    assert resp.status_code == status
    assert [payout.for_withdrawal for payout in await _payouts(db_session, user)] == (
        [] if stored_for_withdrawal is None else [stored_for_withdrawal]
    )


async def test_withdrawal_payout_of_5000_withholds_150_and_10(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _ready(db_client, db_session, 5_000)

    resp = await _request(db_client, for_withdrawal=True)

    assert resp.json() == {"amountKrw": 5_000, "incomeTaxKrw": 150, "localTaxKrw": 10, "netAmountKrw": 4_840}


async def test_return_restores_the_balance_and_transfer_keeps_it_spent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """잔액 = 확정 합 − 처리 중·지급 금액. 반려는 금액을 돌려놓고, 이체는 신청 때 뺀 그대로 둔다."""
    user = await _ready(db_client, db_session, 20_000)
    assert (await _request(db_client)).status_code == 201
    assert await _balance(db_client) == 0
    await _as_admin(db_client, db_session)
    [first] = await _payouts(db_session, user)

    returned = await db_client.post(
        f"/admin/creator-payout/payouts/{first.id}/return", json={"reasonText": "계좌 명의가 다릅니다"}
    )

    assert returned.status_code == 204
    assert await _balance(db_client) == 20_000
    assert (await _request(db_client)).status_code == 201
    [second] = [payout for payout in await _payouts(db_session, user) if payout.status == "requested"]
    transferred = await db_client.post(
        f"/admin/creator-payout/payouts/{second.id}/transfer",
        json={
            "transferredOn": datetime.now(KST).date().isoformat(),
            "payeeProfileId": str(second.profile_id),
            "adminMemo": "국민 이체",
        },
    )
    assert transferred.status_code == 204
    assert await _balance(db_client) == 0
    await _confirm(db_session, user, 3, month=11)
    assert await _balance(db_client) == 3

    listed = (await db_client.get("/me/creator-payout/payouts")).json()["items"]
    assert sorted((item["status"], item["returnReason"], item["transferredOn"]) for item in listed) == [
        ("paid", "", datetime.now(KST).date().isoformat()),
        ("returned", "계좌 명의가 다릅니다", None),
    ]
    assert "adminMemo" not in listed[0]


# ── 어드민 ─────────────────────────────────────────────────────────────────
async def test_admin_detail_masks_the_payee_and_previews_withholding(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상세는 실명 첫·끝 글자와 계좌 끝 4자리만 싣는다. 신청 때 남긴 세액과 지금 세율로 다시 계산한 값을 함께 보인다."""
    user = await _ready(db_client, db_session, 12_345)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    # 신청 뒤 세율이 바뀐 건을 흉내 낸다 — 남긴 값과 지금 계산이 갈린다.
    await db_session.execute(
        update(CreatorPayout)
        .where(CreatorPayout.id == payout.id)
        .values(income_tax_rate_bps=200, income_tax_krw=240, local_tax_krw=20, net_amount_krw=12_085)
    )
    await _as_admin(db_client, db_session)

    resp = await db_client.get(f"/admin/creator-payout/payouts/{payout.id}")

    body = resp.json()
    assert resp.status_code == 200
    assert (body["maskedName"], body["bankCode"], body["accountLast4"], body["withdrawn"]) == (
        "홍*동",
        "088",
        "6789",
        False,
    )
    assert (body["payeeInfoReadable"], body["payeeProfileId"]) == (True, str(payout.profile_id))
    assert body["withholding"] == {
        "incomeTaxRateBps": 200,
        "incomeTaxKrw": 240,
        "localTaxKrw": 20,
        "netAmountKrw": 12_085,
    }
    assert body["currentWithholding"] == {
        "incomeTaxRateBps": 300,
        "incomeTaxKrw": 370,
        "localTaxKrw": 30,
        "netAmountKrw": 11_945,
    }
    assert RRN not in resp.text and ACCOUNT not in resp.text and "홍길동" not in resp.text


async def test_admin_payout_queue_lists_requested_first_by_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    await _as_admin(db_client, db_session)

    requested = (await db_client.get("/admin/creator-payout/payouts")).json()
    paid = (await db_client.get("/admin/creator-payout/payouts", params={"status": "paid"})).json()

    [item] = requested["items"]
    assert (item["userId"], item["nickname"], item["withdrawn"], item["amountKrw"], item["netAmountKrw"]) == (
        str(user.id),
        user.nickname,
        False,
        10_000,
        9_670,
    )
    assert (requested["totalCount"], paid["items"]) == (1, [])


async def test_payee_info_view_needs_a_reason_and_logs_every_view(
    db_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """원문은 응답에만 있다 — 열람마다 감사 1행, 사유가 비면 열람도 기록도 없다. 이 흐름의 어떤 로그에도 원문이 없다."""
    caplog.set_level(logging.DEBUG)
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    admin_id = await _as_admin(db_client, db_session)
    url = f"/admin/creator-payout/payouts/{payout.id}/payee-info-view"

    blank = await db_client.post(url, json={"reasonCategory": "other", "reasonText": "  "})
    chat_only = await db_client.post(url, json={"reasonCategory": "report-investigation", "reasonText": "신고 조사"})
    first = await db_client.post(url, json={"reasonCategory": "payout-statement", "reasonText": "지급명세서 작성"})
    second = await db_client.post(url, json={"reasonCategory": "payout-processing", "reasonText": "이체 계좌 확인"})

    assert blank.status_code == 422
    # 채팅 열람에만 있는 사유 분류는 받지 않는다.
    assert chat_only.status_code == 422
    assert first.json() == {
        "payeeProfileId": str(payout.profile_id),
        "legalName": "홍길동",
        "rrn": RRN,
        "bankCode": "088",
        "accountNumber": ACCOUNT,
    }
    assert second.status_code == 200
    views = await _audit(db_session, "user-creator-payout-info-view")
    assert sorted((log.reason_category, log.reason_text) for log in views) == [
        ("payout-processing", "이체 계좌 확인"),
        ("payout-statement", "지급명세서 작성"),
    ]
    assert {(log.admin_id, log.target_user_id) for log in views} == {(admin_id, user.id)}
    for secret in (RRN, ACCOUNT, "홍길동"):
        assert secret not in caplog.text


async def test_transfer_validates_the_date_and_state(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    admin_id = await _as_admin(db_client, db_session)
    url = f"/admin/creator-payout/payouts/{payout.id}/transfer"
    today = datetime.now(KST).date()
    requested_on = payout.requested_at.astimezone(KST).date()

    payee = {"payeeProfileId": str(payout.profile_id)}

    before = await db_client.post(
        url, json={"transferredOn": (requested_on - timedelta(days=1)).isoformat(), **payee}
    )
    future = await db_client.post(url, json={"transferredOn": (today + timedelta(days=1)).isoformat(), **payee})
    done = await db_client.post(url, json={"transferredOn": today.isoformat(), "adminMemo": "국민 이체", **payee})
    again = await db_client.post(url, json={"transferredOn": today.isoformat(), **payee})
    returned = await db_client.post(
        f"/admin/creator-payout/payouts/{payout.id}/return", json={"reasonText": "중복"}
    )

    invalid_date = (422, {"code": "CREATOR_PAYOUT_TRANSFER_DATE_INVALID"})
    assert (before.status_code, before.json()["detail"]) == invalid_date
    assert (future.status_code, future.json()["detail"]) == invalid_date
    assert done.status_code == 204
    not_requested = (409, {"code": "CREATOR_PAYOUT_NOT_REQUESTED"})
    assert (again.status_code, again.json()["detail"]) == not_requested
    assert (returned.status_code, returned.json()["detail"]) == not_requested
    [stored] = await _payouts(db_session, user)
    assert (stored.status, stored.transferred_on, stored.admin_memo, stored.decided_by_admin_id) == (
        "paid",
        today,
        "국민 이체",
        admin_id,
    )
    assert stored.paid_at is not None
    [log] = await _audit(db_session, "user-creator-payout-transfer")
    assert (log.target_user_id, log.reason_text) == (user.id, "국민 이체")


async def test_return_needs_a_reason_and_logs_it(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    await _as_admin(db_client, db_session)
    url = f"/admin/creator-payout/payouts/{payout.id}/return"

    blank = await db_client.post(url, json={"reasonText": " "})
    done = await db_client.post(url, json={"reasonText": "이체 실패"})

    assert (blank.status_code, done.status_code) == (422, 204)
    [stored] = await _payouts(db_session, user)
    assert (stored.status, stored.return_reason, stored.returned_at is not None) == ("returned", "이체 실패", True)
    [log] = await _audit(db_session, "user-creator-payout-return")
    assert (log.target_user_id, log.reason_text) == (user.id, "이체 실패")


async def test_missing_payout_is_404(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _as_admin(db_client, db_session)
    missing = uuid.uuid4()

    for resp in (
        await db_client.get(f"/admin/creator-payout/payouts/{missing}"),
        await db_client.post(f"/admin/creator-payout/payouts/{missing}/return", json={"reasonText": "x"}),
    ):
        assert (resp.status_code, resp.json()["detail"]) == (404, {"code": "CREATOR_PAYOUT_NOT_FOUND"})


# ── 키 분실·회전 ─────────────────────────────────────────────────────────────
async def _profile_under_other_key(db: AsyncSession, user: User) -> CreatorPayoutProfile:
    """설정에 없는 키로 만든 판 — 키를 잃은 경우와 같다."""
    profile = _profile_for(user.id, FieldKeyring.parse(OTHER_KEYS))
    db.add(profile)
    await db.flush()
    return profile


async def test_lost_key_keeps_both_views_open_without_the_name_and_refuses_the_plaintext(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작가 화면과 어드민 상세는 200 으로 열리고 실명만 비며(은행·끝 4자리는 평문), 원문 열람은 409 이고 열람 기록도 없다.
    상세가 열리므로 운영자가 그 건을 반려해 작가가 지급 정보를 다시 입력하게 할 수 있다."""
    user = await _member(db_session)
    profile = await _profile_under_other_key(db_session, user)
    db_session.add(
        CreatorPayout(
            user_id=user.id,
            profile_id=profile.id,
            status="requested",
            amount_krw=10_000,
            for_withdrawal=False,
            income_tax_rate_bps=300,
            income_tax_krw=300,
            local_tax_krw=30,
            net_amount_krw=9_670,
        )
    )
    await db_session.flush()
    [payout] = await _payouts(db_session, user)
    await _login_as(db_client, user.id)

    owner = await db_client.get("/me/creator-payout")
    await _as_admin(db_client, db_session)
    detail = await db_client.get(f"/admin/creator-payout/payouts/{payout.id}")
    view = await db_client.post(
        f"/admin/creator-payout/payouts/{payout.id}/payee-info-view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )

    assert owner.status_code == 200
    assert owner.json()["payoutInfo"] == {"maskedName": None, "bankCode": "088", "accountLast4": "6789"}
    assert detail.status_code == 200
    body = detail.json()
    assert (body["payeeInfoReadable"], body["maskedName"], body["bankCode"], body["accountLast4"]) == (
        False,
        None,
        "088",
        "6789",
    )
    assert (body["status"], body["amountKrw"], body["payeeProfileId"]) == ("requested", 10_000, str(profile.id))
    assert (view.status_code, view.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_INFO_UNREADABLE"})
    assert await _audit(db_session, "user-creator-payout-info-view") == []

    returned = await db_client.post(
        f"/admin/creator-payout/payouts/{payout.id}/return", json={"reasonText": "지급 정보를 다시 입력해 주세요"}
    )

    assert returned.status_code == 204
    [stored] = await _payouts(db_session, user)
    assert stored.status == "returned"


async def _corrupt(db: AsyncSession, profile: CreatorPayoutProfile, column: EncryptedColumn) -> None:
    """그 칸 암호문의 마지막 바이트를 뒤집는다 — 키는 있는데 한 칸만 복호화에 실패하는 경우."""
    attribute = f"{column}_ciphertext"
    blob: bytes = getattr(profile, attribute)
    setattr(profile, attribute, blob[:-1] + bytes([blob[-1] ^ 1]))
    await db.flush()


@pytest.mark.parametrize("column", [column for column, _ in PLAINTEXTS])
async def test_any_unreadable_payee_field_marks_the_detail_unreadable_and_refuses_the_transfer(
    db_client: httpx.AsyncClient, db_session: AsyncSession, column: EncryptedColumn
) -> None:
    """실명만 멀쩡하고 주민등록번호나 계좌번호가 깨져도 상세는 읽을 수 없다고 답하고 실명 마스킹도 싣지 않는다 — 원문
    열람과 이체 기록이 세 칸을 모두 읽어야 하므로, 실명만 보고 "읽힘"이라 하면 화면이 막힐 일을 보여 준다. 이체 기록은
    409 이고 상태·감사 기록이 그대로다. 응답 어디에도 원문이 없다."""
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    [profile] = await _profiles(db_session, user)
    await _corrupt(db_session, profile, column)
    await _as_admin(db_client, db_session)
    base = f"/admin/creator-payout/payouts/{payout.id}"
    today = datetime.now(KST).date().isoformat()

    detail = await db_client.get(base)
    transfer = await db_client.post(
        f"{base}/transfer", json={"transferredOn": today, "payeeProfileId": str(profile.id)}
    )

    assert detail.status_code == 200
    body = detail.json()
    assert (body["payeeInfoReadable"], body["maskedName"], body["accountLast4"]) == (False, None, "6789")
    for _, secret in PLAINTEXTS:
        assert secret not in detail.text
    assert "홍*동" not in detail.text
    assert (transfer.status_code, transfer.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_INFO_UNREADABLE"})
    [stored] = await _payouts(db_session, user)
    assert (stored.status, stored.paid_at) == ("requested", None)
    assert await _audit(db_session, "user-creator-payout-transfer") == []


@pytest.mark.parametrize("column", ["rrn", "account_number"])
async def test_member_with_an_unreadable_rrn_or_account_is_asked_to_reenter_and_cannot_request(
    db_client: httpx.AsyncClient, db_session: AsyncSession, column: EncryptedColumn
) -> None:
    """실명은 읽히는데 주민등록번호나 계좌번호만 깨져도 작가 화면은 실명 마스킹을 비워 다시 입력하라고 알리고, 지급
    신청은 409 로 받지 않는다 — 운영자가 그 판으로는 이체할 수 없어서다. 응답 어디에도 원문이 없고 지급 행이 생기지
    않는다."""
    user = await _ready(db_client, db_session, 10_000)
    [profile] = await _profiles(db_session, user)
    await _corrupt(db_session, profile, column)

    owner = await db_client.get("/me/creator-payout")
    requested = await _request(db_client)

    assert owner.status_code == 200
    assert owner.json()["payoutInfo"] == {"maskedName": None, "bankCode": "088", "accountLast4": "6789"}
    for response in (owner, requested):
        for _, secret in PLAINTEXTS:
            assert secret not in response.text
        assert "홍*동" not in response.text
    assert (requested.status_code, requested.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_INFO_UNREADABLE"})
    assert await _payouts(db_session, user) == []


async def test_transfer_refusals_on_an_unreadable_payee_come_in_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판이 바뀌었다는 409 가 읽을 수 없다는 409 보다 먼저다(운영자는 새 판부터 다시 봐야 한다). 읽을 수 없다는 409 는
    이체일 422 보다 먼저다(날짜를 고쳐도 기록할 수 없다)."""
    user = await _member(db_session)
    profile = await _profile_under_other_key(db_session, user)
    db_session.add(_payout_row(user.id, profile.id))
    await db_session.flush()
    [payout] = await _payouts(db_session, user)
    await _as_admin(db_client, db_session)
    url = f"/admin/creator-payout/payouts/{payout.id}/transfer"
    today = datetime.now(KST).date()

    changed = await db_client.post(
        url, json={"transferredOn": today.isoformat(), "payeeProfileId": str(uuid.uuid4())}
    )
    future = await db_client.post(
        url, json={"transferredOn": (today + timedelta(days=1)).isoformat(), "payeeProfileId": str(profile.id)}
    )

    assert (changed.status_code, changed.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_PAYEE_CHANGED"})
    assert (future.status_code, future.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_INFO_UNREADABLE"})
    [stored] = await _payouts(db_session, user)
    assert stored.status == "requested"


async def test_admin_without_any_key_reads_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """어드민은 정산 스위치와 무관하게 열려 있어 키가 빈 채로도 들어온다 — 그때 지급 정보는 읽을 수 없는 것과 같다."""
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    await _as_admin(db_client, db_session)
    monkeypatch.setattr(settings, "creator_payout_encryption_keys", "")

    detail = await db_client.get(f"/admin/creator-payout/payouts/{payout.id}")

    assert detail.status_code == 200
    assert (detail.json()["payeeInfoReadable"], detail.json()["maskedName"]) == (False, None)


async def test_key_rotation_reads_old_rows_and_reencrypts_them(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """새 키를 맨 앞에 붙이면 옛 행도 읽힌다. 재암호화 뒤에는 옛 키를 빼도 읽힌다. 목록에 없는 키의 행은 건너뛰고 센다."""
    user = await _member(db_session)
    await _login_as(db_client, user.id)
    await _register(db_client)
    stranger = await _member(db_session)
    await _profile_under_other_key(db_session, stranger)
    new_key = "k2:" + base64.urlsafe_b64encode(bytes(range(50, 82))).decode()
    monkeypatch.setattr(settings, "creator_payout_encryption_keys", f"{new_key},{CREATOR_PAYOUT_TEST_KEYS}")
    assert (await db_client.get("/me/creator-payout")).json()["payoutInfo"]["maskedName"] == "홍*동"

    result = await reencrypt_profiles(async_sessionmaker(bind=db_session.bind, expire_on_commit=False))

    assert (result.reencrypted, result.unreadable) == (1, 1)
    [profile] = await _profiles(db_session, user)
    assert profile.key_id == "k2"
    monkeypatch.setattr(settings, "creator_payout_encryption_keys", new_key)
    for column, plaintext in PLAINTEXTS:
        assert decrypt_field(FieldKeyring.parse(new_key), profile, column) == plaintext
    assert (await db_client.get("/me/creator-payout")).json()["payoutInfo"]["maskedName"] == "홍*동"


# ── 탈퇴 ─────────────────────────────────────────────────────────────────
async def _keep(storage_key: str) -> None:
    return None


async def test_erase_account_keeps_payout_records_and_deletes_unused_payout_info(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """지급·확정 행은 그대로 남고, 지급 정보는 지급이 가리키는 판만 남는다. 탈퇴 전 신청한 지급은 끝까지 처리된다."""
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    await _as_admin(db_client, db_session)
    [paid] = await _payouts(db_session, user)
    today = datetime.now(KST).date().isoformat()
    assert (
        await db_client.post(
            f"/admin/creator-payout/payouts/{paid.id}/transfer",
            json={"transferredOn": today, "payeeProfileId": str(paid.profile_id)},
        )
    ).status_code == 204
    await _register(db_client, bankCode="004")
    await _register(db_client, bankCode="020")
    await _confirm(db_session, user, 10_000, month=11)
    assert (await _request(db_client)).status_code == 201
    used_ids = {payout.profile_id for payout in await _payouts(db_session, user)}
    assert len(await _profiles(db_session, user)) == 3 and len(used_ids) == 2

    tables = (CreatorPayout.__table__, CreatorPayoutConfirmation.__table__)

    async def snapshot() -> list[list[dict[str, object]]]:
        return [
            [dict(row) for row in (await db_session.execute(select(t).where(t.c.user_id == user.id).order_by(t.c.id))).mappings()]
            for t in tables
        ]

    before = await snapshot()
    locked = await db_session.get(User, user.id, with_for_update=True)
    assert locked is not None

    await erase_account(db_session, locked, delete_storage_object=_keep)

    assert await snapshot() == before
    assert {profile.id for profile in await _profiles(db_session, user)} == used_ids
    in_progress = next(payout for payout in await _payouts(db_session, user) if payout.status == "requested")
    listed = (await db_client.get("/admin/creator-payout/payouts")).json()["items"]
    assert [(item["id"], item["nickname"], item["withdrawn"]) for item in listed] == [
        (str(in_progress.id), None, True)
    ]
    assert (await db_client.get(f"/admin/creator-payout/payouts/{in_progress.id}")).status_code == 200
    assert (
        await db_client.post(
            f"/admin/creator-payout/payouts/{in_progress.id}/transfer",
            json={"transferredOn": today, "payeeProfileId": str(in_progress.profile_id)},
        )
    ).status_code == 204


async def test_erase_account_without_payouts_deletes_all_payout_info(db_session: AsyncSession) -> None:
    user = await _member(db_session)
    db_session.add(_profile_for(user.id))
    await db_session.flush()

    await erase_account(db_session, user, delete_storage_object=_keep)

    assert await _profiles(db_session, user) == []


# ── 제약(alembic check 가 비교하지 않는 CHECK·부분 유니크) ─────────────────────────────────────
def _payout_row(user_id: uuid.UUID, profile_id: uuid.UUID, **overrides: object) -> CreatorPayout:
    values: dict[str, object] = {
        "user_id": user_id,
        "profile_id": profile_id,
        "status": "requested",
        "amount_krw": 10_000,
        "for_withdrawal": False,
        "income_tax_rate_bps": 300,
        "income_tax_krw": 300,
        "local_tax_krw": 30,
        "net_amount_krw": 9_670,
    }
    values.update(overrides)
    return CreatorPayout(**values)


async def _insert_fails(db: AsyncSession, row: object) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(row)
            await db.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"status": "cancelled"}, id="status-out-of-list"),
        pytest.param({"income_tax_rate_bps": 0}, id="zero-tax-rate"),
        pytest.param({"amount_krw": 0, "income_tax_krw": 0, "local_tax_krw": 0, "net_amount_krw": 0}, id="zero-amount"),
        pytest.param({"net_amount_krw": 9_671}, id="net-not-amount-minus-taxes"),
        pytest.param({"income_tax_krw": -10, "net_amount_krw": 9_980}, id="negative-tax"),
        pytest.param({"status": "paid", "paid_at": datetime(2026, 10, 9, tzinfo=UTC)}, id="paid-without-transfer-date"),
        pytest.param({"transferred_on": date(2026, 10, 9), "paid_at": datetime(2026, 10, 9, tzinfo=UTC)}, id="requested-with-paid"),
        pytest.param({"status": "returned"}, id="returned-without-time"),
        pytest.param({"status": "held"}, id="held-without-time"),
        pytest.param(
            {"status": "returned", "returned_at": datetime(2026, 10, 9, tzinfo=UTC), "held_at": datetime(2026, 10, 9, tzinfo=UTC)},
            id="held-then-returned",
        ),
    ],
)
async def test_payout_check_constraints(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    user = await _member(db_session)
    profile = _profile_for(user.id)
    db_session.add(profile)
    await db_session.flush()

    await _insert_fails(db_session, _payout_row(user.id, profile.id, **overrides))


async def test_one_in_progress_payout_per_member(db_session: AsyncSession) -> None:
    """처리 중·보류는 아직 이체하지 않은 지급이라 합쳐서 한 사람에 하나다."""
    user = await _member(db_session)
    profile = _profile_for(user.id)
    db_session.add(profile)
    await db_session.flush()
    db_session.add(
        _payout_row(
            user.id, profile.id, status="paid", paid_at=datetime(2026, 10, 9, tzinfo=UTC), transferred_on=date(2026, 10, 9)
        )
    )
    db_session.add(_payout_row(user.id, profile.id))
    await db_session.flush()

    await _insert_fails(db_session, _payout_row(user.id, profile.id))
    await _insert_fails(db_session, _payout_row(user.id, profile.id, status="held", held_at=datetime(2026, 10, 9, tzinfo=UTC)))
    assert await db_session.scalar(select(func.count()).where(CreatorPayout.user_id == user.id)) == 2


async def test_one_current_payout_info_per_member(db_session: AsyncSession) -> None:
    user = await _member(db_session)
    old = _profile_for(user.id)
    old.superseded_at = datetime(2026, 10, 1, tzinfo=UTC)
    db_session.add_all([old, _profile_for(user.id)])
    await db_session.flush()

    await _insert_fails(db_session, _profile_for(user.id))
    short = _profile_for(user.id)
    short.superseded_at, short.account_last4 = datetime(2026, 10, 2, tzinfo=UTC), "123"
    await _insert_fails(db_session, short)
    no_key = _profile_for(user.id)
    no_key.superseded_at, no_key.key_id = datetime(2026, 10, 3, tzinfo=UTC), ""
    await _insert_fails(db_session, no_key)


async def test_payout_info_is_either_consented_or_entered_by_an_admin(db_session: AsyncSession) -> None:
    """판은 회원이 동의하고 넣었거나(동의 시각·처리방침 버전) 운영자가 넣었거나(넣은 운영자) 둘 중 하나다."""
    user = await _member(db_session)
    admin_id = (await _create_admin(db_session))["id"]
    assert isinstance(admin_id, uuid.UUID)
    superseded = datetime(2026, 10, 1, tzinfo=UTC)

    def variant(**values: object) -> CreatorPayoutProfile:
        profile = _profile_for(user.id)
        profile.superseded_at = superseded
        for name, value in values.items():
            setattr(profile, name, value)
        return profile

    await _insert_fails(db_session, variant(entered_by_admin_id=admin_id))
    await _insert_fails(db_session, variant(consented_at=None, privacy_version=None))
    await _insert_fails(db_session, variant(privacy_version=None))
    await _insert_fails(db_session, variant(consented_at=None, entered_by_admin_id=admin_id))
    db_session.add(variant(consented_at=None, privacy_version=None, entered_by_admin_id=admin_id))
    await db_session.flush()


def _load_payouts_migration() -> ModuleType:
    (path,) = (Path(__file__).resolve().parents[1] / "migrations" / "versions").glob("46bda819407c_*.py")
    spec = importlib.util.spec_from_file_location("_migration_46bda819407c", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PAYOUTS_MIGRATION = _load_payouts_migration()


async def test_downgrade_refuses_while_payout_info_exists(db_session: AsyncSession) -> None:
    """지급 정보·지급 행이 있으면 아무것도 바꾸기 전에 멈춘다 — 원천징수·지급명세서 근거를 스키마 되돌리기로 지우지 않는다."""
    user = await _member(db_session)
    db_session.add(_profile_for(user.id))
    await db_session.flush()

    def downgrade(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            _PAYOUTS_MIGRATION.downgrade()

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="creator_payout_profiles 에 1행"):
        await connection.run_sync(downgrade)
    assert len(await _profiles(db_session, user)) == 1


# ── 탈퇴한 회원의 지급: 반려 대신 보류, 수취 정보 교체 ─────────────────────────────
NEW_ACCOUNT = "3333012345678"


async def _withdrawn_with_request(client: httpx.AsyncClient, db: AsyncSession) -> tuple[User, CreatorPayout]:
    """잔액 10,000원을 신청한 뒤 탈퇴한 회원과 그 처리 중인 지급."""
    user = await _ready(client, db, 10_000)
    assert (await _request(client)).status_code == 201
    locked = await db.get(User, user.id, with_for_update=True)
    assert locked is not None
    await erase_account(db, locked, delete_storage_object=_keep)
    [payout] = await _payouts(db, user)
    return user, payout


def _payee(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "legalName": "홍길동",
        "rrn": RRN,
        "bankCode": "090",
        "accountNumber": NEW_ACCOUNT,
        "reasonText": "문의로 받은 계좌",
    }
    body.update(overrides)
    return body


async def test_withdrawn_payee_payout_is_held_not_returned_and_stays_reserved(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴한 회원은 다시 신청할 수 없어 반려하면 금액이 갈 곳을 잃는다 — 반려는 409, 보류는 잔액을 돌려주지 않고 이체로
    끝난다."""
    user, payout = await _withdrawn_with_request(db_client, db_session)
    admin_id = await _as_admin(db_client, db_session)
    base = f"/admin/creator-payout/payouts/{payout.id}"

    returned = await db_client.post(f"{base}/return", json={"reasonText": "계좌 명의가 다릅니다"})
    blank = await db_client.post(f"{base}/hold", json={"reasonText": " "})
    held = await db_client.post(f"{base}/hold", json={"reasonText": "계좌 해지됨"})
    held_again = await db_client.post(f"{base}/hold", json={"reasonText": "다시"})
    returned_after_hold = await db_client.post(f"{base}/return", json={"reasonText": "반려"})

    assert (returned.status_code, returned.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_PAYEE_WITHDRAWN"})
    assert (blank.status_code, held.status_code) == (422, 204)
    not_requested = (409, {"code": "CREATOR_PAYOUT_NOT_REQUESTED"})
    assert (held_again.status_code, held_again.json()["detail"]) == not_requested
    assert (returned_after_hold.status_code, returned_after_hold.json()["detail"]) == not_requested
    [stored] = await _payouts(db_session, user)
    assert (stored.status, stored.hold_reason, stored.decided_by_admin_id) == ("held", "계좌 해지됨", admin_id)
    assert stored.held_at is not None and stored.returned_at is None
    assert await balance_krw(db_session, user.id) == 0
    [log] = await _audit(db_session, "user-creator-payout-hold")
    assert (log.target_user_id, log.reason_text) == (user.id, "계좌 해지됨")
    assert await _audit(db_session, "user-creator-payout-return") == []
    listed = (await db_client.get("/admin/creator-payout/payouts", params={"status": "held"})).json()["items"]
    assert [(item["id"], item["status"], item["withdrawn"]) for item in listed] == [(str(payout.id), "held", True)]
    detail = (await db_client.get(base)).json()
    assert (detail["status"], detail["holdReason"], detail["heldAt"] is not None) == ("held", "계좌 해지됨", True)

    today = datetime.now(KST).date().isoformat()
    transferred = await db_client.post(
        f"{base}/transfer", json={"transferredOn": today, "payeeProfileId": str(payout.profile_id)}
    )

    assert transferred.status_code == 204
    [paid] = await _payouts(db_session, user)
    assert (paid.status, paid.held_at is not None) == ("paid", True)
    assert await balance_krw(db_session, user.id) == 0


async def test_live_member_payout_cannot_be_held_or_have_its_payee_replaced(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """살아 있는 회원의 건은 반려하면 회원이 다시 입력·신청한다 — 보류·운영자 교체는 탈퇴한 회원 건에만 있다."""
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    await _as_admin(db_client, db_session)
    base = f"/admin/creator-payout/payouts/{payout.id}"

    held = await db_client.post(f"{base}/hold", json={"reasonText": "보류"})
    replaced = await db_client.put(f"{base}/payee-info", json=_payee())

    not_withdrawn = {"code": "CREATOR_PAYOUT_PAYEE_NOT_WITHDRAWN"}
    assert (held.status_code, held.json()["detail"]) == (409, not_withdrawn)
    assert (replaced.status_code, replaced.json()["detail"]) == (409, not_withdrawn)
    [stored] = await _payouts(db_session, user)
    assert (stored.status, stored.held_at) == ("requested", None)
    assert len(await _profiles(db_session, user)) == 1


async def test_replacing_the_payee_points_the_payout_at_an_admin_entered_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """새 판을 넣고 지급이 그것을 가리킨다(지급명세서가 실제 수취인을 읽는다). 어느 지급도 가리키지 않게 된 앞 판은 탈퇴
    규칙대로 지운다. 감사 로그에는 사유만, 로그에는 값이 없다."""
    caplog.set_level(logging.DEBUG)
    user, payout = await _withdrawn_with_request(db_client, db_session)
    old_profile_id = payout.profile_id
    admin_id = await _as_admin(db_client, db_session)
    base = f"/admin/creator-payout/payouts/{payout.id}"
    assert (await db_client.post(f"{base}/hold", json={"reasonText": "계좌 해지됨"})).status_code == 204

    blank = await db_client.put(f"{base}/payee-info", json=_payee(reasonText=" "))
    done = await db_client.put(f"{base}/payee-info", json=_payee(legalName="홍길순"))

    assert (blank.status_code, done.status_code) == (422, 204)
    [stored] = await _payouts(db_session, user)
    [profile] = await _profiles(db_session, user)
    assert stored.profile_id == profile.id != old_profile_id
    assert (stored.status, stored.amount_krw, stored.net_amount_krw) == ("held", 10_000, 9_670)
    assert (profile.entered_by_admin_id, profile.consented_at, profile.privacy_version) == (admin_id, None, None)
    assert (profile.superseded_at, profile.bank_code, profile.account_last4) == (None, "090", "5678")
    assert [decrypt_field(_keyring(), profile, column) for column, _ in PLAINTEXTS] == ["홍길순", RRN, NEW_ACCOUNT]
    [log] = await _audit(db_session, "user-creator-payout-payee-replace")
    assert (log.admin_id, log.target_user_id, log.reason_text) == (admin_id, user.id, "문의로 받은 계좌")
    detail = (await db_client.get(base)).json()
    assert (detail["maskedName"], detail["accountLast4"], detail["payeeEnteredByAdmin"]) == ("홍*순", "5678", True)
    for secret in (RRN, NEW_ACCOUNT, "홍길순"):
        assert secret not in caplog.text


async def test_replacing_the_payee_keeps_a_version_another_payout_still_uses(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """앞 판을 이미 이체한 지급이 가리키면 그 판은 원천징수 근거라 남고 내려가기만 한다."""
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    await _confirm(db_session, user, 10_000, month=11)
    [paid] = await _payouts(db_session, user)
    await db_session.execute(
        update(CreatorPayout)
        .where(CreatorPayout.id == paid.id)
        .values(status="paid", paid_at=func.now(), transferred_on=date(2026, 10, 9))
    )
    assert (await _request(db_client)).status_code == 201
    locked = await db_session.get(User, user.id, with_for_update=True)
    assert locked is not None
    await erase_account(db_session, locked, delete_storage_object=_keep)
    [in_progress] = [payout for payout in await _payouts(db_session, user) if payout.status == "requested"]
    await _as_admin(db_client, db_session)

    resp = await db_client.put(f"/admin/creator-payout/payouts/{in_progress.id}/payee-info", json=_payee())

    assert resp.status_code == 204
    profiles = {profile.id: profile for profile in await _profiles(db_session, user)}
    by_status = {payout.status: payout for payout in await _payouts(db_session, user)}
    assert set(profiles) == {by_status["paid"].profile_id, by_status["requested"].profile_id}
    assert profiles[by_status["paid"].profile_id].superseded_at is not None
    assert profiles[by_status["requested"].profile_id].superseded_at is None


async def test_payee_replacement_refuses_bad_input_in_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """형식 → 외국인등록번호 → 지금 판의 주민등록번호와 생년월일이 다름. 키가 없으면 넣을 수 없다. 끝난 건은 바꾸지 않는다."""
    user, payout = await _withdrawn_with_request(db_client, db_session)
    await _as_admin(db_client, db_session)
    url = f"/admin/creator-payout/payouts/{payout.id}/payee-info"

    async def put(**overrides: object) -> tuple[int, object]:
        resp = await db_client.put(url, json=_payee(**overrides))
        return resp.status_code, resp.json()["detail"]

    assert await put(accountNumber="12-34") == (422, {"code": "CREATOR_PAYOUT_INFO_INVALID"})
    assert await put(rrn="0001015123456") == (422, {"code": "CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED"})
    # 생년월일만 하루 다르다.
    assert await put(rrn="0001024123456") == (422, {"code": "CREATOR_PAYOUT_RRN_MISMATCH"})
    monkeypatch.setattr(settings, "creator_payout_encryption_keys", "")
    assert await put() == (503, {"code": "CREATOR_PAYOUT_UNAVAILABLE"})
    monkeypatch.setattr(settings, "creator_payout_encryption_keys", CREATOR_PAYOUT_TEST_KEYS)
    [unchanged] = await _profiles(db_session, user)
    assert unchanged.id == payout.profile_id
    today = datetime.now(KST).date().isoformat()
    assert (
        await db_client.post(
            f"/admin/creator-payout/payouts/{payout.id}/transfer",
            json={"transferredOn": today, "payeeProfileId": str(payout.profile_id)},
        )
    ).status_code == 204
    assert await put() == (409, {"code": "CREATOR_PAYOUT_NOT_REQUESTED"})


async def test_payee_replacement_skips_the_birth_date_check_when_the_old_version_is_unreadable(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """키를 잃어 지금 판을 읽을 수 없으면 대조할 값이 없다 — 형식만 보고 받는다(이 건을 이체할 길이 이것뿐이다). 그 건의
    상세도 실명 없이 열리고 보류할 수 있다."""
    user = await _member(db_session)
    profile = await _profile_under_other_key(db_session, user)
    db_session.add(_payout_row(user.id, profile.id))
    await db_session.flush()
    await erase_account(db_session, user, delete_storage_object=_keep)
    [payout] = await _payouts(db_session, user)
    await _as_admin(db_client, db_session)
    base = f"/admin/creator-payout/payouts/{payout.id}"
    detail = await db_client.get(base)
    assert (detail.status_code, detail.json()["payeeInfoReadable"]) == (200, False)
    assert (await db_client.post(f"{base}/hold", json={"reasonText": "계좌 해지됨"})).status_code == 204

    resp = await db_client.put(f"{base}/payee-info", json=_payee(rrn="0001024123456"))

    assert resp.status_code == 204
    [replacement] = await _profiles(db_session, user)
    assert decrypt_field(_keyring(), replacement, "rrn") == "0001024123456"


async def test_transfer_refuses_when_the_payee_changed_after_the_operator_looked(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """운영자가 보고 이체한 판(상세·원문 열람의 `payeeProfileId`)과 지금 판이 다르면 이체 기록은 409 다 — 그 사이 다른
    운영자가 수취 정보를 바꿨다면 돈은 앞 판 계좌로 갔고, 그대로 기록하면 지급이 돈을 받지 않은 판을 가리킨다. 지금 판을
    다시 보고 보내면 기록된다."""
    user, payout = await _withdrawn_with_request(db_client, db_session)
    await _as_admin(db_client, db_session)
    base = f"/admin/creator-payout/payouts/{payout.id}"
    assert (await db_client.post(f"{base}/hold", json={"reasonText": "계좌 해지됨"})).status_code == 204
    viewed = await db_client.post(
        f"{base}/payee-info-view", json={"reasonCategory": "other", "reasonText": "이체 계좌 확인"}
    )
    seen = viewed.json()["payeeProfileId"]
    assert seen == str(payout.profile_id)
    assert (await db_client.put(f"{base}/payee-info", json=_payee())).status_code == 204
    today = datetime.now(KST).date().isoformat()

    stale = await db_client.post(f"{base}/transfer", json={"transferredOn": today, "payeeProfileId": seen})

    assert (stale.status_code, stale.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_PAYEE_CHANGED"})
    [stored] = await _payouts(db_session, user)
    assert (stored.status, stored.paid_at) == ("held", None)
    assert await _audit(db_session, "user-creator-payout-transfer") == []
    current = (await db_client.get(base)).json()["payeeProfileId"]
    assert current == str(stored.profile_id) != seen

    done = await db_client.post(f"{base}/transfer", json={"transferredOn": today, "payeeProfileId": current})

    assert done.status_code == 204
    [paid] = await _payouts(db_session, user)
    assert (paid.status, str(paid.profile_id)) == ("paid", current)


async def test_return_waits_for_an_in_flight_withdrawal_and_then_refuses(db_engine: AsyncEngine) -> None:
    """반려는 수취인 `users` 행을 잠근 뒤 탈퇴 여부를 읽는다. 탈퇴가 그 행을 쥐고 파기하는 동안 들어온 반려는 그 잠금에서
    멈춰 있어야 하고(`_assert_blocked`), 탈퇴가 커밋한 뒤에는 409 `CREATOR_PAYOUT_PAYEE_WITHDRAWN` 으로 끝나야 한다 —
    잠금 없이 읽으면 "탈퇴 안 함"을 보고 반려해, 다시 신청할 수 없는 사람의 금액이 갈 곳을 잃는다. `db_session` 하나
    위에서는 두 세션이 같은 트랜잭션이라 잠금이 서로를 막지 않으므로 엔진에서 커넥션을 따로 받는다.

    여기서 쓴 행은 롤백되지 않아 끝에 직접 지운다."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        user = _make_user(nickname="탈퇴할 작가")
        admin = AdminUser(email=f"admin-{uuid.uuid4()}@example.com", password_hash="unused")
        setup.add_all([user, admin])
        await setup.flush()
        profile = _profile_for(user.id)
        setup.add(profile)
        await setup.flush()
        payout = _payout_row(user.id, profile.id)
        setup.add(payout)
        await setup.commit()
    email = user.email
    try:
        async with factory() as withdrawal, factory() as operator:
            locked = await lock_active_user(withdrawal, user.id)

            waiting = asyncio.create_task(
                return_creator_payout(
                    payout.id, AdminCreatorPayoutReturnRequest(reason_text="이체 실패"), admin.id, operator
                )
            )
            await _assert_blocked(waiting)

            await erase_account(withdrawal, locked, delete_storage_object=_keep)

            with pytest.raises(HTTPException) as refused:
                await waiting

        detail: object = refused.value.detail
        assert (refused.value.status_code, detail) == (409, {"code": "CREATOR_PAYOUT_PAYEE_WITHDRAWN"})
        async with factory() as check:
            stored = await check.get(CreatorPayout, payout.id)
            assert stored is not None
            assert (stored.status, stored.returned_at) == ("requested", None)
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(AdminActionLog).where(AdminActionLog.admin_id == admin.id))
            await cleanup.execute(delete(CreatorPayout).where(CreatorPayout.user_id == user.id))
            await cleanup.execute(delete(CreatorPayoutProfile).where(CreatorPayoutProfile.user_id == user.id))
            await cleanup.execute(
                delete(WithdrawnEmail).where(WithdrawnEmail.email_hmac == hash_withdrawn_email(email))
            )
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.execute(delete(AdminUser).where(AdminUser.id == admin.id))
            await cleanup.commit()


async def test_held_payout_blocks_the_member_like_a_requested_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """보류는 탈퇴한 회원 건에만 생기지만, 회원 쪽 판정도 보류를 처리 중으로 센다 — 새 확정분이 있어도 두 번째 지급
    신청·지급 정보 변경을 받지 않고, 금액은 잔액에서 빠진 채이며, 화면에는 처리 중으로 보인다."""
    user = await _ready(db_client, db_session, 10_000)
    assert (await _request(db_client)).status_code == 201
    [payout] = await _payouts(db_session, user)
    await db_session.execute(
        update(CreatorPayout).where(CreatorPayout.id == payout.id).values(status="held", held_at=func.now())
    )
    await _confirm(db_session, user, 20_000, month=11)

    request = await _request(db_client)
    info = await db_client.put("/me/creator-payout/payout-info", json=_info(bankCode="004"))
    overview = (await db_client.get("/me/creator-payout")).json()
    listed = (await db_client.get("/me/creator-payout/payouts")).json()["items"]

    in_progress = (409, {"code": "CREATOR_PAYOUT_IN_PROGRESS"})
    assert (request.status_code, request.json()["detail"]) == in_progress
    assert (info.status_code, info.json()["detail"]) == in_progress
    assert (overview["balanceKrw"], overview["inProgressPayout"]["amountKrw"]) == (20_000, 10_000)
    assert [item["status"] for item in listed] == ["requested"]


def test_member_sees_a_held_payout_as_in_progress() -> None:
    statuses: tuple[CreatorPayoutStatus, ...] = ("requested", "held", "paid", "returned")
    assert [member_payout_status(status) for status in statuses] == [
        "requested",
        "requested",
        "paid",
        "returned",
    ]


# ── 어드민 회원 상세의 정산 섹션 ─────────────────────────────────────────────────
async def test_member_detail_section_shows_history_balance_and_recent_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """신청 이력 전부(최신순), 잔액(처리 중 지급을 뺀 값), 확정은 최근 12개, 지급은 최근 20개."""
    user = await _member(db_session, status="revoked")
    db_session.add(
        CreatorPayoutApplication(
            user_id=user.id,
            status="rejected",
            consented_at=datetime(2026, 8, 1, tzinfo=UTC),
            privacy_version="2026-08-01",
            applied_at=datetime(2026, 8, 1, tzinfo=UTC),
            decided_at=datetime(2026, 8, 2, tzinfo=UTC),
            decision_reason="발행 작품 없음",
        )
    )
    for index in range(13):
        start = datetime(2025 + (index // 12), index % 12 + 1, 1, tzinfo=KST)
        db_session.add(
            CreatorPayoutConfirmation(
                user_id=user.id,
                kind="monthly",
                period_month=start.date(),
                window_start=start,
                window_end=start + timedelta(days=28),
                gross_units=0,
                refunded_units=0,
                rate_bps=500,
                exact_krw=Decimal(2_000),
                amount_krw=2_000,
            )
        )
    profile = _profile_for(user.id)
    db_session.add(profile)
    await db_session.flush()
    for day in range(1, 21):
        db_session.add(
            _payout_row(
                user.id,
                profile.id,
                status="returned",
                amount_krw=1_000,
                income_tax_krw=30,
                local_tax_krw=0,
                net_amount_krw=970,
                requested_at=datetime(2026, 9, day, tzinfo=UTC),
                returned_at=datetime(2026, 9, day, tzinfo=UTC),
            )
        )
    db_session.add(_payout_row(user.id, profile.id, requested_at=datetime(2026, 10, 1, tzinfo=UTC)))
    await db_session.flush()
    await _as_admin(db_client, db_session)

    resp = await db_client.get(f"/admin/users/{user.id}/creator-payout")

    assert resp.status_code == 200
    body = resp.json()
    assert [(item["status"], item["decisionReason"]) for item in body["applications"]] == [
        ("revoked", ""),
        ("rejected", "발행 작품 없음"),
    ]
    assert body["balanceKrw"] == 13 * 2_000 - 10_000
    assert [item["periodMonth"] for item in body["confirmations"][:: len(body["confirmations"]) - 1]] == [
        "2026-01-01",
        "2025-02-01",
    ]
    assert len(body["confirmations"]) == 12
    assert len(body["payouts"]) == 20
    assert (body["payouts"][0]["status"], body["payouts"][0]["amountKrw"]) == ("requested", 10_000)
    assert body["payouts"][-1]["requestedAt"].startswith("2026-09-02")


async def test_member_detail_section_is_404_for_withdrawn_or_missing_members(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _member(db_session)
    assert (await db_client.get(f"/admin/users/{user.id}/creator-payout")).status_code == 401
    await erase_account(db_session, user, delete_storage_object=_keep)
    await _as_admin(db_client, db_session)

    for user_id in (user.id, uuid.uuid4()):
        resp = await db_client.get(f"/admin/users/{user_id}/creator-payout")
        assert (resp.status_code, resp.json()["detail"]) == (404, "User not found")
