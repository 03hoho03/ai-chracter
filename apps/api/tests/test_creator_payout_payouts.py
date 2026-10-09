"""크리에이터 지급: 지급 정보 입력(검증·암호화·판 갈기), 지급 신청(잔액 전액·최소액·탈퇴 전 예외·원천징수 스냅숏), 어드민
지급 처리(목록·상세·원문 열람·이체 기록·반려), 탈퇴 뒤 보존, 키 회전·분실.

잔액은 확정 행을 직접 넣어 만든다(확정 계산은 정산 테스트 몫이다). 회원은 2000-01-01생 본인인증 성인이고, 그 사람의
주민등록번호는 `RRN`(2000년대 출생 여성, 7번째 자리 4)이다.
"""

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
from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.withdrawal import erase_account
from api.core import config
from api.core.config import settings
from api.core.field_crypto import FieldDecryptError, FieldKeyring
from api.core.rate_limit import KST
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
from api.creator_payout.router import payout_requested_message
from api.creator_payout.tax import withholding
from api.db.models.auth import User
from api.db.models.creator_payout import (
    CreatorPayout,
    CreatorPayoutApplication,
    CreatorPayoutConfirmation,
    CreatorPayoutProfile,
)
from api.db.models.moderation import AdminActionLog
from api.legal.dependencies import _latest_published_legal_version
from api.main import app
from api.payments.notify import get_payment_notifier
from factories import CREATOR_PAYOUT_TEST_KEYS, _application, _create_admin, _login_as, _login_as_admin, _make_user

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
        json={"transferredOn": datetime.now(KST).date().isoformat()},
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
        json={"transferredOn": datetime.now(KST).date().isoformat(), "adminMemo": "국민 이체"},
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
    first = await db_client.post(url, json={"reasonCategory": "legal-request", "reasonText": "지급명세서 작성"})
    second = await db_client.post(url, json={"reasonCategory": "other", "reasonText": "이체 계좌 확인"})

    assert blank.status_code == 422
    assert first.json() == {"legalName": "홍길동", "rrn": RRN, "bankCode": "088", "accountNumber": ACCOUNT}
    assert second.status_code == 200
    views = await _audit(db_session, "user-creator-payout-info-view")
    assert sorted((log.reason_category, log.reason_text) for log in views) == [
        ("legal-request", "지급명세서 작성"),
        ("other", "이체 계좌 확인"),
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

    before = await db_client.post(url, json={"transferredOn": (requested_on - timedelta(days=1)).isoformat()})
    future = await db_client.post(url, json={"transferredOn": (today + timedelta(days=1)).isoformat()})
    done = await db_client.post(url, json={"transferredOn": today.isoformat(), "adminMemo": "국민 이체"})
    again = await db_client.post(url, json={"transferredOn": today.isoformat()})
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


async def test_lost_key_keeps_the_owner_view_and_stops_the_admin(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작가 화면은 200 으로 열리고 실명만 비며(은행·끝 4자리는 평문), 어드민 상세·원문 열람은 409 이고 열람 기록도 없다."""
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
    unreadable = (409, {"code": "CREATOR_PAYOUT_INFO_UNREADABLE"})
    assert (detail.status_code, detail.json()["detail"]) == unreadable
    assert (view.status_code, view.json()["detail"]) == unreadable
    assert await _audit(db_session, "user-creator-payout-info-view") == []


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

    assert (detail.status_code, detail.json()["detail"]) == (409, {"code": "CREATOR_PAYOUT_INFO_UNREADABLE"})


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
        await db_client.post(f"/admin/creator-payout/payouts/{paid.id}/transfer", json={"transferredOn": today})
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
            f"/admin/creator-payout/payouts/{in_progress.id}/transfer", json={"transferredOn": today}
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
    ],
)
async def test_payout_check_constraints(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    user = await _member(db_session)
    profile = _profile_for(user.id)
    db_session.add(profile)
    await db_session.flush()

    await _insert_fails(db_session, _payout_row(user.id, profile.id, **overrides))


async def test_one_requested_payout_per_member(db_session: AsyncSession) -> None:
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
