"""신고 사유 "아동·청소년 관련"(`minor_safety`)이 세 신고 체계(작품·댓글·채팅 응답)에서 접수되고 어드민이 읽을 수
있는지, 그리고 그 사유를 되돌리는 마이그레이션 downgrade 가 신고 기록을 지우지 않고 `OTHER` 로 옮기는지 본다.

작품·댓글 사유는 Postgres enum 이라 모델에 멤버만 더하고 `ALTER TYPE ... ADD VALUE` 를 빠뜨리면 접수가 500 이 된다.
채팅 응답 사유는 Text 라 DB 는 무엇이든 받지만 요청 스키마의 Literal 이 빠지면 422 가 된다."""

import importlib.util
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from types import ModuleType

import httpx
import pytest_asyncio
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.db.models import (
    ChatMessage,
    ChatMessageReport,
    ChatMessageRole,
    ChatRoom,
    Report,
    ReportReasonCategory,
    ReportStatus,
)
from api.db.models.comments import Comment, CommentReport
from factories import _create_admin, _get_genre, _login_as, _login_as_admin, _make_published_character, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _comment_on_published_work(db_session: AsyncSession) -> tuple[Comment, uuid.UUID, uuid.UUID]:
    """(댓글, 작품 작가 id, 댓글 작성자 id)."""
    creator, author = _make_user(), _make_user()
    db_session.add_all([creator, author])
    await db_session.flush()
    content = await _make_published_character(
        db_session, creator_user_id=creator.id, genre_id=(await _get_genre(db_session)).id
    )
    comment = Comment(
        content_id=content.id,
        author_user_id=author.id,
        body="댓글",
        request_id=uuid.uuid4(),
        request_fingerprint="fixture",
    )
    db_session.add(comment)
    await db_session.flush()
    return comment, creator.id, author.id


async def test_work_and_comment_reports_accept_minor_safety_and_admin_reads_it_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    comment, _, _ = await _comment_on_published_work(db_session)
    reporter = _make_user()
    db_session.add(reporter)
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as(db_client, reporter.id)

    work = await db_client.post(f"/contents/{comment.content_id}/report", json={"reasonCategory": "minor_safety"})
    on_comment = await db_client.post(f"/comments/{comment.id}/reports", json={"reasonCategory": "minor_safety"})

    assert work.status_code == 204
    assert on_comment.status_code == 200
    report = await db_session.scalar(sa.select(Report).where(Report.content_id == comment.content_id))
    assert report is not None and report.reason_category is ReportReasonCategory.MINOR_SAFETY
    assert report.status is ReportStatus.PENDING

    await _login_as_admin(db_client, admin)
    work_detail = (await db_client.get(f"/admin/reports/{report.id}")).json()
    comment_list = (await db_client.get("/admin/comment-reports")).json()
    assert work_detail["reasonCategory"] == "minor_safety"
    (item,) = [item for item in comment_list["items"] if item["id"] == on_comment.json()["reportId"]]
    assert item["reasonCategory"] == "minor_safety"


async def test_chat_response_report_accepts_minor_safety_and_admin_reads_it_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=(await _get_genre(db_session)).id
    )
    room = ChatRoom(user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id)
    db_session.add(room)
    await db_session.flush()
    opening = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content="오프닝")
    db_session.add(opening)
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post(f"/chat-rooms/{room.id}/messages/{opening.id}/report", json={"reason": "minor_safety"})

    assert resp.status_code == 200
    stored = await db_session.get(ChatMessageReport, uuid.UUID(resp.json()["reportId"]))
    assert stored is not None and stored.reason == "minor_safety"
    await _login_as_admin(db_client, admin)
    detail = (await db_client.get(f"/admin/chat-message-reports/{stored.id}")).json()
    assert detail["reason"] == "minor_safety"


@pytest_asyncio.fixture
async def ddl_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """타입을 다시 만드는 DDL 을 공용 풀 밖에서 돌린다 — 공용 풀 커넥션에 남은 준비된 문장 캐시가 롤백으로 사라진
    타입 OID 를 가리키지 않게 하려고 풀 없는 엔진을 따로 만든다. 잠금을 기다리다 멈추지 않게 `lock_timeout` 을 건다."""
    engine = create_async_engine(
        db_engine.url.render_as_string(hide_password=False),
        poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "5s"}},
    )
    yield engine
    await engine.dispose()


async def test_downgrade_moves_minor_safety_reports_to_other_instead_of_failing(ddl_engine: AsyncEngine) -> None:
    """Postgres 에 `DROP VALUE` 가 없어 downgrade 는 타입을 다시 만든다. 새 사유 행을 옮기지 않으면 캐스트가 실패해
    롤백이 막히고, 지우면 신고 기록이 사라진다. 두 테이블 모두에서 그 행만 `OTHER` 로 바뀌어야 한다.
    마이그레이션 함수를 롤백되는 트랜잭션 안에서 직접 실행한다(세션 스코프 스키마는 건드리지 않는다)."""
    downgrade = _load("80f5dda86e33").downgrade
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection)
            comment, _, reporter_id = await _comment_on_published_work(session)
            minor_work = Report(
                reporter_user_id=reporter_id,
                content_id=comment.content_id,
                reason_category=ReportReasonCategory.MINOR_SAFETY,
                status=ReportStatus.PENDING,
            )
            hate_work = Report(
                reporter_user_id=reporter_id,
                content_id=comment.content_id,
                reason_category=ReportReasonCategory.HATE,
                status=ReportStatus.PENDING,
            )
            minor_comment = CommentReport(
                reporter_user_id=reporter_id,
                comment_id=comment.id,
                reason_category=ReportReasonCategory.MINOR_SAFETY,
                status=ReportStatus.PENDING,
            )
            session.add_all([minor_work, hate_work, minor_comment])
            await session.flush()

            def run_downgrade(sync_connection: Connection) -> None:
                with Operations.context(MigrationContext.configure(sync_connection)):
                    downgrade()

            await connection.run_sync(run_downgrade)

            rows = await connection.execute(
                sa.text(
                    "SELECT id, reason_category::text FROM reports WHERE id IN (:a, :b) "
                    "UNION ALL SELECT id, reason_category::text FROM comment_reports WHERE id = :c"
                ),
                {"a": minor_work.id, "b": hate_work.id, "c": minor_comment.id},
            )
            reasons = {row[0]: row[1] for row in rows}
            labels = (
                await connection.scalars(
                    sa.text(
                        "SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_type.oid = enumtypid "
                        "WHERE typname = 'report_reason_category' ORDER BY enumsortorder"
                    )
                )
            ).all()
        finally:
            await transaction.rollback()

    assert reasons == {minor_work.id: "OTHER", hate_work.id: "HATE", minor_comment.id: "OTHER"}
    assert labels == ["ADULT", "COPYRIGHT", "HATE", "SPAM", "OTHER"]
