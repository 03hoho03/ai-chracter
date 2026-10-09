"""노벨 독자의 화 댓글(목록·쓰기·지우기)과 신고(노벨·화·댓글), 정지 회원 차단, 탈퇴가 댓글·신고에 하는 일.

공개 소설은 `_make_public_novel`(원작 = 다른 회원의 공개 작품, 6화 + 2화 묶음, 전부 공개)로 만든다. 앞 5화가 무료라 6화가 첫
유료 화이고, 본문은 "n화 본문" 이다. 같은 `db_client` 로 회원을 바꿔 가며 부른다(`_login_as`)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import (
    NovelChapterPublication,
    NovelComment,
    NovelCommentReport,
    NovelPublication,
    NovelReport,
    ReportReasonCategory,
    ReportStatus,
    User,
)
from api.novel_public import reports as novel_reports
from api.session.suspension import mark_user_suspended
from factories import PublicNovel, _login_as, _make_public_novel, _make_user, _make_user_with_clover_lot


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


def _comments_path(novel: PublicNovel, ordinal: int) -> str:
    return f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[ordinal - 1]}/comments"


async def _write(
    client: httpx.AsyncClient, novel: PublicNovel, ordinal: int, body: str, *, as_user: uuid.UUID
) -> httpx.Response:
    await _login_as(client, as_user)
    return await client.post(_comments_path(novel, ordinal), json={"body": body})


async def _list(client: httpx.AsyncClient, novel: PublicNovel, ordinal: int, *, as_user: uuid.UUID) -> httpx.Response:
    await _login_as(client, as_user)
    return await client.get(_comments_path(novel, ordinal))


# ── 목록·쓰기 ────────────────────────────────────────────────────────────────
async def test_comments_are_listed_newest_first_with_what_the_viewer_may_do(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작성자 본인은 자기 댓글을 지울 수 있고 신고할 수 없다. 게시자의 댓글에는 게시자 표식이 붙고, 게시자는 남의 댓글도 지울 수
    있다. 다른 화의 댓글은 섞이지 않는다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    first = await _write(db_client, novel, 1, "독자 댓글", as_user=reader)
    assert first.status_code == 201
    assert first.json()["body"] == "독자 댓글"
    assert (await _write(db_client, novel, 1, "게시자 댓글", as_user=novel.publisher_id)).status_code == 201
    assert (await _write(db_client, novel, 2, "다른 화", as_user=reader)).status_code == 201
    # 한 트랜잭션 안의 now() 는 같은 값이라 순서를 시각으로 못 가른다 — 독자 댓글을 더 옛날로 민다.
    await db_session.execute(
        sa.update(NovelComment)
        .where(NovelComment.id == uuid.UUID(first.json()["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    await db_session.commit()

    as_reader = (await _list(db_client, novel, 1, as_user=reader)).json()
    assert as_reader["totalCount"] == 2
    assert [
        (c["body"], c["isPublisher"], c["isMine"], c["canDelete"], c["canReport"]) for c in as_reader["items"]
    ] == [("게시자 댓글", True, False, False, True), ("독자 댓글", False, True, True, False)]
    as_publisher = (await _list(db_client, novel, 1, as_user=novel.publisher_id)).json()
    assert [(c["isMine"], c["canDelete"], c["canReport"]) for c in as_publisher["items"]] == [
        (True, True, False),
        (False, True, True),
    ]


async def test_comments_page_by_cursor(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _novel(db_session)
    reader = await _member(db_session)
    base = datetime.now(UTC)
    db_session.add_all(
        [
            NovelComment(
                novel_id=novel.novel_id,
                chapter_id=novel.chapter_ids[0],
                author_user_id=reader,
                body=f"{index}번",
                created_at=base + timedelta(seconds=index),
            )
            for index in range(21)
        ]
    )
    await db_session.commit()

    first = (await _list(db_client, novel, 1, as_user=reader)).json()
    second = (await db_client.get(_comments_path(novel, 1), params={"cursor": first["nextCursor"]})).json()

    assert [c["body"] for c in first["items"]] == [f"{index}번" for index in range(20, 0, -1)]
    assert ([c["body"] for c in second["items"]], second["nextCursor"]) == (["0번"], None)
    assert first["totalCount"] == second["totalCount"] == 21


async def test_a_paid_chapter_takes_comments_only_from_people_who_can_read_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """마지막 무료 화(5화)는 누구나, 첫 유료 화(6화)는 소장한 사람과 게시자만 보고 쓴다 — 쓰기 권한이 곧 열람 권한이다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)

    assert (await _write(db_client, novel, 5, "무료 화", as_user=reader)).status_code == 201
    locked = await _write(db_client, novel, 6, "유료 화", as_user=reader)
    assert (locked.status_code, locked.json()["detail"]["code"]) == (403, "NOVEL_CHAPTER_LOCKED")
    assert (await _list(db_client, novel, 6, as_user=reader)).status_code == 403
    assert (await _write(db_client, novel, 6, "게시자", as_user=novel.publisher_id)).status_code == 201

    await _login_as(db_client, reader)
    bought = await db_client.post(
        f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}/purchase", json={"expectedPrice": 30}
    )
    assert bought.status_code == 200
    assert (await _write(db_client, novel, 6, "소장", as_user=reader)).status_code == 201
    assert (await _list(db_client, novel, 6, as_user=reader)).json()["totalCount"] == 2


