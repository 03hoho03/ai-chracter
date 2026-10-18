from datetime import datetime, timedelta, timezone, UTC

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import legal as admin_legal
from api.db.models import AdminActionLog, LegalDocument
from api.legal import documents
from api.legal.schemas import LegalDocumentKind
from factories import _create_admin, _login_as, _login_as_admin, _make_published, _make_user


async def _login_new_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


async def _make_draft(
    db_session: AsyncSession,
    *,
    kind: str = "terms",
    body_markdown: str = "초안 내용",
    change_notice_markdown: str | None = None,
) -> LegalDocument:
    document = LegalDocument(
        kind=kind, body_markdown=body_markdown, change_notice_markdown=change_notice_markdown, status="draft"
    )
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
    draft = await _make_draft(
        db_session, kind="terms", body_markdown="발행할 내용", change_notice_markdown="  바뀐 점  \n"
    )
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
    # 이전 화면의 `requiresReconsent` 는 그 문서의 동의 단위 전부로 읽는다. 안내는 초안에서 복제되고 앞뒤 공백을 걷는다.
    assert body["published"]["reconsentScopes"] == ["terms"]
    assert body["published"]["changeNoticeMarkdown"] == "바뀐 점"
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


# ---- 시행 예약·철회 -------------------------------------------------------------


def _schedule_body(version: str, effective_at: datetime) -> dict[str, object]:
    return {"version": version, "requiresReconsent": False, "effectiveAt": effective_at.isoformat()}


async def test_withdraw_requires_admin_session(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _assert_requires_admin_session(
        db_client, db_session, "post", "/admin/legal/terms/versions/2026-09-06/withdraw"
    )


async def test_scheduled_publish_stays_upcoming_and_a_second_schedule_is_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """미래 시행 시각으로 게시하면 현행판은 그대로이고 그 판은 예정 판이 된다. 예정 판은 kind 마다 하나라 두 번째 예약은
    409 이고 아무것도 남기지 않는다. 깨지는 시나리오: 예정 판이 둘 생기면 어느 쪽이 먼저 시행될지 운영자가 놓치고, 먼저
    예약한 판의 철회가 뒤 판을 드러낸다."""
    await _make_draft(db_session, kind="terms", body_markdown="예약 본문")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)
    effective_at = datetime.now(UTC) + timedelta(days=30)

    resp = await db_client.post("/admin/legal/terms/publish", json=_schedule_body("2026-11-17", effective_at))

    assert resp.status_code == 200
    body = resp.json()
    assert body["published"]["version"] == "2026-09-06"
    assert body["upcoming"]["version"] == "2026-11-17"
    assert datetime.fromisoformat(body["upcoming"]["effectiveAt"]) == effective_at
    versions = (await db_client.get("/admin/legal/terms/versions")).json()["items"]
    assert [(item["version"], item["state"]) for item in versions] == [
        ("2026-11-17", "scheduled"),
        ("2026-09-06", "current"),
    ]

    second = await db_client.post(
        "/admin/legal/terms/publish", json=_schedule_body("2026-11-18", effective_at + timedelta(days=1))
    )
    assert second.status_code == 409
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(LegalDocument).where(LegalDocument.version == "2026-11-18")
    )
    assert count == 0


async def test_any_publish_is_409_while_an_edition_is_scheduled_until_it_is_withdrawn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """예정 판이 있는 동안 같은 kind 의 게시는 즉시든 예약이든 409 이고 아무것도 남기지 않는다. 예정 판을 철회하면 즉시
    게시가 된다. 깨지는 시나리오: 예정 판을 둔 채 즉시 게시한 수정이 예정 판 시행 순간 조용히 사라지거나, 초안에 남은
    예정 판 본문이 즉시 게시로 공지 기간 없이 오늘 시행된다."""
    await _make_draft(db_session, kind="terms")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)
    effective_at = datetime.now(UTC) + timedelta(days=30)
    assert (
        await db_client.post("/admin/legal/terms/publish", json=_schedule_body("2026-11-17", effective_at))
    ).status_code == 200

    immediate = await db_client.post(
        "/admin/legal/terms/publish", json={"version": "2026-10-18", "requiresReconsent": False}
    )
    scheduled = await db_client.post(
        "/admin/legal/terms/publish", json=_schedule_body("2026-11-20", effective_at + timedelta(days=3))
    )

    assert (immediate.status_code, scheduled.status_code) == (409, 409)
    assert "철회" in immediate.json()["detail"]
    count = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(LegalDocument)
        .where(LegalDocument.version.in_(("2026-10-18", "2026-11-20")))
    )
    assert count == 0

    assert (await db_client.post("/admin/legal/terms/versions/2026-11-17/withdraw")).status_code == 200
    after = await db_client.post(
        "/admin/legal/terms/publish", json={"version": "2026-10-18", "requiresReconsent": False}
    )
    assert after.status_code == 200
    assert after.json()["published"]["version"] == "2026-10-18"


