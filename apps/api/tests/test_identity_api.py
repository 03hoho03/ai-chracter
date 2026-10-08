"""휴대폰 본인인증: 시작(인증 id 를 사용자에 묶기)·완료(포트원 재조회 후 저장)·탈퇴 때 CI 해시 보관·`GET /me` 필드, 그리고
`users` 인증 칸의 CHECK·부분 유니크.

실제 포트원을 부르지 않는다 — 게이트웨이를 가짜로 갈아끼우고, 가짜는 SDK 의 본인인증 클래스를 그대로 돌려준다(완료가
`isinstance` 로 상태를 가른다). 포트원 키와 CI 키는 로컬 `.env` 의 실제 값이 아니라 테스트가 정한다.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from portone_server_sdk.common import SelectedChannel
from portone_server_sdk.identity_verification import (
    IdentityVerification,
    IdentityVerificationRequestedCustomer,
    IdentityVerificationVerifiedCustomer,
    ReadyIdentityVerification,
    VerifiedIdentityVerification,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.withdrawal import erase_account
from api.clover.missions import MissionKey, mission_idempotency_key
from api.core import clover
from api.core.config import settings
from api.core.redis import redis_client
from api.core.security import hash_identity_ci
from api.db.models.auth import User, WithdrawnIdentity
from api.main import app
from api.payments.errors import PortOneUnavailableError
from api.payments.portone import get_portone_gateway
from factories import _login_as, _make_user

_IDENTITY_CHANNEL = "identity-channel-test"
_CI = "ci-of-the-person-under-test=="


@pytest.fixture(autouse=True)
def _portone_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬 `.env` 에 실제 포트원 키가 있다 — 키 유무로 갈리는 분기를 환경이 아니라 테스트가 정한다. 인증 시작은 결제나
    게이트 중 하나가 켜져 있어야 열리므로 게이트를 켠다."""
    monkeypatch.setattr(settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(settings, "portone_payment_channel_key", "channel-key-test-inicis")
    monkeypatch.setattr(settings, "portone_identity_channel_key", _IDENTITY_CHANNEL)
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "portone_webhook_secret", "")
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "identity_gate_enabled", True)


class _FakeGateway:
    def __init__(self) -> None:
        self.verifications: dict[str, IdentityVerification] = {}
        self.calls: list[str] = []
        self.unavailable = False

    async def get_payment(self, payment_id: str) -> Any:
        raise AssertionError("본인인증은 결제를 조회하지 않는다")

    async def cancel_payment(self, payment_id: str, **kwargs: Any) -> Any:
        raise AssertionError("본인인증은 결제를 취소하지 않는다")

    async def get_identity_verification(self, identity_verification_id: str) -> IdentityVerification:
        self.calls.append(identity_verification_id)
        if self.unavailable:
            raise PortOneUnavailableError("get_identity_verification", "ConnectError")
        return self.verifications[identity_verification_id]


@pytest.fixture(autouse=True)
def gateway() -> Iterator[_FakeGateway]:
    fake = _FakeGateway()
    app.dependency_overrides[get_portone_gateway] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_portone_gateway, None)


@pytest_asyncio.fixture(autouse=True)
async def _clear_bindings() -> AsyncIterator[None]:
    """인증 id 묶음은 한 시간짜리 Redis 키다. 다음 실행에 남지 않게 지운다."""
    yield
    keys = [key async for key in redis_client.scan_iter("identity_verification:*")]
    if keys:
        await redis_client.delete(*keys)


def _born_years_ago(years: int) -> date:
    """오늘(UTC) 기준 정확히 만 `years` 세가 되는 생년월일(1월 1일생이라 생일이 이미 지났다)."""
    return date(datetime.now(UTC).date().year - years, 1, 1)


def _verified(
    identity_verification_id: str,
    *,
    ci: str | None = _CI,
    birth_date: str | None = "1990-05-05",
    channel_key: str | None = _IDENTITY_CHANNEL,
) -> VerifiedIdentityVerification:
    return VerifiedIdentityVerification(
        id=identity_verification_id,
        verified_customer=IdentityVerificationVerifiedCustomer(
            name="홍길동", phone_number="01012345678", ci=ci, di="di-test", birth_date=birth_date
        ),
        requested_at="2026-10-08T03:00:00Z",
        updated_at="2026-10-08T03:01:00Z",
        status_changed_at="2026-10-08T03:01:00Z",
        verified_at="2026-10-08T03:01:00Z",
        pg_tx_id="pg-tx-test",
        pg_raw_response="{}",
        version="V2",
        channel=(
            None
            if channel_key is None
            else SelectedChannel(type="TEST", pg_provider="KCP_V2", pg_merchant_id="kcp-test", key=channel_key)
        ),
    )