async def test_comments_disappear_with_the_novel_and_the_switch(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """운영자가 이용제한한 노벨은 댓글도 404 다. 노벨 스위치가 꺼져도 404 다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == novel.novel_id)
        .values(moderation_status="restricted")
    )
    await db_session.commit()

    restricted = await _write(db_client, novel, 1, "댓글", as_user=reader)
    assert (restricted.status_code, restricted.json()["detail"]["code"]) == (404, "NOVEL_CHAPTER_NOT_FOUND")
    assert (await _list(db_client, novel, 1, as_user=reader)).status_code == 404
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(moderation_status="normal")
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "novel_public_enabled", False)
    off = await _list(db_client, novel, 1, as_user=reader)
    assert (off.status_code, off.json()["detail"]["code"]) == (404, "NOVEL_PUBLIC_DISABLED")


async def test_comment_body_must_have_text_and_at_most_1000_characters(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """길이는 화면에 보이는 글자(자소 묶음) 수로 센다 — 피부색이 붙은 이모지 하나는 코드 포인트 둘이지만 한 글자다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)

    blank = await _write(db_client, novel, 1, "  \n ", as_user=reader)
    assert (blank.status_code, blank.json()["detail"]["code"]) == (422, "NOVEL_COMMENT_EMPTY")
    assert (await _write(db_client, novel, 1, "👍🏽" * 1000, as_user=reader)).status_code == 201
    too_long = await _write(db_client, novel, 1, "가" * 1001, as_user=reader)
    assert (too_long.status_code, too_long.json()["detail"]["code"]) == (422, "NOVEL_COMMENT_TOO_LONG")