async def test_publish_rejects_effective_time_before_publish_time(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """시행 시각을 게시 시각보다 이르게 줄 수 없다. 깨지는 시나리오: 소급 시행된 판이 직전 현행판보다 앞에 놓여 영영
    현행이 되지 못하거나, 그 사이 옛 판에 동의한 회원이 새 판에 동의한 것으로 읽힌다."""
    await _make_draft(db_session, kind="terms")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(
        "/admin/legal/terms/publish", json=_schedule_body("2026-10-18", datetime.now(UTC) - timedelta(hours=1))
    )

    assert resp.status_code == 422
    assert await db_session.scalar(sa.select(LegalDocument).where(LegalDocument.version == "2026-10-18")) is None


async def test_withdraw_scheduled_edition_keeps_the_row_and_retires_its_version_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """예정 판을 철회하면 행은 `withdrawn` 으로 남고 감사 로그가 남으며, 예정 판이 사라져 다시 예약할 수 있다. 철회한
    판의 버전 이름은 다시 쓸 수 없다. 깨지는 시나리오: 공지로 나간 버전 이름에 다른 본문이 실려 두 판을 가를 수 없다."""
    await _make_draft(db_session, kind="terms")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)
    effective_at = datetime.now(UTC) + timedelta(days=30)
    assert (
        await db_client.post("/admin/legal/terms/publish", json=_schedule_body("2026-11-17", effective_at))
    ).status_code == 200

    resp = await db_client.post("/admin/legal/terms/versions/2026-11-17/withdraw")

    assert resp.status_code == 200
    assert [(item["version"], item["state"]) for item in resp.json()["items"]] == [
        ("2026-11-17", "withdrawn"),
        ("2026-09-06", "current"),
    ]
    assert (await db_client.get("/admin/legal/terms")).json()["upcoming"] is None
    logs = (
        await db_session.scalars(sa.select(AdminActionLog).where(AdminActionLog.action_type == "legal-withdraw"))
    ).all()
    assert len(logs) == 1
    reuse = await db_client.post("/admin/legal/terms/publish", json=_schedule_body("2026-11-17", effective_at))
    assert reuse.status_code == 409
    rescheduled = await db_client.post("/admin/legal/terms/publish", json=_schedule_body("2026-11-17.2", effective_at))
    assert rescheduled.status_code == 200
    assert rescheduled.json()["upcoming"]["version"] == "2026-11-17.2"