async def _user(db: AsyncSession, client: httpx.AsyncClient | None = None, **overrides: object) -> User:
    user = _make_user(**overrides)
    db.add(user)
    await db.flush()
    if client is not None:
        await _login_as(client, user.id)
    return user


async def _start(client: httpx.AsyncClient) -> str:
    resp = await client.post("/me/identity-verifications")
    assert resp.status_code == 201, resp.text
    identity_verification_id: str = resp.json()["identityVerificationId"]
    return identity_verification_id


async def _refreshed(db: AsyncSession, user: User) -> User:
    await db.refresh(user)
    return user


# ── 시작 ─────────────────────────────────────────────────────────────────
async def test_start_binds_a_server_issued_id_to_the_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _user(db_session, db_client)

    resp = await db_client.post("/me/identity-verifications")

    assert resp.status_code == 201
    body = resp.json()
    assert body["storeId"] == "store-test-0001"
    assert body["channelKey"] == _IDENTITY_CHANNEL
    assert body["identityVerificationId"].startswith("idv")
    assert await redis_client.get(f"identity_verification:{body['identityVerificationId']}") == str(user.id)


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        pytest.param("identity_gate_enabled", False, id="nothing-needs-it"),
        pytest.param("identity_ci_hmac_key", "", id="not-configured"),
    ],
)
async def test_start_is_closed_when_no_feature_needs_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, setting: str, value: object
) -> None:
    """쓰일 곳이 없는 인증(결제·게이트 둘 다 꺼짐)이나 저장할 수 없는 인증(CI 키 없음)으로 개인정보를 받지 않는다."""
    await _user(db_session, db_client)
    monkeypatch.setattr(settings, setting, value)

    resp = await db_client.post("/me/identity-verifications")

    assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "IDENTITY_VERIFICATION_UNAVAILABLE"})


async def test_start_is_open_when_only_payments_need_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """게이트가 꺼져 있어도 결제가 켜져 있으면 결제 전 만 19세 확인을 위해 인증할 수 있어야 한다."""
    await _user(db_session, db_client)
    monkeypatch.setattr(settings, "identity_gate_enabled", False)
    monkeypatch.setattr(settings, "payments_enabled", True)
    monkeypatch.setattr(settings, "portone_webhook_secret", "whsec_dGVzdA==")

    resp = await db_client.post("/me/identity-verifications")

    assert resp.status_code == 201


async def test_start_refuses_an_already_verified_account(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _user(db_session, db_client, identity_ci_hmac="h", identity_verified_at=datetime.now(UTC))

    resp = await db_client.post("/me/identity-verifications")

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "IDENTITY_ALREADY_VERIFIED"})