async def test_comment_writes_are_rate_limited(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    novel = await _novel(db_session)
    reader = await _member(db_session)
    for index in range(5):
        assert (await _write(db_client, novel, 1, f"{index}", as_user=reader)).status_code == 201

    limited = await _write(db_client, novel, 1, "여섯째", as_user=reader)

    assert (limited.status_code, limited.json()["detail"]["code"]) == (429, "NOVEL_COMMENT_RATE_LIMITED")
    assert limited.headers["Retry-After"]


# ── 지우기 ──────────────────────────────────────────────────────────────────
async def test_only_the_author_or_the_publisher_deletes_a_comment(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """지운 댓글은 목록에서 빠지고 행은 본문을 비운 채 지운 사람을 남긴다. 이미 지운 댓글은 다시 지울 수 없다."""
    novel = await _novel(db_session)
    author, stranger = await _member(db_session), await _member(db_session)
    own = (await _write(db_client, novel, 1, "내 댓글", as_user=author)).json()["id"]
    other = (await _write(db_client, novel, 1, "또 다른 댓글", as_user=author)).json()["id"]

    await _login_as(db_client, stranger)
    forbidden = await db_client.delete(f"/webnovels/{novel.novel_id}/comments/{own}")
    assert (forbidden.status_code, forbidden.json()["detail"]["code"]) == (403, "NOVEL_COMMENT_DELETE_FORBIDDEN")
    await _login_as(db_client, author)
    assert (await db_client.delete(f"/webnovels/{novel.novel_id}/comments/{own}")).status_code == 204
    again = await db_client.delete(f"/webnovels/{novel.novel_id}/comments/{own}")
    assert (again.status_code, again.json()["detail"]["code"]) == (404, "NOVEL_COMMENT_NOT_FOUND")
    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete(f"/webnovels/{novel.novel_id}/comments/{other}")).status_code == 204

    rows = (
        await db_session.execute(
            sa.select(NovelComment.id, NovelComment.body, NovelComment.deleted_by).where(
                NovelComment.novel_id == novel.novel_id
            )
        )
    ).all()
    assert {(str(row.id), row.body, row.deleted_by) for row in rows} == {(own, None, "author"), (other, None, "publisher")}
    assert (await _list(db_client, novel, 1, as_user=author)).json()["totalCount"] == 0


# ── 신고 ────────────────────────────────────────────────────────────────────
async def test_a_novel_or_chapter_report_keeps_a_copy_of_the_public_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """신고 시점의 공개본(소설 제목·소개, 화 신고면 화 제목과 본문 앞부분)을 증거로 남긴다. 같은 대상을 다시 신고하면 처음
    신고를 그대로 돌려준다(새 행 없음)."""
    monkeypatch.setattr(novel_reports, "NOVEL_REPORT_EVIDENCE_BODY_CHARS", 3)
    novel = await _novel(db_session)
    reporter = await _member(db_session)
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == novel.chapter_ids[1])
        .values(title="둘째 화 제목")
    )
    await db_session.commit()
    await _login_as(db_client, reporter)
    path = f"/webnovels/{novel.novel_id}/reports"

    whole = await db_client.post(path, json={"reasonCategory": "spam"})
    chapter = await db_client.post(path, json={"reasonCategory": "hate", "chapterId": str(novel.chapter_ids[1])})
    again = await db_client.post(path, json={"reasonCategory": "other", "chapterId": str(novel.chapter_ids[1])})
    whole_again = await db_client.post(path, json={"reasonCategory": "other"})

    assert whole.status_code == chapter.status_code == 200
    assert again.json() == chapter.json() and whole_again.json() == whole.json()
    rows = {
        row.chapter_ordinal: row
        for row in (await db_session.scalars(sa.select(NovelReport).where(NovelReport.reporter_user_id == reporter)))
    }
    assert set(rows) == {None, 2}
    assert (rows[None].evidence_title, rows[None].evidence_synopsis, rows[None].evidence_body) == ("공개 제목", "소개", None)
    assert (rows[2].evidence_chapter_title, rows[2].evidence_body, rows[2].reason_category) == (
        "둘째 화 제목",
        "2화 ",
        ReportReasonCategory.HATE,
    )
    assert (rows[2].publisher_user_id, rows[2].status) == (novel.publisher_id, ReportStatus.PENDING)


