from datetime import datetime, timedelta, timezone, UTC

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import legal as admin_legal
from api.db.models import AdminActionLog, LegalDocument
from api.legal.schemas import LegalDocumentKind
from factories import _create_admin, _login_as, _login_as_admin, _make_published, _make_user


async def _login_new_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


async def _make_draft(
    db_session: AsyncSession, *, kind: str = "terms", body_markdown: str = "초안 내용"
) -> LegalDocument:
    document = LegalDocument(kind=kind, body_markdown=body_markdown, status="draft")
    db_session.add(document)
    await db_session.flush()
    return document


# ---- 인증 -------------------------------------------------------------------


async def _assert_requires_admin_session(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    json: dict[str, object] | None = None,
) -> None:
    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    # 세션이 아예 안 서도 admin 401은 나오므로, 먼저 "이
    # 유저로는 실제로 인증된다"를 고정해야 위 무세션 401과 구분되는 명제가 남는다(공허한 통과 방지).
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401


async def test_get_document_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(db_client, db_session, "get", "/admin/legal/terms")


async def test_upsert_draft_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(
        db_client, db_session, "put", "/admin/legal/terms/draft", json={"bodyMarkdown": "내용"}
    )


async def test_publish_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(
        db_client,
        db_session,
        "post",
        "/admin/legal/terms/publish",
        json={"version": "2024-01-01", "requiresReconsent": False},
    )


async def test_versions_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _assert_requires_admin_session(db_client, db_session, "get", "/admin/legal/terms/versions")


# ---- 조회 --------------------------------------------------------------------


async def test_get_document_with_no_draft_or_published_returns_nulls(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # migration c49014ae5b62 seeds a published terms document — clear it so this
    # test still exercises the "nothing yet" case regardless of seed data.
    await db_session.execute(sa.delete(LegalDocument).where(LegalDocument.kind == "terms"))
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/legal/terms")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "terms"
    assert body["draft"] is None
    assert body["published"] is None


async def test_get_document_returns_draft_and_published_together(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _make_draft(db_session, kind="terms", body_markdown="편집 중인 초안")
    await _make_published(
        db_session, kind="terms", version="2024-01-01", body_markdown="게시본", requires_reconsent=True
    )
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/legal/terms")
    assert resp.status_code == 200
    body = resp.json()
    assert body["draft"]["bodyMarkdown"] == "편집 중인 초안"
    assert body["published"]["version"] == "2024-01-01"
    assert body["published"]["bodyMarkdown"] == "게시본"
    assert body["published"]["requiresReconsent"] is True


async def test_get_document_published_picks_latest_by_published_at(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    await _make_published(
        db_session, kind="terms", version="2024-01-01", published_at=now - timedelta(days=10)
    )
    await _make_published(db_session, kind="terms", version="2024-06-01", published_at=now)
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/legal/terms")
    assert resp.status_code == 200
    assert resp.json()["published"]["version"] == "2024-06-01"


# ---- 초안 저장(upsert) 회귀 --------------------------------------------


async def test_draft_upsert_creates_new_draft_when_none_exists(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)

    resp = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "첫 초안"})
    assert resp.status_code == 200
    assert resp.json()["draft"]["bodyMarkdown"] == "첫 초안"

    drafts = (
        await db_session.scalars(
            sa.select(LegalDocument).where(
                LegalDocument.kind == "terms", LegalDocument.status == "draft"
            )
        )
    ).all()
    assert len(drafts) == 1


async def test_draft_upsert_updates_existing_draft_in_place(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    draft = await _make_draft(db_session, kind="terms", body_markdown="원본")
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "수정됨"})
    assert resp.status_code == 200
    assert resp.json()["draft"]["bodyMarkdown"] == "수정됨"

    drafts = (
        await db_session.scalars(
            sa.select(LegalDocument).where(
                LegalDocument.kind == "terms", LegalDocument.status == "draft"
            )
        )
    ).all()
    assert len(drafts) == 1
    assert drafts[0].id == draft.id
    assert drafts[0].body_markdown == "수정됨"


async def test_draft_upsert_does_not_change_published_document(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """핵심 회귀: 초안 저장은 게시본을 절대 바꾸지 않는다."""
    published = await _make_published(
        db_session, kind="terms", version="2024-01-01", body_markdown="원래 게시본"
    )
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "새 초안 내용"})
    assert resp.status_code == 200
    assert resp.json()["published"]["bodyMarkdown"] == "원래 게시본"

    await db_session.refresh(published)
    assert published.body_markdown == "원래 게시본"
    assert published.version == "2024-01-01"


