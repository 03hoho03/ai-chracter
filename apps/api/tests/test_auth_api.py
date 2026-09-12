import asyncio
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from api.auth.verification import get_verification_code, store_verification_code
from api.core.config import settings
from api.core.email import EmailSendError, get_email_sender
from api.db.models.auth import GuardianConsent, User
from api.db.session import engine
from api.main import app
from factories import _make_asset, _make_user


def _signup_payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "테스터",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
    }
    defaults.update(overrides)
    return defaults


async def test_signup_creates_unverified_user_and_sends_code(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = _signup_payload()

    resp = await db_client.post("/auth/signup", json=payload)
    assert resp.status_code == 201
    assert resp.json() == {"email": payload["email"]}

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.email_verified_at is None
    assert user.password_hash is not None
    assert user.password_hash != payload["password"]

    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None
    assert len(stored["code"]) == 6


async def test_signup_rejects_missing_terms_agreement(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/signup", json=_signup_payload(termsAgreed=False))
    assert resp.status_code == 422


async def test_signup_rejects_missing_privacy_agreement(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/signup", json=_signup_payload(privacyAgreed=False))
    assert resp.status_code == 422


async def test_signup_rejects_duplicate_verified_email(db_client: httpx.AsyncClient) -> None:
    """email-goal-prompt.md E-5: 인증 완료 이메일의 재가입은 409로 막힌다(현행 유지)."""
    payload = await _signup_and_verify(db_client)

    second = await db_client.post("/auth/signup", json=_signup_payload(email=payload["email"]))
    assert second.status_code == 409


async def test_signup_overwrites_unverified_account_and_issues_new_code(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """email-goal-prompt.md E-5: 미인증 재가입은 방치된 가입으로 간주해 기존 row를
    덮어쓴다 — id/created_at은 보존, 닉네임·생일·동의 시각은 갱신, 새 인증코드 발급."""
    payload = _signup_payload()
    first = await db_client.post("/auth/signup", json=payload)
    assert first.status_code == 201

    original = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert original is not None
    original_id = original.id
    original_created_at = original.created_at
    original_terms_agreed_at = original.terms_agreed_at

    # E-5 조사 I-2: 덮어쓰기 분기가 손대면 안 되는 필드도 채워둔다. 지금 구현은 이 둘을
    # 아예 안 건드려서 보존되지만, 값을 비워두면 "조용히 None이 되는" 회귀를 이 테스트가
    # 못 잡는다.
    original.bio = "안녕하세요"
    profile_asset = await _make_asset(db_session, original_id)
    original.profile_image_asset_id = profile_asset.id
    await db_session.commit()

    second = await db_client.post(
        "/auth/signup",
        json=_signup_payload(email=payload["email"], nickname="새닉네임", birthDate="1995-05-05"),
    )
    assert second.status_code == 201

    updated = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert updated is not None
    assert updated.id == original_id
    assert updated.created_at == original_created_at
    assert updated.email_verified_at is None
    assert updated.nickname == "새닉네임"
    assert updated.birth_date == date(1995, 5, 5)
    assert updated.terms_agreed_at > original_terms_agreed_at
    assert updated.bio == "안녕하세요"
    assert updated.profile_image_asset_id == profile_asset.id

    new_code = await get_verification_code(str(payload["email"]))
    assert new_code is not None


async def test_signup_rejects_unverified_account_with_google_sub(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """email-goal-prompt.md E-5 성공기준 7-a: google_sub가 연결된 계정은 email_verified_at이
    없어도(구글 콜백은 그 값을 보지 않고 세션을 발급하므로 실사용 중일 수 있다) 409."""
    email = f"race-google-{uuid.uuid4()}@example.com"
    db_session.add(_make_user(email=email, google_sub=f"sub-{uuid.uuid4()}"))
    await db_session.flush()

    resp = await db_client.post("/auth/signup", json=_signup_payload(email=email))
    assert resp.status_code == 409


async def test_signup_rejects_unverified_deleted_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """email-goal-prompt.md E-5: 탈퇴 계정은 미인증이어도 재가입으로 부활시키지 않는다."""
    email = f"race-deleted-{uuid.uuid4()}@example.com"
    db_session.add(_make_user(email=email, deleted_at=datetime.now(UTC)))
    await db_session.flush()

    resp = await db_client.post("/auth/signup", json=_signup_payload(email=email))
    assert resp.status_code == 409


async def test_signup_rejects_unverified_suspended_account(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """email-goal-prompt.md E-5: 정지 계정은 미인증이어도 재가입으로 초기화되지 않는다."""
    email = f"race-suspended-{uuid.uuid4()}@example.com"
    db_session.add(_make_user(email=email, suspended_at=datetime.now(UTC)))
    await db_session.flush()

    resp = await db_client.post("/auth/signup", json=_signup_payload(email=email))
    assert resp.status_code == 409


async def _wait_until_lock_wait(observer: AsyncConnection, *, seconds: float) -> None:
    """`asyncio.sleep`로 타이밍을 추측하는 대신, signup의 INSERT가 실제로 users 테이블에
    대한 쓰기 잠금(`RowExclusiveLock`)을 이미 쥔 채 인터로퍼의 트랜잭션 종료를 기다리는
    상태(`pg_locks`의 미승인 `transactionid` 대기)에 들어갔는지 `pg_locks`로 직접 관측한다.
    `pg_stat_activity.query`는 이 시나리오에서 신뢰할 수 없었다 — 실제로는 INSERT가 블록된
    상태인데도 그 이전 SELECT의 텍스트를 그대로 보여줬다(직접 재현해 확인). `pg_locks`는
    질의 텍스트가 아니라 실제 잠금 상태이므로 이 문제가 없다. 제한 시간 안에 관측되지 않으면
    조용히 넘어가지 않고 실패시킨다."""
    try:
        async with asyncio.timeout(seconds):
            while True:
                waiting = await observer.scalar(
                    text(
                        "SELECT count(*) FROM pg_locks blocked"
                        " WHERE blocked.locktype = 'transactionid' AND NOT blocked.granted"
                        " AND EXISTS ("
                        "   SELECT 1 FROM pg_locks holding"
                        "   WHERE holding.pid = blocked.pid"
                        "     AND holding.locktype = 'relation'"
                        "     AND holding.relation = 'users'::regclass"
                        "     AND holding.mode = 'RowExclusiveLock'"
                        "     AND holding.granted"
                        " )"
                    )
                )
                if waiting:
                    return
                await asyncio.sleep(0.01)
    except TimeoutError:
        raise AssertionError(
            f"{seconds}초 안에 signup 커넥션이 users 테이블 잠금 대기 상태로 관측되지"
            " 않았다 (pg_locks: RowExclusiveLock 보유 + transactionid 미승인 대기)"
        ) from None


async def test_signup_concurrent_duplicate_returns_409_via_integrity_error(
    db_client: httpx.AsyncClient,
) -> None:
    """email-goal-prompt.md E-11: signup은 select→insert 사이에 경합이 있고, 진 요청은
    users.email unique 제약의 IntegrityError를 맞는다 — 이를 409로 정규화하는지 검증한다.

    진짜 경합을 재현한다(mock 없음): db_client와 별개인 실제 DB 커넥션으로 같은
    이메일을 먼저 INSERT하되 커밋을 미룬다. signup의 INSERT는 그 미커밋 행과 유니크
    인덱스가 충돌해 그 커넥션의 커밋/롤백을 기다리며 블록되고, 그 사이 이 커넥션이
    커밋하면 signup 쪽 INSERT가 실제 IntegrityError로 실패한다. 커밋 시점은 고정 슬립이
    아니라 signup 커넥션이 실제로 그 잠금을 기다리기 시작했다는 관측(`_wait_until_lock_wait`)
    으로 정한다."""
    email = f"race-integrity-{uuid.uuid4()}@example.com"
    payload = _signup_payload(email=email)

    async with engine.connect() as interloper:
        await interloper.execute(
            insert(User).values(
                id=uuid.uuid4(),
                email=email,
                nickname="선점",
                birth_date=date(2000, 1, 1),
                terms_agreed_at=datetime.now(UTC),
                privacy_agreed_at=datetime.now(UTC),
            )
        )

        signup_task = asyncio.create_task(db_client.post("/auth/signup", json=payload))
        try:
            await _wait_until_lock_wait(interloper, seconds=5.0)
            await interloper.commit()
            resp = await signup_task

            assert resp.status_code == 409
        finally:
            await interloper.execute(delete(User).where(User.email == email))
            await interloper.commit()


async def test_signup_succeeds_when_email_send_fails(
    db_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """email-goal-prompt.md 성공기준 3: 발송 실패를 주입해도 signup은 201을 유지하고
    실패는 로그에 남는다(BackgroundTasks가 응답 이후 처리하므로)."""

    async def _failing_sender(to: str, subject: str, body: str) -> None:
        raise EmailSendError("boom")

    app.dependency_overrides[get_email_sender] = lambda: _failing_sender
    try:
        with caplog.at_level(logging.WARNING):
            resp = await db_client.post("/auth/signup", json=_signup_payload())
    finally:
        app.dependency_overrides.pop(get_email_sender, None)

    assert resp.status_code == 201
    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_verify_email_adult_does_not_require_guardian_consent(
    db_client: httpx.AsyncClient,
) -> None:
    payload = _signup_payload(birthDate="2000-01-01")
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"isMinorGuardianRequired": False}


async def test_verify_email_minor_requires_guardian_consent(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = _signup_payload(birthDate=minor_birth_date.isoformat())
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"isMinorGuardianRequired": True}


async def test_verify_email_rejects_wrong_code(db_client: httpx.AsyncClient) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
    )
    assert resp.status_code == 400


async def test_verify_email_unknown_user_returns_404(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/verify-email", json={"email": "nobody@example.com", "code": "123456"}
    )
    assert resp.status_code == 404


async def test_resend_within_cooldown_returns_429_with_retry_after(
    db_client: httpx.AsyncClient,
) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post("/auth/resend-verification-code", json={"email": payload["email"]})
    assert resp.status_code == 429
    assert resp.json()["detail"]["retryAfterSeconds"] > 0


async def test_resend_after_cooldown_issues_new_code(db_client: httpx.AsyncClient) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)
    original = await get_verification_code(str(payload["email"]))
    assert original is not None

    # Simulate the cooldown having already elapsed.
    await store_verification_code(
        str(payload["email"]), original["code"], datetime.now().astimezone() - timedelta(seconds=61)
    )

    resp = await db_client.post("/auth/resend-verification-code", json={"email": payload["email"]})
    assert resp.status_code == 204

    refreshed = await get_verification_code(str(payload["email"]))
    assert refreshed is not None


async def test_resend_unknown_user_returns_404(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/resend-verification-code", json={"email": "nobody@example.com"}
    )
    assert resp.status_code == 404


async def _signup_and_verify(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    payload = _signup_payload(**overrides)
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert resp.status_code == 200
    return payload


def _guardian_consent_payload(email: str, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": email,
        "guardianName": "홍길동",
        "guardianContact": "010-1234-5678",
        "consentAgreed": True,
    }
    defaults.update(overrides)
    return defaults


async def test_guardian_consent_activates_minor_account_and_issues_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())

    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert resp.status_code == 204
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    consent = await db_session.scalar(select(GuardianConsent).where(GuardianConsent.user_id == user.id))
    assert consent is not None
    assert consent.guardian_name == "홍길동"

    echo = await db_client.get("/dev/session-echo")
    assert echo.status_code == 200
    assert echo.json() == {"user_id": str(user.id)}


async def test_guardian_consent_rejects_before_email_verified(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = _signup_payload(birthDate=minor_birth_date.isoformat())
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert resp.status_code == 400


async def test_guardian_consent_rejects_adult_account(db_client: httpx.AsyncClient) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")

    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert resp.status_code == 400


async def test_guardian_consent_rejects_consent_not_agreed(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())

    resp = await db_client.post(
        "/auth/guardian-consent",
        json=_guardian_consent_payload(str(payload["email"]), consentAgreed=False),
    )
    assert resp.status_code == 422


async def test_guardian_consent_unknown_user_returns_404(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload("nobody@example.com")
    )
    assert resp.status_code == 404


async def test_login_adult_issues_session_and_me_returns_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204
    assert settings.session_cookie_name in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None

    me = await db_client.get("/me")
    assert me.status_code == 200
    assert me.json() == {
        "id": str(user.id),
        "email": user.email,
        "nickname": user.nickname,
        "bio": None,
        "profileImageAssetId": None,
        "termsReconsentRequired": False,
        "privacyReconsentRequired": False,
    }


async def test_login_rejects_wrong_password(db_client: httpx.AsyncClient) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_login_rejects_unknown_email(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "password123"}
    )
    assert resp.status_code == 401


async def test_login_rejects_unverified_email(db_client: httpx.AsyncClient) -> None:
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 403


async def test_login_rejects_minor_without_guardian_consent(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 403


async def test_login_succeeds_for_minor_with_guardian_consent(db_client: httpx.AsyncClient) -> None:
    minor_birth_date = date.today().replace(year=date.today().year - 10)
    payload = await _signup_and_verify(db_client, birthDate=minor_birth_date.isoformat())
    consent_resp = await db_client.post(
        "/auth/guardian-consent", json=_guardian_consent_payload(str(payload["email"]))
    )
    assert consent_resp.status_code == 204

    resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


async def test_me_without_session_returns_401(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/me")
    assert resp.status_code == 401


async def test_logout_invalidates_session(db_client: httpx.AsyncClient) -> None:
    payload = await _signup_and_verify(db_client, birthDate="2000-01-01")
    login_resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204

    me_before = await db_client.get("/me")
    assert me_before.status_code == 200

    logout_resp = await db_client.post("/auth/logout")
    assert logout_resp.status_code == 204

    me_after = await db_client.get("/me")
    assert me_after.status_code == 401


async def test_logout_without_session_is_idempotent(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post("/auth/logout")
    assert resp.status_code == 204
