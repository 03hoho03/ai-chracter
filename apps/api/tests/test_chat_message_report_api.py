"""AI 응답 신고: 접수 시 대화 사본을 증거로 남기고, 대상 메시지·방이 지워져도 신고와 사본은
남으며, 신고자가 탈퇴하면 사본만 비운다. 어드민은 만료·파기된 사본을 볼 수 없다."""

import asyncio
import subprocess
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.chat.room_deletion import delete_chat_rooms
from api.db.models import (
    AdminActionLog,
    Asset,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageReport,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentVersion,
    ReportStatus,
    User,
)
from api.main import app
from factories import (
    _clear_llm_override,
    _create_admin,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _login_as_admin,
    _make_published_character,
    _make_user,
    _override_llm_client,
)
from ops import purge_chat_report_evidence

_BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


async def _room_with_turns(db_session: AsyncSession, user: User | None = None) -> tuple[ChatRoom, list[ChatMessage]]:
    """[오프닝(AI), U1, A1, U2, A2] 방. 테스트 하네스는 한 트랜잭션이라 `now()` 가 전부 같으므로
    대화 순서를 created_at 으로 명시한다."""
    if user is None:
        user = _make_user()
        db_session.add(user)
        await db_session.flush()
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=(await _get_genre(db_session)).id
    )
    room = ChatRoom(user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id)
    db_session.add(room)
    await db_session.flush()
    turns = [
        (ChatMessageRole.ASSISTANT, "오프닝"),
        (ChatMessageRole.USER, "첫 질문"),
        (ChatMessageRole.ASSISTANT, "첫 응답"),
        (ChatMessageRole.USER, "둘째 질문"),
        (ChatMessageRole.ASSISTANT, "둘째 응답"),
    ]
    messages = [
        ChatMessage(chat_room_id=room.id, role=role, content=text, created_at=_BASE + timedelta(seconds=index))
        for index, (role, text) in enumerate(turns)
    ]
    db_session.add_all(messages)
    await db_session.commit()
    return room, messages


def _url(room_id: uuid.UUID, message_id: uuid.UUID) -> str:
    return f"/chat-rooms/{room_id}/messages/{message_id}/report"


async def _report_row(db_session: AsyncSession, report_id: str) -> ChatMessageReport:
    # SET NULL·UPDATE 는 DB 에서 일어나 세션의 캐시된 객체에 안 보인다.
    report = await db_session.scalar(
        sa.select(ChatMessageReport)
        .where(ChatMessageReport.id == uuid.UUID(report_id))
        .execution_options(populate_existing=True)
    )
    assert report is not None
    return report


# ---------------------------------------------------------------------------
# 접수
# ---------------------------------------------------------------------------


async def test_report_snapshots_response_and_the_user_message_right_before_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)

    resp = await db_client.post(_url(room.id, messages[4].id), json={"reason": "out_of_character", "note": " 설정과 달라요 "})

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    report = await _report_row(db_session, resp.json()["reportId"])
    assert report.reporter_user_id == room.user_id
    assert report.chat_room_id == room.id
    assert report.chat_message_id == messages[4].id
    assert report.reason == "out_of_character"
    assert report.note == "설정과 달라요"
    assert report.evidence_response == "둘째 응답"
    # 더 오래된 "첫 질문"이 아니라 바로 앞 사용자 메시지다.
    assert report.evidence_user_message == "둘째 질문"
    assert report.evidence_expires_at == report.created_at + timedelta(days=90)
    assert report.evidence_purged_at is None


async def test_opening_message_report_has_no_user_message_evidence(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)

    resp = await db_client.post(_url(room.id, messages[0].id), json={"reason": "broken"})

    assert resp.status_code == 200
    report = await _report_row(db_session, resp.json()["reportId"])
    assert report.evidence_response == "오프닝"
    assert report.evidence_user_message is None
    assert report.note is None


async def test_blank_note_is_stored_as_null(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)

    resp = await db_client.post(_url(room.id, messages[2].id), json={"reason": "other", "note": "   "})

    assert resp.status_code == 200
    assert (await _report_row(db_session, resp.json()["reportId"])).note is None


async def test_note_over_200_characters_is_rejected(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)

    too_long = await db_client.post(_url(room.id, messages[2].id), json={"reason": "other", "note": "가" * 201})
    at_limit = await db_client.post(_url(room.id, messages[2].id), json={"reason": "other", "note": "가" * 200})

    assert too_long.status_code == 422
    assert at_limit.status_code == 200