async def test_draft_upsert_is_scoped_to_kind(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)

    terms_resp = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "약관 초안"})
    privacy_resp = await db_client.put(
        "/admin/legal/privacy/draft", json={"bodyMarkdown": "개인정보 초안"}
    )
    assert terms_resp.status_code == 200
    assert privacy_resp.status_code == 200

    terms_get = await db_client.get("/admin/legal/terms")
    privacy_get = await db_client.get("/admin/legal/privacy")
    assert terms_get.json()["draft"]["bodyMarkdown"] == "약관 초안"
    assert privacy_get.json()["draft"]["bodyMarkdown"] == "개인정보 초안"


async def test_draft_upsert_concurrent_insert_race_falls_back_to_update_not_500(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """결함 2 회귀: `_get_draft`가 None을 본 뒤 다른 요청이 먼저 초안을 커밋하면 이
    요청의 INSERT가 부분 유니크 인덱스(`ix_legal_documents_kind_draft`)에 걸린다. 실제
    동시 요청은 테스트로 재현하기 어려우니, `_get_draft`의 첫 호출만 None을 반환하도록
    감싸 그 순간을 흉내낸다(이미 다른 초안 행을 미리 커밋해 둔 채로) — 그 분기가 500이
    아니라, 경쟁에서 이긴 행을 이 요청의 내용으로 갱신하는 것(upsert의 의미)으로
    끝난다는 걸 검증한다."""
    real_get_draft = admin_legal._get_draft
    call_count = 0

    async def _get_draft_missing_once(
        db: AsyncSession, kind: LegalDocumentKind
    ) -> LegalDocument | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return await real_get_draft(db, kind)

    monkeypatch.setattr(admin_legal, "_get_draft", _get_draft_missing_once)

    # "동시에 먼저 커밋된 다른 요청의 초안" 역할 — 이 행이 있어야 우리 INSERT가 충돌한다.
    raced_in = await _make_draft(db_session, kind="terms", body_markdown="경쟁에서 먼저 커밋된 내용")
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "내 요청의 내용"})
    assert resp.status_code == 200
    assert resp.json()["draft"]["bodyMarkdown"] == "내 요청의 내용"

    drafts = (
        await db_session.scalars(
            sa.select(LegalDocument).where(
                LegalDocument.kind == "terms", LegalDocument.status == "draft"
            )
        )
    ).all()
    assert len(drafts) == 1
    assert drafts[0].id == raced_in.id
    assert drafts[0].body_markdown == "내 요청의 내용"


# ---- 게시 --------------------------------------------------------------------


async def test_publish_creates_published_row_from_draft_and_keeps_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # migration c49014ae5b62 seeds a published terms document — clear it so the count
    # assertions below reflect only what this test creates, regardless of seed data.
    await db_session.execute(
        sa.delete(LegalDocument).where(LegalDocument.kind == "terms", LegalDocument.status == "published")
    )
    draft = await _make_draft(db_session, kind="terms", body_markdown="발행할 내용")
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        "/admin/legal/terms/publish",
        json={"version": "2024-01-01", "requiresReconsent": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"]["version"] == "2024-01-01"
    assert body["published"]["bodyMarkdown"] == "발행할 내용"
    assert body["published"]["requiresReconsent"] is True
    # 게시 후에도 초안 행은 남는다(재게시가 원고를 다시 붙여넣지 않아도 되도록).
    assert body["draft"]["bodyMarkdown"] == "발행할 내용"

    published_rows = (
        await db_session.scalars(
            sa.select(LegalDocument).where(
                LegalDocument.kind == "terms", LegalDocument.status == "published"
            )
        )
    ).all()
    assert len(published_rows) == 1
    assert published_rows[0].version == "2024-01-01"
    assert published_rows[0].published_at is not None

    await db_session.refresh(draft)
    assert draft.status == "draft"
    assert draft.body_markdown == "발행할 내용"

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.action_type == "legal-publish")
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].reason_text != ""


async def test_publish_without_draft_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(
        "/admin/legal/terms/publish",
        json={"version": "2024-01-01", "requiresReconsent": False},
    )
    assert resp.status_code == 400


