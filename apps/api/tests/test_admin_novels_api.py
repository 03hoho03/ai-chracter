"""어드민 노벨 — 공개 노벨 목록·상세·화 공개본, 이용제한·해제, 노벨·노벨 댓글 신고 처리, 댓글 숨김·삭제.

공개 소설은 `_make_public_novel`(원작 = 다른 회원의 공개 작품, 6화 + 2화 묶음, 전부 공개)로 만든다. 앞 5화가 무료라 6화가 첫
유료 화이고, 본문은 "n화 본문" 이다. 같은 `db_client` 에 회원 세션과 운영자 세션을 함께 싣는다(쿠키 이름이 다르다)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import (
    AdminActionLog,
    NovelComment,
    NovelCommentReport,
    NovelPublication,
    NovelReport,
    NovelScreening,
    ReportReasonCategory,
    ReportStatus,
)
from api.novelize.deletion import delete_novels
from factories import (
    PublicNovel,
    _create_admin,
    _login_as,
    _login_as_admin,
    _make_public_novel,
    _make_user,
    _make_user_with_clover_lot,
)


@pytest.fixture(autouse=True)
def _novel_public_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)


async def _member(db_session: AsyncSession, balance: int = 100) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance)
    await db_session.commit()
    return user.id


async def _novel(db_session: AsyncSession) -> PublicNovel:
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id)
    await db_session.commit()
    return novel


async def _as_admin(client: httpx.AsyncClient, db: AsyncSession) -> uuid.UUID:
    admin = await _create_admin(db)
    await db.commit()
    await _login_as_admin(client, admin)
    admin_id = admin["id"]
    assert isinstance(admin_id, uuid.UUID)
    return admin_id


async def _buy_sixth(client: httpx.AsyncClient, novel: PublicNovel, buyer: uuid.UUID) -> None:
    await _login_as(client, buyer)
    resp = await client.post(
        f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}/purchase", json={"expectedPrice": 30}
    )
    assert resp.status_code == 200


async def _logs(db: AsyncSession) -> set[tuple[str, uuid.UUID | None, uuid.UUID | None, str | None, str]]:
    """감사 로그 행들. 한 테스트 안의 `now()` 는 같은 값이라 시각으로 순서를 못 가려 집합으로 비교한다."""
    rows = await db.execute(
        sa.select(
            AdminActionLog.action_type,
            AdminActionLog.target_user_id,
            AdminActionLog.target_novel_id,
            AdminActionLog.reason_category,
            AdminActionLog.reason_text,
        )
    )
    return {(row[0], row[1], row[2], row[3], row[4]) for row in rows}


def _report(novel: PublicNovel, reporter: uuid.UUID, **overrides: object) -> NovelReport:
    values: dict[str, object] = {
        "reporter_user_id": reporter,
        "publisher_user_id": novel.publisher_id,
        "novel_id": novel.novel_id,
        "reason_category": ReportReasonCategory.SPAM,
        "status": ReportStatus.PENDING,
        "evidence_title": "공개 제목",
        "evidence_synopsis": "소개",
        "evidence_expires_at": datetime.now(UTC) + timedelta(days=1),
        **overrides,
    }
    return NovelReport(**values)


# ── 권한 ────────────────────────────────────────────────────────────────────
async def test_admin_novel_routes_need_an_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    member = await _member(db_session)
    await _login_as(db_client, member)
    some = uuid.uuid4()
    responses = [
        await db_client.get("/admin/novels"),
        await db_client.get(f"/admin/novels/{some}"),
        await db_client.post(f"/admin/novels/{some}/moderation", json={"action": "restrict", "adminComment": "x"}),
        await db_client.get("/admin/novel-reports"),
        await db_client.post(f"/admin/novel-reports/{some}/actions", json={"action": "reject", "adminComment": "x"}),
        await db_client.get("/admin/novel-comment-reports"),
        await db_client.post(f"/admin/novel-comments/{some}/actions", json={"action": "hide", "adminComment": "x"}),
    ]
    assert [resp.status_code for resp in responses] == [401] * len(responses)


# ── 목록·상세 ────────────────────────────────────────────────────────────────
async def test_admin_lists_public_novels_with_purchases_and_pending_reports(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이용제한·거둔 노벨도 목록에 있다(독자에게 보이는지는 `readable`). 구매 수는 환급되지 않은 구매, 신고 수는 처리 전
    신고만 센다. 이용제한 걸러 보기가 된다."""
    plain = await _novel(db_session)
    restricted = await _novel(db_session)
    buyer = await _member(db_session)
    await _buy_sixth(db_client, plain, buyer)
    db_session.add_all(
        [_report(plain, buyer), _report(plain, buyer, chapter_id=plain.chapter_ids[0], chapter_ordinal=1, status=ReportStatus.REJECTED)]
    )
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == restricted.novel_id)
        .values(moderation_status="restricted", published_at=sa.func.now() - sa.text("interval '1 day'"))
    )
    await db_session.commit()
    await _as_admin(db_client, db_session)

    listed = (await db_client.get("/admin/novels")).json()
    only_restricted = (await db_client.get("/admin/novels", params={"moderationStatus": "restricted"})).json()

    assert listed["totalCount"] == 2
    by_id = {item["id"]: item for item in listed["items"]}
    assert (by_id[str(plain.novel_id)]["purchaseCount"], by_id[str(plain.novel_id)]["pendingReportCount"]) == (1, 1)
    assert (by_id[str(plain.novel_id)]["readable"], by_id[str(restricted.novel_id)]["readable"]) == (True, False)
    assert by_id[str(plain.novel_id)]["chapterCount"] == 8
    assert [item["id"] for item in only_restricted["items"]] == [str(restricted.novel_id)]


