import uuid
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.verification import get_verification_code
from api.db.models import LegalDocument, User, UserLegalConsent
from api.legal import consents, documents
from api.legal.schemas import LegalConsentUnit
from factories import _make_published


def _signup_payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "password123",
        "nickname": "테스터",
        "birthDate": "2000-01-01",
        "termsAgreed": True,
        "privacyAgreed": True,
        "transferAgreed": True,
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


@pytest.mark.parametrize("kind", ["operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"])
async def test_get_public_document_serves_policy_kinds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, kind: str
) -> None:
    """운영정책·청소년 보호정책·환불정책·크리에이터 정산 정책도 약관과 같은 공개 조회 경로로 최신 게시본을 낸다."""
    await _make_published(db_session, kind=kind, version="2024-06-01", body_markdown="정책 본문")
    await db_session.commit()

    resp = await db_client.get(f"/legal/{kind}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == kind
    assert body["version"] == "2024-06-01"
    assert body["bodyMarkdown"] == "정책 본문"


@pytest.mark.parametrize("kind", ["operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"])
async def test_get_public_document_returns_404_for_policy_kind_without_published(
    db_client: httpx.AsyncClient, kind: str
) -> None:
    """마이그레이션 시드는 약관·처리방침만 넣는다 — 게시 전의 정책 문서는 404 이고 웹은
    이것을 "아직 게시된 문서가 없어요"로 보여 준다."""
    resp = await db_client.get(f"/legal/{kind}")
    assert resp.status_code == 404


async def test_get_public_document_rejects_unknown_kind(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/legal/operation")
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
    # migration c49014ae5b62 seeds a published privacy document — clear it so this
    # test still exercises the "no published document" case regardless of seed data.
    # 가입보다 먼저 지운다 — 가입이 남기는 동의 이력 행이 그 게시본을 가리키면 지울 수 없다.
    await db_session.execute(delete(LegalDocument).where(LegalDocument.kind == "privacy"))
    await db_session.commit()
    await _signup_and_login(db_client)

    resp = await db_client.post(
        "/legal/consent", json={"kind": "privacy", "version": "2024-01-01"}
    )
    assert resp.status_code == 404


async def test_consent_requires_user_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.post(
        "/legal/consent", json={"kind": "terms", "version": "2024-01-01"}
    )
    assert resp.status_code == 401


async def test_consent_terms_updates_version_and_agreed_at(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재동의는 버전뿐 아니라 동의 시각도 갱신한다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    before_version = user.terms_version
    before_agreed_at = user.terms_agreed_at

    await _make_published(db_session, kind="terms", version="2099-01-01")
    await db_session.commit()

    resp = await db_client.post(
        "/legal/consent", json={"kind": "terms", "version": "2099-01-01"}
    )
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.terms_version == "2099-01-01"
    assert user.terms_version != before_version
    assert user.terms_agreed_at != before_agreed_at


async def test_consent_privacy_updates_privacy_and_transfer_pair(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """처리방침 재동의는 privacy·transfer 두 쌍을
    함께 갱신하고, transfer_version은 처리방침 게시본의 버전을 그대로 쓴다. 같은 시점에
    더 높은 버전의 약관(terms)을 함께 게시해, transfer_version이 엉뚱하게 terms 값을
    집어오지 않는지도 같이 확인한다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    before_privacy_version = user.privacy_version
    before_privacy_agreed_at = user.privacy_agreed_at
    before_transfer_version = user.transfer_version
    before_transfer_agreed_at = user.transfer_agreed_at

    await _make_published(db_session, kind="terms", version="2099-09-09")
    await _make_published(db_session, kind="privacy", version="2099-02-01")
    await db_session.commit()

    resp = await db_client.post(
        "/legal/consent", json={"kind": "privacy", "version": "2099-02-01"}
    )
    assert resp.status_code == 204

    await db_session.refresh(user)
    assert user.privacy_version == "2099-02-01"
    assert user.privacy_version != before_privacy_version
    assert user.privacy_agreed_at != before_privacy_agreed_at
    assert user.transfer_version == "2099-02-01"
    assert user.transfer_version != before_transfer_version
    assert user.transfer_agreed_at != before_transfer_agreed_at


@pytest.mark.parametrize("kind", ["operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"])
async def test_consent_rejects_policy_kind_and_leaves_consent_versions_untouched(
    db_client: httpx.AsyncClient, db_session: AsyncSession, kind: str
) -> None:
    """동의를 기록하지 않는 문서로 동의를 보내면 422 이고 어떤 동의 버전도 바뀌지 않는다.
    이 요청이 처리방침 동의로 흘러들면, 처리방침 요구 버전보다 늦은 날짜로 게시된 정책
    문서 하나로 처리방침·국외이전 재동의를 건너뛸 수 있게 된다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    before = (
        user.terms_version,
        user.terms_agreed_at,
        user.privacy_version,
        user.privacy_agreed_at,
        user.transfer_version,
        user.transfer_agreed_at,
    )
    await _make_published(db_session, kind="privacy", version="2099-01-01", requires_reconsent=True)
    await _make_published(db_session, kind=kind, version="2099-12-31")
    await db_session.commit()

    resp = await db_client.post("/legal/consent", json={"kind": kind, "version": "2099-12-31"})
    assert resp.status_code == 422

    await db_session.refresh(user)
    assert (
        user.terms_version,
        user.terms_agreed_at,
        user.privacy_version,
        user.privacy_agreed_at,
        user.transfer_version,
        user.transfer_agreed_at,
    ) == before
    me = await db_client.get("/me")
    assert me.json()["privacyReconsentRequired"] is True


@pytest.mark.parametrize("kind", ["operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"])
async def test_me_reconsent_flags_ignore_policy_kind_marked_reconsent(
    db_client: httpx.AsyncClient, db_session: AsyncSession, kind: str
) -> None:
    """재동의 판정은 약관·처리방침의 동의 단위만 본다 — 정책 문서 행에 재동의 범위가
    (어드민 검증을 거치지 않고) 들어가 있어도 `/me` 의 두 플래그는 그대로다."""
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    await _make_published(
        db_session, kind=kind, version="2099-12-31", reconsent_scopes=["terms", "collection", "transfer"]
    )
    await db_session.commit()

    resp = await db_client.get("/me")
    assert resp.status_code == 200
    assert resp.json()["termsReconsentRequired"] is False
    assert resp.json()["privacyReconsentRequired"] is False


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
    # 국외이전 동의는 처리방침 버전에 묶인다 —
    # terms가 아니라 privacy의 게시본 버전과 같아야 한다.
    assert user.transfer_agreed_at is not None
    assert user.transfer_version == "2024-02-01"


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


# ---- 시행 예정 판 --------------------------------------------------------------


async def test_public_document_serves_current_edition_and_announces_the_scheduled_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시행 예정 판은 시행 전에는 `upcoming` 으로만 알리고 현행판 자리에 오지 않는다. 시계가 시행 시각을 넘으면 그 판이
    현행판이 된다. 깨지는 시나리오: 공개 조회가 게시 시각만 보아 예약하자마자 효력 없는 약관을 현행이라고 보여 준다."""
    effective_at = datetime.now(UTC) + timedelta(days=30)
    await _make_published(db_session, kind="terms", version="2026-11-17", body_markdown="예정 본문", effective_at=effective_at)
    await db_session.commit()

    before = (await db_client.get("/legal/terms")).json()
    assert before["version"] == "2026-09-06"
    assert before["effectiveAt"] == before["publishedAt"]
    assert before["upcoming"]["version"] == "2026-11-17"
    assert datetime.fromisoformat(before["upcoming"]["effectiveAt"]) == effective_at
    upcoming = await db_client.get("/legal/terms/upcoming")
    assert upcoming.status_code == 200
    assert (upcoming.json()["version"], upcoming.json()["bodyMarkdown"]) == ("2026-11-17", "예정 본문")

    monkeypatch.setattr(documents, "utcnow", lambda: effective_at + timedelta(minutes=1))
    after = (await db_client.get("/legal/terms")).json()
    assert (after["version"], after["bodyMarkdown"], after["upcoming"]) == ("2026-11-17", "예정 본문", None)
    assert datetime.fromisoformat(after["effectiveAt"]) == effective_at
    assert (await db_client.get("/legal/terms/upcoming")).status_code == 404


async def test_scheduled_reconsent_edition_reaches_me_and_signup_only_after_it_takes_effect(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시행 예정인 재동의 판은 시행 전에는 `/me` 의 재동의 플래그도, 가입이 기록하는 동의 버전도 바꾸지 않는다. 시계가
    시행 시각을 넘으면 기존 회원은 재동의 대상이 되고 새 가입은 그 판 버전을 기록한다. 깨지는 시나리오: 가입이 아직
    효력 없는 판에 동의한 것으로 기록되거나, 기존 회원이 시행 전부터 재동의 모달에 갇힌다."""
    effective_at = datetime.now(UTC) + timedelta(days=30)
    await _make_published(
        db_session, kind="privacy", version="2026-11-17", requires_reconsent=True, effective_at=effective_at
    )
    await db_session.commit()
    early = await _signup_and_login(db_client)
    early_user = await db_session.scalar(select(User).where(User.email == early["email"]))
    assert early_user is not None
    assert (early_user.privacy_version, early_user.transfer_version) == ("2026-09-06", "2026-09-06")
    assert (await db_client.get("/me")).json()["privacyReconsentRequired"] is False

    monkeypatch.setattr(documents, "utcnow", lambda: effective_at + timedelta(minutes=1))
    assert (await db_client.get("/me")).json()["privacyReconsentRequired"] is True
    late = _signup_payload()
    assert (await db_client.post("/auth/signup", json=late)).status_code == 201
    late_user = await db_session.scalar(select(User).where(User.email == late["email"]))
    assert late_user is not None
    assert (late_user.privacy_version, late_user.transfer_version) == ("2026-11-17", "2026-11-17")


async def test_consent_records_current_edition_not_the_scheduled_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재동의 기록도 현행판 버전이다. 깨지는 시나리오: 시행 전 판에 동의한 것으로 기록돼, 그 판이 시행된 뒤 재동의를
    요구받지 않는다(시행 전 판은 회원이 동의할 대상이 아니다)."""
    payload = await _signup_and_login(db_client)
    await _make_published(
        db_session, kind="terms", version="2026-11-17", effective_at=datetime.now(UTC) + timedelta(days=30)
    )
    await db_session.commit()

    resp = await db_client.post("/legal/consent", json={"kind": "terms", "version": "2026-11-17"})

    assert resp.status_code == 204
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    await db_session.refresh(user)
    assert user.terms_version == "2026-09-06"


# ---- 동의 단위 재동의 -----------------------------------------------------------


async def _consent_history(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, str | None]]:
    """회원의 동의 이력을 (동의 단위, 판 버전)으로. 동의 단위 이름순이다."""
    rows = await db_session.execute(
        select(UserLegalConsent.consent, LegalDocument.version)
        .join(LegalDocument, LegalDocument.id == UserLegalConsent.legal_document_id)
        .where(UserLegalConsent.user_id == user_id)
        .order_by(UserLegalConsent.consent, LegalDocument.version)
    )
    return [(consent, version) for consent, version in rows.all()]


async def _signed_up_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[dict[str, object], User]:
    payload = await _signup_and_login(db_client)
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    return payload, user


_GATED_BODY = {"contentType": "character"}
_UNIT_FLAGS = (
    "termsReconsentRequired",
    "privacyReconsentRequired",
    "collectionReconsentRequired",
    "transferReconsentRequired",
)


async def test_transfer_only_privacy_edition_blocks_only_members_behind_on_transfer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """처리방침 판이 국외이전 동의만 다시 받으면, 국외이전 동의가 그 판보다 옛 회원만 막히고 수집·이용 동의만 옛 회원은
    막히지 않는다. 깨지는 시나리오: 판정이 동의 단위를 보지 않고 문서 단위로 걸어, 국외이전에 이미 동의한 회원까지 모달에
    갇히거나 국외이전에 동의하지 않은 회원을 놓친다."""
    await _make_published(db_session, kind="privacy", version="2099-01-01")
    await _make_published(db_session, kind="privacy", version="2099-02-01", reconsent_scopes=["transfer"])
    await db_session.commit()
    _, user = await _signed_up_user(db_client, db_session)

    user.privacy_version, user.transfer_version = "2026-09-06", "2099-02-01"
    await db_session.commit()
    me = (await db_client.get("/me")).json()
    assert [me[flag] for flag in _UNIT_FLAGS] == [False, False, False, False]
    open_resp = await db_client.post("/chat-rooms", json={**_GATED_BODY, "contentId": str(uuid.uuid4())})
    assert open_resp.status_code != 403

    user.privacy_version, user.transfer_version = "2099-02-01", "2099-01-01"
    await db_session.commit()
    me = (await db_client.get("/me")).json()
    assert [me[flag] for flag in _UNIT_FLAGS] == [False, True, False, True]
    blocked = await db_client.post("/chat-rooms", json={**_GATED_BODY, "contentId": str(uuid.uuid4())})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == {
        "code": "LEGAL_RECONSENT_REQUIRED",
        "kinds": ["privacy"],
        "consents": ["transfer"],
    }


async def test_consent_with_units_records_each_unit_and_appends_history(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """새 바디는 고른 동의 단위만 기록한다 — 국외이전 하나만 보내면 수집·이용 버전은 그대로다. 단위마다 이력 행이 하나씩
    늘고 가입 때 행은 남는다. 깨지는 시나리오: 국외이전 동의가 수집·이용 동의까지 새 판으로 덮어써 그 회원이 수집·이용
    재동의를 건너뛴다."""
    _, user = await _signed_up_user(db_client, db_session)
    await _make_published(
        db_session, kind="privacy", version="2099-02-01", reconsent_scopes=["transfer"], change_notice_markdown="안내"
    )
    await db_session.commit()

    resp = await db_client.post("/legal/consent", json={"consents": ["transfer"]})

    assert resp.status_code == 204
    await db_session.refresh(user)
    assert (user.privacy_version, user.transfer_version) == ("2026-09-06", "2099-02-01")
    assert await _consent_history(db_session, user.id) == [
        ("collection", "2026-09-06"),
        ("terms", "2026-09-06"),
        ("transfer", "2026-09-06"),
        ("transfer", "2099-02-01"),
    ]


async def test_consent_with_old_privacy_body_records_collection_and_transfer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이전 웹의 `{kind: "privacy"}` 는 수집·이용과 국외이전 둘 다에 동의한 것이다(이전 모달은 두 체크박스를 다 받고
    처리방침 한 번으로 보낸다). 깨지는 시나리오: 새 웹 배포 전에 이전 웹으로 동의한 회원의 국외이전 동의가 빠져 모달이 다시
    뜬다."""
    _, user = await _signed_up_user(db_client, db_session)
    await _make_published(db_session, kind="privacy", version="2099-02-01")
    await db_session.commit()

    resp = await db_client.post("/legal/consent", json={"kind": "privacy", "version": "1999-01-01"})

    assert resp.status_code == 204
    history = await _consent_history(db_session, user.id)
    assert [row for row in history if row[1] == "2099-02-01"] == [
        ("collection", "2099-02-01"),
        ("transfer", "2099-02-01"),
    ]


async def test_consent_without_units_or_kind_is_422(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _signed_up_user(db_client, db_session)
    assert (await db_client.post("/legal/consent", json={})).status_code == 422
    assert (await db_client.post("/legal/consent", json={"consents": []})).status_code == 422


async def test_consent_rechecks_withdrawal_after_locking_the_member(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인증을 통과한 뒤 기록하기 전에 탈퇴가 끼어들면 401 이고 이력 행을 남기지 않는다. 깨지는 시나리오: 회원 행을 잠그고
    탈퇴 여부를 다시 보지 않으면, 탈퇴 커밋을 기다렸다가 그 뒤에 동의 이력을 넣어 탈퇴한 회원의 기록이 남는다."""
    _, user = await _signed_up_user(db_client, db_session)
    user_id = user.id
    real = consents.current_consent_documents

    async def withdraw_meanwhile(
        db: AsyncSession, units: list[LegalConsentUnit], *, now: datetime
    ) -> dict[LegalConsentUnit, LegalDocument | None]:
        found = await real(db, units, now=now)
        # 탈퇴 커밋이 이 요청의 인증 확인과 기록 사이에 끝난 상황. 같은 커넥션이라 바로 보인다.
        await db.execute(update(User).where(User.id == user_id).values(deleted_at=datetime.now(UTC)))
        return found

    monkeypatch.setattr(consents, "current_consent_documents", withdraw_meanwhile)
    before = await _consent_history(db_session, user_id)

    resp = await db_client.post("/legal/consent", json={"consents": ["terms"]})

    assert resp.status_code == 401
    assert await _consent_history(db_session, user_id) == before


async def test_signup_appends_three_consent_rows_and_replaces_them_on_abandoned_signup_reuse(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """가입은 동의 단위 셋을 한 행씩 남긴다. 인증하지 않고 방치된 가입 행을 같은 이메일의 새 가입이 재사용하면 옛 이력은
    지우고 새 가입의 세 행만 남긴다. 깨지는 시나리오: 방치된 가입을 남이 해 둔 경우 그 사람의 동의가 새 가입자의 동의로
    남는다."""
    payload = _signup_payload()
    assert (await db_client.post("/auth/signup", json=payload)).status_code == 201
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    expected = [("collection", "2026-09-06"), ("terms", "2026-09-06"), ("transfer", "2026-09-06")]
    assert await _consent_history(db_session, user.id) == expected

    assert (await db_client.post("/auth/signup", json=payload)).status_code == 201
    assert await _consent_history(db_session, user.id) == expected


async def test_withdrawal_erases_consent_history_but_keeps_user_consent_columns(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """탈퇴하면 동의 이력은 파기하고 `users` 의 동의 버전·시각 칸은 남긴다. 깨지는 시나리오: 이력을 파기 경로에 넣지 않아
    탈퇴 뒤에도 그 회원이 언제 어느 판에 동의했는지가 남는다."""
    payload, user = await _signed_up_user(db_client, db_session)
    user_id = user.id
    assert (await db_client.post("/legal/consent", json={"consents": ["terms"]})).status_code == 204
    assert len(await _consent_history(db_session, user_id)) == 4

    resp = await db_client.request("DELETE", "/me", json={"currentPassword": payload["password"]})

    assert resp.status_code == 204
    assert await _consent_history(db_session, user_id) == []
    await db_session.refresh(user)
    assert user.deleted_at is not None
    assert (user.terms_version, user.privacy_version, user.transfer_version) == ("2026-09-06",) * 3
    assert user.terms_agreed_at is not None


# ---- 변경 안내 ----------------------------------------------------------------


async def test_public_document_carries_change_notice_for_current_and_upcoming(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _make_published(db_session, kind="terms", version="2099-01-01", change_notice_markdown="현행 안내")
    await _make_published(
        db_session,
        kind="terms",
        version="2099-02-01",
        change_notice_markdown="예정 안내",
        effective_at=datetime.now(UTC) + timedelta(days=30),
    )
    await db_session.commit()

    body = (await db_client.get("/legal/terms")).json()
    assert (body["version"], body["changeNotice"]) == ("2099-01-01", "현행 안내")
    assert body["upcoming"]["changeNotice"] == "예정 안내"
    assert (await db_client.get("/legal/terms/upcoming")).json()["changeNotice"] == "예정 안내"


async def test_changes_lists_editions_after_since_newest_first_without_scheduled_or_withdrawn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """누적 안내는 `since` 판보다 뒤에 시행된 판을 최신 판부터 준다. 판의 앞뒤는 시행 순서다(버전 문자열이 아니다).
    시행 예정 판과 철회본은 들지 않는다. `since` 가 없거나 시행된 판에 없으면 전부다. 깨지는 시나리오: 재동의 화면이 회원이
    이미 동의한 판의 안내를 다시 보이거나, 효력 없는 판의 안내를 보여 준다."""
    await db_session.execute(delete(LegalDocument).where(LegalDocument.kind == "privacy"))
    base = datetime.now(UTC) - timedelta(days=10)
    await _make_published(
        db_session, kind="privacy", version="2026-10-10", published_at=base, change_notice_markdown="가"
    )
    # 버전 문자열은 앞이지만 늦게 시행된 판(운영 처리방침에 실제로 있는 순서다).
    await _make_published(
        db_session,
        kind="privacy",
        version="2026-10-09",
        published_at=base + timedelta(days=1),
        change_notice_markdown="나",
    )
    await _make_published(
        db_session,
        kind="privacy",
        version="2026-10-12",
        published_at=base + timedelta(days=2),
        reconsent_scopes=["collection"],
        change_notice_markdown="다",
    )
    withdrawn = await _make_published(
        db_session,
        kind="privacy",
        version="2026-10-13",
        published_at=base + timedelta(days=3),
        change_notice_markdown="철회",
    )
    withdrawn.status = "withdrawn"
    await _make_published(
        db_session, kind="privacy", version="2099-01-01", effective_at=datetime.now(UTC) + timedelta(days=30)
    )
    await db_session.commit()

    since = (await db_client.get("/legal/privacy/changes", params={"since": "2026-10-10"})).json()["items"]
    assert [(item["version"], item["changeNotice"], item["reconsentScopes"]) for item in since] == [
        ("2026-10-12", "다", ["collection"]),
        ("2026-10-09", "나", []),
    ]
    assert (await db_client.get("/legal/privacy/changes", params={"since": "2026-10-12"})).json()["items"] == []
    every = ["2026-10-12", "2026-10-09", "2026-10-10"]
    for params in ({}, {"since": "2020-01-01"}, {"since": "2099-01-01"}):
        items = (await db_client.get("/legal/privacy/changes", params=params)).json()["items"]
        assert [item["version"] for item in items] == every
