import asyncio
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from api.auth.verification import (
    VERIFICATION_ATTEMPTS_LIMIT,
    delete_verification_code,
    get_verification_code,
    store_verification_code,
)
from api.core import rate_limit
from api.core.config import settings
from api.core.email import EmailSendError, get_email_sender
from api.core.redis import redis_client
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


async def test_verify_email_unknown_user_returns_400_same_as_wrong_code(
    db_client: httpx.AsyncClient,
) -> None:
    """email-goal-prompt.md E-12 성공기준 7-b: 미등록 이메일도 계정 존재를 새지 않도록
    오답 코드와 완전히 같은 400을 낸다."""
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)

    wrong_code_resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
    )
    unknown_user_resp = await db_client.post(
        "/auth/verify-email",
        json={"email": f"nobody-{uuid.uuid4()}@example.com", "code": "000000"},
    )

    assert wrong_code_resp.status_code == unknown_user_resp.status_code == 400
    assert wrong_code_resp.json() == unknown_user_resp.json()


async def test_verify_email_three_failure_cases_increment_attempts_identically(
    db_client: httpx.AsyncClient,
) -> None:
    """적대적 리뷰: '유저 없음'/'코드 없음'/'코드 오답'이 같은 400 응답을 내는 것만으론
    부족하다 — Redis 왕복 횟수가 다르면 응답 지연으로 계정 존재 여부가 샌다. 세 경우 모두
    오답 카운터가 1로 오르는지 직접 읽어 '같은 연산을 한다'는 것까지 확인한다."""
    unknown_email = f"nobody-{uuid.uuid4()}@example.com"

    no_code_payload = _signup_payload()
    await db_client.post("/auth/signup", json=no_code_payload)
    await delete_verification_code(str(no_code_payload["email"]))

    wrong_code_payload = _signup_payload()
    await db_client.post("/auth/signup", json=wrong_code_payload)

    for email in (unknown_email, no_code_payload["email"], wrong_code_payload["email"]):
        resp = await db_client.post("/auth/verify-email", json={"email": email, "code": "000000"})
        assert resp.status_code == 400
        assert await redis_client.get(f"email_verification_attempts:{email}") == "1"


async def test_verify_email_invalidates_code_after_max_wrong_attempts(
    db_client: httpx.AsyncClient,
) -> None:
    """email-goal-prompt.md E-7 성공기준 7: 오답 5회 → 코드 무효화 → 올바른 코드도 실패,
    재전송 후에는 통과한다."""
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None
    correct_code = stored["code"]

    for _ in range(VERIFICATION_ATTEMPTS_LIMIT):
        resp = await db_client.post(
            "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
        )
        assert resp.status_code == 400

    # 코드가 무효화되어 올바른 코드를 넣어도 실패한다.
    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": correct_code}
    )
    assert resp.status_code == 400

    # 재전송 버튼을 누르면 복구된다 — 별도 잠금 상태가 아니다.
    resend_resp = await db_client.post(
        "/auth/resend-verification-code", json={"email": payload["email"]}
    )
    assert resend_resp.status_code == 204

    new_code = await get_verification_code(str(payload["email"]))
    assert new_code is not None
    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": new_code["code"]}
    )
    assert resp.status_code == 200


async def test_verify_email_succeeds_after_limit_minus_one_wrong_attempts(
    db_client: httpx.AsyncClient,
) -> None:
    """상한 테스트(위)가 LIMIT회에서 무효화되는 것만 보면, `attempts >= LIMIT - 1`로 하나 밀린
    오프바이원 회귀를 못 잡는다. LIMIT-1(=4)번 오답 뒤에는 코드가 아직 살아있어 올바른 코드가
    통과해야 한다."""
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None
    correct_code = stored["code"]

    for _ in range(VERIFICATION_ATTEMPTS_LIMIT - 1):
        resp = await db_client.post(
            "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
        )
        assert resp.status_code == 400

    resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": correct_code}
    )
    assert resp.status_code == 200


async def test_verify_email_success_clears_attempts_counter(db_client: httpx.AsyncClient) -> None:
    """email-goal-prompt.md E-7: 성공하면 오답 카운터가 지워진다."""
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    wrong_resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": "000000"}
    )
    assert wrong_resp.status_code == 400

    ok_resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert ok_resp.status_code == 200

    assert await redis_client.get(f"email_verification_attempts:{payload['email']}") is None


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


async def test_resend_unknown_user_returns_204(db_client: httpx.AsyncClient) -> None:
    """email-goal-prompt.md E-12 성공기준 7-b: 미등록 이메일도 계정 존재를 새지 않도록
    204를 낸다(발송은 하지 않는다)."""
    resp = await db_client.post(
        "/auth/resend-verification-code", json={"email": f"nobody-{uuid.uuid4()}@example.com"}
    )
    assert resp.status_code == 204