async def test_novel_reports_need_a_readable_novel_someone_else_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    novel = await _novel(db_session)
    other = await _novel(db_session)
    reporter = await _member(db_session)
    await _login_as(db_client, novel.publisher_id)
    own = await db_client.post(f"/webnovels/{novel.novel_id}/reports", json={"reasonCategory": "spam"})
    assert (own.status_code, own.json()["detail"]["code"]) == (403, "NOVEL_REPORT_OWN")
    await _login_as(db_client, reporter)
    foreign_chapter = await db_client.post(
        f"/webnovels/{novel.novel_id}/reports", json={"reasonCategory": "spam", "chapterId": str(other.chapter_ids[0])}
    )
    assert (foreign_chapter.status_code, foreign_chapter.json()["detail"]["code"]) == (404, "NOVEL_CHAPTER_NOT_FOUND")
    await db_session.execute(
        sa.update(NovelPublication).where(NovelPublication.novel_id == novel.novel_id).values(visibility="withdrawn")
    )
    await db_session.commit()
    gone = await db_client.post(f"/webnovels/{novel.novel_id}/reports", json={"reasonCategory": "spam"})
    assert (gone.status_code, gone.json()["detail"]["code"]) == (404, "NOVEL_NOT_FOUND")


async def test_reports_are_rate_limited(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """노벨·화·댓글 신고가 한 한도(분당 10)를 같이 쓴다."""
    novel = await _novel(db_session)
    reporter = await _member(db_session)
    await _login_as(db_client, reporter)
    for ordinal in range(1, 9):
        resp = await db_client.post(
            f"/webnovels/{novel.novel_id}/reports",
            json={"reasonCategory": "spam", "chapterId": str(novel.chapter_ids[ordinal - 1])},
        )
        assert resp.status_code == 200
    assert (await db_client.post(f"/webnovels/{novel.novel_id}/reports", json={"reasonCategory": "spam"})).status_code == 200
    comment = (await _write(db_client, novel, 1, "남의 댓글", as_user=novel.publisher_id)).json()["id"]
    await _login_as(db_client, reporter)
    tenth = await db_client.post(f"/webnovels/{novel.novel_id}/comments/{comment}/reports", json={"reasonCategory": "spam"})
    assert tenth.status_code == 200

    limited = await db_client.post(f"/webnovels/{novel.novel_id}/reports", json={"reasonCategory": "hate"})

    assert (limited.status_code, limited.json()["detail"]["code"]) == (429, "NOVEL_REPORT_RATE_LIMITED")


async def test_a_comment_report_keeps_the_comment_text(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """남의 댓글만 신고할 수 있다 — 내 댓글·지운 댓글은 404. 같은 댓글을 다시 신고하면 처음 신고를 돌려준다."""
    novel = await _novel(db_session)
    author, reporter = await _member(db_session), await _member(db_session)
    comment = (await _write(db_client, novel, 1, "신고될 댓글", as_user=author)).json()["id"]
    deleted = (await _write(db_client, novel, 1, "지울 댓글", as_user=author)).json()["id"]
    assert (await db_client.delete(f"/webnovels/{novel.novel_id}/comments/{deleted}")).status_code == 204
    own = await db_client.post(f"/webnovels/{novel.novel_id}/comments/{comment}/reports", json={"reasonCategory": "spam"})
    assert (own.status_code, own.json()["detail"]["code"]) == (404, "NOVEL_COMMENT_NOT_FOUND")

    await _login_as(db_client, reporter)
    first = await db_client.post(f"/webnovels/{novel.novel_id}/comments/{comment}/reports", json={"reasonCategory": "hate"})
    again = await db_client.post(f"/webnovels/{novel.novel_id}/comments/{comment}/reports", json={"reasonCategory": "spam"})
    gone = await db_client.post(f"/webnovels/{novel.novel_id}/comments/{deleted}/reports", json={"reasonCategory": "spam"})

    assert first.status_code == 200 and again.json() == first.json()
    assert gone.status_code == 404
    report = (await db_session.scalars(sa.select(NovelCommentReport))).one()
    assert (report.evidence_body, report.comment_author_user_id, report.novel_id, report.reason_category) == (
        "신고될 댓글",
        author,
        novel.novel_id,
        ReportReasonCategory.HATE,
    )


# ── 정지·탈퇴 ────────────────────────────────────────────────────────────────
async def test_a_suspended_member_cannot_comment_report_or_buy(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """정지는 DB 표식과 요청 차단 표식을 함께 건다(운영자 정지와 같다) — 쓰기·신고·구매 모두 403 이고 아무것도 남지 않는다."""
    novel = await _novel(db_session)
    member = await _member(db_session)
    await db_session.execute(sa.update(User).where(User.id == member).values(suspended_at=sa.func.now()))
    await db_session.commit()
    await mark_user_suspended(member)

    await _login_as(db_client, member)
    responses = [
        await db_client.post(_comments_path(novel, 1), json={"body": "댓글"}),
        await db_client.post(f"/webnovels/{novel.novel_id}/reports", json={"reasonCategory": "spam"}),
        await db_client.post(
            f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}/purchase", json={"expectedPrice": 30}
        ),
    ]

    assert [resp.status_code for resp in responses] == [403, 403, 403]
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelComment)) == 0
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelReport)) == 0