# ── 완료 ─────────────────────────────────────────────────────────────────
async def test_complete_stores_the_ci_hash_and_overwrites_birth_date(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """인증된 생년월일이 자기 신고값을 대신한다(결제 나이 판정이 이 값을 읽는다). CI 는 원문이 아니라 키 있는 해시로만."""
    user = await _user(db_session, db_client, birth_date=date(2001, 2, 3))
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(identity_verification_id, birth_date="1990-05-05")

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert resp.status_code == 200, resp.text
    user = await _refreshed(db_session, user)
    assert user.identity_ci_hmac == hash_identity_ci(_CI) != _CI
    assert user.identity_verified_at is not None
    assert resp.json() == {"verifiedAt": user.identity_verified_at.isoformat().replace("+00:00", "Z")}
    assert user.birth_date == date(1990, 5, 5)
    # 묶음은 한 번 쓰고 지운다.
    assert await redis_client.get(f"identity_verification:{identity_verification_id}") is None


async def test_complete_refuses_an_id_bound_to_someone_else(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """남이 끝낸 인증 id 를 들고 와 자기 계정을 인증하지 못한다 — 포트원을 부르기도 전에 끊는다."""
    owner = await _user(db_session, db_client)
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(identity_verification_id)
    intruder = await _user(db_session, db_client)

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (404, {"code": "IDENTITY_VERIFICATION_NOT_FOUND"})
    assert gateway.calls == []
    assert (await _refreshed(db_session, intruder)).identity_ci_hmac is None
    assert (await _refreshed(db_session, owner)).identity_ci_hmac is None


async def test_complete_refuses_an_unbound_id(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _user(db_session, db_client)

    resp = await db_client.post(f"/me/identity-verifications/idv{uuid.uuid4().hex}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (404, {"code": "IDENTITY_VERIFICATION_NOT_FOUND"})


async def test_complete_refuses_when_the_account_is_already_verified(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """인증 전에 열어 둔 두 번째 창으로 다른 사람의 인증을 덮어써 계정의 주인을 바꾸지 못한다."""
    user = await _user(db_session, db_client)
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(identity_verification_id, ci="someone-else")
    user.identity_ci_hmac = hash_identity_ci(_CI)
    user.identity_verified_at = datetime.now(UTC)
    await db_session.flush()

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "IDENTITY_ALREADY_VERIFIED"})
    assert (await _refreshed(db_session, user)).identity_ci_hmac == hash_identity_ci(_CI)


async def test_complete_reports_portone_failure_as_502(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    await _user(db_session, db_client)
    identity_verification_id = await _start(db_client)
    gateway.unavailable = True

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (502, {"code": "PORTONE_UNAVAILABLE"})


@pytest.mark.parametrize(
    ("make", "code"),
    [
        pytest.param(
            lambda vid: ReadyIdentityVerification(
                id=vid,
                requested_customer=IdentityVerificationRequestedCustomer(),
                requested_at="2026-10-08T03:00:00Z",
                updated_at="2026-10-08T03:00:00Z",
                status_changed_at="2026-10-08T03:00:00Z",
                version="V2",
            ),
            "IDENTITY_VERIFICATION_NOT_VERIFIED",
            id="not-verified",
        ),
        pytest.param(
            lambda vid: _verified(vid, channel_key="payment-channel"), "IDENTITY_VERIFICATION_NOT_VERIFIED", id="channel"
        ),
        pytest.param(lambda vid: _verified(vid, ci=None), "IDENTITY_CI_MISSING", id="no-ci"),
        pytest.param(lambda vid: _verified(vid, birth_date=None), "IDENTITY_BIRTH_DATE_MISSING", id="no-birth-date"),
        pytest.param(lambda vid: _verified(vid, birth_date="1990-13-45"), "IDENTITY_BIRTH_DATE_MISSING", id="bad-date"),
    ],
)
async def test_complete_rejects_unusable_results_without_storing_anything(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, make: Any, code: str
) -> None:
    """CI 가 없으면 한 사람 한 계정을 지킬 수 없고, 생년월일 없이 덮어쓰면 로그인의 연령 확인이 그 계정을 매번 실패시킨다.
    어느 쪽이든 CI 해시도 생년월일도 그대로다."""
    user = await _user(db_session, db_client, birth_date=date(2001, 2, 3))
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = make(identity_verification_id)

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (422, {"code": code})
    user = await _refreshed(db_session, user)
    assert (user.identity_ci_hmac, user.identity_verified_at, user.birth_date) == (None, None, date(2001, 2, 3))


async def test_complete_accepts_a_result_without_channel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """채널은 포트원이 생략할 수 있는 필드다 — 없을 때는 대조할 것이 없을 뿐 거절 사유가 아니다."""
    user = await _user(db_session, db_client)
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(identity_verification_id, channel_key=None)

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert resp.status_code == 200
    assert (await _refreshed(db_session, user)).identity_ci_hmac == hash_identity_ci(_CI)


async def test_complete_under_fourteen_stores_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """만 14세 미만으로 인증되면 CI 도 생년월일도 저장하지 않는다 — 자기 신고 생년월일이 그대로라 계정이 잠기지도 않는다."""
    user = await _user(db_session, db_client, birth_date=date(2001, 2, 3))
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(
        identity_verification_id, birth_date=_born_years_ago(13).isoformat()
    )

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_UNDER_MINIMUM_AGE"})
    user = await _refreshed(db_session, user)
    assert (user.identity_ci_hmac, user.identity_verified_at, user.birth_date) == (None, None, date(2001, 2, 3))


async def test_complete_at_fourteen_is_accepted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """위 거절의 경계 짝 — 만 14세는 가입 하한 안이라 저장한다."""
    user = await _user(db_session, db_client)
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(
        identity_verification_id, birth_date=_born_years_ago(14).isoformat()
    )

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert resp.status_code == 200
    assert (await _refreshed(db_session, user)).birth_date == _born_years_ago(14)


@pytest.mark.parametrize(
    ("age", "keeps_beta"),
    [pytest.param(18, False, id="eighteen-loses-beta"), pytest.param(19, True, id="nineteen-keeps-beta")],
)
async def test_complete_revokes_beta_when_verified_under_nineteen(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, age: int, keeps_beta: bool
) -> None:
    """베타는 성인만 받는데 지정 때는 자기 신고 생년월일만 봤다. 인증 결과가 만 19세 미만이면 베타 자격을 거둔다."""
    joined = datetime(2026, 9, 1, tzinfo=UTC)
    user = await _user(db_session, db_client, beta_joined_at=joined)
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(
        identity_verification_id, birth_date=_born_years_ago(age).isoformat()
    )

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert resp.status_code == 200
    user = await _refreshed(db_session, user)
    assert user.identity_ci_hmac is not None
    assert user.beta_joined_at == (joined if keeps_beta else None)


async def test_complete_refuses_a_person_already_verified_on_another_live_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    await _user(db_session, identity_ci_hmac=hash_identity_ci(_CI), identity_verified_at=datetime.now(UTC))
    user = await _user(db_session, db_client, birth_date=date(2001, 2, 3))
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(identity_verification_id)

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "IDENTITY_ALREADY_USED"})
    user = await _refreshed(db_session, user)
    assert (user.identity_ci_hmac, user.birth_date) == (None, date(2001, 2, 3))


async def test_complete_allows_a_person_who_withdrew_to_verify_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """탈퇴한 사람의 재가입·재인증은 막지 않는다. 탈퇴 행에 해시가 남아 있어도(옛 코드가 탈퇴시킨 행) 살아 있는 계정만
    대조한다."""
    await _user(
        db_session,
        identity_ci_hmac=hash_identity_ci(_CI),
        identity_verified_at=datetime.now(UTC),
        deleted_at=datetime.now(UTC),
    )
    db_session.add(WithdrawnIdentity(ci_hmac=hash_identity_ci(_CI), withdrawn_at=datetime.now(UTC)))
    user = await _user(db_session, db_client)
    identity_verification_id = await _start(db_client)
    gateway.verifications[identity_verification_id] = _verified(identity_verification_id)

    resp = await db_client.post(f"/me/identity-verifications/{identity_verification_id}/complete")

    assert resp.status_code == 200
    assert (await _refreshed(db_session, user)).identity_ci_hmac == hash_identity_ci(_CI)


# ── 제약 ─────────────────────────────────────────────────────────────────
# `alembic check` 는 CHECK 와 부분 인덱스의 WHERE 를 비교하지 않는다 — 이 행위 테스트가 마이그레이션이 실제로 그 제약을
# 걸었는지의 유일한 검증이다.
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"identity_ci_hmac": "h"}, id="hash-without-time"),
        pytest.param({"identity_verified_at": datetime(2026, 10, 8, tzinfo=UTC)}, id="time-without-hash"),
    ],
)
async def test_identity_columns_come_in_pairs(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        await _user(db_session, None, **overrides)


async def test_two_live_accounts_cannot_share_a_ci_hash(db_session: AsyncSession) -> None:
    await _user(db_session, identity_ci_hmac="same", identity_verified_at=datetime.now(UTC))
    with pytest.raises(IntegrityError):
        await _user(db_session, identity_ci_hmac="same", identity_verified_at=datetime.now(UTC))


async def test_a_withdrawn_account_does_not_hold_its_ci_hash(db_session: AsyncSession) -> None:
    """위 거절의 짝 — 유일성은 살아 있는 계정 사이에서만이다."""
    await _user(
        db_session, identity_ci_hmac="same", identity_verified_at=datetime.now(UTC), deleted_at=datetime.now(UTC)
    )
    await _user(db_session, identity_ci_hmac="same", identity_verified_at=datetime.now(UTC))


# ── 탈퇴 ─────────────────────────────────────────────────────────────────
async def _keep(storage_key: str) -> None:
    return None


async def _claim_mission(db: AsyncSession, user: User, key: MissionKey) -> None:
    await clover.grant(
        db,
        user_id=user.id,
        amount=100,
        kind="mission_grant",
        idempotency_key=mission_idempotency_key(user_id=user.id, key=key),
        expires_at=None,
    )


async def test_erase_account_moves_the_ci_hash_and_claimed_missions_aside(db_session: AsyncSession) -> None:
    """탈퇴는 사용자 행의 두 칸을 비우고, 해시와 받은 1회성 미션 키를 보관 행으로 옮긴다(같은 사람이 새 계정으로 같은
    보상을 다시 받지 못하게)."""
    ci_hmac = hash_identity_ci(_CI)
    user = await _user(db_session, identity_ci_hmac=ci_hmac, identity_verified_at=datetime.now(UTC))
    await _claim_mission(db_session, user, "first_message")
    await _claim_mission(db_session, user, "first_publish")

    await erase_account(db_session, user, delete_storage_object=_keep)

    user = await _refreshed(db_session, user)
    assert (user.identity_ci_hmac, user.identity_verified_at) == (None, None)
    row = await db_session.get(WithdrawnIdentity, ci_hmac)
    assert row is not None
    assert sorted(row.claimed_mission_keys) == ["first_message", "first_publish"]
    assert row.withdrawn_at == user.deleted_at


async def test_erase_account_merges_with_a_recent_withdrawal_of_the_same_person(db_session: AsyncSession) -> None:
    """탈퇴 → 재가입 → 다시 탈퇴: 앞 계정에서 받은 기록을 잃으면 세 번째 계정에서 같은 보상을 다시 받는다."""
    ci_hmac = hash_identity_ci(_CI)
    db_session.add(
        WithdrawnIdentity(
            ci_hmac=ci_hmac, withdrawn_at=datetime.now(UTC) - timedelta(days=30), claimed_mission_keys=["first_image"]
        )
    )
    user = await _user(db_session, identity_ci_hmac=ci_hmac, identity_verified_at=datetime.now(UTC))
    await _claim_mission(db_session, user, "first_message")

    await erase_account(db_session, user, delete_storage_object=_keep)

    row = await db_session.get(WithdrawnIdentity, ci_hmac, populate_existing=True)
    assert row is not None
    assert sorted(row.claimed_mission_keys) == ["first_image", "first_message"]


async def test_erase_account_does_not_revive_an_expired_withdrawal(db_session: AsyncSession) -> None:
    """보관 기간이 지난 기록(크론이 아직 못 지운 행)은 이미 조회에서 무시된다 — 새 탈퇴가 그 키를 되살리지 않는다."""
    ci_hmac = hash_identity_ci(_CI)
    db_session.add(
        WithdrawnIdentity(
            ci_hmac=ci_hmac, withdrawn_at=datetime.now(UTC) - timedelta(days=400), claimed_mission_keys=["first_image"]
        )
    )
    user = await _user(db_session, identity_ci_hmac=ci_hmac, identity_verified_at=datetime.now(UTC))

    await erase_account(db_session, user, delete_storage_object=_keep)

    row = await db_session.get(WithdrawnIdentity, ci_hmac, populate_existing=True)
    assert row is not None
    assert row.claimed_mission_keys == []


async def test_erase_account_of_an_unverified_user_leaves_no_identity_row(db_session: AsyncSession) -> None:
    user = await _user(db_session)

    await erase_account(db_session, user, delete_storage_object=_keep)

    assert (await db_session.scalars(select(WithdrawnIdentity))).all() == []


# ── GET /me ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("gate", [pytest.param(True, id="gate-on"), pytest.param(False, id="gate-off")])
@pytest.mark.parametrize("verified", [pytest.param(True, id="verified"), pytest.param(False, id="unverified")])
async def test_me_reports_verification_and_gate(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    gate: bool,
    verified: bool,
) -> None:
    """화면은 이 두 값으로 인증 안내를 띄울지 정한다. 게이트 값은 라우트 게이트와 같은 판정 함수의 값이다."""
    monkeypatch.setattr(settings, "identity_gate_enabled", gate)
    user = await _user(db_session, db_client)
    if verified:
        user.identity_ci_hmac = "h"
        user.identity_verified_at = datetime.now(UTC)
        await db_session.flush()

    resp = await db_client.get("/me")

    assert resp.status_code == 200
    assert (resp.json()["identityVerified"], resp.json()["identityGateEnabled"]) == (verified, gate)