async def test_resend_responses_match_for_registered_and_unregistered_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """email-goal-prompt.md E-12a: 60초 쿨다운이 계정 존재 여부를 새지 않으려면 코드가
    등록 여부와 무관하게 항상 저장돼야 한다 — 연속 2회 호출의 응답이 등록/미등록에서
    같은지 직접 비교한다."""
    registered_email = f"registered-{uuid.uuid4()}@example.com"
    db_session.add(_make_user(email=registered_email))
    await db_session.flush()
    unregistered_email = f"unregistered-{uuid.uuid4()}@example.com"

    registered_first = await db_client.post(
        "/auth/resend-verification-code", json={"email": registered_email}
    )
    unregistered_first = await db_client.post(
        "/auth/resend-verification-code", json={"email": unregistered_email}
    )
    assert registered_first.status_code == unregistered_first.status_code == 204

    registered_second = await db_client.post(
        "/auth/resend-verification-code", json={"email": registered_email}
    )
    unregistered_second = await db_client.post(
        "/auth/resend-verification-code", json={"email": unregistered_email}
    )
    assert registered_second.status_code == unregistered_second.status_code == 429
    assert registered_second.json() == unregistered_second.json()
    # 2회 호출로는 RESEND_VERIFICATION_EMAIL_LIMIT(5)에 닿을 수 없다 — 이 429가 시간당 상한이
    # 아니라 60초 쿨다운에서 온 것임을 명시해 둔다(S3에서 겪은 "다른 이유로 429" 오판 방지).
    assert registered_second.json()["detail"]["retryAfterSeconds"] == 60


async def test_signup_rate_limited_by_ip_returns_429(db_client: httpx.AsyncClient) -> None:
    """email-goal-prompt.md E-6: IP당 시간당 10회. httpx.ASGITransport의 client 기본값이
    모든 요청에서 동일해(`('127.0.0.1', 123)`) 서로 다른 이메일로도 IP 카운터는 공유된다."""
    for _ in range(rate_limit.SIGNUP_IP_LIMIT):
        resp = await db_client.post("/auth/signup", json=_signup_payload())
        assert resp.status_code == 201

    resp = await db_client.post("/auth/signup", json=_signup_payload())
    assert resp.status_code == 429
    assert resp.json()["detail"]["retryAfterSeconds"] > 0


async def test_signup_rate_limited_by_email_returns_429(db_client: httpx.AsyncClient) -> None:
    """email-goal-prompt.md E-6: 이메일당 시간당 5회. 같은 미인증 이메일로 반복 signup은
    E-5의 덮어쓰기 경로를 타 매번 201이므로, 상한을 이메일 카운터만으로 트리거할 수 있다."""
    payload = _signup_payload()
    for _ in range(rate_limit.SIGNUP_EMAIL_LIMIT):
        resp = await db_client.post("/auth/signup", json=payload)
        assert resp.status_code == 201

    resp = await db_client.post("/auth/signup", json=payload)
    assert resp.status_code == 429
    assert resp.json()["detail"]["retryAfterSeconds"] > 0


async def test_resend_rate_limited_by_email_returns_429(db_client: httpx.AsyncClient) -> None:
    """email-goal-prompt.md E-6: resend의 이메일당 시간당 5회는 기존 60초 쿨다운과 별개 규칙이다.
    매 반복 전에 sent_at을 과거로 되돌려 쿨다운을 우회하고, 시간당 상한만으로 6번째를 막는다."""
    payload = _signup_payload()
    await db_client.post("/auth/signup", json=payload)
    past = datetime.now(UTC) - timedelta(seconds=61)

    for _ in range(rate_limit.RESEND_VERIFICATION_EMAIL_LIMIT):
        await store_verification_code(str(payload["email"]), "000000", past)
        resp = await db_client.post(
            "/auth/resend-verification-code", json={"email": payload["email"]}
        )
        assert resp.status_code == 204

    # 쿨다운도 다시 우회해둔다 — 안 그러면 이 마지막 호출은 방금 6번째 성공 호출이 새로 찍은
    # sent_at 때문에 60초 쿨다운으로도 429가 나서, 어느 규칙이 막았는지 테스트가 구분하지 못한다.
    await store_verification_code(str(payload["email"]), "000000", past)
    resp = await db_client.post(
        "/auth/resend-verification-code", json={"email": payload["email"]}
    )
    assert resp.status_code == 429
    assert resp.json()["detail"]["retryAfterSeconds"] > 0


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