async def test_withdraw_refuses_an_edition_already_in_effect(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시행 시각이 지난 판은 철회할 수 없다(409) — 현행판도, 예약했다가 시행된 판도. 없는 판은 404. 깨지는 시나리오: 이미
    회원이 동의했을 수 있는 판이 사라져 그 동의가 가리키는 게시본이 없어진다."""
    await _make_draft(db_session, kind="terms")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)
    effective_at = datetime.now(UTC) + timedelta(days=30)
    assert (
        await db_client.post("/admin/legal/terms/publish", json=_schedule_body("2026-11-17", effective_at))
    ).status_code == 200

    current = await db_client.post("/admin/legal/terms/versions/2026-09-06/withdraw")
    missing = await db_client.post("/admin/legal/terms/versions/2030-01-01/withdraw")
    monkeypatch.setattr(documents, "utcnow", lambda: effective_at + timedelta(minutes=1))
    took_effect = await db_client.post("/admin/legal/terms/versions/2026-11-17/withdraw")

    assert (current.status_code, missing.status_code, took_effect.status_code) == (409, 404, 409)
    states = (await db_client.get("/admin/legal/terms/versions")).json()["items"]
    assert [(item["version"], item["state"]) for item in states] == [
        ("2026-11-17", "current"),
        ("2026-09-06", "past"),
    ]


async def test_released_row_without_effective_time_is_rejected_by_the_database(db_session: AsyncSession) -> None:
    """초안이 아닌 행은 시행 시각이 반드시 있다(CHECK). 깨지는 시나리오: 시행 시각 없는 게시본이 현행 조회에서 조용히
    빠져 영영 현행이 되지 못한다 — 시행 시각을 모르는 옛 코드가 배포 겹침 동안 게시하는 경우가 그렇다."""
    db_session.add(
        LegalDocument(
            kind="terms", version="2026-10-18", body_markdown="본문", status="published", published_at=datetime.now(UTC)
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---- 변경 안내·재동의 범위 ----------------------------------------------------------


async def test_draft_upsert_keeps_change_notice_unless_the_field_is_sent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """안내 칸을 보내지 않은 초안 저장은 안내를 그대로 두고, null 을 보내면 비운다. 깨지는 시나리오: 안내 칸을 모르는 이전
    어드민 화면이 본문만 저장할 때마다 운영자가 쓴 안내가 지워진다."""
    await _login_new_admin(db_client, db_session)

    first = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "본문", "changeNoticeMarkdown": "안내"})
    assert first.json()["draft"]["changeNoticeMarkdown"] == "안내"
    kept = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "본문 2"})
    assert (kept.json()["draft"]["bodyMarkdown"], kept.json()["draft"]["changeNoticeMarkdown"]) == ("본문 2", "안내")
    cleared = await db_client.put("/admin/legal/terms/draft", json={"bodyMarkdown": "본문 2", "changeNoticeMarkdown": None})
    assert cleared.json()["draft"]["changeNoticeMarkdown"] is None


@pytest.mark.parametrize(
    ("notice", "publish_body", "expected_status"),
    [
        pytest.param(None, {"reconsentScopes": ["transfer"]}, 422, id="scoped-without-notice"),
        pytest.param(" \n\t ", {"reconsentScopes": ["collection"]}, 422, id="scoped-with-blank-notice"),
        pytest.param(None, {"requiresReconsent": True}, 422, id="old-body-without-notice"),
        pytest.param("바뀐 점", {"reconsentScopes": ["transfer"]}, 200, id="scoped-with-notice"),
        pytest.param(" \n ", {"reconsentScopes": []}, 200, id="unscoped-with-blank-notice"),
        pytest.param(None, {"requiresReconsent": False}, 200, id="old-unscoped-without-notice"),
    ],
)
async def test_reconsent_publish_requires_a_change_notice(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    notice: str | None,
    publish_body: dict[str, object],
    expected_status: int,
) -> None:
    """재동의 범위가 하나라도 걸린 게시는 안내가 없거나 공백뿐이면 422 이고 아무것도 쓰지 않는다. 범위 없는 게시는 안내가
    없어도 된다. 깨지는 시나리오: 재동의 화면이 무엇이 바뀌었는지 보여 주지 못한 채 회원을 막는다."""
    await _make_draft(db_session, kind="privacy", body_markdown="본문", change_notice_markdown=notice)
    await db_session.commit()
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post("/admin/legal/privacy/publish", json={"version": "2099-01-01", **publish_body})

    assert resp.status_code == expected_status
    published = await db_session.scalar(
        sa.select(LegalDocument).where(LegalDocument.kind == "privacy", LegalDocument.version == "2099-01-01")
    )
    if expected_status == 422:
        assert published is None
    else:
        assert published is not None
        # 공백뿐인 안내는 없는 것으로 저장한다.
        assert published.change_notice_markdown == ((notice.strip() or None) if notice is not None else None)


@pytest.mark.parametrize(
    ("kind", "publish_body", "expected"),
    [
        pytest.param("privacy", {"reconsentScopes": ["transfer"]}, ["transfer"], id="privacy-transfer-only"),
        pytest.param("privacy", {"requiresReconsent": True}, ["collection", "transfer"], id="old-body-whole-document"),
        pytest.param(
            "privacy",
            {"reconsentScopes": ["collection"], "requiresReconsent": True},
            ["collection"],
            id="new-field-wins",
        ),
        pytest.param("privacy", {"reconsentScopes": ["terms"]}, None, id="privacy-rejects-terms-scope"),
        pytest.param("terms", {"reconsentScopes": ["transfer"]}, None, id="terms-rejects-transfer-scope"),
        pytest.param("refund-policy", {"reconsentScopes": ["terms"]}, None, id="policy-rejects-any-scope"),
    ],
)
async def test_publish_reconsent_scopes_follow_the_document_consent_units(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    kind: str,
    publish_body: dict[str, object],
    expected: list[str] | None,
) -> None:
    """재동의 범위는 그 문서의 동의 단위 안에서만 고른다. 이전 화면의 `requiresReconsent: true` 는 그 문서의 동의 단위
    전부이고, 두 칸이 같이 오면 새 칸을 따른다. 깨지는 시나리오: 처리방침 게시에 약관 범위를 걸어 게이트에는 효과가
    없는데 이력에는 재동의를 받은 것으로 남거나, 이전 화면의 재동의 게시가 아무 범위도 걸지 않는다."""
    await _make_draft(db_session, kind=kind, body_markdown="본문", change_notice_markdown="안내")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(f"/admin/legal/{kind}/publish", json={"version": "2099-01-01", **publish_body})

    if expected is None:
        assert resp.status_code == 422
        return
    assert resp.status_code == 200
    assert resp.json()["published"]["reconsentScopes"] == expected
    assert resp.json()["published"]["requiresReconsent"] is True
    assert resp.json()["published"]["changeNoticeMarkdown"] == "안내"
    versions = (await db_client.get(f"/admin/legal/{kind}/versions")).json()["items"]
    assert (versions[0]["reconsentScopes"], versions[0]["changeNoticeMarkdown"]) == (expected, "안내")


async def test_reconsent_republish_from_the_same_draft_needs_a_new_notice(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """게시가 성공하면 초안의 안내는 비워진다. 그래서 같은 초안으로 다시 재동의 게시를 하면, 본문만 고친 저장을 거쳐도
    422 다. 깨지는 시나리오: 이미 나간 안내가 다음 재동의 게시의 "안내 필수" 검사를 통과시켜, 회원이 이번 판에서 바뀐 것이
    아닌 지난 판의 안내를 보고 동의한다."""
    await _make_draft(db_session, kind="privacy", body_markdown="본문", change_notice_markdown="첫 안내")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)

    first = await db_client.post(
        "/admin/legal/privacy/publish", json={"version": "2099-01-01", "reconsentScopes": ["transfer"]}
    )
    assert first.status_code == 200
    assert first.json()["published"]["changeNoticeMarkdown"] == "첫 안내"
    # 본문은 남고 안내만 비워진다.
    assert (first.json()["draft"]["bodyMarkdown"], first.json()["draft"]["changeNoticeMarkdown"]) == ("본문", None)

    # 안내 칸을 모르는 화면처럼 본문만 고쳐 저장한다.
    await db_client.put("/admin/legal/privacy/draft", json={"bodyMarkdown": "본문 2"})
    second = await db_client.post(
        "/admin/legal/privacy/publish", json={"version": "2099-01-02", "reconsentScopes": ["collection"]}
    )

    assert second.status_code == 422
    assert (
        await db_session.scalar(
            sa.select(LegalDocument).where(LegalDocument.kind == "privacy", LegalDocument.version == "2099-01-02")
        )
    ) is None


async def test_publish_after_a_reconsent_publish_does_not_inherit_its_notice(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재동의 게시 뒤 재동의 없는 게시를 하면 새 판의 안내는 비어 있다. 깨지는 시나리오: 오타만 고친 판이 지난 판의 안내를
    복제해, 누적 변경 안내에 같은 안내가 두 판의 것으로 나온다."""
    await _make_draft(db_session, kind="terms", body_markdown="본문", change_notice_markdown="첫 안내")
    await db_session.commit()
    await _login_new_admin(db_client, db_session)

    first = await db_client.post("/admin/legal/terms/publish", json={"version": "2099-01-01", "reconsentScopes": ["terms"]})
    assert first.status_code == 200
    second = await db_client.post("/admin/legal/terms/publish", json={"version": "2099-01-02", "reconsentScopes": []})

    assert second.status_code == 200
    assert second.json()["published"]["version"] == "2099-01-02"
    assert second.json()["published"]["changeNoticeMarkdown"] is None
    versions = (await db_client.get("/admin/legal/terms/versions")).json()["items"]
    notices = {item["version"]: item["changeNoticeMarkdown"] for item in versions}
    assert (notices["2099-01-01"], notices["2099-01-02"]) == ("첫 안내", None)


async def test_requires_reconsent_must_match_reconsent_scopes_in_the_database(db_session: AsyncSession) -> None:
    """`requires_reconsent` 는 재동의 범위가 비어 있지 않음과 같다(CHECK). 이 칸을 모르는 이전 이미지가 배포 겹침·롤백 동안
    그 불리언으로 판정하므로 어긋나면 이전 이미지가 재동의를 놓치거나 잘못 건다."""
    db_session.add(
        LegalDocument(
            kind="terms",
            version="2099-01-01",
            body_markdown="본문",
            status="published",
            requires_reconsent=True,
            reconsent_scopes=[],
            published_at=datetime.now(UTC),
            effective_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