async def test_a_publisher_with_buyers_comments_and_reports_can_withdraw(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """게시자 탈퇴는 204 다. 소설과 그 댓글은 지워지고, 그 소설·댓글에 들어온 신고는 대상 칸만 비고 증거와 함께 남는다."""
    novel = await _novel(db_session)
    reader = await _member(db_session)
    await _login_as(db_client, reader)
    bought = await db_client.post(
        f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}/purchase", json={"expectedPrice": 30}
    )
    assert bought.status_code == 200
    assert (await _write(db_client, novel, 6, "독자 댓글", as_user=reader)).status_code == 201
    publisher_comment = (await _write(db_client, novel, 1, "게시자 댓글", as_user=novel.publisher_id)).json()["id"]
    await _login_as(db_client, reader)
    await db_client.post(f"/webnovels/{novel.novel_id}/reports", json={"reasonCategory": "spam", "chapterId": str(novel.chapter_ids[0])})
    await db_client.post(f"/webnovels/{novel.novel_id}/comments/{publisher_comment}/reports", json={"reasonCategory": "hate"})

    await _login_as(db_client, novel.publisher_id)
    assert (await db_client.delete("/me")).status_code == 204

    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelComment)) == 0
    report = (await db_session.scalars(sa.select(NovelReport))).one()
    assert (report.novel_id, report.chapter_id, report.chapter_ordinal, report.evidence_body) == (None, None, 1, "1화 본문")
    comment_report = (await db_session.scalars(sa.select(NovelCommentReport))).one()
    assert (comment_report.comment_id, comment_report.novel_id, comment_report.evidence_body) == (None, None, "게시자 댓글")


async def test_a_reader_who_commented_and_was_reported_can_withdraw(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """댓글을 단 독자의 탈퇴는 204 이고 그 댓글 행이 지워진다. 그 댓글의 신고는 증거와 함께 남는다. 남의 댓글은 그대로다."""
    novel = await _novel(db_session)
    leaving, staying = await _member(db_session), await _member(db_session)
    doomed = (await _write(db_client, novel, 1, "떠날 사람 댓글", as_user=leaving)).json()["id"]
    assert (await _write(db_client, novel, 1, "남을 사람 댓글", as_user=staying)).status_code == 201
    await db_client.post(f"/webnovels/{novel.novel_id}/comments/{doomed}/reports", json={"reasonCategory": "spam"})

    await _login_as(db_client, leaving)
    assert (await db_client.delete("/me")).status_code == 204

    remaining = (await db_session.scalars(sa.select(NovelComment.body))).all()
    assert remaining == ["남을 사람 댓글"]
    comment_report = (await db_session.scalars(sa.select(NovelCommentReport))).one()
    assert (comment_report.comment_id, comment_report.comment_author_user_id, comment_report.evidence_body) == (
        None,
        leaving,
        "떠날 사람 댓글",
    )