async def test_publish_duplicate_version_returns_409_with_korean_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # migration c49014ae5b62 seeds a published terms document — clear it so the count
    # assertion below reflects only what this test creates, regardless of seed data.
    await db_session.execute(
        sa.delete(LegalDocument).where(LegalDocument.kind == "terms", LegalDocument.status == "published")
    )
    await _make_published(db_session, kind="terms", version="2024-01-01")
    await _make_draft(db_session, kind="terms", body_markdown="같은 버전으로 다시 게시 시도")
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(
        "/admin/legal/terms/publish",
        json={"version": "2024-01-01", "requiresReconsent": False},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "이미 존재하는 버전입니다. 버전을 수정해 주세요."

    # 실패한 게시 시도가 새 published 행을 남기지 않아야 한다.
    published_rows = (
        await db_session.scalars(
            sa.select(LegalDocument).where(
                LegalDocument.kind == "terms", LegalDocument.status == "published"
            )
        )
    ).all()
    assert len(published_rows) == 1


async def test_publish_after_duplicate_conflict_can_retry_with_new_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """IntegrityError 이후 세션이 깨진 채 남지 않아야, 같은 요청 트랜잭션 안에서 다른
    버전으로 다시 게시하는 재시도가 성공한다."""
    await _make_published(db_session, kind="terms", version="2024-01-01")
    await _make_draft(db_session, kind="terms", body_markdown="내용")
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    conflict_resp = await db_client.post(
        "/admin/legal/terms/publish",
        json={"version": "2024-01-01", "requiresReconsent": False},
    )
    assert conflict_resp.status_code == 409

    retry_resp = await db_client.post(
        "/admin/legal/terms/publish",
        json={"version": "2024-02-01", "requiresReconsent": False},
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json()["published"]["version"] == "2024-02-01"


@pytest.mark.parametrize("kind", ["operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"])
async def test_policy_kind_draft_publish_and_versions_round_trip(
    db_client: httpx.AsyncClient, db_session: AsyncSession, kind: str
) -> None:
    """정책 문서도 초안 저장 → 게시 → 이력이 약관과 같은 경로로 돈다. 같은 날짜 버전을
    약관과 각각 게시해도 버전 유일성이 문서 종류별이라 충돌하지 않는다."""
    await _make_published(db_session, kind="terms", version="2026-10-06")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)

    draft_resp = await db_client.put(f"/admin/legal/{kind}/draft", json={"bodyMarkdown": "정책 초안"})
    assert draft_resp.status_code == 200
    assert draft_resp.json()["kind"] == kind
    assert draft_resp.json()["draft"]["bodyMarkdown"] == "정책 초안"
    assert draft_resp.json()["published"] is None

    publish_resp = await db_client.post(
        f"/admin/legal/{kind}/publish",
        json={"version": "2026-10-06", "requiresReconsent": False},
    )
    assert publish_resp.status_code == 200
    assert publish_resp.json()["published"]["version"] == "2026-10-06"
    assert publish_resp.json()["published"]["requiresReconsent"] is False

    versions_resp = await db_client.get(f"/admin/legal/{kind}/versions")
    assert [item["version"] for item in versions_resp.json()["items"]] == ["2026-10-06"]

    public_resp = await db_client.get(f"/legal/{kind}")
    assert public_resp.status_code == 200
    assert public_resp.json()["bodyMarkdown"] == "정책 초안"


@pytest.mark.parametrize("kind", ["operation-policy", "youth-policy", "refund-policy", "creator-payout-policy"])
async def test_publish_policy_kind_with_reconsent_returns_422_and_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, kind: str
) -> None:
    """동의를 기록하지 않는 문서에 재동의를 걸면 게이트는 무시하지만 게시 이력·감사 로그엔
    "재동의 필요"로 남아 운영자를 오도한다 — 서버가 게시 자체를 거부한다."""
    await _make_draft(db_session, kind=kind)
    await db_session.commit()
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(
        f"/admin/legal/{kind}/publish",
        json={"version": "2026-10-06", "requiresReconsent": True},
    )
    assert resp.status_code == 422

    published_count = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(LegalDocument)
        .where(LegalDocument.kind == kind, LegalDocument.status == "published")
    )
    assert published_count == 0
    log_count = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(AdminActionLog)
        .where(AdminActionLog.action_type == "legal-publish")
    )
    assert log_count == 0


# ---- 이력 --------------------------------------------------------------------


async def test_versions_lists_published_history_ordered_by_recency(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # migration c49014ae5b62 seeds a published terms document — clear it so the
    # ordering assertion below reflects only what this test creates.
    await db_session.execute(sa.delete(LegalDocument).where(LegalDocument.kind == "terms"))
    now = datetime.now(UTC)
    await _make_published(
        db_session,
        kind="terms",
        version="2024-01-01",
        published_at=now - timedelta(days=30),
        requires_reconsent=False,
    )
    await _make_published(
        db_session,
        kind="terms",
        version="2024-06-01",
        published_at=now,
        requires_reconsent=True,
    )
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/legal/terms/versions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["version"] for item in items] == ["2024-06-01", "2024-01-01"]
    assert items[0]["requiresReconsent"] is True
    assert items[1]["requiresReconsent"] is False


async def test_versions_is_scoped_to_kind(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # migration c49014ae5b62 seeds published terms/privacy documents — clear them so
    # the scoping assertion below reflects only what this test creates.
    await db_session.execute(sa.delete(LegalDocument).where(LegalDocument.status == "published"))
    await _make_published(db_session, kind="terms", version="2024-01-01")
    await _make_published(db_session, kind="privacy", version="2024-02-01")
    await db_session.commit()

    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/legal/terms/versions")
    versions = [item["version"] for item in resp.json()["items"]]
    assert versions == ["2024-01-01"]