async def test_unknown_reason_is_rejected(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)

    resp = await db_client.post(_url(room.id, messages[2].id), json={"reason": "spam"})

    assert resp.status_code == 422


async def test_cannot_report_in_someone_elses_room(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, messages = await _room_with_turns(db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.post(_url(room.id, messages[2].id), json={"reason": "other"})

    assert resp.status_code == 403
    assert (await db_session.scalar(sa.select(sa.func.count()).select_from(ChatMessageReport))) == 0


async def test_unknown_room_is_404(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)

    resp = await db_client.post(_url(uuid.uuid4(), messages[2].id), json={"reason": "other"})

    assert resp.status_code == 404


async def test_message_from_another_room_is_404(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, _ = await _room_with_turns(db_session)
    owner = await db_session.get(User, room.user_id)
    assert owner is not None
    _, other_room_messages = await _room_with_turns(db_session, owner)
    await _login_as(db_client, room.user_id)

    resp = await db_client.post(_url(room.id, other_room_messages[2].id), json={"reason": "other"})

    assert resp.status_code == 404


async def test_user_message_cannot_be_reported(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)

    resp = await db_client.post(_url(room.id, messages[1].id), json={"reason": "other"})

    assert resp.status_code == 400
    assert (await db_session.scalar(sa.select(sa.func.count()).select_from(ChatMessageReport))) == 0


async def test_duplicate_report_returns_the_first_row_unchanged(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)
    first = await db_client.post(_url(room.id, messages[2].id), json={"reason": "repetitive", "note": "처음"})
    report = await _report_row(db_session, first.json()["reportId"])
    original_expiry = report.evidence_expires_at
    messages[2].content = "신고 뒤 바뀐 본문"
    await db_session.commit()

    duplicate = await db_client.post(_url(room.id, messages[2].id), json={"reason": "hateful", "note": "다시"})

    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()
    report = await _report_row(db_session, first.json()["reportId"])
    assert (report.reason, report.note, report.evidence_response) == ("repetitive", "처음", "첫 응답")
    assert report.evidence_expires_at == original_expiry
    assert (await db_session.scalar(sa.select(sa.func.count()).select_from(ChatMessageReport))) == 1


async def test_reporting_is_rate_limited_before_ownership_is_checked(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)
    # 없는 방을 두드려도 한도가 오른다 — 레이트리밋이 소유 확인보다 먼저다.
    for _ in range(10):
        assert (await db_client.post(_url(uuid.uuid4(), messages[2].id), json={"reason": "other"})).status_code == 404

    limited = await db_client.post(_url(room.id, messages[2].id), json={"reason": "other"})

    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "CHAT_REPORT_RATE_LIMITED"
    assert limited.json()["detail"]["retryAfterSeconds"] > 0
    assert limited.json()["detail"]["windowSeconds"] == 60
    assert int(limited.headers["Retry-After"]) > 0
    assert (await db_session.scalar(sa.select(sa.func.count()).select_from(ChatMessageReport))) == 0


async def test_report_and_snapshot_survive_regeneration_of_the_reported_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)
    resp = await db_client.post(_url(room.id, messages[4].id), json={"reason": "inappropriate"})
    assert resp.status_code == 200

    _override_llm_client(_FakeLLMClient(tokens=["새", "응답"]))
    try:
        regenerated = await db_client.post(f"/chat-rooms/{room.id}/regenerate")
    finally:
        _clear_llm_override()

    assert regenerated.status_code == 200
    assert await db_session.get(ChatMessage, messages[4].id, populate_existing=True) is None
    report = await _report_row(db_session, resp.json()["reportId"])
    assert report.chat_message_id is None
    assert report.chat_room_id == room.id
    assert report.evidence_response == "둘째 응답"
    assert report.evidence_user_message == "둘째 질문"


async def test_report_and_snapshot_survive_room_deletion(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room, messages = await _room_with_turns(db_session)
    await _login_as(db_client, room.user_id)
    resp = await db_client.post(_url(room.id, messages[2].id), json={"reason": "hateful"})

    assert (await db_client.delete(f"/chat-rooms/{room.id}")).status_code == 204

    report = await _report_row(db_session, resp.json()["reportId"])
    assert (report.chat_room_id, report.chat_message_id) == (None, None)
    assert (report.evidence_response, report.evidence_user_message) == ("첫 응답", "첫 질문")
    assert report.evidence_purged_at is None


async def test_withdrawal_clears_own_report_evidence_but_keeps_metadata(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    other_room, other_messages = await _room_with_turns(db_session)
    await _login_as(db_client, other_room.user_id)
    others = await db_client.post(_url(other_room.id, other_messages[2].id), json={"reason": "broken"})
    db_client.cookies.clear()
    await _login_as(db_client, room.user_id)
    mine = await db_client.post(_url(room.id, messages[2].id), json={"reason": "hateful", "note": "메모"})

    assert (await db_client.delete("/me")).status_code == 204

    report = await _report_row(db_session, mine.json()["reportId"])
    assert (report.evidence_response, report.evidence_user_message) == (None, None)
    assert report.evidence_purged_at is not None
    assert (report.reason, report.note, report.status) == ("hateful", "메모", ReportStatus.PENDING)
    assert report.reporter_user_id == room.user_id
    other_report = await _report_row(db_session, others.json()["reportId"])
    assert other_report.evidence_response == "첫 응답"
    assert other_report.evidence_purged_at is None


# ---------------------------------------------------------------------------
# 메시지 삭제와의 경합 — 커밋되는 독립 커넥션
#
# 락 경합은 `db_session`(롤백되는 한 커넥션) 안에서는 드러나지 않는다. 여기서 쓴 행은 커밋되므로
# 픽스처가 표지 도메인으로 골라 지운다.
# ---------------------------------------------------------------------------

_MARKER_DOMAIN = "chat-report-race.test"


@pytest_asyncio.fixture
async def committed_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """락을 기다리다 영영 멈추지 않게 `lock_timeout`을 건 풀 없는 별도 엔진."""
    committed = create_async_engine(
        db_engine.url.render_as_string(hide_password=False),
        poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "5s"}},
    )
    yield committed
    async with async_sessionmaker(committed, expire_on_commit=False)() as cleanup:
        user_ids = (await cleanup.scalars(sa.select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            await cleanup.execute(sa.delete(ChatMessageReport).where(ChatMessageReport.reporter_user_id.in_(user_ids)))
            room_ids = (await cleanup.scalars(sa.select(ChatRoom.id).where(ChatRoom.user_id.in_(user_ids)))).all()
            await delete_chat_rooms(cleanup, room_ids)
            content_ids = (
                await cleanup.scalars(sa.select(Content.id).where(Content.creator_user_id.in_(user_ids)))
            ).all()
            version_ids = (
                await cleanup.scalars(sa.select(ContentVersion.id).where(ContentVersion.content_id.in_(content_ids)))
            ).all()
            await cleanup.execute(
                sa.delete(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id.in_(version_ids))
            )
            await cleanup.execute(
                sa.update(Content).where(Content.id.in_(content_ids)).values(current_published_version_id=None)
            )
            await cleanup.execute(sa.delete(ContentVersion).where(ContentVersion.id.in_(version_ids)))
            await cleanup.execute(sa.delete(Content).where(Content.id.in_(content_ids)))
            await cleanup.execute(sa.delete(Asset).where(Asset.owner_user_id.in_(user_ids)))
            await cleanup.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()
    await committed.dispose()


async def _wait_until_a_lock_is_awaited(engine: AsyncEngine) -> None:
    """어떤 트랜잭션이 행 락을 기다리기 시작할 때까지 기다린다(시간이 아니라 상태로 순서를 강제).
    행 락 대기는 `pg_locks`의 데이터베이스 열이 비어 있어 `pg_stat_activity`의 대기 종류로 본다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with asyncio.timeout(5):
        while True:
            async with factory() as probe:
                waiting = await probe.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                    )
                )
            if waiting:
                return
            await asyncio.sleep(0.01)


async def test_report_racing_a_deletion_of_the_message_is_404_not_500(committed_engine: AsyncEngine) -> None:
    """재생성·수정·삭제가 신고 대상 메시지를 지우는 트랜잭션이 커밋되기 직전에 신고가 들어온다.
    신고는 그 삭제가 끝나기를 기다렸다가 메시지가 없어진 것을 보고 없는 메시지와 같은 404를 낸다
    — 지워진 메시지를 가리키는 신고를 넣으려다 FK 위반 500이 나면 안 된다."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    async with factory() as seed:
        owner = _make_user(email=f"owner-{uuid.uuid4()}@{_MARKER_DOMAIN}")
        seed.add(owner)
        await seed.flush()
        room, messages = await _room_with_turns(seed, owner)
    target = messages[4]

    deleting = factory()
    request: asyncio.Task[httpx.Response] | None = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver"
    ) as client:
        await _login_as(client, room.user_id)
        try:
            await deleting.execute(sa.delete(ChatMessage).where(ChatMessage.id == target.id))
            request = asyncio.create_task(client.post(_url(room.id, target.id), json={"reason": "inappropriate"}))
            await _wait_until_a_lock_is_awaited(committed_engine)
            await deleting.commit()
            resp = await asyncio.wait_for(request, 10)
        finally:
            await deleting.close()
            if request is not None and not request.done():
                await asyncio.wait_for(request, 10)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Message not found"}


# ---------------------------------------------------------------------------
# 파기
# ---------------------------------------------------------------------------


def _report(room: ChatRoom, message: ChatMessage, **overrides: object) -> ChatMessageReport:
    values: dict[str, object] = {
        "reporter_user_id": room.user_id,
        "chat_room_id": room.id,
        "chat_message_id": message.id,
        "reason": "other",
        "note": "메모",
        "status": ReportStatus.PENDING,
        "evidence_response": "응답 사본",
        "evidence_user_message": "질문 사본",
        "evidence_expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    values.update(overrides)
    return ChatMessageReport(**values)


async def test_purge_clears_only_expired_evidence_columns(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """크론이 컨테이너 psql 로 보낼 SQL 을 그대로 테스트 DB 에 실행해 본다."""
    room, messages = await _room_with_turns(db_session)
    now = datetime.now(UTC)
    earlier = now - timedelta(days=3)
    expired = _report(room, messages[0], evidence_expires_at=now - timedelta(seconds=1))
    fresh = _report(room, messages[2])
    already = _report(
        room, messages[4], evidence_expires_at=now - timedelta(days=5), evidence_response="남은 값", evidence_purged_at=earlier
    )
    db_session.add_all([expired, fresh, already])
    await db_session.commit()

    captured_sql: list[str] = []

    def run(script: str, *, url: str, stdin: object = None, stdout: object = None) -> subprocess.CompletedProcess[bytes]:
        captured_sql.append(script.split(" -c ", 1)[1][1:-1].replace("'\\''", "'"))
        return subprocess.CompletedProcess([], 0, stdout=b"row\n", stderr=b"")

    monkeypatch.setattr(purge_chat_report_evidence, "scalar", lambda sql, *, url: "chat_message_reports")
    monkeypatch.setattr(purge_chat_report_evidence, "run_sh", run)
    assert purge_chat_report_evidence.purge_expired_chat_report_evidence("postgresql://unused", now=now) == 1
    returned = (await db_session.execute(sa.text(captured_sql[0]))).all()
    await db_session.commit()

    assert [row[0] for row in returned] == [expired.id]
    for row in (expired, fresh, already):
        await db_session.refresh(row)
    assert (expired.evidence_response, expired.evidence_user_message) == (None, None)
    assert expired.evidence_purged_at == now
    assert (expired.reason, expired.note, expired.chat_message_id) == ("other", "메모", messages[0].id)
    assert (fresh.evidence_response, fresh.evidence_user_message, fresh.evidence_purged_at) == (
        "응답 사본",
        "질문 사본",
        None,
    )
    assert (already.evidence_response, already.evidence_purged_at) == ("남은 값", earlier)


# ---------------------------------------------------------------------------
# 어드민
# ---------------------------------------------------------------------------


async def test_admin_lists_reports_with_status_filter_and_paging(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    # 한 회원이 한 메시지에 한 번만 신고할 수 있어, 대상이 지워진(NULL) 신고로 개수를 채운다.
    pending = [
        _report(room, messages[0], chat_message_id=None, created_at=_BASE + timedelta(minutes=i)) for i in range(21)
    ]
    resolved = _report(room, messages[2], status=ReportStatus.RESOLVED, created_at=_BASE - timedelta(days=1))
    db_session.add_all([*pending, resolved])
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)

    first = (await db_client.get("/admin/chat-message-reports")).json()
    second = (await db_client.get("/admin/chat-message-reports", params={"page": 2})).json()
    only_resolved = (await db_client.get("/admin/chat-message-reports", params={"status": "resolved"})).json()

    assert (first["totalCount"], first["totalPages"], len(first["items"])) == (22, 2, 20)
    assert first["items"][0]["id"] == str(pending[-1].id)  # 최신순
    assert [item["id"] for item in second["items"]] == [str(pending[0].id), str(resolved.id)]
    assert [item["id"] for item in only_resolved["items"]] == [str(resolved.id)]
    assert only_resolved["items"][0]["evidenceAvailable"] is True
    assert only_resolved["items"][0]["chatRoomId"] == str(room.id)


async def test_admin_detail_shows_evidence_and_hides_it_once_expired_or_purged(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    live = _report(room, messages[0], evidence_user_message=None)
    expired = _report(room, messages[2], evidence_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    purged = _report(room, messages[4], evidence_purged_at=datetime.now(UTC))
    db_session.add_all([live, expired, purged])
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)

    live_body = (await db_client.get(f"/admin/chat-message-reports/{live.id}")).json()
    assert live_body["reason"] == "other" and live_body["note"] == "메모"
    assert live_body["evidence"]["available"] is True
    assert live_body["evidence"]["response"] == "응답 사본"
    assert live_body["evidence"]["userMessage"] is None  # 오프닝 신고 — 표시 문구는 FE 몫
    for hidden in (expired, purged):
        evidence = (await db_client.get(f"/admin/chat-message-reports/{hidden.id}")).json()["evidence"]
        assert (evidence["available"], evidence["response"], evidence["userMessage"]) == (False, None, None)
    # 숨기기만 하고 지우지 않는다 — 비우는 건 파기 작업의 몫이다.
    await db_session.refresh(expired)
    assert expired.evidence_response == "응답 사본"


@pytest.mark.parametrize(("action", "expected_status", "log_type"), [
    ("resolve", ReportStatus.RESOLVED, "chat-report-resolve"),
    ("reject", ReportStatus.REJECTED, "chat-report-reject"),
])
async def test_admin_action_sets_status_and_writes_audit_log(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    action: str,
    expected_status: ReportStatus,
    log_type: str,
) -> None:
    room, messages = await _room_with_turns(db_session)
    report = _report(room, messages[2], reason="hateful")
    db_session.add(report)
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)

    resp = await db_client.post(
        f"/admin/chat-message-reports/{report.id}/actions", json={"action": action, "adminComment": " 확인함 "}
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == expected_status.value
    await db_session.refresh(report)
    assert report.status == expected_status
    assert report.resolved_by_admin_id == admin["id"]
    assert report.resolved_at is not None
    logs = (await db_session.scalars(sa.select(AdminActionLog))).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.action_type == log_type
    assert log.admin_id == admin["id"]
    assert log.target_chat_room_id == room.id
    assert log.target_user_id == room.user_id
    assert (log.reason_category, log.reason_text) == ("hateful", "확인함")


async def test_admin_can_reprocess_and_each_action_is_logged(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    report = _report(room, messages[2])
    db_session.add(report)
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)
    url = f"/admin/chat-message-reports/{report.id}/actions"

    assert (await db_client.post(url, json={"action": "reject", "adminComment": "기각"})).status_code == 200
    again = await db_client.post(url, json={"action": "resolve", "adminComment": "다시 보니 맞음"})

    assert again.json()["status"] == "resolved"
    types = (await db_session.scalars(sa.select(AdminActionLog.action_type).order_by(AdminActionLog.created_at))).all()
    assert sorted(types) == ["chat-report-reject", "chat-report-resolve"]


async def test_admin_action_requires_comment_and_existing_report(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    report = _report(room, messages[2])
    db_session.add(report)
    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)

    blank = await db_client.post(
        f"/admin/chat-message-reports/{report.id}/actions", json={"action": "resolve", "adminComment": "  "}
    )
    hide = await db_client.post(
        f"/admin/chat-message-reports/{report.id}/actions", json={"action": "hide", "adminComment": "숨김"}
    )
    missing = await db_client.post(
        f"/admin/chat-message-reports/{uuid.uuid4()}/actions", json={"action": "resolve", "adminComment": "확인"}
    )

    assert (blank.status_code, hide.status_code, missing.status_code) == (422, 422, 404)
    assert (await db_client.get(f"/admin/chat-message-reports/{uuid.uuid4()}")).status_code == 404
    await db_session.refresh(report)
    assert report.status == ReportStatus.PENDING
    assert (await db_session.scalar(sa.select(sa.func.count()).select_from(AdminActionLog))) == 0


async def test_admin_endpoints_reject_a_regular_user_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room, messages = await _room_with_turns(db_session)
    report = _report(room, messages[2])
    db_session.add(report)
    await db_session.commit()
    await _login_as(db_client, room.user_id)

    assert (await db_client.get("/admin/chat-message-reports")).status_code == 401
    assert (await db_client.get(f"/admin/chat-message-reports/{report.id}")).status_code == 401
    acted = await db_client.post(
        f"/admin/chat-message-reports/{report.id}/actions", json={"action": "resolve", "adminComment": "확인"}
    )
    assert acted.status_code == 401
