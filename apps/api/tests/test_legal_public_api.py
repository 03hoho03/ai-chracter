import uuid
from datetime import datetime, timezone, UTC

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code
from api.db.models import LegalDocument, User


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


async def _signup_and_login(db_client: httpx.AsyncClient, **overrides: object) -> dict[str, object]:
    payload = _signup_payload(**overrides)
    await db_client.post("/auth/signup", json=payload)
    stored = await get_verification_code(str(payload["email"]))
    assert stored is not None

    verify_resp = await db_client.post(
        "/auth/verify-email", json={"email": payload["email"], "code": stored["code"]}
    )
    assert verify_resp.status_code == 200

    login_resp = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login_resp.status_code == 204
    return payload


async def _make_published(
    db_session: AsyncSession,
    *,
    kind: str = "terms",
    version: str = "2024-01-01",
    body_markdown: str = "게시된 내용",
    requires_reconsent: bool = False,
    published_at: datetime | None = None,
) -> LegalDocument:
    document = LegalDocument(
        kind=kind,
        version=version,
        body_markdown=body_markdown,
        status="published",
        requires_reconsent=requires_reconsent,
        published_at=published_at or datetime.now(UTC),
    )
    db_session.add(document)
    await db_session.flush()
    return document


# ---- 공개 조회 ----------------------------------------------------------------


async def test_get_public_document_returns_latest_published_without_auth(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _make_published(db_session, kind="terms", version="2024-01-01", body_markdown="옛 버전")
    await _make_published(db_session, kind="terms", version="2024-06-01", body_markdown="최신 버전")
    await db_session.commit()

    resp = await db_client.get("/legal/terms")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "terms"
    assert body["version"] == "2024-06-01"
    assert body["bodyMarkdown"] == "최신 버전"


async def test_get_public_document_returns_404_when_no_published_document(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # migration c49014ae5b62 seeds a published privacy document — clear it so this
    # test still exercises the "no published document" case regardless of seed data.
    await db_session.execute(delete(LegalDocument).where(LegalDocument.kind == "privacy"))
    await db_session.commit()

    resp = await db_client.get("/legal/privacy")
    assert resp.status_code == 404


async def test_get_public_document_rejects_unknown_kind(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/legal/unknown-kind")
    assert resp.status_code == 422


# ---- /me 재동의 판정 -----------------------------------------------------------


async def test_me_reconsent_not_required_when_no_published_document(
    db_client: httpx.AsyncClient,
) -> None:
    await _signup_and_login(db_client)

    resp = await db_client.get("/me")
    assert resp.status_code == 200
    assert resp.json()["termsReconsentRequired"] is False
    assert resp.json()["privacyReconsentRequired"] is False


async def test_me_reconsent_not_required_when_published_does_not_require_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오타 수정처럼 `requires_reconsent=false`로 게시된 새 버전은 모달을 띄우지
    않는다 — required_version 자체를 올리지 않기 때문이다."""
    await _signup_and_login(db_client)
    await _make_published(
        db_session, kind="terms", version="2099-01-01", requires_reconsent=False
    )
    await db_session.commit()

    resp = await db_client.get("/me")
    assert resp.status_code == 200
    assert resp.json()["termsReconsentRequired"] is False


async def test_me_reconsent_required_when_user_version_is_null(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user.terms_version = None
    await db_session.commit()

    resp = await db_client.get("/me")
    assert resp.status_code == 200
    assert resp.json()["termsReconsentRequired"] is True


async def test_me_reconsent_required_when_user_version_is_lower(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user.terms_version = "2020-01-01"
    await db_session.commit()

    resp = await db_client.get("/me")
    assert resp.status_code == 200
    assert resp.json()["termsReconsentRequired"] is True


async def test_me_reconsent_not_required_when_user_version_equals_required(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user.terms_version = "2099-01-01"
    await db_session.commit()

    resp = await db_client.get("/me")
    assert resp.status_code == 200
    assert resp.json()["termsReconsentRequired"] is False


# ---- 동의 기록 ----------------------------------------------------------------


async def test_consent_marks_me_reconsent_required_false(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    payload = await _signup_and_login(db_client)
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    user.terms_version = None
    await db_session.commit()

    before = await db_client.get("/me")
    assert before.json()["termsReconsentRequired"] is True

    consent_resp = await db_client.post(
        "/legal/consent", json={"kind": "terms", "version": "2099-01-01"}
    )
    assert consent_resp.status_code == 204

    after = await db_client.get("/me")
    assert after.json()["termsReconsentRequired"] is False

    await db_session.refresh(user)
    assert user.terms_version == "2099-01-01"


async def test_consent_ignores_client_supplied_version_and_records_current_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """요청 바디의 `version`은 신뢰하지 않는다 — 서버가 다시 조회한 현재 최신
    게시본의 version만 기록한다."""
    payload = await _signup_and_login(db_client)
    await _make_published(db_session, kind="terms", version="2024-01-01")
    await db_session.commit()

    resp = await db_client.post(
        "/legal/consent", json={"kind": "terms", "version": "9999-99-99"}
    )
    assert resp.status_code == 204

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.terms_version == "2024-01-01"


async def test_consent_returns_404_when_no_published_document(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _signup_and_login(db_client)
    # migration c49014ae5b62 seeds a published privacy document — clear it so this
    # test still exercises the "no published document" case regardless of seed data.
    await db_session.execute(delete(LegalDocument).where(LegalDocument.kind == "privacy"))
    await db_session.commit()

    resp = await db_client.post(
        "/legal/consent", json={"kind": "privacy", "version": "2024-01-01"}
    )
    assert resp.status_code == 404


async def test_consent_requires_user_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/legal/consent", json={"kind": "terms", "version": "2024-01-01"}
    )
    assert resp.status_code == 401


# ---- 신규 가입 시 버전 기록 -----------------------------------------------------


async def test_signup_records_current_published_versions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _make_published(db_session, kind="terms", version="2024-01-01")
    await _make_published(db_session, kind="privacy", version="2024-02-01")
    await db_session.commit()

    payload = _signup_payload()
    resp = await db_client.post("/auth/signup", json=payload)
    assert resp.status_code == 201

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.terms_version == "2024-01-01"
    assert user.privacy_version == "2024-02-01"


async def test_signup_records_null_version_when_no_published_document(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # migration c49014ae5b62 seeds published terms/privacy documents — clear them so
    # this test still exercises the "no published document" case regardless of seed data.
    await db_session.execute(delete(LegalDocument).where(LegalDocument.status == "published"))
    await db_session.commit()

    payload = _signup_payload()
    resp = await db_client.post("/auth/signup", json=payload)
    assert resp.status_code == 201

    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    assert user.terms_version is None
    assert user.privacy_version is None