async def test_admin_detail_shows_the_public_copy_screenings_and_reports(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상세는 공개본 글(제목·소개·화 목록)과 심사 사유(운영자만 본다)·신고·구매 수를 싣고, 화 공개본 본문은 따로 연다.
    공개한 적 없는 소설·없는 화는 404 다."""
    novel = await _novel(db_session)
    reporter = await _member(db_session)
    db_session.add_all(
        [
            NovelScreening(
                novel_id=novel.novel_id,
                chapter_id=novel.chapter_ids[1],
                chapter_ordinal=2,
                user_id=novel.publisher_id,
                outcome="rejected",
                flagged_parts=["chapter_body"],
                reason="폭력 묘사",
                model="gemini-test",
            ),
            _report(novel, reporter),
        ]
    )
    await db_session.commit()
    await _as_admin(db_client, db_session)

    detail = (await db_client.get(f"/admin/novels/{novel.novel_id}")).json()
    chapter = await db_client.get(f"/admin/novels/{novel.novel_id}/chapters/{novel.chapter_ids[1]}")
    missing = await db_client.get(f"/admin/novels/{uuid.uuid4()}")
    foreign = await db_client.get(f"/admin/novels/{novel.novel_id}/chapters/{uuid.uuid4()}")

    assert (detail["title"], detail["synopsis"], detail["publisherUserId"]) == ("공개 제목", "소개", str(novel.publisher_id))
    assert [c["ordinal"] for c in detail["chapters"]] == list(range(1, 9))
    assert [(s["chapterOrdinal"], s["outcome"], s["reason"]) for s in detail["screenings"]] == [(2, "rejected", "폭력 묘사")]
    assert [(r["reporterUserId"], r["status"]) for r in detail["reports"]] == [(str(reporter), "pending")]
    assert (chapter.status_code, chapter.json()["paragraphs"]) == (200, ["2화 본문"])
    assert (missing.status_code, foreign.status_code) == (404, 404)


# ── 이용제한·해제 ────────────────────────────────────────────────────────────
async def test_restricting_hides_the_novel_and_lifting_restores_what_buyers_own(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이용제한하면 소장한 사람에게도 열람이 끝나고(410 restricted), 해제하면 소장한 화를 다시 읽는다 — 운영자가 잘못 내린
    조치는 해제로 되돌린다. 조치마다 감사 로그에 게시자·노벨·사유가 남고, 게시자의 회원 상세 조치 이력에 그 줄이 보인다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    await _buy_sixth(db_client, novel, buyer)
    await _as_admin(db_client, db_session)
    chapter_path = f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}"

    restricted = await db_client.post(
        f"/admin/novels/{novel.novel_id}/moderation",
        json={"action": "restrict", "adminComment": "선정적 묘사", "reasonCategory": "adult"},
    )
    assert (restricted.status_code, restricted.json()["moderationStatus"]) == (200, "restricted")
    await _login_as(db_client, buyer)
    ended = await db_client.get(chapter_path)
    assert (ended.status_code, ended.json()["detail"]["reason"]) == (410, "restricted")

    again = await db_client.post(f"/admin/novels/{novel.novel_id}/moderation", json={"action": "restrict", "adminComment": "x"})
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "NOVEL_ALREADY_RESTRICTED")
    lifted = await db_client.post(
        f"/admin/novels/{novel.novel_id}/moderation", json={"action": "lift", "adminComment": "오판 정정"}
    )
    assert (lifted.status_code, lifted.json()["moderationStatus"]) == (200, "normal")
    await _login_as(db_client, buyer)
    reopened = await db_client.get(chapter_path)
    assert (reopened.status_code, reopened.json()["paragraphs"]) == (200, ["6화 본문"])
    lift_again = await db_client.post(f"/admin/novels/{novel.novel_id}/moderation", json={"action": "lift", "adminComment": "x"})
    assert (lift_again.status_code, lift_again.json()["detail"]["code"]) == (409, "NOVEL_NOT_RESTRICTED")

    assert await _logs(db_session) == {
        ("novel-restrict", novel.publisher_id, novel.novel_id, "adult", "선정적 묘사"),
        ("novel-lift", novel.publisher_id, novel.novel_id, None, "오판 정정"),
    }
    user_detail = await db_client.get(f"/admin/users/{novel.publisher_id}")
    assert user_detail.status_code == 200
    assert {log["actionType"] for log in user_detail.json()["actionLogs"]} == {"novel-lift", "novel-restrict"}


async def test_moderation_needs_a_reason_and_a_published_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel = await _novel(db_session)
    await _as_admin(db_client, db_session)

    blank = await db_client.post(f"/admin/novels/{novel.novel_id}/moderation", json={"action": "restrict", "adminComment": "  "})
    missing = await db_client.post(f"/admin/novels/{uuid.uuid4()}/moderation", json={"action": "restrict", "adminComment": "x"})

    assert (blank.status_code, missing.status_code) == (422, 404)
    assert await _logs(db_session) == set()


# ── 노벨 신고 처리 ────────────────────────────────────────────────────────────
async def test_admin_resolves_a_novel_report_by_restricting_or_rejects_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """신고로 이용제한하면 신고가 처리완료가 되고 감사 로그에 신고 사유가 실린다. 반려는 노벨을 건드리지 않는다. 목록은 상태로
    거르고 최신순이다."""
    novel = await _novel(db_session)
    first, second = await _member(db_session), await _member(db_session)
    older = _report(novel, first, created_at=datetime.now(UTC) - timedelta(hours=1))
    newer = _report(novel, second, chapter_id=novel.chapter_ids[1], chapter_ordinal=2, reason_category=ReportReasonCategory.HATE)
    db_session.add_all([older, newer])
    await db_session.commit()
    await _as_admin(db_client, db_session)

    listed = (await db_client.get("/admin/novel-reports", params={"status": "pending"})).json()
    assert [item["id"] for item in listed["items"]] == [str(newer.id), str(older.id)]
    rejected = await db_client.post(f"/admin/novel-reports/{older.id}/actions", json={"action": "reject", "adminComment": "문제 없음"})
    assert (rejected.status_code, rejected.json()["status"]) == (200, "rejected")
    assert await db_session.scalar(sa.select(NovelPublication.moderation_status)) == "normal"
    resolved = await db_client.post(f"/admin/novel-reports/{newer.id}/actions", json={"action": "restrict", "adminComment": "혐오 표현"})
    assert (resolved.status_code, resolved.json()["status"], resolved.json()["novelModerationStatus"]) == (
        200,
        "resolved",
        "restricted",
    )

    assert await _logs(db_session) == {
        ("novel-report-reject", novel.publisher_id, novel.novel_id, "spam", "문제 없음"),
        ("novel-restrict", novel.publisher_id, novel.novel_id, "hate", "혐오 표현"),
    }


async def test_a_report_on_a_deleted_novel_keeps_its_evidence_and_can_only_be_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """게시자가 소설을 지워도 신고 상세는 증거로 무엇이 신고됐는지 보인다. 지운 노벨은 이용제한할 수 없어 409 이고 반려는 된다.
    증거는 보유 기간이 지나면 파기 전이라도 숨긴다."""
    novel = await _novel(db_session)
    reporter = await _member(db_session)
    report = _report(novel, reporter, chapter_id=novel.chapter_ids[0], chapter_ordinal=1, evidence_body="1화 본문")
    expired = _report(novel, await _member(db_session), evidence_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    db_session.add_all([report, expired])
    await db_session.flush()
    await delete_novels(db_session, [novel.novel_id])
    await db_session.commit()
    await _as_admin(db_client, db_session)

    detail = (await db_client.get(f"/admin/novel-reports/{report.id}")).json()
    hidden = (await db_client.get(f"/admin/novel-reports/{expired.id}")).json()
    gone = await db_client.post(f"/admin/novel-reports/{report.id}/actions", json={"action": "restrict", "adminComment": "x"})
    rejected = await db_client.post(f"/admin/novel-reports/{report.id}/actions", json={"action": "reject", "adminComment": "지워짐"})

    assert (detail["novelId"], detail["chapterOrdinal"], detail["novelModerationStatus"]) == (None, 1, None)
    assert (detail["evidence"]["available"], detail["evidence"]["body"], detail["evidence"]["title"]) == (True, "1화 본문", "공개 제목")
    assert (hidden["evidence"]["available"], hidden["evidence"]["title"]) == (False, None)
    assert (gone.status_code, gone.json()["detail"]["code"]) == (409, "NOVEL_GONE")
    assert (rejected.status_code, rejected.json()["status"]) == (200, "rejected")
    assert await _logs(db_session) == {("novel-report-reject", novel.publisher_id, None, "spam", "지워짐")}


# ── 댓글 ────────────────────────────────────────────────────────────────────
async def test_admin_hides_restores_and_deletes_comments(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """숨긴 댓글은 독자 목록에서 빠지고 되돌리면 돌아온다. 운영자 삭제는 본문을 비우고 되돌릴 수 없다. 조치마다 감사 로그에
    작성자·노벨·사유가 남는다."""
    novel = await _novel(db_session)
    author = await _member(db_session)
    await _login_as(db_client, author)
    path = f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[0]}/comments"
    comment_id = (await db_client.post(path, json={"body": "문제 댓글"})).json()["id"]
    await _as_admin(db_client, db_session)

    listed = (await db_client.get(f"/admin/novels/{novel.novel_id}/comments")).json()
    assert [(c["id"], c["chapterOrdinal"], c["body"]) for c in listed["items"]] == [(comment_id, 1, "문제 댓글")]
    actions = f"/admin/novel-comments/{comment_id}/actions"
    assert (await db_client.post(actions, json={"action": "hide", "adminComment": "욕설"})).status_code == 204
    assert (await db_client.get(path)).json()["totalCount"] == 0
    assert (await db_client.post(actions, json={"action": "restore", "adminComment": "오판"})).status_code == 204
    assert (await db_client.get(path)).json()["totalCount"] == 1
    assert (await db_client.post(actions, json={"action": "delete", "adminComment": "욕설 재확인"})).status_code == 204
    after = await db_client.post(actions, json={"action": "restore", "adminComment": "x"})
    blank = await db_client.post(actions, json={"action": "hide", "adminComment": " "})

    assert (after.status_code, after.json()["detail"]["code"]) == (409, "NOVEL_COMMENT_DELETED")
    assert blank.status_code == 422
    row = (await db_session.scalars(sa.select(NovelComment))).one()
    assert (row.body, row.deleted_by) == (None, "moderator")
    assert await _logs(db_session) == {
        ("novel-comment-hide", author, novel.novel_id, None, "욕설"),
        ("novel-comment-restore", author, novel.novel_id, None, "오판"),
        ("novel-comment-delete", author, novel.novel_id, None, "욕설 재확인"),
    }


async def test_admin_resolves_comment_reports(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """댓글 신고로 숨기면 신고가 처리완료가 되고 감사 로그에 신고 사유가 실린다. 반려는 댓글을 건드리지 않는다. 작성자가
    탈퇴해 댓글이 사라진 신고는 숨길 수 없어 409 이고, 상세는 증거 사본으로 무엇이 신고됐는지 보인다."""
    novel = await _novel(db_session)
    author, reporter, leaving = await _member(db_session), await _member(db_session), await _member(db_session)
    path = f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[0]}/comments"
    ids = {}
    for who, body in ((author, "남는 댓글"), (leaving, "떠날 사람 댓글")):
        await _login_as(db_client, who)
        ids[who] = (await db_client.post(path, json={"body": body})).json()["id"]
    await _login_as(db_client, reporter)
    reports = {}
    for who in (author, leaving):
        resp = await db_client.post(f"/webnovels/{novel.novel_id}/comments/{ids[who]}/reports", json={"reasonCategory": "hate"})
        reports[who] = resp.json()["reportId"]
    await _login_as(db_client, leaving)
    assert (await db_client.delete("/me")).status_code == 204
    await _as_admin(db_client, db_session)

    listed = (await db_client.get("/admin/novel-comment-reports")).json()
    detail = (await db_client.get(f"/admin/novel-comment-reports/{reports[author]}")).json()
    orphan = (await db_client.get(f"/admin/novel-comment-reports/{reports[leaving]}")).json()
    gone = await db_client.post(
        f"/admin/novel-comment-reports/{reports[leaving]}/actions", json={"action": "hide", "adminComment": "x"}
    )
    hidden = await db_client.post(
        f"/admin/novel-comment-reports/{reports[author]}/actions", json={"action": "hide", "adminComment": "혐오"}
    )

    assert listed["totalCount"] == 2
    assert (detail["comment"]["body"], detail["evidence"]["body"]) == ("남는 댓글", "남는 댓글")
    assert (orphan["comment"], orphan["commentId"], orphan["evidence"]["body"]) == (None, None, "떠날 사람 댓글")
    assert (gone.status_code, gone.json()["detail"]["code"]) == (409, "NOVEL_COMMENT_GONE")
    assert (hidden.status_code, hidden.json()["status"], hidden.json()["comment"]["moderatorHidden"]) == (200, "resolved", True)
    assert await _logs(db_session) == {("novel-comment-hide", author, novel.novel_id, "hate", "혐오")}
    comment_report = await db_session.get(NovelCommentReport, uuid.UUID(reports[author]))
    assert comment_report is not None and comment_report.resolved_at is not None
